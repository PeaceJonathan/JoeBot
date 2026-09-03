"""Read-only query helpers over the SQLite store, shared by the dashboard
(and usable from a plain script/REPL without pulling in Streamlit).
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from joebot.screener.composite import RankedCandidate
from joebot.signals.base import SignalResult
from joebot.storage.db import get_session
from joebot.storage.models import BacktestRun, Candidate, DataHealthRecord, ScanRun, SignalAttributionRecord


@dataclasses.dataclass
class CandidateView:
    ticker: str
    sector: str
    composite_score: float
    rank: int
    signals: dict[str, dict]  # signal_name -> {"score", "confidence", "metadata"}
    as_of_date: str | None = None

    def to_ranked_candidate(self) -> RankedCandidate:
        """Reconstructs a RankedCandidate (SignalResult objects, not plain
        dicts) so DB-backed views can reuse joebot/reporting/narrative.py --
        the same narrative builder a fresh scan's report uses."""
        return RankedCandidate(
            ticker=self.ticker,
            sector=self.sector,
            composite_score=self.composite_score,
            signal_results={
                name: SignalResult(score=s["score"], confidence=s["confidence"], metadata=s["metadata"])
                for name, s in self.signals.items()
            },
            as_of_date=dt.date.fromisoformat(self.as_of_date) if self.as_of_date else None,
        )


def latest_scan_run() -> ScanRun | None:
    session = get_session()
    try:
        return session.query(ScanRun).order_by(ScanRun.run_at.desc()).first()
    finally:
        session.close()


def candidates_for_run(scan_run_id: int) -> list[CandidateView]:
    session = get_session()
    try:
        scan_run = session.get(ScanRun, scan_run_id)
        as_of_date = scan_run.as_of_date if scan_run else None
        rows = (
            session.query(Candidate)
            .filter(Candidate.scan_run_id == scan_run_id)
            .order_by(Candidate.rank)
            .all()
        )
        views = []
        for row in rows:
            signals = {
                sh.signal_name: {"score": sh.score, "confidence": sh.confidence, "metadata": sh.metadata_json}
                for sh in row.signal_results
            }
            views.append(CandidateView(
                ticker=row.ticker, sector=row.sector, composite_score=row.composite_score,
                rank=row.rank, signals=signals, as_of_date=as_of_date,
            ))
        return views
    finally:
        session.close()


def latest_candidates() -> tuple[ScanRun | None, list[CandidateView]]:
    run = latest_scan_run()
    if run is None:
        return None, []
    return run, candidates_for_run(run.id)


def list_backtest_runs(limit: int = 20) -> list[BacktestRun]:
    session = get_session()
    try:
        return session.query(BacktestRun).order_by(BacktestRun.run_at.desc()).limit(limit).all()
    finally:
        session.close()


def data_health_for_run(scan_run_id: int) -> list[DataHealthRecord]:
    session = get_session()
    try:
        return (
            session.query(DataHealthRecord)
            .filter(DataHealthRecord.scan_run_id == scan_run_id)
            .order_by(DataHealthRecord.source)
            .all()
        )
    finally:
        session.close()


def latest_data_health() -> tuple[ScanRun | None, list[DataHealthRecord]]:
    """Data Health as of the most recent scan -- whichever process ran it
    (cron job or dashboard), since this reads the persisted snapshot rather
    than joebot/data/health.py's in-process registry directly."""
    run = latest_scan_run()
    if run is None:
        return None, []
    return run, data_health_for_run(run.id)


def attributions_for_run(backtest_run_id: int) -> list[SignalAttributionRecord]:
    session = get_session()
    try:
        return (
            session.query(SignalAttributionRecord)
            .filter(SignalAttributionRecord.backtest_run_id == backtest_run_id)
            .order_by(SignalAttributionRecord.horizon, SignalAttributionRecord.signal_name)
            .all()
        )
    finally:
        session.close()
