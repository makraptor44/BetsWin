/**
 * API client.
 *
 * Requests go to a relative `/api/...` path, which `next.config.ts` rewrites to
 * the Python backend in development. That keeps the browser on one origin, so
 * there is no CORS preflight on every poll.
 */

import type {
  Analytics,
  Arb,
  ArbDetail,
  BacktestResult,
  ConvertResult,
  EngineConfig,
  EngineStatus,
  KellyResult,
  MarketRow,
  NearMiss,
  PlaceBetPayload,
  PlaceBetResult,
  PositionsResponse,
  ResizeResult,
  ResolvePayload,
  ResolveResult,
  SellBackPayload,
  SellBackResult,
  StakeCalcResult,
  UnwindQuoteResponse,
  VenueRegistry,
  VoidResult,
  ZoneKey,
} from "./types";

import {
  calcConvert as shimConvert,
  calcKelly as shimKelly,
  calcStakes as shimStakes,
  calcVoid as shimVoid,
  resizeLegs,
  runBacktest,
} from "./staticMath";

/**
 * Static-demo mode.
 *
 * When built for GitHub Pages there is no Python process to talk to, so reads
 * come from JSON captured off a real demo-mode engine and the pure-arithmetic
 * endpoints are computed in the browser. Set at build time; a normal `npm run
 * dev` or `npm run build` leaves it off and talks to the live backend.
 */
export const STATIC_DEMO = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const fixtureCache = new Map<string, unknown>();

async function fixture<T>(name: string): Promise<T> {
  if (fixtureCache.has(name)) return fixtureCache.get(name) as T;
  const res = await fetch(`${BASE_PATH}/demo/${name}.json`, { cache: "force-cache" });
  if (!res.ok) {
    throw new ApiError(`Demo data for "${name}" is missing from this build.`, 404);
  }
  const data = (await res.json()) as T;
  fixtureCache.set(name, data);
  return data;
}

/**
 * Shared secret for the endpoints that change something.
 *
 * NEXT_PUBLIC_* is inlined into the browser bundle, so this is not a secret
 * from anyone using the dashboard -- it is not meant to be. The security
 * boundary is the engine's loopback bind; this key is what lets you move it off
 * loopback on a trusted network without leaving the config and scanner-control
 * endpoints open to it.
 */
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "Cannot reach the arbitrage engine. Is the Python backend running on port 8000?",
      0,
    );
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

// ------------------------------------------------------------------ queries

