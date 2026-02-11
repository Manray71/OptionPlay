# OptionPlay - Multi-Strategy Score Normalizer & Ranker
# ======================================================
# Normalisiert Scores über Strategien hinweg für vergleichbare Rankings
#
# Problem: Rohe Scores sind nicht vergleichbar, da jede Strategie
# unterschiedliche Gewichte und Skalen verwendet.
#
# Lösung: Perzentil-basierte Normalisierung + Expected Value Berechnung

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# STRATEGY PERFORMANCE METRICS (from backtest_full_v381.py with DTE=75)
# =============================================================================

STRATEGY_METRICS = {
    "pullback": {
        "win_rate": 0.861,  # 86.1%
        "avg_pnl": 158.08,  # $158.08 per trade
        "sharpe": 17.50,
        "score_percentiles": {  # Score → Percentile mapping (from backtest)
            "p10": 4.2,
            "p25": 5.1,
            "p50": 6.0,
            "p75": 7.2,
            "p90": 8.5,
            "p95": 9.3,
        },
    },
    "bounce": {
        "win_rate": 0.859,  # 85.9%
        "avg_pnl": 157.29,  # $157.29 per trade
        "sharpe": 17.35,
        "score_percentiles": {
            "p10": 4.0,
            "p25": 4.9,
            "p50": 5.8,
            "p75": 7.0,
            "p90": 8.3,
            "p95": 9.1,
        },
    },
    "ath_breakout": {
        "win_rate": 0.868,  # 86.8%
        "avg_pnl": 156.42,  # $156.42 per trade
        "sharpe": 17.74,
        "score_percentiles": {
            "p10": 4.5,
            "p25": 5.3,
            "p50": 6.2,
            "p75": 7.4,
            "p90": 8.7,
            "p95": 9.5,
        },
    },
    "earnings_dip": {
        "win_rate": 0.849,  # 84.9%
        "avg_pnl": 174.65,  # $174.65 per trade (highest!)
        "sharpe": 19.09,
        "score_percentiles": {
            "p10": 5.5,
            "p25": 6.2,
            "p50": 7.0,  # Higher baseline for earnings_dip
            "p75": 8.0,
            "p90": 9.2,
            "p95": 10.0,
        },
    },
}


@dataclass
class NormalizedScore:
    """Normalisierter Score für eine Strategie."""

    strategy: str
    raw_score: float
    normalized_score: float  # 0-100 Skala
    percentile: float  # Position relativ zur Historie
    expected_value: float  # Score × WinRate × AvgPnL
    win_rate: float
    avg_pnl: float

    def __lt__(self, other) -> bool:
        return self.expected_value < other.expected_value


@dataclass
class MultiStrategyRanking:
    """Ranking eines Symbols über alle Strategien."""

    symbol: str
    current_price: float
    scores: List[NormalizedScore]
    best_strategy: str
    best_expected_value: float
    strategy_count: int  # Anzahl qualifizierender Strategien

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "best_strategy": self.best_strategy,
            "best_expected_value": round(self.best_expected_value, 2),
            "strategy_count": self.strategy_count,
            "scores": [
                {
                    "strategy": s.strategy,
                    "raw_score": round(s.raw_score, 2),
                    "normalized_score": round(s.normalized_score, 1),
                    "percentile": round(s.percentile, 1),
                    "expected_value": round(s.expected_value, 2),
                    "win_rate": f"{s.win_rate:.1%}",
                    "avg_pnl": f"${s.avg_pnl:.0f}",
                }
                for s in sorted(self.scores, reverse=True)
            ],
        }


