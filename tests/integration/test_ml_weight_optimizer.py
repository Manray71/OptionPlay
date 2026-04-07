"""
Tests for the ML Weight Optimizer module.

Tests cover:
- ComponentStats dataclass
- WeightConfig dataclass
- OptimizationResult dataclass
- TradeFeatures dataclass
- FeatureExtractor class
- MLWeightOptimizer class
- WeightedScorer class
"""

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.backtesting import (
    ALL_COMPONENTS,
    DEFAULT_WEIGHTS,
    STRATEGY_COMPONENTS,
    ComponentStats,
    FeatureExtractor,
    MLWeightOptimizer,
    OptimizationMethod,
    OptimizationResult,
    TradeFeatures,
    WeightConfig,
    WeightedScorer,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_component_stats():
    """Create sample ComponentStats."""
    return ComponentStats(
        name="rsi_score",
        sample_size=100,
        win_rate_correlation=0.25,
        pnl_correlation=0.20,
        avg_value_winners=1.8,
        avg_value_losers=1.2,
        std_value=0.5,
        rf_importance=0.15,
        gb_importance=0.18,
        ensemble_importance=0.165,
        predictive_power="moderate",
        recommended_weight=1.2,
        confidence_interval=(0.96, 1.44),
    )


@pytest.fixture
def sample_weight_config():
    """Create sample WeightConfig."""
    return WeightConfig(
        strategy="pullback",
        regime="normal",
        weights={
            "rsi_score": 1.2,
            "support_score": 1.5,
            "macd_score": 0.8,
            "volume_score": 1.0,
        },
        normalized_weights={
            "rsi_score": 0.27,
            "support_score": 0.33,
            "macd_score": 0.18,
            "volume_score": 0.22,
        },
        method=OptimizationMethod.ENSEMBLE,
        training_date=datetime(2026, 1, 15, 10, 0, 0),
        sample_size=500,
        validation_score=0.58,
        confidence="high",
    )


@pytest.fixture
def sample_optimization_result(sample_weight_config, sample_component_stats):
    """Create sample OptimizationResult."""
    strategy_weights = {
        "pullback": sample_weight_config,
        "bounce": WeightConfig(
            strategy="bounce",
            regime=None,
            weights={"rsi_score": 1.0, "support_score": 1.2},
            normalized_weights={"rsi_score": 0.45, "support_score": 0.55},
            method=OptimizationMethod.CORRELATION,
            training_date=datetime(2026, 1, 15, 10, 0, 0),
            sample_size=300,
            validation_score=0.55,
            confidence="medium",
        ),
    }
    return OptimizationResult(
        optimization_id="test_opt_123",
        optimization_date=datetime(2026, 1, 15, 10, 30, 0),
        strategy_weights=strategy_weights,
        regime_weights={},
        component_stats={"rsi_score": sample_component_stats},
        total_trades_analyzed=800,
        overall_validation_score=0.56,
        improvement_vs_baseline=3.5,
        warnings=["Test warning"],
    )


@pytest.fixture
def sample_trade_features():
    """Create sample TradeFeatures."""
    return TradeFeatures(
        trade_id="trade_001",
        symbol="AAPL",
        strategy="pullback",
        signal_date=date(2026, 1, 10),
        components={
            "rsi_score": 1.5,
            "support_score": 2.0,
            "macd_score": 1.0,
        },
        is_winner=True,
        pnl_percent=1.5,
        vix_at_signal=18.5,
        regime="normal",
        holding_days=15,
    )


@pytest.fixture
def sample_trades():
    """Create sample trade data for training."""
    trades = []
    np.random.seed(42)

    for i in range(100):
        is_win = np.random.random() > 0.45
        trades.append({
            "id": i,
            "symbol": np.random.choice(["AAPL", "MSFT", "GOOGL"]),
            "strategy": np.random.choice(["pullback", "bounce"]),
            "signal_date": date(2026, 1, 1) + timedelta(days=i % 30),
            "outcome": "WIN" if is_win else "LOSS",
            "pnl_percent": np.random.uniform(0.5, 2.0) if is_win else np.random.uniform(-1.0, -0.5),
            "vix_at_signal": np.random.uniform(12, 30),
            "holding_days": np.random.randint(5, 30),
            "score_breakdown": {
                "rsi_score": np.random.uniform(0, 2),
                "support_score": np.random.uniform(0, 2),
                "macd_score": np.random.uniform(0, 2),
                "volume_score": np.random.uniform(0, 2),
            },
        })
    return trades


@pytest.fixture
def feature_extractor():
    """Create FeatureExtractor."""
    return FeatureExtractor()


@pytest.fixture
def ml_optimizer():
    """Create MLWeightOptimizer."""
    return MLWeightOptimizer(
        method=OptimizationMethod.ENSEMBLE,
        cv_folds=3,
        min_samples_per_strategy=20,
        enable_regime_weights=True,
    )


# =============================================================================
# CONSTANTS TESTS
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_all_components_defined(self):
        """Test that all components are defined."""
        assert len(ALL_COMPONENTS) > 10
        assert "rsi_score" in ALL_COMPONENTS
        assert "support_score" in ALL_COMPONENTS
        assert "vwap_score" in ALL_COMPONENTS

    def test_strategy_components_defined(self):
        """Test that strategy components are defined."""
        assert "pullback" in STRATEGY_COMPONENTS
        assert "bounce" in STRATEGY_COMPONENTS

    def test_default_weights(self):
        """Test default weights."""
        assert all(w == 1.0 for w in DEFAULT_WEIGHTS.values())


# =============================================================================
# OPTIMIZATION METHOD TESTS
# =============================================================================


class TestOptimizationMethod:
    """Tests for OptimizationMethod enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert OptimizationMethod.RANDOM_FOREST.value == "random_forest"
        assert OptimizationMethod.GRADIENT_BOOSTING.value == "gradient_boosting"
        assert OptimizationMethod.CORRELATION.value == "correlation"
        assert OptimizationMethod.ENSEMBLE.value == "ensemble"


# =============================================================================
# COMPONENT STATS TESTS
# =============================================================================


class TestComponentStats:
    """Tests for ComponentStats dataclass."""

    def test_creation(self, sample_component_stats):
        """Test ComponentStats creation."""
        assert sample_component_stats.name == "rsi_score"
        assert sample_component_stats.sample_size == 100
        assert sample_component_stats.win_rate_correlation == 0.25

    def test_to_dict(self, sample_component_stats):
        """Test to_dict serialization."""
        d = sample_component_stats.to_dict()
        assert d["name"] == "rsi_score"
        assert "correlations" in d
        assert "distribution" in d
        assert "importance" in d
        assert d["predictive_power"] == "moderate"

    def test_to_dict_rounding(self):
        """Test that to_dict rounds values correctly."""
        stats = ComponentStats(
            name="test",
            sample_size=100,
            win_rate_correlation=0.12345678,
            pnl_correlation=0.23456789,
            avg_value_winners=1.23456789,
            avg_value_losers=0.98765432,
            std_value=0.56789012,
            rf_importance=0.11111111,
            gb_importance=0.22222222,
            ensemble_importance=0.16666666,
            predictive_power="moderate",
            recommended_weight=1.23456789,
            confidence_interval=(0.98765, 1.48765),
        )
        d = stats.to_dict()
        assert d["correlations"]["win_rate"] == 0.1235
        assert d["distribution"]["avg_winners"] == 1.235
        assert d["importance"]["ensemble"] == 0.1667


# =============================================================================
# WEIGHT CONFIG TESTS
# =============================================================================


class TestWeightConfig:
    """Tests for WeightConfig dataclass."""

    def test_creation(self, sample_weight_config):
        """Test WeightConfig creation."""
        assert sample_weight_config.strategy == "pullback"
        assert sample_weight_config.regime == "normal"
        assert sample_weight_config.confidence == "high"

    def test_apply_weights(self, sample_weight_config):
        """Test apply_weights method."""
        breakdown = {
            "rsi_score": 1.0,
            "support_score": 2.0,
            "macd_score": 1.5,
            "volume_score": 1.0,
        }
        weighted = sample_weight_config.apply_weights(breakdown)
        # 1.0*1.2 + 2.0*1.5 + 1.5*0.8 + 1.0*1.0 = 1.2 + 3.0 + 1.2 + 1.0 = 6.4
        assert weighted == pytest.approx(6.4)

    def test_apply_weights_missing_component(self, sample_weight_config):
        """Test apply_weights with missing component uses default weight."""
        breakdown = {
            "rsi_score": 1.0,
            "unknown_score": 2.0,  # Not in weights
        }
        weighted = sample_weight_config.apply_weights(breakdown)
        # 1.0*1.2 + 2.0*1.0 = 3.2
        assert weighted == pytest.approx(3.2)

    def test_apply_normalized(self, sample_weight_config):
        """Test apply_normalized method."""
        breakdown = {
            "rsi_score": 1.0,
            "support_score": 1.0,
            "macd_score": 1.0,
            "volume_score": 1.0,
        }
        normalized = sample_weight_config.apply_normalized(breakdown)
        assert normalized > 0

    def test_to_dict(self, sample_weight_config):
        """Test to_dict serialization."""
        d = sample_weight_config.to_dict()
        assert d["strategy"] == "pullback"
        assert d["regime"] == "normal"
        assert "weights" in d
        assert "normalized_weights" in d
        assert "metadata" in d

    def test_from_dict(self, sample_weight_config):
        """Test from_dict deserialization."""
        d = sample_weight_config.to_dict()
        loaded = WeightConfig.from_dict(d)
        assert loaded.strategy == sample_weight_config.strategy
        assert loaded.regime == sample_weight_config.regime
        assert loaded.confidence == sample_weight_config.confidence


# =============================================================================
# OPTIMIZATION RESULT TESTS
# =============================================================================


class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""

    def test_creation(self, sample_optimization_result):
        """Test OptimizationResult creation."""
        assert sample_optimization_result.optimization_id == "test_opt_123"
        assert sample_optimization_result.total_trades_analyzed == 800
        assert len(sample_optimization_result.warnings) == 1

    def test_get_weights_strategy(self, sample_optimization_result):
        """Test get_weights for strategy."""
        config = sample_optimization_result.get_weights("pullback")
        assert config.strategy == "pullback"
        assert config.regime == "normal"

    def test_get_weights_unknown_strategy(self, sample_optimization_result):
        """Test get_weights for unknown strategy returns default."""
        config = sample_optimization_result.get_weights("unknown")
        assert config.strategy == "unknown"
        assert config.confidence == "low"

    def test_get_weights_with_regime(self, sample_optimization_result):
        """Test get_weights with regime (falls back to strategy weights)."""
        config = sample_optimization_result.get_weights("pullback", regime="elevated")
        assert config.strategy == "pullback"

    def test_to_dict(self, sample_optimization_result):
        """Test to_dict serialization."""
        d = sample_optimization_result.to_dict()
        assert d["optimization_id"] == "test_opt_123"
        assert "strategy_weights" in d
        assert "component_stats" in d
        assert "summary" in d
        assert "warnings" in d

    def test_summary(self, sample_optimization_result):
        """Test summary formatting."""
        summary = sample_optimization_result.summary()
        assert "WEIGHT OPTIMIZATION" in summary
        assert "test_opt_123" in summary
        assert "800" in summary


# =============================================================================
# TRADE FEATURES TESTS
# =============================================================================


class TestTradeFeatures:
    """Tests for TradeFeatures dataclass."""

    def test_creation(self, sample_trade_features):
        """Test TradeFeatures creation."""
        assert sample_trade_features.trade_id == "trade_001"
        assert sample_trade_features.symbol == "AAPL"
        assert sample_trade_features.is_winner is True
        assert sample_trade_features.pnl_percent == 1.5


# =============================================================================
# FEATURE EXTRACTOR TESTS
# =============================================================================


class TestFeatureExtractor:
    """Tests for FeatureExtractor class."""

    def test_initialization(self, feature_extractor):
        """Test FeatureExtractor initialization."""
        assert feature_extractor._regime_boundaries is not None
        assert "low_vol" in feature_extractor._regime_boundaries

    def test_extract_from_trades(self, feature_extractor, sample_trades):
        """Test feature extraction from trades."""
        features = feature_extractor.extract_from_trades(sample_trades)
        assert len(features) > 0
        assert all(isinstance(f, TradeFeatures) for f in features)

    def test_extract_from_trades_empty(self, feature_extractor):
        """Test feature extraction with empty trades."""
        features = feature_extractor.extract_from_trades([])
        assert len(features) == 0

    def test_extract_skips_incomplete_trades(self, feature_extractor):
        """Test that incomplete trades are skipped."""
        trades = [
            {"outcome": "PENDING", "score_breakdown": {"rsi_score": 1.0}},
            {"outcome": "WIN", "score_breakdown": {"rsi_score": 1.5}},
        ]
        features = feature_extractor.extract_from_trades(trades)
        assert len(features) == 1

    def test_extract_handles_json_string_breakdown(self, feature_extractor):
        """Test extraction handles JSON string score_breakdown."""
        trades = [
            {
                "outcome": "WIN",
                "score_breakdown": json.dumps({"rsi_score": 1.5, "support_score": 2.0}),
                "pnl_percent": 1.0,
            },
        ]
        features = feature_extractor.extract_from_trades(trades)
        assert len(features) == 1
        assert "rsi_score" in features[0].components

    def test_extract_handles_nested_breakdown(self, feature_extractor):
        """Test extraction handles nested score_breakdown dict."""
        trades = [
            {
                "outcome": "WIN",
                "score_breakdown": {
                    "rsi": {"score": 1.5, "detail": "good"},
                    "support": {"value": 2.0},
                },
                "pnl_percent": 1.0,
            },
        ]
        features = feature_extractor.extract_from_trades(trades)
        assert len(features) == 1
        assert features[0].components.get("rsi_score") == 1.5

    def test_get_regime_low_vol(self, feature_extractor):
        """Test regime detection for low VIX."""
        assert feature_extractor._get_regime(12.0) == "low_vol"

    def test_get_regime_normal(self, feature_extractor):
        """Test regime detection for normal VIX."""
        assert feature_extractor._get_regime(17.0) == "normal"

    def test_get_regime_elevated(self, feature_extractor):
        """Test regime detection for elevated VIX."""
        assert feature_extractor._get_regime(25.0) == "elevated"

    def test_get_regime_high_vol(self, feature_extractor):
        """Test regime detection for high VIX."""
        assert feature_extractor._get_regime(35.0) == "high_vol"

    def test_parse_date_date_object(self, feature_extractor):
        """Test date parsing with date object."""
        d = date(2026, 1, 15)
        assert feature_extractor._parse_date(d) == d

    def test_parse_date_datetime_object(self, feature_extractor):
        """Test date parsing with datetime object."""
        dt = datetime(2026, 1, 15, 10, 30)
        result = feature_extractor._parse_date(dt)
        # The result could be either a datetime or date object
        if isinstance(result, datetime):
            assert result.date() == date(2026, 1, 15)
        else:
            assert result == date(2026, 1, 15)

    def test_parse_date_string(self, feature_extractor):
        """Test date parsing with string."""
        assert feature_extractor._parse_date("2026-01-15") == date(2026, 1, 15)

    def test_parse_date_invalid(self, feature_extractor):
        """Test date parsing with invalid input returns today."""
        result = feature_extractor._parse_date("invalid")
        assert result == date.today()


# =============================================================================
# ML WEIGHT OPTIMIZER TESTS
# =============================================================================


class TestMLWeightOptimizer:
    """Tests for MLWeightOptimizer class."""

    def test_initialization(self, ml_optimizer):
        """Test MLWeightOptimizer initialization."""
        assert ml_optimizer.method == OptimizationMethod.ENSEMBLE
        assert ml_optimizer.cv_folds == 3
        assert ml_optimizer.min_samples == 20
        assert ml_optimizer.enable_regime_weights is True

    def test_initialization_default(self):
        """Test default initialization."""
        opt = MLWeightOptimizer()
        assert opt.method == OptimizationMethod.ENSEMBLE
        assert opt.cv_folds == 5

    def test_train_with_insufficient_data(self, ml_optimizer):
        """Test training with insufficient data."""
        trades = [{"outcome": "WIN", "score_breakdown": {"rsi_score": 1.0}}]
        result = ml_optimizer.train(trades)
        assert "Only" in result.warnings[0]
        assert result.total_trades_analyzed == 0

    def test_train_with_sufficient_data(self, ml_optimizer, sample_trades):
        """Test training with sufficient data."""
        result = ml_optimizer.train(sample_trades)
        assert result.total_trades_analyzed > 0
        assert "pullback" in result.strategy_weights or "bounce" in result.strategy_weights

    def test_analyze_components(self, ml_optimizer, sample_trades):
        """Test component analysis."""
        features = ml_optimizer._feature_extractor.extract_from_trades(sample_trades)
        stats = ml_optimizer._analyze_components(features)
        assert len(stats) > 0
        for stat in stats.values():
            assert isinstance(stat, ComponentStats)

    def test_safe_correlation(self, ml_optimizer):
        """Test safe correlation calculation."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([2.0, 4.0, 5.0, 8.0, 10.0])
        corr = ml_optimizer._safe_correlation(x, y)
        assert 0.9 < corr <= 1.0  # High positive correlation

    def test_safe_correlation_zero_std(self, ml_optimizer):
        """Test safe correlation with zero std."""
        x = np.array([1.0, 1.0, 1.0])
        y = np.array([2.0, 3.0, 4.0])
        corr = ml_optimizer._safe_correlation(x, y)
        assert corr == 0.0

    def test_safe_correlation_insufficient_data(self, ml_optimizer):
        """Test safe correlation with insufficient data."""
        x = np.array([1.0])
        y = np.array([2.0])
        corr = ml_optimizer._safe_correlation(x, y)
        assert corr == 0.0

    def test_create_default_weight_config(self, ml_optimizer):
        """Test creating default weight config."""
        config = ml_optimizer._create_default_weight_config("pullback")
        assert config.strategy == "pullback"
        assert config.confidence == "low"
        assert config.sample_size == 0

    def test_create_default_result(self, ml_optimizer):
        """Test creating default result."""
        result = ml_optimizer._create_default_result("test_id", ["Warning 1"])
        assert result.optimization_id == "test_id"
        assert "Warning 1" in result.warnings
        assert result.total_trades_analyzed == 0

    def test_calculate_baseline_score(self, ml_optimizer, sample_trades):
        """Test baseline score calculation."""
        features = ml_optimizer._feature_extractor.extract_from_trades(sample_trades)
        score = ml_optimizer._calculate_baseline_score(features)
        assert 0 <= score <= 1

    def test_calculate_baseline_score_empty(self, ml_optimizer):
        """Test baseline score with empty features."""
        score = ml_optimizer._calculate_baseline_score([])
        assert score == 0.0

    def test_cross_validate(self, ml_optimizer, sample_trades):
        """Test cross-validation."""
        features = ml_optimizer._feature_extractor.extract_from_trades(sample_trades)
        weights = {"rsi_score": 1.0, "support_score": 1.0}
        score = ml_optimizer._cross_validate(features, weights)
        assert 0 <= score <= 1

    def test_cross_validate_insufficient_data(self, ml_optimizer):
        """Test cross-validation with insufficient data."""
        features = [
            TradeFeatures(
                trade_id="1",
                symbol="AAPL",
                strategy="pullback",
                signal_date=date.today(),
                components={"rsi_score": 1.0},
                is_winner=True,
                pnl_percent=1.0,
                vix_at_signal=18,
                regime="normal",
                holding_days=10,
            )
        ]
        score = ml_optimizer._cross_validate(features, {"rsi_score": 1.0})
        assert score == 0.0


class TestMLWeightOptimizerPersistence:
    """Tests for MLWeightOptimizer persistence."""

    def test_save_and_load(self, ml_optimizer, sample_trades):
        """Test save and load."""
        result = ml_optimizer.train(sample_trades)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "weights.json"
            saved_path = ml_optimizer.save(result, str(filepath))

            loaded = MLWeightOptimizer.load(saved_path)
            assert loaded.optimization_id == result.optimization_id
            assert loaded.total_trades_analyzed == result.total_trades_analyzed

    def test_save_creates_directory(self, ml_optimizer, sample_trades):
        """Test save creates parent directory."""
        result = ml_optimizer.train(sample_trades)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "nested" / "dir" / "weights.json"
            saved_path = ml_optimizer.save(result, str(filepath))
            assert Path(saved_path).exists()

    def test_load_latest_no_files(self):
        """Test load_latest with no files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = MLWeightOptimizer.load_latest(tmpdir)
            assert result is None

    def test_load_latest_nonexistent_dir(self):
        """Test load_latest with nonexistent directory."""
        result = MLWeightOptimizer.load_latest("/nonexistent/path")
        assert result is None


# =============================================================================
# WEIGHTED SCORER TESTS
# =============================================================================


class TestWeightedScorer:
    """Tests for WeightedScorer class."""

    def test_initialization_without_result(self):
        """Test initialization without optimization result."""
        scorer = WeightedScorer()
        assert scorer._result is None

    def test_initialization_with_result(self, sample_optimization_result):
        """Test initialization with optimization result."""
        scorer = WeightedScorer(sample_optimization_result)
        assert scorer._result is not None

    def test_score_without_optimization(self):
        """Test scoring without optimization."""
        scorer = WeightedScorer()
        breakdown = {"rsi_score": 1.0, "support_score": 2.0}
        score = scorer.score(breakdown, strategy="pullback")
        assert score == 3.0  # Sum of raw scores

    def test_score_with_optimization(self, sample_optimization_result):
        """Test scoring with optimization."""
        scorer = WeightedScorer(sample_optimization_result)
        breakdown = {"rsi_score": 1.0, "support_score": 2.0}
        score = scorer.score(breakdown, strategy="pullback")
        assert score != 3.0  # Should be weighted

    def test_score_with_vix_low(self, sample_optimization_result):
        """Test scoring with VIX auto-regime (low)."""
        scorer = WeightedScorer(sample_optimization_result)
        breakdown = {"rsi_score": 1.0}
        scorer.score(breakdown, strategy="pullback", vix=12.0)
        # Just ensure no error

    def test_score_with_vix_normal(self, sample_optimization_result):
        """Test scoring with VIX auto-regime (normal)."""
        scorer = WeightedScorer(sample_optimization_result)
        breakdown = {"rsi_score": 1.0}
        scorer.score(breakdown, strategy="pullback", vix=17.0)

    def test_score_with_vix_elevated(self, sample_optimization_result):
        """Test scoring with VIX auto-regime (elevated)."""
        scorer = WeightedScorer(sample_optimization_result)
        breakdown = {"rsi_score": 1.0}
        scorer.score(breakdown, strategy="pullback", vix=25.0)

    def test_score_with_vix_high(self, sample_optimization_result):
        """Test scoring with VIX auto-regime (high)."""
        scorer = WeightedScorer(sample_optimization_result)
        breakdown = {"rsi_score": 1.0}
        scorer.score(breakdown, strategy="pullback", vix=35.0)

    def test_get_weight_info_no_optimization(self):
        """Test get_weight_info without optimization."""
        scorer = WeightedScorer()
        info = scorer.get_weight_info("pullback")
        assert info["status"] == "default"

    def test_get_weight_info_with_optimization(self, sample_optimization_result):
        """Test get_weight_info with optimization."""
        scorer = WeightedScorer(sample_optimization_result)
        info = scorer.get_weight_info("pullback")
        assert info["status"] == "optimized"
        assert info["strategy"] == "pullback"
        assert "top_weights" in info

    def test_load_latest_integration(self):
        """Test load_latest returns scorer."""
        with patch.object(MLWeightOptimizer, 'load_latest', return_value=None):
            scorer = WeightedScorer.load_latest()
            assert scorer._result is None

    def test_from_file_integration(self, ml_optimizer, sample_trades):
        """Test from_file loads scorer."""
        result = ml_optimizer.train(sample_trades)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "weights.json"
            ml_optimizer.save(result, str(filepath))

            scorer = WeightedScorer.from_file(str(filepath))
            assert scorer._result is not None
