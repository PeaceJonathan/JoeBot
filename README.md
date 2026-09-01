# JoeBot

A personal stock breakout scanner and decision-support tool.

**JoeBot never places trades and never connects to any brokerage.** It
ranks candidate tickers and suggests position sizes for you to enter
manually — originally built with Fidelity in mind, which has no public
trading API for retail accounts. Nothing it produces is financial advice;
verify everything yourself before acting on it. Every signal's usefulness
is only as good as its own backtest evidence (see "Backtesting" below) —
treat a high score as a lead to research, not a conclusion.

## What it does

**Screens** a configured universe of small/mid-cap tickers
(`config/sectors.yaml`: tech, defense, "faded giant" comebacks, pharma —
plus four unvalidated candidate sectors, see "Sector discovery" below)
using six signals, each independently scored and fully visible in the
output (never just a black-box composite number):

| Signal | What it looks for |
|---|---|
| `technical_breakout` | Proximity to the 52-week high, volume surge, ATR, RSI, 50/200-day moving-average crossover |
| `fundamental_sanity` | Revenue growth trend and cash position, from SEC XBRL filings |
| `activist_stake` | A new/recent Schedule 13D or 13G filing that isn't a routine passive-index filing — the mechanism behind a GoPro-style "someone notable took a stake, stock rallies" move |
| `leadership_change` | A recent 8-K Item 5.02 (officer/director departure or appointment) — a classic catalyst for a company that's fallen off |
| `sentiment_reddit` | Mention-volume and mention-velocity across a handful of investing subreddits — one input among many, never a standalone buy signal |
| `clinical_trial` | A recently-updated late-phase (III/IV) trial for a pharma ticker — a proxy for "approaching a readout," not a prediction of the trial's outcome |

These combine into a **weighted composite score** (`config/settings.py::DEFAULT_SIGNAL_WEIGHTS`)
with full per-signal provenance persisted alongside it — see "Why the
signal weights are a placeholder" below before trusting the weighting.

A **risk slider** (0 = conservative .. 100 = aggressive,
`joebot/risk/profile.py`) does two things at once: it filters which
candidates even appear (market-cap floor, volatility ceiling, liquidity
floor) and it scales position sizing. A **budget calculator**
(`joebot/risk/position_sizing.py`) takes a one-off dollar amount — not tied
to any daily/weekly/monthly cadence — and sizes ATR-based positions across
the risk-filtered, ranked candidates, capped so no single name dominates
the budget and so the total never exceeds what you entered.

A **walk-forward backtester** (`joebot/backtest/`) evaluates whether each
signal family actually predicts forward returns, out-of-sample, before any
of this is trusted or reweighted — see "Backtesting" below.

