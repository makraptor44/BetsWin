"""Sizing, fee model and normalisation tests."""

from __future__ import annotations

import pytest

from arbengine.config import settings
from arbengine.fees import BpsFeeModel, KalshiFeeModel, configure_from_settings, fee_model_for
from arbengine.models import DepthLevel, Quote, Side
from arbengine.normalise import canonical_text, extract_numbers, match_titles
from arbengine.sizing import book_capacity, resize, size_arb, walk_book

configure_from_settings(settings)


def q(venue: str, name: str, price: float, side: Side = Side.YES, levels=None, size=8000.0) -> Quote:
    fees = fee_model_for(venue)
    depth = tuple(levels) if levels else (DepthLevel(price=price, size=size),)
    total = sum(d.size for d in depth)
    return Quote(
        venue=venue,
        market_id=f"{venue}:{name}",
        ticker=name,
        outcome=name,
        side=side,
        price=price,
        effective_price=fees.effective_price(price, max(total, 1.0)),
        size_available=total,
        depth=depth,
    )


class TestKalshiFees:
    def test_published_formula(self):
        """fee = ceil(0.07 * C * P * (1-P)), rounded up to the cent."""
        k = KalshiFeeModel()
        assert k.order_fee(0.50, 100) == pytest.approx(1.75)
        assert k.order_fee(0.05, 100) == pytest.approx(0.34)
        assert k.order_fee(0.99, 100) == pytest.approx(0.07)

    def test_fee_peaks_at_the_middle(self):
        k = KalshiFeeModel()
        mid = k.order_fee(0.50, 1000)
        assert mid > k.order_fee(0.20, 1000)
        assert mid > k.order_fee(0.80, 1000)

    def test_fee_rounds_up_never_down(self):
        k = KalshiFeeModel()
        assert k.order_fee(0.50, 1) == pytest.approx(0.02)  # raw 0.0175

    def test_effective_price_exceeds_quoted(self):
        k = KalshiFeeModel()
        assert k.effective_price(0.50, 100) > 0.50

    def test_zero_contracts_costs_nothing(self):
        assert KalshiFeeModel().order_fee(0.50, 0) == 0.0


class TestBpsFees:
    def test_zero_bps_is_free(self):
        assert BpsFeeModel(0.0).effective_price(0.42, 100) == pytest.approx(0.42)

    def test_bps_applied_to_notional(self):
        assert BpsFeeModel(100.0).fee_per_contract(0.50) == pytest.approx(0.005)


class TestWalkBook:
    def test_single_level_fills_at_top(self):
        f = walk_book((DepthLevel(price=0.40, size=1000),), 0.40, 100)
        assert f.avg_price == pytest.approx(0.40)
        assert f.contracts == pytest.approx(250.0)
        assert not f.exhausted

    def test_deeper_orders_pay_a_worse_average(self):
        levels = (DepthLevel(price=0.40, size=100), DepthLevel(price=0.45, size=1000))
        shallow = walk_book(levels, 0.40, 40)
        deep = walk_book(levels, 0.40, 400)
        assert shallow.avg_price == pytest.approx(0.40)
        assert deep.avg_price > shallow.avg_price
        assert deep.levels_cleared == 2

    def test_exhausted_book_is_reported(self):
        f = walk_book((DepthLevel(price=0.40, size=10),), 0.40, 1000)
        assert f.exhausted
        assert f.notional == pytest.approx(4.0)

    def test_missing_depth_assumes_top_of_book(self):
        f = walk_book((), 0.40, 100)
        assert f.avg_price == pytest.approx(0.40)
        assert f.exhausted  # flagged, because the assumption is optimistic

    def test_capacity_counts_only_reachable_depth(self):
        """Depth priced beyond the edge is not capacity.

        0.45 is 12% above the 0.40 top of book. No 1-3% arb survives paying
        that, so it must not be advertised as available size.
        """
        levels = (DepthLevel(price=0.40, size=100), DepthLevel(price=0.45, size=100))
        assert book_capacity(levels, 0.40, 0) == pytest.approx(40.0)

    def test_capacity_includes_depth_within_slack(self):
        levels = (DepthLevel(price=0.40, size=100), DepthLevel(price=0.404, size=100))
        assert book_capacity(levels, 0.40, 0) == pytest.approx(80.4)

    def test_capacity_falls_back_to_reported_size(self):
        assert book_capacity((), 0.40, 250) == pytest.approx(100.0)


