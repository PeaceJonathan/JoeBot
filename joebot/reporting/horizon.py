"""Investment-horizon classification.

Not every opportunity is a short-term breakout: a biotech trial might be a
~6-month catalyst, a defense-technology thesis might take 2-3 years to
play out, a turnaround might be 6-18 months. This project has no data
source that tracks a realized time-to-payoff per signal (that would need
years of its own backtest history to derive empirically), so this is a
stated, documented judgment call about how each *type* of catalyst
typically plays out -- not a measured or backtested quantity. Treat it as
a labeling convenience, not a prediction.

Classified by a candidate's single highest-scoring signal, not a blend of
all of them -- the same "which signal type is actually driving this"
mechanism joebot/signals/base.py::BINARY_CATALYST_SIGNALS and
joebot/screener/composite.py::is_binary_catalyst_led already use for a
different purpose (the risk slider's opportunity-type gate). Keeping the
reasoning tied to one concrete driver, visible in "Why now," is more
honest than an opaque blended horizon nobody could sanity-check.
"""
from __future__ import annotations

import dataclasses

SHORT_TERM = "short_term"
MEDIUM_TERM = "medium_term"
LONG_TERM = "long_term"

DISPLAY_LABELS = {
    SHORT_TERM: "Short-term (~1-3 months)",
    MEDIUM_TERM: "Medium-term (~3-12 months)",
    LONG_TERM: "Long-term (~1-3+ years)",
}

# Per-signal-family horizon judgment call -- see module docstring. Revisit
# this mapping if the backtester ever grows the ability to measure realized
# time-to-payoff per signal; until then it's a stated assumption, not evidence.
_SIGNAL_HORIZON = {
    "technical_breakout": SHORT_TERM,  # price momentum plays out or fails within weeks
    "sentiment_reddit": SHORT_TERM,  # social-attention spikes are short-lived
    "leadership_change": MEDIUM_TERM,  # a new exec team needs a couple quarters to show results
    "activist_stake": MEDIUM_TERM,  # activist campaigns typically play out over 2-4 quarters
    "insider_buying": MEDIUM_TERM,  # insiders often buy ahead of a catalyst a couple quarters out
    "clinical_trial": MEDIUM_TERM,  # a trial readout, consistent with this signal's own 120-day lookback plus buffer
    "gov_contract": LONG_TERM,  # production ramps and follow-on award cycles play out over years
    "fundamental_sanity": LONG_TERM,  # a revenue-growth thesis compounds over years, not months
    "patent_activity": LONG_TERM,  # IP commercialization timelines are inherently multi-year
}

_DEFAULT_HORIZON = MEDIUM_TERM  # fallback for any signal name not in the table above


@dataclasses.dataclass
class HorizonClassification:
    horizon: str  # SHORT_TERM / MEDIUM_TERM / LONG_TERM
    display: str  # human label with the approximate window
    driven_by: str | None  # which signal produced this classification -- None if no signal scored > 0


def classify_horizon(signal_scores: dict[str, float]) -> HorizonClassification:
    """signal_scores: {signal_name: score} for one candidate (e.g.
    {name: r.score for name, r in candidate.signal_results.items()}).
    Classifies by the single highest-scoring signal among those that
    scored above zero -- an explicit, traceable driver rather than an
    opaque blend across every signal regardless of whether it fired."""
    positive = {name: score for name, score in signal_scores.items() if score > 0}
    if not positive:
        return HorizonClassification(horizon=_DEFAULT_HORIZON, display=DISPLAY_LABELS[_DEFAULT_HORIZON], driven_by=None)

    top_signal = max(positive, key=positive.get)
    horizon = _SIGNAL_HORIZON.get(top_signal, _DEFAULT_HORIZON)
    return HorizonClassification(horizon=horizon, display=DISPLAY_LABELS[horizon], driven_by=top_signal)
