"""
Tests for the EnsembleSelector module.

Tests cover:
- StrategyScore dataclass
- EnsembleRecommendation dataclass
- SymbolPerformance dataclass
- RotationState dataclass
- MetaLearner class
- StrategyRotationEngine class
- EnsembleSelector class (main class)
- Helper functions
"""

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.backtesting.ensemble_selector import (
    CLUSTER_STRATEGY_MAP,
    DEFAULT_COMPONENT_WEIGHTS,
    DEFAULT_REGIME_PREFERENCES,
    FEATURE_IMPACT,
    MIN_SCORE_THRESHOLDS,
    SECTOR_STRATEGY_MAP,
    STRATEGIES,
    EnsembleRecommendation,
    EnsembleSelector,
    MetaLearner,
    RotationState,
    RotationTrigger,
    SelectionMethod,
    StrategyRotationEngine,
    StrategyScore,
    SymbolPerformance,
    create_strategy_score,
    format_ensemble_summary,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_strategy_score():
    """Create a sample StrategyScore for testing."""
    return StrategyScore(
        strategy="pullback",
        raw_score=8.5,
        weighted_score=9.0,
        confidence=0.85,
        breakdown={"rsi": 1.5, "support": 2.0, "macd": 1.0, "volume": 1.5, "trend": 2.5},
    )


@pytest.fixture
def sample_strategy_scores():
    """Create a dict of sample strategy scores for testing."""
    return {
        "pullback": StrategyScore(
            strategy="pullback",
            raw_score=8.5,
            weighted_score=9.0,
            confidence=0.85,
            breakdown={"rsi": 1.5, "support": 2.0, "macd": 1.0, "volume": 1.5, "trend": 2.5},
        ),
        "bounce": StrategyScore(
            strategy="bounce",
            raw_score=7.0,
            weighted_score=7.5,
            confidence=0.75,
            breakdown={"rsi": 1.0, "support": 2.5, "volume": 1.0, "bounce": 2.0},
        ),
        "ath_breakout": StrategyScore(
            strategy="ath_breakout",
            raw_score=6.0,
            weighted_score=6.5,
            confidence=0.65,
            breakdown={"ath": 2.0, "volume": 1.5, "trend": 2.5},
        ),
        "earnings_dip": StrategyScore(
            strategy="earnings_dip",
            raw_score=5.5,
            weighted_score=6.0,
            confidence=0.60,
            breakdown={"rsi": 1.0, "support": 1.5, "volume": 1.5, "fibonacci": 1.5},
        ),
    }


@pytest.fixture
def sample_ensemble_recommendation(sample_strategy_scores):
    """Create a sample EnsembleRecommendation for testing."""
    return EnsembleRecommendation(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 15, 10, 30, 0),
        recommended_strategy="pullback",
        recommended_score=9.0,
        selection_method=SelectionMethod.META_LEARNER,
        strategy_scores=sample_strategy_scores,
        ensemble_score=7.5,
        ensemble_confidence=0.75,
        regime="normal",
        vix=18.5,
        selection_reason="highest raw score; preferred in normal regime",
        alternative_strategies=["bounce", "ath_breakout"],
        diversification_benefit=0.65,
        strategy_correlation=0.45,
    )


@pytest.fixture
def sample_symbol_performance():
    """Create a sample SymbolPerformance for testing."""
    return SymbolPerformance(
        symbol="AAPL",
        strategy_win_rates={"pullback": 0.65, "bounce": 0.55, "ath_breakout": 0.50},
        strategy_sample_sizes={"pullback": 20, "bounce": 15, "ath_breakout": 10},
        strategy_avg_returns={"pullback": 1.5, "bounce": 1.2, "ath_breakout": 0.8},
        best_strategy="pullback",
        best_strategy_confidence=0.67,
        last_updated=datetime(2026, 1, 15, 10, 0, 0),
    )


@pytest.fixture
def meta_learner():
    """Create a MetaLearner for testing."""
    return MetaLearner(
        history_window_days=90,
        min_samples_per_strategy=10,
        decay_factor=0.95,
    )


@pytest.fixture
def rotation_engine():
    """Create a StrategyRotationEngine for testing."""
    return StrategyRotationEngine(
        rotation_window_days=30,
        performance_threshold=0.40,
        min_trades_for_rotation=10,
    )


@pytest.fixture
def ensemble_selector():
    """Create an EnsembleSelector for testing."""
    return EnsembleSelector(
        method=SelectionMethod.META_LEARNER,
        enable_rotation=True,
        min_score_threshold=4.0,
    )


