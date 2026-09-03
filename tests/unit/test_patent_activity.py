"""Unit tests for joebot.signals.patent_activity scoring logic, against
fixture data injected via monkeypatch -- no network access."""
import datetime as dt

import pytest

from joebot.data import market_data, patents_client
from joebot.signals.patent_activity import PatentActivitySignal

AS_OF = dt.date(2026, 6, 1)


def _patent(days_ago, title="Some invention"):
    return patents_client.PatentRecord(patent_id="US123", title=title, patent_date=AS_OF - dt.timedelta(days=days_ago))


def test_no_company_name_scores_zero_zero_confidence(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: None)
    result = PatentActivitySignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.confidence == 0.0


def test_no_patents_scores_zero_low_confidence(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")
    monkeypatch.setattr(patents_client, "fetch_patents_for_assignee", lambda *a, **k: [])
    result = PatentActivitySignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.confidence == pytest.approx(0.3)


def test_filing_burst_scores_higher_than_steady_baseline(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")

    # Burst: many recent filings, none in the earlier half.
    burst = [_patent(days_ago=d) for d in range(0, 20, 2)]  # 10 patents, all in last ~20 days
    monkeypatch.setattr(patents_client, "fetch_patents_for_assignee", lambda *a, **k: burst)
    burst_result = PatentActivitySignal(lookback_days=730).score("TEST", AS_OF)

    # Steady: same total count, evenly split between recent and earlier halves.
    steady = [_patent(days_ago=d) for d in (10, 400, 20, 410, 30, 420, 40, 430, 50, 440)]
    monkeypatch.setattr(patents_client, "fetch_patents_for_assignee", lambda *a, **k: steady)
    steady_result = PatentActivitySignal(lookback_days=730).score("TEST", AS_OF)

    assert burst_result.score > steady_result.score


def test_confidence_is_capped_moderate_even_when_score_is_high(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")
    monkeypatch.setattr(patents_client, "fetch_patents_for_assignee", lambda *a, **k: [_patent(days_ago=d) for d in range(20)])
    result = PatentActivitySignal().score("TEST", AS_OF)
    assert result.confidence <= 0.4
