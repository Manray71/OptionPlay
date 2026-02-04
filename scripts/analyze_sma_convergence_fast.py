#!/usr/bin/env python3
"""
SMA Convergence Strategy Analysis - Fast Version

Schnellere Version mit weniger Parametern und direkter SQL-Aggregation.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def analyze_convergence_strategy():
    """Hauptanalyse mit optimierter Datenverarbeitung."""

    conn = sqlite3.connect(DB_PATH)

    # Alle Preisdaten auf einmal laden (effizienter)
    print("Lade Preisdaten...")
    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    print(f"Geladen: {len(df):,} Datenpunkte für {df['symbol'].nunique()} Symbole")

    all_results = []

    # Parameter-Kombinationen zum Testen
    param_grid = [
        {'spread': 2.0, 'rsi_min': 40, 'rsi_max': 55},
        {'spread': 2.5, 'rsi_min': 40, 'rsi_max': 60},
        {'spread': 3.0, 'rsi_min': 40, 'rsi_max': 60},
        {'spread': 3.0, 'rsi_min': 45, 'rsi_max': 55},
        {'spread': 2.0, 'rsi_min': 45, 'rsi_max': 55},
        {'spread': 4.0, 'rsi_min': 35, 'rsi_max': 65},
    ]

    for params in param_grid:
        print(f"\nTeste: spread<{params['spread']}%, RSI {params['rsi_min']}-{params['rsi_max']}...")

        signals_list = []

        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol].copy()
            symbol_df = symbol_df.set_index('date').sort_index()

            if len(symbol_df) < 150:
                continue

            # SMAs berechnen
            symbol_df['sma_12'] = symbol_df['close'].rolling(12).mean()
            symbol_df['sma_24'] = symbol_df['close'].rolling(24).mean()
            symbol_df['sma_36'] = symbol_df['close'].rolling(36).mean()
            symbol_df['sma_120'] = symbol_df['close'].rolling(120).mean()

            # RSI berechnen
            delta = symbol_df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            symbol_df['rsi'] = 100 - (100 / (1 + rs))
            symbol_df['rsi_rising'] = symbol_df['rsi'] > symbol_df['rsi'].shift(3)

            # Konvergenz berechnen
            sma_cols = ['sma_12', 'sma_24', 'sma_36', 'sma_120']
            symbol_df['sma_spread'] = (symbol_df[sma_cols].max(axis=1) - symbol_df[sma_cols].min(axis=1)) / symbol_df['close'] * 100

            # Signale finden
            signals = symbol_df[
                (symbol_df['sma_spread'] < params['spread']) &
                (symbol_df['rsi'] >= params['rsi_min']) &
                (symbol_df['rsi'] <= params['rsi_max']) &
                (symbol_df['rsi_rising'] == True)
            ]

            # Returns berechnen
            for idx, row in signals.iterrows():
                try:
                    pos = symbol_df.index.get_loc(idx)
                    if pos + 20 < len(symbol_df):
                        entry = row['close']
                        exit_20d = symbol_df.iloc[pos + 20]['close']
                        return_20d = (exit_20d - entry) / entry * 100

                        # Max Drawdown
                        period = symbol_df.iloc[pos:pos+21]['close']
                        max_dd = ((period / period.cummax()) - 1).min() * 100

                        signals_list.append({
                            'symbol': symbol,
                            'date': idx,
                            'spread': row['sma_spread'],
                            'rsi': row['rsi'],
                            'return_20d': return_20d,
                            'max_dd': max_dd
                        })
                except:
                    continue

        if signals_list:
            signals_df = pd.DataFrame(signals_list)
            valid = signals_df['return_20d'].dropna()

            win_rate = (valid > 0).mean() * 100
            avg_return = valid.mean()
            sharpe = avg_return / valid.std() if valid.std() > 0 else 0
            avg_dd = signals_df['max_dd'].mean()

            result = {
                'max_spread': params['spread'],
                'rsi_range': f"{params['rsi_min']}-{params['rsi_max']}",
                'trades': len(valid),
                'win_rate': round(win_rate, 1),
                'avg_return': round(avg_return, 2),
                'sharpe': round(sharpe, 3),
                'avg_max_dd': round(avg_dd, 2)
            }
            all_results.append(result)

            print(f"  Trades: {len(valid)}, Win Rate: {win_rate:.1f}%, Avg: {avg_return:+.2f}%, Sharpe: {sharpe:.3f}")

    conn.close()

    # Ergebnis-Zusammenfassung
    print("\n" + "="*70)
    print("PARAMETER-VERGLEICH")
    print("="*70)

    results_df = pd.DataFrame(all_results).sort_values('sharpe', ascending=False)
    print(results_df.to_string(index=False))

    # Beste Parameter
    if len(results_df) > 0:
        best = results_df.iloc[0]
        print(f"\n{'='*70}")
        print("BESTE PARAMETER")
        print(f"{'='*70}")
        print(f"Max Spread:    {best['max_spread']}%")
        print(f"RSI Range:     {best['rsi_range']}")
        print(f"Trades:        {best['trades']}")
        print(f"Win Rate:      {best['win_rate']}%")
        print(f"Avg Return:    {best['avg_return']}%")
        print(f"Sharpe Ratio:  {best['sharpe']}")
        print(f"Avg Max DD:    {best['avg_max_dd']}%")

    return results_df


def compare_to_baseline():
    """Vergleicht die Strategie gegen Buy-and-Hold Baseline."""

    conn = sqlite3.connect(DB_PATH)

    print("\n" + "="*70)
    print("VERGLEICH: SMA Convergence vs. Random Entry")
    print("="*70)

    # Random Sample von Einstiegspunkten
    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        WHERE quote_date >= '2021-06-01'
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    # Zufällige Einstiege berechnen
    random_returns = []
    for symbol in df['symbol'].unique():
        symbol_df = df[df['symbol'] == symbol].set_index('date').sort_index()
        if len(symbol_df) < 150:
            continue

        # Alle 20 Tage ein "zufälliger" Einstieg
        for i in range(120, len(symbol_df) - 20, 20):
            entry = symbol_df.iloc[i]['close']
            exit_20d = symbol_df.iloc[i + 20]['close']
            return_20d = (exit_20d - entry) / entry * 100
            random_returns.append(return_20d)

    conn.close()

    random_returns = pd.Series(random_returns)
    print(f"\nBaseline (Systematische Einstiege alle 20 Tage):")
    print(f"  Trades:     {len(random_returns)}")
    print(f"  Win Rate:   {(random_returns > 0).mean() * 100:.1f}%")
    print(f"  Avg Return: {random_returns.mean():+.2f}%")
    print(f"  Median:     {random_returns.median():+.2f}%")
    print(f"  Std Dev:    {random_returns.std():.2f}%")

    return random_returns


def analyze_by_vix_regime():
    """Analysiert Performance in verschiedenen VIX-Regimes."""

    conn = sqlite3.connect(DB_PATH)

    print("\n" + "="*70)
    print("ANALYSE NACH VIX-REGIME")
    print("="*70)

    # VIX-Daten laden
    vix_df = pd.read_sql_query(
        "SELECT date, value as vix FROM vix_data ORDER BY date",
        conn
    )
    vix_df['date'] = pd.to_datetime(vix_df['date'])
    vix_df = vix_df.set_index('date')

    # Preisdaten laden
    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    results_by_regime = {'low': [], 'medium': [], 'high': [], 'extreme': []}

    for symbol in df['symbol'].unique():
        symbol_df = df[df['symbol'] == symbol].copy()
        symbol_df = symbol_df.set_index('date').sort_index()

        if len(symbol_df) < 150:
            continue

        # SMAs und RSI berechnen
        symbol_df['sma_12'] = symbol_df['close'].rolling(12).mean()
        symbol_df['sma_24'] = symbol_df['close'].rolling(24).mean()
        symbol_df['sma_36'] = symbol_df['close'].rolling(36).mean()
        symbol_df['sma_120'] = symbol_df['close'].rolling(120).mean()

        delta = symbol_df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        symbol_df['rsi'] = 100 - (100 / (1 + rs))
        symbol_df['rsi_rising'] = symbol_df['rsi'] > symbol_df['rsi'].shift(3)

        sma_cols = ['sma_12', 'sma_24', 'sma_36', 'sma_120']
        symbol_df['sma_spread'] = (symbol_df[sma_cols].max(axis=1) - symbol_df[sma_cols].min(axis=1)) / symbol_df['close'] * 100

        # VIX hinzufügen
        symbol_df = symbol_df.join(vix_df, how='left')
        symbol_df['vix'] = symbol_df['vix'].ffill()

        # Signale mit besten Parametern (spread < 2.5%, RSI 40-60)
        signals = symbol_df[
            (symbol_df['sma_spread'] < 2.5) &
            (symbol_df['rsi'] >= 40) &
            (symbol_df['rsi'] <= 60) &
            (symbol_df['rsi_rising'] == True) &
            (symbol_df['vix'].notna())
        ]

        for idx, row in signals.iterrows():
            try:
                pos = symbol_df.index.get_loc(idx)
                if pos + 20 < len(symbol_df):
                    entry = row['close']
                    exit_20d = symbol_df.iloc[pos + 20]['close']
                    return_20d = (exit_20d - entry) / entry * 100
                    vix = row['vix']

                    # VIX-Regime bestimmen
                    if vix < 15:
                        regime = 'low'
                    elif vix < 20:
                        regime = 'medium'
                    elif vix < 30:
                        regime = 'high'
                    else:
                        regime = 'extreme'

                    results_by_regime[regime].append(return_20d)
            except:
                continue

    conn.close()

    # Ergebnisse ausgeben
    for regime, returns in results_by_regime.items():
        if returns:
            returns = pd.Series(returns)
            vix_range = {'low': '<15', 'medium': '15-20', 'high': '20-30', 'extreme': '>30'}[regime]
            print(f"\nVIX {vix_range} ({regime.upper()}):")
            print(f"  Trades:     {len(returns)}")
            print(f"  Win Rate:   {(returns > 0).mean() * 100:.1f}%")
            print(f"  Avg Return: {returns.mean():+.2f}%")
            print(f"  Median:     {returns.median():+.2f}%")


def analyze_holding_periods():
    """Analysiert optimale Halteperiode."""

    conn = sqlite3.connect(DB_PATH)

    print("\n" + "="*70)
    print("OPTIMALE HALTEPERIODE")
    print("="*70)

    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    holding_results = {d: [] for d in [5, 10, 15, 20, 25, 30, 40, 50, 60]}

    for symbol in df['symbol'].unique():
        symbol_df = df[df['symbol'] == symbol].copy()
        symbol_df = symbol_df.set_index('date').sort_index()

        if len(symbol_df) < 180:
            continue

        # Indikatoren berechnen
        symbol_df['sma_12'] = symbol_df['close'].rolling(12).mean()
        symbol_df['sma_24'] = symbol_df['close'].rolling(24).mean()
        symbol_df['sma_36'] = symbol_df['close'].rolling(36).mean()
        symbol_df['sma_120'] = symbol_df['close'].rolling(120).mean()

        delta = symbol_df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        symbol_df['rsi'] = 100 - (100 / (1 + rs))
        symbol_df['rsi_rising'] = symbol_df['rsi'] > symbol_df['rsi'].shift(3)

        sma_cols = ['sma_12', 'sma_24', 'sma_36', 'sma_120']
        symbol_df['sma_spread'] = (symbol_df[sma_cols].max(axis=1) - symbol_df[sma_cols].min(axis=1)) / symbol_df['close'] * 100

        # Signale
        signals = symbol_df[
            (symbol_df['sma_spread'] < 2.5) &
            (symbol_df['rsi'] >= 40) &
            (symbol_df['rsi'] <= 60) &
            (symbol_df['rsi_rising'] == True)
        ]

        for idx, row in signals.iterrows():
            try:
                pos = symbol_df.index.get_loc(idx)
                entry = row['close']

                for days in holding_results.keys():
                    if pos + days < len(symbol_df):
                        exit_price = symbol_df.iloc[pos + days]['close']
                        return_pct = (exit_price - entry) / entry * 100
                        holding_results[days].append(return_pct)
            except:
                continue

    conn.close()

    print(f"\n{'Days':<6} {'Trades':<8} {'Win%':<8} {'Avg Ret':<10} {'Sharpe':<8}")
    print("-" * 50)

    for days, returns in sorted(holding_results.items()):
        if returns:
            returns = pd.Series(returns)
            win_rate = (returns > 0).mean() * 100
            avg_ret = returns.mean()
            sharpe = avg_ret / returns.std() if returns.std() > 0 else 0

            print(f"{days:<6} {len(returns):<8} {win_rate:<8.1f} {avg_ret:<+10.2f} {sharpe:<8.3f}")


if __name__ == "__main__":
    # Hauptanalyse
    results = analyze_convergence_strategy()

    # Baseline-Vergleich
    compare_to_baseline()

    # VIX-Regime Analyse
    analyze_by_vix_regime()

    # Halteperioden-Analyse
    analyze_holding_periods()
