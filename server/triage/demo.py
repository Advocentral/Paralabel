"""DemoClassifier — deterministic, keyword-based scoring.

The point of the demo classifier is that the whole app runs with no API key: it turns
an email into the same TriageResult shape a real model would, using transparent
keyword heuristics. It handles custom questions too, by scoring each allowed answer
against its own name plus any hint words the question provides.

It is deliberately simple and explainable — not accurate at the level of a real
model. The eval harness measures exactly how far off it is.
"""

from __future__ import annotations

import time

from .classifier import QuestionResult, QuestionSpec, TriageInput, TriageResult

# Keyword weights for the built-in system questions. Each maps an answer to the terms
# that push toward it. Weights are additive; results are smoothed and normalized.
_SENDER_TYPE = {
    "court": ["uscourts.gov", "cm/ecf", "ecf", "notice of electronic filing", "clerk",
              "deputy clerk", "chambers", "docket", "case no", "civil action",
              "courtroom", "magistrate", "honorable"],
    "opposing_side": ["opposing counsel", "counsel for", "we represent", "on behalf of our client",
                      "meet and confer", "defendant", "plaintiff's counsel", "settlement demand",
                      "discovery request", "notice of deposition"],
    "prospect": ["free consultation", "need a lawyer", "looking for representation", "referred to you",
                 "potential case", "found you", "new client inquiry", "can you help", "quote"],
    "client": ["my case", "our case", "update on my", "thank you for representing", "my matter",
               "retainer", "status of my", "hi again"],
    "colleague": ["co-counsel", "associate", "paralegal", "our office", "internal", "staff meeting",
                  "team", "of counsel"],
    "vendor": ["invoice", "subscription", "renewal", "westlaw", "lexis", "court reporter",
               "filing service", "payment due", "account statement", "billing"],
    "marketing": ["newsletter", "unsubscribe", "webinar", "cle credit", "special offer", "% off",
                  "sale", "promotion", "download our", "free ebook", "limited time"],
}

_DEADLINE = {
    "within_3_days": ["today", "tomorrow", "by end of day", "eod", "within 24 hours", "within 48 hours",
                      "response due", "due tomorrow", "hearing tomorrow", "24 hours", "48 hours",
                      "immediately", "urgent", "asap"],
    "days_4_to_14": ["next week", "within two weeks", "by the 15th", "10 days", "ten days",
                     "due next", "in a week", "two weeks"],
    "later": ["next month", "in 30 days", "end of quarter", "later this year", "no rush", "in 30"],
    "none": [],
}

_NEEDS_REPLY = {
    "yes": ["please respond", "let me know", "can you", "could you", "confirm", "please reply",
            "awaiting your", "your response", "?", "get back to me", "advise"],
    "no": ["no action needed", "for your records", "fyi", "do not reply", "no reply",
           "newsletter", "receipt", "confirmation only"],
}

_PHISHING = {
    "yes": ["verify your account", "click here to sign", "your password", "unusual activity",
            "gift card", "wire transfer", "update your payment", "confirm your identity",
            "account suspended", "e-signature required", "secure document waiting", "reset your password",
            "validate your", "bit.ly", "tinyurl"],
    "no": [],
}

_SYSTEM_SCORERS = {
    "sender_type": _SENDER_TYPE,
    "deadline_window": _DEADLINE,
    "needs_reply": _NEEDS_REPLY,
    "possible_phishing": _PHISHING,
}

# Prior weight for the "default" answer of some questions — most mail is not phishing,
# has no deadline, etc. Keyword hits must clear this baseline to flip the answer.
_PRIORS = {
    "possible_phishing": {"no": 1.2},
    "deadline_window": {"none": 0.8},
    "needs_reply": {"no": 0.5},
}

_SMOOTHING = 0.15


def _count(text: str, terms: list[str]) -> float:
    return sum(text.count(t) for t in terms)


def _hint_terms(answer: str) -> list[str]:
    """Derive search terms from an answer value (for custom questions)."""
    words = answer.replace("_", " ").lower().split()
    return [answer.lower(), answer.replace("_", " ").lower(), *words]


class DemoClassifier:
    name = "demo"

    def classify(self, inp: TriageInput) -> TriageResult:
        text = f"{inp.subject}\n{inp.body_text}".lower()
        sender_blob = f"{inp.sender_email}\n{inp.sender_name}".lower()
        haystack = f"{text}\n{sender_blob}"
        input_tokens = max(1, len(haystack) // 4)

        results: dict[str, QuestionResult] = {}
        for q in inp.questions:
            started = time.perf_counter()
            probs = self._score(q, haystack)
            answer = max(probs, key=probs.get)
            latency_ms = (time.perf_counter() - started) * 1000.0
            results[q.key] = QuestionResult(
                question_key=q.key,
                answer=answer,
                probabilities=probs,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
            )
        return TriageResult(results=results, classifier_name=self.name)

    def _score(self, q: QuestionSpec, haystack: str) -> dict[str, float]:
        scorer = _SYSTEM_SCORERS.get(q.key)
        priors = _PRIORS.get(q.key, {})
        raw: dict[str, float] = {}
        for ans in q.allowed_answers:
            if scorer is not None:
                score = _count(haystack, scorer.get(ans, []))
            else:
                score = _count(haystack, _hint_terms(ans))
            raw[ans] = score + priors.get(ans, 0.0)
        return _normalize(raw, q.allowed_answers)


def _normalize(raw: dict[str, float], answers: tuple[str, ...]) -> dict[str, float]:
    smoothed = {a: raw.get(a, 0.0) + _SMOOTHING for a in answers}
    total = sum(smoothed.values())
    return {a: round(v / total, 4) for a, v in smoothed.items()}
