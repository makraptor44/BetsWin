"""Canonical data models.

Part II s4: models are pure data with no IO. These are Pydantic models rather
than dataclasses so FastAPI can serialise them straight to the frontend without
a second DTO layer. All timestamps are timezone-aware UTC; conversion to local
time happens only at display.

The shape follows the book -- Quote (was Price) -> Outcome -> Market -> Event,
and ArbLeg -> Arb -- extended for prediction markets, where a "price" is the
cost of a contract that settles at $1 and every quote carries order-book depth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from . import odds as om


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Venue(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    SPORTSBOOK = "sportsbook"
    SMARKETS = "smarkets"
    BETFAIR = "betfair"


class ArbKind(str, Enum):
    """The structural family an opportunity belongs to."""

    # YES on one venue + NO on another (or the same) sum to less than $1.
    BINARY_COMPLEMENT = "binary_complement"
    # n mutually exclusive outcomes; buying every YES costs less than the $1 payout.
    DUTCH_YES = "dutch_yes"
    # n mutually exclusive outcomes; buying every NO costs less than the $(n-1) payout.
    DUTCH_NO = "dutch_no"
    # Same real-world event listed on two venues, matched by title.
    CROSS_VENUE = "cross_venue"
    # Classic best-price-per-outcome across sportsbooks (Part I s3/s4).
    SPORTSBOOK = "sportsbook"
    # A joint-event contract mispriced relative to a Gaussian-copula correlation
    # estimated from history -- see correlation_arb.py. NOT risk-free: this is a
    # directional bet, sized by fractional Kelly, that the market's implied
    # correlation converges toward the prior.
    CORRELATION = "correlation"


class Side(str, Enum):
    YES = "YES"
    NO = "NO"
    BACK = "BACK"
    LAY = "LAY"


# --------------------------------------------------------------------- quotes


class DepthLevel(BaseModel):
    """One price level of an order book."""

    model_config = ConfigDict(frozen=True)

    price: float
    size: float  # contracts (prediction markets) or currency notional


class Quote(BaseModel):
    """A single venue's executable price on a single outcome.

    `price` is the cost of one contract paying $1 (Part I s2.2 in probability
    space). `effective_price` folds in the venue's fee model so the detector
    compares like with like.
    """

    model_config = ConfigDict(frozen=True)

    venue: str
    market_id: str
    ticker: Optional[str] = None
    outcome: str
    side: Side = Side.YES
    price: float
    effective_price: float
    size_available: float = 0.0
    depth: tuple[DepthLevel, ...] = ()
    last_update: datetime = Field(default_factory=utcnow)
    url: Optional[str] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decimal_odds(self) -> float:
        """Raw decimal odds, d = 1/p (Part I s2.2)."""
        return om.prob_to_decimal(self.price)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_decimal_odds(self) -> float:
        """Fee-adjusted decimal odds -- the number the detector actually uses."""
        return om.prob_to_decimal(self.effective_price)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def implied_prob(self) -> float:
        return self.effective_price

    def notional_available(self) -> float:
        """Dollars of stake this quote can absorb at the quoted price."""
        return self.size_available * self.price


class Outcome(BaseModel):
    """One side of a market, with every venue's quote on it."""

    model_config = ConfigDict(frozen=True)

    name: str
    quotes: tuple[Quote, ...] = ()

    def best(self) -> Optional[Quote]:
        """Best executable quote = highest fee-adjusted decimal odds.

        Part I s3.6: only the best price on each outcome matters; the rest are
        strictly dominated.
        """
        if not self.quotes:
            return None
        return max(self.quotes, key=lambda q: q.effective_decimal_odds)

    def best_in(self, venues: set[str]) -> Optional[Quote]:
        allowed = [q for q in self.quotes if q.venue in venues]
        if not allowed:
            return None
        return max(allowed, key=lambda q: q.effective_decimal_odds)


class Market(BaseModel):
    """A market on an event: a binary question, an h2h line, a totals line."""

    model_config = ConfigDict(frozen=True)

    key: str  # canonical key, e.g. 'binary', 'h2h', 'totals_2.5'
    outcomes: tuple[Outcome, ...] = ()

    def outcome(self, name: str) -> Optional[Outcome]:
        return next((o for o in self.outcomes if o.name == name), None)


