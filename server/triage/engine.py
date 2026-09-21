"""The triage engine: classify once, then walk the rules.

Flow (per the brief):
1. Ask the classifier only the questions referenced by an enabled rule, plus enabled
   system questions — all in a single call.
2. Evaluate enabled rules top to bottom. The first matching rule is the "primary"
   lane and applies its actions. Processing stops there unless stop_processing is
   False, in which case later matching rules add more labels/flags.
3. The fallback rule is always last and always matches, so every email gets >=1 label.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .classifier import Classifier, TriageInput, TriageResult
from .rules import EmailMeta, EvalContext, RuleSet


@dataclass
class TriageDecision:
    primary_rule_id: str | None
    matched_rule_ids: list[str]
    applied_labels: list[str]
    mark_important: bool = False
    star: bool = False
    archive: bool = False
    mark_read: bool = False
    result: TriageResult = field(default_factory=TriageResult)


def build_input(ruleset: RuleSet, meta: EmailMeta, body_text: str) -> TriageInput:
    return TriageInput(
        sender_name=meta.sender_name,
        sender_email=meta.sender_email,
        subject=meta.subject,
        body_text=body_text,
        received_at=meta.received_at,
        questions=tuple(ruleset.questions_to_ask()),
    )


def evaluate(ruleset: RuleSet, ctx: EvalContext) -> TriageDecision:
    """Walk enabled rules against an already-computed classifier result."""
    decision = TriageDecision(
        primary_rule_id=None,
        matched_rule_ids=[],
        applied_labels=[],
        result=ctx.result,
    )
    for rule in ruleset.enabled_rules():
        if not rule.matches(ctx):
            continue
        decision.matched_rule_ids.append(rule.id)
        _merge_actions(decision, rule)
        if rule.stop_processing:
            # The rule that stops processing is the email's "lane". Non-stopping
            # rules (e.g. the Due date tags) only decorate it.
            decision.primary_rule_id = rule.id
            break
    # No stopping rule matched (only possible if a fallback is missing/misconfigured):
    # fall back to the first matched rule so primary is never silently null.
    if decision.primary_rule_id is None and decision.matched_rule_ids:
        decision.primary_rule_id = decision.matched_rule_ids[0]
    return decision


def triage(
    ruleset: RuleSet,
    classifier: Classifier,
    meta: EmailMeta,
    body_text: str,
) -> TriageDecision:
    """End-to-end: classify one email, then decide labels/actions."""
    inp = build_input(ruleset, meta, body_text)
    result = classifier.classify(inp)
    ctx = EvalContext(meta=meta, result=result, lists=ruleset.lists)
    return evaluate(ruleset, ctx)


def _merge_actions(decision: TriageDecision, rule) -> None:
    a = rule.actions
    for label in a.add_labels:
        if label not in decision.applied_labels:
            decision.applied_labels.append(label)
    decision.mark_important = decision.mark_important or a.mark_important
    decision.star = decision.star or a.star
    decision.archive = decision.archive or a.archive
    decision.mark_read = decision.mark_read or a.mark_read
