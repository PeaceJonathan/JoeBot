"""Unit tests for joebot.screener.composite's risk-filter predicate."""
from config.settings import RiskProfile
from joebot.screener.composite import RankedCandidate, apply_risk_filter, passes_risk_filter
from joebot.signals.base import SignalResult

PROFILE = RiskProfile(
    name="test",
    min_market_cap=100_000_000,
    max_atr_pct_of_price=0.08,
    min_avg_dollar_volume=1_000_000,
    base_risk_fraction=0.01,
    sizing_aggressiveness_multiplier=1.0,
    max_position_fraction=0.25,
)


def test_passes_when_all_within_thresholds():
    assert passes_risk_filter(atr_pct_of_price=0.05, avg_dollar_volume=2_000_000, market_cap=200_000_000, risk_profile=PROFILE)


def test_fails_on_excessive_volatility():
    assert not passes_risk_filter(atr_pct_of_price=0.15, avg_dollar_volume=2_000_000, market_cap=200_000_000, risk_profile=PROFILE)


def test_fails_on_insufficient_liquidity():
    assert not passes_risk_filter(atr_pct_of_price=0.05, avg_dollar_volume=500_000, market_cap=200_000_000, risk_profile=PROFILE)


def test_fails_on_too_small_market_cap():
    assert not passes_risk_filter(atr_pct_of_price=0.05, avg_dollar_volume=2_000_000, market_cap=50_000_000, risk_profile=PROFILE)


def test_missing_data_never_excludes():
    # "unknown, not bad news" -- a None on any field must not fail the filter.
    assert passes_risk_filter(atr_pct_of_price=None, avg_dollar_volume=None, market_cap=None, risk_profile=PROFILE)
    assert passes_risk_filter(atr_pct_of_price=0.05, avg_dollar_volume=None, market_cap=None, risk_profile=PROFILE)


def _candidate(ticker, atr_pct, avg_dv, market_cap):
    return RankedCandidate(
        ticker=ticker, sector="tech", composite_score=0.5,
        signal_results={
            "technical_breakout": SignalResult(
                score=0.5, confidence=1.0,
                metadata={"atr_pct_of_price": atr_pct, "avg_dollar_volume": avg_dv, "market_cap": market_cap},
            )
        },
    )


def test_apply_risk_filter_on_candidate_list():
    candidates = [
        _candidate("GOOD", 0.05, 2_000_000, 200_000_000),
        _candidate("TOO_VOLATILE", 0.20, 2_000_000, 200_000_000),
        _candidate("TOO_SMALL", 0.05, 2_000_000, 10_000_000),
    ]
    filtered = apply_risk_filter(candidates, PROFILE)
    assert [c.ticker for c in filtered] == ["GOOD"]


def test_apply_risk_filter_candidate_missing_technical_signal_passes():
    candidate = RankedCandidate(ticker="NOTECH", sector="tech", composite_score=0.5, signal_results={})
    filtered = apply_risk_filter([candidate], PROFILE)
    assert [c.ticker for c in filtered] == ["NOTECH"]
