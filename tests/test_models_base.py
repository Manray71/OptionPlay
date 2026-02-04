# Tests for Base Models
# =====================
"""
Tests for TradeSignal, SignalType, SignalStrength from models/base.py.
"""

import pytest
from datetime import datetime, timedelta

from src.models.base import (
    TradeSignal,
    SignalType,
    SignalStrength,
    ValidationError,
    VALID_RELIABILITY_GRADES,
)


# =============================================================================
# SIGNAL TYPE TESTS
# =============================================================================

class TestSignalType:
    """Tests for SignalType enum."""

    def test_has_expected_values(self):
        """Test all expected signal types exist."""
        assert SignalType.LONG.value == "long"
        assert SignalType.SHORT.value == "short"
        assert SignalType.NEUTRAL.value == "neutral"

    def test_enum_count(self):
        """Test correct number of signal types."""
        assert len(SignalType) == 3


# =============================================================================
# SIGNAL STRENGTH TESTS
# =============================================================================

class TestSignalStrength:
    """Tests for SignalStrength enum."""

    def test_has_expected_values(self):
        """Test all expected strengths exist."""
        assert SignalStrength.STRONG.value == "strong"
        assert SignalStrength.MODERATE.value == "moderate"
        assert SignalStrength.WEAK.value == "weak"
        assert SignalStrength.NONE.value == "none"

    def test_enum_count(self):
        """Test correct number of strengths."""
        assert len(SignalStrength) == 4


# =============================================================================
# VALID RELIABILITY GRADES TESTS
# =============================================================================

class TestValidReliabilityGrades:
    """Tests for VALID_RELIABILITY_GRADES constant."""

    def test_contains_expected_grades(self):
        """Test all expected grades exist."""
        assert "A" in VALID_RELIABILITY_GRADES
        assert "B" in VALID_RELIABILITY_GRADES
        assert "C" in VALID_RELIABILITY_GRADES
        assert "D" in VALID_RELIABILITY_GRADES
        assert "F" in VALID_RELIABILITY_GRADES

    def test_is_frozenset(self):
        """Test it's a frozenset."""
        assert isinstance(VALID_RELIABILITY_GRADES, frozenset)


# =============================================================================
# TRADE SIGNAL CREATION TESTS
# =============================================================================

