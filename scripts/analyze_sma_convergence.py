#!/usr/bin/env python3
"""
SMA Convergence Strategy Analysis

These: Konvergierende SMA 12, 24, 36, 120 bei steigendem RSI führt zu einem Ausbruch.

Analysiert historische Daten um diese These zu validieren.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# Datenbank-Pfad
DB_PATH = Path.home() / ".optionplay" / "trades.db"


def load_price_data(symbol: str, conn: sqlite3.Connection) -> pd.DataFrame:
    """Lädt Tagespreise für ein Symbol aus options_prices."""
    query = """
        SELECT quote_date as date, underlying_price as close
        FROM options_prices
        WHERE underlying = ?
        GROUP BY quote_date
        ORDER BY quote_date
    """
    df = pd.read_sql_query(query, conn, params=(symbol,))
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')
    return df


def calculate_smas(df: pd.DataFrame) -> pd.DataFrame:
    """Berechnet SMA 12, 24, 36, 120."""
    df = df.copy()
    df['sma_12'] = df['close'].rolling(window=12).mean()
    df['sma_24'] = df['close'].rolling(window=24).mean()
    df['sma_36'] = df['close'].rolling(window=36).mean()
    df['sma_120'] = df['close'].rolling(window=120).mean()
    return df


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Berechnet RSI."""
    df = df.copy()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df


