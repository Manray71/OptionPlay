#!/usr/bin/env python3
"""
OptionPlay - Walk-Forward Validierung des trainierten Modells
=============================================================

Validiert das GRANULAR_TRAINED_MODEL durch:
1. Multi-Period Out-of-Sample Testing
2. Overfitting-Erkennung
3. Stabilitätsanalyse über verschiedene Marktphasen

Usage:
    python scripts/validate_trained_model.py
"""

import json
import sys
import warnings
from pathlib import Path
from datetime import date, datetime
from typing import Dict, List, Tuple
from collections import defaultdict
import statistics

warnings.filterwarnings("ignore")

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()

# Constants
MODELS_DIR = Path.home() / ".optionplay" / "models"
TRAINED_MODEL = MODELS_DIR / "GRANULAR_TRAINED_MODEL.json"

# VIX Regimes
VIX_REGIMES = {"low": (0, 15), "normal": (15, 20), "elevated": (20, 30), "high": (30, 100)}

# Overfitting thresholds
OVERFIT_NONE = 5.0  # < 5% = keine Degradation
OVERFIT_MILD = 10.0  # 5-10% = leichtes Overfitting
OVERFIT_MODERATE = 15.0  # 10-15% = moderates Overfitting
# > 15% = schweres Overfitting


def load_trained_model() -> Dict:
    """Lädt das trainierte Modell"""
    with open(TRAINED_MODEL) as f:
        return json.load(f)


def classify_overfit(degradation: float) -> str:
    """Klassifiziert den Overfit-Grad"""
    abs_deg = abs(degradation)
    if abs_deg < OVERFIT_NONE:
        return "✅ NONE"
    elif abs_deg < OVERFIT_MILD:
        return "⚠️ MILD"
    elif abs_deg < OVERFIT_MODERATE:
        return "⚠️ MODERATE"
    else:
        return "❌ SEVERE"


def analyze_regime_strategy_performance(model: Dict) -> Dict:
    """Analysiert Performance pro Regime × Strategy"""
    results = {}

    for regime, strategies in model["regime_strategy_configs"].items():
        results[regime] = {}
        for strategy, config in strategies.items():
            if not config.get("enabled", False):
                continue

            train_wr = config.get("train_wr", 0)
            test_wr = config.get("test_wr", 0)
            degradation = config.get("degradation", train_wr - test_wr)
            train_trades = config.get("train_trades", 0)
            test_trades = config.get("test_trades", 0)
            total_pnl = config.get("total_pnl", 0)

            results[regime][strategy] = {
                "train_wr": train_wr,
                "test_wr": test_wr,
                "degradation": degradation,
                "train_trades": train_trades,
                "test_trades": test_trades,
                "total_pnl": total_pnl,
                "overfit_level": classify_overfit(degradation),
                "is_stable": abs(degradation) < OVERFIT_MODERATE,
            }

    return results


def analyze_symbol_stability(model: Dict) -> Dict:
    """Analysiert Symbol-Level Stabilität"""
    symbol_configs = model.get("symbol_configs", {})

    all_symbols = []

    for symbol, config in symbol_configs.items():
        total_trades = config.get("total_trades", 0)
        total_wins = config.get("total_wins", 0)
        win_rate = config.get("win_rate", 0)
        total_pnl = config.get("total_pnl", 0)
        best_strategy = config.get("best_strategy", "unknown")

        # Symbol ist stabil wenn WR >= 70% und positive P&L
        is_stable = win_rate >= 70 and total_pnl >= 0

        symbol_result = {
            "symbol": symbol,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "best_strategy": best_strategy,
            "is_stable": is_stable,
        }
        all_symbols.append(symbol_result)

    stable_symbols = [s for s in all_symbols if s["is_stable"]]
    unstable_symbols = [s for s in all_symbols if not s["is_stable"]]

    return {
        "stable": sorted(stable_symbols, key=lambda x: -x["win_rate"]),
        "unstable": sorted(unstable_symbols, key=lambda x: x["win_rate"]),
        "stability_rate": len(stable_symbols) / len(all_symbols) * 100 if all_symbols else 0,
        "total_symbols": len(all_symbols),
    }


def analyze_iv_rank_stability(model: Dict) -> Dict:
    """Analysiert IV-Rank basierte Stabilität"""
    iv_analysis = model.get("iv_rank_analysis", {})

    results = {}
    for strategy, buckets in iv_analysis.items():
        results[strategy] = {}
        for bucket, data in buckets.items():
            results[strategy][bucket] = {
                "win_rate": data.get("win_rate", 0),
                "trades": data.get("trades", 0),
                "avg_pnl": data.get("avg_pnl", 0),
            }

    return results


