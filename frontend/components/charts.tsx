"use client";

/**
 * Small SVG charts.
 *
 * Hand-rolled rather than pulled from a charting library: the shapes needed here
 * are simple, and every chart inherits the theme tokens directly so light and
 * dark stay consistent without a second theming layer.
 */

import { useId } from "react";

export interface Point {
  label: string;
  value: number;
}

const AXIS = "var(--border)";
const MUTED = "var(--text-faint)";

/* ------------------------------------------------------------- bar chart */

export function BarChart({
  data,
  height = 160,
  color = "var(--accent)",
  valueFormat = (v: number) => v.toFixed(0),
  emptyMessage = "No data yet",
}: {
  data: Point[];
  height?: number;
  color?: string;
  valueFormat?: (v: number) => string;
  emptyMessage?: string;
}) {
  if (!data.length) return <ChartEmpty message={emptyMessage} height={height} />;

  const max = Math.max(...data.map((d) => d.value), 1);
  const barW = 100 / data.length;

  return (
    <div style={{ width: "100%" }}>
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block" }}
        role="img"
        aria-label={`Bar chart: ${data.map((d) => `${d.label} ${valueFormat(d.value)}`).join(", ")}`}
      >
        {data.map((d, i) => {
          const h = (d.value / max) * (height - 20);
          return (
            <rect
              key={d.label + i}
              x={i * barW + barW * 0.18}
              y={height - h}
              width={barW * 0.64}
              height={Math.max(h, d.value > 0 ? 1.5 : 0)}
              fill={color}
              rx="1"
            >
              <title>{`${d.label}: ${valueFormat(d.value)}`}</title>
            </rect>
          );
        })}
        <line x1="0" y1={height} x2="100" y2={height} stroke={AXIS} strokeWidth="0.5" />
      </svg>
      <div className="flex justify-between mt-1.5 text-[10px]" style={{ color: MUTED }}>
        <span>{data[0].label}</span>
        {data.length > 2 && <span>{data[Math.floor(data.length / 2)].label}</span>}
        <span>{data[data.length - 1].label}</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ line chart */

export function LineChart({
  data,
  height = 180,
  color = "var(--accent)",
  fill = true,
  valueFormat = (v: number) => v.toFixed(2),
  zeroLine = false,
  emptyMessage = "No data yet",
}: {
  data: Point[];
  height?: number;
  color?: string;
  fill?: boolean;
  valueFormat?: (v: number) => string;
  zeroLine?: boolean;
  emptyMessage?: string;
}) {
  const gradId = useId().replace(/:/g, "");
  if (data.length < 2) return <ChartEmpty message={emptyMessage} height={height} />;

  const values = data.map((d) => d.value);
  // The real extremes are what the caption reports; the padded values below
  // only shape the plot area. Showing the padding would claim, for instance,
  // that a count series reached -58.
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);

  let min = zeroLine ? Math.min(dataMin, 0) : dataMin;
  let max = zeroLine ? Math.max(dataMax, 0) : dataMax;
  if (max === min) {
    max += 1;
    min -= 1;
  }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;

  const W = 100;
  const H = height;
  const x = (i: number) => (i / (data.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / (max - min)) * H;

  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(d.value).toFixed(2)}`).join(" ");
  const area = `${path} L${W},${H} L0,${H} Z`;
  const zeroY = y(0);

  return (
    <div style={{ width: "100%" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block", overflow: "visible" }}
        role="img"
        aria-label={`Line chart from ${valueFormat(data[0].value)} to ${valueFormat(data[data.length - 1].value)}`}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {zeroLine && zeroY >= 0 && zeroY <= H && (
          <line
            x1="0"
            y1={zeroY}
            x2={W}
            y2={zeroY}
            stroke={AXIS}
            strokeWidth="0.5"
            strokeDasharray="2 2"
          />
        )}
        {fill && <path d={area} fill={`url(#${gradId})`} />}
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth="1.4"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      <div className="flex justify-between mt-1.5 text-[10px]" style={{ color: MUTED }}>
        <span>{data[0].label}</span>
        <span className="mono">
          {valueFormat(dataMin)} … {valueFormat(dataMax)}
        </span>
        <span>{data[data.length - 1].label}</span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- sparkline */

export function Sparkline({
  values,
  width = 90,
  height = 22,
  color = "var(--accent)",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length < 2) return <div style={{ width, height }} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * width},${height - ((v - min) / span) * height}`)
    .join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }} aria-hidden>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.3"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* ------------------------------------------------------------- histogram */

export function Histogram({
  buckets,
  height = 150,
  emptyMessage = "No distribution yet",
}: {
  buckets: Array<{ from: number; to: number; count: number }>;
  height?: number;
  emptyMessage?: string;
}) {
  const nonEmpty = buckets.some((b) => b.count > 0);
  if (!buckets.length || !nonEmpty) return <ChartEmpty message={emptyMessage} height={height} />;

  const max = Math.max(...buckets.map((b) => b.count), 1);
  const barW = 100 / buckets.length;

  return (
    <div style={{ width: "100%" }}>
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block" }}
        role="img"
        aria-label="Distribution of arbitrage margins"
      >
        {buckets.map((b, i) => {
          const h = (b.count / max) * (height - 16);
          // Colour by risk, not by size: the fat tail is the suspicious end.
          const color =
            b.from >= 0.05 ? "var(--danger)" : b.from >= 0.02 ? "var(--caution)" : "var(--accent)";
          return (
            <rect
              key={i}
              x={i * barW + barW * 0.14}
              y={height - h}
              width={barW * 0.72}
              height={Math.max(h, b.count > 0 ? 1.5 : 0)}
              fill={color}
              rx="1"
            >
              <title>{`${(b.from * 100).toFixed(1)}%–${(b.to * 100).toFixed(1)}%: ${b.count}`}</title>
            </rect>
          );
        })}
        <line x1="0" y1={height} x2="100" y2={height} stroke={AXIS} strokeWidth="0.5" />
      </svg>
      <div className="flex justify-between mt-1.5 text-[10px]" style={{ color: MUTED }}>
        <span>{(buckets[0].from * 100).toFixed(1)}%</span>
        <span>margin</span>
        <span>{(buckets[buckets.length - 1].to * 100).toFixed(1)}%+</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ proportions */

export function ProportionBar({
  segments,
  height = 8,
}: {
  segments: Array<{ label: string; value: number; color: string }>;
  height?: number;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (!total) return null;
  return (
    <div>
      <div
        className="flex rounded-full overflow-hidden"
        style={{ height, background: "var(--bg-sunken)" }}
      >
        {segments.map((s) => (
          <div
            key={s.label}
            style={{ width: `${(s.value / total) * 100}%`, background: s.color }}
            title={`${s.label}: ${s.value}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
        {segments.map((s) => (
          <span key={s.label} className="flex items-center gap-1.5 text-xs">
            <span
              className="rounded-full shrink-0"
              style={{ width: 7, height: 7, background: s.color }}
            />
            <span style={{ color: "var(--text-muted)" }}>{s.label}</span>
            <span className="mono" style={{ color: "var(--text)" }}>
              {s.value}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function ChartEmpty({ message, height }: { message: string; height: number }) {
  return (
    <div
      className="flex items-center justify-center text-xs rounded"
      style={{ height, color: "var(--text-faint)", background: "var(--bg-sunken)" }}
    >
      {message}
    </div>
  );
}
