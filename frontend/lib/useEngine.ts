"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, STATIC_DEMO, api } from "./api";
import type { Arb, EngineStatus } from "./types";

type ConnectionState = "connecting" | "live" | "polling" | "offline" | "snapshot";

interface EngineState {
  arbs: Arb[];
  status: EngineStatus | null;
  connection: ConnectionState;
  error: string | null;
  lastUpdate: number;
  refresh: () => Promise<void>;
  scanNow: () => Promise<void>;
  scanning: boolean;
  isStaticDemo: boolean;
}

const POLL_MS = 15_000;
const RECONNECT_BASE_MS = 1_500;
const RECONNECT_MAX_MS = 30_000;

function wsUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return explicit;
  if (typeof window === "undefined") return "";
  // The dev rewrite proxies /api but not the socket, so target the backend
  // directly on its own port when running against localhost.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host =
    window.location.port === "3000"
      ? `${window.location.hostname}:8000`
      : window.location.host;
  return `${proto}//${host}/ws`;
}

/**
 * Live engine state.
 *
 * Prefers a WebSocket push so a new opportunity lands on screen within a second
 * of detection. Falls back to polling if the socket cannot be established --
 * degraded but still correct, and the UI says which mode it is in rather than
 * silently going stale.
 */
export function useEngine(): EngineState {
  const [arbs, setArbs] = useState<Arb[]>([]);
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState(0);
  const [scanning, setScanning] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [arbRes, statusRes] = await Promise.all([
        api.arbs({ limit: 500 }),
        api.status(),
      ]);
      setArbs(arbRes.arbs);
      setStatus(statusRes);
      setLastUpdate(Date.now());
      setError(null);
      // In the static demo the data is a captured snapshot; saying "polling"
      // would imply it is refreshing when nothing is being fetched.
      setConnection((c) =>
        STATIC_DEMO ? "snapshot" : c === "live" ? c : "polling",
      );
    } catch (e) {
      const message =
        e instanceof ApiError
          ? e.message
          : "Unexpected error talking to the engine.";
      setError(message);
      setConnection("offline");
    }
  }, []);

  const scanNow = useCallback(async () => {
    setScanning(true);
    try {
      await api.scanNow();
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan failed.");
    } finally {
      setScanning(false);
    }
  }, [refresh]);

  const isStaticDemo = STATIC_DEMO;

  // Initial load + polling fallback.
  useEffect(() => {
    void refresh();
    // The static demo serves an unchanging snapshot; re-fetching it forever
    // would burn cycles to arrive at the same numbers.
    if (STATIC_DEMO) return;
    pollRef.current = setInterval(() => {
      // Only poll when the socket is not carrying updates.
      if (socketRef.current?.readyState !== WebSocket.OPEN) void refresh();
    }, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  // WebSocket with exponential-backoff reconnect.
  useEffect(() => {
    if (STATIC_DEMO) return;
    closedRef.current = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closedRef.current) return;
      const url = wsUrl();
      if (!url) return;

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        setConnection("polling");
        return;
      }
      socketRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
        setConnection("live");
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "ping") return;
          if (msg.type === "snapshot" || msg.type === "scan") {
            if (msg.data.live) setArbs(msg.data.live as Arb[]);
            if (msg.data.status) setStatus(msg.data.status as EngineStatus);
            setLastUpdate(Date.now());
          } else if (msg.type === "arb") {
            const incoming = msg.data as Arb;
            setArbs((prev) => {
              const rest = prev.filter((a) => a.id !== incoming.id);
              return [incoming, ...rest];
            });
            setLastUpdate(Date.now());
          }
        } catch {
          /* malformed frame: ignore rather than tear down the socket */
        }
      };

      ws.onclose = () => {
        socketRef.current = null;
        if (closedRef.current) return;
        setConnection("polling");
        const delay = Math.min(
          RECONNECT_BASE_MS * 2 ** retryRef.current,
          RECONNECT_MAX_MS,
        );
        retryRef.current += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closedRef.current = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  return {
    arbs,
    status,
    connection,
    error,
    lastUpdate,
    refresh,
    scanNow,
    scanning,
    isStaticDemo,
  };
}

/** Generic one-shot loader with loading and error state. */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): { data: T | null; loading: boolean; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fnRef
      .current()
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof ApiError ? e.message : "Something went wrong.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}
