#!/usr/bin/env python3
"""
OptionPlay - Component Weight Training
======================================

Trainiert optimale Gewichtungen für die 9 Score-Komponenten.
Verwendet verschiedene Optimierungsansätze:
1. Korrelations-basierte Gewichtung
2. Grid-Search Optimierung
3. Walk-Forward Validation

Usage:
    python scripts/train_component_weights.py
    python scripts/train_component_weights.py --method grid
    python scripts/train_component_weights.py --method correlation
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import itertools

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting import TradeTracker, BacktestEngine, BacktestConfig, BacktestResult
from src.backtesting.signal_validation import SignalValidator, StatisticalCalculator


# Score-Komponenten
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


@dataclass
class ComponentAnalysis:
    """Analyse einer einzelnen Komponente"""
    name: str
    sample_size: int
    win_rate_correlation: float
    pnl_correlation: float
    avg_value_winners: float
    avg_value_losers: float
    predictive_power: str  # strong, moderate, weak, none
    recommended_weight: float


@dataclass
class WeightConfig:
    """Gewichtungs-Konfiguration"""
    weights: Dict[str, float]
    total_weight: float
    normalized_weights: Dict[str, float]

    def apply_to_score(self, score_breakdown: Dict[str, float]) -> float:
        """Berechnet gewichteten Score"""
        if not score_breakdown:
            return 0.0

        weighted_sum = 0.0
        for comp, weight in self.normalized_weights.items():
            value = score_breakdown.get(comp, 0.0)
            weighted_sum += value * weight

        return weighted_sum


@dataclass
class TrainingResult:
    """Ergebnis des Komponenten-Trainings"""
    training_date: datetime
    method: str
    component_analysis: List[ComponentAnalysis]
    optimal_weights: WeightConfig
    baseline_metrics: Dict[str, float]  # Gleichgewichtung
    optimized_metrics: Dict[str, float]  # Optimierte Gewichtung
    improvement: Dict[str, float]

    def to_dict(self) -> Dict:
        return {
            "training_date": self.training_date.isoformat(),
            "method": self.method,
            "component_analysis": [
                {
                    "name": c.name,
                    "win_rate_correlation": round(c.win_rate_correlation, 3),
                    "pnl_correlation": round(c.pnl_correlation, 3),
                    "avg_value_winners": round(c.avg_value_winners, 2),
                    "avg_value_losers": round(c.avg_value_losers, 2),
                    "predictive_power": c.predictive_power,
                    "recommended_weight": round(c.recommended_weight, 3),
                }
                for c in self.component_analysis
            ],
            "optimal_weights": {
                "raw": {k: round(v, 3) for k, v in self.optimal_weights.weights.items()},
                "normalized": {k: round(v, 3) for k, v in self.optimal_weights.normalized_weights.items()},
            },
            "baseline_metrics": {k: round(v, 2) for k, v in self.baseline_metrics.items()},
            "optimized_metrics": {k: round(v, 2) for k, v in self.optimized_metrics.items()},
            "improvement": {k: round(v, 2) for k, v in self.improvement.items()},
        }

    def summary(self) -> str:
        lines = [
            "",
            "=" * 70,
            "  COMPONENT WEIGHT TRAINING RESULT",
            "=" * 70,
            f"  Method: {self.method}",
            f"  Date: {self.training_date.strftime('%Y-%m-%d %H:%M')}",
            "",
            "-" * 70,
            "  KOMPONENTEN-ANALYSE",
            "-" * 70,
            f"  {'Komponente':<20} {'Korr':>8} {'Δ Wert':>10} {'Power':>10} {'Gewicht':>10}",
            "-" * 70,
        ]

        for c in sorted(self.component_analysis, key=lambda x: -x.recommended_weight):
            delta = c.avg_value_winners - c.avg_value_losers
            lines.append(
                f"  {c.name:<20} {c.win_rate_correlation:>+7.3f} "
                f"{delta:>+9.2f} {c.predictive_power:>10} "
                f"{c.recommended_weight:>9.1%}"
            )

        lines.extend([
            "",
            "-" * 70,
            "  PERFORMANCE-VERGLEICH",
            "-" * 70,
            f"  {'Metrik':<20} {'Baseline':>12} {'Optimiert':>12} {'Δ':>12}",
            "-" * 70,
        ])

        for metric in ["win_rate", "profit_factor", "sharpe_ratio"]:
            base = self.baseline_metrics.get(metric, 0)
            opt = self.optimized_metrics.get(metric, 0)
            delta = self.improvement.get(metric, 0)

            if metric == "win_rate":
                lines.append(f"  {metric:<20} {base:>11.1f}% {opt:>11.1f}% {delta:>+11.1f}%")
            else:
                lines.append(f"  {metric:<20} {base:>12.2f} {opt:>12.2f} {delta:>+12.2f}")

        lines.extend([
            "",
            "-" * 70,
            "  OPTIMALE GEWICHTUNG",
            "-" * 70,
        ])

        for comp, weight in sorted(
            self.optimal_weights.normalized_weights.items(),
            key=lambda x: -x[1]
        ):
            bar_len = int(weight * 40)
            bar = "█" * bar_len + "░" * (40 - bar_len)
            lines.append(f"  {comp:<20} [{bar}] {weight:>6.1%}")

        lines.append("=" * 70)
        return "\n".join(lines)


def load_data(tracker: TradeTracker, symbols: List[str]) -> Tuple[Dict, List[Dict]]:
    """Lädt historische Daten"""
    historical_data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            historical_data[symbol] = [
                {
                    "date": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in price_data.bars
            ]

    vix_points = tracker.get_vix_data()
    vix_data = [{"date": p.date, "close": p.value} for p in vix_points] if vix_points else []

    return historical_data, vix_data


def analyze_components(trades: List) -> List[ComponentAnalysis]:
    """Analysiert die Vorhersagekraft jeder Komponente"""
    analyses = []

    # Filtere Trades mit score_breakdown
    valid_trades = [t for t in trades if t.score_breakdown]

    if len(valid_trades) < 50:
        print(f"  Warnung: Nur {len(valid_trades)} Trades mit Score-Breakdown")
        return analyses

    # Extrahiere Outcomes und P&L
    outcomes = [1 if t.realized_pnl > 0 else 0 for t in valid_trades]
    pnls = [t.realized_pnl for t in valid_trades]

    for component in SCORE_COMPONENTS:
        values = [t.score_breakdown.get(component, 0) for t in valid_trades]

        # Skip wenn alle Werte gleich
        if len(set(values)) <= 1:
            analyses.append(ComponentAnalysis(
                name=component,
                sample_size=len(valid_trades),
                win_rate_correlation=0.0,
                pnl_correlation=0.0,
                avg_value_winners=0.0,
                avg_value_losers=0.0,
                predictive_power="none",
                recommended_weight=0.0,
            ))
            continue

        # Korrelationen berechnen
        win_corr, win_pval = StatisticalCalculator.pearson_correlation(values, outcomes)
        pnl_corr, _ = StatisticalCalculator.pearson_correlation(values, pnls)

        # Durchschnittswerte für Gewinner/Verlierer
        winner_values = [v for v, o in zip(values, outcomes) if o == 1]
        loser_values = [v for v, o in zip(values, outcomes) if o == 0]

        avg_winners = sum(winner_values) / len(winner_values) if winner_values else 0
        avg_losers = sum(loser_values) / len(loser_values) if loser_values else 0

        # Vorhersagekraft bestimmen
        abs_corr = abs(win_corr)
        if abs_corr >= 0.3:
            power = "strong"
        elif abs_corr >= 0.15:
            power = "moderate"
        elif abs_corr >= 0.05:
            power = "weak"
        else:
            power = "none"

        # Gewicht basierend auf Korrelation und Signifikanz
        if win_pval < 0.05 and win_corr > 0:
            weight = max(0, win_corr) * 2  # Positive Korrelation verstärken
        else:
            weight = max(0, win_corr * 0.5)  # Schwächere Gewichtung

        analyses.append(ComponentAnalysis(
            name=component,
            sample_size=len(valid_trades),
            win_rate_correlation=win_corr,
            pnl_correlation=pnl_corr,
            avg_value_winners=avg_winners,
            avg_value_losers=avg_losers,
            predictive_power=power,
            recommended_weight=weight,
        ))

    return analyses


def create_weight_config(analyses: List[ComponentAnalysis]) -> WeightConfig:
    """Erstellt normalisierte Gewichtungs-Konfiguration"""
    weights = {}
    for a in analyses:
        # Mindestgewicht von 0.05 für alle Komponenten
        weights[a.name] = max(0.05, a.recommended_weight)

    total = sum(weights.values())

    # Normalisieren
    normalized = {k: v / total for k, v in weights.items()}

    return WeightConfig(
        weights=weights,
        total_weight=total,
        normalized_weights=normalized,
    )


def calculate_weighted_score(
    score_breakdown: Dict[str, float],
    weights: Dict[str, float]
) -> float:
    """Berechnet gewichteten Score"""
    if not score_breakdown:
        return 0.0

    weighted_sum = 0.0
    for comp, weight in weights.items():
        value = score_breakdown.get(comp, 0.0)
        weighted_sum += value * weight

    return weighted_sum


def evaluate_weights(
    trades: List,
    weights: Dict[str, float],
    min_score: float = 0.0  # Kein Filter - wir vergleichen alle Trades
) -> Dict[str, float]:
    """Evaluiert eine Gewichtungs-Konfiguration"""
    # Filtere Trades mit score_breakdown
    valid_trades = [t for t in trades if t.score_breakdown]

    if not valid_trades:
        return {"win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0, "trades": 0}

    # Berechne gewichtete Scores
    weighted_scores = []
    for t in valid_trades:
        ws = calculate_weighted_score(t.score_breakdown, weights)
        weighted_scores.append((t, ws))

    # Filtere nach Mindest-Score (0.0 = keine Filterung für Vergleichbarkeit)
    filtered = [(t, ws) for t, ws in weighted_scores if ws >= min_score]

    if len(filtered) < 10:
        return {"win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0, "trades": len(filtered)}

    # Berechne Metriken
    wins = sum(1 for t, _ in filtered if t.realized_pnl > 0)
    win_rate = (wins / len(filtered)) * 100

    gross_profit = sum(t.realized_pnl for t, _ in filtered if t.realized_pnl > 0)
    gross_loss = abs(sum(t.realized_pnl for t, _ in filtered if t.realized_pnl < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    pnls = [t.realized_pnl for t, _ in filtered]
    avg_pnl = sum(pnls) / len(pnls)
    std_pnl = (sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5
    sharpe = avg_pnl / std_pnl if std_pnl > 0 else 0

    return {
        "win_rate": win_rate,
        "profit_factor": min(profit_factor, 99),
        "sharpe_ratio": sharpe,
        "trades": len(filtered),
    }


def grid_search_weights(
    trades: List,
    analyses: List[ComponentAnalysis],
    n_steps: int = 3
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Grid-Search für optimale Gewichtungen"""
    print("\n  Grid-Search für optimale Gewichtungen...")

    # Top-Komponenten nach Korrelation
    top_components = sorted(
        [a for a in analyses if a.win_rate_correlation > 0],
        key=lambda x: -x.win_rate_correlation
    )[:5]

    if len(top_components) < 3:
        print("  Warnung: Weniger als 3 Komponenten mit positiver Korrelation")
        return create_weight_config(analyses).normalized_weights, {}

    # Gewichtungs-Stufen
    weight_steps = [0.05, 0.15, 0.25]

    best_weights = None
    best_metrics = {"win_rate": 0}
    total_combinations = len(weight_steps) ** len(top_components)

    print(f"  Teste {total_combinations} Kombinationen für Top-{len(top_components)} Komponenten...")

    # Basis-Gewichte für andere Komponenten
    base_weight = 0.05
    other_components = [a.name for a in analyses if a not in top_components]

    tested = 0
    for combo in itertools.product(weight_steps, repeat=len(top_components)):
        tested += 1

        # Erstelle Gewichtung
        weights = {comp: base_weight for comp in other_components}
        for i, a in enumerate(top_components):
            weights[a.name] = combo[i]

        # Normalisieren
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

        # Evaluieren
        metrics = evaluate_weights(trades, weights)

        # Optimiere nach Win-Rate mit Mindest-Trades
        if metrics["trades"] >= 100 and metrics["win_rate"] > best_metrics["win_rate"]:
            best_weights = weights.copy()
            best_metrics = metrics.copy()

        if tested % 50 == 0:
            print(f"\r  Progress: {tested}/{total_combinations} ({tested/total_combinations*100:.0f}%)", end='')

    print()
    return best_weights or create_weight_config(analyses).normalized_weights, best_metrics


