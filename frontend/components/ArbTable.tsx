"use client";

import {
  KIND_LABEL,
  money,
  num,
  pct,
  placeableLabel,
  untilLabel,
} from "@/lib/format";
import type { Arb } from "@/lib/types";

import { ConfidenceBar, FlagChip, VenueChip, ZoneChip } from "./ui";

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
      <table className="data">
        <thead>
          <tr>
            <th>Opportunity</th>
            <th>Type</th>
            <th>Venues</th>
            <th>Placeable from</th>
            <th style={{ textAlign: "right" }}>Net margin</th>
            <th style={{ textAlign: "right" }}>Stake</th>
            <th style={{ textAlign: "right" }}>Profit</th>
            <th style={{ textAlign: "right" }}>Max size</th>
            <th>Confidence</th>
            <th>Risks</th>
            <th style={{ textAlign: "right" }}>Closes</th>
            {onPlace && <th style={{ textAlign: "center" }}>Action</th>}
          </tr>
        </thead>
        <tbody>
          {arbs.map((a) => (
            <tr
              key={a.id}
              className="clickable"
              onClick={() => onSelect(a)}
              style={
                selectedId === a.id
                  ? { background: "var(--accent-soft)" }
                  : undefined
              }
            >
              <td style={{ maxWidth: 360 }}>
                <div className="font-medium truncate" title={a.title}>
                  {a.title}
                </div>
                <div
                  className="text-xs truncate mt-0.5"
                  style={{ color: "var(--text-faint)" }}
                >
                  {a.legs
                    .map((l) => `${l.outcome} @ ${l.price.toFixed(3)}`)
                    .join("  ·  ")}
                </div>
              </td>
              <td>
                <span className="chip">{KIND_LABEL[a.kind]}</span>
              </td>
              <td>
                <div className="flex gap-1 flex-wrap">
                  {a.venues.map((v) => (
                    <VenueChip key={v} venue={v} />
                  ))}
                </div>
              </td>
              <td>
                <div className="flex flex-col gap-0.5">
                  <ZoneChip zone={a.zone} short />
                  <span className="text-xs" style={{ color: "var(--text-faint)" }}>
                    {placeableLabel(a.placeable_from)}
                  </span>
                </div>
              </td>
              <td className="mono" style={{ textAlign: "right", fontWeight: 600 }}>
                {pct(a.net_margin)}
                {a.margin > a.net_margin + 0.0005 && (
                  <div
                    className="text-[10px] font-normal"
                    style={{ color: "var(--text-faint)" }}
                    title="Gross margin before venue fees and slippage"
                  >
                    {pct(a.margin)} gross
                  </div>
                )}
              </td>
              <td className="mono" style={{ textAlign: "right" }}>
                {money(a.total_stake, a.currency, 0)}
              </td>
              <td
                className="mono num-positive"
                style={{ textAlign: "right", fontWeight: 600 }}
              >
                {money(a.worst_case_profit, a.currency)}
              </td>
              <td
                className="mono"
                style={{ textAlign: "right", color: "var(--text-muted)" }}
                title="Total stake the visible order-book depth can absorb"
              >
                {money(a.max_stake_available, a.currency, 0)}
              </td>
              <td>
                <ConfidenceBar value={a.confidence} />
              </td>
              <td style={{ maxWidth: 170 }}>
                <div className="flex gap-1 flex-wrap">
                  {a.flags.slice(0, 2).map((f) => (
                    <FlagChip key={f} flag={f} />
                  ))}
                  {a.flags.length > 2 && (
                    <span className="chip">+{a.flags.length - 2}</span>
                  )}
                  {a.flags.length === 0 && (
                    <span className="chip chip-positive">Clean</span>
                  )}
                </div>
              </td>
              <td
                className="mono"
                style={{ textAlign: "right", color: "var(--text-muted)" }}
              >
                {untilLabel(a.close_time)}
              </td>
              {onPlace && (
                <td style={{ textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    style={{ whiteSpace: "nowrap", padding: "4px 10px" }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onPlace(a);
                    }}
                  >
                    Place Bet
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
          className="card card-hover p-3.5 text-left w-full cursor-pointer"
          onClick={() => onSelect(a)}
        >
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="font-medium text-[13px] leading-snug">{a.title}</div>
            <div
              className="mono text-base font-semibold shrink-0"
              style={{ color: "var(--text)" }}
            >
              {pct(a.net_margin)}
            </div>
          </div>
          <div className="flex flex-wrap gap-1 mb-2.5">
            <span className="chip">{KIND_LABEL[a.kind]}</span>
            {a.venues.map((v) => (
              <VenueChip key={v} venue={v} />
            ))}
            <ZoneChip zone={a.zone} short />
          </div>
          <div className="flex flex-col gap-1 mb-2.5">
            {a.legs.map((l, i) => (
              <div key={i} className="flex justify-between text-xs">
                <span style={{ color: "var(--text-muted)" }} className="truncate pr-2">
                  {l.outcome}
                </span>
                <span className="mono shrink-0">
                  {l.price.toFixed(3)} · {money(l.stake, a.currency)}
                </span>
              </div>
            ))}
          </div>
          <div
            className="flex items-center justify-between pt-2.5"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {money(a.total_stake, a.currency, 0)} →{" "}
              <span className="num-positive mono font-semibold">
                {money(a.worst_case_profit, a.currency)}
              </span>
            </span>
            <div className="flex items-center gap-2">
              <ConfidenceBar value={a.confidence} />
              {onPlace && (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPlace(a);
                  }}
                >
                  Place
                </button>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
