/** Mirrors the Pydantic models in `backend/arbengine/models.py`. */

export type ArbKind =
  | "binary_complement"
  | "dutch_yes"
  | "dutch_no"
  | "cross_venue"
  | "sportsbook";

export type RiskFlag =
  | "suspect_margin"
  | "thin_liquidity"
  | "wide_spread"
  | "stale_quote"
  | "cross_venue_rules"
  | "fuzzy_match"
  | "long_dated"
  | "near_resolution"
  | "fee_sensitive"
  | "rounding_exposure"
  | "single_jurisdiction";

export interface ArbLeg {
  venue: string;
  market_id: string;
  ticker: string | null;
  outcome: string;
  side: "YES" | "NO" | "BACK" | "LAY";
  price: number;
  effective_price: number;
  decimal_odds: number;
  effective_decimal_odds: number;
  stake: number;
  contracts: number;
  fee: number;
  size_available: number;
  url: string | null;
  event_title: string | null;
  payout: number;
  net_payout: number;
}

/** Execution zone: a set of venues one operator can reach from one location. */
export type ZoneKey =
  | "us_prediction"
  | "uk_exchange"
  | "us_sportsbook"
  | "unknown";

export interface Arb {
  id: string;
  kind: ArbKind;
  title: string;
  category: string;
  venues: string[];
  zone: ZoneKey;
  zone_label: string;
  currency: string;
  placeable_from: string[];
  market_key: string;
  legs: ArbLeg[];
  total_stake: number;
  book: number;
  margin: number;
  net_margin: number;
  profit: number;
  worst_case_profit: number;
  payout_if: Record<string, number>;
  max_stake_available: number;
  confidence: number;
  flags: RiskFlag[];
  notes: string[];
  detected_at: string;
  close_time: string | null;
  last_seen: string;
  is_suspect: boolean;
  roi_pct: number;
  hours_to_close: number | null;
}

export interface NearMiss {
  id: string;
  title: string;
  venue: string;
  zone: ZoneKey;
  category: string;
  kind: ArbKind;
  book: number;
  /** Basis points from crossing, after fees. Positive means it did not cross. */
  gap_bps: number;
  /** The same gap on quoted prices. The difference is what fees cost. */
  gap_bps_gross: number;
  best_outcome: string;
  outcomes: number;
  liquidity_usd: number;
  close_time: string | null;
  url: string | null;
  seen_at: string;
}

export interface ScanStats {
  started_at: string;
  finished_at: string | null;
  duration_seconds: number;
  events_scanned: number;
  markets_scanned: number;
  quotes_scanned: number;
  arbs_found: number;
  new_arbs: number;
  near_misses: number;
  tightest_gap_bps: number | null;
  by_venue: Record<string, number>;
  by_zone: Record<string, number>;
  cross_zone_rejected: number;
  errors: string[];
  breaker_tripped: boolean;
}

export interface EngineStatus {
  running: boolean;
  demo_mode: boolean;
  last_scan: ScanStats | null;
  next_scan_in: number;
  poll_interval: number;
  live_arbs: number;
  total_detected: number;
  uptime_seconds: number;
  sources: Record<string, boolean>;
  breaker_tripped: boolean;
  breaker_reason: string | null;
  zones: ZoneKey[];
  operator_jurisdiction: string;
  enforce_zone_pairing: boolean;
  near_misses: number;
}

export interface ZoneSummary {
  key: ZoneKey;
  label: string;
  currency: string;
  rationale: string;
  settlement: string;
  venues: string[];
  venue_labels: string[];
}

export interface VenueSummary {
  name: string;
  label: string;
  zone: ZoneKey;
  structure: "contract" | "exchange" | "book";
  currency: string;
  regulator: string;
  commission: number;
  jurisdictions: string[];
  excluded: string[];
  public_data: boolean;
  url: string;
  notes: string;
  live: boolean;
}

export interface VenuePair {
  a: string;
  b: string;
  allowed: boolean;
  reason: string;
  zone: ZoneKey;
  jurisdictions: string[];
  both_live: boolean;
}

