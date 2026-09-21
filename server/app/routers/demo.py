"""Public "try the triage" endpoint for the marketing site.

Runs the real Paralabel engine on an email a visitor supplies and returns the scores,
the matched rule, and the labels — the same pipeline that labels a live inbox, minus
Gmail. Privacy + cost guardrails:

- **No persistence.** The submitted email is classified in memory and discarded.
- **Per-IP rate limit** and an optional Cloudflare Turnstile check.
- **Daily Jev budget.** Real-Jev classifications are capped per day; over the cap the
  endpoint falls back to the free `demo` backend so a bot can't burn Jev credits.
- Optional shared-secret header so only the site's proxy can call it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ...triage.body import MAX_BODY_CHARS, clean_body
from ...triage.classifier import Classifier
from ...triage.demo import DemoClassifier
from ...triage.factory import get_classifier
from ...triage.loader import load_template
from ...triage.rules import EmailMeta
from ...triage import engine
from ..config import Settings, get_settings
from .. import ratelimit

router = APIRouter(prefix="/api/demo", tags=["demo"])

# The demo rule set is loaded once from the configured template.
_RULESET = None


def _ruleset(settings: Settings):
    global _RULESET
    if _RULESET is None or _RULESET.template_key != settings.demo_template:
        _RULESET = load_template(settings.demo_template)
    return _RULESET


class TriageRequest(BaseModel):
    sender_name: str = Field(default="", max_length=200)
    sender_email: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    turnstile_token: str | None = None


class QuestionOut(BaseModel):
    key: str
    prompt: str
    answer: str
    probabilities: dict[str, float]


class TriageResponse(BaseModel):
    classifier: str
    parent_label: str
    labels: list[str]
    matched_rule: str | None
    questions: list[QuestionOut]


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.headers.get("x-real-ip") or (request.client.host if request.client else "")).strip()


def _verify_turnstile(token: str | None, secret: str, ip: str) -> bool:
    if not secret:
        return True  # not configured -> skip
    if not token:
        return False
    try:
        resp = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": ip}, timeout=8.0,
        )
        return bool(resp.json().get("success"))
    except Exception:  # noqa: BLE001 - treat verification errors as failures
        return False


def _pick_classifier(settings: Settings) -> Classifier:
    """The configured classifier, unless it's a paid backend over its daily budget."""
    chosen = get_classifier(settings)
    if chosen.name in ("jev", "llm"):
        if not ratelimit.budget_take(chosen.name, settings.demo_daily_jev_budget):
            return DemoClassifier()
    return chosen


@router.post("/triage", response_model=TriageResponse)
def triage_demo(
    payload: TriageRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    x_demo_token: str | None = Header(default=None),
) -> TriageResponse:
    if settings.demo_shared_secret and x_demo_token != settings.demo_shared_secret:
        raise HTTPException(403, "forbidden")

    ip = _client_ip(request) or "unknown"
    if not ratelimit.allow(f"demo:{ip}", settings.demo_rate_per_hour):
        raise HTTPException(429, "rate limit exceeded — try again later")

    if not _verify_turnstile(payload.turnstile_token, settings.turnstile_secret, ip):
        raise HTTPException(400, "bot check failed")

    ruleset = _ruleset(settings)
    meta = EmailMeta(
        sender_name=payload.sender_name,
        sender_email=payload.sender_email.lower(),
        subject=payload.subject,
        received_at=datetime.now(timezone.utc),
    )
    body = clean_body(payload.body, MAX_BODY_CHARS)

    classifier = _pick_classifier(settings)
    try:
        decision = engine.triage(ruleset, classifier, meta, body)
    except Exception:  # noqa: BLE001 - a paid backend hiccup falls back to demo
        decision = engine.triage(ruleset, DemoClassifier(), meta, body)

    questions = [
        QuestionOut(
            key=k,
            prompt=ruleset.questions[k].prompt if k in ruleset.questions else k,
            answer=r.answer,
            probabilities=r.probabilities,
        )
        for k, r in decision.result.results.items()
    ]
    return TriageResponse(
        classifier=decision.result.classifier_name,
        parent_label=ruleset.parent_label,
        labels=decision.applied_labels,
        matched_rule=decision.primary_rule_id,
        questions=questions,
    )
