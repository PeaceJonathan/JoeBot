"""Unit tests for joebot.reporting.horizon.classify_horizon."""
from joebot.reporting.horizon import (
    LONG_TERM,
    MEDIUM_TERM,
    SHORT_TERM,
    classify_horizon,
)


def test_technical_breakout_dominant_is_short_term():
    result = classify_horizon({"technical_breakout": 0.8, "fundamental_sanity": 0.2})
    assert result.horizon == SHORT_TERM
    assert result.driven_by == "technical_breakout"


def test_gov_contract_dominant_is_long_term():
    result = classify_horizon({"gov_contract": 0.9, "technical_breakout": 0.3})
    assert result.horizon == LONG_TERM
    assert result.driven_by == "gov_contract"


def test_clinical_trial_dominant_is_medium_term():
    result = classify_horizon({"clinical_trial": 0.95})
    assert result.horizon == MEDIUM_TERM


def test_no_positive_signals_falls_back_to_default():
    result = classify_horizon({"technical_breakout": 0.0, "gov_contract": 0.0})
    assert result.horizon == MEDIUM_TERM
    assert result.driven_by is None


def test_empty_signal_scores_falls_back_to_default():
    result = classify_horizon({})
    assert result.driven_by is None


def test_unknown_signal_name_falls_back_to_default_horizon():
    result = classify_horizon({"some_future_signal": 0.9})
    assert result.horizon == MEDIUM_TERM
    assert result.driven_by == "some_future_signal"


def test_ties_pick_one_signal_deterministically_via_max():
    # max() on a dict with tied values picks the first key encountered in
    # iteration order -- just confirming this doesn't raise or pick None.
    result = classify_horizon({"technical_breakout": 0.5, "gov_contract": 0.5})
    assert result.driven_by in ("technical_breakout", "gov_contract")
    assert result.horizon in (SHORT_TERM, LONG_TERM)


def test_display_labels_cover_every_horizon():
    from joebot.reporting.horizon import DISPLAY_LABELS
    assert set(DISPLAY_LABELS) == {SHORT_TERM, MEDIUM_TERM, LONG_TERM}
    for label in DISPLAY_LABELS.values():
        assert label  # non-empty
