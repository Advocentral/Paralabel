"""Engine behavior: ordering, stop_processing, fallback, non-stopping decoration."""

from __future__ import annotations

from server.triage.classifier import QuestionSpec
from server.triage.engine import evaluate, triage
from server.triage.loader import load_template
from server.triage.rules import (
    ClassifierCondition,
    EvalContext,
    Rule,
    RuleActions,
    RuleSet,
)

from .helpers import StubClassifier, meta, q


def _ruleset(rules, questions=None, enabled=None) -> RuleSet:
    questions = questions or {}
    return RuleSet(
        template_key="t",
        parent_label="Paralabel/",
        questions=questions,
        enabled_question_keys=set(enabled or questions.keys()),
        rules=tuple(rules),
    )


def _ctx(result) -> EvalContext:
    return EvalContext(meta=meta(), result=result)


def test_first_matching_stop_rule_wins():
    qs = {"k": q("k", ["a", "b"])}
    rs = _ruleset([
        Rule("r1", "r1", (ClassifierCondition("k", answers=("a",)),), RuleActions(("A",)), position=1),
        Rule("r2", "r2", (ClassifierCondition("k", answers=("a",)),), RuleActions(("B",)), position=2),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ], qs)
    clf = StubClassifier({"k": ("a", {"a": 1.0, "b": 0.0})})
    d = triage(rs, clf, meta(), "")
    assert d.primary_rule_id == "r1"
    assert d.applied_labels == ["A"]


def test_stop_processing_false_lets_later_rules_add_labels():
    qs = {"due": q("due", ["soon", "no"]), "k": q("k", ["a", "b"])}
    rs = _ruleset([
        Rule("tag", "tag", (ClassifierCondition("due", answers=("soon",)),), RuleActions(("Due",)),
             position=1, stop_processing=False),
        Rule("lane", "lane", (ClassifierCondition("k", answers=("a",)),), RuleActions(("Lane",)), position=2),
        Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True),
    ], qs)
    clf = StubClassifier({"due": ("soon", {"soon": 1.0, "no": 0.0}), "k": ("a", {"a": 1.0, "b": 0.0})})
    d = triage(rs, clf, meta(), "")
    assert d.applied_labels == ["Due", "Lane"]
    # The stopping "lane" rule is the primary, not the decoration tag.
    assert d.primary_rule_id == "lane"
    assert d.matched_rule_ids == ["tag", "lane"]


def test_fallback_guarantees_a_label():
    qs = {"k": q("k", ["a", "b"])}
    rs = _ruleset([
        Rule("r1", "r1", (ClassifierCondition("k", answers=("a",)),), RuleActions(("A",)), position=1),
        Rule("fb", "Everything else", (), RuleActions(("Newsletters",)), position=99, is_fallback=True),
    ], qs)
    clf = StubClassifier({"k": ("b", {"a": 0.0, "b": 1.0})})
    d = triage(rs, clf, meta(), "")
    assert d.primary_rule_id == "fb"
    assert d.applied_labels == ["Newsletters"]


def test_any_match_mode():
    qs = {"k": q("k", ["a", "b", "c"])}
    rule = Rule("r", "r", (
        ClassifierCondition("k", answers=("a",)),
        ClassifierCondition("k", answers=("b",)),
    ), RuleActions(("X",)), match_mode="any", position=1)
    rs = _ruleset([rule, Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True)], qs)
    clf = StubClassifier({"k": ("b", {"a": 0.0, "b": 1.0, "c": 0.0})})
    d = triage(rs, clf, meta(), "")
    assert d.primary_rule_id == "r"


def test_probability_threshold_gate():
    qs = {"k": q("k", ["yes", "no"])}
    rule = Rule("r", "r", (ClassifierCondition("k", answers=("yes",), prob_op="gte", threshold=0.6),),
                RuleActions(("Held",)), position=1)
    rs = _ruleset([rule, Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True)], qs)
    # Below threshold -> no match, falls through to fallback.
    low = StubClassifier({"k": ("yes", {"yes": 0.4, "no": 0.6})})
    assert triage(rs, low, meta(), "").primary_rule_id == "fb"
    # At/above threshold -> matches.
    high = StubClassifier({"k": ("yes", {"yes": 0.8, "no": 0.2})})
    assert triage(rs, high, meta(), "").primary_rule_id == "r"


def test_negated_condition():
    qs = {"st": q("st", ["marketing", "vendor", "client"])}
    rule = Rule("r", "r", (ClassifierCondition("st", answers=("marketing", "vendor"), negate=True),),
                RuleActions(("NotMkt",)), position=1)
    rs = _ruleset([rule, Rule("fb", "fb", (), RuleActions(("Z",)), position=99, is_fallback=True)], qs)
    assert triage(rs, StubClassifier({"st": ("client", {"client": 1.0})}), meta(), "").primary_rule_id == "r"
    assert triage(rs, StubClassifier({"st": ("vendor", {"vendor": 1.0})}), meta(), "").primary_rule_id == "fb"


def test_general_template_questions_to_ask_are_enabled_only():
    rs = load_template("general")
    keys = {qq.key for qq in rs.questions_to_ask()}
    # All four system questions are asked; nothing disabled leaks in.
    assert keys == {"sender_type", "deadline_window", "needs_reply", "possible_phishing"}
    assert all(isinstance(qq, QuestionSpec) for qq in rs.questions_to_ask())


def test_general_template_court_lane_with_due_tag():
    rs = load_template("general")
    clf = StubClassifier({
        "possible_phishing": ("no", {"yes": 0.01, "no": 0.99}),
        "sender_type": ("court", {"court": 0.95, "prospect": 0.05}),
        "deadline_window": ("within_3_days", {"within_3_days": 0.9, "none": 0.1}),
        "needs_reply": ("no", {"yes": 0.2, "no": 0.8}),
    })
    d = triage(rs, clf, meta(), "")
    assert d.primary_rule_id == "court"
    assert "Deadlines & court" in d.applied_labels
    assert "Due ≤3 days" in d.applied_labels  # non-stopping tag also applied
