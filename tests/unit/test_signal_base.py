"""Unit test for joebot.signals.base.with_source_status -- the decorator
that stamps every signal's metadata with the health of the external
source(s) it depends on, so a 0.0 score is distinguishable between "no
evidence found" and "data source unavailable" (see joebot/data/health.py).
"""
import datetime as dt

from joebot.data import health
from joebot.signals.base import SignalResult, with_source_status


def setup_function():
    health.reset()


class _DummySignal:
    name = "dummy"

    @with_source_status(health.SEC, health.MARKET_DATA)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        return SignalResult(score=0.0, confidence=0.5, metadata={"foo": "bar"})


def test_decorator_attaches_status_for_every_declared_source():
    health.record_success(health.SEC)
    health.record_failure(health.MARKET_DATA, detail="timeout")

    result = _DummySignal().score("TEST", dt.date(2026, 1, 1))

    assert result.metadata["foo"] == "bar"  # original metadata preserved
    assert result.metadata["data_source_status"] == {
        health.SEC: health.OK,
        health.MARKET_DATA: health.UNAVAILABLE,
    }


def test_decorator_reports_not_configured_when_source_never_called():
    result = _DummySignal().score("TEST", dt.date(2026, 1, 1))
    assert result.metadata["data_source_status"][health.SEC] == health.NOT_CONFIGURED
