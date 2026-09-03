"""Settings: read-only view of the current configuration -- signal weights,
sector universe status, risk-profile breakpoints, and which optional data
sources have credentials configured (never displays the credential values
themselves).

Deliberately read-only. Signal weights may only change from a walk-forward,
out-of-sample backtest result (see the Research page and README) -- letting
someone drag a slider here and quietly hand-tune the composite score would
undermine the one rule this project treats as non-negotiable.
"""
from __future__ import annotations

import os

import streamlit as st
import yaml

from config import settings


def render() -> None:
    st.header("Settings")
    st.caption(
        "Read-only. Signal weights and sector-universe promotion are only "
        "ever changed from a walk-forward backtest result -- see the "
        "Research page and README's 'Why the signal weights are a "
        "placeholder' section -- never edited live from this page."
    )

    st.subheader("Signal weights")
    st.caption("config/settings.py::DEFAULT_SIGNAL_WEIGHTS -- a starting guess until backtest evidence replaces it.")
    st.dataframe(
        [{"Signal": k, "Weight": v} for k, v in sorted(settings.DEFAULT_SIGNAL_WEIGHTS.items(), key=lambda kv: -kv[1])],
        width="stretch", hide_index=True,
    )

    st.subheader("Risk profile breakpoints")
    st.caption("config/settings.py::RISK_PROFILE_BREAKPOINTS -- what the risk slider actually changes.")
    rows = []
    for slider_value, profile in settings.RISK_PROFILE_BREAKPOINTS:
        rows.append({
            "Slider": slider_value,
            "Profile": profile.name,
            "Min market cap": f"${profile.min_market_cap:,.0f}",
            "Max ATR % of price": f"{profile.max_atr_pct_of_price:.0%}",
            "Min avg $ volume": f"${profile.min_avg_dollar_volume:,.0f}",
            "Max position %": f"{profile.max_position_fraction:.0%}",
            "Binary-catalyst tolerance": profile.binary_catalyst_tolerance,
        })
    st.dataframe(rows, width="stretch", hide_index=True)

    st.subheader("Sector universe")
    st.caption("config/sectors.yaml -- 'active' sectors are scanned daily; 'candidate' sectors need a backtest promotion first.")
    try:
        with settings.SECTORS_FILE.open() as f:
            sectors_cfg = yaml.safe_load(f) or {}
        rows = [
            {"Sector": name, "Status": cfg.get("status", "active"), "Tickers": len(cfg.get("tickers", []))}
            for name, cfg in sectors_cfg.items()
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
    except FileNotFoundError:
        st.warning(f"{settings.SECTORS_FILE} not found.")

    st.subheader("Optional data sources")
    st.caption("Whether credentials are present in .env -- never shows the values themselves.")
    rows = [
        {"Source": "SEC_USER_AGENT", "Required": "Yes", "Configured": "your-email" not in settings.SEC_USER_AGENT and "your-real-email" not in settings.SEC_USER_AGENT},
        {"Source": "FINNHUB_API_KEY (market data fallback)", "Required": "No", "Configured": bool(settings.FINNHUB_API_KEY)},
        {"Source": "REDDIT_CLIENT_ID/SECRET", "Required": "No", "Configured": bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET)},
        {"Source": "PATENTSVIEW_API_KEY", "Required": "No", "Configured": bool(os.environ.get("PATENTSVIEW_API_KEY", "").strip())},
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption("See the Data Health page for live connectivity, not just whether a key is present.")
