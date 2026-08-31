"""Expiry has to be derived, never assigned.

A countdown running against a number somebody picked is theatre. A trader who
discovers that once will not trust the timer again, and the timer is the whole
basis on which a short-dated opportunity is actionable. So every bound tested
here traces back to something a provider actually told us: when the market
closes, and when each quote was last published.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from arbengine.config import settings
from arbengine.detector import expiry_for, scan_events
from arbengine.fees import configure_from_settings
from arbengine.models import (
    ArbStatus,
    DepthLevel,
    Event,
    Market,
    Outcome,
    Quote,
    Side,
    utcnow,
)

configure_from_settings(settings)


def _quote(price: float, *, age_seconds: float = 0.0, name: str = "Yes") -> Quote:
    return Quote(
        venue="polymarket",
        market_id=f"m:{name}",
        ticker="m",
        outcome=name,
        side=Side.YES,
        price=price,
        effective_price=price,
        size_available=8000.0,
        depth=(DepthLevel(price=price, size=8000.0),),
        last_update=utcnow() - timedelta(seconds=age_seconds),
    )


class TestExpiryDerivation:
    def test_market_close_bounds_it(self):
        """A book comes down at kickoff; nothing priced on it survives that."""
        close = utcnow() + timedelta(minutes=3)
        got = expiry_for([_quote(0.5)], close)
        assert got == close

    def test_quote_staleness_bounds_it(self):
        """With no close time, the horizon runs from the quote's own timestamp."""
        q = _quote(0.5, age_seconds=60)
        got = expiry_for([q], None)
        assert got is not None
        expected = q.last_update + timedelta(seconds=settings.stale_quote_seconds)
        assert abs((got - expected).total_seconds()) < 1e-6

    def test_the_earlier_bound_wins(self):
        """Both are real limits, so the binding one is whichever comes first."""
        soon = utcnow() + timedelta(seconds=30)
        got = expiry_for([_quote(0.5, age_seconds=0)], soon)
        assert got == soon

    def test_the_oldest_leg_binds(self):
        """An arbitrage is only as current as its stalest price."""
        fresh = _quote(0.46, age_seconds=5, name="Yes")
        stale = _quote(0.50, age_seconds=400, name="No")
        got = expiry_for([fresh, stale], None)
        assert got is not None
        expected = stale.last_update + timedelta(seconds=settings.stale_quote_seconds)
        assert abs((got - expected).total_seconds()) < 1e-6

    def test_nothing_knowable_means_no_countdown(self):
        """Inventing a duration here is the fabrication this exists to avoid."""
        assert expiry_for([], None) is None

    def test_disabling_the_horizon_leaves_only_the_close(self, monkeypatch):
        monkeypatch.setattr(settings, "stale_quote_seconds", 0.0)
        assert expiry_for([_quote(0.5)], None) is None


class TestLifecycleStatus:
    """Status is derived from expires_at, so the two can never disagree."""

    @staticmethod
    def _arb_with_expiry(seconds: float):
        ev = Event(
            id="polymarket:e1",
            venue="polymarket",
            title="A crossed book",
            category="politics",
            close_time=utcnow() + timedelta(seconds=seconds),
            volume_usd=1_000_000,
            liquidity_usd=100_000,
            markets=(
                Market(
                    key="binary",
                    outcomes=(
                        Outcome(name="Yes", quotes=(_quote(0.46, name="Yes"),)),
                        Outcome(name="No", quotes=(_quote(0.50, name="No"),)),
                    ),
                ),
            ),
        )
        arbs = scan_events([ev])
        return arbs[0] if arbs else None

    def test_a_long_window_reads_live(self, monkeypatch):
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        arb = self._arb_with_expiry(3600)
        assert arb is not None
        assert arb.status is ArbStatus.LIVE

    def test_inside_the_urgency_window_reads_expiring(self, monkeypatch):
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        arb = self._arb_with_expiry(20)
        assert arb is not None
        assert arb.status is ArbStatus.EXPIRING

    def test_past_the_window_reads_expired(self, monkeypatch):
        """Derived, so a row cannot be LIVE while its own expiry has passed."""
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        arb = self._arb_with_expiry(3600)
        assert arb is not None
        past = arb.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
        assert past.status is ArbStatus.EXPIRED
        assert past.seconds_to_expiry is not None and past.seconds_to_expiry < 0

    def test_invalidation_outranks_the_clock(self, monkeypatch):
        """Re-priced and gone is a different fact from aged out."""
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        arb = self._arb_with_expiry(3600)
        assert arb is not None
        killed = arb.model_copy(update={"invalidated_at": utcnow()})
        assert killed.status is ArbStatus.INVALIDATED

    def test_every_surfaced_opportunity_carries_an_expiry(self, monkeypatch):
        """The acceptance criterion: no active opportunity without a countdown."""
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        arb = self._arb_with_expiry(3600)
        assert arb is not None
        assert arb.expires_at is not None
        assert arb.seconds_to_expiry is not None
        assert arb.seconds_to_expiry > 0


class TestPricesMoved:
    """`last_updated_at` must mean "moved", not "looked at again"."""

    @staticmethod
    def _pair():
        from arbengine.scanner import _prices_moved

        ev_arb = TestLifecycleStatus._arb_with_expiry(3600)
        return _prices_moved, ev_arb

    def test_an_unchanged_reobservation_is_not_an_update(self, monkeypatch):
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        moved, arb = self._pair()
        assert arb is not None
        assert moved(arb, arb) is False

    def test_a_repriced_leg_is_an_update(self, monkeypatch):
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        moved, arb = self._pair()
        assert arb is not None
        legs = list(arb.legs)
        legs[0] = legs[0].model_copy(
            update={"effective_price": legs[0].effective_price + 0.01}
        )
        assert moved(arb, arb.model_copy(update={"legs": tuple(legs)})) is True

    def test_two_legs_moving_against_each_other_still_counts(self, monkeypatch):
        """The margin can be unchanged while the book you meant to hit is gone."""
        monkeypatch.setattr(settings, "max_hours_to_start", 0.0)
        moved, arb = self._pair()
        assert arb is not None
        legs = list(arb.legs)
        legs[0] = legs[0].model_copy(
            update={"effective_price": legs[0].effective_price + 0.01}
        )
        legs[1] = legs[1].model_copy(
            update={"effective_price": legs[1].effective_price - 0.01}
        )
        after = arb.model_copy(
            update={"legs": tuple(legs), "net_margin": arb.net_margin}
        )
        assert moved(arb, after) is True


def test_every_kind_of_opportunity_carries_an_expiry():
    """Including correlation, which builds its Arb outside `_finalise`.

    That path constructs the model directly, so it does not inherit anything
    the shared finaliser adds -- and a correlation row was briefly the one kind
    of opportunity on the board with no countdown against it.
    """
    from arbengine.demo_data import demo_events  # noqa: PLC0415 - demo-only import

    from arbengine.detector import scan_events

    arbs = scan_events(demo_events())
    assert arbs, "the demo fixture should produce opportunities"
    missing = [a.title for a in arbs if a.expires_at is None]
    assert not missing, f"no expiry on: {missing}"
