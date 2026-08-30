"""Odds mathematics.

Every function here is a direct implementation of a formula from
`arbitrage_betting_theory.pdf`. Section references are given per function so the
code can be checked against the source. All odds are DECIMAL internally
(Part I s2.1); prediction-market prices are quoted in probability space (a
contract costing $0.42 that pays $1) and convert as d = 1/p.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

# A price of exactly 0 or 1 is unusable; clamp to the tightest tick either venue
# supports (Polymarket 0.001, Kalshi 0.01).
MIN_PRICE = 1e-4
MAX_PRICE = 1.0 - 1e-4


# --------------------------------------------------------------------- format


def prob_to_decimal(p: float) -> float:
    """Probability (or prediction-market contract price) -> decimal odds.

    Part I s2.2: p_impl = 1/d, so d = 1/p. A contract costing $0.40 that settles
    at $1.00 is decimal 2.50.
    """
    p = min(max(p, MIN_PRICE), MAX_PRICE)
    return 1.0 / p


def decimal_to_prob(d: float) -> float:
    """Decimal odds -> implied probability. Part I s2.2: p_impl = 1/d."""
    if d <= 1.0:
        return 1.0
    return 1.0 / d


def american_to_decimal(a: float) -> float:
    """American odds -> decimal. Part I s2.1.

    American odds are undefined between -100 and +100: the format expresses
    "stake 100 to win a" or "stake |a| to win 100", and neither reading admits a
    magnitude below 100. Zero is the degenerate case that used to divide by zero.
    """
    if abs(a) < 100.0:
        raise ValueError(
            f"American odds must be +100 or longer, or -100 or shorter; got {a}"
        )
    if a > 0:
        return 1.0 + a / 100.0
    return 1.0 + 100.0 / abs(a)


def decimal_to_american(d: float) -> float:
    """Decimal odds -> American. Part I s2.1.

    Decimal odds of exactly 1.00 are a bet that returns the stake and nothing
    else; they have no American representation, and computing one divided by
    zero.
    """
    if d <= 1.0:
        raise ValueError(f"decimal odds must be greater than 1.0; got {d}")
    if d >= 2.0:
        return (d - 1.0) * 100.0
    return -100.0 / (d - 1.0)


def fractional_to_decimal(num: float, den: float) -> float:
    """Fractional odds -> decimal. Part I s2.1."""
    return 1.0 + num / den


# ----------------------------------------------------------------- the "book"


def book(decimal_odds: Iterable[float]) -> float:
    """Combined book B = sum(1/d_i). Part I s2.3.

    B > 1 at any single bookmaker (the excess is the overround). B < 1 across
    best prices from several venues is precisely the arbitrage condition.
    """
    return sum(decimal_to_prob(d) for d in decimal_odds)


def overround(decimal_odds: Iterable[float]) -> float:
    """The bookmaker's edge, B - 1. Part I s2.3."""
    return book(decimal_odds) - 1.0


def vig(decimal_odds: Iterable[float]) -> float:
    """Fraction of turnover kept on a balanced book: v = 1 - 1/B. Part I s2.3."""
    b = book(decimal_odds)
    if b <= 0:
        return 0.0
    return 1.0 - 1.0 / b


def arb_margin(b: float) -> float:
    """Guaranteed return on turnover: m = 1/B - 1. Part I s2.4."""
    if b <= 0:
        return 0.0
    return 1.0 / b - 1.0


def is_arbitrage(decimal_odds: Iterable[float]) -> bool:
    """B_combined < 1. Part I s2.4."""
    return book(decimal_odds) < 1.0


# --------------------------------------------------------------- stake sizing


def equal_profit_stakes(decimal_odds: Sequence[float], total_stake: float) -> list[float]:
    """Stakes giving identical profit on every outcome. Part I s3.2 / s4.1.

        s_i = S * (1/d_i) / B

    Each leg's normalised implied probability is its share of the total stake.
    """
    b = book(decimal_odds)
    if b <= 0:
        return [0.0] * len(decimal_odds)
    return [total_stake * decimal_to_prob(d) / b for d in decimal_odds]


