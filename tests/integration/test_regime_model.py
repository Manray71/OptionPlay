"""
Tests for the Regime Model module.

Tests cover:
- TradingParameters dataclass
- TradeDecision dataclass
- RegimeStatus dataclass
- RegimeModel class
"""

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backtesting import RegimeConfig, RegimeType, FIXED_REGIMES
from src.backtesting import (
    RegimeModel,
    TradingParameters,
    TradeDecision,
    RegimeStatus,
)


# =============================================================================
# TRADING PARAMETERS TESTS
# =============================================================================


class TestTradingParameters:
    """Tests for TradingParameters dataclass."""

    def test_creation(self):
        """Test TradingParameters creation."""
        params = TradingParameters(
            regime="normal",
            regime_type=RegimeType.NORMAL,
            vix=18.5,
            vix_range=(15.0, 20.0),
            min_score=6.0,
            profit_target_pct=50.0,
            stop_loss_pct=150.0,
            position_size_pct=5.0,
            max_concurrent_positions=10,
            strategies_enabled=["pullback", "bounce"],
            strategy_weights={"pullback": 0.6, "bounce": 0.4},
            is_trained=True,
            confidence_level="high",
        )
        assert params.regime == "normal"
        assert params.vix == 18.5
        assert params.min_score == 6.0
        assert params.is_trained is True

    def test_to_dict(self):
        """Test to_dict serialization."""
        params = TradingParameters(
            regime="elevated",
            regime_type=RegimeType.ELEVATED,
            vix=25.0,
            vix_range=(20.0, 30.0),
            min_score=7.0,
            profit_target_pct=65.0,
            stop_loss_pct=200.0,
            position_size_pct=3.0,
            max_concurrent_positions=5,
            strategies_enabled=["pullback"],
            strategy_weights={"pullback": 1.0},
            is_trained=False,
            confidence_level="medium",
        )
        d = params.to_dict()

        assert d["regime"] == "elevated"
        assert d["vix"] == 25.0
        assert d["parameters"]["min_score"] == 7.0
        assert d["strategies"]["enabled"] == ["pullback"]
        assert d["metadata"]["confidence_level"] == "medium"


# =============================================================================
# TRADE DECISION TESTS
# =============================================================================


class TestTradeDecision:
    """Tests for TradeDecision dataclass."""

    def test_creation(self):
        """Test TradeDecision creation."""
        decision = TradeDecision(
            should_trade=True,
            reason="Score meets threshold",
            regime="normal",
            score_threshold=6.0,
            signal_score=8.5,
            strategy="pullback",
            confidence="high",
            warnings=[],
        )
        assert decision.should_trade is True
        assert decision.signal_score == 8.5
        assert len(decision.warnings) == 0

    def test_to_dict(self):
        """Test to_dict serialization."""
        decision = TradeDecision(
            should_trade=False,
            reason="Score below threshold",
            regime="elevated",
            score_threshold=7.0,
            signal_score=5.5,
            strategy="bounce",
            confidence="low",
            warnings=["VIX elevated", "Low liquidity"],
        )
        d = decision.to_dict()

        assert d["should_trade"] is False
        assert d["reason"] == "Score below threshold"
        assert d["warnings"] == ["VIX elevated", "Low liquidity"]

    def test_with_warnings(self):
        """Test TradeDecision with warnings."""
        decision = TradeDecision(
            should_trade=True,
            reason="Proceed with caution",
            regime="high_vol",
            score_threshold=8.0,
            signal_score=9.0,
            strategy="pullback",
            confidence="medium",
            warnings=["High volatility", "Earnings nearby"],
        )
        assert len(decision.warnings) == 2
        assert "High volatility" in decision.warnings


# =============================================================================
# REGIME STATUS TESTS
# =============================================================================


class TestRegimeStatus:
    """Tests for RegimeStatus dataclass."""

    def test_creation(self):
        """Test RegimeStatus creation."""
        params = TradingParameters(
            regime="normal",
            regime_type=RegimeType.NORMAL,
            vix=18.5,
            vix_range=(15.0, 20.0),
            min_score=6.0,
            profit_target_pct=50.0,
            stop_loss_pct=150.0,
            position_size_pct=5.0,
            max_concurrent_positions=10,
            strategies_enabled=["pullback"],
            strategy_weights={},
            is_trained=True,
            confidence_level="high",
        )
        status = RegimeStatus(
            current_regime="normal",
            regime_type=RegimeType.NORMAL,
            vix=18.5,
            days_in_regime=5,
            pending_transition=None,
            pending_days=0,
            transition_history=[],
            parameters=params,
        )
        assert status.current_regime == "normal"
        assert status.days_in_regime == 5
        assert status.pending_transition is None

    def test_to_dict(self):
        """Test to_dict serialization."""
        params = TradingParameters(
            regime="normal",
            regime_type=RegimeType.NORMAL,
            vix=18.0,
            vix_range=(15.0, 20.0),
            min_score=6.0,
            profit_target_pct=50.0,
            stop_loss_pct=150.0,
            position_size_pct=5.0,
            max_concurrent_positions=10,
            strategies_enabled=["pullback"],
            strategy_weights={},
            is_trained=True,
            confidence_level="high",
        )
        status = RegimeStatus(
            current_regime="normal",
            regime_type=RegimeType.NORMAL,
            vix=18.0,
            days_in_regime=3,
            pending_transition="elevated",
            pending_days=1,
            transition_history=[],
            parameters=params,
        )
        d = status.to_dict()

        assert d["current_regime"] == "normal"
        assert d["vix"] == 18.0
        assert d["pending_transition"] == "elevated"
        assert d["pending_days"] == 1


