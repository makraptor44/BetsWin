"""Generate frontend/app/globals.css.

The dark palette has to appear under two selectors -- the prefers-colour-scheme
media query and the explicit data-theme override -- and CSS has no way to share
one block between them. Generating the file means the two copies cannot drift.
"""
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "app" / "globals.css"

LIGHT = """
  /* Surfaces. A near-white ground with true-white cards, so a card reads as
     lifted without needing a heavy border or a drop shadow to say so. */
  --background: oklch(0.977 0.003 250);
  --foreground: oklch(0.185 0.014 258);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.185 0.014 258);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.185 0.014 258);
  --primary: oklch(0.47 0.115 244);
  --primary-foreground: oklch(0.99 0 0);
  --secondary: oklch(0.955 0.004 250);
  --secondary-foreground: oklch(0.30 0.014 258);
  --muted: oklch(0.958 0.004 250);
  --muted-foreground: oklch(0.505 0.017 256);
  --accent: oklch(0.948 0.008 250);
  --accent-foreground: oklch(0.28 0.014 258);
  --destructive: oklch(0.545 0.19 25);
  --border: oklch(0.916 0.005 250);
  --input: oklch(0.895 0.006 250);
  --ring: oklch(0.47 0.115 244);

  /* Two border weights. Hairlines separate rows inside a surface; the stronger
     one bounds the surface itself. One weight for both made every table read as
     a wireframe. */
  --border-strong: oklch(0.862 0.007 250);
  --hairline: oklch(0.936 0.004 250);

  /* Interaction accent. Named `brand` because shadcn's `--accent` is a muted
     hover surface, not an accent colour. A deep instrument blue rather than the
     default violet: this is a trading tool, and violet on a data-dense page
     reads as decoration. */
  --brand: oklch(0.47 0.115 244);
  --brand-foreground: oklch(0.99 0 0);
  --brand-soft: oklch(0.47 0.115 244 / 0.09);
  --brand-hover: oklch(0.41 0.118 244);

  /* The risk ramp. Reserved for risk and nothing else, so a colour always
     means the same thing. Margin is never coloured by size alone -- a fat
     margin is a warning, not a win (Part I s5.3). */
  --positive: oklch(0.505 0.125 158);
  --positive-soft: oklch(0.505 0.125 158 / 0.11);
  --caution: oklch(0.585 0.115 68);
  --caution-soft: oklch(0.585 0.115 68 / 0.12);
  --danger: oklch(0.535 0.185 25);
  --danger-soft: oklch(0.535 0.185 25 / 0.11);
  --neutral-soft: oklch(0.505 0.017 256 / 0.09);

  /* A third text weight below muted, for labels and captions. */
  --faint: oklch(0.615 0.014 256);

  /* Elevation. Layered rather than a single blur, so a card reads as sitting on
     the page rather than floating above a screenshot of one. */
  --shadow-flat: 0 1px 2px oklch(0.185 0.014 258 / 0.05);
  --shadow-raised:
    0 1px 2px oklch(0.185 0.014 258 / 0.06),
    0 4px 12px oklch(0.185 0.014 258 / 0.05);
  --shadow-overlay:
    0 2px 6px oklch(0.185 0.014 258 / 0.08),
    0 16px 48px oklch(0.185 0.014 258 / 0.14);

  /* Venue identity. Categorical, never semantic. */
  --venue-polymarket: oklch(0.52 0.18 292);
  --venue-kalshi: oklch(0.50 0.11 188);
  --venue-sportsbook: oklch(0.545 0.145 48);
  --venue-smarkets: oklch(0.50 0.14 252);
  --venue-betfair: oklch(0.53 0.115 118);

  --chart-1: oklch(0.47 0.115 244);
  --chart-2: oklch(0.505 0.125 158);
  --chart-3: oklch(0.585 0.115 68);
  --chart-4: oklch(0.52 0.18 292);
  --chart-5: oklch(0.50 0.11 188);
"""

