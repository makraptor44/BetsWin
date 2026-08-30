"use client";

import { useEffect, useState } from "react";

import {
  Card,
  ErrorState,
  Field,
  SectionTitle,
  Skeleton,
  Toggle,
} from "@/components/ui";
import { api } from "@/lib/api";
import { pct, usd, VENUE_LABEL } from "@/lib/format";
import type { EngineConfig } from "@/lib/types";
import { useAsync } from "@/lib/useEngine";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Row {
  key: keyof EngineConfig;
  label: string;
  hint: string;
  kind: "pct" | "money" | "int";
  step: number;
  min: number;
  max: number;
}

const DETECTION: Row[] = [
  {
    key: "min_arb_margin",
    label: "Minimum margin",
    hint: "Floor for surfacing an opportunity. Below roughly 0.4% fees and slippage eat the edge.",
    kind: "pct",
    step: 0.1,
    min: 0,
    max: 20,
  },
  {
    key: "max_arb_margin",
    label: "Maximum margin",
    hint: "Anything fatter than this is discarded as bad data rather than shown.",
    kind: "pct",
    step: 1,
    min: 1,
    max: 100,
  },
  {
    key: "suspect_margin",
    label: "Suspicion threshold",
    hint: "Above this, an opportunity is flagged and its confidence cut. Most very large apparent arbs are mismatched lines or a price that has already moved.",
    kind: "pct",
    step: 0.5,
    min: 0.5,
    max: 50,
  },
  {
    key: "min_confidence",
    label: "Minimum confidence",
    hint: "Opportunities scoring below this are not surfaced at all.",
    kind: "int",
    step: 5,
    min: 0,
    max: 100,
  },
];

const BANKROLL: Row[] = [
  {
    key: "bankroll",
    label: "Bankroll",
    hint: "Total capital allocated to this activity — only money you can afford to have locked up for weeks.",
    kind: "money",
    step: 500,
    min: 100,
    max: 10_000_000,
  },
  {
    key: "default_stake",
    label: "Target stake",
    hint: "Turnover to aim for per opportunity, before depth and bankroll caps apply.",
    kind: "money",
    step: 50,
    min: 20,
    max: 1_000_000,
  },
  {
    key: "max_stake_fraction_per_event",
    label: "Max per event",
    hint: "Hard cap on exposure to any single event, as a share of bankroll. This is what bounds the damage from one voided leg.",
    kind: "pct",
    step: 1,
    min: 0.1,
    max: 100,
  },
];

const RISK: Row[] = [
  {
    key: "assumed_void_rate",
    label: "Assumed void rate",
    hint: "How often a leg is expected to be voided or fail to settle as quoted.",
    kind: "pct",
    step: 0.5,
    min: 0,
    max: 50,
  },
  {
    key: "assumed_void_loss",
    label: "Loss when voided",
    hint: "Cost of a voided leg as a share of that stake, from the unhedged exposure it leaves behind.",
    kind: "pct",
    step: 5,
    min: 0,
    max: 100,
  },
];

const ALERTS: Row[] = [
  {
    key: "alert_min_margin",
    label: "Alert above margin",
    hint: "Push-notify only above this margin. Alert fatigue is what makes an operator stop reading alerts.",
    kind: "pct",
    step: 0.25,
    min: 0,
    max: 50,
  },
  {
    key: "alert_min_confidence",
    label: "Alert above confidence",
    hint: "And only when the quality score clears this bar.",
    kind: "int",
    step: 5,
    min: 0,
    max: 100,
  },
  {
    key: "poll_interval_seconds",
    label: "Scan interval (s)",
    hint: "Seconds between scan cycles. Faster catches more, but burns API quota.",
    kind: "int",
    step: 5,
    min: 10,
    max: 3600,
  },
];

