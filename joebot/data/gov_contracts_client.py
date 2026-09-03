"""USAspending.gov API access for the government-contracts catalyst signal.

Free, public, no API key -- confirmed current as of this writing. POSTs to
/api/v2/search/spending_by_award/, matching on the company's display name
(joebot.data.market_data.fetch_company_name) since USAspending doesn't
index by stock ticker.

NOTE: like the other Phase 2/4 filing-style feeds, the exact response
field names here were not verified against a live call from this
development environment's network policy (outbound to api.usaspending.gov
is blocked in this sandbox). USAspending's documented convention is
capitalized, spaced field names ("Award Amount", "Recipient Name") rather
than snake_case -- this code follows that convention but fails soft (empty
result, not a crash) if the real response shape differs. Needs a live
smoke test before trusting its output; see README.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import requests

from joebot.data.cache import DiskCache

log = logging.getLogger(__name__)

_contracts_cache = DiskCache(namespace="gov_contracts", ttl_seconds=24 * 3600)

API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
# Contract award type codes (USAspending's documented set for procurement
# contracts, as opposed to grants/loans/direct payments).
CONTRACT_AWARD_TYPE_CODES = ("A", "B", "C", "D")


@dataclass
class ContractAward:
    award_id: str | None
    recipient_name: str | None
    amount: float | None
    award_date: dt.date | None
    awarding_agency: str | None
    description: str | None


def fetch_recent_contracts(company_name: str, as_of_date: dt.date, lookback_days: int = 365) -> list[ContractAward]:
    cache_key = company_name.lower().replace(" ", "_")
    cached = _contracts_cache.get(cache_key)
    if cached is None:
        cached = _fetch_contracts_uncached(company_name)
        _contracts_cache.set(cache_key, cached)

    cutoff = as_of_date - dt.timedelta(days=lookback_days)
    awards = []
    for raw in cached:
        award_date = dt.date.fromisoformat(raw["award_date"]) if raw.get("award_date") else None
        if award_date is not None and cutoff <= award_date <= as_of_date:
            awards.append(ContractAward(
                award_id=raw.get("award_id"),
                recipient_name=raw.get("recipient_name"),
                amount=raw.get("amount"),
                award_date=award_date,
                awarding_agency=raw.get("awarding_agency"),
                description=raw.get("description"),
            ))
    return sorted(awards, key=lambda a: a.award_date, reverse=True)


def _fetch_contracts_uncached(company_name: str) -> list[dict]:
    payload = {
        "filters": {
            "recipient_search_text": [company_name],
            "award_type_codes": list(CONTRACT_AWARD_TYPE_CODES),
            "time_period": [{"start_date": "2015-01-01", "end_date": dt.date.today().isoformat()}],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount", "Start Date",
            "Awarding Agency", "Description",
        ],
        "sort": "Award Amount",
        "order": "desc",
        "limit": 20,
    }

    try:
        resp = requests.post(API_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("USAspending.gov lookup failed for %r: %s", company_name, exc)
        return []

    results = []
    for row in data.get("results", []):
        try:
            results.append({
                "award_id": row.get("Award ID"),
                "recipient_name": row.get("Recipient Name"),
                "amount": row.get("Award Amount"),
                "award_date": _normalize_date(row.get("Start Date")),
                "awarding_agency": row.get("Awarding Agency"),
                "description": row.get("Description"),
            })
        except Exception as exc:
            log.warning("Failed to parse a USAspending.gov award for %r: %s", company_name, exc)

    return results


def _normalize_date(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    try:
        return dt.date.fromisoformat(raw_date[:10]).isoformat()
    except ValueError:
        return None
