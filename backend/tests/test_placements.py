import pytest
from datetime import datetime, timezone
import tempfile
import os
from arbengine.models import Arb, ArbKind, ArbLeg, Event, Market, Outcome, Quote, Side
from arbengine.storage import ArbStore


def _sample_arb() -> Arb:
    now = datetime.now(timezone.utc)
    legs = [
        ArbLeg(
            venue="polymarket",
            market_id="pm-1",
            ticker="PM-YES",
            outcome="Arsenal",
            side=Side.YES,
            price=0.45,
            effective_price=0.45,
            decimal_odds=2.222,
            effective_decimal_odds=2.222,
            stake=50.0,
            contracts=111.11,
            fee=0.0,
            size_available=500.0,
            url="https://polymarket.com/market/1",
            event_title="Arsenal vs Chelsea",
            payout=111.11,
            net_payout=111.11,
        ),
        ArbLeg(
            venue="kalshi",
            market_id="kl-1",
            ticker="KL-NO",
            outcome="Chelsea or Draw",
            side=Side.NO,
            price=0.52,
            effective_price=0.52,
            decimal_odds=1.923,
            effective_decimal_odds=1.923,
            stake=50.0,
            contracts=96.15,
            fee=0.0,
            size_available=500.0,
            url="https://kalshi.com/market/1",
            event_title="Arsenal vs Chelsea",
            payout=96.15,
            net_payout=96.15,
        ),
    ]
    return Arb(
        id="test-arb-1",
        kind=ArbKind.BINARY_COMPLEMENT,
        title="Arsenal vs Chelsea",
        category="sports",
        venues=["polymarket", "kalshi"],
        zone="us_prediction",
        zone_label="US Prediction Markets",
        currency="USD",
        placeable_from=["US"],
        market_key="match_winner",
        legs=legs,
        total_stake=100.0,
        book=0.97,
        margin=0.0309,
        net_margin=0.0309,
        profit=3.09,
        worst_case_profit=3.09,
        payout_if={"Arsenal": 111.11, "Chelsea or Draw": 96.15},
        max_stake_available=500.0,
        confidence=95,
        flags=[],
        notes=[],
        detected_at=now,
        close_time=None,
        last_seen=now,
        is_suspect=False,
        roi_pct=3.09,
        hours_to_close=24.0,
    )


def test_storage_placement_and_settlement():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_arbs.db")
        store = ArbStore(db_path)

        arb = _sample_arb()
        row_id = store.upsert_arb(arb)
        assert row_id > 0

        # Record placements
        for leg in arb.legs:
            store.record_placement(
                arb_id=row_id,
                venue=leg.venue,
                market_id=leg.market_id,
                outcome=leg.outcome,
                side=leg.side.value,
                requested_price=leg.price,
                requested_stake=leg.stake,
                status="placed",
                executed_price=leg.price,
                executed_stake=leg.stake,
                note="Test placement",
            )

        store.mark_placed(row_id, True)

        # Check open positions
        open_pos = store.open_positions()
        assert len(open_pos) == 1
        assert open_pos[0]["id"] == row_id

        # Check all positions
        all_pos = store.all_positions(settled=False)
        assert len(all_pos) == 1
        assert all_pos[0]["id"] == row_id

        # Placements check
        placements = store.placements_for(row_id)
        assert len(placements) == 2
        assert placements[0]["venue"] == "polymarket"
        assert placements[1]["venue"] == "kalshi"

        # Settle
        store.settle(row_id, realised_pnl=3.10)
        assert len(store.open_positions()) == 0

        settled_pos = store.all_positions(settled=True)
        assert len(settled_pos) == 1
        assert settled_pos[0]["settled"] == 1
        assert settled_pos[0]["realised_pnl"] == 3.10
        store.close()


def _unique_arb(tag: str) -> Arb:
    """A sample arb with a distinct dedupe key.

    `upsert_arb` dedupes on the leg signature, so two arbs built from identical
    legs collapse onto one stored row however different their ids are.
    """
    arb = _sample_arb()
    legs = tuple(
        l.model_copy(update={"market_id": f"{l.market_id}-{tag}"}) for l in arb.legs
    )
    return arb.model_copy(update={"id": f"arb-{tag}", "legs": legs})


