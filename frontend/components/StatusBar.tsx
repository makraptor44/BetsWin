"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ZoneChip } from "@/components/ui";
import { VENUE_LABEL, agoLabel, bps, duration } from "@/lib/format";
import type { EngineStatus, ZoneKey } from "@/lib/types";

interface EngineLike {
  status: EngineStatus | null;
  connection: "connecting" | "live" | "polling" | "offline" | "snapshot";
  lastUpdate: number;
  lastFrame: number;
  scanNow: () => Promise<void>;
  scanning: boolean;
  isStaticDemo: boolean;
}

const CONNECTION = {
  live: { label: "Live", color: "var(--positive)", pulse: true },
  polling: { label: "Polling", color: "var(--caution)", pulse: false },
  connecting: { label: "Connecting", color: "var(--faint)", pulse: true },
  offline: { label: "Offline", color: "var(--danger)", pulse: false },
  snapshot: { label: "Snapshot", color: "var(--brand)", pulse: false },
} as const;

/**
 * Countdown to the next cycle.
 *
 * `next_scan_in` arrives once per scan and then goes stale, so it is ticked
 * down locally. This is the one element on the page guaranteed to move every
 * second, which is what makes a quiet market distinguishable from a dead
 * connection at a glance.
 */
function useCountdown(seconds: number | undefined, anchor: number): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (seconds === undefined || !anchor) return null;
  return Math.max(0, seconds - (now - anchor) / 1000);
}

export function StatusBar({ engine }: { engine: EngineLike }) {
  const s = engine.status;
  const conn = CONNECTION[engine.connection];
  const nextIn = useCountdown(s?.next_scan_in, engine.lastUpdate);
  const scan = s?.last_scan;

  return (
    <div className="flex flex-col gap-2.5">
      {/* A scan in flight gets a hairline across the top of the content. The
          engine cannot report progress -- it does not know how many venues will
          answer -- so an indeterminate bar is the only honest shape, and it is
          two pixels rather than a spinner because a scan is background work,
          not a modal wait. */}
      {engine.scanning && (
        <div
          className="indeterminate relative h-0.5 overflow-hidden rounded-full bg-brand-soft"
          role="progressbar"
          aria-label="Scanning venues"
        />
      )}

      {engine.isStaticDemo && (
        <div
          className="enter flex items-start gap-2.5 rounded-lg border border-brand bg-brand-soft p-3 shadow-sm"
        >
          <span className="text-brand" aria-hidden>
            ●
          </span>
          <div className="text-xs text-muted-foreground">
            <strong className="text-brand">
              Static demo.
            </strong>{" "}
            These opportunities are a fixed snapshot captured from the real
            engine running on demo fixtures — the detectors, sizing and risk
            scoring all ran for real, but nothing is updating live and no venue
            is being polled. The calculators are fully interactive.{" "}
            <a
              className="text-brand"
              href="https://github.com/makraptor44/BetsWin"
              target="_blank"
              rel="noopener noreferrer"
            >
              Clone the repo
            </a>{" "}
            and run <code>./start.sh</code> to scan live markets.
          </div>
        </div>
      )}
      {s?.breaker_tripped && (
        <div
          className="enter flex items-start gap-2.5 rounded-lg border border-danger bg-danger-soft p-3 shadow-sm"
          role="alert"
        >
          <span className="text-danger" aria-hidden>
            ⚡
          </span>
          <div className="text-xs">
            <strong className="text-danger">
              Circuit breaker tripped.
            </strong>{" "}
            <span className="text-muted-foreground">
              {s.breaker_reason ??
                "An implausible burst of opportunities was detected; scanning has halted."}
            </span>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-border bg-card shadow-sm px-3.5 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-2">
        <span className="flex items-center gap-1.5 text-xs font-medium">
          <span
            className={`size-[7px] rounded-full ${
              conn.pulse ? "animate-pulse" : ""
            }`}
            style={{ background: conn.color }}
            aria-hidden
          />
          {conn.label}
        </span>

        {s?.demo_mode && (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-caution-soft text-caution" title="Serving deterministic fixtures, no network">
            Demo data
          </span>
        )}

        <span className="text-xs text-muted-foreground">
          Scanner{" "}
          <strong className={s?.running ? "text-positive" : "text-faint"}>
            {s?.running ? "running" : "stopped"}
          </strong>
          {s?.running && nextIn !== null && (
            <>
              {" · next in "}
              <span className="tabular">{Math.ceil(nextIn)}s</span>
            </>
          )}
        </span>

        {s && Object.keys(s.sources).length > 0 && (
          <span className="flex items-center gap-2 text-xs">
            {Object.entries(s.sources).map(([name, healthy]) => (
              <span
                key={name}
                className="flex items-center gap-1 text-muted-foreground"
                title={healthy ? "Reachable" : "Last fetch failed"}
              >
                <span
                  className="rounded-full"
                  style={{
                    width: 5,
                    height: 5,
                    background: healthy ? "var(--positive)" : "var(--danger)",
                  }}
                  aria-hidden
                />
                {VENUE_LABEL[name] ?? name}
              </span>
            ))}
          </span>
        )}

        {s && s.zones?.length > 0 && (
          <span className="flex items-center gap-1.5">
            {s.zones.map((z: ZoneKey) => (
              <ZoneChip key={z} zone={z} short />
            ))}
          </span>
        )}

        {/*
          The evidence that a cycle happened, whatever it found. A market with
          no arbitrage in it still produces these numbers, and they are what
          separate "scanning, nothing crossed" from "not scanning".
        */}
        {scan && (
          <span
            className="text-xs tabular hidden md:inline text-faint"
            title="Events read on the last cycle, and how far the tightest book was from crossing"
          >
            {scan.events_scanned.toLocaleString()} events
            {scan.tightest_gap_bps != null &&
              ` · closest ${bps(scan.tightest_gap_bps)}`}
            {` · ${scan.duration_seconds.toFixed(1)}s`}
          </span>
        )}

        {scan && (
          <span className="text-xs text-faint">
            {agoLabel(scan.started_at)}
          </span>
        )}

        {s && s.uptime_seconds > 0 && (
          <span className="text-xs hidden lg:inline text-faint">
            Up {duration(s.uptime_seconds)} · {s.total_detected} found
          </span>
        )}

        {engine.isStaticDemo ? (
          <a
            className="btn btn-sm ml-auto no-underline"
            href="https://github.com/makraptor44/BetsWin"
            target="_blank"
            rel="noopener noreferrer"
          >
            View source ↗
          </a>
        ) : (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => void engine.scanNow()} disabled={engine.scanning} >
            {engine.scanning ? "Scanning…" : "Scan now"}
          </Button>
        )}
      </div>
    </div>
  );
}
