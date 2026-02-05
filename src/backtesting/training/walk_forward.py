#!/usr/bin/env python3
"""
Walk-Forward Training Module - Phase 2 des Hochverlässlichkeits-Frameworks

Implementiert robustes Out-of-Sample Testing mit rollierendem Train/Test Split
über mehrere Epochen. Erkennt Overfitting und liefert produktionsreife
Empfehlungen für Score-Schwellenwerte.

Verwendung:
    from src.backtesting import WalkForwardTrainer, TrainingConfig

    config = TrainingConfig(
        train_months=18,
        test_months=6,
        step_months=6,
    )

    trainer = WalkForwardTrainer(config)
    result = trainer.train_sync(historical_data, vix_data)

    print(result.summary())
    trainer.save(result, "~/.optionplay/models/latest.json")
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from ..core import BacktestEngine, BacktestConfig, BacktestResult, TradeResult
from ..validation import (
    SignalValidator,
    SignalValidationResult,
    SignalReliability,
    StatisticalCalculator,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class TrainingConfig:
    """Konfiguration für Walk-Forward Training"""

    # Zeitfenster
    train_months: int = 18  # Trainingsperiode in Monaten
    test_months: int = 6  # Testperiode in Monaten
    step_months: int = 6  # Schritt zwischen Epochen

    # Qualitätsanforderungen
    min_trades_per_epoch: int = 50  # Minimum Trades pro Epoche
    min_valid_epochs: int = 3  # Minimum gültige Epochen

    # Symbole (None = vollständige Watchlist)
    symbols: Optional[List[str]] = None

    # Backtest-Parameter (für interne BacktestEngine)
    min_pullback_score: float = 5.0
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 200.0
    dte_min: int = 45
    dte_max: int = 75

    # Training-Features
    optimize_parameters: bool = False  # Parameter-Optimierung (Phase 3)
    include_regime_analysis: bool = True  # VIX-Regime-Analyse

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "train_months": self.train_months,
            "test_months": self.test_months,
            "step_months": self.step_months,
            "min_trades_per_epoch": self.min_trades_per_epoch,
            "min_valid_epochs": self.min_valid_epochs,
            "symbols": self.symbols,
            "min_pullback_score": self.min_pullback_score,
            "profit_target_pct": self.profit_target_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "dte_min": self.dte_min,
            "dte_max": self.dte_max,
            "optimize_parameters": self.optimize_parameters,
            "include_regime_analysis": self.include_regime_analysis,
        }


# =============================================================================
# Result Data Classes
# =============================================================================

@dataclass
class EpochResult:
    """Ergebnis einer einzelnen Trainings-Epoche"""

    # Identifikation
    epoch_id: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    # In-Sample (Training) Metriken
    in_sample_trades: int
    in_sample_win_rate: float
    in_sample_sharpe: float
    in_sample_profit_factor: float
    in_sample_avg_pnl: float

    # Out-of-Sample (Test) Metriken
    out_sample_trades: int
    out_sample_win_rate: float
    out_sample_sharpe: float
    out_sample_profit_factor: float
    out_sample_avg_pnl: float

    # Overfitting-Indikatoren
    win_rate_degradation: float  # in_sample - out_sample
    sharpe_degradation: float
    overfit_score: float  # 0-1, höher = mehr Overfit

    # Von SignalValidator (aus Training)
    optimal_threshold: float
    validation_result: Optional[SignalValidationResult] = None

    # Validität
    is_valid: bool = True
    skip_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "epoch_id": self.epoch_id,
            "train_period": {
                "start": self.train_start.isoformat(),
                "end": self.train_end.isoformat(),
            },
            "test_period": {
                "start": self.test_start.isoformat(),
                "end": self.test_end.isoformat(),
            },
            "in_sample": {
                "trades": self.in_sample_trades,
                "win_rate": round(self.in_sample_win_rate, 1),
                "sharpe": round(self.in_sample_sharpe, 2),
                "profit_factor": round(self.in_sample_profit_factor, 2),
                "avg_pnl": round(self.in_sample_avg_pnl, 2),
            },
            "out_sample": {
                "trades": self.out_sample_trades,
                "win_rate": round(self.out_sample_win_rate, 1),
                "sharpe": round(self.out_sample_sharpe, 2),
                "profit_factor": round(self.out_sample_profit_factor, 2),
                "avg_pnl": round(self.out_sample_avg_pnl, 2),
            },
            "overfitting": {
                "win_rate_degradation": round(self.win_rate_degradation, 1),
                "sharpe_degradation": round(self.sharpe_degradation, 2),
                "overfit_score": round(self.overfit_score, 3),
            },
            "optimal_threshold": self.optimal_threshold,
            "is_valid": self.is_valid,
            "skip_reason": self.skip_reason,
        }


@dataclass
class TrainingResult:
    """Vollständiges Trainings-Ergebnis"""

    # Identifikation
    training_id: str
    training_date: datetime
    config: TrainingConfig

    # Epochen
    epochs: List[EpochResult]
    valid_epochs: int
    total_epochs: int

    # Aggregierte In-Sample Metriken
    avg_in_sample_win_rate: float
    avg_in_sample_sharpe: float

    # Aggregierte Out-of-Sample Metriken
    avg_out_sample_win_rate: float
    avg_out_sample_sharpe: float

    # Overfitting-Analyse
    avg_win_rate_degradation: float
    max_win_rate_degradation: float
    overfit_severity: str  # "none", "mild", "moderate", "severe"

    # Empfehlungen
    recommended_min_score: float
    top_predictors: List[str]
    component_weights: Dict[str, float]
    regime_adjustments: Dict[str, Dict[str, float]]

    # Warnungen
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary für JSON-Export"""
        return {
            "version": "1.0.0",
            "training_id": self.training_id,
            "training_date": self.training_date.isoformat(),
            "config": self.config.to_dict(),
            "summary": {
                "valid_epochs": self.valid_epochs,
                "total_epochs": self.total_epochs,
                "avg_in_sample_win_rate": round(self.avg_in_sample_win_rate, 1),
                "avg_in_sample_sharpe": round(self.avg_in_sample_sharpe, 2),
                "avg_out_sample_win_rate": round(self.avg_out_sample_win_rate, 1),
                "avg_out_sample_sharpe": round(self.avg_out_sample_sharpe, 2),
                "avg_win_rate_degradation": round(self.avg_win_rate_degradation, 1),
                "max_win_rate_degradation": round(self.max_win_rate_degradation, 1),
                "overfit_severity": self.overfit_severity,
            },
            "recommendations": {
                "min_score": self.recommended_min_score,
                "top_predictors": self.top_predictors,
                "component_weights": {
                    k: round(v, 3) for k, v in self.component_weights.items()
                },
                "regime_adjustments": {
                    regime: {k: round(v, 1) for k, v in adjustments.items()}
                    for regime, adjustments in self.regime_adjustments.items()
                },
            },
            "epochs": [e.to_dict() for e in self.epochs],
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        """Formatierte Zusammenfassung"""
        lines = [
            "",
            "=" * 70,
            "  WALK-FORWARD TRAINING RESULT",
            "=" * 70,
            f"  Training ID:     {self.training_id}",
            f"  Training Date:   {self.training_date.strftime('%Y-%m-%d %H:%M')}",
            f"  Valid Epochs:    {self.valid_epochs} / {self.total_epochs}",
            "",
            "-" * 70,
            "  IN-SAMPLE (Training) vs OUT-OF-SAMPLE (Test)",
            "-" * 70,
            f"                      In-Sample    Out-of-Sample    Degradation",
            f"  Win Rate:           {self.avg_in_sample_win_rate:6.1f}%        "
            f"{self.avg_out_sample_win_rate:6.1f}%          "
            f"{self.avg_win_rate_degradation:+5.1f}%",
            f"  Sharpe Ratio:       {self.avg_in_sample_sharpe:6.2f}         "
            f"{self.avg_out_sample_sharpe:6.2f}",
            "",
            "-" * 70,
            "  OVERFITTING ANALYSIS",
            "-" * 70,
            f"  Severity:           {self.overfit_severity.upper()}",
            f"  Avg Degradation:    {self.avg_win_rate_degradation:+.1f}%",
            f"  Max Degradation:    {self.max_win_rate_degradation:+.1f}%",
            "",
            "-" * 70,
            "  RECOMMENDATIONS",
            "-" * 70,
            f"  Min Score Threshold: {self.recommended_min_score:.1f}",
        ]

        if self.top_predictors:
            lines.append(f"  Top Predictors:      {', '.join(self.top_predictors[:3])}")

        if self.regime_adjustments:
            lines.extend(["", "  Regime Adjustments:"])
            for regime, adjustments in self.regime_adjustments.items():
                adj = adjustments.get("win_rate_adjustment", 0)
                lines.append(f"    {regime:12s}: {adj:+.1f}% Win Rate")

        if self.warnings:
            lines.extend([
                "",
                "-" * 70,
                "  WARNINGS",
                "-" * 70,
            ])
            for warning in self.warnings:
                lines.append(f"  ! {warning}")

        lines.append("=" * 70)
        return "\n".join(lines)


# =============================================================================
# Walk-Forward Trainer
# =============================================================================

class WalkForwardTrainer:
    """
    Walk-Forward Training für robuste Out-of-Sample Validierung.

    Prozess:
    1. Teile historische Daten in rollierende Train/Test-Epochen
    2. Für jede Epoche:
       - Trainiere auf In-Sample Daten
       - Validiere Signals mit SignalValidator
       - Teste auf Out-of-Sample Daten
       - Vergleiche Metriken
    3. Aggregiere Ergebnisse über alle Epochen
    4. Erkenne Overfitting durch Degradationsanalyse
    """

    # Overfitting-Schwellenwerte
    OVERFIT_THRESHOLDS = {
        "none": 5.0,       # < 5% Degradation
        "mild": 10.0,      # 5-10% Degradation
        "moderate": 15.0,  # 10-15% Degradation
        "severe": float("inf"),  # > 15% Degradation
    }

    def __init__(self, config: TrainingConfig):
        """
        Initialisiert den Trainer.

        Args:
            config: Training-Konfiguration
        """
        self.config = config
        self._last_result: Optional[TrainingResult] = None

    def train_sync(
        self,
        historical_data: Dict[str, List[Dict]],
        vix_data: List[Dict],
        symbols: Optional[List[str]] = None,
    ) -> TrainingResult:
        """
        Führt synchrones Walk-Forward Training durch.

        Args:
            historical_data: Dict mit {symbol: [{date, open, high, low, close, volume}, ...]}
            vix_data: VIX-Historie [{date, close}, ...]
            symbols: Optional: Symbole zum Testen (sonst config.symbols oder alle)

        Returns:
            TrainingResult mit allen Epochen und Empfehlungen
        """
        training_id = f"wf_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        training_date = datetime.now()
        warnings = []

        # Symbole bestimmen
        test_symbols = symbols or self.config.symbols or list(historical_data.keys())

        if not test_symbols:
            raise ValueError("Keine Symbole für Training verfügbar.")

        # Datenbereich ermitteln
        data_start, data_end = self._get_data_range(historical_data, test_symbols)

        if data_start is None or data_end is None:
            raise ValueError("Keine gültigen Daten gefunden.")

        logger.info(
            f"Training mit {len(test_symbols)} Symbolen von {data_start} bis {data_end}"
        )

        # Epochen generieren
        epochs_config = self._generate_epochs(data_start, data_end)

        if len(epochs_config) < self.config.min_valid_epochs:
            warnings.append(
                f"Nur {len(epochs_config)} Epochen möglich. "
                f"Minimum {self.config.min_valid_epochs} empfohlen."
            )

        # Trainiere jede Epoche
        epoch_results: List[EpochResult] = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(epochs_config):
            logger.info(
                f"Epoche {i + 1}/{len(epochs_config)}: "
                f"Train [{train_start} - {train_end}], Test [{test_start} - {test_end}]"
            )

            epoch_result = self._train_epoch(
                epoch_id=i + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                symbols=test_symbols,
                historical_data=historical_data,
                vix_data=vix_data,
            )

            epoch_results.append(epoch_result)

            if not epoch_result.is_valid:
                logger.warning(
                    f"Epoche {i + 1} übersprungen: {epoch_result.skip_reason}"
                )

        # Aggregiere Ergebnisse
        result = self._aggregate_results(
            training_id=training_id,
            training_date=training_date,
            epochs=epoch_results,
            warnings=warnings,
        )

        self._last_result = result
        return result

    def _generate_epochs(
        self,
        data_start: date,
        data_end: date,
    ) -> List[Tuple[date, date, date, date]]:
        """
        Generiert rollierende Train/Test-Epochen.

        Returns:
            Liste von (train_start, train_end, test_start, test_end) Tupeln
        """
        epochs = []

        # Start der ersten Epoche
        train_start = data_start

        while True:
            # Training-Ende = Train-Start + train_months
            train_end = train_start + relativedelta(months=self.config.train_months)

            # Test-Start = Training-Ende + 1 Tag
            test_start = train_end + timedelta(days=1)

            # Test-Ende = Test-Start + test_months
            test_end = test_start + relativedelta(months=self.config.test_months)

            # Prüfe ob Test-Periode noch in Datenbereich liegt
            if test_end > data_end:
                # Letzte Epoche: verkürze Test-Periode wenn möglich
                if test_start < data_end:
                    test_end = data_end
                    epochs.append((train_start, train_end, test_start, test_end))
                break

            epochs.append((train_start, train_end, test_start, test_end))

            # Nächste Epoche: step_months nach vorne
            train_start = train_start + relativedelta(months=self.config.step_months)

            # Prüfe ob noch genug Daten für Training
            if train_start + relativedelta(months=self.config.train_months) > data_end:
                break

        return epochs

    def _train_epoch(
        self,
        epoch_id: int,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        symbols: List[str],
        historical_data: Dict[str, List[Dict]],
        vix_data: List[Dict],
    ) -> EpochResult:
        """
        Trainiert eine einzelne Epoche.

        1. Backtest auf Training-Daten
        2. Signal-Validierung
        3. Backtest auf Test-Daten
        4. Vergleiche In-Sample vs Out-of-Sample
        """
        # Erstelle Backtest-Config für Training
        train_config = BacktestConfig(
            start_date=train_start,
            end_date=train_end,
            min_pullback_score=self.config.min_pullback_score,
            profit_target_pct=self.config.profit_target_pct,
            stop_loss_pct=self.config.stop_loss_pct,
            dte_min=self.config.dte_min,
            dte_max=self.config.dte_max,
        )

        # 1. Training-Backtest
        train_engine = BacktestEngine(train_config)
        train_result = train_engine.run_sync(
            symbols=symbols,
            historical_data=historical_data,
            vix_data=vix_data,
        )

        # Prüfe Mindest-Trades
        if train_result.total_trades < self.config.min_trades_per_epoch:
            return self._create_skipped_epoch(
                epoch_id=epoch_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                reason=f"Nur {train_result.total_trades} Training-Trades "
                       f"(min: {self.config.min_trades_per_epoch})",
            )

        # 2. Signal-Validierung
        validator = SignalValidator()
        validation_result = validator.validate(
            train_result,
            include_regime_analysis=self.config.include_regime_analysis,
        )

        optimal_threshold = validation_result.optimal_threshold

        # 3. Test-Backtest (mit optimiertem Threshold)
        test_config = BacktestConfig(
            start_date=test_start,
            end_date=test_end,
            min_pullback_score=optimal_threshold,
            profit_target_pct=self.config.profit_target_pct,
            stop_loss_pct=self.config.stop_loss_pct,
            dte_min=self.config.dte_min,
            dte_max=self.config.dte_max,
        )

        test_engine = BacktestEngine(test_config)
        test_result = test_engine.run_sync(
            symbols=symbols,
            historical_data=historical_data,
            vix_data=vix_data,
        )

        # Prüfe Test-Trades
        if test_result.total_trades < 10:
            return self._create_skipped_epoch(
                epoch_id=epoch_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                reason=f"Nur {test_result.total_trades} Test-Trades (min: 10)",
            )

        # 4. Metriken extrahieren
        in_sample = self._extract_metrics(train_result)
        out_sample = self._extract_metrics(test_result)

        # 5. Overfitting berechnen
        win_rate_degradation = in_sample["win_rate"] - out_sample["win_rate"]
        sharpe_degradation = in_sample["sharpe"] - out_sample["sharpe"]
        overfit_score = self._calculate_overfit_score(
            win_rate_degradation,
            sharpe_degradation,
        )

        return EpochResult(
            epoch_id=epoch_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            in_sample_trades=in_sample["trades"],
            in_sample_win_rate=in_sample["win_rate"],
            in_sample_sharpe=in_sample["sharpe"],
            in_sample_profit_factor=in_sample["profit_factor"],
            in_sample_avg_pnl=in_sample["avg_pnl"],
            out_sample_trades=out_sample["trades"],
            out_sample_win_rate=out_sample["win_rate"],
            out_sample_sharpe=out_sample["sharpe"],
            out_sample_profit_factor=out_sample["profit_factor"],
            out_sample_avg_pnl=out_sample["avg_pnl"],
            win_rate_degradation=win_rate_degradation,
            sharpe_degradation=sharpe_degradation,
            overfit_score=overfit_score,
            optimal_threshold=optimal_threshold,
            validation_result=validation_result,
            is_valid=True,
        )

    def _create_skipped_epoch(
        self,
        epoch_id: int,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        reason: str,
    ) -> EpochResult:
        """Erstellt eine übersprungene Epoche"""
        return EpochResult(
            epoch_id=epoch_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
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
            optimal_threshold=self.config.min_pullback_score,
            is_valid=False,
            skip_reason=reason,
        )

    def _extract_metrics(self, backtest_result: BacktestResult) -> Dict[str, float]:
        """Extrahiert relevante Metriken aus BacktestResult"""
        trades = backtest_result.trades

        if not trades:
            return {
                "trades": 0,
                "win_rate": 0,
                "sharpe": 0,
                "profit_factor": 0,
                "avg_pnl": 0,
            }

        return {
            "trades": backtest_result.total_trades,
            "win_rate": backtest_result.win_rate,
            "sharpe": backtest_result.sharpe_ratio,
            "profit_factor": backtest_result.profit_factor,
            "avg_pnl": backtest_result.total_pnl / backtest_result.total_trades
            if backtest_result.total_trades > 0 else 0,
        }

    def _calculate_overfit_score(
        self,
        win_rate_degradation: float,
        sharpe_degradation: float,
    ) -> float:
        """
        Berechnet Overfit-Score (0-1).

        Kombiniert Win-Rate und Sharpe Degradation.
        """
        # Normalisiere Degradationen
        wr_factor = min(abs(win_rate_degradation) / 20.0, 1.0)  # 20% = max
        sharpe_factor = min(abs(sharpe_degradation) / 1.0, 1.0)  # 1.0 = max

        # Gewichteter Durchschnitt (Win Rate wichtiger)
        return 0.7 * wr_factor + 0.3 * sharpe_factor

    def _aggregate_results(
        self,
        training_id: str,
        training_date: datetime,
        epochs: List[EpochResult],
        warnings: List[str],
    ) -> TrainingResult:
        """Aggregiert Ergebnisse aller Epochen"""
        valid_epochs = [e for e in epochs if e.is_valid]
        n_valid = len(valid_epochs)

        if n_valid == 0:
            warnings.append("Keine gültigen Epochen für Aggregation!")
            return TrainingResult(
                training_id=training_id,
                training_date=training_date,
                config=self.config,
                epochs=epochs,
                valid_epochs=0,
                total_epochs=len(epochs),
                avg_in_sample_win_rate=0,
                avg_in_sample_sharpe=0,
                avg_out_sample_win_rate=0,
                avg_out_sample_sharpe=0,
                avg_win_rate_degradation=0,
                max_win_rate_degradation=0,
                overfit_severity="severe",
                recommended_min_score=self.config.min_pullback_score,
                top_predictors=[],
                component_weights={},
                regime_adjustments={},
                warnings=warnings,
            )

        # In-Sample Durchschnitte
        avg_in_sample_win_rate = sum(e.in_sample_win_rate for e in valid_epochs) / n_valid
        avg_in_sample_sharpe = sum(e.in_sample_sharpe for e in valid_epochs) / n_valid

        # Out-of-Sample Durchschnitte
        avg_out_sample_win_rate = sum(e.out_sample_win_rate for e in valid_epochs) / n_valid
        avg_out_sample_sharpe = sum(e.out_sample_sharpe for e in valid_epochs) / n_valid

        # Degradation
        avg_win_rate_degradation = avg_in_sample_win_rate - avg_out_sample_win_rate
        max_win_rate_degradation = max(e.win_rate_degradation for e in valid_epochs)

        # Overfit-Severity
        overfit_severity = self._classify_overfit_severity(avg_win_rate_degradation)

        # Empfehlungen aggregieren
        recommended_min_score = self._aggregate_threshold(valid_epochs)
        top_predictors = self._aggregate_predictors(valid_epochs)
        component_weights = self._aggregate_component_weights(valid_epochs)
        regime_adjustments = self._aggregate_regime_adjustments(valid_epochs)

        # Warnungen für Overfit
        if overfit_severity == "moderate":
            warnings.append(
                f"Moderate Overfitting erkannt ({avg_win_rate_degradation:.1f}% Degradation). "
                "Empfehlung: Konservativere Parameter verwenden."
            )
        elif overfit_severity == "severe":
            warnings.append(
                f"Schweres Overfitting erkannt ({avg_win_rate_degradation:.1f}% Degradation). "
                "WARNUNG: Strategie ist möglicherweise nicht produktionsreif!"
            )

        return TrainingResult(
            training_id=training_id,
            training_date=training_date,
            config=self.config,
            epochs=epochs,
            valid_epochs=n_valid,
            total_epochs=len(epochs),
            avg_in_sample_win_rate=avg_in_sample_win_rate,
            avg_in_sample_sharpe=avg_in_sample_sharpe,
            avg_out_sample_win_rate=avg_out_sample_win_rate,
            avg_out_sample_sharpe=avg_out_sample_sharpe,
            avg_win_rate_degradation=avg_win_rate_degradation,
            max_win_rate_degradation=max_win_rate_degradation,
            overfit_severity=overfit_severity,
            recommended_min_score=recommended_min_score,
            top_predictors=top_predictors,
            component_weights=component_weights,
            regime_adjustments=regime_adjustments,
            warnings=warnings,
        )

    def _classify_overfit_severity(self, degradation: float) -> str:
        """Klassifiziert Overfit-Severity"""
        abs_deg = abs(degradation)

        if abs_deg < self.OVERFIT_THRESHOLDS["none"]:
            return "none"
        elif abs_deg < self.OVERFIT_THRESHOLDS["mild"]:
            return "mild"
        elif abs_deg < self.OVERFIT_THRESHOLDS["moderate"]:
            return "moderate"
        else:
            return "severe"

    def _aggregate_threshold(self, epochs: List[EpochResult]) -> float:
        """Aggregiert optimalen Threshold aus allen Epochen"""
        if not epochs:
            return self.config.min_pullback_score

        thresholds = [e.optimal_threshold for e in epochs]

        # Konservativer Ansatz: 75. Perzentil
        sorted_thresholds = sorted(thresholds)
        idx = int(len(sorted_thresholds) * 0.75)
        return sorted_thresholds[min(idx, len(sorted_thresholds) - 1)]

    def _aggregate_predictors(self, epochs: List[EpochResult]) -> List[str]:
        """Aggregiert Top-Predictors aus allen Epochen"""
        from collections import Counter

        predictor_counts: Counter = Counter()

        for epoch in epochs:
            if epoch.validation_result and epoch.validation_result.top_predictors:
                for pred in epoch.validation_result.top_predictors[:3]:
                    predictor_counts[pred] += 1

        return [pred for pred, _ in predictor_counts.most_common(5)]

    def _aggregate_component_weights(
        self,
        epochs: List[EpochResult],
    ) -> Dict[str, float]:
        """Aggregiert Komponenten-Gewichte"""
        from collections import defaultdict

        weights: Dict[str, List[float]] = defaultdict(list)

        for epoch in epochs:
            if epoch.validation_result:
                for corr in epoch.validation_result.component_correlations:
                    if corr.predictive_power in ("strong", "moderate"):
                        weights[corr.component_name].append(
                            abs(corr.win_rate_correlation)
                        )

        # Durchschnitt pro Komponente
        return {
            comp: sum(vals) / len(vals)
            for comp, vals in weights.items()
            if vals
        }

    def _aggregate_regime_adjustments(
        self,
        epochs: List[EpochResult],
    ) -> Dict[str, Dict[str, float]]:
        """Aggregiert Regime-Adjustments"""
        from collections import defaultdict

        adjustments: Dict[str, List[float]] = defaultdict(list)

        for epoch in epochs:
            if epoch.validation_result:
                for regime, adj in epoch.validation_result.regime_sensitivity.items():
                    adjustments[regime].append(adj)

        return {
            regime: {"win_rate_adjustment": sum(vals) / len(vals)}
            for regime, vals in adjustments.items()
            if vals
        }

    def _get_data_range(
        self,
        historical_data: Dict[str, List[Dict]],
        symbols: List[str],
    ) -> Tuple[Optional[date], Optional[date]]:
        """Ermittelt den Datenbereich aus historischen Daten"""
        all_dates = []

        for symbol in symbols:
            if symbol not in historical_data:
                continue

            for bar in historical_data[symbol]:
                bar_date = bar.get("date")
                if isinstance(bar_date, str):
                    bar_date = date.fromisoformat(bar_date)
                if bar_date:
                    all_dates.append(bar_date)

        if not all_dates:
            return None, None

        return min(all_dates), max(all_dates)

    # =========================================================================
    # Persistenz
    # =========================================================================

    def save(
        self,
        result: TrainingResult,
        filepath: Optional[str] = None,
    ) -> str:
        """
        Speichert TrainingResult als JSON.

        Args:
            result: Zu speicherndes Ergebnis
            filepath: Optional: Pfad zum Speichern (sonst Default)

        Returns:
            Vollständiger Pfad der gespeicherten Datei
        """
        if filepath is None:
            models_dir = Path.home() / ".optionplay" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            filepath = str(models_dir / f"{result.training_id}.json")
        else:
            filepath = os.path.expanduser(filepath)
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Training-Ergebnis gespeichert: {filepath}")
        return filepath

    @classmethod
    def load(cls, filepath: str) -> "WalkForwardTrainer":
        """
        Lädt Trainer mit gespeichertem Training-Ergebnis.

        Args:
            filepath: Pfad zur JSON-Datei

        Returns:
            WalkForwardTrainer mit geladenem Ergebnis
        """
        filepath = os.path.expanduser(filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Rekonstruiere Config
        config_data = data.get("config", {})
        config = TrainingConfig(
            train_months=config_data.get("train_months", 18),
            test_months=config_data.get("test_months", 6),
            step_months=config_data.get("step_months", 6),
            min_trades_per_epoch=config_data.get("min_trades_per_epoch", 50),
            min_valid_epochs=config_data.get("min_valid_epochs", 3),
            symbols=config_data.get("symbols"),
            min_pullback_score=config_data.get("min_pullback_score", 5.0),
            profit_target_pct=config_data.get("profit_target_pct", 50.0),
            stop_loss_pct=config_data.get("stop_loss_pct", 200.0),
            dte_min=config_data.get("dte_min", 45),
            dte_max=config_data.get("dte_max", 75),
        )

        trainer = cls(config)

        # Rekonstruiere TrainingResult (vereinfacht, ohne volle Epochs)
        summary = data.get("summary", {})
        recommendations = data.get("recommendations", {})

        trainer._last_result = TrainingResult(
            training_id=data.get("training_id", "loaded"),
            training_date=datetime.fromisoformat(
                data.get("training_date", datetime.now().isoformat())
            ),
            config=config,
            epochs=[],  # Epochen werden nicht vollständig rekonstruiert
            valid_epochs=summary.get("valid_epochs", 0),
            total_epochs=summary.get("total_epochs", 0),
            avg_in_sample_win_rate=summary.get("avg_in_sample_win_rate", 0),
            avg_in_sample_sharpe=summary.get("avg_in_sample_sharpe", 0),
            avg_out_sample_win_rate=summary.get("avg_out_sample_win_rate", 0),
            avg_out_sample_sharpe=summary.get("avg_out_sample_sharpe", 0),
            avg_win_rate_degradation=summary.get("avg_win_rate_degradation", 0),
            max_win_rate_degradation=summary.get("max_win_rate_degradation", 0),
            overfit_severity=summary.get("overfit_severity", "unknown"),
            recommended_min_score=recommendations.get("min_score", 5.0),
            top_predictors=recommendations.get("top_predictors", []),
            component_weights=recommendations.get("component_weights", {}),
            regime_adjustments=recommendations.get("regime_adjustments", {}),
            warnings=data.get("warnings", []),
        )

        logger.info(f"Training-Ergebnis geladen: {filepath}")
        return trainer

    # =========================================================================
    # Produktions-Methoden
    # =========================================================================

    def get_signal_reliability(
        self,
        score: float,
        vix: Optional[float] = None,
    ) -> SignalReliability:
        """
        Bewertet Signal-Reliability basierend auf Training-Ergebnissen.

        Args:
            score: Pullback-Score
            vix: Optional: Aktueller VIX

        Returns:
            SignalReliability Bewertung
        """
        if self._last_result is None:
            raise ValueError(
                "Keine Training-Ergebnisse verfügbar. "
                "Bitte zuerst train_sync() oder load() aufrufen."
            )

        result = self._last_result

        # Regime-Adjustment ermitteln
        regime_adjustment = 0.0
        regime_context = None

        if vix is not None:
            regime = self._get_regime_for_vix(vix)
            regime_context = f"VIX={vix:.1f} ({regime})"

            if regime in result.regime_adjustments:
                regime_adjustment = result.regime_adjustments[regime].get(
                    "win_rate_adjustment", 0
                )

        # Base Win Rate aus Training
        base_win_rate = result.avg_out_sample_win_rate
        adjusted_win_rate = base_win_rate + regime_adjustment

        # Confidence Interval (konservativ aus Out-of-Sample)
        # Vereinfacht: ±5% basierend auf Epochen-Varianz
        ci_margin = 5.0
        ci_lower = max(0, adjusted_win_rate - ci_margin)
        ci_upper = min(100, adjusted_win_rate + ci_margin)

        # Grade basierend auf CI-Untergrenze
        grade = self._determine_grade(ci_lower)

        # Component Strengths (vereinfacht)
        component_strengths = {}
        if result.component_weights:
            for comp, weight in result.component_weights.items():
                if weight >= 0.3:
                    component_strengths[comp] = "strong"
                elif weight >= 0.15:
                    component_strengths[comp] = "moderate"
                else:
                    component_strengths[comp] = "weak"

        warnings = []
        if score < result.recommended_min_score:
            warnings.append(
                f"Score {score:.1f} liegt unter empfohlenem Minimum "
                f"({result.recommended_min_score:.1f})."
            )

        if result.overfit_severity in ("moderate", "severe"):
            warnings.append(
                f"Training zeigt {result.overfit_severity} Overfitting. "
                "Empfehlungen mit Vorsicht verwenden."
            )

        return SignalReliability(
            score=score,
            score_bucket=self._get_bucket_label(score),
            historical_win_rate=adjusted_win_rate,
            confidence_interval=(ci_lower, ci_upper),
            expected_pnl_range=(0, 0),  # Nicht verfügbar ohne detaillierte Daten
            regime_context=regime_context,
            component_strengths=component_strengths,
            reliability_grade=grade,
            sample_size=result.valid_epochs * self.config.min_trades_per_epoch,
            warnings=warnings,
        )

    def should_trade(
        self,
        score: float,
        vix: Optional[float] = None,
        min_grade: str = "C",
    ) -> Tuple[bool, str]:
        """
        Schnelle Prüfung ob ein Trade empfohlen wird.

        Args:
            score: Pullback-Score
            vix: Optional: Aktueller VIX
            min_grade: Mindest-Grade für Trade ("A", "B", "C", "D")

        Returns:
            Tuple von (should_trade, reason)
        """
        if self._last_result is None:
            return False, "Keine Training-Ergebnisse verfügbar."

        result = self._last_result

        # Score-Check
        if score < result.recommended_min_score:
            return False, f"Score {score:.1f} unter Minimum ({result.recommended_min_score:.1f})"

        # Reliability-Check
        reliability = self.get_signal_reliability(score, vix)

        grade_order = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
        if grade_order.get(reliability.reliability_grade, 0) < grade_order.get(min_grade, 3):
            return False, f"Grade {reliability.reliability_grade} unter Minimum ({min_grade})"

        # Overfit-Warning
        if result.overfit_severity == "severe":
            return False, "Schweres Overfitting erkannt - Trade nicht empfohlen"

        return True, f"Trade empfohlen (Grade: {reliability.reliability_grade})"

    def _get_regime_for_vix(self, vix: float) -> str:
        """Ermittelt VIX-Regime"""
        if vix < 15:
            return "low_vol"
        elif vix < 20:
            return "normal"
        elif vix < 30:
            return "elevated"
        else:
            return "high_vol"

    def _get_bucket_label(self, score: float) -> str:
        """Ermittelt Bucket-Label für Score"""
        buckets = [
            (0, 5, "0-5"),
            (5, 7, "5-7"),
            (7, 9, "7-9"),
            (9, 11, "9-11"),
            (11, 16, "11-16"),
        ]

        for low, high, label in buckets:
            if low <= score < high:
                return label

        return "unknown"

    def _determine_grade(self, ci_lower: float) -> str:
        """Bestimmt Grade basierend auf CI-Untergrenze"""
        if ci_lower >= 70:
            return "A"
        elif ci_lower >= 60:
            return "B"
        elif ci_lower >= 50:
            return "C"
        elif ci_lower >= 40:
            return "D"
        else:
            return "F"


# =============================================================================
# Utility Functions
# =============================================================================

def format_training_summary(result: TrainingResult) -> str:
    """Formatiert TrainingResult als lesbaren Summary"""
    return result.summary()
