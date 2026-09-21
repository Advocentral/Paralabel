"""Static warnings for the rules editor: unreachable rules and unused labels.

These are warnings, not errors — the editor surfaces them but does not block saving.

Unreachable-rule detection is intentionally conservative: we only flag a rule when we
can prove it is fully shadowed by an earlier enabled rule that stops processing. Two
provable cases:
  1. An earlier fallback / condition-less rule with stop_processing on matches
     everything, so nothing after it runs.
  2. An earlier "all"-mode stop_processing rule whose conditions are a subset of this
     rule's ("all"-mode) conditions — whenever this rule would match, the earlier one
     already did and stopped.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import RuleSet


@dataclass
class Warning_:
    code: str
    message: str
    rule_id: str | None = None
    label_name: str | None = None


def _dominates(earlier, later) -> bool:
    if not (earlier.enabled and earlier.stop_processing):
        return False
    if earlier.id == later.id:
        return False
    # Case 1: earlier matches everything.
    if earlier.is_fallback or not earlier.conditions:
        return True
    # Case 2: subset of conditions under "all"/"all".
    if earlier.match_mode == "all" and later.match_mode == "all" and not later.is_fallback:
        return set(earlier.conditions).issubset(set(later.conditions))
    return False


def find_unreachable_rules(ruleset: RuleSet) -> list[Warning_]:
    warnings: list[Warning_] = []
    ordered = ruleset.enabled_rules()
    for i, rule in enumerate(ordered):
        if rule.is_fallback:
            continue
        for earlier in ordered[:i]:
            if _dominates(earlier, rule):
                warnings.append(Warning_(
                    code="unreachable_rule",
                    rule_id=rule.id,
                    message=f"rule {rule.name!r} is unreachable — shadowed by {earlier.name!r} above it",
                ))
                break
    return warnings


def find_unused_labels(ruleset: RuleSet) -> list[Warning_]:
    used: set[str] = set()
    for rule in ruleset.enabled_rules():
        used.update(rule.actions.add_labels)
    warnings: list[Warning_] = []
    for label in ruleset.labels:
        if label.name not in used:
            warnings.append(Warning_(
                code="unused_label",
                label_name=label.name,
                message=f"label {label.name!r} is not used by any enabled rule",
            ))
    return warnings


def analyze(ruleset: RuleSet) -> list[Warning_]:
    return find_unreachable_rules(ruleset) + find_unused_labels(ruleset)
