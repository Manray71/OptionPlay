#!/usr/bin/env python3
"""
Statistical Calculations for Signal Validation

Extracted from signal_validation.py for modularity.
Contains: StatisticalCalculator class with Wilson CI, Pearson correlation,
          Sharpe ratio, profit factor, and predictive power assessment.
"""

import math
import statistics
from typing import List, Tuple


class StatisticalCalculator:
    """Statistische Berechnungen für Signal-Validierung"""

    @staticmethod
    def wilson_confidence_interval(
        wins: int,
        total: int,
        confidence: float = 0.95
    ) -> Tuple[float, float]:
        """
        Berechnet Wilson Score Confidence Interval für Win Rate.

        Wilson CI ist robuster als normale Approximation bei kleinen Stichproben
        oder extremen Wahrscheinlichkeiten.
        """
        if total == 0:
            return (0.0, 0.0)

        # Z-Score für Konfidenzlevel
        z = 1.96 if confidence == 0.95 else 1.645  # 95% oder 90%

        p = wins / total
        denominator = 1 + z * z / total

        center = (p + z * z / (2 * total)) / denominator

        # Margin of error
        margin = (z / denominator) * math.sqrt(
            p * (1 - p) / total + z * z / (4 * total * total)
        )

        lower = max(0, center - margin) * 100
        upper = min(1, center + margin) * 100

        return (lower, upper)

    @staticmethod
    def pearson_correlation(
        x: List[float],
        y: List[float]
    ) -> Tuple[float, float]:
        """
        Berechnet Pearson Korrelation und p-Wert.

        Returns:
            Tuple von (correlation, p_value)
        """
        n = len(x)
        if n < 3 or len(y) != n:
            return (0.0, 1.0)

        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)

        # Kovarianz und Standardabweichungen
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
        std_x = statistics.stdev(x) if n > 1 else 0
        std_y = statistics.stdev(y) if n > 1 else 0

        if std_x == 0 or std_y == 0:
            return (0.0, 1.0)

        r = cov / (std_x * std_y)

        # t-Statistik für p-Wert
        if abs(r) >= 1:
            p_value = 0.0
        else:
            t_stat = r * math.sqrt((n - 2) / (1 - r * r))
            # Approximation des p-Werts (vereinfacht)
            p_value = 2 * (1 - StatisticalCalculator._t_cdf(abs(t_stat), n - 2))

        return (r, p_value)

    @staticmethod
    def _t_cdf(t: float, df: int) -> float:
        """
        Approximation der t-Verteilung CDF.
        Für exakte Werte würde scipy.stats.t.cdf benötigt.
        """
        # Approximation für df > 30: t ~ N(0,1)
        if df > 30:
            # Standard-Normal CDF Approximation
            return 0.5 * (1 + math.erf(t / math.sqrt(2)))

        # Für kleinere df: grobe Approximation
        x = df / (df + t * t)
        # Beta function approximation
        return 1 - 0.5 * x ** (df / 2)

    @staticmethod
    def calculate_sharpe(
        returns: List[float],
        risk_free_rate: float = 0.05,
        periods_per_year: float = 12.0
    ) -> float:
        """
        Berechnet Sharpe Ratio.

        Args:
            returns: Liste von Renditen (nicht prozentual)
            risk_free_rate: Risikofreier Zinssatz (annualisiert)
            periods_per_year: Annahme für Perioden pro Jahr
        """
        if len(returns) < 2:
            return 0.0

        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)

        if std_return == 0:
            return 0.0

        # Annualisierung
        excess_return = mean_return - (risk_free_rate / periods_per_year)
        sharpe = (excess_return / std_return) * math.sqrt(periods_per_year)

        return sharpe

    @staticmethod
    def calculate_profit_factor(pnls: List[float]) -> float:
        """Berechnet Profit Factor = Gross Profit / Gross Loss"""
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    @staticmethod
    def assess_predictive_power(
        correlation: float,
        p_value: float,
        sample_size: int,
        min_samples: int = 30
    ) -> str:
        """
        Bewertet die Vorhersagekraft einer Korrelation.

        Returns:
            "strong", "moderate", "weak", "none", oder "insufficient_data"
        """
        if sample_size < min_samples:
            return "insufficient_data"

        if p_value > 0.05:
            return "none"  # Nicht signifikant

        abs_corr = abs(correlation)

        if abs_corr >= 0.5:
            return "strong"
        elif abs_corr >= 0.3:
            return "moderate"
        elif abs_corr >= 0.1:
            return "weak"
        else:
            return "none"
