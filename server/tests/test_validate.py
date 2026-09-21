from __future__ import annotations

from server.triage.loader import load_template
from server.triage.rules import (
    ClassifierCondition,
    LabelSpec,
    Rule,
    RuleActions,
    RuleSet,
)
from server.triage.validate import validate_ruleset

from .helpers import q


def _rs(rules, questions, labels=(), enabled=None) -> RuleSet:
    return RuleSet(
        template_key="t",
        parent_label="Paralabel/",
        questions=questions,
        enabled_question_keys=set(questions.keys()) if enabled is None else set(enabled),
        rules=tuple(rules),
        labels=tuple(labels),
    )


def _codes(issues):
    return {i.code for i in issues}


def test_all_templates_validate_clean():
    for key in ("general", "bankruptcy", "personal_injury", "family_law"):
        issues = validate_ruleset(load_template(key))
        assert issues == [], f"{key}: {[i.message for i in issues]}"


def test_guardrail_blocks_archive_on_phishing_rule():
    qs = {"possible_phishing": q("possible_phishing", ["yes", "no"])}
    rules = [
        Rule("p", "phishing", (ClassifierCondition("possible_phishing", answers=("yes",)),),
             RuleActions(("Held",), archive=True), position=1, is_system_protected=True),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    issues = validate_ruleset(_rs(rules, qs, labels=[LabelSpec("Held"), LabelSpec("Z")]))
    assert "guardrail_hide_protected" in _codes(issues)


def test_guardrail_blocks_mark_read_on_deadline_rule():
    qs = {"deadline_window": q("deadline_window", ["within_3_days", "none"])}
    rules = [
        Rule("d", "deadline", (ClassifierCondition("deadline_window", answers=("within_3_days",)),),
             RuleActions(("Deadlines",), mark_read=True), position=1),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    issues = validate_ruleset(_rs(rules, qs, labels=[LabelSpec("Deadlines"), LabelSpec("Z")]))
    assert "guardrail_hide_protected" in _codes(issues)


def test_rejects_reference_to_disabled_question():
    qs = {"k": q("k", ["a", "b"])}
    rules = [
        Rule("r", "r", (ClassifierCondition("k", answers=("a",)),), RuleActions(("A",)), position=1),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    issues = validate_ruleset(_rs(rules, qs, labels=[LabelSpec("A"), LabelSpec("Z")], enabled=set()))
    assert "disabled_question" in _codes(issues)


def test_rejects_bad_answer_value():
    qs = {"k": q("k", ["a", "b"])}
    rules = [
        Rule("r", "r", (ClassifierCondition("k", answers=("zzz",)),), RuleActions(("A",)), position=1),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    issues = validate_ruleset(_rs(rules, qs, labels=[LabelSpec("A"), LabelSpec("Z")]))
    assert "bad_answer" in _codes(issues)


def test_fallback_must_be_last_and_present():
    qs = {"k": q("k", ["a", "b"])}
    # Fallback in the middle.
    rules = [
        Rule("fb", "fb", (), RuleActions(("Z",)), position=1, is_fallback=True),
        Rule("r", "r", (ClassifierCondition("k", answers=("a",)),), RuleActions(("A",)), position=2),
    ]
    issues = validate_ruleset(_rs(rules, qs, labels=[LabelSpec("A"), LabelSpec("Z")]))
    assert "fallback_not_last" in _codes(issues)

    # No fallback at all.
    rules2 = [Rule("r", "r", (ClassifierCondition("k", answers=("a",)),), RuleActions(("A",)), position=1)]
    issues2 = validate_ruleset(_rs(rules2, qs, labels=[LabelSpec("A")]))
    assert "fallback_count" in _codes(issues2)


def test_unknown_label_rejected():
    qs = {"k": q("k", ["a", "b"])}
    rules = [
        Rule("r", "r", (ClassifierCondition("k", answers=("a",)),), RuleActions(("Missing",)), position=1),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    issues = validate_ruleset(_rs(rules, qs, labels=[LabelSpec("Z")]))
    assert "unknown_label" in _codes(issues)
