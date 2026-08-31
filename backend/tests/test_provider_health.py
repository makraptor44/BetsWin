"""Provider health: the readout that decides whether to trust a feed.

A boolean cannot carry the distinction that matters. A provider answering but
rate-limited into partial coverage is neither healthy nor offline, and treating
it as either is wrong in a different direction each time -- healthy hides that
coverage has silently narrowed, offline discards prices that are perfectly good.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from arbengine.models import Event
from arbengine.sources.base import Health, ProviderStats, Source, redact


class _Stub(Source):
    """A source whose next result the test chooses."""

    name = "stub"
    label = "Stub"

    def __init__(self, *, fail: BaseException | None = None, events: int = 0) -> None:
        super().__init__(client=httpx.AsyncClient())
        self.fail = fail
        self.events = events

    async def fetch_events(self) -> list[Event]:
        if self.fail is not None:
            raise self.fail
        return [
            Event(id=f"stub:{i}", venue="stub", title=f"E{i}")
            for i in range(self.events)
        ]


def _rate_limited() -> httpx.HTTPStatusError:
    """The error httpx itself raises, not a hand-built stand-in.

    Constructing one with a short message would test nothing: the whole risk is
    that raise_for_status puts the full request URL -- credentials and all --
    into the exception message, and only the real call reproduces that.
    """
    request = httpx.Request("GET", "https://example.test/odds?apiKey=SUPERSECRET")
    response = httpx.Response(429, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("raise_for_status did not raise on a 429")


class TestHealthTransitions:
    def test_a_fresh_provider_is_healthy(self):
        assert ProviderStats().health() is Health.HEALTHY

    def test_one_failure_is_degraded_not_offline(self):
        """A single blip must not take a feed out of the rotation."""
        st = ProviderStats()
        st.consecutive_failures = 1
        assert st.health() is Health.DEGRADED

    def test_three_consecutive_failures_is_offline(self):
        st = ProviderStats()
        st.consecutive_failures = 3
        assert st.health() is Health.OFFLINE

    def test_rate_limited_outranks_failure_count(self):
        """Reachable and answering, just out of quota -- not the same as down."""
        st = ProviderStats()
        st.consecutive_failures = 5
        st.rate_limited_until = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert st.health() is Health.RATE_LIMITED

    def test_a_lapsed_rate_limit_stops_applying(self):
        st = ProviderStats()
        st.rate_limited_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert st.health() is Health.HEALTHY

    def test_error_rate_is_windowed_not_lifetime(self):
        """A feed that failed all morning and has been clean since reads clean.

        A lifetime ratio would keep it marked bad for as long as the process
        lives, which is the opposite of what an operational readout is for.
        """
        st = ProviderStats()
        for _ in range(40):
            st.outcomes.append(False)
        assert st.error_rate == 1.0
        for _ in range(40):
            st.outcomes.append(True)
        assert st.error_rate == 0.0
        assert st.health() is Health.HEALTHY


class TestTelemetryIsRecordedOnce:
    """Every adapter gets this without implementing any of it."""

    @pytest.mark.asyncio
    async def test_a_success_records_latency_and_clears_the_streak(self):
        src = _Stub(events=3)
        src.stats.consecutive_failures = 2
        events = await src.safe_fetch()
        await src.close()

        assert len(events) == 3
        assert src.stats.requests == 1
        assert src.stats.consecutive_failures == 0
        assert src.stats.last_success is not None
        assert src.stats.latency_p50_ms is not None
        assert src.health is Health.HEALTHY

    @pytest.mark.asyncio
    async def test_a_failure_is_isolated_and_counted(self):
        """One dead venue must not stop a scan, but it must be visible."""
        src = _Stub(fail=RuntimeError("boom"))
        events = await src.safe_fetch()
        await src.close()

        assert events == []
        assert src.stats.failures == 1
        assert src.stats.consecutive_failures == 1
        assert src.health is Health.DEGRADED

    @pytest.mark.asyncio
    async def test_a_429_marks_rate_limited_rather_than_failed(self):
        src = _Stub(fail=_rate_limited())
        await src.safe_fetch()
        await src.close()
        assert src.health is Health.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_three_failures_take_it_offline(self):
        src = _Stub(fail=RuntimeError("boom"))
        for _ in range(3):
            await src.safe_fetch()
        await src.close()
        assert src.health is Health.OFFLINE

    @pytest.mark.asyncio
    async def test_a_credential_never_reaches_the_stored_error(self):
        """httpx puts the full URL in the message of every HTTPStatusError, and
        this string is persisted to SQLite and served by /api/analytics."""
        src = _Stub(fail=_rate_limited())
        await src.safe_fetch()
        await src.close()

        assert src.stats.last_error is not None
        assert "SUPERSECRET" not in src.stats.last_error
        assert "apiKey=***" in src.stats.last_error


class TestRedaction:
    @pytest.mark.parametrize(
        "raw",
        [
            "GET https://x.test/v4?apiKey=abc123&regions=us",
            "token=abc123",
            "https://x.test?api_key=abc123",
        ],
    )
    def test_secrets_are_masked(self, raw):
        assert "abc123" not in redact(raw)
