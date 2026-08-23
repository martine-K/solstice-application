import uuid
from unittest.mock import patch

from django.test import TestCase

from checkin.publisher import publish_print_requested


class PublisherTests(TestCase):
    @patch("checkin.publisher.handle_print_requested.delay")
    def test_publish_print_requested_enqueues_celery_task(self, mock_delay):
        event_id = uuid.uuid4()
        job_id = uuid.uuid4()
        attendee_id = uuid.uuid4()

        publish_print_requested(event_id=event_id, job_id=job_id, attendee_id=attendee_id)

        mock_delay.assert_called_once()
        (message,), _kwargs = mock_delay.call_args
        self.assertEqual(message["event"], "badge.print.requested")
        self.assertEqual(message["event_id"], str(event_id))
        self.assertEqual(message["job_id"], str(job_id))
        self.assertEqual(message["attendee_id"], str(attendee_id))
        self.assertIn("timestamp", message)
