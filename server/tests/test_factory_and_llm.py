from __future__ import annotations

import pytest

from server.app.config import Settings
from server.triage.demo import DemoClassifier
from server.triage.factory import get_classifier
from server.triage.jev import JevClassifier
from server.triage.llm import LLMClassifier, LLMNotConfigured, build_schema
from datetime import datetime, timezone
from server.triage.classifier import TriageInput
from .helpers import q


def test_factory_selects_demo_by_default():
    assert isinstance(get_classifier(Settings(classifier="demo")), DemoClassifier)


def test_factory_selects_jev():
    assert isinstance(get_classifier(Settings(classifier="jev")), JevClassifier)


def test_factory_llm_requires_provider_and_model():
    with pytest.raises(LLMNotConfigured):
        get_classifier(Settings(classifier="llm"))  # no provider/model -> error


def test_factory_rejects_unknown():
    with pytest.raises(ValueError):
        get_classifier(Settings(classifier="bogus"))


def test_llm_schema_constrains_answers():
    st = q("sender_type", ["client", "vendor"])
    inp = TriageInput("S", "s@x.example", "hi", "body", datetime.now(timezone.utc), (st,))
    schema = build_schema(inp)
    enum = schema["properties"]["sender_type"]["properties"]["answer"]["enum"]
    assert enum == ["client", "vendor"]


def test_llm_transport_not_implemented_yet():
    clf = LLMClassifier(provider="anthropic", model="claude-haiku-4-5", api_key="k")
    st = q("sender_type", ["client", "vendor"])
    inp = TriageInput("S", "s@x.example", "hi", "body", datetime.now(timezone.utc), (st,))
    with pytest.raises(LLMNotConfigured):
        clf.classify(inp)
