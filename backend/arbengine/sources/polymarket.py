"""Polymarket adapter.

Two public APIs, no credentials required for market data:

  * Gamma  (gamma-api.polymarket.com/markets) -- market catalogue with
    `bestBid` / `bestAsk`, the CLOB token ids, and the parent event grouping.
  * CLOB   (clob.polymarket.com/books)        -- full order-book depth for a
    batch of token ids.

Prices are already in probability space: a token trading at 0.42 costs $0.42 and
settles at $1.00, so decimal odds are 1/0.42 (Part I s2.2).

A note on the CLOB payload: `asks` arrive sorted from worst to best (0.999 first)
and `bids` from worst to best as well, so both sides are re-sorted here rather
than trusting position. Getting this backwards would invent arbitrage that does
not exist -- exactly the silent-mismatch failure warned about in Part II s6.2.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from loguru import logger

from ..config import settings
from ..fees import fee_model_for
from ..models import DepthLevel, Event, Market, Outcome, Quote, Side
from ..normalise import classify_category
from .base import Source

_MAX_BOOK_BATCH = 60
_GAMMA_MAX_LIMIT = 100


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _as_list(value: Any) -> list[Any]:
    """Gamma returns several array fields as JSON-encoded strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _category_for(market: dict[str, Any]) -> str:
    """Classify from the question text.

    Gamma's nested event object carries no category or tags, and slicing its
    ticker produces noise rather than a usable filter vocabulary.
    """
    events = market.get("events") or []
    title = (events[0].get("title") if events else None) or market.get("question") or ""
    return classify_category(str(title))


