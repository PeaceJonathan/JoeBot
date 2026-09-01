"""Point-in-time data access guardrail for the backtester.

Every signal in joebot/signals already takes an as_of_date and is meant to
respect it: TechnicalBreakoutSignal filters price history to rows on or
before as_of_date; the catalyst_sec signals gate filings by
filing_date <= as_of_date. This module is the walk-forward engine's other
half of that contract -- computing the *realized outcome* (forward return)
strictly after as_of_date, and refusing to fabricate one when the data
can't support it (e.g. a delisting) rather than silently returning a
misleading 0%.

Known gap, stated plainly rather than hidden: fundamental_sanity's XBRL
fact lookup (joebot/data/sec_client.py::fetch_fundamental_snapshot) does
NOT gate by each fact's actual filing/acceptance date -- it returns the two
most recent annual values regardless of as_of_date, because the facts
DataFrame schema this code defensively parses doesn't reliably expose a
filing-acceptance-date column. That signal's backtest attribution therefore
carries a residual look-ahead risk the other three signal families don't
have. Don't paper over this; joebot/backtest/signal_evaluation.py reports
it per-signal so this is visible in every result, not averaged away.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from joebot.data import market_data

# If the last available price bar is more than this many days short of the
# target exit date, treat the forward return as unknown (None) rather than
# using a stale last price -- this is the guard against silently treating
# "the price feed just stopped" (e.g. an un-curated delisting) as a flat
# 0% return, which would be a survivorship-bias leak.
_MIN_DATA_GAP_TOLERANCE_DAYS = 10


def price_as_of(ticker: str, as_of_date: dt.date) -> pd.DataFrame:
    """Full cached price history, hard-filtered to rows on or before as_of_date."""
    df = market_data.fetch_price_history_covering(ticker, as_of_date)
    if df.empty:
        return df
    return df[df.index.date <= as_of_date]


def forward_return(
    ticker: str,
    entry_date: dt.date,
    horizon_days: int,
    delisting_info=None,
) -> float | None:
    """Realized close-to-close return from entry_date to entry_date + horizon_days.

    delisting_info, if given, is a joebot.backtest.universe_builder.DelistedEntry
    for this ticker. If entry_date falls within its active window and the
    delisting happens before the exit target:
      - event_type "bankruptcy" -> a realized -100% return (the modeling
        simplification this project uses for a Chapter 11 filing; real
        recovery rates for common equity in a bankruptcy are usually close
        to zero anyway, but this is a simplification worth knowing about).
      - anything else (e.g. an acquisition) -> None (unknown outcome,
        excluded from evaluation rather than guessed).

    Returns None whenever the outcome can't be determined from available
    data -- callers (signal_evaluation.py) must drop these, not treat them
    as zero.
    """
    exit_target = entry_date + dt.timedelta(days=horizon_days)

    if delisting_info is not None and delisting_info.active_from <= entry_date <= delisting_info.active_to:
        if delisting_info.active_to <= exit_target:
            if delisting_info.event_type == "bankruptcy":
                return -1.0
            return None

    # Fetch a window covering [entry_date, exit_target]. Anchored on
    # exit_target (not entry_date) since fetch_price_history_covering's
    # lookback counts back from *today* -- this assumes exit_target is not
    # in the future relative to today, which the walk-forward engine
    # always guarantees by construction (it leaves horizon_days of room
    # before end_date).
    df = market_data.fetch_price_history_covering(ticker, exit_target, trailing_days=horizon_days + 30)
    if df.empty:
        return None

    entry_rows = df[df.index.date <= entry_date]
    if entry_rows.empty:
        return None
    entry_price = float(entry_rows["close"].iloc[-1])
    if entry_price <= 0:
        return None

    exit_rows = df[df.index.date <= exit_target]
    if exit_rows.empty:
        return None

    last_available = exit_rows.index[-1].date()
    gap_days = (exit_target - last_available).days
    if gap_days > max(_MIN_DATA_GAP_TOLERANCE_DAYS, horizon_days * 0.1):
        return None

    exit_price = float(exit_rows["close"].iloc[-1])
    return (exit_price - entry_price) / entry_price
