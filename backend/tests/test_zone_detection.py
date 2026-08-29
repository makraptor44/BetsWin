"""End-to-end: the zone rule as the detector applies it.

`test_venues.py` pins the rule. This pins the consequence -- that a cross-zone
pair priced as an obvious arbitrage produces nothing, while the same prices
inside one zone produce an opportunity. Testing the rule without testing the
wiring would let the guard be correct and unreachable.
"""

from __future__ import annotations

import pytest

from arbengine.config import settings
from arbengine.detector import find_near_misses, scan
from arbengine.fees import configure_from_settings
from arbengine.models import DepthLevel, Event, Market, Outcome, Quote, Side


@pytest.fixture(autouse=True)
def _fees():
    configure_from_settings(settings)


def _quote(venue: str, mid: str, outcome: str, side: Side, price: float) -> Quote:
    from arbengine.fees import fee_model_for

    depth = tuple(
        DepthLevel(price=round(price + i * 0.002, 4), size=20_000.0) for i in range(3)
    )
    return Quote(
        venue=venue,
        market_id=f"{mid}:{side.value}",
        ticker=mid,
        outcome=outcome,
        side=side,
        price=price,
        effective_price=fee_model_for(venue).effective_price(price, 20_000.0),
        size_available=60_000.0,
        depth=depth,
    )


def _binary_event(
    venue: str, ident: str, title: str, yes: float, no: float, currency: str = "USD"
) -> Event:
    return Event(
        id=f"{venue}:{ident}",
        venue=venue,
        title=title,
        category="politics",
        currency=currency,
        volume_usd=1_000_000,
        liquidity_usd=100_000,
        markets=(
            Market(
                key="binary",
                outcomes=(
                    Outcome(name="Yes", quotes=(_quote(venue, ident, "Yes", Side.YES, yes),)),
                    Outcome(name="No", quotes=(_quote(venue, ident, "No", Side.NO, no),)),
                ),
            ),
        ),
    )


#: The same question, priced 8% apart. Whether this is an opportunity depends
#: entirely on whether one person can hold both accounts.
_TITLE_A = "Will Labour win the next UK general election?"
_TITLE_B = "Labour to win the next UK general election"


def test_cross_zone_pair_produces_nothing():
    events = [
        _binary_event("kalshi", "k1", _TITLE_A, 0.46, 0.55),
        _binary_event("betfair", "b1", _TITLE_B, 0.52, 0.46, currency="GBP"),
    ]
    result = scan(events, target_stake=500.0)
    assert [a for a in result.arbs if a.kind.value == "cross_venue"] == []
    assert result.cross_zone_rejected, "the rejection should be reported, not silent"


def test_same_zone_pair_with_the_same_prices_does_produce_one():
    """Control: the prices are arbable, so only the zone rule can be suppressing it."""
    events = [
        _binary_event("kalshi", "k1", _TITLE_A, 0.46, 0.55),
        _binary_event("polymarket", "p1", _TITLE_B, 0.52, 0.46),
    ]
    result = scan(events, target_stake=500.0)
    cross = [a for a in result.arbs if a.kind.value == "cross_venue"]
    assert cross, "same-zone venues at these prices must arb"
    assert cross[0].zone == "us_prediction"
    assert cross[0].currency == "USD"


def test_disabling_the_rule_surfaces_the_cross_zone_pair():
    """The zone rule is policy, not hard-coded blindness -- it can be turned off.

    Uses two USD zones, because the currency guard below is separate and does
    not switch off: hedging dollars with pounds is wrong arithmetic, not a
    configurable preference.
    """
    events = [
        _binary_event("kalshi", "k1", _TITLE_A, 0.46, 0.55),
        _binary_event("sportsbook", "s1", _TITLE_B, 0.52, 0.46),
    ]
    original = settings.enforce_zone_pairing
    settings.enforce_zone_pairing = False
    try:
        result = scan(events, target_stake=500.0)
        assert [a for a in result.arbs if a.kind.value == "cross_venue"]
    finally:
        settings.enforce_zone_pairing = original


