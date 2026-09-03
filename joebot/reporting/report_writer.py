"""Writes the daily ranked-candidate report to a markdown file.

This is deliberately plain markdown, not HTML/PDF, so it's easy to read from
a terminal, an editor, or piped into anything else later.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from config import settings
from config.settings import RiskProfile
from joebot.reporting.narrative import build_narrative
from joebot.risk.position_sizing import BudgetAllocation
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
    narrative_top_n: int = 10,
    risk_profile: RiskProfile | None = None,
    budget: float | None = None,
    allocation: BudgetAllocation | None = None,
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

    if candidates:
        lines += ["", f"## Top {min(narrative_top_n, len(candidates))} opportunities -- why they appeared", ""]
        for candidate in candidates[:narrative_top_n]:
            card = build_narrative(candidate)
            lines += [
                f"### {card.ticker} ({card.sector}) -- score {card.composite_score:.2f}",
                "",
                f"**Verdict:** {card.verdict}",
                "",
                "**Why now:**",
            ]
            lines += [f"- {b}" for b in card.why_bullets]
            lines += ["", "**Bear case -- what could go wrong:**"]
            lines += [f"- {b}" for b in card.risk_bullets]
            if card.data_gap_bullets:
                lines += ["", "**Data gaps (checked and reported, not hidden):**"]
                lines += [f"- {b}" for b in card.data_gap_bullets]
            if card.timeline:
                lines += ["", "**Event timeline:**"]
                lines += [f"- {t}" for t in card.timeline]
            lines.append("")

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
        suggestions = allocation.suggestions if allocation else []
        if not suggestions:
            lines.append(
                "_No candidate cleared the conviction floor with enough data to size a position -- "
                "the full budget stays in cash. That's a legitimate outcome, not an error._"
            )
        else:
            lines += [
                "| Ticker | Shares | $ Amount | Entry | Stop |",
                "|---|---|---|---|---|",
            ]
            for s in suggestions:
                lines.append(
                    f"| {s.ticker} | {s.shares} | ${s.dollar_amount:,.2f} | "
                    f"${s.entry_price:.2f} | ${s.stop_price:.2f} |"
                )
            if allocation is not None:
                lines += [
                    "",
                    f"**Allocated: ${allocation.allocated:,.2f} -- Reserved (cash): ${allocation.reserved_cash:,.2f}**",
                ]

    path.write_text("\n".join(lines) + "\n")
    return path
