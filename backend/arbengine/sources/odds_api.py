"""The Odds API adapter -- sportsbooks worldwide (Part II s5).

Optional: without ODDS_API_KEY the source reports itself disabled and the scanner
skips it. When enabled it supplies the classic cross-bookmaker arbitrage of
Part I s3-s4 alongside the prediction-market feeds, and gives the cross-venue
detector a sportsbook reference price for prediction-market lines.

Three things decide how many opportunities this source can find at all:

  REGIONS.  An arbitrage exists when two books disagree. Books in four regions
            disagree far more often than books in one, and regions are the
            cheapest coverage available -- a UK book and a US book pricing the
            same NBA game is the most productive pairing here.
  MARKETS.  Handicaps and totals are two-way markets that arbitrage exactly like
            a moneyline, and there are far more of them, because every book sets
            its own line rather than quoting a common one.
  SPORTS.   Which competitions are in season changes weekly, so the list is
            discovered rather than hard-coded.

Quota is metered as `len(markets) * len(regions)` credits PER SPORT PER REQUEST,
which is why all three of those levers are bounded by configuration, and why the
in-season discovery below matters: fetching odds for a sport whose season ended
costs exactly as much as fetching one being played.

One thing this feed cannot give you: depth. It is an odds aggregator, so there
is no order book and no published stake limit, and the honest reading of a
sportsbook quote is that its capacity is UNKNOWN. That is not the same as zero,
and it is certainly not the same as unlimited -- so the size of a sportsbook leg
comes from `settings.sportsbook_assumed_stake_usd`, an operator-owned risk limit,
rather than from anything the API said.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger

from ..config import settings
from ..fees import fee_model_for
from ..models import Event, Market, Outcome, Quote, Side
from ..odds import decimal_to_prob
from .base import Source, redact

_CACHE_TTL_SECONDS = 60.0
#: The in-season list changes on the timescale of a season, not a scan.
_SPORTS_TTL_SECONDS = 3600.0


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _fmt_point(point: float) -> str:
    """Render a line for use in a market key.

    Trailing zeros are stripped so 2.5 and 2.50 produce the same key. Two books
    quoting the same line must land in the same market or they are never
    compared, and a bare float repr is not a stable identifier.
    """
    text = f"{point:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


class OddsAPISource(Source):
    name = "sportsbook"
    label = "Sportsbooks"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = settings.odds_api_url.rstrip("/")
        self._fees = fee_model_for("sportsbook")
        self.quota_remaining: Optional[int] = None
        self.quota_used: Optional[int] = None
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._sports_cache: Optional[tuple[float, list[str]]] = None

    @property
    def enabled(self) -> bool:
        return settings.odds_api_enabled

    # ------------------------------------------------------------ discovery

    async def _in_season_sports(self) -> list[str]:
        """Sport keys worth spending credits on this cycle.

        `/sports` is free -- it does not decrement the quota -- so asking it
        which competitions are actually running is strictly cheaper than
        fetching odds for a league whose season ended in June and paying full
        price for an empty list.

        Restricted to athletic competition. The same books price politics and
        entertainment novelties, but those settle on bespoke house rules that
        differ between books, and two legs that settle differently are not a
        hedge. Outright/futures markets are excluded too: they resolve months
        out, which is the opposite of what the short-dated window wants.
        """
        cached = self._sports_cache
        if cached and (time.monotonic() - cached[0]) < _SPORTS_TTL_SECONDS:
            return cached[1]

        resp = await self._client.get(
            f"{self.base}/sports", params={"apiKey": settings.odds_api_key}
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload if isinstance(payload, list) else []

        groups = settings.odds_api_group_set
        keys = [
            str(r.get("key"))
            for r in rows
            if r.get("active")
            and not r.get("has_outrights")
            and str(r.get("group") or "") in groups
            and r.get("key")
        ]
        keys = keys[: max(1, settings.odds_api_max_sports)]
        self._sports_cache = (time.monotonic(), keys)
        logger.info(f"sportsbook: {len(keys)} sports in season -- {', '.join(keys)}")
        return keys

    async def fetch_events(self) -> list[Event]:
        if not self.enabled:
            return []

        sports = settings.odds_api_sport_list
        if not sports:
            try:
                sports = await self._in_season_sports()
            except Exception as exc:  # noqa: BLE001 - discovery must not kill a scan
                logger.warning(
                    f"sportsbook: sport discovery failed -- {redact(str(exc))}"
                )
                return []
        if not sports:
            return []

        results = await asyncio.gather(
            *(self._fetch_sport(s) for s in sports), return_exceptions=True
        )
        events: list[Event] = []
        for sport, res in zip(sports, results):
            if isinstance(res, BaseException):
                # The key rides along in the URL inside httpx's exception
                # message; never log one un-redacted.
                logger.warning(f"sportsbook: {sport} failed -- {redact(str(res))}")
                continue
            for raw in res:
                events.extend(self._build_events(raw, sport))

        markets = sum(len(e.markets) for e in events)
        logger.info(
            f"sportsbook: {len(events)} events / {markets} markets "
            f"across {len(sports)} sports"
        )
        return events

    async def _fetch_sport(self, sport: str) -> list[dict[str, Any]]:
        cached = self._cache.get(sport)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        params: dict[str, str] = {
            "apiKey": settings.odds_api_key,
            "regions": settings.odds_api_regions,
            "markets": ",".join(settings.odds_api_market_list),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        # Ask the API for the window rather than filtering afterwards. It costs
        # the same either way, but a smaller response is faster to parse and
        # cannot smuggle a long-dated fixture past a later filter.
        if settings.max_hours_to_start > 0:
            until = datetime.now(timezone.utc) + timedelta(
                hours=settings.max_hours_to_start
            )
            params["commenceTimeTo"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")

        resp = await self._client.get(f"{self.base}/sports/{sport}/odds", params=params)
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

    # ------------------------------------------------------------- building

    @staticmethod
    def _market_key(
        market_key: str, outcomes: list[dict[str, Any]], home_team: Optional[str]
    ) -> Optional[str]:
        """The key two books must agree on before their prices are comparable.

        Moneylines are comparable outright. Handicaps and totals are NOT: a book
        offering Over 44.5 and a book offering Over 45.5 are pricing different
        questions, and staking both produces a middle -- which can win twice but
        can also lose twice, so it is a position, not an arbitrage.

        Totals key on their shared point. Handicaps key on the HOME side's
        SIGNED point, deliberately: keying on the absolute value would collapse
        a home -3.5 and a home +3.5 into one market, and backing both sides of
        that is not a hedge, it is the same directional bet twice.
        """
        if market_key == "h2h":
            return "h2h"

        if market_key == "totals":
            points = {o.get("point") for o in outcomes}
            if len(points) != 1:
                return None  # over and under quoted at different lines
            point = points.pop()
            if point is None:
                return None
            try:
                return f"totals_{_fmt_point(float(point))}"
            except (TypeError, ValueError):
                return None

        if market_key == "spreads":
            if not home_team:
                return None
            for o in outcomes:
                if str(o.get("name") or "") == home_team and o.get("point") is not None:
                    try:
                        return f"spreads_{_fmt_point(float(o['point']))}"
                    except (TypeError, ValueError):
                        return None
            return None

        return None

    def _build_events(self, raw: dict[str, Any], sport: str) -> list[Event]:
        """One Event per fixture, carrying every market both sides priced.

        The moneyline, each totals line and each handicap line become separate
        markets, because each is a separate question. The detector then looks
        for a crossed book within each of them independently.
        """
        event_id = str(raw.get("id") or "")
        commence = _parse_dt(raw.get("commence_time"))
        home = raw.get("home_team")
        away = raw.get("away_team")

        # market key -> outcome name -> quotes from every book
        books: dict[str, dict[str, list[Quote]]] = {}

        for book in raw.get("bookmakers") or []:
            book_key = str(book.get("key") or "")
            updated = _parse_dt(book.get("last_update")) or datetime.now(timezone.utc)

            for mkt in book.get("markets") or []:
                raw_key = str(mkt.get("key") or "")
                outcomes = [
                    o for o in (mkt.get("outcomes") or []) if isinstance(o, dict)
                ]
                if len(outcomes) < 2:
                    continue
                key = self._market_key(raw_key, outcomes, home)
                if key is None:
                    continue

                for oc in outcomes:
                    name = str(oc.get("name") or "")
                    if not name:
                        continue
                    try:
                        d = float(oc.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if d <= 1.0:
                        continue
                    price = decimal_to_prob(d)
                    # The feed carries no book and no stake limit, so capacity
                    # here is UNKNOWN, not zero. Reporting 0 used to slip past
                    # the sizer's depth cap entirely and size every sportsbook
                    # arb as though depth were unlimited. State the assumption
                    # instead: `sportsbook_assumed_stake_usd` is the operator's
                    # own per-leg limit, converted to contracts at this price.
                    assumed_notional = max(settings.sportsbook_assumed_stake_usd, 0.0)
                    size_available = (assumed_notional / price) if price > 0 else 0.0
                    books.setdefault(key, {}).setdefault(name, []).append(
                        Quote(
                            venue=self.name,
                            market_id=f"{event_id}:{book_key}:{key}:{name}",
                            ticker=book_key,
                            outcome=name,
                            side=Side.BACK,
                            price=price,
                            effective_price=price,
                            size_available=size_available,
                            last_update=updated,
                            url=None,
                        )
                    )

        markets = tuple(
            Market(
                key=key,
                outcomes=tuple(
                    Outcome(name=n, quotes=tuple(qs)) for n, qs in by_outcome.items()
                ),
            )
            # A market with only one side priced cannot be arbed, and a
            # three-way h2h (soccer, with the draw) needs all three.
            for key, by_outcome in books.items()
            if len(by_outcome) >= 2
        )
        if not markets:
            return []

        title = (
            f"{home} v {away}"
            if home and away
            else str(raw.get("sport_title") or sport)
        )
        return [
            Event(
                id=f"sportsbook:{event_id}",
                venue=self.name,
                title=title,
                category="sports",
                league=str(raw.get("sport_title") or sport),
                home=home,
                away=away,
                commence_time=commence,
                close_time=commence,
                mutually_exclusive=True,
                url=None,
                markets=markets,
            )
        ]
