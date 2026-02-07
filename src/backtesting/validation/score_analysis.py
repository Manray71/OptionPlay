#!/usr/bin/env python3
"""
Score Bucket Analysis and Regime Analysis for SignalValidator

Extracted from signal_validation.py for modularity.
Contains: ScoreAnalysisMixin with bucket analysis, component correlation,
          and regime analysis methods.
"""

import logging
import statistics
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .statistical_calc import StatisticalCalculator

logger = logging.getLogger(__name__)


class ScoreAnalysisMixin:
    """
    Mixin providing score bucket analysis and regime analysis for SignalValidator.

    Requires the host class to have:
    - self.bucket_ranges (List[Tuple[float, float]])
    - self.min_trades_per_bucket (int)
    - self.confidence_level (float)
    - self.SCORE_COMPONENTS (List[str])
    - self.VIX_REGIMES (Dict)
    """

    def _analyze_score_buckets(self, trades: List) -> List:
        """Analysiert Trades nach Score-Buckets"""
        from .signal_validation import ScoreBucketStats

        results = []

        for bucket_min, bucket_max in self.bucket_ranges:
            bucket_trades = [
                t for t in trades
                if bucket_min <= t.pullback_score < bucket_max
            ]

            if not bucket_trades:
                continue

            stats = self._calculate_bucket_stats(
                bucket_trades,
                (bucket_min, bucket_max)
            )
            results.append(stats)

        return sorted(results, key=lambda x: x.bucket_range[0])

    def _calculate_bucket_stats(self, trades: List, bucket_range: Tuple[float, float]):
        """Berechnet Statistiken für einen Bucket"""
        from .signal_validation import ScoreBucketStats

        bucket_min, bucket_max = bucket_range

        winners = [t for t in trades if t.is_winner]
        losers = [t for t in trades if not t.is_winner]
        pnls = [t.realized_pnl for t in trades]

        win_count = len(winners)
        loss_count = len(losers)
        total = len(trades)

        win_rate = (win_count / total * 100) if total > 0 else 0

        # Confidence Interval
        ci = StatisticalCalculator.wilson_confidence_interval(
            win_count, total, self.confidence_level
        )

        # P&L Statistiken
        avg_pnl = statistics.mean(pnls) if pnls else 0
        median_pnl = statistics.median(pnls) if pnls else 0
        std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0

        # Sharpe und Profit Factor
        returns = [t.realized_pnl / max(t.max_loss, 1) for t in trades]
        sharpe = StatisticalCalculator.calculate_sharpe(returns)
        profit_factor = StatisticalCalculator.calculate_profit_factor(pnls)

        # Hold Days
        avg_hold_days = statistics.mean(t.hold_days for t in trades) if trades else 0

        return ScoreBucketStats(
            bucket_range=bucket_range,
            bucket_label=f"{bucket_min:.0f}-{bucket_max:.0f}",
            trade_count=total,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            avg_pnl=avg_pnl,
            median_pnl=median_pnl,
            std_pnl=std_pnl,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            max_win=max(pnls) if pnls else 0,
            max_loss=min(pnls) if pnls else 0,
            avg_hold_days=avg_hold_days,
            confidence_interval=ci,
            is_statistically_significant=total >= self.min_trades_per_bucket,
        )

    def _analyze_component_correlations(self, trades: List) -> List:
        """Analysiert Korrelation jeder Score-Komponente mit Outcomes"""
        from .signal_validation import ComponentCorrelation

        # Filtere Trades mit score_breakdown
        valid_trades = [
            t for t in trades
            if hasattr(t, "score_breakdown") and t.score_breakdown is not None
        ]

        if len(valid_trades) < self.min_trades_per_bucket:
            logger.warning(
                f"Nur {len(valid_trades)} Trades mit score_breakdown. "
                "Komponenten-Analyse übersprungen."
            )
            return []

        results = []
        outcomes = [1 if t.is_winner else 0 for t in valid_trades]
        pnls = [t.realized_pnl for t in valid_trades]

        for component in self.SCORE_COMPONENTS:
            values = [
                t.score_breakdown.get(component, 0)
                for t in valid_trades
            ]

            # Skip wenn alle Werte gleich
            if len(set(values)) <= 1:
                continue

            # Korrelationen
            win_corr, win_pval = StatisticalCalculator.pearson_correlation(
                values, outcomes
            )
            pnl_corr, _ = StatisticalCalculator.pearson_correlation(values, pnls)

            # Winner/Loser Durchschnitte
            winner_vals = [v for v, t in zip(values, valid_trades) if t.is_winner]
            loser_vals = [v for v, t in zip(values, valid_trades) if not t.is_winner]

            avg_winners = statistics.mean(winner_vals) if winner_vals else 0
            avg_losers = statistics.mean(loser_vals) if loser_vals else 0

            # Predictive Power
            power = StatisticalCalculator.assess_predictive_power(
                win_corr, win_pval, len(valid_trades), self.min_trades_per_bucket
            )

            results.append(ComponentCorrelation(
                component_name=component,
                sample_size=len(valid_trades),
                win_rate_correlation=win_corr,
                pnl_correlation=pnl_corr,
                avg_value_winners=avg_winners,
                avg_value_losers=avg_losers,
                value_difference=avg_winners - avg_losers,
                statistical_significance=win_pval,
                predictive_power=power,
            ))

        # Sortiere nach Korrelationsstärke
        return sorted(
            results,
            key=lambda x: abs(x.win_rate_correlation),
            reverse=True
        )

    def _analyze_by_regime(
        self,
        trades: List
    ) -> Tuple[Dict[str, List], Dict[str, float]]:
        """Analysiert Score-Effektivität nach VIX-Regime"""
        from .signal_validation import RegimeBucketStats

        # Gruppiere Trades nach Regime
        regime_trades: Dict[str, List] = defaultdict(list)

        for trade in trades:
            if trade.entry_vix is not None:
                regime = self._get_regime_for_vix(trade.entry_vix)
                regime_trades[regime].append(trade)

        overall_win_rate = self._calculate_win_rate(trades)

        regime_buckets: Dict[str, List] = {}
        regime_sensitivity: Dict[str, float] = {}

        for regime, rtrades in regime_trades.items():
            if len(rtrades) < self.min_trades_per_bucket:
                continue

            # Bucket-Analyse für dieses Regime
            bucket_stats = self._analyze_score_buckets(rtrades)
            regime_win_rate = self._calculate_win_rate(rtrades)

            regime_buckets[regime] = [
                RegimeBucketStats(
                    regime=regime,
                    bucket_stats=bs,
                    regime_adjustment=bs.win_rate - overall_win_rate,
                )
                for bs in bucket_stats
            ]

            regime_sensitivity[regime] = regime_win_rate - overall_win_rate

        return regime_buckets, regime_sensitivity

    def _get_regime_for_vix(self, vix: float) -> str:
        """Ermittelt VIX-Regime für einen VIX-Wert"""
        for regime, (low, high) in self.VIX_REGIMES.items():
            if low <= vix < high:
                return regime
        return "high_vol"  # Default für extreme Werte

    def _calculate_win_rate(self, trades: List) -> float:
        """Berechnet Win Rate für eine Trade-Liste"""
        if not trades:
            return 0.0
        winners = sum(1 for t in trades if t.is_winner)
        return (winners / len(trades)) * 100

    def _calculate_overall_sharpe(self, trades: List) -> float:
        """Berechnet Gesamt-Sharpe für alle Trades"""
        if not trades:
            return 0.0
        returns = [t.realized_pnl / max(t.max_loss, 1) for t in trades]
        return StatisticalCalculator.calculate_sharpe(returns)

    def _calculate_score_effectiveness(self, trades: List) -> float:
        """Berechnet Korrelation zwischen Score und Outcome"""
        if len(trades) < 10:
            return 0.0

        scores = [t.pullback_score for t in trades]
        outcomes = [1 if t.is_winner else 0 for t in trades]

        corr, _ = StatisticalCalculator.pearson_correlation(scores, outcomes)
        return corr

    def _find_optimal_threshold(
        self,
        buckets: List,
        target_win_rate: float = 60.0
    ) -> float:
        """Findet optimalen Score-Schwellenwert für Ziel-Win-Rate"""
        for bucket in buckets:
            ci_lower = bucket.confidence_interval[0]
            if ci_lower >= target_win_rate and bucket.is_statistically_significant:
                return bucket.bucket_range[0]

        # Fallback: höchster Bucket mit positiver Win Rate
        for bucket in reversed(buckets):
            if bucket.win_rate > 50:
                return bucket.bucket_range[0]

        return 5.0  # Default

    def _find_bucket_for_score(self, score: float, buckets: List):
        """Findet den passenden Bucket für einen Score"""
        for bucket in buckets:
            low, high = bucket.bucket_range
            if low <= score < high:
                return bucket
        return None

    def _calculate_pnl_range(
        self,
        score: float,
        trades: List
    ) -> Tuple[float, float]:
        """Berechnet erwartete P&L-Range (25th-75th Perzentil)"""
        # Finde Trades im passenden Score-Bereich
        matching_trades = []
        for bucket_min, bucket_max in self.bucket_ranges:
            if bucket_min <= score < bucket_max:
                matching_trades = [
                    t for t in trades
                    if bucket_min <= t.pullback_score < bucket_max
                ]
                break

        if len(matching_trades) < 4:
            return (0.0, 0.0)

        pnls = sorted(t.realized_pnl for t in matching_trades)
        n = len(pnls)

        # 25th und 75th Perzentil
        p25_idx = int(n * 0.25)
        p75_idx = int(n * 0.75)

        return (pnls[p25_idx], pnls[p75_idx])

    def _assess_component_strengths(
        self,
        breakdown: Dict[str, float],
        correlations: List
    ) -> Dict[str, str]:
        """Bewertet Stärke jeder Komponente im aktuellen Signal"""
        strengths = {}

        for corr in correlations:
            component = corr.component_name
            if component not in breakdown:
                continue

            value = breakdown[component]

            # Vergleiche mit Winner-Durchschnitt
            if corr.avg_value_winners > 0:
                ratio = value / corr.avg_value_winners
                if ratio >= 1.0:
                    strengths[component] = "strong"
                elif ratio >= 0.7:
                    strengths[component] = "moderate"
                else:
                    strengths[component] = "weak"

        return strengths

    def _determine_grade(self, ci_lower: float, sample_size: int) -> str:
        """Bestimmt Reliability Grade basierend auf CI-Untergrenze"""
        if sample_size < 10:
            return "F"  # Nicht genug Daten

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
