"""Odds mathematics checked against the worked examples in the theory volume."""

from __future__ import annotations

import pytest

from arbengine import odds as om


class TestFormats:
    def test_decimal_probability_roundtrip(self):
        # Part I s2.2: decimal 2.00 = 50%.
        assert om.decimal_to_prob(2.0) == pytest.approx(0.5)
        assert om.prob_to_decimal(0.5) == pytest.approx(2.0)
        assert om.decimal_to_prob(4.0) == pytest.approx(0.25)
        assert om.decimal_to_prob(1.25) == pytest.approx(0.80)

    def test_american_conversion(self):
        # Part I s2.1: decimal 2.00 = fractional 1/1 = American +100.
        assert om.american_to_decimal(100) == pytest.approx(2.0)
        assert om.american_to_decimal(-200) == pytest.approx(1.5)
        assert om.decimal_to_american(2.0) == pytest.approx(100.0)
        assert om.decimal_to_american(1.5) == pytest.approx(-200.0)

    def test_fractional_conversion(self):
        assert om.fractional_to_decimal(1, 1) == pytest.approx(2.0)
        assert om.fractional_to_decimal(5, 2) == pytest.approx(3.5)

    @pytest.mark.parametrize("value", [0, 1, -1, 50, -99, 99.9, -0.0])
    def test_american_odds_inside_plus_minus_100_are_rejected(self, value):
        """American odds have no magnitude below 100.

        `american_to_decimal(0)` used to evaluate 1 + 100/abs(0) and raise
        ZeroDivisionError, which surfaced as a 500 from /api/calc/convert.
        """
        with pytest.raises(ValueError, match="American odds"):
            om.american_to_decimal(value)

    @pytest.mark.parametrize("value", [100, -100, 250, -250])
    def test_american_odds_at_and_beyond_the_boundary_are_accepted(self, value):
        assert om.american_to_decimal(value) > 1.0

    @pytest.mark.parametrize("value", [1.0, 0.5, 0.0, -2.0])
    def test_decimal_to_american_rejects_odds_of_one_or_less(self, value):
        """d = 1.00 returns the stake and nothing else; -100/(d-1) divided by zero."""
        with pytest.raises(ValueError, match="greater than 1.0"):
            om.decimal_to_american(value)

    def test_american_roundtrip_is_stable(self):
        for a in (-500, -250, -110, 100, 150, 400):
            assert om.decimal_to_american(om.american_to_decimal(a)) == pytest.approx(a)

    def test_price_clamping_avoids_division_blowup(self):
        """0 and 1 are clamped to the tightest tick a venue can quote.

        Asserted against MIN_PRICE/MAX_PRICE rather than a literal tolerance:
        the constant moved from 1e-4 to 1e-3 to match its own comment (and
        Polymarket's actual tick), and a hard-coded 1e-3 tolerance here was
        measuring the old value.
        """
        assert om.prob_to_decimal(0.0) == pytest.approx(1.0 / om.MIN_PRICE)
        assert om.prob_to_decimal(1.0) == pytest.approx(1.0 / om.MAX_PRICE)
        # Still finite, still greater than 1, which is the point of the clamp.
        assert 1.0 < om.prob_to_decimal(1.0) < 1.01
        assert om.prob_to_decimal(0.0) > 0


class TestBook:
    def test_overround_positive_at_a_single_book(self):
        # Part I s2.3: B > 1 always at one bookmaker.
        assert om.book([1.90, 1.90]) > 1.0
        assert om.overround([1.90, 1.90]) == pytest.approx(0.0526, abs=1e-4)

    def test_vig(self):
        # v = 1 - 1/B
        b = om.book([1.90, 1.90])
        assert om.vig([1.90, 1.90]) == pytest.approx(1 - 1 / b)

    def test_arbitrage_condition(self):
        # Part I s2.4: arb iff B < 1.
        assert om.is_arbitrage([2.10, 2.10])
        assert not om.is_arbitrage([1.90, 1.90])


class TestWorkedExampleTwoWay:
    """Part I s3.4 -- Djokovic v Alcaraz, 1.95 and 2.15 on GBP 1,000."""

    ODDS = [1.95, 2.15]
    STAKE = 1000.0

    def test_book_and_margin(self):
        b = om.book(self.ODDS)
        assert b == pytest.approx(0.9779, abs=1e-4)
        assert om.arb_margin(b) == pytest.approx(0.0226, abs=1e-4)

    def test_stakes_match_the_document(self):
        s = om.equal_profit_stakes(self.ODDS, self.STAKE)
        assert s[0] == pytest.approx(524.39, abs=0.01)
        assert s[1] == pytest.approx(475.61, abs=0.01)

    def test_payout_identical_in_both_states(self):
        s = om.equal_profit_stakes(self.ODDS, self.STAKE)
        p = om.payouts(s, self.ODDS)
        assert p[0] == pytest.approx(1022.56, abs=0.01)
        assert p[1] == pytest.approx(1022.56, abs=0.01)
        assert p[0] == pytest.approx(p[1])

    def test_profit(self):
        s = om.equal_profit_stakes(self.ODDS, self.STAKE)
        assert om.worst_case_profit(s, self.ODDS) == pytest.approx(22.56, abs=0.01)


