"""The Odds API adapter -- US sportsbooks (Part II s5).

Optional: without ODDS_API_KEY the source reports itself disabled and the scanner
skips it. When enabled it supplies the classic cross-bookmaker arbitrage of
Part I s3-s4 alongside the prediction-market feeds, and gives the cross-venue
detector a sportsbook reference price for prediction-market lines.

Quota is metered per request, so responses are cached for a configurable TTL and
all sports are fetched concurrently (Part II s17.2).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from ..config import settings
from ..fees import fee_model_for
from ..models import Event, Market, Outcome, Quote, Side
from ..odds import decimal_to_prob
from .base import Source

_CACHE_TTL_SECONDS = 60.0


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class OddsAPISource(Source):
    name = "sportsbook"
    label = "US Sportsbooks"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = settings.odds_api_url.rstrip("/")
        self._fees = fee_model_for("sportsbook")
        self.quota_remaining: Optional[int] = None
        self.quota_used: Optional[int] = None
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    @property
    def enabled(self) -> bool:
        return settings.odds_api_enabled

    async def fetch_events(self) -> list[Event]:
        if not self.enabled:
            return []
        sports = settings.odds_api_sport_list
        results = await asyncio.gather(
            *(self._fetch_sport(s) for s in sports), return_exceptions=True
        )
        events: list[Event] = []
        for sport, res in zip(sports, results):
            if isinstance(res, BaseException):
                logger.warning(f"sportsbook: {sport} failed -- {res}")
                continue
            for raw in res:
                ev = self._build_event(raw, sport)
                if ev is not None:
                    events.append(ev)
        logger.info(f"sportsbook: {len(events)} events across {len(sports)} sports")
        return events

    async def _fetch_sport(self, sport: str) -> list[dict[str, Any]]:
        cached = self._cache.get(sport)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        resp = await self._client.get(
            f"{self.base}/sports/{sport}/odds",
            params={
                "apiKey": settings.odds_api_key,
                "regions": settings.odds_api_regions,
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )
        # Track remaining credits so a runaway loop is visible before it bites.
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        if remaining is not None:
            try:
                self.quota_remaining = int(remaining)
            except ValueError:
                pass
        if used is not None:
            try:
                self.quota_used = int(used)
            except ValueError:
                pass
        resp.raise_for_status()
        data = resp.json()
        data = data if isinstance(data, list) else []
        self._cache[sport] = (time.monotonic(), data)
        return data

    def _build_event(self, raw: dict[str, Any], sport: str) -> Optional[Event]:
        by_outcome: dict[str, list[Quote]] = {}
        event_id = str(raw.get("id") or "")
        commence = _parse_dt(raw.get("commence_time"))

        for book in raw.get("bookmakers") or []:
            book_key = str(book.get("key") or "")
            updated = _parse_dt(book.get("last_update")) or datetime.now(timezone.utc)
            for mkt in book.get("markets") or []:
                if mkt.get("key") != "h2h":
                    continue
                for oc in mkt.get("outcomes") or []:
                    name = str(oc.get("name") or "")
                    try:
                        d = float(oc.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if d <= 1.0:
                        continue
                    price = decimal_to_prob(d)
                    by_outcome.setdefault(name, []).append(
                        Quote(
                            venue=self.name,
                            market_id=f"{event_id}:{book_key}:{name}",
                            ticker=book_key,
                            outcome=name,
                            side=Side.BACK,
                            price=price,
                            effective_price=price,
                            size_available=0.0,
                            last_update=updated,
                            url=None,
                        )
                    )

        if len(by_outcome) < 2:
            return None

        outcomes = tuple(
            Outcome(name=n, quotes=tuple(qs)) for n, qs in by_outcome.items()
        )
        home = raw.get("home_team")
        away = raw.get("away_team")
        return Event(
            id=f"sportsbook:{event_id}",
            venue=self.name,
            title=f"{home} v {away}" if home and away else str(raw.get("sport_title") or sport),
            category="sports",
            league=str(raw.get("sport_title") or sport),
            home=home,
            away=away,
            commence_time=commence,
            close_time=commence,
            mutually_exclusive=True,
            url=None,
            markets=(Market(key="h2h", outcomes=outcomes),),
        )
