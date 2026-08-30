"use client";

/**
 * Project-specific presentation, built on shadcn/ui.
 *
 * Everything generic -- surfaces, buttons, inputs, badges, tables -- comes from
 * `components/ui/*`, which is shadcn on Radix primitives. What lives here is
 * only the vocabulary this application adds on top: a venue's identity, an
 * execution zone, a risk flag, a confidence meter.
 *
 * These used to be hand-rolled `.card` / `.chip` / `.btn` classes over a
 * bespoke token set, which is a component library with none of the
 * accessibility work done.
 */

import type { CSSProperties, ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card as ShadCard, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton as ShadSkeleton } from "@/components/ui/skeleton";
import {
  FLAG_LABEL,
  FLAG_SEVERITY,
  VENUE_LABEL,
  ZONE_CURRENCY,
  ZONE_LABEL,
  ZONE_SHORT,
  venueColor,
} from "@/lib/format";
import type { RiskFlag, ZoneKey } from "@/lib/types";
import { AnimatedNumber, Sparkline, useTick } from "@/components/motion";
import { cn } from "@/lib/utils";

/* --------------------------------------------------------------- surfaces */

export function Card({
  children,
  className,
  padded = true,
  raised = false,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  /** For a surface that sits above the page rather than in it -- a detail
   *  panel, a modal body. Ordinary cards stay flat: a page of drop shadows
   *  reads as a slide deck. */
  raised?: boolean;
}) {
  return (
    <ShadCard
      className={cn("gap-0 overflow-hidden py-0 shadow-none", className)}
      style={{ boxShadow: raised ? "var(--shadow-raised)" : "var(--shadow-flat)" }}
    >
      {padded ? <CardContent className="p-4 sm:p-5">{children}</CardContent> : children}
    </ShadCard>
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
    <div className="mb-3.5 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-[14px] font-semibold tracking-[-0.02em]">{title}</h2>
        {hint && (
          <p className="mt-1 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">
            {hint}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Tone is reserved for risk, never for size. See the note in globals.css. */
const TONE_TEXT = {
  positive: "text-positive",
  caution: "text-caution",
  danger: "text-danger",
} as const;

const TONE_RULE = {
  positive: "bg-positive",
  caution: "bg-caution",
  danger: "bg-danger",
} as const;

/**
 * A headline figure.
 *
 * The number is the largest thing in the tile and sits in the mono face, so a
 * row of stats forms a column of digits that can be scanned rather than read.
 * The label sits above it small and quiet; a tile whose caption competes with
 * its number has no hierarchy at all. Tone shows as a rule down the left edge
 * as well as on the figure, because colour alone is not a signal everyone
 * receives.
 */
export function Stat({
  label,
  value,
  sub,
  tone,
  title,
  animate,
  format,
  trend,
  style,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: keyof typeof TONE_TEXT;
  title?: string;
  /** Carries the --i stagger index when the tile sits in a `.stagger` group. */
  style?: CSSProperties;
  /** Numeric value to tween to. When given, it replaces `value` on screen. */
  animate?: number;
  /** Required alongside `animate` -- how to render each intermediate frame. */
  format?: (n: number) => string;
  /** A short recent history, drawn as a trend line behind the figure. */
  trend?: number[];
}) {
  const tick = useTick(animate);

  return (
    <ShadCard
      className="lift relative gap-0 overflow-hidden py-0 shadow-none"
      style={{ boxShadow: "var(--shadow-flat)", ...style }}
      title={title}
    >
      {tone && (
        <span
          aria-hidden
          className={cn("absolute inset-y-0 left-0 w-[3px]", TONE_RULE[tone])}
        />
      )}

      {/* The trend line sits behind the figure at low opacity rather than beside
          it. A sparkline given its own column makes the tile about the chart;
          here it is background texture that answers "which way" without
          competing with the number that answers "how much". */}
      {trend && trend.length > 1 && (
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 bottom-0 h-10 opacity-[0.22]",
            tone ? TONE_TEXT[tone] : "text-brand",
          )}
        >
          <Sparkline points={trend} width={220} height={40} className="h-full w-full" />
        </span>
      )}

      <CardContent className="relative p-3.5 sm:p-4">
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.075em] text-faint">
          {label}
        </div>
        {/* Keyed on the tick so the highlight restarts on every change; a class
            toggled on a timer drifts out of sync with the data it describes. */}
        <div
          key={tick}
          className={cn(
            "num mt-1.5 inline-block rounded px-0.5 text-[26px] font-medium leading-none",
            tick > 0 && "tick",
            tone ? TONE_TEXT[tone] : "text-foreground",
          )}
        >
          {animate !== undefined && format ? (
            <AnimatedNumber value={animate} format={format} />
          ) : (
            value
          )}
        </div>
        {sub && (
          <div className="mt-2 text-[11.5px] leading-snug text-faint">{sub}</div>
        )}
      </CardContent>
    </ShadCard>
  );
}

/* ------------------------------------------------------------------ chips */

export function VenueChip({ venue }: { venue: string }) {
  return (
    <Badge
      variant="outline"
      className="border-current/25 bg-current/10 font-semibold"
      // The venue's identity colour is data, not a fixed palette entry.
      style={{ color: venueColor(venue) }}
    >
      {VENUE_LABEL[venue] ?? venue}
    </Badge>
  );
}

/**
 * Execution zone.
 *
 * Deliberately neutral-coloured. The zone is not a quality signal -- it says
 * where a trade can be placed from, not how good it is, and the semantic colour
 * ramp is reserved for risk.
 */
export function ZoneChip({ zone, short = false }: { zone: ZoneKey; short?: boolean }) {
  if (!zone || zone === "unknown") return null;
  const currency = ZONE_CURRENCY[zone];
  return (
    <Badge
      variant="secondary"
      className="font-semibold text-muted-foreground"
      title={`${ZONE_LABEL[zone]} — settles in ${currency}. Legs are only ever combined inside one zone.`}
    >
      {short ? ZONE_SHORT[zone] : ZONE_LABEL[zone]}
    </Badge>
  );
}

const FLAG_TONE = {
  positive: "bg-positive-soft text-positive",
  caution: "bg-caution-soft text-caution",
  danger: "bg-danger-soft text-danger",
} as const;

export function FlagChip({ flag }: { flag: RiskFlag }) {
  const severity = (FLAG_SEVERITY[flag] ?? "caution") as keyof typeof FLAG_TONE;
  return (
    <Badge
      variant="secondary"
      className={cn("border-transparent font-semibold", FLAG_TONE[severity])}
      title={FLAG_LABEL[flag]}
    >
      {FLAG_LABEL[flag] ?? flag}
    </Badge>
  );
}

const METER_FILL = {
  positive: "bg-positive",
  caution: "bg-caution",
  danger: "bg-danger",
} as const;

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
        className="h-1.5 w-[44px] shrink-0 overflow-hidden rounded-full bg-neutral-soft"
        role="meter"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Confidence"
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-[var(--t-slow)] ease-[var(--ease-out-expo)]",
            METER_FILL[tone],
          )}
          // Width tracks the value, so it cannot be a static class. Transitioned
          // rather than set outright: a meter that jumps between polls is read
          // as a rendering glitch, and the direction of travel is information.
          style={{ width: `${Math.max(2, value)}%` }}
        />
      </div>
      {showLabel && (
        <AnimatedNumber
          value={value}
          format={(n) => String(Math.round(n))}
          className="num text-xs text-muted-foreground"
        />
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
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div
        className="mb-3 flex size-[44px] items-center justify-center rounded-full bg-muted text-2xl text-faint"
        aria-hidden
      >
        {icon}
      </div>
      <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
      <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
        {body}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <ShadCard className="gap-0 border-danger bg-danger-soft py-0" role="alert">
      <CardContent className="flex items-start gap-3 p-4">
        <span className="text-danger" aria-hidden>
          ⚠
        </span>
        <div className="flex-1">
          <div className="text-sm font-medium text-danger">{message}</div>
          {onRetry && (
            <Button size="sm" variant="outline" className="mt-2.5" onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      </CardContent>
    </ShadCard>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <ShadSkeleton
          key={`row-${i}`}
          className="shimmer h-[34px]"
          // Rows fade down the stack, and each starts its shimmer slightly
          // later, so the placeholder reads as loading rather than as a stack
          // of identical grey bars pulsing in lockstep.
          style={{ opacity: 1 - i * 0.12, animationDelay: `${i * 90}ms` }}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ misc */

/**
 * Make a non-button element that responds to a click respond to the keyboard too.
 *
 * Spread onto the element alongside its `onClick`. A `<tr onClick>` is invisible
 * to anyone not using a mouse, which on a table whose rows open a detail panel
 * means the panel is simply unreachable.
 *
 *     <TableRow {...activatable(() => select(row))}>
 */
export function activatable(activate: () => void) {
  return {
    role: "button" as const,
    tabIndex: 0,
    onClick: activate,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    },
  };
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span title={text} className="cursor-help border-b border-dotted border-faint">
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
      className={cn(
        "relative h-[19px] w-[34px] shrink-0 cursor-pointer rounded-full border-0 transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        checked ? "bg-brand" : "bg-border",
      )}
    >
      <span
        className={cn(
          "absolute left-[2px] top-[2px] size-[15px] rounded-full bg-white transition-transform",
          checked && "translate-x-[15px]",
        )}
      />
    </button>
  );
}

/**
 * A native `<select>`, styled to match shadcn's Input.
 *
 * Deliberately not Radix's Select. A native select is already accessible, it
 * needs no JavaScript, and on a phone it opens the platform picker, which beats
 * any listbox a web app can draw. The only thing it was missing was the styling.
 */
export function NativeSelect({
  className,
  children,
  ...props
}: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "flex h-9 w-full min-w-0 cursor-pointer appearance-none rounded-md border border-input",
        "bg-transparent py-1 pl-3 pr-8 text-sm shadow-xs outline-none transition-[color,box-shadow]",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        // The chevron, drawn once as a data URI rather than as stacked gradients.
        "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22 fill=%22none%22 stroke=%22currentColor%22 stroke-width=%221.5%22><path d=%22M4 6l4 4 4-4%22/></svg>')]",
        "bg-[length:16px] bg-[right_0.5rem_center] bg-no-repeat",
        className,
      )}
      {...props}
    >
      {children}
    </select>
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
      <Label className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.055em] text-faint">
        {label}
      </Label>
      {children}
      {hint && <p className="mt-1.5 text-xs text-faint">{hint}</p>}
    </div>
  );
}
