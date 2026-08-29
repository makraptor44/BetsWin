"""Smarkets adapter -- the UK/EU exchange zone.

Smarkets is a peer-to-peer betting exchange licensed in the UK and Malta. Its
v3 market-data API is public: no key, no session, no scraping. That makes it the
counterpart Betfair cannot be without credentials, and it is what gives the
`uk_exchange` zone two venues to arb against each other.

Why an exchange fits this engine unchanged
------------------------------------------

Smarkets quotes in probability units, not decimal odds. A contract priced at
7042 costs 70.42% and pays 100% -- structurally identical to a Polymarket or
Kalshi $1 contract, in sterling. So the whole pipeline (book sums, equal-profit
sizing, depth walking) applies without a special case.

The one genuine difference is the NO side. An exchange has no "NO" contract; it
has a lay. But laying a contract at bid `b` means taking `b` and standing liable
for `1 - b`, which is exactly buying NO at `1 - b`. Modelling it that way keeps
one representation across every venue:

    yes_ask = best offer
    no_ask  = 1 - best bid

Because the spread is non-negative, `yes_ask + no_ask >= 1` always holds on one
contract -- a single Smarkets market can never be a binary-complement arb, and
the detector correctly finds none. The edge on an exchange lives in Dutch books
across a market's contracts, and against the other venue in the zone.

Fees are commission on net winnings, not a spread, so `CommissionFeeModel` is
what converts a quote into an all-in cost.

Units, from the v3 API:
  price     hundredths of a percent of probability   7042 -> 0.7042
  quantity  ten-thousandths of a contract            2932804 -> 293.28 contracts
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from loguru import logger

from ..config import settings
from ..fees import fee_model_for
from ..models import DepthLevel, Event, Market, Outcome, Quote, Side
from ..normalise import classify_category
from .base import Source

#: Price and quantity scaling from the v3 API's integer units.
_PRICE_SCALE = 10_000.0
_QTY_SCALE = 10_000.0

#: Market types whose contracts genuinely partition the sample space. Anything
#: else (handicaps, over/unders on a ladder, goalscorer markets) either overlaps
#: or is one line of many, and a Dutch book over a non-partition is not a Dutch
#: book at all (Part I s5.2).
_EXHAUSTIVE_TYPES = frozenset(
    {
        "WINNER_3_WAY",
        "WINNER_2_WAY",
        "WINNER",
        "MONEYLINE",
        "BTTS",
        "DOUBLE_CHANCE",
    }
)

#: Types kept as ordinary binaries even though they are one line of a ladder.
_BINARY_TYPES = frozenset({"BTTS", "CLEAN_SHEET"})

#: Smarkets event types map cleanly onto the shared category vocabulary. Left to
#: the keyword classifier, "Mainz vs SC Paderborn 07" has nothing in it that
#: says football, so the venue's own type is the better signal.
_CATEGORY_BY_TYPE = {
    "politics": "politics",
    "politics_outright": "politics",
    "current_affairs": "world",
    "tv_entertainment": "entertainment",
}

_MAX_IDS_PER_CALL = 20
#: An outright with more contracts than this is unplaceable by hand anyway.
_MAX_CONTRACTS = 12


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _levels(rows: Any, invert: bool) -> list[DepthLevel]:
    """Turn one side of a Smarkets book into contract-price depth.

    `invert` maps the bid stack onto NO asks: laying at bid `b` is buying NO at
    `1 - b`. Best bids come first, so the inverted stack is already cheapest
    first, which is the order `walk_book` requires.
    """
    out: list[DepthLevel] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            price = float(row.get("price", 0)) / _PRICE_SCALE
            size = float(row.get("quantity", 0)) / _QTY_SCALE
        except (TypeError, ValueError):
            continue
        if invert:
            price = 1.0 - price
        if not (0.0 < price < 1.0) or size <= 0:
            continue
        out.append(DepthLevel(price=round(price, 4), size=round(size, 2)))
    out.sort(key=lambda d: d.price)
    return out


class SmarketsSource(Source):
    name = "smarkets"
    label = "Smarkets"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = settings.smarkets_api_url.rstrip("/")
        self._fees = fee_model_for("smarkets")

    # ------------------------------------------------------------- fetching

    async def fetch_events(self) -> list[Event]:
        raw_events = await self._fetch_event_list()
        if not raw_events:
            return []

        by_id = {str(e.get("id")): e for e in raw_events if e.get("id")}
        markets = await self._fetch_markets(list(by_id))
        if not markets:
            return []

        market_ids = [str(m["id"]) for m in markets]
        contracts, quotes = await asyncio.gather(
            self._fetch_contracts(market_ids),
            self._fetch_quotes(market_ids),
        )

        events: list[Event] = []
        for market in markets:
            ev_raw = by_id.get(str(market.get("event_id")))
            if ev_raw is None:
                continue
            built = self._build_event(
                ev_raw, market, contracts.get(str(market["id"]), []), quotes
            )
            if built is not None:
                events.append(built)

        logger.info(
            f"smarkets: {len(raw_events)} events -> {len(events)} tradeable markets"
        )
        return events

    async def _fetch_event_list(self) -> list[dict[str, Any]]:
        """One page per configured event type, newest first, budget-capped."""
        per_type = max(
            5, settings.smarkets_max_events // max(1, len(settings.smarkets_event_type_list))
        )
        out: list[dict[str, Any]] = []
        for event_type in settings.smarkets_event_type_list:
            try:
                data = await self._get(
                    f"{self.base}/events/",
                    params={
                        "type": event_type,
                        "state": "upcoming",
                        "limit": per_type,
                        "sort": "id",
                    },
                )
            except Exception as exc:  # noqa: BLE001 - one dead type is survivable
                logger.debug(f"smarkets: event type {event_type} failed -- {exc}")
                continue
            for ev in (data or {}).get("events") or []:
                if ev.get("bet_allowed") and not ev.get("hidden"):
                    out.append(ev)
        return out[: settings.smarkets_max_events]

    async def _fetch_markets(self, event_ids: list[str]) -> list[dict[str, Any]]:
        """The main outcome market for each event, and only that.

        A single football fixture carries ~170 markets. Pulling every one would
        cost a hundred requests to produce handicap ladders the detectors
        cannot use, so this keeps one exhaustive market per event.
        """
        found: dict[str, dict[str, Any]] = {}
        for batch in _chunks(event_ids, _MAX_IDS_PER_CALL):
            try:
                data = await self._get(f"{self.base}/events/{','.join(batch)}/markets/")
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"smarkets: markets batch failed -- {exc}")
                continue
            for m in (data or {}).get("markets") or []:
                if str(m.get("state")) != "open" or m.get("hidden"):
                    continue
                type_name = str((m.get("market_type") or {}).get("name") or "")
                if type_name not in _EXHAUSTIVE_TYPES:
                    continue
                if int(m.get("winner_count") or 0) != 1:
                    continue
                ev_id = str(m.get("event_id"))
                # Keep the first (lowest display_order) match per event.
                prev = found.get(ev_id)
                if prev is None or int(m.get("display_order") or 0) < int(
                    prev.get("display_order") or 0
                ):
                    found[ev_id] = m
        return list(found.values())

    async def _fetch_contracts(self, market_ids: list[str]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for batch in _chunks(market_ids, _MAX_IDS_PER_CALL):
            try:
                data = await self._get(f"{self.base}/markets/{','.join(batch)}/contracts/")
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"smarkets: contracts batch failed -- {exc}")
                continue
            for c in (data or {}).get("contracts") or []:
                if c.get("hidden") or str(c.get("state_or_outcome")) != "open":
                    continue
                out.setdefault(str(c.get("market_id")), []).append(c)
        return out

    async def _fetch_quotes(self, market_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Contract-id -> {bids, offers}, merged across batches."""
        out: dict[str, dict[str, Any]] = {}
        for batch in _chunks(market_ids, _MAX_IDS_PER_CALL):
            try:
                data = await self._get(f"{self.base}/markets/{','.join(batch)}/quotes/")
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"smarkets: quotes batch failed -- {exc}")
                continue
            if isinstance(data, dict):
                for contract_id, book in data.items():
                    if isinstance(book, dict):
                        out[str(contract_id)] = book
        return out

    # ----------------------------------------------------------- structuring

    def _build_event(
        self,
        ev_raw: dict[str, Any],
        market_raw: dict[str, Any],
        contracts: list[dict[str, Any]],
        quotes: dict[str, dict[str, Any]],
    ) -> Optional[Event]:
        if not contracts or len(contracts) > _MAX_CONTRACTS:
            return None

        contracts = sorted(contracts, key=lambda c: int(c.get("display_order") or 0))
        market_id = str(market_raw["id"])
        markets: list[Market] = []
        liquidity = 0.0
        now = datetime.now(timezone.utc)
        url = f"https://smarkets.com{ev_raw.get('full_slug') or ''}"

        for contract in contracts:
            cid = str(contract.get("id"))
            book = quotes.get(cid)
            if not book:
                return None  # a missing leg breaks exhaustiveness
            yes_levels = _levels(book.get("offers"), invert=False)
            no_levels = _levels(book.get("bids"), invert=True)
            if not yes_levels or not no_levels:
                return None
            name = str(contract.get("name") or "").strip()
            if not name:
                return None

            yes_q = self._quote(
                market_id, cid, name, Side.YES, yes_levels, now, url
            )
            no_q = self._quote(
                market_id, cid, f"Not {name}", Side.NO, no_levels, now, url
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

        # `complete` is Smarkets' own assertion that the contracts cover every
        # outcome. Without it the Dutch detector would be summing a partial set.
        exhaustive = bool(market_raw.get("complete")) and len(markets) > 1

        title = str(ev_raw.get("name") or market_raw.get("name") or "").strip()
        event_type = str(ev_raw.get("type") or "")
        category = _CATEGORY_BY_TYPE.get(
            event_type, "sports" if event_type.endswith(("_match", "_race", "_outright")) else ""
        )
        return Event(
            id=f"smarkets:{market_id}",
            venue=self.name,
            title=title,
            category=category or classify_category(title),
            currency="GBP",
            close_time=_parse_dt(ev_raw.get("start_datetime")),
            commence_time=_parse_dt(ev_raw.get("start_datetime")),
            mutually_exclusive=exhaustive,
            volume_usd=0.0,
            liquidity_usd=round(liquidity, 2),
            url=url,
            markets=tuple(markets),
        )

    def _quote(
        self,
        market_id: str,
        contract_id: str,
        outcome: str,
        side: Side,
        levels: list[DepthLevel],
        updated: datetime,
        url: str,
    ) -> Quote:
        best = levels[0].price
        total = sum(l.size for l in levels)
        return Quote(
            venue=self.name,
            market_id=f"{market_id}:{contract_id}:{side.value}",
            ticker=contract_id,
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
        """Re-pull quotes for the shortlist.

        The catalogue fetch already carries full depth, so enrichment is about
        freshness rather than detail: candidate books are re-read immediately
        before sizing so the detector is not acting on a price from the start
        of the cycle.
        """
        market_ids = [
            ev.id.split(":", 1)[1] for ev in events if ev.id.startswith("smarkets:")
        ]
        if not market_ids:
            return events
        quotes = await self._fetch_quotes(market_ids[:_MAX_IDS_PER_CALL * 2])
        if not quotes:
            return events
        return [self._refresh(ev, quotes) for ev in events]

    def _refresh(self, ev: Event, quotes: dict[str, dict[str, Any]]) -> Event:
        if not ev.id.startswith("smarkets:"):
            return ev
        now = datetime.now(timezone.utc)
        markets: list[Market] = []
        for mk in ev.markets:
            outcomes: list[Outcome] = []
            for oc in mk.outcomes:
                fresh: list[Quote] = []
                for q in oc.quotes:
                    book = quotes.get(q.ticker or "")
                    levels = (
                        _levels(book.get("offers"), invert=False)
                        if book and q.side is Side.YES
                        else _levels(book.get("bids"), invert=True)
                        if book
                        else []
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
