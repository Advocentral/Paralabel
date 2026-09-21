"""Contract test for the Jev adapter against a recorded response fixture.

This pins the request/response mapping so that when the real TypeSafe docs arrive
(M7), build_request/parse_response can be updated with a failing test to guide them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.triage.classifier import AnswerType, TriageInput
from server.triage.jev import JevClassifier, JevNotConfigured, build_request, parse_response

from .helpers import q

FIXTURE = Path(__file__).parent / "fixtures" / "jev_response.json"


def _inp() -> TriageInput:
    st = q("sender_type", ["prospect", "client", "court", "opposing_side", "colleague", "vendor", "marketing"])
    ph = q("possible_phishing", ["yes", "no"], answer_type=AnswerType.yes_no)
    return TriageInput(
        sender_name="CM/ECF", sender_email="ecf@txsd.uscourts.gov",
        subject="Notice", body_text="Docketed.", received_at=datetime.now(timezone.utc),
        questions=(st, ph),
    )


def test_build_request_shape():
    req = build_request(_inp())
    assert req["input"]["sender_email"] == "ecf@txsd.uscourts.gov"
    keys = {qq["key"] for qq in req["questions"]}
    assert keys == {"sender_type", "possible_phishing"}
    assert req["questions"][0]["answers"]  # allowed answers passed through


def test_parse_recorded_response():
    data = json.loads(FIXTURE.read_text())
    result = parse_response(_inp(), data, latency_ms=42.0)
    assert result.classifier_name == "jev"
    assert result.answer("sender_type") == "court"
    assert result.probability("sender_type", "court") == pytest.approx(0.90)
    # Every allowed answer has a probability entry.
    assert set(result.results["sender_type"].probabilities) == {
        "prospect", "client", "court", "opposing_side", "colleague", "vendor", "marketing"
    }
    assert result.results["sender_type"].input_tokens == 128
    assert result.results["sender_type"].latency_ms == 42.0


def test_classify_requires_config():
    clf = JevClassifier(api_key="", base_url="")
    with pytest.raises(JevNotConfigured):
        clf.classify(_inp())