# =============================================================================
# CONSTANTS TESTS
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_strategies_defined(self):
        """Test that all strategies are defined."""
        assert len(STRATEGIES) == 4
        assert "pullback" in STRATEGIES
        assert "bounce" in STRATEGIES
        assert "ath_breakout" in STRATEGIES
        assert "earnings_dip" in STRATEGIES

    def test_default_regime_preferences_complete(self):
        """Test that default regime preferences cover all regimes."""
        assert "low_vol" in DEFAULT_REGIME_PREFERENCES
        assert "normal" in DEFAULT_REGIME_PREFERENCES
        assert "elevated" in DEFAULT_REGIME_PREFERENCES
        assert "high_vol" in DEFAULT_REGIME_PREFERENCES

        # Each regime should sum to 1.0
        for regime, prefs in DEFAULT_REGIME_PREFERENCES.items():
            total = sum(prefs.values())
            assert abs(total - 1.0) < 0.01, f"Regime {regime} preferences don't sum to 1.0"

    def test_feature_impact_structure(self):
        """Test feature impact dictionary structure."""
        assert "vwap" in FEATURE_IMPACT
        assert "market_context" in FEATURE_IMPACT
        assert "sector" in FEATURE_IMPACT

    def test_cluster_strategy_map_structure(self):
        """Test cluster strategy map structure."""
        for key, value in CLUSTER_STRATEGY_MAP.items():
            assert "strategy" in value
            assert "win_rate" in value
            assert "confidence" in value
            assert value["strategy"] in STRATEGIES

    def test_sector_strategy_map_structure(self):
        """Test sector strategy map structure."""
        for sector, value in SECTOR_STRATEGY_MAP.items():
            assert "strategy" in value
            assert "win_rate" in value
            assert "confidence" in value
            assert value["strategy"] in STRATEGIES

    def test_min_score_thresholds(self):
        """Test minimum score thresholds are defined."""
        for strat in STRATEGIES:
            assert strat in MIN_SCORE_THRESHOLDS
            assert MIN_SCORE_THRESHOLDS[strat] >= 0


# =============================================================================
# ENUM TESTS
# =============================================================================


class TestEnums:
    """Tests for enums."""

    def test_selection_method_values(self):
        """Test SelectionMethod enum values."""
        assert SelectionMethod.BEST_SCORE.value == "best_score"
        assert SelectionMethod.WEIGHTED_BEST.value == "weighted_best"
        assert SelectionMethod.ENSEMBLE_VOTE.value == "ensemble_vote"
        assert SelectionMethod.META_LEARNER.value == "meta_learner"
        assert SelectionMethod.CONFIDENCE_WEIGHTED.value == "confidence_weighted"

    def test_rotation_trigger_values(self):
        """Test RotationTrigger enum values."""
        assert RotationTrigger.PERFORMANCE_DECAY.value == "performance_decay"
        assert RotationTrigger.REGIME_CHANGE.value == "regime_change"
        assert RotationTrigger.TIME_BASED.value == "time_based"
        assert RotationTrigger.MANUAL.value == "manual"


# =============================================================================
# STRATEGY SCORE TESTS
# =============================================================================


class TestStrategyScore:
    """Tests for StrategyScore dataclass."""

    def test_creation(self, sample_strategy_score):
        """Test StrategyScore creation."""
        assert sample_strategy_score.strategy == "pullback"
        assert sample_strategy_score.raw_score == 8.5
        assert sample_strategy_score.weighted_score == 9.0
        assert sample_strategy_score.confidence == 0.85
        assert len(sample_strategy_score.breakdown) == 5

    def test_adjusted_score_property(self, sample_strategy_score):
        """Test adjusted_score calculation."""
        expected = 9.0 * 0.85  # weighted_score * confidence
        assert sample_strategy_score.adjusted_score == expected

    def test_to_dict(self, sample_strategy_score):
        """Test to_dict serialization."""
        d = sample_strategy_score.to_dict()
        assert d["strategy"] == "pullback"
        assert d["raw_score"] == 8.5
        assert d["weighted_score"] == 9.0
        assert d["confidence"] == 0.85
        assert "adjusted_score" in d
        assert "breakdown" in d

    def test_to_dict_rounding(self):
        """Test that to_dict rounds values correctly."""
        score = StrategyScore(
            strategy="test",
            raw_score=8.12345,
            weighted_score=9.56789,
            confidence=0.85432,
            breakdown={"rsi": 1.234567},
        )
        d = score.to_dict()
        assert d["raw_score"] == 8.12
        assert d["weighted_score"] == 9.57
        assert d["confidence"] == 0.854
        assert d["breakdown"]["rsi"] == 1.23