def calculate_convergence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet Konvergenz-Score der SMAs.

    Konvergenz = Alle SMAs nah beieinander (geringe Spreizung relativ zum Preis)
    """
    df = df.copy()

    # Maximale Spreizung zwischen allen SMAs
    sma_cols = ['sma_12', 'sma_24', 'sma_36', 'sma_120']
    df['sma_max'] = df[sma_cols].max(axis=1)
    df['sma_min'] = df[sma_cols].min(axis=1)

    # Spreizung als % des Preises
    df['sma_spread_pct'] = (df['sma_max'] - df['sma_min']) / df['close'] * 100

    # Konvergenz-Score: Je geringer die Spreizung, desto höher
    # Typische Spreizung: 2-15%, Konvergenz wenn < 3%
    df['convergence_score'] = 100 - (df['sma_spread_pct'] * 10)
    df['convergence_score'] = df['convergence_score'].clip(0, 100)

    # RSI steigend (über 3 Tage)
    df['rsi_rising'] = df['rsi'] > df['rsi'].shift(3)

    # RSI beschleunigt (aktuelle Änderung > vorherige Änderung)
    df['rsi_change'] = df['rsi'] - df['rsi'].shift(1)
    df['rsi_accelerating'] = df['rsi_change'] > df['rsi_change'].shift(1)

    return df


def find_convergence_signals(df: pd.DataFrame,
                             max_spread_pct: float = 3.0,
                             min_rsi: float = 40,
                             max_rsi: float = 60) -> pd.DataFrame:
    """
    Findet Konvergenz-Signale.

    Kriterien:
    - SMA Spread < max_spread_pct (eng zusammen)
    - RSI zwischen min_rsi und max_rsi (nicht überkauft/überverkauft)
    - RSI steigend über 3 Tage
    """
    signals = df[
        (df['sma_spread_pct'] < max_spread_pct) &
        (df['rsi'] >= min_rsi) &
        (df['rsi'] <= max_rsi) &
        (df['rsi_rising'] == True)
    ].copy()

    return signals


def analyze_breakout_after_signal(df: pd.DataFrame,
                                  signal_date: pd.Timestamp,
                                  holding_days: list = [5, 10, 20, 30]) -> dict:
    """
    Analysiert Performance nach einem Signal.

    Returns dict mit Returns für verschiedene Halteperioden.
    """
    try:
        signal_idx = df.index.get_loc(signal_date)
        entry_price = df.iloc[signal_idx]['close']

        results = {
            'signal_date': signal_date,
            'entry_price': entry_price,
            'rsi_at_signal': df.iloc[signal_idx]['rsi'],
            'spread_at_signal': df.iloc[signal_idx]['sma_spread_pct'],
        }

        for days in holding_days:
            exit_idx = signal_idx + days
            if exit_idx < len(df):
                exit_price = df.iloc[exit_idx]['close']
                return_pct = (exit_price - entry_price) / entry_price * 100
                results[f'return_{days}d'] = return_pct

                # Max Drawdown in der Periode
                period_data = df.iloc[signal_idx:exit_idx+1]
                max_price = period_data['close'].cummax()
                drawdown = (period_data['close'] - max_price) / max_price * 100
                results[f'max_dd_{days}d'] = drawdown.min()
            else:
                results[f'return_{days}d'] = None
                results[f'max_dd_{days}d'] = None

        return results
    except Exception as e:
        return None


def run_analysis(symbols: list = None,
                 max_spread_pct: float = 3.0,
                 min_rsi: float = 40,
                 max_rsi: float = 60):
    """Hauptanalyse über alle Symbole."""

    conn = sqlite3.connect(DB_PATH)

    # Alle Symbole laden wenn nicht spezifiziert
    if symbols is None:
        query = "SELECT DISTINCT underlying FROM options_prices"
        symbols = pd.read_sql_query(query, conn)['underlying'].tolist()

    print(f"Analysiere {len(symbols)} Symbole...")
    print(f"Parameter: max_spread={max_spread_pct}%, RSI={min_rsi}-{max_rsi}")
    print("-" * 60)

    all_results = []
    signal_counts = defaultdict(int)

    for symbol in symbols:
        try:
            df = load_price_data(symbol, conn)

            if len(df) < 150:  # Brauchen mindestens 120 Tage für SMA-120
                continue

            df = calculate_smas(df)
            df = calculate_rsi(df)
            df = calculate_convergence(df)

            signals = find_convergence_signals(df, max_spread_pct, min_rsi, max_rsi)
            signal_counts[symbol] = len(signals)

            for signal_date in signals.index:
                result = analyze_breakout_after_signal(df, signal_date)
                if result:
                    result['symbol'] = symbol
                    all_results.append(result)

        except Exception as e:
            print(f"Fehler bei {symbol}: {e}")
            continue

    conn.close()

    if not all_results:
        print("Keine Signale gefunden!")
        return None

    results_df = pd.DataFrame(all_results)

    # Statistiken berechnen
    print(f"\n{'='*60}")
    print("ERGEBNISSE: SMA Convergence Strategy")
    print(f"{'='*60}")
    print(f"Anzahl Signale gesamt: {len(results_df)}")
    print(f"Symbole mit Signalen: {len([s for s, c in signal_counts.items() if c > 0])}")
    print()

    for days in [5, 10, 20, 30]:
        col = f'return_{days}d'
        if col in results_df.columns:
            valid = results_df[col].dropna()
            if len(valid) > 0:
                win_rate = (valid > 0).mean() * 100
                avg_return = valid.mean()
                median_return = valid.median()
                std_return = valid.std()
                max_return = valid.max()
                min_return = valid.min()

                dd_col = f'max_dd_{days}d'
                avg_dd = results_df[dd_col].dropna().mean()

                print(f"--- {days}-Tage Holding ---")
                print(f"  Trades:      {len(valid)}")
                print(f"  Win Rate:    {win_rate:.1f}%")
                print(f"  Avg Return:  {avg_return:+.2f}%")
                print(f"  Median:      {median_return:+.2f}%")
                print(f"  Std Dev:     {std_return:.2f}%")
                print(f"  Best:        {max_return:+.2f}%")
                print(f"  Worst:       {min_return:+.2f}%")
                print(f"  Avg Max DD:  {avg_dd:.2f}%")
                print()

    # Top Symbole
    symbol_stats = results_df.groupby('symbol').agg({
        'return_20d': ['count', 'mean', lambda x: (x > 0).mean() * 100]
    }).round(2)
    symbol_stats.columns = ['signals', 'avg_return_20d', 'win_rate_20d']
    symbol_stats = symbol_stats.sort_values('avg_return_20d', ascending=False)

    print(f"\n{'='*60}")
    print("TOP 15 SYMBOLE (nach 20-Tage Return)")
    print(f"{'='*60}")
    print(symbol_stats.head(15).to_string())

    print(f"\n{'='*60}")
    print("BOTTOM 10 SYMBOLE (nach 20-Tage Return)")
    print(f"{'='*60}")
    print(symbol_stats.tail(10).to_string())

    # Konvergenz-Level Analyse
    print(f"\n{'='*60}")
    print("ANALYSE NACH KONVERGENZ-STÄRKE")
    print(f"{'='*60}")

    results_df['spread_bucket'] = pd.cut(results_df['spread_at_signal'],
                                         bins=[0, 1, 2, 3, 5, 10],
                                         labels=['<1%', '1-2%', '2-3%', '3-5%', '5-10%'])

    for bucket in results_df['spread_bucket'].dropna().unique():
        bucket_data = results_df[results_df['spread_bucket'] == bucket]['return_20d'].dropna()
        if len(bucket_data) > 5:
            print(f"\nSpread {bucket}:")
            print(f"  Trades: {len(bucket_data)}, Win Rate: {(bucket_data > 0).mean()*100:.1f}%, Avg: {bucket_data.mean():+.2f}%")

    # RSI-Level Analyse
    print(f"\n{'='*60}")
    print("ANALYSE NACH RSI-LEVEL")
    print(f"{'='*60}")

    results_df['rsi_bucket'] = pd.cut(results_df['rsi_at_signal'],
                                      bins=[30, 40, 50, 60, 70],
                                      labels=['30-40', '40-50', '50-60', '60-70'])

    for bucket in results_df['rsi_bucket'].dropna().unique():
        bucket_data = results_df[results_df['rsi_bucket'] == bucket]['return_20d'].dropna()
        if len(bucket_data) > 5:
            print(f"\nRSI {bucket}:")
            print(f"  Trades: {len(bucket_data)}, Win Rate: {(bucket_data > 0).mean()*100:.1f}%, Avg: {bucket_data.mean():+.2f}%")

    return results_df


def run_parameter_optimization():
    """Optimiert die Parameter für die Strategie."""

    print("\n" + "="*60)
    print("PARAMETER-OPTIMIERUNG")
    print("="*60)

    best_sharpe = -999
    best_params = None
    results_summary = []

    for max_spread in [2.0, 2.5, 3.0, 3.5, 4.0]:
        for min_rsi in [35, 40, 45]:
            for max_rsi in [55, 60, 65]:
                if min_rsi >= max_rsi:
                    continue

                print(f"\nTeste: spread<{max_spread}%, RSI {min_rsi}-{max_rsi}...", end=" ")

                # Leise Analyse durchführen
                import io
                import sys
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()

                try:
                    results = run_analysis(
                        max_spread_pct=max_spread,
                        min_rsi=min_rsi,
                        max_rsi=max_rsi
                    )
                finally:
                    sys.stdout = old_stdout

                if results is not None and len(results) > 20:
                    valid_returns = results['return_20d'].dropna()
                    if len(valid_returns) > 10:
                        avg_return = valid_returns.mean()
                        std_return = valid_returns.std()
                        win_rate = (valid_returns > 0).mean() * 100

                        # Sharpe-ähnliche Metrik (ohne risk-free rate)
                        sharpe = avg_return / std_return if std_return > 0 else 0

                        results_summary.append({
                            'max_spread': max_spread,
                            'min_rsi': min_rsi,
                            'max_rsi': max_rsi,
                            'trades': len(valid_returns),
                            'win_rate': win_rate,
                            'avg_return': avg_return,
                            'sharpe': sharpe
                        })

                        print(f"n={len(valid_returns)}, WR={win_rate:.1f}%, Avg={avg_return:+.2f}%, Sharpe={sharpe:.2f}")

                        if sharpe > best_sharpe:
                            best_sharpe = sharpe
                            best_params = (max_spread, min_rsi, max_rsi)
                else:
                    print("Zu wenig Signale")

    print(f"\n{'='*60}")
    print("BESTE PARAMETER")
    print(f"{'='*60}")
    if best_params:
        print(f"Max Spread: {best_params[0]}%")
        print(f"RSI Range:  {best_params[1]}-{best_params[2]}")
        print(f"Sharpe:     {best_sharpe:.2f}")

    # Zusammenfassung als DataFrame
    if results_summary:
        summary_df = pd.DataFrame(results_summary)
        summary_df = summary_df.sort_values('sharpe', ascending=False)
        print(f"\n{'='*60}")
        print("TOP 10 PARAMETER-KOMBINATIONEN")
        print(f"{'='*60}")
        print(summary_df.head(10).to_string(index=False))

    return best_params


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='SMA Convergence Strategy Analysis')
    parser.add_argument('--optimize', action='store_true', help='Run parameter optimization')
    parser.add_argument('--spread', type=float, default=3.0, help='Max SMA spread in %%')
    parser.add_argument('--rsi-min', type=float, default=40, help='Min RSI')
    parser.add_argument('--rsi-max', type=float, default=60, help='Max RSI')
    parser.add_argument('--symbols', nargs='+', help='Specific symbols to analyze')

    args = parser.parse_args()

    if args.optimize:
        best = run_parameter_optimization()
        if best:
            print(f"\n\nRe-running with best parameters...")
            run_analysis(max_spread_pct=best[0], min_rsi=best[1], max_rsi=best[2])
    else:
        run_analysis(
            symbols=args.symbols,
            max_spread_pct=args.spread,
            min_rsi=args.rsi_min,
            max_rsi=args.rsi_max
        )
