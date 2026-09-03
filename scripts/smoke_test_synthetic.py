#!/usr/bin/env python3
"""Full-pipeline synthetic smoke test -- exercises the whole scan ->
persist -> narrative -> Data Health -> budget-allocation path against
fixture data with every external network call monkeypatched out.

WHY THIS SCRIPT EXISTS: it CANNOT verify that any live API's response
shape matches what the code expects (see scripts/validate_live_data.py for
that). What it verifies is architectural: that a full scan run with
several sources succeeding and several failing/unconfigured doesn't crash
anywhere from the composite screener through persistence, the narrative
"why now"/bear-case/event-timeline builder, the Data Health snapshot, and
the budget allocator -- i.e. the plumbing is sound even before any one
pipe's real contents are confirmed. Run this after any change to the
signal/screener/reporting/storage layers as a fast (~1s, no network)
regression check; run scripts/validate_live_data.py separately for the
live-data question.

Usage:
    python scripts/smoke_test_synthetic.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

AS_OF = dt.date.today()


def _synthetic_price_history(ticker: str, lookback_days: int = 400) -> pd.DataFrame:
    # Deterministic per-ticker "random" walk so different tickers get
    # different (but reproducible) technical signal outcomes.
    seed = sum(ord(c) for c in ticker)
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=AS_OF, periods=lookback_days, freq="D")
    returns = rng.normal(0.001, 0.02, size=lookback_days)
    close = 20 * np.cumprod(1 + returns)
    df = pd.DataFrame({
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": rng.integers(200_000, 5_000_000, size=lookback_days),
    }, index=dates)
    df.index.name = "date"
    return df


def main() -> None:
    from joebot.data import clinicaltrials_client, gov_contracts_client, health, patents_client, reddit_client, sec_client
    from joebot.data import market_data
    from joebot import pipeline
    from joebot.reporting.narrative import build_event_feed, build_narrative
    from joebot.risk.position_sizing import allocate_budget
    from joebot.risk.profile import get_risk_profile
    from joebot.screener.composite import apply_risk_filter
    from joebot.storage.queries import latest_candidates, latest_data_health

    print("=== JoeBot synthetic pipeline smoke test (no network) ===\n")

    patches = [
        mock.patch.object(market_data, "fetch_price_history_covering", side_effect=lambda t, d, trailing_days=400: _synthetic_price_history(t)),
        mock.patch.object(market_data, "fetch_market_cap", return_value=800_000_000.0),
        mock.patch.object(market_data, "fetch_company_name", side_effect=lambda t: f"{t} Corp"),
        mock.patch.object(sec_client, "fetch_fundamental_snapshot", return_value=sec_client.FundamentalSnapshot(revenue_latest=120e6, revenue_prior=90e6, cash=40e6)),
        mock.patch.object(sec_client, "fetch_ownership_filings", side_effect=lambda t, d, lookback_days=180: (
            [sec_client.FilingEvent(ticker=t, form="SC 13D", filing_date=AS_OF - dt.timedelta(days=3), accession_no=f"acc-{t}-13d", filer_name="Example Activist Fund LP")]
            if t == "GPRO" else []
        )),
        mock.patch.object(sec_client, "fetch_8k_leadership_events", side_effect=lambda t, d, lookback_days=180: (
            [sec_client.FilingEvent(ticker=t, form="8-K", filing_date=AS_OF - dt.timedelta(days=10), accession_no=f"acc-{t}-8k", items=("5.02",))]
            if t == "PTON" else []
        )),
        mock.patch.object(clinicaltrials_client, "fetch_trials_for_sponsor", side_effect=lambda sponsor: (
            [clinicaltrials_client.TrialSnapshot(nct_id="NCT99999999", phase="PHASE3", status="RECRUITING", last_update_date=AS_OF - dt.timedelta(days=5))]
            if "Axsome" in sponsor else []
        )),
        mock.patch.object(gov_contracts_client, "fetch_recent_contracts", side_effect=lambda name, d, lookback_days=365: (
            [gov_contracts_client.ContractAward(award_id="AW1", recipient_name=name, amount=45_000_000, award_date=AS_OF - dt.timedelta(days=15), awarding_agency="Department of Defense", description="C-UAS systems")]
            if "KTOS" in name or "Kratos" in name else []
        )),
        # Patents and Reddit deliberately left as "not configured" (no key/creds patched in) --
        # this exercises the NOT_CONFIGURED path through Data Health end-to-end.
    ]

    # The patches above replace each client's PUBLIC function (the correct
    # boundary for a plumbing test), which bypasses the internal
    # "_uncached" functions where joebot/data/health.py's
    # record_success/record_failure calls actually live (see
    # market_data._fetch_from_yfinance, sec_client's _fetch_*_uncached).
    # pipeline.run_daily_scan() calls health.reset() as its first step, so
    # seed the two sources being exercised with a fake success from inside
    # a no-op'd reset -- this keeps the Data Health round-trip below
    # meaningful without actually hitting the network. NOT_CONFIGURED for
    # Reddit/PatentsView is untouched and genuinely exercises that path,
    # since those two clients were never monkeypatched at all.
    def _seed_health_instead_of_reset() -> None:
        health.record_success(health.MARKET_DATA, detail="synthetic smoke test")
        health.record_success(health.SEC, detail="synthetic smoke test")

    patches.append(mock.patch.object(pipeline.health, "reset", side_effect=_seed_health_instead_of_reset))

    for p in patches:
        p.start()
    try:
        candidates = pipeline.run_daily_scan(AS_OF)
    finally:
        for p in patches:
            p.stop()

    print(f"Scanned {len(candidates)} candidates across active sectors.\n")
    assert len(candidates) > 0, "no candidates scored -- universe or screener is broken"

    print("--- Data Health snapshot (in-process, this run) ---")
    for source, h in health.snapshot().items():
        print(f"  {h.emoji} {h.display_name:<28}{h.status:<16}{h.detail or ''}")
    assert health.get_status(health.MARKET_DATA).status == health.OK
    assert health.get_status(health.SEC).status == health.OK
    assert health.get_status(health.REDDIT).status == health.NOT_CONFIGURED

    print("\n--- Persisted Data Health (via storage/queries, simulating dashboard read) ---")
    run, db_health = latest_data_health()
    assert run is not None
    for r in db_health:
        print(f"  {r.source:<16}{r.status:<16}{r.detail or ''}")
    assert any(r.source == health.MARKET_DATA and r.status == health.OK for r in db_health)

    print("\n--- Top 3 candidates: full narrative ---")
    for c in candidates[:3]:
        card = build_narrative(c)
        print(f"\n### {card.ticker} ({card.sector}) -- {card.composite_score * 100:.0f}/100 -- {card.verdict}")
        print("Why now:")
        for b in card.why_bullets:
            print(f"  - {b}")
        print("Bear case:")
        for b in card.risk_bullets[:3]:
            print(f"  - {b}")
        if card.data_gap_bullets:
            print("Data gaps:")
            for b in card.data_gap_bullets:
                print(f"  - {b}")
        if card.timeline:
            print("Timeline:")
            for t in card.timeline:
                print(f"  - {t}")

    print("\n--- Catalysts feed (cross-candidate) ---")
    feed = build_event_feed(candidates, lookback_days=365)
    for date, ticker, desc in feed[:10]:
        print(f"  {date}  {ticker:<8}{desc}")
    assert feed, "expected at least one dated event from the GPRO/PTON/KTOS/AXSM fixtures"

    print("\n--- Risk slider + budget allocation ---")
    for slider in (0, 50, 100):
        profile = get_risk_profile(slider)
        filtered = apply_risk_filter(candidates, profile)
        ranked_tuples = [
            (c.ticker, c.signal_results["technical_breakout"].metadata.get("close"), c.signal_results["technical_breakout"].metadata.get("atr"), c.composite_score)
            for c in filtered if "technical_breakout" in c.signal_results
        ]
        allocation = allocate_budget(ranked_tuples, budget=10_000.0, risk_profile=profile)
        print(f"  slider={slider:>3} ({profile.name:<12}) -- {len(filtered)}/{len(candidates)} pass filter, "
              f"${allocation.allocated:,.2f} allocated, ${allocation.reserved_cash:,.2f} reserved")

    print("\n--- Dashboard query layer round-trip ---")
    run2, views = latest_candidates()
    assert run2 is not None and len(views) == len(candidates)
    reconstructed = views[0].to_ranked_candidate()
    assert reconstructed.as_of_date == AS_OF, "as_of_date didn't round-trip through the DB"
    build_narrative(reconstructed)  # must not raise

    print("\n=== ALL SMOKE TEST ASSERTIONS PASSED ===")
    print("Reminder: this used SYNTHETIC/FIXTURE data throughout, not live API responses.")
    print("Run `python scripts/validate_live_data.py` on a machine with normal internet")
    print("access before trusting this codebase's output against real markets.")


if __name__ == "__main__":
    main()
