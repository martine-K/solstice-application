import json
import uuid

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from checkin.models import Attendee, PrintJob, WebhookEvent
from checkin.security import sign_payload

WEBHOOK_URL = "/api/webhooks/printer/"
TEST_SECRET = "test-secret"


def signed_post(client, payload, secret=TEST_SECRET):
    raw_body = json.dumps(payload).encode("utf-8")
    signature = sign_payload(raw_body, secret=secret)
    return client.post(
        WEBHOOK_URL, data=raw_body, content_type="application/json", HTTP_X_SIGNATURE=signature
    )


@override_settings(PRINTER_WEBHOOK_SECRET=TEST_SECRET)
class WebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.attendee = Attendee.objects.create(
            name="Grace Hopper", qr_code="QR-GRACE-002", status=Attendee.Status.PENDING
        )
        self.job = PrintJob.objects.create(attendee=self.attendee, status=PrintJob.Status.QUEUED)

    def _success_payload(self, event_id=None):
        return {
            "event": "badge.print.completed",
            "event_id": str(event_id or uuid.uuid4()),
            "job_id": str(self.job.job_id),
            "attendee_id": str(self.attendee.id),
            "status": "success",
            "timestamp": "2025-01-01T00:00:00Z",
        }

    def test_successful_webhook_checks_in_attendee(self):
        response = signed_post(self.client, self._success_payload())
        self.assertEqual(response.status_code, 200)

        self.attendee.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.attendee.status, Attendee.Status.CHECKED_IN)
        self.assertEqual(self.job.status, PrintJob.Status.COMPLETED)
        self.assertIsNotNone(self.job.completed_at)

    def test_failed_printing_rolls_attendee_back_to_not_checked_in(self):
        payload = self._success_payload()
        payload["status"] = "failed"
        payload["failure_reason"] = "Out of badge stock."

        response = signed_post(self.client, payload)
        self.assertEqual(response.status_code, 200)

        self.attendee.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.attendee.status, Attendee.Status.NOT_CHECKED_IN)
        self.assertEqual(self.job.status, PrintJob.Status.FAILED)
        self.assertEqual(self.job.failure_reason, "Out of badge stock.")

    def test_duplicate_webhook_is_idempotent(self):
        payload = self._success_payload(event_id="11111111-1111-1111-1111-111111111111")

        first = signed_post(self.client, payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["status"], "checked_in")

        second = signed_post(self.client, payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], "duplicate_ignored")

        self.assertEqual(WebhookEvent.objects.filter(event_id=payload["event_id"]).count(), 1)
        self.attendee.refresh_from_db()
        self.assertEqual(self.attendee.status, Attendee.Status.CHECKED_IN)

    def test_invalid_signature_is_rejected(self):
        raw_body = json.dumps(self._success_payload()).encode("utf-8")
        response = self.client.post(
            WEBHOOK_URL, data=raw_body, content_type="application/json", HTTP_X_SIGNATURE="0" * 64
        )
        self.assertEqual(response.status_code, 401)
        self.attendee.refresh_from_db()
        self.assertEqual(self.attendee.status, Attendee.Status.PENDING)

    def test_missing_signature_is_rejected(self):
        raw_body = json.dumps(self._success_payload()).encode("utf-8")
        response = self.client.post(WEBHOOK_URL, data=raw_body, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_unknown_job_id_returns_404(self):
        payload = self._success_payload()
        payload["job_id"] = str(uuid.uuid4())
        response = signed_post(self.client, payload)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "unknown_job_id")

    def test_attendee_job_mismatch_returns_409(self):
        other_attendee = Attendee.objects.create(name="Alan Turing", qr_code="QR-ALAN-003")
        payload = self._success_payload()
        payload["attendee_id"] = str(other_attendee.id)
        response = signed_post(self.client, payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "attendee_job_mismatch")

    def test_out_of_order_webhooks_terminal_state_wins(self):
        failed_payload = self._success_payload(event_id="22222222-2222-2222-2222-222222222222")
        failed_payload["status"] = "failed"
        r1 = signed_post(self.client, failed_payload)
        self.assertEqual(r1.status_code, 200)

        late_success_payload = self._success_payload(event_id="33333333-3333-3333-3333-333333333333")
        r2 = signed_post(self.client, late_success_payload)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["status"], "no_op_terminal_job")

        self.job.refresh_from_db()
        self.attendee.refresh_from_db()
        self.assertEqual(self.job.status, PrintJob.Status.FAILED)
        self.assertEqual(self.attendee.status, Attendee.Status.NOT_CHECKED_IN)

    def test_invalid_payload_missing_fields(self):
        response = signed_post(self.client, {"event": "badge.print.completed"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "invalid_payload")
