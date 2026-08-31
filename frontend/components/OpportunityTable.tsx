"use client";

import { useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";

import { Countdown } from "@/components/Countdown";
import {
  ConfidenceBar,
  FlagChip,
  VenueChip,
  ZoneChip,
  activatable,
} from "@/components/ui";
import { KIND_LABEL, money, pct, placeableLabel } from "@/lib/format";
import type { Arb, ArbStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The opportunities table.
 *
 * Sorting lives in the table rather than in the page. It used to be a single
 * `SortKey` in page state driving a hand-written comparator, which meant the
 * only sortable columns were the five somebody had remembered to add to the
 * dropdown, the sort direction could not be reversed, and the column showing
 * the sort was not the column you clicked. Column definitions carry their own
 * accessor and comparator here, so every numeric column is sortable both ways
 * by construction and the header shows which one is active.
 */

const col = createColumnHelper<Arb>();

/** Sorts nulls last regardless of direction -- "no close time" is not "soonest". */
const nullsLast = (a: number | null, b: number | null) => {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
};

function SortIcon({ dir }: { dir: false | "asc" | "desc" }) {
  if (!dir) {
    return (
      <svg width="10" height="10" viewBox="0 0 24 24" className="opacity-0 transition-opacity group-hover:opacity-40" aria-hidden>
        <path d="M12 5v14M7 10l5-5 5 5" stroke="currentColor" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 24 24"
      className={cn("text-brand transition-transform", dir === "desc" && "rotate-180")}
      aria-hidden
    >
      <path d="M12 5v14M7 10l5-5 5 5" stroke="currentColor" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Lifecycle state, as a word rather than only a colour.
 *
 * Colour alone fails for anyone who cannot separate the hues, and this is the
 * field that says whether a row is actionable at all -- so the label carries
 * the meaning and the tint only reinforces it.
 */
const STATUS_STYLE: Record<ArbStatus, string> = {
  live: "bg-positive-soft text-positive",
  expiring: "bg-caution-soft text-caution",
  expired: "bg-neutral-soft text-faint",
  invalidated: "bg-danger-soft text-danger",
};

const STATUS_LABEL: Record<ArbStatus, string> = {
  live: "Live",
  expiring: "Expiring",
  expired: "Expired",
  invalidated: "Invalidated",
};

function StatusPill({ status }: { status: ArbStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold",
        STATUS_STYLE[status],
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-1.5 w-1.5 rounded-full bg-current",
          status === "live" && "animate-pulse",
        )}
      />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function OpportunityTable({
  arbs,
  selectedId,
  onSelect,
  onPlace,
}: {
  arbs: Arb[];
  selectedId?: string;
  onSelect: (a: Arb) => void;
  onPlace?: (a: Arb) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "net_margin", desc: true },
  ]);

  const columns = useMemo(
    () => [
      col.accessor("title", {
        header: "Opportunity",
        enableSorting: true,
        cell: (c) => (
          <div className="max-w-[340px]">
            <div className="truncate font-medium text-foreground" title={c.getValue()}>
              {c.getValue()}
            </div>
            <div className="mt-0.5 truncate text-[11px] text-faint">
              {c.row.original.legs
                .map((l) => `${l.outcome} @ ${l.price.toFixed(3)}`)
                .join(" · ")}
            </div>
          </div>
        ),
      }),
      col.accessor("kind", {
        header: "Type",
        cell: (c) => (
          <span className="inline-flex whitespace-nowrap rounded-[5px] bg-neutral-soft px-[7px] py-[2px] text-[11px] font-semibold text-muted-foreground">
            {KIND_LABEL[c.getValue()]}
          </span>
        ),
      }),
      col.display({
        id: "venues",
        header: "Venues",
        cell: (c) => (
          <div className="flex flex-wrap gap-1">
            {c.row.original.venues.map((v) => (
              <VenueChip key={v} venue={v} />
            ))}
          </div>
        ),
      }),
      col.display({
        id: "placeable",
        header: "Placeable from",
        cell: (c) => (
          <div className="flex flex-col gap-0.5">
            <ZoneChip zone={c.row.original.zone} short />
            <span className="text-[11px] text-faint">
              {placeableLabel(c.row.original.placeable_from)}
            </span>
          </div>
        ),
      }),
      col.accessor("net_margin", {
        header: "Net margin",
        meta: { align: "right" },
        cell: (c) => (
          <>
            <div className="font-semibold">{pct(c.getValue())}</div>
            {c.row.original.margin > c.getValue() + 0.0005 && (
              <div
                className="text-[10px] font-normal text-faint"
                title="Gross margin before venue fees and slippage"
              >
                {pct(c.row.original.margin)} gross
              </div>
            )}
          </>
        ),
      }),
      col.accessor("total_stake", {
        header: "Stake",
        meta: { align: "right" },
        cell: (c) => money(c.getValue(), c.row.original.currency, 0),
      }),
      col.accessor("worst_case_profit", {
        header: "Profit",
        meta: { align: "right" },
        cell: (c) => (
          <span
            className={cn(
              "font-semibold",
              c.getValue() >= 0 ? "text-positive" : "text-danger",
            )}
            title={
              c.row.original.strategy === "directional"
                ? "Worst case: the full stake, lost if the bet is wrong -- not a guaranteed profit"
                : undefined
            }
          >
            {money(c.getValue(), c.row.original.currency)}
          </span>
        ),
      }),
      col.accessor("max_stake_available", {
        header: "Max size",
        meta: { align: "right" },
        cell: (c) => (
          <span className="text-muted-foreground">
            {money(c.getValue(), c.row.original.currency, 0)}
          </span>
        ),
      }),
      col.accessor("confidence", {
        header: "Confidence",
        cell: (c) => <ConfidenceBar value={c.getValue()} />,
      }),
      col.display({
        id: "flags",
        header: "Risks",
        cell: (c) => {
          const flags = c.row.original.flags;
          return (
            <div className="flex max-w-[170px] flex-wrap gap-1">
              {flags.slice(0, 2).map((f) => (
                <FlagChip key={f} flag={f} />
              ))}
              {flags.length > 2 && (
                <span className="inline-flex rounded-[5px] bg-neutral-soft px-[7px] py-[2px] text-[11px] font-semibold text-muted-foreground">
                  +{flags.length - 2}
                </span>
              )}
              {flags.length === 0 && (
                <span className="inline-flex rounded-[5px] bg-positive-soft px-[7px] py-[2px] text-[11px] font-semibold text-positive">
                  Clean
                </span>
              )}
            </div>
          );
        },
      }),
      col.accessor((a) => a.seconds_to_expiry, {
        id: "expiry",
        header: "Expires",
        meta: { align: "right" },
        // Against expires_at, not the market close. The close is one of the two
        // bounds the engine derives the expiry from; the other is how stale the
        // quotes behind the price have gone, and on a live book that is usually
        // the binding one.
        sortingFn: (a, b) =>
          nullsLast(a.original.seconds_to_expiry, b.original.seconds_to_expiry),
        cell: (c) => <Countdown iso={c.row.original.expires_at} showIcon />,
      }),
      col.accessor("status", {
        header: "Status",
        cell: (c) => <StatusPill status={c.getValue()} />,
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: arbs,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    // Descending first on every column. Every sortable figure here -- margin,
    // profit, size, confidence -- is one where the interesting end is the top,
    // and an ascending first click puts the worst opportunity on screen.
    sortDescFirst: true,
    getRowId: (a) => a.id,
  });

  return (
    <div className="scroll-x">
      <table className="w-full border-collapse text-[12.5px]">
        <thead className="sticky-head">
          <tr>
            {table.getHeaderGroups()[0].headers.map((header) => {
              const sortable = header.column.getCanSort();
              const align =
                (header.column.columnDef.meta as { align?: string } | undefined)?.align;
              return (
                <th
                  key={header.id}
                  scope="col"
                  aria-sort={
                    header.column.getIsSorted() === "asc"
                      ? "ascending"
                      : header.column.getIsSorted() === "desc"
                        ? "descending"
                        : sortable
                          ? "none"
                          : undefined
                  }
                  className={cn(
                    "px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-faint",
                    align === "right" ? "text-right" : "text-left",
                  )}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={header.column.getToggleSortingHandler()}
                      className={cn(
                        "group inline-flex items-center gap-1 rounded transition-colors hover:text-foreground",
                        align === "right" && "flex-row-reverse",
                        header.column.getIsSorted() && "text-foreground",
                      )}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      <SortIcon dir={header.column.getIsSorted()} />
                    </button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                </th>
              );
            })}
            {onPlace && (
              <th scope="col" className="px-3 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.05em] text-faint">
                Action
              </th>
            )}
          </tr>
        </thead>

        <tbody className="stagger">
          {table.getRowModel().rows.map((row, i) => (
            <tr
              key={row.id}
              style={{ "--i": i } as React.CSSProperties}
              className={cn(
                "row-action border-t border-hairline",
                selectedId === row.original.id && "bg-brand-soft",
              )}
              aria-current={selectedId === row.original.id ? "true" : undefined}
              {...activatable(() => onSelect(row.original))}
            >
              {row.getVisibleCells().map((cell) => {
                const align =
                  (cell.column.columnDef.meta as { align?: string } | undefined)?.align;
                return (
                  <td
                    key={cell.id}
                    className={cn(
                      "px-3 py-2.5 align-top",
                      align === "right" && "num text-right",
                    )}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
              {onPlace && (
                <td className="px-3 py-2.5 text-center align-top">
                  <button
                    type="button"
                    className="press rounded-md border border-border bg-card px-2.5 py-1 text-[11px] font-medium transition-colors hover:border-brand hover:text-brand"
                    onClick={(e) => {
                      // The row is itself a button; without this the click
                      // selects the row behind the modal it just opened.
                      e.stopPropagation();
                      onPlace(row.original);
                    }}
                  >
                    Place bet
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
