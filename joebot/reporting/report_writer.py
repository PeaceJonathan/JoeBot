"""Writes the daily ranked-candidate report to a markdown file.

This is deliberately plain markdown, not HTML/PDF, so it's easy to read from
a terminal, an editor, or piped into anything else later.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from config import settings
from joebot.screener.composite import RankedCandidate

DISCLAIMER = (
    "JoeBot is a personal decision-support tool. It never places trades or "
    "connects to any brokerage. Nothing here is financial advice -- verify "
    "everything yourself before acting on it, and remember small/mid-cap "
    "signals in this report are not yet backtested for predictive validity "
    "(that's Phase 3)."
)


def write_report(as_of_date: dt.date, candidates: list[RankedCandidate], top_n: int = 25) -> Path:
    settings.ensure_dirs()
    path = settings.REPORTS_DIR / f"{as_of_date.isoformat()}.md"

    lines = [
        f"# JoeBot Daily Scan -- {as_of_date.isoformat()}",
        "",
        f"> {DISCLAIMER}",
        "",
        f"{len(candidates)} tickers scanned. Top {min(top_n, len(candidates))} shown below.",
        "",
        "| Rank | Ticker | Sector | Score | Details |",
        "|---|---|---|---|---|",
    ]

    for rank, candidate in enumerate(candidates[:top_n], start=1):
        details = "; ".join(
            f"{name}={result.score:.2f} (conf {result.confidence:.2f})"
            for name, result in candidate.signal_results.items()
        )
        lines.append(
            f"| {rank} | {candidate.ticker} | {candidate.sector} | "
            f"{candidate.composite_score:.3f} | {details} |"
        )

    path.write_text("\n".join(lines) + "\n")
    return path
