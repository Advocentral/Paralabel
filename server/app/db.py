"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


_engine = None
_SessionLocal: sessionmaker | None = None


def _session_factory() -> sessionmaker:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_session() -> Iterator[Session]:
    factory = _session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
