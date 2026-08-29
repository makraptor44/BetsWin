"""Execution-zone pairing rules.

The rule these tests pin down: cross-venue arbitrage is only surfaced when one
operator could place both legs -- same zone, same currency, and a jurisdiction
that serves both. The expensive failure is the opposite direction, a pair that
looks perfect on paper and cannot be traded by anybody, so most of these assert
that something is *rejected*.
"""

from __future__ import annotations

import pytest

from arbengine.config import settings
from arbengine.fees import CommissionFeeModel, configure_from_settings
from arbengine.venues import (
    Zone,
    can_pair,
    common_jurisdictions,
    legs_are_placeable,
    venue,
    venues_in,
    zone_of,
    zones_available_from,
)


# ------------------------------------------------------------ the core rule


def test_same_zone_pairs_are_allowed():
    assert can_pair("polymarket", "kalshi").ok
    assert can_pair("betfair", "smarkets").ok


def test_cross_zone_pairs_are_rejected():
    """The case the feature exists for: a GBP exchange against a USD contract."""
    verdict = can_pair("betfair", "kalshi")
    assert not verdict.ok
    assert "different execution zones" in verdict.reason


@pytest.mark.parametrize(
    "a,b",
    [
        ("betfair", "kalshi"),
        ("betfair", "polymarket"),
        ("smarkets", "kalshi"),
        ("smarkets", "polymarket"),
        ("smarkets", "sportsbook"),
        ("kalshi", "sportsbook"),
    ],
)
def test_every_cross_zone_combination_is_rejected(a, b):
    assert not can_pair(a, b).ok
    assert not can_pair(b, a).ok


def test_rejection_reason_names_both_currencies():
    """The UI shows this string; it has to explain itself without the code."""
    reason = can_pair("smarkets", "kalshi").reason
    assert "GBP" in reason and "USD" in reason


def test_a_venue_never_pairs_with_itself():
    assert not can_pair("kalshi", "kalshi").ok


def test_unknown_venues_never_pair():
    assert not can_pair("kalshi", "some-new-venue").ok
    assert zone_of("some-new-venue") is Zone.UNKNOWN


# ------------------------------------------------------------- jurisdictions


def test_shared_jurisdiction_is_reported():
    verdict = can_pair("betfair", "smarkets")
    assert "GB" in verdict.jurisdictions
    assert "US" not in verdict.jurisdictions


def test_polymarket_excludes_us_persons_from_every_pair():
    """Polymarket's US restriction must survive Kalshi's broad availability."""
    assert "US" not in common_jurisdictions("polymarket", "kalshi")


def test_operator_jurisdiction_filters_pairs():
    """A UK-based operator cannot place the US sportsbook leg."""
    assert can_pair("betfair", "smarkets", "GB").ok
    assert not can_pair("betfair", "smarkets", "US").ok


def test_zones_available_needs_two_reachable_venues():
    from_gb = zones_available_from("GB")
    assert Zone.UK_EXCHANGE in from_gb
    assert Zone.US_SPORTSBOOK not in from_gb


# -------------------------------------------------------------- leg sets


def test_single_venue_leg_sets_are_always_placeable():
    """Dutch books live on one venue; the zone rule must not touch them."""
    assert legs_are_placeable(["kalshi", "kalshi", "kalshi"]).ok


def test_three_leg_set_spanning_zones_is_rejected():
    assert not legs_are_placeable(["kalshi", "polymarket", "betfair"]).ok


def test_two_leg_set_inside_a_zone_is_placeable():
    assert legs_are_placeable(["polymarket", "kalshi"]).ok


# ------------------------------------------------------------ zone contents


def test_zone_membership_matches_the_pairing_rule():
    """Anything in a zone pairs with anything else in it, and nothing outside."""
    for zone in (Zone.US_PREDICTION, Zone.UK_EXCHANGE):
        members = [v.name for v in venues_in(zone)]
        assert len(members) >= 2
        for a in members:
            for b in members:
                if a != b:
                    assert can_pair(a, b).ok


def test_exchange_venues_carry_a_commission():
    assert venue("smarkets").commission > 0
    assert venue("betfair").commission > 0
    assert venue("kalshi").commission == 0


# ------------------------------------------------------- commission maths


def test_commission_is_charged_on_winnings_not_stake():
    """A losing contract costs its price and nothing more."""
    model = CommissionFeeModel(0.02)
    # At a price of 1 there are no winnings, so there is no commission.
    assert model.fee_per_contract(0.999) == pytest.approx(0.0, abs=2e-3)


def test_commission_bites_hardest_at_long_odds():
    """Unlike Kalshi's fee, which peaks at 0.50, this one rises as p falls."""
    model = CommissionFeeModel(0.05)
    long_shot = model.effective_price(0.10) / 0.10 - 1.0
    favourite = model.effective_price(0.90) / 0.90 - 1.0
    assert long_shot > favourite


def test_commission_matches_the_decimal_odds_formula():
    """p_eff = p / (1 - c(1-p)) must agree with 1 + (d-1)(1-c) from Part I s6.1."""
    from arbengine import odds as om

    model = CommissionFeeModel(0.05)
    for p in (0.2, 0.35, 0.5, 0.75):
        via_price = 1.0 / model.effective_price(p)
        via_odds = om.exchange_effective_odds(om.prob_to_decimal(p), 0.05)
        assert via_price == pytest.approx(via_odds, rel=1e-9)


def test_registry_wires_exchange_fee_models():
    from arbengine.fees import fee_model_for

    configure_from_settings(settings)
    assert fee_model_for("smarkets").name == "commission"
    assert fee_model_for("betfair").name == "commission"


# ------------------------------------------------- storage schema migration


def test_existing_database_gains_zone_columns_and_backfills(tmp_path):
    """A database written before execution zones must not need deleting.

    `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so without a
    migration every insert would fail on the new columns. And a backfilled row
    is not 'unknown': its zone is fully determined by the venues already stored
    on it, so leaving it blank would put a meaningless bucket at the top of
    every zone breakdown for the whole retention window.
    """
    import sqlite3

    from arbengine.storage import ArbStore

    db = tmp_path / "old.db"
    store = ArbStore(str(db))
    store.close()

    conn = sqlite3.connect(str(db))
    for column in ("zone", "currency"):
        conn.execute(f"ALTER TABLE arbs DROP COLUMN {column}")
    conn.execute(
        """INSERT INTO arbs
           (arb_key, kind, title, category, venues, market_key, detected_at,
            last_seen, book, margin, net_margin, total_stake, profit,
            worst_case_profit, max_stake, confidence, legs_json, payload_json)
           VALUES ('k','cross_venue','t','politics','["betfair","smarkets"]',
                   'cross_venue','2026-08-29T00:00:00+00:00',
                   '2026-08-29T00:00:00+00:00',0.98,0.02,0.015,500,7.5,7.5,
                   1000,80,'[]','{}')"""
    )
    conn.commit()
    conn.close()

    reopened = ArbStore(str(db))
    try:
        columns = {r[1] for r in reopened.conn.execute("PRAGMA table_info(arbs)")}
        assert {"zone", "currency"} <= columns

        row = reopened._rows("SELECT zone, currency FROM arbs")[0]
        assert row["zone"] == "uk_exchange"
        assert row["currency"] == "GBP"
    finally:
        reopened.close()
