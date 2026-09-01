"""Walk-forward backtest engine.

Iterates as_of_dates across [start_date, end_date] in fixed steps. At each
one: builds the point-in-time universe (universe_builder), scores every
ticker with every signal using only data on or before that date, and
records the realized forward return at a short (~2 month) and long (~2
year) horizon.

Per this project's hard rule against data-snooping, composite screener
weights may only be set from an OUT-OF-SAMPLE fold's results: the run is
split chronologically into a calibration fold (first half of as_of_dates)
and an evaluation fold (second half). joebot/backtest/signal_evaluation.py
must only be trusted on the evaluation fold; anything computed from the
calibration fold is for choosing weights, never for reporting performance.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging

import pandas as pd

from joebot.backtest import point_in_time, universe_builder
from joebot.signals.base import Signal

log = logging.getLogger(__name__)

SHORT_HORIZON_DAYS = 60
LONG_HORIZON_DAYS = 504  # roughly 2 trading years


@dataclasses.dataclass
class BacktestRecord:
    as_of_date: dt.date
    ticker: str
    sector: str
    signal_name: str
    score: float
    confidence: float
    forward_return_short: float | None
    forward_return_long: float | None


@dataclasses.dataclass
class BacktestResult:
    records: list[BacktestRecord]
    calibration_cutoff: dt.date

    def to_frame(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame(columns=[f.name for f in dataclasses.fields(BacktestRecord)])
        return pd.DataFrame([dataclasses.asdict(r) for r in self.records])

    def calibration_fold(self) -> pd.DataFrame:
        df = self.to_frame()
        return df[df["as_of_date"] < self.calibration_cutoff]

    def evaluation_fold(self) -> pd.DataFrame:
        df = self.to_frame()
        return df[df["as_of_date"] >= self.calibration_cutoff]


def _generate_as_of_dates(start_date: dt.date, end_date: dt.date, step_days: int) -> list[dt.date]:
    """Dates spaced step_days apart, leaving enough room before end_date for
    the long-horizon forward return to actually be computable."""
    dates = []
    current = start_date
    max_start = end_date - dt.timedelta(days=LONG_HORIZON_DAYS)
    while current <= max_start:
        dates.append(current)
        current += dt.timedelta(days=step_days)
    return dates


def run_walk_forward(
    signals: list[Signal],
    start_date: dt.date,
    end_date: dt.date,
    step_days: int = 30,
    sector_filter: str | None = None,
) -> BacktestResult:
    """sector_filter, if given, restricts the universe to one sector name
    from config/sectors.yaml -- this is how a candidate sector (Phase 4
    sector discovery) gets validated before being promoted to status:
    active: `run_walk_forward(..., sector_filter="clean_energy")` and look
    at the evaluation fold's spread, per sector, not on vibes."""
    as_of_dates = _generate_as_of_dates(start_date, end_date, step_days)
    if not as_of_dates:
        raise ValueError(
            "Date range too short for a single walk-forward window at the "
            f"{LONG_HORIZON_DAYS}-day long horizon -- widen start_date/end_date."
        )

    delistings = universe_builder.delisting_lookup()
    records: list[BacktestRecord] = []

    for as_of_date in as_of_dates:
        universe_by_sector = universe_builder.universe_as_of(as_of_date)
        if sector_filter is not None:
            universe_by_sector = {sector_filter: universe_by_sector.get(sector_filter, [])}
        for sector, tickers in universe_by_sector.items():
            for ticker in tickers:
                delisting_info = delistings.get(ticker)
                fwd_short = point_in_time.forward_return(ticker, as_of_date, SHORT_HORIZON_DAYS, delisting_info)
                fwd_long = point_in_time.forward_return(ticker, as_of_date, LONG_HORIZON_DAYS, delisting_info)

                for sig in signals:
                    try:
                        result = sig.score(ticker, as_of_date)
                    except Exception as exc:
                        log.warning("Signal %s failed for %s at %s: %s", sig.name, ticker, as_of_date, exc)
                        continue

                    records.append(BacktestRecord(
                        as_of_date=as_of_date,
                        ticker=ticker,
                        sector=sector,
                        signal_name=sig.name,
                        score=result.score,
                        confidence=result.confidence,
                        forward_return_short=fwd_short,
                        forward_return_long=fwd_long,
                    ))

    calibration_cutoff = as_of_dates[len(as_of_dates) // 2]
    return BacktestResult(records=records, calibration_cutoff=calibration_cutoff)
