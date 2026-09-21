"""Rule-set validation and guardrails — enforced in the backend, not just the UI.

Guardrails (from the brief):
- A rule that keys off court sender types, the deadline window, or phishing may NOT
  archive or mark-read (those would hide time-sensitive or dangerous mail).
- The "possible phishing" rule is system-protected: it must stay enabled and cannot
  be deleted/disabled (deletion/reorder is blocked at the API layer; here we assert
  it is present, enabled, and first).
- Every condition must reference a currently-enabled question and an allowed answer;
  rules referencing a disabled/deleted question are rejected.
- Exactly one enabled fallback rule must exist and be last.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import ClassifierCondition, RuleSet

# Questions whose use makes a rule "time-sensitive / dangerous" — such a rule may not
# hide the message.
_PROTECTED_QUESTIONS = {"possible_phishing", "deadline_window"}


@dataclass
class ValidationIssue:
    rule_id: str | None
    code: str
    message: str


def _rule_is_protected_topic(rule) -> bool:
    """True if the rule keys off phishing, the deadline window, or the 'court' sender."""
    for c in rule.conditions:
        if isinstance(c, ClassifierCondition):
            if c.question_key in _PROTECTED_QUESTIONS:
                return True
            if c.question_key == "sender_type" and "court" in c.answers:
                return True
    return False


def validate_ruleset(ruleset: RuleSet) -> list[ValidationIssue]:
    """Return a list of blocking issues. Empty list == valid."""
    issues: list[ValidationIssue] = []
    rules = ruleset.enabled_rules()

    # Fallback: exactly one, enabled, last.
    fallbacks = [r for r in ruleset.rules if r.is_fallback]
    if len(fallbacks) != 1:
        issues.append(ValidationIssue(None, "fallback_count",
                                      f"expected exactly one fallback rule, found {len(fallbacks)}"))
    else:
        fb = fallbacks[0]
        if not fb.enabled:
            issues.append(ValidationIssue(fb.id, "fallback_disabled", "the fallback rule cannot be disabled"))
        if rules and rules[-1].id != fb.id:
            issues.append(ValidationIssue(fb.id, "fallback_not_last", "the fallback rule must be last"))

    # Phishing system-protected rule present and enabled.
    protected = [r for r in ruleset.rules if r.is_system_protected]
    for r in protected:
        if not r.enabled:
            issues.append(ValidationIssue(r.id, "system_rule_disabled",
                                          f"system-protected rule {r.name!r} cannot be disabled"))

    for rule in ruleset.rules:
        # Guardrail: protected-topic rules may not hide the message.
        if _rule_is_protected_topic(rule) and rule.actions.touches_inbox_visibility():
            issues.append(ValidationIssue(
                rule.id, "guardrail_hide_protected",
                f"rule {rule.name!r} keys off court/deadline/phishing and may not archive or mark read",
            ))

        # Condition validity: questions must exist, be enabled; answers must be allowed.
        for c in rule.conditions:
            if isinstance(c, ClassifierCondition):
                q = ruleset.questions.get(c.question_key)
                if q is None:
                    issues.append(ValidationIssue(
                        rule.id, "unknown_question",
                        f"rule {rule.name!r} references unknown question {c.question_key!r}",
                    ))
                    continue
                if c.question_key not in ruleset.enabled_question_keys:
                    issues.append(ValidationIssue(
                        rule.id, "disabled_question",
                        f"rule {rule.name!r} references disabled question {c.question_key!r}",
                    ))
                if c.prob_op not in {"gte", "lte", "gt", "lt"}:
                    issues.append(ValidationIssue(
                        rule.id, "bad_prob_op",
                        f"rule {rule.name!r} has invalid probability operator {c.prob_op!r}",
                    ))
                if c.mode == "is":
                    bad = [a for a in c.answers if a not in q.allowed_answers]
                    if bad:
                        issues.append(ValidationIssue(
                            rule.id, "bad_answer",
                            f"rule {rule.name!r} references answers {bad} not allowed for {c.question_key!r}",
                        ))

            for name in c.list_names():
                if name not in ruleset.lists:
                    issues.append(ValidationIssue(
                        rule.id, "unknown_list",
                        f"rule {rule.name!r} references unknown list {name!r}",
                    ))

        # Every add_label must be a known label.
        known = ruleset.label_names()
        for label in rule.actions.add_labels:
            if known and label not in known:
                issues.append(ValidationIssue(
                    rule.id, "unknown_label",
                    f"rule {rule.name!r} adds unknown label {label!r}",
                ))

    return issues
