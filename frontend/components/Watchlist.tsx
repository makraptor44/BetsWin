"use client";

import { useMemo } from "react";

import { Card, EmptyState, SectionTitle, VenueChip, ZoneChip } from "@/components/ui";
import {
  KIND_LABEL,
  bps,
  compactNum,
  untilLabel,
  usdCompact,
} from "@/lib/format";
import type { ActivityEntry } from "@/lib/useEngine";
import type { NearMiss } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/**
 * The near-miss watchlist.
 *
 * The problem it solves: on a normal cycle the engine finds no arbitrage, and a
 * dashboard whose only live surface is an empty opportunities table looks
 * broken. It is not broken -- it scanned nine hundred events and every book was
 * correctly priced. This table is that work made visible: the tightest books on
 * the tape, how far each is from crossing, and how much of that distance is the
 * venue's fee rather than the market's spread.
 *
 * It is also the thing worth watching. A book 20 bps out is one repricing away
 * from being an opportunity; a book 400 bps out is not.
 */
export function Watchlist({
  rows,
  slackBps,
}: {
  rows: NearMiss[];
  slackBps?: number;
}) {
  const tightest = rows.length > 0 ? rows[0].gap_bps : null;

  return (
    <Card padded={false}>
      <div className="p-3.5 pb-0">
        <SectionTitle
          title="Watchlist — closest books"
          hint={
            rows.length === 0
              ? "Nothing on the tape is within reach of crossing."
              : `The ${rows.length} tightest books the scanner is holding${
                  slackBps ? `, within ${slackBps.toFixed(0)} bps of crossing` : ""
                }. Not opportunities — the ones that could become opportunities.`
          }
          action={
            tightest !== null ? (
              <div className="text-right">
                <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint">Tightest</div>
                <div className="tabular text-sm font-semibold">{bps(tightest)}</div>
              </div>
            ) : undefined
          }
        />
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon="≈"
          title="No book is close"
          body="Every market on the tape is priced comfortably wide of an arbitrage. That is the ordinary state of a liquid venue; the watchlist fills up as spreads tighten near resolution."
        />
      ) : (
        <div className="scroll-x">
          <Table className="w-full border-collapse text-[13px] mt-2">
            <TableHeader>
              <TableRow>
                <TableHead>Market</TableHead>
                <TableHead>Structure</TableHead>
                <TableHead>Venue</TableHead>
                <TableHead className="text-right">Gap to cross</TableHead>
                <TableHead className="text-right">Cost of fees</TableHead>
                <TableHead className="text-right">Book</TableHead>
                <TableHead className="text-right">Liquidity</TableHead>
                <TableHead className="text-right">Closes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((n) => (
                <WatchRow key={n.id} row={n} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}

function WatchRow({ row }: { row: NearMiss }) {
  // How much of the distance from crossing is the fee schedule rather than the
  // market. A book that crosses on quoted prices and misses on effective ones
  // is a fee problem, not a pricing problem, and it is worth saying which.
  const feeCost = row.gap_bps - row.gap_bps_gross;
  const feeKilled = row.gap_bps_gross < 0 && row.gap_bps >= 0;

  return (
    <TableRow>
      <TableCell>
        <div className="truncate max-w-[380px]" title={row.title}>
          {row.url ? (
            <a href={row.url} target="_blank" rel="noopener noreferrer">
              {row.title}
            </a>
          ) : (
            row.title
          )}
        </div>
        <div className="text-xs mt-0.5 text-faint">
          best leg {row.best_outcome} · {row.outcomes} outcomes
        </div>
      </TableCell>
      <TableCell>
        <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">{KIND_LABEL[row.kind]}</span>
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1.5 flex-wrap">
          <VenueChip venue={row.venue} />
          <ZoneChip zone={row.zone} short />
        </div>
      </TableCell>
      <TableCell className="tabular text-right">{bps(row.gap_bps)}</TableCell>
      <TableCell className={cn("tabular text-right", feeKilled && "text-caution")}>
        {feeCost > 0.5 ? bps(feeCost) : "—"}
        {feeKilled && (
          <div className="text-xs text-caution">
            crossed before fees
          </div>
        )}
      </TableCell>
      <TableCell className="tabular text-right">{row.book.toFixed(4)}</TableCell>
      <TableCell className="tabular text-right">
        {row.liquidity_usd > 0 ? usdCompact(row.liquidity_usd) : "—"}
      </TableCell>
      <TableCell className="tabular text-right">{untilLabel(row.close_time)}</TableCell>
    </TableRow>
  );
}

/**
 * The scan log.
 *
 * One line per cycle, pushed over the same socket that carries opportunities.
 * Its whole purpose is to be a heartbeat you can read: if the numbers move, the
 * engine is working, whatever the opportunities table says.
 */
export function ActivityFeed({ entries }: { entries: ActivityEntry[] }) {
  const summary = useMemo(() => {
    if (entries.length === 0) return null;
    const events = entries.reduce((s, e) => s + e.events, 0);
    const found = entries.reduce((s, e) => s + e.newArbs, 0);
    const secs = entries.reduce((s, e) => s + e.durationSeconds, 0);
    return { events, found, avg: secs / entries.length };
  }, [entries]);

  return (
    <Card padded={false}>
      <div className="p-3.5 pb-1">
        <SectionTitle
          title="Scan activity"
          hint={
            summary
              ? `${compactNum(summary.events)} events across ${entries.length} cycles, ${summary.found} new opportunities, ${summary.avg.toFixed(1)}s a cycle.`
              : "Waiting for the first cycle to complete."
          }
        />
      </div>

      {entries.length === 0 ? (
        <div className="px-3.5 pb-4">
          <div className="animate-pulse rounded-md bg-muted h-[28px]" />
        </div>
      ) : (
        <ol className="px-3.5 pb-3 list-none m-0">
          {entries.slice(0, 12).map((e, i) => (
            <li
              key={`${e.at}-${i}`}
              className="flex items-center gap-3 py-1.5 text-xs"
              style={{
                borderTop: i === 0 ? "none" : "1px solid var(--border)",
                opacity: i === 0 ? 1 : Math.max(0.45, 1 - i * 0.055),
              }}
            >
              <span
                className="tabular shrink-0 text-faint w-[62px]"
              >
                {new Date(e.at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              <span className="tabular shrink-0 w-[76px]">
                {compactNum(e.events)} events
              </span>
              <span
                className="tabular shrink-0"
                style={{
                  width: 74,
                  color: e.newArbs > 0 ? "var(--positive)" : "var(--muted-foreground)",
                }}
              >
                {e.newArbs > 0 ? `${e.newArbs} new arb${e.newArbs > 1 ? "s" : ""}` : "0 new"}
              </span>
              <span className="tabular shrink-0 text-muted-foreground w-[96px]">
                {e.tightestGapBps != null ? `${bps(e.tightestGapBps)} closest` : "—"}
              </span>
              <span className="tabular text-faint">
                {(e.durationSeconds ?? 0).toFixed(1)}s
              </span>
              {e.errors > 0 && (
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-caution-soft text-caution ml-auto">
                  {e.errors} feed error{e.errors > 1 ? "s" : ""}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
