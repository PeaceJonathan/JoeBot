"""Unit tests for joebot.reporting.narrative against fixture signal data."""
from joebot.data import health
from joebot.reporting.narrative import BULLET_SCORE_THRESHOLD, build_narrative
from joebot.screener.composite import RankedCandidate
from joebot.signals.base import SignalResult


def _candidate(composite_score, signal_results):
    return RankedCandidate(ticker="TEST", sector="tech", composite_score=composite_score, signal_results=signal_results)


def test_technical_bullet_fires_near_52wk_high_with_volume_surge():
    candidate = _candidate(0.6, {
        "technical_breakout": SignalResult(
            score=0.6, confidence=1.0,
            metadata={"pct_below_52wk_high": 0.05, "volume_surge_ratio": 2.0, "golden_cross": True,
                      "atr_pct_of_price": 0.03, "avg_dollar_volume": 5_000_000, "market_cap": 1_000_000_000},
        )
    })
    card = build_narrative(candidate)
    assert any("52-week high" in b for b in card.why_bullets)
    assert any("volume" in b for b in card.why_bullets)


def test_technical_bullet_absent_when_far_from_high_and_no_surge():
    candidate = _candidate(0.1, {
        "technical_breakout": SignalResult(
            score=0.05, confidence=1.0,
            metadata={"pct_below_52wk_high": 0.40, "volume_surge_ratio": 0.8, "golden_cross": False},
        )
    })
    card = build_narrative(candidate)
    # score below BULLET_SCORE_THRESHOLD -- shouldn't even attempt the signal
    assert not any("52-week" in b or "volume" in b for b in card.why_bullets)


def test_activist_stake_bullet_includes_filer_and_recency():
    candidate = _candidate(0.7, {
        "activist_stake": SignalResult(
            score=0.9, confidence=0.8,
            metadata={
                "filings": [{"filer_name": "Ryan Cohen", "form": "SC 13D"}],
                "most_recent_form": "SC 13D",
                "days_since_filing": 3,
            },
        )
    })
    card = build_narrative(candidate)
    assert any("Ryan Cohen" in b and "3 days ago" in b for b in card.why_bullets)


def test_gov_contract_bullet_includes_amount_and_agency():
    candidate = _candidate(0.6, {
        "gov_contract": SignalResult(
            score=0.5, confidence=0.6,
            metadata={"awards": [{"amount": 140_000_000, "agency": "Department of Defense"}]},
        )
    })
    card = build_narrative(candidate)
    assert any("$140,000,000" in b and "Department of Defense" in b for b in card.why_bullets)


def test_patent_activity_bullet_requires_velocity():
    fires = _candidate(0.5, {
        "patent_activity": SignalResult(score=0.5, confidence=0.5, metadata={"recent_count": 17, "velocity_ratio": 3.0})
    })
    card = build_narrative(fires)
    assert any("patent filings" in b for b in card.why_bullets)

    quiet = _candidate(0.1, {
        "patent_activity": SignalResult(score=0.05, confidence=0.5, metadata={"recent_count": 2, "velocity_ratio": 1.0})
    })
    card2 = build_narrative(quiet)
    assert not any("patent" in b for b in card2.why_bullets)


def test_no_firing_signals_gives_placeholder_bullet():
    candidate = _candidate(0.1, {
        "technical_breakout": SignalResult(score=0.05, confidence=0.5, metadata={}),
    })
    card = build_narrative(candidate)
    assert len(card.why_bullets) == 1
    assert "No individual signal" in card.why_bullets[0]


def test_verdict_tiers():
    assert "High conviction" in build_narrative(_candidate(0.8, {})).verdict
    assert "Moderate interest" in build_narrative(_candidate(0.5, {})).verdict
    assert "Weak signal" in build_narrative(_candidate(0.1, {})).verdict


