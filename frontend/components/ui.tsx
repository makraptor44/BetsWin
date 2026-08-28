"use client";

import type { ReactNode } from "react";

import { FLAG_LABEL, FLAG_SEVERITY, VENUE_LABEL, venueColor } from "@/lib/format";
import type { RiskFlag } from "@/lib/types";

/* --------------------------------------------------------------- surfaces */

export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div className={`card ${padded ? "p-4" : ""} ${className}`}>{children}</div>
  );
}

export function SectionTitle({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-3">
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
        {hint && (
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            {hint}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone,
  title,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "positive" | "caution" | "danger";
  title?: string;
}) {
  const color = tone ? `var(--${tone})` : "var(--text)";
  return (
    <div className="card p-3.5" title={title}>
      <div className="label" style={{ marginBottom: 4 }}>
        {label}
      </div>
      <div className="mono text-xl font-semibold leading-tight" style={{ color }}>
        {value}
      </div>
      {sub && (
        <div className="text-xs mt-1" style={{ color: "var(--text-faint)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ chips */

export function VenueChip({ venue }: { venue: string }) {
  return (
    <span
      className="chip"
      style={{
        background: "color-mix(in srgb, currentColor 13%, transparent)",
        color: venueColor(venue),
      }}
    >
      {VENUE_LABEL[venue] ?? venue}
    </span>
  );
}

export function FlagChip({ flag }: { flag: RiskFlag }) {
  const severity = FLAG_SEVERITY[flag] ?? "caution";
  return (
    <span className={`chip chip-${severity}`} title={FLAG_LABEL[flag]}>
      {FLAG_LABEL[flag] ?? flag}
    </span>
  );
}

export function ConfidenceBar({
  value,
  showLabel = true,
}: {
  value: number;
  showLabel?: boolean;
}) {
  const tone = value >= 75 ? "positive" : value >= 50 ? "caution" : "danger";
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1.5 rounded-full overflow-hidden shrink-0"
        style={{ width: 44, background: "var(--neutral-soft)" }}
        role="meter"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Confidence"
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.max(2, value)}%`,
            background: `var(--${tone})`,
          }}
        />
      </div>
      {showLabel && (
        <span className="mono text-xs" style={{ color: "var(--text-muted)" }}>
          {value}
        </span>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- states */

export function EmptyState({
  title,
  body,
  action,
  icon = "○",
}: {
  title: string;
  body: string;
  action?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-14">
      <div
        className="text-2xl mb-3 flex items-center justify-center rounded-full"
        style={{
          width: 44,
          height: 44,
          background: "var(--bg-sunken)",
          color: "var(--text-faint)",
        }}
        aria-hidden
      >
        {icon}
      </div>
      <h3 className="text-sm font-semibold mb-1.5">{title}</h3>
      <p
        className="text-xs max-w-md leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {body}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      className="card p-4 flex items-start gap-3"
      style={{ borderColor: "var(--danger)", background: "var(--danger-soft)" }}
      role="alert"
    >
      <span style={{ color: "var(--danger)" }} aria-hidden>
        ⚠
      </span>
      <div className="flex-1">
        <div className="text-sm font-medium" style={{ color: "var(--danger)" }}>
          {message}
        </div>
        {onRetry && (
          <button className="btn btn-sm mt-2.5" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 34, opacity: 1 - i * 0.12 }} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ misc */

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span title={text} style={{ cursor: "help", borderBottom: "1px dotted var(--text-faint)" }}>
      {children}
    </span>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className="relative rounded-full shrink-0 transition-colors"
      style={{
        width: 34,
        height: 19,
        background: checked ? "var(--accent)" : "var(--border-strong)",
        border: "none",
        cursor: "pointer",
      }}
    >
      <span
        className="absolute rounded-full transition-transform"
        style={{
          width: 15,
          height: 15,
          top: 2,
          left: 2,
          background: "#fff",
          transform: checked ? "translateX(15px)" : "translateX(0)",
        }}
      />
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && (
        <p className="text-xs mt-1.5" style={{ color: "var(--text-faint)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}
