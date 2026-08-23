import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from checkin import tasks
from checkin.security import verify_signature


@override_settings(PRINTER_SIMULATED_MIN_DELAY_SECONDS=0, PRINTER_SIMULATED_MAX_DELAY_SECONDS=0)
class PrinterWorkerTests(SimpleTestCase):
    @override_settings(PRINTER_SIMULATED_FAILURE_RATE=0.0)
    def test_simulate_printing_always_succeeds_when_failure_rate_zero(self):
        self.assertTrue(tasks._simulate_printing())

    @override_settings(PRINTER_SIMULATED_FAILURE_RATE=1.0)
    def test_simulate_printing_always_fails_when_failure_rate_one(self):
        self.assertFalse(tasks._simulate_printing())

    def test_build_completion_payload_success(self):
        job_id = uuid.uuid4()
        attendee_id = uuid.uuid4()
        payload = tasks.build_completion_webhook_payload(job_id=job_id, attendee_id=attendee_id, success=True)
        self.assertEqual(payload["event"], "badge.print.completed")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["job_id"], str(job_id))
        self.assertNotIn("failure_reason", payload)

    def test_build_completion_payload_failure_includes_reason(self):
        payload = tasks.build_completion_webhook_payload(
            job_id=uuid.uuid4(), attendee_id=uuid.uuid4(), success=False, failure_reason="Jam"
        )
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failure_reason"], "Jam")

    @patch("checkin.tasks.requests.post")
    def test_send_completion_webhook_signs_raw_body(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        payload = tasks.build_completion_webhook_payload(job_id=uuid.uuid4(), attendee_id=uuid.uuid4(), success=True)
        tasks.send_completion_webhook(payload, base_url="http://testserver")

        _, kwargs = mock_post.call_args
        sent_signature = kwargs["headers"]["X-Signature"]
        sent_body = kwargs["data"]
        self.assertTrue(verify_signature(sent_body, sent_signature))
