"""Unit tests for joebot.data.health -- the registry that must keep "no
evidence found" and "data source unavailable" distinguishable (see the
module docstring and README section on data honesty).
"""
from joebot.data import health


def setup_function():
    health.reset()


def test_unrecorded_source_defaults_to_not_configured():
    status = health.get_status(health.REDDIT)
    assert status.status == health.NOT_CONFIGURED
    assert status.call_count == 0


def test_record_success_sets_ok():
    health.record_success(health.SEC)
    status = health.get_status(health.SEC)
    assert status.status == health.OK
    assert status.call_count == 1
    assert status.last_success_at is not None


def test_record_failure_sets_unavailable_and_is_distinguishable_from_not_configured():
    health.record_failure(health.CLINICALTRIALS, detail="timeout")
    status = health.get_status(health.CLINICALTRIALS)
    assert status.status == health.UNAVAILABLE
    assert status.status != health.NOT_CONFIGURED
    assert status.detail == "timeout"
    assert status.failure_count == 1


def test_record_not_configured_sets_status():
    health.record_not_configured(health.PATENTS, detail="no API key")
    status = health.get_status(health.PATENTS)
    assert status.status == health.NOT_CONFIGURED
    assert status.detail == "no API key"


def test_not_configured_does_not_clobber_a_real_success_this_run():
    health.record_success(health.MARKET_DATA)
    health.record_not_configured(health.MARKET_DATA, detail="stale no-op call site")
    status = health.get_status(health.MARKET_DATA)
    assert status.status == health.OK


def test_failure_after_success_flips_to_unavailable():
    health.record_success(health.MARKET_DATA)
    health.record_failure(health.MARKET_DATA, detail="rate limited")
    status = health.get_status(health.MARKET_DATA)
    assert status.status == health.UNAVAILABLE


def test_snapshot_includes_every_canonical_source_even_if_never_called():
    snap = health.snapshot()
    assert set(snap.keys()) == set(health.ALL_SOURCES)
    for source_health in snap.values():
        assert source_health.status == health.NOT_CONFIGURED


def test_snapshot_reflects_recorded_status():
    health.record_success(health.USASPENDING)
    snap = health.snapshot()
    assert snap[health.USASPENDING].status == health.OK
    assert snap[health.REDDIT].status == health.NOT_CONFIGURED  # untouched


def test_display_name_and_emoji_defined_for_every_source():
    for source in health.ALL_SOURCES:
        h = health.SourceHealth(source=source)
        assert h.display_name  # non-empty
        assert h.emoji in ("\U0001F7E2", "\U0001F534", "\U0001F7E1")
