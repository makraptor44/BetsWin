"""Correlation-arb detector: wiring correlation_arb.py to the scanner pipeline."""

from __future__ import annotations

import pytest

from arbengine import correlation_arb as ca
from arbengine.config import settings
from arbengine.correlation_detector import evaluate_pair, scan_correlation_pairs
from arbengine.fees import configure_from_settings
from arbengine.models import ArbKind, Event, Market, Outcome, Quote, RiskFlag, Side
from arbengine.storage import ArbStore

configure_from_settings(settings)


def quote(mid: str, name: str, side: Side, price: float, size: float = 8000.0) -> Quote:
    """Fee-free quote, matching test_detector.py's convention, so the maths in
    these tests can be checked directly against correlation_arb.py."""
    return Quote(
        venue="kalshi",
        market_id=mid,
        ticker=mid,
        outcome=name,
        side=side,
        price=price,
        effective_price=price,
        size_available=size,
    )


def binary_event(event_id: str, title: str, mid: str, yes_price: float) -> Event:
    return Event(
        id=event_id,
        venue="kalshi",
        title=title,
        markets=(
            Market(
                key="binary",
                outcomes=(
                    Outcome(name="Yes", quotes=(quote(f"{mid}:Y", "Yes", Side.YES, yes_price),)),
                    Outcome(
                        name="No",
                        quotes=(quote(f"{mid}:N", "No", Side.NO, round(1.0 - yes_price, 4)),),
                    ),
                ),
            ),
        ),
    )


PAIR = {
    "key": "test_pair",
    "label": "Test pair",
    "venue": "kalshi",
    "market_id_a": "A:Y",
    "outcome_a": "Yes",
    "market_id_b": "B:Y",
    "outcome_b": "Yes",
    "market_id_joint": "J:Y",
    "outcome_joint": "Yes",
    "rho_prior_override": None,
    "min_edge": None,
    "kelly_fraction": None,
    "enabled": True,
}


def events_for(p_a: float, p_b: float, p_joint: float) -> list[Event]:
    return [
        binary_event("kalshi:a", "Event A", "A", p_a),
        binary_event("kalshi:b", "Event B", "B", p_b),
        binary_event("kalshi:j", "Event A and B", "J", p_joint),
    ]


@pytest.fixture
def store(tmp_path):
    s = ArbStore(str(tmp_path / "test_correlation.db"))
    yield s
    s.close()


class TestEvaluatePairWithOverride:
    def test_underpriced_joint_contract_is_a_buy(self):
        p_a, p_b, rho_prior = 0.55, 0.50, 0.6
        p_joint = ca.joint_probability(p_a, p_b, 0.3)  # market implies a lower rho
        pair = {**PAIR, "rho_prior_override": rho_prior}

        arb = evaluate_pair(pair, events_for(p_a, p_b, p_joint))

        assert arb is not None
        assert arb.kind is ArbKind.CORRELATION
        assert arb.strategy == "directional"
        assert arb.legs[0].side == Side.YES
        assert arb.legs[0].outcome == "Yes"
        assert arb.worst_case_profit == pytest.approx(-arb.total_stake)
        assert arb.profit > 0
        assert RiskFlag.STATISTICAL_EDGE in arb.flags

    def test_overpriced_joint_contract_is_a_sell(self):
        p_a, p_b, rho_prior = 0.55, 0.50, 0.2
        p_joint = ca.joint_probability(p_a, p_b, 0.8)  # market implies a higher rho
        pair = {**PAIR, "rho_prior_override": rho_prior}

        arb = evaluate_pair(pair, events_for(p_a, p_b, p_joint))

        assert arb is not None
        assert arb.legs[0].side == Side.NO
        assert arb.legs[0].outcome == "No"

    def test_fairly_priced_joint_contract_produces_no_trade(self):
        p_a, p_b, rho_prior = 0.55, 0.50, 0.4
        p_joint = ca.joint_probability(p_a, p_b, rho_prior)
        pair = {**PAIR, "rho_prior_override": rho_prior}

        assert evaluate_pair(pair, events_for(p_a, p_b, p_joint)) is None

    def test_missing_leg_on_the_tape_produces_no_trade(self):
        pair = {**PAIR, "rho_prior_override": 0.5}
        events = events_for(0.55, 0.50, 0.3)[:2]  # joint contract not on the tape
        assert evaluate_pair(pair, events) is None

    def test_infeasible_prices_do_not_crash(self):
        """p_joint above min(p_a, p_b) is inconsistent under any copula."""
        pair = {**PAIR, "rho_prior_override": 0.5}
        events = events_for(0.30, 0.40, 0.35)  # 0.35 > min(0.30, 0.40)
        assert evaluate_pair(pair, events) is None

    def test_no_rho_prior_available_produces_no_trade(self):
        pair = {**PAIR, "rho_prior_override": None}
        events = events_for(0.55, 0.50, 0.3)
        assert evaluate_pair(pair, events, store=None) is None


