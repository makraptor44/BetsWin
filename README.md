# BetsWin

**An arbitrage scanner for prediction markets and sportsbooks.**

BetsWin polls Polymarket, Kalshi and Smarkets (Betfair and US sportsbooks with
credentials), looks for sets of positions that cost less than they are
guaranteed to return, sizes each one against real order-book depth, and scores
it for the failure modes that turn a theoretical edge into a real loss.

The hard part is not finding a number below 1. It is deciding whether that
number survives contact with reality — fees, depth, stale prices, mismatched
markets, and above all whether a single person could actually place every leg.
Most of this repository exists to answer that question honestly, which is why
the scanner reports *fewer* opportunities than a naive one, not more.

> **[▶ Live demo](https://makraptor44.github.io/BetsWin/)** — a static snapshot
> captured from the real engine. The detectors, sizing and risk scoring genuinely
> ran to produce those numbers; nothing is polling live venues. The calculators
> are fully interactive.

**It does not place bets.** It detects, sizes, and alerts. See
[Scope and limits](#scope-and-limits).

```
Python 3.12 / FastAPI  ── engine, detectors, sizing, storage, backtest
Next.js 16 / React 19  ── dashboard, market explorer, analytics, calculators
SQLite                 ── scan tape, price history, logged placements
```

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Setup](#setup)
  - [1. Clone the repository](#1-clone-the-repository)
  - [2. Install the engine](#2-install-the-engine)
  - [3. Configure the engine](#3-configure-the-engine)
  - [4. Install the dashboard](#4-install-the-dashboard)
  - [5. Run both](#5-run-both)
  - [6. Verify it works](#6-verify-it-works)
- [Running with Docker](#running-with-docker)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [How detection works](#how-detection-works)
  - [Execution zones](#execution-zones)
  - [The parts that matter](#the-parts-that-matter)
- [Using the dashboard](#using-the-dashboard)
- [API](#api)
- [Testing](#testing)
- [The demo deployment](#the-demo-deployment)
- [Contributing](#contributing)
- [Scope and limits](#scope-and-limits)
- [Background and roles](#background-and-roles)

---

## Features

**Detection**

- Four arbitrage detectors — binary complement, Dutch book (both directions),
  cross-venue, and cross-sportsbook — all resting on the same condition.
- Correlation arbitrage on jointly-priced event contracts, via a Gaussian
  copula, reported as a *directional* edge rather than a risk-free one.
- Near-miss watchlist: the tightest books that did not cross, in basis points,
  so an idle dashboard is distinguishable from a dead one.
- Completeness guard that rejects outcome sets which do not partition the
  sample space.

**Pricing and sizing**

- Per-venue fee models applied *before* detection, so every quoted edge is one
  that survives the fee schedule.
- Order-book walking for volume-weighted fills, with capacity counted only
  within 2% of best.
- Equal-profit stake allocation, conservative rounding, and an explicit
  worst-case profit recomputed after rounding.
- Void-adjusted edge alongside the nominal figure.

**Risk and safety**

- Execution-zone pairing: legs are only combined across venues one operator
  could realistically hold accounts on, in one currency.
- Confidence scoring with explicit risk flags; a large margin *lowers*
  confidence rather than raising it.
- Circuit breaker that halts scanning on a burst of implausible margins.
- Credential redaction on every stored error message.

**Interface and operations**

- Live dashboard over WebSocket with a polling fallback.
- Market explorer, venue/zone registry, analytics, and standalone calculators.
- Monte-Carlo backtester over the stored tape with a per-venue void model.
- Optional Telegram alerts above configurable margin and confidence floors.
- Offline demo mode with deterministic fixtures and no network access.

---

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 recommended | `backend/Dockerfile` and CI both use 3.12. `start.sh` accepts 3.11+. |
| Node.js | 22 recommended | `frontend/Dockerfile` and CI both use 22. `start.sh` accepts 18+. |
| npm | ships with Node | The repository uses `package-lock.json`. |
| Docker | optional | Only for [the container path](#running-with-docker). |

**No database server is needed.** Storage is SQLite; the file and its parent
directory are created on first run, and the schema is applied automatically.
**There are no migrations to run.**

**No API keys are needed to start.** Polymarket, Kalshi and Smarkets all publish
market data publicly. Betfair and The Odds API are optional and stay dark
without credentials.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/makraptor44/BetsWin.git
```

```bash
cd BetsWin
```

### 2. Install the engine

Python dependencies can be installed from the repository root:

```bash
pip install -r requirements.txt
```

That file simply includes `backend/requirements.txt`, which stays self-contained
so the Docker build (whose context is `backend/`) keeps working. Installing from
`backend/` works too:

```bash
cd backend && pip install -r requirements.txt
```

A virtual environment is recommended but not required:

```bash
python -m venv .venv && source .venv/bin/activate
```

On Windows, activate with `.venv\Scripts\activate` instead.

### 3. Configure the engine

Copy the annotated example and edit it:

```bash
cp backend/.env.example backend/.env
```

**The defaults work with no edits.** Every setting is documented inline in
`backend/.env.example`; see [Configuration](#configuration) for the ones worth
knowing about first. Never commit a `.env` containing real keys — `.gitignore`
already excludes it.

### 4. Install the dashboard

```bash
cd frontend && npm install
```

### 5. Run both

From the repository root, the launcher starts the engine and the dashboard
together:

```bash
./start.sh
```

On Windows PowerShell:

```powershell
.\start.ps1
```

For offline fixtures and no network access:

```bash
./start.sh --demo
```

Ports can be overridden, and if one is already taken the launcher moves to a
free port and tells you rather than failing:

```bash
API_PORT=8001 WEB_PORT=3001 ./start.sh
```

<details>
<summary>Running the two processes separately</summary>

Engine, from `backend/`:

```bash
python -m arbengine.main
```

Dashboard, from `frontend/`:

```bash
npm run dev
```

The dashboard proxies `/api` to `http://127.0.0.1:8000` by default. Point it
elsewhere with `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`.

</details>

### 6. Verify it works

The dashboard is at <http://localhost:3000> and the API at
<http://127.0.0.1:8000>, with interactive docs at `/docs`.

Check the engine is answering:

```bash
curl http://127.0.0.1:8000/api/health
```

Run a single scan cycle and print what it finds, without starting a server:

```bash
cd backend && python -m arbengine.main --scan
```

Run the test suite:

```bash
cd backend && python -m pytest tests/ -q
```

**Finding zero opportunities is the expected result**, not a failure. A
reasonably efficient market crosses rarely. The signals that the engine is
working are the scan log and the near-miss watchlist, both of which move every
cycle — see [An empty dashboard](#an-empty-dashboard-has-to-look-different-from-a-broken-one).

---

## Running with Docker

```bash
docker compose up --build
```

This builds both images and starts them together. It reads `backend/.env`, so
[step 3](#3-configure-the-engine) still applies. The SQLite database and logs
are bind-mounted to `backend/data` and `backend/logs`, so they survive container
replacement.

---

## Command reference

Every command below is defined in the repository. Run engine commands from
`backend/` and dashboard commands from `frontend/`.

### Engine

| Command | What it does |
|---|---|
| `python -m arbengine.main` | Serve the API and run the scanner. |
| `python -m arbengine.main --scan` | Run one scan cycle, print results, exit. |
| `python -m arbengine.main --demo` | Serve using offline fixtures, no network. |
| `python -m arbengine.main --reload` | Auto-reload on code changes. |
| `python -m arbengine.main --host H --port P` | Override the bind address. |
| `python -m pytest tests/ -q` | Run the test suite. |
| `python -m scripts.generate_demo_fixtures` | Regenerate the demo JSON fixtures. |

### Dashboard

| Command | What it does |
|---|---|
| `npm run dev` | Development server on port 3000. |
| `npm run build` | Production build. |
| `npm run start` | Serve a production build on port 3000. |
| `npm run typecheck` | `tsc --noEmit`. This is what CI runs. |
| `npm run build:demo` | Static export against the JSON fixtures. |
| `npm run preview:demo` | Serve the static export from `out/`. |

> **Two caveats, both verified against this commit.**
>
> `npm run build:demo` sets its environment variable using shell syntax
> (`NEXT_PUBLIC_STATIC_DEMO=true next build`), which **fails on Windows** because
> npm invokes `cmd.exe`. Use a POSIX shell such as Git Bash or WSL, or set the
> variable yourself before calling `npx next build`.
>
> `npm run lint` **does not currently work**. It calls `next lint`, which was
> removed in Next.js 16, and no ESLint configuration or dependency is present.
> Type checking via `npm run typecheck` does work, and is what CI enforces.

---

## Configuration

All engine settings are environment variables, read from `backend/.env`.
`backend/.env.example` documents every one of them inline; these are the ones to
look at first.

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_MODE` | `false` | `true` uses deterministic fixtures and makes no network calls. |
| `ENABLE_POLYMARKET` / `ENABLE_KALSHI` / `ENABLE_SMARKETS` | `true` | Public data, no credentials required. |
| `ENABLE_BETFAIR` | `false` | Needs `BETFAIR_APP_KEY` plus a session token or login. |
| `ODDS_API_KEY` | empty | Optional; enables US sportsbook odds. Without it that source stays dark. |
| `ENFORCE_ZONE_PAIRING` | `true` | Restricts cross-venue pairing to a single execution zone. |
| `OPERATOR_JURISDICTION` | empty | ISO-3166 alpha-2. Set it to hide trades you could not place from where you are. |
| `MIN_ARB_MARGIN` | `0.004` | Floor below which fees eat the edge. |
| `SUSPECT_MARGIN` | `0.05` | Anything fatter is flagged and penalised. |
| `BANKROLL` / `DEFAULT_STAKE` | `10000` / `500` | Sizing inputs. |
| `POLL_INTERVAL_SECONDS` | `45` | Scan cadence. |
| `DATABASE_PATH` | `data/betswin.db` | SQLite file; created automatically. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Optional push alerts. |

Secrets belong in `backend/.env`, which is git-ignored. The engine redacts
credentials from stored error messages, because an API key passed as a query
parameter otherwise travels inside exception text into the database and back out
through the analytics endpoint.

---

## Project structure

```
backend/
  arbengine/
    odds.py         Odds mathematics — every formula from the theory volume
    fees.py         Per-venue fee models (Kalshi's, and exchange commission)
    venues.py       Venue registry and the execution-zone pairing rule
    models.py       Canonical Quote → Outcome → Market → Event → Arb
    normalise.py    Cross-venue title matching and its hard guards
    detector.py     The four detectors, near misses, confidence scoring
    correlation_arb.py       Gaussian-copula joint-probability model
    correlation_detector.py  Correlation edges as directional positions
    sizing.py       Order-book walking and equal-profit allocation
    storage.py      SQLite: arbs, placements, scans, price history
    alerts.py       Telegram push + in-process broadcast to the dashboard
    scanner.py      Pipeline orchestration, dedupe, circuit breaker
    backtest.py     Void-model replay and threshold sweep
    api.py          FastAPI: REST + WebSocket
    config.py       Settings, read from the environment
    main.py         CLI entry point
    demo_data.py    Deterministic offline fixtures
    sources/        base.py · polymarket.py · kalshi.py · smarkets.py ·
                    betfair.py · odds_api.py
  scripts/          Demo fixture generation
  tests/            191 tests, including the PDFs' worked examples
  Dockerfile        Python 3.12 image
  .env.example      Annotated configuration reference

frontend/
  app/              Opportunities (/) · Positions · Markets · Venues ·
                    Analytics · Calculators · Settings
  components/       Table, detail drawer, place-bet modal, charts, primitives
  lib/              API client, types, formatting, live-data hook, demo shim
  public/demo/      JSON fixtures captured from the real engine
  Dockerfile        Node 22 image

.github/workflows/
  deploy-demo.yml   Tests, captures fixtures, publishes the static demo
  attribution.yml   Rejects AI co-author trailers on the default branch

start.sh / start.ps1   Launchers that start engine and dashboard together
docker-compose.yml     Both services, with data and logs bind-mounted
requirements.txt       Root entry point; includes backend/requirements.txt
```

Everything venue-specific stops at `sources/`. Adding a venue means writing one
`Source` subclass; the detectors do not change. That is the point of the
`sources/base.py` interface.

Two PDFs in the repository root are the source material: `arbitrage_betting_theory.pdf`
for the mathematics and risk model, `arbitrage_betting_python.pdf` for the
architecture. Section references throughout the code point back to them.

---

## How detection works

All detectors rest on one condition: take the best price on each outcome, sum
the implied probabilities, and check whether the total falls below what the
position pays.

| Type | Condition | What it is |
|---|---|---|
| **Binary complement** | `p(yes) + p(no) < 1` | One market whose own two sides cost less than the $1 they pay. A crossed book — rare, brief, and the cleanest structure available since both legs settle under one rulebook. |
| **Dutch book (buy all)** | `Σ p(yesᵢ) < 1` | Every outcome of a mutually exclusive event bought at once for less than the $1 exactly one of them returns. |
| **Dutch book (fade all)** | `Σ p(noᵢ) < n − 1` | The NO side of every outcome. Exactly one outcome occurs, so `n−1` legs settle. This is the direction that actually fires, because long-tail outcomes are systematically overpriced on the YES side. |
| **Cross-venue** | `p(yes @ A) + p(no @ B) < 1` | The same question priced differently on two venues *in the same execution zone*. |
| **Sportsbook** | `Σ 1/dᵢ < 1` | Classic best-price-per-outcome across books. Needs `ODDS_API_KEY`. |

Prices reaching the detectors are already fee-adjusted, so a "1.5% edge" is one
that survives Kalshi's trading fee (or Smarkets' commission) rather than a
headline number that evaporates at execution.

Correlation arbitrage is handled separately and reported as a **directional**
position, not a risk-free one: it prices a joint-event contract against a
Gaussian copula and a historical correlation prior, and the full stake is at
risk if the model is wrong.

### Execution zones

The single largest constraint on what this system will show you. A cross-venue
arbitrage is only real if **one person can place both legs**. The detector is
perfectly happy to pair a Kalshi contract against a Betfair price, and the
arithmetic looks immaculate, but nobody can take that trade: the accounts sit in
different jurisdictions, fund in different currencies, and the only way to hold
both is to misrepresent where you are.

So venues are partitioned into zones, and pairing runs **inside** a zone and
never across one:

| Zone | Venues | Currency | Structure |
|---|---|---|---|
| `us_prediction` | Polymarket · Kalshi | USD | $1 binary contracts |
| `uk_exchange` | Betfair · Smarkets | GBP | back/lay exchange, commission on winnings |
| `us_sportsbook` | The Odds API books | USD | fixed odds |

```
polymarket <-> kalshi      allowed
betfair    <-> smarkets    allowed
betfair    <-> kalshi      rejected — different zone
```

Three things follow, and they are the reason the rule is worth its cost:

1. **Everything surfaced is placeable.** The alert stream gets smaller and its
   hit rate goes up. An "opportunity" requiring a second passport is not an
   opportunity.
2. **No FX leg.** At the 1% margins these trades actually run at, an unhedged
   currency exposure is *larger than the entire edge* — a 1% move in GBPUSD
   erases a 1% arb. Pairing inside a currency removes the risk rather than
   warning about it.
3. **Settlement conventions agree.** Two $1-contract venues void and settle
   alike. An exchange voiding a market and a contract market resolving it "NO"
   are not the same event, and that difference cannot be hedged.

Set `OPERATOR_JURISDICTION=GB` (or `US`, or whatever applies) and the engine
narrows further to what you could legitimately place from where you are. The
**Venues** page shows the whole registry, the pairing matrix with a reason for
every verdict, and the pairs the rule declined on the last scan — so a blocked
pair is auditable rather than an invisible absence.

The rule is policy, not hard-coded blindness: `ENFORCE_ZONE_PAIRING=false` turns
it off. The currency guard does not turn off, because hedging dollars with
pounds is wrong arithmetic rather than a configurable preference.

### The parts that matter

Most of the code is plumbing. These are the pieces that decide whether the
output is trustworthy.

#### Fees are priced in before detection, not after

Kalshi charges `ceil(0.07 × contracts × P × (1−P))`, which peaks at `P = 0.50` —
exactly where most arbitrage candidates live. A 2.04% gross edge on a two-leg
trade at mid-price nets **0.25%** after fees. Detecting on quoted prices and
subtracting fees later would surface a stream of opportunities that lose money.
Every quote carries an `effective_price` from the moment it enters the system.

#### Depth is walked, not assumed

Top-of-book tells you a price exists, not that your size can have it. Each leg's
order book is walked for the requested notional to get a volume-weighted fill,
and the edge is recomputed at those realised prices — an opportunity that
survives $200 but not $2,000 is reported at the size it actually survives.

Reported capacity counts only depth priced within 2% of the best offer. Summing
the whole ask stack is arithmetically true and practically useless: Polymarket
books have resting size out to $0.999, and counting it would advertise
**$566,000** of capacity on a trade whose realistic size is **$21,000**.

#### Outcome sets are checked for completeness

A Dutch book is only valid if the outcomes partition the sample space. If a venue
paginates a 20-outcome event, or one leg is dropped for having a one-sided book,
the remaining prices sum to far below 1 — which looks like an enormous edge and
is in fact a set that leaves a real outcome completely uncovered.

Any mutually exclusive set whose YES prices sum below 0.90 is rejected. On live
data this filters roughly 15 phantom opportunities per scan. Complete books
cluster tightly at 1.00, exactly as the theory predicts.

For the same reason, liquidity filters are applied per *event*, never per
outcome — dropping one thin leg would silently break exhaustiveness.

#### Cross-venue matching fails closed

Pairing two markets that are not the same bet is the most expensive mistake the
system can make, because the "hedge" does not hedge. Before any fuzzy comparison
runs, hard guards reject the pair outright:

- **Thresholds** must match exactly. `$100k` and `100,000` are normalised to the
  same token; `$100k` and `$120k` never pair. Calendar fragments are stripped
  first, so the `31` in "Dec 31" is not mistaken for a price level.
- **Years** and **months** must agree.
- **Direction** must agree — "above 3%" never pairs with "below 3%".

Only then does a similarity score apply, and that score travels with the
opportunity to discount its confidence. A paired title is weaker evidence than a
shared identifier, and the UI says so.

#### A large margin lowers confidence

The overwhelming majority of very large apparent arbitrages are mismatched lines,
stale prices, or bad data. Margin is never coloured by size anywhere in the
interface, and anything above `SUSPECT_MARGIN` is flagged and penalised rather
than celebrated. A circuit breaker halts scanning entirely if a burst of
implausible margins appears, on the reasoning that the feed is more likely wrong
than the market.

#### An empty dashboard has to look different from a broken one

Zero opportunities is the normal state of a reasonably efficient market. On a
typical live scan of ~890 events the engine finds two to four, and often none at
all. A dashboard whose only live surface is an opportunities table therefore
spends most of its time showing nothing — which is indistinguishable, from the
browser, from a scanner that has silently died.

So every cycle pushes three things, not one:

- **The scan log.** Events read, cycle duration, feed errors. One line per
  cycle, streamed over the same socket. If those numbers move, the engine works.
- **The watchlist.** The tightest books on the tape and how far each is from
  crossing, in basis points. These are not opportunities; they are the ones that
  could become opportunities, and they move every cycle even when nothing does.
- **How much of that distance is fees.** A book quoted at 0.982 that arrives at
  1.007 after Smarkets' commission crossed on paper and lost to the fee
  schedule. Showing the gross and net gaps side by side says which of the two
  problems you are looking at.

#### Void-adjusted edge is the number that matters

An arbitrage is risk-free only if every leg settles. At a 2% void rate costing
30% of stake, a 1.01% nominal margin is worth **0.39%**. Every opportunity shows
both figures, and the backtester Monte-Carlos the stored tape under a per-venue
void model rather than reporting the naive sum.

---

## Using the dashboard

**Opportunities** is the live table. Click any row for the full breakdown: an
interactive stake calculator, the payout in every state of the world, and the
arithmetic behind the numbers with each step explained.

The payout matrix is the check worth running before staking anything. The
guarantee is only real if profit is positive in *every* row — after rounding,
the outcomes are no longer exactly equal.

Below the table, the **watchlist** carries the books that did not cross and the
**scan activity** feed carries the cycles that produced them.

**Positions** tracks logged placements, unwind quotes and settlement.

**Markets** browses the normalised tape the detectors see, with each event's
combined book and overround.

**Venues** is the execution-zone registry: which venues may be arbed against
which, why, where each is available, and every pair the rule declined on the
last scan.

**Analytics** shows the margin distribution, detection volume, and a backtester
that replays stored history under a void model.

**Calculators** exposes the same arithmetic on arbitrary prices: equal-profit
stakes, void-adjusted edge, Kelly sizing, and odds conversion.

**Settings** tunes thresholds live, and shows what each setting implies —
including the zone-pairing rule and the jurisdiction you trade from.

---

## API

Interactive documentation is served at `/docs` when the engine is running. The
main groups:

| Group | Endpoints |
|---|---|
| System | `/api/health`, `/api/status`, `/api/config`, `/api/venues` |
| Opportunities | `/api/arbs`, `/api/arbs/{id}`, `/api/arbs/{id}/resize`, `/api/near-misses` |
| Placements | `/api/arbs/{id}/place`, `/api/arbs/{id}/log-placement` |
| Positions | `/api/positions`, `/api/positions/{id}/unwind-quote`, `/api/positions/{id}/sell-back`, `/api/positions/{id}/settle` |
| Markets | `/api/markets`, `/api/history` |
| Analytics | `/api/analytics`, `/api/backtest`, `/api/backtest/sweep` |
| Calculators | `/api/calc/stakes`, `/api/calc/kelly`, `/api/calc/convert`, `/api/calc/void-adjusted`, `/api/calc/correlation` |
| Correlation | `/api/correlation/pairs` and nested outcome routes |
| Scanner control | `/api/scanner/scan`, `/api/scanner/start`, `/api/scanner/stop`, `/api/scanner/reset-breaker` |
| Live updates | `/ws` (WebSocket) |

---

## Testing

```bash
cd backend && python -m pytest tests/ -q
```

191 tests, covering the odds mathematics against the worked examples in the PDFs,
the detectors, sizing and order-book walking, venue pairing, the circuit breaker,
scanner retirement, correlation arbitrage, and placement/settlement flows.

Frontend type checking:

```bash
cd frontend && npm run typecheck
```

CI runs the Python suite, the type check, and the static demo build on every
push to `main`. See the caveats in the [command reference](#command-reference)
regarding `npm run lint`.

---

## The demo deployment

`.github/workflows/deploy-demo.yml` publishes the dashboard to GitHub Pages on
every push to `main`. The build runs the test suite, boots the engine in demo
mode, captures its real API responses as JSON, then exports the frontend as
static files that read those fixtures instead of calling a backend.

Pure-arithmetic endpoints (stake sizing, Kelly, void adjustment, odds conversion,
the backtest Monte Carlo) are ported to TypeScript in
`frontend/lib/staticMath.ts`, so the calculators stay genuinely interactive on
the demo rather than being frozen screenshots. Those ports are formula-for-formula
copies of `backend/arbengine/odds.py`.

To enable it once: **Settings → Pages → Source: GitHub Actions**.

---

## Contributing

`.github/workflows/attribution.yml` rejects AI co-author trailers on the default
branch. GitHub reads a `Co-Authored-By` trailer and credits that address as a
repository contributor, and the credit outlives the commit — force-pushing it
away leaves the sidebar entry standing. Several coding tools append such trailers
by default; if yours does, turn it off before committing.

---

## Scope and limits

**It does not place bets.** Automating orders at venues whose terms forbid it
risks account closure and forfeited balances. The system detects, sizes, and
alerts; you place the legs and log them. `POST /api/arbs/{id}/log-placement`
records a manual trade so realised P&L can be reconciled against expectation.

**Real opportunities are small and brief.** On a typical live scan of ~880
events the scanner finds two to four, at margins near 1%, most capped by depth
to a few thousand dollars. Long stretches with zero opportunities are the normal
state of a reasonably efficient market, not a malfunction.

**Fees and voids dominate the arithmetic at these margins.** Both are modelled,
but the void rate is an assumption you should replace with your own measured
figure once you have history — the engine logs every candidate so you can.

**Polymarket restricts US persons** from trading, whatever its market data says.
Kalshi is the CFTC-regulated US venue. Check what you are eligible to use.

**Correlation arbitrage is not arbitrage.** It is a modelled directional edge
sized by fractional Kelly, and the full stake is lost if the model is wrong. The
interface labels it as such.

---

## Background and roles

The product concept: scan prediction-market and sportsbook events, find
mispriced odds across high-margin, low-liquidity order books, and surface
positions that are profitable regardless of outcome — without the user needing
to write code.

Prediction markets rather than sportsbooks, because they carry lower liquidity
and therefore more mispricing, they are peer-to-peer rather than a contest
against a bookmaker's margin, and fewer people are currently arbitraging them.
That last advantage is expected to be temporary.

Work is split across the team as follows.

| Contributor | Area | Files |
|---|---|---|
| Ethan | Stake calculation, notifier, base source, odds API | `sizing.py`, `alerts.py`, `sources/base.py`, `sources/odds_api.py` |
| Tom | Scanning, execution, entry point | `scanner.py`, `api.py`, `main.py` |
| Harry | Backtest, storage, alerts | `backtest.py`, `storage.py`, `alerts.py` |
| Anthony | Normalisation, detection, exchange clients | `normalise.py`, `detector.py`, `venues.py`, `sources/betfair.py` |

### Strategy roadmap

1. **Single-event arbitrage** — binary complement, Dutch book, cross-venue,
   sportsbook. *Implemented.*
2. **Structured products** — correlation arbitrage *(implemented)*, distribution
   arbitrage and long-tail arbitrage *(not yet implemented)*.
3. **Model-driven pricing** — predicted true probabilities from data-driven
   models. *Not yet implemented.*
