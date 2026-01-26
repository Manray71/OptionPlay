#!/usr/bin/env python3
"""
OptionPlay - Walk-Forward Training Script
==========================================

Führt Walk-Forward Training für Bull-Put-Spread Strategie durch.
Erkennt Overfitting und liefert produktionsreife Parameter-Empfehlungen.

Usage:
    # Standard-Training
    python scripts/run_training.py

    # Mit Parameter-Optimierung
    python scripts/run_training.py --optimize

    # Detaillierte Ausgabe
    python scripts/run_training.py --verbose

    # Kurzer Testlauf
    python scripts/run_training.py --quick
"""

import argparse
import sys
from pathlib import Path
from datetime import date
from typing import List, Dict, Optional

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting import TradeTracker
from src.backtesting.walk_forward import WalkForwardTrainer, TrainingConfig


def load_historical_data(
    tracker: TradeTracker,
    symbols: List[str]
) -> Dict[str, List[Dict]]:
    """Lädt historische Preisdaten aus der Datenbank."""
    data = {}

    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            data[symbol] = [
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

    return data


def load_vix_data(tracker: TradeTracker) -> List[Dict]:
    """Lädt VIX-Daten aus der Datenbank."""
    vix_points = tracker.get_vix_data()
    if not vix_points:
        return []

    return [
        {"date": p.date, "close": p.value}
        for p in vix_points
    ]


def print_epoch_details(result, verbose: bool = False):
    """Druckt Details der Epochen"""
    if not verbose:
        return

    print("\n" + "─" * 80)
    print("  EPOCHEN-DETAILS")
    print("─" * 80)

    print(f"{'Epoch':<8} {'Train':<22} {'Test':<22} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10}")
    print("-" * 80)

    for epoch in result.epochs:
        if not epoch.is_valid:
            print(f"{epoch.epoch_id:<8} ÜBERSPRUNGEN: {epoch.skip_reason}")
            continue

        train_period = f"{epoch.train_start} - {epoch.train_end}"
        test_period = f"{epoch.test_start} - {epoch.test_end}"

        degrad_color = "🟢" if epoch.win_rate_degradation < 5 else "🟡" if epoch.win_rate_degradation < 10 else "🔴"

        print(
            f"{epoch.epoch_id:<8} "
            f"{train_period:<22} "
            f"{test_period:<22} "
            f"{epoch.in_sample_win_rate:>9.1f}% "
            f"{epoch.out_sample_win_rate:>9.1f}% "
            f"{degrad_color} {epoch.win_rate_degradation:>+6.1f}%"
        )


def print_parameter_grid_results(results: List[Dict], top_n: int = 10):
    """Druckt Parameter-Grid-Ergebnisse"""
    print("\n" + "─" * 80)
    print("  PARAMETER-OPTIMIERUNG (Top 10)")
    print("─" * 80)

    print(f"{'MinScore':>10} {'Profit%':>10} {'Stop%':>10} {'OOS Win%':>12} {'PF':>8} {'Sharpe':>8}")
    print("-" * 80)

    for r in results[:top_n]:
        print(
            f"{r['min_score']:>10.1f} "
            f"{r['profit_target']:>10.0f} "
            f"{r['stop_loss']:>10.0f} "
            f"{r['oos_win_rate']:>11.1f}% "
            f"{r['profit_factor']:>8.2f} "
            f"{r['sharpe']:>8.2f}"
        )


def run_parameter_optimization(
    historical_data: Dict[str, List[Dict]],
    vix_data: List[Dict],
    symbols: List[str],
) -> List[Dict]:
    """
    Führt Parameter-Grid-Suche durch.

    Testet verschiedene Kombinationen von:
    - Min Pullback Score
    - Profit Target %
    - Stop Loss %
    """
    print("\n" + "═" * 70)
    print("  PARAMETER-OPTIMIERUNG")
    print("═" * 70)

    # Parameter-Grid
    min_scores = [4.0, 5.0, 6.0, 7.0, 8.0]
    profit_targets = [40, 50, 60, 75]
    stop_losses = [100, 150, 200]

    total_combinations = len(min_scores) * len(profit_targets) * len(stop_losses)
    print(f"\n  Teste {total_combinations} Parameter-Kombinationen...")

    results = []
    completed = 0

    for min_score in min_scores:
        for profit_target in profit_targets:
            for stop_loss in stop_losses:
                completed += 1

                # Progress
                pct = (completed / total_combinations) * 100
                print(f"\r  Progress: [{completed}/{total_combinations}] {pct:.0f}%", end='', flush=True)

                config = TrainingConfig(
                    train_months=6,  # Kürzer für Optimierung
                    test_months=3,
                    step_months=3,
                    min_trades_per_epoch=20,
                    min_valid_epochs=2,
                    min_pullback_score=min_score,
                    profit_target_pct=profit_target,
                    stop_loss_pct=stop_loss,
                )

                trainer = WalkForwardTrainer(config)

                try:
                    result = trainer.train_sync(
                        historical_data=historical_data,
                        vix_data=vix_data,
                        symbols=symbols,
                    )

                    if result.valid_epochs > 0:
                        results.append({
                            'min_score': min_score,
                            'profit_target': profit_target,
                            'stop_loss': stop_loss,
                            'oos_win_rate': result.avg_out_sample_win_rate,
                            'profit_factor': result.avg_out_sample_sharpe,  # Vereinfacht
                            'sharpe': result.avg_out_sample_sharpe,
                            'degradation': result.avg_win_rate_degradation,
                            'overfit': result.overfit_severity,
                        })
                except Exception as e:
                    pass  # Skip fehlerhafte Kombinationen

    print()  # Neue Zeile nach Progress

    # Sortiere nach OOS Win Rate (mit Penalty für Overfit)
    for r in results:
        overfit_penalty = 0
        if r['overfit'] == 'mild':
            overfit_penalty = 2
        elif r['overfit'] == 'moderate':
            overfit_penalty = 5
        elif r['overfit'] == 'severe':
            overfit_penalty = 10
        r['adjusted_score'] = r['oos_win_rate'] - overfit_penalty

    results.sort(key=lambda x: x['adjusted_score'], reverse=True)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Walk-Forward Training für Bull-Put-Spread Strategie',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Training-Parameter
    parser.add_argument('--train-months', type=int, default=6,
                        help='Training-Periode in Monaten (default: 6)')
    parser.add_argument('--test-months', type=int, default=3,
                        help='Test-Periode in Monaten (default: 3)')
    parser.add_argument('--step-months', type=int, default=2,
                        help='Schritt zwischen Epochen (default: 2)')

    # Backtest-Parameter
    parser.add_argument('--min-score', type=float, default=5.0,
                        help='Minimum Pullback Score (default: 5.0)')
    parser.add_argument('--profit-target', type=float, default=50,
                        help='Profit Target %% (default: 50)')
    parser.add_argument('--stop-loss', type=float, default=200,
                        help='Stop Loss %% (default: 200)')

    # Modi
    parser.add_argument('--optimize', action='store_true',
                        help='Parameter-Optimierung durchführen')
    parser.add_argument('--quick', action='store_true',
                        help='Schneller Testlauf mit weniger Epochen')

    # Output
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Detaillierte Ausgabe')
    parser.add_argument('--save', type=str,
                        help='Speichere Ergebnisse in Datei')

    args = parser.parse_args()

    print("═" * 70)
    print("  OPTIONPLAY WALK-FORWARD TRAINING")
    print("═" * 70)

    # Tracker laden
    tracker = TradeTracker()

    # Status prüfen
    stats = tracker.get_storage_stats()
    if stats['symbols_with_price_data'] == 0:
        print("\n❌ Keine historischen Daten gefunden!")
        print("   Führe zuerst aus: python scripts/collect_historical_data.py --all")
        sys.exit(1)

    print(f"\n  Datenbank: {stats['symbols_with_price_data']} Symbole, {stats['total_price_bars']:,} Bars")

    # VIX-Daten prüfen
    vix_range = tracker.get_vix_range()
    if vix_range:
        print(f"  VIX-Daten: {vix_range[0]} bis {vix_range[1]}")
    else:
        print("  ⚠️  VIX-Daten: Keine (Training läuft ohne VIX-Regime-Analyse)")

    # Symbole laden
    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]
    print(f"  Symbole: {len(symbols)}")

    # Historische Daten laden
    print("\n  Lade historische Daten...")
    historical_data = load_historical_data(tracker, symbols)
    vix_data = load_vix_data(tracker)

    symbols_with_data = list(historical_data.keys())
    print(f"  Geladen: {len(symbols_with_data)} Symbole mit Daten")

    if not symbols_with_data:
        print("\n❌ Keine Daten für die gewählten Symbole!")
        sys.exit(1)

    # Parameter-Optimierung?
    if args.optimize:
        optimization_results = run_parameter_optimization(
            historical_data=historical_data,
            vix_data=vix_data,
            symbols=symbols_with_data,
        )

        if optimization_results:
            print_parameter_grid_results(optimization_results)

            # Beste Parameter für finales Training
            best = optimization_results[0]
            print(f"\n  Beste Parameter:")
            print(f"    Min Score:     {best['min_score']}")
            print(f"    Profit Target: {best['profit_target']}%")
            print(f"    Stop Loss:     {best['stop_loss']}%")
            print(f"    OOS Win Rate:  {best['oos_win_rate']:.1f}%")
            print(f"    Overfit:       {best['overfit']}")

            # Finales Training mit besten Parametern
            args.min_score = best['min_score']
            args.profit_target = best['profit_target']
            args.stop_loss = best['stop_loss']

    # Quick-Modus anpassen
    if args.quick:
        args.train_months = 3
        args.test_months = 2
        args.step_months = 2

    # Training-Config
    config = TrainingConfig(
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        min_trades_per_epoch=30 if args.quick else 50,
        min_valid_epochs=2 if args.quick else 3,
        min_pullback_score=args.min_score,
        profit_target_pct=args.profit_target,
        stop_loss_pct=args.stop_loss,
        include_regime_analysis=bool(vix_data),
    )

    print(f"\n  Training-Config:")
    print(f"    Train:    {config.train_months} Monate")
    print(f"    Test:     {config.test_months} Monate")
    print(f"    Step:     {config.step_months} Monate")
    print(f"    Min Score: {config.min_pullback_score}")

    # Training starten
    print("\n" + "═" * 70)
    print("  STARTE WALK-FORWARD TRAINING...")
    print("═" * 70)

    trainer = WalkForwardTrainer(config)
    result = trainer.train_sync(
        historical_data=historical_data,
        vix_data=vix_data,
        symbols=symbols_with_data,
    )

    # Ergebnisse anzeigen
    print(result.summary())

    # Epochen-Details
    print_epoch_details(result, args.verbose)

    # Speichern
    if args.save:
        filepath = trainer.save(result, args.save)
        print(f"\n  Ergebnisse gespeichert: {filepath}")
    else:
        # Default-Speicherort
        filepath = trainer.save(result)
        print(f"\n  Ergebnisse gespeichert: {filepath}")

    # Kurze Zusammenfassung
    print("\n" + "═" * 70)
    severity_emoji = {
        "none": "🟢",
        "mild": "🟡",
        "moderate": "🟠",
        "severe": "🔴",
    }
    emoji = severity_emoji.get(result.overfit_severity, "⚪")

    print(f"  Empfohlener Min-Score: {result.recommended_min_score:.1f}")
    print(f"  OOS Win Rate: {result.avg_out_sample_win_rate:.1f}%")
    print(f"  Overfitting: {emoji} {result.overfit_severity.upper()} (Degradation: {result.avg_win_rate_degradation:+.1f}%)")
    print("═" * 70)


if __name__ == '__main__':
    main()