class TestWorkedExampleThreeWay:
    """Part I s4.2 -- Man City v Arsenal 1X2 on GBP 1,500."""

    ODDS = [1 / 0.4348, 1 / 0.2632, 1 / 0.2817]
    STAKE = 1500.0

    def test_book_and_margin(self):
        b = om.book(self.ODDS)
        assert b == pytest.approx(0.9797, abs=1e-4)
        assert om.arb_margin(b) == pytest.approx(0.0207, abs=1e-4)

    def test_stakes_and_payout(self):
        # The document quotes its implied probabilities to 4 d.p. and its own
        # figures are slightly inconsistent: it states a payout of 1530.72
        # (profit 30.72) while also quoting m = 2.07%, which on 1500 is 31.05.
        # 1500 / 0.9797 = 1531.08 is the arithmetically correct payout, so the
        # tolerance here covers the document's rounding rather than hiding a bug.
        s = om.equal_profit_stakes(self.ODDS, self.STAKE)
        assert s[0] == pytest.approx(665.72, abs=0.15)
        assert s[1] == pytest.approx(402.90, abs=0.15)
        assert s[2] == pytest.approx(431.38, abs=0.15)
        for payout in om.payouts(s, self.ODDS):
            assert payout == pytest.approx(1531.08, abs=0.05)

    def test_all_three_payouts_are_identical(self):
        s = om.equal_profit_stakes(self.ODDS, self.STAKE)
        p = om.payouts(s, self.ODDS)
        assert p[0] == pytest.approx(p[1]) == pytest.approx(p[2])


class TestKellyAndValue:
    def test_kelly_formula(self):
        # Part I s7.3: f* = (p*d - 1)/(d - 1)
        assert om.kelly_fraction(0.55, 2.0) == pytest.approx(0.10, abs=1e-9)
        assert om.kelly_fraction(0.60, 2.0) == pytest.approx(0.20, abs=1e-9)

    def test_no_edge_means_no_stake(self):
        assert om.kelly_fraction(0.50, 2.0) == 0.0
        assert om.kelly_fraction(0.40, 2.0) == 0.0

    def test_value_bet_condition(self):
        # Part I s12.1: value iff p*d > 1.
        assert om.is_value_bet(0.55, 2.0)
        assert not om.is_value_bet(0.45, 2.0)
        assert om.expected_value(0.55, 2.0) == pytest.approx(0.10)


class TestDevig:
    def test_proportional_devig_sums_to_one(self):
        probs = om.devig_proportional([1.90, 2.10])
        assert sum(probs) == pytest.approx(1.0)

    def test_power_devig_sums_to_one(self):
        probs = om.devig_power([1.90, 2.10, 3.50])
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)

    def test_devig_preserves_ordering(self):
        probs = om.devig_proportional([1.50, 3.00])
        assert probs[0] > probs[1]


class TestExchange:
    def test_commission_adjusted_odds(self):
        # Part I s6.1: 3.00 at 5% commission -> 2.90.
        assert om.exchange_effective_odds(3.0, 0.05) == pytest.approx(2.90)

    def test_lay_stake_hedges_exactly_with_zero_commission(self):
        # Part I s6.2: with c = 0, s_l = s_b * d_b / d_l.
        assert om.lay_stake_to_hedge(100, 2.0, 2.0, 0.0) == pytest.approx(100.0)
        assert om.lay_stake_to_hedge(100, 3.0, 2.0, 0.0) == pytest.approx(150.0)

    def test_liability(self):
        assert om.lay_liability(100, 3.0) == pytest.approx(200.0)

    @pytest.mark.parametrize(
        "d_back,d_lay,commission",
        [
            (2.10, 2.05, 0.02),   # the reported case
            (2.10, 2.05, 0.05),   # Betfair's standard rate
            (3.40, 3.30, 0.02),
            (1.55, 1.50, 0.05),
            (6.00, 5.80, 0.02),   # long odds: commission bites hardest here
        ],
    )
    def test_lay_stake_hedges_exactly_with_commission(self, d_back, d_lay, commission):
        """A hedge must pay the SAME whichever side wins.

        The denominator used to be `d_l - c*(d_l - 1)`, which left the two states
        unequal: backing 100 at 2.10 against a 2.05 lay on 2% commission paid
        +1.3258 if the back won and +1.4293 if the lay won. Commission is charged
        on the winning bet's net winnings, and a winning lay wins the backer's
        stake, so the denominator is `d_l - c`.
        """
        back_stake = 100.0
        lay_stake = om.lay_stake_to_hedge(back_stake, d_back, d_lay, commission)

        # Back wins: collect the back profit, pay out the lay liability.
        profit_back_wins = back_stake * (d_back - 1.0) - om.lay_liability(lay_stake, d_lay)
        # Lay wins: lose the back stake, keep the backer's stake less commission.
        profit_lay_wins = -back_stake + lay_stake * (1.0 - commission)

        assert profit_back_wins == pytest.approx(profit_lay_wins, abs=1e-9)

    def test_lay_stake_agrees_with_the_arb_condition(self):
        """`lay_stake_to_hedge` and `back_lay_is_arb` must not disagree.

        They are two readings of one derivation: if the condition says an arb
        exists, sizing it must produce a positive locked profit, and if it says
        there is none, sizing it must not.
        """
        for d_back, d_lay, c in [
            (2.10, 2.05, 0.02),
            (2.00, 2.05, 0.02),   # no arb
            (2.50, 2.40, 0.05),
            (1.90, 2.00, 0.02),   # no arb
        ]:
            lay_stake = om.lay_stake_to_hedge(100.0, d_back, d_lay, c)
            locked = -100.0 + lay_stake * (1.0 - c)
            assert (locked > 1e-9) == om.back_lay_is_arb(d_back, d_lay, c)

    def test_reported_case_matches_the_hand_calculation(self):
        # back 100 @ 2.10, lay @ 2.05, 2% commission.
        assert om.lay_stake_to_hedge(100.0, 2.10, 2.05, 0.02) == pytest.approx(
            103.4483, abs=1e-4
        )


