import type { Metadata, Viewport } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";

import { BuildRibbon } from "@/components/BuildRibbon";
import { CommandPalette } from "@/components/CommandPalette";
import { RouteTransitions } from "@/components/RouteTransitions";
import { Nav } from "@/components/Nav";
import { cn } from "@/lib/utils";

import "./globals.css";

const sans = Geist({ subsets: ["latin"], variable: "--font-sans" });

/**
 * Every price, stake, odds figure and P&L number in this application sits in a
 * column, so the digits have to line up. A proportional face cannot do that.
 *
 * JetBrains Mono over Geist Mono for one reason that matters at 11px: its zero
 * is slashed and its 1 has a foot, so an odds ladder cannot be misread. It also
 * carries a lighter weight range, which keeps a dense table from looking bold.
 */
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "BetsWin — Prediction Market Arbitrage",
  description:
    "Scans US prediction markets for arbitrage, sizes each opportunity against real order-book depth, and scores it for the risks that erode theoretical edge.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfc" },
    { media: "(prefers-color-scheme: dark)", color: "#22252c" },
  ],
};

/**
 * Applied before first paint so a stored theme choice never flashes the wrong
 * palette.
 *
 * With no stored choice, nothing is written and the CSS follows the operating
 * system. Only an explicit choice sets the attribute.
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
    <html
      lang="en"
      suppressHydrationWarning
      className={cn("font-sans", sans.variable, mono.variable)}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>
        <div className="relative flex min-h-screen flex-col">
          {/* A very faint wash behind the page. Not decoration: it separates the
              fixed chrome from the scrolling content without a hard rule, so
              the header does not sit on a seam. */}
          <div
            aria-hidden
            className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-[420px]"
            style={{
              background:
                "radial-gradient(70% 100% at 50% 0%, var(--brand-soft) 0%, transparent 70%)",
            }}
          />
          <BuildRibbon />
          <Nav />
          <CommandPalette />
          <RouteTransitions />
          <main className="vt-content mx-auto w-full max-w-[1560px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
            {children}
          </main>
          <footer className="mx-auto mt-4 w-full max-w-[1560px] border-t border-hairline px-4 py-6 text-xs leading-relaxed text-faint sm:px-6 lg:px-8">
            <p className="max-w-[80ch]">
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
