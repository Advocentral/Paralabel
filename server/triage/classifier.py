"""Classifier protocol and the data shapes that flow through triage.

The classifier is the one place where "judgment" happens. Everything else in the
triage pipeline is deterministic. We keep the interface tiny and provider-agnostic
so that DemoClassifier, JevClassifier, and LLMClassifier are freely swappable
(selected by the CLASSIFIER env var — see factory.py).

Data-minimization note: TriageInput carries only sender name/email, subject, and a
trimmed plain-text body. It deliberately has no attachments, other recipients, or
thread history. See docs/data-flow.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class AnswerType(str, Enum):
    single_choice = "single_choice"
    yes_no = "yes_no"


@dataclass(frozen=True)
class QuestionSpec:
    """A fixed-choice question we ask the classifier about one email."""

    key: str
    prompt: str
    answer_type: AnswerType
    allowed_answers: tuple[str, ...]
    is_system: bool = False

    def __post_init__(self) -> None:
        if not self.allowed_answers:
            raise ValueError(f"question {self.key!r} has no allowed answers")
        if self.answer_type is AnswerType.yes_no and set(self.allowed_answers) != {"yes", "no"}:
            raise ValueError(f"yes_no question {self.key!r} must allow exactly yes/no")


@dataclass(frozen=True)
class TriageInput:
    sender_name: str
    sender_email: str
    subject: str
    body_text: str
    received_at: datetime
    questions: tuple[QuestionSpec, ...]


@dataclass(frozen=True)
class QuestionResult:
    """The classifier's answer to one question, with a probability per allowed answer."""

    question_key: str
    answer: str
    probabilities: dict[str, float]
    latency_ms: float
    input_tokens: int

    def top_probability(self) -> float:
        return self.probabilities.get(self.answer, 0.0)


@dataclass(frozen=True)
class TriageResult:
    """All per-question results for one email, plus roll-ups for storage/costing."""

    results: dict[str, QuestionResult] = field(default_factory=dict)
    classifier_name: str = "unknown"

    @property
    def total_latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results.values())

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.results.values())

    def answer(self, question_key: str) -> str | None:
        r = self.results.get(question_key)
        return r.answer if r else None

    def probability(self, question_key: str, answer: str) -> float | None:
        r = self.results.get(question_key)
        if r is None:
            return None
        return r.probabilities.get(answer, 0.0)


@runtime_checkable
class Classifier(Protocol):
    """Any triage backend. One call answers every requested question for one email."""

    name: str

    def classify(self, inp: TriageInput) -> TriageResult: ...
