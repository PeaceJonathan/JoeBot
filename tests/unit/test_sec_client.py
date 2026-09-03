"""Unit tests for two real bugs found and fixed by reading edgartools==5.56.0
source directly (network to SEC EDGAR is unavailable in this environment,
so these can't be exercised against a live response -- see sec_client.py's
module docstring and README's data-validation notes):

1. EntityFacts exposes to_dataframe(), not to_pandas() -- the old code
   called a method that doesn't exist, silently caught by a broad except,
   so fundamental_sanity always reported "no usable XBRL data" regardless
   of what SEC actually had on file.
2. Filing.company is the SUBJECT company on a SC 13D/13G, never the
   reporting owner (the activist) -- the old fallback chain would have
   misattributed a stake to "the company disclosed a stake in itself."
   The real reporting-owner name lives at Filing.header.reporting_owners.
"""
import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

from joebot.data import sec_client


def test_latest_two_annual_picks_fy_rows_over_quarterly():
    df = pd.DataFrame([
        {"concept": "us-gaap:Revenues", "value": 100.0, "period_end": "2025-12-31", "fiscal_period": "FY"},
        {"concept": "us-gaap:Revenues", "value": 90.0, "period_end": "2024-12-31", "fiscal_period": "FY"},
        # A more recent quarterly figure that must NOT be picked as "latest"
        # ahead of the FY value -- mixing quarterly and annual would distort
        # a YoY growth calculation.
        {"concept": "us-gaap:Revenues", "value": 30.0, "period_end": "2026-03-31", "fiscal_period": "Q1"},
    ])
    latest, prior = sec_client._latest_two_annual(df, concept_candidates=("us-gaap:Revenues",))
    assert latest == 100.0
    assert prior == 90.0


def test_latest_two_annual_falls_back_when_no_fy_rows_present():
    df = pd.DataFrame([
        {"concept": "us-gaap:Revenues", "value": 30.0, "period_end": "2026-03-31", "fiscal_period": "Q1"},
        {"concept": "us-gaap:Revenues", "value": 28.0, "period_end": "2025-12-31", "fiscal_period": "Q4"},
    ])
    latest, prior = sec_client._latest_two_annual(df, concept_candidates=("us-gaap:Revenues",))
    assert latest == 30.0
    assert prior == 28.0


def test_latest_two_annual_returns_none_for_missing_concept():
    df = pd.DataFrame([{"concept": "us-gaap:Assets", "value": 5.0, "period_end": "2025-12-31", "fiscal_period": "FY"}])
    latest, prior = sec_client._latest_two_annual(df, concept_candidates=("us-gaap:Revenues",))
    assert latest is None and prior is None


def test_latest_two_annual_handles_empty_dataframe():
    latest, prior = sec_client._latest_two_annual(pd.DataFrame(), concept_candidates=("us-gaap:Revenues",))
    assert latest is None and prior is None


def _owner(name, cik="0001"):
    return SimpleNamespace(owner=SimpleNamespace(name=name, cik=cik))


def test_extract_filer_name_uses_reporting_owners_not_subject_company():
    filing = SimpleNamespace(
        company="Widget Corp",  # the SUBJECT company -- must never be returned here
        header=SimpleNamespace(
            reporting_owners=[_owner("Ryan Cohen")],
            filers=[SimpleNamespace(company_information=SimpleNamespace(name="Widget Corp"))],
        ),
    )
    assert sec_client._extract_filer_name(filing) == "Ryan Cohen"


def test_extract_filer_name_joins_multiple_reporting_owners():
    filing = SimpleNamespace(
        company="Widget Corp",
        header=SimpleNamespace(reporting_owners=[_owner("Fund A"), _owner("Fund B")], filers=[]),
    )
    assert sec_client._extract_filer_name(filing) == "Fund A; Fund B"


def test_extract_filer_name_returns_none_when_no_reporting_owners():
    filing = SimpleNamespace(
        company="Widget Corp",
        header=SimpleNamespace(reporting_owners=[], filers=[SimpleNamespace(company_information=SimpleNamespace(name="Widget Corp"))]),
    )
    assert sec_client._extract_filer_name(filing) is None


def test_extract_filer_name_returns_none_when_header_missing():
    filing = SimpleNamespace(company="Widget Corp", header=None)
    assert sec_client._extract_filer_name(filing) is None
