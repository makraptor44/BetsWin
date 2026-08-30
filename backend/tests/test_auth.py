"""Nothing that changes state may be reachable without the key.

Before this, anyone who could reach the port could rewrite the bankroll and
every risk threshold, stop the scanner, place bets and settle positions.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import arbengine.api as api_mod
from arbengine.api import app, _assert_safe_binding
from arbengine.config import settings


KEY = "test-key-9f3a"


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(settings, "api_key", KEY)
    with TestClient(app) as client:
        yield client


#: Every state-changing route, with a body the handler would otherwise accept.
MUTATING = [
    ("patch", "/api/config", {"bankroll": 500.0}),
    ("post", "/api/scanner/scan", {}),
    ("post", "/api/scanner/start", {}),
    ("post", "/api/scanner/stop", {}),
    ("post", "/api/scanner/reset-breaker", {}),
    ("post", "/api/arbs/nonexistent/place", {"confirmed": True}),
    ("post", "/api/positions/1/settle", {"custom_pnl": 1.0}),
    ("post", "/api/positions/1/sell-back", {"confirmed": True}),
    ("delete", "/api/correlation/pairs/x", None),
]


class TestMutatingRoutesAreGated:
    @pytest.mark.parametrize("method,path,body", MUTATING)
    def test_no_key_is_rejected(self, secured, method, path, body):
        res = getattr(secured, method)(path, json=body) if body is not None else getattr(
            secured, method
        )(path)
        assert res.status_code == 401, f"{method.upper()} {path} was not gated"

    @pytest.mark.parametrize("method,path,body", MUTATING)
    def test_a_wrong_key_is_rejected(self, secured, method, path, body):
        headers = {"X-API-Key": "not-the-key"}
        res = (
            getattr(secured, method)(path, json=body, headers=headers)
            if body is not None
            else getattr(secured, method)(path, headers=headers)
        )
        assert res.status_code == 401

    def test_the_right_key_is_accepted(self, secured):
        res = secured.patch(
            "/api/config", json={"bankroll": 12345.0}, headers={"X-API-Key": KEY}
        )
        assert res.status_code == 200
        assert res.json()["updated"]["bankroll"] == 12345.0


class TestReadsStayOpen:
    @pytest.mark.parametrize(
        "path", ["/api/health", "/api/status", "/api/config", "/api/arbs", "/api/venues"]
    )
    def test_reads_need_no_key(self, secured, path):
        assert secured.get(path).status_code == 200


class TestBindingGuard:
    def test_a_public_bind_without_a_key_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "")
        monkeypatch.setattr(settings, "host", "0.0.0.0")
        with pytest.raises(RuntimeError, match="refusing to bind"):
            _assert_safe_binding()

    def test_a_public_bind_with_a_key_is_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", KEY)
        monkeypatch.setattr(settings, "host", "0.0.0.0")
        _assert_safe_binding()

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
    def test_loopback_without_a_key_is_allowed(self, monkeypatch, host):
        monkeypatch.setattr(settings, "api_key", "")
        monkeypatch.setattr(settings, "host", host)
        _assert_safe_binding()


class TestConfigCrossValidation:
    def test_a_min_above_the_max_is_rejected(self, secured):
        res = secured.patch(
            "/api/config",
            json={"min_arb_margin": 0.20, "max_arb_margin": 0.05},
            headers={"X-API-Key": KEY},
        )
        assert res.status_code == 400
        assert "cannot exceed" in res.json()["detail"]

    def test_a_rejected_patch_changes_nothing(self, secured):
        before = secured.get("/api/config").json()["min_arb_margin"]
        secured.patch(
            "/api/config",
            json={"min_arb_margin": 0.20, "max_arb_margin": 0.05},
            headers={"X-API-Key": KEY},
        )
        assert secured.get("/api/config").json()["min_arb_margin"] == before


class TestConfirmationIsEnforced:
    def test_an_unconfirmed_placement_is_refused(self, secured, monkeypatch):
        from tests.test_placements import _unique_arb

        arb = _unique_arb("no-confirm-auth")
        api_mod.scanner._live[arb.id] = arb
        res = secured.post(
            f"/api/arbs/{arb.id}/place",
            json={"confirmed": False},
            headers={"X-API-Key": KEY},
        )
        assert res.status_code == 400
        assert "confirmation" in res.json()["detail"]
