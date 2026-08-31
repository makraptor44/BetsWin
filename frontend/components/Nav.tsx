"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { withViewTransition } from "@/components/RouteTransitions";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Opportunities" },
  { href: "/positions", label: "Positions" },
  { href: "/markets", label: "Markets" },
  { href: "/venues", label: "Venues" },
  { href: "/analytics", label: "Analytics" },
  { href: "/calculators", label: "Calculators" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [mounted, setMounted] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Rendered after mount: the platform is not knowable during a static export,
  // and a wrong shortcut label is worse than a late one.
  const [isMac, setIsMac] = useState(false);

  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem("betswin-theme");
    setTheme(stored === "light" ? "light" : "dark");
    setIsMac(/mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent));
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("betswin-theme", next);
  };

  return (
    <header
      className="vt-shell sticky top-0 z-40 border-b border-border backdrop-blur-xl"
      style={{ background: "color-mix(in oklch, var(--background) 82%, transparent)" }}
    >
      <div className="mx-auto w-full max-w-[1560px] px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-5 h-14">
          <Link
            href="/"
            className="flex items-center gap-2.5 shrink-0 no-underline text-foreground"
          >
            {/* Two converging bars: the two legs of an arbitrage closing on a
                price. A letter in a rounded square is the default every
                dashboard ships with. */}
            <span aria-hidden className="text-brand">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <path d="M4 18.5 10.5 5.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
                <path d="M20 18.5 13.5 5.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity="0.45" />
                <path d="M7.6 13.4h8.8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
              </svg>
            </span>
            <span className="text-[15px] font-semibold tracking-[-0.02em]">
              BetsWin
            </span>
          </Link>

          {/* The active tab is marked by a rule sitting on the header's own
              bottom border, so the nav reads as a set of tabs rather than a row
              of buttons one of which happens to be shaded. */}
          <nav className="hidden h-14 flex-1 items-stretch gap-0.5 md:flex">
            {LINKS.map((l) => {
              const active =
                l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  onClick={(e) => {
                    // Left click only, and never when a modifier says the user
                    // meant a new tab. Prefetch and history still come from
                    // next/link; all this does is put the swap inside a
                    // transition.
                    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
                      return;
                    }
                    e.preventDefault();
                    withViewTransition(() => router.push(l.href));
                  }}
                  className={cn(
                    "relative flex items-center px-3 text-[13px] font-medium no-underline transition-colors",
                    active
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {l.label}
                  {active && (
                    <span
                      aria-hidden
                      className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand"
                    />
                  )}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {/* Discoverability for the palette. A shortcut nobody is told about
                is a shortcut nobody uses. */}
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("betswin:open-palette"))}
              className="hidden items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground sm:flex"
              aria-label="Open command palette"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              <span>Search</span>
              <kbd className="rounded border border-border px-1 font-mono text-[10px] leading-4">
                {mounted && isMac ? "⌘K" : "Ctrl K"}
              </kbd>
            </button>
            <Button size="sm" variant="outline" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} >
              {mounted ? (theme === "dark" ? "☀" : "☾") : "·"}
            </Button>
            <Button size="sm" variant="outline" className="md:hidden" onClick={() => setMenuOpen((o) => !o)} aria-label="Toggle navigation" aria-expanded={menuOpen} >
              ☰
            </Button>
          </div>
        </div>

        {menuOpen && (
          <nav
            className="md:hidden pb-3 flex flex-col gap-1 animate-in fade-in slide-in-from-top-1 duration-200"
            aria-label="Mobile navigation"
          >
            {LINKS.map((l) => {
              const active =
                l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  onClick={() => setMenuOpen(false)}
                  className="px-3 py-2 rounded-lg text-sm font-medium"
                  style={{
                    textDecoration: "none",
                    color: active ? "var(--foreground)" : "var(--muted-foreground)",
                    background: active ? "var(--muted)" : "transparent",
                  }}
                >
                  {l.label}
                </Link>
              );
            })}
          </nav>
        )}
      </div>
    </header>
  );
}
