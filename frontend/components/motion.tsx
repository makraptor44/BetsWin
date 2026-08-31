"use client";

import { useEffect, useId, useReducer, useRef, useState } from "react";

/**
 * Motion primitives.
 *
 * Everything here degrades to the final state when the user has asked for
 * reduced motion. That is not a courtesy toggle: on a page whose numbers change
 * every fifteen seconds, motion sickness is a real failure mode, and a trader
 * who has turned animation off should still see the value.
 */

/** Tracks the OS setting live, rather than reading it once at mount. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return reduced;
}

/** The house entrance curve, matching --ease-out-quart in globals.css. */
const easeOutQuart = (t: number) => 1 - Math.pow(1 - t, 4);

/**
 * A number that travels to its new value instead of teleporting.
 *
 * The point is not decoration. When a figure updates on a poll, a hard swap
 * gives no clue whether it moved a cent or a thousand dollars -- the eye reads
 * the new value and nothing else. Tweening makes the SIZE of the change legible
 * from across a desk.
 *
 * Driven by requestAnimationFrame against wall-clock time rather than a frame
 * count, so a backgrounded tab that throttles to 1fps still lands exactly on
 * the target rather than crawling.
 */
export function AnimatedNumber({
  value,
  format,
  duration = 620,
  className,
}: {
  value: number;
  /** Applied to every intermediate frame, so units and separators stay put. */
  format: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(value);
  const fromRef = useRef(value);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (reduced || fromRef.current === value) {
      fromRef.current = value;
      setShown(value);
      return;
    }

    const from = fromRef.current;
    const delta = value - from;
    const started = performance.now();

    const step = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      setShown(from + delta * easeOutQuart(t));
      if (t < 1) {
        frameRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = value;
      }
    };

    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current !== undefined) cancelAnimationFrame(frameRef.current);
      // Leave the origin at the target, so an update arriving mid-tween
      // continues from where the eye already is rather than snapping back.
      fromRef.current = value;
    };
  }, [value, duration, reduced]);

  return (
    <span className={className} suppressHydrationWarning>
      {format(shown)}
    </span>
  );
}

/**
 * Fires a one-shot highlight whenever `value` changes.
 *
 * Returns a counter meant to be used as a `key`, which is how you restart a CSS
 * animation without touching the element's class list on a timer.
 */
export function useTick(value: unknown): number {
  const [n, bump] = useReducer((x: number) => x + 1, 0);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    bump();
  }, [value]);
  return n;
}

/**
 * An inline trend line.
 *
 * Drawn as a single path with `stroke-dasharray` set to its own length, so it
 * draws itself in on mount -- no library, no layout pass, and it scales to any
 * container because the viewBox does the work. A flat series gets a flat line
 * rather than a divide-by-zero spike.
 */
export function Sparkline({
  points,
  width = 96,
  height = 26,
  className,
  strokeWidth = 1.6,
  fill = true,
}: {
  points: number[];
  width?: number;
  height?: number;
  className?: string;
  strokeWidth?: number;
  fill?: boolean;
}) {
  const reduced = useReducedMotion();
  // `useId` rather than a random string stashed in a ref: the gradient needs a
  // document-unique id, and randomising it during render is impure (the React
  // compiler rejects it outright) as well as producing a server/client mismatch
  // under SSR. The non-word characters React puts in the id are stripped because
  // this ends up inside a `url(#...)` reference.
  const id = `sk${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  if (points.length < 2) return null;

  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const pad = strokeWidth;

  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (width - pad * 2) + pad;
    const y = height - pad - ((p - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const line = coords
    .map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");
  const area = `${line} L${(width - pad).toFixed(2)} ${height} L${pad.toFixed(2)} ${height} Z`;
  const rising = points[points.length - 1] >= points[0];

  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      role="img"
      aria-label={`Trend, ${rising ? "rising" : "falling"}`}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.20" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${id})`} />}
      <path
        d={line}
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        // 1000 comfortably exceeds any path length at these dimensions, so the
        // dash covers the whole line before the animation runs it off.
        style={
          reduced
            ? undefined
            : {
                strokeDasharray: 1000,
                strokeDashoffset: 1000,
                animation: "draw 900ms var(--ease-out-expo) forwards",
              }
        }
      />
    </svg>
  );
}
