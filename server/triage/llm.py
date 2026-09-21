"""LLMClassifier — fallback that drives any LLM with a strict JSON schema.

Returns the same TriageResult shape as the other classifiers. Provider and model come
from config (no baked-in default — CLASSIFIER=llm requires LLM_PROVIDER + LLM_MODEL).

The schema builder and response parser are pure and unit-tested; the actual network
call is isolated in `_complete()` and filled in fully at Milestone 7. Because true
per-answer probabilities are not available from most chat APIs, we ask the model to
emit a confidence per answer and normalize it — documented as an approximation.
"""

from __future__ import annotations

import json
import time

from .classifier import QuestionResult, TriageInput, TriageResult


class LLMNotConfigured(RuntimeError):
    pass


def build_schema(inp: TriageInput) -> dict:
    """JSON schema constraining the model to answer every question over allowed values."""
    properties = {}
    for q in inp.questions:
        properties[q.key] = {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "enum": list(q.allowed_answers)},
                "confidence": {
                    "type": "object",
                    "properties": {a: {"type": "number"} for a in q.allowed_answers},
                    "required": list(q.allowed_answers),
                    "additionalProperties": False,
                },
            },
            "required": ["answer", "confidence"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": [q.key for q in inp.questions],
        "additionalProperties": False,
    }


def build_prompt(inp: TriageInput) -> str:
    lines = [
        "You are triaging one email for a law firm. Answer each question using ONLY the",
        "allowed values, and give a confidence (0-1) for every allowed value.",
        "",
        f"From: {inp.sender_name} <{inp.sender_email}>",
        f"Subject: {inp.subject}",
        "Body:",
        inp.body_text,
        "",
        "Questions:",
    ]
    for q in inp.questions:
        lines.append(f"- {q.key}: {q.prompt} (allowed: {', '.join(q.allowed_answers)})")
    return "\n".join(lines)


def parse_response(inp: TriageInput, data: dict, latency_ms: float, input_tokens: int) -> TriageResult:
    results: dict[str, QuestionResult] = {}
    for q in inp.questions:
        item = data.get(q.key)
        if not item:
            continue
        conf = item.get("confidence", {})
        raw = {a: max(0.0, float(conf.get(a, 0.0))) for a in q.allowed_answers}
        total = sum(raw.values()) or 1.0
        probs = {a: round(v / total, 4) for a, v in raw.items()}
        answer = item.get("answer") or max(probs, key=probs.get)
        results[q.key] = QuestionResult(
            question_key=q.key,
            answer=answer,
            probabilities=probs,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
        )
    return TriageResult(results=results, classifier_name="llm")


class LLMClassifier:
    name = "llm"

    def __init__(self, provider: str | None, model: str | None, api_key: str | None):
        if not provider or not model:
            raise LLMNotConfigured(
                "CLASSIFIER=llm requires LLM_PROVIDER and LLM_MODEL to be set (no default)."
            )
        self.provider = provider
        self.model = model
        self._api_key = api_key

    def classify(self, inp: TriageInput) -> TriageResult:
        prompt = build_prompt(inp)
        schema = build_schema(inp)
        started = time.perf_counter()
        raw, input_tokens = self._complete(prompt, schema)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return parse_response(inp, json.loads(raw), latency_ms, input_tokens)

    def _complete(self, prompt: str, schema: dict) -> tuple[str, int]:
        """Call the configured LLM and return (raw_json_string, input_tokens).

        TODO(m7): implement per-provider transport (e.g. Anthropic, OpenAI) honoring
        the strict JSON schema. Kept isolated so the rest of the class is testable.
        """
        raise LLMNotConfigured(
            f"LLM transport for provider {self.provider!r} is not implemented yet (M7)."
        )
