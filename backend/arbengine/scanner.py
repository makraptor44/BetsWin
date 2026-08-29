"""The scanner (Part II s9).

Orchestrates the six-stage pipeline: fetch -> normalise -> detect -> size ->
alert -> track. Two details are load-bearing:

Two-pass detection. A first pass runs over cheap top-of-book data from the
catalogue endpoints. Only events whose book is already close to the arbitrage
threshold get an order-book fetch, and the detectors then re-run over the
enriched snapshot. Depth calls are the expensive part of a cycle (Part II s17.1),
so this spends them where they can change an answer.

Circuit breaker. If a burst of implausibly fat margins appears, something is
wrong -- a mis-parsed title, a stale feed, two different lines being compared --
and the correct response is to halt and page a human rather than to alert on
dozens of phantom opportunities (Part II s16.4).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from loguru import logger

from .alerts import AlertManager
from .config import settings
from .correlation_detector import scan_correlation_pairs
from .detector import candidate_events, scan
from .models import Arb, ArbKind, EngineStatus, Event, NearMiss, ScanStats, utcnow
from .sources import (
    BetfairSource,
    KalshiSource,
    OddsAPISource,
    PolymarketSource,
    SmarketsSource,
    Source,
)
from .storage import ArbStore
from .venues import Zone, zone_of


class CircuitBreaker:
    """Trips when too many implausible margins arrive at once (Part II s16.4)."""

    def __init__(
        self,
        threshold: Optional[int] = None,
        window_seconds: Optional[int] = None,
        min_margin: Optional[float] = None,
    ):
        self.threshold = threshold or settings.breaker_threshold
        self.window = window_seconds or settings.breaker_window_seconds
        self.min_margin = min_margin if min_margin is not None else settings.breaker_min_margin
        self._events: deque[datetime] = deque()
        self.tripped = False
        self.reason: Optional[str] = None

    def record(self, arb: Arb) -> bool:
        if arb.net_margin < self.min_margin:
            return self.tripped
        now = utcnow()
        cutoff = now - timedelta(seconds=self.window)
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        self._events.append(now)
        if len(self._events) >= self.threshold:
            self.tripped = True
            self.reason = (
                f"{len(self._events)} opportunities above "
                f"{self.min_margin * 100:.0f}% in {self.window}s - the feed or the "
                f"matcher is probably wrong, not the market."
            )
            logger.critical(f"CIRCUIT BREAKER TRIPPED: {self.reason}")
        return self.tripped

    def reset(self) -> None:
        self._events.clear()
        self.tripped = False
        self.reason = None


class Scanner:
    """Polls every enabled venue, detects, sizes, persists and alerts."""

    def __init__(
        self,
        store: Optional[ArbStore] = None,
        alerts: Optional[AlertManager] = None,
        sources: Optional[Sequence[Source]] = None,
    ):
        self.store = store or ArbStore(settings.database_path)
        self.alerts = alerts or AlertManager()
        self.sources: list[Source] = list(sources) if sources is not None else self._build_sources()
        self.breaker = CircuitBreaker()

        if settings.demo_mode:
            self._seed_demo_correlation_pair()

        self._seen: dict[str, datetime] = {}
        self._live: dict[str, Arb] = {}
        self._events: list[Event] = []
        self._near_misses: list[NearMiss] = []
        self._cross_zone_rejected: list[str] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._started_at = time.monotonic()
        self._next_scan_at = 0.0
        self.last_scan: Optional[ScanStats] = None
        self.total_detected = 0
        self.venue_limits: dict[str, float] = {}

    def _seed_demo_correlation_pair(self) -> None:
        """Demo mode gets one correlation-arb pair pre-configured, matching the
        triple of markets in `demo_data.demo_events` -- otherwise the feature
        would be invisible in demo mode, since pairs are never auto-discovered.
        """
        from .demo_data import demo_correlation_outcomes, demo_correlation_pair

        pair = demo_correlation_pair()
        self.store.upsert_correlation_pair(pair)
        if not self.store.list_correlation_outcomes(pair["key"]):
            for label, outcome_a, outcome_b in demo_correlation_outcomes():
                self.store.add_correlation_outcome(pair["key"], label, outcome_a, outcome_b)

    @staticmethod
    def _build_sources() -> list[Source]:
        """Only sources that can actually be read.

        A venue that needs credentials it does not have is left out entirely
        rather than added and allowed to fail every cycle: an empty feed and a
        broken feed look identical downstream, and only one of them is worth
        alerting about.
        """
        out: list[Source] = []
        if settings.enable_polymarket:
            out.append(PolymarketSource())
        if settings.enable_kalshi:
            out.append(KalshiSource())
        if settings.odds_api_enabled:
            out.append(OddsAPISource())
        if settings.enable_smarkets:
            out.append(SmarketsSource())
        if settings.betfair_enabled:
            out.append(BetfairSource())
        elif settings.enable_betfair:
            logger.warning(
                "betfair is enabled but has no app key and no credentials to "
                "obtain a session -- the source will stay dark"
            )
        return out

    def zones(self) -> list[str]:
        """Execution zones with at least one live feed behind them.

        Demo mode reads its zones off the fixture tape rather than the source
        list, because the fixtures cover venues no live source is configured
        for -- that is the point of them.
        """
        names: Iterable[str]
        if settings.demo_mode and self._events:
            names = {ev.venue for ev in self._events}
        else:
            names = [s.name for s in self.sources]
        seen: list[str] = []
        for name in names:
            z = zone_of(name)
            if z is not Zone.UNKNOWN and z.value not in seen:
                seen.append(z.value)
        return sorted(seen)

    # ------------------------------------------------------------- accessors

    @property
    def running(self) -> bool:
        return self._running

    def live_arbs(self) -> list[Arb]:
        """Currently open opportunities, best risk-adjusted edge first."""
        return sorted(
            self._live.values(),
            key=lambda a: a.net_margin * (a.confidence / 100.0),
            reverse=True,
        )

    def live_events(self) -> list[Event]:
        return self._events

    def near_misses(self) -> list[NearMiss]:
        """Tightest books from the last cycle, closest to crossing first."""
        return self._near_misses

    def cross_zone_rejected(self) -> list[str]:
        """Venue pairs the zone rule declined to compare, with reasons."""
        return self._cross_zone_rejected

    def get_arb(self, arb_id: str) -> Optional[Arb]:
        return self._live.get(arb_id)

    def status(self) -> EngineStatus:
        return EngineStatus(
            running=self._running,
            demo_mode=settings.demo_mode,
            last_scan=self.last_scan,
            next_scan_in=max(0.0, self._next_scan_at - time.monotonic()),
            poll_interval=settings.poll_interval_seconds,
            live_arbs=len(self._live),
            total_detected=self.total_detected,
            uptime_seconds=time.monotonic() - self._started_at,
            sources={s.name: s.healthy for s in self.sources},
            breaker_tripped=self.breaker.tripped,
            breaker_reason=self.breaker.reason,
            zones=self.zones(),
            operator_jurisdiction=settings.operator_jurisdiction,
            enforce_zone_pairing=settings.enforce_zone_pairing,
            near_misses=len(self._near_misses),
        )

    # -------------------------------------------------------------- dedupe

    def _is_new(self, arb: Arb) -> bool:
        key = arb.dedupe_key()
        now = arb.detected_at
        prev = self._seen.get(key)
        window = timedelta(seconds=settings.dedup_window_seconds)
        self._seen[key] = now
        if prev is not None and now - prev < window:
            return False
        cutoff = now - window
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        return True

    # ---------------------------------------------------------------- fetch

    async def _fetch_all(self, stats: ScanStats) -> list[Event]:
        if settings.demo_mode:
            from .demo_data import demo_events

            events = demo_events()
            for ev in events:
                stats.by_venue[ev.venue] = stats.by_venue.get(ev.venue, 0) + 1
            return events

        results = await asyncio.gather(
            *(s.safe_fetch() for s in self.sources), return_exceptions=True
        )
        events: list[Event] = []
        for source, res in zip(self.sources, results):
            if isinstance(res, BaseException):
                stats.errors.append(f"{source.name}: {res}")
                continue
            stats.by_venue[source.name] = len(res)
            events.extend(res)
            if source.last_error:
                stats.errors.append(f"{source.name}: {source.last_error}")
        return events

    async def _enrich(self, events: list[Event]) -> list[Event]:
        """Fetch real depth for the shortlist, keeping everything else as-is."""
        shortlist = candidate_events(events)
        if not shortlist:
            return events
        logger.debug(f"scanner: enriching {len(shortlist)} candidate events with depth")

        by_venue: dict[str, list[Event]] = {}
        for ev in shortlist:
            by_venue.setdefault(ev.venue, []).append(ev)

        enriched: dict[str, Event] = {}
        for source in self.sources:
            batch = by_venue.get(source.name)
            if not batch:
                continue
            try:
                for ev in await source.enrich(batch):
                    enriched[ev.id] = ev
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"scanner: enrichment failed for {source.name} -- {exc}")

        return [enriched.get(ev.id, ev) for ev in events]

    # ----------------------------------------------------------------- scan

    async def scan_once(self) -> list[Arb]:
        stats = ScanStats()
        t0 = time.monotonic()

        events = await self._fetch_all(stats)
        stats.events_scanned = len(events)
        stats.markets_scanned = sum(len(e.markets) for e in events)
        stats.quotes_scanned = sum(
            len(o.quotes) for e in events for m in e.markets for o in m.outcomes
        )

        # Pass 1 on top-of-book, then re-run over enriched depth.
        events = await self._enrich(events)
        self._events = events

        result = await asyncio.to_thread(
            scan, events, settings.default_stake, self.venue_limits
        )
        correlation_arbs = await asyncio.to_thread(
            scan_correlation_pairs, events, self.store, self.venue_limits
        )
        found = result.arbs + correlation_arbs
        self._near_misses = result.near_misses
        self._cross_zone_rejected = result.cross_zone_rejected

        fresh: list[Arb] = []
        for arb in found:
            if self.breaker.record(arb) and settings.demo_mode is False:
                stats.breaker_tripped = True
                break
            existing = self._live.get(arb.id)
            if existing is not None:
                arb = arb.model_copy(
                    update={"detected_at": existing.detected_at, "last_seen": utcnow()}
                )
            self._live[arb.id] = arb
            if self._is_new(arb):
                fresh.append(arb)

        # Retire opportunities that no longer price as arbs.
        current_ids = {a.id for a in found}
        for gone in [k for k in self._live if k not in current_ids]:
            self._live.pop(gone, None)

        for arb in fresh:
            try:
                await asyncio.to_thread(self.store.upsert_arb, arb)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"scanner: persist failed -- {exc}")
            await self.alerts.dispatch(arb)
            logger.success(arb.summary())

        await self._record_prices(events)

        stats.arbs_found = len(found)
        stats.new_arbs = len(fresh)
        stats.near_misses = len(result.near_misses)
        stats.tightest_gap_bps = result.tightest_gap_bps
        stats.cross_zone_rejected = len(result.cross_zone_rejected)
        by_zone: dict[str, int] = {}
        for ev in events:
            z = zone_of(ev.venue)
            by_zone[z.value] = by_zone.get(z.value, 0) + 1
        stats.by_zone = by_zone
        stats.finished_at = utcnow()
        stats.duration_seconds = round(time.monotonic() - t0, 3)
        self.last_scan = stats
        self.total_detected += len(fresh)

        try:
            await asyncio.to_thread(self.store.record_scan, stats)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"scanner: scan telemetry not saved -- {exc}")

        # The dashboard is driven entirely by this frame. It carries near misses
        # as well as opportunities so a cycle that finds nothing still moves
        # something on screen -- otherwise a working scanner and a hung one look
        # exactly alike from the browser.
        await self.alerts.publish(
            {
                "type": "scan",
                "data": {
                    "stats": stats.model_dump(mode="json"),
                    "status": self.status().model_dump(mode="json"),
                    "live": [a.model_dump(mode="json") for a in self.live_arbs()],
                    "near_misses": [
                        n.model_dump(mode="json") for n in self._near_misses[:20]
                    ],
                },
            }
        )
        tightest = (
            f", tightest book {stats.tightest_gap_bps:+.0f} bps from crossing"
            if stats.tightest_gap_bps is not None
            else ""
        )
        logger.info(
            f"scan complete: {stats.events_scanned} events, {stats.arbs_found} arbs "
            f"({stats.new_arbs} new), {stats.near_misses} near misses"
            f"{tightest} in {stats.duration_seconds}s"
        )
        return fresh

    async def _record_prices(self, events: Sequence[Event]) -> None:
        """Snapshot best prices so slow venues can be identified later."""
        rows: list[tuple[str, str, str, float]] = []
        for ev in events[:400]:
            for market in ev.markets:
                for outcome in market.outcomes:
                    q = outcome.best()
                    if q is not None:
                        rows.append((q.venue, q.market_id, q.outcome, q.price))
        if rows:
            try:
                await asyncio.to_thread(self.store.record_prices, rows)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"scanner: price history not saved -- {exc}")

    # ------------------------------------------------------------ lifecycle

    async def _loop(self) -> None:
        logger.info(
            f"scanner starting: sources={[s.name for s in self.sources]}, "
            f"interval={settings.poll_interval_seconds}s, demo={settings.demo_mode}"
        )
        cycles = 0
        while self._running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                logger.exception(f"scan cycle failed: {exc}")

            cycles += 1
            if cycles % 40 == 0:
                try:
                    await asyncio.to_thread(self.store.prune, settings.retention_days)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"scanner: prune failed -- {exc}")

            self._next_scan_at = time.monotonic() + settings.poll_interval_seconds
            try:
                await asyncio.sleep(settings.poll_interval_seconds)
            except asyncio.CancelledError:
                raise

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started_at = time.monotonic()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        logger.info("scanner stopped")

    async def close(self) -> None:
        await self.stop()
        for source in self.sources:
            await source.close()
        await self.alerts.close()
        self.store.close()
