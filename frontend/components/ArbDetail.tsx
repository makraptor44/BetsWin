"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import {
  FLAG_LABEL,
  KIND_BLURB,
  KIND_LABEL,
  VENUE_LABEL,
  ZONE_LABEL,
  money,
  num,
  pct,
  placeableLabel,
  untilLabel,
  usd,
} from "@/lib/format";
import type { Arb, ArbDetail as ArbDetailData, ResizeResult } from "@/lib/types";
import { useAsync } from "@/lib/useEngine";

import {
  ConfidenceBar,
  ErrorState,
  FlagChip,
  Skeleton,
  VenueChip,
  ZoneChip,
} from "./ui";

export function ArbDetailPanel({
  arb,
  onClose,
}: {
  arb: Arb;
  onClose: () => void;
}) {
  const { data, loading, error } = useAsync<ArbDetailData>(
    () => api.arb(arb.id),
    [arb.id],
  );

  // Close on Escape -- a drawer that traps you is worse than no drawer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Opportunity detail"
    >
      <div
        className="absolute inset-0"
        style={{ background: "rgba(0,0,0,0.5)" }}
        onClick={onClose}
      />
      <div
        className="relative h-full overflow-y-auto slide-in"
        style={{
          width: "min(720px, 100vw)",
          background: "var(--bg)",
          borderLeft: "1px solid var(--border)",
        }}
      >
        <Header arb={arb} onClose={onClose} />
        <div className="p-5 flex flex-col gap-5">
          {loading && <Skeleton rows={7} />}
          {error && <ErrorState message={error} />}
          {data && <Body arb={data.arb} detail={data} />}
        </div>
      </div>
    </div>
  );
}

