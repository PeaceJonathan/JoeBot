"""SEC EDGAR access via edgartools.

Phase 1: minimal XBRL fact lookups (revenue trend, cash) for the
fundamental sanity filter in joebot/signals/fundamental.py.

Phase 2: filing feeds for catalyst detection --
- Schedule 13D/13G (beneficial ownership >5%), for the activist-stake signal
- 8-K Item 5.02 (officer/director departures & appointments), for the
  leadership-change signal
consumed by joebot/signals/catalyst_sec.py.

SEC requires a real, identifying User-Agent on every request and asks
callers to stay under 10 req/sec -- both are enforced here, not left to
each call site.

NOTE on Phase 2 field extraction, updated after a source-level (not live)
verification pass against the actually-installed edgartools==5.56.0: this
sandbox's network policy still blocks outbound SEC EDGAR access, so nothing
here has been exercised against a real HTTP response. But edgartools is a
local Python package, so its actual class definitions were read directly
(see edgar/_filings.py, edgar/sgml/sgml_header.py, edgar/company_reports/
current_report.py) to confirm attribute names rather than guessing:
- Filing.filing_date and Filing.accession_no are real, plain instance
  attributes (confirmed correct as originally guessed).
- Filing.obj() for an 8-K returns an EightK whose .items property returns
  strings like "Item 5.02" (confirmed correct as originally guessed).
- Filing.company is the SUBJECT company (the ticker itself), NOT the
  reporting owner on a SC 13D/13G -- the original code's fallback chain
  ("filer", "reporting_owner", "company") would have silently returned the
  ticker's own name as the "activist," which is wrong. The real reporting
  owner lives at Filing.header.reporting_owners (a list of ReportingOwner,
  each with .owner.name) -- see the SC 13D/13G branch below, fixed
  accordingly. header.filers[].company_information.name is used only as a
  last-resort fallback (the subject company, clearly labeled as such if it
  ever surfaces).
This closes the source-level verification gap; a live smoke test (see
scripts/validate_live_data.py) is still needed to catch anything this
static reading missed (e.g. reporting_owners being empty on some filing
eras/forms).
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from config import settings
from joebot.data import health
from joebot.data.cache import DiskCache, sec_rate_limiter

log = logging.getLogger(__name__)

_facts_cache = DiskCache(namespace="sec_facts", ttl_seconds=24 * 3600)
_filings_cache = DiskCache(namespace="sec_filings", ttl_seconds=12 * 3600)

# Large passive institutional filers whose routine 13G filings are not a
# "someone is taking an activist/comeback stake" signal. Matched as a
# case-insensitive substring of the reporting owner's name. Not exhaustive --
# expect to extend this list as false positives show up in real runs
# (Phase 2 verification step).
PASSIVE_FILER_KEYWORDS = (
    "vanguard",
    "blackrock",
    "state street",
    "geode capital",
    "dimensional fund",
    "norges bank",
    "vident advisory",
)

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
        if facts is None:
            health.record_success(health.SEC, detail="no facts for ticker")
            return FundamentalSnapshot(None, None, None)
        # NOTE: edgartools' EntityFacts has to_dataframe(), not to_pandas() --
        # verified by reading edgar/entity/entity_facts.py directly (see
        # module docstring). to_pandas() doesn't exist on this class; calling
        # it here previously raised AttributeError on every ticker, silently
        # caught below, so fundamental_sanity always fell back to "no usable
        # XBRL data" regardless of what SEC actually had on file.
        df = facts.to_dataframe(include_metadata=True)
        health.record_success(health.SEC)
    except Exception as exc:
        log.warning("SEC fact lookup failed for %s: %s", ticker, exc)
        health.record_failure(health.SEC, detail=str(exc))
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
    """Return (latest, prior) annual (fiscal_period == "FY") values for the
    first matching concept found.

    Column names (concept, value, period_end, fiscal_period) match
    EntityFacts.to_dataframe()'s documented schema in edgartools 5.56.0 --
    confirmed by reading edgar/entity/entity_facts.py, not guessed. The
    "FY"-only filter avoids mixing quarterly (10-Q) and annual (10-K)
    values when picking "latest two" -- without it, a company's most recent
    quarterly filing could be compared against a prior annual figure as if
    both were annual, understating or fabricating a growth rate.
    """
    if df is None or df.empty:
        return None, None

    if not {"concept", "value", "period_end"}.issubset(df.columns):
        return None, None

    for concept in concept_candidates:
        rows = df[df["concept"] == concept]
        if rows.empty:
            continue
        if "fiscal_period" in rows.columns and (rows["fiscal_period"] == "FY").any():
            rows = rows[rows["fiscal_period"] == "FY"]
        rows = rows.dropna(subset=["value"]).sort_values("period_end", ascending=False)
        rows = rows.drop_duplicates(subset=["period_end"], keep="first")
        values = rows["value"].tolist()
        latest = float(values[0]) if len(values) > 0 else None
        prior = float(values[1]) if len(values) > 1 else None
        return latest, prior

    return None, None


@dataclass
class FilingEvent:
    """One SEC filing hit relevant to a catalyst signal.

    filer_name is the reporting owner (for 13D/13G) -- None if edgartools'
    schema didn't expose it in a way this code recognizes; callers must not
    treat "unknown filer" as "known non-activist filer" (see
    is_likely_passive_filer, which only returns True on a positive match).
    """

    ticker: str
    form: str  # "SC 13D", "SC 13G", or "8-K"
    filing_date: dt.date
    accession_no: str
    filer_name: str | None = None
    items: tuple[str, ...] = field(default_factory=tuple)  # 8-K item codes, e.g. ("5.02",)

    def is_likely_passive_filer(self) -> bool:
        if not self.filer_name:
            return False
        name = self.filer_name.lower()
        return any(keyword in name for keyword in PASSIVE_FILER_KEYWORDS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "form": self.form,
            "filing_date": self.filing_date.isoformat(),
            "accession_no": self.accession_no,
            "filer_name": self.filer_name,
            "items": list(self.items),
        }


def fetch_ownership_filings(ticker: str, as_of_date: dt.date, lookback_days: int = 180) -> list[FilingEvent]:
    """Schedule 13D/13G filings for `ticker` in the lookback window, point-in-time gated to as_of_date."""
    cache_key = f"{ticker}_13dg"
    cached = _filings_cache.get(cache_key)
    if cached is None:
        cached = _fetch_ownership_filings_uncached(ticker)
        _filings_cache.set(cache_key, cached)

    cutoff = as_of_date - dt.timedelta(days=lookback_days)
    events = []
    for raw in cached:
        filing_date = dt.date.fromisoformat(raw["filing_date"])
        if cutoff <= filing_date <= as_of_date:
            events.append(FilingEvent(
                ticker=ticker,
                form=raw["form"],
                filing_date=filing_date,
                accession_no=raw["accession_no"],
                filer_name=raw.get("filer_name"),
            ))
    return events


def _fetch_ownership_filings_uncached(ticker: str) -> list[dict]:
    results: list[dict] = []
    try:
        _ensure_identity()
        import edgar

        for form in ("SC 13D", "SC 13G"):
            sec_rate_limiter.wait()
            filings = edgar.Company(ticker).get_filings(form=form)
            for filing in list(filings)[:25]:  # bounded: most recent N, not full history
                try:
                    results.append({
                        "form": form,
                        "filing_date": str(filing.filing_date),
                        "accession_no": str(filing.accession_no),
                        "filer_name": _extract_filer_name(filing),
                    })
                except Exception as exc:
                    log.warning("Failed to parse a %s filing for %s: %s", form, ticker, exc)
        health.record_success(health.SEC)
    except Exception as exc:
        log.warning("SEC ownership filing lookup failed for %s: %s", ticker, exc)
        health.record_failure(health.SEC, detail=str(exc))

    return results


def _extract_filer_name(filing: Any) -> str | None:
    """Reporting-owner (the activist/holder, not the subject company) name
    extraction for a SC 13D/13G filing.

    Filing.company is the SUBJECT company (the ticker being filed about),
    never the reporting owner -- using it here would misreport "the company
    disclosed a stake in itself." The real reporting-owner identity is on
    the SGML header at .header.reporting_owners[i].owner.name (see module
    docstring for how this was confirmed by reading edgartools' source).
    """
    try:
        header = getattr(filing, "header", None)
        reporting_owners = getattr(header, "reporting_owners", None) if header else None
        if reporting_owners:
            names = [ro.owner.name for ro in reporting_owners if getattr(ro, "owner", None) and ro.owner.name]
            if names:
                return "; ".join(names)
    except Exception as exc:
        log.warning("Failed to extract reporting_owners from filing header: %s", exc)

    # No reporting_owners on the header -- report unknown rather than fall
    # back to Filing.company (the subject company), which would misattribute
    # the stake to the company disclosing it about itself.
    return None


def fetch_8k_leadership_events(ticker: str, as_of_date: dt.date, lookback_days: int = 180) -> list[FilingEvent]:
    """8-K filings with Item 5.02 (officer/director changes) for `ticker`, point-in-time gated."""
    cache_key = f"{ticker}_8k"
    cached = _filings_cache.get(cache_key)
    if cached is None:
        cached = _fetch_8k_filings_uncached(ticker)
        _filings_cache.set(cache_key, cached)

    cutoff = as_of_date - dt.timedelta(days=lookback_days)
    events = []
    for raw in cached:
        filing_date = dt.date.fromisoformat(raw["filing_date"])
        items = tuple(raw.get("items", []))
        if cutoff <= filing_date <= as_of_date and any(item.startswith("5.02") for item in items):
            events.append(FilingEvent(
                ticker=ticker,
                form="8-K",
                filing_date=filing_date,
                accession_no=raw["accession_no"],
                items=items,
            ))
    return events


def _fetch_8k_filings_uncached(ticker: str) -> list[dict]:
    results: list[dict] = []
    try:
        _ensure_identity()
        import edgar

        sec_rate_limiter.wait()
        filings = edgar.Company(ticker).get_filings(form="8-K")
        for filing in list(filings)[:30]:  # bounded: most recent N, not full history
            try:
                items = _extract_8k_items(filing)
                results.append({
                    "filing_date": str(filing.filing_date),
                    "accession_no": str(filing.accession_no),
                    "items": items,
                })
            except Exception as exc:
                log.warning("Failed to parse an 8-K for %s: %s", ticker, exc)
        health.record_success(health.SEC)
    except Exception as exc:
        log.warning("SEC 8-K lookup failed for %s: %s", ticker, exc)
        health.record_failure(health.SEC, detail=str(exc))

    return results


def _extract_8k_items(filing: Any) -> list[str]:
    """8-K item-code extraction. Filing.obj() -> EightK.items returns strings
    like "Item 5.02" -- confirmed by reading
    edgar/company_reports/current_report.py directly (see module docstring)."""
    try:
        obj = filing.obj()
        raw_items = getattr(obj, "items", None)
        if not raw_items:
            return []
        # Normalize to strings like "5.02" regardless of "Item 5.02" formatting.
        return [str(i).replace("Item", "").strip() for i in raw_items]
    except Exception as exc:
        log.warning("Failed to extract 8-K items: %s", exc)
        return []
