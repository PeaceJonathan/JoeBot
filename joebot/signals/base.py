"""Common interface every signal (technical, fundamental, and later catalyst
and sentiment signals) implements, so the composite screener (Phase 1+) and
the backtest engine (Phase 3) can iterate over signals generically without
special-casing each one.
"""
from __future__ import annotations

import datetime as dt
import functools
from dataclasses import dataclass, field
from typing import Any, Protocol

from joebot.data import health


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


def with_source_status(*sources: str):
    """Decorator for a Signal's score() method: stamps
    metadata["data_source_status"] with each declared external source's
    current health.SourceHealth.status (health.OK / UNAVAILABLE /
    NOT_CONFIGURED) after the scoring logic runs.

    This is what makes "no evidence found" and "data source unavailable"
    distinguishable downstream (narrative.py, the dashboard's Data Health
    panel) without every signal having to thread status through each of its
    own return statements by hand -- a signal often has several early
    returns (missing crosswalk entry, empty result, successful score), and
    the source's health is the same regardless of which branch fired.
    """

    def decorator(score_fn):
        @functools.wraps(score_fn)
        def wrapper(self, ticker: str, as_of_date: dt.date) -> SignalResult:
            result = score_fn(self, ticker, as_of_date)
            result.metadata["data_source_status"] = {s: health.get_status(s).status for s in sources}
            return result

        return wrapper

    return decorator


# Signals whose primary driver is a single binary/event-risk-heavy fact (an
# activist stake, a leadership shakeup, a clinical trial readout) rather
# than a steady trend. Defined here (not in joebot/reporting/narrative.py
# or joebot/screener/composite.py, both of which need it) since this is
# the shared, dependency-free base module both of those already import
# from -- putting it in either one would create a circular import.
BINARY_CATALYST_SIGNALS = frozenset({"activist_stake", "leadership_change", "clinical_trial"})
