/**
 * The TypeScript half of the shared odds vectors.
 *
 * `staticMath.ts` is a port of `backend/arbengine/odds.py`, and the README
 * claims the two produce identical results. They did not: `calcConvert(0,
 * "american")` returned {decimal: Infinity} where Python raised, and the demo
 * backtest silently dropped per-venue void rates.
 *
 * Both suites assert against `shared/odds-vectors.json`, whose expected values
 * are generated from the Python implementation. A divergence now fails a test
 * rather than reaching a user.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  arbMargin,
  book,
  calcConvert,
  decimalToProb,
  devigProportional,
  kellyArbFraction,
  kellyFraction,
  marginAfterVoids,
} from "../staticMath";

type Vectors = Record<string, Array<Record<string, never>>> & {
  decimal_to_prob: Array<{ d: number; expected: number }>;
  book: Array<{ odds: number[]; expected: number }>;
  arb_margin: Array<{ b: number; expected: number }>;
  devig_proportional: Array<{ odds: number[]; expected: number[] }>;
  kelly_fraction: Array<{ p: number; d: number; expected: number }>;
  margin_after_voids: Array<{
    m: number;
    v: number;
    l: number;
    expected: number;
  }>;
  kelly_arb_fraction: Array<{
    m: number;
    v: number;
    l: number;
    expected: number | null;
    unbounded?: boolean;
  }>;
  american_to_decimal: Array<{ a: number; expected: number }>;
  american_to_decimal_rejects: number[];
  decimal_to_american: Array<{ d: number; expected: number }>;
  decimal_to_american_rejects: number[];
};

const vectors: Vectors = JSON.parse(
  readFileSync(join(__dirname, "../../../shared/odds-vectors.json"), "utf8"),
);

/** Both sides are IEEE 754 doubles running the same formula. */
const PRECISION = 12;

describe("shared odds vectors", () => {
  it.each(vectors.decimal_to_prob)("decimalToProb($d)", ({ d, expected }) => {
    expect(decimalToProb(d)).toBeCloseTo(expected, PRECISION);
  });

  it.each(vectors.book)("book($odds)", ({ odds, expected }) => {
    expect(book(odds)).toBeCloseTo(expected, PRECISION);
  });

  it.each(vectors.arb_margin)("arbMargin($b)", ({ b, expected }) => {
    expect(arbMargin(b)).toBeCloseTo(expected, PRECISION);
  });

  it.each(vectors.devig_proportional)(
    "devigProportional($odds)",
    ({ odds, expected }) => {
      const got = devigProportional(odds);
      expect(got).toHaveLength(expected.length);
      got.forEach((p, i) => expect(p).toBeCloseTo(expected[i], PRECISION));
    },
  );

  it.each(vectors.kelly_fraction)(
    "kellyFraction($p, $d)",
    ({ p, d, expected }) => {
      expect(kellyFraction(p, d)).toBeCloseTo(expected, PRECISION);
    },
  );

  it.each(vectors.margin_after_voids)(
    "marginAfterVoids($m, $v, $l)",
    ({ m, v, l, expected }) => {
      expect(marginAfterVoids(m, v, l)).toBeCloseTo(expected, PRECISION);
    },
  );

  it.each(vectors.kelly_arb_fraction)(
    "kellyArbFraction($m, $v, $l)",
    ({ m, v, l, expected, unbounded }) => {
      const got = kellyArbFraction(m, v, l);
      if (unbounded) {
        // No void cost means nothing can go wrong, so Kelly places no bound.
        // Returning 0 here would read as "stake nothing".
        expect(Number.isFinite(got)).toBe(false);
      } else {
        expect(got).toBeCloseTo(expected as number, PRECISION);
      }
    },
  );

  it.each(vectors.american_to_decimal)(
    "calcConvert($a, american)",
    ({ a, expected }) => {
      expect(calcConvert(a, "american").decimal).toBeCloseTo(expected, 5);
    },
  );

  it.each(vectors.american_to_decimal_rejects.map((a) => ({ a })))(
    "calcConvert($a, american) is rejected",
    ({ a }) => {
      // Python raises ValueError here. This used to return Infinity.
      expect(() => calcConvert(a, "american")).toThrow();
    },
  );

  it.each(vectors.decimal_to_american)(
    "calcConvert($d, decimal) -> american",
    ({ d, expected }) => {
      expect(calcConvert(d, "decimal").american).toBeCloseTo(expected, 2);
    },
  );

  it.each(vectors.decimal_to_american_rejects.map((d) => ({ d })))(
    "calcConvert($d, decimal) is rejected",
    ({ d }) => {
      expect(() => calcConvert(d, "decimal")).toThrow();
    },
  );
});
