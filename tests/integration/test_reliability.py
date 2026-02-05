#!/usr/bin/env python3
"""
Tests für Reliability Scoring Module

Testet:
- ReliabilityScorer Initialisierung
- Score-Berechnung
- Grade-Bestimmung
- Regime-Adjustments
- Komponenten-Analyse
- Batch-Scoring
"""

import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backtesting.reliability import (
    ReliabilityScorer,
    ReliabilityResult,
    ScorerConfig,
    create_scorer_from_latest_model,
    format_reliability_badge,
)
from src.backtesting.walk_forward import (
    TrainingConfig,
    TrainingResult,
)
from src.backtesting.signal_validation import (
    SignalValidationResult,
    ScoreBucketStats,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_config():
    """Standard Scorer-Konfiguration"""
    return ScorerConfig(
        min_grade_for_trade="C",
        min_score=5.0,
        min_sample_size=20,
    )


@pytest.fixture
def sample_training_result():
    """Sample TrainingResult"""
    config = TrainingConfig(
        train_months=12,
        test_months=3,
        min_trades_per_epoch=30,
    )

    return TrainingResult(
        training_id="test_training",
        training_date=datetime.now(),
        config=config,
        epochs=[],
        valid_epochs=4,
        total_epochs=5,
        avg_in_sample_win_rate=68.0,
        avg_in_sample_sharpe=1.6,
        avg_out_sample_win_rate=62.0,
        avg_out_sample_sharpe=1.3,
        avg_win_rate_degradation=6.0,
        max_win_rate_degradation=10.0,
        overfit_severity="mild",
        recommended_min_score=7.0,
        top_predictors=["rsi_score", "support_score", "fibonacci_score"],
        component_weights={
            "rsi_score": 0.4,
            "support_score": 0.35,
            "fibonacci_score": 0.25,
        },
        regime_adjustments={
            "low_vol": {"win_rate_adjustment": 5.0},
            "normal": {"win_rate_adjustment": 0.0},
            "elevated": {"win_rate_adjustment": -3.0},
            "high_vol": {"win_rate_adjustment": -8.0},
        },
    )


@pytest.fixture
def sample_validation_result():
    """Sample SignalValidationResult"""
    buckets = [
        ScoreBucketStats(
            bucket_range=(5, 7),
            bucket_label="5-7",
            trade_count=50,
            win_count=27,
            loss_count=23,
            win_rate=54.0,
            avg_pnl=20.0,
            median_pnl=15.0,
            std_pnl=100.0,
            sharpe_ratio=0.8,
            profit_factor=1.2,
            max_win=200.0,
            max_loss=-150.0,
            avg_hold_days=30,
            confidence_interval=(40.0, 68.0),
            is_statistically_significant=True,
        ),
        ScoreBucketStats(
            bucket_range=(7, 9),
            bucket_label="7-9",
            trade_count=80,
            win_count=52,
            loss_count=28,
            win_rate=65.0,
            avg_pnl=45.0,
            median_pnl=40.0,
            std_pnl=90.0,
            sharpe_ratio=1.3,
            profit_factor=1.8,
            max_win=250.0,
            max_loss=-120.0,
            avg_hold_days=28,
            confidence_interval=(54.0, 75.0),
            is_statistically_significant=True,
        ),
        ScoreBucketStats(
            bucket_range=(9, 11),
            bucket_label="9-11",
            trade_count=40,
            win_count=30,
            loss_count=10,
            win_rate=75.0,
            avg_pnl=65.0,
            median_pnl=60.0,
            std_pnl=80.0,
            sharpe_ratio=1.8,
            profit_factor=2.5,
            max_win=300.0,
            max_loss=-80.0,
            avg_hold_days=25,
            confidence_interval=(60.0, 86.0),
            is_statistically_significant=True,
        ),
    ]

    return SignalValidationResult(
        analysis_date=date.today(),
        total_trades_analyzed=170,
        trades_with_scores=170,
        date_range=(date(2022, 1, 1), date(2023, 12, 31)),
        score_coverage=100.0,
        score_buckets=buckets,
        optimal_threshold=7.0,
        component_correlations=[],
        top_predictors=["rsi_score", "support_score"],
        regime_buckets={},
        regime_sensitivity={},
        overall_win_rate=64.0,
        overall_sharpe=1.3,
        score_effectiveness=0.25,
    )


@pytest.fixture
def sample_score_breakdown():
    """Sample Score Breakdown Dict"""
    return {
        "components": {
            "rsi": {"score": 1.5, "value": 35.0},
            "support": {"score": 2.5, "level": 145.0},
            "fibonacci": {"score": 1.5, "level": "38.2%"},
            "ma": {"score": 2.0},
            "trend_strength": {"score": 1.5},
            "volume": {"score": 0.5},
            "macd": {"score": 1.0},
            "stoch": {"score": 0.5},
            "keltner": {"score": 1.0},
        }
    }


# =============================================================================
# ReliabilityResult Tests
# =============================================================================

class TestReliabilityResult:
    """Tests für ReliabilityResult"""

    def test_default_values(self):
        """Test Default-Werte"""
        result = ReliabilityResult(score=8.0)

        assert result.score == 8.0
        assert result.should_trade is False
        assert result.grade == "F"
        assert result.historical_win_rate == 0.0

    def test_to_dict(self):
        """Test Dictionary-Konvertierung"""
        result = ReliabilityResult(
            score=8.5,
            should_trade=True,
            grade="B",
            historical_win_rate=65.0,
            confidence_interval=(55.0, 75.0),
            sample_size=100,
            vix=18.0,
            regime="normal",
        )

        d = result.to_dict()

        assert d["score"] == 8.5
        assert d["recommendation"]["should_trade"] is True
        assert d["recommendation"]["grade"] == "B"
        assert d["historical_performance"]["win_rate"] == 65.0

    def test_summary(self):
        """Test Summary-Formatierung"""
        result = ReliabilityResult(
            score=8.5,
            should_trade=True,
            grade="B",
            historical_win_rate=65.0,
            confidence_interval=(55.0, 75.0),
            sample_size=100,
            regime="normal",
        )

        summary = result.summary()

        assert "✓" in summary
        assert "Grade: B" in summary
        assert "65%" in summary

    def test_summary_rejected(self):
        """Test Summary für abgelehnten Trade"""
        result = ReliabilityResult(
            score=4.0,
            should_trade=False,
            grade="F",
            rejection_reason="Score unter Minimum",
            historical_win_rate=45.0,
            confidence_interval=(30.0, 60.0),
            sample_size=50,
        )

        summary = result.summary()

        assert "✗" in summary
        assert "Score unter Minimum" in summary


# =============================================================================
# ScorerConfig Tests
# =============================================================================

class TestScorerConfig:
    """Tests für ScorerConfig"""

    def test_default_values(self):
        """Test Default-Werte"""
        config = ScorerConfig()

        assert config.min_grade_for_trade == "C"
        assert config.min_score == 5.0
        assert config.min_sample_size == 30
        assert "A" in config.grade_thresholds

    def test_custom_values(self, sample_config):
        """Test Custom-Werte"""
        assert sample_config.min_sample_size == 20

    def test_to_dict(self):
        """Test Dictionary-Konvertierung"""
        config = ScorerConfig()
        d = config.to_dict()

        assert "grade_thresholds" in d
        assert "min_grade_for_trade" in d


# =============================================================================
# ReliabilityScorer Basic Tests
# =============================================================================

class TestReliabilityScorerBasic:
    """Basis-Tests für ReliabilityScorer"""

    def test_init_default(self):
        """Test Default-Initialisierung"""
        scorer = ReliabilityScorer()

        assert scorer.config is not None
        assert scorer._training_result is None
        assert scorer._validation_result is None

    def test_init_with_config(self, sample_config):
        """Test mit Custom Config"""
        scorer = ReliabilityScorer(config=sample_config)

        assert scorer.config.min_sample_size == 20

    def test_init_with_training(self, sample_config, sample_training_result):
        """Test mit Training-Result"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        assert scorer._training_result is not None
        assert scorer._recommended_min_score == 7.0
        assert "rsi_score" in scorer._component_weights

    def test_init_with_validation(self, sample_config, sample_validation_result):
        """Test mit Validation-Result"""
        scorer = ReliabilityScorer(
            config=sample_config,
            validation_result=sample_validation_result,
        )

        assert scorer._validation_result is not None


# =============================================================================
# Score Method Tests
# =============================================================================

class TestScore:
    """Tests für score() Methode"""

    def test_score_below_minimum(self, sample_config, sample_training_result):
        """Test mit Score unter Minimum"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=4.0)

        assert result.should_trade is False
        assert result.grade == "F"
        assert "unter Minimum" in result.rejection_reason

    def test_score_above_minimum(self, sample_config, sample_training_result):
        """Test mit Score über Minimum"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0)

        assert result.score == 8.0
        assert result.historical_win_rate > 0
        assert result.sample_size > 0

    def test_score_with_vix(self, sample_config, sample_training_result):
        """Test mit VIX-Regime"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        # Low Vol Regime (sollte positives Adjustment haben)
        result = scorer.score(pullback_score=8.0, vix=12.0)

        assert result.vix == 12.0
        assert result.regime == "low_vol"
        assert result.regime_adjustment == 5.0

    def test_score_high_vol_regime(self, sample_config, sample_training_result):
        """Test mit High Vol Regime"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0, vix=35.0)

        assert result.regime == "high_vol"
        assert result.regime_adjustment < 0

    def test_score_with_breakdown(
        self, sample_config, sample_training_result, sample_score_breakdown
    ):
        """Test mit Score Breakdown"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(
            pullback_score=8.0,
            score_breakdown=sample_score_breakdown,
        )

        assert len(result.component_strengths) > 0
        assert isinstance(result.weak_components, list)
        assert isinstance(result.strong_components, list)


