#!/usr/bin/env python3
"""Cron entrypoint: run the daily scan and write a report + DB rows.

This script is the source of truth for the unattended path -- it must work
identically whether or not the Streamlit dashboard is running. Example cron
entry (see README.md): 0 7 * * 1-5 cd /path/to/JoeBot && python scripts/run_daily.py
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from joebot import pipeline  # noqa: E402
from joebot.reporting.report_writer import write_report  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_daily")


def main() -> None:
    as_of_date = dt.date.today()
    log.info("Starting daily scan for %s", as_of_date.isoformat())

    candidates = pipeline.run_daily_scan(as_of_date)
    log.info("Scan complete: %d candidates ranked", len(candidates))

    report_path = write_report(as_of_date, candidates)
    log.info("Report written to %s", report_path)


if __name__ == "__main__":
    main()
