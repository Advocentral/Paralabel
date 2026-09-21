"""Tiny in-memory rate limiter + daily budget counter for the public demo endpoint.

In-memory is fine for a single-instance demo. For multiple instances, back these with
Redis — the interface stays the same.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)
_budget: dict[str, int] = {}


def allow(key: str, limit: int, window_seconds: int = 3600) -> bool:
    """True if `key` is under `limit` in the trailing window; records the hit."""
    now = time.time()
    cutoff = now - window_seconds
    with _lock:
        hits = [t for t in _hits[key] if t >= cutoff]
        if len(hits) >= limit:
            _hits[key] = hits
            return False
        hits.append(now)
        _hits[key] = hits
        return True


def budget_take(name: str, daily_limit: int) -> bool:
    """Consume one unit of today's budget for `name`. False when exhausted."""
    today = date.today().isoformat()
    bucket = f"{name}:{today}"
    with _lock:
        used = _budget.get(bucket, 0)
        if used >= daily_limit:
            return False
        _budget[bucket] = used + 1
        return True


def reset() -> None:  # for tests
    with _lock:
        _hits.clear()
        _budget.clear()
