# Tests for Options Models
# ========================
"""
Tests for MaxPainResult, StrikeRecommendation, StrikeQuality from models/options.py.
"""

import pytest
import math

from src.models.options import (
    MaxPainResult,
    StrikePainData,
    StrikeRecommendation,
    StrikeQuality,
)


# =============================================================================
# STRIKE QUALITY TESTS
# =============================================================================

class TestStrikeQuality:
    """Tests for StrikeQuality enum."""

    def test_has_expected_values(self):
        """Test all expected quality values exist."""
        assert StrikeQuality.EXCELLENT.value == "excellent"
        assert StrikeQuality.GOOD.value == "good"
        assert StrikeQuality.ACCEPTABLE.value == "acceptable"
        assert StrikeQuality.POOR.value == "poor"

    def test_enum_count(self):
        """Test correct number of quality levels."""
        assert len(StrikeQuality) == 4


# =============================================================================
# STRIKE PAIN DATA TESTS
# =============================================================================

class TestStrikePainData:
    """Tests for StrikePainData dataclass."""

    def test_create_pain_data(self):
        """Test creating StrikePainData."""
        data = StrikePainData(
            strike=150.0,
            call_oi=1000,
            put_oi=1500,
            total_pain=2500000.0,
        )

        assert data.strike == 150.0
        assert data.call_oi == 1000
        assert data.put_oi == 1500
        assert data.total_pain == 2500000.0


# =============================================================================
# MAX PAIN RESULT CREATION TESTS
# =============================================================================

class TestMaxPainResultCreation:
    """Tests for MaxPainResult creation."""

    def test_create_max_pain_result(self):
        """Test creating MaxPainResult with all fields."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=165.0,
            put_wall_oi=50000,
            call_wall=180.0,
            call_wall_oi=45000,
            total_put_oi=200000,
            total_call_oi=180000,
            pcr=1.11,
        )

        assert result.symbol == "AAPL"
        assert result.expiry == "2024-03-15"
        assert result.current_price == 175.0
        assert result.max_pain == 170.0

    def test_create_without_walls(self):
        """Test creating MaxPainResult without walls."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=0,
            total_call_oi=0,
            pcr=0.0,
        )

        assert result.put_wall is None
        assert result.call_wall is None


# =============================================================================
# PRICE VS MAX PAIN TESTS
# =============================================================================

class TestPriceVsMaxPain:
    """Tests for price_vs_max_pain method."""

    def test_price_above_max_pain(self):
        """Test when price is above max pain."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=180.0,  # Above
            max_pain=170.0,
            distance_pct=5.88,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,
        )

        assert result.price_vs_max_pain() == "above"

    def test_price_below_max_pain(self):
        """Test when price is below max pain."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=165.0,  # Below
            max_pain=170.0,
            distance_pct=2.94,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,
        )

        assert result.price_vs_max_pain() == "below"

    def test_price_at_max_pain(self):
        """Test when price equals max pain."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=170.0,  # Equal
            max_pain=170.0,
            distance_pct=0.0,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,
        )

        assert result.price_vs_max_pain() == "at"


# =============================================================================
# SENTIMENT TESTS
# =============================================================================

class TestSentiment:
    """Tests for sentiment method."""

    def test_bearish_sentiment(self):
        """Test bearish sentiment when PCR > 1.2."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=150000,
            total_call_oi=100000,
            pcr=1.5,  # > 1.2 = bearish
        )

        assert result.sentiment() == "bearish"

    def test_bullish_sentiment(self):
        """Test bullish sentiment when PCR < 0.8."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=60000,
            total_call_oi=100000,
            pcr=0.6,  # < 0.8 = bullish
        )

        assert result.sentiment() == "bullish"

    def test_neutral_sentiment(self):
        """Test neutral sentiment when PCR between 0.8 and 1.2."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,  # Between 0.8-1.2 = neutral
        )

        assert result.sentiment() == "neutral"

    def test_extreme_bearish_sentiment(self):
        """Test extreme bearish sentiment when PCR is infinite."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=0,  # No calls
            pcr=math.inf,
        )

        assert result.sentiment() == "extreme_bearish"


# =============================================================================
# GRAVITY DIRECTION TESTS
# =============================================================================

class TestGravityDirection:
    """Tests for gravity_direction method."""

    def test_gravity_down_when_price_far_above(self):
        """Test gravity is down when price far above max pain."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=180.0,  # Far above
            max_pain=170.0,
            distance_pct=5.88,  # > 3%
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,
        )

        assert result.gravity_direction() == "down"

    def test_gravity_up_when_price_far_below(self):
        """Test gravity is up when price far below max pain."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=160.0,  # Far below
            max_pain=170.0,
            distance_pct=5.88,  # > 3%
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,
        )

        assert result.gravity_direction() == "up"

    def test_gravity_neutral_when_close(self):
        """Test gravity is neutral when price close to max pain."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=172.0,  # Close
            max_pain=170.0,
            distance_pct=1.18,  # < 3%
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=100000,
            pcr=1.0,
        )

        assert result.gravity_direction() == "neutral"


