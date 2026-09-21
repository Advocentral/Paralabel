"""Seed a tenant's editable rule set from a template.

Called on tenant creation and on "reset to defaults" (which creates a new version, so
it is reversible). Maps the template JSON into ORM rows and records an immutable
RuleSetVersion snapshot.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.models import (
    AuditLog,
    Label,
    Question,
    Rule,
    RuleSetVersion,
    SenderList,
)
from .loader import load_template_dict


def _clear_ruleset(session: Session, tenant_id: int) -> None:
    for model in (Rule, Question, Label, SenderList):
        for row in session.scalars(select(model).where(model.tenant_id == tenant_id)):
            session.delete(row)
    session.flush()


def seed_tenant(session: Session, tenant_id: int, template_key: str, author_email: str = "system") -> RuleSetVersion:
    data = load_template_dict(template_key)
    _clear_ruleset(session, tenant_id)

    for qd in data.get("questions", []):
        session.add(Question(
            tenant_id=tenant_id,
            key=qd["key"],
            prompt=qd["prompt"],
            answer_type=qd.get("answer_type", "single_choice"),
            allowed_answers=list(qd["allowed_answers"]),
            is_system=qd.get("is_system", False),
            enabled=qd.get("enabled", True),
        ))

    for ld in data.get("labels", []):
        session.add(Label(
            tenant_id=tenant_id,
            name=ld["name"],
            color=ld.get("color", ""),
            description=ld.get("description", ""),
            parent=data.get("parent_label", "Paralabel/"),
            is_system=ld.get("is_system", False),
            sort_order=int(ld.get("sort_order", 0)),
        ))

    for name, members in data.get("lists", {}).items():
        session.add(SenderList(tenant_id=tenant_id, name=name, members=[m.lower() for m in members]))

    for rd in data.get("rules", []):
        session.add(Rule(
            tenant_id=tenant_id,
            rule_key=rd["id"],
            name=rd["name"],
            enabled=rd.get("enabled", True),
            position=int(rd.get("position", 0)),
            match_mode=rd.get("match_mode", "all"),
            conditions=rd.get("conditions", []),
            actions=rd.get("actions", {}),
            stop_processing=rd.get("stop_processing", True),
            is_fallback=rd.get("is_fallback", False),
            is_system_protected=rd.get("is_system_protected", False),
        ))

    last_version = session.scalars(
        select(RuleSetVersion.version)
        .where(RuleSetVersion.tenant_id == tenant_id)
        .order_by(RuleSetVersion.version.desc())
    ).first()
    version_number = (last_version or 0) + 1

    version = RuleSetVersion(
        tenant_id=tenant_id,
        version=version_number,
        author_email=author_email,
        snapshot=data,
        note=f"Seed from template {template_key!r}",
    )
    session.add(version)
    session.add(AuditLog(
        tenant_id=tenant_id,
        actor=author_email,
        action="ruleset.seed",
        detail={"template": template_key, "version": version_number},
    ))
    session.flush()
    return version
