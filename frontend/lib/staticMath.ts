/**
 * Client-side arithmetic for the static demo.
 *
 * The GitHub Pages build has no Python process behind it, so the endpoints that
 * are *pure functions of their inputs* are reimplemented here. These are ports
 * of `backend/arbengine/odds.py`, formula for formula, so the calculators stay
 * genuinely interactive on the demo rather than being frozen screenshots.
 *
 * Data-heavy endpoints (live opportunities, markets, analytics) are not
 * recomputed here — those are served from fixtures captured off the real engine.
 */

import type {
  ConvertResult,
  KellyResult,
  StakeCalcResult,
  VoidResult,
} from "./types";

const MIN_PRICE = 1e-4;
const MAX_PRICE = 1 - 1e-4;

const clamp = (p: number) => Math.min(Math.max(p, MIN_PRICE), MAX_PRICE);

/** p_impl = 1/d (Part I s2.2). */
export const decimalToProb = (d: number) => (d <= 1 ? 1 : 1 / d);

/** d = 1/p. */
export const probToDecimal = (p: number) => 1 / clamp(p);

/** B = sum(1/d_i) (Part I s2.3). */
export const book = (ds: number[]) =>
  ds.reduce((s, d) => s + decimalToProb(d), 0);

/** m = 1/B - 1 (Part I s2.4). */
export const arbMargin = (b: number) => (b <= 0 ? 0 : 1 / b - 1);

/** s_i = S * (1/d_i) / B (Part I s3.2). */
export function equalProfitStakes(ds: number[], total: number): number[] {
  const b = book(ds);
  if (b <= 0) return ds.map(() => 0);
  return ds.map((d) => (total * decimalToProb(d)) / b);
}

/** Normalise implied probabilities to sum to 1 (Part I s12.2). */
export function devigProportional(ds: number[]): number[] {
  const b = book(ds);
  if (b <= 0) return ds.map(() => 0);
  return ds.map((d) => decimalToProb(d) / b);
}

/** f* = (p*d - 1)/(d - 1) (Part I s7.3). */
export function kellyFraction(p: number, d: number): number {
  if (d <= 1) return 0;
  return Math.max(0, (p * d - 1) / (d - 1));
}

/** E[pi] = (1-v)*m - v*L (Part I s13.3). */
export const marginAfterVoids = (m: number, v: number, l: number) =>
  (1 - v) * m - v * l;

/**
 * f* = ((1-v)*m - v*L) / (m*L) (Part I s13.4).
 *
 * Mirrors `odds.kelly_arb_fraction`, boundary cases included. With no void
 * cost the trade carries no risk and Kelly places no bound, so the answer is
 * Infinity -- not 0, which reads as "stake nothing" for the one input where
 * the trade is riskless. No edge at all really is 0.
 */
export function kellyArbFraction(m: number, v: number, l: number): number {
  if (m <= 0) return 0;
  if (l <= 0) return Infinity;
  return marginAfterVoids(m, v, l) / (m * l);
}

const roundTo = (v: number, step: number) =>
  step <= 0 ? v : Math.round(v / step) * step;

const r2 = (v: number) => Math.round(v * 100) / 100;
const r5 = (v: number) => Math.round(v * 100000) / 100000;

// ------------------------------------------------------------- endpoints

export function calcStakes(
  ds: number[],
  totalStake: number,
  roundToStep?: number,
): StakeCalcResult {
  const b = book(ds);
  let stakes = equalProfitStakes(ds, totalStake);
  if (roundToStep) stakes = stakes.map((s) => roundTo(s, roundToStep));
  const total = stakes.reduce((s, x) => s + x, 0);
  const payouts = stakes.map((s, i) => s * ds[i]);
  const profits = payouts.map((p) => p - total);

  return {
    book: r5(b),
    is_arbitrage: b < 1,
    margin: r5(arbMargin(b)),
    overround_pct: Math.round((b - 1) * 1000000) / 10000,
    vig_pct: Math.round((1 - 1 / b) * 1000000) / 10000,
    implied_probs: ds.map((d) => r5(decimalToProb(d))),
    fair_probs: devigProportional(ds).map(r5),
    stakes: stakes.map(r2),
    total_stake: r2(total),
    payouts: payouts.map(r2),
    profit_by_outcome: profits.map(r2),
    worst_case_profit: r2(Math.min(...payouts) - total),
    guaranteed_profit: r2(total * arbMargin(b)),
  };
}

