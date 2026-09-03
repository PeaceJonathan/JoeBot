"""Unit tests for joebot.backtest.engine.run_walk_forward's resilience.

Regression test for a real bug found by actually running
scripts/run_backtest.py in an environment where every price-data call
fails (see the module-level note in engine.py): point_in_time.forward_return
can raise MarketDataError, and until this was fixed, that exception was
uncaught inside run_walk_forward's loop -- so the very first ticker with no
price data anywhere (a bad symbol, a genuine multi-source outage) crashed
the entire multi-hour walk-forward run, rather than being treated as an
unknown/dropped observation the way a single failing signal already is.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from joebot.backtest import engine, universe_builder
from joebot.data import market_data
from joebot.signals.base import SignalResult

START = dt.date(2020, 1, 1)
END = dt.date(2022, 6, 1)  # wide enough for the 504-day long horizon


class _AlwaysZeroSignal:
    name = "zero_signal"

    def score(self, ticker, as_of_date):
        return SignalResult(score=0.0, confidence=1.0, metadata={})


def _full_range_price_df(seed_price: float) -> pd.DataFrame:
    # Covers the whole test window regardless of the caller's as_of_date/
    # trailing_days -- forward_return() filters this down itself via
    # entry_date/exit_target, so a full-range fixture is simpler and more
    # realistic than trying to replicate fetch_price_history_covering's own
    # lookback-window math in a mock.
    idx = pd.date_range(start=START - dt.timedelta(days=30), end=END + dt.timedelta(days=600), freq="D")
    closes = [seed_price] * len(idx)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(idx)},
        index=idx,
    )


def test_run_walk_forward_survives_a_ticker_with_no_price_data_anywhere(monkeypatch):
    monkeypatch.setattr(universe_builder, "universe_as_of", lambda as_of_date: {"synthetic": ["BADTICKER", "GOODTICKER"]})
    monkeypatch.setattr(universe_builder, "delisting_lookup", lambda: {})

    good_df = _full_range_price_df(100.0)

    def _fetch(ticker, as_of_date, trailing_days=400):
        if ticker == "BADTICKER":
            # The real failure mode: every source exhausted, raises rather
            # than returning an empty DataFrame.
            raise market_data.MarketDataError(f"No price data source returned data for {ticker!r}")
        return good_df

    monkeypatch.setattr(market_data, "fetch_price_history_covering", _fetch)

    # Must not raise -- this is the actual regression being guarded against.
    result = engine.run_walk_forward([_AlwaysZeroSignal()], START, END, step_days=180)

    assert len(result.records) > 0, "GOODTICKER should still produce records even though BADTICKER failed"

    bad_records = [r for r in result.records if r.ticker == "BADTICKER"]
    good_records = [r for r in result.records if r.ticker == "GOODTICKER"]
    assert bad_records, "BADTICKER should still get a record (with unknown forward returns), not be silently dropped"
    assert all(r.forward_return_short is None and r.forward_return_long is None for r in bad_records), (
        "a ticker whose price data failed entirely must have unknown (None) forward returns, "
        "never a fabricated 0% or stale value"
    )
    assert good_records and any(r.forward_return_short is not None for r in good_records)


def test_run_walk_forward_still_raises_on_too_short_a_window():
    with pytest.raises(ValueError):
        engine.run_walk_forward([_AlwaysZeroSignal()], dt.date(2026, 1, 1), dt.date(2026, 2, 1), step_days=30)
