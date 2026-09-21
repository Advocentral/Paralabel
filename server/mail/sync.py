"""Connect and poll orchestration for Gmail accounts.

- connect_account: store the encrypted refresh token, create the tenant's labels in
  Gmail, and record the starting historyId.
- poll_account: pull new INBOX mail since the stored historyId, triage each message,
  and advance the cursor only after everything processed. Handles a too-old historyId
  (404 -> bounded 24h resync) and revoked access (invalid_grant -> mark for reconnect
  and email the owner).

Provider construction is injectable (`provider_factory`) so tests use a fake Gmail API.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import Settings
from ..app.crypto import TokenCipher
from ..app.mailer import send_email
from ..app.models import AuditLog, GoogleAccount, Label, User
from ..triage.factory import get_classifier
from ..triage.store import ruleset_from_db
from ..triage.worker import process_message
from .gmail import GmailApi, GmailProvider
from .oauth import build_credentials, build_gmail_service
from .provider import MailProvider


def _default_provider_factory(settings: Settings, account: GoogleAccount, parent: str) -> MailProvider:
    cipher = TokenCipher(settings.token_encryption_key)
    refresh_token = cipher.decrypt(account.refresh_token_enc)
    creds = build_credentials(settings, refresh_token)
    service = build_gmail_service(creds)
    return GmailProvider(GmailApi(service), parent_label=parent)


def _parent_label(session: Session, tenant_id: int) -> str:
    label = session.scalars(select(Label).where(Label.tenant_id == tenant_id)).first()
    return (label.parent if label else "Paralabel/") or "Paralabel/"


def connect_account(
    session: Session,
    settings: Settings,
    tenant_id: int,
    email: str,
    refresh_token: str,
    provider_factory=_default_provider_factory,
) -> GoogleAccount:
    cipher = TokenCipher(settings.token_encryption_key)
    account = session.scalars(
        select(GoogleAccount).where(GoogleAccount.tenant_id == tenant_id, GoogleAccount.email == email)
    ).first()
    if account is None:
        account = GoogleAccount(tenant_id=tenant_id, email=email)
        session.add(account)
    account.refresh_token_enc = cipher.encrypt(refresh_token)
    account.status = "connected"
    session.flush()

    provider = provider_factory(settings, account, _parent_label(session, tenant_id))

    # Create the tenant's labels in Gmail and store their ids.
    labels = session.scalars(
        select(Label).where(Label.tenant_id == tenant_id).order_by(Label.sort_order)
    ).all()
    for label in labels:
        pl = provider.ensure_label(label.name, label.color)
        label.gmail_label_id = pl.provider_label_id

    # In push mode, register a Gmail watch (sets the starting historyId + expiry).
    # In poll mode, just record the current historyId as the cursor.
    if settings.gmail_mode == "push" and settings.pubsub_topic:
        history_id, expiration = provider.start_watch(settings.pubsub_topic)
        account.history_id = history_id
        account.watch_expiration = expiration
    else:
        account.history_id = provider.current_history_id()
        account.watch_expiration = None
    account.last_sync_at = datetime.now(timezone.utc)
    session.add(AuditLog(tenant_id=tenant_id, actor=email, action="google.connect",
                         detail={"email": email, "mode": settings.gmail_mode}))
    session.flush()
    return account


def _sync_core(session: Session, settings: Settings, account: GoogleAccount, provider: MailProvider) -> int:
    """Advance an account from its stored historyId: fetch new mail, triage, save.

    Shared by poll (poll_account) and push (process_push). The cursor only advances
    after every message is processed, so a crash mid-batch re-processes idempotently.
    """
    tenant_id = account.tenant_id
    if not account.history_id:
        account.history_id = provider.current_history_id()
        account.last_sync_at = datetime.now(timezone.utc)
        session.flush()
        return 0

    ruleset = ruleset_from_db(session, tenant_id)
    classifier = get_classifier(settings)

    try:
        messages, latest = provider.history_since(account.history_id)
    except HttpError as exc:
        if getattr(exc, "resp", None) is not None and exc.resp.status == 404:
            # historyId too old — bounded resync of the last 24h of INBOX.
            messages = provider.resync_recent()
            latest = provider.current_history_id()
        else:
            raise
    except RefreshError:
        _mark_reconnect(session, account)
        return 0

    count = 0
    for msg in messages:
        record = process_message(session, tenant_id, provider, ruleset, classifier, msg, settings)
        if record is not None:
            count += 1

    account.history_id = latest
    account.last_sync_at = datetime.now(timezone.utc)
    session.flush()
    return count


def poll_account(
    session: Session,
    settings: Settings,
    account: GoogleAccount,
    provider_factory=_default_provider_factory,
) -> int:
    """Poll one account; returns the number of messages triaged."""
    if account.status != "connected":
        return 0
    parent = _parent_label(session, account.tenant_id)
    try:
        provider = provider_factory(settings, account, parent)
    except RefreshError:
        _mark_reconnect(session, account)
        return 0
    return _sync_core(session, settings, account, provider)


def _mark_reconnect(session: Session, account: GoogleAccount) -> None:
    account.status = "needs_reconnect"
    session.add(AuditLog(tenant_id=account.tenant_id, actor="system", action="google.invalid_grant",
                         detail={"email": account.email}))
    owner = session.scalars(
        select(User).where(User.tenant_id == account.tenant_id, User.is_owner == True)  # noqa: E712
    ).first()
    if owner:
        send_email(
            owner.email,
            "Reconnect your Gmail account",
            f"Access to {account.email} was revoked or expired. Please reconnect in the dashboard.",
        )
    session.flush()


def poll_all(session: Session, settings: Settings, provider_factory=_default_provider_factory) -> int:
    accounts = session.scalars(
        select(GoogleAccount).where(GoogleAccount.status == "connected")
    ).all()
    total = 0
    for account in accounts:
        total += poll_account(session, settings, account, provider_factory)
    session.commit()
    return total


def process_push(
    session: Session,
    settings: Settings,
    email: str,
    notified_history_id: str,
    provider_factory=_default_provider_factory,
) -> int:
    """Handle a verified Gmail push: sync the matching account from its stored cursor.

    `notified_history_id` is Gmail's latest historyId; we ignore it as the start point
    and sync from our own stored cursor so nothing is skipped, then advance.
    """
    account = session.scalars(
        select(GoogleAccount).where(GoogleAccount.email == email, GoogleAccount.status == "connected")
    ).first()
    if account is None:
        return 0
    parent = _parent_label(session, account.tenant_id)
    try:
        provider = provider_factory(settings, account, parent)
    except RefreshError:
        _mark_reconnect(session, account)
        session.commit()
        return 0
    count = _sync_core(session, settings, account, provider)
    session.commit()
    return count


def renew_watches(session: Session, settings: Settings, provider_factory=_default_provider_factory) -> int:
    """Re-register Gmail watches (they expire after 7 days). Run daily in push mode.

    Renewal keeps the existing processing cursor; it only refreshes the expiration.
    """
    if settings.gmail_mode != "push" or not settings.pubsub_topic:
        return 0
    accounts = session.scalars(
        select(GoogleAccount).where(GoogleAccount.status == "connected")
    ).all()
    renewed = 0
    for account in accounts:
        parent = _parent_label(session, account.tenant_id)
        try:
            provider = provider_factory(settings, account, parent)
            _, expiration = provider.start_watch(settings.pubsub_topic)
        except RefreshError:
            _mark_reconnect(session, account)
            continue
        account.watch_expiration = expiration
        renewed += 1
    session.commit()
    return renewed
