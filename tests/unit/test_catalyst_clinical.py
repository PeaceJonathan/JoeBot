"""Unit tests for joebot.signals.catalyst_clinical scoring logic, against
fixture trial data injected via monkeypatch -- no network access."""
import datetime as dt

import pytest

from joebot.data import clinicaltrials_client
from joebot.signals import catalyst_clinical
from joebot.signals.catalyst_clinical import ClinicalTrialSignal

AS_OF = dt.date(2026, 6, 1)


def _trial(days_ago, phase="PHASE3", status="RECRUITING"):
    return clinicaltrials_client.TrialSnapshot(
        nct_id="NCT0000001", phase=phase, status=status,
        last_update_date=AS_OF - dt.timedelta(days=days_ago),
    )


def test_missing_crosswalk_entry_scores_zero_zero_confidence(monkeypatch):
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {})
    result = ClinicalTrialSignal().score("UNKNOWNTICKER", AS_OF)
    assert result.score == 0.0
    assert result.confidence == 0.0


def test_recent_late_phase_active_trial_scores_high(monkeypatch):
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {"TEST": "Test Sponsor Inc."})
    monkeypatch.setattr(
        clinicaltrials_client, "fetch_trials_for_sponsor",
        lambda sponsor: [_trial(days_ago=2, phase="PHASE3", status="RECRUITING")],
    )
    result = ClinicalTrialSignal(lookback_days=120).score("TEST", AS_OF)
    assert result.score > 0.9
    assert result.metadata["sponsor"] == "Test Sponsor Inc."


def test_early_phase_trial_is_ignored(monkeypatch):
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {"TEST": "Test Sponsor Inc."})
    monkeypatch.setattr(
        clinicaltrials_client, "fetch_trials_for_sponsor",
        lambda sponsor: [_trial(days_ago=2, phase="PHASE1", status="RECRUITING")],
    )
    result = ClinicalTrialSignal(lookback_days=120).score("TEST", AS_OF)
    assert result.score == 0.0


def test_stale_trial_outside_lookback_scores_zero(monkeypatch):
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {"TEST": "Test Sponsor Inc."})
    monkeypatch.setattr(
        clinicaltrials_client, "fetch_trials_for_sponsor",
        lambda sponsor: [_trial(days_ago=500, phase="PHASE3", status="RECRUITING")],
    )
    result = ClinicalTrialSignal(lookback_days=120).score("TEST", AS_OF)
    assert result.score == 0.0


def test_recency_scores_higher_than_stale_within_window(monkeypatch):
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {"TEST": "Test Sponsor Inc."})

    monkeypatch.setattr(clinicaltrials_client, "fetch_trials_for_sponsor", lambda sponsor: [_trial(days_ago=1)])
    fresh = ClinicalTrialSignal(lookback_days=120).score("TEST", AS_OF)

    monkeypatch.setattr(clinicaltrials_client, "fetch_trials_for_sponsor", lambda sponsor: [_trial(days_ago=110)])
    stale = ClinicalTrialSignal(lookback_days=120).score("TEST", AS_OF)

    assert fresh.score > stale.score
