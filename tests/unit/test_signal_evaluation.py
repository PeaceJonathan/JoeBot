"""Unit tests for joebot.backtest.signal_evaluation's median-split attribution."""
import datetime as dt

import pandas as pd
import pytest

from joebot.backtest.signal_evaluation import evaluate


def _row(as_of_date, ticker, signal_name, score, fwd_short):
    return {
        "as_of_date": as_of_date,
        "ticker": ticker,
        "sector": "tech",
        "signal_name": signal_name,
        "score": score,
        "confidence": 1.0,
        "forward_return_short": fwd_short,
        "forward_return_long": None,
    }


def test_evaluate_detects_positive_predictive_signal():
    d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
    rows = [
        # "good_signal": high score always paired with a higher forward return
        _row(d1, "A", "good_signal", score=0.9, fwd_short=0.20),
        _row(d1, "B", "good_signal", score=0.1, fwd_short=-0.05),
        _row(d2, "C", "good_signal", score=0.8, fwd_short=0.15),
        _row(d2, "D", "good_signal", score=0.2, fwd_short=-0.02),
    ]
    df = pd.DataFrame(rows)
    results = evaluate(df, horizon="short")

    assert len(results) == 1
    r = results[0]
    assert r.signal_name == "good_signal"
    assert r.n_observations == 4
    assert r.n_dates == 2
    assert r.top_half_mean_return == pytest.approx((0.20 + 0.15) / 2)
    assert r.bottom_half_mean_return == pytest.approx((-0.05 + -0.02) / 2)
    assert r.spread > 0


def test_evaluate_no_predictive_power_gives_near_zero_spread():
    d1 = dt.date(2026, 1, 1)
    rows = [
        _row(d1, "A", "noise_signal", score=0.9, fwd_short=0.01),
        _row(d1, "B", "noise_signal", score=0.1, fwd_short=0.01),
    ]
    df = pd.DataFrame(rows)
    results = evaluate(df, horizon="short")
    assert results[0].spread == pytest.approx(0.0)


def test_evaluate_drops_missing_returns_from_denominator():
    d1 = dt.date(2026, 1, 1)
    rows = [
        _row(d1, "A", "sig", score=0.9, fwd_short=0.10),
        _row(d1, "B", "sig", score=0.1, fwd_short=None),  # unknown outcome, e.g. delisted -- must be excluded, not zeroed
    ]
    df = pd.DataFrame(rows)
    results = evaluate(df, horizon="short")
    assert results[0].n_observations == 1
    assert results[0].bottom_half_mean_return is None


def test_evaluate_empty_frame_returns_empty_list():
    assert evaluate(pd.DataFrame(), horizon="short") == []
