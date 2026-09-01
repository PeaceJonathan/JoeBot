"""Loads the live screening ticker universe from config/sectors.yaml.

This is the *live* universe only. Phase 3's backtester needs a separate
historical universe (joebot/backtest/universe_builder.py) that also includes
delisted/bankrupt tickers -- do not reuse this module for backtesting.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from config import settings


@dataclass(frozen=True)
class Sector:
    name: str
    description: str
    tickers: tuple[str, ...]


def load_sectors() -> dict[str, Sector]:
    with settings.SECTORS_FILE.open("r") as f:
        raw = yaml.safe_load(f) or {}

    sectors: dict[str, Sector] = {}
    for name, body in raw.items():
        tickers = tuple(dict.fromkeys(body.get("tickers", [])))  # de-dupe, preserve order
        sectors[name] = Sector(
            name=name,
            description=(body.get("description") or "").strip(),
            tickers=tickers,
        )
    return sectors


def all_tickers() -> list[str]:
    """Flat, de-duplicated list of every ticker across every sector."""
    seen: dict[str, None] = {}
    for sector in load_sectors().values():
        for ticker in sector.tickers:
            seen[ticker] = None
    return list(seen.keys())


def sector_for_ticker(ticker: str) -> list[str]:
    """A ticker can legitimately appear in more than one sector (e.g. PLTR)."""
    return [s.name for s in load_sectors().values() if ticker in s.tickers]
