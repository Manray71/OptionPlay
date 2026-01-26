#!/usr/bin/env python3
"""
Tests für Walk-Forward Training Module

Testet:
- TrainingConfig Validierung
- Epochen-Generierung
- Walk-Forward Training
- Overfitting-Erkennung
- Persistenz (save/load)
- Signal Reliability aus Training
"""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backtesting.walk_forward import (
    TrainingConfig,
    EpochResult,
    TrainingResult,
    WalkForwardTrainer,
    format_training_summary,
)
from src.backtesting.engine import (
    BacktestConfig,
    BacktestResult,
    TradeResult,
    TradeOutcome,
    ExitReason,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_config():
    """Standard Training-Konfiguration"""
    return TrainingConfig(
        train_months=12,
        test_months=3,
        step_months=3,
        min_trades_per_epoch=20,
        min_valid_epochs=2,
    )


@pytest.fixture
def sample_historical_data():
    """Generiert 3 Jahre historische Daten für Tests"""
    data = {}
    symbols = ["AAPL", "MSFT", "GOOGL"]
    start_date = date(2021, 1, 1)
    end_date = date(2024, 1, 1)

    for symbol in symbols:
        bars = []
        current = start_date
        price = 100.0

        while current <= end_date:
            if current.weekday() < 5:  # Mo-Fr
                # Simuliere Preis-Bewegung
                import random
                random.seed(hash(f"{symbol}{current}") % 2**32)
                change = random.uniform(-0.02, 0.025)
                price *= (1 + change)

                bars.append({
                    "date": current.isoformat(),
                    "open": round(price * 0.999, 2),
                    "high": round(price * 1.01, 2),
                    "low": round(price * 0.99, 2),
                    "close": round(price, 2),
                    "volume": random.randint(1000000, 5000000),
                })

            current += timedelta(days=1)

        data[symbol] = bars

    return data


@pytest.fixture
def sample_vix_data():
    """Generiert VIX-Daten für Tests"""
    bars = []
    start_date = date(2021, 1, 1)
    end_date = date(2024, 1, 1)
    current = start_date
    vix = 18.0

    import random

    while current <= end_date:
        if current.weekday() < 5:
            random.seed(hash(f"VIX{current}") % 2**32)
            change = random.uniform(-0.05, 0.05)
            vix = max(10, min(50, vix * (1 + change)))

            bars.append({
                "date": current.isoformat(),
                "close": round(vix, 2),
            })

        current += timedelta(days=1)

    return bars


@pytest.fixture
def sample_trades():
    """Generiert Sample Trades für Tests"""
    trades = []
    base_date = date(2022, 1, 1)

    for i in range(100):
        entry_date = base_date + timedelta(days=i * 7)
        exit_date = entry_date + timedelta(days=30)

        # Abwechselnd Winner/Loser mit leichter Winner-Tendenz
        is_winner = (i % 3) != 0  # ~67% Win Rate

        trade = TradeResult(
            symbol=["AAPL", "MSFT", "GOOGL"][i % 3],
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=150.0,
            exit_price=155.0 if is_winner else 145.0,
            short_strike=140.0,
            long_strike=135.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=100.0,
            max_loss=400.0,
            realized_pnl=80.0 if is_winner else -200.0,
            outcome=TradeOutcome.PROFIT_TARGET if is_winner else TradeOutcome.STOP_LOSS,
            exit_reason=ExitReason.PROFIT_TARGET_HIT if is_winner else ExitReason.STOP_LOSS_HIT,
            dte_at_entry=60,
            dte_at_exit=30,
            hold_days=30,
            entry_vix=18.0 + (i % 10),
            pullback_score=5.0 + (i % 10) * 0.5,
        )
        trades.append(trade)

    return trades


@pytest.fixture
def sample_backtest_result(sample_trades, sample_config):
    """Sample BacktestResult"""
    config = BacktestConfig(
        start_date=date(2022, 1, 1),
        end_date=date(2023, 12, 31),
    )
    return BacktestResult(config=config, trades=sample_trades)


# =============================================================================
# TrainingConfig Tests
# =============================================================================

class TestTrainingConfig:
    """Tests für TrainingConfig"""

    def test_default_values(self):
        """Test Default-Werte"""
        config = TrainingConfig()

        assert config.train_months == 18
        assert config.test_months == 6
        assert config.step_months == 6
        assert config.min_trades_per_epoch == 50
        assert config.min_valid_epochs == 3

    def test_custom_values(self, sample_config):
        """Test Custom-Werte"""
        assert sample_config.train_months == 12
        assert sample_config.test_months == 3
        assert sample_config.step_months == 3
        assert sample_config.min_trades_per_epoch == 20

    def test_to_dict(self, sample_config):
        """Test Dictionary-Konvertierung"""
        d = sample_config.to_dict()

        assert d["train_months"] == 12
        assert d["test_months"] == 3
        assert "min_pullback_score" in d
        assert "profit_target_pct" in d


# =============================================================================
# EpochResult Tests
# =============================================================================

class TestEpochResult:
    """Tests für EpochResult"""

    def test_valid_epoch(self):
        """Test gültige Epoche"""
        epoch = EpochResult(
            epoch_id=1,
            train_start=date(2022, 1, 1),
            train_end=date(2023, 6, 30),
            test_start=date(2023, 7, 1),
            test_end=date(2023, 12, 31),
            in_sample_trades=100,
            in_sample_win_rate=65.0,
            in_sample_sharpe=1.5,
            in_sample_profit_factor=2.0,
            in_sample_avg_pnl=50.0,
            out_sample_trades=30,
            out_sample_win_rate=60.0,
            out_sample_sharpe=1.2,
            out_sample_profit_factor=1.8,
            out_sample_avg_pnl=40.0,
            win_rate_degradation=5.0,
            sharpe_degradation=0.3,
            overfit_score=0.2,
            optimal_threshold=7.0,
            is_valid=True,
        )

        assert epoch.is_valid
        assert epoch.win_rate_degradation == 5.0
        assert epoch.overfit_score == 0.2

    def test_skipped_epoch(self):
        """Test übersprungene Epoche"""
        epoch = EpochResult(
            epoch_id=1,
            train_start=date(2022, 1, 1),
            train_end=date(2022, 6, 30),
            test_start=date(2022, 7, 1),
            test_end=date(2022, 12, 31),
            in_sample_trades=0,
            in_sample_win_rate=0,
            in_sample_sharpe=0,
            in_sample_profit_factor=0,
            in_sample_avg_pnl=0,
            out_sample_trades=0,
            out_sample_win_rate=0,
            out_sample_sharpe=0,
            out_sample_profit_factor=0,
            out_sample_avg_pnl=0,
            win_rate_degradation=0,
            sharpe_degradation=0,
            overfit_score=0,
            optimal_threshold=5.0,
            is_valid=False,
            skip_reason="Nicht genug Trades",
        )

        assert not epoch.is_valid
        assert epoch.skip_reason == "Nicht genug Trades"

    def test_to_dict(self):
        """Test Dictionary-Konvertierung"""
        epoch = EpochResult(
            epoch_id=1,
            train_start=date(2022, 1, 1),
            train_end=date(2022, 12, 31),
            test_start=date(2023, 1, 1),
            test_end=date(2023, 6, 30),
            in_sample_trades=50,
            in_sample_win_rate=65.0,
            in_sample_sharpe=1.5,
            in_sample_profit_factor=2.0,
            in_sample_avg_pnl=50.0,
            out_sample_trades=20,
            out_sample_win_rate=60.0,
            out_sample_sharpe=1.2,
            out_sample_profit_factor=1.8,
            out_sample_avg_pnl=40.0,
            win_rate_degradation=5.0,
            sharpe_degradation=0.3,
            overfit_score=0.2,
            optimal_threshold=7.0,
        )

        d = epoch.to_dict()

        assert d["epoch_id"] == 1
        assert "train_period" in d
        assert "test_period" in d
        assert "in_sample" in d
        assert "out_sample" in d
        assert "overfitting" in d
        assert d["in_sample"]["win_rate"] == 65.0


# =============================================================================
# WalkForwardTrainer Tests
# =============================================================================

class TestWalkForwardTrainer:
    """Tests für WalkForwardTrainer"""

    def test_init(self, sample_config):
        """Test Initialisierung"""
        trainer = WalkForwardTrainer(sample_config)

        assert trainer.config == sample_config
        assert trainer._last_result is None

    def test_generate_epochs(self, sample_config):
        """Test Epochen-Generierung"""
        trainer = WalkForwardTrainer(sample_config)

        epochs = trainer._generate_epochs(
            data_start=date(2021, 1, 1),
            data_end=date(2024, 1, 1),
        )

        # 12 Monate Training + 3 Monate Test, Step 3 Monate
        # Sollte mehrere Epochen ergeben
        assert len(epochs) >= 3

        # Prüfe erste Epoche
        train_start, train_end, test_start, test_end = epochs[0]
        assert train_start == date(2021, 1, 1)

        # Prüfe Sequenz
        for i, (ts, te, ts2, te2) in enumerate(epochs[:-1]):
            next_ts, _, _, _ = epochs[i + 1]
            # Step sollte step_months sein
            assert (next_ts.year - ts.year) * 12 + (next_ts.month - ts.month) == sample_config.step_months

    def test_get_data_range(self, sample_config, sample_historical_data):
        """Test Datenbereich-Ermittlung"""
        trainer = WalkForwardTrainer(sample_config)

        start, end = trainer._get_data_range(
            sample_historical_data,
            ["AAPL", "MSFT"],
        )

        assert start == date(2021, 1, 1)  # Erster Tag in Testdaten
        assert end is not None
        assert end > start

    def test_get_data_range_empty(self, sample_config):
        """Test mit leeren Daten"""
        trainer = WalkForwardTrainer(sample_config)

        start, end = trainer._get_data_range({}, [])

        assert start is None
        assert end is None

    def test_calculate_overfit_score(self, sample_config):
        """Test Overfit-Score Berechnung"""
        trainer = WalkForwardTrainer(sample_config)

        # Kein Overfit
        score = trainer._calculate_overfit_score(0, 0)
        assert score == 0.0

        # Leichtes Overfit
        score = trainer._calculate_overfit_score(5.0, 0.2)
        assert 0.1 < score < 0.3

        # Starkes Overfit
        score = trainer._calculate_overfit_score(20.0, 1.0)
        assert score >= 0.9

    def test_classify_overfit_severity(self, sample_config):
        """Test Overfit-Klassifizierung"""
        trainer = WalkForwardTrainer(sample_config)

        assert trainer._classify_overfit_severity(3.0) == "none"
        assert trainer._classify_overfit_severity(7.0) == "mild"
        assert trainer._classify_overfit_severity(12.0) == "moderate"
        assert trainer._classify_overfit_severity(20.0) == "severe"

    def test_get_regime_for_vix(self, sample_config):
        """Test VIX-Regime Zuordnung"""
        trainer = WalkForwardTrainer(sample_config)

        assert trainer._get_regime_for_vix(12.0) == "low_vol"
        assert trainer._get_regime_for_vix(17.0) == "normal"
        assert trainer._get_regime_for_vix(25.0) == "elevated"
        assert trainer._get_regime_for_vix(35.0) == "high_vol"

    def test_get_bucket_label(self, sample_config):
        """Test Bucket-Label"""
        trainer = WalkForwardTrainer(sample_config)

        assert trainer._get_bucket_label(4.0) == "0-5"
        assert trainer._get_bucket_label(6.0) == "5-7"
        assert trainer._get_bucket_label(8.0) == "7-9"
        assert trainer._get_bucket_label(10.0) == "9-11"
        assert trainer._get_bucket_label(12.0) == "11-16"

    def test_determine_grade(self, sample_config):
        """Test Grade-Bestimmung"""
        trainer = WalkForwardTrainer(sample_config)

        assert trainer._determine_grade(75.0) == "A"
        assert trainer._determine_grade(65.0) == "B"
        assert trainer._determine_grade(55.0) == "C"
        assert trainer._determine_grade(45.0) == "D"
        assert trainer._determine_grade(35.0) == "F"


# =============================================================================
# Integration Tests
# =============================================================================

class TestWalkForwardIntegration:
    """Integration Tests für Walk-Forward Training"""

    def test_train_sync_with_mock(self, sample_config, sample_historical_data, sample_vix_data):
        """Test Training mit echten Daten (simplified)"""
        # Verwende kürzere Perioden für schnelleren Test
        config = TrainingConfig(
            train_months=6,
            test_months=2,
            step_months=2,
            min_trades_per_epoch=5,  # Niedriger für Tests
            min_valid_epochs=1,
        )

        trainer = WalkForwardTrainer(config)

        # Training durchführen
        result = trainer.train_sync(
            historical_data=sample_historical_data,
            vix_data=sample_vix_data,
            symbols=["AAPL"],
        )

        # Prüfe Ergebnis
        assert result is not None
        assert result.training_id.startswith("wf_")
        assert result.total_epochs > 0
        assert result.config == config

    def test_extract_metrics(self, sample_config, sample_backtest_result):
        """Test Metriken-Extraktion"""
        trainer = WalkForwardTrainer(sample_config)

        metrics = trainer._extract_metrics(sample_backtest_result)

        assert "trades" in metrics
        assert "win_rate" in metrics
        assert "sharpe" in metrics
        assert "profit_factor" in metrics
        assert "avg_pnl" in metrics

        assert metrics["trades"] == 100
        assert metrics["win_rate"] > 0

    def test_aggregate_threshold(self, sample_config):
        """Test Threshold-Aggregation"""
        trainer = WalkForwardTrainer(sample_config)

        epochs = [
            EpochResult(
                epoch_id=i,
                train_start=date(2022, 1, 1),
                train_end=date(2022, 12, 31),
                test_start=date(2023, 1, 1),
                test_end=date(2023, 6, 30),
                in_sample_trades=50,
                in_sample_win_rate=65.0,
                in_sample_sharpe=1.5,
                in_sample_profit_factor=2.0,
                in_sample_avg_pnl=50.0,
                out_sample_trades=20,
                out_sample_win_rate=60.0,
                out_sample_sharpe=1.2,
                out_sample_profit_factor=1.8,
                out_sample_avg_pnl=40.0,
                win_rate_degradation=5.0,
                sharpe_degradation=0.3,
                overfit_score=0.2,
                optimal_threshold=6.0 + i,  # 6, 7, 8, 9
            )
            for i in range(4)
        ]

        threshold = trainer._aggregate_threshold(epochs)

        # 75. Perzentil von [6, 7, 8, 9] = 8 oder 9
        assert threshold >= 8.0


# =============================================================================
# Persistence Tests
# =============================================================================

class TestPersistence:
    """Tests für Speichern und Laden"""

    def test_save_and_load(self, sample_config):
        """Test Save und Load"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        # Erstelle Mock-Ergebnis
        result = TrainingResult(
            training_id="test_123",
            training_date=datetime.now(),
            config=sample_config,
            epochs=[],
            valid_epochs=3,
            total_epochs=4,
            avg_in_sample_win_rate=65.0,
            avg_in_sample_sharpe=1.5,
            avg_out_sample_win_rate=60.0,
            avg_out_sample_sharpe=1.2,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=8.0,
            overfit_severity="mild",
            recommended_min_score=7.0,
            top_predictors=["rsi_score", "support_score"],
            component_weights={"rsi_score": 0.4, "support_score": 0.3},
            regime_adjustments={"low_vol": {"win_rate_adjustment": 3.0}},
            warnings=["Test warning"],
        )

        # Speichern
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = f"{tmpdir}/test_model.json"
            saved_path = trainer.save(result, filepath)

            assert Path(saved_path).exists()

            # JSON prüfen
            with open(saved_path) as f:
                data = json.load(f)

            assert data["training_id"] == "test_123"
            assert data["summary"]["valid_epochs"] == 3
            assert data["recommendations"]["min_score"] == 7.0

            # Laden
            loaded_trainer = WalkForwardTrainer.load(saved_path)

            assert loaded_trainer._last_result is not None
            assert loaded_trainer._last_result.recommended_min_score == 7.0

    def test_to_dict(self, sample_config):
        """Test TrainingResult.to_dict()"""
        from datetime import datetime

        result = TrainingResult(
            training_id="test_456",
            training_date=datetime(2024, 1, 15, 10, 30, 0),
            config=sample_config,
            epochs=[],
            valid_epochs=2,
            total_epochs=3,
            avg_in_sample_win_rate=62.5,
            avg_in_sample_sharpe=1.3,
            avg_out_sample_win_rate=58.0,
            avg_out_sample_sharpe=1.1,
            avg_win_rate_degradation=4.5,
            max_win_rate_degradation=7.0,
            overfit_severity="none",
            recommended_min_score=6.5,
            top_predictors=["ma_score"],
            component_weights={},
            regime_adjustments={},
        )

        d = result.to_dict()

        assert d["version"] == "1.0.0"
        assert d["training_id"] == "test_456"
        assert "summary" in d
        assert "recommendations" in d
        assert "epochs" in d


# =============================================================================
# Signal Reliability Tests
# =============================================================================

class TestSignalReliability:
    """Tests für Signal Reliability aus Training"""

    def test_get_signal_reliability(self, sample_config):
        """Test Signal Reliability Abfrage"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        # Mock-Ergebnis setzen
        trainer._last_result = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=sample_config,
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
            top_predictors=["rsi_score"],
            component_weights={"rsi_score": 0.4},
            regime_adjustments={"low_vol": {"win_rate_adjustment": 3.0}},
        )

        # Test mit Score über Minimum
        reliability = trainer.get_signal_reliability(score=8.0, vix=13.0)

        assert reliability.score == 8.0
        assert reliability.score_bucket == "7-9"
        assert reliability.regime_context is not None
        assert "low_vol" in reliability.regime_context
        assert reliability.reliability_grade in ["A", "B", "C", "D", "F"]

    def test_get_signal_reliability_under_minimum(self, sample_config):
        """Test mit Score unter Minimum"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        trainer._last_result = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=sample_config,
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
            regime_adjustments={},
        )

        reliability = trainer.get_signal_reliability(score=5.0)

        assert len(reliability.warnings) > 0
        assert any("unter" in w.lower() for w in reliability.warnings)

    def test_get_signal_reliability_no_result(self, sample_config):
        """Test ohne Training-Ergebnis"""
        trainer = WalkForwardTrainer(sample_config)

        with pytest.raises(ValueError, match="Keine Training-Ergebnisse"):
            trainer.get_signal_reliability(score=8.0)


# =============================================================================
# Should Trade Tests
# =============================================================================

class TestShouldTrade:
    """Tests für should_trade() Methode"""

    def test_should_trade_positive(self, sample_config):
        """Test positiver Trade-Empfehlung"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        trainer._last_result = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=sample_config,
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=70.0,
            avg_in_sample_sharpe=1.8,
            avg_out_sample_win_rate=65.0,
            avg_out_sample_sharpe=1.5,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=7.0,
            overfit_severity="none",
            recommended_min_score=6.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        should, reason = trainer.should_trade(score=8.0)

        assert should is True
        assert "empfohlen" in reason.lower()

    def test_should_trade_score_too_low(self, sample_config):
        """Test mit zu niedrigem Score"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        trainer._last_result = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=sample_config,
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=65.0,
            avg_in_sample_sharpe=1.5,
            avg_out_sample_win_rate=60.0,
            avg_out_sample_sharpe=1.2,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=8.0,
            overfit_severity="none",
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        should, reason = trainer.should_trade(score=5.0)

        assert should is False
        assert "minimum" in reason.lower()

    def test_should_trade_severe_overfit(self, sample_config):
        """Test mit schwerem Overfitting"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        trainer._last_result = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=sample_config,
            epochs=[],
            valid_epochs=3,
            total_epochs=3,
            avg_in_sample_win_rate=75.0,
            avg_in_sample_sharpe=2.0,
            avg_out_sample_win_rate=50.0,
            avg_out_sample_sharpe=0.8,
            avg_win_rate_degradation=25.0,
            max_win_rate_degradation=30.0,
            overfit_severity="severe",
            recommended_min_score=7.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        should, reason = trainer.should_trade(score=9.0)

        assert should is False
        # Kann wegen Grade oder Overfit abgelehnt werden
        assert "overfit" in reason.lower() or "grade" in reason.lower()

    def test_should_trade_no_result(self, sample_config):
        """Test ohne Training-Ergebnis"""
        trainer = WalkForwardTrainer(sample_config)

        should, reason = trainer.should_trade(score=8.0)

        assert should is False
        assert "keine" in reason.lower()


