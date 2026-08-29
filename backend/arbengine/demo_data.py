"""Deterministic fixtures for demo mode.

Set DEMO_MODE=true to run the whole stack with no network at all. The generated
tape is seeded, so the dashboard, detectors, sizing and analytics are all
exercisable and reproducible -- useful for development, for tests, and for
demonstrating the app when the live venues are quiet.

Prices are shaped to fire every detector: a crossed binary book, a YES-side Dutch
book, a NO-side Dutch book, a cross-venue pair, and a mass of ordinary
non-arbitrage markets so the scanner has realistic noise to reject.

The tape spans both execution zones -- Polymarket/Kalshi in USD contracts,
Smarkets/Betfair in GBP exchange prices -- and deliberately includes one
cross-zone pair that looks like the fattest arbitrage in the set and is rejected
for being unplaceable. A fixture set that only contains opportunities cannot
demonstrate a guard.
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
    # Exchanges quote a finer ladder than a cent-tick contract market.
    tick = 0.01 if venue == "kalshi" else 0.001 if venue == "polymarket" else 0.002
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

    # 5. The UK/EU exchange zone. Smarkets and Betfair are a legitimate pair:
    #    one operator, one country, one currency, two ordinary accounts.
    events.append(
        Event(
            id="smarkets:demo-ge-labour",
            venue="smarkets",
            title="Will Labour win the next UK general election?",
            category="politics",
            currency="GBP",
            close_time=now + timedelta(days=300),
            volume_usd=0.0,
            liquidity_usd=48_000,
            url="https://example.invalid/smarkets/ge-labour",
            markets=(
                _binary("smarkets", "demo-sm-labour", "Yes", "Not Yes", 0.52, 0.495, 7000, rng),
            ),
        )
    )
    events.append(
        Event(
            id="betfair:demo-ge-labour",
            venue="betfair",
            title="Labour to win the next UK general election",
            category="politics",
            currency="GBP",
            close_time=now + timedelta(days=300),
            volume_usd=0.0,
            liquidity_usd=115_000,
            url="https://example.invalid/betfair/ge-labour",
            markets=(
                _binary("betfair", "demo-bf-labour", "Yes", "Not Yes", 0.535, 0.447, 9000, rng),
            ),
        )
    )

    # 6. A three-way football book on Smarkets. Home/draw/away genuinely
    #    partition the sample space, which is what the Dutch detector needs,
    #    and commission on winnings is what decides whether it survives.
    three_way = [("Arsenal", 0.515), ("Draw", 0.255), ("Brighton", 0.208)]
    events.append(
        Event(
            id="smarkets:demo-football",
            venue="smarkets",
            title="Arsenal vs Brighton - Full-time result",
            category="sports",
            currency="GBP",
            mutually_exclusive=True,
            close_time=now + timedelta(days=3),
            volume_usd=0.0,
            liquidity_usd=86_000,
            url="https://example.invalid/smarkets/arsenal-brighton",
            markets=tuple(
                _binary(
                    "smarkets",
                    f"demo-sm-3way-{i}",
                    name,
                    f"Not {name}",
                    price,
                    round(1.0 - price + 0.008, 4),
                    6000,
                    rng,
                )
                for i, (name, price) in enumerate(three_way)
            ),
        )
    )

    # 7. The trap the zone rule exists for.
    #
    #    These two describe the same question and price it 5.6% apart, which is
    #    the fattest apparent edge in the whole fixture set. It is also
    #    unplaceable: Kalshi settles in USD under CFTC rules, Betfair in GBP
    #    under a UKGC licence, and no single operator holds both from one
    #    country. Detection deliberately never pairs them -- see venues.py. The
    #    pair shows up in /api/venues under `rejected_this_scan`, which is how
    #    you can tell the guard fired rather than the matcher having missed it.
    events.append(
        Event(
            id="kalshi:demo-mancity",
            venue="kalshi",
            title="Will Manchester City win the 2026-27 Premier League?",
            category="sports",
            close_time=now + timedelta(days=280),
            volume_usd=310_000,
            liquidity_usd=42_000,
            url="https://example.invalid/kalshi/mancity-epl",
            markets=(_binary("kalshi", "KXEPL-MCI", "Yes", "No", 0.40, 0.62, 3000, rng),),
        )
    )
    events.append(
        Event(
            id="betfair:demo-mancity",
            venue="betfair",
            title="Manchester City to win the 2026-27 Premier League",
            category="sports",
            currency="GBP",
            close_time=now + timedelta(days=280),
            volume_usd=0.0,
            liquidity_usd=210_000,
            url="https://example.invalid/betfair/mancity-epl",
            markets=(_binary("betfair", "demo-bf-mci", "Yes", "Not Yes", 0.47, 0.55, 8000, rng),),
        )
    )

    # 9. A correlation-arb triple: two marginals plus their joint contract, all
    #    on one venue so a single operator can hold the position. The prices
    #    are synthetic, like every other fixture in this file -- they exist to
    #    exercise correlation_detector.py end to end, not to represent a real
    #    market view. See `demo_correlation_pair` / `demo_correlation_outcomes`
    #    for the matching pair configuration and history seeded alongside it.
    events.append(
        Event(
            id="kalshi:demo-gop-pres",
            venue="kalshi",
            title="Republican nominee wins the 2028 presidency",
            category="politics",
            close_time=now + timedelta(days=430),
            volume_usd=5_100_000,
            liquidity_usd=310_000,
            url="https://example.invalid/kalshi/demo-gop-pres",
            markets=(_binary("kalshi", "KXDEMO-PRES28", "Yes", "No", 0.62, 0.40, 7000, rng),),
        )
    )
    events.append(
        Event(
            id="kalshi:demo-gop-senate",
            venue="kalshi",
            title="Republicans hold a Senate majority after 2028",
            category="politics",
            close_time=now + timedelta(days=430),
            volume_usd=3_600_000,
            liquidity_usd=240_000,
            url="https://example.invalid/kalshi/demo-gop-senate",
            markets=(_binary("kalshi", "KXDEMO-SEN28", "Yes", "No", 0.65, 0.37, 6500, rng),),
        )
    )
    events.append(
        Event(
            id="kalshi:demo-gop-both",
            venue="kalshi",
            title="Republicans win the presidency AND hold the Senate in 2028",
            category="politics",
            close_time=now + timedelta(days=430),
            volume_usd=2_200_000,
            liquidity_usd=160_000,
            url="https://example.invalid/kalshi/demo-gop-both",
            markets=(_binary("kalshi", "KXDEMO-BOTH28", "Yes", "No", 0.48, 0.54, 4000, rng),),
        )
    )

    # 8. Realistic non-arbitrage noise, so the detector has to reject things.
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


def demo_correlation_pair() -> dict:
    """Configuration for the correlation-arb triple added in `demo_events`."""
    return {
        "key": "demo_gop_pres_senate",
        "label": "GOP presidency + Senate (2028, demo)",
        "venue": "kalshi",
        "market_id_a": "KXDEMO-PRES28:Y",
        "outcome_a": "Yes",
        "market_id_b": "KXDEMO-SEN28:Y",
        "outcome_b": "Yes",
        "market_id_joint": "KXDEMO-BOTH28:Y",
        "outcome_joint": "Yes",
        "rho_prior_override": None,
        "min_edge": None,
        "kelly_fraction": None,
        "enabled": True,
    }


def demo_correlation_outcomes() -> list[tuple[str, bool, bool]]:
    """Synthetic past instances of (GOP wins presidency, GOP holds Senate).

    Illustrative, not a claim about real election history -- it exists so
    `estimate_rho_prior_from_outcomes` has something to compute against in
    demo mode. (label, outcome_a, outcome_b).
    """
    return [
        ("Cycle 1", True, True),
        ("Cycle 2", False, False),
        ("Cycle 3", True, True),
        ("Cycle 4", False, True),
        ("Cycle 5", True, True),
        ("Cycle 6", True, False),
        ("Cycle 7", False, False),
        ("Cycle 8", True, True),
    ]
