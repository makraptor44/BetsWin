"""Generate frontend/app/globals.css.

The dark palette has to appear under two selectors -- the prefers-colour-scheme
media query and the explicit data-theme override -- and CSS has no way to share
one block between them. Generating the file means the two copies cannot drift.
"""
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "app" / "globals.css"

LIGHT = """
  /* shadcn surface + text scale */
  --background: oklch(0.985 0.002 250);
  --foreground: oklch(0.205 0.012 260);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.205 0.012 260);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.205 0.012 260);
  --primary: oklch(0.52 0.20 268);
  --primary-foreground: oklch(0.99 0 0);
  --secondary: oklch(0.96 0.004 255);
  --secondary-foreground: oklch(0.30 0.012 260);
  --muted: oklch(0.962 0.004 255);
  --muted-foreground: oklch(0.52 0.017 258);
  --accent: oklch(0.955 0.008 258);
  --accent-foreground: oklch(0.30 0.012 260);
  --destructive: oklch(0.56 0.19 27);
  --border: oklch(0.905 0.006 258);
  --input: oklch(0.905 0.006 258);
  --ring: oklch(0.52 0.20 268);

  /* Interaction accent. Named `brand` because shadcn's `--accent` is a muted
     hover surface, not an accent colour. */
  --brand: oklch(0.52 0.20 268);
  --brand-foreground: oklch(0.99 0 0);
  --brand-soft: oklch(0.52 0.20 268 / 0.10);

  /* The risk ramp. Reserved for risk and nothing else, so a colour always
     means the same thing. Margin is never coloured by size alone -- a fat
     margin is a warning, not a win (Part I s5.3). */
  --positive: oklch(0.55 0.13 158);
  --positive-soft: oklch(0.55 0.13 158 / 0.12);
  --caution: oklch(0.58 0.12 75);
  --caution-soft: oklch(0.58 0.12 75 / 0.13);
  --danger: oklch(0.55 0.19 27);
  --danger-soft: oklch(0.55 0.19 27 / 0.12);
  --neutral-soft: oklch(0.52 0.017 258 / 0.10);

  /* A third text weight below muted, for labels and captions. */
  --faint: oklch(0.63 0.014 258);

  /* Venue identity. Categorical, never semantic. */
  --venue-polymarket: oklch(0.55 0.20 288);
  --venue-kalshi: oklch(0.52 0.12 175);
  --venue-sportsbook: oklch(0.55 0.15 45);
  --venue-smarkets: oklch(0.52 0.16 250);
  --venue-betfair: oklch(0.55 0.12 90);

  --chart-1: oklch(0.52 0.20 268);
  --chart-2: oklch(0.55 0.13 158);
  --chart-3: oklch(0.58 0.12 75);
  --chart-4: oklch(0.55 0.20 288);
  --chart-5: oklch(0.52 0.12 175);
"""

DARK = """
  --background: oklch(0.17 0.011 265);
  --foreground: oklch(0.93 0.006 258);
  --card: oklch(0.213 0.012 265);
  --card-foreground: oklch(0.93 0.006 258);
  --popover: oklch(0.213 0.012 265);
  --popover-foreground: oklch(0.93 0.006 258);
  --primary: oklch(0.70 0.15 268);
  --primary-foreground: oklch(0.17 0.011 265);
  --secondary: oklch(0.26 0.013 265);
  --secondary-foreground: oklch(0.93 0.006 258);
  --muted: oklch(0.253 0.013 265);
  --muted-foreground: oklch(0.70 0.014 258);
  --accent: oklch(0.28 0.014 265);
  --accent-foreground: oklch(0.93 0.006 258);
  --destructive: oklch(0.70 0.17 25);
  --border: oklch(0.30 0.014 265);
  --input: oklch(0.30 0.014 265);
  --ring: oklch(0.70 0.15 268);

  --brand: oklch(0.72 0.14 268);
  --brand-foreground: oklch(0.17 0.011 265);
  --brand-soft: oklch(0.72 0.14 268 / 0.16);

  --positive: oklch(0.78 0.16 158);
  --positive-soft: oklch(0.78 0.16 158 / 0.14);
  --caution: oklch(0.80 0.14 78);
  --caution-soft: oklch(0.80 0.14 78 / 0.15);
  --danger: oklch(0.70 0.17 25);
  --danger-soft: oklch(0.70 0.17 25 / 0.15);
  --neutral-soft: oklch(0.70 0.014 258 / 0.12);

  --faint: oklch(0.58 0.013 258);

  --venue-polymarket: oklch(0.74 0.15 288);
  --venue-kalshi: oklch(0.78 0.13 175);
  --venue-sportsbook: oklch(0.76 0.14 50);
  --venue-smarkets: oklch(0.74 0.13 250);
  --venue-betfair: oklch(0.82 0.13 90);

  --chart-1: oklch(0.72 0.14 268);
  --chart-2: oklch(0.78 0.16 158);
  --chart-3: oklch(0.80 0.14 78);
  --chart-4: oklch(0.74 0.15 288);
  --chart-5: oklch(0.78 0.13 175);
"""