# =============================================================================
# Grade Determination Tests
# =============================================================================

class TestGradeDetermination:
    """Tests für Grade-Bestimmung"""

    def test_determine_grade_a(self, sample_config):
        """Test Grade A"""
        scorer = ReliabilityScorer(config=sample_config)

        grade = scorer._determine_grade(ci_lower=75.0, sample_size=100)

        assert grade == "A"

    def test_determine_grade_b(self, sample_config):
        """Test Grade B"""
        scorer = ReliabilityScorer(config=sample_config)

        grade = scorer._determine_grade(ci_lower=65.0, sample_size=100)

        assert grade == "B"

    def test_determine_grade_c(self, sample_config):
        """Test Grade C"""
        scorer = ReliabilityScorer(config=sample_config)

        grade = scorer._determine_grade(ci_lower=55.0, sample_size=100)

        assert grade == "C"

    def test_determine_grade_d(self, sample_config):
        """Test Grade D"""
        scorer = ReliabilityScorer(config=sample_config)

        grade = scorer._determine_grade(ci_lower=45.0, sample_size=100)

        assert grade == "D"

    def test_determine_grade_f(self, sample_config):
        """Test Grade F"""
        scorer = ReliabilityScorer(config=sample_config)

        grade = scorer._determine_grade(ci_lower=35.0, sample_size=100)

        assert grade == "F"

    def test_determine_grade_insufficient_samples(self, sample_config):
        """Test Grade F bei zu wenig Samples"""
        scorer = ReliabilityScorer(config=sample_config)

        grade = scorer._determine_grade(ci_lower=75.0, sample_size=5)

        assert grade == "F"


