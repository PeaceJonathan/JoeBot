"""Budget/position-sizing calculator view: "how much do I invest" for a
one-off deployable budget, not tied to any daily/weekly/monthly cadence --
you open this whenever you want to deploy money, enter the amount, and it
sizes positions across today's risk-filtered picks.
"""
from __future__ import annotations

import streamlit as st

from config import settings
from joebot.risk.position_sizing import allocate_budget
from joebot.risk.profile import get_risk_profile
from joebot.screener.composite import passes_risk_filter
from joebot.storage.queries import latest_candidates


def render(risk_slider_value: float) -> None:
    st.header("Budget Calculator")
    st.caption(
        "Enter how much you want to deploy right now -- this isn't tied to a "
        "daily/weekly/monthly schedule. Sizing is ATR-based and scaled by the "
        "risk slider; see joebot/risk/position_sizing.py."
    )

    run, candidates = latest_candidates()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first.")
        return

    budget = st.number_input(
        "Budget to deploy ($)", min_value=0.0, value=settings.DEFAULT_BUDGET, step=100.0
    )

    risk_profile = get_risk_profile(risk_slider_value)
    filtered = []
    for c in candidates:
        tech = c.signals.get("technical_breakout", {}).get("metadata", {})
        if passes_risk_filter(
            tech.get("atr_pct_of_price"), tech.get("avg_dollar_volume"), tech.get("market_cap"), risk_profile
        ):
            filtered.append((c, tech))

    if not filtered or budget <= 0:
        st.warning("No risk-filtered candidates (or a zero budget) -- nothing to size.")
        return

    ranked_tuples = [(c.ticker, tech.get("close"), tech.get("atr")) for c, tech in filtered]
    suggestions = allocate_budget(ranked_tuples, budget=budget, risk_profile=risk_profile)

    if not suggestions:
        st.warning("No candidate had enough price/ATR data to size a position.")
        return

    total_spent = sum(s.dollar_amount for s in suggestions)
    st.metric("Allocated", f"${total_spent:,.2f}", f"of ${budget:,.2f} budget")

    st.dataframe(
        [
            {
                "Ticker": s.ticker,
                "Shares": s.shares,
                "$ Amount": round(s.dollar_amount, 2),
                "Entry": round(s.entry_price, 2),
                "Stop": round(s.stop_price, 2),
            }
            for s in suggestions
        ],
        width="stretch",
        hide_index=True,
    )

    st.warning(
        "This is a manual-entry suggestion for your own brokerage. JoeBot "
        "never places an order -- enter these manually and account for "
        "your broker's execution timing (e.g. Fidelity may not execute "
        "until end of the current or next trading day)."
    )
