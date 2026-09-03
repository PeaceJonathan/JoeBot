# JoeBot

A personal market-opportunity research tool: it finds small/mid-cap
candidates showing a meaningful change, explains *why* in plain English
with the specific evidence behind it, flags what could go wrong, and
suggests a position size — never a bare "BUY XYZ."

**JoeBot never places trades and never connects to any brokerage.** You
execute manually, with whatever order type you prefer — a stock/ETF market
order fills promptly, it isn't restricted to once-daily execution the way
some fund orders are, so there's no special timing dance to do around
this. Nothing JoeBot produces is financial advice; verify everything
yourself. Every signal's usefulness is only as good as its own backtest
evidence (see "Backtesting" below) — treat a high score as a lead to
research, not a conclusion.

This deliberately does **not** try to be another Finviz/TradingView/
StockAnalysis — those already do general screening extremely well. JoeBot
is the layer above a screener: given a candidate, why does it matter
*right now*, and how much of your money is that worth risking.

## What it does

**Screens** the `status: active` sectors in `config/sectors.yaml` (tech,
defense, "faded giant" comebacks, pharma — plus four unvalidated candidate
sectors, see "Sector discovery" below) using nine signals, each
independently scored and fully visible in the output — never just a
black-box composite number:

| Signal | What it looks for |
|---|---|
| `technical_breakout` | Proximity to the 52-week high, volume surge, ATR, RSI, 50/200-day moving-average crossover |
| `fundamental_sanity` | Revenue growth trend and cash position, from SEC XBRL filings |
| `activist_stake` | A new/recent Schedule 13D or 13G filing that isn't a routine passive-index filing — the mechanism behind a GoPro-style "someone notable took a stake, stock rallies" move |
| `insider_buying` | An officer/director/insider open-market Form 4 purchase (via Yahoo's aggregated insider-transactions feed) — distinct from `activist_stake`'s 5%+ ownership threshold; a smaller, more common signal |
| `leadership_change` | A recent 8-K Item 5.02 (officer/director departure or appointment) — a classic catalyst for a company that's fallen off |
| `sentiment_reddit` | Mention-volume and mention-velocity across a handful of investing subreddits — one input among many, never a standalone buy signal |
| `clinical_trial` | A recently-updated late-phase (III/IV) trial for a pharma ticker — a proxy for "approaching a readout," not a prediction of the trial's outcome |
| `gov_contract` | A new government contract award, sized relative to the company's own market cap — the "small defense company + huge contract" pattern |
| `patent_activity` | Patent-filing momentum (recent vs. prior filing rate) — evidence worth a look, deliberately not a claim about IP quality; smallest default weight of any signal, see below |

**Explains why**, not just scores. Every signal's raw evidence
(`SignalResult.metadata`) feeds `joebot/reporting/narrative.py`, which
renders each top candidate as a card:

```
### XYZ (defense) -- score 0.78
**Verdict:** High conviction -- investigate further.
**Horizon:** Long-term (~1-3+ years) -- driven by gov_contract
**Why now:**
- Technical: trading within 5.0% of its 52-week high; volume running 2.1x its 20-day average.
- Government: a new contract award from Department of Defense worth $140,000,000 was recorded.
**Bear case -- what could go wrong:**
- High volatility -- ATR is 9.0% of price.
- Thin liquidity -- average dollar volume is only $800,000/day.
- Not checked at all (no data source in this project): share dilution, customer concentration, short interest, ...
**Data gaps** (only shown if a source was unavailable/unconfigured for this candidate):
- patent_activity: Patent Data (PatentsView) isn't configured (optional) -- this signal wasn't evaluated at all.
**Event timeline:**
- 2026-04-15 -- Government contract award ($140,000,000, Department of Defense)
```

These combine into a **weighted composite score**
(`config/settings.py::DEFAULT_SIGNAL_WEIGHTS`) with full per-signal
provenance persisted alongside it — see "Why the signal weights are a
placeholder" below before trusting the weighting.

**Classifies horizon**, not just score. Not every opportunity is a
short-term breakout -- a biotech trial might be a ~6-month catalyst, a
defense-technology thesis might take years. `joebot/reporting/horizon.py`
labels each candidate Short-term (~1-3 months), Medium-term (~3-12 months),
or Long-term (~1-3+ years) based on its single highest-scoring signal (a
price breakout is short-term; a patent/IP or government-contract thesis is
long-term). This is a **stated judgment call, not a backtested or measured
quantity** — this project has no data tracking realized time-to-payoff per
signal. Filterable on the Dashboard and Discover pages.

A **risk slider** (0 = conservative .. 100 = aggressive,
`joebot/risk/profile.py`) does three things at once:
1. Filters candidates by market-cap floor, volatility ceiling, and
   liquidity floor.
2. **Gates opportunity *type***, not just size — below the conservative→
   moderate crossover, any candidate whose single highest-scoring signal is
   a binary/event-risk one (`activist_stake`, `leadership_change`,
   `clinical_trial` — see `joebot/signals/base.py::BINARY_CATALYST_SIGNALS`)
   is excluded outright. A conservative investor isn't shown a smaller
   version of a turnaround special situation; they aren't shown it at all.
3. Scales position sizing (below).

A **budget calculator** (`joebot/risk/position_sizing.py`) takes a one-off
dollar amount — not tied to any daily/weekly/monthly cadence — and sizes
ATR-based positions across the risk-filtered, ranked candidates. Each
candidate needs a minimum composite score (a conviction floor, adjustable
in the dashboard) to receive any money at all; if too few candidates clear
it, **the leftover budget stays in cash** rather than being spread across
mediocre picks just to "use" the whole allocation.

A **walk-forward backtester** (`joebot/backtest/`) evaluates whether each
signal family actually predicts forward returns, out-of-sample, before any
of this is trusted or reweighted — see "Backtesting" below.

Every run — the scheduled one and the interactive one — shares the same
`joebot/pipeline.py` orchestration and the same SQLite database
(`data/joebot.db`), so they never drift apart.

## Setup

**One command** (recommended -- creates the venv, installs everything, and
copies `.env.example` to `.env` for you):

```bash
./setup.sh      # macOS/Linux
setup.bat       # Windows
```

Or manually:

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
- `PATENTSVIEW_API_KEY` — optional; same graceful-no-op pattern. Free but
  requires registration at <https://patentsview.org/apis/keyrequest> (the
  old keyless PatentsView endpoint was retired in 2026).

