from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/checkin/", include("checkin.urls")),
    path("api/webhooks/", include("checkin.webhook_urls")),
    path("", include("kiosk.urls")),
]
