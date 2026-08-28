"""Alerting (Part II s10).

For anything placed by hand, a push notification within a second of detection is
the difference between catching the opportunity and watching it evaporate. Two
channels are wired here: Telegram, and an in-process broadcaster the web UI
subscribes to over a WebSocket.

Sending is fire-and-forget from the scanner's point of view (Part II s17.1) --
a slow Telegram round trip must never delay the next cycle.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable, Optional

import httpx
from loguru import logger

from .config import settings
from .models import Arb

_TELEGRAM_BASE = "https://api.telegram.org"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramAlerter:
    """Telegram bot notifier with per-chat rate limiting (1 msg/sec)."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.bot_token = bot_token if bot_token is not None else settings.telegram_bot_token
        self.chat_id = chat_id if chat_id is not None else settings.telegram_chat_id
        self._client = client or httpx.AsyncClient(timeout=8.0)
        self._last_sent = 0.0
        self._lock = asyncio.Lock()
        self.sent_count = 0
        self.last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, text: str, silent: bool = False) -> bool:
        if not self.enabled:
            return False
        async with self._lock:
            # Telegram allows one message per second per chat.
            wait = 1.05 - (time.monotonic() - self._last_sent)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_sent = time.monotonic()
        try:
            resp = await self._client.post(
                f"{_TELEGRAM_BASE}/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_notification": silent,
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            self.sent_count += 1
            self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.warning(f"telegram: send failed -- {exc}")
            return False

    async def send_arb(self, arb: Arb) -> bool:
        legs = "\n".join(
            f"  • <b>{_escape(l.outcome)}</b> @ <code>{l.price:.3f}</code> "
            f"({_escape(l.venue)}) → ${l.stake:,.2f} "
            f"[{l.contracts:,.0f} contracts]"
            for l in arb.legs
        )
        flags = ", ".join(f.value for f in arb.flags)
        text = (
            f"<b>{arb.kind.value.upper()} {arb.net_margin * 100:.2f}%</b>\n"
            f"{_escape(arb.title[:140])}\n"
            f"{legs}\n"
            f"Stake ${arb.total_stake:,.2f} → profit ${arb.worst_case_profit:,.2f} "
            f"({arb.roi_pct:.2f}%)\n"
            f"Confidence {arb.confidence}/100"
            + (f"\n⚠ {_escape(flags)}" if flags else "")
        )
        return await self.send(text)

    async def close(self) -> None:
        await self._client.aclose()


Subscriber = Callable[[dict[str, Any]], Awaitable[None]]


class Broadcaster:
    """In-process pub/sub feeding the dashboard's WebSocket.

    Each subscriber gets a bounded queue. A client that stops draining is dropped
    rather than allowed to grow unbounded and take the process with it.
    """

    def __init__(self, maxsize: int = 64):
        self._queues: set[asyncio.Queue] = set()
        self._maxsize = maxsize
        self._history: deque[dict[str, Any]] = deque(maxlen=50)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    async def publish(self, message: dict[str, Any]) -> None:
        self._history.append(message)
        dead: list[asyncio.Queue] = []
        for q in self._queues:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            logger.debug("broadcaster: dropping a subscriber that stopped reading")
            self._queues.discard(q)


class AlertManager:
    """Fans one detected arb out to every configured channel.

    Only opportunities that clear both the margin and confidence floors are
    pushed to a phone; everything else stays in the dashboard. Alert fatigue is
    what makes an operator stop reading alerts.
    """

    def __init__(self, broadcaster: Optional[Broadcaster] = None):
        self.telegram = TelegramAlerter()
        self.broadcaster = broadcaster or Broadcaster()
        self.alerted: set[str] = set()

    def should_alert(self, arb: Arb) -> bool:
        if arb.dedupe_key() in self.alerted:
            return False
        return (
            arb.net_margin >= settings.alert_min_margin
            and arb.confidence >= settings.alert_min_confidence
        )

    async def dispatch(self, arb: Arb) -> None:
        await self.broadcaster.publish({"type": "arb", "data": arb.model_dump(mode="json")})
        if not self.should_alert(arb):
            return
        self.alerted.add(arb.dedupe_key())
        if self.telegram.enabled:
            # Fire and forget: never block the scan loop on a network round trip.
            asyncio.create_task(self.telegram.send_arb(arb))

    async def publish(self, message: dict[str, Any]) -> None:
        await self.broadcaster.publish(message)

    async def close(self) -> None:
        await self.telegram.close()
