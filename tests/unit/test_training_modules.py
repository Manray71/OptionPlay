# Tests for Backtesting Training Modules
# ========================================
"""
Tests for:
- optimization_methods.py (safe_correlation, analyze_components, cross_validate, etc.)
- data_prep.py (DataPrep: normalize_vix_data, segment_data_by_regime, etc.)
- performance.py (PerformanceAnalyzer: calculate_trade_metrics, classify_overfit, etc.)
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.backtesting.training.data_prep import DataPrep
from src.backtesting.training.feature_extraction import TradeFeatures
from src.backtesting.training.optimization_methods import (
    analyze_components,
    calculate_baseline_score,
    cross_validate,
    safe_correlation,
    validate_weights,
)
from src.backtesting.training.performance import PerformanceAnalyzer

# =============================================================================
# HELPERS
# =============================================================================


def make_feature(
    strategy: str = "pullback",
    components: Optional[Dict[str, float]] = None,
    is_winner: bool = True,
    pnl_percent: float = 5.0,
    signal_date: Optional[date] = None,
) -> TradeFeatures:
    """Create a TradeFeatures for testing."""
    if components is None:
        components = {"score1": 3.0, "score2": 2.0}
    if signal_date is None:
        signal_date = date(2025, 1, 1)
    return TradeFeatures(
        trade_id="test",
        symbol="AAPL",
        strategy=strategy,
        signal_date=signal_date,
        components=components,
        is_winner=is_winner,
        pnl_percent=pnl_percent,
        vix_at_signal=18.0,
        regime="normal",
        holding_days=30,
    )


def make_features(n: int, win_rate: float = 0.7) -> List[TradeFeatures]:
    """Create n features with given win rate, dates spread across 2025."""
    features = []
    for i in range(n):
        is_win = i < int(n * win_rate)
        features.append(
            make_feature(
                components={
                    "score1": float(3 + i % 5),
                    "score2": float(2 + i % 3),
                },
                is_winner=is_win,
                pnl_percent=5.0 if is_win else -3.0,
                signal_date=date(2025, 1 + (i % 12), 1 + (i % 28)),
            )
        )
    return features


# =============================================================================
# OPTIMIZATION METHODS — safe_correlation
# =============================================================================


class TestSafeCorrelation:
    """Tests for safe_correlation()."""

    def test_perfect_positive_correlation(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        assert safe_correlation(x, y) == pytest.approx(1.0, abs=1e-10)

    def test_perfect_negative_correlation(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        assert safe_correlation(x, y) == pytest.approx(-1.0, abs=1e-10)

    def test_zero_std_x_returns_zero(self):
        x = np.array([5.0, 5.0, 5.0])
        y = np.array([1.0, 2.0, 3.0])
        assert safe_correlation(x, y) == 0.0

    def test_zero_std_y_returns_zero(self):
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([5.0, 5.0, 5.0])
        assert safe_correlation(x, y) == 0.0

    def test_single_element_returns_zero(self):
        assert safe_correlation(np.array([1.0]), np.array([2.0])) == 0.0

    def test_empty_arrays_returns_zero(self):
        assert safe_correlation(np.array([]), np.array([])) == 0.0

    def test_no_correlation(self):
        np.random.seed(42)
        x = np.random.randn(1000)
        y = np.random.randn(1000)
        corr = safe_correlation(x, y)
        assert abs(corr) < 0.1  # Should be close to 0


# =============================================================================
# OPTIMIZATION METHODS — analyze_components
# =============================================================================


class TestAnalyzeComponents:
    """Tests for analyze_components()."""

    def test_empty_features(self):
        assert analyze_components([]) == {}

    def test_fewer_than_10_samples_skipped(self):
        features = [make_feature() for _ in range(9)]
        result = analyze_components(features)
        assert result == {}

    def test_exactly_10_samples_included(self):
        features = make_features(10)
        result = analyze_components(features)
        assert "score1" in result
        assert "score2" in result

    def test_result_has_required_keys(self):
        features = make_features(20)
        result = analyze_components(features)
        expected_keys = {
            "sample_size",
            "win_rate_correlation",
            "pnl_correlation",
            "avg_value_winners",
            "avg_value_losers",
            "std_value",
            "rf_importance",
            "gb_importance",
            "ensemble_importance",
            "predictive_power",
            "recommended_weight",
            "confidence_interval",
        }
        for comp_stats in result.values():
            assert set(comp_stats.keys()) == expected_keys

    def test_sample_size_correct(self):
        features = make_features(25)
        result = analyze_components(features)
        assert result["score1"]["sample_size"] == 25

    def test_all_winners(self):
        features = [
            make_feature(is_winner=True, pnl_percent=5.0, components={"s": float(i)})
            for i in range(15)
        ]
        result = analyze_components(features)
        assert result["s"]["avg_value_losers"] == 0.0
        assert result["s"]["avg_value_winners"] > 0

    def test_all_losers(self):
        features = [
            make_feature(is_winner=False, pnl_percent=-3.0, components={"s": float(i)})
            for i in range(15)
        ]
        result = analyze_components(features)
        assert result["s"]["avg_value_winners"] == 0.0
        assert result["s"]["avg_value_losers"] >= 0

    def test_predictive_power_strong(self):
        """Ensemble importance > 0.2 → strong."""
        # Create features where score perfectly predicts outcome
        features = []
        for i in range(20):
            is_win = i >= 10
            features.append(
                make_feature(
                    components={"s": 10.0 if is_win else 0.0},
                    is_winner=is_win,
                    pnl_percent=10.0 if is_win else -10.0,
                )
            )
        result = analyze_components(features)
        # High correlation → high ensemble importance → strong
        assert result["s"]["predictive_power"] == "strong"

    def test_predictive_power_none(self):
        """Ensemble importance ≤ 0.05 → none."""
        # All same component value → zero std → zero correlation → none
        features = [
            make_feature(
                components={"s": 5.0},
                is_winner=(i % 2 == 0),
                pnl_percent=1.0 if i % 2 == 0 else -1.0,
            )
            for i in range(20)
        ]
        result = analyze_components(features)
        assert result["s"]["predictive_power"] == "none"

    def test_confidence_interval_is_tuple(self):
        features = make_features(20)
        result = analyze_components(features)
        for comp_stats in result.values():
            ci = comp_stats["confidence_interval"]
            assert isinstance(ci, tuple)
            assert len(ci) == 2
            assert ci[0] <= ci[1]


# =============================================================================
# OPTIMIZATION METHODS — cross_validate
# =============================================================================


class TestCrossValidate:
    """Tests for cross_validate()."""

    def test_fewer_than_20_features_returns_zero(self):
        features = make_features(19)
        assert cross_validate(features, {"score1": 1.0}) == 0.0

    def test_empty_features_returns_zero(self):
        assert cross_validate([], {"score1": 1.0}) == 0.0

    def test_returns_value_between_0_and_1(self):
        features = make_features(50)
        result = cross_validate(features, {"score1": 1.0, "score2": 1.0})
        assert 0.0 <= result <= 1.0

    def test_with_20_features_runs(self):
        features = make_features(20)
        result = cross_validate(features, {"score1": 1.0})
        assert isinstance(result, float)

    def test_custom_folds(self):
        features = make_features(30)
        result = cross_validate(features, {"score1": 1.0}, cv_folds=3)
        assert 0.0 <= result <= 1.0


# =============================================================================
# OPTIMIZATION METHODS — calculate_baseline_score
# =============================================================================


class TestCalculateBaselineScore:
    """Tests for calculate_baseline_score()."""

    def test_empty_features(self):
        assert calculate_baseline_score([]) == 0.0

    def test_returns_value_between_0_and_1(self):
        features = make_features(30)
        result = calculate_baseline_score(features)
        assert 0.0 <= result <= 1.0

    def test_single_feature(self):
        features = [make_feature()]
        # With single feature, score == median, so score > median is False.
        # is_winner is True → mismatch → correct=0
        result = calculate_baseline_score(features)
        assert result == 0.0


# =============================================================================
# OPTIMIZATION METHODS — validate_weights
# =============================================================================


class TestValidateWeights:
    """Tests for validate_weights()."""

    def test_empty_features(self):
        assert validate_weights([], {}) == 0.0

    def test_no_matching_strategies(self):
        features = make_features(10)  # strategy="pullback"
        mock_config = MagicMock()
        result = validate_weights(features, {"bounce": mock_config})
        assert result == 0.0

    def test_matching_strategy(self):
        features = make_features(20)
        mock_config = MagicMock()
        mock_config.apply_weights.side_effect = lambda c: sum(c.values())
        result = validate_weights(features, {"pullback": mock_config})
        assert 0.0 <= result <= 1.0

    def test_multiple_strategies(self):
        features = make_features(10, win_rate=0.6) + [
            make_feature(strategy="bounce", signal_date=date(2025, 1, i + 1)) for i in range(10)
        ]
        mock_config = MagicMock()
        mock_config.apply_weights.side_effect = lambda c: sum(c.values())
        result = validate_weights(features, {"pullback": mock_config, "bounce": mock_config})
        assert 0.0 <= result <= 1.0


# =============================================================================
# DATA PREP — normalize_vix_data
# =============================================================================


class TestNormalizeVixData:
    """Tests for DataPrep.normalize_vix_data()."""

    @pytest.fixture
    def prep(self):
        return DataPrep()

    def test_empty_data(self, prep):
        assert prep.normalize_vix_data([]) == {}

    def test_string_dates(self, prep):
        data = [{"date": "2025-01-15", "value": 18.5}]
        result = prep.normalize_vix_data(data)
        assert result == {date(2025, 1, 15): 18.5}

    def test_date_objects(self, prep):
        data = [{"date": date(2025, 3, 1), "value": 20.0}]
        result = prep.normalize_vix_data(data)
        assert result == {date(2025, 3, 1): 20.0}

    def test_close_key_fallback(self, prep):
        data = [{"date": "2025-01-01", "close": 15.0}]
        result = prep.normalize_vix_data(data)
        assert result[date(2025, 1, 1)] == 15.0

    def test_missing_date_skipped(self, prep):
        data = [{"value": 18.0}]
        result = prep.normalize_vix_data(data)
        assert result == {}

    def test_missing_value_skipped(self, prep):
        data = [{"date": "2025-01-01"}]
        result = prep.normalize_vix_data(data)
        assert result == {}

    def test_multiple_entries(self, prep):
        data = [
            {"date": "2025-01-01", "value": 15.0},
            {"date": "2025-01-02", "value": 16.0},
            {"date": "2025-01-03", "value": 17.0},
        ]
        result = prep.normalize_vix_data(data)
        assert len(result) == 3

    def test_value_converted_to_float(self, prep):
        data = [{"date": "2025-01-01", "value": "18.5"}]
        result = prep.normalize_vix_data(data)
        assert result[date(2025, 1, 1)] == 18.5
        assert isinstance(result[date(2025, 1, 1)], float)


# =============================================================================
# DATA PREP — generate_trade_opportunities
# =============================================================================


class TestGenerateTradeOpportunities:
    """Tests for DataPrep.generate_trade_opportunities()."""

    @pytest.fixture
    def prep(self):
        return DataPrep()

    def test_empty_dates(self, prep):
        result = prep.generate_trade_opportunities(
            regime_dates=set(),
            historical_data={"AAPL": [{"date": "2025-01-01", "close": 150}]},
            symbols=["AAPL"],
        )
        assert result == []

    def test_empty_symbols(self, prep):
        result = prep.generate_trade_opportunities(
            regime_dates={date(2025, 1, 1)},
            historical_data={"AAPL": [{"date": "2025-01-01", "close": 150}]},
            symbols=[],
        )
        assert result == []

    def test_symbol_not_in_data(self, prep):
        result = prep.generate_trade_opportunities(
            regime_dates={date(2025, 1, 1)},
            historical_data={},
            symbols=["AAPL"],
        )
        assert result == []

    def test_basic_opportunity_generation(self, prep):
        result = prep.generate_trade_opportunities(
            regime_dates={date(2025, 1, 1)},
            historical_data={"AAPL": [{"date": "2025-01-01", "close": 150.0, "volume": 1000000}]},
            symbols=["AAPL"],
        )
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["price"] == 150.0
        assert result[0]["volume"] == 1000000

    def test_date_not_in_bars(self, prep):
        """Date in regime_dates but not in historical_data bars."""
        result = prep.generate_trade_opportunities(
            regime_dates={date(2025, 1, 2)},
            historical_data={"AAPL": [{"date": "2025-01-01", "close": 150}]},
            symbols=["AAPL"],
        )
        assert result == []

    def test_multiple_symbols(self, prep):
        result = prep.generate_trade_opportunities(
            regime_dates={date(2025, 1, 1)},
            historical_data={
                "AAPL": [{"date": "2025-01-01", "close": 150, "volume": 100}],
                "MSFT": [{"date": "2025-01-01", "close": 350, "volume": 200}],
            },
            symbols=["AAPL", "MSFT"],
        )
        assert len(result) == 2

    def test_missing_close_defaults_to_zero(self, prep):
        result = prep.generate_trade_opportunities(
            regime_dates={date(2025, 1, 1)},
            historical_data={"AAPL": [{"date": "2025-01-01"}]},
            symbols=["AAPL"],
        )
        assert result[0]["price"] == 0
        assert result[0]["volume"] == 0


# =============================================================================
# DATA PREP — segment_data_by_regime
# =============================================================================


class TestSegmentDataByRegime:
    """Tests for DataPrep.segment_data_by_regime()."""

    @pytest.fixture
    def prep(self):
        return DataPrep()

    @patch("src.backtesting.training.data_prep.get_regime_for_vix")
    def test_empty_data(self, mock_regime, prep):
        mock_regime.return_value = ("normal", MagicMock())
        regimes = {"normal": MagicMock(), "elevated": MagicMock()}
        result = prep.segment_data_by_regime(
            historical_data={},
            vix_by_date={},
            regimes=regimes,
            symbols=[],
        )
        assert "normal" in result
        assert "elevated" in result
        assert result["normal"]["dates"] == []

    @patch("src.backtesting.training.data_prep.get_regime_for_vix")
    def test_basic_segmentation(self, mock_regime, prep):
        mock_regime.return_value = ("normal", MagicMock())
        d1 = date(2025, 1, 1)
        regimes = {"normal": MagicMock()}
        result = prep.segment_data_by_regime(
            historical_data={"AAPL": [{"date": d1, "close": 150, "volume": 100}]},
            vix_by_date={d1: 18.0},
            regimes=regimes,
            symbols=["AAPL"],
        )
        assert d1 in result["normal"]["dates"]
        assert 18.0 in result["normal"]["vix_values"]
        assert len(result["normal"]["trades"]) >= 1


# =============================================================================
# PERFORMANCE ANALYZER — calculate_trade_metrics
# =============================================================================


class TestCalculateTradeMetrics:
    """Tests for PerformanceAnalyzer.calculate_trade_metrics()."""

    @pytest.fixture
    def analyzer(self):
        return PerformanceAnalyzer()

    def test_empty_trades(self, analyzer):
        result = analyzer.calculate_trade_metrics([])
        assert result["win_rate"] == 0
        assert result["total_pnl"] == 0
        assert result["avg_pnl"] == 0
        assert result["sharpe"] == 0
        assert result["profit_factor"] == 0

    def test_single_winner(self, analyzer):
        result = analyzer.calculate_trade_metrics([{"pnl": 100}])
        assert result["win_rate"] == 100.0
        assert result["total_pnl"] == 100
        assert result["avg_pnl"] == 100
        assert result["sharpe"] == 0  # Need >1 for stdev
        assert result["profit_factor"] == 0  # No losers → gross_loss=0 → 0

    def test_single_loser(self, analyzer):
        result = analyzer.calculate_trade_metrics([{"pnl": -50}])
        assert result["win_rate"] == 0.0
        assert result["total_pnl"] == -50
        assert result["sharpe"] == 0

    def test_mixed_trades(self, analyzer):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -30}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["win_rate"] == pytest.approx(66.67, abs=0.1)
        assert result["total_pnl"] == 120
        assert result["avg_pnl"] == 40.0
        assert result["profit_factor"] == pytest.approx(150 / 30, abs=0.01)

    def test_all_winners(self, analyzer):
        trades = [{"pnl": 100}, {"pnl": 200}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["win_rate"] == 100.0
        assert result["profit_factor"] == 0  # No losers

    def test_all_losers(self, analyzer):
        trades = [{"pnl": -100}, {"pnl": -200}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["win_rate"] == 0.0
        assert result["total_pnl"] == -300

    def test_sharpe_ratio_calculation(self, analyzer):
        trades = [{"pnl": 10}, {"pnl": 20}, {"pnl": -5}, {"pnl": 15}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["sharpe"] != 0
        # Positive avg PnL → positive sharpe
        assert result["sharpe"] > 0

    def test_negative_sharpe(self, analyzer):
        trades = [{"pnl": -10}, {"pnl": -20}, {"pnl": 5}, {"pnl": -15}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["sharpe"] < 0

    def test_zero_pnl_trades(self, analyzer):
        trades = [{"pnl": 0}, {"pnl": 0}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["win_rate"] == 0.0  # pnl=0 is neither winner nor loser
        assert result["sharpe"] == 0  # std=0

    def test_missing_pnl_key(self, analyzer):
        trades = [{"symbol": "AAPL"}, {"pnl": 100}]
        result = analyzer.calculate_trade_metrics(trades)
        assert result["total_pnl"] == 100
        assert result["win_rate"] == 50.0


# =============================================================================
# PERFORMANCE ANALYZER — analyze_strategy_performance
# =============================================================================


class TestAnalyzeStrategyPerformance:
    """Tests for PerformanceAnalyzer.analyze_strategy_performance()."""

    @pytest.fixture
    def analyzer(self):
        return PerformanceAnalyzer()

    @pytest.fixture
    def config(self):
        from src.backtesting.models.training_models import RegimeTrainingConfig

        return RegimeTrainingConfig()

    def test_empty_strategy_trades(self, analyzer, config):
        result = analyzer.analyze_strategy_performance({}, "normal", config)
        assert result == {}

    def test_strategy_with_no_epochs(self, analyzer, config):
        result = analyzer.analyze_strategy_performance({"pullback": []}, "normal", config)
        assert "pullback" not in result

    def test_basic_strategy_performance(self, analyzer, config):
        strategy_trades = {
            "pullback": [
                {"trades": 50, "win_rate": 65.0},
                {"trades": 45, "win_rate": 68.0},
            ]
        }
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert "pullback" in result
        perf = result["pullback"]
        assert perf.strategy == "pullback"
        assert perf.regime == "normal"
        assert perf.total_trades == 95
        assert perf.win_rate == pytest.approx(66.5, abs=0.1)
        assert perf.should_enable is True  # 66.5 >= 45.0 threshold

    def test_should_disable_low_win_rate(self, analyzer, config):
        strategy_trades = {
            "pullback": [
                {"trades": 30, "win_rate": 40.0},
                {"trades": 20, "win_rate": 42.0},
            ]
        }
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert result["pullback"].should_enable is False  # 41.0 < 45.0

    def test_confidence_high(self, analyzer, config):
        strategy_trades = {"pullback": [{"trades": 100, "win_rate": 70.0}]}
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert result["pullback"].confidence == "high"

    def test_confidence_medium(self, analyzer, config):
        strategy_trades = {"pullback": [{"trades": 50, "win_rate": 70.0}]}
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert result["pullback"].confidence == "medium"

    def test_confidence_low(self, analyzer, config):
        strategy_trades = {"pullback": [{"trades": 30, "win_rate": 70.0}]}
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert result["pullback"].confidence == "low"

    def test_confidence_boundary_50(self, analyzer, config):
        """50 trades → medium (>= 50)."""
        strategy_trades = {"pullback": [{"trades": 50, "win_rate": 60.0}]}
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert result["pullback"].confidence == "medium"

    def test_confidence_boundary_100(self, analyzer, config):
        """100 trades → high (>= 100)."""
        strategy_trades = {"pullback": [{"trades": 100, "win_rate": 60.0}]}
        result = analyzer.analyze_strategy_performance(strategy_trades, "normal", config)
        assert result["pullback"].confidence == "high"

    def test_multiple_strategies(self, analyzer, config):
        strategy_trades = {
            "pullback": [{"trades": 60, "win_rate": 70.0}],
            "bounce": [{"trades": 40, "win_rate": 50.0}],
        }
        result = analyzer.analyze_strategy_performance(strategy_trades, "elevated", config)
        assert len(result) == 2
        assert result["pullback"].regime == "elevated"
        assert result["bounce"].regime == "elevated"


# =============================================================================
# PERFORMANCE ANALYZER — classify_overfit
# =============================================================================


class TestClassifyOverfit:
    """Tests for PerformanceAnalyzer.classify_overfit()."""

    @pytest.fixture
    def analyzer(self):
        return PerformanceAnalyzer()

    def test_zero_degradation(self, analyzer):
        assert analyzer.classify_overfit(0.0) == "none"

    def test_none_threshold(self, analyzer):
        assert analyzer.classify_overfit(4.9) == "none"

    def test_mild_threshold(self, analyzer):
        assert analyzer.classify_overfit(5.0) == "mild"
        assert analyzer.classify_overfit(9.9) == "mild"

    def test_moderate_threshold(self, analyzer):
        assert analyzer.classify_overfit(10.0) == "moderate"
        assert analyzer.classify_overfit(14.9) == "moderate"

    def test_severe_threshold(self, analyzer):
        assert analyzer.classify_overfit(15.0) == "severe"
        assert analyzer.classify_overfit(100.0) == "severe"

    def test_negative_degradation_uses_abs(self, analyzer):
        assert analyzer.classify_overfit(-7.5) == "mild"
        assert analyzer.classify_overfit(-3.0) == "none"
        assert analyzer.classify_overfit(-12.0) == "moderate"
        assert analyzer.classify_overfit(-20.0) == "severe"

    def test_exact_boundaries(self, analyzer):
        # Boundaries: none<5, mild<10, moderate<15, severe>=15
        assert analyzer.classify_overfit(4.999) == "none"
        assert analyzer.classify_overfit(5.001) == "mild"
        assert analyzer.classify_overfit(9.999) == "mild"
        assert analyzer.classify_overfit(10.001) == "moderate"
        assert analyzer.classify_overfit(14.999) == "moderate"
        assert analyzer.classify_overfit(15.001) == "severe"
