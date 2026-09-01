"""Per-signal-family predictive-power attribution.

Must only be run on BacktestResult.evaluation_fold(), never the calibration
fold -- that's this project's walk-forward, out-of-sample discipline. If
you're using this to choose or adjust DEFAULT_SIGNAL_WEIGHTS, the numbers
justifying that change must come from here, from an evaluation fold.

Method: for each signal, on each as_of_date, split that date's scored
tickers into above-median-score ("top") and below-median-score ("bottom"),
then compare mean forward return between the two buckets across all dates.
Splitting per-date (rather than pooling scores across the whole fold) keeps
the comparison from being confounded by market-wide moves that happened to
coincide with a particular date -- a signal that fires more during a rally
shouldn't get credit for the rally itself. This is a deliberately simple,
low-N-friendly method: it doesn't assume a return distribution and isn't
thrown off by a handful of extreme outliers the way a raw correlation
coefficient would be.

Small-sample caveat, stated explicitly: catalyst-signal events
(activist_stake, leadership_change) will be rare in a small tracked
universe, so n_observations for those will likely stay too low to draw a
confident conclusion for a long time. A low n is "not yet enough evidence,"
not "the signal doesn't work" -- always look at n_observations alongside
the spread, never the spread alone.
"""
from __future__ import annotations

import dataclasses

import pandas as pd


@dataclasses.dataclass
class SignalAttribution:
    signal_name: str
    horizon: str  # "short" or "long"
    n_observations: int
    n_dates: int
    top_half_mean_return: float | None
    bottom_half_mean_return: float | None
    spread: float | None  # top - bottom; positive means higher score -> higher forward return
    baseline_mean_return: float | None  # equal-weighted mean across the whole evaluation-fold universe


def _median_split(group: pd.DataFrame) -> pd.DataFrame:
    median = group["score"].median()
    group = group.copy()
    group["bucket"] = group["score"].apply(lambda s: "top" if s >= median else "bottom")
    return group


def evaluate(evaluation_fold: pd.DataFrame, horizon: str = "short") -> list[SignalAttribution]:
    return_col = f"forward_return_{horizon}"
    if evaluation_fold.empty:
        return []

    baseline = evaluation_fold.dropna(subset=[return_col])
    baseline_mean = float(baseline[return_col].mean()) if not baseline.empty else None

    results = []
    for signal_name, group in evaluation_fold.groupby("signal_name"):
        group = group.dropna(subset=[return_col])
        if group.empty:
            results.append(SignalAttribution(signal_name, horizon, 0, 0, None, None, None, baseline_mean))
            continue

        split = group.groupby("as_of_date", group_keys=False).apply(_median_split)
        top = split[split["bucket"] == "top"]
        bottom = split[split["bucket"] == "bottom"]

        top_mean = float(top[return_col].mean()) if not top.empty else None
        bottom_mean = float(bottom[return_col].mean()) if not bottom.empty else None
        spread = (top_mean - bottom_mean) if (top_mean is not None and bottom_mean is not None) else None

        results.append(SignalAttribution(
            signal_name=signal_name,
            horizon=horizon,
            n_observations=len(group),
            n_dates=int(group["as_of_date"].nunique()),
            top_half_mean_return=top_mean,
            bottom_half_mean_return=bottom_mean,
            spread=spread,
            baseline_mean_return=baseline_mean,
        ))

    return results