# =============================================================================
# Regime Tests
# =============================================================================

class TestRegime:
    """Tests für Regime-Handling"""

    def test_get_regime_low_vol(self, sample_config):
        """Test Low Vol Regime"""
        scorer = ReliabilityScorer(config=sample_config)

        assert scorer._get_regime(12.0) == "low_vol"
        assert scorer._get_regime(14.9) == "low_vol"

    def test_get_regime_normal(self, sample_config):
        """Test Normal Regime"""
        scorer = ReliabilityScorer(config=sample_config)

        assert scorer._get_regime(15.0) == "normal"
        assert scorer._get_regime(19.9) == "normal"

    def test_get_regime_elevated(self, sample_config):
        """Test Elevated Regime"""
        scorer = ReliabilityScorer(config=sample_config)

        assert scorer._get_regime(20.0) == "elevated"
        assert scorer._get_regime(29.9) == "elevated"

    def test_get_regime_high_vol(self, sample_config):
        """Test High Vol Regime"""
        scorer = ReliabilityScorer(config=sample_config)

        assert scorer._get_regime(30.0) == "high_vol"
        assert scorer._get_regime(50.0) == "high_vol"


# =============================================================================
# Component Analysis Tests
# =============================================================================

class TestComponentAnalysis:
    """Tests für Komponenten-Analyse"""

    def test_analyze_components_basic(
        self, sample_config, sample_score_breakdown
    ):
        """Test Basis-Analyse"""
        scorer = ReliabilityScorer(config=sample_config)

        strengths, weak, strong = scorer._analyze_components(sample_score_breakdown)

        assert "rsi" in strengths
        assert "support" in strengths
        assert isinstance(weak, list)
        assert isinstance(strong, list)

    def test_analyze_components_strong(self, sample_config):
        """Test starke Komponenten"""
        scorer = ReliabilityScorer(config=sample_config)

        breakdown = {
            "components": {
                "rsi": {"score": 2.0},  # Max = 2.0
                "support": {"score": 3.0},  # Max = 3.0
            }
        }

        strengths, weak, strong = scorer._analyze_components(breakdown)

        assert strengths["rsi"] == "strong"
        assert strengths["support"] == "strong"
        assert "rsi" in strong
        assert "support" in strong

    def test_analyze_components_weak(self, sample_config):
        """Test schwache Komponenten"""
        scorer = ReliabilityScorer(config=sample_config)

        breakdown = {
            "components": {
                "rsi": {"score": 0.5},  # < 50% of max
                "support": {"score": 0.5},
            }
        }

        strengths, weak, strong = scorer._analyze_components(breakdown)

        assert strengths["rsi"] == "weak"
        assert "rsi" in weak


# =============================================================================
# Batch Scoring Tests
# =============================================================================

class TestBatchScoring:
    """Tests für Batch-Scoring"""

    def test_score_batch(self, sample_config, sample_training_result):
        """Test Batch-Scoring"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        candidates = [
            {"symbol": "AAPL", "score": 9.0},
            {"symbol": "MSFT", "score": 7.5},
            {"symbol": "GOOGL", "score": 4.0},  # Unter Minimum
        ]

        results = scorer.score_batch(candidates, vix=18.0)

        assert len(results) == 3

        # Sortierung: tradeable first
        first_candidate, first_result = results[0]
        assert first_result.should_trade is True

    def test_score_batch_with_breakdown(
        self, sample_config, sample_training_result, sample_score_breakdown
    ):
        """Test Batch-Scoring mit Breakdown"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        candidates = [
            {"symbol": "AAPL", "score": 8.5, "score_breakdown": sample_score_breakdown},
        ]

        results = scorer.score_batch(candidates)

        _, result = results[0]
        assert len(result.component_strengths) > 0

    def test_get_recommendation_summary(
        self, sample_config, sample_training_result
    ):
        """Test Empfehlungs-Summary"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        candidates = [
            {"symbol": "AAPL", "score": 9.0},
            {"symbol": "MSFT", "score": 8.0},
            {"symbol": "LOW", "score": 3.0},
        ]

        results = scorer.score_batch(candidates)
        summary = scorer.get_recommendation_summary(results)

        assert "RELIABILITY ASSESSMENT" in summary
        assert "EMPFOHLEN" in summary or "ABGELEHNT" in summary


# =============================================================================
# Factory Method Tests
# =============================================================================

class TestFactoryMethods:
    """Tests für Factory-Methoden"""

    def test_from_trained_model_not_found(self, sample_config):
        """Test mit nicht existierendem Modell"""
        scorer = ReliabilityScorer.from_trained_model(
            "/nonexistent/path/model.json",
            config=sample_config,
        )

        # Sollte ohne Fehler funktionieren, aber ohne Trainingsdaten
        assert scorer._training_result is None

    def test_from_trained_model_exists(
        self, sample_config, sample_training_result
    ):
        """Test mit existierendem Modell"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Speichere Test-Modell
            model_path = f"{tmpdir}/test_model.json"

            with open(model_path, "w") as f:
                json.dump(sample_training_result.to_dict(), f)

            scorer = ReliabilityScorer.from_trained_model(
                model_path,
                config=sample_config,
            )

            assert scorer._training_result is not None


