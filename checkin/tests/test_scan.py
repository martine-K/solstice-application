from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from checkin.models import Attendee, PrintJob


class ScanFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.attendee = Attendee.objects.create(name="Ada Lovelace", qr_code="QR-ADA-001")
        patcher = patch("checkin.services.publish_print_requested")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

    def test_successful_scan_creates_print_job_and_publishes_event(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/checkin/scan/", {"qr_code": "QR-ADA-001"}, format="json")
        self.assertEqual(response.status_code, 202)

        self.attendee.refresh_from_db()
        self.assertEqual(self.attendee.status, Attendee.Status.PENDING)

        self.assertEqual(PrintJob.objects.filter(attendee=self.attendee).count(), 1)
        job = PrintJob.objects.get(attendee=self.attendee)
        self.assertEqual(job.status, PrintJob.Status.QUEUED)

        self.mock_publish.assert_called_once_with(
            event_id=job.event_id, job_id=job.job_id, attendee_id=self.attendee.id
        )

    def test_invalid_qr_code_returns_404(self):
        response = self.client.post("/api/checkin/scan/", {"qr_code": "QR-DOES-NOT-EXIST"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "attendee_not_found")

    def test_duplicate_scan_while_pending_is_rejected(self):
        first = self.client.post("/api/checkin/scan/", {"qr_code": "QR-ADA-001"}, format="json")
        self.assertEqual(first.status_code, 202)

        second = self.client.post("/api/checkin/scan/", {"qr_code": "QR-ADA-001"}, format="json")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["error"], "print_already_in_progress")

        self.assertEqual(PrintJob.objects.filter(attendee=self.attendee).count(), 1)

    def test_duplicate_scan_after_check_in_is_rejected(self):
        self.attendee.status = Attendee.Status.CHECKED_IN
        self.attendee.save()

        response = self.client.post("/api/checkin/scan/", {"qr_code": "QR-ADA-001"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "already_checked_in")
        self.assertEqual(PrintJob.objects.filter(attendee=self.attendee).count(), 0)

    def test_attendee_status_endpoint(self):
        response = self.client.get(f"/api/checkin/{self.attendee.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "NOT_CHECKED_IN")

    def test_attendee_status_endpoint_unknown_id_404(self):
        response = self.client.get("/api/checkin/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)
