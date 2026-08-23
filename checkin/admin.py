from django.contrib import admin

from checkin.models import Attendee, PrintJob, WebhookEvent


@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
    list_display = ("name", "qr_code", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "qr_code")


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "attendee", "status", "created_at", "completed_at")
    list_filter = ("status",)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "processed", "received_at")
    list_filter = ("processed", "event_type")
