"""Read-only query helpers over the SQLite store, shared by the dashboard
(and usable from a plain script/REPL without pulling in Streamlit).
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from joebot.storage.db import get_session
from joebot.storage.models import BacktestRun, Candidate, ScanRun, SignalAttributionRecord


@dataclasses.dataclass
class CandidateView:
    ticker: str
    sector: str
    composite_score: float
    rank: int
    signals: dict[str, dict]  # signal_name -> {"score", "confidence", "metadata"}


def latest_scan_run() -> ScanRun | None:
    session = get_session()
    try:
        return session.query(ScanRun).order_by(ScanRun.run_at.desc()).first()
    finally:
        session.close()


def candidates_for_run(scan_run_id: int) -> list[CandidateView]:
    session = get_session()
    try:
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
                rank=row.rank, signals=signals,
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
