"""Unit tests for joebot.signals.insider_buying scoring logic, against
fixture transaction data injected via monkeypatch -- no network access.
"""
import datetime as dt

import pytest

from joebot.data import market_data
from joebot.signals.insider_buying import InsiderBuyingSignal, _is_open_market_purchase

AS_OF = dt.date(2026, 6, 1)


def _txn(days_ago, text="Purchase at price 10.00", insider="Jane Doe", value=100_000, shares=10_000):
    return {
        "start_date": (AS_OF - dt.timedelta(days=days_ago)).isoformat(),
        "insider": insider,
        "position": "Officer",
        "text": text,
        "shares": shares,
        "value": value,
        "ownership": "D",
    }


def test_no_transactions_scores_zero(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [])
    result = InsiderBuyingSignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.confidence > 0


def test_only_sales_scores_zero(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [_txn(5, text="Sale at price 10.00")])
    result = InsiderBuyingSignal().score("TEST", AS_OF)
    assert result.score == 0.0


def test_option_exercise_is_excluded(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [_txn(5, text="Option Exercise at price 10.00")])
    result = InsiderBuyingSignal().score("TEST", AS_OF)
    assert result.score == 0.0


def test_recent_purchase_scores_higher_than_stale_purchase(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [_txn(2)])
    recent = InsiderBuyingSignal(lookback_days=90).score("TEST", AS_OF)

    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [_txn(85)])
    stale = InsiderBuyingSignal(lookback_days=90).score("TEST", AS_OF)

    assert recent.score > stale.score


def test_multiple_distinct_insiders_scores_higher_than_one(monkeypatch):
    monkeypatch.setattr(
        market_data, "fetch_insider_transactions",
        lambda ticker: [_txn(2, insider="Jane Doe"), _txn(3, insider="John Roe"), _txn(4, insider="Alex Lee")],
    )
    multi = InsiderBuyingSignal().score("TEST", AS_OF)

    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [_txn(2, insider="Jane Doe")])
    single = InsiderBuyingSignal().score("TEST", AS_OF)

    assert multi.score > single.score
    assert multi.metadata["distinct_insiders"] == 3


def test_purchase_outside_lookback_window_excluded(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_insider_transactions", lambda ticker: [_txn(200)])
    result = InsiderBuyingSignal(lookback_days=90).score("TEST", AS_OF)
    assert result.score == 0.0


def test_total_value_summed_in_metadata(monkeypatch):
    monkeypatch.setattr(
        market_data, "fetch_insider_transactions",
        lambda ticker: [_txn(2, value=100_000), _txn(3, value=50_000)],
    )
    result = InsiderBuyingSignal().score("TEST", AS_OF)
    assert result.metadata["total_value"] == 150_000


@pytest.mark.parametrize("text,expected", [
    ("Purchase at price 12.50", True),
    ("Sale at price 12.50", False),
    ("Option Exercise at price 12.50", False),
    ("Stock Gift", False),
    ("Tax withholding", False),
    (None, False),
    ("", False),
])
def test_is_open_market_purchase(text, expected):
    assert _is_open_market_purchase(text) is expected
