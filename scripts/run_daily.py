#!/usr/bin/env python3
"""Cron entrypoint: run the daily scan and write a report + DB rows.

This script is the source of truth for the unattended path -- it must work
identically whether or not the Streamlit dashboard is running. Example cron
entry (see README.md): 0 7 * * 1-5 cd /path/to/JoeBot && python scripts/run_daily.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings  # noqa: E402
from joebot import pipeline  # noqa: E402
from joebot.reporting.report_writer import write_report  # noqa: E402
from joebot.risk.position_sizing import allocate_budget  # noqa: E402
from joebot.risk.profile import get_risk_profile  # noqa: E402
from joebot.screener.composite import apply_risk_filter  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_daily")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--budget", type=float, default=settings.DEFAULT_BUDGET,
        help="Dollar amount to size the standalone report's position suggestions against.",
    )
    parser.add_argument(
        "--risk-slider", type=float, default=settings.DEFAULT_RISK_SLIDER,
        help="0 (conservative) to 100 (aggressive); see joebot/risk/profile.py.",
    )
    args = parser.parse_args()

    as_of_date = dt.date.today()
    log.info("Starting daily scan for %s", as_of_date.isoformat())

    candidates = pipeline.run_daily_scan(as_of_date)
    log.info("Scan complete: %d candidates ranked", len(candidates))

    risk_profile = get_risk_profile(args.risk_slider)
    filtered = apply_risk_filter(candidates, risk_profile)
    log.info("%d/%d candidates passed the '%s' risk filter", len(filtered), len(candidates), risk_profile.name)

    ranked_tuples = []
    for c in filtered:
        tech_signal = c.signal_results.get("technical_breakout")
        tech_meta = tech_signal.metadata if tech_signal else {}
        ranked_tuples.append((c.ticker, tech_meta.get("close"), tech_meta.get("atr")))

    suggestions = allocate_budget(ranked_tuples, budget=args.budget, risk_profile=risk_profile)
    log.info("Position sizing: %d suggestions against a $%.2f budget", len(suggestions), args.budget)

    report_path = write_report(
        as_of_date, candidates,
        risk_profile=risk_profile, budget=args.budget, position_suggestions=suggestions,
    )
    log.info("Report written to %s", report_path)


if __name__ == "__main__":
    main()