# =============================================================================
# ENSEMBLE RECOMMENDATION TESTS
# =============================================================================


class TestEnsembleRecommendation:
    """Tests for EnsembleRecommendation dataclass."""

    def test_creation(self, sample_ensemble_recommendation):
        """Test EnsembleRecommendation creation."""
        rec = sample_ensemble_recommendation
        assert rec.symbol == "AAPL"
        assert rec.recommended_strategy == "pullback"
        assert rec.recommended_score == 9.0
        assert rec.selection_method == SelectionMethod.META_LEARNER
        assert rec.regime == "normal"
        assert rec.vix == 18.5

    def test_to_dict(self, sample_ensemble_recommendation):
        """Test to_dict serialization."""
        d = sample_ensemble_recommendation.to_dict()
        assert d["symbol"] == "AAPL"
        assert "recommendation" in d
        assert d["recommendation"]["strategy"] == "pullback"
        assert "ensemble" in d
        assert "all_strategies" in d
        assert "context" in d
        assert "risk" in d

    def test_summary(self, sample_ensemble_recommendation):
        """Test summary formatting."""
        summary = sample_ensemble_recommendation.summary()
        assert "AAPL" in summary
        assert "PULLBACK" in summary
        assert "normal" in summary
        assert "bounce" in summary or "ath_breakout" in summary


# =============================================================================
# SYMBOL PERFORMANCE TESTS
# =============================================================================


class TestSymbolPerformance:
    """Tests for SymbolPerformance dataclass."""

    def test_creation(self, sample_symbol_performance):
        """Test SymbolPerformance creation."""
        perf = sample_symbol_performance
        assert perf.symbol == "AAPL"
        assert perf.strategy_win_rates["pullback"] == 0.65
        assert perf.best_strategy == "pullback"

    def test_get_preference_weights_with_history(self, sample_symbol_performance):
        """Test preference weights calculation with history."""
        weights = sample_symbol_performance.get_preference_weights()
        assert sum(weights.values()) - 1.0 < 0.01  # Should sum to ~1.0
        # Pullback should have highest weight due to better win rate and more samples
        assert weights["pullback"] >= weights["bounce"]

    def test_get_preference_weights_empty(self):
        """Test preference weights with no history."""
        perf = SymbolPerformance(symbol="TEST")
        weights = perf.get_preference_weights()
        assert all(w == 0.25 for w in weights.values())

    def test_to_dict(self, sample_symbol_performance):
        """Test to_dict serialization."""
        d = sample_symbol_performance.to_dict()
        assert d["symbol"] == "AAPL"
        assert "win_rates" in d
        assert "sample_sizes" in d
        assert "best_strategy" in d


# =============================================================================
# ROTATION STATE TESTS
# =============================================================================


class TestRotationState:
    """Tests for RotationState dataclass."""

    def test_should_rotate_time_based(self):
        """Test time-based rotation trigger."""
        state = RotationState(
            current_preferences={s: 0.25 for s in STRATEGIES},
            last_rotation_date=date.today() - timedelta(days=35),
            rotation_reason=None,
            recent_win_rates={s: [] for s in STRATEGIES},
            consecutive_losses={s: 0 for s in STRATEGIES},
        )
        should, trigger = state.should_rotate(date.today(), max_days=30)
        assert should is True
        assert trigger == RotationTrigger.TIME_BASED

    def test_should_rotate_performance_decay(self):
        """Test performance decay rotation trigger."""
        state = RotationState(
            current_preferences={s: 0.25 for s in STRATEGIES},
            last_rotation_date=date.today(),
            rotation_reason=None,
            recent_win_rates={
                "pullback": [0.0] * 15,  # 0% win rate in last 15 trades
                "bounce": [],
                "ath_breakout": [],
                "earnings_dip": [],
            },
            consecutive_losses={s: 0 for s in STRATEGIES},
        )
        should, trigger = state.should_rotate(date.today(), performance_threshold=0.40)
        assert should is True
        assert trigger == RotationTrigger.PERFORMANCE_DECAY

    def test_should_rotate_consecutive_losses(self):
        """Test consecutive losses rotation trigger."""
        state = RotationState(
            current_preferences={s: 0.25 for s in STRATEGIES},
            last_rotation_date=date.today(),
            rotation_reason=None,
            recent_win_rates={s: [] for s in STRATEGIES},
            consecutive_losses={
                "pullback": 6,  # More than 5 consecutive losses
                "bounce": 0,
                "ath_breakout": 0,
                "earnings_dip": 0,
            },
        )
        should, trigger = state.should_rotate(date.today())
        assert should is True
        assert trigger == RotationTrigger.PERFORMANCE_DECAY

    def test_should_not_rotate(self):
        """Test no rotation needed."""
        state = RotationState(
            current_preferences={s: 0.25 for s in STRATEGIES},
            last_rotation_date=date.today() - timedelta(days=10),
            rotation_reason=None,
            recent_win_rates={s: [0.5] * 5 for s in STRATEGIES},
            consecutive_losses={s: 0 for s in STRATEGIES},
        )
        should, trigger = state.should_rotate(date.today())
        assert should is False
        assert trigger is None