class TestSizeArb:
    def test_equal_contracts_means_equal_profit(self):
        s = size_arb([q("polymarket", "Yes", 0.47), q("polymarket", "No", 0.51)], target_stake=400)
        assert s is not None
        counts = [l.contracts for l in s.legs]
        assert counts[0] == pytest.approx(counts[1], rel=1e-3)
        profits = [v - s.total_stake for v in s.payout_if.values()]
        assert profits[0] == pytest.approx(profits[1], abs=0.05)

    def test_profit_is_positive_and_matches_margin(self):
        s = size_arb([q("polymarket", "Yes", 0.47), q("polymarket", "No", 0.51)], target_stake=400)
        assert s.worst_case_profit > 0
        assert s.worst_case_profit == pytest.approx(s.total_stake * s.net_margin, abs=0.05)

    def test_kalshi_fees_reduce_net_margin_below_gross(self):
        s = size_arb([q("polymarket", "Yes", 0.47), q("kalshi", "No", 0.51, Side.NO)], target_stake=400)
        assert s is not None
        assert s.net_margin < s.margin

    def test_edge_destroyed_by_fees_returns_none(self):
        # 0.49 + 0.50 is a 1% gross edge; two Kalshi legs at mid-price cost more.
        assert size_arb([q("kalshi", "Yes", 0.49), q("kalshi", "No", 0.50, Side.NO)], target_stake=400) is None

    def test_bankroll_cap_is_respected(self):
        cap = settings.bankroll * settings.max_stake_fraction_per_event
        s = size_arb([q("polymarket", "Yes", 0.47), q("polymarket", "No", 0.51)], target_stake=1e9)
        assert s.total_stake <= cap + 0.01

    def test_thin_book_limits_the_size(self):
        thin = [
            q("polymarket", "Yes", 0.47, levels=[DepthLevel(price=0.47, size=200)]),
            q("polymarket", "No", 0.51, Side.NO, levels=[DepthLevel(price=0.51, size=200)]),
        ]
        s = size_arb(thin, target_stake=5000)
        assert s is not None
        assert s.depth_limited
        assert s.total_stake < 300

    def test_no_arb_returns_none(self):
        assert size_arb([q("polymarket", "Yes", 0.52), q("polymarket", "No", 0.51)], target_stake=400) is None

    def test_single_leg_is_not_an_arb(self):
        assert size_arb([q("polymarket", "Yes", 0.40)], target_stake=400) is None

    def test_dutch_no_payout_multiple(self):
        """Five NO legs at 0.78 pay out four of five, so the book is 3.90/4."""
        legs = [q("polymarket", f"Not{i}", 0.78, Side.NO) for i in range(5)]
        s = size_arb(legs, target_stake=500, payout_multiple=4.0)
        assert s is not None
        assert s.book == pytest.approx(3.90 / 4.0, abs=1e-3)
        assert s.worst_case_profit > 0

    def test_slippage_is_reported(self):
        """A thin top level means the average fill is worse than the quote."""
        deep = [
            q(
                "polymarket",
                "Yes",
                0.47,
                levels=[DepthLevel(price=0.47, size=50), DepthLevel(price=0.474, size=5000)],
            ),
            q(
                "polymarket",
                "No",
                0.51,
                Side.NO,
                levels=[DepthLevel(price=0.51, size=50), DepthLevel(price=0.514, size=5000)],
            ),
        ]
        s = size_arb(deep, target_stake=400)
        assert s is not None
        assert s.slippage_bps > 0
        assert s.legs[0].price > 0.47  # filled above the quoted top of book


