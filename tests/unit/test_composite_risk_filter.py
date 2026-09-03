"""Unit tests for joebot.screener.composite's risk-filter predicate."""
import dataclasses

from config.settings import RiskProfile
from joebot.screener.composite import RankedCandidate, apply_risk_filter, is_binary_catalyst_led, passes_risk_filter
from joebot.signals.base import SignalResult

PROFILE = RiskProfile(
    name="test",
    min_market_cap=100_000_000,
    max_atr_pct_of_price=0.08,
    min_avg_dollar_volume=1_000_000,
    base_risk_fraction=0.01,
    sizing_aggressiveness_multiplier=1.0,
    max_position_fraction=0.25,
    binary_catalyst_tolerance=1.0,
)

INTOLERANT_PROFILE = dataclasses.replace(PROFILE, binary_catalyst_tolerance=0.0)


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


def test_is_binary_catalyst_led_true_when_top_signal_is_binary():
    assert is_binary_catalyst_led({"activist_stake": 0.9, "technical_breakout": 0.3})
    assert is_binary_catalyst_led({"clinical_trial": 0.7, "fundamental_sanity": 0.1})


def test_is_binary_catalyst_led_false_when_top_signal_is_steady():
    assert not is_binary_catalyst_led({"technical_breakout": 0.9, "activist_stake": 0.3})


def test_is_binary_catalyst_led_false_when_top_score_is_zero():
    assert not is_binary_catalyst_led({"activist_stake": 0.0, "technical_breakout": 0.0})


def test_is_binary_catalyst_led_false_for_empty_scores():
    assert not is_binary_catalyst_led({})


def test_passes_risk_filter_excludes_binary_led_when_intolerant():
    scores = {"activist_stake": 0.9, "technical_breakout": 0.2}
    assert not passes_risk_filter(0.05, 2_000_000, 200_000_000, INTOLERANT_PROFILE, signal_scores=scores)
    # Same candidate is fine under a tolerant profile.
    assert passes_risk_filter(0.05, 2_000_000, 200_000_000, PROFILE, signal_scores=scores)


def test_passes_risk_filter_allows_steady_led_even_when_intolerant():
    scores = {"technical_breakout": 0.9, "activist_stake": 0.2}
    assert passes_risk_filter(0.05, 2_000_000, 200_000_000, INTOLERANT_PROFILE, signal_scores=scores)


def test_apply_risk_filter_excludes_turnaround_at_conservative_profile():
    turnaround = RankedCandidate(
        ticker="TURNAROUND", sector="faded_giants", composite_score=0.6,
        signal_results={
            "technical_breakout": SignalResult(0.2, 1.0, {"atr_pct_of_price": 0.05, "avg_dollar_volume": 2_000_000, "market_cap": 200_000_000}),
            "activist_stake": SignalResult(0.9, 0.8, {}),
        },
    )
    assert apply_risk_filter([turnaround], PROFILE) == [turnaround]
    assert apply_risk_filter([turnaround], INTOLERANT_PROFILE) == []
