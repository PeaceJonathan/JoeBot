"""Combines per-ticker signal results into a single ranked candidate list.

Weighting is a simple weighted sum of DEFAULT_SIGNAL_WEIGHTS in Phase 1. Per
the plan's hard rule, these weights may only be updated from a walk-forward
out-of-sample backtest result (joebot/backtest), never hand-tuned on the
full history.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from config import settings
from joebot.signals.base import Signal, SignalResult


@dataclass
class RankedCandidate:
    ticker: str
    sector: str
    composite_score: float
    signal_results: dict[str, SignalResult] = field(default_factory=dict)


def score_ticker(
    ticker: str,
    sector: str,
    signals: list[Signal],
    as_of_date: dt.date,
    weights: dict[str, float] = settings.DEFAULT_SIGNAL_WEIGHTS,
) -> RankedCandidate:
    results: dict[str, SignalResult] = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for sig in signals:
        result = sig.score(ticker, as_of_date)
        results[sig.name] = result
        weight = weights.get(sig.name, 0.0)
        # Down-weight low-confidence signals rather than dropping them --
        # a signal starved of data shouldn't silently vanish from provenance.
        effective_weight = weight * max(result.confidence, 0.1)
        weighted_sum += effective_weight * result.score
        weight_total += effective_weight

    composite = weighted_sum / weight_total if weight_total > 0 else 0.0
    return RankedCandidate(ticker=ticker, sector=sector, composite_score=composite, signal_results=results)


def rank_candidates(candidates: list[RankedCandidate]) -> list[RankedCandidate]:
    return sorted(candidates, key=lambda c: c.composite_score, reverse=True)