export interface VenueRegistry {
  enforce_zone_pairing: boolean;
  operator_jurisdiction: string;
  zones: ZoneSummary[];
  zones_available: ZoneKey[];
  venues: VenueSummary[];
  pairs: VenuePair[];
  rejected_this_scan: string[];
}

export interface EngineConfig {
  bankroll: number;
  default_stake: number;
  min_arb_margin: number;
  max_arb_margin: number;
  suspect_margin: number;
  min_confidence: number;
  max_stake_fraction_per_event: number;
  poll_interval_seconds: number;
  alert_min_margin: number;
  alert_min_confidence: number;
  assumed_void_rate: number;
  assumed_void_loss: number;
  fuzzy_match_threshold: number;
  demo_mode: boolean;
  sources: Record<string, boolean>;
  telegram_enabled: boolean;
  kinds: ArbKind[];
  enforce_zone_pairing: boolean;
  operator_jurisdiction: string;
  near_miss_slack: number;
  smarkets_commission: number;
  betfair_commission: number;
}

export interface MarketOutcome {
  name: string;
  side: string;
  price: number;
  effective_price: number;
  decimal_odds: number;
  implied_pct: number;
  size_available: number;
  venue: string;
  url: string | null;
}

export interface MarketRow {
  id: string;
  venue: string;
  zone: ZoneKey;
  currency: string;
  title: string;
  category: string;
  mutually_exclusive: boolean;
  market_count: number;
  volume_usd: number;
  liquidity_usd: number;
  close_time: string | null;
  url: string | null;
  best_book: number | null;
  overround_pct: number | null;
  outcomes: MarketOutcome[];
}

export interface PayoutRow {
  outcome: string;
  venue: string;
  gross_return: number;
  total_stake: number;
  profit: number;
  roi_pct: number;
}

export interface ArbMaths {
  implied_probs: number[];
  book_quoted: number;
  book_effective: number;
  margin_gross: number;
  margin_net: number;
  vig_equivalent: number;
  void_rate: number;
  void_loss: number;
  margin_after_voids: number;
  kelly_arb_fraction: number;
  devig_fair_probs: number[];
  bankroll_cap: number;
}

export interface ArbDetail {
  arb: Arb;
  payout_matrix: PayoutRow[];
  maths: ArbMaths;
}

export interface ResizeResult {
  total_stake: number;
  legs: ArbLeg[];
  payout_if: Record<string, number>;
  worst_case_profit: number;
  roi_pct: number;
  exceeds_depth: boolean;
  max_stake_available: number;
  bankroll_cap: number;
}

export interface Analytics {
  stored: {
    window_days: number;
    total_detected: number;
    avg_margin: number;
    max_margin: number;
    avg_confidence: number;
    theoretical_turnover: number;
    theoretical_profit: number;
    settled_count: number;
    realised_pnl: number;
    by_kind: Array<{
      kind: string;
      n: number;
      avg_margin: number;
      profit: number;
    }>;
    by_venue: Record<string, number>;
    by_zone: Array<{
      zone: string;
      n: number;
      avg_margin: number;
      turnover: number;
      profit: number;
    }>;
    by_day: Array<{
      day: string;
      n: number;
      avg_margin: number;
      profit: number;
    }>;
  };
  margin_histogram: Array<{ from: number; to: number; count: number }>;
  recent_scans: Array<{
    started_at: string;
    duration: number;
    events_scanned: number;
    arbs_found: number;
    new_arbs: number;
  }>;
  zones: {
    active: ZoneKey[];
    enforced: boolean;
    operator_jurisdiction: string;
    cross_zone_rejected: number;
  };
  near_misses: NearMiss[];
  live: {
    count: number;
    by_kind: Record<string, number>;
    by_venue: Record<string, number>;
    by_zone: Record<string, number>;
    total_profit_available: number;
    total_stake_required: number;
    avg_margin: number;
    avg_confidence: number;
  };
}

