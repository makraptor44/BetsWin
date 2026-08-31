"use client";

/**
 * Small SVG charts.
 *
 * Hand-rolled rather than pulled from a charting library: the shapes needed here
 * are simple, and every chart inherits the theme tokens directly so light and
 * dark stay consistent without a second theming layer.
 */

import { useId } from "react";
import {
  Area,
  Bar,
  BarChart as RBarChart,
  CartesianGrid,
  Line,
  LineChart as RLineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface Point {
  label: string;
  value: number;
}

const AXIS = "var(--border)";

/**
 * One tooltip for every chart here.
 *
 * Recharts' default is a white card with its own typography, which on a themed
 * dark dashboard looks like a foreign object. This one is built from the same
 * surface tokens as everything else, so it inherits light and dark for free.
 */
function ChartTooltip({
  active,
  payload,
  label,
  valueFormat,
}: {
  active?: boolean;
  payload?: Array<{ value?: number | string }>;
  label?: string | number;
  valueFormat: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  const raw = payload[0]?.value;
  const value = typeof raw === "number" ? valueFormat(raw) : String(raw ?? "");
  return (
    <div
      className="rounded-md border border-border-strong bg-popover px-2.5 py-1.5 text-[11px]"
      style={{ boxShadow: "var(--shadow-overlay)" }}
    >
      <div className="num font-medium text-foreground">{value}</div>
      {label !== undefined && label !== "" && (
        <div className="mt-0.5 text-faint">{String(label)}</div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- bar chart */

export function BarChart({
  data,
  height = 160,
  color = "var(--brand)",
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

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <RBarChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={AXIS} strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: "var(--faint)" }}
            axisLine={{ stroke: AXIS }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            tickFormatter={valueFormat}
            width={40}
            tick={{ fontSize: 10, fill: "var(--faint)" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: "var(--brand-soft)" }}
            content={<ChartTooltip valueFormat={valueFormat} />}
          />
          {/* Capped, because Recharts divides the full width between however many
              bars there are: a window with a single day in it produced one bar
              spanning the entire chart, which reads as a rendering fault rather
              than as one day of data. */}
          <Bar
            dataKey="value"
            fill={color}
            radius={[2, 2, 0, 0]}
            maxBarSize={44}
            animationDuration={480}
          />
        </RBarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------ line chart */

export function LineChart({
  data,
  height = 180,
  color = "var(--brand)",
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

  // The domain is padded so the line does not graze the frame, but the padding
  // is never shown on the axis: a count series must not appear to reach -58
  // because the plot area needed headroom.
  const values = data.map((d) => d.value);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  let min = zeroLine ? Math.min(dataMin, 0) : dataMin;
  let max = zeroLine ? Math.max(dataMax, 0) : dataMax;
  if (max === min) {
    max += 1;
    min -= 1;
  }
  const pad = (max - min) * 0.08;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <RLineChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.24} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={AXIS} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" hide />
        <YAxis
          domain={[min - pad, max + pad]}
          tickFormatter={valueFormat}
          width={52}
          tick={{ fontSize: 10, fill: "var(--faint)" }}
          axisLine={false}
          tickLine={false}
        />
        {zeroLine && <ReferenceLine y={0} stroke={AXIS} strokeWidth={1} />}
        <Tooltip
          cursor={{ stroke: AXIS, strokeWidth: 1 }}
          content={<ChartTooltip valueFormat={valueFormat} />}
        />
        {fill && (
          <Area
            type="monotone"
            dataKey="value"
            stroke="none"
            fill={`url(#${gradId})`}
            isAnimationActive={false}
          />
        )}
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.8}
          dot={false}
          activeDot={{ r: 3.5, strokeWidth: 0 }}
          animationDuration={520}
        />
      </RLineChart>
    </ResponsiveContainer>
  );
}

export function Sparkline({
  values,
  width = 90,
  height = 22,
  color = "var(--brand)",
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
    <svg className="block" width={width} height={height} aria-hidden>
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
    <div className="w-full">
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
            b.from >= 0.05 ? "var(--danger)" : b.from >= 0.02 ? "var(--caution)" : "var(--brand)";
          return (
            <rect
              key={b.from}
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
      <div className="flex justify-between mt-1.5 text-[10px] text-muted-foreground">
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
        className="flex rounded-full overflow-hidden bg-muted"
        style={{ height }}
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
              className="rounded-full shrink-0 w-[7px] h-[7px]" style={{ background: s.color }}
            />
            <span className="text-muted-foreground">{s.label}</span>
            <span className="tabular text-foreground">
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
      className="flex items-center justify-center text-xs rounded text-faint bg-muted"
      style={{ height }}
    >
      {message}
    </div>
  );
}
