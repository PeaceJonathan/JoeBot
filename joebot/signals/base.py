"""Common interface every signal (technical, fundamental, and later catalyst
and sentiment signals) implements, so the composite screener (Phase 1+) and
the backtest engine (Phase 3) can iterate over signals generically without
special-casing each one.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SignalResult:
    """The output of one signal for one ticker as of one date.

    score: normalized to roughly [0, 1], higher = more bullish/notable. A
    signal that found nothing should return score=0.0, not raise.
    confidence: rough measure of how much evidence backs the score (e.g. a
    signal starved of data for a small-cap should report low confidence
    rather than a misleadingly precise score).
    metadata: human-readable detail for the report/dashboard (which
    threshold fired, raw values) -- this is what lets the user do their own
    due diligence instead of trusting a bare number, and what Phase 3's
    signal_evaluation.py needs for per-signal attribution.
    """

    score: float
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


class Signal(Protocol):
    """Every concrete signal must expose `name` and `score(...)`."""

    name: str

    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        ...


# Signals whose primary driver is a single binary/event-risk-heavy fact (an
# activist stake, a leadership shakeup, a clinical trial readout) rather
# than a steady trend. Defined here (not in joebot/reporting/narrative.py
# or joebot/screener/composite.py, both of which need it) since this is
# the shared, dependency-free base module both of those already import
# from -- putting it in either one would create a circular import.
BINARY_CATALYST_SIGNALS = frozenset({"activist_stake", "leadership_change", "clinical_trial"})
