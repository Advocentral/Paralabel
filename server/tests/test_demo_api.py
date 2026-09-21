from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app.config import Settings, get_settings
from server.app.main import app
from server.app import ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()
    app.dependency_overrides.pop(get_settings, None)


def _client(**overrides) -> TestClient:
    s = Settings(_env_file=None, classifier="demo", **overrides)
    app.dependency_overrides[get_settings] = lambda: s
    return TestClient(app)


COURT = {"sender_name": "Clerk", "sender_email": "ecf@txsd.uscourts.gov",
         "subject": "Notice of Electronic Filing", "body": "The Clerk of court docketed this. CM/ECF."}
PHISH = {"sender_name": "DocuSign", "sender_email": "no-reply@secure-verify.example",
         "subject": "Secure document waiting - e-signature required",
         "body": "Click here to sign and verify your account or it will be deleted."}


def test_triage_court_email():
    r = _client().post("/api/demo/triage", json=COURT)
    assert r.status_code == 200
    data = r.json()
    assert data["classifier"] == "demo"
    assert data["parent_label"] == "Paralabel/"
    assert "Deadlines & court" in data["labels"]
    assert data["matched_rule"] == "court"
    keys = {q["key"] for q in data["questions"]}
    assert "sender_type" in keys
    st = next(q for q in data["questions"] if q["key"] == "sender_type")
    assert st["answer"] == "court"
    assert abs(sum(st["probabilities"].values()) - 1.0) < 0.01  # probs rounded to 4dp


def test_triage_phishing_email():
    r = _client().post("/api/demo/triage", json=PHISH)
    assert r.status_code == 200
    assert "Held: possible phishing" in r.json()["labels"]


def test_rate_limit():
    c = _client(demo_rate_per_hour=1)
    assert c.post("/api/demo/triage", json=COURT).status_code == 200
    assert c.post("/api/demo/triage", json=COURT).status_code == 429


def test_shared_secret_required():
    c = _client(demo_shared_secret="s3cret")
    assert c.post("/api/demo/triage", json=COURT).status_code == 403
    ok = c.post("/api/demo/triage", json=COURT, headers={"X-Demo-Token": "s3cret"})
    assert ok.status_code == 200


def test_body_is_capped_not_rejected():
    payload = {**COURT, "body": "The Clerk of court docketed this. CM/ECF. " + "x" * 5000}
    assert _client().post("/api/demo/triage", json=payload).status_code == 200


def test_no_persistence_smoke():
    # The endpoint has no DB dependency and stores nothing; a bare request just works.
    r = _client().post("/api/demo/triage", json={"subject": "hi", "body": "hello"})
    assert r.status_code == 200
    assert r.json()["labels"]  # fallback still labels it
