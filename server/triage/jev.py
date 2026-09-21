"""JevClassifier — adapter for TypeSafe's Jev (System One) model.

API contract (https://docs.typesafe.ai/api): POST {base_url}/systemone with
`Authorization: Bearer <key>`, body `{state, model, questions}`. Each question is a
typed primitive:

- our `single_choice` questions map to Jev **choice** (returns `choice` + per-option
  `probabilities`);
- our `yes_no` questions map to Jev **noul** (returns `noul` = P(true); we expand it
  to {yes: p, no: 1-p}).

The response's single `usage.input_tokens` covers the whole call, so we split it (and
the call latency) evenly across the questions to keep TriageResult's roll-ups correct.
"""

from __future__ import annotations

import time

import httpx

from .classifier import AnswerType, QuestionResult, QuestionSpec, TriageInput, TriageResult

# Curated criteria for the built-in system questions — better Jev accuracy than bare
# option labels. Custom questions fall back to their answer labels / generic yes-no.
_CHOICE_CRITERIA: dict[str, dict[str, str]] = {
    "sender_type": {
        "prospect": "a potential new client who has not hired the firm yet",
        "client": "an existing client of the firm",
        "court": "a court, clerk, chambers, or court e-filing system such as CM/ECF",
        "opposing_side": "opposing counsel or the opposing party",
        "colleague": "someone inside the firm, staff, or co-counsel",
        "vendor": "a vendor, service provider, or biller",
        "marketing": "marketing, a newsletter, or a promotion",
    },
    "deadline_window": {
        "within_3_days": "a deadline within the next 3 days",
        "days_4_to_14": "a deadline in 4 to 14 days",
        "later": "a deadline more than 14 days away",
        "none": "no deadline is implied",
    },
}
_NOUL_CRITERIA: dict[str, dict[str, str]] = {
    "needs_reply": {"true": "the email needs a reply from someone at the firm", "false": "no reply is needed"},
    "possible_phishing": {"true": "phishing, a scam, or a spoofed/fraudulent message", "false": "a legitimate message"},
    "medical_records": {"true": "about medical records, treatment, or medical providers", "false": "not about medical records"},
}


class JevNotConfigured(RuntimeError):
    pass


def _question_payload(q: QuestionSpec) -> dict:
    if q.answer_type is AnswerType.yes_no:
        criteria = _NOUL_CRITERIA.get(q.key, {"true": q.prompt, "false": "otherwise"})
        return {"type": "noul", "instructions": q.prompt, "criteria": criteria}
    # single_choice -> choice
    overrides = _CHOICE_CRITERIA.get(q.key, {})
    criteria = {a: overrides.get(a, a.replace("_", " ")) for a in q.allowed_answers}
    return {"type": "choice", "instructions": q.prompt, "criteria": criteria}


def build_request(inp: TriageInput, model: str) -> dict:
    """Build the JSON body for POST /systemone."""
    return {
        "model": model,
        "state": {
            "sender_name": inp.sender_name,
            "sender_email": inp.sender_email,
            "subject": inp.subject,
            "body": inp.body_text,
            "received_at": inp.received_at.isoformat(),
        },
        "questions": {q.key: _question_payload(q) for q in inp.questions},
    }


def parse_response(inp: TriageInput, data: dict, latency_ms: float) -> TriageResult:
    """Map Jev's response into a TriageResult."""
    answers = data.get("answers", {})
    total_tokens = int(data.get("usage", {}).get("input_tokens", 0))
    n = max(1, len(inp.questions))
    per_tokens = total_tokens // n
    per_latency = latency_ms / n

    results: dict[str, QuestionResult] = {}
    for q in inp.questions:
        ans = answers.get(q.key)
        if ans is None:
            continue
        if q.answer_type is AnswerType.yes_no:
            p_true = float(ans.get("noul", 0.0))
            probs = {"yes": round(p_true, 4), "no": round(1.0 - p_true, 4)}
            chosen = "yes" if p_true >= 0.5 else "no"
        else:
            raw = ans.get("probabilities", {}) or {}
            probs = {a: round(float(raw.get(a, 0.0)), 4) for a in q.allowed_answers}
            chosen = ans.get("choice") or (max(probs, key=probs.get) if probs else q.allowed_answers[0])
        results[q.key] = QuestionResult(
            question_key=q.key,
            answer=chosen,
            probabilities=probs,
            latency_ms=per_latency,
            input_tokens=per_tokens,
        )
    return TriageResult(results=results, classifier_name="jev")


class JevClassifier:
    name = "jev"

    def __init__(self, api_key: str | None, base_url: str | None, model: str = "jev-latest",
                 client: httpx.Client | None = None):
        self._api_key = api_key
        self._base_url = base_url or "https://api.typesafe.ai/v1"
        self._model = model or "jev-latest"
        self._client = client

    def classify(self, inp: TriageInput) -> TriageResult:
        if not self._api_key:
            raise JevNotConfigured("JEV_API_KEY must be set to use CLASSIFIER=jev.")
        payload = build_request(inp, self._model)
        started = time.perf_counter()
        client = self._client or httpx.Client(timeout=30.0)
        resp = client.post(
            f"{self._base_url.rstrip('/')}/systemone",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return parse_response(inp, resp.json(), latency_ms)