# =============================================================================
# Utility Function Tests
# =============================================================================

class TestUtilityFunctions:
    """Tests für Utility-Funktionen"""

    def test_format_reliability_badge(self):
        """Test Badge-Formatierung"""
        result = ReliabilityResult(
            score=8.0,
            grade="B",
            historical_win_rate=65.0,
            confidence_interval=(55.0, 75.0),
        )

        badge = format_reliability_badge(result)

        assert "[B]" in badge
        assert "65%" in badge

    def test_create_scorer_from_latest_model_no_dir(self):
        """Test mit nicht existierendem Verzeichnis"""
        scorer = create_scorer_from_latest_model("/nonexistent/path")

        assert scorer is not None
        assert scorer._training_result is None


# =============================================================================
# Overfit Warning Tests
# =============================================================================

class TestOverfitWarnings:
    """Tests für Overfit-Warnungen"""

    def test_mild_overfit_no_warning(self, sample_config, sample_training_result):
        """Test: Mild Overfit = keine Blockierung"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0)

        # Mild sollte nicht blockieren (default max = moderate)
        assert result.overfit_severity == "mild"
        # Kann trotzdem traden wenn andere Kriterien erfüllt

    def test_severe_overfit_blocks(self, sample_config):
        """Test: Severe Overfit blockiert Trade"""
        training = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=TrainingConfig(),
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=75.0,
            avg_in_sample_sharpe=2.0,
            avg_out_sample_win_rate=45.0,
            avg_out_sample_sharpe=0.5,
            avg_win_rate_degradation=30.0,
            max_win_rate_degradation=35.0,
            overfit_severity="severe",
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=training,
        )

        result = scorer.score(pullback_score=9.0)

        assert result.should_trade is False
        assert "Overfitting" in result.rejection_reason


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge Cases und Fehlerbehandlung"""

    def test_score_no_training_no_validation(self, sample_config):
        """Test ohne Training und Validation"""
        scorer = ReliabilityScorer(config=sample_config)

        result = scorer.score(pullback_score=8.0)

        # Sollte Default-Werte verwenden
        assert result.historical_win_rate == 50.0
        assert result.sample_size == 0

    def test_empty_score_breakdown(self, sample_config, sample_training_result):
        """Test mit leerem Breakdown"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0, score_breakdown={})

        # Sollte funktionieren, aber keine Komponenten
        assert result.component_strengths == {}

    def test_validation_bucket_lookup(
        self, sample_config, sample_validation_result
    ):
        """Test Bucket-Lookup aus Validation"""
        scorer = ReliabilityScorer(
            config=sample_config,
            validation_result=sample_validation_result,
        )

        # Score im 7-9 Bucket
        result = scorer.score(pullback_score=8.0)

        assert result.historical_win_rate == 65.0  # Aus Bucket
        assert result.sample_size == 80

    def test_validation_fallback_to_overall(
        self, sample_config, sample_validation_result
    ):
        """Test Fallback auf Overall Win Rate"""
        scorer = ReliabilityScorer(
            config=sample_config,
            validation_result=sample_validation_result,
        )

        # Score außerhalb aller Buckets
        result = scorer.score(pullback_score=12.0)

        assert result.historical_win_rate == 64.0  # Overall Rate

    def test_confidence_interval_zero_samples(self, sample_config):
        """Test CI mit 0 Samples"""
        scorer = ReliabilityScorer(config=sample_config)

        ci_low, ci_high = scorer._calculate_confidence_interval(50.0, 0)

        assert ci_low == 0.0
        assert ci_high == 100.0


# =============================================================================
# Confidence Interval Tests (Extended)
# =============================================================================

class TestConfidenceIntervals:
    """Erweiterte Tests fuer Confidence Interval Berechnung"""

    def test_ci_high_win_rate(self, sample_config):
        """Test CI bei hoher Win Rate"""
        scorer = ReliabilityScorer(config=sample_config)

        # 80% win rate with 100 samples
        ci_low, ci_high = scorer._calculate_confidence_interval(80.0, 100)

        # CI should be around 70-88%
        assert 65 < ci_low < 80
        assert 80 < ci_high < 95

    def test_ci_low_win_rate(self, sample_config):
        """Test CI bei niedriger Win Rate"""
        scorer = ReliabilityScorer(config=sample_config)

        # 30% win rate with 100 samples
        ci_low, ci_high = scorer._calculate_confidence_interval(30.0, 100)

        # CI should be around 21-40%
        assert 15 < ci_low < 35
        assert 30 < ci_high < 50

    def test_ci_small_sample_wide_interval(self, sample_config):
        """Test CI breiter bei kleiner Stichprobe"""
        scorer = ReliabilityScorer(config=sample_config)

        # Same win rate, different sample sizes
        ci_small_low, ci_small_high = scorer._calculate_confidence_interval(60.0, 20)
        ci_large_low, ci_large_high = scorer._calculate_confidence_interval(60.0, 200)

        # Smaller sample should have wider interval
        small_width = ci_small_high - ci_small_low
        large_width = ci_large_high - ci_large_low

        assert small_width > large_width

    def test_ci_extreme_win_rate_100(self, sample_config):
        """Test CI bei 100% Win Rate"""
        scorer = ReliabilityScorer(config=sample_config)

        ci_low, ci_high = scorer._calculate_confidence_interval(100.0, 50)

        # Should still have reasonable bounds
        assert ci_low > 85
        assert ci_high <= 100

    def test_ci_extreme_win_rate_0(self, sample_config):
        """Test CI bei 0% Win Rate"""
        scorer = ReliabilityScorer(config=sample_config)

        ci_low, ci_high = scorer._calculate_confidence_interval(0.0, 50)

        # Should still have reasonable bounds
        assert ci_low >= 0
        assert ci_high < 15


# =============================================================================
# Historical Performance Tracking Tests
# =============================================================================

class TestHistoricalPerformanceTracking:
    """Tests fuer historische Performance-Verfolgung"""

    def test_training_result_metrics(self, sample_config, sample_training_result):
        """Test Metriken aus Training Result"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0)

        # Should use out-of-sample win rate from training
        assert result.historical_win_rate == 62.0  # avg_out_sample_win_rate
        assert result.sample_size == 4 * 30  # valid_epochs * min_trades_per_epoch

    def test_validation_result_bucket_lookup(
        self, sample_config, sample_validation_result
    ):
        """Test Bucket-Lookup aus Validation Result"""
        scorer = ReliabilityScorer(
            config=sample_config,
            validation_result=sample_validation_result,
        )

        # Test score in 7-9 bucket
        result = scorer.score(pullback_score=8.0)

        assert result.historical_win_rate == 65.0
        assert result.sample_size == 80

    def test_validation_result_bucket_5_7(
        self, sample_config, sample_validation_result
    ):
        """Test Bucket-Lookup fuer 5-7 Range"""
        scorer = ReliabilityScorer(
            config=sample_config,
            validation_result=sample_validation_result,
        )

        result = scorer.score(pullback_score=6.0)

        assert result.historical_win_rate == 54.0
        assert result.sample_size == 50

    def test_validation_result_bucket_9_11(
        self, sample_config, sample_validation_result
    ):
        """Test Bucket-Lookup fuer 9-11 Range"""
        scorer = ReliabilityScorer(
            config=sample_config,
            validation_result=sample_validation_result,
        )

        result = scorer.score(pullback_score=10.0)

        assert result.historical_win_rate == 75.0
        assert result.sample_size == 40

    def test_training_takes_priority_over_validation(
        self, sample_config, sample_training_result, sample_validation_result
    ):
        """Test: Training Result hat Vorrang vor Validation"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
            validation_result=sample_validation_result,
        )

        result = scorer.score(pullback_score=8.0)

        # Should use training result's out-of-sample win rate
        assert result.historical_win_rate == 62.0  # From training, not validation

    def test_no_data_returns_defaults(self, sample_config):
        """Test Default-Werte ohne Training/Validation"""
        scorer = ReliabilityScorer(config=sample_config)

        win_rate, sample_size = scorer._get_base_metrics(8.0)

        assert win_rate == 50.0
        assert sample_size == 0


# =============================================================================
# Grade Threshold Customization Tests
# =============================================================================

class TestGradeThresholdCustomization:
    """Tests fuer anpassbare Grade-Schwellenwerte"""

    def test_custom_grade_thresholds(self):
        """Test mit benutzerdefinierten Schwellenwerten"""
        config = ScorerConfig(
            grade_thresholds={
                "A": 80.0,  # Higher threshold
                "B": 70.0,
                "C": 60.0,
                "D": 50.0,
            }
        )
        scorer = ReliabilityScorer(config=config)

        # With default thresholds, 75% CI would be A
        # With custom thresholds, 75% CI is B
        grade = scorer._determine_grade(ci_lower=75.0, sample_size=100)
        assert grade == "B"

        # 85% CI should be A with custom thresholds
        grade = scorer._determine_grade(ci_lower=85.0, sample_size=100)
        assert grade == "A"

    def test_strict_min_grade_for_trade(self, sample_training_result):
        """Test striktere Mindest-Grade fuer Trade"""
        config = ScorerConfig(
            min_grade_for_trade="A",  # Only A grades can trade
            min_score=5.0,
        )
        scorer = ReliabilityScorer(
            config=config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0)

        # Even with good metrics, may not meet A grade
        if result.grade != "A":
            assert result.should_trade is False
            assert "unter Minimum" in result.rejection_reason

    def test_lenient_min_grade_for_trade(self, sample_training_result):
        """Test lockere Mindest-Grade fuer Trade"""
        config = ScorerConfig(
            min_grade_for_trade="D",  # D and above can trade
            min_score=5.0,
        )
        scorer = ReliabilityScorer(
            config=config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0)

        # Should trade unless grade is F
        if result.grade != "F":
            assert result.should_trade is True


# =============================================================================
# Regime Adjustment Extended Tests
# =============================================================================

class TestRegimeAdjustmentExtended:
    """Erweiterte Tests fuer Regime-Anpassungen"""

    def test_large_positive_adjustment_warning(self, sample_config):
        """Test Warnung bei grosser positiver Anpassung"""
        training = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=TrainingConfig(),
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=65.0,
            avg_in_sample_sharpe=1.5,
            avg_out_sample_win_rate=60.0,
            avg_out_sample_sharpe=1.2,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=8.0,
            overfit_severity="mild",
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={
                "low_vol": {"win_rate_adjustment": 10.0},  # Large positive
                "normal": {"win_rate_adjustment": 0.0},
            },
        )

        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=training,
        )

        result = scorer.score(pullback_score=8.0, vix=12.0)  # low_vol

        # Should have warning about large adjustment
        assert any("Win-Rate-Abweichung" in w for w in result.warnings)

    def test_large_negative_adjustment_warning(self, sample_config):
        """Test Warnung bei grosser negativer Anpassung"""
        training = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=TrainingConfig(),
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=65.0,
            avg_in_sample_sharpe=1.5,
            avg_out_sample_win_rate=60.0,
            avg_out_sample_sharpe=1.2,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=8.0,
            overfit_severity="mild",
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={
                "high_vol": {"win_rate_adjustment": -15.0},  # Large negative
                "normal": {"win_rate_adjustment": 0.0},
            },
        )

        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=training,
        )

        result = scorer.score(pullback_score=8.0, vix=35.0)  # high_vol

        assert any("Win-Rate-Abweichung" in w for w in result.warnings)

    def test_small_adjustment_no_warning(self, sample_training_result, sample_config):
        """Test keine Warnung bei kleiner Anpassung"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        # Normal regime has 0.0 adjustment
        result = scorer.score(pullback_score=8.0, vix=17.0)

        # Should not have regime adjustment warning
        assert not any("Win-Rate-Abweichung" in w for w in result.warnings)

    def test_regime_adjustments_disabled(self, sample_training_result):
        """Test mit deaktivierten Regime-Anpassungen"""
        config = ScorerConfig(use_regime_adjustments=False)
        scorer = ReliabilityScorer(
            config=config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=8.0, vix=12.0)

        # Should not apply regime adjustment
        assert result.regime is None
        assert result.regime_adjustment == 0.0