HEADER = '''@import "tailwindcss";
@import "tw-animate-css";
@import "shadcn/tailwind.css";

/*
  BetsWin design tokens.

  Everything visual comes from here or from shadcn/ui. There are no bespoke
  `.btn` / `.card` / `.chip` primitives any more, and no inline style props in
  the components -- both were reimplementing a component library by hand.

  The palette is deliberately narrow: one accent for interactive affordances,
  and a semantic ramp (positive / caution / danger) reserved exclusively for
  RISK, so a colour always means the same thing. Margins are never coloured by
  size alone -- a fat margin is a warning, not a win (Part I s5.3).

  Theming has three states, and all three have to work:

    - no preference expressed  -> follow the operating system
    - data-theme="light"       -> light, even on a dark OS
    - data-theme="dark"        -> dark, even on a light OS

  The previous file declared its palette three times and had no
  prefers-color-scheme query at all, so a light-mode visitor got a dark
  dashboard until they found the toggle. The dark block below is duplicated
  across two selectors because CSS cannot share one declaration block between a
  media query and an attribute selector; both copies are generated from a single
  source in scripts/gen_globals.py, so they cannot drift.
*/

/* Tailwind's `dark:` variant has to agree with the palette above: on for an
   explicit dark choice, and on for a dark OS unless light was chosen. */
@custom-variant dark {
  @media (prefers-color-scheme: dark) {
    &:where(:root:not([data-theme="light"]) *) {
      @slot;
    }
  }
  &:where(:root[data-theme="dark"] *) {
    @slot;
  }
}
'''

THEME = """
/* Expose the tokens as Tailwind utilities: `text-muted-foreground`,
   `bg-positive-soft`, `border-border`, `text-venue-kalshi`, and so on. */
@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);

  --color-brand: var(--brand);
  --color-brand-foreground: var(--brand-foreground);
  --color-brand-soft: var(--brand-soft);

  --color-positive: var(--positive);
  --color-positive-soft: var(--positive-soft);
  --color-caution: var(--caution);
  --color-caution-soft: var(--caution-soft);
  --color-danger: var(--danger);
  --color-danger-soft: var(--danger-soft);
  --color-neutral-soft: var(--neutral-soft);
  --color-faint: var(--faint);

  --color-venue-polymarket: var(--venue-polymarket);
  --color-venue-kalshi: var(--venue-kalshi);
  --color-venue-sportsbook: var(--venue-sportsbook);
  --color-venue-smarkets: var(--venue-smarkets);
  --color-venue-betfair: var(--venue-betfair);

  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);

  --font-sans: var(--font-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-mono), ui-monospace, "SF Mono", Menlo, monospace;

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }

  body {
    @apply bg-background text-foreground;
    font-size: 14px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }

  /* Every price, stake, odds and P&L figure is a number in a column, so the
     digits have to line up. */
  .tabular,
  table {
    font-variant-numeric: tabular-nums;
  }

  ::selection {
    background: var(--brand-soft);
  }
}

@layer components {
  /* Wide content scrolls inside its own container. The page body must never
     scroll sideways -- it did, at 375px, by 38 pixels. */
  .scroll-x {
    @apply overflow-x-auto;
    -webkit-overflow-scrolling: touch;
  }

  /* A row that behaves as a button. Keyboard-reachable, which the bare
     `<tr onClick>` it replaces was not. */
  .row-action {
    @apply cursor-pointer transition-colors;
  }
  .row-action:hover {
    @apply bg-muted/60;
  }
  .row-action:focus-visible {
    @apply outline-2 outline-offset-[-2px] outline-ring;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

::-webkit-scrollbar {
  width: 9px;
  height: 9px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 5px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--muted-foreground);
}
"""


def build() -> str:
    light = LIGHT.rstrip()
    dark = DARK.rstrip()
    dark_indented = "\n".join(
        ("  " + line) if line.strip() else line for line in dark.splitlines()
    )
    return (
        HEADER
        + "\n/* Light is the base. */\n:root {\n  --radius: 0.625rem;\n"
        + light
        + "\n}\n"
        + "\n/* A dark OS, unless light was explicitly chosen. */\n"
        + "@media (prefers-color-scheme: dark) {\n"
        + '  :root:not([data-theme="light"]) {\n'
        + dark_indented
        + "\n  }\n}\n"
        + "\n/* An explicit dark choice beats a light OS. Kept identical to the\n"
        + "   block above -- see the note at the top of this file. */\n"
        + ':root[data-theme="dark"] {\n'
        + dark
        + "\n}\n"
        + THEME
    )


OUT.write_text(build(), encoding="utf-8")
print(f"wrote {OUT.name}: {len(build().splitlines())} lines")
