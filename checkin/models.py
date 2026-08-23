import uuid

from django.db import models


class Attendee(models.Model):
    class Status(models.TextChoices):
        NOT_CHECKED_IN = "NOT_CHECKED_IN", "Not checked in"
        PENDING = "PENDING", "Pending (badge printing)"
        CHECKED_IN = "CHECKED_IN", "Checked in"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    qr_code = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_CHECKED_IN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.status})"


class PrintJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        PRINTING = "PRINTING", "Printing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.BigAutoField(primary_key=True)
    job_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attendee = models.ForeignKey(Attendee, on_delete=models.CASCADE, related_name="print_jobs")
    event_id = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attendee"],
                condition=models.Q(status="QUEUED"),
                name="unique_queued_print_job_per_attendee",
            ),
        ]

    def __str__(self):
        return f"PrintJob({self.job_id}) for {self.attendee_id} [{self.status}]"


class WebhookEvent(models.Model):
    event_id = models.UUIDField(primary_key=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)

    def __str__(self):
        return f"WebhookEvent({self.event_id}, {self.event_type}, processed={self.processed})"
