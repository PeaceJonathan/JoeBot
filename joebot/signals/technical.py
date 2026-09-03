"""Technical breakout indicators computed from OHLCV history.

Each function here is a pure computation on a price DataFrame (easy to unit
test against hand-computed values); TechnicalBreakoutSignal wires them
together into the Signal interface for the screener/backtester.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from config import settings
from joebot.data import health, market_data
from joebot.signals.base import SignalResult, with_source_status


def pct_below_52wk_high(prices: pd.Series) -> float:
    """0.0 = at or above the 52-week high, larger = further below it."""
    window = prices.tail(252)
    high = window.max()
    if high <= 0:
        return float("nan")
    return float((high - prices.iloc[-1]) / high)


def volume_surge_ratio(volume: pd.Series, window: int = settings.VOLUME_SURGE_WINDOW) -> float:
    """Today's volume divided by the trailing `window`-day average (excluding today)."""
    if len(volume) < window + 1:
        return float("nan")
    avg = volume.iloc[-(window + 1):-1].mean()
    if avg <= 0:
        return float("nan")
    return float(volume.iloc[-1] / avg)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = settings.ATR_PERIOD) -> pd.Series:
    """Average True Range (Wilder's smoothing) as a pandas Series aligned to input index."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = settings.RSI_PERIOD) -> pd.Series:
    """Wilder's RSI as a pandas Series aligned to input index."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.where(avg_loss != 0, 100.0)


def ma_crossover_bullish(
    close: pd.Series, fast: int = settings.MA_FAST, slow: int = settings.MA_SLOW
) -> bool | None:
    """True if the fast MA is above the slow MA (a 'golden cross' regime); None if insufficient history."""
    if len(close) < slow:
        return None
    fast_ma = close.rolling(fast).mean().iloc[-1]
    slow_ma = close.rolling(slow).mean().iloc[-1]
    if pd.isna(fast_ma) or pd.isna(slow_ma):
        return None
    return bool(fast_ma > slow_ma)


class TechnicalBreakoutSignal:
    name = "technical_breakout"

    @with_source_status(health.MARKET_DATA)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        try:
            df = market_data.fetch_price_history_covering(ticker, as_of_date)
        except market_data.MarketDataError as exc:
            return SignalResult(score=0.0, confidence=0.0, metadata={"error": str(exc)})

        if df.empty:
            return SignalResult(score=0.0, confidence=0.0, metadata={"error": "no price history"})

        df = df[df.index.date <= as_of_date]
        if df.empty:
            return SignalResult(score=0.0, confidence=0.0, metadata={"error": "no data as of date"})

        close_near_high = pct_below_52wk_high(df["close"])
        vol_surge = volume_surge_ratio(df["volume"])
        atr_series = atr(df["high"], df["low"], df["close"])
        rsi_series = rsi(df["close"])
        golden_cross = ma_crossover_bullish(df["close"])

        latest_atr = atr_series.iloc[-1] if not atr_series.empty else np.nan
        latest_rsi = rsi_series.iloc[-1] if not rsi_series.empty else np.nan
        latest_close = df["close"].iloc[-1]
        atr_pct_of_price = float(latest_atr / latest_close) if pd.notna(latest_atr) and latest_close else None

        # Avg dollar volume and market cap: liquidity/size metrics the risk
        # profile (joebot/risk) filters candidates on. Stored here in
        # metadata (persisted to signals_history) rather than re-fetched by
        # every consumer, so the dashboard can re-filter by risk slider
        # against already-persisted data without hitting the network again.
        # market_cap is always *current* (fetch_market_cap has no point-in-time
        # variant), unlike everything else in this signal which is correctly
        # gated to as_of_date. Harmless for a live scan or the dashboard's
        # risk filter (both use as_of_date=today), but this field must never
        # be used inside backtest scoring/attribution -- it isn't today, and
        # joebot/backtest/engine.py doesn't read signal metadata at all, only
        # score/confidence, so this can't leak into a backtest result.
        dollar_volume = (df["close"] * df["volume"]).tail(settings.VOLUME_SURGE_WINDOW)
        avg_dollar_volume = float(dollar_volume.mean()) if not dollar_volume.empty else None
        market_cap = market_data.fetch_market_cap(ticker)

        # Sub-scores, each in [0, 1], simple and interpretable -- real relative
        # weighting across signal families is Phase 3's job, not guessed here.
        proximity_score = (
            max(0.0, 1.0 - close_near_high / 0.15) if pd.notna(close_near_high) else 0.0
        )  # full credit at/near the 52wk high, zero once >15% below it
        volume_score = min(1.0, max(0.0, (vol_surge - 1.0) / 2.0)) if pd.notna(vol_surge) else 0.0
        momentum_score = min(1.0, max(0.0, (latest_rsi - 50) / 30)) if pd.notna(latest_rsi) else 0.0
        trend_score = 1.0 if golden_cross else 0.0 if golden_cross is not None else 0.0

        score = 0.4 * proximity_score + 0.3 * volume_score + 0.2 * momentum_score + 0.1 * trend_score

        known_fields = sum(
            x is not None
            for x in (pd.notna(close_near_high), pd.notna(vol_surge), pd.notna(latest_rsi), golden_cross is not None)
        )
        confidence = known_fields / 4.0

        return SignalResult(
            score=float(score),
            confidence=float(confidence),
            metadata={
                "pct_below_52wk_high": None if pd.isna(close_near_high) else round(float(close_near_high), 4),
                "volume_surge_ratio": None if pd.isna(vol_surge) else round(float(vol_surge), 2),
                "rsi": None if pd.isna(latest_rsi) else round(float(latest_rsi), 1),
                "atr_pct_of_price": None if atr_pct_of_price is None else round(atr_pct_of_price, 4),
                "atr": None if pd.isna(latest_atr) else round(float(latest_atr), 4),
                "avg_dollar_volume": None if avg_dollar_volume is None else round(avg_dollar_volume, 2),
                "market_cap": market_cap,
                "golden_cross": golden_cross,
                "close": round(float(latest_close), 2),
            },
        )
