"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, Field, SectionTitle,
  NativeSelect,
} from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct, usd } from "@/lib/format";
import type {
  ConvertResult,
  KellyResult,
  StakeCalcResult,
  VoidResult,
} from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function CalculatorsPage() {
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">Calculators</h1>
        <p className="text-sm mt-0.5 text-muted-foreground">
          The same arithmetic the engine runs, available on any prices you like.
          Useful for checking an opportunity by hand before staking.
        </p>
      </header>

      <div className="grid lg:grid-cols-2 gap-4">
        <StakeCalculator />
        <VoidCalculator />
        <KellyCalculator />
        <OddsConverter />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ arb stakes */

function StakeCalculator() {
  const [odds, setOdds] = useState<string[]>(["1.95", "2.15"]);
  const [stake, setStake] = useState(1000);
  const [result, setResult] = useState<StakeCalcResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const parsed = odds.map(Number).filter((d) => Number.isFinite(d) && d > 1);
    if (parsed.length < 2) {
      setResult(null);
      setErr(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .calcStakes(parsed, stake)
        .then((r) => {
          if (!cancelled) {
            setResult(r);
            setErr(null);
          }
        })
        .catch(() => {
          if (!cancelled) setErr("Calculation failed.");
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [odds, stake]);

  const setAt = (i: number, v: string) =>
    setOdds((prev) => prev.map((o, j) => (j === i ? v : o)));

  return (
    <Card>
      <SectionTitle
        title="Arbitrage stake calculator"
        hint="Equal-profit sizing: sᵢ = S · (1/dᵢ) / B. Enter decimal odds for every outcome."
      />

      <div className="flex flex-col gap-2 mb-3">
        {/*
          Index is the right key here: these are positional slots
          (outcome 1, outcome 2...) whose VALUES change as you type.
          Keying by value would remount the input on every keystroke and
          take the caret with it.
        */}
        {odds.map((o, i) => (
          <div key={`outcome-${i}`} className="flex items-center gap-2">
            <span
              className="text-xs shrink-0 text-faint w-[62px]"
            >
              Outcome {i + 1}
            </span>
            <Input className="tabular" type="number" step="0.01" min="1.01" value={o} onChange={(e) => setAt(i, e.target.value)} aria-label={`Decimal odds for outcome ${i + 1}`} />
            {result && (
              <span
                className="tabular text-xs shrink-0 text-right w-[92px]"
              >
                {usd(result.stakes[i] ?? 0)}
              </span>
            )}
            {odds.length > 2 && (
              <Button size="sm" variant="outline" className="shrink-0" onClick={() => setOdds((p) => p.filter((_, j) => j !== i))} aria-label={`Remove outcome ${i + 1}`} >
                ✕
              </Button>
            )}
          </div>
        ))}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setOdds((p) => [...p, "3.00"])} >
            + Outcome
          </Button>
        </div>
      </div>

      <Field label="Total stake ($)">
        <Input className="tabular" type="number" min="1" value={stake} onChange={(e) => setStake(Number(e.target.value) || 0)} />
      </Field>

      {err && (
        <p className="text-xs mt-3 text-danger">
          {err}
        </p>
      )}

      {result && (
        <div
          className="mt-4 pt-3 border-t border-border"
        >
          <div
            className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg"
            style={{
              background: result.is_arbitrage
                ? "var(--positive-soft)"
                : "var(--neutral-soft)",
            }}
          >
            <span
              style={{
                color: result.is_arbitrage ? "var(--positive)" : "var(--muted-foreground)",
              }}
              aria-hidden
            >
              {result.is_arbitrage ? "✓" : "✕"}
            </span>
            <span className="text-[13px] font-medium">
              {result.is_arbitrage
                ? `Arbitrage: ${pct(result.margin)} guaranteed on turnover`
                : `No arbitrage — the book is ${result.overround_pct.toFixed(2)}% over`}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <Row label="Combined book (B)" value={result.book.toFixed(5)} />
            <Row label="Margin" value={pct(result.margin)} />
            <Row label="Overround" value={`${result.overround_pct.toFixed(3)}%`} />
            <Row label="Vig" value={`${result.vig_pct.toFixed(3)}%`} />
            <Row label="Total staked" value={usd(result.total_stake)} />
            <Row
              label="Guaranteed profit"
              value={usd(result.worst_case_profit)}
              tone={result.worst_case_profit >= 0 ? "positive" : "danger"}
            />
          </div>

          <div className="scroll-x mt-3">
            <Table className="w-full border-collapse text-[13px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Outcome</TableHead>
                  <TableHead className="text-right">Stake</TableHead>
                  <TableHead className="text-right">Payout</TableHead>
                  <TableHead className="text-right">Profit</TableHead>
                  <TableHead className="text-right">Fair prob</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {/* Positional: row i is outcome i's stake. */}
                {result.stakes.map((s, i) => (
                  <TableRow key={`stake-${i}`}>
                    <TableCell>#{i + 1} @ {odds[i]}</TableCell>
                    <TableCell className="tabular text-right">
                      {usd(s)}
                    </TableCell>
                    <TableCell className="tabular text-right">
                      {usd(result.payouts[i] ?? 0)}
                    </TableCell>
                    <TableCell
                      className={`tabular ${
                        (result.profit_by_outcome[i] ?? 0) >= 0
                          ? "text-positive"
                          : "text-danger"
                      }text-right`}
                    >
                      {usd(result.profit_by_outcome[i] ?? 0)}
                    </TableCell>
                    <TableCell
                      className="tabular text-right text-muted-foreground"
                    >
                      {pct(result.fair_probs[i] ?? 0, 1)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------- void adjustment */

function VoidCalculator() {
  const [margin, setMargin] = useState(2);
  const [voidRate, setVoidRate] = useState(3);
  const [voidLoss, setVoidLoss] = useState(30);
  const [turnovers, setTurnovers] = useState(100);
  const [result, setResult] = useState<VoidResult | null>(null);

  useEffect(() => {
    if (margin <= 0) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .calcVoid(margin / 100, voidRate / 100, voidLoss / 100, turnovers)
        .then((r) => !cancelled && setResult(r))
        .catch(() => {});
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [margin, voidRate, voidLoss, turnovers]);

  const retained = result?.edge_retained_pct ?? 100;
  const tone = retained < 50 ? "danger" : retained < 80 ? "caution" : "positive";

  return (
    <Card>
      <SectionTitle
        title="Void-adjusted edge"
        hint="An arbitrage is only risk-free if every leg settles. This is the number that decides whether a trade is worth doing."
      />

      <div className="grid grid-cols-2 gap-3 mb-4">
        <Field label="Nominal margin %">
          <Input className="tabular" type="number" step="0.1" min="0.01" value={margin} onChange={(e) => setMargin(Number(e.target.value) || 0)} />
        </Field>
        <Field label="Void rate %">
          <Input className="tabular" type="number" step="0.5" min="0" max="99" value={voidRate} onChange={(e) => setVoidRate(Number(e.target.value) || 0)} />
        </Field>
        <Field label="Loss on void %" hint="of the stake">
          <Input className="tabular" type="number" step="5" min="0" max="100" value={voidLoss} onChange={(e) => setVoidLoss(Number(e.target.value) || 0)} />
        </Field>
        <Field label="Turnovers / year">
          <Input className="tabular" type="number" step="10" min="1" value={turnovers} onChange={(e) => setTurnovers(Number(e.target.value) || 1)} />
        </Field>
      </div>

      {result && (
        <div className="border-t border-border pt-[12px]">
          <div className="mb-3">
            <div className="flex justify-between items-baseline mb-1.5">
              <span className="text-xs text-muted-foreground">
                Edge retained after voids
              </span>
              <span
                className="tabular text-sm font-semibold"
                style={{ color: `var(--${tone})` }}
              >
                {retained.toFixed(0)}%
              </span>
            </div>
            <div
              className="h-2 rounded-full overflow-hidden bg-neutral-soft"
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(0, Math.min(100, retained))}%`,
                  background: `var(--${tone})`,
                }}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <Row label="Nominal margin" value={pct(result.nominal_margin)} />
            <Row
              label="Effective margin"
              value={pct(result.effective_margin)}
              tone={result.effective_margin > 0 ? "positive" : "danger"}
            />
            <Row
              label="Kelly fraction"
              value={
                result.kelly_arb_unbounded
                  ? "unbounded"
                  : `${result.kelly_arb_fraction!.toFixed(2)}×`
              }
            />
            <Row
              label="Annualised (simple)"
              value={pct(result.annualised_simple, 1)}
            />
          </div>

          {result.effective_margin <= 0 && (
            <p
              className="text-xs mt-3 p-2.5 rounded-lg bg-danger-soft text-danger"
            >
              At this void rate the strategy loses money. The expected value has
              to be positive <em>after</em> voids, not before them.
            </p>
          )}
          {result.kelly_arb_unbounded && result.effective_margin > 0 && (
            <p className="text-xs mt-3 text-muted-foreground">
              With no cost to a voided leg there is nothing to lose, so Kelly
              places no bound at all. Bankroll and per-venue concentration
              limits are the only things governing size here.
            </p>
          )}
          {!result.kelly_arb_unbounded &&
            result.kelly_arb_fraction! > 1 &&
            result.effective_margin > 0 && (
              <p className="text-xs mt-3 text-muted-foreground">
                Kelly says stake more than the whole bankroll, which you cannot
                do. Bankroll, not risk aversion, is the binding constraint here
                — so per-venue concentration limits are what actually govern
                sizing.
              </p>
            )}
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ Kelly */

function KellyCalculator() {
  const [prob, setProb] = useState(55);
  const [odds, setOdds] = useState(2.0);
  const [fraction, setFraction] = useState(25);
  const [result, setResult] = useState<KellyResult | null>(null);

  useEffect(() => {
    if (prob <= 0 || prob >= 100 || odds <= 1) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .calcKelly(prob / 100, odds, fraction / 100)
        .then((r) => !cancelled && setResult(r))
        .catch(() => {});
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [prob, odds, fraction]);

  return (
    <Card>
      <SectionTitle
        title="Kelly stake (value betting)"
        hint="f* = (p·d − 1)/(d − 1). Needs a genuine probability estimate, so it applies to one-legged value bets rather than to arbitrage."
      />

      <div className="grid grid-cols-3 gap-3 mb-4">
        <Field label="True prob %">
          <Input className="tabular" type="number" step="1" min="1" max="99" value={prob} onChange={(e) => setProb(Number(e.target.value) || 0)} />
        </Field>
        <Field label="Decimal odds">
          <Input className="tabular" type="number" step="0.05" min="1.01" value={odds} onChange={(e) => setOdds(Number(e.target.value) || 0)} />
        </Field>
        <Field label="Kelly %" hint="fractional">
          <Input className="tabular" type="number" step="5" min="1" max="100" value={fraction} onChange={(e) => setFraction(Number(e.target.value) || 0)} />
        </Field>
      </div>

      {result && (
        <div className="border-t border-border pt-[12px]">
          <div
            className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg"
            style={{
              background: result.is_value_bet
                ? "var(--positive-soft)"
                : "var(--neutral-soft)",
            }}
          >
            <span
              style={{
                color: result.is_value_bet ? "var(--positive)" : "var(--muted-foreground)",
              }}
              aria-hidden
            >
              {result.is_value_bet ? "✓" : "✕"}
            </span>
            <span className="text-[13px] font-medium">
              {result.is_value_bet
                ? `Value bet: ${pct(result.edge)} edge per unit staked`
                : "No value — the price is worse than fair"}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <Row label="Fair odds" value={num(result.fair_odds, 3)} />
            <Row label="Edge" value={pct(result.edge)} />
            <Row
              label="Full Kelly"
              value={`${pct(result.kelly_fraction)} · ${usd(result.kelly_stake, 0)}`}
            />
            <Row
              label={`${fraction}% Kelly`}
              value={`${pct(result.fractional_kelly)} · ${usd(result.fractional_stake, 0)}`}
              tone="positive"
            />
          </div>
          <p className="text-xs mt-3 text-faint">
            Fractional Kelly trades a little growth for much less drawdown.
            Probability estimates are noisy, and over-estimating edge past the
            Kelly point makes growth collapse rather than merely slow.
          </p>
        </div>
      )}
    </Card>
  );
}

/* -------------------------------------------------------------- converter */

function OddsConverter() {
  const [value, setValue] = useState("2.00");
  const [format, setFormat] = useState("decimal");
  const [result, setResult] = useState<ConvertResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const v = Number(value);
    if (!Number.isFinite(v)) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .calcConvert(v, format)
        .then((r) => {
          if (!cancelled) {
            setResult(r);
            setErr(null);
          }
        })
        .catch(() => {
          if (!cancelled) setErr("Not a valid price in that format.");
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [value, format]);

  return (
    <Card>
      <SectionTitle
        title="Odds converter"
        hint="Prediction markets quote a contract price; sportsbooks quote odds. Same thing: a $0.40 contract paying $1 is decimal 2.50."
      />

      <div className="flex gap-2 mb-4">
        <Input className="tabular" type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Value to convert" />
        <NativeSelect className="w-[148px]" value={format} onChange={(e) => setFormat(e.target.value)} aria-label="Input format" >
          <option value="decimal">Decimal</option>
          <option value="american">American</option>
          <option value="probability">Probability</option>
        </NativeSelect>
      </div>

      {err && (
        <p className="text-xs text-danger">
          {err}
        </p>
      )}

      {result && !err && (
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "Decimal", value: num(result.decimal, 3) },
            {
              label: "American",
              value:
                result.american > 0
                  ? `+${result.american.toFixed(0)}`
                  : result.american.toFixed(0),
            },
            { label: "Probability", value: pct(result.probability, 2) },
            { label: "Contract price", value: `$${result.contract_price.toFixed(4)}` },
          ].map((f) => (
            <div
              key={f.label}
              className="rounded-lg px-3 py-2.5 bg-muted"
            >
              <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint mb-[2px]">
                {f.label}
              </div>
              <div className="tabular text-base font-semibold">{f.value}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "positive" | "danger" | "caution";
}) {
  return (
    <>
      <span className="text-muted-foreground">{label}</span>
      <span
        className="tabular"
        style={{ textAlign: "right", color: tone ? `var(--${tone})` : "var(--foreground)" }}
      >
        {value}
      </span>
    </>
  );
}
