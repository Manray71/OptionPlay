#!/usr/bin/env python3
from __future__ import annotations

"""
Reliability Scoring Module - Phase 3 des Hochverlässlichkeits-Frameworks

Kombiniert Signal Validation und Walk-Forward Training zu einem
produktionsreifen Reliability-System für Echtzeit-Empfehlungen.

Dieses Modul ist die Schnittstelle für den Scanner/Analyzer und liefert:
- Reliability Grades (A-F) basierend auf historischer Performance
- Confidence Intervals für Win Rates
- Regime-adjustierte Empfehlungen
- Komponenten-basierte Stärkenanalyse

Verwendung:
    from src.backtesting import ReliabilityScorer

    # Initialisieren (lädt trainiertes Modell)
    scorer = ReliabilityScorer.from_trained_model("~/.optionplay/models/latest.json")

    # Für jeden Scanner-Kandidaten
    result = scorer.score(
        pullback_score=8.5,
        score_breakdown=candidate.score_breakdown.to_dict(),
        vix=current_vix,
    )

    if result.should_trade:
        print(f"✓ Trade empfohlen: Grade {result.grade}")
    else:
        print(f"✗ Nicht empfohlen: {result.rejection_reason}")
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ...constants.trading_rules import VIX_ELEVATED_MAX, VIX_LOW_VOL_MAX, VIX_NORMAL_MAX

if TYPE_CHECKING:
    from ..training import TrainingConfig, TrainingResult

from .signal_validation import (
    SignalReliability,
    SignalValidationResult,
    SignalValidator,
    StatisticalCalculator,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Result Data Classes
# =============================================================================


@dataclass
class ReliabilityResult:
    """
    Vollständiges Reliability-Ergebnis für einen Kandidaten.

    Kombiniert alle Informationen für Trade-Entscheidung.
    """

    # Identifikation
    score: float
    timestamp: datetime = field(default_factory=datetime.now)

    # Trade-Empfehlung
    should_trade: bool = False
    grade: str = "F"  # A, B, C, D, F
    rejection_reason: Optional[str] = None

    # Historische Performance
    historical_win_rate: float = 0.0
    confidence_interval: Tuple[float, float] = (0.0, 0.0)
    sample_size: int = 0

    # Regime-Kontext
    vix: Optional[float] = None
    regime: Optional[str] = None
    regime_adjustment: float = 0.0  # Win Rate Adjustment

    # Komponenten-Analyse
    component_strengths: Dict[str, str] = field(default_factory=dict)
    weak_components: List[str] = field(default_factory=list)
    strong_components: List[str] = field(default_factory=list)

    # Overfitting-Warnung
    overfit_warning: bool = False
    overfit_severity: str = "none"

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "score": self.score,
            "timestamp": self.timestamp.isoformat(),
            "recommendation": {
                "should_trade": self.should_trade,
                "grade": self.grade,
                "rejection_reason": self.rejection_reason,
            },
            "historical_performance": {
                "win_rate": round(self.historical_win_rate, 1),
                "confidence_interval": (
                    round(self.confidence_interval[0], 1),
                    round(self.confidence_interval[1], 1),
                ),
                "sample_size": self.sample_size,
            },
            "regime_context": {
                "vix": self.vix,
                "regime": self.regime,
                "adjustment": round(self.regime_adjustment, 1),
            },
            "components": {
                "strengths": self.component_strengths,
                "weak": self.weak_components,
                "strong": self.strong_components,
            },
            "overfitting": {
                "warning": self.overfit_warning,
                "severity": self.overfit_severity,
            },
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        """Kurze Zusammenfassung für CLI-Output"""
        icon = "✓" if self.should_trade else "✗"
        ci_low, ci_high = self.confidence_interval

        lines = [
            f"{icon} Grade: {self.grade} | "
            f"Win Rate: {self.historical_win_rate:.0f}% "
            f"[{ci_low:.0f}-{ci_high:.0f}%] | "
            f"n={self.sample_size}"
        ]

        if self.regime:
            lines[0] += f" | {self.regime}"

        if not self.should_trade and self.rejection_reason:
            lines.append(f"  Grund: {self.rejection_reason}")

        if self.warnings:
            for w in self.warnings[:2]:
                lines.append(f"  ⚠ {w}")

        return "\n".join(lines)


@dataclass
class ScorerConfig:
    """Konfiguration für ReliabilityScorer"""

    # Grade-Schwellenwerte (CI-Untergrenze)
    grade_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "A": 70.0,
            "B": 60.0,
            "C": 50.0,
            "D": 40.0,
        }
    )

    # Mindest-Grade für Trade-Empfehlung
    min_grade_for_trade: str = "C"

    # Mindest-Score
    min_score: float = 5.0

    # Mindest-Sample-Size für Vertrauen
    min_sample_size: int = 30

    # Regime-Adjustments aktivieren
    use_regime_adjustments: bool = True

    # Komponenten-Analyse aktivieren
    analyze_components: bool = True

    # Overfit-Warnung ausgeben
    warn_on_overfit: bool = True
    max_overfit_severity: str = "moderate"  # "none", "mild", "moderate", "severe"

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "grade_thresholds": self.grade_thresholds,
            "min_grade_for_trade": self.min_grade_for_trade,
            "min_score": self.min_score,
            "min_sample_size": self.min_sample_size,
            "use_regime_adjustments": self.use_regime_adjustments,
            "analyze_components": self.analyze_components,
            "warn_on_overfit": self.warn_on_overfit,
            "max_overfit_severity": self.max_overfit_severity,
        }


# =============================================================================
# Reliability Scorer
# =============================================================================


class ReliabilityScorer:
    """
    Zentraler Scorer für Reliability-basierte Trade-Empfehlungen.

    Kombiniert:
    - Walk-Forward Training Results
    - Signal Validation
    - VIX-Regime Adjustments
    - Komponenten-Analyse
    """

    # Grade-Reihenfolge für Vergleiche
    GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}

    def __init__(
        self,
        config: Optional[ScorerConfig] = None,
        training_result: Optional[TrainingResult] = None,
        validation_result: Optional[SignalValidationResult] = None,
    ) -> None:
        """
        Initialisiert den Scorer.

        Args:
            config: Scorer-Konfiguration (oder Default)
            training_result: Optional: Vortrainiertes Modell
            validation_result: Optional: Signal-Validierung
        """
        self.config = config or ScorerConfig()
        self._training_result = training_result
        self._validation_result = validation_result

        # Cached Lookups
        self._component_weights: Dict[str, float] = {}
        self._regime_adjustments: Dict[str, float] = {}
        self._recommended_min_score: float = self.config.min_score

        if training_result:
            self._load_from_training(training_result)

    def _load_from_training(self, result: TrainingResult) -> None:
        """Lädt Konfiguration aus Training-Ergebnis"""
        self._component_weights = result.component_weights.copy()
        self._regime_adjustments = {
            regime: adj.get("win_rate_adjustment", 0.0)
            for regime, adj in result.regime_adjustments.items()
        }
        self._recommended_min_score = result.recommended_min_score

        logger.info(
            f"Loaded training result: {result.training_id} "
            f"(min_score={self._recommended_min_score:.1f}, "
            f"overfit={result.overfit_severity})"
        )

    @classmethod
    def from_trained_model(
        cls,
        model_path: str,
        config: Optional[ScorerConfig] = None,
    ) -> "ReliabilityScorer":
        """
        Erstellt Scorer aus gespeichertem Trainings-Modell.

        Args:
            model_path: Pfad zur JSON-Datei
            config: Optional: Custom Konfiguration

        Returns:
            Initialisierter ReliabilityScorer
        """
        model_path = os.path.expanduser(model_path)

        if not Path(model_path).exists():
            logger.warning(f"Model not found: {model_path}. Using defaults.")
            return cls(config=config)

        from ..training import WalkForwardTrainer  # Lazy import (CIRC-01)

        trainer = WalkForwardTrainer.load(model_path)

        return cls(
            config=config,
            training_result=trainer._last_result,
        )

    @classmethod
    def from_backtest(
        cls,
        backtest_result: Any,
        config: Optional[ScorerConfig] = None,
    ) -> "ReliabilityScorer":
        """
        Erstellt Scorer direkt aus Backtest-Ergebnis (ohne Training).

        Nützlich für schnelle Validierung ohne vollständiges Walk-Forward.

        Args:
            backtest_result: BacktestResult mit Trades
            config: Optional: Custom Konfiguration

        Returns:
            Initialisierter ReliabilityScorer
        """
        validator = SignalValidator()
        validation = validator.validate(backtest_result)

        return cls(
            config=config,
            validation_result=validation,
        )

    def score(
        self,
        pullback_score: float,
        score_breakdown: Optional[Dict[str, Any]] = None,
        vix: Optional[float] = None,
    ) -> ReliabilityResult:
        """
        Bewertet einen Kandidaten und gibt Trade-Empfehlung.

        Args:
            pullback_score: Gesamt-Pullback-Score (0-16)
            score_breakdown: Optional: ScoreBreakdown.to_dict() für Komponenten
            vix: Optional: Aktueller VIX für Regime-Adjustment

        Returns:
            ReliabilityResult mit Empfehlung
        """
        warnings = []
        rejection_reason = None

        # 1. Score-Check
        effective_min_score = max(self.config.min_score, self._recommended_min_score)

        if pullback_score < effective_min_score:
            return ReliabilityResult(
                score=pullback_score,
                should_trade=False,
                grade="F",
                rejection_reason=f"Score {pullback_score:.1f} unter Minimum ({effective_min_score:.1f})",
            )

        # 2. Basis-Metriken ermitteln
        base_win_rate, sample_size = self._get_base_metrics(pullback_score)

        # 3. Regime-Adjustment
        regime = None
        regime_adjustment = 0.0

        if vix is not None and self.config.use_regime_adjustments:
            regime = self._get_regime(vix)
            regime_adjustment = self._regime_adjustments.get(regime, 0.0)

            if abs(regime_adjustment) > 5:
                warnings.append(
                    f"Regime {regime} zeigt {regime_adjustment:+.0f}% Win-Rate-Abweichung"
                )

        adjusted_win_rate = base_win_rate + regime_adjustment

        # 4. Confidence Interval
        ci_lower, ci_upper = self._calculate_confidence_interval(adjusted_win_rate, sample_size)

        # 5. Grade bestimmen
        grade = self._determine_grade(ci_lower, sample_size)

        # 6. Komponenten-Analyse
        component_strengths = {}
        weak_components = []
        strong_components = []

        if score_breakdown and self.config.analyze_components:
            component_strengths, weak_components, strong_components = self._analyze_components(
                score_breakdown
            )

            if len(weak_components) >= 3:
                warnings.append(f"Mehrere schwache Komponenten: {', '.join(weak_components[:3])}")

        # 7. Overfit-Check
        overfit_warning = False
        overfit_severity = "none"

        if self._training_result:
            overfit_severity = self._training_result.overfit_severity

            if self.config.warn_on_overfit:
                severity_order = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}
                max_allowed = severity_order.get(self.config.max_overfit_severity, 2)
                actual = severity_order.get(overfit_severity, 0)

                if actual > max_allowed:
                    overfit_warning = True
                    warnings.append(
                        f"Overfitting-Warnung: {overfit_severity} "
                        "(Empfehlungen mit Vorsicht verwenden)"
                    )

        # 8. Trade-Entscheidung
        should_trade = True

        # Grade-Check
        min_grade_value = self.GRADE_ORDER.get(self.config.min_grade_for_trade, 3)
        actual_grade_value = self.GRADE_ORDER.get(grade, 1)

        if actual_grade_value < min_grade_value:
            should_trade = False
            rejection_reason = f"Grade {grade} unter Minimum ({self.config.min_grade_for_trade})"

        # Sample-Size Check
        if sample_size < self.config.min_sample_size:
            warnings.append(
                f"Nur {sample_size} historische Trades "
                f"(empfohlen: {self.config.min_sample_size})"
            )

        # Severe Overfit Block
        if overfit_severity == "severe":
            should_trade = False
            rejection_reason = "Schweres Overfitting - Trade nicht empfohlen"

        return ReliabilityResult(
            score=pullback_score,
            should_trade=should_trade,
            grade=grade,
            rejection_reason=rejection_reason,
            historical_win_rate=adjusted_win_rate,
            confidence_interval=(ci_lower, ci_upper),
            sample_size=sample_size,
            vix=vix,
            regime=regime,
            regime_adjustment=regime_adjustment,
            component_strengths=component_strengths,
            weak_components=weak_components,
            strong_components=strong_components,
            overfit_warning=overfit_warning,
            overfit_severity=overfit_severity,
            warnings=warnings,
        )

    def score_batch(
        self,
        candidates: List[Dict[str, Any]],
        vix: Optional[float] = None,
    ) -> List[Tuple[Dict[str, Any], ReliabilityResult]]:
        """
        Bewertet mehrere Kandidaten.

        Args:
            candidates: Liste von Kandidaten-Dicts mit 'score' und optional 'score_breakdown'
            vix: Aktueller VIX (für alle gleich)

        Returns:
            Liste von (candidate, result) Tupeln, sortiert nach Grade
        """
        results = []

        for candidate in candidates:
            score = candidate.get("score", 0)
            breakdown = candidate.get("score_breakdown")

            result = self.score(
                pullback_score=score,
                score_breakdown=breakdown,
                vix=vix,
            )

            results.append((candidate, result))

        # Sortiere: should_trade first, dann nach Grade, dann nach Score
        def sort_key(item) -> Tuple[bool, int, float]:
            _, result = item
            return (
                not result.should_trade,  # True trades first
                -self.GRADE_ORDER.get(result.grade, 0),  # Higher grade first
                -result.score,  # Higher score first
            )

        return sorted(results, key=sort_key)

    def get_recommendation_summary(
        self,
        results: List[Tuple[Dict[str, Any], ReliabilityResult]],
    ) -> str:
        """
        Formatiert Empfehlungs-Summary für CLI.

        Args:
            results: Output von score_batch()

        Returns:
            Formatierter String
        """
        tradeable = [(c, r) for c, r in results if r.should_trade]
        rejected = [(c, r) for c, r in results if not r.should_trade]

        lines = [
            "",
            "=" * 60,
            f"  RELIABILITY ASSESSMENT: {len(tradeable)}/{len(results)} empfohlen",
            "=" * 60,
        ]

        if tradeable:
            lines.append("")
            lines.append("  EMPFOHLEN:")
            for candidate, result in tradeable[:10]:
                symbol = candidate.get("symbol", "???")
                lines.append(
                    f"    {symbol:6s} | Score: {result.score:5.1f} | "
                    f"Grade: {result.grade} | "
                    f"Win: {result.historical_win_rate:.0f}%"
                )

        if rejected:
            lines.append("")
            lines.append("  ABGELEHNT:")
            for candidate, result in rejected[:5]:
                symbol = candidate.get("symbol", "???")
                reason = result.rejection_reason or "unbekannt"
                lines.append(f"    {symbol:6s} | {reason}")

        lines.append("=" * 60)
        return "\n".join(lines)

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _get_base_metrics(
        self,
        score: float,
    ) -> Tuple[float, int]:
        """
        Ermittelt Basis-Metriken für einen Score.

        Returns:
            Tuple von (win_rate, sample_size)
        """
        # Priorität 1: Training Result
        if self._training_result:
            return (
                self._training_result.avg_out_sample_win_rate,
                self._training_result.valid_epochs
                * self._training_result.config.min_trades_per_epoch,
            )

        # Priorität 2: Validation Result mit Bucket-Lookup
        if self._validation_result:
            for bucket in self._validation_result.score_buckets:
                low, high = bucket.bucket_range
                if low <= score < high:
                    return (bucket.win_rate, bucket.trade_count)

            # Fallback auf Gesamt-Rate
            return (
                self._validation_result.overall_win_rate,
                self._validation_result.trades_with_scores,
            )

        # Kein Training/Validation: Default
        return (50.0, 0)

    def _calculate_confidence_interval(
        self,
        win_rate: float,
        sample_size: int,
    ) -> Tuple[float, float]:
        """Berechnet 95% Confidence Interval für Win Rate"""
        if sample_size == 0:
            return (0.0, 100.0)

        # Konvertiere Win Rate zu Wins
        wins = int(win_rate * sample_size / 100)

        return StatisticalCalculator.wilson_confidence_interval(wins, sample_size, confidence=0.95)

    def _determine_grade(self, ci_lower: float, sample_size: int) -> str:
        """Bestimmt Grade basierend auf CI-Untergrenze"""
        if sample_size < 10:
            return "F"

        thresholds = self.config.grade_thresholds

        if ci_lower >= thresholds.get("A", 70):
            return "A"
        elif ci_lower >= thresholds.get("B", 60):
            return "B"
        elif ci_lower >= thresholds.get("C", 50):
            return "C"
        elif ci_lower >= thresholds.get("D", 40):
            return "D"
        else:
            return "F"

    def _get_regime(self, vix: float) -> str:
        """Ermittelt VIX-Regime"""
        if vix < VIX_LOW_VOL_MAX:
            return "low_vol"
        elif vix < VIX_NORMAL_MAX:
            return "normal"
        elif vix < VIX_ELEVATED_MAX:
            return "elevated"
        else:
            return "high_vol"

    def _analyze_components(
        self,
        breakdown: Dict[str, Any],
    ) -> Tuple[Dict[str, str], List[str], List[str]]:
        """
        Analysiert Komponenten-Stärken.

        Returns:
            Tuple von (strengths_dict, weak_list, strong_list)
        """
        strengths = {}
        weak = []
        strong = []

        # Extrahiere Komponenten-Scores
        components = breakdown.get("components", breakdown)

        # Mapping von Komponenten zu ihren Max-Werten
        max_scores = {
            "rsi": 2.0,
            "support": 3.0,
            "fibonacci": 2.0,
            "ma": 2.0,
            "trend_strength": 2.0,
            "volume": 1.0,
            "macd": 2.0,
            "stoch": 1.0,
            "keltner": 2.0,
        }

        for comp_name, max_score in max_scores.items():
            comp_data = components.get(comp_name, {})

            if isinstance(comp_data, dict):
                score = comp_data.get("score", 0)
            else:
                score = comp_data if isinstance(comp_data, (int, float)) else 0

            # Normalisiere auf 0-1
            if max_score > 0:
                ratio = score / max_score
            else:
                ratio = 0

            # Klassifiziere
            if ratio >= 0.8:
                strengths[comp_name] = "strong"
                strong.append(comp_name)
            elif ratio >= 0.5:
                strengths[comp_name] = "moderate"
            elif ratio > 0:
                strengths[comp_name] = "weak"
                weak.append(comp_name)
            else:
                strengths[comp_name] = "none"
                weak.append(comp_name)

        return strengths, weak, strong


# =============================================================================
# Utility Functions
# =============================================================================


def create_scorer_from_latest_model(
    models_dir: str = "~/.optionplay/models",
) -> ReliabilityScorer:
    """
    Erstellt Scorer aus dem neuesten Modell im Verzeichnis.

    Args:
        models_dir: Verzeichnis mit Modell-Dateien

    Returns:
        Initialisierter ReliabilityScorer
    """
    models_dir = Path(os.path.expanduser(models_dir))

    if not models_dir.exists():
        logger.warning(f"Models directory not found: {models_dir}")
        return ReliabilityScorer()

    # Finde neueste Datei
    model_files = list(models_dir.glob("wf_*.json"))

    if not model_files:
        logger.warning(f"No model files found in {models_dir}")
        return ReliabilityScorer()

    latest = max(model_files, key=lambda p: p.stat().st_mtime)

    return ReliabilityScorer.from_trained_model(str(latest))


def format_reliability_badge(result: ReliabilityResult) -> str:
    """
    Formatiert ein kompaktes Badge für CLI/Terminal.

    Returns:
        String wie "[A] 72% ±5"
    """
    ci_low, ci_high = result.confidence_interval
    margin = (ci_high - ci_low) / 2

    return f"[{result.grade}] {result.historical_win_rate:.0f}% ±{margin:.0f}"
