"""JoeBot Streamlit dashboard entrypoint.

Run with: streamlit run dashboard/app.py

Shares joebot/pipeline.py and the SQLite store with scripts/run_daily.py --
this dashboard never re-implements scan logic, only reads persisted
results (and can trigger the identical run_daily_scan() on demand via the
sidebar button) so the unattended cron path and this interactive path
never drift apart.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st  # noqa: E402

from dashboard.views import (  # noqa: E402
    backtest,
    budget,
    candidate_detail,
    catalysts,
    data_health,
    discover,
    settings_view,
    today,
)
from joebot import pipeline  # noqa: E402

st.set_page_config(page_title="JoeBot", layout="wide")

st.title("JoeBot")
st.caption(
    "Personal stock breakout scanner and decision-support tool. "
    "Never places trades or connects to any brokerage. Not financial advice."
)

with st.sidebar:
    st.header("Risk")
    risk_slider = st.slider(
        "Risk appetite", min_value=0, max_value=100, value=50,
        help="0 = conservative (larger caps, tighter volatility/liquidity floors, smaller positions). "
             "100 = aggressive (smaller caps, looser thresholds, larger positions). "
             "See joebot/risk/profile.py.",
    )

    st.divider()
    if st.button("Re-run scan now", width="stretch"):
        with st.spinner("Running the full scan (this hits every configured data source)..."):
            pipeline.run_daily_scan(dt.date.today())
        st.success("Scan complete.")
        st.rerun()

    st.divider()
    page = st.radio(
        "View",
        [
            "Dashboard",
            "Discover",
            "Candidate Detail",
            "Catalysts",
            "Research",
            "Portfolio",
            "Data Health",
            "Settings",
        ],
    )

if page == "Dashboard":
    today.render(risk_slider)
elif page == "Discover":
    discover.render()
elif page == "Candidate Detail":
    candidate_detail.render()
elif page == "Catalysts":
    catalysts.render()
elif page == "Research":
    backtest.render()
elif page == "Portfolio":
    budget.render(risk_slider)
elif page == "Data Health":
    data_health.render()
else:
    settings_view.render()
