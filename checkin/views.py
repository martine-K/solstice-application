import json
import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from checkin import services
from checkin.models import Attendee
from checkin.security import SIGNATURE_HEADER, verify_signature
from checkin.serializers import AttendeeSerializer, ScanRequestSerializer, ScanResponseSerializer

logger = logging.getLogger(__name__)


class ScanView(APIView):
    def post(self, request):
        req = ScanRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        qr_code = req.validated_data["qr_code"]

        try:
            result = services.scan_attendee(qr_code)
        except services.ScanError as exc:
            return Response({"error": exc.code, "detail": exc.message}, status=exc.http_status)

        body = ScanResponseSerializer({"attendee": result.attendee, "print_job": result.print_job}).data
        return Response(body, status=202)


class AttendeeStatusView(APIView):
    def get(self, request, attendee_id):
        try:
            attendee = Attendee.objects.get(id=attendee_id)
        except (Attendee.DoesNotExist, ValueError, TypeError):
            return Response({"error": "attendee_not_found", "detail": "No such attendee."}, status=404)
        return Response(AttendeeSerializer(attendee).data, status=200)


class PrinterWebhookView(APIView):
    def post(self, request):
        raw_body = request.body
        signature = request.headers.get(SIGNATURE_HEADER, "")

        if not verify_signature(raw_body, signature):
            logger.warning("rejected printer webhook: invalid HMAC signature")
            return Response(
                {"error": "invalid_signature", "detail": "HMAC signature verification failed."}, status=401
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response({"error": "invalid_payload", "detail": "Body was not valid JSON."}, status=400)

        try:
            result = services.process_print_completed_webhook(payload)
        except services.WebhookProcessingError as exc:
            return Response({"error": exc.code, "detail": exc.message}, status=exc.http_status)

        return Response(result, status=200)
