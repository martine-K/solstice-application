from rest_framework import serializers

from checkin.models import Attendee, PrintJob


class PrintJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintJob
        fields = [
            "job_id",
            "event_id",
            "status",
            "created_at",
            "completed_at",
            "failure_reason",
        ]


class AttendeeSerializer(serializers.ModelSerializer):
    latest_print_job = serializers.SerializerMethodField()

    class Meta:
        model = Attendee
        fields = [
            "id",
            "name",
            "qr_code",
            "status",
            "created_at",
            "updated_at",
            "latest_print_job",
        ]

    def get_latest_print_job(self, attendee):
        job = attendee.print_jobs.order_by("-created_at").first()
        return PrintJobSerializer(job).data if job else None


class ScanRequestSerializer(serializers.Serializer):
    qr_code = serializers.CharField(max_length=255)


class ScanResponseSerializer(serializers.Serializer):
    attendee = AttendeeSerializer()
    print_job = PrintJobSerializer()
