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
from joebot.signals.gov_contract import GovContractSignal
from joebot.signals.patent_activity import PatentActivitySignal
from joebot.signals.sentiment_reddit import SentimentRedditSignal
from joebot.signals.technical import TechnicalBreakoutSignal

log = logging.getLogger(__name__)

# Catalyst, sentiment, gov-contract, and patent signals apply across every
# sector -- a 13D/13G activist stake, a leadership shakeup, Reddit chatter,
# a contract award, or a patent-filing burst isn't confined to any one
# sector. ClinicalTrialSignal, GovContractSignal, and PatentActivitySignal
# all no-op (score 0, low/zero confidence) when their prerequisite data is
# missing (no crosswalk entry, no company name, no API key), so it's safe
# to include them everywhere rather than special-casing which sectors get
# which signals.
DEFAULT_SIGNALS: list[Signal] = [
    TechnicalBreakoutSignal(),
    FundamentalSanitySignal(),
    ActivistStakeSignal(),
    LeadershipChangeSignal(),
    SentimentRedditSignal(),
    ClinicalTrialSignal(),
    GovContractSignal(),
    PatentActivitySignal(),
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
