"""Kalshi adapter.

Kalshi is the CFTC-regulated US prediction market. Market data is public; only
trading needs credentials, and this system never places orders.

Ingestion goes through `/events?with_nested_markets=true` rather than `/markets`.
That is deliberate: the flat `/markets` feed is dominated by tens of thousands of
auto-generated multivariate parlay markets (KXMVE*) with no liquidity, which
would swamp the scanner. The events feed also carries the `mutually_exclusive`
flag, which is the precondition for the Dutch-book detector (Part I s5.1) -- an
82-outcome "World Cup winner" event is exactly the structure worth scanning.

Price units: the current API returns dollars as strings (`yes_ask_dollars`), but
older deployments return integer cents (`yes_ask`). Both are handled.

Order book shape: `orderbook_fp` has `yes_dollars` and `no_dollars`, and BOTH are
bid stacks -- there is no ask side. To buy YES you cross against the NO bids, so
    yes_ask(level) = 1 - no_bid(level)
Levels arrive ascending, so the best bid is the LAST element.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from ..config import settings
from ..fees import fee_model_for
from ..models import DepthLevel, Event, Market, Outcome, Quote, Side
from ..normalise import classify_category
from .base import Source

# Auto-generated multivariate/parlay families carry no useful liquidity.
_EXCLUDED_PREFIXES = ("KXMVE",)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _price(market: dict[str, Any], dollars_key: str, cents_key: str) -> Optional[float]:
    """Read a price as dollars, accepting either API generation."""
    if dollars_key in market and market[dollars_key] not in (None, ""):
        p = _as_float(market[dollars_key], -1.0)
        return p if 0.0 < p < 1.0 else None
    if cents_key in market and market[cents_key] not in (None, ""):
        p = _as_float(market[cents_key], -1.0) / 100.0
        return p if 0.0 < p < 1.0 else None
    return None


class KalshiSource(Source):
    name = "kalshi"
    label = "Kalshi"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = settings.kalshi_api_url.rstrip("/")
        self._fees = fee_model_for("kalshi")

    # ------------------------------------------------------------- fetching

    async def fetch_events(self) -> list[Event]:
        raw = await self._fetch_raw_events()
        events = [ev for ev in (self._build_event(e) for e in raw) if ev is not None]
        logger.info(f"kalshi: {len(raw)} raw events -> {len(events)} tradeable")
        return events

    async def _fetch_raw_events(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(settings.kalshi_max_pages):
            params: dict[str, Any] = {
                "limit": settings.kalshi_page_limit,
                "status": "open",
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            data = await self._get(f"{self.base}/events", params=params)
            batch = (data or {}).get("events") or []
            if not batch:
                break
            out.extend(batch)
            cursor = (data or {}).get("cursor")
            if not cursor:
                break
        return out

    # ----------------------------------------------------------- structuring

    def _build_event(self, raw: dict[str, Any]) -> Optional[Event]:
        ticker = str(raw.get("event_ticker") or "")
        if not ticker or ticker.startswith(_EXCLUDED_PREFIXES):
            return None

        raw_markets = raw.get("markets") or []
        markets: list[Market] = []
        volume = 0.0
        liquidity = 0.0
        close_time: Optional[datetime] = None

        for m in raw_markets:
            built = self._build_market(m)
            if built is None:
                continue
            markets.append(built)
            volume += _as_float(m.get("volume_fp"), _as_float(m.get("volume")))
            liquidity += _as_float(m.get("liquidity_dollars"), _as_float(m.get("liquidity")) / 100.0)
            close = _parse_dt(m.get("close_time"))
            if close and (close_time is None or close < close_time):
                close_time = close

        if not markets:
            return None
        if volume < settings.min_market_volume_usd and liquidity < settings.min_market_liquidity_usd:
            return None

        return Event(
            id=f"kalshi:{ticker}",
            venue=self.name,
            title=str(raw.get("title") or ticker),
            category=classify_category(str(raw.get("title") or ""), raw.get("category")),
            close_time=close_time,
            mutually_exclusive=bool(raw.get("mutually_exclusive")) and len(markets) > 1,
            volume_usd=volume,
            liquidity_usd=liquidity,
            url=f"https://kalshi.com/markets/{ticker.split('-')[0].lower()}",
            markets=tuple(markets),
        )

    def _build_market(self, m: dict[str, Any]) -> Optional[Market]:
        if str(m.get("status") or "open") not in ("open", "active"):
            return None
        if str(m.get("market_type") or "binary") != "binary":
            return None

        ticker = str(m.get("ticker") or "")
        yes_ask = _price(m, "yes_ask_dollars", "yes_ask")
        no_ask = _price(m, "no_ask_dollars", "no_ask")
        if yes_ask is None or no_ask is None:
            return None

        # A one-sided book quotes the untradeable side at 1.00; skip those.
        if yes_ask >= 0.999 or no_ask >= 0.999:
            return None

        yes_name = str(m.get("yes_sub_title") or "Yes").strip() or "Yes"
        no_name = str(m.get("no_sub_title") or "No").strip() or "No"
        if yes_name == no_name:
            yes_name, no_name = f"{yes_name} (Yes)", f"{no_name} (No)"

        updated = _parse_dt(m.get("updated_time")) or datetime.now(timezone.utc)
        size = _as_float(m.get("yes_ask_size_fp"), _as_float(m.get("yes_ask_size")))
        if size <= 0:
            size = _as_float(m.get("open_interest_fp"), _as_float(m.get("open_interest"))) * 0.05
        url = f"https://kalshi.com/markets/{ticker}"

        yes_q = self._quote(ticker, yes_name, Side.YES, yes_ask, size, updated, url)
        no_q = self._quote(ticker, no_name, Side.NO, no_ask, size, updated, url)

        return Market(
            key="binary",
            outcomes=(
                Outcome(name=yes_name, quotes=(yes_q,)),
                Outcome(name=no_name, quotes=(no_q,)),
            ),
        )

    def _quote(
        self,
        ticker: str,
        outcome: str,
        side: Side,
        price: float,
        size: float,
        updated: datetime,
        url: str,
    ) -> Quote:
        contracts = max(size, 1.0)
        return Quote(
            venue=self.name,
            market_id=f"{ticker}:{side.value}",
            ticker=ticker,
            outcome=outcome,
            side=side,
            price=price,
            effective_price=self._fees.effective_price(price, contracts),
            size_available=size,
            last_update=updated,
            url=url,
        )

    # ------------------------------------------------------------- enrichment

    async def enrich(self, events: list[Event]) -> list[Event]:
        tickers: list[str] = []
        for ev in events:
            for mk in ev.markets:
                for oc in mk.outcomes:
                    for q in oc.quotes:
                        if q.venue == self.name and q.ticker:
                            tickers.append(q.ticker)
        tickers = list(dict.fromkeys(tickers))
        if not tickers:
            return events

        books: dict[str, dict[Side, list[DepthLevel]]] = {}
        for t in tickers[:80]:
            book = await self._fetch_book(t)
            if book:
                books[t] = book
        if not books:
            return events
        return [self._apply_books(ev, books) for ev in events]

    async def _fetch_book(self, ticker: str) -> Optional[dict[Side, list[DepthLevel]]]:
        try:
            data = await self._get(f"{self.base}/markets/{ticker}/orderbook", params={"depth": 10})
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"kalshi: orderbook {ticker} failed -- {exc}")
            return None

        ob = (data or {}).get("orderbook_fp") or (data or {}).get("orderbook") or {}
        yes_bids = ob.get("yes_dollars") or ob.get("yes") or []
        no_bids = ob.get("no_dollars") or ob.get("no") or []
        scale = 1.0 if ("yes_dollars" in ob or "no_dollars" in ob) else 0.01

        def asks_from_opposing_bids(bids: list[Any]) -> list[DepthLevel]:
            """Best ask for one side is 1 - best bid on the other side."""
            levels: list[DepthLevel] = []
            for row in bids:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                bid = _as_float(row[0]) * scale
                size = _as_float(row[1])
                if not (0.0 < bid < 1.0) or size <= 0:
                    continue
                levels.append(DepthLevel(price=round(1.0 - bid, 4), size=size))
            # Cheapest ask first.
            return sorted(levels, key=lambda d: d.price)

        yes_asks = asks_from_opposing_bids(no_bids)
        no_asks = asks_from_opposing_bids(yes_bids)
        if not yes_asks and not no_asks:
            return None
        return {Side.YES: yes_asks, Side.NO: no_asks}

    def _apply_books(
        self, ev: Event, books: dict[str, dict[Side, list[DepthLevel]]]
    ) -> Event:
        markets: list[Market] = []
        for mk in ev.markets:
            outcomes: list[Outcome] = []
            for oc in mk.outcomes:
                quotes: list[Quote] = []
                for q in oc.quotes:
                    levels = (books.get(q.ticker or "") or {}).get(q.side) or []
                    if not levels:
                        quotes.append(q)
                        continue
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
                                "depth": tuple(levels),
                            }
                        )
                    )
                outcomes.append(Outcome(name=oc.name, quotes=tuple(quotes)))
            markets.append(Market(key=mk.key, outcomes=tuple(outcomes)))
        return ev.model_copy(update={"markets": tuple(markets)})
