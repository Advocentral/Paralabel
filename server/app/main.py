"""FastAPI application entrypoint.

Exposes health/info plus the Google connection endpoints. In poll mode a background
scheduler pulls new mail on an interval. Gmail push and the dashboard APIs arrive in
later milestones.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..triage.loader import available_templates
from .config import get_settings
from .routers import google


@asynccontextmanager
async def lifespan(app: FastAPI):
    from ..jobs.scheduler import start_scheduler

    scheduler = start_scheduler(get_settings())
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Paralabel", version="0.1.0", lifespan=lifespan)
app.include_router(google.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/info")
def info() -> dict:
    settings = get_settings()
    return {
        "classifier": settings.classifier,
        "gmail_mode": settings.gmail_mode,
        "templates": available_templates(),
        "retention_days": settings.retention_days,
    }
