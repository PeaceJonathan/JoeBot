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


def test_multiple_sponsor_aliases_are_queried_and_merged(monkeypatch):
    # A renamed company (e.g. Cassava Sciences -> Filana Therapeutics,
    # SAVA -> FLNA) may have trials registered under its old sponsor name
    # that ClinicalTrials.gov never backfilled to the new one -- both
    # aliases must be queried, not just the primary/current name.
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {"FLNA": ["Filana Therapeutics, Inc.", "Cassava Sciences, Inc."]})

    def _fetch(sponsor):
        if sponsor == "Filana Therapeutics, Inc.":
            return [clinicaltrials_client.TrialSnapshot(
                nct_id="NCT1111111", phase="PHASE3", status="RECRUITING",
                last_update_date=AS_OF - dt.timedelta(days=5),
            )]  # a newer, distinct trial registered under the new name
        if sponsor == "Cassava Sciences, Inc.":
            return [clinicaltrials_client.TrialSnapshot(
                nct_id="NCT2222222", phase="PHASE3", status="RECRUITING",
                last_update_date=AS_OF - dt.timedelta(days=50),
            )]  # an older, distinct trial still registered under the old name
        return []

    monkeypatch.setattr(clinicaltrials_client, "fetch_trials_for_sponsor", _fetch)
    result = ClinicalTrialSignal(lookback_days=120).score("FLNA", AS_OF)

    assert result.metadata["sponsor"] == "Filana Therapeutics, Inc."  # primary name shown
    assert result.score > 0.0
    assert result.metadata["days_since_update"] == 5  # picked the more recent of the two aliases' trials


def test_single_string_crosswalk_entry_still_works(monkeypatch):
    # _load_crosswalk() itself always normalizes to a list, but score()
    # tolerates a bare string too (e.g. a test/caller bypassing that
    # normalization), so this legacy single-alias shape isn't a silent bug.
    monkeypatch.setattr(catalyst_clinical, "_load_crosswalk", lambda: {"TEST": "Test Sponsor Inc."})
    monkeypatch.setattr(clinicaltrials_client, "fetch_trials_for_sponsor", lambda sponsor: [_trial(days_ago=1)])
    result = ClinicalTrialSignal(lookback_days=120).score("TEST", AS_OF)
    assert result.score > 0.0


def test_real_crosswalk_file_normalizes_both_string_and_list_entries():
    # Regression check against the actual config/pharma_crosswalk.yaml --
    # confirms it's valid YAML and that _load_crosswalk() normalizes both
    # a single-string entry (e.g. AXSM) and a multi-alias list entry (FLNA,
    # for the Cassava Sciences -> Filana Therapeutics rename) to a list.
    catalyst_clinical._crosswalk_cache = None
    crosswalk = catalyst_clinical._load_crosswalk()
    catalyst_clinical._crosswalk_cache = None  # don't leak into other tests

    assert crosswalk["AXSM"] == ["Axsome Therapeutics, Inc."]
    assert crosswalk["FLNA"] == ["Filana Therapeutics, Inc.", "Cassava Sciences, Inc."]
    assert "SAVA" not in crosswalk
