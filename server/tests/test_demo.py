from __future__ import annotations

from datetime import datetime, timezone

from server.triage.classifier import AnswerType, TriageInput
from server.triage.demo import DemoClassifier

from .helpers import q


def _inp(subject, body, sender_email="x@y.example", questions=None):
    return TriageInput(
        sender_name="S", sender_email=sender_email, subject=subject, body_text=body,
        received_at=datetime.now(timezone.utc),
        questions=tuple(questions or []),
    )


def test_probabilities_cover_all_answers_and_sum_to_one():
    clf = DemoClassifier()
    st = q("sender_type", ["prospect", "client", "court", "opposing_side", "colleague", "vendor", "marketing"])
    res = clf.classify(_inp("Notice of Electronic Filing", "The Clerk docketed. CM/ECF.", questions=[st]))
    r = res.results["sender_type"]
    assert set(r.probabilities) == set(st.allowed_answers)
    assert abs(sum(r.probabilities.values()) - 1.0) < 1e-6


def test_detects_court_and_phishing():
    clf = DemoClassifier()
    st = q("sender_type", ["prospect", "client", "court", "opposing_side", "colleague", "vendor", "marketing"])
    ph = q("possible_phishing", ["yes", "no"], answer_type=AnswerType.yes_no)
    res = clf.classify(_inp(
        "Notice of Electronic Filing",
        "The Clerk of court docketed this. CM/ECF case no. Honorable judge.",
        sender_email="ecf@txsd.uscourts.gov", questions=[st, ph],
    ))
    assert res.answer("sender_type") == "court"

    res2 = clf.classify(_inp(
        "Verify your account",
        "Click here to sign. E-signature required. Reset your password. Gift card needed.",
        questions=[st, ph],
    ))
    assert res2.answer("possible_phishing") == "yes"


def test_custom_question_scored_by_answer_hints():
    clf = DemoClassifier()
    custom = q("chapter", ["chapter_7", "chapter_13", "adversary", "other"])
    res = clf.classify(_inp("Chapter 13 plan", "This concerns the chapter 13 repayment plan.", questions=[custom]))
    assert res.answer("chapter") == "chapter_13"


def test_reports_latency_and_tokens():
    clf = DemoClassifier()
    st = q("sender_type", ["client", "vendor"])
    res = clf.classify(_inp("hello", "an invoice for your subscription", questions=[st]))
    r = res.results["sender_type"]
    assert r.input_tokens >= 1
    assert r.latency_ms >= 0.0
    assert res.classifier_name == "demo"
