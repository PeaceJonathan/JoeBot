"""Backtest results browser: read-only view over past scripts/run_backtest.py
runs. Does NOT trigger a new backtest from here -- a real walk-forward run
over years of history is slow and network-bound, not something to kick off
from a Streamlit callback. Run `python scripts/run_backtest.py` from a
terminal, then come back here to browse the result.
"""
from __future__ import annotations

import streamlit as st

from joebot.storage.queries import attributions_for_run, list_backtest_runs


def render() -> None:
    st.header("Backtest Results")
    st.caption(
        "Run `python scripts/run_backtest.py --years 3` from a terminal to "
        "produce a new result -- this page only browses past runs."
    )

    runs = list_backtest_runs()
    if not runs:
        st.info("No backtest runs yet. Run `python scripts/run_backtest.py` first.")
        return

    options = {
        f"#{r.id} -- {r.start_date} to {r.end_date} (step={r.step_days}d, {r.n_records} records, run {r.run_at} UTC)": r.id
        for r in runs
    }
    selected_label = st.selectbox("Backtest run", list(options.keys()))
    run_id = options[selected_label]

    attributions = attributions_for_run(run_id)
    if not attributions:
        st.warning("This run has no attribution records.")
        return

    st.caption(
        "spread = mean forward return of above-median-score names minus "
        "below-median-score names on the same as_of_date, evaluation-fold "
        "only (out-of-sample). Read n_observations alongside spread -- a "
        "low n means 'not enough evidence yet,' not 'the signal doesn't work.'"
    )

    for horizon in ("short", "long"):
        st.subheader(f"{horizon.title()}-horizon attribution")
        rows = [a for a in attributions if a.horizon == horizon]
        st.dataframe(
            [
                {
                    "Signal": a.signal_name,
                    "N obs": a.n_observations,
                    "N dates": a.n_dates,
                    "Top-half mean return": None if a.top_half_mean_return is None else round(a.top_half_mean_return, 4),
                    "Bottom-half mean return": None if a.bottom_half_mean_return is None else round(a.bottom_half_mean_return, 4),
                    "Spread": None if a.spread is None else round(a.spread, 4),
                    "Baseline mean return": None if a.baseline_mean_return is None else round(a.baseline_mean_return, 4),
                }
                for a in rows
            ],
            width="stretch",
            hide_index=True,
        )

    st.warning(
        "Per this project's hard rule, DEFAULT_SIGNAL_WEIGHTS in "
        "config/settings.py may only be changed based on a result like "
        "this one -- never hand-tuned on a full-history fit."
    )
