from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from checkin.models import Attendee, PrintJob, WebhookEvent
from checkin.publisher import publish_print_requested

logger = logging.getLogger(__name__)


class ScanError(Exception):
    code = "scan_error"
    http_status = 400

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class AttendeeNotFound(ScanError):
    code = "attendee_not_found"
    http_status = 404


class AlreadyCheckedIn(ScanError):
    code = "already_checked_in"
    http_status = 409


class PrintAlreadyInProgress(ScanError):
    code = "print_already_in_progress"
    http_status = 409


@dataclass
class ScanResult:
    attendee: Attendee
    print_job: PrintJob


def scan_attendee(qr_code: str) -> ScanResult:
    with transaction.atomic():
        try:
            attendee = Attendee.objects.select_for_update().get(qr_code=qr_code)
        except Attendee.DoesNotExist as exc:
            raise AttendeeNotFound(f"No attendee found for QR code {qr_code!r}") from exc

        if attendee.status == Attendee.Status.CHECKED_IN:
            raise AlreadyCheckedIn(f"{attendee.name} is already checked in.")

        active_job = (
            PrintJob.objects.select_for_update()
            .filter(attendee=attendee, status__in=[PrintJob.Status.QUEUED, PrintJob.Status.PRINTING])
            .first()
        )
        if active_job is not None:
            raise PrintAlreadyInProgress(
                f"{attendee.name} already has an active print job "
                f"({active_job.job_id}, status={active_job.status})."
            )

        try:
            print_job = PrintJob.objects.create(
                attendee=attendee,
                job_id=uuid.uuid4(),
                event_id=uuid.uuid4(),
                status=PrintJob.Status.QUEUED,
            )
        except IntegrityError as exc:
            raise PrintAlreadyInProgress(f"{attendee.name} already has an active print job.") from exc

        attendee.status = Attendee.Status.PENDING
        attendee.save(update_fields=["status", "updated_at"])

        transaction.on_commit(
            lambda: publish_print_requested(
                event_id=print_job.event_id,
                job_id=print_job.job_id,
                attendee_id=attendee.id,
            )
        )

    return ScanResult(attendee=attendee, print_job=print_job)


class WebhookProcessingError(Exception):
    code = "webhook_error"
    http_status = 400

    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status


def process_print_completed_webhook(payload: dict) -> dict:
    event_id = payload.get("event_id")
    job_id = payload.get("job_id")
    attendee_id = payload.get("attendee_id")
    status = payload.get("status")
    event_type = payload.get("event")

    if not event_id or not job_id or not attendee_id or not status:
        raise WebhookProcessingError(
            "Payload missing required fields (event_id, job_id, attendee_id, status).",
            code="invalid_payload",
        )

    try:
        event_uuid = uuid.UUID(str(event_id))
        job_uuid = uuid.UUID(str(job_id))
    except (ValueError, AttributeError) as exc:
        raise WebhookProcessingError("event_id/job_id must be valid UUIDs.", code="invalid_payload") from exc

    with transaction.atomic():
        webhook_event, created = WebhookEvent.objects.select_for_update().get_or_create(
            event_id=event_uuid,
            defaults={
                "event_type": event_type or "badge.print.completed",
                "payload": payload,
                "processed": False,
            },
        )

        if not created and webhook_event.processed:
            logger.info("duplicate webhook event_id=%s ignored", event_id)
            return {"status": "duplicate_ignored", "event_id": str(event_id)}

        try:
            print_job = PrintJob.objects.select_for_update().get(job_id=job_uuid)
        except PrintJob.DoesNotExist as exc:
            raise WebhookProcessingError(
                f"Unknown job_id {job_id!r}.", code="unknown_job_id", http_status=404
            ) from exc

        if str(print_job.attendee_id) != str(attendee_id):
            raise WebhookProcessingError(
                "attendee_id does not match the attendee on record for this job_id.",
                code="attendee_job_mismatch",
                http_status=409,
            )

        if print_job.status in (PrintJob.Status.COMPLETED, PrintJob.Status.FAILED):
            webhook_event.processed = True
            webhook_event.save(update_fields=["processed"])
            logger.info(
                "webhook for already-terminal job_id=%s (status=%s) recorded, no state change",
                job_id,
                print_job.status,
            )
            return {"status": "no_op_terminal_job", "job_status": print_job.status}

        if status == "success":
            print_job.status = PrintJob.Status.COMPLETED
            print_job.completed_at = timezone.now()
            print_job.failure_reason = None
            print_job.save(update_fields=["status", "completed_at", "failure_reason"])

            attendee = Attendee.objects.select_for_update().get(id=print_job.attendee_id)
            if attendee.status != Attendee.Status.CHECKED_IN:
                attendee.status = Attendee.Status.CHECKED_IN
                attendee.save(update_fields=["status", "updated_at"])
            result_status = "checked_in"
        else:
            print_job.status = PrintJob.Status.FAILED
            print_job.completed_at = timezone.now()
            print_job.failure_reason = payload.get("failure_reason", "Printer reported failure.")
            print_job.save(update_fields=["status", "completed_at", "failure_reason"])

            attendee = Attendee.objects.select_for_update().get(id=print_job.attendee_id)
            if attendee.status == Attendee.Status.PENDING:
                attendee.status = Attendee.Status.NOT_CHECKED_IN
                attendee.save(update_fields=["status", "updated_at"])
            result_status = "print_failed"

        webhook_event.payload = payload
        webhook_event.processed = True
        webhook_event.save(update_fields=["payload", "processed"])

    return {"status": result_status, "job_id": str(job_id), "event_id": str(event_id)}
