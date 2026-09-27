"""Authentication helpers for ElevenLabs webhooks and company call data."""

from __future__ import annotations

import hashlib
import hmac
import time


class InvalidWebhookSignature(ValueError):
    pass


def verify_elevenlabs_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
    *,
    now: int | None = None,
    tolerance_seconds: int = 300,
) -> None:
    """Verify ElevenLabs' ``t=<unix>,v0=<hmac>`` signed body format."""

    if not signature_header:
        raise InvalidWebhookSignature("missing signature")
    values: dict[str, list[str]] = {}
    for component in signature_header.split(","):
        key, separator, value = component.strip().partition("=")
        if separator and key and value:
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values["t"][0])
        signatures = values["v0"]
    except (KeyError, ValueError, IndexError):
        raise InvalidWebhookSignature("malformed signature") from None
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise InvalidWebhookSignature("expired signature")
    signed = str(timestamp).encode("ascii") + b"." + body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidWebhookSignature("signature mismatch")


def token_matches(value: str | None, expected: str | None) -> bool:
    if not value or not expected:
        return False
    scheme, separator, token = value.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token.strip(), expected)
    )

