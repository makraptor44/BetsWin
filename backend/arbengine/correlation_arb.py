"""Correlation arbitrage between two related event contracts.

Prediction markets often list three contracts off one pair of correlated
events -- e.g. "Trump wins the presidency" (A), "Republicans win the Senate"
(B), and "Both happen" (A and B). The two marginals price A and B on their
own; the joint contract prices their *dependence* as well.

Model each event as a latent standard-normal variable crossing a threshold
(a Gaussian copula / probit model):

    A occurs iff  Z_A <= Phi^-1(p_a)
    B occurs iff  Z_B <= Phi^-1(p_b)

with corr(Z_A, Z_B) = rho. The marginals p_a, p_b pin down the two
thresholds, so once they're fixed the joint probability

    P(A and B) = Phi_2(Phi^-1(p_a), Phi^-1(p_b); rho)

depends on nothing else but rho. Solving that equation for the rho that
reproduces the market's actual joint price gives rho_impl -- the
correlation the market is implicitly pricing in.

`rho_impl` is then compared against `rho_prior`, an independent estimate of
the true dependence (e.g. from historical outcome pairs). Holding the
marginals fixed:

    rho_impl < rho_prior  -> market treats A, B as LESS dependent than they
                              really are -> the joint contract is UNDERpriced
                              (less-dependent events produce a smaller joint
                              probability) -> BUY the joint contract.
    rho_impl > rho_prior  -> market treats A, B as MORE dependent than they
                              really are -> the joint contract is OVERpriced
                              -> SELL the joint contract.

This module is pure math -- no IO, no venue-specific quote handling -- so it
has no dependency on `models.Quote`. Feed it prices (0-1 probabilities)
however they're sourced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Optional, Sequence

# Prices this close to 0 or 1 make Phi^-1 blow up; nothing tradeable prices there.
_MIN_PROB = 1e-6
_MAX_PROB = 1.0 - 1e-6

# phi(z) is below double-precision noise well before this; safe as a
# "-infinity" cutoff for the bivariate CDF's integral.
_NEG_INF_CUTOFF = -10.0

# As |rho| -> 1, the conditional Phi((y-rho*z)/sqrt(1-rho^2)) term turns into
# an increasingly steep step function that a fixed-step Simpson's rule can no
# longer resolve -- so anything this close to +-1 is treated as exactly +-1.
# Correlations this extreme aren't distinguishable from comonotonic /
# countermonotonic in practice, so the approximation costs nothing real.
_RHO_EDGE_EPS = 1e-6


def _validate_prob(p: float, name: str) -> None:
    if not _MIN_PROB <= p <= _MAX_PROB:
        raise ValueError(f"{name} must be a probability in (0, 1), got {p}")


def _validate_rho(rho: float) -> None:
    if not -1.0 <= rho <= 1.0:
        raise ValueError(f"rho must be in [-1, 1], got {rho}")


# ------------------------------------------------------------- normal maths


def _phi_pdf(z: float) -> float:
    """Standard normal density."""
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def norm_cdf(z: float) -> float:
    """Standard normal CDF via the error function (exact to machine precision)."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (the probit function).

    Acklam's rational approximation (accurate to ~1.15e-9) followed by one
    Halley refinement step against the exact `norm_cdf`, which pushes the
    result to full double precision and self-corrects any residual error in
    the rational approximation's coefficients.
    """
    _validate_prob(p, "p")

    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)

    p_low, p_high = 0.02425, 1 - 0.02425

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    # Halley refinement step against the exact CDF.
    e = norm_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(0.5 * x * x)
    x -= u / (1.0 + x * u / 2.0)
    return x


#: Simpson steps at rho = 0, scaled up as |rho| approaches 1 by `_simpson_steps`.
#: Chosen empirically -- `test_correlation_arb.py` pins the resulting accuracy
#: against a 4,000-step reference across the whole (x, y, rho) grid.
_BASE_STEPS = 448
_MAX_STEPS = 2000


def _simpson_steps(rho: float) -> int:
    """How finely to sample the integral for this correlation.

    The integrand carries a `Phi((y - rho*z)/sqrt(1 - rho^2))` factor, which
    steepens into a step function as |rho| -> 1; away from that limit it is
    smooth and a fixed 2,000 steps is three orders of magnitude more work than
    double precision needs. Simpson's error falls as n^-4, and the steepness
    grows as 1/sqrt(1 - rho^2), so sampling in proportion to that holds the
    error roughly flat instead of over-paying in the middle of the range --
    where a bisection spends most of its iterations.
    """
    n = int(_BASE_STEPS / math.sqrt(max(1.0 - rho * rho, 1e-12)))
    return max(_BASE_STEPS, min(n, _MAX_STEPS))


@lru_cache(maxsize=4096)
def bivariate_normal_cdf(
    x: float, y: float, rho: float, n_steps: Optional[int] = None
) -> float:
    """P(Z1 <= x, Z2 <= y) for a standard bivariate normal with correlation rho.

    Uses the exact conditioning identity -- Z2 | Z1=z is Normal(rho*z, 1-rho^2) --
    to reduce the 2-D CDF to a 1-D integral:

        P(Z1<=x, Z2<=y) = integral_{-inf}^{x} phi(z) * Phi((y - rho*z)/sqrt(1-rho^2)) dz

    evaluated by composite Simpson's rule. This avoids the branchy
    Drezner-Wesolowsky approximation (easy to mis-transcribe) in favour of a
    method that's simple to verify by inspection.
    """
    _validate_rho(rho)

    if rho >= 1.0 - _RHO_EDGE_EPS:
        return norm_cdf(min(x, y))
    if rho <= -1.0 + _RHO_EDGE_EPS:
        return max(0.0, norm_cdf(x) + norm_cdf(y) - 1.0)

    lower = _NEG_INF_CUTOFF
    if x <= lower:
        return 0.0

    denom = math.sqrt(1.0 - rho * rho)
    if n_steps is None:
        n_steps = _simpson_steps(rho)
    if n_steps % 2:
        n_steps += 1
    h = (x - lower) / n_steps

    def integrand(z: float) -> float:
        return _phi_pdf(z) * norm_cdf((y - rho * z) / denom)

    total = integrand(lower) + integrand(x)
    for i in range(1, n_steps):
        z = lower + i * h
        total += (4.0 if i % 2 else 2.0) * integrand(z)
    return total * h / 3.0


# ------------------------------------------------------------ copula model


def joint_probability(p_a: float, p_b: float, rho: float) -> float:
    """Model-implied P(A and B) given marginals p_a, p_b and latent correlation rho."""
    _validate_prob(p_a, "p_a")
    _validate_prob(p_b, "p_b")
    return bivariate_normal_cdf(norm_ppf(p_a), norm_ppf(p_b), rho)


def check_frechet(p_a: float, p_b: float, p_joint: float) -> float:
    """Reject a triple no copula can produce, and clamp to the bounds.

    Pure arithmetic -- no integration -- so it stays eager even where the
    correlation solve itself is deferred.
    """
    lo_bound = max(0.0, p_a + p_b - 1.0)  # Frechet-Hoeffding lower bound
    hi_bound = min(p_a, p_b)              # Frechet-Hoeffding upper bound
    if not (lo_bound - 1e-9 <= p_joint <= hi_bound + 1e-9):
        raise ValueError(
            f"p_joint={p_joint} is outside the Frechet-Hoeffding bounds "
            f"[{lo_bound:.6f}, {hi_bound:.6f}] implied by p_a={p_a}, p_b={p_b} "
            "-- these three prices are not jointly consistent under any copula."
        )
    return min(max(p_joint, lo_bound), hi_bound)


def implied_correlation(
    p_a: float,
    p_b: float,
    p_joint: float,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float:
    """Solve for rho_impl: the latent correlation that reproduces the market's
    joint price, holding the marginals p_a, p_b fixed.

    `joint_probability` is monotonically increasing in rho (more dependence
    always raises P(A and B)), so bisection is safe and doesn't need a
    derivative or a good starting guess.
    """
    _validate_prob(p_a, "p_a")
    _validate_prob(p_b, "p_b")
    _validate_prob(p_joint, "p_joint")

    p_joint = check_frechet(p_a, p_b, p_joint)

    za, zb = norm_ppf(p_a), norm_ppf(p_b)

    def f(rho: float) -> float:
        return bivariate_normal_cdf(za, zb, rho) - p_joint

    lo, hi = -1.0 + _RHO_EDGE_EPS, 1.0 - _RHO_EDGE_EPS
    # The bracket endpoints, not +-1. Returning the sentinel put the caller on
    # the other side of the `_RHO_EDGE_EPS` cutoff in `bivariate_normal_cdf`,
    # where it short-circuits to the comonotonic bound instead of integrating --
    # so `joint_probability(p_a, p_b, implied_correlation(...))` did not
    # reproduce the price it was solved from.
    if f(lo) >= 0:
        return lo
    if f(hi) <= 0:
        return hi

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = f(mid)
        if abs(f_mid) < tol:
            return mid
        if f_mid > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def estimate_rho_prior_from_outcomes(
    outcomes_a: Sequence[int],
    outcomes_b: Sequence[int],
) -> float:
    """Estimate rho_prior from historical paired binary outcomes.

    This is the tetrachoric correlation estimator: take the empirical
    marginals and joint frequency from the historical sample, then reuse
    `implied_correlation` to find the latent-normal correlation consistent
    with them under the same Gaussian copula used for rho_impl. Comparing
    rho_impl to rho_prior is then an apples-to-apples comparison -- both are
    "the rho a Gaussian copula would need" for their respective probabilities.
    """
    n = len(outcomes_a)
    if n == 0 or n != len(outcomes_b):
        raise ValueError("outcomes_a and outcomes_b must be non-empty and equal length")

    p_a = sum(outcomes_a) / n
    p_b = sum(outcomes_b) / n
    p_joint = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a and b) / n

    # A sample can hand back an empirical marginal of exactly 0 or 1; clamp to
    # the tightest value the sample size can actually resolve.
    eps = 0.5 / n
    p_a = min(max(p_a, eps), 1.0 - eps)
    p_b = min(max(p_b, eps), 1.0 - eps)
    p_joint = min(max(p_joint, eps), min(p_a, p_b))

    return implied_correlation(p_a, p_b, p_joint)


# -------------------------------------------------------------- the signal


@dataclass(frozen=True)
class CorrelationArbSignal:
    """A correlation-arb read on one joint-event contract."""

    p_a: float
    p_b: float
    p_joint_market: float
    rho_prior: float
    fair_joint_price: float   # joint_probability(p_a, p_b, rho_prior)
    edge: float                # fair_joint_price - p_joint_market, in probability points
    action: str                 # "BUY", "SELL", or "HOLD"

    @cached_property
    def rho_impl(self) -> float:
        """The correlation the market is pricing in.

        Computed on demand, because it costs a bisection over a numerically
        integrated bivariate normal -- up to a hundred solves of a 2,000-step
        Simpson's rule, each step calling erfc -- and the BUY/SELL/HOLD decision
        below does not use it. `evaluate` used to pay that on every pair on
        every scan cycle, and most pairs are a HOLD that nothing ever displays.

        It is still the honest headline number when an opportunity IS surfaced,
        so it is a property rather than a deletion.
        """
        return implied_correlation(self.p_a, self.p_b, self.p_joint_market)

    @property
    def edge_pct(self) -> float:
        """Edge as a fraction of the market price the joint contract trades at."""
        if self.p_joint_market <= 0:
            return 0.0
        return 100.0 * self.edge / self.p_joint_market


def evaluate(
    p_a: float,
    p_b: float,
    p_joint_market: float,
    rho_prior: float,
    min_edge: float = 0.0,
) -> CorrelationArbSignal:
    """Compare the market's implied correlation to a prior and signal a trade.

    Holding the marginals p_a, p_b fixed:

        rho_impl < rho_prior -> market underestimates the dependence between
                                 A and B -> the joint contract is priced too
                                 low relative to the historical prior -> BUY.
        rho_impl > rho_prior -> market overestimates the dependence -> the
                                 joint contract is priced too high -> SELL.

    `min_edge` is a probability-point deadband (e.g. 0.01 = 1c) below which
    the signal is HOLD -- the mispricing may not clear fees/slippage.
    """
    _validate_rho(rho_prior)
    # Consistency is checked eagerly (cheap); the correlation solve behind
    # `signal.rho_impl` is deferred until something asks for it.
    check_frechet(p_a, p_b, p_joint_market)
    fair_price = joint_probability(p_a, p_b, rho_prior)
    edge = fair_price - p_joint_market

    if edge > min_edge:
        action = "BUY"
    elif edge < -min_edge:
        action = "SELL"
    else:
        action = "HOLD"

    return CorrelationArbSignal(
        p_a=p_a,
        p_b=p_b,
        p_joint_market=p_joint_market,
        rho_prior=rho_prior,
        fair_joint_price=fair_price,
        edge=edge,
        action=action,
    )
