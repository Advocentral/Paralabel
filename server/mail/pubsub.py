"""Gmail push (Pub/Sub) message verification and parsing.

Gmail publishes a change notification to a Pub/Sub topic; the subscription pushes it to
our endpoint as an HTTP POST. Google signs the push with an OIDC JWT in the
Authorization header. We verify the token's audience and service-account email before
trusting the body, then decode the message to (emailAddress, historyId).
"""

from __future__ import annotations

import base64
import json

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from ..app.config import Settings


class PushVerificationError(RuntimeError):
    pass


_request = google_requests.Request()


def verify_push_token(token: str, settings: Settings) -> dict:
    """Verify the OIDC JWT Google attached to the push. Returns its claims.

    Requires PUBSUB_AUDIENCE and PUBSUB_SERVICE_ACCOUNT to be configured — we refuse
    unverified pushes rather than trusting the body blindly.
    """
    if not settings.pubsub_audience or not settings.pubsub_service_account:
        raise PushVerificationError(
            "PUBSUB_AUDIENCE and PUBSUB_SERVICE_ACCOUNT must be set to accept push notifications."
        )
    if not token:
        raise PushVerificationError("missing bearer token")
    try:
        claims = id_token.verify_oauth2_token(token, _request, audience=settings.pubsub_audience)
    except Exception as exc:  # noqa: BLE001 - any verification failure is a rejection
        raise PushVerificationError(f"token verification failed: {exc}") from exc
    if claims.get("email") != settings.pubsub_service_account:
        raise PushVerificationError("token email does not match the configured service account")
    if not claims.get("email_verified", False):
        raise PushVerificationError("token email is not verified")
    return claims


def bearer_token(authorization_header: str | None) -> str:
    if not authorization_header:
        return ""
    parts = authorization_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization_header.strip()


def decode_message(body: dict) -> tuple[str, str]:
    """Decode a Pub/Sub push body into (emailAddress, historyId)."""
    message = body.get("message") or {}
    data = message.get("data")
    if not data:
        raise PushVerificationError("push message has no data")
    decoded = json.loads(base64.b64decode(data).decode())
    email = decoded.get("emailAddress", "")
    history_id = str(decoded.get("historyId", ""))
    if not email or not history_id:
        raise PushVerificationError("push data missing emailAddress or historyId")
    return email, history_id