class TestResize:
    def test_scaling_down_preserves_the_ratio(self):
        s = size_arb([q("polymarket", "Yes", 0.47), q("polymarket", "No", 0.51)], target_stake=400)
        half = resize(s, 200)
        assert half.total_stake == pytest.approx(200, abs=0.02)
        ratio_before = s.legs[0].stake / s.legs[1].stake
        ratio_after = half.legs[0].stake / half.legs[1].stake
        assert ratio_before == pytest.approx(ratio_after, rel=1e-3)

    def test_scaling_past_depth_is_flagged(self):
        s = size_arb([q("polymarket", "Yes", 0.47), q("polymarket", "No", 0.51)], target_stake=400)
        big = resize(s, s.max_stake_available * 10)
        assert big.depth_limited


class TestNormalise:
    def test_number_forms_unify(self):
        assert extract_numbers("$100k") == extract_numbers("100,000") == {100000.0}

    def test_canonical_text_keeps_numbers_whole(self):
        assert "100000" in canonical_text("Will Bitcoin reach $100,000?")

    def test_years_are_not_treated_as_thresholds(self):
        assert 2026.0 not in extract_numbers("Something in 2026")

    def test_day_of_month_is_not_a_threshold(self):
        """The bug that let $100k pair with $120k: 'Dec 31' contributed a 31."""
        assert extract_numbers("Will BTC hit $100k by Dec 31, 2026?") == {100000.0}

    @pytest.mark.parametrize(
        "a,b,expected",
        [
            ("Will the Fed cut rates in March 2026?", "Fed rate cut in March 2026?", True),
            ("Man City vs Arsenal", "Manchester City v Arsenal", True),
            ("Will BTC hit $100k by Dec 31 2026?", "Bitcoin above $100,000 on December 31, 2026", True),
            ("Will the Fed cut rates in March 2026?", "Will the Fed cut rates in June 2026?", False),
            ("Will BTC hit $100k in 2026?", "Will BTC hit $120k in 2026?", False),
            ("Will CPI be above 3% in 2026?", "Will CPI be below 3% in 2026?", False),
            ("Will Jesus Christ return before 2027?", "Will the US invade Iran before 2027?", False),
        ],
    )
    def test_matching(self, a: str, b: str, expected: bool):
        assert match_titles(a, b).ok is expected


class TestCategoryClassification:
    """A usable filter vocabulary, shared across venues."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Will the Fed cut rates in December?", "economics"),
            ("Texas Senate Election Winner", "politics"),
            ("Will Bitcoin close above $150,000?", "crypto"),
            ("Super Bowl LXI winner", "sports"),
            ("Will SpaceX land Starship on the Moon?", "science"),
            ("Oscar Winner: Best Makeup", "entertainment"),
            ("Will GPT-6 be released in 2026?", "tech"),
            ("Will the world pass 2 degrees Celsius?", "climate"),
            ("An entirely unclassifiable question", "other"),
        ],
    )
    def test_titles_map_to_the_shared_vocabulary(self, title: str, expected: str):
        from arbengine.normalise import classify_category

        assert classify_category(title) == expected

    def test_bitcoin_price_question_is_crypto_not_economics(self):
        """Order matters: crypto is tested before economics."""
        from arbengine.normalise import classify_category

        assert classify_category("Bitcoin ETF approval and interest rates") == "crypto"

    def test_venue_hint_wins_when_recognised(self):
        from arbengine.normalise import classify_category

        assert classify_category("Anything at all", "Politics") == "politics"
        assert classify_category("Anything at all", "Climate and Weather") == "climate"

    def test_unrecognised_hint_falls_back_to_the_title(self):
        from arbengine.normalise import classify_category

        assert classify_category("Super Bowl LXI winner", "Wibble") == "sports"