# =============================================================================
# META LEARNER TESTS
# =============================================================================


class TestMetaLearner:
    """Tests for MetaLearner class."""

    def test_initialization(self, meta_learner):
        """Test MetaLearner initialization."""
        assert meta_learner.history_window == 90
        assert meta_learner.min_samples == 10
        assert meta_learner.decay_factor == 0.95

    def test_predict_best_strategy_no_history(self, meta_learner, sample_strategy_scores):
        """Test prediction with no symbol history."""
        strat, confidence, reason = meta_learner.predict_best_strategy(
            "AAPL", sample_strategy_scores, "normal"
        )
        assert strat in STRATEGIES
        assert 0 <= confidence <= 1
        assert len(reason) > 0

    def test_predict_best_strategy_with_history(self, meta_learner, sample_strategy_scores):
        """Test prediction with symbol history."""
        # Add some history first
        for _ in range(15):
            meta_learner.update_performance(
                "AAPL", "pullback", True, 1.5, date.today() - timedelta(days=10), "normal"
            )

        strat, confidence, reason = meta_learner.predict_best_strategy(
            "AAPL", sample_strategy_scores, "normal"
        )
        assert strat in STRATEGIES
        assert confidence > 0

    def test_update_performance(self, meta_learner):
        """Test performance tracking update."""
        meta_learner.update_performance(
            "AAPL", "pullback", True, 1.5, date.today(), "normal"
        )

        perf = meta_learner._symbol_performance.get("AAPL")
        assert perf is not None
        assert perf.strategy_win_rates.get("pullback") == 1.0
        assert perf.strategy_sample_sizes.get("pullback") == 1

    def test_update_performance_multiple_trades(self, meta_learner):
        """Test multiple trades update."""
        meta_learner.update_performance("AAPL", "pullback", True, 1.5, date.today(), "normal")
        meta_learner.update_performance("AAPL", "pullback", False, -0.5, date.today(), "normal")
        meta_learner.update_performance("AAPL", "pullback", True, 1.0, date.today(), "normal")

        perf = meta_learner._symbol_performance.get("AAPL")
        assert perf.strategy_sample_sizes.get("pullback") == 3
        # Win rate should be 2/3 ≈ 0.67
        assert abs(perf.strategy_win_rates.get("pullback") - 0.6667) < 0.01

    def test_get_symbol_insights_no_data(self, meta_learner):
        """Test symbol insights with no data."""
        insights = meta_learner.get_symbol_insights("UNKNOWN")
        assert insights is None

    def test_get_symbol_insights_with_data(self, meta_learner):
        """Test symbol insights with data."""
        meta_learner.update_performance("AAPL", "pullback", True, 1.5, date.today(), "normal")

        insights = meta_learner.get_symbol_insights("AAPL")
        assert insights is not None
        assert insights["symbol"] == "AAPL"
        assert "win_rates" in insights
        assert "preference_weights" in insights

    def test_save_and_load(self, meta_learner):
        """Test save and load functionality."""
        # Add some data
        meta_learner.update_performance("AAPL", "pullback", True, 1.5, date.today(), "normal")
        meta_learner.update_performance("MSFT", "bounce", False, -0.5, date.today(), "normal")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "meta_learner.json"
            meta_learner.save(str(filepath))

            # Load and verify
            loaded = MetaLearner.load(str(filepath))
            assert "AAPL" in loaded._symbol_performance
            assert "MSFT" in loaded._symbol_performance


# =============================================================================
# STRATEGY ROTATION ENGINE TESTS
# =============================================================================


