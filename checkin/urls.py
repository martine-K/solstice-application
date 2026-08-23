from django.urls import path

from checkin.views import AttendeeStatusView, ScanView

urlpatterns = [
    path("scan/", ScanView.as_view(), name="checkin-scan"),
    path("<uuid:attendee_id>/", AttendeeStatusView.as_view(), name="checkin-status"),
]
