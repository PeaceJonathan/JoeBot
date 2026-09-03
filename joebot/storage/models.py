"""SQLAlchemy models for JoeBot's SQLite store.

Phase 1 defines `candidates` and `signals_history`. Phase 2 adds
`filings_events` (raw SEC filing hits, replayable for Phase 3's backtest).
Phase 3 adds `backtest_runs` and `signal_attributions` so the dashboard's
backtest view (Phase 5) can browse past runs without re-running them.
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

    # How many tickers the configured universe actually contained
    # (joebot/screener/sector_screens.py::ScreenResult.attempted) vs. how
    # many produced zero candidates because every signal raised for them
    # (e.g. a Yahoo Finance rate-limit mid-scan, a renamed/delisted
    # symbol -- see ScreenResult's docstring). len(candidates) alone can't
    # distinguish "the universe is just small" from "most of it silently
    # failed," which is exactly the confusion this exists to prevent.
    tickers_attempted: Mapped[int] = mapped_column(Integer, default=0)
    tickers_skipped_json: Mapped[list] = mapped_column(JSON, default=list)  # [{"ticker","sector","reason"}, ...]

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


class DataHealthRecord(Base):
    """One external source's connectivity status as of one scan run --
    a persisted snapshot of joebot/data/health.py's in-process registry, so
    the dashboard's Data Health panel (section 16) reflects the health of
    whichever process actually ran the scan (a cron job, most often) rather
    than only the Streamlit process's own, separate in-memory state.
    """

    __tablename__ = "data_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"))
    source: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[str | None] = mapped_column(String, nullable=True)
    last_attempt_at: Mapped[str | None] = mapped_column(String, nullable=True)


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


class BacktestRun(Base):
    """One walk-forward backtest invocation (scripts/run_backtest.py)."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    start_date: Mapped[str] = mapped_column(String)  # ISO date
    end_date: Mapped[str] = mapped_column(String)  # ISO date
    step_days: Mapped[int] = mapped_column(Integer)
    calibration_cutoff: Mapped[str] = mapped_column(String)  # ISO date
    n_records: Mapped[int] = mapped_column(Integer)

    attributions: Mapped[list["SignalAttributionRecord"]] = relationship(back_populates="backtest_run")


class SignalAttributionRecord(Base):
    """One signal family's evaluation-fold attribution result from one backtest run.

    This -- not the calibration fold, and never a single anecdote -- is
    what DEFAULT_SIGNAL_WEIGHTS changes must cite, per this project's hard
    rule against data-snooping.
    """

    __tablename__ = "signal_attributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"))
    signal_name: Mapped[str] = mapped_column(String)
    horizon: Mapped[str] = mapped_column(String)  # "short" or "long"
    n_observations: Mapped[int] = mapped_column(Integer)
    n_dates: Mapped[int] = mapped_column(Integer)
    top_half_mean_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    bottom_half_mean_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_mean_return: Mapped[float | None] = mapped_column(Float, nullable=True)

    backtest_run: Mapped[BacktestRun] = relationship(back_populates="attributions")
