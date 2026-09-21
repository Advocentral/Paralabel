"""JevClassifier — adapter for TypeSafe's Jev (System One) model.

STATUS: stub. The real HTTP request/response shape is filled in at Milestone 7 once
the TypeSafe API docs + key are supplied. Everything the app needs around Jev already
exists here; only the two clearly-marked functions below change.

Design: build_request() and parse_response() are pure and unit-tested against a
recorded fixture (server/tests/fixtures/jev_response.json), so the contract is pinned
before we ever hit the network. classify() just does the transport.
"""

from __future__ import annotations

import time

import httpx

from .classifier import QuestionResult, TriageInput, TriageResult


class JevNotConfigured(RuntimeError):
    pass


def build_request(inp: TriageInput) -> dict:
    """Build the JSON payload sent to Jev.

    TODO(jev-docs): replace this body with the exact shape from TypeSafe's API docs.
    Until then it is a best-guess placeholder used only by the contract test's request
    assertions, NOT sent to a real endpoint.
    """
    return {
        "input": {
            "sender_name": inp.sender_name,
            "sender_email": inp.sender_email,
            "subject": inp.subject,
            "body": inp.body_text,
            "received_at": inp.received_at.isoformat(),
        },
        "questions": [
            {
                "key": q.key,
                "prompt": q.prompt,
                "type": q.answer_type.value,
                "answers": list(q.allowed_answers),
            }
            for q in inp.questions
        ],
    }


def parse_response(inp: TriageInput, data: dict, latency_ms: float) -> TriageResult:
    """Map Jev's JSON response into a TriageResult.

    TODO(jev-docs): align the field names below with the real response schema. The
    contract test (test_jev_contract.py) drives this with a recorded fixture; update
    the fixture and these accessors together.
    """
    per_q = {item["key"]: item for item in data.get("answers", [])}
    tokens = int(data.get("input_tokens", 0))
    results: dict[str, QuestionResult] = {}
    for q in inp.questions:
        item = per_q.get(q.key)
        if item is None:
            continue
        probs = {a: float(item["probabilities"].get(a, 0.0)) for a in q.allowed_answers}
        results[q.key] = QuestionResult(
            question_key=q.key,
            answer=item.get("answer") or max(probs, key=probs.get),
            probabilities=probs,
            latency_ms=latency_ms,
            input_tokens=tokens,
        )
    return TriageResult(results=results, classifier_name="jev")


class JevClassifier:
    name = "jev"

    def __init__(self, api_key: str | None, base_url: str | None, client: httpx.Client | None = None):
        self._api_key = api_key
        self._base_url = base_url
        self._client = client

    def classify(self, inp: TriageInput) -> TriageResult:
        if not self._api_key or not self._base_url:
            raise JevNotConfigured(
                "JEV_API_KEY and JEV_BASE_URL must be set to use CLASSIFIER=jev. "
                "The Jev adapter is a stub until TypeSafe's docs are wired in (M7)."
            )
        payload = build_request(inp)
        started = time.perf_counter()
        client = self._client or httpx.Client(timeout=30.0)
        # TODO(jev-docs): confirm endpoint path + auth header scheme from the docs.
        resp = client.post(
            f"{self._base_url.rstrip('/')}/classify",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return parse_response(inp, resp.json(), latency_ms)
