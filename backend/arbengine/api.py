"""HTTP + WebSocket API (Part II s20.3: "a small FastAPI app showing live arbs,
deployed bankroll, and P&L by book and by sport").

The Next.js frontend is the only consumer. Everything the dashboard renders is
served from here; there is no second source of truth.

One deliberate omission: there is no place-bet endpoint. Part II s19.2 is
unambiguous that automating placement at venues whose terms forbid it gets
accounts closed and balances confiscated. This system detects, sizes and alerts;
execution is recorded, not performed.
"""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from . import correlation_arb as ca
from . import odds as om
from .backtest import BacktestParams, replay, sweep
from .config import settings
from .correlation_detector import evaluate_pair
from .fees import configure_from_settings, fee_model_for
from .models import Arb, ArbKind, EngineStatus, Event
from .scanner import Scanner
from .sizing import resize, size_arb
from .venues import (
    Zone,
    all_venues,
    can_pair,
    describe,
    venue as venue_info,
    zone_of,
    zones_available_from,
)

configure_from_settings(settings)

scanner: Optional[Scanner] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scanner
    scanner = Scanner()
    if settings.autostart_scanner:
        # Run one cycle immediately so the dashboard is populated on first load.
        asyncio.create_task(_bootstrap(scanner))
    logger.info(f"api ready on {settings.host}:{settings.port} (demo={settings.demo_mode})")
    try:
        yield
    finally:
        if scanner is not None:
            await scanner.close()


async def _bootstrap(s: Scanner) -> None:
    try:
        await s.scan_once()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"initial scan failed: {exc}")
    await s.start()