function Header({ arb, onClose }: { arb: Arb; onClose: () => void }) {
  return (
    <div
      className="sticky top-0 z-10 px-5 py-4 border-b"
      style={{ background: "var(--bg-elevated)", borderColor: "var(--border)" }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
            <span className="chip chip-accent">{KIND_LABEL[arb.kind]}</span>
            {arb.venues.map((v) => (
              <VenueChip key={v} venue={v} />
            ))}
            <ZoneChip zone={arb.zone} short />
          </div>
          <h2 className="text-[15px] font-semibold leading-snug">{arb.title}</h2>
        </div>
        <button className="btn btn-sm shrink-0" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
    </div>
  );
}

function Body({ arb, detail }: { arb: Arb; detail: ArbDetailData }) {
  return (
    <>
      <Summary arb={arb} />
      <Executability arb={arb} />
      <WhatThisIs arb={arb} />
      {arb.notes.length > 0 && <RiskNotes arb={arb} />}
      <StakeCalculator arb={arb} />
      <PayoutMatrix detail={detail} />
      <Derivation detail={detail} />
      <Placement arb={arb} />
    </>
  );
}

function Summary({ arb }: { arb: Arb }) {
  const cells = [
    { label: "Net margin", value: pct(arb.net_margin), hint: "after fees & slippage" },
    { label: "Gross margin", value: pct(arb.margin), hint: "at quoted prices" },
    {
      label: "Guaranteed profit",
      value: money(arb.worst_case_profit, arb.currency),
      hint: "worst case, after rounding",
      tone: "positive" as const,
    },
    {
      label: "Total stake",
      value: money(arb.total_stake, arb.currency, 0),
      hint: "sized for this book",
    },
    {
      label: "Depth ceiling",
      value: money(arb.max_stake_available, arb.currency, 0),
      hint: "what the book can absorb",
    },
    { label: "Closes in", value: untilLabel(arb.close_time), hint: "capital lock-up" },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
      {cells.map((c) => (
        <div key={c.label} className="card p-3">
          <div className="label" style={{ marginBottom: 3 }}>
            {c.label}
          </div>
          <div
            className="mono text-lg font-semibold leading-tight"
            style={{ color: c.tone ? `var(--${c.tone})` : "var(--text)" }}
          >
            {c.value}
          </div>
          <div className="text-[11px] mt-0.5" style={{ color: "var(--text-faint)" }}>
            {c.hint}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Can one person actually place this?
 *
 * The question every other number on this panel presumes an answer to. Both
 * legs already share an execution zone -- the detector will not construct a set
 * that does not -- so this states which zone, in what currency, and from where.
 */
function Executability({ arb }: { arb: Arb }) {
  const broad = arb.placeable_from.includes("*");
  return (
    <div className="card p-4">
      <div className="label">Where this can be placed</div>
      <div className="flex flex-wrap items-center gap-2 mb-2.5">
        <span className="chip">{ZONE_LABEL[arb.zone] ?? arb.zone}</span>
        <span className="chip">{arb.currency}</span>
        <span
          className={`chip ${broad ? "" : "chip-caution"}`}
          title="Jurisdictions in which one operator could hold every account this trade needs"
        >
          {placeableLabel(arb.placeable_from)}
        </span>
      </div>
      <p className="text-[13px] leading-relaxed m-0" style={{ color: "var(--text-muted)" }}>
        {arb.venues.length > 1 ? (
          <>
            Both legs sit on {arb.venues.map((v) => VENUE_LABEL[v] ?? v).join(" and ")},
            which settle in the same currency under comparable rules. Legs are never
            combined across execution zones, so this trade needs no second
            jurisdiction and carries no currency exposure between its legs.
          </>
        ) : (
          <>
            Every leg is on {VENUE_LABEL[arb.venues[0]] ?? arb.venues[0]}, so there is
            no cross-venue rulebook risk at all — one account, one settlement
            source.
          </>
        )}
      </p>
    </div>
  );
}

function WhatThisIs({ arb }: { arb: Arb }) {
  return (
    <div className="card p-4">
      <div className="label">What this is</div>
      <p className="text-[13px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
        {KIND_BLURB[arb.kind]}
      </p>
      <div className="flex items-center gap-3 mt-3">
        <span className="label" style={{ margin: 0 }}>
          Confidence
        </span>
        <ConfidenceBar value={arb.confidence} />
      </div>
    </div>
  );
}

function RiskNotes({ arb }: { arb: Arb }) {
  const danger = arb.flags.includes("suspect_margin");
  return (
    <div
      className="card p-4"
      style={
        danger
          ? { borderColor: "var(--danger)", background: "var(--danger-soft)" }
          : undefined
      }
    >
      <div className="flex items-center gap-2 mb-2.5">
        <span className="label" style={{ margin: 0 }}>
          Before you stake
        </span>
        <div className="flex gap-1 flex-wrap">
          {arb.flags.map((f) => (
            <FlagChip key={f} flag={f} />
          ))}
        </div>
      </div>
      <ul className="flex flex-col gap-2 m-0 pl-0" style={{ listStyle: "none" }}>
        {arb.notes.map((n, i) => (
          <li
            key={i}
            className="text-[13px] leading-relaxed flex gap-2"
            style={{ color: "var(--text-muted)" }}
          >
            <span style={{ color: "var(--caution)" }} aria-hidden>
              •
            </span>
            <span>{n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StakeCalculator({ arb }: { arb: Arb }) {
  const [stake, setStake] = useState(arb.total_stake);
  const [result, setResult] = useState<ResizeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Debounce so dragging the slider does not fire a request per pixel.
  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    const t = setTimeout(() => {
      api
        .resize(arb.id, stake)
        .then((r) => {
          if (!cancelled) {
            setResult(r);
            setErr(null);
          }
        })
        .catch(() => {
          if (!cancelled) setErr("Could not recompute stakes.");
        })
        .finally(() => {
          if (!cancelled) setBusy(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [arb.id, stake]);

  const legs = result?.legs ?? arb.legs;
  const total = result?.total_stake ?? arb.total_stake;
  const profit = result?.worst_case_profit ?? arb.worst_case_profit;
  const max = Math.max(arb.max_stake_available, arb.total_stake);

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between mb-3">
        <div className="label" style={{ margin: 0 }}>
          Stake calculator
        </div>
        <div className="text-xs" style={{ color: "var(--text-faint)" }}>
          equal-profit sizing
        </div>
      </div>

      <div className="flex items-center gap-3 mb-1">
        <input
          type="range"
          min={20}
          max={Math.ceil(max * 1.5)}
          step={10}
          value={stake}
          onChange={(e) => setStake(Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--accent)" }}
          aria-label="Total stake"
        />
        <div className="flex items-center gap-1 shrink-0">
          <span style={{ color: "var(--text-faint)" }}>$</span>
          <input
            className="input mono"
            style={{ width: 108 }}
            type="number"
            min={20}
            value={Math.round(stake)}
            onChange={(e) => setStake(Math.max(20, Number(e.target.value) || 0))}
            aria-label="Total stake in dollars"
          />
        </div>
      </div>

      {result?.exceeds_depth && (
        <p className="text-xs mb-2" style={{ color: "var(--caution)" }}>
          Beyond {usd(result.max_stake_available, 0)} the visible book cannot
          fill this size — the realised price would be worse than shown.
        </p>
      )}

      <div className="scroll-x mt-3">
        <table className="data">
          <thead>
            <tr>
              <th>Leg</th>
              <th>Venue</th>
              <th style={{ textAlign: "right" }}>Price</th>
              <th style={{ textAlign: "right" }}>Odds</th>
              <th style={{ textAlign: "right" }}>Stake</th>
              <th style={{ textAlign: "right" }}>Contracts</th>
              <th style={{ textAlign: "right" }}>Fee</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((l, i) => (
              <tr key={i}>
                <td>
                  <div className="font-medium">{l.outcome}</div>
                  <div className="text-[11px]" style={{ color: "var(--text-faint)" }}>
                    {l.side}
                  </div>
                </td>
                <td>
                  <VenueChip venue={l.venue} />
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {l.price.toFixed(4)}
                </td>
                <td className="mono" style={{ textAlign: "right", color: "var(--text-muted)" }}>
                  {l.decimal_odds.toFixed(3)}
                </td>
                <td className="mono" style={{ textAlign: "right", fontWeight: 600 }}>
                  {usd(l.stake)}
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {num(l.contracts, 0)}
                </td>
                <td className="mono" style={{ textAlign: "right", color: "var(--text-muted)" }}>
                  {l.fee > 0 ? usd(l.fee) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        className="flex flex-wrap items-center justify-between gap-3 mt-3 pt-3"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Total staked <span className="mono">{usd(total)}</span>
          {busy && <span className="ml-2 pulse-dot">·</span>}
        </span>
        <span className="text-sm">
          Guaranteed{" "}
          <span className="mono font-semibold num-positive">{usd(profit)}</span>{" "}
          <span style={{ color: "var(--text-faint)" }}>
            ({result ? result.roi_pct.toFixed(2) : arb.roi_pct.toFixed(2)}%)
          </span>
        </span>
      </div>
      {err && (
        <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>
          {err}
        </p>
      )}
    </div>
  );
}

function PayoutMatrix({ detail }: { detail: ArbDetailData }) {
  return (
    <div className="card p-4">
      <div className="label">Payout in every state</div>
      <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
        The guarantee is only real if profit is positive in every row. This is the
        check to run before committing, since rounded stakes make the outcomes
        slightly unequal.
      </p>
      <div className="scroll-x">
        <table className="data">
          <thead>
            <tr>
              <th>If this outcome occurs</th>
              <th style={{ textAlign: "right" }}>Returns</th>
              <th style={{ textAlign: "right" }}>Staked</th>
              <th style={{ textAlign: "right" }}>Profit</th>
              <th style={{ textAlign: "right" }}>ROI</th>
            </tr>
          </thead>
          <tbody>
            {detail.payout_matrix.map((r, i) => (
              <tr key={i}>
                <td>
                  <span className="font-medium">{r.outcome}</span>
                  <span className="text-xs ml-2" style={{ color: "var(--text-faint)" }}>
                    {r.venue}
                  </span>
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {usd(r.gross_return)}
                </td>
                <td className="mono" style={{ textAlign: "right", color: "var(--text-muted)" }}>
                  {usd(r.total_stake)}
                </td>
                <td
                  className={`mono ${r.profit >= 0 ? "num-positive" : "num-negative"}`}
                  style={{ textAlign: "right", fontWeight: 600 }}
                >
                  {usd(r.profit)}
                </td>
                <td
                  className={`mono ${r.roi_pct >= 0 ? "num-positive" : "num-negative"}`}
                  style={{ textAlign: "right" }}
                >
                  {r.roi_pct.toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Derivation({ detail }: { detail: ArbDetailData }) {
  const m = detail.maths;
  const rows: Array<[string, string, string]> = [
    [
      "Combined book (quoted)",
      m.book_quoted.toFixed(5),
      "B = Σ 1/dᵢ at the prices shown. Below 1.0 is the arbitrage condition.",
    ],
    [
      "Combined book (all-in)",
      m.book_effective.toFixed(5),
      "The same sum after venue fees and the price of filling this size.",
    ],
    [
      "Margin",
      `${pct(m.margin_gross)} → ${pct(m.margin_net)}`,
      "m = 1/B − 1, gross then net. The gap is what execution costs.",
    ],
    [
      "Margin after voids",
      pct(m.margin_after_voids),
      `Assuming ${pct(m.void_rate, 1)} of legs void at ${pct(m.void_loss, 0)} of stake. This is the number that decides whether the trade is worth doing.`,
    ],
    [
      "Kelly fraction",
      `${m.kelly_arb_fraction.toFixed(2)}×`,
      m.kelly_arb_fraction > 1
        ? "Above 1.0, meaning bankroll — not risk appetite — is the binding constraint."
        : "The share of bankroll this edge justifies.",
    ],
    [
      "Per-event cap",
      usd(m.bankroll_cap, 0),
      "Hard ceiling on exposure to any single event, from your bankroll settings.",
    ],
  ];

  return (
    <div className="card p-4">
      <div className="label">The arithmetic</div>
      <div className="flex flex-col gap-2.5 mt-1">
        {rows.map(([label, value, note]) => (
          <div key={label}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px] font-medium">{label}</span>
              <span className="mono text-[13px] shrink-0">{value}</span>
            </div>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-faint)" }}>
              {note}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="label">Implied vs de-vigged probability</div>
        <div className="flex flex-col gap-1.5">
          {m.implied_probs.map((p, i) => (
            <div key={i} className="flex items-center gap-3 text-xs">
              <span className="mono shrink-0" style={{ width: 62 }}>
                {(p * 100).toFixed(2)}%
              </span>
              <div
                className="flex-1 h-1.5 rounded-full overflow-hidden"
                style={{ background: "var(--neutral-soft)" }}
              >
                <div
                  className="h-full"
                  style={{ width: `${p * 100}%`, background: "var(--accent)" }}
                />
              </div>
              <span
                className="mono shrink-0"
                style={{ width: 62, textAlign: "right", color: "var(--text-muted)" }}
              >
                {((m.devig_fair_probs[i] ?? 0) * 100).toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
        <p className="text-[11px] mt-2" style={{ color: "var(--text-faint)" }}>
          Left: the price you pay. Right: the same prices normalised to sum to
          100%, i.e. the market&apos;s fair view with the margin stripped out.
        </p>
      </div>
    </div>
  );
}

function Placement({ arb }: { arb: Arb }) {
  const [logged, setLogged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const log = async () => {
    setBusy(true);
    try {
      await api.logPlacement(arb.id);
      setLogged(true);
      setErr(null);
    } catch {
      setErr("Could not record the placement.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card p-4">
      <div className="label">Place the legs</div>
      <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
        Open each venue and place the legs yourself. Fill the least liquid side
        first — if it moves against you before the second leg lands, abandon the
        trade and close the open leg rather than chasing the price.
      </p>
      <div className="flex flex-col gap-2">
        {arb.legs.map((l, i) => (
          <div
            key={i}
            className="flex items-center justify-between gap-3 p-2.5 rounded-lg"
            style={{ background: "var(--bg-sunken)" }}
          >
            <div className="min-w-0">
              <div className="text-[13px] font-medium truncate">
                {l.side} · {l.outcome}
              </div>
              <div className="text-xs mono" style={{ color: "var(--text-muted)" }}>
                {usd(l.stake)} @ max {l.price.toFixed(4)} · {num(l.contracts, 0)}{" "}
                contracts
              </div>
            </div>
            {l.url ? (
              <a
                className="btn btn-sm shrink-0"
                href={l.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open ↗
              </a>
            ) : (
              <span className="chip shrink-0">{l.venue}</span>
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 mt-3">
        <button
          className="btn btn-sm"
          onClick={log}
          disabled={busy || logged}
        >
          {logged ? "✓ Logged" : busy ? "Saving…" : "Log as placed"}
        </button>
        <span className="text-xs" style={{ color: "var(--text-faint)" }}>
          Records the trade so realised P&amp;L can be reconciled later.
        </span>
      </div>
      {err && (
        <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>
          {err}
        </p>
      )}
    </div>
  );
}