class MultiStrategyRanker:
    """
    Normalisiert und rankt Scores über Strategien hinweg.

    Verwendung:
    ```python
    ranker = MultiStrategyRanker()

    # Einzelnes Symbol
    scores = {
        'pullback': 7.5,
        'bounce': 6.2,
        'ath_breakout': 8.1,
        'earnings_dip': None  # Nicht im Earnings-Fenster
    }
    ranking = ranker.rank_symbol('AAPL', 185.0, scores)

    # Output:
    # {
    #   'symbol': 'AAPL',
    #   'best_strategy': 'ath_breakout',
    #   'best_expected_value': 142.5,
    #   'scores': [
    #     {'strategy': 'ath_breakout', 'normalized_score': 85.2, 'expected_value': 142.5, ...},
    #     {'strategy': 'pullback', 'normalized_score': 72.1, 'expected_value': 128.3, ...},
    #     ...
    #   ]
    # }
    ```
    """

    def __init__(self, metrics: Optional[Dict] = None) -> None:
        """
        Args:
            metrics: Optionale Custom-Metriken, sonst werden Backtest-Ergebnisse verwendet
        """
        self.metrics = metrics or STRATEGY_METRICS

    def normalize_score(self, strategy: str, raw_score: float) -> NormalizedScore:
        """
        Normalisiert einen Raw-Score auf eine 0-100 Skala.

        Args:
            strategy: Name der Strategie (pullback, bounce, ath_breakout, earnings_dip)
            raw_score: Roher Score aus der Strategie

        Returns:
            NormalizedScore mit allen berechneten Metriken
        """
        if strategy not in self.metrics:
            raise ValueError(f"Unknown strategy: {strategy}")

        m = self.metrics[strategy]
        percentiles = m["score_percentiles"]

        # Berechne Perzentil basierend auf historischer Verteilung
        if raw_score <= percentiles["p10"]:
            percentile = 10 * (raw_score / percentiles["p10"]) if percentiles["p10"] > 0 else 0
        elif raw_score <= percentiles["p25"]:
            percentile = 10 + 15 * (raw_score - percentiles["p10"]) / (
                percentiles["p25"] - percentiles["p10"]
            )
        elif raw_score <= percentiles["p50"]:
            percentile = 25 + 25 * (raw_score - percentiles["p25"]) / (
                percentiles["p50"] - percentiles["p25"]
            )
        elif raw_score <= percentiles["p75"]:
            percentile = 50 + 25 * (raw_score - percentiles["p50"]) / (
                percentiles["p75"] - percentiles["p50"]
            )
        elif raw_score <= percentiles["p90"]:
            percentile = 75 + 15 * (raw_score - percentiles["p75"]) / (
                percentiles["p90"] - percentiles["p75"]
            )
        elif raw_score <= percentiles["p95"]:
            percentile = 90 + 5 * (raw_score - percentiles["p90"]) / (
                percentiles["p95"] - percentiles["p90"]
            )
        else:
            # Über 95. Perzentil - extrapoliere
            percentile = min(100, 95 + 5 * (raw_score - percentiles["p95"]) / percentiles["p95"])

        percentile = max(0, min(100, percentile))

        # Normalisierter Score (0-100)
        normalized = percentile

        # Expected Value = Percentile-Factor × WinRate × AvgPnL
        # Höheres Perzentil = besseres Signal = höherer EV-Multiplier
        percentile_factor = percentile / 50  # 1.0 bei 50%, 2.0 bei 100%
        expected_value = percentile_factor * m["win_rate"] * m["avg_pnl"]

        return NormalizedScore(
            strategy=strategy,
            raw_score=raw_score,
            normalized_score=normalized,
            percentile=percentile,
            expected_value=expected_value,
            win_rate=m["win_rate"],
            avg_pnl=m["avg_pnl"],
        )

    def rank_symbol(
        self,
        symbol: str,
        current_price: float,
        strategy_scores: Dict[str, Optional[float]],
        min_score: float = 5.0,
    ) -> MultiStrategyRanking:
        """
        Rankt ein Symbol über alle verfügbaren Strategien.

        Args:
            symbol: Das Symbol
            current_price: Aktueller Preis
            strategy_scores: Dict mit {strategie: score} oder None falls nicht anwendbar
            min_score: Minimum Raw-Score um berücksichtigt zu werden

        Returns:
            MultiStrategyRanking mit allen qualifizierenden Strategien
        """
        normalized_scores = []

        for strategy, raw_score in strategy_scores.items():
            if raw_score is None or raw_score < min_score:
                continue

            if strategy not in self.metrics:
                continue

            try:
                normalized = self.normalize_score(strategy, raw_score)
                normalized_scores.append(normalized)
            except Exception as e:
                logger.warning(f"Error normalizing {strategy} score for {symbol}: {e}")

        # Sortiere nach Expected Value (absteigend)
        normalized_scores.sort(reverse=True)

        best_strategy = normalized_scores[0].strategy if normalized_scores else "none"
        best_ev = normalized_scores[0].expected_value if normalized_scores else 0.0

        return MultiStrategyRanking(
            symbol=symbol,
            current_price=current_price,
            scores=normalized_scores,
            best_strategy=best_strategy,
            best_expected_value=best_ev,
            strategy_count=len(normalized_scores),
        )

    def rank_multiple(
        self, symbols_data: List[Dict], min_score: float = 5.0, min_strategies: int = 1
    ) -> List[MultiStrategyRanking]:
        """
        Rankt mehrere Symbole und sortiert nach bestem Expected Value.

        Args:
            symbols_data: Liste von Dicts mit {symbol, price, scores: {strategy: score}}
            min_score: Minimum Raw-Score
            min_strategies: Minimum Anzahl qualifizierender Strategien

        Returns:
            Liste von MultiStrategyRankings, sortiert nach best_expected_value
        """
        rankings = []

        for data in symbols_data:
            ranking = self.rank_symbol(
                symbol=data["symbol"],
                current_price=data.get("price", 0.0),
                strategy_scores=data.get("scores", {}),
                min_score=min_score,
            )

            if ranking.strategy_count >= min_strategies:
                rankings.append(ranking)

        # Sortiere nach bestem Expected Value
        rankings.sort(key=lambda r: r.best_expected_value, reverse=True)

        return rankings

    def format_ranking(self, ranking: MultiStrategyRanking) -> str:
        """Formatiert ein Ranking für die Ausgabe."""
        lines = [
            f"{'='*60}",
            f"  {ranking.symbol} @ ${ranking.current_price:.2f}",
            f"{'='*60}",
            f"  Best Strategy: {ranking.best_strategy.upper()}",
            f"  Expected Value: ${ranking.best_expected_value:.2f}",
            f"  Qualifying Strategies: {ranking.strategy_count}",
            f"",
            f"  {'Strategy':<15} {'Score':<8} {'Norm':<8} {'Pctl':<8} {'EV':<10} {'WR':<8}",
            f"  {'-'*55}",
        ]

        for s in ranking.scores:
            lines.append(
                f"  {s.strategy:<15} {s.raw_score:<8.1f} {s.normalized_score:<8.1f} "
                f"{s.percentile:<8.1f} ${s.expected_value:<9.0f} {s.win_rate:.1%}"
            )

        return "\n".join(lines)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_ranker() -> MultiStrategyRanker:
    """Returns the default MultiStrategyRanker instance."""
    return MultiStrategyRanker()


def compare_strategies(
    symbol: str,
    price: float,
    pullback_score: Optional[float] = None,
    bounce_score: Optional[float] = None,
    ath_breakout_score: Optional[float] = None,
    earnings_dip_score: Optional[float] = None,
) -> MultiStrategyRanking:
    """
    Convenience function to compare strategies for a symbol.

    Example:
        ranking = compare_strategies(
            'AAPL', 185.0,
            pullback_score=7.5,
            bounce_score=6.2,
            ath_breakout_score=8.1
        )
        print(ranking.best_strategy)  # 'ath_breakout'
    """
    ranker = MultiStrategyRanker()
    scores = {
        "pullback": pullback_score,
        "bounce": bounce_score,
        "ath_breakout": ath_breakout_score,
        "earnings_dip": earnings_dip_score,
    }
    return ranker.rank_symbol(symbol, price, scores)
