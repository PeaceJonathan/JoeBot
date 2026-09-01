"""Unit tests for joebot.signals.catalyst_sec scoring logic.

These test the *scoring math and filtering* (recency, form-type weighting,
passive-filer exclusion) against fixture FilingEvent data injected via
monkeypatch -- no network access, and independent of whatever edgartools'
real attribute names turn out to be (that's the fetch layer in sec_client,
not covered here; see its module docstring for the outstanding
verification gap).
"""
import datetime as dt

import pytest

from joebot.data import sec_client
from joebot.signals.catalyst_sec import ActivistStakeSignal, LeadershipChangeSignal

AS_OF = dt.date(2026, 6, 1)


def _event(form, days_ago, filer_name=None, items=()):
    return sec_client.FilingEvent(
        ticker="TEST",
        form=form,
        filing_date=AS_OF - dt.timedelta(days=days_ago),
        accession_no=f"acc-{form}-{days_ago}",
        filer_name=filer_name,
        items=items,
    )


def test_activist_stake_no_filings_scores_zero(monkeypatch):
    monkeypatch.setattr(sec_client, "fetch_ownership_filings", lambda *a, **k: [])
    result = ActivistStakeSignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.confidence > 0


def test_activist_stake_recent_13d_scores_higher_than_old_13g(monkeypatch):
    monkeypatch.setattr(
        sec_client, "fetch_ownership_filings",
        lambda *a, **k: [_event("SC 13D", days_ago=1, filer_name="Some Fund LLC")],
    )
    recent_13d = ActivistStakeSignal().score("TEST", AS_OF)

    monkeypatch.setattr(
        sec_client, "fetch_ownership_filings",
        lambda *a, **k: [_event("SC 13G", days_ago=170, filer_name="Some Fund LLC")],
    )
    old_13g = ActivistStakeSignal().score("TEST", AS_OF)

    assert recent_13d.score > old_13g.score


def test_activist_stake_filters_out_passive_filers(monkeypatch):
    monkeypatch.setattr(
        sec_client, "fetch_ownership_filings",
        lambda *a, **k: [_event("SC 13G", days_ago=1, filer_name="Vanguard Group Inc")],
    )
    result = ActivistStakeSignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.metadata["filtered_passive_count"] == 1


def test_activist_stake_keeps_unknown_filer_name(monkeypatch):
    monkeypatch.setattr(
        sec_client, "fetch_ownership_filings",
        lambda *a, **k: [_event("SC 13D", days_ago=1, filer_name=None)],
    )
    result = ActivistStakeSignal().score("TEST", AS_OF)
    assert result.score > 0.0


def test_leadership_change_no_filings_scores_zero(monkeypatch):
    monkeypatch.setattr(sec_client, "fetch_8k_leadership_events", lambda *a, **k: [])
    result = LeadershipChangeSignal().score("TEST", AS_OF)
    assert result.score == 0.0


def test_leadership_change_recency_scores_higher_when_fresh(monkeypatch):
    monkeypatch.setattr(
        sec_client, "fetch_8k_leadership_events",
        lambda *a, **k: [_event("8-K", days_ago=2, items=("5.02",))],
    )
    fresh = LeadershipChangeSignal().score("TEST", AS_OF)

    monkeypatch.setattr(
        sec_client, "fetch_8k_leadership_events",
        lambda *a, **k: [_event("8-K", days_ago=175, items=("5.02",))],
    )
    stale = LeadershipChangeSignal().score("TEST", AS_OF)

    assert fresh.score > stale.score
    assert fresh.score == pytest.approx(1.0 - 2 / 180, abs=1e-6)


def test_is_likely_passive_filer_matches_case_insensitively():
    event = _event("SC 13G", days_ago=1, filer_name="BLACKROCK, INC.")
    assert event.is_likely_passive_filer()


def test_is_likely_passive_filer_false_for_unknown_name():
    event = _event("SC 13D", days_ago=1, filer_name="Ryan Cohen")
    assert not event.is_likely_passive_filer()
