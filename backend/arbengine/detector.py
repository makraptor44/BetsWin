"""Arbitrage detection (Part II s7).

Four detectors, all resting on the same condition from Part I s2.4 -- take the
best price on every outcome, sum the implied probabilities, and check whether the
total falls below the payout:

  BINARY_COMPLEMENT  YES here + NO there. sum(p) < 1.
  DUTCH_YES          n mutually exclusive outcomes, buy every YES. sum(p) < 1.
  DUTCH_NO           n mutually exclusive outcomes, buy every NO. sum(p) < n-1,
                     because every leg but the winner settles at $1.
  SPORTSBOOK         best price per outcome across books (Part I s3-s4).

Prices fed to the detectors are already fee-adjusted by the source layer, so a
"1.5% edge" here is an edge that survives Kalshi's trading fee -- not a headline
number that evaporates at the point of execution.

Everything surfaced carries a confidence score and explicit risk flags. Part I
s5.3 is the governing instinct: the overwhelming majority of very large apparent
arbs are bad data, mismatched lines, or a price that has already moved, so the
scoring function treats an unusually fat margin as evidence against an
opportunity rather than for it.
"""

from __future__ import annotations

import hashlib
import itertools
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, Optional, Sequence

from loguru import logger

from . import odds as om
from .config import settings
from .models import (
    Arb,
    ArbKind,
    Event,
    Market,
    Quote,
    RiskFlag,
    Side,
    utcnow,
)
from .normalise import MatchResult, match_titles
from .sizing import SizedArb, size_arb

# Quotes older than this are treated as possibly moved (Part I s9.3).
_STALE_AFTER = timedelta(minutes=10)
# Beyond this horizon capital is locked long enough to matter (Part I s8.2).
_LONG_DATED_DAYS = 180
# Inside this window a market may settle before both legs are placed.
_NEAR_RESOLUTION_HOURS = 2.0
# A Dutch book across more legs than this is not placeable by hand (Part I s5.1).
_MAX_DUTCH_LEGS = 12
# A genuinely exhaustive set of mutually exclusive outcomes always prices at a
# YES-sum of roughly 1 -- at or just above it on a normal book, a little below it
# when an arb exists. A sum far below 1 does not mean a huge edge; it means
# outcomes are MISSING from the set, whether because a venue paginated the event,
# because a leg was filtered out for having a one-sided book, or because the
# market genuinely has an unlisted "any other" case. Part I s5.2: outcomes that
# do not partition the sample space cannot be arbed with this formula, and
# staking such a "book" leaves the missing outcome completely uncovered.
_DUTCH_COMPLETENESS_FLOOR = 0.90


def _arb_id(kind: ArbKind, quotes: Sequence[Quote]) -> str:
    parts = [kind.value] + sorted(f"{q.venue}:{q.market_id}:{q.outcome}" for q in quotes)
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _binary_outcomes(market: Market) -> Optional[tuple[Quote, Quote]]:
    """Return (YES quote, NO quote) for a two-sided market."""
    if len(market.outcomes) != 2:
        return None
    a, b = market.outcomes[0].best(), market.outcomes[1].best()
    if a is None or b is None:
        return None
    return a, b


# --------------------------------------------------------------- risk scoring


