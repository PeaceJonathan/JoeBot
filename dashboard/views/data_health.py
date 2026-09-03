"""Data Health panel (section 16): shows every external source's live
connectivity status as of the most recent scan, whichever process ran it.

This is a hard requirement, not a nice-to-have: a signal that scores 0
because its data source was unreachable must never look identical to a
signal that scored 0 because it genuinely found nothing. See
joebot/data/health.py and joebot/signals/base.py::with_source_status.
"""
from __future__ import annotations

import streamlit as st

from joebot.data import health
from joebot.storage.queries import latest_data_health

_STATUS_LABEL = {
    health.OK: "Connected",
    health.UNAVAILABLE: "Unreachable",
    health.NOT_CONFIGURED: "Not configured (optional)",
}


def render() -> None:
    st.header("Data Health")
    st.caption(
        "Connectivity as of the most recent scan (scripts/run_daily.py or a "
        "dashboard 'Re-run scan now'). A source can be unreachable even when "
        "everything else in JoeBot works -- a 0.0 score from an unreachable "
        "source means 'unknown,' not 'no.'"
    )

    run, records = latest_data_health()
    if run is None:
        st.info("No scan has been run yet. Run `python scripts/run_daily.py` first, or click 'Re-run scan now' in the sidebar.")
        return

    st.caption(f"Last scan: {run.as_of_date} (run at {run.run_at} UTC)")

    by_source = {r.source: r for r in records}
    rows = []
    for source in health.ALL_SOURCES:
        r = by_source.get(source)
        display = health.DISPLAY_NAMES.get(source, source)
        if r is None:
            rows.append({"Source": display, "Status": "⚪ Not called this scan", "Detail": "", "Calls": 0, "Failures": 0, "Last success": ""})
            continue
        emoji = {"ok": "\U0001F7E2", "unavailable": "\U0001F534", "not_configured": "\U0001F7E1"}.get(r.status, "⚪")
        rows.append({
            "Source": display,
            "Status": f"{emoji} {_STATUS_LABEL.get(r.status, r.status)}",
            "Detail": r.detail or "",
            "Calls": r.call_count,
            "Failures": r.failure_count,
            "Last success": r.last_success_at or "never this scan",
        })

    st.dataframe(rows, width="stretch", hide_index=True)

    unavailable = [r for r in records if r.status == health.UNAVAILABLE]
    if unavailable:
        st.error(
            f"{len(unavailable)} source(s) were unreachable during the last scan: "
            + ", ".join(health.DISPLAY_NAMES.get(r.source, r.source) for r in unavailable)
            + ". Any candidate whose score leaned on these signals has an incomplete picture -- "
              "check that candidate's 'Data gaps' section before trusting a low score as a real negative."
        )

    not_configured = [r for r in records if r.status == health.NOT_CONFIGURED]
    if not_configured:
        st.warning(
            "Optional sources not configured: "
            + ", ".join(health.DISPLAY_NAMES.get(r.source, r.source) for r in not_configured)
            + ". These signals score 0 for every candidate until you add credentials in .env -- see README."
        )

    st.caption(
        "This panel reflects the most recent scan only, not a live connection check right now. "
        "For a real live-network smoke test, run `python scripts/validate_live_data.py` from a "
        "terminal on a machine with normal internet access."
    )
