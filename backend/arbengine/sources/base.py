"""Abstract source interface (Part II s1.2 / s3).

A Source turns one venue's API into canonical `Event` objects. Swapping a source
must never require touching the detector, so everything venue-specific --
pagination, price units, fee models, URL construction -- stops here.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
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
        """fetch_events with failure isolation -- one dead venue must not stop a scan."""
        try:
            events = await self.fetch_events()
            self.healthy = True
            self.last_error = None
            self.last_fetch_count = len(events)
            return events
        except Exception as exc:  # noqa: BLE001 - deliberately broad, logged
            self.healthy = False
            # Redacted before it is stored: this string ends up in
            # ScanStats.errors, which is written to SQLite and served by
            # /api/analytics.
            self.last_error = redact(f"{type(exc).__name__}: {exc}")
            logger.error(f"{self.name}: fetch failed -- {self.last_error}")
            return []
