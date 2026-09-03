"""Central configuration for JoeBot, loaded from environment variables and defaults.

JoeBot is a decision-support tool: it ranks candidates and suggests position
sizes for the user to enter manually in their brokerage. It never places,
sizes-for-auto-execution, or connects to any brokerage order API.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "joebot.db"
SECTORS_FILE = CONFIG_DIR / "sectors.yaml"
DELISTED_UNIVERSE_FILE = DATA_DIR / "delisted_universe.csv"

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "JoeBot/0.1 (set SEC_USER_AGENT in .env)")
SEC_MAX_REQUESTS_PER_SECOND = 8  # stay comfortably under SEC's documented 10 req/sec cap

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "joebot/0.1")

# Technical screen defaults (Phase 1).
LOOKBACK_DAYS = 400  # enough history for a 52-week window plus moving averages
VOLUME_SURGE_WINDOW = 20
ATR_PERIOD = 14
RSI_PERIOD = 14
MA_FAST = 50
MA_SLOW = 200

# Composite screener weights. These are a starting guess only, per the plan's
# hard rule: they must be replaced by walk-forward out-of-sample results from
# joebot/backtest, never hand-tuned on the full history.
DEFAULT_SIGNAL_WEIGHTS = {
    "technical_breakout": 0.25,
    "fundamental_sanity": 0.18,
    "activist_stake": 0.17,
    "leadership_change": 0.09,
    "sentiment_reddit": 0.08,
    "clinical_trial": 0.09,
    "gov_contract": 0.09,
    "patent_activity": 0.05,  # deliberately the smallest weight -- weak evidence on its own, see joebot/signals/patent_activity.py
}

# How far back (in days) the catalyst signals look for a qualifying filing.
CATALYST_LOOKBACK_DAYS = 180


@dataclass(frozen=True)
class RiskProfile:
    """A point on the risk slider. See joebot/risk/profile.py for slider mapping."""

    name: str
    min_market_cap: float
    max_atr_pct_of_price: float
    min_avg_dollar_volume: float
    base_risk_fraction: float
    sizing_aggressiveness_multiplier: float
    max_position_fraction: float


# Named breakpoints the slider (0-100) interpolates between. Kept in config so
# they can be retuned without touching code as backtest evidence comes in.
RISK_PROFILE_BREAKPOINTS: list[tuple[int, RiskProfile]] = [
    (0, RiskProfile(
        name="conservative",
        min_market_cap=500_000_000,
        max_atr_pct_of_price=0.04,
        min_avg_dollar_volume=5_000_000,
        base_risk_fraction=0.005,
        sizing_aggressiveness_multiplier=0.5,
        max_position_fraction=0.15,
    )),
    (50, RiskProfile(
        name="moderate",
        min_market_cap=150_000_000,
        max_atr_pct_of_price=0.07,
        min_avg_dollar_volume=1_000_000,
        base_risk_fraction=0.01,
        sizing_aggressiveness_multiplier=1.0,
        max_position_fraction=0.25,
    )),
    (100, RiskProfile(
        name="aggressive",
        min_market_cap=50_000_000,
        max_atr_pct_of_price=0.12,
        min_avg_dollar_volume=250_000,
        base_risk_fraction=0.02,
        sizing_aggressiveness_multiplier=1.75,
        max_position_fraction=0.35,
    )),
]

# Defaults for scripts/run_daily.py's standalone position-sizing suggestion
# when the user hasn't opened the dashboard to set a real budget/slider.
DEFAULT_RISK_SLIDER = 50.0
DEFAULT_BUDGET = 10_000.0


def ensure_dirs() -> None:
    for d in (DATA_DIR, REPORTS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
