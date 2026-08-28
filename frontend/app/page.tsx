"use client";

import { useMemo, useState } from "react";

import { ArbDetailPanel } from "@/components/ArbDetail";
import { ArbCards, ArbTable } from "@/components/ArbTable";
import { StatusBar } from "@/components/StatusBar";
import { Card, EmptyState, ErrorState, Stat } from "@/components/ui";
import { KIND_LABEL, pct, usd, usdCompact } from "@/lib/format";
import type { Arb, ArbKind } from "@/lib/types";
import { useEngine } from "@/lib/useEngine";

type SortKey = "margin" | "profit" | "confidence" | "closing" | "size";

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

  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<ArbKind | "all">("all");
  const [venue, setVenue] = useState<string>("all");
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
  }, [engine.arbs, search, kind, venue, minMargin, minConfidence, sort]);

  const totals = useMemo(() => {
    const profit = filtered.reduce((s, a) => s + a.worst_case_profit, 0);
    const stake = filtered.reduce((s, a) => s + a.total_stake, 0);
    const best = filtered.reduce((m, a) => Math.max(m, a.net_margin), 0);
    const clean = filtered.filter((a) => a.flags.length === 0).length;
    return { profit, stake, best, clean };
  }, [filtered]);

  const hasFilters =
    search.trim() !== "" ||
    kind !== "all" ||
    venue !== "all" ||
    minMargin > 0 ||
    minConfidence > 0;

  const clearFilters = () => {
    setSearch("");
    setKind("all");
    setVenue("all");
    setMinMargin(0);
    setMinConfidence(0);
  };

  return (
    <div className="flex flex-col gap-5">
      <StatusBar engine={engine} />

      {engine.error && (
        <ErrorState message={engine.error} onRetry={() => void engine.refresh()} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Live opportunities"
          value={filtered.length}
          sub={
            hasFilters
              ? `${engine.arbs.length} before filters`
              : `${totals.clean} with no risk flags`
          }
        />
        <Stat
          label="Profit available"
          value={usd(totals.profit)}
          sub={`on ${usdCompact(totals.stake)} of stake`}
          tone={totals.profit > 0 ? "positive" : undefined}
        />
        <Stat
          label="Best net margin"
          value={pct(totals.best)}
          sub="after fees and slippage"
        />
        <Stat
          label="Last scan"
          value={
            engine.status?.last_scan
              ? `${engine.status.last_scan.events_scanned}`
              : "—"
          }
          sub={
            engine.status?.last_scan
              ? `events in ${engine.status.last_scan.duration_seconds.toFixed(1)}s`
              : "waiting for first scan"
          }
        />
      </div>

      <Card padded={false}>
        <div
          className="p-3 flex flex-wrap items-end gap-2.5 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <div style={{ flex: "1 1 220px", minWidth: 180 }}>
            <label className="label" htmlFor="search">
              Search
            </label>
            <input
              id="search"
              className="input"
              placeholder="Market or outcome…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div style={{ width: 172 }}>
            <label className="label" htmlFor="kind">
              Type
            </label>
            <select
              id="kind"
              className="input"
              value={kind}
              onChange={(e) => setKind(e.target.value as ArbKind | "all")}
            >
              <option value="all">All types</option>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </div>

          <div style={{ width: 138 }}>
            <label className="label" htmlFor="venue">
              Venue
            </label>
            <select
              id="venue"
              className="input"
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
            >
              <option value="all">All venues</option>
              {venues.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>

          <div style={{ width: 118 }}>
            <label className="label" htmlFor="minmargin">
              Min margin %
            </label>
            <input
              id="minmargin"
              className="input mono"
              type="number"
              step="0.1"
              min="0"
              value={minMargin || ""}
              placeholder="0.0"
              onChange={(e) => setMinMargin(Number(e.target.value) || 0)}
            />
          </div>

          <div style={{ width: 118 }}>
            <label className="label" htmlFor="minconf">
              Min confidence
            </label>
            <input
              id="minconf"
              className="input mono"
              type="number"
              step="5"
              min="0"
              max="100"
              value={minConfidence || ""}
              placeholder="0"
              onChange={(e) => setMinConfidence(Number(e.target.value) || 0)}
            />
          </div>

          <div style={{ width: 160 }}>
            <label className="label" htmlFor="sort">
              Sort by
            </label>
            <select
              id="sort"
              className="input"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {hasFilters && (
            <button className="btn btn-sm" onClick={clearFilters}>
              Clear
            </button>
          )}
        </div>

        {filtered.length === 0 ? (
          hasFilters ? (
            <EmptyState
              icon="⌕"
              title="Nothing matches these filters"
              body="Loosen the margin or confidence floor, or clear the filters to see everything the scanner currently holds."
              action={
                <button className="btn btn-sm" onClick={clearFilters}>
                  Clear filters
                </button>
              }
            />
          ) : (
            <EmptyState
              icon="○"
              title="No arbitrage right now"
              body="This is the normal state of a reasonably efficient market. The scanner keeps polling; opportunities appear here the moment a book crosses, and usually last seconds to minutes."
              action={
                engine.isStaticDemo ? undefined : (
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => void engine.scanNow()}
                    disabled={engine.scanning}
                  >
                    {engine.scanning ? "Scanning…" : "Scan now"}
                  </button>
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
                selectedId={selected?.id}
              />
            </div>
            <div className="lg:hidden p-3">
              <ArbCards arbs={filtered} onSelect={setSelected} />
            </div>
          </>
        )}
      </Card>

      {selected && (
        <ArbDetailPanel arb={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
