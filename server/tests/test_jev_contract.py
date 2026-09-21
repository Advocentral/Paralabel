"""Contract test for the Jev adapter against a recorded response fixture.

Pins the TypeSafe /systemone request/response mapping so a change on either side
fails loudly.
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
    req = build_request(_inp(), model="jev-latest")
    assert req["model"] == "jev-latest"
    assert req["state"]["sender_email"] == "ecf@txsd.uscourts.gov"
    # choice question carries per-option criteria
    st = req["questions"]["sender_type"]
    assert st["type"] == "choice"
    assert set(st["criteria"]) == {"prospect", "client", "court", "opposing_side", "colleague", "vendor", "marketing"}
    # yes_no maps to noul with true/false criteria
    ph = req["questions"]["possible_phishing"]
    assert ph["type"] == "noul"
    assert set(ph["criteria"]) == {"true", "false"}


def test_parse_recorded_response():
    data = json.loads(FIXTURE.read_text())
    result = parse_response(_inp(), data, latency_ms=42.0)
    assert result.classifier_name == "jev"
    # choice
    assert result.answer("sender_type") == "court"
    assert result.probability("sender_type", "court") == pytest.approx(0.90)
    assert set(result.results["sender_type"].probabilities) == {
        "prospect", "client", "court", "opposing_side", "colleague", "vendor", "marketing"
    }
    # noul -> yes/no expansion (P(true)=0.04 -> no)
    assert result.answer("possible_phishing") == "no"
    assert result.probability("possible_phishing", "yes") == pytest.approx(0.04)
    assert result.probability("possible_phishing", "no") == pytest.approx(0.96)
    # usage split across the 2 questions
    assert result.results["sender_type"].input_tokens == 64


def test_classify_requires_key():
    clf = JevClassifier(api_key="", base_url="https://api.typesafe.ai/v1")
    with pytest.raises(JevNotConfigured):
        clf.classify(_inp())