def _score(
    kind: ArbKind,
    sized: SizedArb,
    quotes: Sequence[Quote],
    close_time: Optional[datetime],
    match: Optional[MatchResult] = None,
) -> tuple[int, tuple[RiskFlag, ...], tuple[str, ...]]:
    """Confidence 0-100 plus the reasons it is not 100."""
    flags: list[RiskFlag] = []
    notes: list[str] = []
    score = 100.0

    # Part I s5.3 -- a very large margin is a red flag, not a prize.
    if sized.net_margin > settings.suspect_margin:
        flags.append(RiskFlag.SUSPECT_MARGIN)
        excess = sized.net_margin - settings.suspect_margin
        score -= min(55.0, 25.0 + excess * 400.0)
        notes.append(
            f"Margin of {sized.net_margin * 100:.1f}% is above the "
            f"{settings.suspect_margin * 100:.0f}% suspicion threshold - verify "
            f"both legs describe the same outcome before staking."
        )

    # Fees eating the edge.
    if sized.margin > 0:
        retained = sized.net_margin / sized.margin
        if retained < 0.5:
            flags.append(RiskFlag.FEE_SENSITIVE)
            score -= 12.0
            notes.append(
                f"Fees and slippage consume {(1 - retained) * 100:.0f}% of the "
                f"gross edge ({sized.margin * 100:.2f}% -> "
                f"{sized.net_margin * 100:.2f}%)."
            )

    # Liquidity: can the trade be done at a size worth doing?
    if sized.depth_limited or sized.max_stake_available < settings.min_total_stake * 2:
        flags.append(RiskFlag.THIN_LIQUIDITY)
        score -= 15.0
        notes.append(
            f"Order-book depth caps this at ${sized.max_stake_available:,.0f} total stake."
        )

    no_depth = [q for q in quotes if not q.depth]
    if no_depth:
        score -= 8.0
        notes.append(
            f"{len(no_depth)} leg(s) have no published depth; size is estimated "
            f"from top of book."
        )

    # Spread width as a proxy for how real the top-of-book price is.
    if sized.slippage_bps > 50:
        flags.append(RiskFlag.WIDE_SPREAD)
        score -= 10.0
        notes.append(f"Filling this size moves the average price by {sized.slippage_bps:.0f} bps.")

    # Staleness (Part I s9.3).
    now = utcnow()
    oldest = min((q.last_update for q in quotes), default=now)
    age = now - oldest
    if age > _STALE_AFTER:
        flags.append(RiskFlag.STALE_QUOTE)
        score -= min(25.0, age.total_seconds() / 120.0)
        notes.append(f"Oldest quote is {age.total_seconds() / 60:.0f} minutes old.")

    # Cross-venue rule risk (Part I s9.2, Part II s6.2).
    venues = {q.venue for q in quotes}
    if len(venues) > 1:
        flags.append(RiskFlag.CROSS_VENUE_RULES)
        score -= 6.0
        notes.append(
            "Legs sit on different venues; confirm the resolution criteria and "
            "settlement dates agree before treating this as risk-free."
        )
    if match is not None:
        flags.append(RiskFlag.FUZZY_MATCH)
        penalty = max(0.0, (100.0 - match.score)) * 1.2
        score -= penalty
        notes.append(
            f"Markets were paired by title similarity ({match.score:.0f}/100), "
            f"not by a shared identifier."
        )

    # Time to resolution.
    if close_time is not None:
        hours = (close_time - now).total_seconds() / 3600.0
        if hours < _NEAR_RESOLUTION_HOURS:
            flags.append(RiskFlag.NEAR_RESOLUTION)
            score -= 18.0
            notes.append(f"Market closes in {max(hours, 0):.1f}h - execution risk is high.")
        elif hours > _LONG_DATED_DAYS * 24:
            flags.append(RiskFlag.LONG_DATED)
            score -= 10.0
            notes.append(
                f"Resolution is {hours / 24 / 365:.1f} years out; capital is locked "
                f"for the duration, so annualised return is far below the headline."
            )

    if sized.rounding_exposure:
        flags.append(RiskFlag.ROUNDING_EXPOSURE)
        score -= 5.0
        notes.append("Rounded stakes leave slightly unequal profit across outcomes.")

    # A Dutch book over many legs is operationally hard (Part I s5.1).
    if len(quotes) > 4:
        score -= min(20.0, (len(quotes) - 4) * 3.0)
        notes.append(f"{len(quotes)} legs must be filled before prices move.")

    return int(max(0.0, min(100.0, score))), tuple(dict.fromkeys(flags)), tuple(notes)


def _finalise(
    kind: ArbKind,
    title: str,
    category: str,
    quotes: Sequence[Quote],
    sized: SizedArb,
    close_time: Optional[datetime],
    market_key: str = "binary",
    match: Optional[MatchResult] = None,
) -> Optional[Arb]:
    if not (settings.min_arb_margin <= sized.net_margin <= settings.max_arb_margin):
        return None

    confidence, flags, notes = _score(kind, sized, quotes, close_time, match)
    if confidence < settings.min_confidence:
        return None

    return Arb(
        id=_arb_id(kind, quotes),
        kind=kind,
        title=title,
        category=category,
        venues=tuple(dict.fromkeys(q.venue for q in quotes)),
        market_key=market_key,
        legs=sized.legs,
        total_stake=sized.total_stake,
        book=sized.book,
        margin=sized.margin,
        net_margin=sized.net_margin,
        profit=sized.profit,
        worst_case_profit=sized.worst_case_profit,
        payout_if=sized.payout_if,
        max_stake_available=sized.max_stake_available,
        confidence=confidence,
        flags=flags,
        notes=notes,
        close_time=close_time,
    )


# ------------------------------------------------------------ single-event


def detect_intra_market(event: Event, **kw) -> Iterator[Arb]:
    """A single market whose own YES and NO asks sum to less than $1.

    On a healthy book this cannot happen -- it is a crossed market. It does occur
    briefly on prediction markets when one side is repriced before the other, and
    it is the cleanest arb available because both legs settle under one rulebook.
    """
    for market in event.markets:
        pair = _binary_outcomes(market)
        if pair is None:
            continue
        yes, no = pair
        if yes.effective_price + no.effective_price >= 1.0:
            continue
        sized = size_arb(
            [yes, no],
            target_stake=kw.get("target_stake"),
            venue_limits=kw.get("venue_limits"),
            event_title=event.title,
        )
        if sized is None:
            continue
        arb = _finalise(
            ArbKind.BINARY_COMPLEMENT,
            event.title,
            event.category,
            [yes, no],
            sized,
            event.close_time,
        )
        if arb is not None:
            yield arb


