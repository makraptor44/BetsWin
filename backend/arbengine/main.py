"""Entry point (Part II s9.1).

    python -m arbengine.main            # serve the API + run the scanner
    python -m arbengine.main --scan     # one scan cycle, print results, exit
    python -m arbengine.main --demo     # force demo mode (no network)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from loguru import logger

from .config import settings
from .fees import configure_from_settings


def _configure_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, colorize=True)
    logger.add(
        "logs/scanner.log",
        rotation="10 MB",
        retention="14 days",
        level="DEBUG",
        enqueue=True,
    )


async def _scan_once() -> int:
    from .scanner import Scanner

    scanner = Scanner()
    try:
        arbs = await scanner.scan_once()
        live = scanner.live_arbs()
        print()
        print(f"  Scanned {scanner.last_scan.events_scanned} events across "
              f"{len(scanner.sources)} venues in {scanner.last_scan.duration_seconds}s")
        print(f"  {len(live)} live opportunities ({len(arbs)} new)")
        print()
        if not live:
            print("  No arbitrage available right now. That is the normal state of")
            print("  an efficient market -- run the scanner continuously instead.")
        for a in live[:25]:
            print(f"  [{a.net_margin * 100:5.2f}%] conf {a.confidence:3}  {a.kind.value:18} {a.title[:64]}")
            for leg in a.legs:
                print(f"        {leg.venue:12} {leg.outcome[:26]:26} @ {leg.price:.4f}  "
                      f"${leg.stake:8.2f}  ({leg.contracts:,.0f} contracts)")
            print(f"        -> stake ${a.total_stake:,.2f}, guaranteed ${a.worst_case_profit:,.2f}")
            print()
        return 0
    finally:
        await scanner.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="arbengine", description="BetsWin arbitrage engine")
    parser.add_argument("--scan", action="store_true", help="run one scan cycle and exit")
    parser.add_argument("--demo", action="store_true", help="use offline demo fixtures")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = parser.parse_args()

    if args.demo:
        settings.demo_mode = True
    _configure_logging()
    configure_from_settings(settings)

    if args.scan:
        return asyncio.run(_scan_once())

    import uvicorn

    uvicorn.run(
        "arbengine.api:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