def test_settlement_figure_is_never_silently_discarded():
    """Posting a P&L must book that P&L, or fail loudly.

    The dashboard posted `realised_pnl` to /settle, but the endpoint declares
    `custom_pnl`. Pydantic drops unknown fields by default, so the figure was
    thrown away, the theoretical worst case was booked instead, and the call
    returned ok: true.
    """
    from fastapi.testclient import TestClient
    from arbengine.api import app
    import arbengine.api as api_mod

    with TestClient(app) as client:
        arb = _unique_arb("settle-contract")
        api_mod.scanner._live[arb.id] = arb
        row_id = client.post(
            f"/api/arbs/{arb.id}/place", json={"confirmed": True}
        ).json()["arb_row_id"]

        # The field the endpoint actually declares books the figure given.
        res = client.post(
            f"/api/positions/{row_id}/settle", json={"custom_pnl": 12.34}
        )
        assert res.status_code == 200
        assert res.json()["realised_pnl"] == pytest.approx(12.34)

        row = api_mod.scanner.store.arb_by_id(row_id)
        assert row["realised_pnl"] == pytest.approx(12.34)
        assert row["realised_pnl"] != row["worst_case_profit"]


def test_an_unknown_settlement_field_is_rejected_not_ignored():
    from fastapi.testclient import TestClient
    from arbengine.api import app
    import arbengine.api as api_mod

    with TestClient(app) as client:
        arb = _unique_arb("settle-drift")
        api_mod.scanner._live[arb.id] = arb
        row_id = client.post(
            f"/api/arbs/{arb.id}/place", json={"confirmed": True}
        ).json()["arb_row_id"]

        res = client.post(
            f"/api/positions/{row_id}/settle", json={"realised_pnl": 99.99}
        )
        assert res.status_code == 422, "contract drift must not pass silently"

        row = api_mod.scanner.store.arb_by_id(row_id)
        assert row["settled"] == 0, "a rejected request must not settle anything"


def test_api_unwind_and_resolve():
    from fastapi.testclient import TestClient
    from arbengine.api import app
    import arbengine.api as api_mod

    with TestClient(app) as client:
        # Place an arb via API
        arb = _sample_arb()
        api_mod.scanner._live[arb.id] = arb

        res = client.post(f"/api/arbs/{arb.id}/place", json={"confirmed": True, "note": "Test API place"})
        assert res.status_code == 200
        data = res.json()
        row_id = data["arb_row_id"]

        # 1. Unwind quote. Nothing is on the live tape in this test, so no leg
        #    has a bid and the position cannot be valued. It used to report a
        #    price here regardless, invented as entry_price * (1 - 0.005).
        quote_res = client.get(f"/api/positions/{row_id}/unwind-quote")
        assert quote_res.status_code == 200
        q = quote_res.json()
        assert q["row_id"] == row_id
        assert q["total_stake"] == 100.0
        assert len(q["legs"]) == 2
        assert q["quotable"] is False
        assert q["priced_legs"] == 0
        assert all(l["current_bid"] is None for l in q["legs"])
        assert q["unwind_pnl"] is None

        # 2. Test resolve position (Hold to Resolution)
        resolve_res = client.post(f"/api/positions/{row_id}/resolve", json={"winning_outcome": "Arsenal"})
        assert resolve_res.status_code == 200
        r = resolve_res.json()
        assert r["ok"] is True
        assert r["settlement_type"] == "hold_to_resolution"
        assert r["winning_outcome"] == "Arsenal"

        # Verify positions endpoint shows it as settled
        pos_res = client.get("/api/positions")
        assert pos_res.status_code == 200
        pdata = pos_res.json()
        pos_item = next((p for p in pdata["positions"] if p["id"] == row_id), None)
        assert pos_item is not None
        assert pos_item["settled"] == 1

        # Place a second arb and test sell-back. Its LEGS have to differ, not
        # just its id: upsert_arb dedupes on the leg signature, so an arb built
        # from identical legs lands on the row already settled above.
        arb2 = _unique_arb("sell-back")
        arb2_id = arb2.id
        api_mod.scanner._live[arb2_id] = arb2

        res2 = client.post(f"/api/arbs/{arb2_id}/place", json={"confirmed": True})
        assert res2.status_code == 200
        row_id2 = res2.json()["arb_row_id"]

        # With no live bid the unwind is refused rather than booked at a made-up
        # price. This assertion is the inverse of what it used to be: the old
        # test asserted a 200 here, which only passed because the handler
        # invented a price and wrote it to the ledger as realised P&L.
        sell_res = client.post(
            f"/api/positions/{row_id2}/sell-back",
            json={"confirmed": True, "note": "Test unwind"},
        )
        assert sell_res.status_code == 409
        assert "no live bid" in sell_res.json()["detail"]

        row = api_mod.scanner.store.arb_by_id(row_id2)
        assert row["settled"] == 0, "a refused unwind must not settle the position"

        # An unwind executed by hand can still be recorded, at prices the
        # operator states rather than any the engine made up.
        manual = client.post(
            f"/api/positions/{row_id2}/sell-back",
            json={"confirmed": True, "custom_prices": [0.46, 0.53], "note": "Filled by hand"},
        )
        assert manual.status_code == 200
        s = manual.json()
        assert s["ok"] is True
        assert s["settlement_type"] == "sell_back_early"
        assert api_mod.scanner.store.arb_by_id(row_id2)["settled"] == 1

        # And an unconfirmed unwind is refused outright.
        arb3 = _unique_arb("no-confirm")
        api_mod.scanner._live[arb3.id] = arb3
        row_id3 = client.post(
            f"/api/arbs/{arb3.id}/place", json={"confirmed": True}
        ).json()["arb_row_id"]
        unconfirmed = client.post(
            f"/api/positions/{row_id3}/sell-back", json={"confirmed": False}
        )
        assert unconfirmed.status_code == 400



