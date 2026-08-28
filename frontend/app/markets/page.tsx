"use client";

import { useMemo, useState } from "react";

import { Card, EmptyState, ErrorState, Skeleton, Stat, VenueChip } from "@/components/ui";
import { api } from "@/lib/api";
import { compactNum, num, untilLabel, usdCompact } from "@/lib/format";
import type { MarketRow } from "@/lib/types";
import { useAsync } from "@/lib/useEngine";

type Sort = "volume" | "liquidity" | "book" | "close";

export default function MarketsPage() {
  const [venue, setVenue] = useState("all");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("volume");
  const [onlyME, setOnlyME] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, loading, error, reload } = useAsync(
    () =>
      api.markets({
        venue: venue === "all" ? undefined : venue,
        category: category === "all" ? undefined : category,
        search: search || undefined,
        only_mutually_exclusive: onlyME || undefined,
        sort,
        limit: 300,
      }),
    [venue, category, search, sort, onlyME],
  );

  const rows = data?.markets ?? [];

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
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
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
          className="p-3 flex flex-wrap items-end gap-2.5 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <div style={{ flex: "1 1 220px", minWidth: 180 }}>
            <label className="label" htmlFor="msearch">
              Search
            </label>
            <input
              id="msearch"
              className="input"
              placeholder="Market title…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div style={{ width: 150 }}>
            <label className="label" htmlFor="mvenue">
              Venue
            </label>
            <select
              id="mvenue"
              className="input"
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
            >
              <option value="all">All venues</option>
              {(data?.venues ?? []).map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div style={{ width: 160 }}>
            <label className="label" htmlFor="mcat">
              Category
            </label>
            <select
              id="mcat"
              className="input"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="all">All categories</option>
              {(data?.categories ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div style={{ width: 168 }}>
            <label className="label" htmlFor="msort">
              Sort by
            </label>
            <select
              id="msort"
              className="input"
              value={sort}
              onChange={(e) => setSort(e.target.value as Sort)}
            >
              <option value="volume">Volume</option>
              <option value="liquidity">Liquidity</option>
              <option value="book">Tightest book</option>
              <option value="close">Closing soonest</option>
            </select>
          </div>
          <label
            className="flex items-center gap-2 text-xs cursor-pointer pb-2"
            style={{ color: "var(--text-muted)" }}
          >
            <input
              type="checkbox"
              checked={onlyME}
              onChange={(e) => setOnlyME(e.target.checked)}
              style={{ accentColor: "var(--accent)" }}
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
            <table className="data">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Venue</th>
                  <th>Category</th>
                  <th style={{ textAlign: "right" }}>Outcomes</th>
                  <th style={{ textAlign: "right" }}>Book</th>
                  <th style={{ textAlign: "right" }}>Overround</th>
                  <th style={{ textAlign: "right" }}>Volume</th>
                  <th style={{ textAlign: "right" }}>Liquidity</th>
                  <th style={{ textAlign: "right" }}>Closes</th>
                </tr>
              </thead>
              <tbody>
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
              </tbody>
            </table>
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
      <tr className="clickable" onClick={onToggle}>
        <td style={{ maxWidth: 400 }}>
          <div className="flex items-center gap-1.5">
            <span
              style={{ color: "var(--text-faint)", fontSize: 10 }}
              aria-hidden
            >
              {expanded ? "▼" : "▶"}
            </span>
            <span className="font-medium truncate" title={m.title}>
              {m.title}
            </span>
            {m.mutually_exclusive && (
              <span className="chip shrink-0" title="Outcomes are mutually exclusive and exhaustive">
                ME
              </span>
            )}
          </div>
        </td>
        <td>
          <VenueChip venue={m.venue} />
        </td>
        <td style={{ color: "var(--text-muted)" }}>{m.category}</td>
        <td className="mono" style={{ textAlign: "right" }}>
          {m.market_count}
        </td>
        <td
          className="mono"
          style={{
            textAlign: "right",
            fontWeight: isArb ? 600 : 400,
            color: isArb ? "var(--positive)" : "var(--text)",
          }}
        >
          {m.best_book !== null ? m.best_book.toFixed(4) : "—"}
        </td>
        <td
          className="mono"
          style={{ textAlign: "right", color: "var(--text-muted)" }}
        >
          {m.overround_pct !== null ? `${m.overround_pct.toFixed(2)}%` : "—"}
        </td>
        <td className="mono" style={{ textAlign: "right" }}>
          {usdCompact(m.volume_usd)}
        </td>
        <td className="mono" style={{ textAlign: "right", color: "var(--text-muted)" }}>
          {usdCompact(m.liquidity_usd)}
        </td>
        <td className="mono" style={{ textAlign: "right", color: "var(--text-muted)" }}>
          {untilLabel(m.close_time)}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={9} style={{ background: "var(--bg-sunken)", padding: 0 }}>
            <div className="p-3.5">
              <div className="flex items-center justify-between mb-2.5">
                <span className="label" style={{ margin: 0 }}>
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
              <div className="grid gap-1.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
                {m.outcomes.map((o, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg"
                    style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-medium truncate" title={o.name}>
                        {o.name}
                      </div>
                      <div className="text-[11px]" style={{ color: "var(--text-faint)" }}>
                        {o.side} · {compactNum(o.size_available)} available
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }} className="shrink-0">
                      <div className="mono text-xs font-semibold">
                        {o.price.toFixed(4)}
                      </div>
                      <div className="text-[11px] mono" style={{ color: "var(--text-faint)" }}>
                        {o.implied_pct.toFixed(1)}% · {num(o.decimal_odds, 2)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
