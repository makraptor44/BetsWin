"""The Python half of the shared odds vectors.

`frontend/lib/staticMath.ts` is a port of `arbengine/odds.py`, and the README
claims the two produce identical results. They did not: `calcConvert(0,
"american")` returned {decimal: Infinity} in TypeScript where Python raised, and
the demo backtest silently dropped per-venue void rates.

Both suites now assert against `shared/odds-vectors.json`, so a divergence fails
a test rather than reaching a user. The TypeScript half is
`frontend/lib/__tests__/sharedVectors.test.ts`.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

from arbengine import odds as om

VECTORS = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "shared" / "odds-vectors.json").read_text(
        encoding="utf-8"
    )
)


def cases(name: str):
    return VECTORS[name]


class TestSharedVectors:
    @pytest.mark.parametrize("c", cases("decimal_to_prob"))
    def test_decimal_to_prob(self, c):
        assert om.decimal_to_prob(c["d"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("book"))
    def test_book(self, c):
        assert om.book(c["odds"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("arb_margin"))
    def test_arb_margin(self, c):
        assert om.arb_margin(c["b"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("equal_profit_stakes"))
    def test_equal_profit_stakes(self, c):
        got = om.equal_profit_stakes(c["odds"], c["total"])
        assert got == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("devig_proportional"))
    def test_devig_proportional(self, c):
        assert om.devig_proportional(c["odds"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("kelly_fraction"))
    def test_kelly_fraction(self, c):
        assert om.kelly_fraction(c["p"], c["d"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("margin_after_voids"))
    def test_margin_after_voids(self, c):
        assert om.margin_after_voids(c["m"], c["v"], c["l"]) == pytest.approx(
            c["expected"]
        )

    @pytest.mark.parametrize("c", cases("kelly_arb_fraction"))
    def test_kelly_arb_fraction(self, c):
        got = om.kelly_arb_fraction(c["m"], c["v"], c["l"])
        if c.get("unbounded"):
            assert math.isinf(got), "no void cost means Kelly places no bound"
        else:
            assert got == pytest.approx(c["expected"])

    @pytest.mark.parametrize("c", cases("american_to_decimal"))
    def test_american_to_decimal(self, c):
        assert om.american_to_decimal(c["a"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("a", cases("american_to_decimal_rejects"))
    def test_american_to_decimal_rejects(self, a):
        with pytest.raises(ValueError):
            om.american_to_decimal(a)

    @pytest.mark.parametrize("c", cases("decimal_to_american"))
    def test_decimal_to_american(self, c):
        assert om.decimal_to_american(c["d"]) == pytest.approx(c["expected"])

    @pytest.mark.parametrize("d", cases("decimal_to_american_rejects"))
    def test_decimal_to_american_rejects(self, d):
        with pytest.raises(ValueError):
            om.decimal_to_american(d)

    @pytest.mark.parametrize("c", cases("round_down_to_step"))
    def test_round_down_to_step(self, c):
        assert om.round_down_to_step(c["value"], c["step"]) == pytest.approx(
            c["expected"]
        )
