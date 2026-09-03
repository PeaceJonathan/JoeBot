"""Candidate Detail: the full non-black-box breakdown for one ticker --
per-signal score breakdown, why now, bear case, data gaps, and event
timeline (sections 10, 11, 23). Search across every scanned candidate from
the latest run, not just the risk-filtered set.
"""
from __future__ import annotations

import streamlit as st

from joebot.reporting.narrative import build_narrative
from joebot.storage.queries import latest_candidates

_SIGNAL_LABELS = {
    "technical_breakout": "Technical",
    "fundamental_sanity": "Fundamentals",
    "activist_stake": "Ownership/Activist",
    "insider_buying": "Insider Buying",
    "leadership_change": "Leadership",
    "sentiment_reddit": "Sentiment",
    "clinical_trial": "Clinical",
    "gov_contract": "Government",
    "patent_activity": "Patent/IP",
}


def render() -> None:
    st.header("Candidate Detail")

    run, candidates = latest_candidates()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first, or click 'Re-run scan now' in the sidebar.")
        return

    ticker_options = [c.ticker for c in candidates]
    selected = st.selectbox("Ticker", ticker_options)
    c = next(cand for cand in candidates if cand.ticker == selected)
    ranked = c.to_ranked_candidate()
    card = build_narrative(ranked)

    st.subheader(f"{card.ticker} ({card.sector}) -- {card.composite_score * 100:.0f}/100")
    st.markdown(f"**Verdict:** {card.verdict}")

    st.markdown("### Score breakdown")
    cols = st.columns(len(c.signals) or 1)
    for col, (name, sig) in zip(cols, sorted(c.signals.items())):
        label = _SIGNAL_LABELS.get(name, name)
        col.metric(label, f"{sig['score'] * 100:.0f}", help=f"confidence {sig['confidence']:.2f} -- {name}")

    st.markdown("### Why now")
    for b in card.why_bullets:
        st.markdown(f"- {b}")

    st.markdown("### Bear case -- what could go wrong")
    for b in card.risk_bullets:
        st.markdown(f"- {b}")

    if card.data_gap_bullets:
        st.markdown("### Data gaps")
        st.warning("This candidate's score is built on incomplete data for at least one signal:")
        for b in card.data_gap_bullets:
            st.markdown(f"- {b}")

    if card.timeline:
        st.markdown("### Event timeline")
        for t in card.timeline:
            st.markdown(f"- {t}")
    else:
        st.caption("No dated events found for this candidate in the tracked signals.")

    st.markdown("### Historical comparison")
    st.info(
        "Per-candidate historical comparison (\"similar setups historically performed X\") "
        "isn't implemented -- it would need matching this candidate's signal profile against "
        "the backtester's historical observations, which scripts/run_backtest.py doesn't yet "
        "expose per-candidate. See the Research page for signal-family-level evidence instead, "
        "and treat that as the closest available substitute."
    )

    with st.expander("Raw signal data (for your own due diligence)"):
        for name, sig in c.signals.items():
            st.write(f"**{name}** -- score={sig['score']:.3f}, confidence={sig['confidence']:.2f}")
            st.json(sig["metadata"])
