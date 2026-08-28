"use client";

import { useState } from "react";

import { BarChart, Histogram, LineChart, ProportionBar } from "@/components/charts";
import { Card, EmptyState, ErrorState, Field, SectionTitle, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { KIND_LABEL, pct, usd, usdCompact, venueColor } from "@/lib/format";
import type { ArbKind, BacktestResult } from "@/lib/types";
import { useAsync } from "@/lib/useEngine";

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const { data, loading, error, reload } = useAsync(
    () => api.analytics(days),
    [days],
  );

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Analytics</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
            What the scanner has found over time, and what it would actually have
            paid once voided legs are priced in.
          </p>
        </div>
        <select
          className="input"
          style={{ width: 150 }}
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          aria-label="Time window"
        >
          <option value={1}>Last 24 hours</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </header>

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && <Skeleton rows={6} />}

      {data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat
              label="Detected"
              value={data.stored.total_detected}
              sub={`over ${days} day${days === 1 ? "" : "s"}`}
            />
            <Stat
              label="Average margin"
              value={pct(data.stored.avg_margin)}
              sub={`best ${pct(data.stored.max_margin)}`}
            />
            <Stat
              label="Theoretical profit"
              value={usd(data.stored.theoretical_profit)}
              sub={`on ${usdCompact(data.stored.theoretical_turnover)} turnover`}
              tone={data.stored.theoretical_profit > 0 ? "positive" : undefined}
              title="Before voids. The backtest below is the honest number."
            />
            <Stat
              label="Avg confidence"
              value={data.stored.avg_confidence.toFixed(0)}
              sub="0–100 quality score"
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card>
              <SectionTitle
                title="Margin distribution"
                hint="Most real edge is small. The coloured tail is where bad data lives."
              />
              <Histogram
                buckets={data.margin_histogram}
                emptyMessage="No opportunities stored in this window yet"
              />
            </Card>

            <Card>
              <SectionTitle
                title="Opportunities per day"
                hint="Detection volume over the window"
              />
              <BarChart
                data={data.stored.by_day.map((d) => ({
                  label: d.day.slice(5),
                  value: d.n,
                }))}
                emptyMessage="No daily history yet"
              />
            </Card>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card>
              <SectionTitle title="Live now, by type" />
              {Object.keys(data.live.by_kind).length > 0 ? (
                <ProportionBar
                  segments={Object.entries(data.live.by_kind).map(([k, v], i) => ({
                    label: KIND_LABEL[k as ArbKind] ?? k,
                    value: v,
                    color: [
                      "var(--accent)",
                      "var(--positive)",
                      "var(--caution)",
                      "var(--venue-polymarket)",
                      "var(--venue-kalshi)",
                    ][i % 5],
                  }))}
                />
              ) : (
                <p className="text-xs" style={{ color: "var(--text-faint)" }}>
                  Nothing live at the moment.
                </p>
              )}

              <div className="mt-4">
                <SectionTitle title="Live now, by venue" />
                {Object.keys(data.live.by_venue).length > 0 ? (
                  <ProportionBar
                    segments={Object.entries(data.live.by_venue).map(([k, v]) => ({
                      label: k,
                      value: v,
                      color: venueColor(k),
                    }))}
                  />
                ) : (
                  <p className="text-xs" style={{ color: "var(--text-faint)" }}>
                    Nothing live at the moment.
                  </p>
                )}
              </div>
            </Card>

            <Card>
              <SectionTitle
                title="Scan performance"
                hint="Events processed per cycle"
              />
              <LineChart
                data={data.recent_scans.map((s, i) => ({
                  label: `${i}`,
                  value: s.events_scanned,
                }))}
                valueFormat={(v) => v.toFixed(0)}
                emptyMessage="No scan history yet"
              />
              <div className="grid grid-cols-3 gap-2 mt-3">
                <MiniStat
                  label="Cycles"
                  value={String(data.recent_scans.length)}
                />
                <MiniStat
                  label="Avg duration"
                  value={
                    data.recent_scans.length
                      ? `${(
                          data.recent_scans.reduce((s, x) => s + x.duration, 0) /
                          data.recent_scans.length
                        ).toFixed(1)}s`
                      : "—"
                  }
                />
                <MiniStat
                  label="Found"
                  value={String(
                    data.recent_scans.reduce((s, x) => s + x.new_arbs, 0),
                  )}
                />
              </div>
            </Card>
          </div>

          {data.stored.by_kind.length > 0 && (
            <Card padded={false}>
              <div className="p-4 pb-0">
                <SectionTitle title="By opportunity type" />
              </div>
              <div className="scroll-x">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th style={{ textAlign: "right" }}>Count</th>
                      <th style={{ textAlign: "right" }}>Avg margin</th>
                      <th style={{ textAlign: "right" }}>Theoretical profit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.stored.by_kind.map((k) => (
                      <tr key={k.kind}>
                        <td>{KIND_LABEL[k.kind as ArbKind] ?? k.kind}</td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {k.n}
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {pct(k.avg_margin)}
                        </td>
                        <td
                          className="mono num-positive"
                          style={{ textAlign: "right" }}
                        >
                          {usd(k.profit)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <Backtester />
        </>
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="rounded-lg px-2.5 py-2"
      style={{ background: "var(--bg-sunken)" }}
    >
      <div className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-faint)" }}>
        {label}
      </div>
      <div className="mono text-sm font-semibold">{value}</div>
    </div>
  );
}

function Backtester() {
  const [days, setDays] = useState(30);
  const [minMargin, setMinMargin] = useState(0.5);
  const [voidRate, setVoidRate] = useState(2);
  const [voidLoss, setVoidLoss] = useState(30);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.backtest({
        days,
        min_margin: minMargin / 100,
        max_margin: 0.5,
        void_rate: voidRate / 100,
        void_loss: voidLoss / 100,
        simulations: 600,
      });
      setResult(r);
    } catch {
      setErr("Backtest failed. Is the engine running?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <SectionTitle
        title="Backtest"
        hint="Replays stored opportunities under a void model. A leg that gets voided leaves the rest of the set unhedged, which is what turns a nominal edge into a real one."
        action={
          <button className="btn btn-primary btn-sm" onClick={run} disabled={busy}>
            {busy ? "Running…" : "Run backtest"}
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <Field label="Window (days)">
          <input
            className="input mono"
            type="number"
            min={1}
            max={365}
            value={days}
            onChange={(e) => setDays(Number(e.target.value) || 1)}
          />
        </Field>
        <Field label="Min margin %">
          <input
            className="input mono"
            type="number"
            step="0.1"
            min={0}
            value={minMargin}
            onChange={(e) => setMinMargin(Number(e.target.value) || 0)}
          />
        </Field>
        <Field label="Void rate %" hint="chance a leg is voided">
          <input
            className="input mono"
            type="number"
            step="0.5"
            min={0}
            max={100}
            value={voidRate}
            onChange={(e) => setVoidRate(Number(e.target.value) || 0)}
          />
        </Field>
        <Field label="Void loss %" hint="of stake, when it happens">
          <input
            className="input mono"
            type="number"
            step="5"
            min={0}
            max={100}
            value={voidLoss}
            onChange={(e) => setVoidLoss(Number(e.target.value) || 0)}
          />
        </Field>
      </div>

      {err && <ErrorState message={err} />}

      {!result && !err && (
        <EmptyState
          icon="⟳"
          title="No backtest run yet"
          body="Run one to see what the stored opportunities would have returned once voids are modelled. You need some scan history first — leave the scanner running for a while."
        />
      )}

      {result && result.n === 0 && (
        <EmptyState
          icon="○"
          title="Nothing to replay"
          body="No stored opportunities match these filters. Widen the window or lower the margin floor, or let the scanner accumulate more history."
        />
      )}

      {result && result.n > 0 && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat
              label="Naive profit"
              value={usd(result.naive_profit)}
              sub={`${pct(result.naive_yield)} of turnover`}
            />
            <Stat
              label="After voids"
              value={usd(result.expected_profit)}
              sub={`${pct(result.expected_yield)} of turnover`}
              tone={result.expected_profit > 0 ? "positive" : "danger"}
            />
            <Stat
              label="5th percentile"
              value={usd(result.p5_profit)}
              sub="a bad run"
              tone={result.p5_profit < 0 ? "danger" : undefined}
            />
            <Stat
              label="Chance of loss"
              value={pct(result.prob_loss, 1)}
              sub={`across ${result.n} opportunities`}
              tone={result.prob_loss > 0.05 ? "caution" : "positive"}
            />
          </div>

          {result.equity_curve.length > 1 && (
            <div className="mt-4">
              <SectionTitle
                title="Equity curve"
                hint="One simulated path, in detection order. The drawdowns are voided legs."
              />
              <LineChart
                data={result.equity_curve.map((p, i) => ({
                  label: i === 0 ? "start" : `${i}`,
                  value: p.equity,
                }))}
                color={
                  result.expected_profit >= 0 ? "var(--positive)" : "var(--danger)"
                }
                valueFormat={(v) => usd(v, 0)}
                zeroLine
                height={200}
              />
            </div>
          )}

          {result.notes.length > 0 && (
            <ul
              className="flex flex-col gap-2 mt-4 pt-3 pl-0 m-0"
              style={{ listStyle: "none", borderTop: "1px solid var(--border)" }}
            >
              {result.notes.map((n, i) => (
                <li
                  key={i}
                  className="text-xs flex gap-2 leading-relaxed"
                  style={{ color: "var(--text-muted)" }}
                >
                  <span style={{ color: "var(--caution)" }} aria-hidden>
                    •
                  </span>
                  {n}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
