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
import time

import pandas as pd
import requests
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from config import settings
from joebot.data import health
from joebot.data.cache import DiskCache, market_data_rate_limiter

log = logging.getLogger(__name__)

_price_cache = DiskCache(namespace="prices", ttl_seconds=6 * 3600)
_info_cache = DiskCache(namespace="info", ttl_seconds=24 * 3600)
_insider_cache = DiskCache(namespace="insider_transactions", ttl_seconds=24 * 3600)

# Scanning a full sector universe means dozens of tickers x several
# yfinance calls each (history, info, insider transactions) in one run.
# yfinance's own client raises YFRateLimitError on an HTTP 429 from Yahoo
# (confirmed by reading yfinance/data.py directly) well before this
# process's own market_data_rate_limiter pacing necessarily helps -- Yahoo's
# real limit is undocumented and can be tighter than our client-side cap.
# Retried here with backoff since a 429 is transient (unlike "bad ticker"),
# and until this existed, a rate-limit mid-scan silently ate wide swaths of
# the universe: every ticker after the limit kicked in just failed and got
# dropped by joebot/screener/sector_screens.py's per-ticker exception
# handling, with no visible explanation of why so few candidates came back.
_RATE_LIMIT_RETRY_DELAYS = (5, 15, 30)  # seconds; 3 attempts total


def _call_with_rate_limit_retry(fn):
    """Runs fn() (a zero-arg thunk), retrying on YFRateLimitError with
    increasing backoff. Re-raises the last error if every attempt fails."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0, *_RATE_LIMIT_RETRY_DELAYS)):
        if delay:
            log.warning("Rate-limited by Yahoo Finance -- waiting %ds before retry %d/%d", delay, attempt, len(_RATE_LIMIT_RETRY_DELAYS))
            time.sleep(delay)
        try:
            return fn()
        except YFRateLimitError as exc:
            last_exc = exc
            continue
    raise last_exc


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
        hist = _call_with_rate_limit_retry(lambda: yf.Ticker(ticker).history(period=f"{lookback_days}d", auto_adjust=True))
        if hist is None or hist.empty:
            # A clean empty response (not an exception) is a real "no data
            # for this ticker" -- e.g. a bad symbol -- not a source outage.
            health.record_success(health.MARKET_DATA, detail="empty response")
            return None
        hist = hist.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        hist.index.name = "date"
        health.record_success(health.MARKET_DATA)
        return hist
    except Exception as exc:  # yfinance can raise a variety of network/parse errors
        log.warning("yfinance failed for %s: %s", ticker, exc)
        health.record_failure(health.MARKET_DATA, detail=str(exc))
        return None


def _fetch_from_finnhub(ticker: str, lookback_days: int) -> pd.DataFrame | None:
    if not settings.FINNHUB_API_KEY:
        # Only a fallback for yfinance, and yfinance already recorded its
        # own failure -- don't overwrite that with "not configured", which
        # would hide a real yfinance outage behind an unrelated message.
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
        # Recovered via the fallback -- overall market-data availability is
        # OK even though yfinance itself just failed for this ticker.
        health.record_success(health.MARKET_DATA, detail="finnhub fallback")
        return df
    except Exception as exc:
        log.warning("Finnhub fallback failed for %s: %s", ticker, exc)
        health.record_failure(health.MARKET_DATA, detail=f"finnhub fallback: {exc}")
        return None


def _fetch_info(ticker: str) -> dict:
    """Cached yfinance `.get_info()` payload -- market cap and company name
    both come from this one call, so both accessors below share the cache
    entry instead of double-fetching."""
    cached = _info_cache.get(ticker)
    if cached is not None:
        return cached

    market_cap = None
    company_name = None
    try:
        market_data_rate_limiter.wait()
        info = _call_with_rate_limit_retry(lambda: yf.Ticker(ticker).get_info())
        market_cap = info.get("marketCap")
        company_name = info.get("longName") or info.get("shortName")
        health.record_success(health.MARKET_DATA)
    except Exception as exc:
        log.warning("Failed to fetch info for %s: %s", ticker, exc)
        health.record_failure(health.MARKET_DATA, detail=str(exc))

    result = {"market_cap": market_cap, "company_name": company_name}
    _info_cache.set(ticker, result)
    return result


def fetch_market_cap(ticker: str) -> float | None:
    """Best-effort current market cap; returns None if unavailable."""
    return _fetch_info(ticker).get("market_cap")


def fetch_company_name(ticker: str) -> str | None:
    """Best-effort company legal/display name (e.g. for matching against
    SEC filer names, USAspending.gov recipient names, or patent assignee
    names) -- returns None if unavailable rather than guessing from the
    ticker symbol."""
    return _fetch_info(ticker).get("company_name")


def fetch_insider_transactions(ticker: str) -> list[dict]:
    """Recent Form-4-derived insider transactions (Yahoo's aggregated feed,
    not a raw SEC parse) for the insider_buying signal.

    Column names below (Start Date, Insider, Position, Text, Shares, Value,
    Ownership) match yfinance's Holders._parse_insider_transactions exactly
    -- confirmed by reading yfinance/scrapers/holders.py directly (this
    package is installed locally even though this environment can't reach
    Yahoo's servers to actually call it; see market_data.py's module note
    and scripts/validate_live_data.py), not guessed. "Text" is Yahoo's free
    -text transaction description (e.g. "Purchase at price X", "Sale at
    price X", "Option Exercise") -- there's no separate structured
    transaction-code field, so the insider_buying signal matches on that
    text rather than the SEC Form 4 transaction code (P/S/A/M/etc.)
    directly, which this feed doesn't expose.

    Returns [] if yfinance has nothing for this ticker or the call fails --
    never raises. Each dict: {"start_date" (ISO), "insider", "position",
    "text", "shares", "value", "ownership"}.
    """
    cached = _insider_cache.get(ticker)
    if cached is not None:
        return cached

    result: list[dict] = []
    try:
        market_data_rate_limiter.wait()
        df = _call_with_rate_limit_retry(lambda: yf.Ticker(ticker).get_insider_transactions())
        health.record_success(health.MARKET_DATA)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                start_date = row.get("Start Date")
                result.append({
                    "start_date": start_date.date().isoformat() if pd.notna(start_date) else None,
                    "insider": row.get("Insider"),
                    "position": row.get("Position"),
                    "text": row.get("Text"),
                    "shares": row.get("Shares"),
                    "value": row.get("Value"),
                    "ownership": row.get("Ownership"),
                })
    except Exception as exc:
        log.warning("Failed to fetch insider transactions for %s: %s", ticker, exc)
        health.record_failure(health.MARKET_DATA, detail=str(exc))
        return []

    _insider_cache.set(ticker, result)
    return result