`insider_buying` needs no key -- it reuses the same `yfinance` price-data
access as `technical_breakout`.

**Then, before trusting any output, run the live data validator** on a
machine with normal internet access (this repo was developed and hardened
in network-sandboxed environments that cannot reach any of these APIs --
see "Known limitations" below):

```bash
python scripts/validate_live_data.py
```

It hits every configured source with a well-known ticker/company and
reports PASS/FAIL/SKIPPED per source, plus a non-zero exit code if a
required source fails -- see the script's own docstring for why it exists.

## Running it

**Daily scan (writes a report + DB rows, meant for cron):**

```bash
python scripts/run_daily.py --budget 10000 --risk-slider 50
```

Writes `data/reports/<today>.md` with the ranked candidates, narrative
"why it appeared" cards for the top opportunities, and a position-sizing
table (with the reserved-cash amount shown explicitly) — and records
everything in `data/joebot.db`.

```cron
0 7 * * 1-5 cd /path/to/JoeBot && /path/to/JoeBot/.venv/bin/python scripts/run_daily.py >> data/reports/cron.log 2>&1
```

**Interactive dashboard** (same pipeline, same database, live risk slider):

```bash
streamlit run dashboard/app.py    # or: ./run.sh / run.bat
```

Eight pages, each a thin view over `joebot/` -- no scan logic lives in the
dashboard itself:

