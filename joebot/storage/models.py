"""SQLAlchemy models for JoeBot's SQLite store.

Phase 1 defines `candidates` and `signals_history`. Phase 2 adds
`filings_events` (raw SEC filing hits, replayable for Phase 3's backtest).
Phase 3 will further extend this file (backtest_runs,
backtest_window_results, signal_attribution) rather than creating parallel
storage.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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


class FilingEvent(Base):
    """One raw SEC filing hit (13D/13G/8-K) discovered by a catalyst signal.

    Deduped by accession_no across runs so the same filing isn't stored
    twice as it keeps appearing in the lookback window day after day. This
    table is what Phase 3's backtester replays -- it needs the raw filing
    history, not just the day-of composite score.
    """

    __tablename__ = "filings_events"
    __table_args__ = (UniqueConstraint("accession_no", name="uq_filings_events_accession_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    form: Mapped[str] = mapped_column(String)
    filing_date: Mapped[str] = mapped_column(String)  # ISO date
    accession_no: Mapped[str] = mapped_column(String)
    filer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