def guaranteed_profit(decimal_odds: Sequence[float], total_stake: float) -> float:
    """Guaranteed profit = S * (1/B - 1). Part I s3.3."""
    return total_stake * arb_margin(book(decimal_odds))


def worst_case_profit(stakes: Sequence[float], decimal_odds: Sequence[float]) -> float:
    """Realised worst-case profit once stakes are rounded. Part II s8.3.

    After rounding, profit is no longer identical across outcomes, so the honest
    number is min(payout) - total staked. Always compute this before committing.
    """
    if not stakes:
        return 0.0
    total = sum(stakes)
    return min(s * d for s, d in zip(stakes, decimal_odds)) - total


def payouts(stakes: Sequence[float], decimal_odds: Sequence[float]) -> list[float]:
    """Per-outcome payout. Payout on leg i is s_i * d_i (Part I s3.1)."""
    return [s * d for s, d in zip(stakes, decimal_odds)]


def profit_by_outcome(stakes: Sequence[float], decimal_odds: Sequence[float]) -> list[float]:
    """Profit in each state of the world: pi_i = s_i*d_i - S. Part I s3.1."""
    total = sum(stakes)
    return [p - total for p in payouts(stakes, decimal_odds)]


def skewed_stakes(
    decimal_odds: Sequence[float],
    settle_probs: Sequence[float],
    total_stake: float,
) -> list[float]:
    """Stake sizing when a leg may be voided or moved. Part I s7.2.

    Replace 1/d_i with q_i * (1/d_i) where q_i is your personal probability that
    leg i settles at the quoted price, then renormalise. Under-staking a doubtful
    leg trades some hedge completeness for higher conditional return.
    """
    weights = [q * decimal_to_prob(d) for d, q in zip(decimal_odds, settle_probs)]
    tw = sum(weights)
    if tw <= 0:
        return [0.0] * len(decimal_odds)
    return [total_stake * w / tw for w in weights]


# -------------------------------------------------------------- Kelly / value


def kelly_fraction(p: float, d: float) -> float:
    """Kelly-optimal bankroll fraction. Part I s7.3 / s12.1.

        f* = (p*d - 1) / (d - 1)

    Requires a genuine probability estimate, so it belongs to value betting
    rather than arbitrage (where every outcome is covered).
    """
    if d <= 1.0:
        return 0.0
    f = (p * d - 1.0) / (d - 1.0)
    return max(0.0, f)


def expected_value(p: float, d: float) -> float:
    """Expected profit per unit stake: p*d - 1. Part I s12.1."""
    return p * d - 1.0


def is_value_bet(p: float, d: float) -> bool:
    """A value bet iff p*d > 1, i.e. d > 1/p. Part I s12.1."""
    return p * d > 1.0


def devig_proportional(decimal_odds: Sequence[float]) -> list[float]:
    """Strip the margin from a sharp book's prices. Part I s12.2.

    The vig-free implied probability of outcome i is (1/d_i) / B. Applied to a
    sharp reference (Pinnacle, or on prediction markets the deepest venue) this
    is the workhorse estimate of true probability.
    """
    b = book(decimal_odds)
    if b <= 0:
        return [0.0] * len(decimal_odds)
    return [decimal_to_prob(d) / b for d in decimal_odds]


def devig_power(decimal_odds: Sequence[float], tol: float = 1e-10) -> list[float]:
    """Power de-vigging: solve for k with sum((1/d_i)^k) = 1.

    Less biased than proportional de-vigging on longshots, which matters on
    prediction markets where prices cluster near 0 and 1.
    """
    raw = [decimal_to_prob(d) for d in decimal_odds]
    if not raw or min(raw) <= 0:
        return devig_proportional(decimal_odds)
    lo, hi = 0.5, 3.0
    k = 1.0
    for _ in range(200):
        k = 0.5 * (lo + hi)
        s = sum(r ** k for r in raw)
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = k
        else:
            hi = k
    out = [r ** k for r in raw]
    tot = sum(out)
    return [o / tot for o in out] if tot else devig_proportional(decimal_odds)


