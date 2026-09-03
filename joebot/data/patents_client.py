"""USPTO PatentsView PatentSearch API access for the patent-activity signal.

IMPORTANT deviation from this project's usual "free and keyless" data
sources: PatentsView's original keyless endpoint (api.patentsview.org) was
retired (dead as of 2026-05-16, redirecting into a USPTO migration guide).
Its replacement, the PatentSearch API at search.patentsview.org, is still
free but requires a registered API key sent as the X-Api-Key header
(sign up at https://patentsview.org/apis/keyrequest). This module follows
the same optional-key, graceful-no-op pattern already used for Reddit in
joebot/data/reddit_client.py: PATENTSVIEW_API_KEY absent from .env is
treated exactly like Reddit credentials being absent -- the signal scores
0 for everything rather than erroring, so the rest of the pipeline is
unaffected either way.

NOTE: like gov_contracts_client.py, the exact response field names here
were not verified against a live call from this development environment's
network policy. Field extraction is defensive and fails soft.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass

import requests

from joebot.data import health
from joebot.data.cache import DiskCache

log = logging.getLogger(__name__)

_patents_cache = DiskCache(namespace="patents", ttl_seconds=24 * 3600)

API_URL = "https://search.patentsview.org/api/v1/patent/"


@dataclass
class PatentRecord:
    patent_id: str | None
    title: str | None
    patent_date: dt.date | None


def _api_key() -> str | None:
    return os.environ.get("PATENTSVIEW_API_KEY", "").strip() or None


def fetch_patents_for_assignee(assignee_organization: str, as_of_date: dt.date, lookback_days: int = 730) -> list[PatentRecord]:
    """Patents assigned to `assignee_organization`, filed within the lookback
    window ending as_of_date. Returns [] if no API key is configured or the
    call fails -- never raises."""
    cache_key = assignee_organization.lower().replace(" ", "_")
    cached = _patents_cache.get(cache_key)
    if cached is None:
        cached = _fetch_patents_uncached(assignee_organization)
        _patents_cache.set(cache_key, cached)

    cutoff = as_of_date - dt.timedelta(days=lookback_days)
    records = []
    for raw in cached:
        patent_date = dt.date.fromisoformat(raw["patent_date"]) if raw.get("patent_date") else None
        if patent_date is not None and cutoff <= patent_date <= as_of_date:
            records.append(PatentRecord(patent_id=raw.get("patent_id"), title=raw.get("title"), patent_date=patent_date))
    return records


def _fetch_patents_uncached(assignee_organization: str) -> list[dict]:
    api_key = _api_key()
    if not api_key:
        log.info("PATENTSVIEW_API_KEY not configured -- patent_activity signal will score 0 for everything.")
        health.record_not_configured(health.PATENTS, detail="PATENTSVIEW_API_KEY not set")
        return []

    query = {
        "q": {"_text_any": {"assignees.assignee_organization": assignee_organization}},
        "f": ["patent_id", "patent_title", "patent_date"],
        "o": {"size": 50},
    }

    try:
        resp = requests.post(API_URL, json=query, headers={"X-Api-Key": api_key}, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        health.record_success(health.PATENTS)
    except Exception as exc:
        log.warning("PatentsView lookup failed for %r: %s", assignee_organization, exc)
        health.record_failure(health.PATENTS, detail=str(exc))
        return []

    results = []
    for row in payload.get("patents", []):
        try:
            results.append({
                "patent_id": row.get("patent_id"),
                "title": row.get("patent_title"),
                "patent_date": _normalize_date(row.get("patent_date")),
            })
        except Exception as exc:
            log.warning("Failed to parse a PatentsView record for %r: %s", assignee_organization, exc)

    return results


def _normalize_date(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    try:
        return dt.date.fromisoformat(raw_date[:10]).isoformat()
    except ValueError:
        return None
