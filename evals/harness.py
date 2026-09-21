"""Shared eval machinery: load fixtures, build an oracle, score a classifier.

The oracle is a classifier that simply returns each fixture's expected answers at high
probability. Running the engine with the oracle gives the "correct" lane for each
email without hand-labeling lanes — we then compare the classifier-under-test's lane
against it.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from server.triage.body import clean_body
from server.triage.classifier import Classifier, QuestionResult, TriageInput, TriageResult
from server.triage.engine import triage
from server.triage.loader import load_template
from server.triage.rules import EmailMeta, Rule, RuleSet

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class OracleClassifier:
    """Returns each fixture's expected answers at 0.95; unknown questions near-uniform."""

    name = "oracle"

    def __init__(self, expected: dict[str, str]):
        self._expected = expected

    def classify(self, inp: TriageInput) -> TriageResult:
        results: dict[str, QuestionResult] = {}
        for q in inp.questions:
            want = self._expected.get(q.key)
            if want in q.allowed_answers:
                others = [a for a in q.allowed_answers if a != want]
                rest = 0.05 / len(others) if others else 0.0
                probs = {a: rest for a in others}
                probs[want] = 0.95
                answer = want
            else:
                p = 1.0 / len(q.allowed_answers)
                probs = {a: p for a in q.allowed_answers}
                answer = q.allowed_answers[0]
            results[q.key] = QuestionResult(q.key, answer, probs, 0.0, 0)
        return TriageResult(results=results, classifier_name=self.name)


def _meta(email: dict) -> EmailMeta:
    return EmailMeta(
        sender_name=email.get("sender_name", ""),
        sender_email=email.get("sender_email", ""),
        subject=email.get("subject", ""),
        received_at=datetime.now(timezone.utc),
        has_attachment=email.get("has_attachment", False),
        delivered_to=tuple(email.get("delivered_to", ())),
        is_reply=email.get("is_reply", False),
    )


def _primary_label(ruleset: RuleSet, rule_id: str | None) -> str:
    if rule_id is None:
        return "(none)"
    rule: Rule | None = next((r for r in ruleset.rules if r.id == rule_id), None)
    if rule and rule.actions.add_labels:
        return rule.actions.add_labels[0]
    return "(none)"


@dataclass
class EvalReport:
    template: str
    classifier: str
    total: int = 0
    question_correct: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    question_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    confusion: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    lane_correct: int = 0
    check_manually: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0


def run_eval(classifier: Classifier, template: str, price_per_billion: float = 0.0) -> tuple[EvalReport, float]:
    ruleset = load_template(template)
    fixtures = json.loads((FIXTURES_DIR / f"{template}.json").read_text())
    report = EvalReport(template=template, classifier=getattr(classifier, "name", "?"))

    for email in fixtures["emails"]:
        meta = _meta(email)
        body = clean_body(email.get("body", ""))
        expected = email.get("expected", {})

        decision = triage(ruleset, classifier, meta, body)
        oracle_decision = triage(ruleset, OracleClassifier(expected), meta, body)

        report.total += 1
        report.total_latency_ms += decision.result.total_latency_ms
        report.total_tokens += decision.result.total_input_tokens

        for key, want in expected.items():
            got = decision.result.answer(key)
            if got is None:
                continue
            report.question_total[key] += 1
            if got == want:
                report.question_correct[key] += 1
            if key == "sender_type":
                report.confusion[(want, got)] += 1

        if _primary_label(ruleset, decision.primary_rule_id) == _primary_label(ruleset, oracle_decision.primary_rule_id):
            report.lane_correct += 1
        if decision.primary_rule_id == "low_confidence":
            report.check_manually += 1

    cost = report.total_tokens / 1e9 * price_per_billion
    return report, cost