class PolymarketSource(Source):
    name = "polymarket"
    label = "Polymarket"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.gamma = settings.polymarket_gamma_url.rstrip("/")
        self.clob = settings.polymarket_clob_url.rstrip("/")
        self._fees = fee_model_for("polymarket")

    # ------------------------------------------------------------- fetching

    async def fetch_events(self) -> list[Event]:
        raw = await self._fetch_markets()
        grouped = self._group_by_event(raw)
        events = [ev for ev in (self._build_event(g) for g in grouped) if ev is not None]
        logger.info(f"polymarket: {len(raw)} markets -> {len(events)} events")
        return events

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """Page through the active market catalogue, most-traded first.

        Gamma silently caps `limit` at 100 and ignores anything larger, so the
        page size is clamped here. Advancing the offset by the requested size
        rather than the served size would skip whole blocks of the catalogue.
        """
        out: list[dict[str, Any]] = []
        limit = min(settings.polymarket_page_limit, _GAMMA_MAX_LIMIT)
        offset = 0
        for _ in range(settings.polymarket_max_pages):
            batch = await self._get(
                f"{self.gamma}/markets",
                params={
                    "closed": "false",
                    "active": "true",
                    "archived": "false",
                    "limit": limit,
                    "offset": offset,
                    "order": "volumeNum",
                    "ascending": "false",
                },
            )
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            offset += len(batch)
            if len(batch) < limit:
                break
        return [m for m in out if self._is_tradeable(m)]

    def _is_tradeable(self, m: dict[str, Any]) -> bool:
        """Structural validity only.

        Deliberately no volume or liquidity test here. Those are applied to the
        EVENT after grouping, because dropping one thin outcome from a
        multi-outcome event silently destroys its exhaustiveness -- and a Dutch
        book computed over a partial outcome set leaves the missing outcome
        completely uncovered (Part I s5.2).
        """
        if not m.get("enableOrderBook") or not m.get("acceptingOrders"):
            return False
        if m.get("closed") or m.get("archived") or not m.get("active"):
            return False
        if len(_as_list(m.get("clobTokenIds"))) < 2:
            return False
        ask, bid = _as_float(m.get("bestAsk")), _as_float(m.get("bestBid"))
        return 0.0 < bid < 1.0 and 0.0 < ask < 1.0

    # ----------------------------------------------------------- structuring

    def _group_by_event(self, markets: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Group markets under their parent Gamma event.

        A standalone yes/no question is its own group. A "who will win" event is
        many binary markets sharing one parent, which is what makes the Dutch
        book detector (Part I s5.1) possible.
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in markets:
            evs = m.get("events") or []
            key = str(evs[0].get("id")) if evs and evs[0].get("id") else f"solo:{m.get('id')}"
            groups.setdefault(key, []).append(m)
        return list(groups.values())

    def _build_event(self, group: list[dict[str, Any]]) -> Optional[Event]:
        if not group:
            return None
        head = group[0]
        parents = head.get("events") or []
        parent = parents[0] if parents else {}

        event_id = str(parent.get("id") or head.get("id"))
        title = str(parent.get("title") or head.get("question") or "Untitled")
        slug = parent.get("slug") or head.get("slug") or ""

        markets: list[Market] = []
        volume = 0.0
        liquidity = 0.0
        close_time: Optional[datetime] = None

        for m in group:
            built = self._build_market(m)
            if built is None:
                continue
            markets.append(built)
            volume += _as_float(m.get("volumeNum"))
            liquidity += _as_float(m.get("liquidityNum"))
            end = _parse_dt(m.get("endDate"))
            if end and (close_time is None or end < close_time):
                close_time = end

        if not markets:
            return None

        # Liquidity is judged at the event level, after every outcome has been
        # collected, so the filter can never punch a hole in an outcome set.
        if (
            volume < settings.min_market_volume_usd
            and liquidity < settings.min_market_liquidity_usd
        ):
            return None

        # negRisk marks a Polymarket event whose outcomes are mutually exclusive
        # and collectively exhaustive -- the precondition for a Dutch book.
        mutually_exclusive = bool(head.get("negRisk")) and len(markets) > 1

        return Event(
            id=f"polymarket:{event_id}",
            venue=self.name,
            title=title,
            category=_category_for(head),
            close_time=close_time,
            mutually_exclusive=mutually_exclusive,
            volume_usd=volume,
            liquidity_usd=liquidity,
            url=f"https://polymarket.com/event/{slug}" if slug else None,
            markets=tuple(markets),
        )

    def _build_market(self, m: dict[str, Any]) -> Optional[Market]:
        """One Gamma market -> a binary market with YES and NO quotes.

        Gamma publishes `bestAsk`/`bestBid` for the YES token only. The NO ask is
        the complement of the YES bid: to buy NO you cross the spread against the
        best YES bid, so no_ask = 1 - yes_bid.
        """
        names = _as_list(m.get("outcomes")) or ["Yes", "No"]
        token_ids = _as_list(m.get("clobTokenIds"))
        if len(token_ids) < 2:
            return None

        yes_ask = _as_float(m.get("bestAsk"))
        yes_bid = _as_float(m.get("bestBid"))
        if not (0.0 < yes_ask < 1.0 and 0.0 < yes_bid < 1.0):
            return None
        no_ask = 1.0 - yes_bid

        market_id = str(m.get("id"))
        slug = m.get("slug") or ""
        url = f"https://polymarket.com/market/{slug}" if slug else None
        updated = _parse_dt(m.get("updatedAt")) or datetime.now(timezone.utc)
        # Liquidity is reported for the market as a whole; split it across the
        # two sides as a conservative first-pass size until the book is fetched.
        approx_size = max(_as_float(m.get("liquidityNum")) / 2.0, 0.0)

        # In a multi-outcome event every sub-market is its own yes/no question,
        # so a bare "Yes" is useless -- label the leg with the outcome it names
        # ("Democrat", "Chiefs") and fall back to the market question.
        label = str(m.get("groupItemTitle") or "").strip()
        yes_name = str(names[0]) if names else "Yes"
        no_name = str(names[1]) if len(names) > 1 else "No"
        if label:
            yes_name = label
            no_name = f"Not {label}"

        quotes = [
            self._quote(str(token_ids[0]), market_id, yes_name, Side.YES, yes_ask, approx_size, updated, url),
            self._quote(str(token_ids[1]), market_id, no_name, Side.NO, no_ask, approx_size, updated, url),
        ]
        return Market(
            key="binary",
            outcomes=(
                Outcome(name=yes_name, quotes=(quotes[0],)),
                Outcome(name=no_name, quotes=(quotes[1],)),
            ),
        )

    def _quote(
        self,
        token_id: str,
        market_id: str,
        outcome: str,
        side: Side,
        price: float,
        size: float,
        updated: datetime,
        url: Optional[str],
    ) -> Quote:
        contracts = (size / price) if price > 0 else 0.0
        return Quote(
            venue=self.name,
            market_id=token_id,
            ticker=market_id,
            outcome=outcome,
            side=side,
            price=price,
            effective_price=self._fees.effective_price(price, max(contracts, 1.0)),
            size_available=contracts,
            last_update=updated,
            url=url,
        )

    # ------------------------------------------------------------- enrichment

    async def enrich(self, events: list[Event]) -> list[Event]:
        """Replace top-of-book estimates with real CLOB depth for a shortlist."""
        token_ids: list[str] = []
        for ev in events:
            for mk in ev.markets:
                for oc in mk.outcomes:
                    for q in oc.quotes:
                        if q.venue == self.name:
                            token_ids.append(q.market_id)
        token_ids = list(dict.fromkeys(token_ids))
        if not token_ids:
            return events

        books = await self._fetch_books(token_ids)
        if not books:
            return events
        return [self._apply_books(ev, books) for ev in events]

    async def _fetch_books(self, token_ids: list[str]) -> dict[str, dict[str, list[DepthLevel]]]:
        out: dict[str, dict[str, list[DepthLevel]]] = {}
        for i in range(0, len(token_ids), _MAX_BOOK_BATCH):
            chunk = token_ids[i : i + _MAX_BOOK_BATCH]
            payload = [{"token_id": t} for t in chunk]
            try:
                data = await self._post(f"{self.clob}/books", payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"polymarket: order book batch failed -- {exc}")
                continue
            for entry in data or []:
                asset = str(entry.get("asset_id") or "")
                if not asset:
                    continue
                # Sort explicitly: best ask is the LOWEST price, best bid the highest.
                asks = sorted(
                    (
                        DepthLevel(price=_as_float(l.get("price")), size=_as_float(l.get("size")))
                        for l in entry.get("asks") or []
                    ),
                    key=lambda d: d.price,
                )
                bids = sorted(
                    (
                        DepthLevel(price=_as_float(l.get("price")), size=_as_float(l.get("size")))
                        for l in entry.get("bids") or []
                    ),
                    key=lambda d: -d.price,
                )
                out[asset] = {"asks": asks, "bids": bids}
        return out

    def _apply_books(self, ev: Event, books: dict[str, dict[str, list[DepthLevel]]]) -> Event:
        markets: list[Market] = []
        for mk in ev.markets:
            outcomes: list[Outcome] = []
            for oc in mk.outcomes:
                quotes: list[Quote] = []
                for q in oc.quotes:
                    book = books.get(q.market_id)
                    if not book or not book["asks"]:
                        quotes.append(q)
                        continue
                    levels = tuple(book["asks"])
                    best = levels[0].price
                    total = sum(l.size for l in levels)
                    quotes.append(
                        q.model_copy(
                            update={
                                "price": best,
                                "effective_price": self._fees.effective_price(
                                    best, max(total, 1.0)
                                ),
                                "size_available": total,
                                "depth": levels,
                            }
                        )
                    )
                outcomes.append(Outcome(name=oc.name, quotes=tuple(quotes)))
            markets.append(Market(key=mk.key, outcomes=tuple(outcomes)))
        return ev.model_copy(update={"markets": tuple(markets)})
