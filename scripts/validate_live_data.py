#!/usr/bin/env python3
"""Live data-source smoke test. Run this once after setup, on a machine with
normal internet access, before trusting any of JoeBot's output.

WHY THIS SCRIPT EXISTS: this codebase was largely developed and even this
"Priority 1: real data" hardening pass was done inside network-sandboxed
environments that cannot reach any of these external APIs (SEC EDGAR, Yahoo
Finance, ClinicalTrials.gov, USAspending.gov, PatentsView, Reddit -- every
outbound host was blocked at the network-policy layer). Every data client
was hardened as far as possible by reading the installed libraries' actual
source code (see joebot/data/sec_client.py's module docstring for what that
caught), but that is not a substitute for an actual live HTTP round trip.
This script is that live round trip. Run it yourself; don't take the rest
of this codebase's word for it.

Usage:
    python scripts/validate_live_data.py

Exits non-zero if any REQUIRED source (market data, SEC) fails. Optional
sources (Reddit, PatentsView) print SKIPPED if unconfigured -- that's
expected and not a failure, per the project's "not configured" != "checked
and found nothing" distinction (see joebot/data/health.py).
"""
from __future__ import annotations

import datetime as dt
import sys
import traceback
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


class Result:
    def __init__(self, name: str, status: str, detail: str, required: bool):
        self.name = name
        self.status = status
        self.detail = detail
        self.required = required


def _run(name: str, required: bool, fn) -> Result:
    try:
        detail = fn()
        return Result(name, PASS, detail, required)
    except _Skip as exc:
        return Result(name, SKIP, str(exc), required)
    except Exception as exc:
        return Result(name, FAIL, f"{type(exc).__name__}: {exc}", required)


class _Skip(Exception):
    pass


def check_market_data() -> str:
    from joebot.data import market_data

    ticker = "AAPL"
    df = market_data.fetch_price_history(ticker, lookback_days=30)
    if df is None or df.empty:
        raise AssertionError(f"empty price history for {ticker}")
    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise AssertionError(f"missing expected columns: {missing}")
    cap = market_data.fetch_market_cap(ticker)
    name = market_data.fetch_company_name(ticker)
    return f"{len(df)} rows for {ticker}; market_cap={cap}; company_name={name!r}"


def check_sec() -> str:
    from joebot.data import sec_client

    if "your-email" in settings.SEC_USER_AGENT or "your-real-email" in settings.SEC_USER_AGENT:
        raise _Skip("SEC_USER_AGENT in .env still has the placeholder email -- set it to a real contact address first")

    ticker = "AAPL"
    as_of = dt.date.today()

    snapshot = sec_client.fetch_fundamental_snapshot(ticker)
    if snapshot.revenue_latest is None:
        raise AssertionError(
            "fetch_fundamental_snapshot returned no revenue figure for AAPL -- "
            "EntityFacts.to_dataframe()'s schema may have changed again; see sec_client.py"
        )

    filings = sec_client.fetch_ownership_filings(ticker, as_of, lookback_days=3650)
    filer_names = [f.filer_name for f in filings if f.filer_name]

    events_8k = sec_client.fetch_8k_leadership_events(ticker, as_of, lookback_days=3650)

    return (
        f"revenue_latest={snapshot.revenue_latest:,.0f}; "
        f"{len(filings)} SC 13D/13G filings found ({len(filer_names)} with a resolved filer name); "
        f"{len(events_8k)} 8-K Item 5.02 filings found in the last 10y"
    )


def check_clinicaltrials() -> str:
    from joebot.data import clinicaltrials_client

    trials = clinicaltrials_client.fetch_trials_for_sponsor("Pfizer")
    if not trials:
        raise AssertionError("no trials returned for sponsor 'Pfizer' -- expected many; check query.spons param/response shape")
    return f"{len(trials)} trials found for sponsor 'Pfizer'; sample phase={trials[0].phase!r} status={trials[0].status!r}"


def check_usaspending() -> str:
    from joebot.data import gov_contracts_client

    awards = gov_contracts_client.fetch_recent_contracts("Lockheed Martin", dt.date.today(), lookback_days=3650)
    if not awards:
        raise AssertionError("no contract awards returned for 'Lockheed Martin' -- expected many; check recipient_search_text/field names")
    return f"{len(awards)} awards found for 'Lockheed Martin'; most recent amount=${awards[0].amount or 0:,.0f}"


def check_patents() -> str:
    from joebot.data import patents_client

    if not _env("PATENTSVIEW_API_KEY"):
        raise _Skip("PATENTSVIEW_API_KEY not set in .env -- register at https://patentsview.org/apis/keyrequest")

    patents = patents_client.fetch_patents_for_assignee("International Business Machines Corporation", dt.date.today(), lookback_days=3650)
    if not patents:
        raise AssertionError("no patents returned for IBM -- expected thousands; check query/field names")
    return f"{len(patents)} patents found for IBM in the lookback window"


def check_reddit() -> str:
    from joebot.data import reddit_client

    if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
        raise _Skip("REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set in .env -- create an app at https://www.reddit.com/prefs/apps")

    mentions = reddit_client.fetch_mentions("GME", dt.date.today(), lookback_days=30)
    return f"{len(mentions)} mentions found for GME in the last 30 days (0 is plausible, not necessarily a failure)"


def _env(key: str) -> str:
    import os

    return os.environ.get(key, "")


CHECKS = [
    ("Market data (yfinance)", True, check_market_data),
    ("SEC EDGAR (edgartools)", True, check_sec),
    ("ClinicalTrials.gov", False, check_clinicaltrials),
    ("USAspending.gov", False, check_usaspending),
    ("Patent data (PatentsView)", False, check_patents),
    ("Reddit", False, check_reddit),
]


def main() -> int:
    print(f"JoeBot live data validation -- {dt.datetime.now().isoformat(timespec='seconds')}\n")
    results = []
    for name, required, fn in CHECKS:
        print(f"Checking {name} ...", end=" ", flush=True)
        r = _run(name, required, fn)
        print(r.status)
        if r.status == FAIL:
            print(f"  -> {r.detail}")
        results.append(r)
    print()

    print(f"{'Source':<28}{'Required':<10}{'Result':<8}Detail")
    print("-" * 100)
    for r in results:
        req = "yes" if r.required else "optional"
        print(f"{r.name:<28}{req:<10}{r.status:<8}{r.detail}")

    required_failures = [r for r in results if r.required and r.status == FAIL]
    optional_failures = [r for r in results if not r.required and r.status == FAIL]
    skipped = [r for r in results if r.status == SKIP]

    print()
    if required_failures:
        print(f"RESULT: FAIL -- {len(required_failures)} required source(s) failed. JoeBot's core pipeline cannot run reliably until these are fixed.")
    elif optional_failures:
        print(f"RESULT: PASS with warnings -- {len(optional_failures)} optional source(s) failed (not blocking, but those signals will silently look like 'no evidence' unless you check joebot/data/health.py's status). {len(skipped)} not configured.")
    else:
        print(f"RESULT: PASS -- all required sources verified live. {len(skipped)} optional source(s) not configured (expected unless you set up their credentials).")

    return 1 if required_failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("\nUnexpected error running the validation script itself:")
        traceback.print_exc()
        sys.exit(2)
