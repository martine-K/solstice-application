import logging
from datetime import datetime, timezone

from checkin.tasks import handle_print_requested

logger = logging.getLogger(__name__)


def publish_print_requested(*, event_id, job_id, attendee_id) -> None:
    message = {
        "event": "badge.print.requested",
        "event_id": str(event_id),
        "job_id": str(job_id),
        "attendee_id": str(attendee_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("publishing badge.print.requested %s", message)
    handle_print_requested.delay(message)
