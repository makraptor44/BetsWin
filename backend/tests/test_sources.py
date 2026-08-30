"""Source adapters: the shape of what they hand the detector.

Everything venue-specific stops at the source layer, so a wrong unit or a
missing field here is invisible everywhere downstream until it shows up as a
number nobody can explain.
"""

from __future__ import annotations

import pytest

from arbengine.config import settings
from arbengine.sizing import book_capacity, size_arb
from arbengine.sources.odds_api import OddsAPISource


def _raw_h2h(price_home: float = 2.10, price_away: float = 2.05) -> dict:
    """One event as The Odds API returns it: two books, h2h, decimal odds."""
    return {
        "id": "evt-1",
        "sport_title": "NFL",
        "home_team": "Chiefs",
        "away_team": "Bills",
        "commence_time": "2026-09-01T18:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "last_update": "2026-08-30T12:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Chiefs", "price": price_home},
                            {"name": "Bills", "price": 1.80},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "last_update": "2026-08-30T12:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Chiefs", "price": 1.85},
                            {"name": "Bills", "price": price_away},
                        ],
                    }
                ],
            },
        ],
    }


class TestSportsbookSizeIsAnExplicitAssumption:
    """The feed has no depth, so the size must come from stated policy.

    Quotes used to carry `size_available=0.0`, which the sizer's depth cap
    skipped rather than stopped on -- so every sportsbook arb was sized as
    though depth were unlimited.
    """

    def test_quotes_carry_the_configured_notional(self):
        src = OddsAPISource()
        ev = src._build_event(_raw_h2h(), "americanfootball_nfl")
        assert ev is not None

        quotes = [q for m in ev.markets for o in m.outcomes for q in o.quotes]
        assert quotes, "expected h2h quotes"
        for q in quotes:
            # size_available is in contracts; notional is contracts * price.
            notional = q.size_available * q.price
            assert notional == pytest.approx(settings.sportsbook_assumed_stake_usd)

    def test_no_quote_reports_zero_capacity(self):
        src = OddsAPISource()
        ev = src._build_event(_raw_h2h(), "americanfootball_nfl")
        for m in ev.markets:
            for o in m.outcomes:
                for q in o.quotes:
                    assert book_capacity(q.depth, q.price, q.size_available) > 0

    def test_a_sportsbook_arb_sizes_within_the_assumed_limit(self):
        """The assumption must actually bind the trade, not decorate it."""
        src = OddsAPISource()
        # 1/2.10 + 1/2.05 = 0.964 -- a real cross-book arb.
        ev = src._build_event(_raw_h2h(2.10, 2.05), "americanfootball_nfl")
        market = ev.markets[0]
        best = [o.best() for o in market.outcomes]
        assert all(b is not None for b in best)

        sized = size_arb(best, target_stake=1e9)
        assert sized is not None
        assert sized.depth_limited, "an assumed limit must constrain the size"
        # Neither leg may be staked past the per-leg assumption.
        for leg in sized.legs:
            assert leg.stake <= settings.sportsbook_assumed_stake_usd + 0.01

    def test_setting_the_limit_to_zero_disables_sportsbook_sizing(self, monkeypatch):
        monkeypatch.setattr(settings, "sportsbook_assumed_stake_usd", 0.0)
        src = OddsAPISource()
        ev = src._build_event(_raw_h2h(2.10, 2.05), "americanfootball_nfl")
        best = [o.best() for o in ev.markets[0].outcomes]
        assert size_arb(best, target_stake=500) is None


class TestSportsbookCounterpartyRisk:
    """Two bookmakers are two counterparties, whatever the feed calls itself."""

    def test_a_cross_book_arb_is_flagged_as_cross_venue(self):
        from arbengine.detector import scan_events
        from arbengine.models import RiskFlag

        src = OddsAPISource()
        ev = src._build_event(_raw_h2h(2.10, 2.05), "americanfootball_nfl")
        arbs = scan_events([ev])
        assert arbs, "expected a cross-book arbitrage"

        arb = arbs[0]
        # Both legs report venue="sportsbook"; the bookmakers are in `ticker`.
        assert {l.venue for l in arb.legs} == {"sportsbook"}
        assert len({l.ticker for l in arb.legs}) == 2
        assert RiskFlag.CROSS_VENUE_RULES in arb.flags, (
            "two books means two rulebooks and two accounts"
        )
        assert any("counterparties" in n for n in arb.notes)

    def test_the_note_names_the_actual_books(self):
        from arbengine.detector import scan_events

        src = OddsAPISource()
        ev = src._build_event(_raw_h2h(2.10, 2.05), "americanfootball_nfl")
        arb = scan_events([ev])[0]
        note = next(n for n in arb.notes if "counterparties" in n)
        assert "draftkings" in note and "fanduel" in note
