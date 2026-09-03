"""Discover: search/filter across every scanned candidate from the latest
run (not risk-slider-gated like Today's Picks -- this is for browsing the
full universe, including candidates a conservative risk profile would hide).
"""
from __future__ import annotations

import streamlit as st

from joebot.reporting.horizon import LONG_TERM, MEDIUM_TERM, SHORT_TERM, classify_horizon
from joebot.storage.queries import latest_candidates

_HORIZON_LABELS = {SHORT_TERM: "Short-term", MEDIUM_TERM: "Medium-term", LONG_TERM: "Long-term"}


def render() -> None:
    st.header("Discover")
    st.caption(
        "Search and filter every candidate from the latest scan -- unlike "
        "Today's Picks, this is not gated by the risk slider, so it includes "
        "candidates a conservative profile would exclude outright."
    )

    run, candidates = latest_candidates()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first, or click 'Re-run scan now' in the sidebar.")
        return

    st.caption(f"Scan as of {run.as_of_date} (run at {run.run_at} UTC) -- {len(candidates)} tickers scanned.")

    horizons = {c.ticker: classify_horizon({name: s["score"] for name, s in c.signals.items()}) for c in candidates}

    sectors = sorted({c.sector for c in candidates})
    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
    with col1:
        selected_sectors = st.multiselect("Sector", sectors, default=sectors)
    with col2:
        min_score = st.slider("Minimum composite score", 0.0, 1.0, 0.0, 0.05)
    with col3:
        ticker_query = st.text_input("Ticker contains", "").strip().upper()
    with col4:
        selected_horizon_labels = st.multiselect(
            "Horizon", list(_HORIZON_LABELS.values()), default=list(_HORIZON_LABELS.values()),
            help="A per-signal-family judgment call, not measured/backtested -- see joebot/reporting/horizon.py.",
        )
    selected_horizon_keys = {k for k, label in _HORIZON_LABELS.items() if label in selected_horizon_labels}

    filtered = [
        c for c in candidates
        if c.sector in selected_sectors
        and c.composite_score >= min_score
        and (not ticker_query or ticker_query in c.ticker.upper())
        and horizons[c.ticker].horizon in selected_horizon_keys
    ]

    st.caption(f"{len(filtered)}/{len(candidates)} candidates match.")
    if not filtered:
        st.warning("No candidates match these filters.")
        return

    rows = []
    for c in filtered:
        row = {"Rank": c.rank, "Ticker": c.ticker, "Sector": c.sector, "Score": round(c.composite_score, 3), "Horizon": horizons[c.ticker].display}
        for name, sig in c.signals.items():
            row[name] = round(sig["score"], 2)
        rows.append(row)
    st.dataframe(rows, width="stretch", hide_index=True)

    st.caption("Open a ticker's full breakdown, timeline, and bear case on the Candidate Detail page.")
