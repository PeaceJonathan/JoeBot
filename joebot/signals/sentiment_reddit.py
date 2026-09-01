"""Reddit mention-volume/velocity signal.

Deliberately simple: counts recent mentions across a small set of investing
subreddits and compares the count in the more-recent half of the lookback
window to the earlier half (velocity), rather than attempting full NLP
sentiment classification. A bare mention-count spike is a noisier but much
more robust signal on free data than a sentiment classifier trained to
parse short, slang-heavy Reddit post titles would be. This is one input
among many in the composite score, never a standalone buy signal.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import reddit_client
from joebot.signals.base import SignalResult

DEFAULT_LOOKBACK_DAYS = 14


class SentimentRedditSignal:
    name = "sentiment_reddit"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        mentions = reddit_client.fetch_mentions(ticker, as_of_date, self.lookback_days)

        if not mentions:
            # Low, not zero, confidence: an absence of Reddit chatter for a
            # small/mid-cap is common and not strongly informative either
            # way, unlike an absence of an SEC filing (a hard fact).
            return SignalResult(score=0.0, confidence=0.3, metadata={"mention_count": 0})

        midpoint = as_of_date - dt.timedelta(days=self.lookback_days // 2)
        recent = [m for m in mentions if dt.date.fromisoformat(m["created_date"]) >= midpoint]
        earlier = [m for m in mentions if dt.date.fromisoformat(m["created_date"]) < midpoint]

        earlier_count_safe = max(len(earlier), 1)  # avoid divide-by-zero; a missing baseline is treated as mild, not infinite
        velocity_ratio = len(recent) / earlier_count_safe

        volume_score = min(1.0, len(mentions) / 20.0)  # 20+ mentions in the window -> full credit
        velocity_score = min(1.0, max(0.0, (velocity_ratio - 1.0) / 3.0))  # 4x+ velocity -> full credit

        score = 0.5 * volume_score + 0.5 * velocity_score

        return SignalResult(
            score=float(score),
            confidence=0.5,
            metadata={
                "mention_count": len(mentions),
                "recent_count": len(recent),
                "earlier_count": len(earlier),
                "velocity_ratio": round(velocity_ratio, 2),
            },
        )
