"""Historical universe construction for the backtester.

Merges the live sector universe (config/sectors.yaml) with
data/delisted_universe.csv -- a manually curated, explicitly incomplete
list of known small/mid-cap delistings/bankruptcies in the tracked sectors.
This is this project's stated survivorship-bias mitigation on a free data
budget: it is NOT a comprehensive point-in-time universe (that requires
paid data like Sharadar/Norgate/CRSP) -- it only prevents the most obvious
failure mode of testing exclusively on names that are still trading today.
Expect data/delisted_universe.csv to need ongoing manual upkeep as more
names in these sectors delist.

Simplification worth knowing about: every *live* sector ticker is included
at every past as_of_date, even ones that hadn't IPO'd yet (e.g. IONQ didn't
exist in 2015). This isn't a correctness bug -- fetching price history for
a ticker before its IPO just returns empty data, which every signal and
point_in_time.forward_return already handle as "unknown" -- but it does
mean pre-IPO as_of_dates for newer names contribute no information rather
than being actively excluded, which is wasted computation, not bias.
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt

from config import settings
from joebot.data import universe


@dataclasses.dataclass
class DelistedEntry:
    ticker: str
    sector: str
    company_name: str
    active_from: dt.date
    active_to: dt.date
    event_type: str  # "bankruptcy" or "delisted_other"
    notes: str


def load_delisted_universe() -> list[DelistedEntry]:
    if not settings.DELISTED_UNIVERSE_FILE.exists():
        return []

    entries = []
    with settings.DELISTED_UNIVERSE_FILE.open(newline="") as f:
        for row in csv.DictReader(f):
            entries.append(DelistedEntry(
                ticker=row["ticker"],
                sector=row["sector"],
                company_name=row["company_name"],
                active_from=dt.date.fromisoformat(row["active_from"]),
                active_to=dt.date.fromisoformat(row["active_to"]),
                event_type=row["event_type"],
                notes=row.get("notes", ""),
            ))
    return entries


def universe_as_of(as_of_date: dt.date) -> dict[str, list[str]]:
    """sector -> tickers considered part of the tradable universe as of as_of_date."""
    result: dict[str, list[str]] = {name: list(s.tickers) for name, s in universe.load_sectors().items()}

    for entry in load_delisted_universe():
        if entry.active_from <= as_of_date <= entry.active_to:
            result.setdefault(entry.sector, [])
            if entry.ticker not in result[entry.sector]:
                result[entry.sector].append(entry.ticker)

    return result


def delisting_lookup() -> dict[str, DelistedEntry]:
    """ticker -> DelistedEntry, for point_in_time.forward_return's delisting_info argument."""
    return {e.ticker: e for e in load_delisted_universe()}
