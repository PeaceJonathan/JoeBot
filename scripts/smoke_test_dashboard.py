#!/usr/bin/env python3
"""Dashboard smoke test using Streamlit's official AppTest harness: runs
every page in dashboard/app.py's sidebar radio and fails if any of them
raises. This is real verification, not a syntax check -- it actually
executes each view's render() against whatever is in data/joebot.db.

Run scripts/smoke_test_synthetic.py first (or scripts/run_daily.py, or the
dashboard's "Re-run scan now") to populate data/joebot.db with something to
render -- an empty DB is also a valid state to test (every view has an
"no scan yet" branch) but exercises less of each page's logic.

Usage:
    python scripts/smoke_test_dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PAGES = [
    "Dashboard", "Discover", "Candidate Detail", "Catalysts",
    "Research", "Portfolio", "Data Health", "Settings",
]


def main() -> int:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT_DIR / "dashboard" / "app.py"), default_timeout=60)
    at.run()

    failures = []
    if at.exception:
        failures.append(("<initial load>", list(at.exception)))

    for page in PAGES:
        at.radio[0].set_value(page)
        at.run()
        if at.exception:
            failures.append((page, list(at.exception)))
        print(f"{page:<18} {'FAIL' if at.exception else 'OK'}")

    if failures:
        print(f"\n{len(failures)} page(s) raised an exception:")
        for page, excs in failures:
            print(f"\n--- {page} ---")
            for e in excs:
                print(f"  {e}")
        return 1

    print("\nAll dashboard pages rendered without raising.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
