from __future__ import annotations

from server.triage.reachability import analyze, find_unreachable_rules, find_unused_labels
from server.triage.rules import (
    ClassifierCondition,
    LabelSpec,
    Rule,
    RuleActions,
    RuleSet,
)

from .helpers import q


def _rs(rules, labels=()) -> RuleSet:
    qs = {"k": q("k", ["a", "b"])}
    return RuleSet("t", "Paralabel/", qs, {"k"}, tuple(rules), tuple(labels))


def test_rule_after_fallback_is_unreachable():
    rules = [
        Rule("fb", "fb", (), RuleActions(("Z",)), position=1, is_fallback=True),
        Rule("r", "r", (ClassifierCondition("k", answers=("a",)),), RuleActions(("A",)), position=2),
    ]
    warnings = find_unreachable_rules(_rs(rules))
    assert any(w.rule_id == "r" for w in warnings)


def test_subset_conditions_shadow_later_rule():
    cond_a = ClassifierCondition("k", answers=("a",))
    cond_b = ClassifierCondition("k", answers=("b",), mode="top_prob", prob_op="lt", threshold=0.5)
    rules = [
        Rule("broad", "broad", (cond_a,), RuleActions(("A",)), position=1, stop_processing=True),
        Rule("narrow", "narrow", (cond_a, cond_b), RuleActions(("B",)), position=2),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    warnings = find_unreachable_rules(_rs(rules))
    assert any(w.rule_id == "narrow" for w in warnings)


def test_non_stopping_rule_does_not_shadow():
    cond_a = ClassifierCondition("k", answers=("a",))
    rules = [
        Rule("tag", "tag", (cond_a,), RuleActions(("A",)), position=1, stop_processing=False),
        Rule("later", "later", (cond_a,), RuleActions(("B",)), position=2),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    warnings = find_unreachable_rules(_rs(rules))
    assert not any(w.rule_id == "later" for w in warnings)


def test_unused_labels_flagged():
    rules = [
        Rule("r", "r", (ClassifierCondition("k", answers=("a",)),), RuleActions(("Used",)), position=1),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ]
    warnings = find_unused_labels(_rs(rules, labels=[LabelSpec("Used"), LabelSpec("Z"), LabelSpec("Lonely")]))
    assert {w.label_name for w in warnings} == {"Lonely"}


def test_analyze_combines():
    rules = [Rule("fb", "fb", (), RuleActions(("Z",)), position=1, is_fallback=True)]
    assert isinstance(analyze(_rs(rules, labels=[LabelSpec("Z")])), list)
