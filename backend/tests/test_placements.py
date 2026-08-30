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

        # 1. Test unwind quote
        quote_res = client.get(f"/api/positions/{row_id}/unwind-quote")
        assert quote_res.status_code == 200
        q = quote_res.json()
        assert q["row_id"] == row_id
        assert q["total_stake"] == 100.0
        assert len(q["legs"]) == 2

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

        # Place a second arb and test sell-back
        arb2 = _sample_arb()
        arb2_id = "test-arb-2"
        arb2 = arb2.model_copy(update={"id": arb2_id, "title": "Arsenal vs Chelsea 2"})
        api_mod.scanner._live[arb2_id] = arb2

        res2 = client.post(f"/api/arbs/{arb2_id}/place", json={"confirmed": True})
        assert res2.status_code == 200
        row_id2 = res2.json()["arb_row_id"]

        sell_res = client.post(f"/api/positions/{row_id2}/sell-back", json={"confirmed": True, "note": "Test unwind"})
        assert sell_res.status_code == 200
        s = sell_res.json()
        assert s["ok"] is True
        assert s["settlement_type"] == "sell_back_early"