# =============================================================================
# Component Analysis Extended Tests
# =============================================================================

class TestComponentAnalysisExtended:
    """Erweiterte Tests fuer Komponenten-Analyse"""

    def test_analyze_components_disabled(self, sample_training_result, sample_score_breakdown):
        """Test mit deaktivierter Komponenten-Analyse"""
        config = ScorerConfig(analyze_components=False)
        scorer = ReliabilityScorer(
            config=config,
            training_result=sample_training_result,
        )

        result = scorer.score(
            pullback_score=8.0,
            score_breakdown=sample_score_breakdown,
        )

        # Should not have component analysis
        assert result.component_strengths == {}
        assert result.weak_components == []
        assert result.strong_components == []

    def test_many_weak_components_warning(self, sample_config, sample_training_result):
        """Test Warnung bei vielen schwachen Komponenten"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        # Breakdown with many weak/zero scores
        breakdown = {
            "components": {
                "rsi": {"score": 0.0},
                "support": {"score": 0.0},
                "fibonacci": {"score": 0.0},
                "ma": {"score": 0.5},  # weak
                "trend_strength": {"score": 0.0},
                "volume": {"score": 0.0},
                "macd": {"score": 0.0},
                "stoch": {"score": 0.0},
                "keltner": {"score": 0.0},
            }
        }

        result = scorer.score(
            pullback_score=8.0,
            score_breakdown=breakdown,
        )

        # Should have warning about weak components
        assert any("schwache Komponenten" in w for w in result.warnings)

    def test_component_moderate_strength(self, sample_config):
        """Test moderate Komponenten-Staerke"""
        scorer = ReliabilityScorer(config=sample_config)

        breakdown = {
            "components": {
                "rsi": {"score": 1.2},  # 60% of max 2.0 = moderate
                "support": {"score": 1.8},  # 60% of max 3.0 = moderate
            }
        }

        strengths, weak, strong = scorer._analyze_components(breakdown)

        assert strengths["rsi"] == "moderate"
        assert strengths["support"] == "moderate"
        assert "rsi" not in weak
        assert "rsi" not in strong

    def test_component_numeric_values(self, sample_config):
        """Test mit numerischen Komponenten-Werten (nicht Dict)"""
        scorer = ReliabilityScorer(config=sample_config)

        breakdown = {
            "components": {
                "rsi": 1.8,  # Direct numeric value
                "support": 2.4,
            }
        }

        strengths, weak, strong = scorer._analyze_components(breakdown)

        assert "rsi" in strengths
        assert "support" in strengths


# =============================================================================
# Sample Size Warning Tests
# =============================================================================

class TestSampleSizeWarnings:
    """Tests fuer Sample-Size Warnungen"""

    def test_warning_below_min_sample_size(self, sample_config, sample_validation_result):
        """Test Warnung bei zu geringer Sample Size"""
        config = ScorerConfig(min_sample_size=100)  # Higher than bucket sample sizes
        scorer = ReliabilityScorer(
            config=config,
            validation_result=sample_validation_result,
        )

        result = scorer.score(pullback_score=8.0)

        # Should have warning about sample size (80 < 100)
        assert any("historische Trades" in w for w in result.warnings)

    def test_no_warning_above_min_sample_size(self, sample_config, sample_validation_result):
        """Test keine Warnung bei ausreichender Sample Size"""
        config = ScorerConfig(min_sample_size=50)  # Lower than bucket
        scorer = ReliabilityScorer(
            config=config,
            validation_result=sample_validation_result,
        )

        result = scorer.score(pullback_score=8.0)  # Bucket 7-9 has 80 samples

        # Should not have sample size warning
        assert not any("historische Trades" in w for w in result.warnings)


# =============================================================================
# Overfit Configuration Tests
# =============================================================================

class TestOverfitConfiguration:
    """Tests fuer Overfit-Konfiguration"""

    def test_warn_on_overfit_disabled(self, sample_config):
        """Test mit deaktivierter Overfit-Warnung"""
        config = ScorerConfig(warn_on_overfit=False)
        training = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=TrainingConfig(),
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=75.0,
            avg_in_sample_sharpe=2.0,
            avg_out_sample_win_rate=55.0,
            avg_out_sample_sharpe=0.8,
            avg_win_rate_degradation=20.0,
            max_win_rate_degradation=25.0,
            overfit_severity="moderate",  # Would normally warn
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        scorer = ReliabilityScorer(
            config=config,
            training_result=training,
        )

        result = scorer.score(pullback_score=8.0)

        # Should not have overfit warning
        assert result.overfit_warning is False
        assert not any("Overfitting" in w for w in result.warnings)

    def test_max_overfit_severity_mild(self):
        """Test max_overfit_severity auf mild"""
        config = ScorerConfig(
            max_overfit_severity="mild",  # Only mild is allowed
        )
        training = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=TrainingConfig(),
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=70.0,
            avg_in_sample_sharpe=1.8,
            avg_out_sample_win_rate=58.0,
            avg_out_sample_sharpe=1.2,
            avg_win_rate_degradation=12.0,
            max_win_rate_degradation=15.0,
            overfit_severity="moderate",  # Exceeds max
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        scorer = ReliabilityScorer(
            config=config,
            training_result=training,
        )

        result = scorer.score(pullback_score=8.0)

        # Should have overfit warning because moderate > mild
        assert result.overfit_warning is True


# =============================================================================
# from_backtest Factory Tests
# =============================================================================

class TestFromBacktest:
    """Tests fuer from_backtest Factory-Methode"""

    def test_from_backtest_creates_scorer(self, sample_config):
        """Test from_backtest erstellt Scorer"""
        # Create mock backtest result
        mock_backtest = MagicMock()
        mock_backtest.trades = []

        # Mock SignalValidator
        with patch('src.backtesting.reliability.SignalValidator') as MockValidator:
            mock_validation = MagicMock()
            MockValidator.return_value.validate.return_value = mock_validation

            scorer = ReliabilityScorer.from_backtest(
                mock_backtest,
                config=sample_config,
            )

            assert scorer is not None
            assert scorer._validation_result == mock_validation
            assert scorer._training_result is None


# =============================================================================
# GRADE_ORDER Tests
# =============================================================================

class TestGradeOrder:
    """Tests fuer GRADE_ORDER Konstante"""

    def test_grade_order_values(self):
        """Test GRADE_ORDER Werte"""
        assert ReliabilityScorer.GRADE_ORDER["A"] == 5
        assert ReliabilityScorer.GRADE_ORDER["B"] == 4
        assert ReliabilityScorer.GRADE_ORDER["C"] == 3
        assert ReliabilityScorer.GRADE_ORDER["D"] == 2
        assert ReliabilityScorer.GRADE_ORDER["F"] == 1

    def test_grade_comparison(self):
        """Test Grade-Vergleiche"""
        order = ReliabilityScorer.GRADE_ORDER

        assert order["A"] > order["B"]
        assert order["B"] > order["C"]
        assert order["C"] > order["D"]
        assert order["D"] > order["F"]


# =============================================================================
# Score Method Edge Cases
# =============================================================================

class TestScoreMethodEdgeCases:
    """Edge Cases fuer score() Methode"""

    def test_score_at_exact_minimum(self, sample_config, sample_training_result):
        """Test Score genau am Minimum"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        # Training result has recommended_min_score=7.0
        result = scorer.score(pullback_score=7.0)

        # Should be accepted (>= minimum)
        assert "unter Minimum" not in (result.rejection_reason or "")

    def test_score_just_below_minimum(self, sample_config, sample_training_result):
        """Test Score knapp unter Minimum"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=6.9)

        assert result.should_trade is False
        assert "unter Minimum" in result.rejection_reason

    def test_score_zero(self, sample_config):
        """Test Score von 0"""
        scorer = ReliabilityScorer(config=sample_config)

        result = scorer.score(pullback_score=0.0)

        assert result.should_trade is False
        assert result.grade == "F"

    def test_score_maximum(self, sample_config, sample_training_result):
        """Test maximaler Score"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        result = scorer.score(pullback_score=16.0)

        # Should process without error
        assert result.score == 16.0

    def test_effective_min_score_uses_max(self, sample_training_result):
        """Test effective_min_score verwendet Maximum"""
        # Config min_score is lower than training recommended
        config = ScorerConfig(min_score=3.0)  # Lower
        scorer = ReliabilityScorer(
            config=config,
            training_result=sample_training_result,  # recommended_min_score=7.0
        )

        result = scorer.score(pullback_score=5.0)

        # Should use higher value (7.0 from training)
        assert result.should_trade is False
        assert "7.0" in result.rejection_reason


