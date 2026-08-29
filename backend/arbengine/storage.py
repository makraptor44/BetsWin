"""Persistence (Part II s14).

Every candidate is logged. The value is in three places: reconciling expected
against realised P&L, quantifying void rates per venue, and debugging the
detector when it produces false positives.

SQLite is accessed from a thread pool rather than the event loop, so a slow
write never stalls a scan. `check_same_thread=False` plus a lock keeps a single
connection safe across the executor's threads.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from loguru import logger

from .models import Arb, ArbKind, ScanStats

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS arbs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    arb_key           TEXT NOT NULL,
    kind              TEXT NOT NULL,
    title             TEXT NOT NULL,
    category          TEXT NOT NULL DEFAULT 'other',
    venues            TEXT NOT NULL,
    zone              TEXT NOT NULL DEFAULT 'unknown',
    currency          TEXT NOT NULL DEFAULT 'USD',
    market_key        TEXT NOT NULL,
    detected_at       TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    close_time        TEXT,
    book              REAL NOT NULL,
    margin            REAL NOT NULL,
    net_margin        REAL NOT NULL,
    total_stake       REAL NOT NULL,
    profit            REAL NOT NULL,
    worst_case_profit REAL NOT NULL,
    max_stake         REAL NOT NULL DEFAULT 0,
    confidence        INTEGER NOT NULL,
    flags             TEXT NOT NULL DEFAULT '[]',
    legs_json         TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    placed            INTEGER NOT NULL DEFAULT 0,
    settled           INTEGER NOT NULL DEFAULT 0,
    settlement_type   TEXT,
    settled_at        TEXT,
    realised_pnl      REAL
);
CREATE INDEX IF NOT EXISTS ix_arbs_detected ON arbs(detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_arbs_key      ON arbs(arb_key);
CREATE INDEX IF NOT EXISTS ix_arbs_kind     ON arbs(kind);

CREATE TABLE IF NOT EXISTS placements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    arb_id          INTEGER NOT NULL REFERENCES arbs(id),
    venue           TEXT NOT NULL,
    market_id       TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    side            TEXT NOT NULL,
    requested_price REAL NOT NULL,
    requested_stake REAL NOT NULL,
    executed_price  REAL,
    executed_stake  REAL,
    external_ref    TEXT,
    status          TEXT NOT NULL,
    placed_at       TEXT NOT NULL,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS ix_placements_arb ON placements(arb_id);

CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    duration        REAL NOT NULL,
    events_scanned  INTEGER NOT NULL,
    markets_scanned INTEGER NOT NULL,
    quotes_scanned  INTEGER NOT NULL,
    arbs_found      INTEGER NOT NULL,
    new_arbs        INTEGER NOT NULL,
    errors          TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_scans_started ON scans(started_at DESC);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    venue       TEXT NOT NULL,
    market_id   TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    price       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_price_market ON price_history(venue, market_id, recorded_at DESC);
"""


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


