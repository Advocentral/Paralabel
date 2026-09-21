from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from server.app.db import Base
from server.app.models import Label, Question, Rule, RuleSetVersion, Tenant
from server.triage.seed import seed_tenant


def _session() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_seed_creates_rows_and_version():
    s = _session()
    tenant = Tenant(name="Test Firm", template_key="general")
    s.add(tenant)
    s.flush()

    version = seed_tenant(s, tenant.id, "general", author_email="owner@firm.example")
    s.commit()

    assert version.version == 1
    assert s.scalars(select(Question).where(Question.tenant_id == tenant.id)).all()
    labels = s.scalars(select(Label).where(Label.tenant_id == tenant.id)).all()
    assert any(label.name == "Newsletters & marketing" for label in labels)
    rules = s.scalars(select(Rule).where(Rule.tenant_id == tenant.id)).all()
    assert any(r.is_fallback for r in rules)
    assert any(r.is_system_protected for r in rules)


def test_reseed_bumps_version_and_replaces_rules():
    s = _session()
    tenant = Tenant(name="Firm", template_key="general")
    s.add(tenant)
    s.flush()

    seed_tenant(s, tenant.id, "general")
    v2 = seed_tenant(s, tenant.id, "bankruptcy")
    s.commit()

    assert v2.version == 2
    versions = s.scalars(select(RuleSetVersion).where(RuleSetVersion.tenant_id == tenant.id)).all()
    assert len(versions) == 2
    # Rules replaced, not duplicated: bankruptcy has a 'trustee' rule.
    rules = s.scalars(select(Rule).where(Rule.tenant_id == tenant.id)).all()
    keys = {r.rule_key for r in rules}
    assert "trustee" in keys
