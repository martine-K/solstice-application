from django.urls import path

from checkin.views import PrinterWebhookView

urlpatterns = [
    path("printer/", PrinterWebhookView.as_view(), name="printer-webhook"),
]
