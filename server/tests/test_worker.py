from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from server.app.models import Label, TriageRecord
from server.mail.gmail import GmailProvider
from server.mail.provider import IncomingMessage
from server.triage.demo import DemoClassifier
from server.triage.store import ruleset_from_db
from server.triage.worker import process_message

from .fakes import FakeGmailApi


def _msg(mid="m1", sender_email="ecf@txsd.uscourts.gov", subject="Notice of Electronic Filing",
         body="The Clerk of court docketed this. CM/ECF case no.") -> IncomingMessage:
    return IncomingMessage(
        message_id=mid, thread_id="t1", sender_name="Clerk",
        sender_email=sender_email, subject=subject, body_text=body,
        received_at=datetime.now(timezone.utc),
    )


def test_process_message_labels_and_records(session, settings, tenant_id):
    provider = GmailProvider(FakeGmailApi())
    ruleset = ruleset_from_db(session, tenant_id)
    rec = process_message(session, tenant_id, provider, ruleset, DemoClassifier(), _msg(), settings)

    assert rec is not None
    assert rec.matched_rule_key == "court"
    assert "Deadlines & court" in rec.applied_labels
    # A Gmail label id was created and stored on the Label row.
    label = session.scalars(
        select(Label).where(Label.tenant_id == tenant_id, Label.name == "Deadlines & court")
    ).first()
    assert label.gmail_label_id
    # Cost derived from tokens and price.
    assert rec.input_tokens > 0
    assert rec.cost > 0


def test_no_body_is_stored(session, settings, tenant_id):
    provider = GmailProvider(FakeGmailApi())
    ruleset = ruleset_from_db(session, tenant_id)
    process_message(session, tenant_id, provider, ruleset, DemoClassifier(), _msg(), settings)
    rec = session.scalars(select(TriageRecord)).first()
    # The model has no body column at all; the stored columns never include body text.
    assert not hasattr(rec, "body")
    assert "docketed" not in (rec.subject or "")


def test_idempotent_skip(session, settings, tenant_id):
    provider = GmailProvider(FakeGmailApi())
    ruleset = ruleset_from_db(session, tenant_id)
    first = process_message(session, tenant_id, provider, ruleset, DemoClassifier(), _msg(), settings)
    second = process_message(session, tenant_id, provider, ruleset, DemoClassifier(), _msg(), settings)
    assert first is not None
    assert second is None
    assert len(session.scalars(select(TriageRecord)).all()) == 1


def test_fallback_label_applied_for_unclassifiable(session, settings, tenant_id):
    provider = GmailProvider(FakeGmailApi())
    ruleset = ruleset_from_db(session, tenant_id)
    rec = process_message(
        session, tenant_id, provider, ruleset, DemoClassifier(),
        _msg(mid="m9", sender_email="random@nowhere.example", subject="hello", body="just saying hi"),
        settings,
    )
    assert rec is not None
    assert rec.applied_labels  # always at least one label
