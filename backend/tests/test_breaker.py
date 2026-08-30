"""The circuit breaker halts the scanner; it does not quietly blind it.

Part II s16.4: a burst of implausible margins means the feed or the matcher is
wrong, and the correct response is to stop and page a human.
"""

from __future__ import annotations

import asyncio
import tempfile
import os

import pytest

from arbengine.config import settings
from arbengine.models import Arb, ArbKind, ArbLeg, Side
from arbengine.scanner import CircuitBreaker, Scanner
from arbengine.storage import ArbStore


def _fat_arb(i: int, margin: float = 0.40) -> Arb:
    leg = ArbLeg(
        venue="kalshi",
        market_id=f"m{i}",
        outcome="Yes",
        side=Side.YES,
        price=0.3,
        effective_price=0.3,
        decimal_odds=3.3,
        effective_decimal_odds=3.3,
        stake=100.0,
        contracts=333.0,
    )
    return Arb(
        id=f"fat-{i}",
        kind=ArbKind.BINARY_COMPLEMENT,
        title=f"Implausible {i}",
        venues=("kalshi",),
        legs=(leg,),
        total_stake=100.0,
        net_margin=margin,
        worst_case_profit=40.0,
        confidence=90,
    )


class TestBreakerRecording:
    def test_it_trips_once_the_threshold_is_crossed(self):
        b = CircuitBreaker(threshold=3, window_seconds=60, min_margin=0.10)
        assert not b.record(_fat_arb(0))
        assert not b.record(_fat_arb(1))
        assert b.record(_fat_arb(2))
        assert b.tripped

    def test_thin_margins_do_not_count_towards_it(self):
        b = CircuitBreaker(threshold=2, window_seconds=60, min_margin=0.10)
        for i in range(10):
            b.record(_fat_arb(i, margin=0.01))
        assert not b.tripped

    def test_reset_clears_it(self):
        b = CircuitBreaker(threshold=1, window_seconds=60, min_margin=0.10)
        b.record(_fat_arb(0))
        assert b.tripped
        b.reset()
        assert not b.tripped
        assert b.reason is None


@pytest.fixture
def scanner():
    d = tempfile.mkdtemp()
    s = Scanner(store=ArbStore(os.path.join(d, "t.db")), sources=[])
    yield s
    s.store.close()


class TestBreakerHaltsTheScanner:
    def test_a_tripped_breaker_stops_the_engine(self, scanner, monkeypatch):
        """It used to set a flag and let the loop keep turning."""
        monkeypatch.setattr(settings, "demo_mode", False)
        scanner.breaker = CircuitBreaker(threshold=2, window_seconds=60, min_margin=0.10)
        scanner._running = True

        found = [_fat_arb(i) for i in range(5)]
        monkeypatch.setattr(
            "arbengine.scanner.scan",
            lambda *a, **k: type("R", (), {
                "arbs": found, "near_misses": [], "cross_zone_rejected": [],
                "tightest_gap_bps": None,
            })(),
        )
        monkeypatch.setattr("arbengine.scanner.scan_correlation_pairs", lambda *a, **k: [])

        fresh = asyncio.run(scanner.scan_once())

        assert scanner.breaker.tripped
        assert fresh == [], "nothing may be published from an untrusted tape"
        assert scanner._running is False, "the engine must halt, not carry on"
        assert scanner.last_scan.breaker_tripped is True
        assert scanner.live_arbs() == [], "no partial state from a halted scan"

    def test_the_reason_reaches_the_scan_telemetry(self, scanner, monkeypatch):
        monkeypatch.setattr(settings, "demo_mode", False)
        scanner.breaker = CircuitBreaker(threshold=1, window_seconds=60, min_margin=0.10)
        scanner._running = True
        monkeypatch.setattr(
            "arbengine.scanner.scan",
            lambda *a, **k: type("R", (), {
                "arbs": [_fat_arb(0)], "near_misses": [], "cross_zone_rejected": [],
                "tightest_gap_bps": None,
            })(),
        )
        monkeypatch.setattr("arbengine.scanner.scan_correlation_pairs", lambda *a, **k: [])

        asyncio.run(scanner.scan_once())
        assert any("circuit breaker" in e for e in scanner.last_scan.errors)

    def test_demo_mode_is_not_halted_by_it(self, scanner, monkeypatch):
        """Fixtures are deliberately fat; halting on them would be theatre."""
        monkeypatch.setattr(settings, "demo_mode", True)
        scanner.breaker = CircuitBreaker(threshold=1, window_seconds=60, min_margin=0.10)
        scanner._running = True
        found = [_fat_arb(i) for i in range(3)]
        monkeypatch.setattr(
            "arbengine.scanner.scan",
            lambda *a, **k: type("R", (), {
                "arbs": found, "near_misses": [], "cross_zone_rejected": [],
                "tightest_gap_bps": None,
            })(),
        )
        monkeypatch.setattr("arbengine.scanner.scan_correlation_pairs", lambda *a, **k: [])

        asyncio.run(scanner.scan_once())
        assert scanner._running is True
        assert len(scanner.live_arbs()) == 3
