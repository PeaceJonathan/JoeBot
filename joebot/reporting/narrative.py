"""Turns a RankedCandidate's raw per-signal scores/metadata into a human-
readable "why did this appear" narrative, instead of a bare composite
number. The signal design already produces exactly the raw material this
needs -- every SignalResult carries a metadata dict of the specific facts
that drove its score -- this module just renders that into English.

Deliberately conservative about what it claims: a bullet only appears when
the underlying signal actually fired with real data (never fabricated).
There is currently no forward-looking catalyst calendar (PDUFA dates,
scheduled earnings, etc.) in this project, so "upcoming catalyst" claims
are NOT generated here -- only what already happened is described. Adding
a real forward-looking calendar would be a future, explicitly-labeled
addition, not something to fake from what's on hand.
"""
from __future__ import annotations

import dataclasses
from typing import Callable

from joebot.screener.composite import RankedCandidate
from joebot.signals.base import SignalResult

# Signals whose primary driver is a single binary/event-risk-heavy fact
# (an activist stake, a leadership shakeup, a clinical trial readout)
# rather than a steady trend -- used both for risk bullets here and for
# the risk slider's signal-type gating in joebot/screener/composite.py.
BINARY_CATALYST_SIGNALS = frozenset({"activist_stake", "leadership_change", "clinical_trial"})

# A signal must clear this score to be worth a "why it appeared" bullet at
# all -- a signal that fired weakly (or not at all) shouldn't clutter the
# narrative with a non-finding.
BULLET_SCORE_THRESHOLD = 0.15


@dataclasses.dataclass
class NarrativeCard:
    ticker: str
    sector: str
    composite_score: float
    verdict: str
    why_bullets: list[str]
    risk_bullets: list[str]


def _fmt_pct(x: float | None, decimals: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{decimals}f}%"


def _technical_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    parts = []
    pct_below = m.get("pct_below_52wk_high")
    if pct_below is not None and pct_below <= 0.15:
        parts.append(f"trading within {_fmt_pct(pct_below)} of its 52-week high")
    vol_surge = m.get("volume_surge_ratio")
    if vol_surge is not None and vol_surge >= 1.5:
        parts.append(f"volume running {vol_surge:.1f}x its 20-day average")
    if m.get("golden_cross"):
        parts.append("50-day average above its 200-day average (bullish trend regime)")
    if not parts:
        return None
    return "Technical: " + "; ".join(parts) + "."


def _fundamental_bullet(result: SignalResult) -> str | None:
    growth = result.metadata.get("revenue_growth_pct")
    if growth is None or growth <= 0.10:
        return None
    return f"Fundamental: revenue grew {_fmt_pct(growth)} year over year."


def _activist_stake_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    filings = m.get("filings") or []
    if not filings:
        return None
    form = m.get("most_recent_form", "a Schedule 13D/13G")
    days_ago = m.get("days_since_filing")
    filer = filings[0].get("filer_name") if filings else None
    filer_part = f" by {filer}" if filer else ""
    when = f"{days_ago} days ago" if days_ago is not None else "recently"
    return f"Ownership: a new {form} was filed{filer_part} {when} -- someone is taking a meaningful stake."


def _leadership_change_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    if not m.get("filings"):
        return None
    days_ago = m.get("days_since_filing")
    when = f"{days_ago} days ago" if days_ago is not None else "recently"
    return f"Leadership: an 8-K disclosing an officer/director change was filed {when}."


def _sentiment_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    velocity = m.get("velocity_ratio")
    count = m.get("mention_count", 0)
    if not count or velocity is None or velocity < 1.5:
        return None
    return f"Sentiment: mentions across tracked communities are running {velocity:.1f}x their prior rate ({count} in the window)."


def _clinical_trial_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    if not m.get("nct_id"):
        return None
    phase = m.get("phase", "a late-phase")
    status = m.get("status", "an active")
    days_ago = m.get("days_since_update")
    when = f"{days_ago} days ago" if days_ago is not None else "recently"
    return f"Clinical: {phase} trial ({status}) was updated {when} ({m.get('nct_id')})."