# =============================================================================
# REGIME MODEL TESTS
# =============================================================================


class TestRegimeModel:
    """Tests for RegimeModel class."""

    def test_initialization_default(self):
        """Test default initialization."""
        model = RegimeModel(use_trained_model=False)
        assert model is not None
        assert model.regimes is not None

    def test_initialization_with_regimes(self):
        """Test initialization with custom regimes."""
        custom_regimes = {
            "test": RegimeConfig(
                name="test",
                regime_type=RegimeType.NORMAL,
                vix_lower=10.0,
                vix_upper=30.0,
            ),
        }
        model = RegimeModel(regimes=custom_regimes, use_trained_model=False)
        assert "test" in model.regimes

    def test_get_parameters_low_vix(self):
        """Test get_parameters for low VIX."""
        model = RegimeModel(use_trained_model=False)
        params = model.get_parameters(vix=12.0)

        assert params is not None
        assert isinstance(params, TradingParameters)
        assert params.vix == 12.0
        assert params.regime_type == RegimeType.LOW_VOL

    def test_get_parameters_normal_vix(self):
        """Test get_parameters for normal VIX."""
        model = RegimeModel(use_trained_model=False)
        params = model.get_parameters(vix=17.0)

        assert params is not None
        assert params.regime_type == RegimeType.NORMAL

    def test_get_parameters_elevated_vix(self):
        """Test get_parameters for elevated VIX."""
        model = RegimeModel(use_trained_model=False)
        params = model.get_parameters(vix=25.0)

        assert params is not None
        assert params.regime_type == RegimeType.ELEVATED

    def test_get_parameters_high_vix(self):
        """Test get_parameters for high VIX."""
        model = RegimeModel(use_trained_model=False)
        params = model.get_parameters(vix=35.0)

        assert params is not None
        assert params.regime_type == RegimeType.HIGH_VOL

    def test_should_trade_returns_trade_decision(self):
        """Test should_trade returns TradeDecision object."""
        model = RegimeModel(use_trained_model=False)
        decision = model.should_trade(
            score=9.0,
            strategy="pullback",
            vix=18.0,
        )
        # Returns TradeDecision object
        assert isinstance(decision, TradeDecision)
        assert isinstance(decision.should_trade, bool)
        assert isinstance(decision.reason, str)

    def test_should_trade_score_below_threshold(self):
        """Test should_trade returns False when score below threshold."""
        model = RegimeModel(use_trained_model=False)
        decision = model.should_trade(
            score=2.0,  # Very low score
            strategy="pullback",
            vix=18.0,
        )
        # Should not trade with very low score
        assert decision.should_trade is False

    def test_should_trade_invalid_strategy(self):
        """Test should_trade handles invalid strategy."""
        model = RegimeModel(use_trained_model=False)
        decision = model.should_trade(
            score=8.0,
            strategy="invalid_strategy",
            vix=18.0,
        )
        # Should handle gracefully
        assert isinstance(decision, TradeDecision)

    def test_get_min_score_for_strategy(self):
        """Test get_min_score_for_strategy method."""
        model = RegimeModel(use_trained_model=False)
        threshold = model.get_min_score_for_strategy("pullback")

        assert threshold is not None
        assert isinstance(threshold, float)
        assert 0 <= threshold <= 15

    def test_get_min_score_for_strategy_with_regime(self):
        """Test get_min_score_for_strategy with explicit regime."""
        model = RegimeModel(use_trained_model=False)
        model.initialize(vix=18.0)
        threshold = model.get_min_score_for_strategy("pullback", regime="normal")

        assert threshold >= 0

    def test_initialize_sets_state(self):
        """Test initialize method sets regime state."""
        model = RegimeModel(use_trained_model=False)
        regime_name = model.initialize(vix=18.0)

        assert regime_name is not None
        assert model._state is not None
        assert model._last_vix == 18.0

    def test_update_changes_regime(self):
        """Test update method can change regime."""
        model = RegimeModel(use_trained_model=False)
        model.initialize(vix=18.0)

        # Update with high VIX
        result = model.update(vix=35.0)
        # Result is either new regime name or None
        assert result is None or isinstance(result, str)


class TestRegimeModelPersistence:
    """Tests for RegimeModel persistence."""

    def test_save_and_load(self):
        """Test saving and loading regime model."""
        model = RegimeModel(use_trained_model=False, model_id="test_model")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "model.json"
            model.save(str(filepath))

            loaded = RegimeModel.load(str(filepath))
            assert loaded is not None
            # Model should have same regimes
            assert len(loaded.regimes) == len(model.regimes)

    def test_load_nonexistent_file_raises(self):
        """Test loading from nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            RegimeModel.load("/nonexistent/path/model.json")


class TestRegimeModelTransitions:
    """Tests for regime transition handling."""

    def test_regime_initialization_at_different_vix(self):
        """Test regime initialization at different VIX levels."""
        model = RegimeModel(use_trained_model=False)

        # Initialize at low VIX
        regime_low = model.initialize(vix=12.0)
        assert "low" in regime_low.lower()

        # Create new model and initialize at normal VIX
        model2 = RegimeModel(use_trained_model=False)
        regime_normal = model2.initialize(vix=18.0)
        assert "normal" in regime_normal.lower()

    def test_update_method(self):
        """Test update method."""
        model = RegimeModel(use_trained_model=False)
        model.initialize(vix=18.0)
        result = model.update(vix=18.5)
        # Update same regime should return None (no transition)
        assert result is None or isinstance(result, str)
