"""Where a leg set can actually be placed from.

Getting this wrong surfaces a trade nobody can take, which is worse than
surfacing nothing: it looks like an opportunity right up until the account
application is refused.
"""

from __future__ import annotations

import pytest

from arbengine.venues import (
    Zone,
    blocked_jurisdictions,
    can_pair,
    common_jurisdictions,
    legs_are_placeable,
    venue,
)


class TestWildcardDoesNotSwallowExclusions:
    """A wildcard is not a licence to ignore who a venue turns away.

    Polymarket is jurisdictions={"*"}, excluded={"US"}. Pairing it with Kalshi
    short-circuited to ("*",), and since "*" is not a country code the exclusion
    filter could never remove anything -- so the pair read as placeable from
    anywhere, US included, and `operator_jurisdiction` defaults to blank so
    nothing downstream caught it.
    """

    def test_the_exclusion_survives_the_wildcard(self):
        assert common_jurisdictions("polymarket", "kalshi") == ("*",)
        assert blocked_jurisdictions("polymarket", "kalshi") == ("US",)

    def test_the_verdict_carries_the_exclusion(self):
        verdict = can_pair("polymarket", "kalshi")
        assert verdict.ok
        assert verdict.jurisdictions == ("*",)
        assert "US" in verdict.excluded

    def test_a_us_operator_is_still_refused(self):
        verdict = can_pair("polymarket", "kalshi", "US")
        assert not verdict.ok
        assert "does not serve US" in verdict.reason

    def test_a_gb_operator_is_allowed(self):
        assert can_pair("polymarket", "kalshi", "GB").ok


class TestEveryLegIsIntersected:
    """`legs_are_placeable` used to answer for the first and last venue only.

    It walked consecutive pairs and then returned `can_pair(first, last)`, whose
    jurisdictions are that pair's intersection -- so on a three-leg book across
    A, B and C the answer could name a country B does not serve.
    """

    def test_three_legs_intersect_all_of_them(self):
        verdict = legs_are_placeable(["betfair", "smarkets", "betfair"])
        assert verdict.ok
        both = venue("betfair").jurisdictions & venue("smarkets").jurisdictions
        blocked = venue("betfair").excluded | venue("smarkets").excluded
        assert set(verdict.jurisdictions) == both - blocked

    def test_no_named_country_is_unserved_by_any_leg(self):
        names = ["betfair", "smarkets"]
        verdict = legs_are_placeable(names)
        for cc in verdict.jurisdictions:
            if cc == "*":
                continue
            for n in names:
                assert venue(n).serves(cc), f"{n} does not serve {cc}"

    def test_a_set_spanning_zones_is_refused(self):
        verdict = legs_are_placeable(["kalshi", "betfair"])
        assert not verdict.ok
        assert "execution zone" in verdict.reason

    def test_a_single_venue_set_is_fine(self):
        verdict = legs_are_placeable(["kalshi"])
        assert verdict.ok
        assert verdict.zone is Zone.US_PREDICTION

    def test_a_single_venue_the_operator_cannot_reach_is_refused(self):
        verdict = legs_are_placeable(["polymarket"], "US")
        assert not verdict.ok

    def test_an_empty_set_is_refused_rather_than_crashing(self):
        assert not legs_are_placeable([]).ok

    def test_repeated_venues_collapse(self):
        once = legs_are_placeable(["smarkets"])
        twice = legs_are_placeable(["smarkets", "smarkets"])
        assert twice.ok == once.ok
        assert set(twice.jurisdictions) == set(once.jurisdictions)


class TestExclusionsAcrossASet:
    def test_blocked_is_the_union_across_every_venue(self):
        blocked = set(blocked_jurisdictions("betfair", "smarkets"))
        assert blocked == set(venue("betfair").excluded) | set(
            venue("smarkets").excluded
        )

    @pytest.mark.parametrize("cc", ["US", "FR", "IT", "AU"])
    def test_an_excluded_country_never_appears_as_placeable(self, cc):
        verdict = legs_are_placeable(["betfair", "smarkets"])
        assert cc not in verdict.jurisdictions