def detect_dutch(event: Event, **kw) -> Iterator[Arb]:
    """Dutch books across a mutually exclusive, exhaustive event (Part I s5.1).

    YES side: buying one contract on every outcome costs sum(p_i) and returns $1,
    so the arb condition is sum(p_i) < 1.

    NO side: buying one NO on every outcome returns $(n-1), because exactly one
    outcome occurs and every other NO settles. The condition is sum(p_no) < n-1.
    This is the direction that actually fires in practice, since long-tail
    outcomes are systematically overpriced on the YES side.

    Requires `mutually_exclusive`: without it the outcomes do not partition the
    sample space and the formula does not apply (Part I s5.2).
    """
    if not event.mutually_exclusive or len(event.markets) < 2:
        return

    yes_quotes: list[Quote] = []
    no_quotes: list[Quote] = []
    for market in event.markets:
        pair = _binary_outcomes(market)
        if pair is None:
            return  # a non-binary leg breaks the partition; abandon the event
        yes, no = pair
        yes_quotes.append(yes)
        no_quotes.append(no)

    n = len(yes_quotes)
    if n > _MAX_DUTCH_LEGS:
        logger.debug(f"dutch: skipping {event.title!r}, {n} legs is unplaceable")
        return

    # --- Exhaustiveness guard (Part I s5.2) --------------------------------
    # Reject sets whose YES prices sum far below 1: those outcomes do not cover
    # the sample space, so the "arb" would leave a real outcome unhedged.
    yes_sum = sum(q.effective_price for q in yes_quotes)
    if yes_sum < _DUTCH_COMPLETENESS_FLOOR:
        logger.debug(
            f"dutch: {event.title!r} sums to {yes_sum:.3f} across {n} outcomes -- "
            f"incomplete outcome set, not an arbitrage"
        )
        return

    # --- YES side ---------------------------------------------------------
    if yes_sum < 1.0:
        sized = size_arb(
            yes_quotes,
            target_stake=kw.get("target_stake"),
            venue_limits=kw.get("venue_limits"),
            payout_multiple=1.0,
            event_title=event.title,
        )
        if sized is not None:
            arb = _finalise(
                ArbKind.DUTCH_YES,
                f"{event.title} - buy every outcome",
                event.category,
                yes_quotes,
                sized,
                event.close_time,
                market_key="dutch_yes",
            )
            if arb is not None:
                yield arb

    # --- NO side ----------------------------------------------------------
    if n >= 3 and sum(q.effective_price for q in no_quotes) < (n - 1):
        sized = size_arb(
            no_quotes,
            target_stake=kw.get("target_stake"),
            venue_limits=kw.get("venue_limits"),
            payout_multiple=float(n - 1),
            event_title=event.title,
        )
        if sized is not None:
            arb = _finalise(
                ArbKind.DUTCH_NO,
                f"{event.title} - fade every outcome",
                event.category,
                no_quotes,
                sized,
                event.close_time,
                market_key="dutch_no",
            )
            if arb is not None:
                yield arb


def detect_sportsbook(event: Event, **kw) -> Iterator[Arb]:
    """Best price per outcome across books (Part I s3.6 / s4.1)."""
    for market in event.markets:
        if market.key == "binary":
            continue
        best: list[Quote] = []
        for outcome in market.outcomes:
            q = outcome.best()
            if q is None:
                best = []
                break
            best.append(q)
        if len(best) < 2:
            continue
        if sum(q.effective_price for q in best) >= 1.0:
            continue
        # Only interesting if the legs are actually at different books.
        if len({q.ticker for q in best}) < 2:
            continue
        sized = size_arb(
            best,
            target_stake=kw.get("target_stake"),
            venue_limits=kw.get("venue_limits"),
            event_title=event.title,
        )
        if sized is None:
            continue
        arb = _finalise(
            ArbKind.SPORTSBOOK,
            event.title,
            event.category,
            best,
            sized,
            event.close_time or event.commence_time,
            market_key=market.key,
        )
        if arb is not None:
            yield arb


# -------------------------------------------------------------- cross-venue


def _cross_pairs(
    a_yes: Quote, a_no: Quote, b_yes: Quote, b_no: Quote
) -> list[tuple[Quote, Quote]]:
    """The two ways to cover a binary question across two venues."""
    return [(a_yes, b_no), (b_yes, a_no)]