export function calcKelly(
  probability: number,
  decimalOdds: number,
  fraction: number,
  bankroll: number,
): KellyResult {
  const f = kellyFraction(probability, decimalOdds);
  return {
    edge: r5(probability * decimalOdds - 1),
    is_value_bet: probability * decimalOdds > 1,
    kelly_fraction: r5(f),
    kelly_stake: r2(f * bankroll),
    fractional_kelly: r5(f * fraction),
    fractional_stake: r2(f * fraction * bankroll),
    fair_odds: Math.round((1 / probability) * 10000) / 10000,
    bankroll,
  };
}

export function calcConvert(value: number, from: string): ConvertResult {
  let d: number;
  if (from === "decimal") {
    d = value;
  } else if (from === "american") {
    // American odds are undefined between -100 and +100. Without this guard
    // Math.abs(0) yields Infinity rather than throwing, so the demo returned
    // {decimal: Infinity} where the Python path raised. Same rule both sides.
    if (Math.abs(value) < 100) {
      throw new Error(
        "American odds must be +100 or longer, or -100 or shorter",
      );
    }
    d = value > 0 ? 1 + value / 100 : 1 + 100 / Math.abs(value);
  } else {
    if (!(value > 0 && value < 1)) throw new Error("probability must be 0-1");
    d = probToDecimal(value);
  }
  if (d <= 1) throw new Error("decimal odds must exceed 1.0");
  const american = d >= 2 ? (d - 1) * 100 : -100 / (d - 1);
  return {
    decimal: r5(d),
    american: r2(american),
    probability: r5(decimalToProb(d)),
    contract_price: Math.round(decimalToProb(d) * 10000) / 10000,
  };
}

/** JSON has no Infinity, so an unbounded Kelly bound travels as null + a flag. */
function kellyArbPayload(
  m: number,
  v: number,
  l: number,
): Pick<VoidResult, "kelly_arb_fraction" | "kelly_arb_unbounded"> {
  const f = kellyArbFraction(m, v, l);
  const unbounded = !Number.isFinite(f);
  return {
    kelly_arb_fraction: unbounded ? null : Math.round(f * 10000) / 10000,
    kelly_arb_unbounded: unbounded,
  };
}

export function calcVoid(
  margin: number,
  voidRate: number,
  voidLoss: number,
  turnovers: number,
): VoidResult {
  const eff = marginAfterVoids(margin, voidRate, voidLoss);
  return {
    nominal_margin: margin,
    effective_margin: Math.round(eff * 1000000) / 1000000,
    edge_retained_pct: margin ? r2((100 * eff) / margin) : 0,
    ...kellyArbPayload(margin, voidRate, voidLoss),
    annualised_simple: Math.round(eff * turnovers * 10000) / 10000,
    annualised_compounded:
      Math.round((Math.pow(1 + eff, turnovers) - 1) * 10000) / 10000,
  };
}

/**
 * Re-run equal-profit allocation at a new total stake.
 *
 * Mirrors `sizing.resize`: prices are held at their already-realised fill
 * levels, so this is exact for reductions and optimistic above the depth
 * ceiling, which the caller flags.
 */
export function resizeLegs(
  legs: Array<{
    effective_decimal_odds: number;
    effective_price: number;
    price: number;
    venue: string;
    outcome: string;
  }>,
  newTotal: number,
  isDutchNo: boolean,
) {
  const eff = legs.map((l) => l.effective_decimal_odds);
  const stakes = equalProfitStakes(eff, newTotal).map(
    (s) => Math.floor(s * 100) / 100,
  );
  const contracts = legs.map((l, i) =>
    l.effective_price > 0 ? stakes[i] / l.effective_price : 0,
  );
  const total = stakes.reduce((s, x) => s + x, 0);

  const payoutIf: Record<string, number> = {};
  let worst: number | null = null;
  legs.forEach((leg, i) => {
    const gross = isDutchNo
      ? contracts.reduce((s, c, j) => (j === i ? s : s + c), 0)
      : contracts[i];
    payoutIf[`${leg.outcome} (${leg.venue})`] = r2(gross);
    const profit = gross - total;
    worst = worst === null ? profit : Math.min(worst, profit);
  });

  return {
    stakes: stakes.map(r2),
    contracts: contracts.map((c) => Math.round(c * 100) / 100),
    total_stake: r2(total),
    payout_if: payoutIf,
    worst_case_profit: r2(worst ?? 0),
    roi_pct: total ? Math.round((100 * (worst ?? 0) * 1000) / total) / 1000 : 0,
  };
}