class TestTradeSignalCreation:
    """Tests for TradeSignal creation."""

    def test_create_minimal_signal(self):
        """Test creating signal with minimal required fields."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.5,
            current_price=150.0,
        )

        assert signal.symbol == "AAPL"
        assert signal.strategy == "pullback"
        assert signal.signal_type == SignalType.LONG
        assert signal.score == 7.5

    def test_create_full_signal(self):
        """Test creating signal with all fields."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            entry_price=148.0,
            stop_loss=145.0,
            target_price=160.0,
            reason="Strong pullback setup",
            reliability_grade="A",
            reliability_win_rate=85.0,
        )

        assert signal.entry_price == 148.0
        assert signal.stop_loss == 145.0
        assert signal.target_price == 160.0
        assert signal.reliability_grade == "A"

    def test_default_values(self):
        """Test default values are set correctly."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
        )

        assert signal.entry_price is None
        assert signal.stop_loss is None
        assert signal.target_price is None
        assert signal.reason == ""
        assert signal.details == {}
        assert signal.warnings == []
        assert signal.reliability_grade is None


# =============================================================================
# TRADE SIGNAL VALIDATION TESTS
# =============================================================================

class TestTradeSignalValidation:
    """Tests for TradeSignal validation."""

    def test_empty_symbol_raises_error(self):
        """Test empty symbol raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
            )
        assert "symbol" in str(exc.value).lower()

    def test_long_symbol_raises_error(self):
        """Test symbol > 10 chars raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="VERYLONGSYMBOL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
            )
        assert "too long" in str(exc.value).lower()

    def test_empty_strategy_raises_error(self):
        """Test empty strategy raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
            )
        assert "strategy" in str(exc.value).lower()

    def test_negative_score_raises_error(self):
        """Test negative score raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=-1.0,
                current_price=150.0,
            )
        assert "score" in str(exc.value).lower()

    def test_score_too_high_raises_error(self):
        """Test score > 20 raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=25.0,
                current_price=150.0,
            )
        assert "score" in str(exc.value).lower()

    def test_negative_current_price_raises_error(self):
        """Test negative current_price raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=-10.0,
            )
        assert "current_price" in str(exc.value).lower()

    def test_negative_entry_price_raises_error(self):
        """Test negative entry_price raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                entry_price=-10.0,
            )
        assert "entry_price" in str(exc.value).lower()

    def test_invalid_reliability_grade_raises_error(self):
        """Test invalid reliability_grade raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_grade="X",  # Invalid
            )
        assert "reliability_grade" in str(exc.value).lower()

    def test_negative_reliability_win_rate_raises_error(self):
        """Test negative reliability_win_rate raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_win_rate=-5.0,
            )
        assert "reliability_win_rate" in str(exc.value).lower()

    def test_reliability_win_rate_over_100_raises_error(self):
        """Test reliability_win_rate > 100 raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_win_rate=105.0,
            )
        assert "reliability_win_rate" in str(exc.value).lower()


# =============================================================================
# PRICE LEVELS VALIDATION TESTS
# =============================================================================

class TestPriceLevelsValidation:
    """Tests for price levels consistency validation."""

    def test_long_signal_valid_price_levels(self):
        """Test LONG signal with valid price levels."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            entry_price=148.0,
            stop_loss=145.0,  # Below entry
            target_price=160.0,  # Above entry
        )

        assert signal.entry_price == 148.0

    def test_long_signal_stop_above_entry_raises_error(self):
        """Test LONG signal with stop >= entry raises error."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.STRONG,
                score=8.0,
                current_price=150.0,
                entry_price=148.0,
                stop_loss=150.0,  # Above entry
                target_price=160.0,
            )
        assert "stop_loss" in str(exc.value).lower()

    def test_long_signal_target_below_entry_raises_error(self):
        """Test LONG signal with target <= entry raises error."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.STRONG,
                score=8.0,
                current_price=150.0,
                entry_price=148.0,
                stop_loss=145.0,
                target_price=140.0,  # Below entry
            )
        assert "target_price" in str(exc.value).lower()

    def test_short_signal_valid_price_levels(self):
        """Test SHORT signal with valid price levels."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="bearish",
            signal_type=SignalType.SHORT,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            entry_price=152.0,
            stop_loss=155.0,  # Above entry
            target_price=140.0,  # Below entry
        )

        assert signal.entry_price == 152.0

    def test_short_signal_stop_below_entry_raises_error(self):
        """Test SHORT signal with stop <= entry raises error."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="bearish",
                signal_type=SignalType.SHORT,
                strength=SignalStrength.STRONG,
                score=8.0,
                current_price=150.0,
                entry_price=152.0,
                stop_loss=150.0,  # Below entry
                target_price=140.0,
            )
        assert "stop_loss" in str(exc.value).lower()

    def test_entry_equals_stop_raises_error(self):
        """Test entry == stop raises error."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.STRONG,
                score=8.0,
                current_price=150.0,
                entry_price=148.0,
                stop_loss=148.0,  # Equal to entry
                target_price=160.0,
            )
        assert "cannot equal stop_loss" in str(exc.value).lower()


# =============================================================================
# RELIABILITY CI VALIDATION TESTS
# =============================================================================

class TestReliabilityCIValidation:
    """Tests for reliability_ci validation."""

    def test_valid_ci(self):
        """Test valid confidence interval."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
            reliability_ci=(75.0, 90.0),
        )

        assert signal.reliability_ci == (75.0, 90.0)

    def test_invalid_ci_format_raises_error(self):
        """Test invalid CI format raises error."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_ci=(75.0,),  # Only one value
            )
        assert "reliability_ci" in str(exc.value).lower()

    def test_ci_low_greater_than_high_raises_error(self):
        """Test CI low > high raises error."""
        with pytest.raises(ValidationError) as exc:
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_ci=(90.0, 75.0),  # Low > high
            )
        assert "reliability_ci" in str(exc.value).lower()


# =============================================================================
# RISK REWARD RATIO TESTS
# =============================================================================

class TestRiskRewardRatio:
    """Tests for risk_reward_ratio property."""

    def test_calculates_ratio(self):
        """Test risk reward ratio calculation."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            entry_price=100.0,
            stop_loss=95.0,  # Risk = 5
            target_price=115.0,  # Reward = 15
        )

        # Ratio = 15 / 5 = 3.0
        assert signal.risk_reward_ratio == 3.0

    def test_returns_none_without_all_prices(self):
        """Test returns None if prices missing."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
            entry_price=148.0,
            # Missing stop_loss and target_price
        )

        assert signal.risk_reward_ratio is None


# =============================================================================
# IS ACTIONABLE TESTS
# =============================================================================

class TestIsActionable:
    """Tests for is_actionable property."""

    def test_actionable_long_high_score(self):
        """Test LONG signal with high score is actionable."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
        )

        assert signal.is_actionable is True

    def test_actionable_short_high_score(self):
        """Test SHORT signal with high score is actionable."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="bearish",
            signal_type=SignalType.SHORT,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
        )

        assert signal.is_actionable is True

    def test_not_actionable_low_score(self):
        """Test low score is not actionable."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.WEAK,
            score=2.0,
            current_price=150.0,
        )

        assert signal.is_actionable is False

    def test_not_actionable_neutral(self):
        """Test NEUTRAL signal is not actionable."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.NEUTRAL,
            strength=SignalStrength.NONE,
            score=5.0,
            current_price=150.0,
        )

        assert signal.is_actionable is False


# =============================================================================
# RELIABILITY BADGE TESTS
# =============================================================================

class TestReliabilityBadge:
    """Tests for reliability_badge property."""

    def test_badge_with_grade_and_win_rate(self):
        """Test badge with grade and win rate."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            reliability_grade="A",
            reliability_win_rate=85.0,
        )

        badge = signal.reliability_badge
        assert "[A]" in badge
        assert "85%" in badge

    def test_badge_empty_without_grade(self):
        """Test badge is empty without grade."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
        )

        assert signal.reliability_badge == ""


# =============================================================================
# TO DICT TESTS
# =============================================================================

class TestToDict:
    """Tests for to_dict method."""

    def test_to_dict_basic(self):
        """Test to_dict returns correct dictionary."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
        )

        result = signal.to_dict()

        assert isinstance(result, dict)
        assert result['symbol'] == "AAPL"
        assert result['strategy'] == "pullback"
        assert result['signal_type'] == "long"
        assert result['strength'] == "moderate"
        assert result['score'] == 7.0

    def test_to_dict_includes_reliability(self):
        """Test to_dict includes reliability when present."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            reliability_grade="A",
            reliability_win_rate=85.0,
            reliability_ci=(80.0, 90.0),
        )

        result = signal.to_dict()

        assert 'reliability' in result
        assert result['reliability']['grade'] == "A"
        assert result['reliability']['win_rate'] == 85.0

    def test_to_dict_includes_risk_reward(self):
        """Test to_dict includes risk_reward ratio."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            score=8.0,
            current_price=150.0,
            entry_price=100.0,
            stop_loss=95.0,
            target_price=115.0,
        )

        result = signal.to_dict()

        assert result['risk_reward'] == 3.0

    def test_to_dict_includes_timestamps(self):
        """Test to_dict includes timestamps."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
        )

        result = signal.to_dict()

        assert 'timestamp' in result
        assert result['expires_at'] is None


# =============================================================================
# ADDITIONAL EDGE CASE TESTS FOR COVERAGE
# =============================================================================

class TestAdditionalValidation:
    """Additional edge case tests for complete coverage."""

    def test_non_string_symbol_raises_error(self):
        """Test non-string symbol raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol=123,  # type: ignore
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
            )

    def test_non_string_strategy_raises_error(self):
        """Test non-string strategy raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy=123,  # type: ignore
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
            )

    def test_non_numeric_score_raises_error(self):
        """Test non-numeric score raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score="high",  # type: ignore
                current_price=150.0,
            )

    def test_non_numeric_current_price_raises_error(self):
        """Test non-numeric current_price raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price="high",  # type: ignore
            )

    def test_non_numeric_stop_loss_raises_error(self):
        """Test non-numeric stop_loss raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                stop_loss="low",  # type: ignore
            )

    def test_negative_stop_loss_raises_error(self):
        """Test negative stop_loss raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                stop_loss=-10.0,
            )

    def test_non_numeric_target_price_raises_error(self):
        """Test non-numeric target_price raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                target_price="high",  # type: ignore
            )

    def test_negative_target_price_raises_error(self):
        """Test negative target_price raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                target_price=-10.0,
            )

    def test_non_numeric_win_rate_raises_error(self):
        """Test non-numeric reliability_win_rate raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_win_rate="high",  # type: ignore
            )

    def test_non_numeric_ci_values_raises_error(self):
        """Test non-numeric CI values raises ValidationError."""
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                strategy="pullback",
                signal_type=SignalType.LONG,
                strength=SignalStrength.MODERATE,
                score=7.0,
                current_price=150.0,
                reliability_ci=("low", "high"),  # type: ignore
            )

    def test_expired_signal_adds_warning(self):
        """Test expires_at <= timestamp adds warning."""
        signal = TradeSignal(
            symbol="AAPL",
            strategy="pullback",
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=7.0,
            current_price=150.0,
            expires_at=datetime.now() - timedelta(hours=1),
        )

        assert any("expires_at" in w for w in signal.warnings)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
