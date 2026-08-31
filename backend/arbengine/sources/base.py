"""Abstract source interface (Part II s1.2 / s3).

A Source turns one venue's API into canonical `Event` objects. Swapping a source
must never require touching the detector, so everything venue-specific --
pagination, price units, fee models, URL construction -- stops here.
"""

from __future__ import annotations

import re
import statistics
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Event


class SourceError(RuntimeError):
    """Raised when a venue cannot be reached or returns something unusable."""


#: Query parameters whose value must never reach a log line, the scan telemetry
#: or the database. httpx puts the full request URL into the message of every
#: HTTPStatusError it raises, so any credential passed in a query string travels
#: with the exception -- and `safe_fetch` stringifies that into `last_error`,
#: which `ScanStats.errors` persists and /api/analytics serves back out.
_SECRET_PARAMS = ("apikey", "api_key", "key", "token", "secret", "password")

#: How long a 429 keeps a provider in RATE_LIMITED before it is retried.
_RATE_LIMIT_COOLDOWN_SECONDS = 60.0

_SECRET_RE = re.compile(
    r"(?i)\b(" + "|".join(_SECRET_PARAMS) + r")=([^&\s'\"]+)"
)


def redact(text: str) -> str:
    """Mask credentials that appear as query parameters in `text`."""
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", text)


def _is_retryable(exc: BaseException) -> bool:
    """Only retry what a retry could plausibly fix.

    Retrying every HTTPStatusError meant three attempts, with backoff, against
    a 401 or a 404 -- answers that will not change however many times you ask,
    and on a metered feed three times the quota to learn the same thing. A 429
    is retryable because the whole point of backing off is to be asked later.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


class Health(str, Enum):
    """How much of what a provider says can currently be relied on.

    A boolean cannot express the state that matters most. A feed answering
    slowly, or answering but rate-limited into partial coverage, is neither
    healthy nor offline -- and the difference decides whether you widen the poll
    interval or stop trusting the prices altogether.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    OFFLINE = "offline"


#: Consecutive failures before a provider is called offline rather than
#: degraded. One failure is a blip; three in a row is a feed that is down.
_OFFLINE_AFTER = 3
#: Rolling window for the error-rate and latency figures.
_WINDOW = 40


@dataclass
class ProviderStats:
    """Rolling telemetry for one provider.

    Bounded on purpose: this is an operational readout, not an audit log. The
    scan tape in SQLite is the durable record, and keeping every latency sample
    here would grow without limit in a process designed to run for weeks.
    """

    requests: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: Optional[str] = None
    #: Recent request durations in milliseconds, newest last.
    latencies_ms: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))
    #: Recent outcomes, True for success. Drives the windowed error rate.
    outcomes: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))
    rate_limited_until: Optional[datetime] = None

    @property
    def latency_p50_ms(self) -> Optional[float]:
        if not self.latencies_ms:
            return None
        return statistics.median(self.latencies_ms)

    @property
    def latency_p95_ms(self) -> Optional[float]:
        """The figure that sets scan time: a cycle waits on its slowest feed."""
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        idx = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
        return ordered[idx]

    @property
    def error_rate(self) -> float:
        """Windowed rather than lifetime.

        A feed that failed all morning and has answered cleanly since should
        read as fine now -- a lifetime ratio would keep it marked bad for as
        long as the process lives.
        """
        if not self.outcomes:
            return 0.0
        return sum(1 for ok in self.outcomes if not ok) / len(self.outcomes)

    def health(self, now: Optional[datetime] = None) -> "Health":
        now = now or datetime.now(timezone.utc)
        if self.rate_limited_until is not None and self.rate_limited_until > now:
            return Health.RATE_LIMITED
        if self.consecutive_failures >= _OFFLINE_AFTER:
            return Health.OFFLINE
        if self.consecutive_failures > 0 or self.error_rate > 0.2:
            return Health.DEGRADED
        return Health.HEALTHY


class Source(ABC):
    """Base class for a venue adapter."""

    name: str = "source"
    #: Human-readable venue label for the UI.
    label: str = "Source"

    def __init__(self, client: Optional[httpx.AsyncClient] = None, timeout: float = 20.0):
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "BetsWin/1.0 (+arbitrage scanner)", "Accept": "application/json"},
            follow_redirects=True,
        )
        self.last_error: Optional[str] = None
        self.last_fetch_count: int = 0
        self.healthy: bool = True
        self.stats = ProviderStats()

    @property
    def health(self) -> Health:
        return self.stats.health()

    # ------------------------------------------------------------------ http

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.6, min=0.6, max=8),
        reraise=True,
    )
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self._client.get(url, params=params)
        if resp.status_code == 429:
            # Let the retry decorator's backoff do the waiting; sleeping here as
            # well doubled the delay on every rate-limited call.
            logger.warning(f"{self.name}: rate limited, backing off")
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.6, min=0.6, max=8),
        reraise=True,
    )
    async def _post(self, url: str, payload: Any) -> Any:
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------ interface

    @abstractmethod
    async def fetch_events(self) -> list[Event]:
        """Return canonical events with every quote this venue offers."""

    async def enrich(self, events: list[Event]) -> list[Event]:
        """Optionally deepen a shortlist of events with full order books.

        Called after detection has narrowed the field, so the expensive
        per-market book calls are spent only on genuine candidates.
        """
        return events

    async def close(self) -> None:
        if self._own_client:
            await self._client.aclose()

    # ------------------------------------------------------------- helpers

    async def safe_fetch(self) -> list[Event]:
        """fetch_events with failure isolation -- one dead venue must not stop a scan.

        Also the single place provider telemetry is recorded, so every adapter
        gets latency, error rate and health without implementing any of it.
        """
        started = time.monotonic()
        now = datetime.now(timezone.utc)
        self.stats.requests += 1
        try:
            events = await self.fetch_events()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, logged
            self.healthy = False
            self.stats.failures += 1
            self.stats.consecutive_failures += 1
            self.stats.last_failure = now
            self.stats.outcomes.append(False)
            self.stats.latencies_ms.append((time.monotonic() - started) * 1000.0)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                # Held for one cooldown. The provider is reachable and
                # answering, so calling it offline would be wrong -- it simply
                # has nothing left to give us this cycle.
                self.stats.rate_limited_until = now + timedelta(
                    seconds=_RATE_LIMIT_COOLDOWN_SECONDS
                )
            # Redacted before it is stored: this string ends up in
            # ScanStats.errors, which is written to SQLite and served by
            # /api/analytics.
            self.last_error = redact(f"{type(exc).__name__}: {exc}")
            self.stats.last_error = self.last_error
            logger.error(f"{self.name}: fetch failed -- {self.last_error}")
            return []

        self.healthy = True
        self.last_error = None
        self.last_fetch_count = len(events)
        self.stats.consecutive_failures = 0
        self.stats.last_success = now
        self.stats.last_error = None
        self.stats.outcomes.append(True)
        self.stats.latencies_ms.append((time.monotonic() - started) * 1000.0)
        return events
