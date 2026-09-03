"""Catalysts feed: recent dated events across every scanned candidate --
new ownership stakes, leadership changes, government contracts, clinical
trial updates, patent bursts -- most-recent-first (section 22/23).

Deliberately events that already happened, not a forward-looking calendar
(PDUFA dates, scheduled earnings). This project has no data source for
genuinely upcoming events, and fabricating one would violate the project's
hardest rule (never invent data) -- see joebot/reporting/narrative.py.
"""
from __future__ import annotations

import streamlit as st

from joebot.reporting.narrative import build_event_feed
from joebot.storage.queries import latest_candidates


def render() -> None:
    st.header("Catalysts")
    st.caption(
        "Recent events across every scanned candidate, most recent first. "
        "This is a record of what already happened (filings, contracts, trial "
        "updates, patent activity) -- not a forward-looking calendar. JoeBot "
        "has no data source for genuinely upcoming events (PDUFA dates, "
        "scheduled earnings) and won't fabricate one."
    )

    run, candidates = latest_candidates()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first, or click 'Re-run scan now' in the sidebar.")
        return

    lookback = st.slider("Lookback window (days)", min_value=7, max_value=180, value=30, step=7)
    ranked = [c.to_ranked_candidate() for c in candidates]
    feed = build_event_feed(ranked, lookback_days=lookback)

    if not feed:
        st.info(f"No dated events found across {len(candidates)} scanned candidates in the last {lookback} days.")
        return

    st.caption(f"{len(feed)} events across {len(candidates)} scanned candidates in the last {lookback} days.")
    st.dataframe(
        [{"Date": date, "Ticker": ticker, "Event": desc} for date, ticker, desc in feed],
        width="stretch",
        hide_index=True,
    )
