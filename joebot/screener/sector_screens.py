"""Runs the composite screener across every configured sector."""
from __future__ import annotations

import datetime as dt
import logging

from joebot.data import universe
from joebot.screener.composite import RankedCandidate, rank_candidates, score_ticker
from joebot.signals.base import Signal
from joebot.signals.catalyst_clinical import ClinicalTrialSignal
from joebot.signals.catalyst_sec import ActivistStakeSignal, LeadershipChangeSignal
from joebot.signals.fundamental import FundamentalSanitySignal
from joebot.signals.sentiment_reddit import SentimentRedditSignal
from joebot.signals.technical import TechnicalBreakoutSignal

log = logging.getLogger(__name__)

# Catalyst and sentiment signals apply across every sector -- a 13D/13G
# activist stake, a leadership shakeup, or Reddit chatter isn't confined to
# any one sector. ClinicalTrialSignal is a no-op (score 0, confidence 0)
# for any ticker missing from config/pharma_crosswalk.yaml, so it's safe to
# include in every sector's scoring rather than special-casing pharma.
DEFAULT_SIGNALS: list[Signal] = [
    TechnicalBreakoutSignal(),
    FundamentalSanitySignal(),
    ActivistStakeSignal(),
    LeadershipChangeSignal(),
    SentimentRedditSignal(),
    ClinicalTrialSignal(),
]


def run_all_sectors(as_of_date: dt.date, signals: list[Signal] = DEFAULT_SIGNALS) -> list[RankedCandidate]:
    """Scans only status: active sectors -- candidate sectors (Phase 4 sector
    discovery) are backtest-only until manually promoted in sectors.yaml
    based on a real evaluation-fold result from scripts/run_backtest.py."""
    sectors = universe.active_sectors()
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
