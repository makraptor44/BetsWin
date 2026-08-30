# BetsWin
An automated profitable sports bet and prediction market finder and placer available from the tips of your fingers.

How the prouct Works?
1. API's scan across prediction market events, including sports, politics and crypto
2. We find the mispriced odds across high margin, low liquid order books.
3. We provide the service to place an arbitrage bet for a given event across mutiple exchanges
4. Gives the opportunity to place risk free bets within minutes.


Why is this product useful?
1. The first centralised platform which incorporates arbitrage free programatic betting without needing to program.
2. free money for users, competing against manual users who place bets and lose out to slippage.
3. Free to use, only expense is commission on your winnings.  We only win if you win.


Why prediction markets as opposed to sportbooks?
1. Lower liquidity, more mispricings
2. competing in a pvp platform rather than against a bookie
3. less arbers on prediction markets -> though short time span for this product to be profitable.


Roles:
Ethan -> Stake Calculation, Notifier System, base.py, odds_api
Tom -> Scanning, Execution, main (entry point)
Harry -> Backtest (historical replay), storage (SQL), alerts
Anthony -> normalise.py (make sure man u or 1 ex and man utd are the same reference), detector, betfair.py(exchange client)

Very much open to change roles

---

# Implementation

> **[▶ Live demo](https://makraptor44.github.io/BetsWin/)** — a static snapshot captured
> from the real engine. The detectors, sizing and risk scoring genuinely ran to
> produce those numbers; nothing is polling live venues. The calculators are fully
> interactive.

A working build of the system described above. It polls Polymarket, Kalshi and
Smarkets (Betfair too, with credentials), finds sets of positions that cost less
than they are guaranteed to return, sizes each one against real order-book depth,
and scores it for the failure modes that turn a theoretical edge into a real
loss — including the one that matters most, whether a single person could
actually place every leg.

Built from the two PDFs in this repo: `arbitrage_betting_theory.pdf` for the
mathematics and risk model, `arbitrage_betting_python.pdf` for the architecture.
Section references throughout the code point back to them.

```
Python / FastAPI  ── engine, detectors, sizing, storage, backtest
Next.js / React   ── dashboard, market explorer, analytics, calculators
```

## Where each role's work lives

The file layout follows the split agreed in the plan above:

| Area | Files |
|---|---|
| Stake calculation, notifier, base source, odds API | `backend/arbengine/sizing.py`, `alerts.py`, `sources/base.py`, `sources/odds_api.py` |
| Scanning, execution, entry point | `backend/arbengine/scanner.py`, `api.py`, `main.py` |
| Backtest, storage, alerts | `backend/arbengine/backtest.py`, `storage.py`, `alerts.py` |
| Normalisation, detection, exchange clients | `backend/arbengine/normalise.py`, `detector.py`, `venues.py`, `sources/polymarket.py`, `sources/kalshi.py`, `sources/smarkets.py`, `sources/betfair.py` |

`betfair.py` is there as planned, alongside `smarkets.py`. Both slot in as
`Source` subclasses without the detectors changing, which is the point of the
`sources/base.py` interface. Smarkets' market-data API is public, so it works
with no credentials; Betfair's needs an application key and stays dark without
one.

## Quick start

**Prerequisites:** Python 3.11+, Node 18+.

```bash
cd backend && pip install -r requirements.txt && cp .env.example .env
cd ../frontend && npm install
```

Then from the project root:

```bash
./start.sh
```

Windows PowerShell:

```powershell
.\start.ps1
```

Dashboard at <http://localhost:3000>, API at <http://127.0.0.1:8000> (docs at
`/docs`). No credentials needed — Polymarket, Kalshi and Smarkets all publish
market data publicly. Turn the UK exchange zone on with `ENABLE_SMARKETS=true`.

Run `./start.sh --demo` for offline fixtures and no network. If a port is
already taken the launcher moves to a free one and says so rather than dying.

Docker: `docker compose up --build`.

## What it looks for

All four detectors rest on one condition from the theory volume: take the best
price on each outcome, sum the implied probabilities, and check whether the total
falls below what the position pays.

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

## Execution zones

The single largest change to what this system will show you. A cross-venue
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

The rule is policy, not hard-coded blindness: `ENFORCE_ZONE_PAIRING=false`
turns it off. The currency guard does not turn off, because hedging dollars with
pounds is wrong arithmetic rather than a configurable preference.

## The parts that matter

Most of the code is plumbing. These are the pieces that decide whether the
output is trustworthy.

### Fees are priced in before detection, not after.

Kalshi charges `ceil(0.07 × contracts × P × (1−P))`, which peaks at `P = 0.50` —
exactly where most arbitrage candidates live. A 2.04% gross edge on a two-leg
trade at mid-price nets **0.25%** after fees. Detecting on quoted prices and
subtracting fees later would surface a stream of opportunities that lose money.
Every quote carries an `effective_price` from the moment it enters the system.

### Depth is walked, not assumed

Top-of-book tells you a price exists, not that your size can have it. Each leg's
order book is walked for the requested notional to get a volume-weighted fill,
and the edge is recomputed at those realised prices — an opportunity that
survives $200 but not $2,000 is reported at the size it actually survives.

Reported capacity counts only depth priced within 2% of the best offer. Summing
the whole ask stack is arithmetically true and practically useless: Polymarket
books have resting size out to $0.999, and counting it would advertise
**$566,000** of capacity on a trade whose realistic size is **$21,000**.

### Outcome sets are checked for completeness

A Dutch book is only valid if the outcomes partition the sample space. If a venue
paginates a 20-outcome event, or one leg is dropped for having a one-sided book,
the remaining prices sum to far below 1 — which looks like an enormous edge and
is in fact a set that leaves a real outcome completely uncovered.