export interface ArbFilters {
  kind?: string;
  venue?: string;
  zone?: string;
  category?: string;
  min_margin?: number;
  min_confidence?: number;
  max_hours_to_close?: number;
  search?: string;
  limit?: number;
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Client-side filtering, so the demo's filter controls still do something. */
function filterArbs(all: Arb[], f: ArbFilters): Arb[] {
  let out = all;
  if (f.kind) {
    const want = new Set(String(f.kind).split(",").map((s) => s.trim()));
    out = out.filter((a) => want.has(a.kind));
  }
  if (f.venue) {
    const want = new Set(String(f.venue).split(",").map((s) => s.trim()));
    out = out.filter((a) => a.venues.some((v) => want.has(v)));
  }
  if (f.zone) {
    const want = new Set(String(f.zone).split(",").map((s) => s.trim()));
    out = out.filter((a) => want.has(a.zone));
  }
  if (f.category) out = out.filter((a) => a.category === f.category);
  if (f.min_margin) out = out.filter((a) => a.net_margin >= f.min_margin!);
  if (f.min_confidence)
    out = out.filter((a) => a.confidence >= f.min_confidence!);
  if (f.max_hours_to_close !== undefined) {
    // The live backend honours this; the demo used to render the control and
    // then ignore it, so the same filter behaved differently in each mode.
    out = out.filter(
      (a) =>
        a.hours_to_close !== null &&
        a.hours_to_close !== undefined &&
        a.hours_to_close <= f.max_hours_to_close!,
    );
  }
  if (f.search) {
    const q = f.search.toLowerCase();
    out = out.filter((a) => a.title.toLowerCase().includes(q));
  }
  return out.slice(0, f.limit ?? 200);
}

const demoUnavailable = (what: string) =>
  Promise.reject(
    new ApiError(
      `${what} needs the Python engine running. This is the static demo — clone the repo and run ./start.sh to use it for real.`,
      501,
    ),
  );

export const api = {
  status: () =>
    STATIC_DEMO ? fixture<EngineStatus>("status") : request<EngineStatus>("/api/status"),

  config: () =>
    STATIC_DEMO ? fixture<EngineConfig>("config") : request<EngineConfig>("/api/config"),

  patchConfig: (patch: Partial<EngineConfig>) =>
    STATIC_DEMO
      ? demoUnavailable("Changing settings")
      : request<{ updated: Record<string, unknown>; config: EngineConfig }>(
          "/api/config",
          { method: "PATCH", body: JSON.stringify(patch) },
        ),

  arbs: async (filters: ArbFilters = {}) => {
    if (!STATIC_DEMO) {
      return request<{ count: number; total: number; arbs: Arb[]; generated_at: string }>(
        `/api/arbs${qs(filters as Record<string, unknown>)}`,
      );
    }
    const all = await fixture<{ arbs: Arb[]; generated_at: string }>("arbs");
    const arbs = filterArbs(all.arbs, filters);
    return {
      count: arbs.length,
      total: all.arbs.length,
      arbs,
      generated_at: all.generated_at,
    };
  },

  arb: (id: string) =>
    STATIC_DEMO ? fixture<ArbDetail>(`arb-${id}`) : request<ArbDetail>(`/api/arbs/${id}`),

  /** Books that did not cross. On a normal cycle this is the entire output. */
  nearMisses: async (zone?: string) => {
    type Res = {
      count: number;
      total: number;
      slack_bps: number;
      near_misses: NearMiss[];
    };
    if (!STATIC_DEMO) return request<Res>(`/api/near-misses${qs({ zone })}`);
    const all = await fixture<Res>("near-misses");
    if (!zone) return all;
    const want = new Set(zone.split(",").map((s) => s.trim()));
    const rows = all.near_misses.filter((n) => want.has(n.zone));
    return { ...all, count: rows.length, near_misses: rows };
  },

  /** The venue registry and the execution-zone pairing matrix. */
  venues: () =>
    STATIC_DEMO
      ? fixture<VenueRegistry>("venues")
      : request<VenueRegistry>("/api/venues"),

  resize: async (id: string, total_stake: number) => {
    if (!STATIC_DEMO) {
      return post<ResizeResult>(`/api/arbs/${id}/resize`, { total_stake });
    }
    const detail = await fixture<ArbDetail>(`arb-${id}`);
    const arb = detail.arb;
    const r = resizeLegs(arb.legs, total_stake, arb.kind === "dutch_no");
    return {
      total_stake: r.total_stake,
      legs: arb.legs.map((l, i) => ({
        ...l,
        stake: r.stakes[i],
        contracts: r.contracts[i],
      })),
      payout_if: r.payout_if,
      worst_case_profit: r.worst_case_profit,
      roi_pct: r.roi_pct,
      exceeds_depth: total_stake > arb.max_stake_available,
      max_stake_available: arb.max_stake_available,
      bankroll_cap: detail.maths.bankroll_cap,
    } satisfies ResizeResult;
  },

  logPlacement: (id: string, note?: string) =>
    STATIC_DEMO
      ? demoUnavailable("Logging a placement")
      : // The endpoint returns `legs_placed`; this said `legs_logged`, so the
        // typed field was always undefined.
        post<PlaceBetResult>(`/api/arbs/${id}/log-placement`, {
          confirmed: true,
          note,
        }),

  placeBet: (id: string, payload: PlaceBetPayload = { confirmed: true, retire: true }) =>
    STATIC_DEMO
      ? demoUnavailable("Placing a bet")
      : post<PlaceBetResult>(`/api/arbs/${id}/place`, payload),

  markets: async (params: Record<string, unknown> = {}) => {
    type Res = {
      count: number;
      total: number;
      markets: MarketRow[];
      categories: string[];
      venues: string[];
      zones: ZoneKey[];
    };
    if (!STATIC_DEMO) return request<Res>(`/api/markets${qs(params)}`);

    const all = await fixture<Res>("markets");
    let rows = all.markets;
    if (params.venue) rows = rows.filter((m) => m.venue === params.venue);
    if (params.zone) rows = rows.filter((m) => m.zone === params.zone);
    if (params.category) rows = rows.filter((m) => m.category === params.category);
    if (params.only_mutually_exclusive)
      rows = rows.filter((m) => m.mutually_exclusive);
    if (params.search) {
      const q = String(params.search).toLowerCase();
      rows = rows.filter((m) => m.title.toLowerCase().includes(q));
    }
    const keys: Record<string, (m: MarketRow) => number | string> = {
      volume: (m) => -m.volume_usd,
      liquidity: (m) => -m.liquidity_usd,
      book: (m) => m.best_book ?? 99,
      close: (m) => m.close_time ?? "9999",
    };
    // The backend constrains this with a regex on the query parameter; the
    // demo shim did not, so any unexpected value threw
    // "keys[sort] is not a function" out of the comparator.
    const requested = String(params.sort ?? "volume");
    const sort = requested in keys ? requested : "volume";
    rows = [...rows].sort((a, b) => {
      const ka = keys[sort](a);
      const kb = keys[sort](b);
      return ka < kb ? -1 : ka > kb ? 1 : 0;
    });
    return { ...all, count: rows.length, markets: rows };
  },

  analytics: (days = 30) =>
    STATIC_DEMO ? fixture<Analytics>("analytics") : request<Analytics>(`/api/analytics?days=${days}`),

  backtest: async (body: Record<string, unknown>) => {
    if (!STATIC_DEMO) return post<BacktestResult>("/api/backtest", body);
    const hist = await fixture<{ arbs: Array<Record<string, unknown>> }>("history");
    const rows = hist.arbs.map((r) => ({
      kind: String(r.kind),
      net_margin: Number(r.net_margin),
      total_stake: Number(r.total_stake),
      venues: (r.venues as string[]) ?? [],
    }));
    const result = runBacktest(rows, {
      minMargin: Number(body.min_margin ?? 0.005),
      maxMargin: Number(body.max_margin ?? 0.05),
      voidRate: Number(body.void_rate ?? 0.02),
      voidLoss: Number(body.void_loss ?? 0.3),
      simulations: Number(body.simulations ?? 600),
    });
    if (!result) {
      return { ...(await fixture<BacktestResult>("backtest")), n: 0, equity_curve: [] };
    }
    return result as BacktestResult;
  },

  sweep: (body: Record<string, unknown>) =>
    STATIC_DEMO
      ? demoUnavailable("The threshold sweep")
      : post<{ sweep: Array<Record<string, number>> }>("/api/backtest/sweep", body),

  history: (params: Record<string, unknown> = {}) =>
    STATIC_DEMO
      ? fixture<{ count: number; arbs: Array<Record<string, unknown>> }>("history")
      : request<{ count: number; arbs: Array<Record<string, unknown>> }>(
          `/api/history${qs(params)}`,
        ),

  positions: (settled?: boolean) =>
    STATIC_DEMO
      ? fixture<PositionsResponse>("positions")
      : request<PositionsResponse>(`/api/positions${settled !== undefined ? `?settled=${settled}` : ""}`),

  unwindQuote: (rowId: number) =>
    STATIC_DEMO
      ? demoUnavailable("Fetching unwind quote")
      : request<UnwindQuoteResponse>(`/api/positions/${rowId}/unwind-quote`),

  sellBackPosition: (rowId: number, payload: SellBackPayload = { confirmed: true }) =>
    STATIC_DEMO
      ? demoUnavailable("Selling back position")
      : post<SellBackResult>(`/api/positions/${rowId}/sell-back`, payload),

  resolvePosition: (rowId: number, payload: ResolvePayload = {}) =>
    STATIC_DEMO
      ? demoUnavailable("Resolving position")
      : post<ResolveResult>(`/api/positions/${rowId}/resolve`, payload),

  /**
   * Book a known realised P&L against a position.
   *
   * The field is `custom_pnl`: that is what /settle declares. This used to post
   * `realised_pnl`, which the endpoint quietly discarded before booking the
   * theoretical worst case instead and returning ok.
   */
  settlePosition: (rowId: number, realisedPnl: number) =>
    STATIC_DEMO
      ? demoUnavailable("Settling a position")
      : post<ResolveResult>(`/api/positions/${rowId}/settle`, {
          custom_pnl: realisedPnl,
        }),

  scanNow: () =>
    STATIC_DEMO
      ? demoUnavailable("Triggering a scan")
      : post<{ ok: boolean; new_arbs: number }>("/api/scanner/scan", {}),
  start: () =>
    STATIC_DEMO ? demoUnavailable("Starting the scanner") : post<{ ok: boolean }>("/api/scanner/start", {}),
  stop: () =>
    STATIC_DEMO ? demoUnavailable("Stopping the scanner") : post<{ ok: boolean }>("/api/scanner/stop", {}),
  resetBreaker: () =>
    STATIC_DEMO
      ? demoUnavailable("Resetting the breaker")
      : post<{ ok: boolean }>("/api/scanner/reset-breaker", {}),

  // The calculators are pure functions of their inputs, so they stay fully
  // interactive in the static demo rather than being frozen.
  calcStakes: (decimal_odds: number[], total_stake: number, round_to?: number) =>
    STATIC_DEMO
      ? Promise.resolve(shimStakes(decimal_odds, total_stake, round_to))
      : post<StakeCalcResult>("/api/calc/stakes", { decimal_odds, total_stake, round_to }),

  calcKelly: (probability: number, decimal_odds: number, fraction = 0.25) =>
    STATIC_DEMO
      ? Promise.resolve(shimKelly(probability, decimal_odds, fraction, 10000))
      : post<KellyResult>("/api/calc/kelly", { probability, decimal_odds, fraction }),

  calcConvert: (value: number, from_format: string) => {
    if (!STATIC_DEMO) {
      return post<ConvertResult>("/api/calc/convert", { value, from_format });
    }
    try {
      return Promise.resolve(shimConvert(value, from_format));
    } catch (e) {
      return Promise.reject(new ApiError((e as Error).message, 400));
    }
  },

  calcVoid: (
    margin: number,
    void_rate: number,
    void_loss: number,
    turnovers_per_year: number,
  ) =>
    STATIC_DEMO
      ? Promise.resolve(shimVoid(margin, void_rate, void_loss, turnovers_per_year))
      : post<VoidResult>("/api/calc/void-adjusted", {
          margin,
          void_rate,
          void_loss,
          turnovers_per_year,
        }),
};
