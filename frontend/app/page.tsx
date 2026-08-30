"use client";

import type { CSSProperties } from "react";
import { useMemo, useState } from "react";

import { ArbDetailPanel } from "@/components/ArbDetail";
import { ArbCards, ArbTable } from "@/components/ArbTable";
import { PlaceBetModal } from "@/components/PlaceBetModal";
import { StatusBar } from "@/components/StatusBar";
import { ActivityFeed, Watchlist } from "@/components/Watchlist";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, EmptyState, ErrorState, Stat,
  NativeSelect,
} from "@/components/ui";
import { KIND_LABEL, ZONE_LABEL, pct, usd, usdCompact } from "@/lib/format";
import type { Arb, ArbKind, ZoneKey } from "@/lib/types";
import { useEngine } from "@/lib/useEngine";

type SortKey = "margin" | "profit" | "confidence" | "closing" | "size";

/** One label treatment for the whole filter bar. Repeating the class list per
 *  field is how six fields end up with four different labels. */
const LABEL =
  "mb-1.5 block text-[10.5px] font-semibold uppercase tracking-[0.075em] text-faint";

const SORTS: Array<{ key: SortKey; label: string }> = [
  { key: "margin", label: "Net margin" },
  { key: "profit", label: "Profit" },
  { key: "confidence", label: "Confidence" },
  { key: "size", label: "Max size" },
  { key: "closing", label: "Closing soonest" },
];

