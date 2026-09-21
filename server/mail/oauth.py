"""Google OAuth 2.0 web flow (offline access) and Gmail service construction.

Scopes are minimal and fixed: gmail.modify (labels + read metadata) plus openid/email
for sign-in. Do not add scopes for unshipped features — Google review rejects unused
scopes.
"""

from __future__ import annotations

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..app.config import Settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_flow(settings: Settings, state: str | None = None) -> Flow:
    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def authorization_url(settings: Settings) -> tuple[str, str]:
    flow = build_flow(settings)
    url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return url, state


def exchange_code(settings: Settings, code: str, state: str | None = None) -> dict:
    """Exchange an auth code for tokens; returns email + refresh token."""
    flow = build_flow(settings, state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    email = _fetch_email(creds)
    return {
        "email": email,
        "refresh_token": creds.refresh_token,
        "access_token": creds.token,
    }


def _fetch_email(creds: Credentials) -> str:
    oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    return oauth2.userinfo().get().execute().get("email", "")


def build_credentials(settings: Settings, refresh_token: str) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )


def build_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
