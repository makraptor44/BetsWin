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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
          className="text-xs leading-relaxed text-muted-foreground"
        >
          <p className="mb-2">
            The alternative is worse than it looks. Pairing a sterling exchange
            against a dollar contract market produces immaculate arithmetic and
            an untakeable trade: it needs accounts in two jurisdictions, and the
            unhedged currency leg is larger than the edge — a 1% margin is
            erased by a 1% move in the exchange rate. The zone rule removes
            both problems by construction rather than by warning about them.
          </p>
          <p className="m-0">
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
          className="rounded-lg border border-border bg-card shadow-sm p-3 flex items-start gap-2.5 border-danger bg-danger-soft"
          role="alert"
        >
          <span className="text-danger" aria-hidden>
            ⚠
          </span>
          <div className="text-xs text-muted-foreground">
            <strong className="text-danger">
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
              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">{zone.currency}</span>
              {venues.some((v) => v.live) && (
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-positive-soft text-positive">Live</span>
              )}
            </div>
            <p
              className="text-xs leading-relaxed text-muted-foreground"
            >
              {zone.rationale}
            </p>
          </div>

          <div className="scroll-x">
            <Table className="w-full border-collapse text-[13px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Venue</TableHead>
                  <TableHead>Structure</TableHead>
                  <TableHead>Regulator</TableHead>
                  <TableHead className="text-right">Commission</TableHead>
                  <TableHead>Available from</TableHead>
                  <TableHead>Data</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {venues.map((v) => (
                  <VenueRow key={v.name} venue={v} />
                ))}
              </TableBody>
            </Table>
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
          <Table className="w-full border-collapse text-[13px]">
            <TableHeader>
              <TableRow>
                <TableHead>Pair</TableHead>
                <TableHead>Verdict</TableHead>
                <TableHead>Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...allowedPairs, ...blockedPairs].map((p) => (
                <PairRow key={`${p.a}-${p.b}`} pair={p} />
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

      {data.rejected_this_scan.length > 0 && (
        <Card>
          <SectionTitle
            title="Rejected on the last scan"
            hint="Venue pairs the rule declined to compare during the most recent cycle. This is how you tell the guard fired rather than the matcher having found nothing."
          />
          <ul
            className="text-xs flex flex-col gap-1.5 text-muted-foreground m-0 pl-[16px]"
          >
            {data.rejected_this_scan.map((r) => (
              <li key={r}>{r}</li>
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
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-2">
          <VenueChip venue={v.name} />
          {v.url && (
            <a href={v.url} target="_blank" rel="noopener noreferrer" className="text-xs">
              ↗
            </a>
          )}
        </div>
        <div
          className="text-xs mt-1 leading-relaxed text-faint max-w-[380px]"
        >
          {v.notes}
        </div>
      </TableCell>
      <TableCell className="text-xs">{STRUCTURE_LABEL[v.structure] ?? v.structure}</TableCell>
      <TableCell className="text-xs text-muted-foreground max-w-[200px]">
        {v.regulator || "—"}
      </TableCell>
      <TableCell className="tabular text-right">
        {v.commission > 0 ? pct(v.commission, 1) : "—"}
        {v.commission > 0 && (
          <div className="text-[10px] text-faint">
            on winnings
          </div>
        )}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground max-w-[220px]">
        {available}
      </TableCell>
      <TableCell>
        <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground ${v.public_data ? "" : "chip-caution"}`}>
          {v.public_data ? "Public" : "Needs credentials"}
        </span>
      </TableCell>
      <TableCell>
        {v.live ? (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-positive-soft text-positive">Connected</span>
        ) : (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">Not configured</span>
        )}
      </TableCell>
    </TableRow>
  );
}

function PairRow({ pair: p }: { pair: VenuePair }) {
  return (
    <TableRow className={p.allowed ? undefined : "opacity-72"}>
      <TableCell>
        <div className="flex items-center gap-1.5 flex-wrap">
          <VenueChip venue={p.a} />
          <span className="text-faint">×</span>
          <VenueChip venue={p.b} />
        </div>
      </TableCell>
      <TableCell>
        {p.allowed ? (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-positive-soft text-positive">Paired</span>
            <ZoneChip zone={p.zone} short />
            {p.both_live && <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground">both live</span>}
          </div>
        ) : (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-danger-soft text-danger">Blocked</span>
        )}
      </TableCell>
      <TableCell
        className="text-xs leading-relaxed text-muted-foreground max-w-[620px]"
      >
        {p.reason}
        {p.allowed && p.jurisdictions.length > 0 && !p.jurisdictions.includes("*") && (
          <span className="text-faint">
            {" "}
            Placeable from {p.jurisdictions.join(", ")}.
          </span>
        )}
      </TableCell>
    </TableRow>
  );
}
