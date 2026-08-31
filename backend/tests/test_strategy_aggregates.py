"""Guaranteed profit and directional risk must never be added together.

An arbitrage's `worst_case_profit` is a profit it cannot fail to make. A
directional position's is what it loses when the bet is wrong -- the negative of
its whole stake. Summing the two produces a number that means nothing, and on
the deployed demo it produced a headline of "Profit available: -$72.68" from
$83.78 of real arbitrage plus one correlation position at -$156.46.
"""

from __future__ import annotations

import pytest

from arbengine.models import Arb, ArbKind, ArbLeg, Side


def _arb(id_: str, strategy: str, worst: float, stake: float) -> Arb:
    leg = ArbLeg(
        venue="kalshi",
        market_id=f"m-{id_}",
        outcome="Yes",
        side=Side.YES,
        price=0.5,
        effective_price=0.5,
        decimal_odds=2.0,
        effective_decimal_odds=2.0,
        stake=stake,
        contracts=stake / 0.5,
    )
    return Arb(
        id=id_,
        kind=ArbKind.CORRELATION if strategy == "directional" else ArbKind.BINARY_COMPLEMENT,
        strategy=strategy,
        title=id_,
        venues=("kalshi",),
        legs=(leg,),
        total_stake=stake,
        worst_case_profit=worst,
        net_margin=0.02,
        confidence=80,
    )


#: The exact shape of the deployed demo tape that produced the negative headline.
LIVE = [
    _arb("corr", "directional", -156.46, 156.46),
    _arb("cross", "arbitrage", 38.01, 499.99),
    _arb("dutch", "arbitrage", 18.12, 499.98),
    _arb("binary", "arbitrage", 8.13, 499.99),
    _arb("dutch2", "arbitrage", 6.87, 500.00),
    _arb("cross2", "arbitrage", 7.74, 499.99),
    _arb("dutch3", "arbitrage", 4.91, 499.99),
]


def _guaranteed(live):
    return round(sum(a.worst_case_profit for a in live if a.strategy != "directional"), 2)


def _at_risk(live):
    return round(sum(a.total_stake for a in live if a.strategy == "directional"), 2)


class TestLiveAggregates:
    def test_naive_sum_is_the_bug_being_fixed(self):
        """Documents the old behaviour so the regression is unmistakable."""
        assert round(sum(a.worst_case_profit for a in LIVE), 2) == -72.68

    def test_guaranteed_profit_counts_arbitrage_only(self):
        assert _guaranteed(LIVE) == 83.78
        assert _guaranteed(LIVE) > 0

    def test_directional_exposure_is_reported_as_risk_not_profit(self):
        assert _at_risk(LIVE) == 156.46

    def test_a_tape_of_only_directional_positions_has_no_guaranteed_profit(self):
        only = [_arb("d1", "directional", -100.0, 100.0)]
        assert _guaranteed(only) == 0.0
        assert _at_risk(only) == 100.0

    def test_a_tape_of_only_arbitrage_has_no_directional_risk(self):
        only = [_arb("a1", "arbitrage", 10.0, 500.0)]
        assert _guaranteed(only) == 10.0
        assert _at_risk(only) == 0.0

    def test_guaranteed_profit_is_never_negative_for_real_arbitrage(self):
        """Every surfaced arbitrage locks a profit, so the total cannot go under."""
        arbs = [a for a in LIVE if a.strategy != "directional"]
        assert all(a.worst_case_profit > 0 for a in arbs)
        assert _guaranteed(arbs) == pytest.approx(sum(a.worst_case_profit for a in arbs))


class TestStrategyIsPersisted:
    def test_strategy_survives_a_round_trip_through_the_store(self, tmp_path):
        from arbengine.storage import ArbStore

        store = ArbStore(str(tmp_path / "t.db"))
        try:
            arb_id = store.upsert_arb(_arb("corr-store", "directional", -50.0, 50.0))
            row = store.arb_by_id(arb_id)
            assert row["strategy"] == "directional"

            arb_id2 = store.upsert_arb(_arb("arb-store", "arbitrage", 5.0, 200.0))
            assert store.arb_by_id(arb_id2)["strategy"] == "arbitrage"
        finally:
            store.close()

    def test_sql_can_separate_the_two(self, tmp_path):
        """The split has to work in aggregate queries, not just in Python."""
        from arbengine.storage import ArbStore

        store = ArbStore(str(tmp_path / "t.db"))
        try:
            for a in LIVE:
                store.upsert_arb(a)
            rows = store._rows(
                "SELECT strategy, SUM(worst_case_profit) p FROM arbs GROUP BY strategy"
            )
            by = {r["strategy"]: r["p"] for r in rows}
            assert by["arbitrage"] == pytest.approx(83.78)
            assert by["directional"] == pytest.approx(-156.46)
        finally:
            store.close()
