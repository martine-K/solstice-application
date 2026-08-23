from django.urls import path

from kiosk.views import kiosk_home

urlpatterns = [
    path("", kiosk_home, name="kiosk-home"),
]
