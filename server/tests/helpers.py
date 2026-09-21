"""Small builders used across the engine/validation tests."""

from __future__ import annotations

from datetime import datetime, timezone

from server.triage.classifier import (
    AnswerType,
    QuestionResult,
    QuestionSpec,
    TriageInput,
    TriageResult,
)
from server.triage.rules import EmailMeta


class StubClassifier:
    """Returns preset answers. spec: {question_key: (answer, {answer: prob})}."""

    name = "stub"

    def __init__(self, spec: dict[str, tuple[str, dict[str, float]]]):
        self._spec = spec

    def classify(self, inp: TriageInput) -> TriageResult:
        results: dict[str, QuestionResult] = {}
        for q in inp.questions:
            answer, probs = self._spec.get(q.key, (q.allowed_answers[0], {}))
            if not probs:
                probs = {a: (1.0 if a == answer else 0.0) for a in q.allowed_answers}
            results[q.key] = QuestionResult(q.key, answer, probs, 0.1, 10)
        return TriageResult(results=results, classifier_name=self.name)


def meta(sender_email="a@b.example", subject="hi", body="", **kw) -> EmailMeta:
    return EmailMeta(
        sender_name=kw.get("sender_name", "Sender"),
        sender_email=sender_email,
        subject=subject,
        received_at=datetime.now(timezone.utc),
        has_attachment=kw.get("has_attachment", False),
        delivered_to=tuple(kw.get("delivered_to", ())),
        is_reply=kw.get("is_reply", False),
    )


def q(key, answers, answer_type=AnswerType.single_choice, is_system=False) -> QuestionSpec:
    return QuestionSpec(key=key, prompt=key, answer_type=answer_type,
                        allowed_answers=tuple(answers), is_system=is_system)
