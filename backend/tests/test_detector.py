"""Detector tests.

Includes the three cases from Part II s7.4 plus coverage of the
prediction-market-specific detectors and the safety guards that stop the engine
surfacing opportunities that are not real.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from arbengine.config import settings
from arbengine.detector import (
    candidate_events,
    detect_cross_venue,
    detect_dutch,
    detect_intra_market,
    scan_events,
)
from arbengine.fees import configure_from_settings
from arbengine.models import (
    ArbKind,
    DepthLevel,
    Event,
    Market,
    Outcome,
    Quote,
    RiskFlag,
    Side,
    utcnow,
)

configure_from_settings(settings)


# ------------------------------------------------------------------ builders


def quote(venue: str, mid: str, name: str, side: Side, price: float, size: float = 8000.0) -> Quote:
    """A quote with a deep, flat book so sizing is never the binding constraint."""
    return Quote(
        venue=venue,
        market_id=mid,
        ticker=mid,
        outcome=name,
        side=side,
        price=price,
        effective_price=price,  # fee-free, to isolate detector behaviour
        size_available=size,
        depth=(DepthLevel(price=price, size=size),),
        last_update=utcnow(),
    )


def binary(venue: str, mid: str, yes_name: str, no_name: str, yes: float, no: float) -> Market:
    return Market(
        key="binary",
        outcomes=(
            Outcome(name=yes_name, quotes=(quote(venue, f"{mid}:Y", yes_name, Side.YES, yes),)),
            Outcome(name=no_name, quotes=(quote(venue, f"{mid}:N", no_name, Side.NO, no),)),
        ),
    )


def event(
    venue: str,
    eid: str,
    title: str,
    markets: tuple[Market, ...],
    mutually_exclusive: bool = False,
    days_out: int = 30,
) -> Event:
    return Event(
        id=f"{venue}:{eid}",
        venue=venue,
        title=title,
        category="test",
        close_time=utcnow() + timedelta(days=days_out),
        mutually_exclusive=mutually_exclusive,
        volume_usd=1_000_000,
        liquidity_usd=100_000,
        markets=markets,
    )


# --------------------------------------------------- Part II s7.4 base cases


class TestCoreConditions:
    def test_two_way_arb_is_detected(self):
        """Both sides at 2.10 -> B = 0.952, margin ~5%."""
        ev = event("polymarket", "e1", "Test", (binary("polymarket", "m1", "A", "B", 1 / 2.10, 1 / 2.10),))
        arbs = list(detect_intra_market(ev))
        assert len(arbs) == 1
        assert arbs[0].margin == pytest.approx(0.05, abs=0.001)
        assert arbs[0].kind is ArbKind.BINARY_COMPLEMENT

    def test_no_arb_when_book_above_one(self):
        """Both sides at 1.90 -> B = 1.052, no arbitrage."""
        ev = event("polymarket", "e2", "Test", (binary("polymarket", "m1", "A", "B", 1 / 1.90, 1 / 1.90),))
        assert list(detect_intra_market(ev)) == []

    def test_suspiciously_high_margin_is_rejected(self):
        """Both sides at 3.00 is a 50% 'arb' -- a bug or a palpable error."""
        ev = event("polymarket", "e3", "Test", (binary("polymarket", "m1", "A", "B", 1 / 3.0, 1 / 3.0),))
        assert list(detect_intra_market(ev)) == []

    def test_margin_just_above_suspicion_is_flagged_not_dropped(self):
        # 0.46 + 0.48 = 0.94 -> 6.4%, above the 5% suspicion line but plausible.
        ev = event("polymarket", "e4", "Test", (binary("polymarket", "m1", "A", "B", 0.46, 0.48),))
        arbs = list(detect_intra_market(ev))
        assert len(arbs) == 1
        assert RiskFlag.SUSPECT_MARGIN in arbs[0].flags
        assert arbs[0].confidence < 100


# ------------------------------------------------------------- Dutch books


class TestDutchBooks:
    def _nway(self, prices: list[float], mutually_exclusive: bool = True) -> Event:
        markets = tuple(
            binary("polymarket", f"m{i}", f"Cand{i}", f"Not Cand{i}", p, round(1 - p + 0.005, 4))
            for i, p in enumerate(prices)
        )
        return event("polymarket", "dutch", "Who wins?", markets, mutually_exclusive)

    def test_yes_side_dutch_book(self):
        # 0.30 + 0.28 + 0.22 + 0.16 = 0.96 -> 4.17%
        arbs = [a for a in detect_dutch(self._nway([0.30, 0.28, 0.22, 0.16])) if a.kind is ArbKind.DUTCH_YES]
        assert len(arbs) == 1
        assert arbs[0].margin == pytest.approx(1 / 0.96 - 1, abs=1e-3)
        assert len(arbs[0].legs) == 4

    def test_no_dutch_book_without_mutual_exclusivity(self):
        """Without a partition of the sample space the formula does not apply."""
        assert list(detect_dutch(self._nway([0.30, 0.28, 0.22, 0.16], mutually_exclusive=False))) == []

    def test_incomplete_outcome_set_is_rejected(self):
        """Part I s5.2: outcomes summing far below 1 are MISSING, not cheap.

        This is the guard that matters most in production -- a venue paginating a
        20-outcome event would otherwise present a 70% 'arbitrage'.
        """
        arbs = list(detect_dutch(self._nway([0.10, 0.08, 0.05])))
        assert arbs == []

    def test_no_side_dutch_book(self):
        # Five NO legs at 0.78 sum to 3.90 against a $4 payout.
        markets = tuple(
            binary("polymarket", f"m{i}", f"T{i}", f"Not T{i}", 0.202, 0.78) for i in range(5)
        )
        ev = event("polymarket", "sb", "Winner?", markets, mutually_exclusive=True)
        arbs = [a for a in detect_dutch(ev) if a.kind is ArbKind.DUTCH_NO]
        assert len(arbs) == 1
        assert len(arbs[0].legs) == 5

    def test_no_side_needs_at_least_three_outcomes(self):
        """With two outcomes, NO on both is just the complement bet."""
        markets = tuple(
            binary("polymarket", f"m{i}", f"T{i}", f"Not T{i}", 0.49, 0.49) for i in range(2)
        )
        ev = event("polymarket", "two", "Winner?", markets, mutually_exclusive=True)
        assert [a for a in detect_dutch(ev) if a.kind is ArbKind.DUTCH_NO] == []

    def test_too_many_legs_is_skipped(self):
        """Part I s5.1: an outright with many outcomes is operationally infeasible."""
        prices = [0.05] * 19 + [0.04]
        assert list(detect_dutch(self._nway(prices))) == []


# ------------------------------------------------------------- cross venue


class TestCrossVenue:
    def test_matching_titles_produce_an_arb(self):
        a = event("polymarket", "a", "Will the Fed cut rates in March 2026?",
                  (binary("polymarket", "pa", "Yes", "No", 0.47, 0.55),))
        b = event("kalshi", "b", "Fed cuts rates in March 2026?",
                  (binary("kalshi", "kb", "Yes", "No", 0.56, 0.50),))
        arbs = list(detect_cross_venue([a, b]))
        assert len(arbs) >= 1
        arb = arbs[0]
        assert arb.kind is ArbKind.CROSS_VENUE
        assert set(arb.venues) == {"polymarket", "kalshi"}
        assert RiskFlag.FUZZY_MATCH in arb.flags
        assert RiskFlag.CROSS_VENUE_RULES in arb.flags

    def test_different_thresholds_never_pair(self):
        """The $100k vs $120k trap -- same words, different bet."""
        a = event("polymarket", "a", "Will Bitcoin reach $100,000 by Dec 31, 2026?",
                  (binary("polymarket", "pa", "Yes", "No", 0.30, 0.30),))
        b = event("kalshi", "b", "Will Bitcoin reach $120,000 by Dec 31, 2026?",
                  (binary("kalshi", "kb", "Yes", "No", 0.30, 0.30),))
        assert list(detect_cross_venue([a, b])) == []

    def test_opposite_directions_never_pair(self):
        a = event("polymarket", "a", "Will CPI be above 3% in 2026?",
                  (binary("polymarket", "pa", "Yes", "No", 0.30, 0.30),))
        b = event("kalshi", "b", "Will CPI be below 3% in 2026?",
                  (binary("kalshi", "kb", "Yes", "No", 0.30, 0.30),))
        assert list(detect_cross_venue([a, b])) == []

    def test_unrelated_markets_never_pair(self):
        a = event("polymarket", "a", "Will Jesus Christ return before 2027?",
                  (binary("polymarket", "pa", "Yes", "No", 0.30, 0.30),))
        b = event("kalshi", "b", "Will the US invade Iran before 2027?",
                  (binary("kalshi", "kb", "Yes", "No", 0.30, 0.30),))
        assert list(detect_cross_venue([a, b])) == []

    def test_same_venue_pairs_are_not_cross_venue(self):
        a = event("polymarket", "a", "Will the Fed cut rates in March 2026?",
                  (binary("polymarket", "pa", "Yes", "No", 0.47, 0.47),))
        b = event("polymarket", "b", "Fed cuts rates in March 2026?",
                  (binary("polymarket", "pb", "Yes", "No", 0.47, 0.47),))
        assert list(detect_cross_venue([a, b])) == []


# ------------------------------------------------------------------ scoring


class TestRiskScoring:
    def test_stale_quotes_lower_confidence(self):
        fresh = binary("polymarket", "m1", "A", "B", 0.48, 0.50)
        stale_q = quote("polymarket", "m2:Y", "A", Side.YES, 0.48).model_copy(
            update={"last_update": utcnow() - timedelta(hours=2)}
        )
        stale = Market(
            key="binary",
            outcomes=(
                Outcome(name="A", quotes=(stale_q,)),
                Outcome(name="B", quotes=(quote("polymarket", "m2:N", "B", Side.NO, 0.50),)),
            ),
        )
        a = list(detect_intra_market(event("polymarket", "f", "T", (fresh,))))[0]
        b = list(detect_intra_market(event("polymarket", "s", "T", (stale,))))[0]
        assert b.confidence < a.confidence
        assert RiskFlag.STALE_QUOTE in b.flags

    def test_imminent_close_lowers_confidence(self):
        m = binary("polymarket", "m1", "A", "B", 0.48, 0.50)
        far = list(detect_intra_market(event("polymarket", "f", "T", (m,), days_out=30)))[0]
        soon = list(detect_intra_market(event("polymarket", "s", "T", (m,), days_out=0)))[0]
        assert soon.confidence < far.confidence
        assert RiskFlag.NEAR_RESOLUTION in soon.flags

    def test_thin_liquidity_is_flagged(self):
        thin = Market(
            key="binary",
            outcomes=(
                Outcome(name="A", quotes=(quote("polymarket", "t:Y", "A", Side.YES, 0.48, size=120),)),
                Outcome(name="B", quotes=(quote("polymarket", "t:N", "B", Side.NO, 0.50, size=120),)),
            ),
        )
        arbs = list(detect_intra_market(event("polymarket", "t", "T", (thin,))))
        assert arbs
        assert RiskFlag.THIN_LIQUIDITY in arbs[0].flags


# ------------------------------------------------------------ orchestration


class TestScanEvents:
    def test_results_are_sorted_by_risk_adjusted_edge(self):
        small = event("polymarket", "s", "Small", (binary("polymarket", "s1", "A", "B", 0.495, 0.500),))
        big = event("polymarket", "b", "Big", (binary("polymarket", "b1", "A", "B", 0.480, 0.500),))
        arbs = scan_events([small, big])
        assert len(arbs) == 2
        assert arbs[0].net_margin > arbs[1].net_margin

    def test_kind_filter(self):
        ev = event("polymarket", "e", "T", (binary("polymarket", "m", "A", "B", 0.48, 0.50),))
        assert scan_events([ev], kinds={ArbKind.DUTCH_YES}) == []
        assert len(scan_events([ev], kinds={ArbKind.BINARY_COMPLEMENT})) == 1

    def test_a_broken_event_does_not_stop_the_scan(self):
        good = event("polymarket", "g", "Good", (binary("polymarket", "g1", "A", "B", 0.48, 0.50),))
        empty = event("polymarket", "b", "Broken", (Market(key="binary", outcomes=()),))
        assert len(scan_events([empty, good])) == 1


class TestCandidateSelection:
    def test_near_threshold_events_are_shortlisted(self):
        near = event("polymarket", "n", "Near", (binary("polymarket", "n1", "A", "B", 0.50, 0.51),))
        far = event("polymarket", "f", "Far", (binary("polymarket", "f1", "A", "B", 0.60, 0.60),))
        ids = {e.id for e in candidate_events([near, far])}
        assert near.id in ids
        assert far.id not in ids
