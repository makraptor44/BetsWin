"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

/**
 * Time remaining until a market closes, counted live.
 *
 * On short-dated sport this is the number that decides whether an opportunity
 * is actionable at all: a 2% edge on a fixture kicking off in four minutes is
 * not a trade, it is a race you have already lost. A static "4m" rendered once
 * on page load and never updated actively misleads -- it says four minutes for
 * as long as the tab stays open.
 *
 * ONE timer drives every countdown on the page. A table of two hundred rows
 * holding two hundred intervals wakes the main thread two hundred times a
 * second, which is both wasteful and jittery; a single store with subscribers
 * ticks once and re-renders whoever is listening.
 */

type Listener = () => void;

const listeners = new Set<Listener>();
let timer: ReturnType<typeof setInterval> | null = null;
let now = Date.now();

function start() {
  if (timer !== null) return;
  // Re-read on start: `now` was last set whenever the module loaded, which may
  // have been minutes ago on a page that had no countdowns until now.
  now = Date.now();
  timer = setInterval(() => {
    now = Date.now();
    for (const l of listeners) l();
  }, 1000);
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  start();
  return () => {
    listeners.delete(listener);
    // The last subscriber leaving stops the clock, so a page with no
    // countdowns on it is not paying for one every second.
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

/** Wall-clock milliseconds, re-rendering the caller once a second. */
export function useClock(): number {
  return useSyncExternalStore(
    subscribe,
    () => now,
    // The server has no clock the client will agree with, so render a stable
    // value there and let the first client tick correct it. Returning
    // Date.now() here instead produces a hydration mismatch on every mount.
    () => 0,
  );
}

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Formats a duration at the coarsest granularity that is still useful.
 *
 * Seconds matter under an hour and are noise above it -- nobody reads "2d 4h
 * 17m 03s" and acts on the 03. The unit therefore changes with the horizon
 * rather than being fixed.
 */
export function formatRemaining(ms: number): string {
  if (ms <= 0) return "closed";
  const s = Math.floor(ms / 1000);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = s % 60;

  if (days >= 1) return days >= 365 ? `${(days / 365).toFixed(1)}y` : `${days}d ${hours}h`;
  if (hours >= 1) return `${hours}h ${pad(mins)}m`;
  return `${mins}:${pad(secs)}`;
}

/** Under this many ms the countdown is treated as urgent. */
const URGENT_MS = 15 * 60 * 1000;
const SOON_MS = 60 * 60 * 1000;

export function Countdown({
  iso,
  className,
  showIcon = false,
}: {
  iso: string | null;
  className?: string;
  showIcon?: boolean;
}) {
  // On the server the store reports 0, so nothing is rendered until mount --
  // a countdown baked into a static export would be wrong from the first view.
  const clock = useClock();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!iso) return <span className={cn("text-faint", className)}>—</span>;

  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) {
    return <span className={cn("text-faint", className)}>—</span>;
  }

  const remaining = target - clock;
  const urgent = remaining > 0 && remaining <= URGENT_MS;
  const soon = remaining > URGENT_MS && remaining <= SOON_MS;
  const closed = remaining <= 0;

  return (
    <span
      className={cn(
        "num inline-flex items-center gap-1 tabular-nums",
        closed && "text-faint line-through",
        urgent && "text-danger",
        soon && "text-caution",
        className,
      )}
      // The machine-readable value, so the exact instant survives a screenshot
      // and a screen reader is not read a ticking string character by character.
      title={new Date(iso).toLocaleString()}
      suppressHydrationWarning
    >
      {showIcon && !closed && (
        <svg
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          aria-hidden
          // A dot that pulses once a second only inside the urgent window --
          // motion is the loudest thing on a dense page and it should mean
          // something when it appears.
          className={urgent ? "animate-pulse" : undefined}
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
      )}
      {mounted ? formatRemaining(remaining) : "—"}
    </span>
  );
}