export default function SettingsPage() {
  const { data, loading, error, reload } = useAsync(() => api.config(), []);
  const [draft, setDraft] = useState<Partial<EngineConfig>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    setDraft({});
    setSaved(false);
  }, [data]);

  if (loading) return <Skeleton rows={9} />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const value = (r: Row): number => {
    const raw = (draft[r.key] ?? data[r.key]) as number;
    return r.kind === "pct" ? Number((raw * 100).toFixed(4)) : raw;
  };

  const setValue = (r: Row, v: number) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [r.key]: r.kind === "pct" ? v / 100 : v }));
  };

  const dirty = Object.keys(draft).length > 0;

  const save = async () => {
    setSaving(true);
    setSaveErr(null);
    try {
      await api.patchConfig(draft);
      setDraft({});
      setSaved(true);
      reload();
    } catch {
      setSaveErr("Could not save. Is the engine running?");
    } finally {
      setSaving(false);
    }
  };

  const group = (title: string, hint: string, rows: Row[]) => (
    <Card key={title}>
      <SectionTitle title={title} hint={hint} />
      <div className="flex flex-col gap-3.5">
        {rows.map((r) => (
          <Field key={String(r.key)} label={r.label} hint={r.hint}>
            <div className="flex items-center gap-2">
              <Input className="tabular" type="number" step={r.step} min={r.min} max={r.max} value={value(r)} onChange={(e) => setValue(r, Number(e.target.value))} />
              <span
                className="text-xs shrink-0 text-faint w-[20px]"
              >
                {r.kind === "pct" ? "%" : r.kind === "money" ? "$" : ""}
              </span>
            </div>
          </Field>
        ))}
      </div>
    </Card>
  );

  const perEventCap =
    ((draft.bankroll ?? data.bankroll) as number) *
    ((draft.max_stake_fraction_per_event ??
      data.max_stake_fraction_per_event) as number);

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
          <p className="text-sm mt-0.5 text-muted-foreground">
            Changes apply from the next scan cycle. They live in memory — set
            them permanently in the backend&apos;s <code>.env</code>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {saved && (
            <span className="text-xs text-positive">
              ✓ Saved
            </span>
          )}
          {dirty && (
            <Button size="sm" variant="outline" onClick={() => { setDraft({}); setSaved(false); }} >
              Discard
            </Button>
          )}
          <Button size="sm" onClick={save} disabled={!dirty || saving} >
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </header>

      {saveErr && <ErrorState message={saveErr} />}

      <Card>
        <SectionTitle
          title="Execution zones"
          hint="Which venues may be arbed against each other. This is the rule that keeps every surfaced pair placeable by one person from one place."
        />
        <div className="grid sm:grid-cols-2 gap-4">
          <Field
            label="Pair only within a zone"
            hint="On: Polymarket pairs with Kalshi and Betfair with Smarkets, but never Betfair with Kalshi. Off: cross-venue detection compares everything, including pairs that need accounts in two jurisdictions and carry an unhedged currency leg."
          >
            <div className="flex items-center gap-2.5 pt-1">
              <Toggle
                checked={
                  (draft.enforce_zone_pairing ??
                    data.enforce_zone_pairing) as boolean
                }
                onChange={(v) => {
                  setSaved(false);
                  setDraft((d) => ({ ...d, enforce_zone_pairing: v }));
                }}
                label="Enforce execution-zone pairing"
              />
              <span className="text-xs text-muted-foreground">
                {(draft.enforce_zone_pairing ?? data.enforce_zone_pairing)
                  ? "Enforced"
                  : "Disabled — pairs may be unplaceable"}
              </span>
            </div>
          </Field>

          <Field
            label="Trading from"
            hint="ISO country code, e.g. GB or US. Set it and the engine hides anything you could not legitimately place from there. Leave blank to see every zone."
          >
            <Input className="tabular" maxLength={2} placeholder="—" value={ ((draft.operator_jurisdiction ?? data.operator_jurisdiction) as string) ?? "" } onChange={(e) => { setSaved(false); setDraft((d) => ({ ...d, operator_jurisdiction: e.target.value.toUpperCase().slice(0, 2), })); }} />
          </Field>
        </div>
      </Card>

      <Card>
        <SectionTitle title="Data sources" hint="Configured in the backend environment" />
        <div className="flex flex-wrap gap-2 mb-3">
          {Object.entries(data.sources).map(([name, enabled]) => (
            <span
              key={name}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs"
              style={{
                background: "var(--muted)",
                opacity: enabled ? 1 : 0.5,
              }}
            >
              <span
                className="rounded-full"
                style={{
                  width: 6,
                  height: 6,
                  background: enabled ? "var(--positive)" : "var(--faint)",
                }}
                aria-hidden
              />
              {VENUE_LABEL[name] ?? name}
              <span className="text-faint">
                {enabled ? "on" : "off"}
              </span>
            </span>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Polymarket, Kalshi and Smarkets need no credentials for market data.
          Sportsbook coverage requires <code>ODDS_API_KEY</code>; Betfair
          requires <code>BETFAIR_APP_KEY</code> and a session. Telegram alerts
          are{" "}
          <strong>{data.telegram_enabled ? "enabled" : "not configured"}</strong>.
          {data.demo_mode && (
            <>
              {" "}
              <strong className="text-caution">
                Demo mode is on
              </strong>{" "}
              — the engine is serving fixtures, not live markets.
            </>
          )}
        </p>
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        {group(
          "Detection thresholds",
          "What counts as an opportunity worth showing",
          DETECTION,
        )}
        {group(
          "Bankroll and sizing",
          "How much capital any one opportunity may consume",
          BANKROLL,
        )}
        {group(
          "Risk assumptions",
          "Used to compute void-adjusted edge and backtests",
          RISK,
        )}
        {group("Alerts and scanning", "When to interrupt you", ALERTS)}
      </div>

      <Card>
        <SectionTitle title="What these settings imply" />
        <div className="grid sm:grid-cols-3 gap-3">
          <Implication
            label="Max exposure per event"
            value={usd(perEventCap, 0)}
            note="A single voided leg cannot cost more than this."
          />
          <Implication
            label="Void-adjusted edge on a 2% arb"
            value={pct(
              (1 -
                ((draft.assumed_void_rate ?? data.assumed_void_rate) as number)) *
                0.02 -
                ((draft.assumed_void_rate ?? data.assumed_void_rate) as number) *
                  ((draft.assumed_void_loss ??
                    data.assumed_void_loss) as number),
            )}
            note="What a nominal 2% actually returns under your assumptions."
          />
          <Implication
            label="Cross-venue match floor"
            value={`${data.fuzzy_match_threshold}/100`}
            note="Title similarity needed before two venues' markets are paired."
          />
          <Implication
            label="Exchange commission"
            value={`${pct(data.smarkets_commission, 1)} / ${pct(data.betfair_commission, 1)}`}
            note="Smarkets and Betfair take this share of net winnings. Priced into every quote before detection."
          />
          <Implication
            label="Watchlist reach"
            value={`${(data.near_miss_slack * 10000).toFixed(0)} bps`}
            note="How far from crossing a book can be and still be worth watching."
          />
          <Implication
            label="Pairing rule"
            value={
              (draft.enforce_zone_pairing ?? data.enforce_zone_pairing)
                ? "Same zone only"
                : "Unrestricted"
            }
            note="Whether cross-venue legs must share a currency, a settlement convention and an account footprint."
          />
        </div>
      </Card>
    </div>
  );
}

function Implication({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="rounded-lg p-3 bg-muted">
      <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint mb-[3px]">
        {label}
      </div>
      <div className="tabular text-base font-semibold">{value}</div>
      <div className="text-[11px] mt-1 text-faint">
        {note}
      </div>
    </div>
  );
}
