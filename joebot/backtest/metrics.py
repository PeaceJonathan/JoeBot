"""Standard performance metrics for a return series (one value per period,
e.g. one walk-forward window's realized return for a simulated top-N
portfolio). Kept separate from signal_evaluation.py's per-signal
attribution, which operates on individual ticker-level forward returns
rather than a portfolio-level series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(returns: pd.Series, periods_per_year: float) -> float | None:
    returns = returns.dropna()
    if returns.empty:
        return None
    growth = float((1 + returns).prod())
    n_years = len(returns) / periods_per_year
    if n_years <= 0 or growth <= 0:
        return None
    return growth ** (1 / n_years) - 1


def sharpe_ratio(returns: pd.Series, periods_per_year: float, risk_free_rate: float = 0.0) -> float | None:
    returns = returns.dropna()
    if returns.empty:
        return None
    std = returns.std(ddof=0)
    if np.isclose(std, 0.0, atol=1e-12):
        return None
    excess = returns - risk_free_rate / periods_per_year
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float | None:
    returns = returns.dropna()
    if returns.empty:
        return None
    wealth = (1 + returns).cumprod()
    peak = wealth.cummax()
    drawdown = (wealth - peak) / peak
    return float(drawdown.min())


def hit_rate(returns: pd.Series) -> float | None:
    returns = returns.dropna()
    if returns.empty:
        return None
    return float((returns > 0).mean())
