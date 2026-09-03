"""SEC filing-based catalyst signals: the "faded giant comeback" detector.

ActivistStakeSignal looks for a new/recent Schedule 13D or 13G filing on the
ticker (someone accumulating a >5% stake) that isn't a routine passive-index
filing -- this is the mechanism behind the user's GoPro example (a notable
individual/fund taking a meaningful stake ahead of a rally).

LeadershipChangeSignal looks for a recent 8-K Item 5.02 (officer/director
departure or appointment) -- a new CEO/exec team is a classic comeback
catalyst for a company that's fallen off.

Both signals score purely on recency + filing-type strength in Phase 2.
Whether either signal actually predicts forward returns -- and at what
weight it deserves relative to the technical/fundamental signals -- is
exactly what Phase 3's backtester exists to answer; don't read a high score
here as a validated buy case.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import health, sec_client
from joebot.signals.base import SignalResult, with_source_status

DEFAULT_LOOKBACK_DAYS = 180


class ActivistStakeSignal:
    name = "activist_stake"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    @with_source_status(health.SEC)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        events = sec_client.fetch_ownership_filings(ticker, as_of_date, self.lookback_days)

        if not events:
            # Absence of a filing is itself informative (not "unknown data"
            # like a missing XBRL tag), so this is a confident zero.
            return SignalResult(score=0.0, confidence=0.8, metadata={"filings": []})

        active_events = [e for e in events if not e.is_likely_passive_filer()]
        passive_count = len(events) - len(active_events)

        if not active_events:
            return SignalResult(
                score=0.0,
                confidence=0.8,
                metadata={"filings": [], "filtered_passive_count": passive_count},
            )

        most_recent = max(active_events, key=lambda e: e.filing_date)
        days_ago = (as_of_date - most_recent.filing_date).days
        recency_score = max(0.0, 1.0 - days_ago / self.lookback_days)
        # SC 13D signals active/activist intent; 13G is passive-but-large,
        # still worth flagging but weighted lower.
        form_score = 1.0 if most_recent.form == "SC 13D" else 0.6

        score = 0.6 * recency_score + 0.4 * form_score

        return SignalResult(
            score=float(score),
            confidence=0.8,
            metadata={
                "filings": [e.as_dict() for e in active_events],
                "filtered_passive_count": passive_count,
                "most_recent_form": most_recent.form,
                "days_since_filing": days_ago,
            },
        )


class LeadershipChangeSignal:
    name = "leadership_change"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    @with_source_status(health.SEC)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        events = sec_client.fetch_8k_leadership_events(ticker, as_of_date, self.lookback_days)

        if not events:
            return SignalResult(score=0.0, confidence=0.8, metadata={"filings": []})

        most_recent = max(events, key=lambda e: e.filing_date)
        days_ago = (as_of_date - most_recent.filing_date).days
        recency_score = max(0.0, 1.0 - days_ago / self.lookback_days)

        return SignalResult(
            score=float(recency_score),
            confidence=0.8,
            metadata={
                "filings": [e.as_dict() for e in events],
                "days_since_filing": days_ago,
            },
        )
