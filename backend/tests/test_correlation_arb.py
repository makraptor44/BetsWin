"""Correlation-arb math checked against closed-form special cases."""

from __future__ import annotations

import math

import pytest

from arbengine import correlation_arb as ca


class TestNormalMaths:
    def test_norm_cdf_at_zero(self):
        assert ca.norm_cdf(0.0) == pytest.approx(0.5)

    def test_norm_ppf_is_the_inverse_of_norm_cdf(self):
        for p in (0.001, 0.05, 0.25, 0.5, 0.75, 0.95, 0.999):
            z = ca.norm_ppf(p)
            assert ca.norm_cdf(z) == pytest.approx(p, abs=1e-9)

    def test_known_quantiles(self):
        assert ca.norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
        assert ca.norm_ppf(0.975) == pytest.approx(1.959963985, abs=1e-6)


class TestBivariateNormalCdf:
    def test_independence_factorises(self):
        # rho = 0 -> the bivariate CDF is just the product of the marginals.
        x, y = 0.5, -0.3
        assert ca.bivariate_normal_cdf(x, y, 0.0) == pytest.approx(
            ca.norm_cdf(x) * ca.norm_cdf(y), abs=1e-6
        )

    def test_perfect_positive_correlation(self):
        # rho = 1 -> Z1 == Z2, so P(Z1<=x, Z2<=y) = P(Z<=min(x,y)).
        assert ca.bivariate_normal_cdf(0.4, 1.1, 1.0) == pytest.approx(
            ca.norm_cdf(0.4), abs=1e-6
        )
        assert ca.bivariate_normal_cdf(1.1, 0.4, 1.0) == pytest.approx(
            ca.norm_cdf(0.4), abs=1e-6
        )

    def test_perfect_negative_correlation(self):
        # rho = -1 -> Z2 == -Z1, so P(Z1<=x, Z2<=y) = max(0, Phi(x)+Phi(y)-1).
        assert ca.bivariate_normal_cdf(0.4, 1.1, -1.0) == pytest.approx(
            max(0.0, ca.norm_cdf(0.4) + ca.norm_cdf(1.1) - 1.0), abs=1e-6
        )

    def test_monotone_increasing_in_rho(self):
        vals = [ca.bivariate_normal_cdf(0.2, -0.1, r) for r in (-0.9, -0.3, 0.0, 0.3, 0.9)]
        assert vals == sorted(vals)


class TestJointProbabilityAndImpliedCorrelation:
    def test_zero_correlation_matches_independent_product(self):
        p = ca.joint_probability(0.4, 0.3, 0.0)
        assert p == pytest.approx(0.4 * 0.3, abs=1e-6)

    def test_implied_correlation_roundtrips(self):
        for rho in (-0.8, -0.2, 0.0, 0.35, 0.9):
            p_joint = ca.joint_probability(0.55, 0.42, rho)
            recovered = ca.implied_correlation(0.55, 0.42, p_joint)
            assert recovered == pytest.approx(rho, abs=1e-5)

    def test_independent_marginals_imply_zero_correlation(self):
        rho = ca.implied_correlation(0.6, 0.35, 0.6 * 0.35)
        assert rho == pytest.approx(0.0, abs=1e-6)

    def test_comonotone_upper_bound_implies_rho_one(self):
        # p_joint at the Frechet-Hoeffding upper bound (min(p_a, p_b)) means
        # the smaller event always happens whenever the larger one does.
        rho = ca.implied_correlation(0.7, 0.4, 0.4)
        assert rho == pytest.approx(1.0, abs=1e-4)

    def test_countermonotone_lower_bound_implies_rho_minus_one(self):
        rho = ca.implied_correlation(0.7, 0.4, max(0.0, 0.7 + 0.4 - 1.0))
        assert rho == pytest.approx(-1.0, abs=1e-4)

    def test_infeasible_joint_price_raises(self):
        # p_joint above min(p_a, p_b) can't come from any copula.
        with pytest.raises(ValueError):
            ca.implied_correlation(0.3, 0.4, 0.35)


class TestEstimateRhoPriorFromOutcomes:
    def test_perfectly_matched_outcomes_give_high_positive_rho(self):
        a = [1, 0, 1, 0, 1, 1, 0, 0, 1, 0] * 5
        rho = ca.estimate_rho_prior_from_outcomes(a, a)
        assert rho > 0.99

    def test_perfectly_opposite_outcomes_give_strongly_negative_rho(self):
        a = [1, 0, 1, 0, 1, 1, 0, 0, 1, 0] * 5
        b = [1 - x for x in a]
        rho = ca.estimate_rho_prior_from_outcomes(a, b)
        assert rho < -0.99

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            ca.estimate_rho_prior_from_outcomes([1, 0], [1, 0, 1])


class TestEvaluateSignal:
    def test_underdependent_market_is_a_buy(self):
        # Market prices the joint as if rho were lower than the historical
        # prior -> joint contract is underpriced relative to fair value -> BUY.
        p_a, p_b, rho_prior = 0.55, 0.5, 0.6
        rho_market = 0.3
        p_joint_market = ca.joint_probability(p_a, p_b, rho_market)

        sig = ca.evaluate(p_a, p_b, p_joint_market, rho_prior)

        assert sig.rho_impl == pytest.approx(rho_market, abs=1e-5)
        assert sig.rho_impl < sig.rho_prior
        assert sig.fair_joint_price > sig.p_joint_market
        assert sig.edge > 0
        assert sig.action == "BUY"

    def test_overdependent_market_is_a_sell(self):
        p_a, p_b, rho_prior = 0.55, 0.5, 0.2
        rho_market = 0.7
        p_joint_market = ca.joint_probability(p_a, p_b, rho_market)

        sig = ca.evaluate(p_a, p_b, p_joint_market, rho_prior)

        assert sig.rho_impl > sig.rho_prior
        assert sig.fair_joint_price < sig.p_joint_market
        assert sig.edge < 0
        assert sig.action == "SELL"

    def test_matching_prior_is_a_hold(self):
        p_a, p_b, rho = 0.55, 0.5, 0.4
        p_joint_market = ca.joint_probability(p_a, p_b, rho)
        sig = ca.evaluate(p_a, p_b, p_joint_market, rho)
        assert sig.edge == pytest.approx(0.0, abs=1e-6)
        assert sig.action == "HOLD"

    def test_min_edge_deadband_suppresses_small_signals(self):
        p_a, p_b, rho_prior = 0.55, 0.5, 0.41
        rho_market = 0.4
        p_joint_market = ca.joint_probability(p_a, p_b, rho_market)
        sig = ca.evaluate(p_a, p_b, p_joint_market, rho_prior, min_edge=0.05)
        assert sig.action == "HOLD"

    def test_edge_pct_matches_edge_over_market_price(self):
        p_a, p_b, rho_prior = 0.55, 0.5, 0.6
        p_joint_market = ca.joint_probability(p_a, p_b, 0.3)
        sig = ca.evaluate(p_a, p_b, p_joint_market, rho_prior)
        assert sig.edge_pct == pytest.approx(100.0 * sig.edge / sig.p_joint_market)
