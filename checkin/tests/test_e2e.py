from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from checkin import tasks
from checkin.models import Attendee, PrintJob

TEST_SECRET = "e2e-test-secret"


@override_settings(
    PRINTER_WEBHOOK_SECRET=TEST_SECRET,
    PRINTER_SIMULATED_MIN_DELAY_SECONDS=0,
    PRINTER_SIMULATED_MAX_DELAY_SECONDS=0,
)
class ThreeAttendeeEndToEndTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ada = Attendee.objects.create(name="Ada Lovelace", qr_code="QR-ADA-001")
        self.grace = Attendee.objects.create(name="Grace Hopper", qr_code="QR-GRACE-002")
        self.alan = Attendee.objects.create(name="Alan Turing", qr_code="QR-ALAN-003")

        def fake_post(url, data, headers, timeout):
            response = self.client.post(
                "/api/webhooks/printer/",
                data=data,
                content_type="application/json",
                HTTP_X_SIGNATURE=headers["X-Signature"],
            )
            mock_resp = MagicMock()
            mock_resp.status_code = response.status_code
            mock_resp.raise_for_status = MagicMock(
                side_effect=None if response.status_code < 400 else Exception("http error")
            )
            return mock_resp

        patcher = patch("checkin.tasks.requests.post", side_effect=fake_post)
        self.mock_post = patcher.start()
        self.addCleanup(patcher.stop)

        def fake_publish(*, event_id, job_id, attendee_id):
            tasks.handle_print_requested.run(
                {
                    "event": "badge.print.requested",
                    "event_id": str(event_id),
                    "job_id": str(job_id),
                    "attendee_id": str(attendee_id),
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            )

        publish_patcher = patch("checkin.services.publish_print_requested", side_effect=fake_publish)
        self.mock_publish = publish_patcher.start()
        self.addCleanup(publish_patcher.stop)

    def _scan(self, qr_code):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/checkin/scan/", {"qr_code": qr_code}, format="json")
        return response

    @override_settings(PRINTER_SIMULATED_FAILURE_RATE=0.0)
    def test_three_attendees_all_check_in_successfully(self):
        for attendee, qr in [
            (self.ada, "QR-ADA-001"),
            (self.grace, "QR-GRACE-002"),
            (self.alan, "QR-ALAN-003"),
        ]:
            response = self._scan(qr)
            self.assertEqual(response.status_code, 202, response.data)

            attendee.refresh_from_db()
            self.assertEqual(attendee.status, Attendee.Status.CHECKED_IN)

            job = PrintJob.objects.get(attendee=attendee)
            self.assertEqual(job.status, PrintJob.Status.COMPLETED)

        dup_response = self._scan("QR-ADA-001")
        self.assertEqual(dup_response.status_code, 409)
        self.assertEqual(dup_response.data["error"], "already_checked_in")
        self.assertEqual(PrintJob.objects.filter(attendee=self.ada).count(), 1)

    @override_settings(PRINTER_SIMULATED_FAILURE_RATE=1.0)
    def test_printer_failure_rolls_attendee_back_and_allows_rescan(self):
        response = self._scan("QR-GRACE-002")
        self.assertEqual(response.status_code, 202)

        self.grace.refresh_from_db()
        self.assertEqual(self.grace.status, Attendee.Status.NOT_CHECKED_IN)

        job = PrintJob.objects.get(attendee=self.grace)
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertIsNotNone(job.failure_reason)

        second_scan = self._scan("QR-GRACE-002")
        self.assertEqual(second_scan.status_code, 202)
        self.assertEqual(PrintJob.objects.filter(attendee=self.grace).count(), 2)