class Event(BaseModel):
    """A real-world event carrying one or more markets."""

    model_config = ConfigDict(frozen=True)

    id: str
    venue: str
    title: str
    category: str = "other"
    #: Settlement currency. Legs are only ever combined within one currency:
    #: at 1% margins an unhedged FX leg is larger than the edge.
    currency: str = "USD"
    league: Optional[str] = None
    home: Optional[str] = None
    away: Optional[str] = None
    commence_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    mutually_exclusive: bool = False
    volume_usd: float = 0.0
    liquidity_usd: float = 0.0
    url: Optional[str] = None
    markets: tuple[Market, ...] = ()

    def market(self, key: str) -> Optional[Market]:
        return next((m for m in self.markets if m.key == key), None)


# ------------------------------------------------------------------- the arb


class ArbLeg(BaseModel):
    """One bet in an arbitrage set."""

    model_config = ConfigDict(frozen=True)

    venue: str
    market_id: str
    ticker: Optional[str] = None
    outcome: str
    side: Side = Side.YES
    price: float
    effective_price: float
    decimal_odds: float
    effective_decimal_odds: float
    stake: float = 0.0
    contracts: float = 0.0
    fee: float = 0.0
    size_available: float = 0.0
    url: Optional[str] = None
    event_title: Optional[str] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def payout(self) -> float:
        """Return if this leg wins.

        `stake` is the ALL-IN outlay -- contract cost plus fees -- so the number
        of contracts it buys is stake / effective_price, and each settles at $1.
        Multiplying the all-in stake by `decimal_odds` (which is 1/price, the
        PRE-fee price) charges the fee and then pays out as though it had not
        been charged. On $100 all-in at an effective price of 0.52 that reported
        $200.00 against a true payout of $192.31.
        """
        return self.stake * self.effective_decimal_odds

    @computed_field  # type: ignore[prop-decorator]
    @property
    def net_payout(self) -> float:
        """Return net of fees.

        Identical to `payout`: the fee is already inside `stake`, so it is
        already inside the contract count this pays out on. Subtracting `fee`
        again here deducted it twice. Kept as a field because the dashboard and
        the stored payload both read it.
        """
        return self.payout


class ArbStatus(str, Enum):
    """Where an opportunity sits in its lifecycle.

    The distinction between the last two is the one that matters operationally.
    EXPIRED means the window we could vouch for has passed -- the prices may
    still be good, but we can no longer assert it. INVALIDATED means we looked
    again and the arbitrage was gone. Collapsing them loses the signal that
    tells you whether your scan interval is too slow or the market is simply
    efficient.
    """

    LIVE = "live"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


#: Inside this many seconds an opportunity reports EXPIRING rather than LIVE.
#: Thirty seconds is roughly one scan interval: past that point the next
#: observation may not arrive before the window closes.
EXPIRING_WINDOW_SECONDS = 30.0


class RiskFlag(str, Enum):
    """Named failure modes from Part I s9 and s5.3."""

    SUSPECT_MARGIN = "suspect_margin"          # s5.3: too good to be true
    THIN_LIQUIDITY = "thin_liquidity"          # cannot fill at the quoted size
    WIDE_SPREAD = "wide_spread"                # top of book is not representative
    STALE_QUOTE = "stale_quote"                # s9.3: price may have moved
    CROSS_VENUE_RULES = "cross_venue_rules"    # s9.2: different rulebooks
    FUZZY_MATCH = "fuzzy_match"                # s6.2: titles matched, not identical
    LONG_DATED = "long_dated"                  # capital locked for months
    NEAR_RESOLUTION = "near_resolution"        # settles imminently
    FEE_SENSITIVE = "fee_sensitive"            # fees consume most of the edge
    ROUNDING_EXPOSURE = "rounding_exposure"    # s8.3: stakes rounded, unequal profit
    SINGLE_JURISDICTION = "single_jurisdiction"  # both legs need one specific country
    STATISTICAL_EDGE = "statistical_edge"      # directional, not risk-free -- full stake at risk