| Page | What it shows |
|---|---|
| **Dashboard** | The latest scan, filtered live by the sidebar risk slider against already-persisted data (no re-fetch on every slider move), with a per-ticker narrative panel. |
| **Discover** | Search/filter every scanned candidate (sector, min score, ticker text) -- not risk-slider-gated, so it includes what a conservative profile would hide outright. |
| **Candidate Detail** | The full non-black-box breakdown for one ticker: per-signal score breakdown, why now, bear case, data gaps, event timeline, raw metadata. |
| **Catalysts** | A cross-candidate feed of recent dated events (filings, contracts, trial updates, insider buys, patents), most recent first -- not a forward-looking calendar (JoeBot has no data source for genuinely upcoming events and won't fabricate one). |
| **Research** | Browse past `scripts/run_backtest.py` runs -- per-signal evaluation-fold spread and `n_observations`. |
| **Portfolio** | Enter a dollar amount and a conviction floor, get sized positions plus the cash reserve. |
| **Data Health** | Connectivity status for every external source as of the latest scan -- see "Data honesty" below. |
| **Settings** | Read-only view of signal weights, risk-profile breakpoints, sector universe status, and which optional sources have credentials configured. |

A "Re-run scan now" button in the sidebar calls the identical
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
n means "not enough evidence yet," not "the signal doesn't work." If this
grows into testing combinations of signals (not just each one alone),
correct for multiple comparisons or require replication across
non-overlapping periods — testing enough combinations will eventually
produce one that looks great by chance alone.

**Tests:**

```bash
pytest
```

150 unit tests, all deterministic and network-free (hand-computed values,
fixture data via monkeypatch) — technical indicators, every signal's
scoring math (including `insider_buying`), horizon classification,
narrative bullet formatters, point-in-time forward-return edge cases (data
gaps, bankruptcies), signal attribution, risk-profile interpolation
(including the opportunity-type gate), budget allocation (including the
conviction floor/cash-reserve behavior), data-source health tracking, the
`yfinance` rate-limit retry logic, the SQLite schema migration, and the
walk-forward engine's resilience to a ticker with no price data anywhere
(see "Known limitations").

**Full-pipeline smoke tests** (no network, run these after any change to
signal/screener/reporting/storage code):

```bash
python scripts/smoke_test_synthetic.py     # scan -> persist -> narrative -> Data Health -> budget allocation
python scripts/smoke_test_dashboard.py     # every dashboard page, via Streamlit's AppTest harness
python scripts/backtest_synthetic_check.py # confirms the backtest engine recovers an engineered signal-return relationship
```

These prove the *plumbing* is sound end-to-end on fixture data; they say
nothing about whether real API responses match what the code expects (see
`scripts/validate_live_data.py`, "Setup" above) or whether any real signal
has predictive value (see "Known limitations").

## Sector discovery

`clean_energy`, `cybersecurity`, `space_satellite`, and
`robotics_automation` are seeded in `config/sectors.yaml` as
`status: candidate` — excluded from the daily scan, but included in the
backtester's universe by construction. Validate one with
`python scripts/run_backtest.py --sector <name>`, look at the
evaluation-fold spread, and only then manually flip its `status` to
`active`. Don't promote a sector on vibes — that defeats the point of
having a backtester at all. This is deliberately generic: nothing about
the pipeline is hard-coded to today's five sector names.

## Data sources (all free-tier)

| Purpose | Source | Notes |
|---|---|---|
| Price/volume, insider transactions | `yfinance` (primary), Finnhub (price fallback, optional key) | `yfinance` is unofficial and can be blocked/changed by Yahoo without notice; failures degrade gracefully per-ticker. Powers `technical_breakout` and `insider_buying` both. |
| Fundamentals/filings | SEC EDGAR via `edgartools` | Free, official, no key. Requires a real `SEC_USER_AGENT`, stays under 10 req/sec. |
| Sentiment | Reddit API via `praw` | Free at ~100 req/min for non-commercial personal use. StockTwits' API is frozen to new developers, so it's not used. |
| Clinical trials | ClinicalTrials.gov API | Free, public, no key. |
| Government contracts | USAspending.gov API | Free, public, no key. |
| Patents | USPTO PatentsView PatentSearch API | Free but requires a registered key (see Setup) — the old keyless endpoint was retired in 2026. |

Every source above reports its live connectivity to `joebot/data/health.py`
on every call, persisted per scan run and shown on the dashboard's **Data
Health** page — see "Data honesty" below for why this exists and what it
does and doesn't tell you.

General-purpose screeners (Finviz, TradingView, StockAnalysis, MarketBeat)
and investor-tracking tools (Dataroma) are good free tools JoeBot
deliberately doesn't try to replace — use them alongside this, not instead
of it, if you want that kind of broad screening.

## Data honesty: "no evidence found" vs. "data source unavailable"

Every external client (`joebot/data/*_client.py`, `market_data.py`)
records its live-call outcome to `joebot/data/health.py` -- OK, UNAVAILABLE
(the call failed), or NOT_CONFIGURED (an optional source with no
credentials). Every signal's `metadata["data_source_status"]` carries this
(via `joebot/signals/base.py::with_source_status`), so a 0.0 score is never
silently ambiguous between "checked, nothing there" and "couldn't check."
The narrative layer (`joebot/reporting/narrative.py`) surfaces this per
candidate as a **Data gaps** section, and the dashboard's **Data Health**
page shows it for the whole last scan. Every candidate's bear case also
explicitly lists the factors this project has *no* data source for at all
(dilution, customer concentration, short interest, competitive
positioning) rather than silently omitting them, which would read as
"checked, no issue."

## Known limitations (stated plainly, not hidden)

- **This environment could not reach any external data host at all.**
  Both the sandboxed environment the original signal/backtest code was
  written in, and separately the Claude Code Remote session that did this
  round of hardening, have network-egress policies that block every host
  this project needs (SEC EDGAR, Yahoo Finance, Reddit, ClinicalTrials.gov,
  USAspending.gov, PatentsView, Finnhub -- confirmed directly, including
  through the coding agent's own server-side web-fetch tool, not just
  inferred). **No code in this repository has been exercised against a
  real live HTTP response, ever, at any point in its development.** What
  *has* been done instead: every installed client library
  (`edgartools`, `yfinance`, `praw`) was read at the source level to verify
  attribute/method names and DataFrame schemas match what the code
  assumes -- this caught two real, confirmed bugs (below) -- and the full
  scan → persist → narrative → Data Health → budget-allocation pipeline,
  the backtest engine, and every dashboard page were verified end-to-end
  against fixture data (`scripts/smoke_test_synthetic.py`,
  `scripts/backtest_synthetic_check.py`, `scripts/smoke_test_dashboard.py`).
  **Run `python scripts/validate_live_data.py` on a machine with normal
  internet access before trusting any of this project's output.** That is
  not optional caution -- it is the one verification step that has
  genuinely never been performed.
- **Two real bugs found and fixed this way** (both in `joebot/data/sec_client.py`,
  found by reading `edgartools==5.56.0`'s actual source, not guessed): (1)
  `EntityFacts` exposes `to_dataframe()`, not `to_pandas()` -- the prior
  code called a method that doesn't exist, silently caught, so
  `fundamental_sanity` reported "no usable XBRL data" for every ticker
  regardless of what SEC actually had on file; (2) a SC 13D/13G's filer
  identity lives at `Filing.header.reporting_owners`, not `Filing.company`
  (the subject company) -- the prior fallback chain would have
  misattributed every activist stake to "the company disclosed a stake in
  itself." A third bug was found by actually *running*
  `scripts/run_backtest.py` in this network-blocked environment: an
  uncaught `MarketDataError` from a single ticker with no price data
  anywhere crashed the entire walk-forward run rather than being treated
  as one unknown observation -- fixed in `joebot/backtest/engine.py`.
  None of this proves the rest of the code is correct; it proves these
  three specific things were, and no longer are, wrong.
- **Two more real bugs found from an actual live run against real data**
  (by the project's own user, on their own machine -- the first genuine
  live exercise of this codebase): (1) scanning a full sector universe
  (dozens of tickers x several `yfinance` calls each) triggered Yahoo
  Finance's own rate limiting (`YFRateLimitError` / HTTP 429) partway
  through, and every ticker after that point silently failed and vanished
  from the results with no visible explanation -- a 39-ticker universe
  scan came back with 2 candidates. Fixed with retry-with-backoff on a
  confirmed rate-limit error (`joebot/data/market_data.py`), a gentler
  default request pace, and -- more importantly -- the scan now records
  *why* each skipped ticker was skipped and surfaces it prominently on the
  Dashboard page rather than just quietly returning a shorter table (see
  `joebot/screener/sector_screens.py::ScreenResult`,
  `ScanRun.tickers_skipped_json`). (2) `config/sectors.yaml` and
  `config/pharma_crosswalk.yaml` had `SAVA` (Cassava Sciences) -- the
  company renamed to Filana Therapeutics and changed its ticker to `FLNA`
  on 2026-03-11, confirmed via web search, months before this was caught.
  This is exactly the "static ticker universe needs manual upkeep" limitation
  already documented in `config/sectors.yaml`'s own header comment, now with
  a concrete example: a candidate the app was still confidently showing was
  for a ticker that hadn't existed for months. Fixed, and
  `catalyst_clinical.py`'s sponsor crosswalk now supports multiple
  name aliases per ticker (old + new legal name), since a renamed company's
  older trials may still be registered under the old name on
  ClinicalTrials.gov. **If a ticker in this repo's config looks wrong,
  it's stale config, not a live-data freshness problem** -- price/filing
  data itself is fetched fresh on every scan (subject to each source's own
  cache TTL, a few hours at most); the *list of which tickers to look at*
  is a hand-maintained file that nothing in this project auto-updates.
- **No true point-in-time fundamentals or delisted-ticker universe.**
  `data/delisted_universe.csv` is a small, manually curated, explicitly
  incomplete seed list — not a comprehensive survivorship-bias fix (that
  needs paid data like Sharadar/Norgate/CRSP, or Alpha Vantage's
  listing-status endpoint as a free partial upgrade worth evaluating
  later). `fundamental_sanity`'s XBRL lookup gates by fiscal period, not
  actual filing/acceptance date, so its backtest attribution carries a
  residual look-ahead risk the other signal families don't have (see
  `joebot/backtest/point_in_time.py`).
- **No real multi-year backtest has been run.** `scripts/run_backtest.py`
  and `joebot/backtest/` are architecturally verified (walk-forward date
  generation, point-in-time forward-return computation, calibration/
  evaluation fold split, and median-split signal attribution all
  demonstrably recover an engineered signal-to-return relationship on
  synthetic data -- `scripts/backtest_synthetic_check.py`), but this
  environment cannot fetch real historical prices, so **which signals
  actually have predictive value on real markets is still an entirely open
  question.** `DEFAULT_SIGNAL_WEIGHTS` remains an unvalidated starting
  guess. Run `python scripts/run_backtest.py --years 3` yourself once live
  data access is confirmed, and only change the weights from that
  evaluation-fold result.
- **No signal-combination testing exists yet** (section 6's "revenue
  acceleration + insider buying," "activist stake + depressed valuation,"
  etc.) -- `joebot/backtest/signal_evaluation.py` only evaluates one signal
  family at a time. Building this without the multiple-testing correction
  the project's own rules require (see "Backtesting" above) would be worse
  than not building it; this is the next highest-value piece of the
  research system, not a small add-on.
- **Sample sizes will be small.** Catalyst-signal events (activist stakes,
  insider purchases, leadership changes, contract awards) are rare in a
  small tracked universe — don't overfit the composite screener to one
  anecdote (the GoPro example that inspired this project is one data
  point, not a validated pattern, until backtested).
- **`patent_activity` measures filing momentum only, not IP quality**
  (citations, claim breadth, competitive relevance) — that's a hard
  problem this doesn't attempt, and it's why the signal's confidence is
  capped and its default weight is the smallest of any signal.
- **`insider_buying` reads Yahoo's free-text transaction description**
  (e.g. "Purchase at price X"), not the SEC's structured Form 4
  transaction code, since that structured field isn't in this feed --
  matched by keyword, which is more failure-prone than a code match. Insider
  *selling* is deliberately not scored as a negative (see the signal's
  module docstring) and isn't tracked as a bear-case factor either.
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
  data/          external data clients (market data, SEC, Reddit, clinical trials,
                 gov contracts, patents) + health.py (connectivity tracking) +
                 shared cache/rate-limiter
  signals/       one module per signal family, all behind a common Signal interface
  screener/      combines signals into a ranked, risk-filtered candidate list
  risk/          risk-slider profile + ATR-based budget allocator (with cash reserve)
  backtest/      walk-forward engine, point-in-time guardrails, signal attribution, metrics
  storage/       SQLite models + read queries
  reporting/     narrative "why it appeared"/bear-case/event-timeline cards +
                 horizon.py (short/medium/long-term classification) +
                 daily markdown report writer
  pipeline.py    shared orchestration seam for the CLI and the dashboard
scripts/         run_daily.py (cron), run_backtest.py (CLI),
                 validate_live_data.py (live smoke test -- run this yourself),
                 smoke_test_synthetic.py / smoke_test_dashboard.py /
                 backtest_synthetic_check.py (fixture-driven regression checks)
dashboard/       Streamlit app -- Dashboard / Discover / Candidate Detail /
                 Catalysts / Research / Portfolio / Data Health / Settings
tests/unit/      150 deterministic, network-free tests
data/            delisted_universe.csv (tracked), joebot.db + reports + cache (gitignored)
setup.sh / setup.bat   one-command install (venv + deps + .env)
run.sh / run.bat       one-command dashboard launch
```
