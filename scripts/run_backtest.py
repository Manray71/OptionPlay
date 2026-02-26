#!/usr/bin/env python3
"""
OptionPlay - Backtest Runner
============================

Führt Backtests mit den gesammelten historischen Daten durch.

Usage:
    # Standard-Backtest mit allen Daten
    python scripts/run_backtest.py

    # Nur Tech-Sektor
    python scripts/run_backtest.py --sector tech

    # Mit Custom-Parametern
    python scripts/run_backtest.py --profit-target 50 --stop-loss 100

    # Detaillierte Ausgabe
    python scripts/run_backtest.py --verbose
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import List, Dict, Optional

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting import TradeTracker, BacktestEngine, BacktestConfig, BacktestResult
from src.config.watchlist_loader import get_watchlist_loader


def load_historical_data(tracker: TradeTracker, symbols: List[str]) -> Dict[str, List[Dict]]:
    """
    Lädt historische Preisdaten aus der Datenbank.

    Args:
        tracker: TradeTracker-Instanz
        symbols: Liste der Symbole

    Returns:
        Dict mit {symbol: [{date, open, high, low, close, volume}, ...]}
    """
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
    """
    Lädt VIX-Daten aus der Datenbank.

    Returns:
        Liste von {date, close}
    """
    vix_points = tracker.get_vix_data()
    if not vix_points:
        return []

    return [{"date": p.date, "close": p.value} for p in vix_points]


def get_symbols_by_sector(sector: str) -> List[str]:
    """Lädt Symbole für einen Sektor"""
    sector_map = {
        "tech": "information_technology",
        "health": "health_care",
        "finance": "financials",
        "consumer": "consumer_discretionary",
        "communication": "communication_services",
        "industrial": "industrials",
        "staples": "consumer_staples",
        "energy": "energy",
        "utilities": "utilities",
        "materials": "materials",
        "realestate": "real_estate",
    }

    full_sector = sector_map.get(sector.lower(), sector)
    loader = get_watchlist_loader()
    return loader.get_sector(full_sector)


def print_trade_details(result: BacktestResult, max_trades: int = 20):
    """Druckt Details einzelner Trades"""
    print("\n" + "─" * 80)
    print("  TRADE DETAILS (letzte {})".format(min(max_trades, len(result.trades))))
    print("─" * 80)

    # Sortiere nach Exit-Datum, neueste zuerst
    sorted_trades = sorted(result.trades, key=lambda t: t.exit_date, reverse=True)

    print(f"{'Symbol':<7} {'Entry':<12} {'Exit':<12} {'P&L':>10} {'Outcome':<15} {'Hold':>5}")
    print("-" * 80)

    for trade in sorted_trades[:max_trades]:
        pnl_str = f"${trade.realized_pnl:+,.0f}"
        pnl_color = "🟢" if trade.realized_pnl > 0 else "🔴" if trade.realized_pnl < 0 else "⚪"

        print(
            f"{trade.symbol:<7} "
            f"{str(trade.entry_date):<12} "
            f"{str(trade.exit_date):<12} "
            f"{pnl_str:>10} "
            f"{pnl_color} {trade.outcome.value:<13} "
            f"{trade.hold_days:>4}d"
        )

    if len(result.trades) > max_trades:
        print(f"\n  ... und {len(result.trades) - max_trades} weitere Trades")


def print_monthly_breakdown(result: BacktestResult):
    """Druckt monatliche P&L-Aufschlüsselung"""
    if not result.trades:
        return

    print("\n" + "─" * 60)
    print("  MONATLICHE PERFORMANCE")
    print("─" * 60)

    # Gruppiere nach Monat
    by_month: Dict[str, List] = {}
    for trade in result.trades:
        month_key = trade.exit_date.strftime("%Y-%m")
        if month_key not in by_month:
            by_month[month_key] = []
        by_month[month_key].append(trade)

    print(f"{'Monat':<10} {'Trades':>8} {'Gewinner':>10} {'P&L':>12} {'Win Rate':>10}")
    print("-" * 60)

    for month in sorted(by_month.keys()):
        trades = by_month[month]
        winners = len([t for t in trades if t.realized_pnl > 0])
        pnl = sum(t.realized_pnl for t in trades)
        win_rate = (winners / len(trades) * 100) if trades else 0

        pnl_indicator = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

        print(
            f"{month:<10} "
            f"{len(trades):>8} "
            f"{winners:>10} "
            f"{pnl_indicator} ${pnl:>+9,.0f} "
            f"{win_rate:>9.1f}%"
        )

    print("-" * 60)
    total_pnl = sum(t.realized_pnl for t in result.trades)
    print(
        f"{'GESAMT':<10} {len(result.trades):>8} {result.winning_trades:>10} ${total_pnl:>+10,.0f} {result.win_rate:>9.1f}%"
    )


def print_symbol_breakdown(result: BacktestResult, top_n: int = 10):
    """Druckt P&L nach Symbol"""
    if not result.trades:
        return

    print("\n" + "─" * 60)
    print("  PERFORMANCE NACH SYMBOL")
    print("─" * 60)

    # Gruppiere nach Symbol
    by_symbol: Dict[str, List] = {}
    for trade in result.trades:
        if trade.symbol not in by_symbol:
            by_symbol[trade.symbol] = []
        by_symbol[trade.symbol].append(trade)

    # Sortiere nach P&L
    symbol_pnl = [
        (sym, sum(t.realized_pnl for t in trades), len(trades)) for sym, trades in by_symbol.items()
    ]
    symbol_pnl.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  Top {top_n} Gewinner:")
    for sym, pnl, count in symbol_pnl[:top_n]:
        print(f"    {sym:<6} ${pnl:>+8,.0f}  ({count} trades)")

    print(f"\n  Top {top_n} Verlierer:")
    for sym, pnl, count in symbol_pnl[-top_n:]:
        if pnl < 0:
            print(f"    {sym:<6} ${pnl:>+8,.0f}  ({count} trades)")


def save_results(result: BacktestResult, output_path: Path):
    """Speichert Ergebnisse als JSON"""
    data = result.to_dict()
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\nErgebnisse gespeichert: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run backtest with historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Symbol-Auswahl
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols")
    parser.add_argument("--sector", type=str, help="Test single sector (tech, health, etc.)")
    parser.add_argument(
        "--all", action="store_true", default=True, help="Test all available symbols (default)"
    )

    # Backtest-Parameter
    parser.add_argument(
        "--capital", type=float, default=100000, help="Initial capital (default: 100000)"
    )
    parser.add_argument(
        "--profit-target", type=float, default=50, help="Profit target %% (default: 50)"
    )
    parser.add_argument("--stop-loss", type=float, default=100, help="Stop loss %% (default: 100)")
    parser.add_argument(
        "--min-score", type=float, default=5.0, help="Minimum pullback score (default: 5.0)"
    )

    # Output
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output with trade details"
    )
    parser.add_argument("--output", type=str, help="Save results to JSON file")

    args = parser.parse_args()

    print("═" * 70)
    print("  OPTIONPLAY BACKTEST")
    print("═" * 70)

    # Tracker laden
    tracker = TradeTracker()

    # Status prüfen
    stats = tracker.get_storage_stats()
    if stats["symbols_with_price_data"] == 0:
        print("\n❌ Keine historischen Daten gefunden!")
        print("   Führe zuerst aus: python scripts/collect_historical_data.py --all")
        sys.exit(1)

    print(
        f"\n  Datenbank: {stats['symbols_with_price_data']} Symbole, {stats['total_price_bars']:,} Bars"
    )

    # VIX-Daten prüfen
    vix_range = tracker.get_vix_range()
    if vix_range:
        print(f"  VIX-Daten: {vix_range[0]} bis {vix_range[1]}")
    else:
        print("  VIX-Daten: Keine (Backtest läuft ohne VIX)")

    # Symbole bestimmen
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.sector:
        symbols = get_symbols_by_sector(args.sector)
        print(f"\n  Sektor: {args.sector} ({len(symbols)} Symbole)")
    else:
        # Alle Symbole mit Daten
        symbol_info = tracker.list_symbols_with_price_data()
        symbols = [s["symbol"] for s in symbol_info]

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

    # Zeitraum aus Daten bestimmen
    all_dates = []
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar["date"]
            if isinstance(d, str):
                d = date.fromisoformat(d)
            all_dates.append(d)

    start_date = min(all_dates)
    end_date = max(all_dates)

    print(f"  Zeitraum: {start_date} bis {end_date}")

    # Backtest-Config
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.capital,
        profit_target_pct=args.profit_target,
        stop_loss_pct=args.stop_loss,
        min_pullback_score=args.min_score,
    )

    print(f"\n  Config:")
    print(f"    Kapital:       ${config.initial_capital:,.0f}")
    print(f"    Profit Target: {config.profit_target_pct}%")
    print(f"    Stop Loss:     {config.stop_loss_pct}%")
    print(f"    Min Score:     {config.min_pullback_score}")

    # Backtest ausführen
    print("\n" + "═" * 70)
    print("  RUNNING BACKTEST...")
    print("═" * 70)

    engine = BacktestEngine(config)
    result = engine.run_sync(
        symbols=symbols_with_data,
        historical_data=historical_data,
        vix_data=vix_data,
    )

    # Ergebnisse anzeigen
    print(result.summary())

    # Zusätzliche Details wenn verbose
    if args.verbose:
        print_trade_details(result)
        print_monthly_breakdown(result)
        print_symbol_breakdown(result)

    # Speichern wenn gewünscht
    if args.output:
        output_path = Path(args.output)
        save_results(result, output_path)

    # Kurze Zusammenfassung
    print("\n" + "═" * 70)
    roi = (result.total_pnl / config.initial_capital) * 100
    print(
        f"  ROI: {roi:+.2f}%  |  Win Rate: {result.win_rate:.1f}%  |  Profit Factor: {result.profit_factor:.2f}"
    )
    print("═" * 70)


if __name__ == "__main__":
    main()
