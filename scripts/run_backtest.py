#!/usr/bin/env python3
"""CLI: run a walk-forward backtest over the tracked universe and report
which signal families actually predicted forward returns.

Usage:
    python scripts/run_backtest.py --years 3 --step-days 30

Results print to stdout and persist to backtest_runs/signal_attributions in
the same SQLite DB the daily scan uses, so the dashboard's backtest view
(Phase 5) can browse past runs.

Remember the standing caveats (see README): free data sources here don't
give point-in-time fundamentals or a fully comprehensive delisted-ticker
universe, catalyst-signal sample sizes will be small, and
fundamental_sanity's attribution carries a residual look-ahead risk (see
joebot/backtest/point_in_time.py's docstring). Read n_observations, not
just the spread.
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

from joebot.backtest import signal_evaluation  # noqa: E402
from joebot.backtest.engine import run_walk_forward  # noqa: E402
from joebot.screener.sector_screens import DEFAULT_SIGNALS  # noqa: E402
from joebot.storage.db import get_session  # noqa: E402
from joebot.storage.models import BacktestRun, SignalAttributionRecord  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_backtest")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=float, default=3.0, help="How many years of history to walk forward over.")
    parser.add_argument("--step-days", type=int, default=30, help="Spacing between as_of_dates.")
    parser.add_argument("--end-date", type=str, default=None, help="ISO date; defaults to today.")
    args = parser.parse_args()

    end_date = dt.date.fromisoformat(args.end_date) if args.end_date else dt.date.today()
    start_date = end_date - dt.timedelta(days=int(args.years * 365))

    log.info("Running walk-forward backtest %s -> %s (step=%dd)", start_date, end_date, args.step_days)
    result = run_walk_forward(DEFAULT_SIGNALS, start_date, end_date, step_days=args.step_days)
    log.info("Collected %d records; calibration cutoff at %s", len(result.records), result.calibration_cutoff)

    evaluation_fold = result.evaluation_fold()
    attributions = []
    for horizon in ("short", "long"):
        attributions.extend(signal_evaluation.evaluate(evaluation_fold, horizon=horizon))

    _print_report(attributions)
    _persist(start_date, end_date, args.step_days, result, attributions)


def _print_report(attributions: list[signal_evaluation.SignalAttribution]) -> None:
    print("\n=== Evaluation-fold signal attribution (out-of-sample only) ===")
    print(f"{'signal':<20}{'horizon':<8}{'n_obs':<8}{'n_dates':<9}{'top_mean':<12}{'bottom_mean':<14}{'spread':<12}{'baseline':<12}")
    for a in attributions:
        fmt = lambda v: f"{v:.4f}" if v is not None else "n/a"
        print(
            f"{a.signal_name:<20}{a.horizon:<8}{a.n_observations:<8}{a.n_dates:<9}"
            f"{fmt(a.top_half_mean_return):<12}{fmt(a.bottom_half_mean_return):<14}"
            f"{fmt(a.spread):<12}{fmt(a.baseline_mean_return):<12}"
        )
    print(
        "\nspread = mean forward return of above-median-score names minus "
        "below-median-score names on the same as_of_date. Positive spread "
        "with a meaningful n_observations is evidence the signal is doing "
        "something; a low n_observations means 'not enough evidence yet,' "
        "not 'it doesn't work' -- see joebot/backtest/signal_evaluation.py.\n"
    )


def _persist(start_date, end_date, step_days, result, attributions) -> None:
    session = get_session()
    try:
        run = BacktestRun(
            run_at=dt.datetime.utcnow(),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            step_days=step_days,
            calibration_cutoff=result.calibration_cutoff.isoformat(),
            n_records=len(result.records),
        )
        session.add(run)
        session.flush()

        for a in attributions:
            session.add(SignalAttributionRecord(
                backtest_run_id=run.id,
                signal_name=a.signal_name,
                horizon=a.horizon,
                n_observations=a.n_observations,
                n_dates=a.n_dates,
                top_half_mean_return=a.top_half_mean_return,
                bottom_half_mean_return=a.bottom_half_mean_return,
                spread=a.spread,
                baseline_mean_return=a.baseline_mean_return,
            ))

        session.commit()
        log.info("Backtest run #%d persisted", run.id)
    finally:
        session.close()


if __name__ == "__main__":
    main()
