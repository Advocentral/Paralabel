"""Load a triage template (JSON) into a RuleSet.

Templates live in triage/templates/*.json and are also the import/export format for a
tenant's rule set, so this loader is the single source of truth for that schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from .classifier import AnswerType, QuestionSpec
from .rules import (
    ClassifierCondition,
    Condition,
    LabelSpec,
    ListCondition,
    MetadataCondition,
    Rule,
    RuleActions,
    RuleSet,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _condition(d: dict) -> Condition:
    kind = d["kind"]
    if kind == "classifier":
        return ClassifierCondition(
            question_key=d["question_key"],
            mode=d.get("mode", "is"),
            answers=tuple(d.get("answers", ())),
            prob_op=d.get("prob_op", "gte"),
            threshold=float(d.get("threshold", 0.0)),
            negate=bool(d.get("negate", False)),
        )
    if kind == "metadata":
        return MetadataCondition(
            field=d["field"],
            op=d.get("op", "equals"),
            values=tuple(d.get("values", ())),
            negate=bool(d.get("negate", False)),
        )
    if kind == "list":
        return ListCondition(field=d.get("field", "sender_domain"), list_name=d["list_name"])
    raise ValueError(f"unknown condition kind: {kind!r}")


def _actions(d: dict) -> RuleActions:
    return RuleActions(
        add_labels=tuple(d.get("add_labels", ())),
        mark_important=bool(d.get("mark_important", False)),
        star=bool(d.get("star", False)),
        archive=bool(d.get("archive", False)),
        mark_read=bool(d.get("mark_read", False)),
    )


def _rule(d: dict) -> Rule:
    return Rule(
        id=d["id"],
        name=d["name"],
        conditions=tuple(_condition(c) for c in d.get("conditions", [])),
        actions=_actions(d.get("actions", {})),
        match_mode=d.get("match_mode", "all"),
        enabled=d.get("enabled", True),
        position=int(d.get("position", 0)),
        stop_processing=d.get("stop_processing", True),
        is_fallback=d.get("is_fallback", False),
        is_system_protected=d.get("is_system_protected", False),
    )


def _question(d: dict) -> tuple[QuestionSpec, bool]:
    spec = QuestionSpec(
        key=d["key"],
        prompt=d["prompt"],
        answer_type=AnswerType(d.get("answer_type", "single_choice")),
        allowed_answers=tuple(d["allowed_answers"]),
        is_system=d.get("is_system", False),
    )
    return spec, d.get("enabled", True)


def ruleset_from_dict(data: dict) -> RuleSet:
    questions: dict[str, QuestionSpec] = {}
    enabled_keys: set[str] = set()
    for qd in data.get("questions", []):
        spec, enabled = _question(qd)
        questions[spec.key] = spec
        if enabled:
            enabled_keys.add(spec.key)

    labels = tuple(
        LabelSpec(
            name=ld["name"],
            color=ld.get("color", ""),
            description=ld.get("description", ""),
            is_system=ld.get("is_system", False),
            sort_order=int(ld.get("sort_order", 0)),
        )
        for ld in data.get("labels", [])
    )

    lists = {name: frozenset(m.lower() for m in members) for name, members in data.get("lists", {}).items()}
    rules = tuple(_rule(r) for r in data.get("rules", []))

    return RuleSet(
        template_key=data["template_key"],
        parent_label=data.get("parent_label", "Paralabel/"),
        questions=questions,
        enabled_question_keys=enabled_keys,
        rules=rules,
        labels=labels,
        lists=lists,
    )


def load_template_dict(template_key: str) -> dict:
    path = TEMPLATES_DIR / f"{template_key}.json"
    if not path.exists():
        raise FileNotFoundError(f"template {template_key!r} not found at {path}")
    return json.loads(path.read_text())


def load_template(template_key: str) -> RuleSet:
    return ruleset_from_dict(load_template_dict(template_key))


def available_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.json"))
