"""ClinicalTrials.gov API (v2) access for the pharma catalyst signal.

Free, public, no API key required. Sponsor-to-ticker mapping is not
something ClinicalTrials.gov provides -- config/pharma_crosswalk.yaml is a
small, manually maintained mapping from ticker to the sponsor name that
shows up in that company's ClinicalTrials.gov filings. Expect ongoing
manual correction, the same as the passive-filer keyword list in
sec_client.py: this is ordinary upkeep for this kind of crosswalk, not a
one-time solve.

NOTE: like the Phase 2 SEC filing feeds, the exact response JSON shape here
was not verified against a live call from this development environment's
network policy. Field extraction is defensive and fails soft to an empty
result rather than raising, but the field paths (protocolSection ->
identificationModule/designModule/statusModule) should be treated as a
best-effort guess pending a real smoke test.
"""
from __future__ import annotations

import datetime as dt
import logging

import requests

from joebot.data import health
from joebot.data.cache import DiskCache

log = logging.getLogger(__name__)

_trials_cache = DiskCache(namespace="clinicaltrials", ttl_seconds=24 * 3600)

API_URL = "https://clinicaltrials.gov/api/v2/studies"
LATE_PHASES = ("PHASE3", "PHASE4")
ACTIVE_STATUSES = ("RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED")


class TrialSnapshot:
    def __init__(self, nct_id: str | None, phase: str | None, status: str | None, last_update_date: dt.date | None):
        self.nct_id = nct_id
        self.phase = phase
        self.status = status
        self.last_update_date = last_update_date


def fetch_trials_for_sponsor(sponsor_name: str) -> list[TrialSnapshot]:
    cache_key = sponsor_name.lower().replace(" ", "_").replace(",", "").replace(".", "")
    cached = _trials_cache.get(cache_key)
    if cached is None:
        cached = _fetch_trials_uncached(sponsor_name)
        _trials_cache.set(cache_key, cached)

    trials = []
    for raw in cached:
        last_update = None
        if raw.get("last_update_date"):
            try:
                last_update = dt.date.fromisoformat(raw["last_update_date"])
            except ValueError:
                pass
        trials.append(TrialSnapshot(
            nct_id=raw.get("nct_id"),
            phase=raw.get("phase"),
            status=raw.get("status"),
            last_update_date=last_update,
        ))
    return trials


def _fetch_trials_uncached(sponsor_name: str) -> list[dict]:
    try:
        resp = requests.get(
            API_URL,
            params={"query.spons": sponsor_name, "pageSize": 25},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        health.record_success(health.CLINICALTRIALS)
    except Exception as exc:
        log.warning("ClinicalTrials.gov lookup failed for sponsor %r: %s", sponsor_name, exc)
        health.record_failure(health.CLINICALTRIALS, detail=str(exc))
        return []

    results = []
    for study in payload.get("studies", []):
        try:
            protocol = study.get("protocolSection", {})
            ident = protocol.get("identificationModule", {})
            design = protocol.get("designModule", {})
            status_module = protocol.get("statusModule", {})

            phases = design.get("phases") or []
            phase = phases[0] if phases else None
            status = status_module.get("overallStatus")
            last_update_raw = (status_module.get("lastUpdatePostDateStruct") or {}).get("date")

            results.append({
                "nct_id": ident.get("nctId"),
                "phase": phase,
                "status": status,
                "last_update_date": _normalize_date(last_update_raw),
            })
        except Exception as exc:
            log.warning("Failed to parse a ClinicalTrials.gov study for %r: %s", sponsor_name, exc)

    return results


def _normalize_date(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    for fmt in ("%Y-%m-%d", "%B %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(raw_date, fmt).date().isoformat()
        except ValueError:
            continue
    return None
