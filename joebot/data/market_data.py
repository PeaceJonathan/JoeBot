"""Price/volume data access. yfinance is primary (free, no key); if a
FINNHUB_API_KEY is configured, Finnhub is used as a fallback when yfinance
fails for a given ticker, since yfinance is an unofficial API that Yahoo can
block or change without notice.

Every fetch is cached to disk so repeated runs / a full universe scan don't
re-hit external services for data that doesn't change intraday.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
import requests
import yfinance as yf

from config import settings
from joebot.data.cache import DiskCache, market_data_rate_limiter

log = logging.getLogger(__name__)

_price_cache = DiskCache(namespace="prices", ttl_seconds=6 * 3600)
_info_cache = DiskCache(namespace="info", ttl_seconds=24 * 3600)


class MarketDataError(Exception):
    """Raised when no data source could provide data for a ticker."""


def fetch_price_history(ticker: str, lookback_days: int = settings.LOOKBACK_DAYS) -> pd.DataFrame:
    """Return a DataFrame of daily OHLCV for `ticker`, indexed by date (ascending).

    Columns: open, high, low, close, volume. Raises MarketDataError if no
    source could return data (does not raise on ordinary empty results for
    e.g. a delisted ticker -- caller should check for an empty DataFrame too).
    """
    cache_key = f"{ticker}_{lookback_days}"
    cached = _price_cache.get(cache_key)
    if cached is not None:
        df = pd.DataFrame(cached)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df

    df = _fetch_from_yfinance(ticker, lookback_days)
    if df is None or df.empty:
        df = _fetch_from_finnhub(ticker, lookback_days)

    if df is None:
        raise MarketDataError(f"No price data source returned data for {ticker!r}")

    to_store = df.reset_index().rename(columns={"index": "date", "Date": "date"})
    to_store["date"] = to_store["date"].astype(str)
    _price_cache.set(cache_key, to_store.to_dict(orient="records"))
    return df


def fetch_price_history_covering(
    ticker: str, as_of_date: dt.date, trailing_days: int = settings.LOOKBACK_DAYS
) -> pd.DataFrame:
    """Price history guaranteed to cover [as_of_date - trailing_days, as_of_date],
    even when as_of_date is well in the past.

    fetch_price_history's lookback_days always counts back from *today*
    (yfinance fetches a trailing window ending now) -- a plain call with the
    default ~1-year lookback would silently return no data at all for an
    as_of_date from a multi-year-old backtest window, since that window
    wouldn't even be inside the fetched range. This computes how far in the
    past as_of_date itself is and extends the lookback to compensate, so
    every signal and the backtester's point_in_time module can share one
    fetch path regardless of whether as_of_date is today or years ago.
    """
    days_since_as_of = max(0, (dt.date.today() - as_of_date).days)
    lookback_days = trailing_days + days_since_as_of
    return fetch_price_history(ticker, lookback_days=lookback_days)


def _fetch_from_yfinance(ticker: str, lookback_days: int) -> pd.DataFrame | None:
    try:
        market_data_rate_limiter.wait()
        hist = yf.Ticker(ticker).history(period=f"{lookback_days}d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        hist = hist.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        hist.index.name = "date"
        return hist
    except Exception as exc:  # yfinance can raise a variety of network/parse errors
        log.warning("yfinance failed for %s: %s", ticker, exc)
        return None


def _fetch_from_finnhub(ticker: str, lookback_days: int) -> pd.DataFrame | None:
    if not settings.FINNHUB_API_KEY:
        return None
    try:
        import time

        market_data_rate_limiter.wait()
        end = int(time.time())
        start = end - lookback_days * 86400
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={
                "symbol": ticker,
                "resolution": "D",
                "from": start,
                "to": end,
                "token": settings.FINNHUB_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("s") != "ok":
            return None
        df = pd.DataFrame(
            {
                "open": payload["o"],
                "high": payload["h"],
                "low": payload["l"],
                "close": payload["c"],
                "volume": payload["v"],
            },
            index=pd.to_datetime(payload["t"], unit="s"),
        )
        df.index.name = "date"
        return df
    except Exception as exc:
        log.warning("Finnhub fallback failed for %s: %s", ticker, exc)
        return None


def fetch_market_cap(ticker: str) -> float | None:
    """Best-effort current market cap; returns None if unavailable."""
    cached = _info_cache.get(ticker)
    if cached is not None:
        return cached.get("market_cap")

    market_cap = None
    try:
        market_data_rate_limiter.wait()
        info = yf.Ticker(ticker).get_info()
        market_cap = info.get("marketCap")
    except Exception as exc:
        log.warning("Failed to fetch market cap for %s: %s", ticker, exc)

    _info_cache.set(ticker, {"market_cap": market_cap})
    return market_cap
