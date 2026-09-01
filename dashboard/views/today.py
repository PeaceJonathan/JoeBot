"""Today's picks view: the latest scan's candidates, live-filtered by the
risk slider against already-persisted data (no re-fetch on every slider
move -- see joebot/screener/composite.py::passes_risk_filter).
"""
from __future__ import annotations

import streamlit as st

from joebot.risk.profile import get_risk_profile
from joebot.screener.composite import passes_risk_filter
from joebot.storage.queries import latest_candidates


def render(risk_slider_value: float) -> None:
    st.header("Today's Picks")

    run, candidates = latest_candidates()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first, or click 'Re-run scan now' in the sidebar.")
        return

    st.caption(f"Scan as of {run.as_of_date} (run at {run.run_at} UTC) -- {len(candidates)} tickers scanned.")

    risk_profile = get_risk_profile(risk_slider_value)
    filtered = []
    for c in candidates:
        tech = c.signals.get("technical_breakout", {}).get("metadata", {})
        if passes_risk_filter(
            tech.get("atr_pct_of_price"), tech.get("avg_dollar_volume"), tech.get("market_cap"), risk_profile
        ):
            filtered.append(c)

    st.caption(f"{len(filtered)}/{len(candidates)} pass the **{risk_profile.name}** risk profile (slider={risk_slider_value:.0f}).")

    if not filtered:
        st.warning("No candidates pass this risk profile. Try a higher risk slider value.")
        return

    rows = []
    for c in filtered:
        row = {"Rank": c.rank, "Ticker": c.ticker, "Sector": c.sector, "Score": round(c.composite_score, 3)}
        for name, sig in c.signals.items():
            row[name] = round(sig["score"], 2)
        rows.append(row)

    st.dataframe(rows, width="stretch", hide_index=True)

    st.caption(
        "Score is a weighted composite across all signals -- see "
        "config/settings.py::DEFAULT_SIGNAL_WEIGHTS and run "
        "`python scripts/run_backtest.py` before trusting these weights."
    )

    with st.expander("Full signal detail for a ticker"):
        ticker_options = [c.ticker for c in filtered]
        selected = st.selectbox("Ticker", ticker_options)
        selected_candidate = next(c for c in filtered if c.ticker == selected)
        for name, sig in selected_candidate.signals.items():
            st.write(f"**{name}** -- score={sig['score']:.3f}, confidence={sig['confidence']:.2f}")
            st.json(sig["metadata"])