# =============================================================================
# Batch Scoring Extended Tests
# =============================================================================

class TestBatchScoringExtended:
    """Erweiterte Tests fuer Batch-Scoring"""

    def test_batch_sorting_tradeable_first(self, sample_config, sample_training_result):
        """Test Batch-Sortierung: Tradeable zuerst"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        candidates = [
            {"symbol": "LOW", "score": 4.0},   # Not tradeable (below min)
            {"symbol": "AAPL", "score": 9.0},  # Tradeable
            {"symbol": "MID", "score": 6.0},   # Not tradeable (below min)
            {"symbol": "MSFT", "score": 8.0},  # Tradeable
        ]

        results = scorer.score_batch(candidates)

        # First results should be tradeable
        tradeable_symbols = [c["symbol"] for c, r in results if r.should_trade]
        non_tradeable_symbols = [c["symbol"] for c, r in results if not r.should_trade]

        # Check ordering: tradeable first
        for i, (c, r) in enumerate(results):
            if r.should_trade:
                assert i < len(tradeable_symbols)
            else:
                assert i >= len(tradeable_symbols)

    def test_batch_empty_candidates(self, sample_config, sample_training_result):
        """Test Batch mit leerer Kandidatenliste"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        results = scorer.score_batch([])

        assert results == []

    def test_batch_with_missing_score_key(self, sample_config, sample_training_result):
        """Test Batch mit fehlendem score-Schluessel"""
        scorer = ReliabilityScorer(
            config=sample_config,
            training_result=sample_training_result,
        )

        candidates = [
            {"symbol": "AAPL"},  # Missing score, defaults to 0
        ]

        results = scorer.score_batch(candidates)

        _, result = results[0]
        assert result.score == 0


