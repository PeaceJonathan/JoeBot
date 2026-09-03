"""Runs the composite screener across every configured sector."""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging

from joebot.data import universe
from joebot.screener.composite import RankedCandidate, rank_candidates, score_ticker
from joebot.signals.base import Signal
from joebot.signals.catalyst_clinical import ClinicalTrialSignal
from joebot.signals.catalyst_sec import ActivistStakeSignal, LeadershipChangeSignal
from joebot.signals.fundamental import FundamentalSanitySignal
from joebot.signals.gov_contract import GovContractSignal
from joebot.signals.insider_buying import InsiderBuyingSignal
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
    InsiderBuyingSignal(),
    LeadershipChangeSignal(),
    SentimentRedditSignal(),
    ClinicalTrialSignal(),
    GovContractSignal(),
    PatentActivitySignal(),
]


@dataclasses.dataclass
class SkippedTicker:
    ticker: str
    sector: str
    reason: str


@dataclasses.dataclass
class ScreenResult:
    """candidates is what most callers want; attempted/skipped exist so a
    scan that silently returns far fewer candidates than the configured
    universe is explainable rather than mysterious (see
    joebot/pipeline.py::_persist_scan, which persists these onto the
    ScanRun row, and dashboard/views/today.py, which surfaces them).
    A ticker being skipped here means EVERY signal failed for it outright
    (an exception, not just a low/zero score) -- almost always a real
    problem (bad/renamed symbol, or every data source unreachable for that
    ticker this run), not a normal "nothing interesting found" outcome.
    """

    candidates: list[RankedCandidate]
    attempted: int
    skipped: list[SkippedTicker]


def run_all_sectors(as_of_date: dt.date, signals: list[Signal] = DEFAULT_SIGNALS) -> ScreenResult:
    """Scans only status: active sectors -- candidate sectors (Phase 4 sector
    discovery) are backtest-only until manually promoted in sectors.yaml
    based on a real evaluation-fold result from scripts/run_backtest.py."""
    sectors = universe.active_sectors()
    all_candidates: list[RankedCandidate] = []
    skipped: list[SkippedTicker] = []
    attempted = 0

    for sector in sectors.values():
        for ticker in sector.tickers:
            attempted += 1
            try:
                candidate = score_ticker(ticker, sector.name, signals, as_of_date)
                all_candidates.append(candidate)
            except Exception as exc:
                # One bad ticker (delisted, renamed, API hiccup) must not
                # take down the whole scan -- but it IS worth recording,
                # not just logging, since a run that skips a large chunk of
                # the universe (e.g. a Yahoo Finance rate-limit mid-scan)
                # should be obviously abnormal to the user, not just a
                # shorter-than-expected table with no explanation.
                log.warning("Skipping %s (%s): %s", ticker, sector.name, exc)
                skipped.append(SkippedTicker(ticker=ticker, sector=sector.name, reason=str(exc)))

    return ScreenResult(candidates=rank_candidates(all_candidates), attempted=attempted, skipped=skipped)
