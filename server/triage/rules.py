"""Domain model for the rules engine.

These are plain, immutable dataclasses — deliberately decoupled from the ORM
(server/app/models.py) so the engine can be unit-tested with no database. Templates
(triage/templates/*.json) load straight into a RuleSet, and the ORM maps to/from
these same shapes.

A rule has conditions (ALL or ANY must match), a set of actions, and a
stop_processing flag. Conditions come in three kinds — classifier, metadata, list —
each with an evaluate() that reads an EvalContext.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .classifier import AnswerType, QuestionSpec, TriageResult

# --- comparison operators for probability thresholds ------------------------------

_PROB_OPS = {
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
}


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


# --- evaluation context -----------------------------------------------------------


@dataclass(frozen=True)
class EmailMeta:
    """Deterministic facts about an email — everything a metadata condition needs."""

    sender_name: str
    sender_email: str
    subject: str
    received_at: datetime
    has_attachment: bool = False
    delivered_to: tuple[str, ...] = ()
    is_reply: bool = False

    @property
    def sender_domain(self) -> str:
        return domain_of(self.sender_email)


@dataclass(frozen=True)
class EvalContext:
    meta: EmailMeta
    result: TriageResult
    lists: dict[str, frozenset[str]] = field(default_factory=dict)


# --- conditions -------------------------------------------------------------------


class Condition(Protocol):
    def evaluate(self, ctx: EvalContext) -> bool: ...

    def question_keys(self) -> set[str]: ...

    def list_names(self) -> set[str]: ...


@dataclass(frozen=True)
class ClassifierCondition:
    """Reads a classifier answer/probability.

    mode="is":       chosen answer is one of `answers` AND its probability `prob_op`
                     `threshold` (threshold defaults to 0.0 → a plain answer check).
    mode="top_prob": the chosen answer's probability `prob_op` `threshold`,
                     regardless of which answer it is (e.g. "top prob < 0.7").
    """

    question_key: str
    mode: str = "is"  # "is" | "top_prob"
    answers: tuple[str, ...] = ()
    prob_op: str = "gte"
    threshold: float = 0.0
    negate: bool = False

    def evaluate(self, ctx: EvalContext) -> bool:
        return self._evaluate(ctx) != self.negate

    def _evaluate(self, ctx: EvalContext) -> bool:
        r = ctx.result.results.get(self.question_key)
        if r is None:
            return False
        op = _PROB_OPS[self.prob_op]
        if self.mode == "top_prob":
            return op(r.top_probability(), self.threshold)
        # mode == "is"
        if r.answer not in self.answers:
            return False
        return op(r.top_probability(), self.threshold)

    def question_keys(self) -> set[str]:
        return {self.question_key}

    def list_names(self) -> set[str]:
        return set()


@dataclass(frozen=True)
class MetadataCondition:
    """Deterministic match against email metadata — no classifier needed.

    field: sender_email | sender_domain | subject | has_attachment | delivered_to | is_reply
    op:    equals | in | matches | contains | is_true
    """

    field: str
    op: str
    values: tuple[str, ...] = ()
    negate: bool = False

    def evaluate(self, ctx: EvalContext) -> bool:
        return self._evaluate(ctx) != self.negate

    def _evaluate(self, ctx: EvalContext) -> bool:
        m = ctx.meta
        if self.field == "has_attachment":
            return m.has_attachment
        if self.field == "is_reply":
            return m.is_reply

        if self.field == "sender_email":
            hay = m.sender_email.lower()
        elif self.field == "sender_domain":
            hay = m.sender_domain
        elif self.field == "subject":
            hay = m.subject.lower()
        elif self.field == "delivered_to":
            addrs = {a.lower() for a in m.delivered_to}
            vals = {v.lower() for v in self.values}
            return bool(addrs & vals)
        else:
            return False

        vals = [v.lower() for v in self.values]
        if self.op == "equals":
            return hay in vals
        if self.op == "in":
            return hay in vals
        if self.op == "contains":
            return any(v in hay for v in vals)
        if self.op == "matches":
            return any(_matches(hay, v) for v in vals)
        return False

    def question_keys(self) -> set[str]:
        return set()

    def list_names(self) -> set[str]:
        return set()


def _matches(value: str, pattern: str) -> bool:
    # Support glob-style (*.uscourts.gov) and, if it looks like a regex, regex.
    if any(c in pattern for c in "^$[]()|+"):
        try:
            return re.search(pattern, value) is not None
        except re.error:
            return False
    return fnmatch.fnmatch(value, pattern)


@dataclass(frozen=True)
class ListCondition:
    """Membership of a sender field in a tenant-managed list (e.g. 'Court domains')."""

    field: str  # sender_email | sender_domain
    list_name: str

    def evaluate(self, ctx: EvalContext) -> bool:
        members = ctx.lists.get(self.list_name, frozenset())
        if self.field == "sender_domain":
            return ctx.meta.sender_domain in members
        return ctx.meta.sender_email.lower() in members

    def question_keys(self) -> set[str]:
        return set()

    def list_names(self) -> set[str]:
        return {self.list_name}


# --- actions ----------------------------------------------------------------------


@dataclass(frozen=True)
class RuleActions:
    add_labels: tuple[str, ...] = ()
    mark_important: bool = False
    star: bool = False
    archive: bool = False
    mark_read: bool = False

    def touches_inbox_visibility(self) -> bool:
        """True if the action would hide the message (archive) or dim it (mark read)."""
        return self.archive or self.mark_read


# --- rules ------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    conditions: tuple[Condition, ...]
    actions: RuleActions
    match_mode: str = "all"  # "all" | "any"
    enabled: bool = True
    position: int = 0
    stop_processing: bool = True
    is_fallback: bool = False
    is_system_protected: bool = False  # phishing rule: can edit, cannot delete/disable

    def matches(self, ctx: EvalContext) -> bool:
        if self.is_fallback:
            return True
        if not self.conditions:
            return False
        checks = (c.evaluate(ctx) for c in self.conditions)
        return all(checks) if self.match_mode == "all" else any(checks)

    def question_keys(self) -> set[str]:
        keys: set[str] = set()
        for c in self.conditions:
            keys |= c.question_keys()
        return keys

    def list_names(self) -> set[str]:
        names: set[str] = set()
        for c in self.conditions:
            names |= c.list_names()
        return names


@dataclass(frozen=True)
class LabelSpec:
    name: str
    color: str = ""
    description: str = ""
    is_system: bool = False
    sort_order: int = 0


@dataclass
class RuleSet:
    template_key: str
    parent_label: str
    questions: dict[str, QuestionSpec]
    enabled_question_keys: set[str]
    rules: tuple[Rule, ...]
    labels: tuple[LabelSpec, ...] = ()
    lists: dict[str, frozenset[str]] = field(default_factory=dict)

    def enabled_rules(self) -> list[Rule]:
        return sorted((r for r in self.rules if r.enabled), key=lambda r: r.position)

    def system_question_keys(self) -> set[str]:
        return {k for k, q in self.questions.items() if q.is_system and k in self.enabled_question_keys}

    def referenced_question_keys(self) -> set[str]:
        """Questions we must ask the classifier: those used by an enabled rule, plus
        all enabled system questions. Only enabled questions count."""
        keys = set(self.system_question_keys())
        for r in self.enabled_rules():
            keys |= r.question_keys()
        return {k for k in keys if k in self.enabled_question_keys}

    def questions_to_ask(self) -> list[QuestionSpec]:
        return [self.questions[k] for k in sorted(self.referenced_question_keys()) if k in self.questions]

    def label_names(self) -> set[str]:
        return {label.name for label in self.labels}