def train_correlation_based(
    trades: List,
    analyses: List[ComponentAnalysis]
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Korrelations-basierte Gewichtung"""
    print("\n  Korrelations-basierte Gewichtung...")

    weight_config = create_weight_config(analyses)
    metrics = evaluate_weights(trades, weight_config.normalized_weights)

    return weight_config.normalized_weights, metrics


def run_training(
    method: str = "correlation",
    verbose: bool = False
) -> TrainingResult:
    """Führt das Komponenten-Training durch"""

    print("=" * 70)
    print("  COMPONENT WEIGHT TRAINING")
    print("=" * 70)

    # Daten laden
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    print(f"\n  Datenbank: {stats['symbols_with_price_data']} Symbole, {stats['total_price_bars']:,} Bars")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

    print(f"  Lade historische Daten...")
    historical_data, vix_data = load_data(tracker, symbols)

    # Backtest durchführen um Trades zu sammeln
    print(f"  Führe Backtest durch...")

    all_dates = []
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            all_dates.append(d)

    start_date = min(all_dates)
    end_date = max(all_dates)

    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        min_pullback_score=3.0,  # Niedrig um alle Trades zu erfassen
        profit_target_pct=50.0,
        stop_loss_pct=100.0,
    )

    engine = BacktestEngine(config)
    result = engine.run_sync(
        symbols=list(historical_data.keys()),
        historical_data=historical_data,
        vix_data=vix_data,
    )

    print(f"  {result.total_trades} Trades generiert")

    # Komponenten analysieren
    print(f"\n  Analysiere Komponenten...")
    analyses = analyze_components(result.trades)

    if not analyses:
        print("  FEHLER: Keine Komponenten-Analyse möglich (keine score_breakdown Daten)")
        print("  Hinweis: Der Backtest generiert keine score_breakdown Daten.")
        print("  Diese müssen aus dem Live-Scanner stammen.")
        sys.exit(1)

    # Baseline (Gleichgewichtung)
    equal_weights = {comp: 1.0 / len(SCORE_COMPONENTS) for comp in SCORE_COMPONENTS}
    baseline_metrics = evaluate_weights(result.trades, equal_weights)

    # Training je nach Methode
    if method == "grid":
        optimal_weights, optimized_metrics = grid_search_weights(result.trades, analyses)
    else:
        optimal_weights, optimized_metrics = train_correlation_based(result.trades, analyses)

    # Improvement berechnen
    improvement = {
        "win_rate": optimized_metrics.get("win_rate", 0) - baseline_metrics.get("win_rate", 0),
        "profit_factor": optimized_metrics.get("profit_factor", 0) - baseline_metrics.get("profit_factor", 0),
        "sharpe_ratio": optimized_metrics.get("sharpe_ratio", 0) - baseline_metrics.get("sharpe_ratio", 0),
    }

    # Weight Config erstellen
    weight_config = WeightConfig(
        weights=optimal_weights,
        total_weight=sum(optimal_weights.values()),
        normalized_weights=optimal_weights,
    )

    return TrainingResult(
        training_date=datetime.now(),
        method=method,
        component_analysis=analyses,
        optimal_weights=weight_config,
        baseline_metrics=baseline_metrics,
        optimized_metrics=optimized_metrics,
        improvement=improvement,
    )


def main():
    parser = argparse.ArgumentParser(
        description='Train component weights for Bull-Put-Spread scoring'
    )
    parser.add_argument('--method', choices=['correlation', 'grid'], default='correlation',
                        help='Training method (default: correlation)')
    parser.add_argument('--save', type=str,
                        help='Save results to file')
    parser.add_argument('-v', '--verbose', action='store_true')

    args = parser.parse_args()

    result = run_training(method=args.method, verbose=args.verbose)

    # Ergebnis anzeigen
    print(result.summary())

    # Speichern
    if args.save:
        output_path = Path(args.save)
    else:
        output_path = Path.home() / ".optionplay" / "models" / "component_weights.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)

    print(f"\n  Ergebnisse gespeichert: {output_path}")


if __name__ == '__main__':
    main()
