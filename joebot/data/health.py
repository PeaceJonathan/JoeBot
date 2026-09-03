"""Central data-source health tracking.

Every external client (market_data, sec_client, clinicaltrials_client,
gov_contracts_client, patents_client, reddit_client) records a status here
on every fetch attempt. This exists to enforce the project's hardest rule
around data honesty: a failed/unreachable API must never be silently
indistinguishable from "checked, and there's genuinely nothing there."

Three states, deliberately not a plain bool:
- OK: the last live call to this source succeeded. The *data* returned may
  still be empty -- that's a real "no evidence found," and is fine.
- UNAVAILABLE: the last live call raised (network error, non-2xx, timeout,
  unparseable response). A score of 0 derived while a source is in this
  state must be reported as "unknown," not "no."
- NOT_CONFIGURED: an optional source (Reddit, PatentsView) has no
  credentials/key in .env. Expected and not an error, but still not the
  same thing as "checked and found nothing."

Consumers: joebot/signals/*.py attach the relevant source's status into
their SignalResult.metadata (see metadata["data_source_status"]);
joebot/reporting/narrative.py reads that to phrase a zero score correctly;
dashboard/views render the full snapshot() as the "Data Health" panel.

This registry is in-process and reset per run (module-level dict) -- it
reflects the *current* scan's connectivity, not a historical log. Historical
per-run health could be persisted to SQLite later if that turns out to
matter; not built until there's a reason to.
"""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass

OK = "ok"
UNAVAILABLE = "unavailable"
NOT_CONFIGURED = "not_configured"

# Canonical source names used across clients/signals/dashboard. Keep these
# in sync with any new client added to joebot/data/.
MARKET_DATA = "market_data"
SEC = "sec"
CLINICALTRIALS = "clinicaltrials"
USASPENDING = "usaspending"
PATENTS = "patents"
REDDIT = "reddit"

ALL_SOURCES = (MARKET_DATA, SEC, CLINICALTRIALS, USASPENDING, PATENTS, REDDIT)

DISPLAY_NAMES = {
    MARKET_DATA: "Market Data",
    SEC: "SEC EDGAR",
    CLINICALTRIALS: "ClinicalTrials.gov",
    USASPENDING: "USAspending.gov",
    PATENTS: "Patent Data (PatentsView)",
    REDDIT: "Reddit",
}


@dataclass
class SourceHealth:
    source: str
    status: str = NOT_CONFIGURED
    detail: str | None = None
    last_success_at: str | None = None
    last_attempt_at: str | None = None
    call_count: int = 0
    failure_count: int = 0

    @property
    def display_name(self) -> str:
        return DISPLAY_NAMES.get(self.source, self.source)

    @property
    def emoji(self) -> str:
        return {"ok": "\U0001F7E2", "unavailable": "\U0001F534", "not_configured": "\U0001F7E1"}.get(self.status, "⚪")


_lock = threading.Lock()
_registry: dict[str, SourceHealth] = {}


def _now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _get_or_create(source: str) -> SourceHealth:
    if source not in _registry:
        _registry[source] = SourceHealth(source=source)
    return _registry[source]


def record_success(source: str, detail: str | None = None) -> None:
    with _lock:
        h = _get_or_create(source)
        h.status = OK
        h.detail = detail
        now = _now()
        h.last_success_at = now
        h.last_attempt_at = now
        h.call_count += 1


def record_failure(source: str, detail: str) -> None:
    with _lock:
        h = _get_or_create(source)
        h.status = UNAVAILABLE
        h.detail = detail
        h.last_attempt_at = _now()
        h.call_count += 1
        h.failure_count += 1


def record_not_configured(source: str, detail: str | None = None) -> None:
    with _lock:
        h = _get_or_create(source)
        # Don't clobber a status that already reflects a real attempt this
        # run (e.g. a source that's configured but flaky) with a stale
        # "not configured" from an earlier no-op call site.
        if h.status == OK and h.call_count > 0:
            return
        h.status = NOT_CONFIGURED
        h.detail = detail


def get_status(source: str) -> SourceHealth:
    with _lock:
        h = _registry.get(source)
        return SourceHealth(**vars(h)) if h else SourceHealth(source=source)


def snapshot() -> dict[str, SourceHealth]:
    with _lock:
        merged = {s: SourceHealth(source=s) for s in ALL_SOURCES}
        for name, h in _registry.items():
            merged[name] = SourceHealth(**vars(h))
        return merged


def reset() -> None:
    """Test/CLI hook: clear all recorded status (start-of-run or between tests)."""
    with _lock:
        _registry.clear()
