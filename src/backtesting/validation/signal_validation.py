#!/usr/bin/env python3
"""
Signal Validation Module - Phase 1 des Hochverlässlichkeits-Frameworks

Analysiert die historische Korrelation zwischen Pullback-Scores und Trade-Outcomes,
um "Reliability Scores" für neue Empfehlungen zu ermöglichen.

Verwendung:
    from src.backtesting import SignalValidator, BacktestResult

    # Nach Backtest
    validator = SignalValidator()
    result = validator.validate(backtest_result)

    # Reliability für neue Empfehlung
    reliability = validator.get_reliability(score=9.5, vix=18.5)
    print(f"Grade: {reliability.reliability_grade}")

Implementation split across:
    - signal_validation.py  (this file) — Dataclasses, SignalValidator orchestrator,
                                          format_reliability_report utility
    - statistical_calc.py   — StatisticalCalculator (Wilson CI, Pearson, Sharpe, etc.)
    - score_analysis.py     — ScoreAnalysisMixin (bucket analysis, regime analysis)
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Dict, Optional, Tuple, Any

# Re-export StatisticalCalculator from sub-module
from .statistical_calc import StatisticalCalculator
# Import mixin with analysis methods
from .score_analysis import ScoreAnalysisMixin

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ScoreBucketStats:
    """Statistiken für einen Score-Bucket"""
    bucket_range: Tuple[float, float]  # z.B. (7.0, 9.0)
    bucket_label: str  # z.B. "7-9"
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float  # Prozent
    avg_pnl: float
    median_pnl: float
    std_pnl: float
    sharpe_ratio: float
    profit_factor: float
    max_win: float
    max_loss: float
    avg_hold_days: float
    confidence_interval: Tuple[float, float]  # 95% CI für Win Rate
    is_statistically_significant: bool  # >= MIN_TRADES

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "bucket_range": self.bucket_range,
            "bucket_label": self.bucket_label,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(self.win_rate, 1),
            "avg_pnl": round(self.avg_pnl, 2),
            "median_pnl": round(self.median_pnl, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "profit_factor": round(self.profit_factor, 2),
            "confidence_interval": (
                round(self.confidence_interval[0], 1),
                round(self.confidence_interval[1], 1),
            ),
            "is_statistically_significant": self.is_statistically_significant,
        }


@dataclass
class ComponentCorrelation:
    """Korrelationsanalyse für eine einzelne Score-Komponente"""
    component_name: str  # z.B. "rsi_score"
    sample_size: int
    win_rate_correlation: float  # Pearson Korrelation mit Win/Loss
    pnl_correlation: float  # Pearson Korrelation mit P&L
    avg_value_winners: float  # Durchschnittswert bei Gewinnern
    avg_value_losers: float  # Durchschnittswert bei Verlierern
    value_difference: float  # avg_winners - avg_losers
    statistical_significance: float  # p-value
    predictive_power: str  # "strong", "moderate", "weak", "none"

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "component_name": self.component_name,
            "sample_size": self.sample_size,
            "win_rate_correlation": round(self.win_rate_correlation, 3),
            "pnl_correlation": round(self.pnl_correlation, 3),
            "avg_value_winners": round(self.avg_value_winners, 2),
            "avg_value_losers": round(self.avg_value_losers, 2),
            "value_difference": round(self.value_difference, 2),
            "predictive_power": self.predictive_power,
        }


@dataclass
class RegimeBucketStats:
    """Statistiken für einen Score-Bucket innerhalb eines VIX-Regimes"""
    regime: str  # "low_vol", "normal", "elevated", "high_vol"
    bucket_stats: ScoreBucketStats
    regime_adjustment: float  # Win Rate Delta vs. Gesamt

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "regime": self.regime,
            "bucket_stats": self.bucket_stats.to_dict(),
            "regime_adjustment": round(self.regime_adjustment, 1),
        }


@dataclass
class SignalReliability:
    """Reliability-Bewertung für ein neues Signal"""
    score: float
    score_bucket: str
    historical_win_rate: float
    confidence_interval: Tuple[float, float]
    expected_pnl_range: Tuple[float, float]  # 25th-75th Perzentil
    regime_context: Optional[str]  # Aktueller Regime-Einfluss
    component_strengths: Dict[str, str]  # Komponente -> "strong"/"weak"
    reliability_grade: str  # "A", "B", "C", "D", "F"
    sample_size: int
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "score": self.score,
            "score_bucket": self.score_bucket,
            "historical_win_rate": round(self.historical_win_rate, 1),
            "confidence_interval": (
                round(self.confidence_interval[0], 1),
                round(self.confidence_interval[1], 1),
            ),
            "expected_pnl_range": (
                round(self.expected_pnl_range[0], 2),
                round(self.expected_pnl_range[1], 2),
            ),
            "regime_context": self.regime_context,
            "component_strengths": self.component_strengths,
            "reliability_grade": self.reliability_grade,
            "sample_size": self.sample_size,
            "warnings": self.warnings,
        }


@dataclass
class SignalValidationResult:
    """Vollständiges Signal-Validierungsergebnis"""
    # Metadaten
    analysis_date: date
    total_trades_analyzed: int
    trades_with_scores: int
    date_range: Tuple[date, date]
    score_coverage: float  # % der Trades mit Score

    # Bucket-Analyse
    score_buckets: List[ScoreBucketStats]
    optimal_threshold: float  # Empfohlener Mindest-Score

    # Komponenten-Analyse
    component_correlations: List[ComponentCorrelation]
    top_predictors: List[str]  # Beste 3 Komponenten

    # Regime-Analyse
    regime_buckets: Dict[str, List[RegimeBucketStats]]
    regime_sensitivity: Dict[str, float]  # Wie stark beeinflusst jedes Regime

    # Summary-Statistiken
    overall_win_rate: float
    overall_sharpe: float
    score_effectiveness: float  # Korrelation Score vs. Outcome

    # Warnungen
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "analysis_date": self.analysis_date.isoformat(),
            "total_trades_analyzed": self.total_trades_analyzed,
            "trades_with_scores": self.trades_with_scores,
            "date_range": (
                self.date_range[0].isoformat(),
                self.date_range[1].isoformat(),
            ),
            "score_coverage": round(self.score_coverage, 1),
            "score_buckets": [b.to_dict() for b in self.score_buckets],
            "optimal_threshold": self.optimal_threshold,
            "component_correlations": [c.to_dict() for c in self.component_correlations],
            "top_predictors": self.top_predictors,
            "regime_buckets": {
                regime: [rb.to_dict() for rb in buckets]
                for regime, buckets in self.regime_buckets.items()
            },
            "regime_sensitivity": {
                k: round(v, 1) for k, v in self.regime_sensitivity.items()
            },
            "overall_win_rate": round(self.overall_win_rate, 1),
            "overall_sharpe": round(self.overall_sharpe, 2),
            "score_effectiveness": round(self.score_effectiveness, 3),
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        """Formatierte Zusammenfassung"""
        lines = [
            "",
            "=" * 60,
            "  SIGNAL VALIDATION REPORT",
            "=" * 60,
            f"  Analysierte Trades:  {self.total_trades_analyzed}",
            f"  Mit Score:           {self.trades_with_scores} ({self.score_coverage:.0f}%)",
            f"  Zeitraum:            {self.date_range[0]} bis {self.date_range[1]}",
            "-" * 60,
            "  SCORE BUCKETS",
            "-" * 60,
        ]

        for bucket in self.score_buckets:
            sig = "*" if bucket.is_statistically_significant else " "
            ci_low, ci_high = bucket.confidence_interval
            lines.append(
                f"  {sig} {bucket.bucket_label:6s}  "
                f"Win: {bucket.win_rate:5.1f}%  "
                f"CI: [{ci_low:.0f}-{ci_high:.0f}%]  "
                f"n={bucket.trade_count:3d}  "
                f"PF: {bucket.profit_factor:.2f}"
            )

        lines.extend([
            "-" * 60,
            f"  Optimaler Schwellenwert: {self.optimal_threshold:.1f}",
            f"  Score-Effektivität:      {self.score_effectiveness:.3f}",
            "-" * 60,
            "  TOP PRÄDIKTOREN",
            "-" * 60,
        ])

        for i, pred in enumerate(self.top_predictors[:3], 1):
            corr = next(
                (c for c in self.component_correlations if c.component_name == pred),
                None
            )
            if corr:
                lines.append(
                    f"  {i}. {pred:20s}  "
                    f"r={corr.win_rate_correlation:+.3f}  "
                    f"({corr.predictive_power})"
                )

        if self.warnings:
            lines.extend([
                "-" * 60,
                "  WARNUNGEN",
                "-" * 60,
            ])
            for warning in self.warnings:
                lines.append(f"  ! {warning}")

        lines.append("=" * 60)
        return "\n".join(lines)


# =============================================================================
# Signal Validator (Orchestrator — analysis methods via ScoreAnalysisMixin)
# =============================================================================

class SignalValidator(ScoreAnalysisMixin):
    """
    Validiert Signal-Zuverlässigkeit basierend auf historischen Trade-Outcomes.

    Verwendet BacktestResult mit TradeResult-Objekten, die pullback_score enthalten.

    Analysis methods inherited from ScoreAnalysisMixin:
        _analyze_score_buckets, _calculate_bucket_stats,
        _analyze_component_correlations, _analyze_by_regime,
        _get_regime_for_vix, _calculate_win_rate, _calculate_overall_sharpe,
        _calculate_score_effectiveness, _find_optimal_threshold,
        _find_bucket_for_score, _calculate_pnl_range,
        _assess_component_strengths, _determine_grade
    """

    # Default Score-Buckets (basierend auf max_score=16)
    DEFAULT_BUCKETS = [
        (0, 5),    # Nicht qualifiziert
        (5, 7),    # Marginal
        (7, 9),    # Gut
        (9, 11),   # Stark
        (11, 16),  # Exzellent
    ]

    # Minimum Trades für statistische Signifikanz
    MIN_TRADES_PER_BUCKET = 30

    # VIX Regime Grenzen
    VIX_REGIMES = {
        "low_vol": (0, 15),
        "normal": (15, 20),
        "elevated": (20, 30),
        "high_vol": (30, 100),
    }

    # Score-Komponenten (aus ScoreBreakdown)
    SCORE_COMPONENTS = [
        "rsi_score",
        "support_score",
        "fibonacci_score",
        "ma_score",
        "trend_strength_score",
        "volume_score",
        "macd_score",
        "stoch_score",
        "keltner_score",
    ]

    def __init__(
        self,
        bucket_ranges: Optional[List[Tuple[float, float]]] = None,
        min_trades_per_bucket: int = 30,
        confidence_level: float = 0.95
    ) -> None:
        """
        Initialisiert den Validator.

        Args:
            bucket_ranges: Custom Score-Buckets, oder None für Default
            min_trades_per_bucket: Minimum für statistische Signifikanz
            confidence_level: Konfidenzlevel für CIs (0.95 = 95%)
        """
        self.bucket_ranges = bucket_ranges or self.DEFAULT_BUCKETS
        self.min_trades_per_bucket = min_trades_per_bucket
        self.confidence_level = confidence_level

        # Cache für letzte Validierung
        self._last_result: Optional[SignalValidationResult] = None
        self._last_trades: Optional[List] = None

    def validate(
        self,
        backtest_result: Any,  # BacktestResult
        include_regime_analysis: bool = True
    ) -> SignalValidationResult:
        """
        Führt vollständige Signal-Validierungs-Analyse durch.

        Args:
            backtest_result: Ergebnis von BacktestEngine mit trades
            include_regime_analysis: Ob VIX-Regime-Analyse durchgeführt werden soll

        Returns:
            SignalValidationResult mit allen Analysen
        """
        trades = backtest_result.trades
        warnings = []

        # Filtere Trades mit gültigem pullback_score
        valid_trades = [t for t in trades if t.pullback_score is not None]
        score_coverage = (len(valid_trades) / len(trades) * 100) if trades else 0

        if score_coverage < 80:
            warnings.append(
                f"Nur {score_coverage:.0f}% der Trades haben Pullback-Scores. "
                "Ergebnisse sind möglicherweise nicht repräsentativ."
            )

        if len(valid_trades) < self.min_trades_per_bucket:
            warnings.append(
                f"Nur {len(valid_trades)} Trades mit Scores. "
                f"Minimum {self.min_trades_per_bucket} empfohlen."
            )

        # Datumsbereich ermitteln
        if trades:
            dates = [t.entry_date for t in trades]
            date_range = (min(dates), max(dates))
        else:
            date_range = (date.today(), date.today())

        # 1. Score Bucket Analyse
        score_buckets = self._analyze_score_buckets(valid_trades)

        # 2. Komponenten-Korrelation
        component_correlations = self._analyze_component_correlations(valid_trades)
        top_predictors = [
            c.component_name for c in component_correlations[:3]
            if c.predictive_power in ("strong", "moderate")
        ]

        # 3. Regime-Analyse
        regime_buckets: Dict[str, List[RegimeBucketStats]] = {}
        regime_sensitivity: Dict[str, float] = {}

        if include_regime_analysis:
            regime_buckets, regime_sensitivity = self._analyze_by_regime(valid_trades)

        # 4. Gesamt-Statistiken
        overall_win_rate = self._calculate_win_rate(valid_trades)
        overall_sharpe = self._calculate_overall_sharpe(valid_trades)
        score_effectiveness = self._calculate_score_effectiveness(valid_trades)

        # 5. Optimalen Schwellenwert finden
        optimal_threshold = self._find_optimal_threshold(score_buckets)

        result = SignalValidationResult(
            analysis_date=date.today(),
            total_trades_analyzed=len(trades),
            trades_with_scores=len(valid_trades),
            date_range=date_range,
            score_coverage=score_coverage,
            score_buckets=score_buckets,
            optimal_threshold=optimal_threshold,
            component_correlations=component_correlations,
            top_predictors=top_predictors,
            regime_buckets=regime_buckets,
            regime_sensitivity=regime_sensitivity,
            overall_win_rate=overall_win_rate,
            overall_sharpe=overall_sharpe,
            score_effectiveness=score_effectiveness,
            warnings=warnings,
        )

        # Cache speichern
        self._last_result = result
        self._last_trades = valid_trades

        return result

    def get_reliability(
        self,
        score: float,
        score_breakdown: Optional[Dict[str, float]] = None,
        vix: Optional[float] = None,
        validation_result: Optional[SignalValidationResult] = None
    ) -> SignalReliability:
        """
        Ermittelt Reliability-Bewertung für ein neues Signal.

        Args:
            score: Pullback-Score des Signals
            score_breakdown: Optional: Komponenten-Breakdown
            vix: Optional: Aktueller VIX für Regime-Kontext
            validation_result: Optional: Validierungsergebnis (sonst cached)

        Returns:
            SignalReliability mit Bewertung
        """
        result = validation_result or self._last_result
        trades = self._last_trades or []

        if result is None:
            raise ValueError(
                "Keine Validierungsergebnisse verfügbar. "
                "Bitte zuerst validate() aufrufen."
            )

        warnings = []

        # Finde passenden Bucket
        bucket = self._find_bucket_for_score(score, result.score_buckets)

        if bucket is None:
            # Kein passender Bucket gefunden
            return SignalReliability(
                score=score,
                score_bucket="unknown",
                historical_win_rate=result.overall_win_rate,
                confidence_interval=(0, 100),
                expected_pnl_range=(0, 0),
                regime_context=None,
                component_strengths={},
                reliability_grade="F",
                sample_size=0,
                warnings=["Kein historischer Bucket für diesen Score gefunden."],
            )

        # Basis-Metriken vom Bucket
        historical_win_rate = bucket.win_rate
        confidence_interval = bucket.confidence_interval
        sample_size = bucket.trade_count

        if not bucket.is_statistically_significant:
            warnings.append(
                f"Nur {sample_size} historische Trades in diesem Bucket. "
                "Statistisch nicht signifikant."
            )

        # P&L Range berechnen (aus historischen Trades im Bucket)
        expected_pnl_range = self._calculate_pnl_range(score, trades)

        # Regime-Kontext
        regime_context = None
        if vix is not None:
            regime = self._get_regime_for_vix(vix)
            regime_context = f"VIX={vix:.1f} ({regime})"

            # Regime-Adjustment wenn verfügbar
            if regime in result.regime_sensitivity:
                adjustment = result.regime_sensitivity[regime]
                if abs(adjustment) > 5:
                    warnings.append(
                        f"Aktuelles Regime ({regime}) zeigt "
                        f"{adjustment:+.0f}% Win-Rate-Abweichung."
                    )

        # Komponenten-Stärken bewerten
        component_strengths = {}
        if score_breakdown:
            component_strengths = self._assess_component_strengths(
                score_breakdown, result.component_correlations
            )

        # Reliability Grade bestimmen
        ci_lower = confidence_interval[0]
        grade = self._determine_grade(ci_lower, sample_size)

        return SignalReliability(
            score=score,
            score_bucket=bucket.bucket_label,
            historical_win_rate=historical_win_rate,
            confidence_interval=confidence_interval,
            expected_pnl_range=expected_pnl_range,
            regime_context=regime_context,
            component_strengths=component_strengths,
            reliability_grade=grade,
            sample_size=sample_size,
            warnings=warnings,
        )


# =============================================================================
# Utility Functions
# =============================================================================

def format_reliability_report(reliability: SignalReliability) -> str:
    """Formatiert SignalReliability als lesbaren Report"""
    lines = [
        "",
        "=" * 50,
        "  SIGNAL RELIABILITY ASSESSMENT",
        "=" * 50,
        f"  Score:          {reliability.score:.1f}",
        f"  Bucket:         {reliability.score_bucket}",
        f"  Grade:          {reliability.reliability_grade}",
        "-" * 50,
        f"  Historical Win Rate: {reliability.historical_win_rate:.1f}%",
        f"  Confidence Interval: [{reliability.confidence_interval[0]:.0f}% - "
        f"{reliability.confidence_interval[1]:.0f}%]",
        f"  Sample Size:         {reliability.sample_size} trades",
    ]

    if reliability.regime_context:
        lines.append(f"  Regime Context:      {reliability.regime_context}")

    if reliability.expected_pnl_range != (0, 0):
        p25, p75 = reliability.expected_pnl_range
        lines.append(f"  Expected P&L Range:  ${p25:.0f} - ${p75:.0f}")

    if reliability.component_strengths:
        lines.extend(["-" * 50, "  Component Strengths:"])
        for comp, strength in sorted(reliability.component_strengths.items()):
            icon = {"strong": "+", "moderate": "~", "weak": "-"}.get(strength, "?")
            lines.append(f"    [{icon}] {comp}: {strength}")

    if reliability.warnings:
        lines.extend(["-" * 50, "  Warnings:"])
        for warning in reliability.warnings:
            lines.append(f"    ! {warning}")

    lines.append("=" * 50)
    return "\n".join(lines)
