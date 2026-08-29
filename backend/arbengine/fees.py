"""Venue fee models.

The theory volume assumes bookmaker prices are the whole cost. On US prediction
markets that is false: Kalshi charges an explicit per-contract trading fee that
peaks at mid-price, which is exactly where most arbitrage candidates live. A 2%
nominal margin can be entirely consumed by fees, so every price is converted to
an EFFECTIVE cost per $1 of payout before the detector ever sees it.

Effective decimal odds: d_eff = 1 / (price + fee_per_contract).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

from .odds import MAX_PRICE, MIN_PRICE


class FeeModel(ABC):
    """Converts a quoted contract price into a true all-in cost."""

    name: str = "none"

    @abstractmethod
    def fee_per_contract(self, price: float, contracts: float = 1.0) -> float:
        """Fee in dollars attributable to one contract at `price`."""

    def effective_price(self, price: float, contracts: float = 1.0) -> float:
        """All-in cost of one contract paying $1 on success."""
        p = price + self.fee_per_contract(price, contracts)
        return min(max(p, MIN_PRICE), MAX_PRICE)

    def effective_decimal_odds(self, price: float, contracts: float = 1.0) -> float:
        return 1.0 / self.effective_price(price, contracts)

    def total_fee(self, price: float, contracts: float) -> float:
        return self.fee_per_contract(price, contracts) * contracts


class NoFeeModel(FeeModel):
    """Zero-fee venue."""

    name = "none"

    def fee_per_contract(self, price: float, contracts: float = 1.0) -> float:
        return 0.0


class BpsFeeModel(FeeModel):
    """Flat basis-point taker fee on notional, plus an optional fixed cost.

    Used for Polymarket, whose CLOB currently charges no taker fee but where gas
    or a relayer cost can be modelled by `fixed_cost_usd` amortised over the
    order.
    """

    name = "bps"

    def __init__(self, bps: float = 0.0, fixed_cost_usd: float = 0.0) -> None:
        self.bps = bps
        self.fixed_cost_usd = fixed_cost_usd

    def fee_per_contract(self, price: float, contracts: float = 1.0) -> float:
        variable = price * (self.bps / 10_000.0)
        fixed = (self.fixed_cost_usd / contracts) if contracts > 0 else 0.0
        return variable + fixed


class CommissionFeeModel(FeeModel):
    """Betting-exchange commission, charged on net winnings rather than stake.

    An exchange takes nothing when you lose and a percentage of your profit when
    you win. For one contract bought at price `p` and paying $1:

        win  -> gross profit (1 - p), commission c*(1 - p), net payout
                1 - c*(1 - p)
        lose -> nothing

    So the all-in cost per $1 of NET payout is

        p_eff = p / (1 - c*(1 - p))

    which is `exchange_effective_odds` from Part I s6.1 expressed in price
    space. Note the shape: unlike Kalshi's fee, this one is largest at long
    odds, because that is where the winnings -- and therefore the commission --
    are largest relative to the outlay.

    One deliberate conservatism. Both Betfair and Smarkets charge commission on
    NET winnings across a whole market, so a Dutch book that backs every outcome
    pays commission only on the netted result, not leg by leg. Charging every
    leg here overstates the bill and therefore understates the edge. That is the
    right direction to be wrong in: it suppresses marginal opportunities rather
    than manufacturing them.
    """

    name = "commission"

    def __init__(self, commission: float = 0.02) -> None:
        self.commission = commission

    def fee_per_contract(self, price: float, contracts: float = 1.0) -> float:
        c = self.commission
        if c <= 0:
            return 0.0
        p = min(max(price, MIN_PRICE), MAX_PRICE)
        denom = 1.0 - c * (1.0 - p)
        if denom <= 0:
            return MAX_PRICE - p
        return p / denom - p


class KalshiFeeModel(FeeModel):
    """Kalshi's published trading fee.

        fee = ceil(coefficient * C * P * (1 - P))   [dollars, rounded up to $0.01]

    with coefficient 0.07 for takers. The P*(1-P) shape means the fee is maximal
    at P = 0.50 (1.75c per contract) and vanishes at the extremes. Because both
    legs of a binary complement arb sit either side of the same price, the
    combined fee bill is what decides whether a 1-2% book edge survives.
    """

    name = "kalshi"

    def __init__(self, coefficient: float = 0.07, maker_coefficient: float = 0.0025) -> None:
        self.coefficient = coefficient
        self.maker_coefficient = maker_coefficient

    def order_fee(self, price: float, contracts: float, maker: bool = False) -> float:
        """Total dollar fee for an order of `contracts` at `price`, rounded up."""
        if contracts <= 0:
            return 0.0
        coef = self.maker_coefficient if maker else self.coefficient
        raw = coef * contracts * price * (1.0 - price)
        # Round before the ceiling: 0.07*100*0.5*0.5 is 1.7500000000000002 in
        # binary floating point, which would otherwise round up a whole cent.
        return math.ceil(round(raw * 100.0, 9)) / 100.0

    def fee_per_contract(self, price: float, contracts: float = 1.0) -> float:
        contracts = max(contracts, 1.0)
        return self.order_fee(price, contracts) / contracts


# Registry -------------------------------------------------------------------

_REGISTRY: dict[str, FeeModel] = {}


def register_fee_model(venue: str, model: FeeModel) -> None:
    _REGISTRY[venue.lower()] = model


def fee_model_for(venue: str) -> FeeModel:
    return _REGISTRY.get(venue.lower(), _NO_FEE)


_NO_FEE = NoFeeModel()


def configure_from_settings(settings) -> None:
    """Wire the registry from application settings."""
    register_fee_model(
        "polymarket",
        BpsFeeModel(settings.polymarket_fee_bps, settings.polymarket_gas_cost_usd),
    )
    register_fee_model(
        "kalshi",
        KalshiFeeModel(settings.kalshi_fee_coefficient, settings.kalshi_maker_fee_coefficient),
    )
    # Sportsbooks price their margin into the odds; no separate fee.
    register_fee_model("sportsbook", _NO_FEE)
    # Exchanges take a cut of winnings instead of quoting a margin.
    register_fee_model("smarkets", CommissionFeeModel(settings.smarkets_commission))
    register_fee_model("betfair", CommissionFeeModel(settings.betfair_commission))


__all__ = [
    "FeeModel",
    "NoFeeModel",
    "BpsFeeModel",
    "CommissionFeeModel",
    "KalshiFeeModel",
    "fee_model_for",
    "register_fee_model",
    "configure_from_settings",
]
