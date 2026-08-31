"use client";

import { useMemo, useState } from "react";

import {
  activatable,
  Card,
  EmptyState,
  ErrorState,
  Skeleton,
  Stat,
  VenueChip,
  ZoneChip,
  NativeSelect,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ZONE_LABEL, compactNum, num, usdCompact } from "@/lib/format";
import type { MarketRow, ZoneKey } from "@/lib/types";
import { useAsync } from "@/lib/useEngine";
import { Countdown } from "@/components/Countdown";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Sort = "volume" | "liquidity" | "book" | "close";

export default function MarketsPage() {
  const [venue, setVenue] = useState("all");
  const [zone, setZone] = useState<ZoneKey | "all">("all");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("volume");
  const [onlyME, setOnlyME] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, loading, error, reload } = useAsync(
    () =>
      api.markets({
        venue: venue === "all" ? undefined : venue,
        zone: zone === "all" ? undefined : zone,
        category: category === "all" ? undefined : category,
        search: search || undefined,
        only_mutually_exclusive: onlyME || undefined,
        sort,
        limit: 300,
      }),
    [venue, zone, category, search, sort, onlyME],
  );

  // Memoised so the summary below actually caches: a fresh [] literal each
  // render invalidated it every time.
  const rows = useMemo(() => data?.markets ?? [], [data]);

  const summary = useMemo(() => {
    if (!rows.length) return null;
    const withBook = rows.filter((r) => r.best_book !== null);
    const tightest = withBook.reduce<MarketRow | null>(
      (best, r) => (!best || (r.best_book ?? 9) < (best.best_book ?? 9) ? r : best),
      null,
    );
    const avgOverround =
      withBook.reduce((s, r) => s + (r.overround_pct ?? 0), 0) /
      (withBook.length || 1);
    return {
      volume: rows.reduce((s, r) => s + r.volume_usd, 0),
      liquidity: rows.reduce((s, r) => s + r.liquidity_usd, 0),
      tightest,
      avgOverround,
    };
  }, [rows]);

  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">Markets</h1>
        <p className="text-sm mt-0.5 text-muted-foreground">
          The normalised tape the detectors actually see. &ldquo;Book&rdquo; is the
          sum of implied probabilities across a market&apos;s outcomes — below
          1.0000 is an arbitrage, and how far above it sits is the venue&apos;s
          effective margin.
        </p>
      </header>

      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Markets" value={data?.total ?? 0} sub="matching filters" />
          <Stat label="Total volume" value={usdCompact(summary.volume)} sub="lifetime traded" />
          <Stat
            label="Resting liquidity"
            value={usdCompact(summary.liquidity)}
            sub="across all books"
          />
          <Stat
            label="Avg overround"
            value={`${summary.avgOverround.toFixed(2)}%`}
            sub="the cost of crossing both sides"
          />
        </div>
      )}

      <Card padded={false}>
        <div
          className="p-3 flex flex-wrap items-end gap-2.5 border-b border-border"
        >
          <div className="min-w-[180px] flex-[1_1_220px]">
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint" htmlFor="msearch">
              Search
            </label>
            <Input id="msearch" placeholder="Market title…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {(data?.zones?.length ?? 0) > 1 && (
            <div className="w-[176px]">
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint" htmlFor="mzone">
                Execution zone
              </label>
              <NativeSelect id="mzone" value={zone} onChange={(e) => setZone(e.target.value as ZoneKey | "all")} >
                <option value="all">All zones</option>
                {(data?.zones ?? []).map((z) => (
                  <option key={z} value={z}>
                    {ZONE_LABEL[z] ?? z}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
          <div className="w-[150px]">
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint" htmlFor="mvenue">
              Venue
            </label>
            <NativeSelect id="mvenue" value={venue} onChange={(e) => setVenue(e.target.value)} >
              <option value="all">All venues</option>
              {(data?.venues ?? []).map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="w-[160px]">
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint" htmlFor="mcat">
              Category
            </label>
            <NativeSelect id="mcat" value={category} onChange={(e) => setCategory(e.target.value)} >
              <option value="all">All categories</option>
              {(data?.categories ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="w-[168px]">
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint" htmlFor="msort">
              Sort by
            </label>
            <NativeSelect id="msort" value={sort} onChange={(e) => setSort(e.target.value as Sort)} >
              <option value="volume">Volume</option>
              <option value="liquidity">Liquidity</option>
              <option value="book">Tightest book</option>
              <option value="close">Closing soonest</option>
            </NativeSelect>
          </div>
          <label
            className="flex items-center gap-2 text-xs cursor-pointer pb-2 text-muted-foreground"
          >
            <input
              type="checkbox"
              checked={onlyME}
              onChange={(e) => setOnlyME(e.target.checked)}
              className="accent-brand"
            />
            Multi-outcome only
          </label>
        </div>

        {loading && <Skeleton rows={8} />}
        {error && (
          <div className="p-4">
            <ErrorState message={error} onRetry={reload} />
          </div>
        )}

        {!loading && !error && rows.length === 0 && (
          <EmptyState
            icon="⌕"
            title="No markets match"
            body="Adjust the filters, or wait for the scanner's first cycle to populate the tape."
          />
        )}

        {!loading && rows.length > 0 && (
          <div className="scroll-x">
            <Table className="w-full border-collapse text-[13px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Market</TableHead>
                  <TableHead>Venue</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Outcomes</TableHead>
                  <TableHead className="text-right">Book</TableHead>
                  <TableHead className="text-right">Overround</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Liquidity</TableHead>
                  <TableHead className="text-right">Closes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((m) => (
                  <MarketRowView
                    key={m.id}
                    market={m}
                    expanded={expanded === m.id}
                    onToggle={() =>
                      setExpanded((cur) => (cur === m.id ? null : m.id))
                    }
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}

function MarketRowView({
  market: m,
  expanded,
  onToggle,
}: {
  market: MarketRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isArb = m.best_book !== null && m.best_book < 1;
  return (
    <>
      <TableRow
        className="row-action"
        aria-expanded={expanded}
        {...activatable(onToggle)}
      >
        <TableCell className="max-w-[400px]">
          <div className="flex items-center gap-1.5">
            <span className="text-faint text-[10px]"
              aria-hidden
            >
              {expanded ? "▼" : "▶"}
            </span>
            <span className="font-medium truncate" title={m.title}>
              {m.title}
            </span>
            {m.mutually_exclusive && (
              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground shrink-0" title="Outcomes are mutually exclusive and exhaustive">
                ME
              </span>
            )}
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5 flex-wrap">
            <VenueChip venue={m.venue} />
            <ZoneChip zone={m.zone} short />
          </div>
        </TableCell>
        <TableCell className="text-muted-foreground">{m.category}</TableCell>
        <TableCell className="tabular text-right">
          {m.market_count}
        </TableCell>
        <TableCell
          className="tabular"
          style={{
            textAlign: "right",
            fontWeight: isArb ? 600 : 400,
            color: isArb ? "var(--positive)" : "var(--foreground)",
          }}
        >
          {m.best_book !== null ? m.best_book.toFixed(4) : "—"}
        </TableCell>
        <TableCell
          className="tabular text-right text-muted-foreground"
        >
          {m.overround_pct !== null ? `${m.overround_pct.toFixed(2)}%` : "—"}
        </TableCell>
        <TableCell className="tabular text-right">
          {usdCompact(m.volume_usd)}
        </TableCell>
        <TableCell className="tabular text-right text-muted-foreground">
          {usdCompact(m.liquidity_usd)}
        </TableCell>
        <TableCell className="tabular text-right text-muted-foreground">
          <Countdown iso={m.close_time} />
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell className="bg-muted p-0" colSpan={9}>
            <div className="p-3.5">
              <div className="flex items-center justify-between mb-2.5">
                <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint m-0">
                  Best price on each outcome
                </span>
                {m.url && (
                  <a
                    className="btn btn-sm"
                    href={m.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open on {m.venue} ↗
                  </a>
                )}
              </div>
              <div className="grid gap-1.5 grid-cols-[repeat(auto-fill,minmax(230px,1fr))]">
                {m.outcomes.map((o) => (
                  <div
                    key={o.name}
                    className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg border border-border bg-card"
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-medium truncate" title={o.name}>
                        {o.name}
                      </div>
                      <div className="text-[11px] text-faint">
                        {o.side} · {compactNum(o.size_available)} available
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="tabular text-xs font-semibold">
                        {o.price.toFixed(4)}
                      </div>
                      <div className="text-[11px] tabular text-faint">
                        {o.implied_pct.toFixed(1)}% · {num(o.decimal_odds, 2)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
