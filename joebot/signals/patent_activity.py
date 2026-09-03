"""Patent-filing-momentum signal.

Deliberately does NOT try to score patent "quality" (citation counts,
claim breadth, competitive validation) -- that's a genuinely hard
NLP/graph problem and not something to fake with a made-up formula. What's
implementable on free/cheap data is simpler and still useful: is this
company's patent filing activity accelerating? A recent burst of filings
in a small company is worth a human's attention even before knowing
whether the underlying IP is any good -- this signal exists to surface
that, not to declare the IP valuable.

Per the project's design principle (see joebot/signals/sentiment_reddit.py
for the same pattern with Reddit mentions): patent activity alone is weak
evidence and should almost never be enough on its own to drive a
recommendation -- it's one input the composite scoring combines with
everything else, and DEFAULT_SIGNAL_WEIGHTS gives it a correspondingly
modest weight until backtest evidence says otherwise.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import health, market_data, patents_client
from joebot.signals.base import SignalResult, with_source_status

DEFAULT_LOOKBACK_DAYS = 730  # 2 years, since patent activity is a slow-moving signal


class PatentActivitySignal:
    name = "patent_activity"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    @with_source_status(health.PATENTS, health.MARKET_DATA)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        company_name = market_data.fetch_company_name(ticker)
        if not company_name:
            return SignalResult(score=0.0, confidence=0.0, metadata={"error": "company name unavailable"})

        patents = patents_client.fetch_patents_for_assignee(company_name, as_of_date, self.lookback_days)
        if not patents:
            return SignalResult(score=0.0, confidence=0.3, metadata={"company_name": company_name, "recent_count": 0})

        midpoint = as_of_date - dt.timedelta(days=self.lookback_days // 2)
        recent = [p for p in patents if p.patent_date and p.patent_date >= midpoint]
        earlier = [p for p in patents if p.patent_date and p.patent_date < midpoint]

        earlier_count_safe = max(len(earlier), 1)
        velocity_ratio = len(recent) / earlier_count_safe

        volume_score = min(1.0, len(patents) / 15.0)  # 15+ patents in the window -> full credit
        velocity_score = min(1.0, max(0.0, (velocity_ratio - 1.0) / 3.0))
        score = 0.4 * volume_score + 0.6 * velocity_score  # weight momentum over raw count -- a burst matters more than a steady baseline

        return SignalResult(
            score=float(score),
            confidence=0.4,  # capped moderate -- this signal's evidentiary weight is deliberately limited, see module docstring
            metadata={
                "company_name": company_name,
                "recent_count": len(recent),
                "earlier_count": len(earlier),
                "velocity_ratio": round(velocity_ratio, 2),
                "sample_titles": [p.title for p in recent[:3] if p.title],
                "recent_patents": [
                    {"title": p.title, "date": p.patent_date.isoformat() if p.patent_date else None}
                    for p in sorted(recent, key=lambda p: p.patent_date or dt.date.min, reverse=True)[:5]
                ],
            },
        )
