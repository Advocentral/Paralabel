"""SQLAlchemy models.

Design notes:
- Every table carries `tenant_id` — v0.1 runs one firm per deployment, but the schema
  is multi-tenant from day one.
- Rule conditions and actions are stored as JSON (the same shape templates use). This
  keeps the schema small and the mapping to the engine's domain objects trivial; we do
  not over-normalize a structure the engine already treats as a nested document.
- TriageRecord deliberately has NO body column. We store metadata, applied labels, the
  matched rule, the probabilities JSON, and cost/latency — never email content.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    template_key: Mapped[str] = mapped_column(String(64), default="general")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)


class GoogleAccount(Base):
    __tablename__ = "google_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    # Refresh token encrypted at rest (Fernet). Never logged.
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")
    history_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    watch_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # connected | disconnected | needs_reconnect
    status: Mapped[str] = mapped_column(String(32), default="connected")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    color: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    gmail_label_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent: Mapped[str] = mapped_column(String(128), default="Paralabel/")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_label_tenant_name"),)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    answer_type: Mapped[str] = mapped_column(String(32), default="single_choice")
    allowed_answers: Mapped[list] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_question_tenant_key"),)


class SenderList(Base):
    __tablename__ = "sender_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    # list of email addresses / domains (lowercased)
    members: Mapped[list] = mapped_column(JSON, default=list)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_list_tenant_name"),)


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    rule_key: Mapped[str] = mapped_column(String(64))  # stable id used by the engine
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    match_mode: Mapped[str] = mapped_column(String(8), default="all")
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    actions: Mapped[dict] = mapped_column(JSON, default=dict)
    stop_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system_protected: Mapped[bool] = mapped_column(Boolean, default=False)


class RuleSetVersion(Base):
    __tablename__ = "ruleset_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    author_email: Mapped[str] = mapped_column(String(320), default="")
    # Immutable snapshot of the whole rule set in template JSON format.
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TriageRecord(Base):
    __tablename__ = "triage_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    applied_labels: Mapped[list] = mapped_column(JSON, default=list)
    matched_rule_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ruleset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    classifier_name: Mapped[str] = mapped_column(String(32), default="")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", name="uq_triage_tenant_message"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor: Mapped[str] = mapped_column(String(320), default="system")
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(128), index=True)
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    corrected_labels: Mapped[list] = mapped_column(JSON, default=list)
    probabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
