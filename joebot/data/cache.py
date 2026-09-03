"""Shared disk cache and rate limiter for all external data clients.

Every outbound client (market_data, sec_client, clinicaltrials_client,
reddit_client) should route through this module rather than sleeping or
caching ad hoc, so rate limits are enforced consistently in one place.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from config import settings


class RateLimiter:
    """Simple token-bucket-ish limiter: blocks so calls stay under N per second."""

    def __init__(self, max_per_second: float):
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            sleep_for = self._min_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


class DiskCache:
    """A dumb JSON-per-key disk cache with a TTL, keyed by an arbitrary string.

    Not thread-safe across processes; fine for a single local scheduled job.
    """

    def __init__(self, namespace: str, ttl_seconds: float):
        self._dir = settings.CACHE_DIR / namespace
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds

    def _path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self._dir / f"{safe_key}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self._ttl:
            return None
        try:
            with path.open("r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        with path.open("w") as f:
            json.dump(value, f)

    def get_or_fetch(self, key: str, fetch_fn: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = fetch_fn()
        self.set(key, value)
        return value


# Shared limiter instances. SEC's documented cap is 10 req/sec; we stay under it.
sec_rate_limiter = RateLimiter(max_per_second=settings.SEC_MAX_REQUESTS_PER_SECOND)
# Yahoo's real limit for yfinance's unofficial API is undocumented and, in
# practice, tighter than this project's original 2/sec guess -- scanning a
# full sector universe (dozens of tickers x several calls each: price
# history, info, insider transactions) was observed hitting 429s partway
# through a real run. 1/sec is more conservative; joebot/data/market_data.py
# additionally retries with backoff on an actual 429 (YFRateLimitError) as
# a second line of defense, since even a conservative client-side pace
# doesn't guarantee Yahoo's server-side limit won't still trip.
market_data_rate_limiter = RateLimiter(max_per_second=1.0)
