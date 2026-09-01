"""Unit tests for joebot.risk.profile's slider interpolation."""
import pytest

from config.settings import RISK_PROFILE_BREAKPOINTS
from joebot.risk.profile import get_risk_profile

_conservative = dict(RISK_PROFILE_BREAKPOINTS)[0]
_moderate = dict(RISK_PROFILE_BREAKPOINTS)[50]
_aggressive = dict(RISK_PROFILE_BREAKPOINTS)[100]


def test_slider_at_breakpoint_returns_exact_profile():
    assert get_risk_profile(0) == _conservative
    assert get_risk_profile(50) == _moderate
    assert get_risk_profile(100) == _aggressive


def test_slider_clamps_out_of_range():
    assert get_risk_profile(-10) == _conservative
    assert get_risk_profile(150) == _aggressive


def test_slider_midpoint_interpolates_linearly():
    # Halfway between conservative (0) and moderate (50) breakpoints is slider=25.
    profile = get_risk_profile(25)
    expected_min_cap = (_conservative.min_market_cap + _moderate.min_market_cap) / 2
    assert profile.min_market_cap == pytest.approx(expected_min_cap)

    expected_risk_fraction = (_conservative.base_risk_fraction + _moderate.base_risk_fraction) / 2
    assert profile.base_risk_fraction == pytest.approx(expected_risk_fraction)


def test_slider_monotonic_min_market_cap_decreases_with_risk():
    caps = [get_risk_profile(v).min_market_cap for v in (0, 25, 50, 75, 100)]
    assert caps == sorted(caps, reverse=True)


def test_slider_monotonic_sizing_multiplier_increases_with_risk():
    multipliers = [get_risk_profile(v).sizing_aggressiveness_multiplier for v in (0, 25, 50, 75, 100)]
    assert multipliers == sorted(multipliers)