def _gov_contract_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    awards = m.get("awards") or []
    if not awards:
        return None
    top = awards[0]
    amount = top.get("amount")
    agency = top.get("agency")
    amount_str = f"${amount:,.0f}" if isinstance(amount, (int, float)) else "an undisclosed amount"
    agency_str = f" from {agency}" if agency else ""
    return f"Government: a new contract award{agency_str} worth {amount_str} was recorded."


def _patent_activity_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    recent = m.get("recent_count", 0)
    velocity = m.get("velocity_ratio")
    if not recent or velocity is None or velocity < 1.3:
        return None
    return f"IP: patent filings are running {velocity:.1f}x their prior rate ({recent} recent filings) -- worth checking what technology they cover."


_BULLET_FORMATTERS: dict[str, Callable[[SignalResult], str | None]] = {
    "technical_breakout": _technical_bullet,
    "fundamental_sanity": _fundamental_bullet,
    "activist_stake": _activist_stake_bullet,
    "leadership_change": _leadership_change_bullet,
    "sentiment_reddit": _sentiment_bullet,
    "clinical_trial": _clinical_trial_bullet,
    "gov_contract": _gov_contract_bullet,
    "patent_activity": _patent_activity_bullet,
}


def _verdict(composite_score: float) -> str:
    if composite_score >= 0.65:
        return "High conviction -- investigate further."
    if composite_score >= 0.40:
        return "Moderate interest -- worth a closer look."
    return "Weak signal -- likely noise at this point."


def _risk_bullets(candidate: RankedCandidate) -> list[str]:
    bullets = []
    tech = candidate.signal_results.get("technical_breakout")
    if tech:
        atr_pct = tech.metadata.get("atr_pct_of_price")
        if atr_pct is not None and atr_pct >= 0.08:
            bullets.append(f"High volatility -- ATR is {_fmt_pct(atr_pct)} of price.")
        avg_dv = tech.metadata.get("avg_dollar_volume")
        if avg_dv is not None and avg_dv < 1_000_000:
            bullets.append(f"Thin liquidity -- average dollar volume is only ${avg_dv:,.0f}/day.")
        market_cap = tech.metadata.get("market_cap")
        if market_cap is None:
            bullets.append("Market cap unavailable -- size/liquidity risk unknown.")

    low_confidence_signals = [
        name for name, r in candidate.signal_results.items() if r.confidence < 0.3 and r.score > 0
    ]
    if low_confidence_signals:
        bullets.append(
            f"Limited underlying data for: {', '.join(low_confidence_signals)} -- treat those contributions cautiously."
        )

    binary_driven = [
        name for name in BINARY_CATALYST_SIGNALS
        if candidate.signal_results.get(name) and candidate.signal_results[name].score >= BULLET_SCORE_THRESHOLD
    ]
    if binary_driven:
        bullets.append(
            f"Driven partly by event risk ({', '.join(binary_driven)}) -- a binary outcome, not a steady trend."
        )

    bullets.append(
        "Not yet validated by a real backtest run on this repo -- run scripts/run_backtest.py "
        "and check n_observations before weighting this heavily."
    )
    return bullets


def build_narrative(candidate: RankedCandidate) -> NarrativeCard:
    why_bullets = []
    for name, result in candidate.signal_results.items():
        if result.score < BULLET_SCORE_THRESHOLD:
            continue
        formatter = _BULLET_FORMATTERS.get(name)
        if formatter is None:
            continue
        bullet = formatter(result)
        if bullet:
            why_bullets.append(bullet)

    if not why_bullets:
        why_bullets.append("No individual signal cleared the reporting threshold -- composite score is a diffuse blend of weak evidence.")

    return NarrativeCard(
        ticker=candidate.ticker,
        sector=candidate.sector,
        composite_score=candidate.composite_score,
        verdict=_verdict(candidate.composite_score),
        why_bullets=why_bullets,
        risk_bullets=_risk_bullets(candidate),
    )