# =============================================================================
# MAX PAIN TO DICT TESTS
# =============================================================================

class TestMaxPainToDict:
    """Tests for MaxPainResult to_dict method."""

    def test_to_dict_basic(self):
        """Test to_dict returns correct dictionary."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=165.0,
            put_wall_oi=50000,
            call_wall=180.0,
            call_wall_oi=45000,
            total_put_oi=200000,
            total_call_oi=180000,
            pcr=1.11,
        )

        d = result.to_dict()

        assert isinstance(d, dict)
        assert d['symbol'] == "AAPL"
        assert d['expiry'] == "2024-03-15"
        assert d['current_price'] == 175.0
        assert d['max_pain'] == 170.0

    def test_to_dict_includes_derived(self):
        """Test to_dict includes derived values."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=180.0,
            max_pain=170.0,
            distance_pct=5.88,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=150000,
            total_call_oi=100000,
            pcr=1.5,
        )

        d = result.to_dict()

        assert d['price_vs_max_pain'] == "above"
        assert d['gravity_direction'] == "down"
        assert d['sentiment'] == "bearish"

    def test_to_dict_handles_infinite_pcr(self):
        """Test to_dict handles infinite PCR."""
        result = MaxPainResult(
            symbol="AAPL",
            expiry="2024-03-15",
            current_price=175.0,
            max_pain=170.0,
            distance_pct=2.86,
            put_wall=None,
            put_wall_oi=0,
            call_wall=None,
            call_wall_oi=0,
            total_put_oi=100000,
            total_call_oi=0,
            pcr=math.inf,
        )

        d = result.to_dict()

        assert d['pcr'] == "inf"


# =============================================================================
# STRIKE RECOMMENDATION CREATION TESTS
# =============================================================================

class TestStrikeRecommendationCreation:
    """Tests for StrikeRecommendation creation."""

    def test_create_minimal(self):
        """Test creating StrikeRecommendation with minimal fields."""
        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Below support level",
        )

        assert rec.symbol == "AAPL"
        assert rec.short_strike == 145.0
        assert rec.long_strike == 140.0
        assert rec.spread_width == 5.0

    def test_create_full(self):
        """Test creating StrikeRecommendation with all fields."""
        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Below support level",
            estimated_delta=-0.20,
            estimated_credit=1.50,
            max_loss=350.0,
            max_profit=150.0,
            break_even=143.50,
            prob_profit=80.0,
            risk_reward_ratio=0.43,
            quality=StrikeQuality.EXCELLENT,
            confidence_score=85.0,
            warnings=["Near earnings"],
        )

        assert rec.estimated_delta == -0.20
        assert rec.estimated_credit == 1.50
        assert rec.quality == StrikeQuality.EXCELLENT

    def test_default_values(self):
        """Test default values."""
        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Test",
        )

        assert rec.estimated_delta is None
        assert rec.estimated_credit is None
        assert rec.quality == StrikeQuality.GOOD
        assert rec.confidence_score == 0.0
        assert rec.warnings == []


# =============================================================================
# STRIKE RECOMMENDATION TO DICT TESTS
# =============================================================================

class TestStrikeRecommendationToDict:
    """Tests for StrikeRecommendation to_dict method."""

    def test_to_dict_basic(self):
        """Test to_dict returns correct dictionary."""
        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Below support",
        )

        d = rec.to_dict()

        assert isinstance(d, dict)
        assert d['symbol'] == "AAPL"
        assert d['current_price'] == 150.0
        assert d['short_strike'] == 145.0
        assert d['long_strike'] == 140.0
        assert d['spread_width'] == 5.0

    def test_to_dict_includes_quality(self):
        """Test to_dict includes quality as string."""
        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Test",
            quality=StrikeQuality.EXCELLENT,
        )

        d = rec.to_dict()

        assert d['quality'] == "excellent"

    def test_to_dict_includes_support_level(self):
        """Test to_dict includes support level if present."""
        # Create a mock support level
        class MockSupportLevel:
            price = 142.0
            strength = 0.85
            touches = 3
            confirmed_by_fib = True

        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Test",
            support_level_used=MockSupportLevel(),
        )

        d = rec.to_dict()

        assert d['support_level'] is not None
        assert d['support_level']['price'] == 142.0
        assert d['support_level']['touches'] == 3

    def test_to_dict_no_support_level(self):
        """Test to_dict handles no support level."""
        rec = StrikeRecommendation(
            symbol="AAPL",
            current_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            short_strike_reason="Test",
        )

        d = rec.to_dict()

        assert d['support_level'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