/**
 * Monte-Carlo replay, mirroring `backtest.replay`.
 *
 * A voided leg leaves the rest of the set unhedged, costing `voidLoss` of that
 * stake instead of paying the margin. Seeded so the demo is reproducible.
 */
export function runBacktest(
  rows: Array<{ kind: string; net_margin: number; total_stake: number; venues: string[] }>,
  opts: {
    minMargin: number;
    maxMargin: number;
    voidRate: number;
    voidLoss: number;
    simulations: number;
  },
) {
  // Mirrors BacktestParams.venue_void_rates: keyed by kind AND by venue, worst
  // one wins. Cross-venue legs carry the most rulebook risk (Part I s9.2).
  const voidRateFor: Record<string, number> = {
    cross_venue: 0.05,
    sportsbook: 0.03,
  };

  const filtered = rows.filter(
    (r) => r.net_margin >= opts.minMargin && r.net_margin <= opts.maxMargin,
  );
  if (!filtered.length) return null;

  const stakes = filtered.map((r) => r.total_stake);
  const profits = filtered.map((r) => r.total_stake * r.net_margin);
  const voidRates = filtered.map((r) => {
    let rate = voidRateFor[r.kind] ?? opts.voidRate;
    // This loop used to ignore `v` and re-take max against the same global
    // rate every time, so per-venue rates were silently dropped and the demo
    // backtest disagreed with the engine's.
    for (const v of r.venues) {
      rate = Math.max(rate, voidRateFor[v] ?? opts.voidRate);
    }
    if (r.venues.length > 1) rate = 1 - (1 - rate) ** 2;
    return Math.min(rate, 0.9);
  });

  // Deterministic PRNG (mulberry32) so the demo shows stable numbers.
  let seed = 42;
  const rand = () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  const totals: number[] = [];
  for (let s = 0; s < opts.simulations; s++) {
    let run = 0;
    for (let i = 0; i < filtered.length; i++) {
      run += rand() < voidRates[i] ? -opts.voidLoss * stakes[i] : profits[i];
    }
    totals.push(run);
  }
  totals.sort((a, b) => a - b);

  const turnover = stakes.reduce((s, x) => s + x, 0);
  const naive = profits.reduce((s, x) => s + x, 0);
  const mean = totals.reduce((s, x) => s + x, 0) / totals.length;
  const avgMargin =
    filtered.reduce((s, r) => s + r.net_margin, 0) / filtered.length;
  const avgVoid = voidRates.reduce((s, x) => s + x, 0) / voidRates.length;

  // A single simulated path, for the equity curve.
  seed = 42;
  let equity = 0;
  const curve = filtered.map((r, i) => {
    equity += rand() < voidRates[i] ? -opts.voidLoss * stakes[i] : profits[i];
    return { at: String(i), equity: r2(equity), kind: r.kind };
  });

  const notes: string[] = [];
  const naiveYield = turnover ? naive / turnover : 0;
  const expYield = turnover ? mean / turnover : 0;
  if (naiveYield > 0 && expYield < naiveYield * 0.7) {
    notes.push(
      `Voids remove ${Math.round((1 - expYield / naiveYield) * 100)}% of the naive edge. Part I s13.3: this is the number that matters.`,
    );
  }
  const probLoss = totals.filter((t) => t < 0).length / totals.length;
  if (probLoss > 0.05) {
    notes.push(
      `${Math.round(probLoss * 100)}% of simulated runs finished negative. Arbitrage is only risk-free if every leg settles.`,
    );
  }

  return {
    n: filtered.length,
    turnover: r2(turnover),
    naive_profit: r2(naive),
    naive_yield: naiveYield,
    expected_profit: r2(mean),
    expected_yield: expYield,
    median_profit: r2(totals[Math.floor(totals.length / 2)]),
    p5_profit: r2(totals[Math.floor(0.05 * (totals.length - 1))]),
    p95_profit: r2(totals[Math.floor(0.95 * (totals.length - 1))]),
    stdev_profit: 0,
    worst_simulation: r2(totals[0]),
    best_simulation: r2(totals[totals.length - 1]),
    prob_loss: probLoss,
    avg_margin: avgMargin,
    effective_margin: marginAfterVoids(avgMargin, avgVoid, opts.voidLoss),
    voids_modelled: avgVoid,
    turnovers_per_year: 0,
    annualised_return: 0,
    by_kind: [],
    equity_curve: curve,
    notes,
  };
}