Any mutually exclusive set whose YES prices sum below 0.90 is rejected. On live
data this filters roughly 15 phantom opportunities per scan. Complete books
cluster tightly at 1.00, exactly as the theory predicts.

For the same reason, liquidity filters are applied per *event*, never per
outcome — dropping one thin leg would silently break exhaustiveness.

### Cross-venue matching fails closed

Pairing two markets that are not the same bet is the most expensive mistake the
system can make, because the "hedge" does not hedge. Before any fuzzy comparison
runs, four hard guards reject the pair outright:

- **Thresholds** must match exactly. `$100k` and `100,000` are normalised to the
  same token; `$100k` and `$120k` never pair. Calendar fragments are stripped
  first, so the `31` in "Dec 31" is not mistaken for a price level.
- **Years** and **months** must agree.
- **Direction** must agree — "above 3%" never pairs with "below 3%".

Only then does a similarity score apply, and that score travels with the
opportunity to discount its confidence. A paired title is weaker evidence than a
shared identifier, and the UI says so.

### A large margin lowers confidence

The overwhelming majority of very large apparent arbitrages are mismatched lines,
stale prices, or bad data. Margin is never coloured by size anywhere in the
interface, and anything above 5% is flagged and penalised rather than
celebrated. A circuit breaker halts scanning entirely if a burst of implausible
margins appears, on the reasoning that the feed is more likely wrong than the
market.

### An empty dashboard has to look different from a broken one

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

### Void-adjusted edge is the number that matters

An arbitrage is risk-free only if every leg settles. At a 2% void rate costing
30% of stake, a 1.01% nominal margin is worth **0.39%**. Every opportunity shows
both figures, and the backtester Monte-Carlos the stored tape under a per-venue
void model rather than reporting the naive sum.

## Layout

```
backend/
  arbengine/
    odds.py         Odds mathematics — every formula from the theory volume
    fees.py         Per-venue fee models (Kalshi's, and exchange commission)
    venues.py       Venue registry and the execution-zone pairing rule
    models.py       Canonical Quote → Outcome → Market → Event → Arb
    normalise.py    Cross-venue title matching and its hard guards
    detector.py     The four detectors, near misses, confidence scoring
    sizing.py       Order-book walking and equal-profit allocation
    storage.py      SQLite: arbs, placements, scans, price history
    alerts.py       Telegram push + in-process broadcast to the dashboard
    scanner.py      Pipeline orchestration, dedupe, circuit breaker
    backtest.py     Void-model replay and threshold sweep
    api.py          FastAPI: REST + WebSocket
    demo_data.py    Deterministic offline fixtures
    sources/        polymarket.py · kalshi.py · smarkets.py · betfair.py · odds_api.py
  tests/            138 tests, including the PDFs' worked examples
frontend/
  app/              Opportunities · Markets · Venues · Analytics · Calculators · Settings
  components/       Table, detail drawer, charts, design primitives
  lib/              API client, types, formatting, live-data hook, demo shim
```

## Using it

**Opportunities** is the live table. Click any row for the full breakdown: an
interactive stake calculator, the payout in every state of the world, and the
arithmetic behind the numbers with each step explained.

The payout matrix is the check worth running before staking anything. The
guarantee is only real if profit is positive in *every* row — after rounding,
the outcomes are no longer exactly equal.

Below the table, the **watchlist** carries the books that did not cross and the
**scan activity** feed carries the cycles that produced them. Together they are
the answer to "the terminal is busy but the dashboard is empty": the tape is
moving, it just is not crossing.

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

### CLI

```bash
cd backend
python -m arbengine.main --scan      # one cycle, print results, exit
python -m arbengine.main --demo      # serve with offline fixtures
python -m pytest tests/ -q           # the backend test suite
```

## The demo deployment

`.github/workflows/deploy-demo.yml` publishes the dashboard to GitHub Pages on
every push to `main`. The build runs the test suite, boots the engine in demo
mode, captures its real API responses as JSON, then exports the frontend as
static files that read those fixtures instead of calling a backend.

Pure-arithmetic endpoints (stake sizing, Kelly, void adjustment, odds
conversion, the backtest Monte Carlo) are ported to TypeScript in
`frontend/lib/staticMath.ts`, so the calculators stay genuinely interactive on
the demo rather than being frozen screenshots.

Two implementations of one formula drift -- and these had: the odds converter
returned `Infinity` in TypeScript where Python raised, and the demo backtest
silently dropped per-venue void rates. Both suites therefore assert against one
shared fixture, `shared/odds-vectors.json`, whose expected values are generated
from the Python implementation. The Python half is
`backend/tests/test_shared_vectors.py`; the TypeScript half is
`frontend/lib/__tests__/sharedVectors.test.ts` (`npm test`). A divergence now
fails a test instead of reaching a user.

To enable it once: **Settings → Pages → Source: GitHub Actions**.

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


## Strategies

Implemented, and covered by the test suite:

1. **Single-event arbitrage** — binary complement, Dutch books (YES and NO
   side), cross-venue pairs, and best-price-per-outcome across sportsbooks.
   All risk-free once every leg fills; see `arbengine/detector.py`.
2. **Correlation arbitrage** — a joint-event contract priced against a
   Gaussian-copula fair value from its two marginals. Directional, not
   risk-free, and reported as such; see `arbengine/correlation_arb.py`.

### Roadmap

Not implemented. Listed so the ambition is visible, not because any code
exists for them yet:

- Distribution arbitrage across strike ladders.
- Long-tail arbitrage on many-outcome events.
- Model-derived true probabilities (data-driven value betting).