app = FastAPI(
    title="BetsWin Arbitrage Engine",
    version="1.0.0",
    description=(
        "Scans prediction markets (Polymarket, Kalshi), betting exchanges "
        "(Smarkets, Betfair) and sportsbooks for arbitrage, sizes each "
        "opportunity against real order-book depth, and scores it for the "
        "failure modes that erode theoretical edge. Cross-venue legs are only "
        "combined within an execution zone -- a set of venues one operator can "
        "reach from a single location in a single currency -- so nothing "
        "surfaced requires accounts in two jurisdictions."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _engine() -> Scanner:
    if scanner is None:
        raise HTTPException(503, "engine not started")
    return scanner


# ------------------------------------------------------------------- health


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": app.version,
        "demo_mode": settings.demo_mode,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status", response_model=EngineStatus, tags=["system"])
async def status() -> EngineStatus:
    return _engine().status()


@app.get("/api/config", tags=["system"])
async def get_config() -> dict[str, Any]:
    """Everything the UI needs to render and explain the engine's behaviour."""
    return {
        "bankroll": settings.bankroll,
        "default_stake": settings.default_stake,
        "min_arb_margin": settings.min_arb_margin,
        "max_arb_margin": settings.max_arb_margin,
        "suspect_margin": settings.suspect_margin,
        "min_confidence": settings.min_confidence,
        "max_stake_fraction_per_event": settings.max_stake_fraction_per_event,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "alert_min_margin": settings.alert_min_margin,
        "alert_min_confidence": settings.alert_min_confidence,
        "assumed_void_rate": settings.assumed_void_rate,
        "assumed_void_loss": settings.assumed_void_loss,
        "fuzzy_match_threshold": settings.fuzzy_match_threshold,
        "demo_mode": settings.demo_mode,
        "sources": {
            "polymarket": settings.enable_polymarket,
            "kalshi": settings.enable_kalshi,
            "sportsbook": settings.odds_api_enabled,
            "smarkets": settings.enable_smarkets,
            "betfair": settings.betfair_enabled,
        },
        "telegram_enabled": settings.telegram_enabled,
        "kinds": [k.value for k in ArbKind],
        "enforce_zone_pairing": settings.enforce_zone_pairing,
        "operator_jurisdiction": settings.operator_jurisdiction,
        "near_miss_slack": settings.near_miss_slack,
        "smarkets_commission": settings.smarkets_commission,
        "betfair_commission": settings.betfair_commission,
    }


class ConfigPatch(BaseModel):
    bankroll: Optional[float] = Field(None, gt=0)
    default_stake: Optional[float] = Field(None, gt=0)
    min_arb_margin: Optional[float] = Field(None, ge=0, le=1)
    max_arb_margin: Optional[float] = Field(None, ge=0, le=1)
    suspect_margin: Optional[float] = Field(None, ge=0, le=1)
    min_confidence: Optional[int] = Field(None, ge=0, le=100)
    max_stake_fraction_per_event: Optional[float] = Field(None, gt=0, le=1)
    poll_interval_seconds: Optional[int] = Field(None, ge=10, le=3600)
    alert_min_margin: Optional[float] = Field(None, ge=0, le=1)
    alert_min_confidence: Optional[int] = Field(None, ge=0, le=100)
    assumed_void_rate: Optional[float] = Field(None, ge=0, le=1)
    assumed_void_loss: Optional[float] = Field(None, ge=0, le=1)
    enforce_zone_pairing: Optional[bool] = None
    operator_jurisdiction: Optional[str] = Field(None, max_length=2)
    near_miss_slack: Optional[float] = Field(None, ge=0, le=0.25)


@app.patch("/api/config", tags=["system"])
async def patch_config(patch: ConfigPatch) -> dict[str, Any]:
    """Live-tune thresholds. Applies to the next scan cycle."""
    changed: dict[str, Any] = {}
    for key, value in patch.model_dump(exclude_none=True).items():
        if key == "operator_jurisdiction":
            value = str(value).strip().upper()
        setattr(settings, key, value)
        changed[key] = value
    if changed:
        logger.info(f"config updated: {changed}")
    return {"updated": changed, "config": await get_config()}


# --------------------------------------------------------------------- arbs


@app.get("/api/arbs", tags=["arbs"])
async def list_arbs(
    kind: Optional[str] = None,
    venue: Optional[str] = None,
    zone: Optional[str] = None,
    category: Optional[str] = None,
    min_margin: float = 0.0,
    min_confidence: int = 0,
    max_hours_to_close: Optional[float] = None,
    search: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """Currently live opportunities, filtered."""
    arbs = _engine().live_arbs()

    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        arbs = [a for a in arbs if a.kind.value in wanted]
    if zone:
        wanted = {z.strip() for z in zone.split(",") if z.strip()}
        arbs = [a for a in arbs if a.zone in wanted]
    if venue:
        wanted = {v.strip() for v in venue.split(",") if v.strip()}
        arbs = [a for a in arbs if wanted & set(a.venues)]
    if category:
        arbs = [a for a in arbs if a.category == category]
    if min_margin:
        arbs = [a for a in arbs if a.net_margin >= min_margin]
    if min_confidence:
        arbs = [a for a in arbs if a.confidence >= min_confidence]
    if max_hours_to_close is not None:
        arbs = [
            a
            for a in arbs
            if a.hours_to_close is not None and a.hours_to_close <= max_hours_to_close
        ]
    if search:
        needle = search.lower()
        arbs = [a for a in arbs if needle in a.title.lower()]

    total = len(arbs)
    arbs = arbs[:limit]
    return {
        "count": len(arbs),
        "total": total,
        "arbs": [a.model_dump(mode="json") for a in arbs],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------- execution zones


@app.get("/api/venues", tags=["system"])
async def venues() -> dict[str, Any]:
    """The venue registry and the pairing rule derived from it.

    Cross-venue arbitrage is only real if one person can place both legs, so
    venues are partitioned into execution zones -- a shared currency, a shared
    settlement convention, and an account footprint one operator can plausibly
    hold. This endpoint exposes that partition and the resulting pairing matrix
    so the UI can explain a rejection instead of silently showing nothing.
    """
    eng = scanner
    live = {s.name for s in eng.sources} if eng is not None else set()

    zones = [describe(z) for z in (Zone.US_PREDICTION, Zone.UK_EXCHANGE, Zone.US_SPORTSBOOK)]

    matrix: list[dict[str, Any]] = []
    names = [v.name for v in all_venues() if v.name != "demo"]
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            verdict = can_pair(a, b, settings.operator_jurisdiction)
            matrix.append(
                {
                    "a": a,
                    "b": b,
                    "allowed": verdict.ok,
                    "reason": verdict.reason,
                    "zone": verdict.zone.value,
                    "jurisdictions": list(verdict.jurisdictions),
                    "both_live": a in live and b in live,
                }
            )

    return {
        "enforce_zone_pairing": settings.enforce_zone_pairing,
        "operator_jurisdiction": settings.operator_jurisdiction,
        "zones": zones,
        "zones_available": [
            z.value for z in zones_available_from(settings.operator_jurisdiction)
        ],
        "venues": [
            {
                "name": v.name,
                "label": v.label,
                "zone": v.zone.value,
                "structure": v.structure.value,
                "currency": v.currency,
                "regulator": v.regulator,
                "commission": v.commission,
                "jurisdictions": sorted(v.jurisdictions),
                "excluded": sorted(v.excluded),
                "public_data": v.public_data,
                "url": v.url,
                "notes": v.notes,
                "live": v.name in live,
            }
            for v in all_venues()
            if v.name != "demo"
        ],
        "pairs": matrix,
        "rejected_this_scan": (eng.cross_zone_rejected() if eng is not None else []),
    }


@app.get("/api/near-misses", tags=["arbs"])
async def near_misses(
    zone: Optional[str] = None,
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    """Books that did not cross, closest first.

    On a normal cycle this is the whole output of the engine: the tape is
    efficient and nothing arbs. Surfacing the near misses is what distinguishes
    "scanning, found nothing" from "not scanning".
    """
    rows = _engine().near_misses()
    if zone:
        wanted = {z.strip() for z in zone.split(",") if z.strip()}
        rows = [n for n in rows if n.zone in wanted]
    return {
        "count": min(len(rows), limit),
        "total": len(rows),
        "slack_bps": round(settings.near_miss_slack * 10_000, 0),
        "near_misses": [n.model_dump(mode="json") for n in rows[:limit]],
    }


@app.get("/api/arbs/{arb_id}", tags=["arbs"])
async def get_arb(arb_id: str) -> dict[str, Any]:
    arb = _engine().get_arb(arb_id)
    if arb is None:
        raise HTTPException(404, "opportunity is no longer live")

    # The payout matrix makes the guarantee auditable: profit in every state.
    # A directional position has no such guarantee -- built from `payout_if`
    # instead of one row per leg, so the losing state (the whole stake) shows
    # up as a row rather than being silently absent.
    total = arb.total_stake
    matrix = []
    if arb.strategy == "directional":
        venue_name = arb.legs[0].venue if arb.legs else ""
        for label, profit in arb.payout_if.items():
            matrix.append(
                {
                    "outcome": label,
                    "venue": venue_name,
                    "gross_return": round(profit + total, 2),
                    "total_stake": round(total, 2),
                    "profit": round(profit, 2),
                    "roi_pct": round(100.0 * profit / total, 3) if total else 0.0,
                }
            )
    else:
        for i, leg in enumerate(arb.legs):
            if arb.kind is ArbKind.DUTCH_NO:
                gross = sum(l.contracts for j, l in enumerate(arb.legs) if j != i)
            else:
                gross = leg.contracts
            matrix.append(
                {
                    "outcome": leg.outcome,
                    "venue": leg.venue,
                    "gross_return": round(gross, 2),
                    "total_stake": round(total, 2),
                    "profit": round(gross - total, 2),
                    "roi_pct": round(100.0 * (gross - total) / total, 3) if total else 0.0,
                }
            )

    return {
        "arb": arb.model_dump(mode="json"),
        "payout_matrix": matrix,
        "maths": _maths_for(arb),
    }


def _kelly_arb_payload(margin: float, void_rate: float, void_loss: float) -> dict[str, Any]:
    """Serialise the Kelly arb bound, which may legitimately be unbounded.

    With no void cost the trade carries no risk, Kelly places no bound, and the
    honest answer is "bankroll is the only constraint" -- not the 0.0 this used
    to report, which reads as "stake nothing". JSON has no infinity, so it goes
    over the wire as a null plus an explicit flag the UI can render.
    """
    f = om.kelly_arb_fraction(margin, void_rate, void_loss)
    unbounded = math.isinf(f)
    return {
        "kelly_arb_fraction": None if unbounded else round(f, 4),
        "kelly_arb_unbounded": unbounded,
    }


def _maths_for(arb: Arb) -> dict[str, Any]:
    """The derivation behind the numbers, so the UI can show its working."""
    eff = [l.effective_decimal_odds for l in arb.legs]
    raw = [l.decimal_odds for l in arb.legs]
    void_rate = settings.assumed_void_rate
    void_loss = settings.assumed_void_loss
    return {
        "implied_probs": [round(om.decimal_to_prob(d), 5) for d in eff],
        "book_quoted": round(om.book(raw), 5),
        "book_effective": round(arb.book, 5),
        "margin_gross": arb.margin,
        "margin_net": arb.net_margin,
        "vig_equivalent": round(om.vig(raw), 5),
        "void_rate": void_rate,
        "void_loss": void_loss,
        "margin_after_voids": round(
            om.margin_after_voids(arb.net_margin, void_rate, void_loss), 5
        ),
        **_kelly_arb_payload(arb.net_margin, void_rate, void_loss),
        "devig_fair_probs": [round(p, 5) for p in om.devig_proportional(raw)],
        "bankroll_cap": round(
            settings.bankroll * settings.max_stake_fraction_per_event, 2
        ),
    }


class ResizeRequest(BaseModel):
    total_stake: float = Field(..., gt=0)


@app.post("/api/arbs/{arb_id}/resize", tags=["arbs"])
async def resize_arb(arb_id: str, req: ResizeRequest) -> dict[str, Any]:
    """Recompute equal-profit stakes at a different total. Backs the calculator."""
    arb = _engine().get_arb(arb_id)
    if arb is None:
        raise HTTPException(404, "opportunity is no longer live")
    if arb.strategy == "directional":
        raise HTTPException(
            400,
            "equal-profit resizing does not apply to a directional position -- "
            "it is sized by fractional Kelly, and every leg is not guaranteed to pay out",
        )

    eff = [l.effective_decimal_odds for l in arb.legs]
    stakes = om.equal_profit_stakes(eff, req.total_stake)
    rounded = [om.round_down_to_step(s, settings.stake_step) for s in stakes]
    total = sum(rounded)

    legs = []
    payout_if: dict[str, float] = {}
    contracts_list: list[float] = []
    for leg, stake in zip(arb.legs, rounded):
        fees = fee_model_for(leg.venue)
        contracts = stake / leg.effective_price if leg.effective_price > 0 else 0.0
        contracts_list.append(contracts)
        legs.append(
            {
                **leg.model_dump(mode="json"),
                "stake": round(stake, 2),
                "contracts": round(contracts, 2),
                "fee": round(fees.total_fee(leg.price, contracts), 2),
            }
        )

    worst = None
    for i, leg in enumerate(arb.legs):
        if arb.kind is ArbKind.DUTCH_NO:
            gross = sum(c for j, c in enumerate(contracts_list) if j != i)
        else:
            gross = contracts_list[i]
        payout_if[f"{leg.outcome} ({leg.venue})"] = round(gross, 2)
        profit = gross - total
        worst = profit if worst is None else min(worst, profit)

    return {
        "total_stake": round(total, 2),
        "legs": legs,
        "payout_if": payout_if,
        "worst_case_profit": round(worst or 0.0, 2),
        "roi_pct": round(100.0 * (worst or 0.0) / total, 3) if total else 0.0,
        "exceeds_depth": req.total_stake > arb.max_stake_available,
        "max_stake_available": arb.max_stake_available,
        "bankroll_cap": round(settings.bankroll * settings.max_stake_fraction_per_event, 2),
    }


class PlaceBetRequest(BaseModel):
    """Execution / confirmation payload when user places a bet."""

    confirmed: bool = Field(True, description="Explicit confirmation by the user")
    executed_prices: Optional[list[float]] = None
    executed_stakes: Optional[list[float]] = None
    note: Optional[str] = None
    retire: bool = Field(True, description="Retire from live opportunities after placement")


@app.post("/api/arbs/{arb_id}/place", tags=["arbs"])
@app.post("/api/arbs/{arb_id}/log-placement", tags=["arbs"])
async def place_bet(arb_id: str, body: PlaceBetRequest = Body(default_factory=PlaceBetRequest)) -> dict[str, Any]:
    """Record placed bet with explicit confirmation and refresh live opportunities."""
    eng = _engine()
    arb = eng.get_arb(arb_id)
    if arb is None:
        # Fallback: check if already in store
        raise HTTPException(404, "opportunity is no longer live or has already been placed")

    row_id = await asyncio.to_thread(eng.store.upsert_arb, arb)
    for i, leg in enumerate(arb.legs):
        exec_price = (
            body.executed_prices[i]
            if body.executed_prices and i < len(body.executed_prices)
            else leg.price
        )
        exec_stake = (
            body.executed_stakes[i]
            if body.executed_stakes and i < len(body.executed_stakes)
            else leg.stake
        )
        await asyncio.to_thread(
            eng.store.record_placement,
            row_id,
            leg.venue,
            leg.market_id,
            leg.outcome,
            leg.side.value,
            leg.price,
            leg.stake,
            "placed",
            exec_price,
            exec_stake,
            None,
            body.note,
        )
    await asyncio.to_thread(eng.store.mark_placed, row_id, True)

    # Retire the arb from active live memory so it is removed from live opportunities immediately
    if body.retire:
        eng.retire_arb(arb_id)

    # Broadcast websocket update with updated live arbs list
    try:
        await eng.alerts.publish(
            {
                "type": "placed",
                "data": {
                    "arb_id": arb_id,
                    "row_id": row_id,
                    "live": [a.model_dump(mode="json") for a in eng.live_arbs()],
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"failed to broadcast placement: {exc}")

    return {
        "ok": True,
        "arb_row_id": row_id,
        "legs_placed": len(arb.legs),
        "message": f"Successfully placed {len(arb.legs)} legs for {arb.title}",
    }


class ResolveRequest(BaseModel):
    """How a position settled.

    `extra="forbid"` is load-bearing. Pydantic drops unknown fields by default,
    so the dashboard posting `realised_pnl` (a field that only ever existed on a
    since-deleted SettleRequest) was silently ignored: `custom_pnl` stayed None,
    the handler fell through to the theoretical worst case, and the endpoint
    returned ok. A settlement figure is not something to lose quietly -- a
    mismatched field is now a 422.
    """

    model_config = ConfigDict(extra="forbid")

    winning_outcome: Optional[str] = Field(None, description="Winning outcome name or 'VOID'")
    custom_pnl: Optional[float] = Field(None, description="Realised P&L to book, overriding the derived figure")
    note: Optional[str] = None


class SellBackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = Field(True, description="Explicit confirmation to unwind")
    custom_prices: Optional[list[float]] = None
    note: Optional[str] = None


def _quote_index(events) -> dict[tuple[str, str], Any]:
    """Every live quote, keyed by (venue, market_id) -- the leg's own identity.

    The previous lookup keyed live events by `Event.id` and then searched that
    map with a `market_id`, so it never matched anything and the "live price"
    branch was unreachable dead code.
    """
    index: dict[tuple[str, str], Any] = {}
    for ev in events:
        for market in ev.markets:
            for outcome in market.outcomes:
                for q in outcome.quotes:
                    index[(q.venue, q.market_id)] = q
    return index


def _complement_index(events) -> dict[tuple[str, str], Any]:
    """For each quote, the best ask on the OTHER side of the same binary market.

    On a $1 binary contract, selling a YES is the same trade as buying a NO, so
    the YES bid is exactly `1 - (NO ask)`. `Quote` carries only the ask side, so
    this identity is how a genuine exit price is recovered from the tape rather
    than invented.
    """
    index: dict[tuple[str, str], Any] = {}
    for ev in events:
        for market in ev.markets:
            if len(market.outcomes) != 2:
                continue
            a, b = market.outcomes[0].best(), market.outcomes[1].best()
            if a is None or b is None:
                continue
            index[(a.venue, a.market_id)] = b
            index[(b.venue, b.market_id)] = a
    return index


@app.get("/api/positions/{row_id}/unwind-quote", tags=["arbs"])
async def get_unwind_quote(row_id: int) -> dict[str, Any]:
    """What this position would fetch if it were sold back right now.

    You hold N contracts per leg. Unwinding means SELLING them, so the price
    that matters is the bid, not the ask you bought at.

    `Quote` carries only the ask side of the book, so the bid is recovered from
    the complementary contract: on a $1 binary, selling a YES is the same trade
    as buying a NO, so the YES bid is `1 - (NO ask)`. That is a real price off
    the tape.

    When the tape cannot supply one, this returns no price for that leg and
    says so. It used to invent `entry_price * (1 - 0.005)` instead, which made
    every unwind report a loss of about half a percent of stake whatever the
    market had done -- and `sell-back` wrote that invented figure into the
    ledger as realised P&L.
    """
    eng = _engine()
    row = await asyncio.to_thread(eng.store.arb_by_id, row_id)
    if not row:
        raise HTTPException(404, "position not found")

    legs = json.loads(row.get("legs_json") or "[]")
    total_stake = float(row.get("total_stake") or 0.0)
    currency = row.get("currency") or "USD"

    events = eng.live_events()
    quotes = _quote_index(events)
    complements = _complement_index(events)

    unwind_legs: list[dict[str, Any]] = []
    total_net_proceeds = 0.0
    priced_legs = 0

    for leg in legs:
        venue = leg.get("venue") or ""
        market_id = leg.get("market_id") or ""
        outcome = leg.get("outcome")
        side = str(leg.get("side", "YES")).upper()
        entry_price = float(leg.get("price") or 0.0)
        stake = float(leg.get("stake") or 0.0)
        contracts = float(leg.get("contracts") or 0.0)

        key = (venue, market_id)
        current_bid: Optional[float] = None
        source = "unavailable"

        complement = complements.get(key)
        if complement is not None:
            # Selling this contract == buying its complement.
            bid = 1.0 - complement.effective_price
            if 0.0 < bid < 1.0:
                current_bid = bid
                source = "complement_ask"

        if current_bid is None and key in quotes:
            # No complement on the tape. The same-side ask is an upper bound on
            # the bid, never the bid itself, so it is reported as an estimate
            # rather than passed off as executable.
            source = "same_side_ask_upper_bound"

        if current_bid is None:
            unwind_legs.append(
                {
                    "venue": venue,
                    "outcome": outcome,
                    "side": side,
                    "contracts": contracts,
                    "entry_price": entry_price,
                    "current_bid": None,
                    "price_source": source,
                    "gross_proceeds": None,
                    "fee": None,
                    "net_proceeds": None,
                    "stake": stake,
                    "pnl": None,
                }
            )
            continue

        fees = fee_model_for(venue)
        gross = round(contracts * current_bid, 2)
        fee = round(fees.total_fee(current_bid, contracts), 2)
        net_proceeds = round(max(0.0, gross - fee), 2)
        total_net_proceeds += net_proceeds
        priced_legs += 1

        unwind_legs.append(
            {
                "venue": venue,
                "outcome": outcome,
                "side": side,
                "contracts": contracts,
                "entry_price": entry_price,
                "current_bid": round(current_bid, 4),
                "price_source": source,
                "gross_proceeds": gross,
                "fee": fee,
                "net_proceeds": net_proceeds,
                "stake": stake,
                "pnl": round(net_proceeds - stake, 2),
            }
        )

    complete = bool(legs) and priced_legs == len(legs)
    unwind_pnl = round(total_net_proceeds - total_stake, 2) if complete else None
    roi_pct = (
        round((unwind_pnl / total_stake) * 100, 2)
        if complete and total_stake > 0
        else None
    )

    return {
        "row_id": row_id,
        "title": row.get("title"),
        "total_stake": total_stake,
        "currency": currency,
        "total_proceeds": round(total_net_proceeds, 2) if complete else None,
        "unwind_pnl": unwind_pnl,
        "roi_pct": roi_pct,
        "legs": unwind_legs,
        "priced_legs": priced_legs,
        "leg_count": len(legs),
        #: False when at least one leg has no live bid. The position cannot be
        #: valued, let alone settled, until it is True.
        "quotable": complete,
        "live_prices_used": complete,
    }


@app.post("/api/positions/{row_id}/sell-back", tags=["arbs"])
async def sell_back_position(
    row_id: int,
    body: SellBackRequest = Body(default_factory=SellBackRequest),
) -> dict[str, Any]:
    """Record an early unwind of a position, at prices sourced from the tape.

    Refuses when any leg has no live bid. A settlement figure written into the
    ledger is a claim about money that changed hands, so an unpriceable
    position is a 409 rather than a guess.
    """
    eng = _engine()
    if not body.confirmed:
        raise HTTPException(400, "unwinding a position requires explicit confirmation")

    quote = await get_unwind_quote(row_id)
    if not quote["quotable"] and not body.custom_prices:
        unpriced = [l["outcome"] for l in quote["legs"] if l["current_bid"] is None]
        raise HTTPException(
            409,
            "no live bid for "
            + ", ".join(str(o) for o in unpriced)
            + " -- the position cannot be valued right now. Supply custom_prices "
            "to record an unwind you executed by hand.",
        )

    if body.custom_prices:
        if len(body.custom_prices) != len(quote["legs"]):
            raise HTTPException(
                400,
                f"custom_prices has {len(body.custom_prices)} entries for "
                f"{len(quote['legs'])} legs",
            )
        proceeds = 0.0
        for leg, price in zip(quote["legs"], body.custom_prices):
            fees = fee_model_for(leg["venue"])
            gross = leg["contracts"] * price
            proceeds += max(0.0, gross - fees.total_fee(price, leg["contracts"]))
            leg["current_bid"] = round(price, 4)
            leg["price_source"] = "operator_supplied"
            leg["net_proceeds"] = round(max(0.0, gross - fees.total_fee(price, leg["contracts"])), 2)
        quote["total_proceeds"] = round(proceeds, 2)
        quote["unwind_pnl"] = round(proceeds - quote["total_stake"], 2)

    realised_pnl = quote["unwind_pnl"]

    # Record SELL placements for each leg
    for i, leg in enumerate(quote["legs"]):
        exec_price = (
            body.custom_prices[i]
            if body.custom_prices and i < len(body.custom_prices)
            else leg["current_bid"]
        )
        await asyncio.to_thread(
            eng.store.record_placement,
            row_id,
            leg["venue"],
            f"unwind-{leg.get('venue')}",
            leg["outcome"],
            "SELL",
            leg["current_bid"],
            leg["net_proceeds"],
            "unwound",
            exec_price,
            leg["net_proceeds"],
            None,
            body.note or "Sell back early via API",
        )

    await asyncio.to_thread(
        eng.store.settle,
        row_id,
        realised_pnl,
        "sell_back_early",
    )

    return {
        "ok": True,
        "row_id": row_id,
        "settlement_type": "sell_back_early",
        "realised_pnl": realised_pnl,
        "total_proceeds": quote["total_proceeds"],
        "message": f"Position #{row_id} successfully sold back early for {quote['currency']} {quote['total_proceeds']} (P&L: {quote['currency']} {realised_pnl:+0.2f}).",
    }


@app.post("/api/positions/{row_id}/resolve", tags=["arbs"])
@app.post("/api/positions/{row_id}/settle", tags=["arbs"])
async def resolve_position(row_id: int, body: ResolveRequest = Body(default_factory=ResolveRequest)) -> dict[str, Any]:
    """Settle an open position upon market resolution (Hold to Resolution)."""
    eng = _engine()
    row = await asyncio.to_thread(eng.store.arb_by_id, row_id)
    if not row:
        raise HTTPException(404, "position not found")

    legs = json.loads(row.get("legs_json") or "[]")
    total_stake = float(row.get("total_stake") or 0.0)
    kind = row.get("kind")
    currency = row.get("currency") or "USD"

    final_pnl: float
    if body.custom_pnl is not None:
        final_pnl = float(body.custom_pnl)
    elif body.winning_outcome:
        winning = body.winning_outcome.strip().lower()
        if winning in ("void", "refund", "cancelled", "postponed"):
            final_pnl = 0.0
        else:
            if kind == "dutch_no":
                gross = sum(
                    float(l.get("contracts", 0.0))
                    for l in legs
                    if l.get("outcome", "").strip().lower() != winning
                )
            else:
                win_leg = next(
                    (l for l in legs if l.get("outcome", "").strip().lower() == winning),
                    None,
                )
                gross = float(win_leg.get("contracts", 0.0)) if win_leg else float(row.get("worst_case_profit", 0.0)) + total_stake
            final_pnl = round(gross - total_stake, 2)
    else:
        final_pnl = float(row.get("worst_case_profit") or 0.0)

    await asyncio.to_thread(
        eng.store.settle,
        row_id,
        final_pnl,
        "hold_to_resolution",
    )

    return {
        "ok": True,
        "row_id": row_id,
        "settlement_type": "hold_to_resolution",
        "winning_outcome": body.winning_outcome,
        "realised_pnl": final_pnl,
        "message": f"Position #{row_id} settled upon resolution (P&L: {currency} {final_pnl:+0.2f}).",
    }


@app.get("/api/positions", tags=["arbs"])
async def get_positions(
    settled: Optional[bool] = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    eng = _engine()
    rows = await asyncio.to_thread(eng.store.all_positions, limit, settled)
    out = []
    for r in rows:
        r = dict(r)
        r["legs"] = json.loads(r.pop("legs_json", "[]"))
        r.pop("payload_json", None)
        r["flags"] = json.loads(r.get("flags") or "[]")
        r["venues"] = json.loads(r.get("venues") or "[]")
        placements = await asyncio.to_thread(eng.store.placements_for, int(r["id"]))
        r["placements"] = [dict(p) for p in placements]
        out.append(r)

    # An arbitrage's worst_case_profit is a guaranteed gain; a directional
    # position's is the loss if the bet is simply wrong. Adding them produces a
    # number that is neither, so they are reported apart.
    open_rows = [p for p in out if not p.get("settled")]
    arb_rows = [p for p in open_rows if p.get("strategy", "arbitrage") != "directional"]
    dir_rows = [p for p in open_rows if p.get("strategy", "arbitrage") == "directional"]

    total_stake = sum(p.get("total_stake") or 0 for p in open_rows)
    guaranteed_profit = sum(p.get("worst_case_profit") or 0 for p in arb_rows)
    directional_at_risk = sum(p.get("total_stake") or 0 for p in dir_rows)
    realised_pnl = sum(p.get("realised_pnl") or 0 for p in out if p.get("settled"))

    return {
        "count": len(out),
        "total_active_stake": round(total_stake, 2),
        "total_expected_profit": round(guaranteed_profit, 2),
        "guaranteed_profit": round(guaranteed_profit, 2),
        "directional_at_risk": round(directional_at_risk, 2),
        "directional_count": len(dir_rows),
        "total_realised_pnl": round(realised_pnl, 2),
        "positions": out,
    }


# ------------------------------------------------------------------ markets


@app.get("/api/markets", tags=["markets"])
async def list_markets(
    venue: Optional[str] = None,
    zone: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    only_mutually_exclusive: bool = False,
    sort: str = Query("volume", pattern="^(volume|liquidity|book|close)$"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Browse the normalised tape the detectors actually see."""
    events = _engine().live_events()

    if venue:
        wanted = {v.strip() for v in venue.split(",") if v.strip()}
        events = [e for e in events if e.venue in wanted]
    if zone:
        wanted = {z.strip() for z in zone.split(",") if z.strip()}
        events = [e for e in events if zone_of(e.venue).value in wanted]
    if category:
        events = [e for e in events if e.category == category]
    if only_mutually_exclusive:
        events = [e for e in events if e.mutually_exclusive]
    if search:
        needle = search.lower()
        events = [e for e in events if needle in e.title.lower()]

    rows = [_event_row(e) for e in events]
    keys = {
        "volume": lambda r: -r["volume_usd"],
        "liquidity": lambda r: -r["liquidity_usd"],
        "book": lambda r: r["best_book"],
        "close": lambda r: r["close_time"] or "9999",
    }
    rows.sort(key=keys[sort])

    return {
        "count": min(len(rows), limit),
        "total": len(rows),
        "markets": rows[:limit],
        "categories": sorted({e.category for e in events}),
        "venues": sorted({e.venue for e in events}),
        "zones": sorted({zone_of(e.venue).value for e in events}),
    }


def _event_row(e: Event) -> dict[str, Any]:
    """Flatten an event for the market browser, including its tightest book."""
    best_book = 99.0
    outcomes: list[dict[str, Any]] = []
    for market in e.markets:
        quotes = [o.best() for o in market.outcomes]
        quotes = [q for q in quotes if q is not None]
        if len(quotes) >= 2:
            b = sum(q.effective_price for q in quotes)
            best_book = min(best_book, b)
        for q in quotes:
            outcomes.append(
                {
                    "name": q.outcome,
                    "side": q.side.value,
                    "price": round(q.price, 4),
                    "effective_price": round(q.effective_price, 4),
                    "decimal_odds": round(q.decimal_odds, 3),
                    "implied_pct": round(q.effective_price * 100, 2),
                    "size_available": round(q.size_available, 1),
                    "venue": q.venue,
                    "url": q.url,
                }
            )
    return {
        "id": e.id,
        "venue": e.venue,
        "zone": zone_of(e.venue).value,
        "currency": e.currency,
        "title": e.title,
        "category": e.category,
        "mutually_exclusive": e.mutually_exclusive,
        "market_count": len(e.markets),
        "volume_usd": round(e.volume_usd, 2),
        "liquidity_usd": round(e.liquidity_usd, 2),
        "close_time": e.close_time.isoformat() if e.close_time else None,
        "url": e.url,
        "best_book": round(best_book, 5) if best_book < 99 else None,
        "overround_pct": round((best_book - 1.0) * 100, 3) if best_book < 99 else None,
        "outcomes": outcomes[:24],
    }


# ---------------------------------------------------------------- analytics


@app.get("/api/analytics", tags=["analytics"])
async def analytics(days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    eng = _engine()
    stats = await asyncio.to_thread(eng.store.stats, days)
    hist = await asyncio.to_thread(eng.store.margin_histogram, days)
    scans = await asyncio.to_thread(eng.store.recent_scans, 60)

    live = eng.live_arbs()
    by_kind: dict[str, int] = {}
    by_venue: dict[str, int] = {}
    by_zone: dict[str, int] = {}
    for a in live:
        by_kind[a.kind.value] = by_kind.get(a.kind.value, 0) + 1
        by_zone[a.zone] = by_zone.get(a.zone, 0) + 1
        for v in a.venues:
            by_venue[v] = by_venue.get(v, 0) + 1

    return {
        "stored": stats,
        "margin_histogram": hist,
        "recent_scans": list(reversed(scans)),
        "zones": {
            "active": eng.zones(),
            "enforced": settings.enforce_zone_pairing,
            "operator_jurisdiction": settings.operator_jurisdiction,
            "cross_zone_rejected": len(eng.cross_zone_rejected()),
        },
        "near_misses": [n.model_dump(mode="json") for n in eng.near_misses()[:15]],
        "live": {
            "count": len(live),
            "by_kind": by_kind,
            "by_venue": by_venue,
            "by_zone": by_zone,
            # Guaranteed profit is an arbitrage concept. A directional position
            # has no guarantee -- its worst case is losing the stake -- so it is
            # reported as capital at risk rather than folded into the total.
            # Summing the two is what put "profit available: -$72.68" on the
            # dashboard, one correlation row at -$156.46 swamping the rest.
            "total_profit_available": round(
                sum(a.worst_case_profit for a in live if a.strategy != "directional"), 2
            ),
            "directional_at_risk": round(
                sum(a.total_stake for a in live if a.strategy == "directional"), 2
            ),
            "directional_count": sum(1 for a in live if a.strategy == "directional"),
            "total_stake_required": round(sum(a.total_stake for a in live), 2),
            "avg_margin": round(
                sum(a.net_margin for a in live) / len(live), 5
            ) if live else 0.0,
            "avg_confidence": round(
                sum(a.confidence for a in live) / len(live), 1
            ) if live else 0.0,
        },
    }


class BacktestRequest(BaseModel):
    days: int = Field(30, ge=1, le=365)
    min_margin: float = Field(0.005, ge=0, le=1)
    max_margin: float = Field(0.05, ge=0, le=1)
    min_confidence: int = Field(0, ge=0, le=100)
    kinds: Optional[list[str]] = None
    void_rate: float = Field(0.02, ge=0, le=1)
    void_loss: float = Field(0.30, ge=0, le=1)
    stake_per_arb: Optional[float] = Field(None, gt=0)
    simulations: int = Field(400, ge=10, le=5000)


@app.post("/api/backtest", tags=["analytics"])
async def run_backtest(req: BacktestRequest) -> dict[str, Any]:
    """Replay stored opportunities under a void model (Part I s13.3)."""
    eng = _engine()
    params = BacktestParams(**req.model_dump())
    result = await asyncio.to_thread(replay, eng.store, params)
    return result.to_dict()


@app.post("/api/backtest/sweep", tags=["analytics"])
async def run_sweep(req: BacktestRequest) -> dict[str, Any]:
    """Sweep the minimum-margin floor to find where the edge actually peaks."""
    eng = _engine()
    base = BacktestParams(**req.model_dump())
    rows = await asyncio.to_thread(sweep, eng.store, (0.002, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03), base)
    return {"sweep": rows}


@app.get("/api/history", tags=["analytics"])
async def history(
    days: int = Query(7, ge=1, le=365),
    kind: Optional[str] = None,
    min_margin: float = 0.0,
    limit: int = Query(300, ge=1, le=2000),
) -> dict[str, Any]:
    eng = _engine()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await asyncio.to_thread(
        eng.store.recent_arbs, limit, kind, min_margin, since
    )
    out = []
    for r in rows:
        r = dict(r)
        r["legs"] = json.loads(r.pop("legs_json", "[]"))
        r["flags"] = json.loads(r.get("flags") or "[]")
        r["venues"] = json.loads(r.get("venues") or "[]")
        r.pop("payload_json", None)
        out.append(r)
    return {"count": len(out), "arbs": out}


# ------------------------------------------------------------- calculators


class StakeCalcRequest(BaseModel):
    """Standalone equal-profit calculator (Part I s3.2)."""

    decimal_odds: list[float] = Field(..., min_length=2)
    total_stake: float = Field(1000.0, gt=0)
    round_to: Optional[float] = None


@app.post("/api/calc/stakes", tags=["calculators"])
async def calc_stakes(req: StakeCalcRequest) -> dict[str, Any]:
    ds = req.decimal_odds
    if any(d <= 1.0 for d in ds):
        raise HTTPException(400, "decimal odds must all be greater than 1.0")

    b = om.book(ds)
    stakes = om.equal_profit_stakes(ds, req.total_stake)
    if req.round_to:
        stakes = [om.round_to_step(s, req.round_to) for s in stakes]
    total = sum(stakes)
    return {
        "book": round(b, 6),
        "is_arbitrage": b < 1.0,
        "margin": round(om.arb_margin(b), 6),
        "overround_pct": round((b - 1.0) * 100, 4),
        "vig_pct": round(om.vig(ds) * 100, 4),
        "implied_probs": [round(om.decimal_to_prob(d), 5) for d in ds],
        "fair_probs": [round(p, 5) for p in om.devig_proportional(ds)],
        "stakes": [round(s, 2) for s in stakes],
        "total_stake": round(total, 2),
        "payouts": [round(p, 2) for p in om.payouts(stakes, ds)],
        "profit_by_outcome": [round(p, 2) for p in om.profit_by_outcome(stakes, ds)],
        "worst_case_profit": round(om.worst_case_profit(stakes, ds), 2),
        "guaranteed_profit": round(om.guaranteed_profit(ds, total), 2),
    }


class KellyRequest(BaseModel):
    probability: float = Field(..., gt=0, lt=1)
    decimal_odds: float = Field(..., gt=1)
    bankroll: Optional[float] = None
    fraction: float = Field(0.25, gt=0, le=1)


@app.post("/api/calc/kelly", tags=["calculators"])
async def calc_kelly(req: KellyRequest) -> dict[str, Any]:
    """Kelly sizing for value bets (Part I s7.3 / s12)."""
    bankroll = req.bankroll or settings.bankroll
    f = om.kelly_fraction(req.probability, req.decimal_odds)
    return {
        "edge": round(om.expected_value(req.probability, req.decimal_odds), 5),
        "is_value_bet": om.is_value_bet(req.probability, req.decimal_odds),
        "kelly_fraction": round(f, 5),
        "kelly_stake": round(f * bankroll, 2),
        "fractional_kelly": round(f * req.fraction, 5),
        "fractional_stake": round(f * req.fraction * bankroll, 2),
        "fair_odds": round(1.0 / req.probability, 4),
        "bankroll": bankroll,
    }


class ConvertRequest(BaseModel):
    value: float
    from_format: str = Field(..., pattern="^(decimal|american|probability)$")


@app.post("/api/calc/convert", tags=["calculators"])
async def calc_convert(req: ConvertRequest) -> dict[str, Any]:
    """Odds format conversion (Part I s2.1).

    Bad input is the user's mistake, not the server's: every rejection here is a
    400 with the reason. `value: 0, from_format: "american"` used to divide by
    zero and return a 500.
    """
    try:
        if req.from_format == "decimal":
            d = req.value
        elif req.from_format == "american":
            d = om.american_to_decimal(req.value)
        else:
            if not 0 < req.value < 1:
                raise HTTPException(400, "probability must be between 0 and 1")
            d = om.prob_to_decimal(req.value)
        if d <= 1.0:
            raise HTTPException(400, "decimal odds must be greater than 1.0")
        american = round(om.decimal_to_american(d), 2)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "decimal": round(d, 5),
        "american": american,
        "probability": round(om.decimal_to_prob(d), 5),
        "contract_price": round(om.decimal_to_prob(d), 4),
    }


class VoidRequest(BaseModel):
    margin: float = Field(..., gt=0, lt=1)
    void_rate: float = Field(0.02, ge=0, le=1)
    void_loss: float = Field(0.30, ge=0, le=1)
    turnovers_per_year: float = Field(100.0, gt=0)


@app.post("/api/calc/void-adjusted", tags=["calculators"])
async def calc_void(req: VoidRequest) -> dict[str, Any]:
    """Effective margin and Kelly bound once voids are priced in (Part I s13)."""
    eff = om.margin_after_voids(req.margin, req.void_rate, req.void_loss)
    return {
        "nominal_margin": req.margin,
        "effective_margin": round(eff, 6),
        "edge_retained_pct": round(100.0 * eff / req.margin, 2) if req.margin else 0.0,
        **_kelly_arb_payload(req.margin, req.void_rate, req.void_loss),
        "annualised_simple": round(om.annualised_return(eff, req.turnovers_per_year), 4),
        "annualised_compounded": round(
            om.compounded_return(eff, req.turnovers_per_year), 4
        ),
    }


# ---------------------------------------------------------- correlation arb


class CorrelationCalcRequest(BaseModel):
    """Standalone calculator: no pair needs to be configured to use this."""

    p_a: float = Field(..., gt=0, lt=1)
    p_b: float = Field(..., gt=0, lt=1)
    p_joint_market: float = Field(..., gt=0, lt=1)
    rho_prior: float = Field(..., ge=-1, le=1)
    min_edge: float = Field(0.0, ge=0, le=1)


@app.post("/api/calc/correlation", tags=["calculators"])
async def calc_correlation(req: CorrelationCalcRequest) -> dict[str, Any]:
    """rho_impl, the fair joint price under rho_prior, and the BUY/SELL/HOLD read."""
    try:
        sig = ca.evaluate(
            req.p_a, req.p_b, req.p_joint_market, req.rho_prior, min_edge=req.min_edge
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "rho_impl": round(sig.rho_impl, 5),
        "rho_prior": sig.rho_prior,
        "fair_joint_price": round(sig.fair_joint_price, 5),
        "p_joint_market": sig.p_joint_market,
        "edge": round(sig.edge, 5),
        "edge_pct": round(sig.edge_pct, 3),
        "action": sig.action,
    }


class CorrelationPairRequest(BaseModel):
    """Registers a correlation-arb candidate: one venue, three markets.

    There is no automatic discovery of which markets share a joint contract,
    so this has to be entered by hand -- market_id/outcome for the two
    marginal events and for the "both happen" contract.
    """

    key: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(..., min_length=1)
    venue: str
    market_id_a: str
    outcome_a: str
    market_id_b: str
    outcome_b: str
    market_id_joint: str
    outcome_joint: str
    rho_prior_override: Optional[float] = Field(None, ge=-1, le=1)
    min_edge: Optional[float] = Field(None, ge=0, le=1)
    kelly_fraction: Optional[float] = Field(None, gt=0, le=1)
    enabled: bool = True


@app.get("/api/correlation/pairs", tags=["correlation"])
async def list_correlation_pairs() -> dict[str, Any]:
    eng = _engine()
    rows = await asyncio.to_thread(eng.store.list_correlation_pairs)
    return {"count": len(rows), "pairs": rows}


@app.post("/api/correlation/pairs", tags=["correlation"])
async def upsert_correlation_pair(req: CorrelationPairRequest) -> dict[str, Any]:
    eng = _engine()
    await asyncio.to_thread(eng.store.upsert_correlation_pair, req.model_dump())
    pair = await asyncio.to_thread(eng.store.get_correlation_pair, req.key)
    return {"ok": True, "pair": pair}


@app.delete("/api/correlation/pairs/{key}", tags=["correlation"])
async def delete_correlation_pair(key: str) -> dict[str, Any]:
    eng = _engine()
    await asyncio.to_thread(eng.store.delete_correlation_pair, key)
    return {"ok": True}


@app.get("/api/correlation/pairs/{key}/preview", tags=["correlation"])
async def preview_correlation_pair(key: str) -> dict[str, Any]:
    """Evaluate a pair against the current tape without gating on min_edge/confidence.

    Lets an operator sanity-check a pair (are the three markets actually
    resolving on the tape? what does rho_impl look like right now?) before
    trusting it to fire live.
    """
    eng = _engine()
    pair = await asyncio.to_thread(eng.store.get_correlation_pair, key)
    if pair is None:
        raise HTTPException(404, "no such pair")
    # min_edge=0 so a real mismatch still surfaces as BUY/SELL rather than HOLD.
    preview_pair = {**pair, "min_edge": 0.0}
    arb = await asyncio.to_thread(
        evaluate_pair, preview_pair, eng.live_events(), eng.store, eng.venue_limits
    )
    return {"pair": pair, "would_trade": arb.model_dump(mode="json") if arb else None}


class CorrelationOutcomeRequest(BaseModel):
    """One real, resolved instance of a pair -- e.g. one past election cycle."""

    label: str = Field(..., min_length=1)
    outcome_a: bool
    outcome_b: bool


@app.get("/api/correlation/pairs/{key}/outcomes", tags=["correlation"])
async def list_correlation_outcomes(key: str) -> dict[str, Any]:
    eng = _engine()
    if await asyncio.to_thread(eng.store.get_correlation_pair, key) is None:
        raise HTTPException(404, "no such pair")
    rows = await asyncio.to_thread(eng.store.list_correlation_outcomes, key)
    rho = None
    if len(rows) >= 2:
        rho = ca.estimate_rho_prior_from_outcomes(
            [int(r["outcome_a"]) for r in rows], [int(r["outcome_b"]) for r in rows]
        )
    return {"count": len(rows), "outcomes": rows, "rho_prior_from_history": rho}


@app.post("/api/correlation/pairs/{key}/outcomes", tags=["correlation"])
async def add_correlation_outcome(key: str, req: CorrelationOutcomeRequest) -> dict[str, Any]:
    eng = _engine()
    if await asyncio.to_thread(eng.store.get_correlation_pair, key) is None:
        raise HTTPException(404, "no such pair")
    row_id = await asyncio.to_thread(
        eng.store.add_correlation_outcome, key, req.label, req.outcome_a, req.outcome_b
    )
    return {"ok": True, "id": row_id}


@app.delete("/api/correlation/outcomes/{outcome_id}", tags=["correlation"])
async def delete_correlation_outcome(outcome_id: int) -> dict[str, Any]:
    eng = _engine()
    await asyncio.to_thread(eng.store.delete_correlation_outcome, outcome_id)
    return {"ok": True}


# ------------------------------------------------------------------ control


@app.post("/api/scanner/scan", tags=["system"])
async def force_scan() -> dict[str, Any]:
    eng = _engine()
    found = await eng.scan_once()
    return {
        "ok": True,
        "new_arbs": len(found),
        "stats": eng.last_scan.model_dump(mode="json") if eng.last_scan else None,
    }


@app.post("/api/scanner/start", tags=["system"])
async def start_scanner() -> dict[str, Any]:
    await _engine().start()
    return {"ok": True, "running": True}


@app.post("/api/scanner/stop", tags=["system"])
async def stop_scanner() -> dict[str, Any]:
    await _engine().stop()
    return {"ok": True, "running": False}


@app.post("/api/scanner/reset-breaker", tags=["system"])
async def reset_breaker() -> dict[str, Any]:
    _engine().breaker.reset()
    return {"ok": True}


# ---------------------------------------------------------------- websocket


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Live push of new opportunities and scan telemetry."""
    await ws.accept()
    eng = _engine()
    queue = eng.alerts.broadcaster.subscribe()
    try:
        await ws.send_json(
            {
                "type": "snapshot",
                "data": {
                    "status": eng.status().model_dump(mode="json"),
                    "live": [a.model_dump(mode="json") for a in eng.live_arbs()],
                    "near_misses": [
                        n.model_dump(mode="json") for n in eng.near_misses()[:20]
                    ],
                },
            }
        )
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=25.0)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
                continue
            await ws.send_json(msg)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"websocket closed: {exc}")
    finally:
        eng.alerts.broadcaster.unsubscribe(queue)
