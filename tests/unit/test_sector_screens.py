"""Unit tests for joebot.screener.sector_screens.run_all_sectors's
ScreenResult -- the attempted/skipped tracking that makes a scan that
silently drops most of its universe (a rate limit, a renamed/delisted
ticker) visible on the dashboard instead of just a shorter-than-expected
table. See dashboard/views/today.py and joebot/pipeline.py.
"""
from __future__ import annotations

import datetime as dt

from joebot.data import universe
from joebot.screener import sector_screens
from joebot.signals.base import SignalResult

AS_OF = dt.date(2026, 6, 1)


class _FakeSector:
    def __init__(self, name, tickers):
        self.name = name
        self.tickers = tickers


class _AlwaysScoresSignal:
    name = "always_scores"

    def score(self, ticker, as_of_date):
        return SignalResult(score=0.1, confidence=1.0, metadata={})


class _FailsForOneTickerSignal:
    name = "fails_for_bad"

    def score(self, ticker, as_of_date):
        if ticker == "BADTICKER":
            raise RuntimeError("simulated: every data source failed for this ticker")
        return SignalResult(score=0.2, confidence=1.0, metadata={})


def test_screen_result_reports_attempted_and_no_skips_when_everything_succeeds(monkeypatch):
    monkeypatch.setattr(universe, "active_sectors", lambda: {"tech": _FakeSector("tech", ["AAA", "BBB"])})
    result = sector_screens.run_all_sectors(AS_OF, signals=[_AlwaysScoresSignal()])
    assert result.attempted == 2
    assert result.skipped == []
    assert len(result.candidates) == 2


def test_screen_result_records_a_skipped_ticker_with_reason(monkeypatch):
    monkeypatch.setattr(universe, "active_sectors", lambda: {"tech": _FakeSector("tech", ["GOODTICKER", "BADTICKER"])})
    result = sector_screens.run_all_sectors(AS_OF, signals=[_FailsForOneTickerSignal()])

    assert result.attempted == 2
    assert len(result.candidates) == 1
    assert result.candidates[0].ticker == "GOODTICKER"
    assert len(result.skipped) == 1
    assert result.skipped[0].ticker == "BADTICKER"
    assert result.skipped[0].sector == "tech"
    assert "simulated" in result.skipped[0].reason


def test_screen_result_across_multiple_sectors(monkeypatch):
    monkeypatch.setattr(universe, "active_sectors", lambda: {
        "tech": _FakeSector("tech", ["AAA"]),
        "defense": _FakeSector("defense", ["BBB", "BADTICKER"]),
    })
    result = sector_screens.run_all_sectors(AS_OF, signals=[_FailsForOneTickerSignal()])
    assert result.attempted == 3
    assert len(result.candidates) == 2
    assert len(result.skipped) == 1