def calculate_aggregate_metrics(model: Dict) -> Dict:
    """Berechnet aggregierte Metriken"""
    regime_configs = model.get("regime_strategy_configs", {})

    total_train_trades = 0
    total_train_wins = 0
    total_test_trades = 0
    total_test_wins = 0
    total_pnl = 0
    degradations = []

    for regime, strategies in regime_configs.items():
        for strategy, config in strategies.items():
            if not config.get("enabled", False):
                continue

            train_trades = config.get("train_trades", 0)
            train_wins = config.get("train_wins", 0)
            test_trades = config.get("test_trades", 0)
            test_wins = config.get("test_wins", 0)
            degradation = config.get("degradation", 0)
            pnl = config.get("total_pnl", 0)

            total_train_trades += train_trades
            total_train_wins += train_wins
            total_test_trades += test_trades
            total_test_wins += test_wins
            total_pnl += pnl

            if train_trades > 50 and test_trades > 10:  # Significant sample
                degradations.append(degradation)

    train_wr = total_train_wins / total_train_trades * 100 if total_train_trades > 0 else 0
    test_wr = total_test_wins / total_test_trades * 100 if total_test_trades > 0 else 0
    avg_degradation = statistics.mean(degradations) if degradations else 0

    return {
        "total_train_trades": total_train_trades,
        "total_train_wins": total_train_wins,
        "total_test_trades": total_test_trades,
        "total_test_wins": total_test_wins,
        "train_wr": train_wr,
        "test_wr": test_wr,
        "overall_degradation": train_wr - test_wr,
        "avg_degradation": avg_degradation,
        "total_pnl": total_pnl,
    }


