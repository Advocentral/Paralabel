"""Build the engine's domain RuleSet from a tenant's editable ORM rows.

We reconstruct the same template-shaped dict the loader understands and reuse
`ruleset_from_dict`, so there is exactly one parser for conditions/actions.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.models import Label, Question, Rule, SenderList, Tenant
from .loader import ruleset_from_dict
from .rules import RuleSet


def ruleset_dict_from_db(session: Session, tenant_id: int) -> dict:
    tenant = session.get(Tenant, tenant_id)
    parent = "Paralabel/"
    questions = session.scalars(select(Question).where(Question.tenant_id == tenant_id)).all()
    labels = session.scalars(
        select(Label).where(Label.tenant_id == tenant_id).order_by(Label.sort_order)
    ).all()
    lists = session.scalars(select(SenderList).where(SenderList.tenant_id == tenant_id)).all()
    rules = session.scalars(
        select(Rule).where(Rule.tenant_id == tenant_id).order_by(Rule.position)
    ).all()
    if labels:
        parent = labels[0].parent or parent

    return {
        "template_key": tenant.template_key if tenant else "general",
        "parent_label": parent,
        "questions": [
            {
                "key": q.key,
                "prompt": q.prompt,
                "answer_type": q.answer_type,
                "allowed_answers": q.allowed_answers,
                "is_system": q.is_system,
                "enabled": q.enabled,
            }
            for q in questions
        ],
        "labels": [
            {
                "name": lb.name,
                "color": lb.color,
                "description": lb.description,
                "is_system": lb.is_system,
                "sort_order": lb.sort_order,
            }
            for lb in labels
        ],
        "lists": {sl.name: sl.members for sl in lists},
        "rules": [
            {
                "id": r.rule_key,
                "name": r.name,
                "enabled": r.enabled,
                "position": r.position,
                "match_mode": r.match_mode,
                "conditions": r.conditions,
                "actions": r.actions,
                "stop_processing": r.stop_processing,
                "is_fallback": r.is_fallback,
                "is_system_protected": r.is_system_protected,
            }
            for r in rules
        ],
    }


def ruleset_from_db(session: Session, tenant_id: int) -> RuleSet:
    return ruleset_from_dict(ruleset_dict_from_db(session, tenant_id))


def label_gmail_ids(session: Session, tenant_id: int) -> dict[str, str]:
    """Map label name -> Gmail label id for labels already synced to Gmail."""
    labels = session.scalars(select(Label).where(Label.tenant_id == tenant_id)).all()
    return {lb.name: lb.gmail_label_id for lb in labels if lb.gmail_label_id}
