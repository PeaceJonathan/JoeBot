"""Today's picks view: the latest scan's candidates, live-filtered by the
risk slider against already-persisted data (no re-fetch on every slider
move -- see joebot/screener/composite.py::passes_risk_filter).
"""
from __future__ import annotations

import streamlit as st

from joebot.reporting.horizon import LONG_TERM, MEDIUM_TERM, SHORT_TERM, classify_horizon
from joebot.reporting.narrative import build_narrative
from joebot.risk.profile import get_risk_profile
from joebot.screener.composite import passes_risk_filter
from joebot.storage.queries import latest_candidates


def render(risk_slider_value: float) -> None:
    st.header("Today's Picks")

    run, candidates = latest_candidates()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first, or click 'Re-run scan now' in the sidebar.")
        return

    attempted = run.tickers_attempted or 0
    skipped = run.tickers_skipped_json or []
    st.caption(f"Scan as of {run.as_of_date} (run at {run.run_at} UTC) -- {len(candidates)} tickers scanned.")

    if skipped:
        # A ticker only lands here if EVERY signal failed for it outright
        # (an exception, not a normal low/zero score) -- most often a
        # transient API rate-limit (see joebot/data/market_data.py's
        # retry-with-backoff for yfinance's 429s) or a renamed/delisted
        # symbol still listed in config/sectors.yaml. Surfaced prominently
        # rather than left as a silently smaller table, since "why did I
        # only get 2 candidates out of a 39-ticker universe" should never
        # require reading a terminal log to answer.
        st.warning(
            f"{len(skipped)}/{attempted} tickers in the configured universe were skipped entirely this "
            f"scan (every signal failed for them) -- this is usually a rate limit or a stale ticker in "
            f"config/sectors.yaml, not a real 'nothing here.' Try 'Re-run scan now' again in a minute, or "
            f"check the Data Health page."
        )
        with st.expander(f"Show all {len(skipped)} skipped tickers and why"):
            st.dataframe(
                [{"Ticker": s.get("ticker"), "Sector": s.get("sector"), "Reason": s.get("reason")} for s in skipped],
                width="stretch", hide_index=True,
            )
    elif attempted and len(candidates) < attempted:
        st.caption(f"({attempted - len(candidates)} of {attempted} attempted tickers produced no candidate row.)")

    risk_profile = get_risk_profile(risk_slider_value)
    filtered = []
    for c in candidates:
        tech = c.signals.get("technical_breakout", {}).get("metadata", {})
        signal_scores = {name: s["score"] for name, s in c.signals.items()}
        if passes_risk_filter(
            tech.get("atr_pct_of_price"), tech.get("avg_dollar_volume"), tech.get("market_cap"),
            risk_profile, signal_scores,
        ):
            filtered.append(c)

    st.caption(f"{len(filtered)}/{len(candidates)} pass the **{risk_profile.name}** risk profile (slider={risk_slider_value:.0f}).")

    if not filtered:
        st.warning("No candidates pass this risk profile. Try a higher risk slider value.")
        return

    horizons = {
        c.ticker: classify_horizon({name: s["score"] for name, s in c.signals.items()})
        for c in filtered
    }

    horizon_labels = {SHORT_TERM: "Short-term", MEDIUM_TERM: "Medium-term", LONG_TERM: "Long-term"}
    selected_labels = st.multiselect(
        "Horizon", list(horizon_labels.values()), default=list(horizon_labels.values()),
        help="Not measured or backtested -- a per-signal-family judgment call about how that type of "
             "catalyst typically plays out (e.g. a price breakout is short-term, a patent/IP thesis is "
             "long-term). See joebot/reporting/horizon.py.",
    )
    selected_keys = {k for k, label in horizon_labels.items() if label in selected_labels}
    filtered = [c for c in filtered if horizons[c.ticker].horizon in selected_keys]

    if not filtered:
        st.warning("No candidates match the selected horizon(s).")
        return

    rows = []
    for c in filtered:
        row = {"Rank": c.rank, "Ticker": c.ticker, "Sector": c.sector, "Score": round(c.composite_score, 3), "Horizon": horizons[c.ticker].display}
        for name, sig in c.signals.items():
            row[name] = round(sig["score"], 2)
        rows.append(row)

    st.dataframe(rows, width="stretch", hide_index=True)

    st.caption(
        "Score is a weighted composite across all signals -- see "
        "config/settings.py::DEFAULT_SIGNAL_WEIGHTS and run "
        "`python scripts/run_backtest.py` before trusting these weights."
    )

    st.subheader("Why now")
    ticker_options = [c.ticker for c in filtered]
    selected = st.selectbox("Ticker", ticker_options)
    selected_candidate = next(c for c in filtered if c.ticker == selected)

    card = build_narrative(selected_candidate.to_ranked_candidate())
    st.markdown(f"**Verdict:** {card.verdict}")
    if card.horizon:
        driven_by = f" -- driven by `{card.horizon.driven_by}`" if card.horizon.driven_by else ""
        st.markdown(f"**Horizon:** {card.horizon.display}{driven_by}")
    st.markdown("**Why now:**")
    for b in card.why_bullets:
        st.markdown(f"- {b}")
    st.markdown("**Bear case -- what could go wrong:**")
    for b in card.risk_bullets:
        st.markdown(f"- {b}")
    if card.data_gap_bullets:
        st.markdown("**Data gaps:**")
        for b in card.data_gap_bullets:
            st.markdown(f"- {b}")
    if card.timeline:
        st.markdown("**Event timeline:**")
        for t in card.timeline:
            st.markdown(f"- {t}")

    with st.expander("Raw signal data (for debugging)"):
        for name, sig in selected_candidate.signals.items():
            st.write(f"**{name}** -- score={sig['score']:.3f}, confidence={sig['confidence']:.2f}")
            st.json(sig["metadata"])
