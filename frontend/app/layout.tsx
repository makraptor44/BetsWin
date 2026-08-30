import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { BuildRibbon } from "@/components/BuildRibbon";
import { Nav } from "@/components/Nav";
import { cn } from "@/lib/utils";

import "./globals.css";

const sans = Geist({ subsets: ["latin"], variable: "--font-sans" });

/**
 * Every price, stake, odds figure and P&L number in this application sits in a
 * column, so the digits have to line up. A proportional face cannot do that.
 */
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

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
        <div className="flex min-h-screen flex-col">
          <BuildRibbon />
          <Nav />
          <main className="mx-auto w-full max-w-[1560px] flex-1 px-4 py-6 sm:px-6">
            {children}
          </main>
          <footer className="mx-auto w-full max-w-[1560px] px-4 py-6 text-xs text-faint sm:px-6">
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
