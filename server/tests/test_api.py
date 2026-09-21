from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from server.app.config import Settings, get_settings
from server.app.crypto import new_key
from server.app.db import Base, get_session
from server.app import models  # noqa: F401
from server.app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_session():
        s: Session = TestingSession()
        try:
            yield s
        finally:
            s.close()

    def _get_settings():
        return Settings(token_encryption_key=new_key(), google_client_id="", _env_file=None)

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_settings] = _get_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_info_lists_templates(client):
    data = client.get("/api/info").json()
    assert "general" in data["templates"]


def test_status_seeds_tenant_and_returns_no_accounts(client):
    resp = client.get("/api/google/status")
    assert resp.status_code == 200
    assert resp.json() == {"accounts": []}


def test_poll_with_no_accounts(client):
    resp = client.post("/api/google/poll")
    assert resp.status_code == 200
    assert resp.json() == {"triaged": 0}


def test_authorize_requires_client_id(client):
    # google_client_id is empty in the override -> 400
    assert client.get("/api/google/authorize").status_code == 400


def test_push_rejects_bad_token(client, monkeypatch):
    from server.app.routers import google
    from server.mail import pubsub

    def boom(token, settings):
        raise pubsub.PushVerificationError("bad")

    monkeypatch.setattr(google.pubsub, "verify_push_token", boom)
    resp = client.post("/api/google/push", json={"message": {"data": "x"}}, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_push_accepts_and_schedules(client, monkeypatch):
    import base64
    import json as _json
    from server.app.routers import google

    monkeypatch.setattr(google.pubsub, "verify_push_token", lambda token, settings: {"email": "ok"})
    calls = {}
    monkeypatch.setattr(google, "_run_push", lambda settings, email, hid: calls.update(email=email, hid=hid))

    data = base64.b64encode(_json.dumps({"emailAddress": "firm@example.com", "historyId": 55}).encode()).decode()
    resp = client.post("/api/google/push", json={"message": {"data": data}}, headers={"Authorization": "Bearer good"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert calls == {"email": "firm@example.com", "hid": "55"}
