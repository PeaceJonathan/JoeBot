"""Writes the daily ranked-candidate report to a markdown file.

This is deliberately plain markdown, not HTML/PDF, so it's easy to read from
a terminal, an editor, or piped into anything else later.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from config import settings
from config.settings import RiskProfile
from joebot.risk.position_sizing import PositionSuggestion
from joebot.screener.composite import RankedCandidate

DISCLAIMER = (
    "JoeBot is a personal decision-support tool. It never places trades or "
    "connects to any brokerage. Nothing here is financial advice -- verify "
    "everything yourself before acting on it, and remember every signal in "
    "this report is only as trustworthy as its own backtest evidence -- see "
    "scripts/run_backtest.py's output before weighting any of this heavily."
)


def write_report(
    as_of_date: dt.date,
    candidates: list[RankedCandidate],
    top_n: int = 25,
    risk_profile: RiskProfile | None = None,
    budget: float | None = None,
    position_suggestions: list[PositionSuggestion] | None = None,
) -> Path:
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

    if risk_profile is not None and budget is not None:
        lines += [
            "",
            f"## Suggested position sizing -- risk profile: {risk_profile.name}, budget: ${budget:,.2f}",
            "",
            "This is a manual-entry suggestion for your own brokerage -- JoeBot "
            "never places an order. Re-run with a different --budget/--risk-slider, "
            "or use the dashboard for an interactive slider (see README).",
            "",
        ]
        if not position_suggestions:
            lines.append("_No candidates passed the risk filter and had enough data to size a position._")
        else:
            lines += [
                "| Ticker | Shares | $ Amount | Entry | Stop |",
                "|---|---|---|---|---|",
            ]
            for s in position_suggestions:
                lines.append(
                    f"| {s.ticker} | {s.shares} | ${s.dollar_amount:,.2f} | "
                    f"${s.entry_price:.2f} | ${s.stop_price:.2f} |"
                )

    path.write_text("\n".join(lines) + "\n")
    return path
