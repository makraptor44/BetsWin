import type { Metadata, Viewport } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "BetsWin — Prediction Market Arbitrage",
  description:
    "Scans US prediction markets for arbitrage, sizes each opportunity against real order-book depth, and scores it for the risks that erode theoretical edge.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8fa" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0d12" },
  ],
};

/**
 * Applied before first paint so a stored theme choice never flashes the wrong
 * palette. The CSS defaults to dark, so only an explicit choice is written.
 */
const THEME_BOOTSTRAP = `
try {
  var t = localStorage.getItem("betswin-theme");
  if (t === "light" || t === "dark") {
    document.documentElement.setAttribute("data-theme", t);
  }
} catch (e) {}
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>
        <div className="min-h-screen flex flex-col">
          <Nav />
          <main className="flex-1 w-full max-w-[1560px] mx-auto px-4 sm:px-6 py-6">
            {children}
          </main>
          <footer
            className="w-full max-w-[1560px] mx-auto px-4 sm:px-6 py-6 text-xs"
            style={{ color: "var(--text-faint)" }}
          >
            <p>
              BetsWin is a detection and analysis tool. It does not place bets:
              automating orders at venues whose terms forbid it risks account
              closure and forfeited balances. Verify every leg by hand before
              staking, and treat any margin above ~5% as bad data until proven
              otherwise.
            </p>
          </footer>
        </div>
      </body>
    </html>
  );
}