DARK = """
  /* Graphite, not navy, and not pure black. A slight cool cast keeps the
     accent readable without tinting the numbers. */
  --background: oklch(0.158 0.008 258);
  --foreground: oklch(0.945 0.005 250);
  --card: oklch(0.196 0.009 258);
  --card-foreground: oklch(0.945 0.005 250);
  --popover: oklch(0.214 0.010 258);
  --popover-foreground: oklch(0.945 0.005 250);
  --primary: oklch(0.72 0.115 240);
  --primary-foreground: oklch(0.158 0.008 258);
  --secondary: oklch(0.245 0.010 258);
  --secondary-foreground: oklch(0.945 0.005 250);
  --muted: oklch(0.238 0.010 258);
  --muted-foreground: oklch(0.715 0.012 252);
  --accent: oklch(0.268 0.011 258);
  --accent-foreground: oklch(0.945 0.005 250);
  --destructive: oklch(0.695 0.165 25);
  --border: oklch(0.278 0.011 258);
  --input: oklch(0.318 0.012 258);
  --ring: oklch(0.72 0.115 240);

  --border-strong: oklch(0.345 0.013 258);
  --hairline: oklch(0.245 0.010 258);

  --brand: oklch(0.735 0.112 240);
  --brand-foreground: oklch(0.158 0.008 258);
  --brand-soft: oklch(0.735 0.112 240 / 0.15);
  --brand-hover: oklch(0.795 0.105 240);

  --positive: oklch(0.775 0.145 158);
  --positive-soft: oklch(0.775 0.145 158 / 0.14);
  --caution: oklch(0.815 0.13 78);
  --caution-soft: oklch(0.815 0.13 78 / 0.14);
  --danger: oklch(0.705 0.165 25);
  --danger-soft: oklch(0.705 0.165 25 / 0.15);
  --neutral-soft: oklch(0.715 0.012 252 / 0.12);

  --faint: oklch(0.605 0.012 252);

  /* Shadow does almost nothing on a dark ground -- separation there comes from
     the surface being lighter than the page, so these stay subtle and the card
     border does the work. */
  --shadow-flat: 0 1px 2px oklch(0 0 0 / 0.28);
  --shadow-raised:
    0 1px 2px oklch(0 0 0 / 0.32),
    0 4px 14px oklch(0 0 0 / 0.30);
  --shadow-overlay:
    0 2px 8px oklch(0 0 0 / 0.40),
    0 20px 56px oklch(0 0 0 / 0.52);

  --venue-polymarket: oklch(0.755 0.145 292);
  --venue-kalshi: oklch(0.785 0.115 188);
  --venue-sportsbook: oklch(0.775 0.135 52);
  --venue-smarkets: oklch(0.755 0.125 252);
  --venue-betfair: oklch(0.825 0.125 118);

  --chart-1: oklch(0.735 0.112 240);
  --chart-2: oklch(0.775 0.145 158);
  --chart-3: oklch(0.815 0.13 78);
  --chart-4: oklch(0.755 0.145 292);
  --chart-5: oklch(0.785 0.115 188);
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
  --color-border-strong: var(--border-strong);
  --color-hairline: var(--hairline);
  --color-brand-hover: var(--brand-hover);

  --ease-out-quart: var(--ease-out-quart);
  --ease-out-expo: var(--ease-out-expo);
  --ease-spring: var(--ease-spring);

  --shadow-flat: var(--shadow-flat);
  --shadow-raised: var(--shadow-raised);
  --shadow-overlay: var(--shadow-overlay);

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

/* Registered so they interpolate. An unregistered custom property is a string
   to the animation engine, which is why `transition: --value` silently does
   nothing -- the value snaps at 50% instead of ramping. Registering gives the
   browser a type to tween through, which is what makes the counters and the
   confidence bars move rather than jump. */
@property --tw-num {
  syntax: "<number>";
  inherits: false;
  initial-value: 0;
}

@property --sweep {
  syntax: "<percentage>";
  inherits: false;
  initial-value: 0%;
}

@property --glow {
  syntax: "<percentage>";
  inherits: false;
  initial-value: 0%;
}

:root {
  /* Motion vocabulary. Four curves, used consistently: anything entering uses
     out-quart, anything travelling a long distance uses out-expo, anything the
     user directly manipulated gets the spring's slight overshoot, and state
     changes that are not worth noticing get the plain one. */
  --ease-out-quart: cubic-bezier(0.25, 1, 0.5, 1);
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-standard: cubic-bezier(0.4, 0, 0.2, 1);

  /* Three durations. More than three and nothing feels deliberate. */
  --t-fast: 130ms;
  --t-base: 220ms;
  --t-slow: 420ms;
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }

  body {
    @apply bg-background text-foreground;
    font-size: 13.5px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    /* Optical sizing and a fractionally tighter tracking. At this size the
       default spacing reads as loose, which is most of what makes a dense
       dashboard look unconsidered. */
    letter-spacing: -0.006em;
    text-rendering: optimizeLegibility;
  }

  /* Headings tighten as they grow, the way a type specimen does. Uniform
     tracking across a scale is the giveaway of a layout nobody set. */
  h1, h2, h3 {
    letter-spacing: -0.021em;
    text-wrap: balance;
  }

  p {
    text-wrap: pretty;
  }

  /* Every price, stake, odds and P&L figure is a number in a column, so the
     digits have to line up -- and the zero needs a slash or it reads as an O
     at 11px. */
  .tabular,
  table {
    font-variant-numeric: tabular-nums;
  }

  .num {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-feature-settings: "zero" 1, "ss01" 1;
    letter-spacing: -0.012em;
  }

  ::selection {
    background: var(--brand-soft);
  }

  /* One focus treatment everywhere, and never on a mouse click. */
  :focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
  }
}

@layer components {
  /* Wide content scrolls inside its own container. The page body must never
     scroll sideways -- it did, at 375px, by 38 pixels. */
  .scroll-x {
    @apply overflow-x-auto;
    -webkit-overflow-scrolling: touch;

    /* Shadows that appear only on the edge with content scrolled off it.
       A twelve-column table always overflows on a laptop, and until now the
       only clue was a column sliced in half at the frame -- which reads as a
       layout bug rather than as an invitation to scroll.

       The trick is `background-attachment`: the two covers scroll WITH the
       content (`local`) and so slide away from an edge that has more to show,
       uncovering the shadow beneath, which is pinned to the frame (`scroll`). */
    background:
      linear-gradient(to right, var(--card) 30%, transparent) left / 28px 100% no-repeat,
      linear-gradient(to left, var(--card) 30%, transparent) right / 28px 100% no-repeat,
      radial-gradient(farthest-side at 0 50%, oklch(0 0 0 / 0.13), transparent)
        left / 11px 100% no-repeat,
      radial-gradient(farthest-side at 100% 50%, oklch(0 0 0 / 0.13), transparent)
        right / 11px 100% no-repeat;
    background-color: var(--card);
    background-attachment: local, local, scroll, scroll;
  }

  /* A row that behaves as a button. Keyboard-reachable, which the bare
     `<tr onClick>` it replaces was not. The left rule appears on hover rather
     than a full-row tint: at this density a background change on every hover
     makes the whole table flicker as the pointer crosses it. */
  .row-action {
    @apply cursor-pointer;
    transition: background-color 120ms ease, box-shadow 120ms ease;
  }
  .row-action:hover {
    background: color-mix(in oklch, var(--brand) 5%, transparent);
    box-shadow: inset 2px 0 0 var(--brand);
  }
  .row-action:focus-visible {
    @apply outline-2 outline-offset-[-2px] outline-ring;
  }

  /* The one surface treatment. Components reach for this rather than each
     re-deciding border, radius and elevation -- which is how a dashboard ends
     up with four different card styles on one screen. */
  .surface {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-flat);
  }
  .surface-raised {
    box-shadow: var(--shadow-raised);
  }

  /* Rows inside a surface are separated by the hairline, not the border that
     bounds the surface. */
  .divide-hairline > * + * {
    border-top: 1px solid var(--hairline);
  }

  /* A header that stays put while a long table scrolls under it. */
  .sticky-head th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: color-mix(in oklch, var(--card) 92%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }

  /* Numbers that have just changed are worth a glance, not a fanfare. */
  .flash {
    animation: flash 900ms ease-out;
  }

  /* Placeholder shimmer, so a loading table reads as loading rather than as
     empty. */
  .shimmer {
    background: linear-gradient(
      90deg,
      var(--muted) 25%,
      color-mix(in oklch, var(--muted) 55%, var(--card)) 37%,
      var(--muted) 63%
    );
    background-size: 400% 100%;
    animation: shimmer 1.4s ease-in-out infinite;
  }
  /* ------------------------------------------------------------- motion */

  /* Entrances. `rise` is the house transition: four pixels and a fade, fast
     enough that it registers as the element arriving rather than as an
     animation being played at you. */
  .enter {
    animation: rise var(--t-base) var(--ease-out-quart) both;
  }

  /* Stagger without a JS loop. Each child reads its own index from a custom
     property set inline, so a list of any length cascades in on one rule.
     Capped at twelve: past that the last row waits long enough to feel broken
     rather than choreographed. */
  .stagger > * {
    animation: rise var(--t-base) var(--ease-out-quart) both;
    animation-delay: calc(min(var(--i, 0), 12) * 28ms);
  }

  /* Scroll-driven reveal, running entirely on the compositor -- no observer,
     no scroll listener, no layout thrash. `view()` ties the animation's
     timeline to the element crossing the viewport, so it is frame-perfect at
     any scroll speed. Browsers without it simply show the element, which is
     the correct fallback. */
  @supports (animation-timeline: view()) {
    .reveal {
      animation: rise-far var(--t-slow) var(--ease-out-quart) both;
      animation-timeline: view();
      animation-range: entry 0% cover 18%;
    }
  }

  /* A surface that responds to the pointer. The lift is small and the shadow
     does most of the work: a card that visibly jumps on hover is a card that
     will be hovered accidentally a hundred times an hour. */
  .lift {
    transition:
      transform var(--t-base) var(--ease-out-quart),
      box-shadow var(--t-base) var(--ease-out-quart),
      border-color var(--t-base) var(--ease-out-quart);
    will-change: transform;
  }
  .lift:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-raised);
    border-color: var(--border-strong);
  }

  /* A live figure that has just changed. The sweep runs a highlight across the
     number once; the eye catches motion far better than it catches a colour
     that was already there when you looked. */
  .tick {
    animation: sweep 720ms var(--ease-out-expo);
  }

  /* Buttons and rows compress very slightly on press. This is the whole of
     what makes an interface feel physical rather than photographic. */
  .press {
    transition: transform var(--t-fast) var(--ease-out-quart);
  }
  .press:active {
    transform: scale(0.98);
  }

  /* An indeterminate progress hairline for the top of the page during a scan.
     Two bars at different phases, which reads as continuous motion without
     ever implying a percentage the engine does not know. */
  .indeterminate::before,
  .indeterminate::after {
    content: "";
    position: absolute;
    inset-block: 0;
    background: var(--brand);
    border-radius: 999px;
  }
  .indeterminate::before {
    animation: slide-a 2.1s var(--ease-standard) infinite;
  }
  .indeterminate::after {
    animation: slide-b 2.1s var(--ease-standard) 1.15s infinite;
  }
}

@keyframes rise-far {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: none; }
}

@keyframes sweep {
  0% { background: var(--brand-soft); }
  100% { background: transparent; }
}

@keyframes slide-a {
  0% { left: -35%; right: 100%; }
  60%, 100% { left: 100%; right: -90%; }
}

@keyframes slide-b {
  0% { left: -200%; right: 100%; }
  60%, 100% { left: 107%; right: -8%; }
}

@keyframes flash {
  from { background-color: var(--brand-soft); }
  to { background-color: transparent; }
}

@keyframes shimmer {
  from { background-position: 100% 50%; }
  to { background-position: 0 50%; }
}

@keyframes rise {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
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
        + "\n/* Light is the base. */\n:root {\n  --radius: 0.5rem;\n"
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