# ------------------------------------------------------- exchange / back-lay


def exchange_effective_odds(d_back: float, commission: float) -> float:
    """Commission-adjusted back price. Part I s6.1: d_eff = 1 + (d-1)*(1-c)."""
    return 1.0 + (d_back - 1.0) * (1.0 - commission)


def lay_stake_to_hedge(
    back_stake: float, d_back: float, d_lay: float, commission: float
) -> float:
    """Lay stake that fully hedges a back bet. Part I s6.2.

        s_l = s_b * d_b / (d_l - c)

    The denominator is `d_l - c`, not `d_l - c*(d_l - 1)`. Commission on an
    exchange is charged on the NET WINNINGS of the bet that wins, and when a lay
    wins the winnings are the backer's stake s_l -- not the liability, and not a
    function of the lay price. Equating the two states:

        back wins:  s_b*(d_b - 1) - s_l*(d_l - 1)
        lay wins:   -s_b + s_l*(1 - c)

        =>  s_b*d_b = s_l*(d_l - c)   =>   s_l = s_b*d_b / (d_l - c)

    This is the same derivation `back_lay_is_arb` below already rests on, so the
    two agree. The previous denominator left the position unhedged: backing 100
    at 2.10 and laying at 2.05 on 2% commission returned a lay stake of 103.4993,
    paying +1.3258 if the back won and +1.4293 if the lay won.
    """
    denom = d_lay - commission
    if denom <= 0:
        return 0.0
    return back_stake * d_back / denom


def lay_liability(lay_stake: float, d_lay: float) -> float:
    """Liability on a lay bet: s * (d_lay - 1). Part I s6."""
    return lay_stake * (d_lay - 1.0)


def back_lay_is_arb(d_back: float, d_lay: float, commission: float) -> bool:
    """Back-at-bookie / lay-at-exchange arbitrage condition. Part I s6.2."""
    return d_back * (1.0 - commission) > d_lay - commission


# --------------------------------------------------------- risk-adjusted edge


def margin_after_voids(margin: float, void_rate: float, void_loss: float) -> float:
    """Effective margin once legs get voided. Part I s13.3.

        E[pi] ~= (1 - v)*m - v*L

    A 2% arb with a 3% void rate costing 30% of stake nets ~1.04% - half of
    nominal. Expected value must be positive AFTER voids, not before.
    """
    return (1.0 - void_rate) * margin - void_rate * void_loss


def kelly_arb_fraction(margin: float, void_rate: float, void_loss: float) -> float:
    """Kelly bound on per-event arb exposure. Part I s13.4.

        f* = ((1-v)*m - v*L) / (m*L)

    Typically returns >1 for realistic inputs, which is the formal statement that
    bankroll, not risk aversion, is the binding constraint for an arber.

    Two boundary cases have to be told apart, because collapsing both to 0.0
    said "stake nothing" for the one input where the trade carries no risk at
    all:

    * `void_loss == 0` with a positive margin -- nothing can go wrong, so Kelly
      places no bound and the answer is +infinity. Callers that have to render
      or serialise it should special-case `math.isinf`.
    * `margin <= 0` -- there is no edge to stake on, so the answer really is 0.
    """
    if margin <= 0:
        return 0.0
    if void_loss <= 0:
        return math.inf
    return margin_after_voids(margin, void_rate, void_loss) / (margin * void_loss)


def annualised_return(margin: float, turnovers_per_year: float) -> float:
    """Annual return ~= N * m. Part I s8.2."""
    return margin * turnovers_per_year


def compounded_return(margin: float, turnovers_per_year: float) -> float:
    """Compounded growth over a year at N turnovers of margin m. Part I s8.2."""
    return math.pow(1.0 + margin, turnovers_per_year) - 1.0


# --------------------------------------------------------- rounding utilities


def round_down_to_step(value: float, step: float) -> float:
    """Round down to a multiple of `step`. Part II s8.1 (conservative)."""
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def round_to_step(value: float, step: float) -> float:
    """Round to the nearest multiple of `step`."""
    if step <= 0:
        return value
    return round(value / step) * step
