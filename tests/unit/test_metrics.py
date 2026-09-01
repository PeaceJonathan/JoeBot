"""Unit tests for joebot.backtest.metrics against hand-computed values."""
import pandas as pd
import pytest

from joebot.backtest.metrics import cagr, hit_rate, max_drawdown, sharpe_ratio


def test_cagr_hand_computed():
    # Two periods of +10% each, 2 periods/year -> total growth 1.21 over 1 year -> CAGR = 0.21
    returns = pd.Series([0.10, 0.10])
    assert cagr(returns, periods_per_year=2) == pytest.approx(0.21)


def test_cagr_empty_series_is_none():
    assert cagr(pd.Series([], dtype=float), periods_per_year=12) is None


def test_sharpe_ratio_hand_computed():
    # Constant +5% every period: mean=0.05, population std=0 -> our guard returns None
    # (a genuinely non-zero-variance case instead:)
    returns = pd.Series([0.05, -0.05, 0.05, -0.05])
    # mean=0, std(ddof=0)=0.05 -> sharpe = 0/0.05 * sqrt(12) = 0
    assert sharpe_ratio(returns, periods_per_year=12) == pytest.approx(0.0)


def test_sharpe_ratio_zero_variance_is_none():
    returns = pd.Series([0.05, 0.05, 0.05])
    assert sharpe_ratio(returns, periods_per_year=12) is None


def test_max_drawdown_hand_computed():
    # Wealth path: 1 -> 1.20 -> 0.90 -> 1.05 (returns: +20%, -25%, +16.667%)
    returns = pd.Series([0.20, -0.25, 0.16667])
    # peak wealth 1.20, trough 0.90 -> drawdown = (0.90-1.20)/1.20 = -0.25
    assert max_drawdown(returns) == pytest.approx(-0.25, abs=1e-3)


def test_hit_rate_hand_computed():
    returns = pd.Series([0.01, -0.02, 0.03, -0.01, 0.0])
    # positive: 0.01, 0.03 -> 2 of 5 = 0.4 (0.0 counts as not > 0)
    assert hit_rate(returns) == pytest.approx(0.4)
