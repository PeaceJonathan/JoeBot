# JoeBot

A personal stock breakout scanner and decision-support tool.

**JoeBot never places trades and never connects to any brokerage.** It
ranks candidate tickers and (in a later phase) suggests position sizes for
you to enter manually — originally built with Fidelity in mind, which has
no public trading API for retail accounts. Nothing it produces is financial
advice; verify everything yourself before acting on it.

## What it does today (Phase 1 + 2)

- Screens a configured universe of small/mid-cap tech, defense, and
  "faded giant" comeback tickers (`config/sectors.yaml`) using:
  - **Technical breakout signals**: proximity to the 52-week high, volume
    surge, ATR, RSI, and a 50/200-day moving-average crossover.
  - **Fundamental sanity signals**: revenue growth trend and cash position,
    pulled from SEC XBRL filings.
  - **Activist-stake signal**: a new/recent Schedule 13D or 13G filing on
    the ticker that isn't a routine passive-index filing — the mechanism
    behind the GoPro-style "someone notable took a stake, stock rallies"
    pattern.
  - **Leadership-change signal**: a recent 8-K Item 5.02 (officer/director
    departure or appointment) — a new exec team is a classic comeback
    catalyst for a company that's fallen off.
- Combines signals into a ranked, weighted composite score with full
  per-signal provenance (see "Why weights are a placeholder" below).
- Persists every run to a local SQLite database (`data/joebot.db`) —
  candidates, per-signal scores, and raw filing hits (deduped by SEC
  accession number so a filing isn't stored twice as it stays in the
  lookback window) — and writes a markdown report to
  `data/reports/YYYY-MM-DD.md`.

Later phases (see the project plan) add a rigorous walk-forward backtesting
framework, sentiment and clinical-trial signals, sector discovery, a risk
slider, a budget/position-size calculator, and a local Streamlit dashboard.

**Verification note on the catalyst signals (Phase 2):** this sandboxed
development session's network policy blocks outbound SEC EDGAR/Yahoo
Finance access, so `edgartools`' exact attribute names for a parsed 13D/13G
filer identity and 8-K item codes were not confirmed against live data —
`joebot/data/sec_client.py` tries several plausible attribute names
defensively and fails soft, but this needs a real backfill check (see the
plan's Phase 2 verification step) on a machine with normal internet access
before trusting the catalyst signals' output. The scoring math itself
(recency weighting, 13D vs. 13G weighting, passive-filer exclusion, and the
filing-event dedupe-by-accession-number) is covered by fully-stubbed unit
and integration tests and does not depend on the live fetch layer.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dashboard,sentiment,dev]"
cp .env.example .env
# Edit .env: set SEC_USER_AGENT to "JoeBot/0.1 (your-real-email@example.com)".
# SEC requires a real, identifying User-Agent on every request.
```

## Running the daily scan

```bash
python scripts/run_daily.py
```

This scans every ticker in `config/sectors.yaml`, ranks them, prints
progress to stdout, writes `data/reports/<today>.md`, and records the run in
`data/joebot.db`.

### Running it unattended (cron)

```cron
0 7 * * 1-5 cd /path/to/JoeBot && /path/to/JoeBot/.venv/bin/python scripts/run_daily.py >> data/reports/cron.log 2>&1
```

The scheduled job and the (future) dashboard both call the same
`joebot/pipeline.py` functions and share the same database, so the report
keeps being generated whether or not you ever open the dashboard.

## Running tests

```bash
pytest
```

Unit tests check the technical indicators (ATR, RSI, moving-average
crossover, volume surge, 52-week-high proximity) against hand-computed
values on small synthetic price series — no network access required.

## Data sources (all free-tier for now)

| Purpose | Source | Notes |
|---|---|---|
| Price/volume | `yfinance` (primary), Finnhub (fallback, optional `FINNHUB_API_KEY`) | `yfinance` is unofficial and can be blocked/changed by Yahoo without notice; failures degrade gracefully per-ticker. |
| Fundamentals/filings | SEC EDGAR via `edgartools` | Free, official, no key. Requires a real `SEC_USER_AGENT` and stays under 10 req/sec. |
| Sentiment (Phase 4) | Reddit API via `praw` | Free at ~100 req/min for non-commercial personal use. |
| Clinical trials (Phase 4) | ClinicalTrials.gov API | Free, public. |

A known limitation, stated plainly rather than hidden: none of these free
sources provide clean point-in-time historical fundamentals or a
delisted-ticker universe, so backtest results (Phase 3) are best-effort on
survivorship bias, not fully solved. Paid data (Sharadar/Norgate/CRSP-grade)
is a labeled future upgrade, not part of this build.

## Why signal weights are a placeholder

`config/settings.py::DEFAULT_SIGNAL_WEIGHTS` is a starting guess, not a
tuned model. Per the project's hard rule, these weights may only be updated
from a walk-forward, out-of-sample backtest result (Phase 3) — never
hand-tuned on the full history, to avoid data-snooping bias.

## Project plan

The full phased implementation plan lives in this repo's PR/commit history
and covers: SEC filing catalyst detection, walk-forward backtesting with
explicit look-ahead/survivorship-bias mitigation, sentiment and
clinical-trial signals, sector discovery validated by backtesting, a risk
slider, a budget calculator, and a Streamlit dashboard sharing the same
pipeline as the daily cron job.
