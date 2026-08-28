"""Deterministic fixtures for demo mode.

Set DEMO_MODE=true to run the whole stack with no network at all. The generated
tape is seeded, so the dashboard, detectors, sizing and analytics are all
exercisable and reproducible -- useful for development, for tests, and for
demonstrating the app when the live venues are quiet.

Prices are shaped to fire every detector: a crossed binary book, a YES-side Dutch
book, a NO-side Dutch book, a cross-venue pair, and a mass of ordinary
non-arbitrage markets so the scanner has realistic noise to reject.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Optional

from .fees import fee_model_for
from .models import DepthLevel, Event, Market, Outcome, Quote, Side, utcnow

_SEED = 20260827


def _quote(
    venue: str,
    market_id: str,
    outcome: str,
    side: Side,
    price: float,
    size: float,
    rng: random.Random,
    ticker: Optional[str] = None,
) -> Quote:
    fees = fee_model_for(venue)
    tick = 0.01 if venue == "kalshi" else 0.001
    depth = tuple(
        DepthLevel(price=round(price + i * tick, 4), size=round(size * (0.6 ** i), 2))
        for i in range(4)
    )
    total = sum(d.size for d in depth)
    return Quote(
        venue=venue,
        market_id=market_id,
        ticker=ticker or market_id,
        outcome=outcome,
        side=side,
        price=price,
        effective_price=fees.effective_price(price, max(total, 1.0)),
        size_available=total,
        depth=depth,
        last_update=utcnow() - timedelta(seconds=rng.randint(1, 90)),
        url=f"https://example.invalid/{venue}/{market_id}",
    )


def _binary(
    venue: str,
    mid: str,
    yes_name: str,
    no_name: str,
    yes_price: float,
    no_price: float,
    size: float,
    rng: random.Random,
) -> Market:
    return Market(
        key="binary",
        outcomes=(
            Outcome(name=yes_name, quotes=(_quote(venue, f"{mid}:Y", yes_name, Side.YES, yes_price, size, rng),)),
            Outcome(name=no_name, quotes=(_quote(venue, f"{mid}:N", no_name, Side.NO, no_price, size, rng),)),
        ),
    )


def demo_events() -> list[Event]:
    """A reproducible market snapshot containing several real arbitrages."""
    rng = random.Random(_SEED)
    now = utcnow()
    events: list[Event] = []

    # 1. Crossed book on a single venue -- the cleanest possible arb.
    events.append(
        Event(
            id="polymarket:demo-crossed",
            venue="polymarket",
            title="Will the Federal Reserve cut rates at the December 2026 meeting?",
            category="economics",
            close_time=now + timedelta(days=45),
            volume_usd=2_400_000,
            liquidity_usd=180_000,
            url="https://example.invalid/polymarket/fed-dec-2026",
            markets=(_binary("polymarket", "demo-fed", "Yes", "No", 0.462, 0.522, 9000, rng),),
        )
    )

    # 2. Same question on Kalshi, priced differently -> cross-venue arb.
    events.append(
        Event(
            id="kalshi:demo-fed",
            venue="kalshi",
            title="Fed cuts rates at the December 2026 meeting?",
            category="economics",
            close_time=now + timedelta(days=45),
            volume_usd=890_000,
            liquidity_usd=64_000,
            url="https://example.invalid/kalshi/fed-dec-2026",
            markets=(_binary("kalshi", "KXFED-26DEC", "Yes", "No", 0.56, 0.45, 4200, rng),),
        )
    )

    # 3. Mutually exclusive four-way -> YES-side Dutch book (sums to 0.965).
    nominees = [("Vance", 0.305), ("Newsom", 0.276), ("Haley", 0.221), ("Field", 0.163)]
    events.append(
        Event(
            id="polymarket:demo-nominee",
            venue="polymarket",
            title="2028 Presidential nominee",
            category="politics",
            mutually_exclusive=True,
            close_time=now + timedelta(days=120),
            volume_usd=14_200_000,
            liquidity_usd=920_000,
            url="https://example.invalid/polymarket/nominee-2028",
            markets=tuple(
                _binary("polymarket", f"demo-nom-{i}", name, f"Not {name}", price, round(1.0 - price + 0.012, 4), 6000, rng)
                for i, (name, price) in enumerate(nominees)
            ),
        )
    )

    # 4. Mutually exclusive five-way where the NO side is cheap -> Dutch NO.
    #    Five NO legs at ~0.79 sum to 3.95 against a $4 payout.
    teams = ["Chiefs", "49ers", "Ravens", "Lions", "Bills"]
    events.append(
        Event(
            id="kalshi:demo-superbowl",
            venue="kalshi",
            title="Super Bowl LXI winner",
            category="sports",
            mutually_exclusive=True,
            close_time=now + timedelta(days=90),
            volume_usd=6_800_000,
            liquidity_usd=410_000,
            url="https://example.invalid/kalshi/superbowl-61",
            markets=tuple(
                _binary("kalshi", f"KXSB-{t}", t, f"Not {t}", 0.212, 0.777, 5200, rng)
                for t in teams
            ),
        )
    )

    # 5. Realistic non-arbitrage noise, so the detector has to reject things.
    topics = [
        ("Will SpaceX land Starship on the Moon before 2029?", "science", 0.34),
        ("Will GPT-6 be released in 2026?", "technology", 0.58),
        ("Will Bitcoin close above $150,000 on Dec 31, 2026?", "crypto", 0.27),
        ("Will there be a US government shutdown in 2026?", "politics", 0.41),
        ("Will global average temperature set a record in 2026?", "climate", 0.62),
        ("Will Arsenal win the 2026-27 Premier League?", "sports", 0.19),
        ("Will the S&P 500 close above 8000 in 2026?", "economics", 0.46),
        ("Will a new Pope be elected in 2026?", "world", 0.07),
    ]
    for i, (title, category, p) in enumerate(topics):
        venue = "polymarket" if i % 2 == 0 else "kalshi"
        # Both sides quoted with a normal spread: no arbitrage available.
        spread = 0.012 if venue == "polymarket" else 0.02
        events.append(
            Event(
                id=f"{venue}:demo-noise-{i}",
                venue=venue,
                title=title,
                category=category,
                close_time=now + timedelta(days=rng.randint(20, 400)),
                volume_usd=rng.randint(50_000, 3_000_000),
                liquidity_usd=rng.randint(10_000, 200_000),
                url=f"https://example.invalid/{venue}/noise-{i}",
                markets=(
                    _binary(
                        venue,
                        f"demo-noise-{i}",
                        "Yes",
                        "No",
                        round(p + spread / 2, 4),
                        round(1.0 - p + spread / 2, 4),
                        rng.randint(2000, 12000),
                        rng,
                    ),
                ),
            )
        )

    return events
