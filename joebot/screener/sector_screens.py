"""Runs the composite screener across every configured sector."""
from __future__ import annotations

import datetime as dt
import logging

from joebot.data import universe
from joebot.screener.composite import RankedCandidate, rank_candidates, score_ticker
from joebot.signals.base import Signal
from joebot.signals.catalyst_sec import ActivistStakeSignal, LeadershipChangeSignal
from joebot.signals.fundamental import FundamentalSanitySignal
from joebot.signals.technical import TechnicalBreakoutSignal

log = logging.getLogger(__name__)

# Catalyst signals apply across every sector -- a 13D/13G activist stake or
# a leadership shakeup isn't confined to tech/defense/faded-giants.
DEFAULT_SIGNALS: list[Signal] = [
    TechnicalBreakoutSignal(),
    FundamentalSanitySignal(),
    ActivistStakeSignal(),
    LeadershipChangeSignal(),
]


def run_all_sectors(as_of_date: dt.date, signals: list[Signal] = DEFAULT_SIGNALS) -> list[RankedCandidate]:
    sectors = universe.load_sectors()
    all_candidates: list[RankedCandidate] = []

    for sector in sectors.values():
        for ticker in sector.tickers:
            try:
                candidate = score_ticker(ticker, sector.name, signals, as_of_date)
                all_candidates.append(candidate)
            except Exception as exc:
                # One bad ticker (delisted, renamed, API hiccup) must not
                # take down the whole scan.
                log.warning("Skipping %s (%s): %s", ticker, sector.name, exc)

    return rank_candidates(all_candidates)
