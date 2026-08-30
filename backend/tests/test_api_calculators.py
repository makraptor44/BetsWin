"""Calculator endpoints.

These are pure functions of their inputs, so the only interesting behaviour is
what they do with input that is not valid: bad input is the caller's mistake and
must come back as a 400 with a reason, never as a 500.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arbengine.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestConvert:
    @pytest.mark.parametrize("value", [0, 1, -1, 50, -99])
    def test_american_odds_inside_plus_minus_100_are_a_400(self, client, value):
        """`{"value": 0, "from_format": "american"}` used to be a 500.

        1 + 100/abs(0) raised ZeroDivisionError inside the handler.
        """
        res = client.post(
            "/api/calc/convert", json={"value": value, "from_format": "american"}
        )
        assert res.status_code == 400
        assert "American odds" in res.json()["detail"]

    def test_valid_american_still_converts(self, client):
        res = client.post(
            "/api/calc/convert", json={"value": -200, "from_format": "american"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["decimal"] == pytest.approx(1.5)
        assert body["american"] == pytest.approx(-200.0)
        assert body["probability"] == pytest.approx(0.6667, abs=1e-3)

    def test_decimal_of_one_is_a_400_not_a_crash(self, client):
        res = client.post(
            "/api/calc/convert", json={"value": 1.0, "from_format": "decimal"}
        )
        assert res.status_code == 400

    @pytest.mark.parametrize("value", [0.0, 1.0, 1.5, -0.2])
    def test_probability_outside_the_open_unit_interval_is_a_400(self, client, value):
        res = client.post(
            "/api/calc/convert", json={"value": value, "from_format": "probability"}
        )
        assert res.status_code == 400

    def test_probability_roundtrips(self, client):
        res = client.post(
            "/api/calc/convert", json={"value": 0.25, "from_format": "probability"}
        )
        assert res.status_code == 200
        assert res.json()["decimal"] == pytest.approx(4.0)


class TestVoidAdjusted:
    def test_zero_void_loss_reports_an_unbounded_kelly_bound(self, client):
        """No void cost means no risk, so bankroll binds -- not "stake nothing".

        The bound used to be reported as 0.0, which reads as "do not trade" for
        the one input where the trade is riskless.
        """
        res = client.post(
            "/api/calc/void-adjusted",
            json={"margin": 0.02, "void_rate": 0.0, "void_loss": 0.0},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["kelly_arb_fraction"] is None
        assert body["kelly_arb_unbounded"] is True

    def test_a_real_void_model_still_returns_a_number(self, client):
        res = client.post(
            "/api/calc/void-adjusted",
            json={"margin": 0.02, "void_rate": 0.03, "void_loss": 0.30},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["kelly_arb_unbounded"] is False
        assert body["kelly_arb_fraction"] == pytest.approx(1.733, abs=0.01)
        assert body["effective_margin"] == pytest.approx(0.0104, abs=1e-4)


class TestAlertDedupeDoesNotLeak:
    def test_the_alerted_map_is_bounded(self, monkeypatch):
        """A plain set grew one entry per alerted arb and was never pruned."""
        import time

        from arbengine.alerts import AlertManager
        from arbengine.config import settings as s
        from tests.test_strategy_aggregates import _arb

        monkeypatch.setattr(s, "alert_min_margin", 0.0)
        monkeypatch.setattr(s, "alert_min_confidence", 0)
        monkeypatch.setattr(s, "dedup_window_seconds", 0)

        mgr = AlertManager()
        for i in range(500):
            arb = _arb(f"a{i}", "arbitrage", 5.0, 100.0)
            mgr.should_alert(arb)
            mgr._alerted[arb.dedupe_key()] = time.monotonic() - 10_000

        # One more call prunes everything already outside the window.
        mgr.should_alert(_arb("final", "arbitrage", 5.0, 100.0))
        assert len(mgr._alerted) <= 64

    def test_a_repeat_inside_the_window_is_not_re_alerted(self, monkeypatch):
        from arbengine.alerts import AlertManager
        from arbengine.config import settings as s
        from tests.test_strategy_aggregates import _arb

        monkeypatch.setattr(s, "alert_min_margin", 0.0)
        monkeypatch.setattr(s, "alert_min_confidence", 0)
        monkeypatch.setattr(s, "dedup_window_seconds", 300)

        mgr = AlertManager()
        arb = _arb("dupe", "arbitrage", 5.0, 100.0)
        assert mgr.should_alert(arb) is True
        mgr._alerted[arb.dedupe_key()] = __import__("time").monotonic()
        assert mgr.should_alert(arb) is False


class TestWebsocketBeforeStartup:
    def test_it_closes_cleanly_when_the_engine_is_not_up(self, monkeypatch):
        """`_engine()` raises HTTPException, which is meaningless over a socket."""
        from starlette.testclient import WebSocketDisconnect
        from fastapi.testclient import TestClient

        import arbengine.api as api_mod

        monkeypatch.setattr(api_mod, "scanner", None)
        # No lifespan: the app never starts the engine.
        client = TestClient(api_mod.app)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws"):
                pass
        assert exc.value.code == 1013