def _binary_event(venue: str, market_id: str, name: str, ask: float, comp_ask: float) -> Event:
    """A two-sided market so the unwind quote can derive a bid.

    Selling a contract is buying its complement, so the bid on `name` is
    1 - (ask on the other side).
    """
    def _q(mid: str, outcome: str, price: float, side: Side) -> Quote:
        return Quote(
            venue=venue,
            market_id=mid,
            outcome=outcome,
            side=side,
            price=price,
            effective_price=price,
            size_available=5000.0,
        )

    return Event(
        id=f"{venue}:{market_id}",
        venue=venue,
        title="Arsenal vs Chelsea",
        markets=(
            Market(
                key="binary",
                outcomes=(
                    Outcome(name=name, quotes=(_q(market_id, name, ask, Side.YES),)),
                    Outcome(
                        name=f"Not {name}",
                        quotes=(_q(f"{market_id}-no", f"Not {name}", comp_ask, Side.NO),),
                    ),
                ),
            ),
        ),
    )


def test_unwind_quote_derives_a_real_bid_from_the_complement():
    """With the tape present, the exit price comes from the book, not a guess.

    On a $1 binary, selling a YES is buying a NO, so the YES bid is
    1 - (NO ask). That is a real price; `entry_price * (1 - 0.005)` was not.
    """
    from fastapi.testclient import TestClient
    from arbengine.api import app
    import arbengine.api as api_mod

    with TestClient(app) as client:
        arb = _unique_arb("live-bid")
        api_mod.scanner._live[arb.id] = arb
        row_id = client.post(
            f"/api/arbs/{arb.id}/place", json={"confirmed": True}
        ).json()["arb_row_id"]

        pm_leg, kl_leg = arb.legs
        api_mod.scanner._events = [
            _binary_event("polymarket", pm_leg.market_id, pm_leg.outcome, 0.45, 0.53),
            _binary_event("kalshi", kl_leg.market_id, kl_leg.outcome, 0.52, 0.49),
        ]
        try:
            q = client.get(f"/api/positions/{row_id}/unwind-quote").json()
            assert q["quotable"] is True
            assert q["priced_legs"] == 2

            by_outcome = {l["outcome"]: l for l in q["legs"]}
            # 1 - 0.53 and 1 - 0.49, straight off the complementary asks.
            assert by_outcome[pm_leg.outcome]["current_bid"] == pytest.approx(0.47)
            assert by_outcome[kl_leg.outcome]["current_bid"] == pytest.approx(0.51)
            assert all(
                l["price_source"] == "complement_ask" for l in q["legs"]
            )
            assert q["unwind_pnl"] is not None
        finally:
            api_mod.scanner._events = []
