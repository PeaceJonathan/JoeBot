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
import datetime as dt
from typing import Callable

from joebot.data import health
from joebot.screener.composite import RankedCandidate
from joebot.signals.base import BINARY_CATALYST_SIGNALS, SignalResult

# A signal must clear this score to be worth a "why it appeared" bullet at
# all -- a signal that fired weakly (or not at all) shouldn't clutter the
# narrative with a non-finding.
BULLET_SCORE_THRESHOLD = 0.15

# Bear-case factors this project has no data source for at all (as opposed
# to "checked this source and it's fine"). Section 11's bear-case list asks
# for these explicitly; rather than silently omitting them (which would
# read as "checked, no issue") or faking a number, every candidate's bear
# case says outright that these were never evaluated -- per the project's
# hardest rule: don't hide uncertainty, don't manufacture confidence.
UNCHECKED_BEAR_CASE_FACTORS = (
    "share dilution / share count trend",
    "customer concentration",
    "insider selling (only insider *buying* is tracked -- see insider_buying signal)",
    "short interest",
    "competitive positioning",
    "regulatory risk beyond what an 8-K/13D happens to disclose",
)


@dataclasses.dataclass
class NarrativeCard:
    ticker: str
    sector: str
    composite_score: float
    verdict: str
    why_bullets: list[str]
    risk_bullets: list[str]
    data_gap_bullets: list[str] = dataclasses.field(default_factory=list)
    timeline: list[str] = dataclasses.field(default_factory=list)


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


def _insider_buying_bullet(result: SignalResult) -> str | None:
    m = result.metadata
    purchases = m.get("purchases") or []
    if not purchases:
        return None
    distinct = m.get("distinct_insiders", 0)
    total_value = m.get("total_value")
    days_ago = m.get("days_since_purchase")
    when = f"{days_ago} days ago" if days_ago is not None else "recently"
    who = f"{distinct} distinct insider(s)" if distinct and distinct > 1 else "an insider"
    value_part = f" totaling ~${total_value:,.0f}" if isinstance(total_value, (int, float)) else ""
    return f"Insider buying: {who} made an open-market purchase{value_part}, most recently {when}."


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
    "insider_buying": _insider_buying_bullet,
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
    bullets.append(
        "Not checked at all (no data source in this project): " + "; ".join(UNCHECKED_BEAR_CASE_FACTORS) + "."
    )
    return bullets


def _data_gap_bullets(candidate: RankedCandidate) -> list[str]:
    """Surfaces every signal whose underlying source was UNAVAILABLE (a
    failed live call) or NOT_CONFIGURED (an optional source with no
    credentials) during this scan, so a 0.0 contribution to the composite
    score is never silently read as "checked, nothing there" -- see
    joebot/data/health.py and joebot/signals/base.py::with_source_status.
    """
    bullets = []
    seen: set[tuple[str, str]] = set()
    for signal_name, result in candidate.signal_results.items():
        statuses = result.metadata.get("data_source_status") or {}
        for source, status in statuses.items():
            if status == health.OK or (source, status) in seen:
                continue
            seen.add((source, status))
            display = health.DISPLAY_NAMES.get(source, source)
            if status == health.UNAVAILABLE:
                bullets.append(
                    f"{signal_name}: {display} was unreachable during this scan -- this signal's score "
                    "reflects incomplete data, not a confirmed absence of evidence."
                )
            elif status == health.NOT_CONFIGURED and result.score == 0.0:
                bullets.append(f"{signal_name}: {display} isn't configured (optional) -- this signal wasn't evaluated at all.")
    return bullets


def _event_timeline(candidate: RankedCandidate) -> list[str]:
    """Chronological list of dated events pulled from every signal's own
    metadata (filing dates, contract award dates, trial update dates,
    patent dates) -- a single score hides *when* things happened; this
    doesn't. Sorted oldest-first, per section 23's example format.
    """
    events: list[tuple[dt.date, str]] = []

    def _add(raw_date: str | None, description: str) -> None:
        if not raw_date:
            return
        try:
            events.append((dt.date.fromisoformat(raw_date[:10]), description))
        except ValueError:
            pass

    for signal_name in ("activist_stake", "leadership_change"):
        result = candidate.signal_results.get(signal_name)
        if not result:
            continue
        for f in result.metadata.get("filings", []):
            if signal_name == "activist_stake":
                filer = f.get("filer_name") or "an undisclosed filer"
                _add(f.get("filing_date"), f"{f.get('form', 'Ownership filing')} filed by {filer}")
            else:
                _add(f.get("filing_date"), "8-K disclosing an officer/director change")

    insider = candidate.signal_results.get("insider_buying")
    if insider:
        for p in insider.metadata.get("purchases", []):
            who = p.get("insider") or "an insider"
            value = p.get("value")
            value_part = f" (~${value:,.0f})" if isinstance(value, (int, float)) else ""
            _add(p.get("start_date"), f"Open-market insider purchase by {who}{value_part}")

    gov = candidate.signal_results.get("gov_contract")
    if gov:
        for a in gov.metadata.get("awards", []):
            amount = a.get("amount")
            amount_str = f"${amount:,.0f}" if isinstance(amount, (int, float)) else "undisclosed amount"
            agency = a.get("agency")
            _add(a.get("date"), f"Government contract award ({amount_str}{f', {agency}' if agency else ''})")

    clinical = candidate.signal_results.get("clinical_trial")
    if clinical and clinical.metadata.get("nct_id"):
        m = clinical.metadata
        _add(m.get("last_update_date"), f"Clinical trial {m.get('nct_id')} ({m.get('phase')}) updated -- status: {m.get('status')}")

    patents = candidate.signal_results.get("patent_activity")
    if patents:
        for p in patents.metadata.get("recent_patents", []):
            title = p.get("title") or "patent filing"
            _add(p.get("date"), f"Patent filed: {title}")

    events.sort(key=lambda e: e[0])
    return [f"{d.isoformat()} -- {desc}" for d, desc in events]


def build_event_feed(candidates: list[RankedCandidate], lookback_days: int = 30) -> list[tuple[str, str, str]]:
    """Cross-candidate feed of recent dated events (ticker, date, description),
    most-recent-first, for the dashboard's Catalysts page (section 22/23).

    Deliberately events that ALREADY happened, not a forward-looking
    calendar (PDUFA dates, scheduled earnings) -- this project has no data
    source for genuinely upcoming events, and section 28/29's rule against
    fabricating data applies here too. See this module's docstring.
    """
    feed: list[tuple[dt.date, str, str]] = []
    for candidate in candidates:
        cutoff = (candidate.as_of_date or dt.date.today()) - dt.timedelta(days=lookback_days)
        for entry in _event_timeline(candidate):
            date_str, _, desc = entry.partition(" -- ")
            try:
                d = dt.date.fromisoformat(date_str)
            except ValueError:
                continue
            if d >= cutoff:
                feed.append((d, candidate.ticker, desc))

    feed.sort(key=lambda e: e[0], reverse=True)
    return [(d.isoformat(), ticker, desc) for d, ticker, desc in feed]


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
        data_gap_bullets=_data_gap_bullets(candidate),
        timeline=_event_timeline(candidate),
    )
