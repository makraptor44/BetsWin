"use client";

import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

/**
 * Ctrl/Cmd-K navigation.
 *
 * Seven pages behind a horizontal nav means every jump is a mouse trip to the
 * top of the window, and this is a tool people keep open for hours. A palette
 * makes the whole surface reachable from the keyboard without learning a
 * shortcut per destination -- type two letters, press Enter.
 *
 * Written against plain React rather than adding `cmdk`: the whole behaviour is
 * a filtered list and four key handlers, and the dependency would be larger
 * than the component.
 */

interface Command {
  id: string;
  label: string;
  /** Where the row sits in the list, and the caption under the label. */
  group: string;
  hint?: string;
  /** Extra words that should match but need not be shown. */
  keywords?: string;
  run: (ctx: { router: ReturnType<typeof useRouter> }) => void;
}

const COMMANDS: Command[] = [
  {
    id: "nav-opportunities",
    label: "Opportunities",
    group: "Go to",
    hint: "Live arbitrage across every venue",
    keywords: "arbs home dashboard edge",
    run: ({ router }) => router.push("/"),
  },
  {
    id: "nav-positions",
    label: "Positions",
    group: "Go to",
    hint: "Open stakes, unwind quotes and settlement",
    keywords: "bets placed open pnl",
    run: ({ router }) => router.push("/positions"),
  },
  {
    id: "nav-markets",
    label: "Markets",
    group: "Go to",
    hint: "Everything the scanner has seen this cycle",
    keywords: "events books quotes",
    run: ({ router }) => router.push("/markets"),
  },
  {
    id: "nav-venues",
    label: "Venues",
    group: "Go to",
    hint: "Execution zones, fees and pairing rules",
    keywords: "exchanges books zones jurisdiction",
    run: ({ router }) => router.push("/venues"),
  },
  {
    id: "nav-analytics",
    label: "Analytics",
    group: "Go to",
    hint: "Backtests, yield and the void model",
    keywords: "backtest history charts equity",
    run: ({ router }) => router.push("/analytics"),
  },
  {
    id: "nav-calculators",
    label: "Calculators",
    group: "Go to",
    hint: "Stakes, Kelly, odds conversion, void adjustment",
    keywords: "kelly stake convert maths",
    run: ({ router }) => router.push("/calculators"),
  },
  {
    id: "nav-settings",
    label: "Settings",
    group: "Go to",
    hint: "Bankroll, thresholds and scanner controls",
    keywords: "config bankroll thresholds",
    run: ({ router }) => router.push("/settings"),
  },
  {
    id: "theme-toggle",
    label: "Toggle light / dark",
    group: "Display",
    keywords: "theme dark light appearance contrast",
    run: () => {
      const root = document.documentElement;
      const current =
        root.getAttribute("data-theme") ??
        (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("betswin-theme", next);
      } catch {
        /* private mode: the choice just does not persist */
      }
    },
  },
  {
    id: "scroll-top",
    label: "Back to top",
    group: "Display",
    keywords: "scroll up start",
    run: () => window.scrollTo({ top: 0, behavior: "smooth" }),
  },
];

/**
 * Subsequence match, the way an editor's file finder works: "anly" finds
 * "Analytics". Scored so a prefix beats a scattered match, which is what stops
 * the ranking feeling arbitrary.
 */
function score(query: string, command: Command): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;

  const haystack = `${command.label} ${command.group} ${command.keywords ?? ""}`.toLowerCase();
  const label = command.label.toLowerCase();

  if (label.startsWith(q)) return 1000;
  if (label.includes(q)) return 700;
  if (haystack.includes(q)) return 400;

  let i = 0;
  let gaps = 0;
  for (const ch of haystack) {
    if (ch === q[i]) {
      i += 1;
      if (i === q.length) return Math.max(50, 300 - gaps);
    } else if (i > 0) {
      gaps += 1;
    }
  }
  return 0;
}

export function CommandPalette() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => {
    return COMMANDS.map((c) => ({ c, s: score(query, c) }))
      .filter((r) => r.s > 0)
      .sort((a, b) => b.s - a.s)
      .map((r) => r.c);
  }, [query]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActive(0);
  }, []);

  const runAt = useCallback(
    (index: number) => {
      const command = results[index];
      if (!command) return;
      close();
      command.run({ router });
    },
    [results, close, router],
  );

  // Open on Cmd/Ctrl-K from anywhere, including from inside an input, since
  // that is where a hand already is when the thought occurs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    const onOpenRequest = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("betswin:open-palette", onOpenRequest);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("betswin:open-palette", onOpenRequest);
    };
  }, []);

  // Route changes dismiss it, so a jump does not leave the overlay behind.
  useEffect(() => {
    close();
  }, [pathname, close]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Keep the highlighted row visible when arrowing past the fold.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  useEffect(() => setActive(0), [query]);

  if (!open) return null;

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (results.length ? (i + 1) % results.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runAt(active);
    }
  };

  let lastGroup = "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <button
        type="button"
        aria-label="Close command palette"
        className="absolute inset-0 bg-background/70 backdrop-blur-[2px]"
        onClick={close}
      />

      <div
        className="relative w-full max-w-[560px] overflow-hidden rounded-xl border border-border-strong bg-popover"
        style={{ boxShadow: "var(--shadow-overlay)", animation: "rise 140ms ease-out" }}
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2.5 border-b border-hairline px-3.5">
          <span aria-hidden className="text-faint">
            {/* A magnifier, drawn rather than imported: two shapes. */}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
          </span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to a page, or change the display…"
            className="h-12 w-full bg-transparent text-[14px] outline-none placeholder:text-faint"
            aria-label="Search commands"
            aria-activedescendant={results[active] ? `cmd-${results[active].id}` : undefined}
          />
          <kbd className="hidden shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-faint sm:block">
            ESC
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-1.5" role="listbox">
          {results.length === 0 && (
            <p className="px-3 py-8 text-center text-xs text-faint">
              Nothing matches “{query}”.
            </p>
          )}

          {results.map((command, i) => {
            const newGroup = command.group !== lastGroup;
            lastGroup = command.group;
            return (
              <div key={command.id}>
                {newGroup && (
                  <div className="px-2.5 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
                    {command.group}
                  </div>
                )}
                <div
                  id={`cmd-${command.id}`}
                  data-index={i}
                  role="option"
                  aria-selected={i === active}
                  tabIndex={-1}
                  onMouseMove={() => setActive(i)}
                  onClick={() => runAt(i)}
                  className={[
                    "flex cursor-pointer items-center justify-between gap-3 rounded-md px-2.5 py-2",
                    i === active ? "bg-brand-soft text-foreground" : "text-muted-foreground",
                  ].join(" ")}
                >
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-foreground">
                      {command.label}
                    </span>
                    {command.hint && (
                      <span className="block truncate text-[11px] text-faint">
                        {command.hint}
                      </span>
                    )}
                  </span>
                  {i === active && (
                    <kbd className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-faint">
                      ↵
                    </kbd>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