class TestStrategyRotationEngine:
    """Tests for StrategyRotationEngine class."""

    def test_initialization(self, rotation_engine):
        """Test StrategyRotationEngine initialization."""
        assert rotation_engine.rotation_window == 30
        assert rotation_engine.performance_threshold == 0.40
        assert rotation_engine.min_trades == 10

    def test_record_trade_result_win(self, rotation_engine):
        """Test recording a winning trade."""
        rotation_engine.record_trade_result("pullback", True, date.today())
        assert rotation_engine._state.recent_win_rates["pullback"] == [1.0]
        assert rotation_engine._state.consecutive_losses["pullback"] == 0

    def test_record_trade_result_loss(self, rotation_engine):
        """Test recording a losing trade."""
        rotation_engine.record_trade_result("pullback", False, date.today())
        assert rotation_engine._state.recent_win_rates["pullback"] == [0.0]
        assert rotation_engine._state.consecutive_losses["pullback"] == 1

    def test_record_trade_result_consecutive_losses(self, rotation_engine):
        """Test consecutive losses tracking."""
        for _ in range(3):
            rotation_engine.record_trade_result("pullback", False, date.today())
        assert rotation_engine._state.consecutive_losses["pullback"] == 3

        # Win resets counter
        rotation_engine.record_trade_result("pullback", True, date.today())
        assert rotation_engine._state.consecutive_losses["pullback"] == 0

    def test_check_rotation_no_rotation(self, rotation_engine):
        """Test check rotation when not needed."""
        result = rotation_engine.check_rotation(date.today())
        assert result is None

    def test_check_rotation_time_based(self, rotation_engine):
        """Test time-based rotation trigger."""
        rotation_engine._state.last_rotation_date = date.today() - timedelta(days=35)
        result = rotation_engine.check_rotation(date.today())
        assert result is not None
        assert result["trigger"] == "time_based"

    def test_get_current_preferences(self, rotation_engine):
        """Test getting current preferences."""
        prefs = rotation_engine.get_current_preferences()
        assert all(s in prefs for s in STRATEGIES)
        assert abs(sum(prefs.values()) - 1.0) < 0.01

    def test_get_rotation_summary(self, rotation_engine):
        """Test rotation summary."""
        summary = rotation_engine.get_rotation_summary()
        assert "current_preferences" in summary
        assert "last_rotation" in summary
        assert "days_since_rotation" in summary
        assert "rotation_count" in summary


# =============================================================================
# ENSEMBLE SELECTOR TESTS
# =============================================================================


