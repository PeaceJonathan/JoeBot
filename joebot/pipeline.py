"""Orchestration seam shared by scripts/run_daily.py (cron) and the future
Streamlit dashboard (Phase 5). Both must call these functions rather than
duplicating scan logic, so the unattended report and the on-demand dashboard
view never drift apart.
"""
from __future__ import annotations

import datetime as dt
import logging

from joebot.screener.composite import RankedCandidate
from joebot.screener.sector_screens import run_all_sectors
from joebot.storage.db import get_session
from joebot.storage.models import Candidate, ScanRun, SignalHistory

log = logging.getLogger(__name__)


def run_daily_scan(as_of_date: dt.date | None = None) -> list[RankedCandidate]:
    """Run the full sector screener and persist results. Returns ranked candidates."""
    as_of_date = as_of_date or dt.date.today()

    candidates = run_all_sectors(as_of_date)
    _persist_scan(as_of_date, candidates)
    return candidates


def _persist_scan(as_of_date: dt.date, candidates: list[RankedCandidate]) -> None:
    session = get_session()
    try:
        scan_run = ScanRun(run_at=dt.datetime.utcnow(), as_of_date=as_of_date.isoformat())
        session.add(scan_run)
        session.flush()  # assigns scan_run.id

        for rank, candidate in enumerate(candidates, start=1):
            row = Candidate(
                scan_run_id=scan_run.id,
                ticker=candidate.ticker,
                sector=candidate.sector,
                composite_score=candidate.composite_score,
                rank=rank,
            )
            session.add(row)
            session.flush()  # assigns row.id

            for signal_name, result in candidate.signal_results.items():
                session.add(
                    SignalHistory(
                        candidate_id=row.id,
                        signal_name=signal_name,
                        score=result.score,
                        confidence=result.confidence,
                        metadata_json=result.metadata,
                    )
                )

        session.commit()
    finally:
        session.close()
