"use client";

import { agoLabel, duration, VENUE_LABEL } from "@/lib/format";

interface EngineLike {
  status: {
    running: boolean;
    demo_mode: boolean;
    poll_interval: number;
    next_scan_in: number;
    uptime_seconds: number;
    total_detected: number;
    sources: Record<string, boolean>;
    breaker_tripped: boolean;
    breaker_reason: string | null;
    last_scan: { started_at: string; duration_seconds: number } | null;
  } | null;
  connection: "connecting" | "live" | "polling" | "offline" | "snapshot";
  lastUpdate: number;
  scanNow: () => Promise<void>;
  scanning: boolean;
  isStaticDemo: boolean;
}

const CONNECTION = {
  live: { label: "Live", color: "var(--positive)", pulse: true },
  polling: { label: "Polling", color: "var(--caution)", pulse: false },
  connecting: { label: "Connecting", color: "var(--text-faint)", pulse: true },
  offline: { label: "Offline", color: "var(--danger)", pulse: false },
  snapshot: { label: "Snapshot", color: "var(--accent)", pulse: false },
} as const;

export function StatusBar({ engine }: { engine: EngineLike }) {
  const s = engine.status;
  const conn = CONNECTION[engine.connection];

  return (
    <div className="flex flex-col gap-2.5">
      {engine.isStaticDemo && (
        <div
          className="card p-3 flex items-start gap-2.5"
          style={{ borderColor: "var(--accent)", background: "var(--accent-soft)" }}
        >
          <span style={{ color: "var(--accent-text)" }} aria-hidden>
            ●
          </span>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            <strong style={{ color: "var(--accent-text)" }}>
              Static demo.
            </strong>{" "}
            These opportunities are a fixed snapshot captured from the real
            engine running on demo fixtures — the detectors, sizing and risk
            scoring all ran for real, but nothing is updating live and no venue
            is being polled. The calculators are fully interactive.{" "}
            <a
              href="https://github.com/makraptor44/BetsWin"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--accent-text)" }}
            >
              Clone the repo
            </a>{" "}
            and run <code>./start.sh</code> to scan live markets.
          </div>
        </div>
      )}
      {s?.breaker_tripped && (
        <div
          className="card p-3 flex items-start gap-2.5"
          style={{ borderColor: "var(--danger)", background: "var(--danger-soft)" }}
          role="alert"
        >
          <span style={{ color: "var(--danger)" }} aria-hidden>
            ⚡
          </span>
          <div className="text-xs">
            <strong style={{ color: "var(--danger)" }}>
              Circuit breaker tripped.
            </strong>{" "}
            <span style={{ color: "var(--text-muted)" }}>
              {s.breaker_reason ??
                "An implausible burst of opportunities was detected; scanning has halted."}
            </span>
          </div>
        </div>
      )}

      <div className="card px-3.5 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-2">
        <span className="flex items-center gap-1.5 text-xs font-medium">
          <span
            className={`rounded-full ${conn.pulse ? "pulse-dot" : ""}`}
            style={{ width: 7, height: 7, background: conn.color }}
            aria-hidden
          />
          {conn.label}
        </span>

        {s?.demo_mode && (
          <span className="chip chip-caution" title="Serving deterministic fixtures, no network">
            Demo data
          </span>
        )}

        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Scanner{" "}
          <strong style={{ color: s?.running ? "var(--positive)" : "var(--text-faint)" }}>
            {s?.running ? "running" : "stopped"}
          </strong>
          {s?.running && ` · every ${s.poll_interval}s`}
        </span>

        {s && Object.keys(s.sources).length > 0 && (
          <span className="flex items-center gap-2 text-xs">
            {Object.entries(s.sources).map(([name, healthy]) => (
              <span
                key={name}
                className="flex items-center gap-1"
                style={{ color: "var(--text-muted)" }}
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

        {s?.last_scan && (
          <span className="text-xs" style={{ color: "var(--text-faint)" }}>
            Last scan {agoLabel(s.last_scan.started_at)}
          </span>
        )}

        {s && s.uptime_seconds > 0 && (
          <span className="text-xs hidden sm:inline" style={{ color: "var(--text-faint)" }}>
            Up {duration(s.uptime_seconds)} · {s.total_detected} found
          </span>
        )}

        {engine.isStaticDemo ? (
          <a
            className="btn btn-sm ml-auto"
            href="https://github.com/makraptor44/BetsWin"
            target="_blank"
            rel="noopener noreferrer"
            style={{ textDecoration: "none" }}
          >
            View source ↗
          </a>
        ) : (
          <button
            className="btn btn-sm ml-auto"
            onClick={() => void engine.scanNow()}
            disabled={engine.scanning}
          >
            {engine.scanning ? "Scanning…" : "Scan now"}
          </button>
        )}
      </div>
    </div>
  );
}
