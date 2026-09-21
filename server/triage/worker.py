"""Process one incoming message end to end: classify, decide, label, record.

Idempotent: a message already in triage_records for this tenant is skipped, so
duplicate notifications (M3) never double-process.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import Settings
from ..app.models import AuditLog, Label, RuleSetVersion, TriageRecord
from ..mail.provider import IncomingMessage, MailProvider
from .body import clean_body
from .classifier import Classifier
from .engine import triage
from .rules import EmailMeta, RuleSet


def _latest_version(session: Session, tenant_id: int) -> int | None:
    return session.scalars(
        select(RuleSetVersion.version)
        .where(RuleSetVersion.tenant_id == tenant_id)
        .order_by(RuleSetVersion.version.desc())
    ).first()


def _resolve_gmail_ids(session: Session, tenant_id: int, provider: MailProvider, names: list[str]) -> list[str]:
    """Return Gmail label ids for the given label names, creating any not yet synced."""
    ids: list[str] = []
    for name in names:
        label = session.scalars(
            select(Label).where(Label.tenant_id == tenant_id, Label.name == name)
        ).first()
        if label is None:
            continue  # label deleted between rule save and now; skip defensively
        if not label.gmail_label_id:
            pl = provider.ensure_label(label.name, label.color)
            label.gmail_label_id = pl.provider_label_id
            session.flush()
        ids.append(label.gmail_label_id)
    return ids


def already_triaged(session: Session, tenant_id: int, message_id: str) -> bool:
    return session.scalars(
        select(TriageRecord.id).where(
            TriageRecord.tenant_id == tenant_id, TriageRecord.message_id == message_id
        )
    ).first() is not None


def process_message(
    session: Session,
    tenant_id: int,
    provider: MailProvider,
    ruleset: RuleSet,
    classifier: Classifier,
    msg: IncomingMessage,
    settings: Settings,
) -> TriageRecord | None:
    if already_triaged(session, tenant_id, msg.message_id):
        return None

    meta = EmailMeta(
        sender_name=msg.sender_name,
        sender_email=msg.sender_email,
        subject=msg.subject,
        received_at=msg.received_at,
        has_attachment=msg.has_attachment,
        delivered_to=msg.delivered_to,
        is_reply=msg.is_reply,
    )
    body = clean_body(msg.body_text)
    decision = triage(ruleset, classifier, meta, body)

    gmail_ids = _resolve_gmail_ids(session, tenant_id, provider, decision.applied_labels)
    if gmail_ids:
        provider.apply_labels(msg.message_id, add=gmail_ids, remove=[])

    probabilities = {
        key: {"answer": r.answer, "probabilities": r.probabilities}
        for key, r in decision.result.results.items()
    }
    tokens = decision.result.total_input_tokens
    cost = tokens / 1e9 * settings.price_per_billion_tokens

    record = TriageRecord(
        tenant_id=tenant_id,
        message_id=msg.message_id,
        thread_id=msg.thread_id,
        received_at=msg.received_at,
        sender_email=msg.sender_email,
        subject=msg.subject,
        applied_labels=decision.applied_labels,
        matched_rule_key=decision.primary_rule_id,
        ruleset_version=_latest_version(session, tenant_id),
        probabilities=probabilities,
        classifier_name=decision.result.classifier_name,
        latency_ms=decision.result.total_latency_ms,
        input_tokens=tokens,
        cost=cost,
        created_at=datetime.now(timezone.utc),
    )
    session.add(record)
    session.add(AuditLog(
        tenant_id=tenant_id,
        actor="system",
        action="triage.decision",
        detail={
            "message_id": msg.message_id,
            "rule": decision.primary_rule_id,
            "labels": decision.applied_labels,
        },
    ))
    session.flush()
    return record
