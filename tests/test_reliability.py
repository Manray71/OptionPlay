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
