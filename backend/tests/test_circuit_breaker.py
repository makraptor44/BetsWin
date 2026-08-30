"""What the circuit breaker is counting.

The breaker exists to catch a feed that has gone wrong -- a mis-parsed title, a
stale tape, two different lines compared as one -- which shows up as a burst of
implausibly fat margins arriving together (Part II s16.4). A genuinely wide
book that simply stands for a while is not that, but the scanner re-detects it
on every cycle, so a breaker that tallies sightings cannot tell the two apart
and eventually halts on the honest one.

These tests pin the distinction: many opportunities trip it, one opportunity
seen many times does not.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from arbengine.models import Arb, ArbKind, utcnow
from arbengine.scanner import CircuitBreaker


def _arb(arb_id: str, margin: float = 0.15) -> Arb:
    return Arb(id=arb_id, kind=ArbKind.BINARY_COMPLEMENT, title=arb_id, net_margin=margin)


def test_a_burst_of_distinct_opportunities_trips_it():
    """The signal it is built for: many different books, all implausible."""
    b = CircuitBreaker(threshold=5, window_seconds=60, min_margin=0.10)
    for i in range(4):
        assert b.record(_arb(f"arb-{i}")) is False
    assert b.record(_arb("arb-4")) is True
    assert b.tripped
    assert "5 distinct opportunities" in (b.reason or "")


def test_one_opportunity_seen_every_cycle_does_not_trip_it():
    """The regression: persistence is not burstiness.

    A single wide book re-detected on 200 consecutive cycles is one
    mispricing, not two hundred, and must not halt the scanner.
    """
    b = CircuitBreaker(threshold=5, window_seconds=60, min_margin=0.10)
    standing = _arb("one-persistent-book")
    for _ in range(200):
        b.record(standing)
    assert not b.tripped, "a single standing opportunity halted the scanner"


def test_margins_below_the_floor_are_ignored():
    """Ordinary edge is not evidence of a broken feed."""
    b = CircuitBreaker(threshold=3, window_seconds=60, min_margin=0.10)
    for i in range(50):
        b.record(_arb(f"normal-{i}", margin=0.02))
    assert not b.tripped


def test_sightings_outside_the_window_stop_counting():
    """The window is what makes it a burst detector rather than a total."""
    b = CircuitBreaker(threshold=3, window_seconds=60, min_margin=0.10)
    b.record(_arb("a"))
    b.record(_arb("b"))
    # Age both sightings out of the window.
    stale = utcnow() - timedelta(seconds=120)
    b._seen = {k: stale for k in b._seen}
    assert b.record(_arb("c")) is False
    assert not b.tripped, "expired sightings must not count toward the threshold"


def test_reset_clears_the_trip():
    b = CircuitBreaker(threshold=2, window_seconds=60, min_margin=0.10)
    b.record(_arb("x"))
    assert b.record(_arb("y")) is True
    b.reset()
    assert not b.tripped and b.reason is None
    assert b.record(_arb("z")) is False