class TestVoidAdjustment:
    def test_worked_example_from_section_13_3(self):
        # 2% margin, 3% void rate, 30% loss on void -> ~1.04%.
        eff = om.margin_after_voids(0.02, 0.03, 0.30)
        assert eff == pytest.approx(0.0104, abs=1e-4)

    def test_effective_margin_is_about_half_of_nominal(self):
        eff = om.margin_after_voids(0.02, 0.03, 0.30)
        assert eff / 0.02 == pytest.approx(0.52, abs=0.02)

    def test_kelly_arb_bound_from_section_13_4(self):
        # f* ~= 1.73 -- more than the whole bankroll, so bankroll binds.
        f = om.kelly_arb_fraction(0.02, 0.03, 0.30)
        assert f == pytest.approx(1.733, abs=0.01)
        assert f > 1.0

    def test_high_void_rate_destroys_the_edge(self):
        assert om.margin_after_voids(0.02, 0.20, 0.30) < 0


class TestReturns:
    def test_simple_annualised(self):
        # Part I s8.2: 100 turnovers at 1.8% -> 180%.
        assert om.annualised_return(0.018, 100) == pytest.approx(1.80)

    def test_compounding_beats_simple(self):
        assert om.compounded_return(0.018, 100) > om.annualised_return(0.018, 100)


class TestRounding:
    def test_round_down_is_conservative(self):
        assert om.round_down_to_step(10.999, 0.01) == pytest.approx(10.99)
        assert om.round_down_to_step(47.83, 5.0) == pytest.approx(45.0)

    def test_round_to_nearest(self):
        assert om.round_to_step(47.83, 5.0) == pytest.approx(50.0)
        assert om.round_to_step(52.17, 5.0) == pytest.approx(50.0)

    def test_rounding_creates_unequal_profit(self):
        # Part II s8.3: after rounding, profit is no longer identical.
        ds = [1.95, 2.15]
        exact = om.equal_profit_stakes(ds, 1000.0)
        rounded = [om.round_to_step(s, 5.0) for s in exact]
        profits = om.profit_by_outcome(rounded, ds)
        assert profits[0] != pytest.approx(profits[1])
        assert om.worst_case_profit(rounded, ds) < om.worst_case_profit(exact, ds) + 1e-6


class TestSkewedStakes:
    def test_doubtful_leg_gets_less_stake(self):
        # Part I s7.2: a leg likely to be voided is under-staked.
        ds = [2.0, 2.0]
        even = om.skewed_stakes(ds, [1.0, 1.0], 1000.0)
        skewed = om.skewed_stakes(ds, [1.0, 0.5], 1000.0)
        assert even[0] == pytest.approx(even[1])
        assert skewed[1] < even[1]
        assert sum(skewed) == pytest.approx(1000.0)


class TestDevigPowerGuards:
    """Power de-vigging needs strictly interior probabilities.

    `decimal_to_prob` clamps any d <= 1 to exactly 1.0, and 1**k == 1 for every
    k, so the sum can never fall to 1 and the bisection walks to its upper bound
    -- returning a confident, meaningless answer.
    """

    def test_a_degenerate_price_falls_back_to_proportional(self):
        odds = [1.0, 3.0, 4.0]
        assert om.devig_power(odds) == om.devig_proportional(odds)

    def test_output_is_still_a_probability_distribution(self):
        for odds in ([1.0, 3.0], [2.1, 2.0, 8.0], [1.9, 1.9]):
            probs = om.devig_power(odds)
            assert all(0.0 <= p <= 1.0 for p in probs)
            assert sum(probs) == pytest.approx(1.0)

    def test_healthy_input_is_unaffected_by_the_guard(self):
        probs = om.devig_power([2.1, 2.0])
        assert sum(probs) == pytest.approx(1.0)
        assert all(0.0 < p < 1.0 for p in probs)
