"""Title normalisation and category classification.

A mis-normalised title is a false negative on a real opportunity; a
mis-classified one breaks every category filter downstream. Both are silent.
"""

from __future__ import annotations

import pytest

from arbengine.normalise import (
    canonical_text,
    classify_category,
    extract_direction,
    extract_months,
    extract_numbers,
    extract_years,
)


class TestCategoryWordBoundaries:
    """Keywords are matched as words, not as substrings.

    A bare `k in text` test conflates a keyword with any longer word containing
    it, and the failures are not obvious from the output -- they just look like
    a mis-filed market.
    """

    @pytest.mark.parametrize(
        "title,expected,was",
        [
            ("Whether the Fed cuts rates", "economics", "crypto: 'eth' in 'Whether'"),
            ("Will it rain in Chicago on Dec 31?", "climate", "tech: 'ai' in 'rain'"),
            ("Will Ukraine and Russia sign a treaty?", "world", "tech: 'ai' in 'Ukraine'"),
        ],
    )
    def test_substring_collisions_are_gone(self, title, expected, was):
        assert classify_category(title) == expected, f"used to be {was}"

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Will Bitcoin close above $100,000?", "crypto"),
            ("Who wins the Super Bowl?", "sports"),
            ("Will the Fed cut rates in December?", "economics"),
            ("Next president of the United States", "politics"),
            ("Will SpaceX launch Starship again?", "science"),
            ("Will there be a ceasefire in 2026?", "world"),
            ("Hurricane landfall in Florida", "climate"),
            ("Best Picture at the Oscars", "entertainment"),
            ("Something with no keywords whatsoever", "other"),
        ],
    )
    def test_real_titles_still_classify(self, title, expected):
        assert classify_category(title) == expected

    def test_a_venue_hint_wins_when_it_is_a_known_category(self):
        assert classify_category("Anything at all", hint="Crypto") == "crypto"

    def test_hint_matching_is_deterministic(self):
        """The scan used to iterate a set, so hash order picked the winner."""
        hint = "politics_and_economics"
        assert len({classify_category("x", hint=hint) for _ in range(50)}) == 1


class TestAliasExpansionIsIdempotent:
    """Several aliases are prefixes of their own expansion.

    A plain substitution fires again on text it has already rewritten, doubling
    the tail and wrecking the fuzzy score on exactly the titles the alias list
    exists to help.
    """

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Inter Milan to win Serie A", "inter milan serie"),
            ("Bayern Munich to win", "bayern munich"),
            ("Manchester United vs Man City", "manchester united vs manchester city"),
        ],
    )
    def test_already_expanded_text_is_left_alone(self, title, expected):
        assert canonical_text(title) == expected

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Inter to win", "inter milan"),
            ("Bayern to win", "bayern munich"),
            ("Man Utd vs Spurs", "manchester united vs tottenham hotspur"),
            ("BTC above 100k", "bitcoin above 100000"),
        ],
    )
    def test_short_forms_still_expand(self, title, expected):
        assert canonical_text(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "Inter Milan to win Serie A",
            "Bayern Munich to win",
            "Man Utd vs Spurs",
            "US election 2028",
            "Will the GOP win?",
        ],
    )
    def test_normalising_twice_changes_nothing(self, title):
        once = canonical_text(title)
        assert canonical_text(once) == once


class TestTitleParsersAreCacheSafe:
    """The extractors are memoised, so their results are shared.

    `detect_cross_venue` compares every event on one venue against every event
    on another, which re-parsed each title once per candidate PAIR rather than
    once per event. Caching removes that, but a cached mutable set would be one
    object handed to every caller -- so the return type has to be immutable, or
    a single caller mutating it corrupts every later match.
    """

    @pytest.mark.parametrize(
        "fn",
        [extract_numbers, extract_years, extract_months, extract_direction],
    )
    def test_results_are_immutable(self, fn):
        title = "Will Bitcoin exceed $100k above the line by December 31 2026?"
        result = fn(title)
        assert isinstance(result, frozenset)
        with pytest.raises(AttributeError):
            result.add("mutated")  # type: ignore[attr-defined]

    def test_repeated_calls_return_the_same_object(self):
        title = "Will Bitcoin exceed $100k by December 31 2026?"
        assert extract_numbers(title) is extract_numbers(title)
        assert canonical_text(title) == canonical_text(title)

    def test_caching_did_not_change_the_answers(self):
        """Frozenset compares equal to the set the callers used to get."""
        assert extract_numbers("Bitcoin above $100k") == {100_000.0}
        assert extract_years("Election 2026 result") == {2026}
        assert extract_direction("Will it trade above the line?") == {"above"}