class TestRhoPriorFromHistory:
    def test_pair_trades_off_stored_historical_outcomes(self, store: ArbStore):
        store.upsert_correlation_pair(PAIR)
        for label, a, b in [("1", True, True), ("2", False, False), ("3", True, True), ("4", False, True)]:
            store.add_correlation_outcome(PAIR["key"], label, a, b)

        outcomes = store.list_correlation_outcomes(PAIR["key"])
        rho_prior = ca.estimate_rho_prior_from_outcomes(
            [int(o["outcome_a"]) for o in outcomes], [int(o["outcome_b"]) for o in outcomes]
        )
        p_a, p_b = 0.55, 0.50
        p_joint = ca.joint_probability(p_a, p_b, rho_prior * 0.5)  # market underestimates it

        arb = evaluate_pair(PAIR, events_for(p_a, p_b, p_joint), store=store)

        assert arb is not None
        assert f"rho_prior={rho_prior:.2f}" in arb.notes[0]
        assert "historical, n=4" in arb.notes[0]

    def test_too_few_historical_outcomes_produces_no_trade(self, store: ArbStore):
        store.upsert_correlation_pair(PAIR)
        store.add_correlation_outcome(PAIR["key"], "1", True, True)  # only one instance
        assert evaluate_pair(PAIR, events_for(0.55, 0.50, 0.2), store=store) is None

    def test_small_sample_is_scored_down(self, store: ArbStore):
        store.upsert_correlation_pair(PAIR)
        for label, a, b in [("1", True, True), ("2", False, False)]:  # n=2, below the confidence floor
            store.add_correlation_outcome(PAIR["key"], label, a, b)
        outcomes = store.list_correlation_outcomes(PAIR["key"])
        rho_prior = ca.estimate_rho_prior_from_outcomes(
            [int(o["outcome_a"]) for o in outcomes], [int(o["outcome_b"]) for o in outcomes]
        )
        p_a, p_b = 0.55, 0.50
        p_joint = ca.joint_probability(p_a, p_b, rho_prior * 0.3)
        arb = evaluate_pair(PAIR, events_for(p_a, p_b, p_joint), store=store)
        assert arb is not None
        assert arb.confidence < 100


class TestScanCorrelationPairs:
    def test_disabled_globally_returns_nothing(self, store: ArbStore, monkeypatch):
        store.upsert_correlation_pair({**PAIR, "rho_prior_override": 0.5})
        monkeypatch.setattr(settings, "enable_correlation_arb", False)
        assert scan_correlation_pairs(events_for(0.55, 0.50, 0.3), store) == []
        monkeypatch.setattr(settings, "enable_correlation_arb", True)

    def test_disabled_pair_is_skipped(self, store: ArbStore):
        store.upsert_correlation_pair({**PAIR, "rho_prior_override": 0.6, "enabled": False})
        p_joint = ca.joint_probability(0.55, 0.50, 0.3)
        assert scan_correlation_pairs(events_for(0.55, 0.50, p_joint), store) == []

    def test_a_bad_pair_does_not_stop_the_scan(self, store: ArbStore):
        store.upsert_correlation_pair({**PAIR, "key": "broken", "rho_prior_override": None})
        store.upsert_correlation_pair({**PAIR, "key": "good", "rho_prior_override": 0.6})
        p_joint = ca.joint_probability(0.55, 0.50, 0.2)
        arbs = scan_correlation_pairs(events_for(0.55, 0.50, p_joint), store)
        assert len(arbs) == 1
