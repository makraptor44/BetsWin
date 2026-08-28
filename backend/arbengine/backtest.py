"""Backtesting (Part II s15).

Replays the arbs the scanner has already logged and computes what they would
actually have paid once voids are modelled. The point is stated plainly in
Part I s13.3: a nominal 2% margin with a 3% void rate costing 30% of stake nets
around 1.04%, so expected value must be positive AFTER voids, not before.

Two engines:

  `replay`      Monte Carlo over the stored tape, with a per-venue void rate.
  `sweep`       The same, run across a grid of minimum-margin thresholds, to
                answer "where should I set the floor?" empirically.

Part II s15.2 is worth repeating: any tuning that pushes yield far above 30%
annualised on turnover is almost certainly over-fitting. The output includes the
naive figure alongside the void-adjusted one so the gap is always visible.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from . import odds as om
from .config import settings
from .storage import ArbStore


@dataclass
class BacktestParams:
    days: int = 30
    min_margin: float = 0.005
    max_margin: float = 0.05
    min_confidence: int = 0
    kinds: Optional[list[str]] = None
    void_rate: float = 0.02
    void_loss: float = 0.30
    stake_per_arb: Optional[float] = None
    simulations: int = 400
    seed: int = 42
    # Per-venue void rates override the global rate when present. Cross-venue
    # legs are the risky ones (Part I s9.2), so they carry a higher default.
    venue_void_rates: dict[str, float] = field(
        default_factory=lambda: {"cross_venue": 0.05, "sportsbook": 0.03}
    )


@dataclass
class BacktestResult:
    n: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    turnover: float = 0.0
    naive_profit: float = 0.0
    naive_yield: float = 0.0
    expected_profit: float = 0.0
    expected_yield: float = 0.0
    median_profit: float = 0.0
    p5_profit: float = 0.0
    p95_profit: float = 0.0
    stdev_profit: float = 0.0
    worst_simulation: float = 0.0
    best_simulation: float = 0.0
    prob_loss: float = 0.0
    avg_margin: float = 0.0
    effective_margin: float = 0.0
    voids_modelled: float = 0.0
    turnovers_per_year: float = 0.0
    annualised_return: float = 0.0
    by_kind: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load(store: ArbStore, p: BacktestParams) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=p.days)).isoformat()
    rows = store._rows(  # noqa: SLF001 - internal helper, same package
        """SELECT id, kind, detected_at, venues, margin, net_margin, total_stake,
                  worst_case_profit, confidence
           FROM arbs
           WHERE detected_at >= ? AND net_margin BETWEEN ? AND ? AND confidence >= ?
           ORDER BY detected_at""",
        (since, p.min_margin, p.max_margin, p.min_confidence),
    )
    if p.kinds:
        wanted = set(p.kinds)
        rows = [r for r in rows if r["kind"] in wanted]
    return rows


def _void_rate_for(row: dict[str, Any], p: BacktestParams) -> float:
    """Void probability for one opportunity, worst venue wins."""
    rate = p.venue_void_rates.get(row["kind"], p.void_rate)
    try:
        venues = json.loads(row.get("venues") or "[]")
    except (TypeError, json.JSONDecodeError):
        venues = []
    for v in venues:
        rate = max(rate, p.venue_void_rates.get(v, p.void_rate))
    if len(venues) > 1:
        # Two venues means two rulebooks and two chances to be voided.
        rate = 1.0 - (1.0 - rate) ** 2
    return min(rate, 0.9)


def replay(store: ArbStore, p: Optional[BacktestParams] = None) -> BacktestResult:
    """Monte Carlo the stored tape under a void model."""
    p = p or BacktestParams()
    rows = _load(store, p)
    result = BacktestResult(params=asdict(p))
    if not rows:
        result.notes.append(
            "No stored opportunities match these filters. Let the scanner run, "
            "or widen the window."
        )
        return result

    stakes = [
        (p.stake_per_arb if p.stake_per_arb is not None else float(r["total_stake"]))
        for r in rows
    ]
    margins = [float(r["net_margin"]) for r in rows]
    profits = [s * m for s, m in zip(stakes, margins)]
    void_rates = [_void_rate_for(r, p) for r in rows]

    result.n = len(rows)
    result.turnover = round(sum(stakes), 2)
    result.naive_profit = round(sum(profits), 2)
    result.naive_yield = result.naive_profit / result.turnover if result.turnover else 0.0
    result.avg_margin = statistics.fmean(margins)
    result.voids_modelled = statistics.fmean(void_rates)
    result.effective_margin = om.margin_after_voids(
        result.avg_margin, result.voids_modelled, p.void_loss
    )

    rng = random.Random(p.seed)
    totals: list[float] = []
    for _ in range(max(1, p.simulations)):
        run = 0.0
        for stake, profit, vr in zip(stakes, profits, void_rates):
            # A voided leg leaves unhedged exposure on the rest of the set
            # (Part I s9.1); `void_loss` is that cost as a fraction of stake.
            run += (-p.void_loss * stake) if rng.random() < vr else profit
        totals.append(run)

    totals.sort()
    result.expected_profit = round(statistics.fmean(totals), 2)
    result.expected_yield = (
        result.expected_profit / result.turnover if result.turnover else 0.0
    )
    result.median_profit = round(statistics.median(totals), 2)
    result.p5_profit = round(totals[int(0.05 * (len(totals) - 1))], 2)
    result.p95_profit = round(totals[int(0.95 * (len(totals) - 1))], 2)
    result.stdev_profit = round(statistics.pstdev(totals), 2) if len(totals) > 1 else 0.0
    result.worst_simulation = round(totals[0], 2)
    result.best_simulation = round(totals[-1], 2)
    result.prob_loss = sum(1 for t in totals if t < 0) / len(totals)

    # Capital turnover -> annualised return (Part I s8.2). Capital is locked on
    # both legs until settlement, so this is an upper bound.
    if settings.bankroll > 0 and p.days > 0:
        per_year = (result.turnover / settings.bankroll) * (365.0 / p.days)
        result.turnovers_per_year = round(per_year, 2)
        result.annualised_return = om.annualised_return(
            result.expected_yield, per_year
        )

    # Per-kind breakdown.
    by_kind: dict[str, dict[str, Any]] = {}
    for row, stake, profit, vr in zip(rows, stakes, profits, void_rates):
        k = row["kind"]
        b = by_kind.setdefault(
            k, {"kind": k, "n": 0, "turnover": 0.0, "naive_profit": 0.0,
                "margins": [], "void_rate": 0.0}
        )
        b["n"] += 1
        b["turnover"] += stake
        b["naive_profit"] += profit
        b["margins"].append(float(row["net_margin"]))
        b["void_rate"] = max(b["void_rate"], vr)
    for b in by_kind.values():
        m = statistics.fmean(b["margins"])
        b["avg_margin"] = m
        b["effective_margin"] = om.margin_after_voids(m, b["void_rate"], p.void_loss)
        b["expected_profit"] = round(b["effective_margin"] * b["turnover"], 2)
        b["turnover"] = round(b["turnover"], 2)
        b["naive_profit"] = round(b["naive_profit"], 2)
        b.pop("margins")
    result.by_kind = sorted(by_kind.values(), key=lambda x: -x["n"])

    # Median-path equity curve, in detection order.
    rng = random.Random(p.seed)
    equity = 0.0
    for row, stake, profit, vr in zip(rows, stakes, profits, void_rates):
        equity += (-p.void_loss * stake) if rng.random() < vr else profit
        result.equity_curve.append(
            {"at": row["detected_at"], "equity": round(equity, 2), "kind": row["kind"]}
        )

    if result.naive_yield > 0 and result.expected_yield < result.naive_yield * 0.7:
        result.notes.append(
            f"Voids remove {(1 - result.expected_yield / result.naive_yield) * 100:.0f}% "
            f"of the naive edge. Part I s13.3: this is the number that matters."
        )
    if result.annualised_return > 0.30:
        result.notes.append(
            "Annualised return above 30% on turnover is the over-fitting warning "
            "sign flagged in Part II s15.2 - treat with scepticism."
        )
    if result.prob_loss > 0.05:
        result.notes.append(
            f"{result.prob_loss * 100:.0f}% of simulated runs finished negative. "
            f"Arbitrage is only risk-free if every leg settles."
        )
    return result


def sweep(
    store: ArbStore,
    thresholds: Sequence[float] = (0.002, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03),
    base: Optional[BacktestParams] = None,
) -> list[dict[str, Any]]:
    """Run `replay` across a grid of minimum-margin floors.

    Raising the floor trades volume for quality. The curve usually peaks well
    below the intuitive setting, because most of the profit lives in the many
    small, reliable opportunities rather than the few fat suspicious ones.
    """
    out: list[dict[str, Any]] = []
    for t in thresholds:
        p = BacktestParams(**{**asdict(base or BacktestParams()), "min_margin": t})
        r = replay(store, p)
        out.append(
            {
                "min_margin": t,
                "n": r.n,
                "turnover": r.turnover,
                "naive_yield": r.naive_yield,
                "expected_yield": r.expected_yield,
                "expected_profit": r.expected_profit,
                "prob_loss": r.prob_loss,
                "annualised_return": r.annualised_return,
            }
        )
    return out