Every run — the scheduled one and the interactive one — shares the same
`joebot/pipeline.py` orchestration and the same SQLite database
(`data/joebot.db`), so they never drift apart.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dashboard,sentiment,dev]"
cp .env.example .env
```

Edit `.env`:
- `SEC_USER_AGENT` — **required**. SEC requires a real, identifying
  User-Agent on every EDGAR request (`"JoeBot/0.1 (your-real-email@example.com)"`).
- `FINNHUB_API_KEY` — optional fallback price source if `yfinance` is
  blocked/rate-limited.
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — optional; without these,
  `sentiment_reddit` just scores 0 for everything rather than erroring
  (create a Reddit app at <https://www.reddit.com/prefs/apps>).

## Running it

**Daily scan (writes a report + DB rows, meant for cron):**

```bash
python scripts/run_daily.py --budget 10000 --risk-slider 50
```

Writes `data/reports/<today>.md` with the ranked candidates and a
position-sizing suggestion table, and records everything in
`data/joebot.db`.

```cron
0 7 * * 1-5 cd /path/to/JoeBot && /path/to/JoeBot/.venv/bin/python scripts/run_daily.py >> data/reports/cron.log 2>&1
```

**Interactive dashboard** (same pipeline, same database, live risk slider):

```bash
streamlit run dashboard/app.py
```

Three views: **Today's Picks** (the latest scan, filtered live by the
sidebar risk slider against already-persisted data — no re-fetch on every
slider move), **Budget Calculator** (enter a dollar amount, get sized
positions), and **Backtest Results** (browse past `scripts/run_backtest.py`
runs). A "Re-run scan now" button in the sidebar calls the identical
`pipeline.run_daily_scan()` the cron job uses.

**Backtesting:**

```bash
python scripts/run_backtest.py --years 3 --step-days 30
# Validate one candidate sector before promoting it:
python scripts/run_backtest.py --sector clean_energy
```

Walks forward through the tracked universe (including a curated
`data/delisted_universe.csv` of known small/mid-cap delistings/bankruptcies,
so results aren't purely survivorship-biased toward names still trading
today), scoring every signal at each date using only data on or before
that date, then reports whether each signal family's score actually
predicted forward returns — split chronologically into a calibration fold
and an evaluation fold, so any conclusion is out-of-sample.
`DEFAULT_SIGNAL_WEIGHTS` may only be changed based on an evaluation-fold
result from this command, per this project's hard rule against
data-snooping — never hand-tuned. **Read `n_observations` alongside every
result** — catalyst-signal events are rare in a small universe, and a low
n means "not enough evidence yet," not "the signal doesn't work."

**Tests:**

```bash
pytest
```

61 unit tests, all deterministic and network-free (hand-computed values,
fixture data via monkeypatch) — technical indicators, catalyst/sentiment/
clinical-trial scoring math, point-in-time forward-return edge cases
(data gaps, bankruptcies), signal attribution, risk-profile interpolation,
and position sizing.

## Sector discovery

`clean_energy`, `cybersecurity`, `space_satellite`, and
`robotics_automation` are seeded in `config/sectors.yaml` as
`status: candidate` — excluded from the daily scan, but included in the
backtester's universe by construction. Validate one with
`python scripts/run_backtest.py --sector <name>`, look at the
evaluation-fold spread, and only then manually flip its `status` to
`active`. Don't promote a sector on vibes — that defeats the point of
having a backtester at all.

## Data sources (all free-tier)

| Purpose | Source | Notes |
|---|---|---|
| Price/volume | `yfinance` (primary), Finnhub (fallback, optional key) | `yfinance` is unofficial and can be blocked/changed by Yahoo without notice; failures degrade gracefully per-ticker. |
| Fundamentals/filings | SEC EDGAR via `edgartools` | Free, official, no key. Requires a real `SEC_USER_AGENT`, stays under 10 req/sec. |
| Sentiment | Reddit API via `praw` | Free at ~100 req/min for non-commercial personal use. StockTwits' API is frozen to new developers, so it's not used. |
| Clinical trials | ClinicalTrials.gov API | Free, public, no key. |

## Known limitations (stated plainly, not hidden)

- **No true point-in-time fundamentals or delisted-ticker universe.**
  `data/delisted_universe.csv` is a small, manually curated, explicitly
  incomplete seed list — not a comprehensive survivorship-bias fix (that
  needs paid data like Sharadar/Norgate/CRSP). `fundamental_sanity`'s XBRL
  lookup gates by fiscal period, not actual filing/acceptance date, so its
  backtest attribution carries a residual look-ahead risk the other five
  signal families don't have (see `joebot/backtest/point_in_time.py`).
- **`edgartools` and PRAW/ClinicalTrials.gov field-name assumptions are
  unverified against live data.** This project was built in a sandboxed
  environment whose network policy blocks outbound SEC EDGAR, Yahoo
  Finance, Reddit, and ClinicalTrials.gov access. Every data-fetching
  module fails soft and is unit-tested on fixture data, and the
  entire pipeline was verified end-to-end with fully-stubbed network
  calls (including a synthetic-data check that the backtester correctly
  recovers a known signal-to-return relationship) — but the *real* field
  names/response shapes for 13D/13G filer identity, 8-K item codes, and
  ClinicalTrials.gov's JSON structure need a live smoke test on a machine
  with normal internet access before you trust their output. Start there.
- **Sample sizes will be small.** Catalyst-signal events (activist stakes,
  leadership changes) are rare in a small tracked universe — don't overfit
  the composite screener to one anecdote (the GoPro example that inspired
  this project is one data point, not a validated pattern, until backtested).
- **This is decision support only**, at every phase — it never places,
  sizes-for-auto-execution, or connects to any brokerage order API.

## Why the signal weights are a placeholder

`config/settings.py::DEFAULT_SIGNAL_WEIGHTS` is a starting guess, not a
tuned model. These weights may only be updated from a walk-forward,
out-of-sample backtest result (`scripts/run_backtest.py`'s evaluation
fold) — never hand-tuned on the full history, to avoid data-snooping bias.

## Repo layout

```
config/          settings, sectors.yaml, pharma sponsor crosswalk
joebot/
  data/          external data clients (market data, SEC, Reddit, clinical trials) + shared cache/rate-limiter
  signals/       one module per signal family, all behind a common Signal interface
  screener/      combines signals into a ranked, risk-filtered candidate list
  risk/          risk-slider profile + ATR-based budget allocator
  backtest/      walk-forward engine, point-in-time guardrails, signal attribution, metrics
  storage/       SQLite models + read queries
  reporting/     daily markdown report writer
  pipeline.py    shared orchestration seam for the CLI and the dashboard
scripts/         run_daily.py (cron), run_backtest.py (CLI)
dashboard/       Streamlit app (today / budget / backtest views)
tests/unit/      61 deterministic, network-free tests
data/            delisted_universe.csv (tracked), joebot.db + reports + cache (gitignored)
```
