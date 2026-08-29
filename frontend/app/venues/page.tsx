"use client";

import { useMemo } from "react";

import {
  Card,
  ErrorState,
  SectionTitle,
  Skeleton,
  Stat,
  VenueChip,
  ZoneChip,
} from "@/components/ui";
import { api } from "@/lib/api";
import { pct } from "@/lib/format";
import type { VenuePair, VenueSummary } from "@/lib/types";
import { useAsync } from "@/lib/useEngine";

const STRUCTURE_LABEL: Record<string, string> = {
  contract: "Binary contract",
  exchange: "Back/lay exchange",
  book: "Fixed odds",
};

/**
 * Venues and execution zones.
 *
 * The page exists because the most important rule in the engine is invisible
 * everywhere else: cross-venue detection runs inside a zone and never across
 * one. Without this view a rejected pair and a pair that simply never crossed
 * look identical, and the guard is impossible to audit.
 */
export default function VenuesPage() {
  const { data, loading, error, reload } = useAsync(() => api.venues(), []);

  const byZone = useMemo(() => {
    if (!data) return [];
    return data.zones.map((z) => ({
      zone: z,
      venues: data.venues.filter((v) => v.zone === z.key),
    }));
  }, [data]);

  const allowedPairs = data?.pairs.filter((p) => p.allowed) ?? [];
  const blockedPairs = data?.pairs.filter((p) => !p.allowed) ?? [];
  const livePairs = allowedPairs.filter((p) => p.both_live);

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading || !data) return <Skeleton rows={8} />;

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <SectionTitle
          title="Execution zones"
          hint="A cross-venue arbitrage is only real if one person can place both legs. Venues are grouped into zones that share a currency, a settlement convention, and an account footprint a single operator can plausibly hold — and pairing runs inside a zone, never across one."
        />
        <div
          className="text-xs leading-relaxed"
          style={{ color: "var(--text-muted)" }}
        >
          <p style={{ margin: "0 0 8px" }}>
            The alternative is worse than it looks. Pairing a sterling exchange
            against a dollar contract market produces immaculate arithmetic and
            an untakeable trade: it needs accounts in two jurisdictions, and the
            unhedged currency leg is larger than the edge — a 1% margin is
            erased by a 1% move in the exchange rate. The zone rule removes
            both problems by construction rather than by warning about them.
          </p>
          <p style={{ margin: 0 }}>
            It costs opportunities. That is the trade: fewer candidates, all of
            them placeable.
          </p>
        </div>
      </Card>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Zones"
          value={data.zones.length}
          sub={`${data.venues.length} venues in the registry`}
        />
        <Stat
          label="Pairs allowed"
          value={allowedPairs.length}
          sub={`of ${data.pairs.length} possible combinations`}
        />
        <Stat
          label="Pairs blocked"
          value={blockedPairs.length}
          sub="different zone, currency or jurisdiction"
        />
        <Stat
          label="Live pairs"
          value={livePairs.length}
          sub={
            livePairs.length > 0
              ? "both feeds connected right now"
              : "no zone has two live feeds"
          }
          tone={livePairs.length > 0 ? "positive" : "caution"}
        />
      </div>

      {!data.enforce_zone_pairing && (
        <div
          className="card p-3 flex items-start gap-2.5"
          style={{ borderColor: "var(--danger)", background: "var(--danger-soft)" }}
          role="alert"
        >
          <span style={{ color: "var(--danger)" }} aria-hidden>
            ⚠
          </span>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            <strong style={{ color: "var(--danger)" }}>
              Zone pairing is disabled.
            </strong>{" "}
            Cross-venue detection will compare venues in different jurisdictions
            and currencies. Anything it surfaces may not be placeable by one
            operator. Re-enable it in Settings.
          </div>
        </div>
      )}

      {byZone.map(({ zone, venues }) => (
        <Card key={zone.key} padded={false}>
          <div className="p-4 pb-2">
            <div className="flex items-center gap-2 flex-wrap mb-1.5">
              <h2 className="text-[15px] font-semibold tracking-tight">
                {zone.label}
              </h2>
              <span className="chip">{zone.currency}</span>
              {venues.some((v) => v.live) && (
                <span className="chip chip-positive">Live</span>
              )}
            </div>
            <p
              className="text-xs leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              {zone.rationale}
            </p>
          </div>

          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>Venue</th>
                  <th>Structure</th>
                  <th>Regulator</th>
                  <th style={{ textAlign: "right" }}>Commission</th>
                  <th>Available from</th>
                  <th>Data</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {venues.map((v) => (
                  <VenueRow key={v.name} venue={v} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}

      <Card padded={false}>
        <div className="p-4 pb-2">
          <SectionTitle
            title="Pairing matrix"
            hint="Every venue combination and the verdict on it. A blocked pair is not a missed opportunity — it is a trade nobody could have placed."
          />
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>Pair</th>
                <th>Verdict</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {[...allowedPairs, ...blockedPairs].map((p) => (
                <PairRow key={`${p.a}-${p.b}`} pair={p} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {data.rejected_this_scan.length > 0 && (
        <Card>
          <SectionTitle
            title="Rejected on the last scan"
            hint="Venue pairs the rule declined to compare during the most recent cycle. This is how you tell the guard fired rather than the matcher having found nothing."
          />
          <ul
            className="text-xs flex flex-col gap-1.5"
            style={{ color: "var(--text-muted)", margin: 0, paddingLeft: 16 }}
          >
            {data.rejected_this_scan.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function VenueRow({ venue: v }: { venue: VenueSummary }) {
  const available =
    v.jurisdictions.includes("*")
      ? v.excluded.length > 0
        ? `Broadly, except ${v.excluded.join(", ")}`
        : "Broadly available"
      : v.jurisdictions.join(", ");

  return (
    <tr>
      <td>
        <div className="flex items-center gap-2">
          <VenueChip venue={v.name} />
          {v.url && (
            <a href={v.url} target="_blank" rel="noopener noreferrer" className="text-xs">
              ↗
            </a>
          )}
        </div>
        <div
          className="text-xs mt-1 leading-relaxed"
          style={{ color: "var(--text-faint)", maxWidth: 380 }}
        >
          {v.notes}
        </div>
      </td>
      <td className="text-xs">{STRUCTURE_LABEL[v.structure] ?? v.structure}</td>
      <td className="text-xs" style={{ color: "var(--text-muted)", maxWidth: 200 }}>
        {v.regulator || "—"}
      </td>
      <td className="mono" style={{ textAlign: "right" }}>
        {v.commission > 0 ? pct(v.commission, 1) : "—"}
        {v.commission > 0 && (
          <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>
            on winnings
          </div>
        )}
      </td>
      <td className="text-xs" style={{ color: "var(--text-muted)", maxWidth: 220 }}>
        {available}
      </td>
      <td>
        <span className={`chip ${v.public_data ? "" : "chip-caution"}`}>
          {v.public_data ? "Public" : "Needs credentials"}
        </span>
      </td>
      <td>
        {v.live ? (
          <span className="chip chip-positive">Connected</span>
        ) : (
          <span className="chip">Not configured</span>
        )}
      </td>
    </tr>
  );
}

function PairRow({ pair: p }: { pair: VenuePair }) {
  return (
    <tr style={{ opacity: p.allowed ? 1 : 0.72 }}>
      <td>
        <div className="flex items-center gap-1.5 flex-wrap">
          <VenueChip venue={p.a} />
          <span style={{ color: "var(--text-faint)" }}>×</span>
          <VenueChip venue={p.b} />
        </div>
      </td>
      <td>
        {p.allowed ? (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="chip chip-positive">Paired</span>
            <ZoneChip zone={p.zone} short />
            {p.both_live && <span className="chip">both live</span>}
          </div>
        ) : (
          <span className="chip chip-danger">Blocked</span>
        )}
      </td>
      <td
        className="text-xs leading-relaxed"
        style={{ color: "var(--text-muted)", maxWidth: 620 }}
      >
        {p.reason}
        {p.allowed && p.jurisdictions.length > 0 && !p.jurisdictions.includes("*") && (
          <span style={{ color: "var(--text-faint)" }}>
            {" "}
            Placeable from {p.jurisdictions.join(", ")}.
          </span>
        )}
      </td>
    </tr>
  );
}