# =============================================================================
# Summary Format Tests
# =============================================================================

class TestSummaryFormat:
    """Tests für Formatierung"""

    def test_training_result_summary(self, sample_config):
        """Test TrainingResult.summary()"""
        from datetime import datetime

        result = TrainingResult(
            training_id="test_summary",
            training_date=datetime(2024, 1, 15, 10, 30, 0),
            config=sample_config,
            epochs=[],
            valid_epochs=3,
            total_epochs=4,
            avg_in_sample_win_rate=65.0,
            avg_in_sample_sharpe=1.5,
            avg_out_sample_win_rate=60.0,
            avg_out_sample_sharpe=1.2,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=8.0,
            overfit_severity="mild",
            recommended_min_score=7.0,
            top_predictors=["rsi_score", "support_score"],
            component_weights={},
            regime_adjustments={"low_vol": {"win_rate_adjustment": 3.0}},
            warnings=["Test warning"],
        )

        summary = result.summary()

        assert "WALK-FORWARD TRAINING RESULT" in summary
        assert "test_summary" in summary
        assert "65.0%" in summary  # In-sample Win Rate
        assert "60.0%" in summary  # Out-of-sample Win Rate
        assert "MILD" in summary  # Overfit severity
        assert "7.0" in summary  # Min Score
        assert "Test warning" in summary

    def test_format_training_summary(self, sample_config):
        """Test format_training_summary utility"""
        from datetime import datetime

        result = TrainingResult(
            training_id="test",
            training_date=datetime.now(),
            config=sample_config,
            epochs=[],
            valid_epochs=2,
            total_epochs=2,
            avg_in_sample_win_rate=60.0,
            avg_in_sample_sharpe=1.2,
            avg_out_sample_win_rate=55.0,
            avg_out_sample_sharpe=1.0,
            avg_win_rate_degradation=5.0,
            max_win_rate_degradation=7.0,
            overfit_severity="none",
            recommended_min_score=6.0,
            top_predictors=[],
            component_weights={},
            regime_adjustments={},
        )

        summary = format_training_summary(result)

        assert isinstance(summary, str)
        assert len(summary) > 100


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge Cases und Fehlerbehandlung"""

    def test_empty_historical_data(self, sample_config):
        """Test mit leeren historischen Daten"""
        trainer = WalkForwardTrainer(sample_config)

        with pytest.raises(ValueError, match="Keine Symbole"):
            trainer.train_sync(
                historical_data={},
                vix_data=[],
            )

    def test_no_valid_dates(self, sample_config):
        """Test ohne gültige Daten"""
        trainer = WalkForwardTrainer(sample_config)

        with pytest.raises(ValueError, match="Keine gültigen Daten"):
            trainer.train_sync(
                historical_data={"AAPL": []},
                vix_data=[],
                symbols=["AAPL"],
            )

    def test_aggregate_with_no_valid_epochs(self, sample_config):
        """Test Aggregation ohne gültige Epochen"""
        from datetime import datetime

        trainer = WalkForwardTrainer(sample_config)

        result = trainer._aggregate_results(
            training_id="test",
            training_date=datetime.now(),
            epochs=[],
            warnings=[],
        )

        assert result.valid_epochs == 0
        assert result.overfit_severity == "severe"
        assert any("Keine gültigen Epochen" in w for w in result.warnings)

    def test_aggregate_empty_predictors(self, sample_config):
        """Test Predictor-Aggregation ohne Daten"""
        trainer = WalkForwardTrainer(sample_config)

        predictors = trainer._aggregate_predictors([])

        assert predictors == []

    def test_aggregate_empty_component_weights(self, sample_config):
        """Test Component-Weight-Aggregation ohne Daten"""
        trainer = WalkForwardTrainer(sample_config)

        weights = trainer._aggregate_component_weights([])

        assert weights == {}
