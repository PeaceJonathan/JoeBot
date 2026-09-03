"""Government contract catalyst signal.

The "small company + huge addressable market + government adoption"
pattern -- a new contract award, sized relative to the company's own
market cap (a $5M contract barely matters to a $1B company but is
transformative for a $50M one), is the signal. Recency and materiality are
what drive the score; this does not attempt to predict follow-on business.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import gov_contracts_client, health, market_data
from joebot.signals.base import SignalResult, with_source_status

DEFAULT_LOOKBACK_DAYS = 180


class GovContractSignal:
    name = "gov_contract"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    @with_source_status(health.USASPENDING, health.MARKET_DATA)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        company_name = market_data.fetch_company_name(ticker)
        if not company_name:
            return SignalResult(score=0.0, confidence=0.0, metadata={"error": "company name unavailable"})

        awards = gov_contracts_client.fetch_recent_contracts(company_name, as_of_date, self.lookback_days)
        if not awards:
            return SignalResult(score=0.0, confidence=0.5, metadata={"company_name": company_name, "awards": []})

        market_cap = market_data.fetch_market_cap(ticker)
        most_recent = awards[0]

        days_ago = (as_of_date - most_recent.award_date).days if most_recent.award_date else self.lookback_days
        recency_score = max(0.0, 1.0 - days_ago / self.lookback_days)

        materiality_score = 0.5  # neutral default when market cap is unknown -- don't guess at materiality
        if market_cap and market_cap > 0 and most_recent.amount:
            ratio = most_recent.amount / market_cap
            # A contract worth 10%+ of market cap is about as material as it
            # gets for a small-cap; scale linearly up to that.
            materiality_score = min(1.0, ratio / 0.10)

        score = 0.5 * recency_score + 0.5 * materiality_score

        return SignalResult(
            score=float(score),
            confidence=0.6,
            metadata={
                "company_name": company_name,
                "awards": [
                    {"amount": a.amount, "agency": a.awarding_agency, "date": a.award_date.isoformat() if a.award_date else None, "description": a.description}
                    for a in awards[:5]
                ],
                "days_since_award": days_ago,
                "materiality_ratio_of_market_cap": None if not (market_cap and most_recent.amount) else round(most_recent.amount / market_cap, 4),
            },
        )
