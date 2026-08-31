"use client";

import {
  KIND_LABEL,
  money,
  pct,
  placeableLabel,
} from "@/lib/format";
import type { CSSProperties } from "react";

import type { Arb } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Countdown } from "./Countdown";
import { ConfidenceBar, FlagChip, VenueChip, ZoneChip, activatable } from "./ui";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function ArbTable({
  arbs,
  onSelect,
  onPlace,
  selectedId,
}: {
  arbs: Arb[];
  onSelect: (arb: Arb) => void;
  onPlace?: (arb: Arb) => void;
  selectedId?: string | null;
}) {
  return (
    <div className="scroll-x">
      {/* `sticky-head` keeps the column names in view: this table runs to
          hundreds of rows and a numeric column with no header is unreadable. */}
      <Table className="w-full border-collapse text-[12.5px]">
        <TableHeader className="sticky-head">
          <TableRow className="hover:bg-transparent">
            <TableHead>Opportunity</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Venues</TableHead>
            <TableHead>Placeable from</TableHead>
            <TableHead className="text-right">Net margin</TableHead>
            <TableHead className="text-right">Stake</TableHead>
            <TableHead className="text-right">Profit</TableHead>
            <TableHead className="text-right">Max size</TableHead>
            <TableHead>Confidence</TableHead>
            <TableHead>Risks</TableHead>
            <TableHead className="text-right">Closes</TableHead>
            {onPlace && <TableHead className="text-center">Action</TableHead>}
          </TableRow>
        </TableHeader>
        {/* `stagger` reads --i off each row, so the cascade is one CSS rule
            rather than a delay computed per row in JS. Only the first screenful
            is staggered -- rows below the fold have finished animating long
            before anyone scrolls to them, and delaying them further just makes
            a long table feel slow to settle. */}
        <TableBody className="stagger">
          {arbs.map((a, i) => (
            <TableRow
              key={a.id}
              style={{ "--i": i } as CSSProperties}
              className={cn(
                "row-action",
                selectedId === a.id && "bg-brand-soft",
              )}
              aria-current={selectedId === a.id ? "true" : undefined}
              {...activatable(() => onSelect(a))}
            >
              <TableCell className="max-w-[360px]">
                <div className="truncate font-medium text-foreground" title={a.title}>
                  {a.title}
                </div>
                <div
                  className="text-xs truncate mt-0.5 text-faint"
                >
                  {a.legs
                    .map((l) => `${l.outcome} @ ${l.price.toFixed(3)}`)
                    .join("  ·  ")}
                </div>
              </TableCell>
              <TableCell>
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">{KIND_LABEL[a.kind]}</span>
              </TableCell>
              <TableCell>
                <div className="flex gap-1 flex-wrap">
                  {a.venues.map((v) => (
                    <VenueChip key={v} venue={v} />
                  ))}
                </div>
              </TableCell>
              <TableCell>
                <div className="flex flex-col gap-0.5">
                  <ZoneChip zone={a.zone} short />
                  <span className="text-xs text-faint">
                    {placeableLabel(a.placeable_from)}
                  </span>
                </div>
              </TableCell>
              <TableCell className="num text-right font-semibold">
                {pct(a.net_margin)}
                {a.margin > a.net_margin + 0.0005 && (
                  <div
                    className="text-[10px] font-normal text-faint"
                    title="Gross margin before venue fees and slippage"
                  >
                    {pct(a.margin)} gross
                  </div>
                )}
              </TableCell>
              <TableCell className="num text-right">
                {money(a.total_stake, a.currency, 0)}
              </TableCell>
              <TableCell
                className={`num text-right font-semibold ${
                  a.worst_case_profit >= 0 ? "text-positive" : "text-danger"
                }`}
                title={
                  a.strategy === "directional"
                    ? "Worst case: the full stake, lost if the bet is wrong -- not a guaranteed profit"
                    : undefined
                }
              >
                {money(a.worst_case_profit, a.currency)}
              </TableCell>
              <TableCell
                className="num text-right text-muted-foreground"
                title="Total stake the visible order-book depth can absorb"
              >
                {money(a.max_stake_available, a.currency, 0)}
              </TableCell>
              <TableCell>
                <ConfidenceBar value={a.confidence} />
              </TableCell>
              <TableCell className="max-w-[170px]">
                <div className="flex gap-1 flex-wrap">
                  {a.flags.slice(0, 2).map((f) => (
                    <FlagChip key={f} flag={f} />
                  ))}
                  {a.flags.length > 2 && (
                    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">+{a.flags.length - 2}</span>
                  )}
                  {a.flags.length === 0 && (
                    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-positive-soft text-positive">Clean</span>
                  )}
                </div>
              </TableCell>
              <TableCell
                className="num text-right text-muted-foreground"
              >
                <Countdown iso={a.close_time} showIcon />
              </TableCell>
              {onPlace && (
                <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="whitespace-nowrap px-[10px] py-[4px]"
                    onClick={(e) => {
                      e.stopPropagation();
                      onPlace(a);
                    }}
                  >
                    Place Bet
                  </button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Card layout for narrow screens, where a ten-column table is unreadable. */
export function ArbCards({
  arbs,
  onSelect,
  onPlace,
}: {
  arbs: Arb[];
  onSelect: (arb: Arb) => void;
  onPlace?: (arb: Arb) => void;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      {arbs.map((a) => (
        <div
          key={a.id}
          className="row-action w-full rounded-lg border border-border bg-card p-3.5 text-left shadow-sm"
          {...activatable(() => onSelect(a))}
        >
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="font-medium text-[13px] leading-snug">{a.title}</div>
            <div
              className="tabular text-base font-semibold shrink-0 text-foreground"
            >
              {pct(a.net_margin)}
            </div>
          </div>
          <div className="flex flex-wrap gap-1 mb-2.5">
            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">{KIND_LABEL[a.kind]}</span>
            {a.venues.map((v) => (
              <VenueChip key={v} venue={v} />
            ))}
            <ZoneChip zone={a.zone} short />
          </div>
          <div className="flex flex-col gap-1 mb-2.5">
            {a.legs.map((l) => (
              <div
                key={`${l.venue}:${l.market_id}:${l.outcome}`}
                className="flex justify-between text-xs"
              >
                <span className="truncate pr-2 text-muted-foreground">
                  {l.outcome}
                </span>
                <span className="tabular shrink-0">
                  {l.price.toFixed(3)} · {money(l.stake, a.currency)}
                </span>
              </div>
            ))}
          </div>
          <div
            className="flex items-center justify-between pt-2.5 border-t border-border"
          >
            <span className="text-xs text-muted-foreground">
              {money(a.total_stake, a.currency, 0)} →{" "}
              <span
                className={`tabular font-semibold ${
                  a.worst_case_profit >= 0 ? "num-positive" : "num-negative"
                }`}
              >
                {money(a.worst_case_profit, a.currency)}
              </span>
            </span>
            <div className="flex items-center gap-2">
              <ConfidenceBar value={a.confidence} />
              {onPlace && (
                <Button size="sm" type="button" onClick={(e) => { e.stopPropagation(); onPlace(a); }} >
                  Place
                </Button>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
