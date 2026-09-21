"""APScheduler setup.

In poll mode (GMAIL_MODE=poll) a background job pulls new mail every
GMAIL_POLL_SECONDS. Later milestones add daily watch renewal, the digest, and the
retention purge here. In push mode the poll job is not scheduled.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ..app.config import Settings, get_settings
from ..app.db import _session_factory
from ..mail import sync

log = logging.getLogger("jobs.scheduler")


def _poll_job() -> None:
    settings = get_settings()
    session = _session_factory()()
    try:
        triaged = sync.poll_all(session, settings)
        if triaged:
            log.info("poll triaged %d message(s)", triaged)
    except Exception:  # noqa: BLE001 - a job failure must not kill the scheduler
        log.exception("poll job failed")
    finally:
        session.close()


def _watch_renewal_job() -> None:
    settings = get_settings()
    session = _session_factory()()
    try:
        n = sync.renew_watches(session, settings)
        if n:
            log.info("renewed %d Gmail watch(es)", n)
    except Exception:  # noqa: BLE001 - a job failure must not kill the scheduler
        log.exception("watch renewal job failed")
    finally:
        session.close()


def start_scheduler(settings: Settings | None = None) -> BackgroundScheduler | None:
    settings = settings or get_settings()
    scheduler = BackgroundScheduler(daemon=True)

    if settings.gmail_mode == "poll" and settings.google_client_id:
        scheduler.add_job(
            _poll_job, "interval", seconds=settings.gmail_poll_seconds,
            id="gmail_poll", max_instances=1, coalesce=True,
        )
        log.info("scheduled Gmail poll every %ds", settings.gmail_poll_seconds)

    if settings.gmail_mode == "push" and settings.pubsub_topic:
        # Gmail watches expire after 7 days; renew daily with headroom.
        scheduler.add_job(
            _watch_renewal_job, "interval", hours=24,
            id="gmail_watch_renewal", max_instances=1, coalesce=True,
        )
        log.info("scheduled daily Gmail watch renewal")

    if scheduler.get_jobs():
        scheduler.start()
        return scheduler
    return None
