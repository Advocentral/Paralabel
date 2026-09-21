"""Google connection endpoints: authorize, OAuth callback, status, poll, disconnect."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...mail import oauth, pubsub, sync
from ..bootstrap import ensure_default_tenant
from ..config import Settings, get_settings
from ..crypto import TokenCipher
from ..db import _session_factory, get_session
from ..models import GoogleAccount

router = APIRouter(prefix="/api/google", tags=["google"])


def _tenant_id(session: Session, settings: Settings) -> int:
    return ensure_default_tenant(session, settings)


@router.get("/authorize")
def authorize(settings: Settings = Depends(get_settings)) -> dict:
    if not settings.google_client_id:
        raise HTTPException(400, "GOOGLE_CLIENT_ID is not configured")
    url, state = oauth.authorization_url(settings)
    return {"authorization_url": url, "state": state}


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str | None = Query(None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    tenant_id = _tenant_id(session, settings)
    tokens = oauth.exchange_code(settings, code, state=state)
    if not tokens.get("refresh_token"):
        raise HTTPException(400, "No refresh token returned; re-consent with prompt=consent")
    sync.connect_account(
        session, settings, tenant_id, tokens["email"], tokens["refresh_token"]
    )
    session.commit()
    return RedirectResponse(f"{settings.dashboard_origin}/connect?status=connected")


@router.get("/status")
def status(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    tenant_id = _tenant_id(session, settings)
    accounts = session.scalars(
        select(GoogleAccount).where(GoogleAccount.tenant_id == tenant_id)
    ).all()
    return {
        "accounts": [
            {
                "email": a.email,
                "status": a.status,
                "history_id": a.history_id,
                "last_sync_at": a.last_sync_at.isoformat() if a.last_sync_at else None,
                "watch_expiration": a.watch_expiration.isoformat() if a.watch_expiration else None,
            }
            for a in accounts
        ]
    }


@router.post("/poll")
def poll(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    _tenant_id(session, settings)
    triaged = sync.poll_all(session, settings)
    return {"triaged": triaged}


def _run_push(settings: Settings, email: str, history_id: str) -> None:
    """Background worker: sync the notified account on its own DB session."""
    session = _session_factory()()
    try:
        sync.process_push(session, settings, email, history_id)
    finally:
        session.close()


@router.post("/push")
async def push(
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Gmail Pub/Sub push endpoint. Verify the JWT, ack fast, enqueue the sync."""
    token = pubsub.bearer_token(request.headers.get("authorization"))
    try:
        pubsub.verify_push_token(token, settings)
    except pubsub.PushVerificationError:
        raise HTTPException(401, "invalid push token")
    try:
        body = await request.json()
        email, history_id = pubsub.decode_message(body)
    except Exception:  # noqa: BLE001 - malformed but authenticated: ack to stop redelivery
        return {"status": "ignored"}
    background.add_task(_run_push, settings, email, history_id)
    return {"status": "ok"}


@router.post("/disconnect")
def disconnect(
    email: str = Query(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    tenant_id = _tenant_id(session, settings)
    account = session.scalars(
        select(GoogleAccount).where(
            GoogleAccount.tenant_id == tenant_id, GoogleAccount.email == email
        )
    ).first()
    if account is None:
        raise HTTPException(404, "account not found")

    # Best-effort token revocation with Google.
    try:
        cipher = TokenCipher(settings.token_encryption_key)
        refresh_token = cipher.decrypt(account.refresh_token_enc)
        httpx.post("https://oauth2.googleapis.com/revoke",
                   data={"token": refresh_token}, timeout=10.0)
    except Exception:  # noqa: BLE001 - revocation is best-effort
        pass

    account.status = "disconnected"
    account.refresh_token_enc = ""
    session.commit()
    return {"status": "disconnected", "email": email}
