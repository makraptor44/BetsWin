"""Wires correlation_arb.py into the scanner pipeline.

There is no way to auto-discover "these two events also have a joint
contract" the way title-matching finds the same event on two venues -- a
Trump/Senate joint contract does not look like either of its marginals. So
pairs are registered explicitly (via /api/correlation/pairs) rather than
detected: each row names a venue and the three markets (event A, event B, the
"both happen" contract) that make up one correlation-arb candidate.

Per scan cycle, for every enabled pair:

  1. Look up the three current quotes from the live tape.
  2. Resolve rho_prior -- either a manually configured override, or the
     tetrachoric estimate from resolved historical instances of this pair
     (correlation_arb.estimate_rho_prior_from_outcomes). Neither is invented
     here: an override is the operator's own number, and history is only
     ever what they have actually recorded as events resolved.
  3. Solve for rho_impl and compare (correlation_arb.evaluate).
  4. If there's a tradeable edge, size a single-leg directional position by
     fractional Kelly (sizing.size_correlation_trade) and emit it as an
     `Arb` with kind=CORRELATION, strategy="directional" -- explicitly NOT a
     risk-free lock, unlike every other kind this engine produces.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional, Sequence

from loguru import logger

from . import correlation_arb as ca
from . import odds as om
from .config import settings
from .detector import _binary_outcomes, _NEAR_RESOLUTION_HOURS, _STALE_AFTER
from .models import Arb, ArbKind, ArbLeg, Event, Market, Quote, RiskFlag, Side, utcnow
from .sizing import SizedCorrelationTrade, size_correlation_trade
from .storage import ArbStore
from .venues import PairVerdict, legs_are_placeable, venue, zone_info


def _placeable(quote: Quote) -> PairVerdict:
    """Mirrors detector._placeable for a single-venue leg set."""
    if not settings.enforce_zone_pairing:
        return PairVerdict(True, "Zone pairing is disabled in configuration.")
    return legs_are_placeable([quote.venue], settings.operator_jurisdiction)


def _find_quote(
    events: Sequence[Event], venue_name: str, market_id: str, outcome_name: str
) -> Optional[Quote]:
    venue_name = venue_name.lower().strip()
    for ev in events:
        if ev.venue != venue_name:
            continue
        outcome = None
        for market in ev.markets:
            outcome = market.outcome(outcome_name)
            if outcome is not None:
                break
        if outcome is None:
            continue
        for q in outcome.quotes:
            if q.market_id == market_id:
                return q
    return None


def _find_market(events: Sequence[Event], venue_name: str, market_id: str) -> Optional[Market]:
    venue_name = venue_name.lower().strip()
    for ev in events:
        if ev.venue != venue_name:
            continue
        for market in ev.markets:
            if any(q.market_id == market_id for o in market.outcomes for q in o.quotes):
                return market
    return None


def _resolve_rho_prior(
    pair: dict[str, Any], store: Optional[ArbStore]
) -> Optional[tuple[float, str, Optional[int]]]:
    """rho_prior, its source label, and the sample count behind it (if any)."""
    override = pair.get("rho_prior_override")
    if override is not None:
        return float(override), "override", None

    if store is None:
        return None
    outcomes = store.list_correlation_outcomes(pair["key"])
    if len(outcomes) < 2:
        return None
    a = [int(o["outcome_a"]) for o in outcomes]
    b = [int(o["outcome_b"]) for o in outcomes]
    try:
        rho = ca.estimate_rho_prior_from_outcomes(a, b)
    except ValueError as exc:
        logger.debug(f"correlation: rho_prior estimate failed for {pair['key']!r}: {exc}")
        return None
    return rho, "historical", len(outcomes)


def _score(
    signal: ca.CorrelationArbSignal,
    sized: SizedCorrelationTrade,
    quotes: Sequence[Quote],
    rho_source: str,
    n_samples: Optional[int],
    close_time: Optional[datetime],
) -> tuple[int, tuple[RiskFlag, ...], tuple[str, ...]]:
    flags: list[RiskFlag] = [RiskFlag.STATISTICAL_EDGE]
    notes: list[str] = [
        f"Directional bet that the market's implied correlation "
        f"(rho_impl={signal.rho_impl:.2f}) converges toward the prior "
        f"(rho_prior={signal.rho_prior:.2f}, {rho_source}"
        f"{f', n={n_samples}' if n_samples else ''}) -- not a risk-free "
        f"arbitrage. The full stake is at risk if the joint contract "
        f"resolves the other way."
    ]
    score = 100.0

    if abs(signal.edge_pct) > 25.0:
        flags.append(RiskFlag.SUSPECT_MARGIN)
        score -= 30.0
        notes.append(
            f"Edge of {signal.edge_pct:.0f}% of the market price is unusually "
            "large -- verify the marginals and the joint contract actually "
            "describe the same pair of events before trusting the model over "
            "the market."
        )

    if rho_source == "historical" and (n_samples or 0) < settings.correlation_min_rho_prior_samples:
        score -= 20.0
        notes.append(
            f"rho_prior is estimated from only {n_samples or 0} historical "
            f"instance(s) (want >= {settings.correlation_min_rho_prior_samples}) "
            "-- treat this signal as exploratory."
        )

    if sized.depth_limited:
        flags.append(RiskFlag.THIN_LIQUIDITY)
        score -= 15.0
        notes.append("Order-book depth caps the size this edge can be taken at.")

    now = utcnow()
    oldest = min((q.last_update for q in quotes), default=now)
    age = now - oldest
    if age > _STALE_AFTER:
        flags.append(RiskFlag.STALE_QUOTE)
        score -= min(25.0, age.total_seconds() / 120.0)
        notes.append(f"Oldest quote is {age.total_seconds() / 60:.0f} minutes old.")

    if close_time is not None:
        hours = (close_time - now).total_seconds() / 3600.0
        if hours < _NEAR_RESOLUTION_HOURS:
            flags.append(RiskFlag.NEAR_RESOLUTION)
            score -= 18.0
            notes.append(f"Market closes in {max(hours, 0):.1f}h -- execution risk is high.")

    return int(max(0.0, min(100.0, score))), tuple(dict.fromkeys(flags)), tuple(notes)


def _arb_id(pair_key: str, quote: Quote, side: Side) -> str:
    parts = f"correlation|{pair_key}|{quote.venue}|{quote.market_id}|{side.value}"
    return hashlib.sha1(parts.encode()).hexdigest()[:16]


def evaluate_pair(
    pair: dict[str, Any],
    events: Sequence[Event],
    store: Optional[ArbStore] = None,
    venue_limits: Optional[dict[str, float]] = None,
) -> Optional[Arb]:
    """Evaluate one configured pair against the current tape. None if no trade."""
    quote_a = _find_quote(events, pair["venue"], pair["market_id_a"], pair["outcome_a"])
    quote_b = _find_quote(events, pair["venue"], pair["market_id_b"], pair["outcome_b"])
    joint_market = _find_market(events, pair["venue"], pair["market_id_joint"])
    if quote_a is None or quote_b is None or joint_market is None:
        logger.debug(f"correlation: {pair['key']!r} -- one or more legs not on the current tape")
        return None

    joint_pair = _binary_outcomes(joint_market)
    if joint_pair is None:
        logger.debug(f"correlation: {pair['key']!r} -- joint market is not a clean binary")
        return None
    joint_yes, joint_no = joint_pair

    rho = _resolve_rho_prior(pair, store)
    if rho is None:
        logger.debug(f"correlation: {pair['key']!r} -- no rho_prior (no override, no history)")
        return None
    rho_prior, rho_source, n_samples = rho

    min_edge = pair.get("min_edge")
    min_edge = min_edge if min_edge is not None else settings.correlation_min_edge

    try:
        signal = ca.evaluate(
            quote_a.effective_price,
            quote_b.effective_price,
            joint_yes.effective_price,
            rho_prior,
            min_edge=min_edge,
        )
    except ValueError as exc:
        logger.debug(f"correlation: {pair['key']!r} -- {exc}")
        return None

    if signal.action == "HOLD":
        return None

    if signal.action == "BUY":
        quote, side, fair_probability = joint_yes, Side.YES, signal.fair_joint_price
    else:
        quote, side, fair_probability = joint_no, Side.NO, 1.0 - signal.fair_joint_price

    kelly_fraction = pair.get("kelly_fraction")
    kelly_fraction = kelly_fraction if kelly_fraction is not None else settings.correlation_kelly_fraction

    sized = size_correlation_trade(
        quote,
        side.value,
        fair_probability,
        bankroll=settings.bankroll,
        kelly_fraction=kelly_fraction,
        venue_limits=venue_limits,
    )
    if sized is None:
        return None

    verdict = _placeable(quote)
    if not verdict.ok:
        logger.debug(f"correlation: {pair['key']!r} rejected -- {verdict.reason}")
        return None

    close_time = _joint_market_close(events, pair)
    confidence, flags, notes = _score(
        signal, sized, (quote_a, quote_b, quote), rho_source, n_samples, close_time
    )
    if confidence < settings.min_confidence:
        return None

    leg = ArbLeg(
        venue=quote.venue,
        market_id=quote.market_id,
        ticker=quote.ticker,
        outcome=quote.outcome,
        side=side,
        price=round(sized.fill_price, 6),
        effective_price=round(sized.effective_price, 6),
        decimal_odds=om.prob_to_decimal(sized.fill_price),
        effective_decimal_odds=om.prob_to_decimal(sized.effective_price),
        stake=sized.stake,
        contracts=sized.contracts,
        fee=sized.fee,
        size_available=quote.size_available,
        url=quote.url,
        event_title=pair["label"],
    )

    zone = venue(quote.venue).zone
    payout_if = {
        f"{quote.outcome} resolves {side.value}": round(sized.contracts - sized.stake, 2),
        f"{quote.outcome} resolves against": round(-sized.stake, 2),
    }

    return Arb(
        id=_arb_id(pair["key"], quote, side),
        kind=ArbKind.CORRELATION,
        strategy="directional",
        title=f'{pair["label"]} - correlation edge on "{quote.outcome}"',
        category="correlation",
        venues=(quote.venue,),
        zone=zone.value,
        zone_label=zone_info(zone).label,
        currency=venue(quote.venue).currency,
        placeable_from=verdict.jurisdictions,
        market_key="correlation",
        legs=(leg,),
        total_stake=sized.stake,
        margin=round(abs(signal.edge_pct) / 100.0, 5),
        net_margin=round(abs(signal.edge_pct) / 100.0, 5),
        profit=sized.expected_value,
        worst_case_profit=sized.worst_case_profit,
        payout_if=payout_if,
        max_stake_available=sized.stake,
        confidence=confidence,
        flags=flags,
        notes=notes,
        close_time=close_time,
    )


def _joint_market_close(events: Sequence[Event], pair: dict[str, Any]) -> Optional[datetime]:
    for ev in events:
        if ev.venue != pair["venue"].lower().strip():
            continue
        for market in ev.markets:
            if any(
                q.market_id == pair["market_id_joint"] for o in market.outcomes for q in o.quotes
            ):
                return ev.close_time
    return None


def scan_correlation_pairs(
    events: Sequence[Event],
    store: Optional[ArbStore] = None,
    venue_limits: Optional[dict[str, float]] = None,
) -> list[Arb]:
    """Evaluate every enabled configured pair against the current tape."""
    if not settings.enable_correlation_arb or store is None:
        return []
    pairs = store.list_correlation_pairs(enabled_only=True)
    out: list[Arb] = []
    for pair in pairs:
        try:
            arb = evaluate_pair(pair, events, store, venue_limits)
        except Exception as exc:  # noqa: BLE001 - one bad pair must not stop a scan
            logger.warning(f"correlation: pair {pair.get('key')!r} failed -- {exc}")
            continue
        if arb is not None:
            out.append(arb)
    return out
