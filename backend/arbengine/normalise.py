"""Cross-venue reconciliation (Part II s6).

Polymarket and Kalshi describe the same real-world question in different words:
"Will Bitcoin close above $100,000 on Dec 31?" versus "BTC above $100k". Matching
them is what makes cross-venue arbitrage possible, and mis-matching them is the
single largest source of false positives (Part II s6.2) -- a phantom arb between
two questions that are not actually the same bet loses real money.

Three defences are used here:

1. Aggressive normalisation before comparison (case, punctuation, filler words,
   number formats such as "100k" -> "100000").
2. A high fuzzy-match floor, with the score carried forward so the detector can
   discount confidence rather than silently trusting the match.
3. A hard guard on extracted numbers and dates: if both titles mention a
   threshold or a date and they disagree, the pair is rejected outright however
   similar the words are. This is the "different lines dressed as the same
   market" trap from Part I s5.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from rapidfuzz import fuzz

from .config import settings
from .models import Event

# Words that carry no discriminating power between venues.
_STOPWORDS = {
    "will", "the", "a", "an", "be", "is", "are", "to", "of", "in", "on", "at",
    "for", "by", "and", "or", "who", "what", "which", "does", "do", "did",
    "market", "markets", "before", "after", "than", "this", "that", "it",
    "there", "any", "win", "wins", "winner",
}

_TEAM_ALIASES = {
    "man city": "manchester city",
    "man utd": "manchester united",
    "man united": "manchester united",
    "psg": "paris saint germain",
    "spurs": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "bayern": "bayern munich",
    "inter": "inter milan",
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "gop": "republican",
    "dems": "democrat",
    "democrats": "democrat",
    "democratic": "democrat",
    "republicans": "republican",
    "fed": "federal reserve",
    "potus": "president",
    "us": "united states",
    "usa": "united states",
    "u s": "united states",
    "uk": "united kingdom",
}

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_MONTH_NAMES = (
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
    "aug|august|sep|sept|september|oct|october|nov|november|dec|december"
)
_MONTH_RE = re.compile(rf"\b({_MONTH_NAMES})\b", re.I)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_NUM_RE = re.compile(r"(?<![\w.])(\d+\.?\d*)\s*([kmb])?(?![\w])", re.I)

# "Dec 31", "31 December", "12/31" -- day numbers are calendar noise, never
# thresholds, and must not be mistaken for one.
_DATE_FRAGMENT_RE = re.compile(
    rf"\b(?:{_MONTH_NAMES})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_NAMES})\b"
    rf"|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b",
    re.I,
)

# Directional words. Conflating "above" with "below" would pair a market with
# its own opposite -- the worst possible false positive.
_ABOVE_WORDS = re.compile(
    r"\b(above|over|exceed|exceeds|higher|greater|more than|at least|"
    r"or more|up|rise|reach|reaches|hit|hits|surpass|surpasses)\b", re.I
)
_BELOW_WORDS = re.compile(
    r"\b(below|under|less than|lower|fewer|at most|or less|down|fall|falls|"
    r"drop|drops|decline|declines)\b", re.I
)


def _normalise_numbers(text: str) -> str:
    """Rewrite every number into one canonical spelling.

    "$100,000", "100k" and "100000" must all become the same token, otherwise
    de-punctuation turns "100,000" into the two words "100" and "000" and a real
    cross-venue match scores far too low to survive the threshold.
    """
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)

    def _expand(m: re.Match[str]) -> str:
        raw, suffix = m.group(1), (m.group(2) or "").lower()
        try:
            value = float(raw)
        except ValueError:
            return m.group(0)
        value *= {"k": 1e3, "m": 1e6, "b": 1e9}.get(suffix, 1.0)
        return f"{value:.10g}"

    return _NUM_RE.sub(_expand, t)


def canonical_text(text: str) -> str:
    """Lowercase, normalise numbers and dates, expand aliases, drop filler."""
    t = (text or "").lower().strip()
    t = t.replace("&", " and ")
    t = _normalise_numbers(t)
    # Collapse month spellings so "dec" and "december" agree.
    t = _MONTH_RE.sub(lambda m: m.group(1)[:3].lower(), t)
    t = re.sub(r"[^\w\s.$%-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for alias, full in _TEAM_ALIASES.items():
        t = re.sub(rf"\b{re.escape(alias)}\b", full, t)
    words = [w for w in t.split() if w not in _STOPWORDS]
    return " ".join(words)


def extract_numbers(text: str) -> set[float]:
    """Pull thresholds out of a title, expanding k/m/b suffixes.

    Calendar fragments are stripped first so the "31" in "Dec 31" is never
    treated as a price level -- that stray match is enough to let a $100k market
    pair with a $120k one.
    """
    cleaned = _DATE_FRAGMENT_RE.sub(" ", (text or "").lower())
    cleaned = _normalise_numbers(cleaned)
    out: set[float] = set()
    for raw, _suffix in _NUM_RE.findall(cleaned):
        try:
            value = float(raw)
        except ValueError:
            continue
        # Bare years are handled by extract_years, not as thresholds.
        if 2000 <= value <= 2100 and float(value).is_integer():
            continue
        out.add(round(value, 4))
    return out


def extract_years(text: str) -> set[int]:
    return {int(y) for y in _YEAR_RE.findall(text or "")}


def extract_months(text: str) -> set[int]:
    return {_MONTHS[m.lower()] for m in _MONTH_RE.findall(text or "")}


def extract_direction(text: str) -> set[str]:
    """Which way the question points, if it says."""
    out: set[str] = set()
    if _ABOVE_WORDS.search(text or ""):
        out.add("above")
    if _BELOW_WORDS.search(text or ""):
        out.add("below")
    return out


@dataclass(frozen=True)
class MatchResult:
    score: float
    reason: str

    @property
    def ok(self) -> bool:
        return self.score >= settings.fuzzy_match_threshold


def title_similarity(a: str, b: str) -> float:
    """Blended fuzzy score over normalised titles."""
    ca, cb = canonical_text(a), canonical_text(b)
    if not ca or not cb:
        return 0.0
    return max(
        fuzz.token_set_ratio(ca, cb) * 0.55 + fuzz.token_sort_ratio(ca, cb) * 0.45,
        fuzz.partial_ratio(ca, cb) * 0.80,
    )


def match_titles(a: str, b: str) -> MatchResult:
    """Compare two market titles with hard guards on lines, dates and direction.

    Every guard is deliberately strict. A rejected true match costs one missed
    opportunity; an accepted false match costs the whole stake, because the two
    "legs" do not in fact cover the outcome space (Part I s5.2).
    """
    na, nb = extract_numbers(a), extract_numbers(b)
    # Strict equality, not overlap: "$100k by Dec 31" and "$120k by Dec 31" share
    # a date but are different lines.
    if na and nb and na != nb:
        return MatchResult(0.0, "threshold mismatch")

    ya, yb = extract_years(a), extract_years(b)
    if ya and yb and not (ya & yb):
        return MatchResult(0.0, "year mismatch")

    ma, mb = extract_months(a), extract_months(b)
    if ma and mb and not (ma & mb):
        return MatchResult(0.0, "month mismatch")

    da, db = extract_direction(a), extract_direction(b)
    if da and db and not (da & db):
        return MatchResult(0.0, "direction mismatch")

    score = title_similarity(a, b)
    return MatchResult(score, "fuzzy title match")


def best_match(
    title: str, candidates: Iterable[tuple[str, object]]
) -> Optional[tuple[object, MatchResult]]:
    """Highest-scoring candidate above the configured threshold, else None."""
    best: Optional[tuple[object, MatchResult]] = None
    for cand_title, payload in candidates:
        res = match_titles(title, cand_title)
        if not res.ok:
            continue
        if best is None or res.score > best[1].score:
            best = (payload, res)
    return best


# ------------------------------------------------------------- market naming


_MARKET_CANONICAL = {
    "binary": "binary",
    "h2h": "h2h",
    "moneyline": "h2h",
    "match_odds": "h2h",
    "totals": "totals",
    "spreads": "spreads",
    "asian_handicap": "spreads",
}


def canonical_market(source_key: str) -> str:
    """Map a venue's market key onto the internal vocabulary (Part II s6.2).

    Line values must stay in the key -- 'totals_2.5', never bare 'totals' --
    or over 2.5 at one venue silently compares against over 2.75 at another.
    """
    key = (source_key or "").strip().lower()
    if key in _MARKET_CANONICAL:
        return _MARKET_CANONICAL[key]
    base = key.split("_")[0]
    if base in _MARKET_CANONICAL and "_" in key:
        return key  # already carries a line value
    return key or "binary"


def event_signature(event: Event) -> str:
    """Stable comparison key for an event across scan cycles."""
    return canonical_text(event.title)


# ------------------------------------------------------------- categories


#: A shared vocabulary across venues. Kalshi publishes a category; Polymarket's
#: market payload does not carry one at all, and deriving it from the event
#: ticker yields noise ("cilia", "bab") rather than anything a filter can use.
#: Keyword classification gives both venues the same small, meaningful set.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("crypto", ("bitcoin", "btc", "ethereum", "eth", "solana", "crypto", "coin",
                "token", "blockchain", "defi", "nft", "stablecoin", "binance")),
    ("politics", ("election", "president", "senate", "congress", "governor",
                  "nominee", "primary", "parliament", "prime minister", "vote",
                  "impeach", "cabinet", "democrat", "republican", "poll",
                  "chancellor", "referendum", "mayor")),
    ("economics", ("fed", "inflation", "cpi", "gdp", "rate", "recession",
                   "unemployment", "s&p", "nasdaq", "dow", "treasury", "tariff",
                   "interest", "jobs report", "fomc", "economy")),
    ("sports", ("nfl", "nba", "mlb", "nhl", "super bowl", "world cup", "premier"
                , "league", "champion", "playoff", "olympic", "match", "game",
                "tournament", "cup", "f1", "grand prix", "ufc", "tennis",
                "golf", "soccer", "football", "basketball", "baseball")),
    ("science", ("spacex", "nasa", "rocket", "mars", "moon", "launch",
                 "satellite", "asteroid", "fusion", "quantum", "nobel")),
    ("tech", ("ai", "gpt", "openai", "google", "apple", "tesla",
              "microsoft", "meta", "nvidia", "chip", "model", "llm", "ipo")),
    ("health", ("covid", "flu", "virus", "outbreak", "vaccine", "fda", "cdc",
                "measles", "ebola", "pandemic", "disease")),
    ("climate", ("temperature", "warming", "hurricane", "climate", "weather",
                 "storm", "earthquake", "wildfire", "drought", "snow", "rain",
                 "celsius", "fahrenheit", "degrees", "emissions", "co2")),
    ("entertainment", ("oscar", "grammy", "emmy", "box office", "movie", "film",
                       "album", "song", "spotify", "netflix", "bachelor",
                       "billboard", "award")),
    ("world", ("war", "ceasefire", "invade", "invasion", "treaty", "nato", "un ",
               "sanction", "hostage", "peace", "pope", "coup", "strike")),
]

_KNOWN_CATEGORIES = {c for c, _ in _CATEGORY_KEYWORDS} | {"other"}


def classify_category(title: str, hint: str | None = None) -> str:
    """Map an event onto the shared category vocabulary.

    A venue-supplied `hint` wins when it is already one of the known values;
    otherwise the title decides. Order matters -- "Bitcoin ETF approval" is
    crypto rather than economics, so crypto is tested first.
    """
    if hint:
        h = hint.strip().lower().replace(" and ", "_").replace(" ", "_")
        if h in _KNOWN_CATEGORIES:
            return h
        for known in _KNOWN_CATEGORIES:
            if known in h:
                return known

    text = f" {(title or '').lower()} "
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(k in text for k in keywords):
            return category
    return "other"
