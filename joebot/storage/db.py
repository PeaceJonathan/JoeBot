"""SQLite engine/session setup for JoeBot."""
from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from joebot.storage.models import Base

log = logging.getLogger(__name__)

_engine = None
_SessionLocal: sessionmaker | None = None

# SQLAlchemy type -> SQLite column type, for the minimal ALTER TABLE
# migration below. Only the handful of types this project's models
# actually use -- not a general-purpose mapping.
_SQLITE_TYPE_BY_PYTHON = {int: "INTEGER", float: "REAL", str: "TEXT", dict: "TEXT", list: "TEXT"}


def _migrate_missing_columns(engine) -> None:
    """Adds any column present on a declared model but missing from the
    actual (already-existing) SQLite file, via a plain ALTER TABLE.

    This project has no migration framework (Alembic, etc.) -- Base.metadata
    .create_all() only creates missing TABLES, never adds columns to a
    table that already exists. Without this, adding a column to an existing
    model (as this session did for ScanRun.tickers_attempted/
    tickers_skipped_json) would raise "no such column" on every real,
    already-populated data/joebot.db from before that change, rather than
    just picking up the new column. SQLite's ALTER TABLE ADD COLUMN is
    simple enough (no defaults/constraints/rename) that this covers this
    project's actual needs without pulling in a real migration tool.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # brand-new table -- create_all() already handled it
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                sqlite_type = _SQLITE_TYPE_BY_PYTHON.get(column.type.python_type, "TEXT")
                log.info("Migrating %s: adding missing column %s %s", table.name, column.name, sqlite_type)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {sqlite_type}'))


def get_engine():
    global _engine
    if _engine is None:
        settings.ensure_dirs()
        _engine = create_engine(f"sqlite:///{settings.DB_PATH}")
        Base.metadata.create_all(_engine)
        _migrate_missing_columns(_engine)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()