def test_risk_bullets_flag_high_volatility_and_thin_liquidity():
    candidate = _candidate(0.5, {
        "technical_breakout": SignalResult(
            score=0.5, confidence=1.0,
            metadata={"atr_pct_of_price": 0.15, "avg_dollar_volume": 200_000, "market_cap": 50_000_000},
        )
    })
    card = build_narrative(candidate)
    assert any("High volatility" in b for b in card.risk_bullets)
    assert any("Thin liquidity" in b for b in card.risk_bullets)


def test_risk_bullets_flag_binary_catalyst_dependence():
    candidate = _candidate(0.6, {
        "clinical_trial": SignalResult(score=0.7, confidence=0.6, metadata={"nct_id": "NCT123", "phase": "PHASE3", "status": "RECRUITING"}),
    })
    card = build_narrative(candidate)
    assert any("event risk" in b and "clinical_trial" in b for b in card.risk_bullets)


def test_risk_bullets_flag_low_confidence_contributing_signals():
    candidate = _candidate(0.4, {
        "sentiment_reddit": SignalResult(score=0.4, confidence=0.2, metadata={"mention_count": 5, "velocity_ratio": 2.0}),
    })
    card = build_narrative(candidate)
    assert any("Limited underlying data" in b and "sentiment_reddit" in b for b in card.risk_bullets)


def test_bullet_score_threshold_is_positive():
    assert BULLET_SCORE_THRESHOLD > 0


def test_bear_case_always_discloses_unchecked_factors():
    card = build_narrative(_candidate(0.5, {}))
    assert any("Not checked at all" in b and "short interest" in b for b in card.risk_bullets)


def test_data_gap_bullet_fires_when_source_unavailable():
    candidate = _candidate(0.3, {
        "clinical_trial": SignalResult(
            score=0.0, confidence=0.0,
            metadata={"data_source_status": {health.CLINICALTRIALS: health.UNAVAILABLE}},
        ),
    })
    card = build_narrative(candidate)
    assert any("ClinicalTrials.gov was unreachable" in b for b in card.data_gap_bullets)


def test_data_gap_bullet_fires_for_not_configured_zero_score_signal():
    candidate = _candidate(0.3, {
        "sentiment_reddit": SignalResult(
            score=0.0, confidence=0.3,
            metadata={"mention_count": 0, "data_source_status": {health.REDDIT: health.NOT_CONFIGURED}},
        ),
    })
    card = build_narrative(candidate)
    assert any("isn't configured" in b for b in card.data_gap_bullets)


def test_no_data_gap_bullets_when_all_sources_ok():
    candidate = _candidate(0.3, {
        "technical_breakout": SignalResult(score=0.3, confidence=1.0, metadata={"data_source_status": {health.MARKET_DATA: health.OK}}),
    })
    card = build_narrative(candidate)
    assert card.data_gap_bullets == []


def test_event_timeline_is_sorted_chronologically_across_signals():
    candidate = _candidate(0.7, {
        "activist_stake": SignalResult(
            score=0.9, confidence=0.8,
            metadata={"filings": [{"form": "SC 13D", "filer_name": "Ryan Cohen", "filing_date": "2026-04-02"}]},
        ),
        "leadership_change": SignalResult(
            score=0.5, confidence=0.8,
            metadata={"filings": [{"filing_date": "2026-01-12"}]},
        ),
        "gov_contract": SignalResult(
            score=0.6, confidence=0.6,
            metadata={"awards": [{"amount": 5_000_000, "agency": "DoD", "date": "2026-04-15"}]},
        ),
    })
    card = build_narrative(candidate)
    dates_in_order = [t.split(" -- ")[0] for t in card.timeline]
    assert dates_in_order == sorted(dates_in_order)
    assert any("Ryan Cohen" in t for t in card.timeline)
    assert any("officer/director change" in t for t in card.timeline)
    assert any("DoD" in t for t in card.timeline)


def test_event_timeline_empty_when_no_dated_events():
    card = build_narrative(_candidate(0.2, {"technical_breakout": SignalResult(score=0.2, confidence=1.0, metadata={})}))
    assert card.timeline == []