class Arb(BaseModel):
    """A detected arbitrage opportunity, fully sized and risk-scored."""

    id: str
    kind: ArbKind
    #: "arbitrage" legs lock a profit regardless of outcome (worst_case_profit is
    #: a guarantee). "directional" is a modelled edge with real variance --
    #: worst_case_profit is the loss if the bet is simply wrong. Every field
    #: below is populated for both, but only means "guaranteed" for the former.
    strategy: Literal["arbitrage", "directional"] = "arbitrage"
    title: str
    category: str = "other"
    venues: tuple[str, ...] = ()
    market_key: str = "binary"
    legs: tuple[ArbLeg, ...] = ()

    # --- executability (see venues.py) -----------------------------------
    #: Execution zone every leg belongs to. Legs never span zones.
    zone: str = "unknown"
    zone_label: str = ""
    #: Settlement currency shared by every leg.
    currency: str = "USD"
    #: Places one operator could hold all the accounts. ("*",) means broadly
    #: available; a short list means the trade is location-specific.
    placeable_from: tuple[str, ...] = ()

    total_stake: float = 0.0
    book: float = 1.0             # B_combined (Part I s2.4)
    margin: float = 0.0           # m = 1/B - 1, gross of fees
    net_margin: float = 0.0       # after venue fees
    profit: float = 0.0           # guaranteed profit at the sized stake
    worst_case_profit: float = 0.0
    payout_if: dict[str, float] = Field(default_factory=dict)

    max_stake_available: float = 0.0   # depth-constrained ceiling
    confidence: int = 50               # 0-100 quality score
    flags: tuple[RiskFlag, ...] = ()
    notes: tuple[str, ...] = ()

    detected_at: datetime = Field(default_factory=utcnow)
    close_time: Optional[datetime] = None
    last_seen: datetime = Field(default_factory=utcnow)
    #: Bumped only when the PRICES moved, unlike `last_seen`, which is bumped
    #: every time the scan re-observes the same opportunity. A feed that says
    #: "updated 2s ago" when nothing has changed for ten minutes is noise.
    last_updated_at: datetime = Field(default_factory=utcnow)
    #: The instant beyond which this opportunity can no longer be asserted.
    #:
    #: Derived, never assigned arbitrarily -- see `detector.expiry_for`. It is
    #: the earliest of: the market closing, and the point at which the oldest
    #: quote behind it has aged past the staleness horizon. Both are facts the
    #: providers gave us.
    expires_at: Optional[datetime] = None
    #: Set when the scanner retires the opportunity, so the reason survives.
    invalidated_at: Optional[datetime] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_suspect(self) -> bool:
        """Part I s5.3: treat anything above ~5% as a red flag until verified."""
        return RiskFlag.SUSPECT_MARGIN in self.flags

    @computed_field  # type: ignore[prop-decorator]
    @property
    def roi_pct(self) -> float:
        if self.total_stake <= 0:
            return 0.0
        return 100.0 * self.worst_case_profit / self.total_stake

    @computed_field  # type: ignore[prop-decorator]
    @property
    def seconds_to_expiry(self) -> Optional[float]:
        """Seconds until this can no longer be asserted. Negative once past."""
        if self.expires_at is None:
            return None
        return (self.expires_at - utcnow()).total_seconds()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> ArbStatus:
        """Lifecycle state, derived rather than stored.

        Storing it would mean a row could be LIVE in the database while its own
        expires_at had passed -- the two would need reconciling on every read,
        and whichever won would be the one nobody was looking at.
        """
        if self.invalidated_at is not None:
            return ArbStatus.INVALIDATED
        remaining = self.seconds_to_expiry
        if remaining is None:
            return ArbStatus.LIVE
        if remaining <= 0:
            return ArbStatus.EXPIRED
        if remaining <= EXPIRING_WINDOW_SECONDS:
            return ArbStatus.EXPIRING
        return ArbStatus.LIVE

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hours_to_close(self) -> Optional[float]:
        if self.close_time is None:
            return None
        return (self.close_time - utcnow()).total_seconds() / 3600.0

    def summary(self) -> str:
        """One-line rendering, as in Part II s4."""
        legs = " | ".join(
            f"{l.outcome}@{l.effective_decimal_odds:.3f}({l.venue}):${l.stake:.2f}"
            for l in self.legs
        )
        return (
            f"[{self.net_margin * 100:.2f}%] {self.title} ({self.market_key}) "
            f"-> {legs} -> ${self.worst_case_profit:.2f} profit"
        )

    def dedupe_key(self) -> str:
        """Identity for the scanner's dedup window (Part II s9)."""
        legs = "|".join(
            f"{l.venue}:{l.market_id}:{l.outcome}:{l.effective_price:.4f}"
            for l in sorted(self.legs, key=lambda x: (x.venue, x.market_id, x.outcome))
        )
        return f"{self.kind.value}|{legs}"


