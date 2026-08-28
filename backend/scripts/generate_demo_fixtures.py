"""Snapshot the demo-mode API into static JSON.

The GitHub Pages demo has no Python process behind it, so the dashboard is built
against these files instead of a live engine. Running the real engine in demo
mode and capturing its actual responses keeps the fixtures honest: the numbers on
the deployed site are computed by the same detectors, sizing and risk scoring as
a live install, not hand-written to look good.

    python -m scripts.generate_demo_fixtures

Output lands in `frontend/public/demo/`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Demo mode must be set before the settings singleton is constructed.
os.environ["DEMO_MODE"] = "true"
os.environ["AUTOSTART_SCANNER"] = "false"
os.environ["DATABASE_PATH"] = "data/demo_fixtures.db"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT.parent / "frontend" / "public" / "demo"


def write(name: str, payload: object) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"  {name}  ({path.stat().st_size:,} bytes)")


def main() -> int:
    from fastapi.testclient import TestClient

    from arbengine.api import app

    # Start from a clean database so repeat runs produce identical fixtures.
    db = ROOT / "data" / "demo_fixtures.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db) + suffix)
        if candidate.exists():
            candidate.unlink()

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Writing demo fixtures to {OUT}")

    with TestClient(app) as client:
        # Several cycles so the analytics and history views have something to
        # show rather than a single lonely data point.
        for _ in range(4):
            client.post("/api/scanner/scan")

        write("status.json", client.get("/api/status").json())
        write("config.json", client.get("/api/config").json())

        arbs = client.get("/api/arbs?limit=200").json()
        write("arbs.json", arbs)

        for arb in arbs["arbs"]:
            detail = client.get(f"/api/arbs/{arb['id']}").json()
            write(f"arb-{arb['id']}.json", detail)

        write("markets.json", client.get("/api/markets?limit=300").json())
        write("analytics.json", client.get("/api/analytics?days=30").json())
        write("history.json", client.get("/api/history?days=30&limit=300").json())
        write("positions.json", client.get("/api/positions").json())
        write(
            "backtest.json",
            client.post(
                "/api/backtest",
                json={
                    "days": 30,
                    "min_margin": 0.001,
                    "max_margin": 0.5,
                    "void_rate": 0.02,
                    "void_loss": 0.30,
                    "simulations": 600,
                },
            ).json(),
        )

    print(f"\nDone. {len(arbs['arbs'])} opportunities captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