export default function OpportunitiesPage() {
  const engine = useEngine();
  const [selected, setSelected] = useState<Arb | null>(null);
  const [placingArb, setPlacingArb] = useState<Arb | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<ArbKind | "all">("all");
  const [venue, setVenue] = useState<string>("all");
  // Execution zone: which set of venues you can actually place from. Filtering
  // by it is how an operator in one country stops looking at trades that need
  // an account in another.
  const [zone, setZone] = useState<ZoneKey | "all">("all");
  const [minMargin, setMinMargin] = useState(0);
  const [minConfidence, setMinConfidence] = useState(0);
  const [sort, setSort] = useState<SortKey>("margin");

  const venues = useMemo(
    () => Array.from(new Set(engine.arbs.flatMap((a) => a.venues))).sort(),
    [engine.arbs],
  );

  const kinds = useMemo(
    () => Array.from(new Set(engine.arbs.map((a) => a.kind))).sort(),
    [engine.arbs],
  );

  const zones = useMemo(() => {
    const fromArbs = engine.arbs.map((a) => a.zone);
    const fromEngine = engine.status?.zones ?? [];
    return Array.from(new Set([...fromEngine, ...fromArbs])).filter(
      (z): z is ZoneKey => Boolean(z) && z !== "unknown",
    );
  }, [engine.arbs, engine.status]);

  const watchlist = useMemo(
    () =>
      zone === "all"
        ? engine.nearMisses
        : engine.nearMisses.filter((n) => n.zone === zone),
    [engine.nearMisses, zone],
  );

  const filtered = useMemo(() => {
    let out = engine.arbs;
    if (search.trim()) {
      const q = search.toLowerCase();
      out = out.filter(
        (a) =>
          a.title.toLowerCase().includes(q) ||
          a.legs.some((l) => l.outcome.toLowerCase().includes(q)),
      );
    }
    if (kind !== "all") out = out.filter((a) => a.kind === kind);
    if (zone !== "all") out = out.filter((a) => a.zone === zone);
    if (venue !== "all") out = out.filter((a) => a.venues.includes(venue));
    if (minMargin > 0) out = out.filter((a) => a.net_margin * 100 >= minMargin);
    if (minConfidence > 0) out = out.filter((a) => a.confidence >= minConfidence);

    const sorted = [...out];
    sorted.sort((a, b) => {
      switch (sort) {
        case "profit":
          return b.worst_case_profit - a.worst_case_profit;
        case "confidence":
          return b.confidence - a.confidence;
        case "size":
          return b.max_stake_available - a.max_stake_available;
        case "closing":
          return (a.hours_to_close ?? 1e9) - (b.hours_to_close ?? 1e9);
        default:
          return b.net_margin - a.net_margin;
      }
    });
    return sorted;
  }, [engine.arbs, search, kind, zone, venue, minMargin, minConfidence, sort]);

  const totals = useMemo(() => {
    // An arbitrage's worst_case_profit is a guaranteed gain. A directional
    // position's is what it loses if the bet is wrong, so adding the two gives
    // a number that is neither -- one correlation row at -$156.46 was enough to
    // headline "Profit available: -$72.68" over $83.78 of real arbitrage.
    const arbs = filtered.filter((a) => a.strategy !== "directional");
    const directional = filtered.filter((a) => a.strategy === "directional");
    const profit = arbs.reduce((s, a) => s + a.worst_case_profit, 0);
    const directionalAtRisk = directional.reduce((s, a) => s + a.total_stake, 0);
    const stake = filtered.reduce((s, a) => s + a.total_stake, 0);
    const best = filtered.reduce((m, a) => Math.max(m, a.net_margin), 0);
    const clean = filtered.filter((a) => a.flags.length === 0).length;
    return {
      profit,
      stake,
      best,
      clean,
      directionalAtRisk,
      directionalCount: directional.length,
    };
  }, [filtered]);

  // The scan log is already in memory, oldest last. Reversed and trimmed it is
  // exactly the short history a sparkline wants -- no extra request, and no
  // separate history state to keep in sync with the tape.
  const trends = useMemo(() => {
    const recent = engine.activity.slice(0, 24).reverse();
    return {
      arbs: recent.map((a) => a.arbs),
      gaps: recent
        .map((a) => a.tightestGapBps)
        .filter((g): g is number => g !== null),
    };
  }, [engine.activity]);

  const hasFilters =
    search.trim() !== "" ||
    kind !== "all" ||
    zone !== "all" ||
    venue !== "all" ||
    minMargin > 0 ||
    minConfidence > 0;

  const clearFilters = () => {
    setSearch("");
    setKind("all");
    setZone("all");
    setVenue("all");
    setMinMargin(0);
    setMinConfidence(0);
  };

  const handleBetPlaced = (msg?: string) => {
    setPlacingArb(null);
    if (selected && placingArb && selected.id === placingArb.id) {
      setSelected(null);
    }
    setToast(msg || "Bet successfully placed! Live opportunities refreshed.");
    setTimeout(() => setToast(null), 5000);
    // Trigger immediate refresh of opportunities
    void engine.refresh();
    void engine.scanNow();
  };

  return (
    <div className="flex flex-col gap-4 sm:gap-5">
      <StatusBar engine={engine} />

      {toast && (
        // A tinted panel rather than a solid green bar. A full-bleed success
        // colour is the loudest thing on a page whose colour vocabulary is
        // otherwise reserved for risk.
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-lg border border-positive/30 bg-positive-soft px-3.5 py-3 text-xs font-medium text-positive"
          style={{ animation: "rise 180ms ease-out" }}
        >
          <div className="flex items-center gap-2.5">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M20 6 9 17l-5-5" />
            </svg>
            <span>{toast}</span>
          </div>
          <button
            type="button"
            className="rounded p-1 transition-opacity hover:opacity-60"
            onClick={() => setToast(null)}
            aria-label="Dismiss"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden>
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {engine.error && (
        <ErrorState message={engine.error} onRetry={() => void engine.refresh()} />
      )}

      <div className="stagger grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          style={{ "--i": 0 } as CSSProperties}
          label="Live opportunities"
          animate={filtered.length}
          format={(n) => String(Math.round(n))}
          value={filtered.length}
          trend={trends.arbs}
          sub={
            hasFilters
              ? `${engine.arbs.length} before filters`
              : `${totals.clean} with no risk flags`
          }
        />
        <Stat
          style={{ "--i": 1 } as CSSProperties}
          label="Guaranteed profit"
          animate={totals.profit}
          format={(n) => usd(n)}
          value={usd(totals.profit)}
          sub={
            totals.directionalCount > 0
              ? `plus ${usdCompact(totals.directionalAtRisk)} at risk in ${totals.directionalCount} directional`
              : `on ${usdCompact(totals.stake)} of stake`
          }
          tone={totals.profit > 0 ? "positive" : undefined}
        />
        <Stat
          style={{ "--i": 2 } as CSSProperties}
          label="Best net margin"
          animate={totals.best}
          format={(n) => pct(n)}
          value={pct(totals.best)}
          trend={trends.gaps}
          sub={totals.best > 0 ? "after all fees" : undefined}
        />
        <Stat
          style={{ "--i": 3 } as CSSProperties}
          label="Total stake"
          animate={totals.stake}
          format={(n) => usdCompact(n)}
          value={usdCompact(totals.stake)}
          sub="sized for visible depth"
        />
      </div>

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-hairline bg-muted/25 p-4">
          <div className="flex-1 min-w-[200px]">
            <label className={LABEL} htmlFor="search">
              Search
            </label>
            <Input id="search" className="w-full" type="search" placeholder="Filter by event, outcome or player…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>

          <div className="w-[148px]">
            <label className={LABEL} htmlFor="kind">
              Arb type
            </label>
            <NativeSelect id="kind" value={kind} onChange={(e) => setKind(e.target.value as ArbKind | "all")} >
              <option value="all">All types</option>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </NativeSelect>
          </div>

          {zones.length > 1 && (
            <div className="w-[186px]">
              <label className={LABEL} htmlFor="zone">
                Execution zone
              </label>
              <NativeSelect id="zone" value={zone} onChange={(e) => setZone(e.target.value as ZoneKey | "all")} title="Venues you can hold accounts on from one location, in one currency. Legs are never combined across zones." >
                <option value="all">All zones</option>
                {zones.map((z) => (
                  <option key={z} value={z}>
                    {ZONE_LABEL[z]}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}

          <div className="w-[138px]">
            <label className={LABEL} htmlFor="venue">
              Venue
            </label>
            <NativeSelect id="venue" value={venue} onChange={(e) => setVenue(e.target.value)} >
              <option value="all">All venues</option>
              {venues.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </NativeSelect>
          </div>

          <div className="w-[118px]">
            <label className={LABEL} htmlFor="minmargin">
              Min margin %
            </label>
            <Input id="minmargin" className="tabular" type="number" step="0.1" min="0" value={minMargin || ""} placeholder="0.0" onChange={(e) => setMinMargin(Number(e.target.value) || 0)} />
          </div>

          <div className="w-[118px]">
            <label className={LABEL} htmlFor="minconf">
              Min confidence
            </label>
            <Input id="minconf" className="tabular" type="number" step="5" min="0" max="100" value={minConfidence || ""} placeholder="0" onChange={(e) => setMinConfidence(Number(e.target.value) || 0)} />
          </div>

          <div className="w-[160px]">
            <label className={LABEL} htmlFor="sort">
              Sort by
            </label>
            <NativeSelect id="sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </NativeSelect>
          </div>

          {hasFilters && (
            <Button size="sm" variant="outline" onClick={clearFilters}>
              Clear
            </Button>
          )}
        </div>

        {filtered.length === 0 ? (
          hasFilters ? (
            <EmptyState
              icon="⌕"
              title="Nothing matches these filters"
              body="Loosen the margin or confidence floor, or clear the filters to see everything the scanner currently holds."
              action={
                <Button size="sm" variant="outline" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon="○"
              title="No arbitrage right now"
              body="This is the normal state of a reasonably efficient market, not a fault. The scan activity and watchlist below show what the engine is reading and how close the tightest books are; opportunities appear here the moment one crosses, and usually last seconds to minutes."
              action={
                engine.isStaticDemo ? undefined : (
                  <Button size="sm" onClick={() => void engine.scanNow()} disabled={engine.scanning} >
                    {engine.scanning ? "Scanning…" : "Scan now"}
                  </Button>
                )
              }
            />
          )
        ) : (
          <>
            <div className="hidden lg:block">
              <ArbTable
                arbs={filtered}
                onSelect={setSelected}
                onPlace={(arb) => setPlacingArb(arb)}
                selectedId={selected?.id}
              />
            </div>
            <div className="lg:hidden p-3">
              <ArbCards
                arbs={filtered}
                onSelect={setSelected}
                onPlace={(arb) => setPlacingArb(arb)}
              />
            </div>
          </>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-[1.6fr_1fr] gap-4">
        <Watchlist rows={watchlist} />
        <ActivityFeed entries={engine.activity} />
      </div>

      {selected && (
        <ArbDetailPanel
          arb={selected}
          onClose={() => setSelected(null)}
          onPlace={(arb) => setPlacingArb(arb)}
        />
      )}

      {placingArb && (
        <PlaceBetModal
          arb={placingArb}
          onClose={() => setPlacingArb(null)}
          onSuccess={handleBetPlaced}
        />
      )}
    </div>
  );
}
