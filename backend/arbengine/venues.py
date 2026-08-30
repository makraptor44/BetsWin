"""Venue registry and execution zones.

The problem this file solves
---------------------------

A cross-venue arbitrage is only real if *one person* can place *both* legs. The
detector is happy to pair a Kalshi contract with a Betfair price, and the
arithmetic will look immaculate, but nobody can take that trade: the accounts
sit in different jurisdictions, fund in different currencies, and the only way
to hold both is to misrepresent where you are. An "opportunity" that requires
falsifying your location is not an opportunity -- it is a compliance incident
with a spreadsheet attached.

So venues are partitioned into EXECUTION ZONES. A zone is a set of venues that
a single operator can plausibly hold funded, KYC'd accounts on, from one
location, in one currency. Cross-venue detection runs *within* a zone and never
across zones:

    polymarket <-> kalshi      allowed   (USD-settled $1 binary contracts)
    betfair    <-> smarkets    allowed   (GBP back/lay exchanges, UK/IE/EU)
    betfair    <-> kalshi      REJECTED  (different zone)

This is a deliberate reduction in the opportunity set. It buys three things:

1.  Every surfaced pair is actually placeable by the operator, so the hit rate
    of the alert stream goes up even though its volume goes down.
2.  No FX leg. Pairing a GBP exchange against a USD contract market leaves the
    "risk-free" profit exposed to the currency, which at typical 1% arb margins
    is the dominant term -- a 1% edge is erased by a 1% move in GBPUSD.
3.  Settlement conventions inside a zone agree. Two $1-contract venues void and
    settle alike; an exchange voiding a market and a contract market resolving
    it "NO" are not the same event, and that difference is unhedgeable.

Everything here is DATA, deliberately. Jurisdiction lists are operational
defaults for deciding what to pair, not legal advice and not a substitute for
each venue's own terms. Edit them; the engine reads them at scan time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


class Zone(str, Enum):
    """A set of venues one operator can reach from a single location."""

    US_PREDICTION = "us_prediction"
    UK_EXCHANGE = "uk_exchange"
    US_SPORTSBOOK = "us_sportsbook"
    UNKNOWN = "unknown"


class Structure(str, Enum):
    """How a venue expresses a price. Determines the maths, not just the label."""

    #: Binary contract settling at $1. Price IS the implied probability.
    CONTRACT = "contract"
    #: Back/lay exchange. Decimal odds, commission charged on net winnings.
    EXCHANGE = "exchange"
    #: Fixed-odds bookmaker. Margin priced into the odds, no separate fee.
    BOOK = "book"


@dataclass(frozen=True)
class ZoneInfo:
    key: Zone
    label: str
    currency: str
    #: Why these venues belong together, in one line, for the UI.
    rationale: str
    settlement: str


ZONES: dict[Zone, ZoneInfo] = {
    Zone.US_PREDICTION: ZoneInfo(
        key=Zone.US_PREDICTION,
        label="USD prediction markets",
        currency="USD",
        rationale=(
            "Dollar-denominated binary contracts that settle at $1. Both venues "
            "quote in probability space, so a price on one is directly "
            "comparable to a price on the other with no FX leg."
        ),
        settlement="Contracts resolve to $1 or $0 against a published source.",
    ),
    Zone.UK_EXCHANGE: ZoneInfo(
        key=Zone.UK_EXCHANGE,
        label="UK/EU betting exchanges",
        currency="GBP",
        rationale=(
            "Sterling peer-to-peer exchanges under UK Gambling Commission "
            "licences. Both charge commission on net winnings rather than "
            "pricing a margin into the odds, and both settle on the same "
            "sporting result."
        ),
        settlement="Bets settle on the official result; voids return the stake.",
    ),
    Zone.US_SPORTSBOOK: ZoneInfo(
        key=Zone.US_SPORTSBOOK,
        label="US sportsbooks",
        currency="USD",
        rationale=(
            "Fixed-odds books priced through one aggregator, state-licensed and "
            "reachable from the same account footprint."
        ),
        settlement="Fixed-odds settlement on the book's own rulebook.",
    ),
    Zone.UNKNOWN: ZoneInfo(
        key=Zone.UNKNOWN,
        label="Unclassified",
        currency="",
        rationale="Venue not in the registry; never paired with anything.",
        settlement="Unknown.",
    ),
}


@dataclass(frozen=True)
class VenueInfo:
    """Everything the engine needs to know about a venue that is not a price."""

    name: str
    label: str
    zone: Zone
    structure: Structure
    currency: str
    #: ISO-3166 alpha-2 codes an operator can realistically hold an account
    #: from. "*" means "broadly available, subject to the venue's own terms".
    jurisdictions: frozenset[str]
    #: Jurisdictions the venue explicitly turns away. Subtracted from "*".
    excluded: frozenset[str] = frozenset()
    regulator: str = ""
    #: Commission on net winnings (exchanges). Contract venues use fees.py.
    commission: float = 0.0
    url: str = ""
    notes: str = ""
    #: Live market data reachable without credentials.
    public_data: bool = True

    def serves(self, jurisdiction: str) -> bool:
        cc = jurisdiction.strip().upper()
        if not cc:
            return True
        if cc in self.excluded:
            return False
        return "*" in self.jurisdictions or cc in self.jurisdictions


# ---------------------------------------------------------------- the registry
#
# Jurisdiction sets are the operational question "can one person hold funded
# accounts on all of these at once", not a legal opinion. They are intentionally
# conservative: a venue is listed as unavailable wherever its own terms are
# ambiguous, because a wrongly-permitted pair produces an unplaceable trade.

_VENUES: dict[str, VenueInfo] = {
    "polymarket": VenueInfo(
        name="polymarket",
        label="Polymarket",
        zone=Zone.US_PREDICTION,
        structure=Structure.CONTRACT,
        currency="USD",
        jurisdictions=frozenset({"*"}),
        excluded=frozenset({"US"}),
        regulator="CFTC-registered (Polymarket US); offshore CLOB for non-US",
        url="https://polymarket.com",
        notes=(
            "USDC-settled binary contracts on Polygon. The order book is public "
            "and needs no credentials to read. US persons are restricted from "
            "trading the offshore book whatever the market data says."
        ),
    ),
    "kalshi": VenueInfo(
        name="kalshi",
        label="Kalshi",
        zone=Zone.US_PREDICTION,
        structure=Structure.CONTRACT,
        currency="USD",
        jurisdictions=frozenset({"*"}),
        regulator="CFTC-regulated designated contract market",
        url="https://kalshi.com",
        notes=(
            "Dollar-settled event contracts. Charges an explicit trading fee "
            "that peaks at a price of 0.50 -- exactly where arbitrage lives."
        ),
    ),
    "smarkets": VenueInfo(
        name="smarkets",
        label="Smarkets",
        zone=Zone.UK_EXCHANGE,
        structure=Structure.EXCHANGE,
        currency="GBP",
        jurisdictions=frozenset({"GB", "IE", "MT", "AT", "DE", "ES", "FI", "SE"}),
        excluded=frozenset({"US", "AU", "FR", "IT"}),
        regulator="UK Gambling Commission / Malta Gaming Authority",
        commission=0.02,
        url="https://smarkets.com",
        notes=(
            "Peer-to-peer exchange quoting in probability units, which maps "
            "directly onto the $1-contract model. Market data is public."
        ),
    ),
    "betfair": VenueInfo(
        name="betfair",
        label="Betfair Exchange",
        zone=Zone.UK_EXCHANGE,
        structure=Structure.EXCHANGE,
        currency="GBP",
        jurisdictions=frozenset({"GB", "IE", "MT", "ES", "IT", "SE", "DK", "RO"}),
        excluded=frozenset({"US"}),
        regulator="UK Gambling Commission",
        commission=0.05,
        url="https://www.betfair.com/exchange",
        notes=(
            "The deepest exchange book in the zone. Requires an application key "
            "and a session token; without them the source stays dark."
        ),
        public_data=False,
    ),
    "sportsbook": VenueInfo(
        name="sportsbook",
        label="US sportsbooks",
        zone=Zone.US_SPORTSBOOK,
        structure=Structure.BOOK,
        currency="USD",
        jurisdictions=frozenset({"US"}),
        regulator="State gaming commissions",
        url="https://the-odds-api.com",
        notes="Aggregated fixed-odds prices. Needs an ODDS_API_KEY.",
        public_data=False,
    ),
    "demo": VenueInfo(
        name="demo",
        label="Demo",
        zone=Zone.US_PREDICTION,
        structure=Structure.CONTRACT,
        currency="USD",
        jurisdictions=frozenset({"*"}),
        notes="Offline fixtures.",
    ),
}


# ------------------------------------------------------------------- lookups


_UNKNOWN = VenueInfo(
    name="unknown",
    label="Unknown venue",
    zone=Zone.UNKNOWN,
    structure=Structure.CONTRACT,
    currency="",
    jurisdictions=frozenset(),
)


def venue(name: str) -> VenueInfo:
    """Registry entry for a venue, or a never-pairable placeholder."""
    return _VENUES.get(name.lower().strip(), _UNKNOWN)


def known(name: str) -> bool:
    return name.lower().strip() in _VENUES


def all_venues() -> list[VenueInfo]:
    return list(_VENUES.values())


def zone_of(name: str) -> Zone:
    return venue(name).zone


def zone_info(zone: Zone) -> ZoneInfo:
    return ZONES.get(zone, ZONES[Zone.UNKNOWN])


def venues_in(zone: Zone) -> list[VenueInfo]:
    return [v for v in _VENUES.values() if v.zone is zone and v.name != "demo"]


def zone_for_venues(names: Iterable[str]) -> Zone:
    """The single zone a leg set belongs to, or UNKNOWN if it spans zones."""
    zones = {zone_of(n) for n in names}
    if len(zones) == 1:
        return zones.pop()
    return Zone.UNKNOWN


# ---------------------------------------------------------- the pairing rule


@dataclass(frozen=True)
class PairVerdict:
    """Whether two venues may be arbed against each other, and why."""

    ok: bool
    reason: str
    zone: Zone = Zone.UNKNOWN
    #: Places an operator could hold every account. Empty when ok is False.
    #: ("*",) means "broadly available" -- read it together with `excluded`,
    #: which is never empty for a pair that turns any country away.
    jurisdictions: tuple[str, ...] = ()
    #: Countries at least one venue in the set refuses. Meaningful even when
    #: `jurisdictions` is ("*",): "everywhere except here".
    excluded: tuple[str, ...] = ()


def blocked_jurisdictions(*names: str) -> tuple[str, ...]:
    """Every country any venue in the set turns away."""
    blocked: set[str] = set()
    for n in names:
        blocked |= venue(n).excluded
    return tuple(sorted(blocked))


def common_jurisdictions(*names: str) -> tuple[str, ...]:
    """Where one person could hold funded accounts on every venue named.

    Takes any number of venues, not two. `legs_are_placeable` used to walk a
    chain of pairs and return the FIRST-versus-LAST intersection, so on a
    three-leg set the middle venue was never intersected and the answer could
    name a country it does not serve.

    A wildcard is not a licence to ignore exclusions. Polymarket is
    `jurisdictions={"*"}, excluded={"US"}`; pairing it with Kalshi used to
    short-circuit to ("*",), and since "*" is not a country code the exclusion
    filter could never remove anything from it -- so the pair was reported
    placeable from anywhere, US included. The wildcard is now only returned
    alongside the exclusions that qualify it.
    """
    infos = [venue(n) for n in names]
    if not infos:
        return ()

    explicit = [i.jurisdictions for i in infos if "*" not in i.jurisdictions]
    if not explicit:
        merged: tuple[str, ...] = ("*",)
    else:
        common = set(explicit[0])
        for js in explicit[1:]:
            common &= js
        merged = tuple(sorted(common))

    blocked = set(blocked_jurisdictions(*names))
    return tuple(cc for cc in merged if cc not in blocked)


def can_pair(a: str, b: str, operator_jurisdiction: str = "") -> PairVerdict:
    """The rule the cross-venue detector consults before pairing anything.

    Same zone, both venues known, and -- if the operator has declared where
    they are -- both venues reachable from there. Anything else is rejected
    with a reason the UI can show, because a silently dropped pair is
    indistinguishable from a bug.
    """
    va, vb = venue(a), venue(b)

    if va.zone is Zone.UNKNOWN or vb.zone is Zone.UNKNOWN:
        return PairVerdict(False, f"{a} or {b} is not in the venue registry.")

    if va.name == vb.name:
        return PairVerdict(False, "Both legs are on the same venue.")

    if va.zone is not vb.zone:
        return PairVerdict(
            False,
            f"{va.label} ({zone_info(va.zone).label}, {va.currency}) and "
            f"{vb.label} ({zone_info(vb.zone).label}, {vb.currency}) sit in "
            f"different execution zones. Holding both would need accounts in "
            f"two jurisdictions and would leave an unhedged "
            f"{va.currency}/{vb.currency} leg.",
        )

    shared = common_jurisdictions(a, b)
    if not shared:
        return PairVerdict(
            False,
            f"No jurisdiction serves both {va.label} and {vb.label}.",
            zone=va.zone,
        )

    if operator_jurisdiction:
        cc = operator_jurisdiction.strip().upper()
        if not (va.serves(cc) and vb.serves(cc)):
            unreachable = va.label if not va.serves(cc) else vb.label
            return PairVerdict(
                False,
                f"{unreachable} does not serve {cc}, the jurisdiction this "
                f"engine is configured to trade from.",
                zone=va.zone,
            )

    return PairVerdict(
        True,
        f"Both venues sit in {zone_info(va.zone).label} and settle in "
        f"{va.currency}.",
        zone=va.zone,
        jurisdictions=shared,
        excluded=blocked_jurisdictions(a, b),
    )


def legs_are_placeable(
    venues: Iterable[str], operator_jurisdiction: str = ""
) -> PairVerdict:
    """Extend `can_pair` to a leg set of any size (Dutch books, sportsbooks).

    The jurisdictions are intersected across the WHOLE set. This used to check
    consecutive pairs and then return `can_pair(first, last)`, whose answer is
    the intersection of those two venues only -- so on a three-leg book across
    A, B and C the result could name a country B does not serve.
    """
    names = list(dict.fromkeys(v.lower().strip() for v in venues))
    if not names:
        return PairVerdict(False, "No venues to place.", Zone.UNKNOWN)

    cc = operator_jurisdiction.strip().upper()

    if len(names) == 1:
        v = venue(names[0])
        if cc and not v.serves(cc):
            return PairVerdict(
                False, f"{v.label} does not serve {cc}.", zone=v.zone
            )
        return PairVerdict(
            True,
            "Single-venue trade; no cross-venue risk.",
            v.zone,
            common_jurisdictions(names[0]),
            blocked_jurisdictions(names[0]),
        )

    # Every pair has to clear the zone and jurisdiction rule, not just the
    # consecutive ones -- zone equality is transitive but "serves" is not.
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            verdict = can_pair(names[i], names[j], operator_jurisdiction)
            if not verdict.ok:
                return verdict

    shared = common_jurisdictions(*names)
    if not shared:
        return PairVerdict(
            False,
            "No single jurisdiction serves every venue in this set: "
            + ", ".join(venue(n).label for n in names),
            zone=zone_for_venues(names),
        )

    return PairVerdict(
        True,
        f"All {len(names)} legs sit in "
        f"{zone_info(zone_for_venues(names)).label}.",
        zone_for_venues(names),
        shared,
        blocked_jurisdictions(*names),
    )


def zones_available_from(jurisdiction: str) -> list[Zone]:
    """Zones with at least two venues reachable from `jurisdiction`.

    Two is the floor because a zone with one reachable venue cannot produce a
    cross-venue trade, only single-venue ones.
    """
    cc = jurisdiction.strip().upper()
    out: list[Zone] = []
    for z in (Zone.US_PREDICTION, Zone.UK_EXCHANGE, Zone.US_SPORTSBOOK):
        reachable = [v for v in venues_in(z) if v.serves(cc)]
        if len(reachable) >= 2:
            out.append(z)
    return out


def describe(zone: Zone) -> dict[str, object]:
    """Serialisable zone summary for the API."""
    info = zone_info(zone)
    members = venues_in(zone)
    return {
        "key": info.key.value,
        "label": info.label,
        "currency": info.currency,
        "rationale": info.rationale,
        "settlement": info.settlement,
        "venues": [v.name for v in members],
        "venue_labels": [v.label for v in members],
    }


__all__ = [
    "Zone",
    "ZoneInfo",
    "ZONES",
    "Structure",
    "VenueInfo",
    "PairVerdict",
    "venue",
    "known",
    "all_venues",
    "zone_of",
    "zone_info",
    "venues_in",
    "zone_for_venues",
    "can_pair",
    "legs_are_placeable",
    "common_jurisdictions",
    "blocked_jurisdictions",
    "zones_available_from",
    "describe",
]
