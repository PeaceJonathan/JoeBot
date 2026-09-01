"""Basic fundamental sanity filter: revenue growth trend and cash cushion.

Phase 1 keeps this intentionally simple -- a few sanity checks to avoid
ranking companies that are shrinking or about to run out of cash highly,
not a full valuation model. XBRL tagging for small/mid-caps is often sparse,
so missing data is scored as neutral (low confidence), never penalized as
if it were bad news.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import sec_client
from joebot.signals.base import SignalResult


class FundamentalSanitySignal:
    name = "fundamental_sanity"

    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        snapshot = sec_client.fetch_fundamental_snapshot(ticker)

        growth = snapshot.revenue_growth_pct
        has_cash_data = snapshot.cash is not None

        if growth is None and not has_cash_data:
            return SignalResult(score=0.5, confidence=0.0, metadata={"error": "no usable XBRL data"})

        # Growth sub-score: 0 at -20% YoY or worse, 1 at +40% YoY or better.
        growth_score = 0.5
        if growth is not None:
            growth_score = min(1.0, max(0.0, (growth + 0.20) / 0.60))

        # Cash sub-score is a coarse presence check in Phase 1 (a real burn-rate
        # /runway calc needs quarterly cash-flow data, not just a balance).
        cash_score = 0.6 if has_cash_data and snapshot.cash > 0 else 0.5

        score = 0.7 * growth_score + 0.3 * cash_score
        confidence = (0.7 if growth is not None else 0.0) + (0.3 if has_cash_data else 0.0)

        return SignalResult(
            score=float(score),
            confidence=float(confidence),
            metadata={
                "revenue_growth_pct": None if growth is None else round(growth, 4),
                "revenue_latest": snapshot.revenue_latest,
                "cash": snapshot.cash,
            },
        )