export interface BacktestResult {
  n: number;
  turnover: number;
  naive_profit: number;
  naive_yield: number;
  expected_profit: number;
  expected_yield: number;
  median_profit: number;
  p5_profit: number;
  p95_profit: number;
  stdev_profit: number;
  worst_simulation: number;
  best_simulation: number;
  prob_loss: number;
  avg_margin: number;
  effective_margin: number;
  voids_modelled: number;
  turnovers_per_year: number;
  annualised_return: number;
  by_kind: Array<{
    kind: string;
    n: number;
    turnover: number;
    naive_profit: number;
    avg_margin: number;
    effective_margin: number;
    expected_profit: number;
    void_rate: number;
  }>;
  equity_curve: Array<{ at: string; equity: number; kind: string }>;
  notes: string[];
}

export interface StakeCalcResult {
  book: number;
  is_arbitrage: boolean;
  margin: number;
  overround_pct: number;
  vig_pct: number;
  implied_probs: number[];
  fair_probs: number[];
  stakes: number[];
  total_stake: number;
  payouts: number[];
  profit_by_outcome: number[];
  worst_case_profit: number;
  guaranteed_profit: number;
}

export interface KellyResult {
  edge: number;
  is_value_bet: boolean;
  kelly_fraction: number;
  kelly_stake: number;
  fractional_kelly: number;
  fractional_stake: number;
  fair_odds: number;
  bankroll: number;
}

export interface VoidResult {
  nominal_margin: number;
  effective_margin: number;
  edge_retained_pct: number;
  kelly_arb_fraction: number;
  annualised_simple: number;
  annualised_compounded: number;
}

export interface ConvertResult {
  decimal: number;
  american: number;
  probability: number;
  contract_price: number;
}

export interface PositionPlacement {
  id: number;
  arb_id: number;
  venue: string;
  market_id: string;
  outcome: string;
  side: string;
  requested_price: number;
  requested_stake: number;
  executed_price: number | null;
  executed_stake: number | null;
  external_ref: string | null;
  status: string;
  placed_at: string;
  note: string | null;
}

export interface PositionItem {
  id: number;
  arb_key: string;
  kind: ArbKind;
  title: string;
  category: string;
  venues: string[];
  zone: ZoneKey;
  currency: string;
  market_key: string;
  detected_at: string;
  last_seen: string;
  close_time: string | null;
  book: number;
  margin: number;
  net_margin: number;
  total_stake: number;
  profit: number;
  worst_case_profit: number;
  max_stake: number;
  confidence: number;
  flags: RiskFlag[];
  legs: ArbLeg[];
  placed: number;
  settled: number;
  realised_pnl: number | null;
  placements?: PositionPlacement[];
}

export interface PositionsResponse {
  count: number;
  total_active_stake: number;
  total_expected_profit: number;
  total_realised_pnl: number;
  positions: PositionItem[];
}

export interface PlaceBetPayload {
  confirmed: boolean;
  executed_prices?: number[];
  executed_stakes?: number[];
  note?: string;
  retire?: boolean;
}

export interface PlaceBetResult {
  ok: boolean;
  arb_row_id: number;
  legs_placed: number;
  message: string;
}

export interface UnwindLeg {
  venue: string;
  outcome: string;
  side: string;
  contracts: number;
  entry_price: number;
  current_bid: number;
  gross_proceeds: number;
  fee: number;
  net_proceeds: number;
  stake: number;
  pnl: number;
}

export interface UnwindQuoteResponse {
  row_id: number;
  title: string;
  total_stake: number;
  currency: string;
  total_proceeds: number;
  unwind_pnl: number;
  roi_pct: number;
  legs: UnwindLeg[];
}

export interface SellBackPayload {
  confirmed: boolean;
  custom_prices?: number[];
  note?: string;
}

export interface SellBackResult {
  ok: boolean;
  row_id: number;
  settlement_type: string;
  realised_pnl: number;
  total_proceeds: number;
  message: string;
}

export interface ResolvePayload {
  winning_outcome?: string;
  custom_pnl?: number;
  note?: string;
}

export interface ResolveResult {
  ok: boolean;
  row_id: number;
  settlement_type: string;
  winning_outcome?: string;
  realised_pnl: number;
  message: string;
}


