import json
import logging
import random
import time
import uuid
from datetime import datetime, timezone

import requests
from celery import shared_task
from django.conf import settings

from checkin.security import SIGNATURE_HEADER, sign_payload

logger = logging.getLogger(__name__)


def _simulate_printing():
    delay = random.uniform(
        settings.PRINTER_SIMULATED_MIN_DELAY_SECONDS,
        settings.PRINTER_SIMULATED_MAX_DELAY_SECONDS,
    )
    time.sleep(delay)
    failed = random.random() < settings.PRINTER_SIMULATED_FAILURE_RATE
    return not failed


def build_completion_webhook_payload(*, job_id, attendee_id, success: bool, failure_reason: str | None = None) -> dict:
    payload = {
        "event": "badge.print.completed",
        "event_id": str(uuid.uuid4()),
        "job_id": str(job_id),
        "attendee_id": str(attendee_id),
        "status": "success" if success else "failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if not success and failure_reason:
        payload["failure_reason"] = failure_reason
    return payload


def send_completion_webhook(payload: dict, base_url: str | None = None) -> requests.Response:
    base_url = base_url or settings.DJANGO_INTERNAL_BASE_URL
    url = f"{base_url.rstrip('/')}/api/webhooks/printer/"
    raw_body = json.dumps(payload).encode("utf-8")
    signature = sign_payload(raw_body)
    return requests.post(
        url,
        data=raw_body,
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: signature},
        timeout=10,
    )


@shared_task(name="checkin.handle_print_requested", bind=True, max_retries=3)
def handle_print_requested(self, message: dict):
    job_id = message["job_id"]
    attendee_id = message["attendee_id"]
    logger.info("printer worker received print request for job_id=%s", job_id)

    try:
        success = _simulate_printing()
    except Exception as exc:
        logger.exception("printer simulation crashed for job_id=%s", job_id)
        success = False
        failure_reason = f"Printer worker exception: {exc}"
    else:
        failure_reason = None if success else "Simulated printer jam / out of badge stock."

    payload = build_completion_webhook_payload(
        job_id=job_id, attendee_id=attendee_id, success=success, failure_reason=failure_reason
    )

    try:
        response = send_completion_webhook(payload)
        response.raise_for_status()
        logger.info(
            "completion webhook delivered for job_id=%s status=%s (%s)",
            job_id, payload["status"], response.status_code,
        )
    except requests.RequestException as exc:
        logger.warning("failed to deliver completion webhook for job_id=%s: %s", job_id, exc)
        raise self.retry(exc=exc, countdown=2**self.request.retries)
