"""The backtest's equity curve has to be a path something actually walked.

Everything else `replay` returns describes a distribution. The curve is the one
output that claims to be a single realisation, and two earlier versions of it
were not: one replayed simulation number one and called it the median, the other
voided each opportunity independently if it voided in over half the runs. With
void rates of 2-5% that second rule never fires, so the chart drew the void-free
line while the summary beside it reported voids eating a fifth of the edge.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from arbengine.backtest import BacktestParams, replay
from arbengine.storage import ArbStore


@pytest.fixture
def store():
    d = tempfile.mkdtemp()
    s = ArbStore(os.path.join(d, "t.db"))
    _seed(s)
    yield s
    s.close()


def _seed(store: ArbStore, n: int = 60) -> None:
    """A tape of `n` opportunities, spread over the last fortnight.

    Written through `_exec` rather than `upsert_arb` so a row costs the columns
    the schema requires rather than a fully populated `Arb` model each.
    """
    now = datetime.now(timezone.utc)
    for i in range(n):
        store._exec(  # noqa: SLF001 - test reaching into its own package
            """INSERT INTO arbs
                 (arb_key, kind, title, category, venues, market_key, detected_at,
                  last_seen, book, margin, net_margin, total_stake, profit,
                  worst_case_profit, confidence, legs_json, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"row{i}",
                "cross_venue" if i % 3 == 0 else "binary_complement",
                f"Opportunity {i}",
                "politics",
                json.dumps(["kalshi", "polymarket"] if i % 3 == 0 else ["kalshi"]),
                "binary",
                (now - timedelta(days=14) + timedelta(hours=i * 4)).isoformat(),
                now.isoformat(),
                0.985,
                0.02,
                0.015,
                500.0,
                7.5,
                7.5,
                80,
                "[]",
                "{}",
            ),
        )


def _params(**kw) -> BacktestParams:
    return BacktestParams(days=30, min_margin=0.001, max_margin=0.5, **kw)


def test_equity_curve_ends_on_the_median_profit(store):
    """The headline number and the last point of the chart are one figure.

    If they disagree, one of the two is describing a run that did not happen.
    """
    r = replay(store, _params(simulations=201))
    assert r.equity_curve
    assert r.equity_curve[-1]["equity"] == pytest.approx(r.median_profit, abs=0.02)


def test_equity_curve_actually_models_voids(store):
    """With a void rate this high, a curve showing none is not a median path.

    This is the regression that mattered: the marginal-median rule required an
    opportunity to void in over half of all runs, which at any realistic rate
    never happens, so the curve silently became the naive one.
    """
    r = replay(store, _params(simulations=201, void_rate=0.25, void_loss=0.30))
    voided = [p for p in r.equity_curve if p["voided"]]
    assert voided, "a 25% void rate must show voided legs on the median path"
    assert r.equity_curve[-1]["equity"] < r.naive_profit


def test_curve_is_in_detection_order_and_carries_timestamps(store):
    r = replay(store, _params(simulations=51))
    ats = [p["at"] for p in r.equity_curve]
    assert ats == sorted(ats)
    assert all(p["at"] and p["at"] != str(i) for i, p in enumerate(r.equity_curve))


def test_replay_is_deterministic_for_a_seed(store):
    a = replay(store, _params(simulations=101, seed=7))
    b = replay(store, _params(simulations=101, seed=7))
    assert a.equity_curve == b.equity_curve
    assert a.median_profit == b.median_profit


def test_median_profit_is_a_simulation_that_happened(store):
    """Not the average of the two middle runs, which no run reached.

    The curve replays one real void mask, so the summary has to name that same
    run rather than an interpolation between two of them.
    """
    r = replay(store, _params(simulations=200))
    assert r.worst_simulation <= r.median_profit <= r.best_simulation
    assert r.equity_curve[-1]["equity"] == pytest.approx(r.median_profit, abs=0.02)
