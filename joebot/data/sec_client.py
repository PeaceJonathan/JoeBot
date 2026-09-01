"""SEC EDGAR access via edgartools.

Phase 1 scope: minimal XBRL fact lookups (revenue trend, cash) for the
fundamental sanity filter in joebot/signals/fundamental.py. Filing feeds
(13D/13G, 8-K) are added in Phase 2.

SEC requires a real, identifying User-Agent on every request and asks
callers to stay under 10 req/sec -- both are enforced here, not left to
each call site.
"""
from __future__ import annotations

import logging

from config import settings
from joebot.data.cache import DiskCache, sec_rate_limiter

log = logging.getLogger(__name__)

_facts_cache = DiskCache(namespace="sec_facts", ttl_seconds=24 * 3600)

_identity_set = False


def _ensure_identity() -> None:
    global _identity_set
    if _identity_set:
        return
    import edgar

    edgar.set_identity(settings.SEC_USER_AGENT)
    _identity_set = True


class FundamentalSnapshot:
    """Best-effort fundamental facts as of the most recent filing edgartools returns.

    Any field may be None -- small/mid-cap XBRL tagging is inconsistent, and
    callers (fundamental.py) must treat missing data as "unknown", not "bad".
    """

    def __init__(self, revenue_latest: float | None, revenue_prior: float | None, cash: float | None):
        self.revenue_latest = revenue_latest
        self.revenue_prior = revenue_prior
        self.cash = cash

    @property
    def revenue_growth_pct(self) -> float | None:
        if self.revenue_latest is None or not self.revenue_prior:
            return None
        return (self.revenue_latest - self.revenue_prior) / abs(self.revenue_prior)


def fetch_fundamental_snapshot(ticker: str) -> FundamentalSnapshot:
    cache_key = ticker
    cached = _facts_cache.get(cache_key)
    if cached is not None:
        return FundamentalSnapshot(**cached)

    snapshot = _fetch_fundamental_snapshot_uncached(ticker)
    _facts_cache.set(
        cache_key,
        {
            "revenue_latest": snapshot.revenue_latest,
            "revenue_prior": snapshot.revenue_prior,
            "cash": snapshot.cash,
        },
    )
    return snapshot


def _fetch_fundamental_snapshot_uncached(ticker: str) -> FundamentalSnapshot:
    try:
        _ensure_identity()
        import edgar

        sec_rate_limiter.wait()
        company = edgar.Company(ticker)
        facts = company.get_facts()
        df = facts.to_pandas()
    except Exception as exc:
        log.warning("SEC fact lookup failed for %s: %s", ticker, exc)
        return FundamentalSnapshot(None, None, None)

    revenue_latest, revenue_prior = _latest_two_annual(df, concept_candidates=(
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    ))
    cash_latest, _ = _latest_two_annual(df, concept_candidates=(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    ))
    return FundamentalSnapshot(revenue_latest, revenue_prior, cash_latest)


def _latest_two_annual(df, concept_candidates: tuple[str, ...]) -> tuple[float | None, float | None]:
    """Return (latest, prior) values for the first matching concept found.

    Defensive against edgartools' facts DataFrame schema varying by version --
    if expected columns aren't present, fail soft (None, None) rather than
    raising, since a single ticker's odd tagging shouldn't crash a full scan.
    """
    if df is None or df.empty:
        return None, None

    concept_col = next((c for c in ("concept", "fact", "name") if c in df.columns), None)
    value_col = next((c for c in ("value", "val") if c in df.columns), None)
    period_col = next((c for c in ("period_end", "end", "fiscal_period") if c in df.columns), None)
    if not (concept_col and value_col and period_col):
        return None, None

    for concept in concept_candidates:
        rows = df[df[concept_col] == concept]
        if rows.empty:
            continue
        rows = rows.sort_values(period_col, ascending=False)
        values = rows[value_col].tolist()
        latest = float(values[0]) if len(values) > 0 else None
        prior = float(values[1]) if len(values) > 1 else None
        return latest, prior

    return None, None
