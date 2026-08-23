import hashlib
import hmac

from django.conf import settings

SIGNATURE_HEADER = "X-Signature"


def sign_payload(raw_body: bytes, secret: str | None = None) -> str:
    secret = secret or settings.PRINTER_WEBHOOK_SECRET
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, signature: str, secret: str | None = None) -> bool:
    if not signature:
        return False
    expected = sign_payload(raw_body, secret=secret)
    return hmac.compare_digest(expected, signature)
