"""Maps the risk slider (0 = conservative .. 100 = aggressive) to a concrete
RiskProfile, linearly interpolating between the named breakpoints in
config/settings.py::RISK_PROFILE_BREAKPOINTS.

One slider, two effects, per the plan: joebot/screener/composite.py uses
this profile's market-cap/liquidity/volatility thresholds to filter which
candidates even appear; joebot/risk/position_sizing.py uses its
risk-fraction/sizing-multiplier fields to size the ones that do.
"""
from __future__ import annotations

from config.settings import RISK_PROFILE_BREAKPOINTS, RiskProfile

_NUMERIC_FIELDS = (
    "min_market_cap",
    "max_atr_pct_of_price",
    "min_avg_dollar_volume",
    "base_risk_fraction",
    "sizing_aggressiveness_multiplier",
    "max_position_fraction",
    "binary_catalyst_tolerance",
)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def get_risk_profile(slider_value: float) -> RiskProfile:
    slider_value = max(0.0, min(100.0, slider_value))
    breakpoints = sorted(RISK_PROFILE_BREAKPOINTS, key=lambda bp: bp[0])

    if slider_value <= breakpoints[0][0]:
        return breakpoints[0][1]
    if slider_value >= breakpoints[-1][0]:
        return breakpoints[-1][1]
    for val, profile in breakpoints:
        if slider_value == val:
            return profile

    for (lo_val, lo_profile), (hi_val, hi_profile) in zip(breakpoints, breakpoints[1:]):
        if lo_val <= slider_value <= hi_val:
            t = (slider_value - lo_val) / (hi_val - lo_val) if hi_val != lo_val else 0.0
            kwargs = {
                field: _lerp(getattr(lo_profile, field), getattr(hi_profile, field), t)
                for field in _NUMERIC_FIELDS
            }
            return RiskProfile(name=f"{lo_profile.name}-{hi_profile.name} blend ({slider_value:.0f})", **kwargs)

    raise AssertionError("unreachable -- slider_value is bounds-checked above")
