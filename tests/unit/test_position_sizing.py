"""Unit tests for joebot.risk.position_sizing against hand-computed values."""
import pytest

from config.settings import RiskProfile
from joebot.risk.position_sizing import allocate_budget, suggest_position

PROFILE = RiskProfile(
    name="test",
    min_market_cap=0,
    max_atr_pct_of_price=1.0,
    min_avg_dollar_volume=0,
    base_risk_fraction=0.01,   # risk 1% of budget per trade
    sizing_aggressiveness_multiplier=1.0,
    max_position_fraction=0.25,  # never more than 25% of budget in one name
)


def test_suggest_position_hand_computed():
    # budget=10000, risk_fraction=0.01 -> risk_dollars=100
    # atr=2.0, stop_multiplier=2.0 -> stop_distance=4.0
    # shares_by_risk = 100/4 = 25
    # max_dollars = 10000*0.25 = 2500; price=20 -> shares_by_cap=125
    # binding constraint is risk (25 shares)
    result = suggest_position("TEST", price=20.0, atr=2.0, budget=10000, risk_profile=PROFILE)
    assert result.shares == 25
    assert result.dollar_amount == pytest.approx(500.0)
    assert result.stop_distance == pytest.approx(4.0)
    assert result.stop_price == pytest.approx(16.0)


def test_suggest_position_capped_by_max_position_fraction():
    # Very tight ATR (small stop distance) would suggest a huge share count
    # by risk alone; max_position_fraction must cap it.
    # budget=10000, risk_dollars=100, atr=0.01 -> stop_distance=0.02 -> shares_by_risk=5000
    # max_dollars=2500, price=20 -> shares_by_cap=125 (binding)
    result = suggest_position("TEST", price=20.0, atr=0.01, budget=10000, risk_profile=PROFILE)
    assert result.shares == 125
    assert result.dollar_amount == pytest.approx(2500.0)


def test_suggest_position_none_for_missing_data():
    assert suggest_position("TEST", price=None, atr=1.0, budget=1000, risk_profile=PROFILE) is None
    assert suggest_position("TEST", price=10.0, atr=None, budget=1000, risk_profile=PROFILE) is None
    assert suggest_position("TEST", price=0.0, atr=1.0, budget=1000, risk_profile=PROFILE) is None
    assert suggest_position("TEST", price=10.0, atr=1.0, budget=0, risk_profile=PROFILE) is None


def test_allocate_budget_stops_at_budget_not_padding_weak_picks():
    # A tight ATR (0.01) makes max_position_fraction the binding constraint
    # for every candidate: ideal size = 0.25 * budget = $312.50 -> 15 shares
    # @ $20 = $300 each (shares_by_risk would be ~600, far larger, so the
    # cap always wins here -- see test_suggest_position_capped_by_max_position_fraction).
    candidates = [(name, 20.0, 0.01) for name in ("A", "B", "C", "D", "E")]
    suggestions = allocate_budget(candidates, budget=1250, risk_profile=PROFILE)

    total_spent = sum(s.dollar_amount for s in suggestions)
    assert total_spent <= 1250

    # First 4 fill fully at their $300 ideal size (15 shares each) = $1200.
    for s in suggestions[:4]:
        assert s.shares == 15
        assert s.dollar_amount == pytest.approx(300.0)

    # $50 remains for E's $300 ideal -> scaled down to fit (2 shares @ $20),
    # not dropped outright.
    assert suggestions[4].ticker == "E"
    assert suggestions[4].shares == 2
    assert suggestions[4].dollar_amount == pytest.approx(40.0)


def test_allocate_budget_skips_when_price_missing():
    candidates = [("A", None, 2.0), ("B", 20.0, 2.0)]
    suggestions = allocate_budget(candidates, budget=1000, risk_profile=PROFILE)
    assert len(suggestions) == 1
    assert suggestions[0].ticker == "B"


def test_allocate_budget_empty_candidates():
    assert allocate_budget([], budget=1000, risk_profile=PROFILE) == []
