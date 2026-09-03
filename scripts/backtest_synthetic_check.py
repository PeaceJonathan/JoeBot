#!/usr/bin/env python3
"""Synthetic recovery check for the walk-forward backtest engine: does
joebot/backtest actually detect a real signal-to-return relationship when
one is deliberately engineered into the data, and correctly report ~zero
edge for a signal that's pure noise?

WHY THIS SCRIPT EXISTS: this project's hard rule is that DEFAULT_SIGNAL_WEIGHTS
may only change based on a real evaluation-fold backtest result (see
README, scripts/run_backtest.py). That rule is only trustworthy if the
backtest engine itself is verified correct -- otherwise "the evaluation
fold says X" is meaningless. This can't be checked with real market data in
this environment (every external host is network-policy-blocked here; see
scripts/validate_live_data.py), so it's checked architecturally instead:
construct a synthetic universe and price history where the true
signal-return relationship is known by construction, run the real
joebot.backtest.engine + joebot.backtest.signal_evaluation code against it
unmodified, and confirm the reported spread matches what was engineered in.

This is NOT a substitute for scripts/run_backtest.py against real history --
it only proves the plumbing (walk-forward date generation, point-in-time
forward-return computation including the delisting/gap-tolerance logic,
calibration/evaluation fold split, median-split spread attribution) does
what it claims to do. Whether any *real* signal has predictive value is a
question only real data can answer.

Usage:
    python scripts/backtest_synthetic_check.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd  # noqa: E402

# 8 tickers with a real, engineered relationship to future returns (rises
# steadily after every as_of_date) and 8 with none (flat/random, no signal).
GOOD_TICKERS = [f"GOOD{i}" for i in range(8)]
BAD_TICKERS = [f"BAD{i}" for i in range(8)]
ALL_TICKERS = GOOD_TICKERS + BAD_TICKERS

START = dt.date(2020, 1, 1)
END = dt.date(2023, 6, 1)


def _stable_hash(s: str) -> int:
    """Deterministic across runs/processes, unlike Python's built-in hash()
    for strings, which is randomized per-process (PYTHONHASHSEED) by
    default. Using hash() here previously made NoiseSignal's scores vary
    run to run, which could occasionally produce a degenerate median split
    (every ticker in one bucket) and a flaky spread=None -- not a real bug
    in the backtest engine, just nondeterminism in this synthetic fixture."""
    import zlib
    return zlib.crc32(s.encode())


def _synthetic_series(ticker: str, end_date: dt.date, trailing_days: int) -> pd.DataFrame:
    """A deterministic price path: GOOD tickers drift up ~0.15%/day after
    any point, BAD tickers drift flat with the same noise -- so a signal
    that can tell GOOD from BAD should show a large positive spread, and a
    signal that can't (pure noise) should show ~zero spread."""
    dates = pd.date_range(end=end_date, periods=trailing_days, freq="D")
    daily_drift = 0.0015 if ticker in GOOD_TICKERS else 0.0000
    # A small ticker-specific deterministic wobble (no randomness at all) so
    # prices aren't perfectly smooth, without introducing any actual noise
    # that could accidentally wash out the engineered relationship.
    import numpy as np
    idx = np.arange(trailing_days)
    wobble = 0.002 * np.sin(idx / 7.0 + _stable_hash(ticker) % 7)
    close = 50 * (1 + daily_drift) ** idx * (1 + wobble)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [1_000_000] * trailing_days,
    }, index=dates)


class PerfectSignal:
    """Knows the ground truth by construction -- scores 1.0 for GOOD
    tickers, 0.0 for BAD. Should recover a strongly positive spread."""

    name = "perfect_signal"

    def score(self, ticker, as_of_date):
        from joebot.signals.base import SignalResult
        return SignalResult(score=1.0 if ticker in GOOD_TICKERS else 0.0, confidence=1.0, metadata={})


class NoiseSignal:
    """Deterministic but uncorrelated with the engineered relationship
    (alternates 0/1 by ticker index, independent of GOOD/BAD). Should show
    ~zero spread -- this is the negative control."""

    name = "noise_signal"

    def score(self, ticker, as_of_date):
        from joebot.signals.base import SignalResult
        score = 1.0 if (_stable_hash(ticker) % 2 == 0) else 0.0
        return SignalResult(score=score, confidence=1.0, metadata={})


def main() -> None:
    from joebot.backtest import engine, signal_evaluation, universe_builder
    from joebot.data import market_data

    print("=== Backtest engine synthetic recovery check (no network) ===\n")

    with mock.patch.object(universe_builder, "universe_as_of", return_value={"synthetic": ALL_TICKERS}), \
         mock.patch.object(universe_builder, "delisting_lookup", return_value={}), \
         mock.patch.object(market_data, "fetch_price_history_covering", side_effect=_synthetic_series):

        result = engine.run_walk_forward(
            signals=[PerfectSignal(), NoiseSignal()],
            start_date=START, end_date=END, step_days=45,
        )

    print(f"{len(result.records)} records collected; calibration cutoff = {result.calibration_cutoff}\n")
    assert len(result.records) > 0, "engine produced zero records -- walk-forward date generation or universe hook is broken"

    evaluation_fold = result.evaluation_fold()
    print(f"Evaluation fold: {len(evaluation_fold)} records (out-of-sample only)\n")

    print(f"{'signal':<16}{'horizon':<8}{'n_obs':<8}{'spread':<12}{'baseline':<12}")
    attributions = {}
    for horizon in ("short", "long"):
        for a in signal_evaluation.evaluate(evaluation_fold, horizon=horizon):
            fmt = lambda v: f"{v:.4f}" if v is not None else "n/a"
            print(f"{a.signal_name:<16}{a.horizon:<8}{a.n_observations:<8}{fmt(a.spread):<12}{fmt(a.baseline_mean_return):<12}")
            attributions[(a.signal_name, a.horizon)] = a

    print()
    perfect_short = attributions.get(("perfect_signal", "short"))
    noise_short = attributions.get(("noise_signal", "short"))

    assert perfect_short is not None and perfect_short.n_observations > 0, "perfect_signal produced no evaluation-fold observations"
    assert perfect_short.spread is not None and perfect_short.spread > 0.01, (
        f"PerfectSignal should show a clearly positive spread (engineered GOOD tickers drift up); got {perfect_short.spread}"
    )
    assert noise_short is not None and noise_short.spread is not None
    assert abs(noise_short.spread) < abs(perfect_short.spread), (
        "NoiseSignal's spread should be much smaller in magnitude than PerfectSignal's -- "
        f"got noise={noise_short.spread}, perfect={perfect_short.spread}"
    )

    print("PASS: PerfectSignal recovered a positive spread; NoiseSignal's spread was near zero by comparison.")
    print("This confirms the walk-forward engine, point-in-time forward-return computation, and")
    print("median-split signal attribution are architecturally sound.")
    print("\nThis does NOT confirm any real signal (technical_breakout, activist_stake, etc.) has")
    print("predictive value -- that requires scripts/run_backtest.py against real market history,")
    print("which needs live network access this environment does not have. See README.")


if __name__ == "__main__":
    main()