# =============================================================================
# ReliabilityResult Extended Tests
# =============================================================================

class TestReliabilityResultExtended:
    """Erweiterte Tests fuer ReliabilityResult"""

    def test_to_dict_complete(self):
        """Test vollstaendige to_dict Konvertierung"""
        result = ReliabilityResult(
            score=9.0,
            should_trade=True,
            grade="A",
            rejection_reason=None,
            historical_win_rate=72.0,
            confidence_interval=(65.0, 79.0),
            sample_size=150,
            vix=18.0,
            regime="normal",
            regime_adjustment=0.0,
            component_strengths={"rsi": "strong", "support": "moderate"},
            weak_components=["volume"],
            strong_components=["rsi"],
            overfit_warning=False,
            overfit_severity="none",
            warnings=["Test warning"],
        )

        d = result.to_dict()

        assert d["score"] == 9.0
        assert d["recommendation"]["should_trade"] is True
        assert d["recommendation"]["grade"] == "A"
        assert d["historical_performance"]["win_rate"] == 72.0
        assert d["historical_performance"]["confidence_interval"] == (65.0, 79.0)
        assert d["regime_context"]["vix"] == 18.0
        assert d["components"]["strengths"] == {"rsi": "strong", "support": "moderate"}
        assert d["components"]["weak"] == ["volume"]
        assert d["overfitting"]["warning"] is False
        assert d["warnings"] == ["Test warning"]

    def test_summary_with_warnings(self):
        """Test Summary mit Warnungen"""
        result = ReliabilityResult(
            score=7.5,
            should_trade=True,
            grade="C",
            historical_win_rate=55.0,
            confidence_interval=(45.0, 65.0),
            sample_size=40,
            warnings=["Warning 1", "Warning 2", "Warning 3"],
        )

        summary = result.summary()

        # Should include first 2 warnings
        assert "Warning 1" in summary
        assert "Warning 2" in summary

    def test_summary_without_regime(self):
        """Test Summary ohne Regime"""
        result = ReliabilityResult(
            score=8.0,
            should_trade=True,
            grade="B",
            historical_win_rate=65.0,
            confidence_interval=(55.0, 75.0),
            sample_size=100,
            regime=None,
        )

        summary = result.summary()

        # Should not have regime in output
        assert "normal" not in summary
        assert "low_vol" not in summary
