"""Betfair Exchange adapter -- the second venue in the UK/EU zone.

Betfair is the deepest exchange book in the zone and the natural counterparty to
Smarkets: same currency, same settlement, same rulebook family, so a pair
between them is placeable by one person from one country with two ordinary
accounts. That is the whole point of `venues.Zone.UK_EXCHANGE`.

Unlike Smarkets, Betfair publishes nothing without credentials. This source
stays dark unless an application key and a session token are configured, exactly
as the sportsbook source does without an API key -- a venue that cannot be read
must never silently degrade into a venue that appears to have no opportunities.

Price mapping
-------------

Betfair quotes decimal odds; this engine works in contracts that pay 1. The
translation is Part I s2.2 plus the lay identity:

    back at d      -> buy YES at price 1/d
    lay at d_lay   -> buy NO  at price 1 - 1/d_lay

`availableToBack` is what you can back at right now, `availableToLay` what you
can lay at. Sizes are stake in the account currency, so the payout-denominated
size of a level is `size * price`.

Commission is charged on net winnings, so `CommissionFeeModel` -- not a spread
-- converts these into all-in costs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from loguru import logger

from ..config import settings
from ..fees import fee_model_for
from ..models import DepthLevel, Event, Market, Outcome, Quote, Side
from ..normalise import classify_category
from .base import Source, SourceError

_RPC = "SportsAPING/v1.0/"

#: Three-way match odds and outright winner markets are the exhaustive ones.
_MARKET_TYPES = ("MATCH_ODDS", "WINNER")
_MAX_RUNNERS = 12
#: listMarketBook is rate-limited by weight; 25 markets per call is the
#: documented ceiling for EX_BEST_OFFERS.
_BOOK_BATCH = 25


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _levels(rows: Any, invert: bool) -> list[DepthLevel]:
    """Decimal-odds ladder -> contract-price depth, cheapest first."""
    out: list[DepthLevel] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            odds = float(row.get("price", 0))
            stake = float(row.get("size", 0))
        except (TypeError, ValueError):
            continue
        if odds <= 1.0 or stake <= 0:
            continue
        implied = 1.0 / odds
        price = 1.0 - implied if invert else implied
        if not (0.0 < price < 1.0):
            continue
        # Stake is in currency; the payout-denominated size is stake * odds.
        out.append(DepthLevel(price=round(price, 4), size=round(stake * odds, 2)))
    out.sort(key=lambda d: d.price)
    return out


class BetfairSource(Source):
    name = "betfair"
    label = "Betfair Exchange"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = settings.betfair_api_url
        self.app_key = settings.betfair_app_key
        self._session_token = settings.betfair_session_token
        self._fees = fee_model_for("betfair")

    # ----------------------------------------------------------------- auth

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Application": self.app_key,
            "X-Authentication": self._session_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _ensure_session(self) -> None:
        """Interactive login, used only when no session token was supplied.

        Betfair's non-interactive endpoint needs a client certificate, which is
        deployment configuration rather than something this adapter can invent.
        A supplied `BETFAIR_SESSION_TOKEN` skips this path entirely.
        """
        if self._session_token:
            return
        if not (settings.betfair_username and settings.betfair_password):
            raise SourceError(
                "betfair: no session token and no username/password to obtain one"
            )
        resp = await self._client.post(
            settings.betfair_login_url,
            data={
                "username": settings.betfair_username,
                "password": settings.betfair_password,
            },
            headers={
                "X-Application": self.app_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "SUCCESS":
            raise SourceError(f"betfair: login rejected ({body.get('error')})")
        self._session_token = str(body.get("token") or "")
        if not self._session_token:
            raise SourceError("betfair: login returned no session token")
        logger.info("betfair: session established")

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        await self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "method": f"{_RPC}{method}",
            "params": params,
            "id": 1,
        }
        try:
            resp = await self._client.post(self.base, json=payload, headers=self._headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                # A stale token is the common failure; drop it so the next
                # cycle logs in again rather than failing forever.
                self._session_token = ""
            raise
        body = resp.json()
        if isinstance(body, dict) and body.get("error"):
            raise SourceError(f"betfair: {method} -- {body['error']}")
        return (body or {}).get("result")

    # ------------------------------------------------------------- fetching

    async def fetch_events(self) -> list[Event]:
        if not settings.betfair_enabled:
            return []

        catalogue = await self._list_catalogue()
        if not catalogue:
            return []

        market_ids = [str(m["marketId"]) for m in catalogue if m.get("marketId")]
        books = await self._list_books(market_ids)

        events: list[Event] = []
        for entry in catalogue:
            built = self._build_event(entry, books.get(str(entry.get("marketId"))))
            if built is not None:
                events.append(built)

        logger.info(f"betfair: {len(catalogue)} markets -> {len(events)} tradeable")
        return events

    async def _list_catalogue(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        result = await self._rpc(
            "listMarketCatalogue",
            {
                "filter": {
                    "eventTypeIds": settings.betfair_event_type_id_list,
                    "marketTypeCodes": list(_MARKET_TYPES),
                    "marketStartTime": {
                        "from": now.isoformat(),
                        "to": (now + timedelta(days=30)).isoformat(),
                    },
                },
                "marketProjection": [
                    "EVENT_TYPE",
                    "EVENT",
                    "RUNNER_DESCRIPTION",
                    "MARKET_START_TIME",
                    "MARKET_DESCRIPTION",
                ],
                "sort": "MAXIMUM_TRADED",
                "maxResults": settings.betfair_max_markets,
            },
        )
        return result or []

    async def _list_books(self, market_ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(market_ids), _BOOK_BATCH):
            batch = market_ids[i : i + _BOOK_BATCH]
            try:
                result = await self._rpc(
                    "listMarketBook",
                    {
                        "marketIds": batch,
                        "priceProjection": {
                            "priceData": ["EX_BEST_OFFERS"],
                            "exBestOffersOverrides": {"bestPricesDepth": 5},
                            "virtualise": True,
                        },
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"betfair: listMarketBook batch failed -- {exc}")
                continue
            for book in result or []:
                out[str(book.get("marketId"))] = book
        return out

    # ----------------------------------------------------------- structuring

    def _build_event(
        self, entry: dict[str, Any], book: Optional[dict[str, Any]]
    ) -> Optional[Event]:
        if not book or str(book.get("status")) != "OPEN" or book.get("inplay"):
            return None

        runners_meta = {
            int(r["selectionId"]): str(r.get("runnerName") or "")
            for r in entry.get("runners") or []
            if r.get("selectionId") is not None
        }
        runner_books = [
            r
            for r in book.get("runners") or []
            if str(r.get("status")) == "ACTIVE"
            and int(r.get("selectionId", -1)) in runners_meta
        ]
        if not 1 < len(runner_books) <= _MAX_RUNNERS:
            return None

        market_id = str(entry["marketId"])
        event_meta = entry.get("event") or {}
        title = str(event_meta.get("name") or entry.get("marketName") or "").strip()
        if not title:
            return None
        url = f"https://www.betfair.com/exchange/plus/market/{market_id}"
        now = datetime.now(timezone.utc)

        markets: list[Market] = []
        liquidity = 0.0
        for rb in runner_books:
            ex = rb.get("ex") or {}
            yes_levels = _levels(ex.get("availableToBack"), invert=False)
            no_levels = _levels(ex.get("availableToLay"), invert=True)
            if not yes_levels or not no_levels:
                return None  # a one-sided runner breaks the partition
            name = runners_meta[int(rb["selectionId"])].strip()
            if not name:
                return None

            yes_q = self._quote(market_id, rb, name, Side.YES, yes_levels, now, url)
            no_q = self._quote(
                market_id, rb, f"Not {name}", Side.NO, no_levels, now, url
            )
            liquidity += yes_q.notional_available()
            markets.append(
                Market(
                    key="binary",
                    outcomes=(
                        Outcome(name=yes_q.outcome, quotes=(yes_q,)),
                        Outcome(name=no_q.outcome, quotes=(no_q,)),
                    ),
                )
            )

        if liquidity < settings.min_market_liquidity_usd:
            return None

        return Event(
            id=f"betfair:{market_id}",
            venue=self.name,
            title=title,
            # Betfair's own event-type id is a better category signal than the
            # words in a fixture name, which rarely say what sport it is.
            category=(
                "politics"
                if str((entry.get("eventType") or {}).get("id") or "") == "2378961"
                else classify_category(title, str(entry.get("marketName") or ""))
            ),
            currency=str(book.get("currency") or "GBP"),
            commence_time=_parse_dt(entry.get("marketStartTime")),
            close_time=_parse_dt(entry.get("marketStartTime")),
            # Betfair's MATCH_ODDS and WINNER markets are exhaustive by
            # construction: exactly one runner wins.
            mutually_exclusive=len(markets) > 1,
            volume_usd=float(book.get("totalMatched") or 0.0),
            liquidity_usd=round(liquidity, 2),
            url=url,
            markets=tuple(markets),
        )

    def _quote(
        self,
        market_id: str,
        runner: dict[str, Any],
        outcome: str,
        side: Side,
        levels: list[DepthLevel],
        updated: datetime,
        url: str,
    ) -> Quote:
        best = levels[0].price
        total = sum(l.size for l in levels)
        selection = str(runner.get("selectionId"))
        return Quote(
            venue=self.name,
            market_id=f"{market_id}:{selection}:{side.value}",
            ticker=f"{market_id}:{selection}",
            outcome=outcome,
            side=side,
            price=best,
            effective_price=self._fees.effective_price(best, max(total, 1.0)),
            size_available=round(total, 2),
            depth=tuple(levels),
            last_update=updated,
            url=url,
        )

    # ------------------------------------------------------------- enrichment

    async def enrich(self, events: list[Event]) -> list[Event]:
        """Re-read the shortlist's books immediately before sizing."""
        ids = [ev.id.split(":", 1)[1] for ev in events if ev.id.startswith("betfair:")]
        if not ids:
            return events
        books = await self._list_books(ids[:_BOOK_BATCH])
        if not books:
            return events

        out: list[Event] = []
        for ev in events:
            if not ev.id.startswith("betfair:"):
                out.append(ev)
                continue
            book = books.get(ev.id.split(":", 1)[1])
            out.append(self._refresh(ev, book) if book else ev)
        return out

    def _refresh(self, ev: Event, book: dict[str, Any]) -> Event:
        by_selection = {
            f"{book.get('marketId')}:{r.get('selectionId')}": r
            for r in book.get("runners") or []
        }
        now = datetime.now(timezone.utc)
        markets: list[Market] = []
        for mk in ev.markets:
            outcomes: list[Outcome] = []
            for oc in mk.outcomes:
                fresh: list[Quote] = []
                for q in oc.quotes:
                    runner = by_selection.get(q.ticker or "")
                    ex = (runner or {}).get("ex") or {}
                    levels = (
                        _levels(ex.get("availableToBack"), invert=False)
                        if q.side is Side.YES
                        else _levels(ex.get("availableToLay"), invert=True)
                    )
                    if not levels:
                        fresh.append(q)
                        continue
                    best = levels[0].price
                    total = sum(l.size for l in levels)
                    fresh.append(
                        q.model_copy(
                            update={
                                "price": best,
                                "effective_price": self._fees.effective_price(
                                    best, max(total, 1.0)
                                ),
                                "size_available": round(total, 2),
                                "depth": tuple(levels),
                                "last_update": now,
                            }
                        )
                    )
                outcomes.append(Outcome(name=oc.name, quotes=tuple(fresh)))
            markets.append(Market(key=mk.key, outcomes=tuple(outcomes)))
        return ev.model_copy(update={"markets": tuple(markets)})
