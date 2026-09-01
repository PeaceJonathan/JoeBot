"""Unit tests for the backtester's point-in-time forward-return logic --
the single most safety-critical piece of the backtest engine (a bug here
means silent look-ahead bias or a survivorship-bias leak). All network
access is stubbed via monkeypatch; these are pure logic tests.
"""
import dataclasses
import datetime as dt

import pandas as pd
import pytest

from joebot.backtest import point_in_time
from joebot.data import market_data


def _price_df(dates_and_closes):
    dates = [d for d, _ in dates_and_closes]
    closes = [c for _, c in dates_and_closes]
    idx = pd.DatetimeIndex(dates)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=idx,
    )


def test_forward_return_hand_computed(monkeypatch):
    df = _price_df([
        (dt.date(2026, 1, 1), 100.0),
        (dt.date(2026, 1, 2), 110.0),
        (dt.date(2026, 1, 3), 121.0),
    ])
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: df)

    result = point_in_time.forward_return("TEST", dt.date(2026, 1, 1), horizon_days=2)
    # entry=100 at day1, exit=121 at day1+2=day3 -> (121-100)/100 = 0.21
    assert result == pytest.approx(0.21)


def test_forward_return_none_when_data_gap_too_large(monkeypatch):
    df = _price_df([
        (dt.date(2026, 1, 1), 100.0),
        (dt.date(2026, 1, 2), 105.0),
        # nothing after day 2 -- simulates a feed that just stopped
    ])
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: df)

    # horizon 60 days but data stops after day 2: far short of day1+60 -> unknown, not 0%
    result = point_in_time.forward_return("TEST", dt.date(2026, 1, 1), horizon_days=60)
    assert result is None


def test_forward_return_none_when_entry_before_any_data(monkeypatch):
    df = _price_df([(dt.date(2026, 3, 1), 50.0)])
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: df)

    result = point_in_time.forward_return("TEST", dt.date(2026, 1, 1), horizon_days=10)
    assert result is None


def test_forward_return_empty_history_returns_none(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: pd.DataFrame())
    result = point_in_time.forward_return("TEST", dt.date(2026, 1, 1), horizon_days=10)
    assert result is None


@dataclasses.dataclass
class _FakeDelistedEntry:
    ticker: str
    sector: str
    company_name: str
    active_from: dt.date
    active_to: dt.date
    event_type: str
    notes: str = ""


def test_forward_return_bankruptcy_is_total_loss(monkeypatch):
    # Even if stale price data exists, a known bankruptcy within the window
    # must override it with a -100% realized loss, not a stale-price return.
    df = _price_df([(dt.date(2026, 1, 1), 10.0)])
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: df)

    entry = dt.date(2026, 1, 1)
    delisting = _FakeDelistedEntry(
        ticker="TEST", sector="tech", company_name="Test Co",
        active_from=dt.date(2020, 1, 1), active_to=dt.date(2026, 2, 1),
        event_type="bankruptcy",
    )
    result = point_in_time.forward_return("TEST", entry, horizon_days=60, delisting_info=delisting)
    assert result == -1.0


def test_forward_return_non_bankruptcy_delisting_is_unknown(monkeypatch):
    df = _price_df([(dt.date(2026, 1, 1), 10.0)])
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: df)

    entry = dt.date(2026, 1, 1)
    delisting = _FakeDelistedEntry(
        ticker="TEST", sector="tech", company_name="Test Co",
        active_from=dt.date(2020, 1, 1), active_to=dt.date(2026, 2, 1),
        event_type="delisted_other",
    )
    result = point_in_time.forward_return("TEST", entry, horizon_days=60, delisting_info=delisting)
    assert result is None


def test_forward_return_delisting_after_exit_target_ignored(monkeypatch):
    # If the delisting happens well after the exit target, it shouldn't
    # affect this particular forward-return calculation at all.
    df = _price_df([
        (dt.date(2026, 1, 1), 100.0),
        (dt.date(2026, 1, 3), 110.0),
    ])
    monkeypatch.setattr(market_data, "fetch_price_history_covering", lambda ticker, as_of_date, trailing_days=365: df)

    entry = dt.date(2026, 1, 1)
    delisting = _FakeDelistedEntry(
        ticker="TEST", sector="tech", company_name="Test Co",
        active_from=dt.date(2020, 1, 1), active_to=dt.date(2030, 1, 1),
        event_type="bankruptcy",
    )
    result = point_in_time.forward_return("TEST", entry, horizon_days=2, delisting_info=delisting)
    assert result == pytest.approx(0.10)
