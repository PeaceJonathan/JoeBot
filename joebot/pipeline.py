"""Orchestration seam shared by scripts/run_daily.py (cron) and the future
Streamlit dashboard (Phase 5). Both must call these functions rather than
duplicating scan logic, so the unattended report and the on-demand dashboard
view never drift apart.
"""
from __future__ import annotations

import datetime as dt
import logging

from joebot.data import health
from joebot.screener.composite import RankedCandidate
from joebot.screener.sector_screens import run_all_sectors
from joebot.storage.db import get_session
from joebot.storage.models import Candidate, DataHealthRecord, FilingEvent, ScanRun, SignalHistory

log = logging.getLogger(__name__)

# Signal names whose metadata carries a "filings" list of raw filing dicts
# (see joebot/signals/catalyst_sec.py and joebot/data/sec_client.py) to be
# persisted into filings_events for Phase 3's backtester to replay.
_FILING_SIGNAL_NAMES = ("activist_stake", "leadership_change")


def run_daily_scan(as_of_date: dt.date | None = None) -> list[RankedCandidate]:
    """Run the full sector screener and persist results. Returns ranked candidates."""
    as_of_date = as_of_date or dt.date.today()

    # Reset before scanning so this run's persisted Data Health snapshot
    # reflects only this run's calls -- a long-lived process (the Streamlit
    # dashboard, across repeated "Re-run scan now" clicks) would otherwise
    # carry stale status from a previous run for any source this run never
    # happened to call again (e.g. skipped due to an empty candidate list).
    health.reset()

    candidates = run_all_sectors(as_of_date)
    _persist_scan(as_of_date, candidates)
    return candidates


def _persist_scan(as_of_date: dt.date, candidates: list[RankedCandidate]) -> None:
    session = get_session()
    try:
        existing_accessions = {row[0] for row in session.query(FilingEvent.accession_no).all()}
        seen_this_run: set[str] = set()

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

                if signal_name in _FILING_SIGNAL_NAMES:
                    for raw in result.metadata.get("filings", []):
                        accession_no = raw.get("accession_no")
                        if not accession_no or accession_no in existing_accessions or accession_no in seen_this_run:
                            continue
                        seen_this_run.add(accession_no)
                        session.add(
                            FilingEvent(
                                ticker=raw.get("ticker", candidate.ticker),
                                form=raw.get("form", ""),
                                filing_date=raw.get("filing_date", as_of_date.isoformat()),
                                accession_no=accession_no,
                                filer_name=raw.get("filer_name"),
                                metadata_json=raw,
                            )
                        )

        for source, source_health in health.snapshot().items():
            session.add(DataHealthRecord(
                scan_run_id=scan_run.id,
                source=source,
                status=source_health.status,
                detail=source_health.detail,
                call_count=source_health.call_count,
                failure_count=source_health.failure_count,
                last_success_at=source_health.last_success_at,
                last_attempt_at=source_health.last_attempt_at,
            ))

        session.commit()
    finally:
        session.close()
