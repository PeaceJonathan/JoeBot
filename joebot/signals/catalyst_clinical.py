"""Pharma/biotech clinical-trial catalyst signal.

Scores a ticker on whether it has a late-phase (Phase 3/4) trial that was
recently updated -- a proxy for "approaching a readout or approval
decision" without trying to predict the trial's actual outcome, which is a
genuinely high-variance binary event no free data source can forecast.
Sponsor identification is via config/pharma_crosswalk.yaml; a ticker
missing from that crosswalk scores 0 with zero confidence (unknown, not
"no trial activity" -- don't read a missing crosswalk entry as bad news).

Each ticker maps to one or more sponsor-name aliases (a plain string, or a
YAML list of strings). Multiple aliases matter for a renamed company: when
Cassava Sciences renamed to Filana Therapeutics (SAVA -> FLNA, 2026-03-11),
trials registered before the rename may still carry the old sponsor name on
ClinicalTrials.gov (registries don't necessarily backfill a corporate
rename onto historical records) -- querying only the new name would silently
miss them. All aliases are queried and merged (deduped by nct_id).
"""
from __future__ import annotations

import datetime as dt

import yaml

from config import settings
from joebot.data import clinicaltrials_client, health
from joebot.signals.base import SignalResult, with_source_status

DEFAULT_LOOKBACK_DAYS = 120

_crosswalk_cache: dict[str, list[str]] | None = None


def _load_crosswalk() -> dict[str, list[str]]:
    """ticker -> list of sponsor-name aliases (always a list, even for a
    single-alias entry, so callers never special-case the YAML shape)."""
    global _crosswalk_cache
    if _crosswalk_cache is not None:
        return _crosswalk_cache

    path = settings.CONFIG_DIR / "pharma_crosswalk.yaml"
    if not path.exists():
        _crosswalk_cache = {}
        return _crosswalk_cache

    with path.open() as f:
        raw = yaml.safe_load(f) or {}

    _crosswalk_cache = {
        ticker: (aliases if isinstance(aliases, list) else [aliases])
        for ticker, aliases in raw.items()
    }
    return _crosswalk_cache


class ClinicalTrialSignal:
    name = "clinical_trial"

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    @with_source_status(health.CLINICALTRIALS)
    def score(self, ticker: str, as_of_date: dt.date) -> SignalResult:
        sponsor_aliases = _load_crosswalk().get(ticker)
        if not sponsor_aliases:
            return SignalResult(score=0.0, confidence=0.0, metadata={"error": "no sponsor crosswalk entry"})
        if isinstance(sponsor_aliases, str):
            sponsor_aliases = [sponsor_aliases]  # tolerate a caller/test bypassing _load_crosswalk's own normalization

        trials_by_nct: dict[str | None, clinicaltrials_client.TrialSnapshot] = {}
        for alias in sponsor_aliases:
            for t in clinicaltrials_client.fetch_trials_for_sponsor(alias):
                trials_by_nct[t.nct_id] = t
        trials = list(trials_by_nct.values())
        sponsor_name = sponsor_aliases[0]  # primary/current name, for display
        cutoff = as_of_date - dt.timedelta(days=self.lookback_days)

        relevant = [
            t for t in trials
            if t.phase in clinicaltrials_client.LATE_PHASES
            and t.last_update_date is not None
            and cutoff <= t.last_update_date <= as_of_date
        ]

        if not relevant:
            return SignalResult(
                score=0.0, confidence=0.6,
                metadata={"sponsor": sponsor_name, "trials_checked": len(trials)},
            )

        most_recent = max(relevant, key=lambda t: t.last_update_date)
        days_ago = (as_of_date - most_recent.last_update_date).days
        recency_score = max(0.0, 1.0 - days_ago / self.lookback_days)
        status_score = 1.0 if (most_recent.status or "").upper() in clinicaltrials_client.ACTIVE_STATUSES else 0.6

        score = 0.6 * recency_score + 0.4 * status_score

        return SignalResult(
            score=float(score),
            confidence=0.6,
            metadata={
                "sponsor": sponsor_name,
                "nct_id": most_recent.nct_id,
                "phase": most_recent.phase,
                "status": most_recent.status,
                "days_since_update": days_ago,
                "last_update_date": most_recent.last_update_date.isoformat(),
            },
        )