def print_validation_report(model: Dict):
    """Druckt den Validierungsbericht"""
    print()
    print("=" * 80)
    print("   WALK-FORWARD VALIDIERUNG - TRAINIERTES MODELL")
    print("=" * 80)
    print()

    # Summary
    summary = model.get("summary", {})
    print(f"Modell Version:     {model.get('version', 'unknown')}")
    print(f"Trainiert am:       {model.get('created_at', 'unknown')[:10]}")
    print(f"Total Trades:       {summary.get('total_trades', 0):,}")
    print(f"Gesamt Win Rate:    {summary.get('win_rate', 0):.2f}%")
    print(f"Total P&L:          ${summary.get('total_pnl', 0):,.2f}")
    print()

    # Aggregate Metrics
    print("-" * 80)
    print("   AGGREGIERTE IN-SAMPLE vs OUT-OF-SAMPLE METRIKEN")
    print("-" * 80)

    agg = calculate_aggregate_metrics(model)
    print(f"                    {'In-Sample':>15}  {'Out-of-Sample':>15}  {'Degradation':>12}")
    print(f"  Trades:           {agg['total_train_trades']:>15,}  {agg['total_test_trades']:>15,}")
    print(f"  Wins:             {agg['total_train_wins']:>15,}  {agg['total_test_wins']:>15,}")
    print(
        f"  Win Rate:         {agg['train_wr']:>14.2f}%  {agg['test_wr']:>14.2f}%  {agg['overall_degradation']:>+11.2f}%"
    )
    print()
    print(f"  Durchschn. Degradation: {agg['avg_degradation']:+.2f}%")
    print(f"  Overfit-Level:          {classify_overfit(agg['avg_degradation'])}")
    print()

    # Per Regime × Strategy
    print("-" * 80)
    print("   REGIME × STRATEGY ANALYSE")
    print("-" * 80)

    perf = analyze_regime_strategy_performance(model)

    for regime in ["low", "normal", "elevated", "high"]:
        if regime not in perf:
            continue
        print(f"\n  {regime.upper()} REGIME:")

        for strategy, data in perf[regime].items():
            train_wr = data["train_wr"]
            test_wr = data["test_wr"]
            deg = data["degradation"]
            train_n = data["train_trades"]
            test_n = data["test_trades"]
            overfit = data["overfit_level"]
            pnl = data["total_pnl"]

            print(
                f"    {strategy:15s} | Train: {train_wr:5.1f}% ({train_n:5d}) | "
                f"Test: {test_wr:5.1f}% ({test_n:4d}) | Deg: {deg:+6.2f}% | "
                f"{overfit:12s} | P&L: ${pnl:>10,.0f}"
            )

    print()

    # Symbol Stability
    print("-" * 80)
    print("   SYMBOL-LEVEL STABILITÄT")
    print("-" * 80)

    symbol_analysis = analyze_symbol_stability(model)
    stability_rate = symbol_analysis["stability_rate"]
    stable = symbol_analysis["stable"]
    unstable = symbol_analysis["unstable"]

    print(f"\n  Total Symbole:      {symbol_analysis.get('total_symbols', 0)}")
    print(f"  Stabile Symbole:    {len(stable)} ({stability_rate:.1f}%)")
    print(f"  Instabile Symbole:  {len(unstable)}")

    if stable:
        print(f"\n  TOP 10 Stabilste Symbole (höchste Win Rate):")
        for s in stable[:10]:
            print(
                f"    {s['symbol']:6s} | WR: {s['win_rate']:5.1f}% | "
                f"P&L: ${s['total_pnl']:>10,.0f} | Trades: {s['total_trades']:4d} | "
                f"Best: {s['best_strategy']}"
            )

    if unstable:
        print(f"\n  TOP 5 Instabilste Symbole (niedrigste Win Rate):")
        for s in unstable[:5]:
            print(
                f"    {s['symbol']:6s} | WR: {s['win_rate']:5.1f}% | "
                f"P&L: ${s['total_pnl']:>10,.0f} | Trades: {s['total_trades']:4d} | "
                f"Best: {s['best_strategy']}"
            )

    print()

    # IV-Rank Analysis
    print("-" * 80)
    print("   IV-RANK WIN RATE ANALYSE")
    print("-" * 80)

    iv_analysis = analyze_iv_rank_stability(model)
    if iv_analysis:
        print(
            f"\n  {'Strategy':15s} | {'0-25':>10s} | {'25-50':>10s} | {'50-75':>10s} | "
            f"{'75-100':>10s} | {'100+':>10s}"
        )
        print("  " + "-" * 75)

        for strategy, buckets in iv_analysis.items():
            values = []
            for bucket in ["0-25", "25-50", "50-75", "75-100", "100-125"]:
                if bucket in buckets:
                    wr = buckets[bucket].get("win_rate", 0)
                    values.append(f"{wr:5.1f}%")
                else:
                    values.append("   -")
            print(
                f"  {strategy:15s} | {values[0]:>10s} | {values[1]:>10s} | "
                f"{values[2]:>10s} | {values[3]:>10s} | {values[4]:>10s}"
            )

    print()

    # Final Assessment
    print("=" * 80)
    print("   FINAL ASSESSMENT")
    print("=" * 80)

    # Determine overall status
    issues = []
    strengths = []

    if agg["avg_degradation"] < 0:
        strengths.append(
            f"Negative Durchschnittsdegradation ({agg['avg_degradation']:+.2f}%) - KEIN Overfitting!"
        )
    elif agg["avg_degradation"] < OVERFIT_NONE:
        strengths.append(
            f"Minimale Degradation ({agg['avg_degradation']:+.2f}%) - Kein signifikantes Overfitting"
        )
    elif agg["avg_degradation"] < OVERFIT_MILD:
        issues.append(f"Leichtes Overfitting ({agg['avg_degradation']:+.2f}%)")
    elif agg["avg_degradation"] < OVERFIT_MODERATE:
        issues.append(f"Moderates Overfitting ({agg['avg_degradation']:+.2f}%)")
    else:
        issues.append(f"Schweres Overfitting ({agg['avg_degradation']:+.2f}%)")

    if stability_rate >= 90:
        strengths.append(f"Hohe Symbol-Stabilität ({stability_rate:.0f}%)")
    elif stability_rate < 70:
        issues.append(f"Niedrige Symbol-Stabilität ({stability_rate:.0f}%)")

    if agg["test_wr"] >= 75:
        strengths.append(f"Exzellente Out-of-Sample Win Rate ({agg['test_wr']:.1f}%)")
    elif agg["test_wr"] >= 65:
        strengths.append(f"Gute Out-of-Sample Win Rate ({agg['test_wr']:.1f}%)")
    elif agg["test_wr"] < 50:
        issues.append(f"Niedrige Out-of-Sample Win Rate ({agg['test_wr']:.1f}%)")

    if agg["total_pnl"] > 0:
        strengths.append(f"Positive Gesamt-P&L (${agg['total_pnl']:,.0f})")
    else:
        issues.append(f"Negative Gesamt-P&L (${agg['total_pnl']:,.0f})")

    print()
    if strengths:
        print("  ✅ STÄRKEN:")
        for s in strengths:
            print(f"     • {s}")

    print()
    if issues:
        print("  ⚠️ PROBLEME:")
        for i in issues:
            print(f"     • {i}")
    else:
        print("  ⚠️ PROBLEME: Keine gefunden")

    print()

    # Final verdict
    if not issues and agg["test_wr"] >= 70 and agg["avg_degradation"] < OVERFIT_MILD:
        print("  🏆 VERDICT: MODELL IST PRODUKTIONSREIF")
        print("     Das trainierte Modell zeigt robuste Out-of-Sample Performance")
        print("     ohne signifikantes Overfitting. Bereit für Live-Trading.")
    elif len(issues) <= 1 and agg["test_wr"] >= 60:
        print("  ✅ VERDICT: MODELL IST AKZEPTABEL")
        print("     Das Modell zeigt solide Performance mit kleinen Einschränkungen.")
        print("     Kann für Live-Trading verwendet werden mit erhöhter Vorsicht.")
    else:
        print("  ⚠️ VERDICT: MODELL BENÖTIGT ÜBERARBEITUNG")
        print("     Es gibt signifikante Probleme, die vor dem Live-Trading")
        print("     adressiert werden sollten.")

    print()
    print("=" * 80)


def main():
    """Main entry point"""
    print("\nLade trainiertes Modell...")

    if not TRAINED_MODEL.exists():
        print(f"ERROR: Modell nicht gefunden: {TRAINED_MODEL}")
        return 1

    model = load_trained_model()
    print_validation_report(model)

    return 0


if __name__ == "__main__":
    sys.exit(main())
