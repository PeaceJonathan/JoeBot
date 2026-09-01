"""ATR-based position sizing and budget allocation.

Output is explicitly a manual-entry suggestion for the user's own
brokerage (originally Fidelity, which has no retail trading API) -- never
an automated order. See joebot/risk/profile.py for how the risk slider
produces the RiskProfile consumed here.
"""
from __future__ import annotations

import dataclasses

from config.settings import RiskProfile

ATR_STOP_MULTIPLIER = 2.0


@dataclasses.dataclass
class PositionSuggestion:
    ticker: str
    shares: int
    dollar_amount: float
    entry_price: float
    stop_price: float
    stop_distance: float


def suggest_position(
    ticker: str,
    price: float | None,
    atr: float | None,
    budget: float,
    risk_profile: RiskProfile,
) -> PositionSuggestion | None:
    """Sizes a position so a stop-out at ATR_STOP_MULTIPLIER * ATR away
    loses roughly risk_profile.base_risk_fraction * sizing_aggressiveness_multiplier
    of `budget`, capped so the position's dollar value never exceeds
    risk_profile.max_position_fraction of `budget`.

    Returns None if price/atr are missing or non-positive, or if the sizing
    rounds down to zero shares -- callers must not size a position on
    unknown volatility, and must not report a phantom 0-share "buy."
    """
    if price is None or atr is None or price <= 0 or atr <= 0 or budget <= 0:
        return None

    stop_distance = ATR_STOP_MULTIPLIER * atr
    risk_dollars = budget * risk_profile.base_risk_fraction * risk_profile.sizing_aggressiveness_multiplier
    shares_by_risk = risk_dollars / stop_distance

    max_dollars = budget * risk_profile.max_position_fraction
    shares_by_cap = max_dollars / price

    shares = int(min(shares_by_risk, shares_by_cap))
    if shares <= 0:
        return None

    dollar_amount = shares * price
    stop_price = max(0.0, price - stop_distance)

    return PositionSuggestion(
        ticker=ticker,
        shares=shares,
        dollar_amount=dollar_amount,
        entry_price=price,
        stop_price=stop_price,
        stop_distance=stop_distance,
    )


def allocate_budget(
    ranked_candidates: list[tuple[str, float | None, float | None]],
    budget: float,
    risk_profile: RiskProfile,
) -> list[PositionSuggestion]:
    """Allocates `budget` across `ranked_candidates` -- a list of
    (ticker, price, atr) tuples the caller has already ranked best-first by
    composite score.

    Each candidate's ideal size is computed independently against the full
    budget (per suggest_position's fixed-fractional formula); this function
    then walks the ranked list consuming the budget, scaling a position
    down to fit what's left rather than dropping it outright, and stopping
    once the budget is exhausted rather than forcing full deployment into
    weak picks further down the list. Because candidates are pre-ranked,
    higher-scored names get first claim on the budget -- this is how "size
    proportional to composite score" is achieved without double-counting
    score in the per-trade risk math itself.
    """
    suggestions: list[PositionSuggestion] = []
    remaining = budget

    for ticker, price, atr in ranked_candidates:
        if remaining <= 0:
            break

        suggestion = suggest_position(ticker, price, atr, budget, risk_profile)
        if suggestion is None:
            continue

        if suggestion.dollar_amount > remaining:
            if price is None or price <= 0:
                continue
            scaled_shares = int(remaining // price)
            if scaled_shares <= 0:
                continue
            suggestion = dataclasses.replace(
                suggestion, shares=scaled_shares, dollar_amount=scaled_shares * price
            )

        suggestions.append(suggestion)
        remaining -= suggestion.dollar_amount

    return suggestions
