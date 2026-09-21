from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import select

from server.app.config import Settings
from server.app.crypto import new_key
from server.app.models import GoogleAccount, TriageRecord
from server.mail import pubsub, sync
from server.mail.gmail import GmailProvider

from .fakes import FakeGmailApi


def _push_settings() -> Settings:
    return Settings(
        token_encryption_key=new_key(), classifier="demo", price_per_billion_tokens=1000.0,
        gmail_mode="push", pubsub_topic="projects/p/topics/gmail",
        pubsub_audience="https://app.example/api/google/push",
        pubsub_service_account="push@p.iam.gserviceaccount.com", _env_file=None,
    )


def _factory(api: FakeGmailApi):
    def make(settings, account, parent):
        return GmailProvider(api, parent_label=parent)
    return make


# ---- pubsub message parsing / verification ----

def test_decode_message():
    payload = base64.b64encode(json.dumps({"emailAddress": "firm@example.com", "historyId": 4321}).encode()).decode()
    email, hid = pubsub.decode_message({"message": {"data": payload}})
    assert email == "firm@example.com"
    assert hid == "4321"


def test_decode_message_rejects_empty():
    with pytest.raises(pubsub.PushVerificationError):
        pubsub.decode_message({"message": {}})


def test_bearer_token_parsing():
    assert pubsub.bearer_token("Bearer abc.def") == "abc.def"
    assert pubsub.bearer_token(None) == ""


def test_verify_requires_config():
    s = Settings(pubsub_audience="", pubsub_service_account="", _env_file=None)
    with pytest.raises(pubsub.PushVerificationError):
        pubsub.verify_push_token("tok", s)


# ---- connect registers a watch in push mode ----

def test_connect_registers_watch(session, tenant_id):
    settings = _push_settings()
    api = FakeGmailApi(profile_history_id="900")
    account = sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok",
                                   provider_factory=_factory(api))
    session.commit()
    assert account.history_id == "900"
    assert account.watch_expiration is not None
    assert api.watched[0] == "projects/p/topics/gmail"


# ---- push processing ----

def test_process_push_triages_and_advances(session, tenant_id):
    settings = _push_settings()
    api = FakeGmailApi(profile_history_id="900")
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok", provider_factory=_factory(api))
    session.commit()

    api.add_inbox_message("m1", history_id="901", sender="Clerk <ecf@txsd.uscourts.gov>",
                          subject="Notice of Electronic Filing", body="The Clerk of court docketed this. CM/ECF.")
    n = sync.process_push(session, settings, "firm@example.com", "901", provider_factory=_factory(api))
    assert n == 1
    rec = session.scalars(select(TriageRecord)).first()
    assert rec.message_id == "m1"
    assert "Deadlines & court" in rec.applied_labels
    account = session.scalars(select(GoogleAccount)).first()
    assert account.history_id == "901"


def test_duplicate_push_is_idempotent(session, tenant_id):
    settings = _push_settings()
    api = FakeGmailApi(profile_history_id="900")
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok", provider_factory=_factory(api))
    session.commit()
    api.add_inbox_message("m1", history_id="901", subject="Invoice", body="invoice for your subscription")

    sync.process_push(session, settings, "firm@example.com", "901", provider_factory=_factory(api))
    second = sync.process_push(session, settings, "firm@example.com", "901", provider_factory=_factory(api))
    assert second == 0
    assert len(session.scalars(select(TriageRecord)).all()) == 1


def test_push_unknown_email_noop(session, tenant_id):
    settings = _push_settings()
    api = FakeGmailApi()
    n = sync.process_push(session, settings, "nobody@example.com", "1", provider_factory=_factory(api))
    assert n == 0


def test_renew_watches_updates_expiration(session, tenant_id):
    settings = _push_settings()
    api = FakeGmailApi(profile_history_id="900")
    sync.connect_account(session, settings, tenant_id, "firm@example.com", "tok", provider_factory=_factory(api))
    session.commit()
    account = session.scalars(select(GoogleAccount)).first()
    account.watch_expiration = None
    session.commit()

    n = sync.renew_watches(session, settings, provider_factory=_factory(api))
    assert n == 1
    assert session.scalars(select(GoogleAccount)).first().watch_expiration is not None
