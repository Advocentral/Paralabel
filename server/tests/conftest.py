from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import Settings
from server.app.crypto import new_key
from server.app.db import Base
from server.app import models  # noqa: F401 - register tables
from server.app.models import Tenant
from server.triage.seed import seed_tenant


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def settings() -> Settings:
    return Settings(
        token_encryption_key=new_key(),
        classifier="demo",
        price_per_billion_tokens=1000.0,
        _env_file=None,
    )


@pytest.fixture
def tenant_id(session: Session) -> int:
    tenant = Tenant(name="Test Firm", template_key="general")
    session.add(tenant)
    session.flush()
    seed_tenant(session, tenant.id, "general")
    session.commit()
    return tenant.id
