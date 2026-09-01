"""SQLAlchemy models for JoeBot's SQLite store.

Phase 1 defines `candidates` and `signals_history`. Later phases extend this
file (filings_events in Phase 2; backtest_runs, backtest_window_results,
signal_attribution in Phase 3) rather than creating parallel storage.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanRun(Base):
    """One invocation of the daily scan (or an on-demand dashboard re-run)."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    as_of_date: Mapped[dt.date] = mapped_column(String)  # stored as ISO date string

    candidates: Mapped[list["Candidate"]] = relationship(back_populates="scan_run")


class Candidate(Base):
    """One ranked ticker from one scan run, with full signal provenance."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(String, index=True)
    sector: Mapped[str] = mapped_column(String)
    composite_score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)

    scan_run: Mapped[ScanRun] = relationship(back_populates="candidates")
    signal_results: Mapped[list["SignalHistory"]] = relationship(back_populates="candidate")


class SignalHistory(Base):
    """One signal's result for one candidate -- the provenance record."""

    __tablename__ = "signals_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    signal_name: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    candidate: Mapped[Candidate] = relationship(back_populates="signal_results")
