from django.shortcuts import render


def kiosk_home(request):
    return render(request, "kiosk/index.html")