# ------------------------------------------------------------------ analytics


class NearMiss(BaseModel):
    """A book that is close to arbing but has not crossed.

    Zero opportunities is the normal state of a reasonably efficient market, and
    a dashboard that shows nothing in that state is indistinguishable from a
    dashboard that is broken. Near misses are the evidence of work: they are the
    tightest books the scanner found this cycle, ordered by how far they are
    from crossing, so an operator can see the market breathing and know which
    events are worth watching before they cross.
    """

    id: str
    title: str
    venue: str
    zone: str = "unknown"
    category: str = "other"
    kind: ArbKind = ArbKind.BINARY_COMPLEMENT
    #: Combined book. Below 1.0 is an arbitrage; this is what did not get there.
    book: float = 1.0
    #: How far from crossing, in basis points. 0 means it just crossed.
    gap_bps: float = 0.0
    #: Same gap using quoted prices, before fees. The difference between the two
    #: is what the venue's fee schedule costs you.
    gap_bps_gross: float = 0.0
    best_outcome: str = ""
    outcomes: int = 2
    liquidity_usd: float = 0.0
    close_time: Optional[datetime] = None
    url: Optional[str] = None
    seen_at: datetime = Field(default_factory=utcnow)


class ScanStats(BaseModel):
    """Telemetry for one scan cycle."""

    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    events_scanned: int = 0
    markets_scanned: int = 0
    quotes_scanned: int = 0
    arbs_found: int = 0
    new_arbs: int = 0
    #: Still open but not re-priced this cycle, because a venue they depend on
    #: did not answer. Held rather than retired -- see Scanner.scan_once.
    arbs_unconfirmed: int = 0
    #: Re-observed this cycle at a different price. Distinct from `new_arbs`:
    #: an opportunity that moved is not a new one, but it is not unchanged
    #: either, and the activity stream needs to say which.
    updated_arbs: int = 0
    #: Retired because the window we could vouch for had passed.
    expired_arbs: int = 0
    #: Retired because we re-priced it and the edge was gone.
    invalidated_arbs: int = 0
    near_misses: int = 0
    #: Tightest book seen this cycle, in basis points from crossing. The number
    #: that moves every scan even when `arbs_found` is stuck at zero.
    tightest_gap_bps: Optional[float] = None
    by_venue: dict[str, int] = Field(default_factory=dict)
    by_zone: dict[str, int] = Field(default_factory=dict)
    #: Cross-venue pairs rejected because the venues sit in different zones.
    cross_zone_rejected: int = 0
    errors: list[str] = Field(default_factory=list)
    breaker_tripped: bool = False


class EngineStatus(BaseModel):
    running: bool = False
    demo_mode: bool = False
    last_scan: Optional[ScanStats] = None
    next_scan_in: float = 0.0
    poll_interval: int = 45
    live_arbs: int = 0
    total_detected: int = 0
    uptime_seconds: float = 0.0
    sources: dict[str, bool] = Field(default_factory=dict)
    breaker_tripped: bool = False
    breaker_reason: Optional[str] = None
    #: Execution zones with a live source behind them, and the pairing policy.
    zones: list[str] = Field(default_factory=list)
    operator_jurisdiction: str = ""
    enforce_zone_pairing: bool = True
    near_misses: int = 0
