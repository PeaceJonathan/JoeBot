"""Insider open-market buying signal.

Distinct from activist_stake (joebot/signals/catalyst_sec.py), which only
catches a NEW >5% beneficial-ownership stake (Schedule 13D/13G). This
signal catches smaller, more common insider activity -- an officer,
director, or other Section 16 insider buying shares on the open market,
reported on a Form 4 -- via Yahoo's aggregated insider-transactions feed
(joebot.data.market_data.fetch_insider_transactions). Section 3/22's
"insider buying" and "major insider purchases" are this signal, not
activist_stake, which is a different (larger, ownership-threshold-based)
mechanism.

Insider selling is deliberately NOT scored here as a negative -- insiders
sell for many mundane reasons (taxes, diversification, planned 10b5-1
programs) that have little to do with company outlook, while open-market
*buying* with their own money is a comparatively clean signal. This
asymmetry is a deliberate, common practice in this kind of analysis, not an
oversight -- see UNCHECKED_BEAR_CASE_FACTORS in joebot/reporting/narrative.py,
which explicitly discloses that insider *selling* isn't tracked as a bear-case
factor for this same reason.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import health, market_data
from joebot.signals.base import SignalResult, with_source_status

DEFAULT_LOOKBACK_DAYS = 90

# Yahoo's insider-transactions feed has no structured transaction-code field
# (see market_data.fetch_insider_transactions's docstring) -- only a free-text
# "Text" description. Matched case-insensitively; "sale" and "option exercise"
# are excluded explicitly since "purchase" as a substring wouldn't otherwise
# rule out something like "Sale to cover option exercise cost."
_PURCHASE_KEYWORDS = ("purchase", "buy")
_EXCLUDE_KEYWORDS = ("sale", "sell", "option exercise", "gift", "tax")


def _is_open_market_purchase(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(kw in lowered for kw in _EXCLUDE_KEYWORDS):
        return False
    return any(kw in lowered for kw in _PURCHASE_KEYWORDS)


class InsiderBuyingSignal:
    name = "insider_buying"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    @with_source_status(health.MARKET_DATA)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        transactions = market_data.fetch_insider_transactions(ticker)
        if not transactions:
            # Confident zero, same reasoning as activist_stake: an absence
            # of any recorded Form 4 activity is itself informative, not an
            # "unknown data" gap -- unless the source itself was unavailable
            # (with_source_status surfaces that distinction separately).
            return SignalResult(score=0.0, confidence=0.6, metadata={"purchases": []})

        cutoff = as_of_date - dt.timedelta(days=self.lookback_days)
        purchases = []
        for t in transactions:
            if not _is_open_market_purchase(t.get("text")):
                continue
            start_date = t.get("start_date")
            if not start_date:
                continue
            try:
                d = dt.date.fromisoformat(start_date)
            except ValueError:
                continue
            if cutoff <= d <= as_of_date:
                purchases.append({**t, "start_date": start_date})

        if not purchases:
            return SignalResult(score=0.0, confidence=0.6, metadata={"purchases": []})

        purchases.sort(key=lambda p: p["start_date"], reverse=True)
        most_recent_date = dt.date.fromisoformat(purchases[0]["start_date"])
        days_ago = (as_of_date - most_recent_date).days
        recency_score = max(0.0, 1.0 - days_ago / self.lookback_days)

        distinct_insiders = len({p.get("insider") for p in purchases if p.get("insider")})
        # More than one distinct insider buying in the window is a notably
        # stronger signal than a single purchase -- full credit at 3+.
        breadth_score = min(1.0, distinct_insiders / 3.0) if distinct_insiders else 0.3

        total_value = sum(v for p in purchases if isinstance((v := p.get("value")), (int, float)))
        # $250k+ in aggregate open-market buying in the window -> full credit.
        # A coarse, deliberately simple materiality threshold -- this isn't
        # scaled to company size the way gov_contract's is, since insider
        # purchase size doesn't relate to market cap as directly as a
        # contract award does.
        magnitude_score = min(1.0, total_value / 250_000) if total_value else 0.3

        score = 0.4 * recency_score + 0.3 * breadth_score + 0.3 * magnitude_score

        return SignalResult(
            score=float(score),
            confidence=0.6,
            metadata={
                "purchases": purchases[:10],
                "distinct_insiders": distinct_insiders,
                "total_value": total_value or None,
                "days_since_purchase": days_ago,
            },
        )