class TestEnsembleSelector:
    """Tests for EnsembleSelector class."""

    def test_initialization(self, ensemble_selector):
        """Test EnsembleSelector initialization."""
        assert ensemble_selector.method == SelectionMethod.META_LEARNER
        assert ensemble_selector.enable_rotation is True
        assert ensemble_selector.min_score_threshold == 4.0

    def test_initialization_without_rotation(self):
        """Test initialization without rotation."""
        selector = EnsembleSelector(enable_rotation=False)
        assert selector._rotation_engine is None

    def test_get_recommendation(self, ensemble_selector, sample_strategy_scores):
        """Test getting a recommendation."""
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=sample_strategy_scores,
            vix=18.5,
        )
        assert rec.symbol == "AAPL"
        assert rec.recommended_strategy in STRATEGIES
        assert rec.regime == "normal"  # VIX 18.5 is normal regime

    def test_get_recommendation_low_vix(self, ensemble_selector, sample_strategy_scores):
        """Test recommendation with low VIX."""
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=sample_strategy_scores,
            vix=12.0,
        )
        assert rec.regime == "low_vol"

    def test_get_recommendation_elevated_vix(self, ensemble_selector, sample_strategy_scores):
        """Test recommendation with elevated VIX."""
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=sample_strategy_scores,
            vix=25.0,
        )
        assert rec.regime == "elevated"

    def test_get_recommendation_high_vix(self, ensemble_selector, sample_strategy_scores):
        """Test recommendation with high VIX."""
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=sample_strategy_scores,
            vix=35.0,
        )
        assert rec.regime == "high_vol"

    def test_get_recommendation_explicit_regime(self, ensemble_selector, sample_strategy_scores):
        """Test recommendation with explicit regime."""
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=sample_strategy_scores,
            vix=18.5,
            regime="elevated",  # Override VIX-based regime
        )
        assert rec.regime == "elevated"

    def test_get_recommendation_with_sector(self, ensemble_selector, sample_strategy_scores):
        """Test recommendation with sector."""
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=sample_strategy_scores,
            vix=18.5,
            sector="Technology",
        )
        assert rec is not None

    def test_get_recommendation_no_valid_scores(self, ensemble_selector):
        """Test recommendation with no valid scores."""
        low_scores = {
            "pullback": StrategyScore(
                strategy="pullback",
                raw_score=2.0,
                weighted_score=2.0,
                confidence=0.3,
                breakdown={"rsi": 0.5},
            ),
        }
        rec = ensemble_selector.get_recommendation(
            symbol="AAPL",
            strategy_scores=low_scores,
            vix=18.5,
        )
        # Should still return a recommendation even if below threshold
        assert rec is not None

    def test_update_with_result(self, ensemble_selector):
        """Test updating with trade result."""
        ensemble_selector.update_with_result(
            symbol="AAPL",
            strategy="pullback",
            outcome=True,
            pnl_percent=1.5,
            signal_date=date.today(),
            regime="normal",
        )

        # Check meta-learner was updated
        insights = ensemble_selector.get_insights("AAPL")
        assert insights is not None

    def test_get_regime_from_vix(self, ensemble_selector):
        """Test VIX to regime mapping."""
        assert ensemble_selector._get_regime_from_vix(10) == "low_vol"
        assert ensemble_selector._get_regime_from_vix(17) == "normal"
        assert ensemble_selector._get_regime_from_vix(25) == "elevated"
        assert ensemble_selector._get_regime_from_vix(35) == "high_vol"

    def test_select_best_score(self, ensemble_selector, sample_strategy_scores):
        """Test best score selection method."""
        strat, conf, reason = ensemble_selector._select_best_score(sample_strategy_scores)
        assert strat == "pullback"  # Highest raw score
        assert "highest raw score" in reason

    def test_select_best_score_empty(self, ensemble_selector):
        """Test best score selection with empty scores."""
        strat, conf, reason = ensemble_selector._select_best_score({})
        assert strat == "pullback"  # Default
        assert conf == 0.0

    def test_select_weighted_best(self, ensemble_selector, sample_strategy_scores):
        """Test weighted best selection method."""
        strat, conf, reason = ensemble_selector._select_weighted_best(
            sample_strategy_scores, "normal"
        )
        assert strat in STRATEGIES
        assert "regime-weighted" in reason

    def test_select_confidence_weighted(self, ensemble_selector, sample_strategy_scores):
        """Test confidence weighted selection method."""
        strat, conf, reason = ensemble_selector._select_confidence_weighted(sample_strategy_scores)
        assert strat in STRATEGIES
        assert "confidence-adjusted" in reason

    def test_select_ensemble_vote(self, ensemble_selector, sample_strategy_scores):
        """Test ensemble vote selection method."""
        strat, conf, reason = ensemble_selector._select_ensemble_vote(
            "AAPL", sample_strategy_scores, "normal"
        )
        assert strat in STRATEGIES
        assert "ensemble vote" in reason

    def test_calculate_ensemble_score(self, ensemble_selector, sample_strategy_scores):
        """Test ensemble score calculation."""
        score, conf = ensemble_selector._calculate_ensemble_score(
            sample_strategy_scores, "normal"
        )
        assert score > 0
        assert 0 <= conf <= 1

    def test_calculate_ensemble_score_empty(self, ensemble_selector):
        """Test ensemble score with empty scores."""
        score, conf = ensemble_selector._calculate_ensemble_score({}, "normal")
        assert score == 0.0
        assert conf == 0.0

    def test_get_alternatives(self, ensemble_selector, sample_strategy_scores):
        """Test getting alternative strategies."""
        alts = ensemble_selector._get_alternatives(sample_strategy_scores, "pullback")
        assert "pullback" not in alts
        assert len(alts) <= 2

    def test_calculate_diversification_benefit(self, ensemble_selector, sample_strategy_scores):
        """Test diversification benefit calculation."""
        benefit = ensemble_selector._calculate_diversification_benefit(sample_strategy_scores)
        assert 0 <= benefit <= 1

    def test_calculate_diversification_benefit_single(self, ensemble_selector):
        """Test diversification with single strategy."""
        single = {
            "pullback": StrategyScore(
                strategy="pullback",
                raw_score=8.0,
                weighted_score=8.0,
                confidence=0.8,
                breakdown={},
            ),
        }
        benefit = ensemble_selector._calculate_diversification_benefit(single)
        assert benefit == 0.0

    def test_calculate_strategy_correlation(self, ensemble_selector, sample_strategy_scores):
        """Test strategy correlation calculation."""
        corr = ensemble_selector._calculate_strategy_correlation(
            sample_strategy_scores, "pullback"
        )
        assert 0 <= corr <= 1

    def test_get_insights_no_data(self, ensemble_selector):
        """Test insights with no data."""
        insights = ensemble_selector.get_insights("UNKNOWN")
        assert insights is None

    def test_get_rotation_status(self, ensemble_selector):
        """Test rotation status."""
        status = ensemble_selector.get_rotation_status()
        assert status is not None
        assert "current_preferences" in status

    def test_get_rotation_status_disabled(self):
        """Test rotation status when disabled."""
        selector = EnsembleSelector(enable_rotation=False)
        status = selector.get_rotation_status()
        assert status is None

    def test_save_and_load(self, ensemble_selector):
        """Test save and load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "ensemble.json"
            ensemble_selector.save(str(filepath))

            loaded = EnsembleSelector.load(str(filepath))
            assert loaded.method == ensemble_selector.method
            assert loaded.enable_rotation == ensemble_selector.enable_rotation


class TestEnsembleSelectorMethods:
    """Tests for different selection methods."""

    def test_best_score_method(self, sample_strategy_scores):
        """Test BEST_SCORE selection method."""
        selector = EnsembleSelector(method=SelectionMethod.BEST_SCORE)
        rec = selector.get_recommendation("AAPL", sample_strategy_scores, vix=18.5)
        assert rec.selection_method == SelectionMethod.BEST_SCORE
        assert rec.recommended_strategy == "pullback"  # Highest raw score

    def test_weighted_best_method(self, sample_strategy_scores):
        """Test WEIGHTED_BEST selection method."""
        selector = EnsembleSelector(method=SelectionMethod.WEIGHTED_BEST)
        rec = selector.get_recommendation("AAPL", sample_strategy_scores, vix=18.5)
        assert rec.selection_method == SelectionMethod.WEIGHTED_BEST

    def test_ensemble_vote_method(self, sample_strategy_scores):
        """Test ENSEMBLE_VOTE selection method."""
        selector = EnsembleSelector(method=SelectionMethod.ENSEMBLE_VOTE)
        rec = selector.get_recommendation("AAPL", sample_strategy_scores, vix=18.5)
        assert rec.selection_method == SelectionMethod.ENSEMBLE_VOTE

    def test_confidence_weighted_method(self, sample_strategy_scores):
        """Test CONFIDENCE_WEIGHTED selection method."""
        selector = EnsembleSelector(method=SelectionMethod.CONFIDENCE_WEIGHTED)
        rec = selector.get_recommendation("AAPL", sample_strategy_scores, vix=18.5)
        assert rec.selection_method == SelectionMethod.CONFIDENCE_WEIGHTED


class TestEnsembleSelectorClusterAndSector:
    """Tests for cluster and sector recommendations."""

    def test_get_cluster_recommendation_no_data(self, ensemble_selector):
        """Test cluster recommendation without cluster data."""
        rec = ensemble_selector.get_cluster_recommendation("AAPL")
        assert rec is None

    def test_get_cluster_recommendation_with_data(self):
        """Test cluster recommendation with cluster data."""
        selector = EnsembleSelector()
        selector._symbol_clusters = {
            "AAPL": {
                "cluster_name": "Steady Mean-Reverting Medium",
                "vol_regime": "low",
                "price_tier": "medium",
                "trend_bias": "mean_reverting",
            }
        }

        rec = selector.get_cluster_recommendation("AAPL")
        assert rec is not None
        assert rec["symbol"] == "AAPL"
        assert "strategy" in rec
        assert "win_rate" in rec

    def test_get_sector_recommendation_known_sector(self, ensemble_selector):
        """Test sector recommendation for known sector."""
        rec = ensemble_selector.get_sector_recommendation("Utilities")
        assert rec is not None
        assert rec["strategy"] == "earnings_dip"
        assert rec["win_rate"] == 90.0

    def test_get_sector_recommendation_unknown_sector(self, ensemble_selector):
        """Test sector recommendation for unknown sector."""
        rec = ensemble_selector.get_sector_recommendation("Unknown")
        assert rec is None

    def test_get_sector_weights_no_data(self, ensemble_selector):
        """Test sector weights without loaded data."""
        weights = ensemble_selector.get_sector_weights("Technology")
        assert weights == DEFAULT_COMPONENT_WEIGHTS

    def test_get_sector_weights_with_data(self):
        """Test sector weights with loaded data."""
        selector = EnsembleSelector()
        selector._sector_weights = {
            "Technology": {
                "optimal_weights": {"rsi": 1.5, "support": 1.2},
                "win_rate": 55.0,
            }
        }

        weights = selector.get_sector_weights("Technology")
        assert weights["rsi"] == 1.5
        assert weights["support"] == 1.2

    def test_get_cluster_weights_no_data(self, ensemble_selector):
        """Test cluster weights without loaded data."""
        weights = ensemble_selector.get_cluster_weights("Steady Mean-Reverting Medium")
        assert weights == DEFAULT_COMPONENT_WEIGHTS

    def test_get_combined_weights_default(self, ensemble_selector):
        """Test combined weights returns default."""
        weights, source = ensemble_selector.get_combined_weights("AAPL")
        assert weights == DEFAULT_COMPONENT_WEIGHTS
        assert source == "default"

    def test_get_combined_weights_cluster(self):
        """Test combined weights uses cluster."""
        selector = EnsembleSelector()
        selector._symbol_clusters = {
            "AAPL": {"cluster_name": "Test Cluster"}
        }
        selector._cluster_weights = {
            "Test Cluster": {
                "optimal_weights": {"rsi": 2.0},
                "win_rate": 60.0,
            }
        }

        weights, source = selector.get_combined_weights("AAPL")
        assert weights["rsi"] == 2.0
        assert "cluster:" in source

    def test_get_strategy_preference_no_data(self, ensemble_selector):
        """Test strategy preference without data."""
        strat, conf, source = ensemble_selector.get_strategy_preference("AAPL")
        assert strat is None
        assert conf == 0.0
        assert source == "no preference"

    def test_get_strategy_preference_from_sector(self):
        """Test strategy preference from sector."""
        selector = EnsembleSelector()
        strat, conf, source = selector.get_strategy_preference("AAPL", "Utilities")
        assert strat == "earnings_dip"
        assert conf > 0.5
        assert "sector:" in source


class TestEnsembleSelectorLoadTrainedModel:
    """Tests for loading trained models."""

    def test_load_trained_model_no_files(self):
        """Test loading when model files don't exist."""
        with patch.object(Path, 'exists', return_value=False):
            selector = EnsembleSelector.load_trained_model()
            assert selector is not None
            assert selector._symbol_clusters == {}

    def test_load_trained_model_with_files(self):
        """Test loading with mock model files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            models_dir = Path(tmpdir) / ".optionplay" / "models"
            models_dir.mkdir(parents=True)

            # Create mock ensemble model
            ensemble_data = {
                "top_symbol_preferences": {
                    "AAPL": {"strategy": "pullback", "win_rate": 65.0, "trades": 20},
                }
            }
            with open(models_dir / "ENSEMBLE_V2_TRAINED.json", "w") as f:
                json.dump(ensemble_data, f)

            # Create mock cluster data
            cluster_data = {
                "symbol_to_cluster": {
                    "AAPL": {"cluster_name": "Test", "vol_regime": "low"}
                }
            }
            with open(models_dir / "SYMBOL_CLUSTERS.json", "w") as f:
                json.dump(cluster_data, f)

            with patch.object(Path, 'home', return_value=Path(tmpdir)):
                selector = EnsembleSelector.load_trained_model()
                assert "AAPL" in selector._meta_learner._symbol_performance


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_create_strategy_score_basic(self):
        """Test basic strategy score creation."""
        score = create_strategy_score(
            strategy="pullback",
            raw_score=8.0,
            breakdown={"rsi": 1.5, "support": 2.0},
        )
        assert score.strategy == "pullback"
        assert score.raw_score == 8.0
        assert score.weighted_score == 8.0  # Defaults to raw_score

    def test_create_strategy_score_with_weights(self):
        """Test strategy score creation with explicit weighted score."""
        score = create_strategy_score(
            strategy="pullback",
            raw_score=8.0,
            breakdown={"rsi": 1.5},
            weighted_score=9.0,
            confidence=0.9,
        )
        assert score.weighted_score == 9.0
        assert score.confidence == 0.9

    def test_create_strategy_score_auto_confidence(self):
        """Test automatic confidence calculation."""
        score = create_strategy_score(
            strategy="pullback",
            raw_score=6.0,
            breakdown={"rsi": 1.5, "support": 2.0, "macd": 2.5},  # 3 components
        )
        # Max possible = 3 * 2 = 6, raw = 6, confidence = 6/6 = 1.0
        assert score.confidence == 1.0

    def test_create_strategy_score_empty_breakdown(self):
        """Test with empty breakdown."""
        score = create_strategy_score(
            strategy="pullback",
            raw_score=8.0,
            breakdown={},
        )
        assert score.confidence == 0.5  # Default when empty

    def test_format_ensemble_summary(self, sample_ensemble_recommendation):
        """Test formatting ensemble summary."""
        summary = format_ensemble_summary(sample_ensemble_recommendation)
        assert "AAPL" in summary
        assert "PULLBACK" in summary