def test_currency_mismatch_is_rejected_even_with_the_zone_rule_off():
    """At a 1% margin an unhedged FX leg is larger than the entire edge."""
    events = [
        _binary_event("kalshi", "k1", _TITLE_A, 0.46, 0.55),
        _binary_event("betfair", "b1", _TITLE_B, 0.52, 0.46, currency="GBP"),
    ]
    original = settings.enforce_zone_pairing
    settings.enforce_zone_pairing = False
    try:
        result = scan(events, target_stake=500.0)
        assert [a for a in result.arbs if a.kind.value == "cross_venue"] == []
    finally:
        settings.enforce_zone_pairing = original


def test_operator_jurisdiction_hides_unreachable_venues():
    events = [
        _binary_event("smarkets", "s1", _TITLE_A, 0.46, 0.55, currency="GBP"),
        _binary_event("betfair", "b1", _TITLE_B, 0.52, 0.46, currency="GBP"),
    ]
    original = settings.operator_jurisdiction
    try:
        settings.operator_jurisdiction = "GB"
        assert [a for a in scan(events, 500.0).arbs if a.kind.value == "cross_venue"]

        # Neither exchange serves a US operator, so the same tape yields nothing.
        settings.operator_jurisdiction = "US"
        assert not [a for a in scan(events, 500.0).arbs if a.kind.value == "cross_venue"]
    finally:
        settings.operator_jurisdiction = original


def test_dutch_book_on_one_venue_is_unaffected_by_the_zone_rule():
    """Single-venue structures must not be collateral damage."""
    outcomes = [("Alpha", 0.30), ("Beta", 0.28), ("Gamma", 0.22), ("Delta", 0.17)]
    ev = Event(
        id="polymarket:multi",
        venue="polymarket",
        title="Four-way race",
        category="politics",
        mutually_exclusive=True,
        volume_usd=5_000_000,
        liquidity_usd=400_000,
        markets=tuple(
            Market(
                key="binary",
                outcomes=(
                    Outcome(
                        name=name,
                        quotes=(_quote("polymarket", f"m{i}", name, Side.YES, p),),
                    ),
                    Outcome(
                        name=f"Not {name}",
                        quotes=(
                            _quote("polymarket", f"m{i}", f"Not {name}", Side.NO, round(1 - p + 0.02, 4)),
                        ),
                    ),
                ),
            )
            for i, (name, p) in enumerate(outcomes)
        ),
    )
    arbs = scan([ev], target_stake=500.0).arbs
    assert any(a.kind.value == "dutch_yes" for a in arbs)


# ------------------------------------------------------------- near misses


def test_near_misses_report_books_that_did_not_cross():
    ev = _binary_event("polymarket", "p1", "A tight book", 0.50, 0.505)
    misses = find_near_misses([ev])
    assert misses
    assert misses[0].gap_bps > 0
    assert misses[0].zone == "us_prediction"


def test_a_crossed_book_is_not_a_near_miss():
    """It is an opportunity; listing it in the watchlist would double-count it."""
    ev = _binary_event("polymarket", "p1", "A crossed book", 0.46, 0.52)
    assert find_near_misses([ev]) == []


def test_near_misses_are_one_row_per_event_and_structure():
    """A 40-outcome event must not contribute 40 rows and crowd out the tape."""
    ev = Event(
        id="kalshi:wide",
        venue="kalshi",
        title="Wide field",
        category="politics",
        mutually_exclusive=True,
        volume_usd=1_000_000,
        liquidity_usd=100_000,
        markets=tuple(
            Market(
                key="binary",
                outcomes=(
                    Outcome(
                        name=f"Runner {i}",
                        quotes=(_quote("kalshi", f"w{i}", f"Runner {i}", Side.YES, 0.10),),
                    ),
                    Outcome(
                        name=f"Not {i}",
                        quotes=(_quote("kalshi", f"w{i}", f"Not {i}", Side.NO, 0.905),),
                    ),
                ),
            )
            for i in range(10)
        ),
    )
    misses = find_near_misses([ev])
    kinds = [m.kind.value for m in misses]
    assert len(kinds) == len(set(kinds)), "one row per structure, not per market"


def test_near_miss_separates_gross_and_net_gaps():
    """The difference between the two is exactly what the fee schedule costs."""
    # Quoted, this book crosses by 50 bps. Kalshi's fee turns it into a miss --
    # which is precisely the number an operator needs to see.
    ev = _binary_event("kalshi", "k1", "Fee-sensitive book", 0.10, 0.895)
    miss = find_near_misses([ev])[0]
    assert miss.gap_bps_gross < 0 < miss.gap_bps
