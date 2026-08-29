"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const LINKS = [
  { href: "/", label: "Opportunities" },
  { href: "/markets", label: "Markets" },
  { href: "/venues", label: "Venues" },
  { href: "/analytics", label: "Analytics" },
  { href: "/calculators", label: "Calculators" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [mounted, setMounted] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem("betswin-theme");
    setTheme(stored === "light" ? "light" : "dark");
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("betswin-theme", next);
  };

  return (
    <header
      className="sticky top-0 z-40 border-b backdrop-blur"
      style={{
        background: "color-mix(in srgb, var(--bg) 88%, transparent)",
        borderColor: "var(--border)",
      }}
    >
      <div className="w-full max-w-[1560px] mx-auto px-4 sm:px-6">
        <div className="flex items-center gap-5 h-14">
          <Link
            href="/"
            className="flex items-center gap-2.5 shrink-0"
            style={{ textDecoration: "none", color: "var(--text)" }}
          >
            <span
              className="flex items-center justify-center rounded-md font-bold text-[13px]"
              style={{
                width: 26,
                height: 26,
                background: "var(--accent)",
                color: "#fff",
              }}
              aria-hidden
            >
              B
            </span>
            <span className="font-semibold tracking-tight text-[15px]">
              BetsWin
            </span>
          </Link>

          <nav className="hidden md:flex items-center gap-1 flex-1">
            {LINKS.map((l) => {
              const active =
                l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className="px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors"
                  style={{
                    textDecoration: "none",
                    color: active ? "var(--text)" : "var(--text-muted)",
                    background: active ? "var(--bg-sunken)" : "transparent",
                  }}
                >
                  {l.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2 ml-auto">
            <button
              className="btn btn-sm"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {mounted ? (theme === "dark" ? "☀" : "☾") : "·"}
            </button>
            <button
              className="btn btn-sm md:hidden"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle navigation"
              aria-expanded={menuOpen}
            >
              ☰
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav
            className="md:hidden pb-3 flex flex-col gap-1 slide-in"
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
                    color: active ? "var(--text)" : "var(--text-muted)",
                    background: active ? "var(--bg-sunken)" : "transparent",
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
