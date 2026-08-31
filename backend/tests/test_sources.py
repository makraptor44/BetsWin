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
        events = src._build_events(_raw_h2h(), "americanfootball_nfl")
        assert events
        ev = events[0]

        quotes = [q for m in ev.markets for o in m.outcomes for q in o.quotes]
        assert quotes, "expected h2h quotes"
        for q in quotes:
            # size_available is in contracts; notional is contracts * price.
            notional = q.size_available * q.price
            assert notional == pytest.approx(settings.sportsbook_assumed_stake_usd)

    def test_no_quote_reports_zero_capacity(self):
        src = OddsAPISource()
        ev = src._build_events(_raw_h2h(), "americanfootball_nfl")[0]
        for m in ev.markets:
            for o in m.outcomes:
                for q in o.quotes:
                    assert book_capacity(q.depth, q.price, q.size_available) > 0

    def test_a_sportsbook_arb_sizes_within_the_assumed_limit(self):
        """The assumption must actually bind the trade, not decorate it."""
        src = OddsAPISource()
        # 1/2.10 + 1/2.05 = 0.964 -- a real cross-book arb.
        ev = src._build_events(_raw_h2h(2.10, 2.05), "americanfootball_nfl")[0]
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
        ev = src._build_events(_raw_h2h(2.10, 2.05), "americanfootball_nfl")[0]
        best = [o.best() for o in ev.markets[0].outcomes]
        assert size_arb(best, target_stake=500) is None


class TestSportsbookCounterpartyRisk:
    """Two bookmakers are two counterparties, whatever the feed calls itself."""

    def test_a_cross_book_arb_is_flagged_as_cross_venue(self):
        from arbengine.detector import scan_events
        from arbengine.models import RiskFlag

        src = OddsAPISource()
        ev = src._build_events(_raw_h2h(2.10, 2.05), "americanfootball_nfl")[0]
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
        ev = src._build_events(_raw_h2h(2.10, 2.05), "americanfootball_nfl")[0]
        arb = scan_events([ev])[0]
        note = next(n for n in arb.notes if "counterparties" in n)
        assert "draftkings" in note and "fanduel" in note


def _raw_lines() -> dict:
    """One fixture priced on three markets by two books.

    DraftKings and FanDuel agree on the total (44.5) but disagree on the
    handicap: DK has the Chiefs at -3.5, FD at -4.5. Those are different
    questions and must not be combined.
    """
    return {
        "id": "evt-2",
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
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 2.10, "point": 44.5},
                            {"name": "Under", "price": 1.80, "point": 44.5},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Chiefs", "price": 1.95, "point": -3.5},
                            {"name": "Bills", "price": 1.90, "point": 3.5},
                        ],
                    },
                ],
            },
            {
                "key": "fanduel",
                "last_update": "2026-08-30T12:00:00Z",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.85, "point": 44.5},
                            {"name": "Under", "price": 2.05, "point": 44.5},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Chiefs", "price": 2.00, "point": -4.5},
                            {"name": "Bills", "price": 1.85, "point": 4.5},
                        ],
                    },
                ],
            },
        ],
    }


class TestLineMarketsAreKeyedByTheirLine:
    """Two books are only comparable when they priced the same question.

    A handicap or a total is not a moneyline: Over 44.5 and Over 45.5 are
    different bets, and staking both is a middle -- which can win twice, but can
    also LOSE twice. Treating them as one market would report a guaranteed
    profit on a position that is not hedged at all.
    """

    def _markets(self) -> dict:
        src = OddsAPISource()
        ev = src._build_events(_raw_lines(), "americanfootball_nfl")[0]
        return {m.key: m for m in ev.markets}

    def test_the_shared_total_is_one_market_with_both_books(self):
        markets = self._markets()
        assert "totals_44.5" in markets
        over = markets["totals_44.5"].outcome("Over")
        assert over is not None
        assert {q.ticker for q in over.quotes} == {"draftkings", "fanduel"}

    def test_differing_handicaps_stay_separate(self):
        markets = self._markets()
        assert "spreads_-3.5" in markets
        assert "spreads_-4.5" in markets
        for key in ("spreads_-3.5", "spreads_-4.5"):
            for outcome in markets[key].outcomes:
                assert len(outcome.quotes) == 1, (
                    f"{key} pooled two books that priced different lines"
                )

    def test_handicap_keys_carry_the_sign(self):
        """Home -3.5 and home +3.5 are opposite bets, not one market.

        Keying on the absolute point would collapse them, and backing both
        sides of THAT is the same directional bet placed twice.
        """
        src = OddsAPISource()
        favoured = src._market_key(
            "spreads",
            [{"name": "Chiefs", "point": -3.5}, {"name": "Bills", "point": 3.5}],
            "Chiefs",
        )
        underdog = src._market_key(
            "spreads",
            [{"name": "Chiefs", "point": 3.5}, {"name": "Bills", "point": -3.5}],
            "Chiefs",
        )
        assert favoured != underdog

    def test_a_total_quoted_at_two_lines_is_rejected(self):
        """Malformed payload: over and under at different points is not a market."""
        src = OddsAPISource()
        assert (
            src._market_key(
                "totals",
                [{"name": "Over", "point": 44.5}, {"name": "Under", "point": 45.5}],
                "Chiefs",
            )
            is None
        )

    def test_unknown_market_types_are_dropped(self):
        src = OddsAPISource()
        assert src._market_key("player_props", [{"name": "x"}], "Chiefs") is None

    def test_equivalent_line_spellings_produce_one_key(self):
        """2.5 and 2.50 must not become two markets nobody can arb between."""
        src = OddsAPISource()
        a = src._market_key(
            "totals", [{"name": "Over", "point": 2.5}, {"name": "Under", "point": 2.5}], None
        )
        b = src._market_key(
            "totals",
            [{"name": "Over", "point": 2.50}, {"name": "Under", "point": 2.50}],
            None,
        )
        assert a == b == "totals_2.5"
