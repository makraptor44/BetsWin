"""When an opportunity leaves the board, and when it must not.

The scanner holds live opportunities in memory and the dashboard renders that
dict directly, so anything dropped here vanishes from the UI immediately. The
distinction that matters is between a venue that answered and priced the edge
away, and a venue that never answered at all. Both produce an absent leg; only
the first means there is nothing left to trade.

Retiring on both is the bug these tests pin: one timed-out fetch would clear
every opportunity resting on that venue and report it as the market
correcting.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from arbengine.config import settings
from arbengine.demo_data import demo_events
from arbengine.fees import configure_from_settings
from arbengine.models import utcnow
from arbengine.scanner import Scanner
from arbengine.sources.base import Source


@pytest.fixture(autouse=True)
def _engine_settings(tmp_path):
    """Real source path (not demo fixtures), throwaway database."""
    configure_from_settings(settings)
    before = (settings.demo_mode, settings.database_path, settings.stale_arb_seconds)
    settings.demo_mode = False
    settings.database_path = str(tmp_path / "test.db")
    yield
    settings.demo_mode, settings.database_path, settings.stale_arb_seconds = before


class StubSource(Source):
    """Replays one venue's slice of the demo tape.

    `down` raises, which is what a timeout looks like by the time it reaches
    the scanner. `listings` empty is the other case: the venue answered, and
    the answer was that it has nothing.
    """

    def __init__(self, venue: str, events):
        self.name = venue
        self.label = venue
        super().__init__()
        self.listings = [e for e in events if e.venue == venue]
        self.down = False

    async def fetch_events(self):
        if self.down:
            raise RuntimeError("read timeout")
        return list(self.listings)


def _scanner():
    tape = demo_events()
    sources = [StubSource(v, tape) for v in sorted({e.venue for e in tape})]
    return Scanner(sources=sources), sources


def _run(coro_fn):
    """Drive an async scanner sequence from a sync test."""
    return asyncio.run(coro_fn())


def test_stable_feed_holds_every_opportunity():
    """Control: an unchanged tape must not churn the board."""

    async def go():
        sc, _ = _scanner()
        seen = []
        for _ in range(3):
            await sc.scan_once()
            seen.append({a.id for a in sc.live_arbs()})
        await sc.close()
        return seen

    first, second, third = _run(go)
    assert first, "the demo tape should price at least one arbitrage"
    assert first == second == third


def test_venue_that_answers_with_nothing_retires_its_opportunities():
    """The genuine close. A healthy venue with no listings means the edge is gone."""

    async def go():
        sc, sources = _scanner()
        await sc.scan_once()
        before = {a.id for a in sc.live_arbs()}

        # Answers normally, just has nothing to say.
        for s in sources:
            s.listings = []
        await sc.scan_once()
        after = {a.id for a in sc.live_arbs()}
        unconfirmed = sc.last_scan.arbs_unconfirmed
        await sc.close()
        return before, after, unconfirmed

    before, after, unconfirmed = _run(go)
    assert before
    assert after == set(), "a venue that answered must retire its own opportunities"
    assert unconfirmed == 0, "nothing was held back -- every venue replied"


def test_unreachable_venue_holds_opportunities_instead_of_retiring_them():
    """The regression. A failed fetch must not read as a market correction."""

    async def go():
        sc, sources = _scanner()
        await sc.scan_once()
        before = {a.id for a in sc.live_arbs()}

        for s in sources:
            s.down = True
        await sc.scan_once()
        during = {a.id for a in sc.live_arbs()}
        stats = sc.last_scan

        for s in sources:
            s.down = False
        await sc.scan_once()
        after = {a.id for a in sc.live_arbs()}
        await sc.close()
        return before, during, after, stats

    before, during, after, stats = _run(go)
    assert before
    assert during == before, "a total outage wiped the board"
    assert stats.arbs_found == 0 and stats.events_scanned == 0
    assert stats.arbs_unconfirmed == len(before), "held opportunities must be counted"
    assert stats.errors, "the outage itself must still be reported"
    assert after == before


def test_partial_outage_only_holds_the_affected_venue():
    """One dark venue must not disturb opportunities priced entirely elsewhere."""

    async def go():
        sc, sources = _scanner()
        await sc.scan_once()
        before = {a.id for a in sc.live_arbs()}
        dead = "kalshi"
        touching_dead = {
            a.id for a in sc.live_arbs() if any(l.venue == dead for l in a.legs)
        }

        for s in sources:
            if s.name == dead:
                s.down = True
        await sc.scan_once()
        during = {a.id for a in sc.live_arbs()}
        unconfirmed = sc.last_scan.arbs_unconfirmed
        await sc.close()
        return before, during, touching_dead, unconfirmed

    before, during, touching_dead, unconfirmed = _run(go)
    assert touching_dead, "the tape should include kalshi legs for this to mean anything"
    assert during == before, "nothing should be retired while a venue is unreachable"
    # Only the ones that actually depend on the dead venue are unconfirmed; the
    # rest were genuinely re-priced this cycle.
    assert unconfirmed == len(touching_dead)


def test_held_opportunities_expire_once_the_outage_outlasts_the_window():
    """Holding is not forever -- a venue that never comes back stops counting."""

    async def go():
        sc, sources = _scanner()
        await sc.scan_once()
        before = {a.id for a in sc.live_arbs()}

        for s in sources:
            s.down = True
        await sc.scan_once()
        held = {a.id for a in sc.live_arbs()}

        # Age the board past the hold window rather than sleeping through it.
        cutoff = timedelta(seconds=settings.stale_arb_seconds + 60)
        for key, arb in list(sc._live.items()):
            sc._live[key] = arb.model_copy(update={"last_seen": utcnow() - cutoff})

        await sc.scan_once()
        expired = {a.id for a in sc.live_arbs()}
        await sc.close()
        return before, held, expired

    before, held, expired = _run(go)
    assert held == before
    assert expired == set(), "a stale opportunity on a dead venue must eventually go"
