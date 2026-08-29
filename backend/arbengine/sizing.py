"""Stake sizing (Part II s8).

The detector proves an edge exists at top-of-book. Sizing decides how much of it
is actually collectable, which is a different question: prediction-market books
are thin, and a $2,000 order that clears four price levels can turn a 2% edge
into a loss before a single contract settles.

The unifying idea: every leg is expressed as CONTRACTS THAT PAY $1. A
prediction-market contract does this literally; a sportsbook bet at decimal odds
d is the same thing bought at price 1/d (Part I s2.2). Under that framing the
equal-profit condition of Part I s3.2 reduces to something simpler -- buy the
same number of contracts on every leg. Outlay is then N * sum(p_eff_i) and the
payout is N in every state, so profit is N * (1 - B_eff), identical whichever
outcome occurs. All-in "stake" per leg therefore means contract cost plus fees.

Order of operations:

  1. Walk each leg's order book for the true volume-weighted cost of the
     requested size, rather than assuming top-of-book depth persists.
  2. Cap total stake by depth, per-venue limits, and the per-event bankroll
     fraction from Part I s7.4.
  3. Allocate by equal-profit weights (Part I s3.2) at those realised prices.
  4. Round down conservatively and re-derive worst-case profit explicitly,
     because after rounding profit is no longer identical (Part II s8.3).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from . import odds as om
from .config import settings
from .fees import fee_model_for
from .models import ArbLeg, DepthLevel, Quote


@dataclass(frozen=True)
class Fill:
    """The result of walking an order book for a requested notional."""

    avg_price: float          # volume-weighted average cost per contract
    contracts: float          # contracts obtainable for the requested notional
    notional: float           # dollars actually spendable
    levels_cleared: int
    exhausted: bool           # the book ran out before the request was filled

    @property
    def slippage_vs(self) -> float:
        return self.avg_price


def walk_book(
    levels: Sequence[DepthLevel],
    top_price: float,
    target_notional: float,
) -> Fill:
    """Volume-weighted cost of spending `target_notional` against an ask stack.

    `levels` must be sorted cheapest-first. When no depth is published the top
    price is assumed to hold for the whole order -- optimistic, so the caller
    marks such a result as thin liquidity rather than trusting it.
    """
    if target_notional <= 0 or top_price <= 0:
        return Fill(max(top_price, om.MIN_PRICE), 0.0, 0.0, 0, False)

    usable = [l for l in levels if l.price > 0 and l.size > 0]
    if not usable:
        return Fill(top_price, target_notional / top_price, target_notional, 0, True)

    spent = 0.0
    contracts = 0.0
    cleared = 0
    exhausted = True
    for lvl in usable:
        remaining = target_notional - spent
        if remaining <= 1e-9:
            exhausted = False
            break
        cleared += 1
        level_notional = lvl.price * lvl.size
        if level_notional >= remaining:
            contracts += remaining / lvl.price
            spent += remaining
            exhausted = False
            break
        contracts += lvl.size
        spent += level_notional

    avg = spent / contracts if contracts > 0 else top_price
    return Fill(avg, contracts, spent, cleared, exhausted)


#: How far above the best price a fill may reach before the edge is gone.
#: Arb margins live in the 0.5-3% band, so paying 2% more than top of book
#: destroys the trade -- depth beyond that point is not real capacity.
MAX_PRICE_SLACK = 0.02


def book_capacity(
    levels: Sequence[DepthLevel],
    top_price: float,
    fallback_size: float,
    max_slack: float = MAX_PRICE_SLACK,
) -> float:
    """Dollars this leg can absorb *while the edge survives*.

    Summing the whole ask stack would be arithmetically true and practically
    useless: a Polymarket book has resting size all the way out to 0.999, and
    counting it would advertise a million dollars of capacity on a trade whose
    edge dies after a couple of ticks. Only depth priced within `max_slack` of
    the best offer can actually be taken.
    """
    usable = [l for l in levels if l.price > 0 and l.size > 0]
    if not usable:
        return max(fallback_size, 0.0) * max(top_price, 0.0)
    best = min(l.price for l in usable)
    ceiling = best * (1.0 + max_slack)
    return sum(l.price * l.size for l in usable if l.price <= ceiling)


@dataclass(frozen=True)
class SizedArb:
    """Output of the sizer: legs with stakes, plus honest profit numbers."""

    legs: tuple[ArbLeg, ...]
    total_stake: float
    book: float
    margin: float                 # gross of fees, at quoted top-of-book
    net_margin: float             # after fees and realised slippage
    profit: float                 # theoretical, total_stake * net_margin
    worst_case_profit: float      # min across states, after rounding
    payout_if: dict[str, float]
    max_stake_available: float
    payout_multiple: float
    depth_limited: bool
    rounding_exposure: bool
    slippage_bps: float = 0.0


def _state_payouts(
    legs: Sequence[ArbLeg], payout_multiple: float
) -> tuple[dict[str, float], float]:
    """Payout in each state of the world, and the worst profit across them.

    Standard arb: exactly one leg settles at $1 per contract.
    NO-side Dutch book on n mutually exclusive outcomes: every leg BUT the
    winning one settles, so n-1 legs pay.
    """
    total = sum(l.stake for l in legs)
    payout_if: dict[str, float] = {}
    worst: Optional[float] = None

    for i, leg in enumerate(legs):
        if payout_multiple <= 1.0:
            gross = leg.contracts
        else:
            gross = sum(l.contracts for j, l in enumerate(legs) if j != i)
        label = f"{leg.outcome} ({leg.venue})"
        payout_if[label] = round(gross, 2)
        profit = gross - total
        worst = profit if worst is None else min(worst, profit)

    return payout_if, round(worst if worst is not None else 0.0, 2)


def _build_leg(
    quote: Quote,
    stake: float,
    fill_price: float,
    event_title: Optional[str],
) -> ArbLeg:
    """Turn an allocated all-in stake into a concrete leg.

    `stake` is the all-in outlay: contract cost plus fees. Contracts are
    therefore stake / effective_price, and each contract returns $1.
    """
    fees = fee_model_for(quote.venue)
    # Solve for contracts given an all-in budget. The fee per contract depends
    # weakly on size (Kalshi rounds up to the cent), so one refinement pass is
    # enough to converge.
    contracts = stake / fill_price if fill_price > 0 else 0.0
    for _ in range(3):
        eff = fees.effective_price(fill_price, max(contracts, 1.0))
        contracts = stake / eff if eff > 0 else 0.0
    eff_price = fees.effective_price(fill_price, max(contracts, 1.0))
    fee = fees.total_fee(fill_price, contracts)

    return ArbLeg(
        venue=quote.venue,
        market_id=quote.market_id,
        ticker=quote.ticker,
        outcome=quote.outcome,
        side=quote.side,
        price=round(fill_price, 6),
        effective_price=round(eff_price, 6),
        decimal_odds=om.prob_to_decimal(fill_price),
        effective_decimal_odds=om.prob_to_decimal(eff_price),
        stake=round(stake, 2),
        contracts=round(contracts, 4),
        fee=round(fee, 4),
        size_available=quote.size_available,
        url=quote.url,
        event_title=event_title,
    )


def size_arb(
    quotes: Sequence[Quote],
    target_stake: Optional[float] = None,
    venue_limits: Optional[dict[str, float]] = None,
    payout_multiple: float = 1.0,
    event_title: Optional[str] = None,
) -> Optional[SizedArb]:
    """Size a set of legs that together cover every outcome.

    `payout_multiple` is how many legs pay out in each state: 1 for a standard
    arb, n-1 for a NO-side Dutch book across n mutually exclusive outcomes.
    Returns None when the edge does not survive depth, fees and rounding.
    """
    if len(quotes) < 2:
        return None

    target = target_stake if target_stake is not None else settings.default_stake
    limits = venue_limits or {}

    # --- Ceiling from bankroll policy (Part I s7.4) -------------------------
    target = min(target, settings.bankroll * settings.max_stake_fraction_per_event)
    if target <= 0:
        return None

    # --- Provisional equal-profit weights from top of book ------------------
    top_odds = [om.prob_to_decimal(q.effective_price) for q in quotes]
    b_top = om.book(top_odds)
    if b_top <= 0:
        return None
    weights = [om.decimal_to_prob(d) / b_top for d in top_odds]

    # --- Ceiling from order-book depth and venue limits ---------------------
    depth_limited = False
    capacities: list[float] = []
    for q, w in zip(quotes, weights):
        capacity = book_capacity(q.depth, q.price, q.size_available)
        venue_cap = limits.get(q.venue)
        if venue_cap is not None:
            capacity = min(capacity, venue_cap)
        capacities.append(capacity)
        if w <= 0 or capacity <= 0:
            continue
        leg_ceiling = capacity / w
        if leg_ceiling < target:
            target = leg_ceiling
            depth_limited = True

    if target < settings.min_total_stake:
        return None

    # --- Walk each book at the sized allocation -----------------------------
    fills = [walk_book(q.depth, q.price, target * w) for q, w in zip(quotes, weights)]

    # --- Re-price at realised average fill, including fees at that size -----
    eff_odds: list[float] = []
    for q, f, w in zip(quotes, fills, weights):
        fees = fee_model_for(q.venue)
        contracts = max((target * w) / f.avg_price, 1.0) if f.avg_price > 0 else 1.0
        eff_odds.append(om.prob_to_decimal(fees.effective_price(f.avg_price, contracts)))

    # For a payout multiple of k, the arb condition is sum(p_i) < k, so the
    # comparable book is B/k (Part I s5.1 generalised).
    raw_book = om.book(eff_odds)
    b = raw_book / payout_multiple if payout_multiple > 0 else raw_book
    if b >= 1.0:
        return None  # the edge did not survive slippage and fees

    quoted_book = om.book([om.prob_to_decimal(q.price) for q in quotes])
    margin_gross = om.arb_margin(quoted_book / payout_multiple)
    net_margin = om.arb_margin(b)

    # --- Allocate by equal-profit weights at realised prices ----------------
    stakes = om.equal_profit_stakes(eff_odds, target)

    # --- Round down conservatively (Part II s8.1) ---------------------------
    rounded = [om.round_down_to_step(s, settings.stake_step) for s in stakes]
    if any(s < settings.min_stake_per_leg for s in rounded):
        return None
    total = sum(rounded)
    if total < settings.min_total_stake:
        return None

    legs = tuple(
        _build_leg(q, s, f.avg_price, event_title)
        for q, s, f in zip(quotes, rounded, fills)
    )

    payout_if, worst = _state_payouts(legs, payout_multiple)
    theoretical = total * net_margin
    rounding_exposure = abs(worst - theoretical) > max(0.02, 0.05 * abs(theoretical))

    max_available = min(
        (c / w for c, w in zip(capacities, weights) if w > 0 and c > 0),
        default=total,
    )

    quoted_avg = sum(q.price for q in quotes)
    filled_avg = sum(f.avg_price for f in fills)
    slippage_bps = (
        10_000.0 * (filled_avg - quoted_avg) / quoted_avg if quoted_avg > 0 else 0.0
    )

    return SizedArb(
        legs=legs,
        total_stake=round(total, 2),
        book=b,
        margin=margin_gross,
        net_margin=net_margin,
        profit=round(theoretical, 2),
        worst_case_profit=worst,
        payout_if=payout_if,
        max_stake_available=round(max(max_available, total), 2),
        payout_multiple=payout_multiple,
        depth_limited=depth_limited,
        rounding_exposure=rounding_exposure,
        slippage_bps=round(slippage_bps, 2),
    )


@dataclass(frozen=True)
class SizedCorrelationTrade:
    """A directional position sized by fractional Kelly against a modelled edge.

    Unlike `SizedArb`, this is NOT risk-free: the position loses its stake in
    full if the contract resolves the other way. `worst_case_profit` says so
    honestly (it is simply `-stake`) rather than reusing the guaranteed-profit
    convention that the true arbitrage kinds share.
    """

    side: str                   # "YES" or "NO" -- which side of the joint contract
    stake: float                # all-in outlay: contract cost plus fees
    contracts: float
    fill_price: float           # volume-weighted average cost per contract
    effective_price: float      # fee-adjusted cost per contract
    fee: float
    fair_probability: float     # model's fair P(this side pays out)
    kelly_fraction_full: float  # what the un-haircut Kelly formula wants
    kelly_fraction_used: float  # after the fractional-Kelly haircut and caps
    expected_value: float       # p*payout - stake, in dollars
    worst_case_profit: float    # -stake
    depth_limited: bool


def size_correlation_trade(
    quote: Quote,
    side: str,
    fair_probability: float,
    bankroll: Optional[float] = None,
    kelly_fraction: Optional[float] = None,
    venue_limits: Optional[dict[str, float]] = None,
) -> Optional[SizedCorrelationTrade]:
    """Size a directional bet on one side of a contract by fractional Kelly.

    `fair_probability` is the model's belief that THIS quote's side resolves
    in your favour (i.e. already flipped to 1-p if `side` is the NO leg).
    Returns None when the effective price leaves no edge, when depth or
    bankroll policy caps the trade below the minimum stake, or when the
    resulting stake is too small to bother placing.
    """
    bankroll = bankroll if bankroll is not None else settings.bankroll
    frac = kelly_fraction if kelly_fraction is not None else settings.correlation_kelly_fraction

    d_eff = om.prob_to_decimal(quote.effective_price)
    f_full = om.kelly_fraction(fair_probability, d_eff)
    if f_full <= 0:
        return None  # no edge at the effective price once fees are priced in

    f_used = min(f_full * frac, settings.max_stake_fraction_per_event)
    target = om.round_down_to_step(bankroll * f_used, settings.stake_step)

    capacity = book_capacity(quote.depth, quote.price, quote.size_available)
    venue_cap = (venue_limits or {}).get(quote.venue)
    if venue_cap is not None:
        capacity = min(capacity, venue_cap)
    depth_limited = capacity > 0 and target > capacity
    if capacity > 0:
        target = min(target, capacity)
    target = om.round_down_to_step(target, settings.stake_step)
    if target < settings.min_stake_per_leg:
        return None

    fill = walk_book(quote.depth, quote.price, target)
    fees = fee_model_for(quote.venue)
    contracts = target / fill.avg_price if fill.avg_price > 0 else 0.0
    for _ in range(3):
        eff = fees.effective_price(fill.avg_price, max(contracts, 1.0))
        contracts = target / eff if eff > 0 else 0.0
    eff_price = fees.effective_price(fill.avg_price, max(contracts, 1.0))
    fee = fees.total_fee(fill.avg_price, contracts)

    stake = round(target, 2)
    contracts = round(contracts, 4)
    expected_value = fair_probability * contracts - stake

    return SizedCorrelationTrade(
        side=side,
        stake=stake,
        contracts=contracts,
        fill_price=fill.avg_price,
        effective_price=eff_price,
        fee=round(fee, 4),
        fair_probability=fair_probability,
        kelly_fraction_full=round(f_full, 5),
        kelly_fraction_used=round(f_used, 5),
        expected_value=round(expected_value, 2),
        worst_case_profit=round(-stake, 2),
        depth_limited=depth_limited,
    )


def resize(sized: SizedArb, new_total: float) -> SizedArb:
    """Re-run equal-profit allocation at a different total stake.

    Backs the interactive stake calculator in the UI. Prices are held at their
    already-realised fill levels rather than re-walking the book, so this is
    exact for reductions and optimistic for increases beyond
    `max_stake_available` -- which is why `depth_limited` is re-flagged.
    """
    new_total = max(new_total, 0.0)
    eff_odds = [l.effective_decimal_odds for l in sized.legs]
    stakes = om.equal_profit_stakes(eff_odds, new_total)
    rounded = [om.round_down_to_step(s, settings.stake_step) for s in stakes]

    legs: list[ArbLeg] = []
    for leg, stake in zip(sized.legs, rounded):
        fees = fee_model_for(leg.venue)
        contracts = stake / leg.effective_price if leg.effective_price > 0 else 0.0
        legs.append(
            leg.model_copy(
                update={
                    "stake": round(stake, 2),
                    "contracts": round(contracts, 4),
                    "fee": round(fees.total_fee(leg.price, contracts), 4),
                }
            )
        )

    legs_t = tuple(legs)
    total = round(sum(l.stake for l in legs_t), 2)
    payout_if, worst = _state_payouts(legs_t, sized.payout_multiple)

    return replace(
        sized,
        legs=legs_t,
        total_stake=total,
        profit=round(total * sized.net_margin, 2),
        worst_case_profit=worst,
        payout_if=payout_if,
        depth_limited=new_total > sized.max_stake_available,
    )