def detect_cross_venue(events: Sequence[Event], **kw) -> Iterator[Arb]:
    """Same question on two venues: buy YES on one, NO on the other.

    Titles are matched by `normalise.match_titles`, which enforces hard guards on
    thresholds, dates and direction before any fuzzy comparison. The match score
    travels with the opportunity and is discounted in the confidence score, since
    a paired title is weaker evidence than a shared identifier (Part II s6.2).
    """
    # Only single-market (genuinely binary) events pair cleanly. A multi-outcome
    # event would need per-outcome matching, which is a different problem.
    binaries: list[tuple[Event, Quote, Quote]] = []
    for ev in events:
        if len(ev.markets) != 1:
            continue
        pair = _binary_outcomes(ev.markets[0])
        if pair is None:
            continue
        binaries.append((ev, pair[0], pair[1]))

    by_venue: dict[str, list[tuple[Event, Quote, Quote]]] = {}
    for entry in binaries:
        by_venue.setdefault(entry[0].venue, []).append(entry)

    seen: set[str] = set()
    for venue_a, venue_b in itertools.combinations(sorted(by_venue), 2):
        for ev_a, a_yes, a_no in by_venue[venue_a]:
            for ev_b, b_yes, b_no in by_venue[venue_b]:
                match = match_titles(ev_a.title, ev_b.title)
                if not match.ok:
                    continue
                for leg1, leg2 in _cross_pairs(a_yes, a_no, b_yes, b_no):
                    if leg1.effective_price + leg2.effective_price >= 1.0:
                        continue
                    key = _arb_id(ArbKind.CROSS_VENUE, [leg1, leg2])
                    if key in seen:
                        continue
                    sized = size_arb(
                        [leg1, leg2],
                        target_stake=kw.get("target_stake"),
                        venue_limits=kw.get("venue_limits"),
                        event_title=ev_a.title,
                    )
                    if sized is None:
                        continue
                    close = min(
                        (t for t in (ev_a.close_time, ev_b.close_time) if t is not None),
                        default=None,
                    )
                    arb = _finalise(
                        ArbKind.CROSS_VENUE,
                        f"{ev_a.title}  ==  {ev_b.title}",
                        ev_a.category if ev_a.category != "other" else ev_b.category,
                        [leg1, leg2],
                        sized,
                        close,
                        market_key="cross_venue",
                        match=match,
                    )
                    if arb is not None:
                        seen.add(key)
                        yield arb


# ------------------------------------------------------------- orchestration


def scan_events(
    events: Sequence[Event],
    target_stake: Optional[float] = None,
    venue_limits: Optional[dict[str, float]] = None,
    kinds: Optional[set[ArbKind]] = None,
) -> list[Arb]:
    """Run every enabled detector over a normalised snapshot of the market."""
    kw = {"target_stake": target_stake, "venue_limits": venue_limits}
    wanted = kinds or set(ArbKind)
    found: list[Arb] = []

    for ev in events:
        try:
            if ArbKind.BINARY_COMPLEMENT in wanted:
                found.extend(detect_intra_market(ev, **kw))
            if ArbKind.DUTCH_YES in wanted or ArbKind.DUTCH_NO in wanted:
                found.extend(a for a in detect_dutch(ev, **kw) if a.kind in wanted)
            if ArbKind.SPORTSBOOK in wanted:
                found.extend(detect_sportsbook(ev, **kw))
        except Exception as exc:  # noqa: BLE001 - one bad event must not stop a scan
            logger.warning(f"detector failed on {ev.id}: {exc}")

    if ArbKind.CROSS_VENUE in wanted:
        try:
            found.extend(detect_cross_venue(events, **kw))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"cross-venue detector failed: {exc}")

    # Best first: net margin, then confidence.
    found.sort(key=lambda a: (a.net_margin * (a.confidence / 100.0)), reverse=True)
    return found


def candidate_events(events: Sequence[Event], slack: float = 0.04) -> list[Event]:
    """Events close enough to arbing to be worth an order-book fetch.

    Depth calls are the expensive part of a cycle (Part II s17.1), so they are
    spent only where the top-of-book sum is already within `slack` of the
    threshold. A book at 1.02 can become an arb after a real depth fetch reveals
    a better inside price; one at 1.30 cannot.
    """
    out: list[Event] = []
    for ev in events:
        interesting = False
        for market in ev.markets:
            pair = _binary_outcomes(market)
            if pair is None:
                continue
            if pair[0].effective_price + pair[1].effective_price < 1.0 + slack:
                interesting = True
                break
        if not interesting and ev.mutually_exclusive and len(ev.markets) >= 2:
            yes_sum = 0.0
            no_sum = 0.0
            n = 0
            for market in ev.markets:
                pair = _binary_outcomes(market)
                if pair is None:
                    break
                yes_sum += pair[0].effective_price
                no_sum += pair[1].effective_price
                n += 1
            if n >= 2 and (yes_sum < 1.0 + slack or no_sum < (n - 1) + slack):
                interesting = True
        if interesting:
            out.append(ev)
    return out
