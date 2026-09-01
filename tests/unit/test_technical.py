"""Unit tests for joebot.signals.technical against hand-computed values on
small synthetic series -- no network access, fully deterministic."""
import pandas as pd
import pytest

from joebot.signals.technical import (
    atr,
    ma_crossover_bullish,
    pct_below_52wk_high,
    rsi,
    volume_surge_ratio,
)


def test_pct_below_52wk_high_at_high():
    prices = pd.Series([80.0, 90.0, 100.0])
    assert pct_below_52wk_high(prices) == pytest.approx(0.0)


def test_pct_below_52wk_high_below_high():
    prices = pd.Series([100.0, 95.0, 90.0])
    # high=100, last=90 -> (100-90)/100 = 0.10
    assert pct_below_52wk_high(prices) == pytest.approx(0.10)


def test_volume_surge_ratio_hand_computed():
    volume = pd.Series([10, 10, 10, 40])
    # avg of the 3 days before today = 10; today = 40 -> ratio 4.0
    assert volume_surge_ratio(volume, window=3) == pytest.approx(4.0)


def test_volume_surge_ratio_insufficient_history():
    volume = pd.Series([10, 20])
    assert pd.isna(volume_surge_ratio(volume, window=3))


def test_atr_hand_computed():
    high = pd.Series([10.0, 12.0, 11.0, 13.0])
    low = pd.Series([9.0, 10.0, 9.0, 11.0])
    close = pd.Series([9.5, 11.0, 10.0, 12.0])

    result = atr(high, low, close, period=2)

    # Hand-computed True Range: [1, 2.5, 2, 3] (see PR description / plan for derivation)
    # Wilder EWM with alpha=0.5, adjust=False, min_periods=2:
    #   idx1 = 0.5*TR0 + 0.5*TR1 = 0.5*1 + 0.5*2.5 = 1.75
    #   idx2 = 0.5*1.75 + 0.5*2 = 1.875
    #   idx3 = 0.5*1.875 + 0.5*3 = 2.4375
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == pytest.approx(1.75)
    assert result.iloc[2] == pytest.approx(1.875)
    assert result.iloc[3] == pytest.approx(2.4375)


def test_rsi_all_gains_is_100():
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    result = rsi(close, period=3)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_all_losses_is_0():
    close = pd.Series([14.0, 13.0, 12.0, 11.0, 10.0])
    result = rsi(close, period=3)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_ma_crossover_bullish_true():
    close = pd.Series(range(1, 11), dtype=float)  # 1..10
    # fast(3) of last 3 = mean(8,9,10)=9; slow(5) of last 5 = mean(6..10)=8
    assert ma_crossover_bullish(close, fast=3, slow=5) is True


def test_ma_crossover_bullish_false_when_declining():
    close = pd.Series(range(10, 0, -1), dtype=float)  # 10..1
    assert ma_crossover_bullish(close, fast=3, slow=5) is False


def test_ma_crossover_none_when_insufficient_history():
    close = pd.Series([1.0, 2.0, 3.0])
    assert ma_crossover_bullish(close, fast=3, slow=5) is None
