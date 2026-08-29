import type { ArbKind, RiskFlag, ZoneKey } from "./types";

export const usd = (n: number, dp = 2) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });

export const usdCompact = (n: number) => {
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
};

export const pct = (n: number, dp = 2) => `${(n * 100).toFixed(dp)}%`;

export const num = (n: number, dp = 2) =>
  n.toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });

export const compactNum = (n: number) => {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
};

/** "3h 12m", "4d", "12m" -- compact enough for a dense table. */
export function untilLabel(iso: string | null): string {
  if (!iso) return "—";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "—";
  if (ms <= 0) return "closed";
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  const days = Math.floor(hrs / 24);
  if (days < 365) return `${days}d`;
  return `${(days / 365).toFixed(1)}y`;
}

export function agoLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const secs = Math.max(0, Math.floor(ms / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d ${hrs % 24}h`;
}

export const KIND_LABEL: Record<ArbKind, string> = {
  binary_complement: "Binary complement",
  dutch_yes: "Dutch book (buy all)",
  dutch_no: "Dutch book (fade all)",
  cross_venue: "Cross-venue",
  sportsbook: "Sportsbook",
  correlation: "Correlation edge",
};

export const KIND_BLURB: Record<ArbKind, string> = {
  binary_complement:
    "A single market whose YES and NO asks together cost less than the $1 they pay. Both legs settle under one rulebook, which makes this the cleanest structure available.",
  dutch_yes:
    "Every outcome of a mutually exclusive event bought at once for less than the $1 that exactly one of them will return.",
  dutch_no:
    "The NO side of every outcome. Exactly one outcome occurs, so n-1 legs settle at $1 — an arb when the NO prices sum to less than n-1.",
  cross_venue:
    "The same question priced on two venues: buy YES on the cheaper one and NO on the other. Confirm both resolve on identical criteria before staking.",
  sportsbook:
    "Best price on each outcome taken from different books, in the classic cross-bookmaker form.",
  correlation:
    "A joint-event contract priced against a correlation that diverges from a historical prior. NOT risk-free — a directional bet sized by fractional Kelly. The full stake is lost if it's wrong.",
};

export const FLAG_LABEL: Record<RiskFlag, string> = {
  suspect_margin: "Suspect margin",
  thin_liquidity: "Thin liquidity",
  wide_spread: "Wide spread",
  stale_quote: "Stale quote",
  cross_venue_rules: "Cross-venue rules",
  fuzzy_match: "Fuzzy match",
  long_dated: "Long dated",
  near_resolution: "Near resolution",
  fee_sensitive: "Fee sensitive",
  rounding_exposure: "Rounding exposure",
  single_jurisdiction: "One jurisdiction",
  statistical_edge: "Not risk-free",
};

/** Which flags are outright warnings versus things merely worth knowing. */
export const FLAG_SEVERITY: Record<RiskFlag, "danger" | "caution"> = {
  suspect_margin: "danger",
  fuzzy_match: "danger",
  cross_venue_rules: "caution",
  thin_liquidity: "caution",
  wide_spread: "caution",
  stale_quote: "caution",
  long_dated: "caution",
  near_resolution: "danger",
  fee_sensitive: "caution",
  rounding_exposure: "caution",
  single_jurisdiction: "caution",
  statistical_edge: "danger",
};

export const VENUE_LABEL: Record<string, string> = {
  polymarket: "Polymarket",
  kalshi: "Kalshi",
  sportsbook: "Sportsbooks",
  smarkets: "Smarkets",
  betfair: "Betfair",
  demo: "Demo",
};

export const ZONE_LABEL: Record<ZoneKey, string> = {
  us_prediction: "USD prediction markets",
  uk_exchange: "UK/EU exchanges",
  us_sportsbook: "US sportsbooks",
  unknown: "Unclassified",
};

/** Short form for a dense table cell. */
export const ZONE_SHORT: Record<ZoneKey, string> = {
  us_prediction: "USD contracts",
  uk_exchange: "UK exchanges",
  us_sportsbook: "US books",
  unknown: "—",
};

export const ZONE_CURRENCY: Record<ZoneKey, string> = {
  us_prediction: "USD",
  uk_exchange: "GBP",
  us_sportsbook: "USD",
  unknown: "",
};

/**
 * Where a trade can be placed from, in words.
 *
 * `["*"]` means both venues are broadly available; a short list means the
 * trade is location-specific and most operators cannot take it.
 */
export function placeableLabel(codes: string[]): string {
  if (codes.length === 0) return "Unknown";
  if (codes.includes("*")) return "Broadly available";
  if (codes.length <= 4) return codes.join(", ");
  return `${codes.slice(0, 3).join(", ")} +${codes.length - 3} more`;
}

/**
 * Basis points from crossing.
 *
 * Deliberately signed and never coloured green: a book 20 bps away is closer
 * than one 200 bps away, but neither is money, and the whole design principle
 * here is that only realised, placeable edge gets a positive colour.
 */
export const bps = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(0)} bps`;

export const money = (n: number, currency: string, dp = 2) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: currency || "USD",
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });

export function venueColor(venue: string): string {
  return `var(--venue-${venue}, var(--text-muted))`;
}

/**
 * Confidence colour. Note the deliberate asymmetry with margin: confidence is
 * green when high, but margin is NEVER coloured by size, because a large margin
 * is a warning sign rather than a prize (Part I s5.3).
 */
export function confidenceTone(c: number): "positive" | "caution" | "danger" {
  if (c >= 75) return "positive";
  if (c >= 50) return "caution";
  return "danger";
}