class ArbStore:
    """Thread-safe SQLite store for arbs, placements and scan telemetry."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.commit()
        logger.info(f"storage: using {self.path}")

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _migrate(self) -> None:
        """Add columns a pre-existing database is missing.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a database written before execution zones would silently
        keep the old shape and every insert would fail on the new columns.
        Callers hold `self._lock`.
        """
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(arbs)")}
        added = False
        for column, ddl in (
            ("zone", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("currency", "TEXT NOT NULL DEFAULT 'USD'"),
            ("settlement_type", "TEXT"),
            ("settled_at", "TEXT"),
        ):
            if column not in have:
                self.conn.execute(f"ALTER TABLE arbs ADD COLUMN {column} {ddl}")
                logger.info(f"storage: added arbs.{column}")
                added = True
        if added:
            self._backfill_zones()

    def _backfill_zones(self) -> None:
        """Derive zone and currency for rows written before those columns.

        The zone of an existing row is not unknown -- it is fully determined by
        the venues already stored on it. Leaving history as 'unknown' would put
        a meaningless bucket at the top of every zone breakdown for as long as
        the retention window lasts.
        """
        from .venues import venue as venue_info, zone_for_venues

        rows = self.conn.execute(
            "SELECT id, venues FROM arbs WHERE zone = 'unknown'"
        ).fetchall()
        patched = 0
        for row in rows:
            try:
                names = json.loads(row["venues"]) or []
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not names:
                continue
            zone = zone_for_venues(names)
            self.conn.execute(
                "UPDATE arbs SET zone = ?, currency = ? WHERE id = ?",
                (zone.value, venue_info(names[0]).currency or "USD", row["id"]),
            )
            patched += 1
        if patched:
            logger.info(f"storage: backfilled zone on {patched} historical rows")

    # ------------------------------------------------------------- internals

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return int(cur.lastrowid or 0)

    # ------------------------------------------------------------------ arbs

    def upsert_arb(self, arb: Arb) -> int:
        """Insert a new arb, or refresh `last_seen` if it is the same opportunity.

        Deduping on the leg signature means a price that persists across cycles
        is one row with a moving `last_seen`, not a thousand near-duplicates.
        """
        key = arb.dedupe_key()
        existing = self._rows(
            "SELECT id FROM arbs WHERE arb_key = ? ORDER BY id DESC LIMIT 1", (key,)
        )
        if existing:
            arb_id = int(existing[0]["id"])
            self._exec(
                "UPDATE arbs SET last_seen = ?, net_margin = ?, confidence = ? WHERE id = ?",
                (_iso(arb.last_seen), arb.net_margin, arb.confidence, arb_id),
            )
            return arb_id

        legs = [l.model_dump(mode="json") for l in arb.legs]
        return self._exec(
            """INSERT INTO arbs
               (arb_key, kind, title, category, venues, zone, currency,
                market_key, detected_at,
                last_seen, close_time, book, margin, net_margin, total_stake,
                profit, worst_case_profit, max_stake, confidence, flags,
                legs_json, payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key,
                arb.kind.value,
                arb.title,
                arb.category,
                json.dumps(list(arb.venues)),
                arb.zone,
                arb.currency,
                arb.market_key,
                _iso(arb.detected_at),
                _iso(arb.last_seen),
                _iso(arb.close_time),
                arb.book,
                arb.margin,
                arb.net_margin,
                arb.total_stake,
                arb.profit,
                arb.worst_case_profit,
                arb.max_stake_available,
                arb.confidence,
                json.dumps([f.value for f in arb.flags]),
                json.dumps(legs),
                arb.model_dump_json(),
            ),
        )

    def recent_arbs(
        self,
        limit: int = 200,
        kind: Optional[str] = None,
        min_margin: float = 0.0,
        since: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM arbs WHERE net_margin >= ?"
        params: list[Any] = [min_margin]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if since:
            sql += " AND detected_at >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, params)

    def arb_by_id(self, arb_id: int) -> Optional[dict[str, Any]]:
        rows = self._rows("SELECT * FROM arbs WHERE id = ?", (arb_id,))
        return rows[0] if rows else None

    def mark_placed(self, arb_id: int, placed: bool = True) -> None:
        self._exec("UPDATE arbs SET placed = ? WHERE id = ?", (1 if placed else 0, arb_id))

    def settle(
        self,
        arb_id: int,
        realised_pnl: float,
        settlement_type: str = "resolution",
        settled_at: Optional[datetime] = None,
    ) -> None:
        dt = (settled_at or datetime.now(timezone.utc)).isoformat()
        self._exec(
            "UPDATE arbs SET settled = 1, realised_pnl = ?, settlement_type = ?, settled_at = ? WHERE id = ?",
            (realised_pnl, settlement_type, dt, arb_id),
        )

    # ------------------------------------------------------------ placements

    def record_placement(
        self,
        arb_id: int,
        venue: str,
        market_id: str,
        outcome: str,
        side: str,
        requested_price: float,
        requested_stake: float,
        status: str = "logged",
        executed_price: Optional[float] = None,
        executed_stake: Optional[float] = None,
        external_ref: Optional[str] = None,
        note: Optional[str] = None,
    ) -> int:
        return self._exec(
            """INSERT INTO placements
               (arb_id, venue, market_id, outcome, side, requested_price,
                requested_stake, executed_price, executed_stake, external_ref,
                status, placed_at, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                arb_id,
                venue,
                market_id,
                outcome,
                side,
                requested_price,
                requested_stake,
                executed_price,
                executed_stake,
                external_ref,
                status,
                datetime.now(timezone.utc).isoformat(),
                note,
            ),
        )

    def placements_for(self, arb_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM placements WHERE arb_id = ? ORDER BY id", (arb_id,)
        )

    def open_positions(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM arbs WHERE placed = 1 AND settled = 0 ORDER BY detected_at DESC"
        )

    def all_positions(self, limit: int = 100, settled: Optional[bool] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM arbs WHERE placed = 1"
        params: list[Any] = []
        if settled is not None:
            sql += " AND settled = ?"
            params.append(1 if settled else 0)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, params)

    # ------------------------------------------------------------------ scans

    def record_scan(self, stats: ScanStats) -> int:
        return self._exec(
            """INSERT INTO scans
               (started_at, duration, events_scanned, markets_scanned,
                quotes_scanned, arbs_found, new_arbs, errors)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                _iso(stats.started_at),
                stats.duration_seconds,
                stats.events_scanned,
                stats.markets_scanned,
                stats.quotes_scanned,
                stats.arbs_found,
                stats.new_arbs,
                json.dumps(stats.errors),
            ),
        )

    def recent_scans(self, limit: int = 60) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM scans ORDER BY started_at DESC LIMIT ?", (limit,)
        )

    # -------------------------------------------------------- price history

    def record_prices(self, rows: Sequence[tuple[str, str, str, float]]) -> None:
        """Log price points so slow venues can be identified later (Part II s20.3)."""
        if not rows:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.executemany(
                """INSERT INTO price_history (recorded_at, venue, market_id, outcome, price)
                   VALUES (?,?,?,?,?)""",
                [(now, *r) for r in rows],
            )
            self.conn.commit()

    def price_history(self, venue: str, market_id: str, limit: int = 500) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT * FROM price_history WHERE venue = ? AND market_id = ?
               ORDER BY recorded_at DESC LIMIT ?""",
            (venue, market_id, limit),
        )

    # ------------------------------------------------------------- analytics

    def stats(self, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        totals = self._rows(
            """SELECT COUNT(*) n, AVG(net_margin) avg_margin, MAX(net_margin) max_margin,
                      SUM(total_stake) turnover, SUM(worst_case_profit) profit,
                      AVG(confidence) avg_conf
               FROM arbs WHERE detected_at >= ?""",
            (since,),
        )
        by_kind = self._rows(
            """SELECT kind, COUNT(*) n, AVG(net_margin) avg_margin,
                      SUM(worst_case_profit) profit
               FROM arbs WHERE detected_at >= ? GROUP BY kind ORDER BY n DESC""",
            (since,),
        )
        by_venue: dict[str, int] = {}
        for row in self._rows(
            "SELECT venues FROM arbs WHERE detected_at >= ?", (since,)
        ):
            for v in json.loads(row["venues"]):
                by_venue[v] = by_venue.get(v, 0) + 1
        # Zone-level performance is the question the pairing rule creates: is
        # the edge coming from the USD contract venues or the sterling
        # exchanges? Kept as its own aggregate rather than derived from venues,
        # because a leg set belongs to exactly one zone by construction.
        by_zone = self._rows(
            """SELECT zone, COUNT(*) n, AVG(net_margin) avg_margin,
                      SUM(total_stake) turnover, SUM(worst_case_profit) profit
               FROM arbs WHERE detected_at >= ? GROUP BY zone ORDER BY n DESC""",
            (since,),
        )
        by_day = self._rows(
            """SELECT substr(detected_at, 1, 10) day, COUNT(*) n,
                      AVG(net_margin) avg_margin, SUM(worst_case_profit) profit
               FROM arbs WHERE detected_at >= ?
               GROUP BY day ORDER BY day""",
            (since,),
        )
        settled = self._rows(
            """SELECT COUNT(*) n, SUM(realised_pnl) pnl FROM arbs
               WHERE settled = 1 AND detected_at >= ?""",
            (since,),
        )
        head = totals[0] if totals else {}
        return {
            "window_days": days,
            "total_detected": head.get("n") or 0,
            "avg_margin": head.get("avg_margin") or 0.0,
            "max_margin": head.get("max_margin") or 0.0,
            "avg_confidence": head.get("avg_conf") or 0.0,
            "theoretical_turnover": head.get("turnover") or 0.0,
            "theoretical_profit": head.get("profit") or 0.0,
            "settled_count": (settled[0].get("n") if settled else 0) or 0,
            "realised_pnl": (settled[0].get("pnl") if settled else 0.0) or 0.0,
            "by_kind": by_kind,
            "by_venue": by_venue,
            "by_zone": by_zone,
            "by_day": by_day,
        }

    def margin_histogram(self, days: int = 30, buckets: int = 12) -> list[dict[str, Any]]:
        """Distribution of margins -- the empirical version of Part I s8.1."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._rows(
            "SELECT net_margin FROM arbs WHERE detected_at >= ?", (since,)
        )
        if not rows:
            return []
        width = 0.005
        hist: dict[int, int] = {}
        for r in rows:
            idx = min(int((r["net_margin"] or 0.0) / width), buckets - 1)
            hist[idx] = hist.get(idx, 0) + 1
        return [
            {
                "from": round(i * width, 4),
                "to": round((i + 1) * width, 4),
                "count": hist.get(i, 0),
            }
            for i in range(buckets)
        ]

    def prune(self, days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        removed = self._exec("DELETE FROM price_history WHERE recorded_at < ?", (cutoff,))
        self._exec("DELETE FROM scans WHERE started_at < ?", (cutoff,))
        self._exec(
            "DELETE FROM arbs WHERE detected_at < ? AND placed = 0", (cutoff,)
        )
        return removed

    def close(self) -> None:
        with self._lock:
            self.conn.close()


class AsyncArbStore:
    """Thin async wrapper so the scanner never blocks the event loop on disk IO."""

    def __init__(self, path: str):
        self._store = ArbStore(path)

    @property
    def sync(self) -> ArbStore:
        return self._store

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def __getattr__(self, name: str):
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        async def _wrapper(*args, **kwargs):
            return await asyncio.to_thread(attr, *args, **kwargs)

        return _wrapper
