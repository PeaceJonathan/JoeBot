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

from config.settings import DEFAULT_SIGNAL_WEIGHTS, RiskProfile
from joebot.signals.base import BINARY_CATALYST_SIGNALS, Signal, SignalResult


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
    weights: dict[str, float] = DEFAULT_SIGNAL_WEIGHTS,
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


def is_binary_catalyst_led(signal_scores: dict[str, float]) -> bool:
    """True if the highest-scoring signal for this candidate is a
    binary/event-risk one (see joebot/signals/base.py::BINARY_CATALYST_SIGNALS)
    -- an activist stake, a leadership shakeup, or a clinical trial readout
    -- rather than a steady-trend one. Used by the risk slider to decide
    whether this *kind* of opportunity is even eligible at a given risk
    level, not just whether its numbers clear a threshold."""
    if not signal_scores:
        return False
    top_signal = max(signal_scores, key=signal_scores.get)
    return top_signal in BINARY_CATALYST_SIGNALS and signal_scores[top_signal] > 0


def passes_risk_filter(
    atr_pct_of_price: float | None,
    avg_dollar_volume: float | None,
    market_cap: float | None,
    risk_profile: RiskProfile,
    signal_scores: dict[str, float] | None = None,
) -> bool:
    """The risk slider's first effect: which candidates even appear.

    A None value (data unavailable) never excludes a candidate -- per this
    project's "unknown, not bad news" convention, a data gap is not
    grounds for filtering something out. Only a known value that actually
    violates the profile's threshold excludes it. This is a pure predicate
    (no I/O) so both a live scan and the dashboard re-filtering
    already-persisted data can share it.

    signal_scores (ticker's per-signal composite contributions), if given,
    also gates on opportunity *type*: a conservative risk_profile
    (binary_catalyst_tolerance < 0.5) excludes any candidate whose top
    signal is a binary-catalyst one -- a conservative investor shouldn't
    be shown a turnaround special situation at all, not just a size-capped
    version of one.
    """
    if atr_pct_of_price is not None and atr_pct_of_price > risk_profile.max_atr_pct_of_price:
        return False
    if avg_dollar_volume is not None and avg_dollar_volume < risk_profile.min_avg_dollar_volume:
        return False
    if market_cap is not None and market_cap < risk_profile.min_market_cap:
        return False
    if signal_scores and risk_profile.binary_catalyst_tolerance < 0.5 and is_binary_catalyst_led(signal_scores):
        return False
    return True


def apply_risk_filter(candidates: list[RankedCandidate], risk_profile: RiskProfile) -> list[RankedCandidate]:
    """Filters a ranked candidate list using each candidate's technical_breakout
    metadata (atr_pct_of_price, avg_dollar_volume, market_cap) plus its full
    per-signal score breakdown for the binary-catalyst-type gate -- all
    already computed and persisted, no extra data fetch needed here."""
    filtered = []
    for c in candidates:
        tech = c.signal_results.get("technical_breakout")
        meta = tech.metadata if tech else {}
        signal_scores = {name: r.score for name, r in c.signal_results.items()}
        if passes_risk_filter(
            meta.get("atr_pct_of_price"), meta.get("avg_dollar_volume"), meta.get("market_cap"),
            risk_profile, signal_scores,
        ):
            filtered.append(c)
    return filtered
