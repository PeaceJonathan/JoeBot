"""Unit tests for joebot.signals.gov_contract scoring logic, against fixture
data injected via monkeypatch -- no network access."""
import datetime as dt

import pytest

from joebot.data import gov_contracts_client, market_data
from joebot.signals.gov_contract import GovContractSignal

AS_OF = dt.date(2026, 6, 1)


def _award(days_ago, amount=10_000_000, agency="Department of Defense"):
    return gov_contracts_client.ContractAward(
        award_id="AW123", recipient_name="Test Co", amount=amount,
        award_date=AS_OF - dt.timedelta(days=days_ago), awarding_agency=agency, description="test contract",
    )


def test_no_company_name_scores_zero_zero_confidence(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: None)
    result = GovContractSignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.confidence == 0.0


def test_no_awards_scores_zero(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")
    monkeypatch.setattr(gov_contracts_client, "fetch_recent_contracts", lambda *a, **k: [])
    result = GovContractSignal().score("TEST", AS_OF)
    assert result.score == 0.0


def test_large_recent_contract_relative_to_small_market_cap_scores_high(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")
    monkeypatch.setattr(market_data, "fetch_market_cap", lambda ticker: 50_000_000.0)
    monkeypatch.setattr(gov_contracts_client, "fetch_recent_contracts", lambda *a, **k: [_award(days_ago=2, amount=10_000_000)])
    result = GovContractSignal().score("TEST", AS_OF)
    # amount/market_cap = 10M/50M = 0.20 -> materiality_score capped at 1.0 (ratio/0.10 = 2.0 -> capped)
    assert result.score > 0.9
    assert result.metadata["materiality_ratio_of_market_cap"] == pytest.approx(0.20)


def test_small_contract_relative_to_large_market_cap_scores_low(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")
    monkeypatch.setattr(market_data, "fetch_market_cap", lambda ticker: 50_000_000_000.0)
    monkeypatch.setattr(gov_contracts_client, "fetch_recent_contracts", lambda *a, **k: [_award(days_ago=2, amount=1_000_000)])
    result = GovContractSignal().score("TEST", AS_OF)
    # ratio = 1M/50B = 0.00002 -> materiality_score ~0, only recency contributes
    assert result.score < 0.55


def test_missing_market_cap_uses_neutral_materiality(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_company_name", lambda ticker: "Test Co")
    monkeypatch.setattr(market_data, "fetch_market_cap", lambda ticker: None)
    monkeypatch.setattr(gov_contracts_client, "fetch_recent_contracts", lambda *a, **k: [_award(days_ago=2, amount=10_000_000)])
    result = GovContractSignal().score("TEST", AS_OF)
    # recency_score ~= 1.0, materiality_score = 0.5 (neutral) -> ~0.75
    assert result.score == pytest.approx(0.75, abs=0.05)
