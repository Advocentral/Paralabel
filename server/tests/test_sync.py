from __future__ import annotations

from sqlalchemy import select

from server.app.models import GoogleAccount, Label, TriageRecord, User
from server.mail import sync
from server.mail.gmail import GmailProvider

from .fakes import FakeGmailApi, make_raw_message


def _factory(api: FakeGmailApi):
    def make(settings, account, parent):
        return GmailProvider(api, parent_label=parent)
    return make


def test_connect_creates_labels_and_sets_history(session, settings, tenant_id):
    api = FakeGmailApi(profile_history_id="500")
    account = sync.connect_account(
        session, settings, tenant_id, "firm@example.com", "refresh-tok",
        provider_factory=_factory(api),
    )
    session.commit()

    assert account.status == "connected"
    assert account.history_id == "500"
    # Every tenant label now has a Gmail id.
    labels = session.scalars(select(Label).where(Label.tenant_id == tenant_id)).all()
    assert labels and all(lb.gmail_label_id for lb in labels)
    # Refresh token stored encrypted, not in plaintext.
    assert account.refresh_token_enc and account.refresh_token_enc != "refresh-tok"


def test_poll_triages_new_mail_and_advances_cursor(session, settings, tenant_id):
    api = FakeGmailApi(profile_history_id="500")
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok",
                         provider_factory=_factory(api))
    session.commit()

    api.add_inbox_message("m1", history_id="501",
                          sender="Clerk <ecf@txsd.uscourts.gov>",
                          subject="Notice of Electronic Filing",
                          body="The Clerk of court docketed this. CM/ECF.")
    account = session.scalars(select(GoogleAccount)).first()
    n = sync.poll_account(session, settings, account, provider_factory=_factory(api))
    session.commit()

    assert n == 1
    assert account.history_id == "501"
    rec = session.scalars(select(TriageRecord)).first()
    assert rec.message_id == "m1"
    assert "Deadlines & court" in rec.applied_labels


def test_poll_is_idempotent_on_duplicate_history(session, settings, tenant_id):
    api = FakeGmailApi(profile_history_id="500")
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok",
                         provider_factory=_factory(api))
    session.commit()
    api.add_inbox_message("m1", history_id="501", subject="Invoice", body="invoice for your subscription")
    account = session.scalars(select(GoogleAccount)).first()

    sync.poll_account(session, settings, account, provider_factory=_factory(api))
    # Same history record delivered again (duplicate notification).
    second = sync.poll_account(session, settings, account, provider_factory=_factory(api))
    session.commit()
    assert second == 0
    assert len(session.scalars(select(TriageRecord)).all()) == 1


def test_poll_404_triggers_resync(session, settings, tenant_id, monkeypatch):
    api = FakeGmailApi(profile_history_id="500")
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok",
                         provider_factory=_factory(api))
    session.commit()
    account = session.scalars(select(GoogleAccount)).first()

    # Make history_since raise a 404 HttpError; resync_recent should be used instead.
    from googleapiclient.errors import HttpError

    class _Resp:
        status = 404
        reason = "Not Found"

    def boom(_start):
        raise HttpError(_Resp(), b"gone")

    api.messages["m5"] = make_raw_message(
        "m5", subject="Notice of Electronic Filing", body="Clerk of court docketed. CM/ECF.")

    provider = GmailProvider(api, parent_label="Paralabel/")
    monkeypatch.setattr(provider, "history_since", boom)
    n = sync.poll_account(session, settings, account, provider_factory=lambda *a, **k: provider)
    session.commit()
    assert n == 1


def test_invalid_grant_marks_reconnect_and_emails_owner(session, settings, tenant_id, monkeypatch):
    from google.auth.exceptions import RefreshError

    session.add(User(tenant_id=tenant_id, email="owner@firm.example", is_owner=True))
    api = FakeGmailApi()
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok",
                         provider_factory=_factory(api))
    session.commit()
    account = session.scalars(select(GoogleAccount)).first()
    account.history_id = "500"

    sent = {}

    def fake_send(to, subject, body, settings=None):
        sent["to"] = to
        return True

    monkeypatch.setattr(sync, "send_email", fake_send)

    def raise_refresh(*a, **k):
        raise RefreshError("invalid_grant")

    n = sync.poll_account(session, settings, account, provider_factory=raise_refresh)
    session.commit()
    assert n == 0
    assert account.status == "needs_reconnect"
    assert sent.get("to") == "owner@firm.example"
