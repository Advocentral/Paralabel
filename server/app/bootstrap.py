"""Single-tenant bootstrap for v0.1.

Ensures one default tenant exists and is seeded from the configured template. The
schema is multi-tenant (tenant_id everywhere); this just picks the one tenant a v0.1
deployment serves.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..triage.seed import seed_tenant
from .config import Settings
from .models import Question, Tenant


def ensure_default_tenant(session: Session, settings: Settings) -> int:
    tenant = session.scalars(select(Tenant).order_by(Tenant.id)).first()
    if tenant is None:
        tenant = Tenant(name=settings.default_tenant_name, template_key=settings.default_template)
        session.add(tenant)
        session.flush()
    # Seed the rule set once (detect by whether any question exists).
    has_questions = session.scalars(
        select(Question.id).where(Question.tenant_id == tenant.id)
    ).first()
    if not has_questions:
        seed_tenant(session, tenant.id, tenant.template_key)
    session.commit()
    return tenant.id
