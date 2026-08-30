"""Model-level invariants.

These are the numbers the dashboard renders straight off the serialised model,
so an error here reaches the user without passing through any other code.
"""

from __future__ import annotations

import pytest

from arbengine import odds as om
from arbengine.models import ArbLeg, Side


def _leg(price: float, effective_price: float, stake: float, fee: float) -> ArbLeg:
    """A leg sized the way `sizing._build_leg` sizes one.

    `stake` is the all-in outlay, so the contract count it buys is
    stake / effective_price.
    """
    return ArbLeg(
        venue="kalshi",
        market_id="m1",
        outcome="Yes",
        side=Side.YES,
        price=price,
        effective_price=effective_price,
        decimal_odds=om.prob_to_decimal(price),
        effective_decimal_odds=om.prob_to_decimal(effective_price),
        stake=stake,
        contracts=stake / effective_price,
        fee=fee,
    )


class TestArbLegPayout:
    def test_payout_equals_the_contract_count(self):
        """Every contract settles at $1, so payout must equal `contracts`.

        `payout` used to multiply the all-in stake by the PRE-fee odds, which
        charges the fee and then pays out as though it had not been charged.
        """
        leg = _leg(price=0.50, effective_price=0.52, stake=100.0, fee=2.0)
        assert leg.payout == pytest.approx(leg.contracts)
        assert leg.payout == pytest.approx(192.3077, abs=1e-4)

    def test_net_payout_does_not_deduct_the_fee_twice(self):
        """The fee is inside `stake`, so it is already inside the payout."""
        leg = _leg(price=0.50, effective_price=0.52, stake=100.0, fee=2.0)
        assert leg.net_payout == pytest.approx(leg.payout)

    def test_a_fee_free_venue_is_unchanged(self):
        """With no fee, effective price is the price and nothing moves."""
        leg = _leg(price=0.40, effective_price=0.40, stake=100.0, fee=0.0)
        assert leg.payout == pytest.approx(250.0)
        assert leg.net_payout == pytest.approx(250.0)

    @pytest.mark.parametrize(
        "price,effective_price,stake,fee",
        [
            (0.50, 0.52, 100.0, 2.0),
            (0.20, 0.2140, 250.0, 16.4),
            (0.75, 0.7625, 400.0, 6.5),
            (0.05, 0.0533, 50.0, 3.1),
        ],
    )
    def test_payout_never_exceeds_what_the_stake_can_buy(
        self, price, effective_price, stake, fee
    ):
        leg = _leg(price, effective_price, stake, fee)
        assert leg.payout <= stake / price + 1e-9
        assert leg.payout == pytest.approx(stake / effective_price)

    def test_profit_is_payout_minus_the_all_in_stake(self):
        """The whole point: profit must be computable without re-deducting fees."""
        leg = _leg(price=0.50, effective_price=0.52, stake=100.0, fee=2.0)
        assert leg.payout - leg.stake == pytest.approx(92.3077, abs=1e-4)

    def test_serialised_payout_matches_the_property(self):
        """It is a computed field, so this is what the frontend actually sees."""
        leg = _leg(price=0.50, effective_price=0.52, stake=100.0, fee=2.0)
        dumped = leg.model_dump(mode="json")
        assert dumped["payout"] == pytest.approx(leg.contracts)
        assert dumped["net_payout"] == pytest.approx(leg.contracts)
