"""Abstract source interface (Part II s1.2 / s3).

A Source turns one venue's API into canonical `Event` objects. Swapping a source
must never require touching the detector, so everything venue-specific --
pagination, price units, fee models, URL construction -- stops here.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Event


class SourceError(RuntimeError):
    """Raised when a venue cannot be reached or returns something unusable."""


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
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.6, min=0.6, max=8),
        reraise=True,
    )
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self._client.get(url, params=params)
        if resp.status_code == 429:
            logger.warning(f"{self.name}: rate limited, backing off")
            await asyncio.sleep(3.0)
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
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
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.error(f"{self.name}: fetch failed -- {self.last_error}")
            return []
