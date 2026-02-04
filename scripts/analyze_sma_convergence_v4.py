#!/usr/bin/env python3
"""
SMA Convergence Strategy Analysis v4

KORRIGIERTE These:
- Die KURZEN SMAs (12, 24, 36) konvergieren ZUEINANDER
- Sie nähern sich gleichzeitig der SMA-120 von unten an
- RSI steigt = Momentum baut sich auf
- Multi-Timeframe-Bestätigung verstärkt das Signal

Das ist eine "Compression before Expansion" Strategie:
Die kurzen SMAs kommen zusammen (Volatilitäts-Kontraktion),
bevor ein Ausbruch stattfindet.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Berechnet alle technischen Indikatoren."""
    df = df.copy()

    # SMAs
    df['sma_12'] = df['close'].rolling(12).mean()
    df['sma_24'] = df['close'].rolling(24).mean()
    df['sma_36'] = df['close'].rolling(36).mean()
    df['sma_120'] = df['close'].rolling(120).mean()
    df['sma_250'] = df['close'].rolling(250).mean()  # 1-Jahres-SMA

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # RSI steigend über 3 Tage
    df['rsi_rising'] = df['rsi'] > df['rsi'].shift(3)

    return df


def detect_short_sma_convergence(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """
    Erkennt Konvergenz der KURZEN SMAs (12, 24, 36).

    Kriterien:
    1. Spread zwischen kurzen SMAs wird kleiner (Konvergenz)
    2. Alle kurzen SMAs steigen (aufwärts gerichtet)
    3. Kurze SMAs nähern sich der SMA-120 (optional: von unten)
    """
    df = df.copy()

    # Spread NUR zwischen kurzen SMAs (12, 24, 36)
    short_smas = ['sma_12', 'sma_24', 'sma_36']
    df['short_sma_max'] = df[short_smas].max(axis=1)
    df['short_sma_min'] = df[short_smas].min(axis=1)
    df['short_sma_spread_pct'] = (df['short_sma_max'] - df['short_sma_min']) / df['close'] * 100

    # Spread vor 'lookback' Tagen
    df['short_spread_prev'] = df['short_sma_spread_pct'].shift(lookback)

    # KONVERGENZ: Spread der kurzen SMAs wird kleiner
    df['short_smas_converging'] = df['short_sma_spread_pct'] < df['short_spread_prev']

    # Konvergenz-Geschwindigkeit (wie schnell kommen sie zusammen)
    df['convergence_rate'] = (df['short_spread_prev'] - df['short_sma_spread_pct']) / df['short_spread_prev'] * 100
    df['convergence_rate'] = df['convergence_rate'].clip(-100, 100)

    # Alle kurzen SMAs steigen
    df['sma_12_rising'] = df['sma_12'] > df['sma_12'].shift(lookback)
    df['sma_24_rising'] = df['sma_24'] > df['sma_24'].shift(lookback)
    df['sma_36_rising'] = df['sma_36'] > df['sma_36'].shift(lookback)
    df['all_short_smas_rising'] = df['sma_12_rising'] & df['sma_24_rising'] & df['sma_36_rising']

    # Distanz zur SMA-120 (Durchschnitt der kurzen SMAs)
    df['short_sma_avg'] = df[short_smas].mean(axis=1)
    df['dist_to_sma120_pct'] = (df['sma_120'] - df['short_sma_avg']) / df['close'] * 100

    # Nähern sich der SMA-120 (Distanz wird kleiner)
    df['approaching_sma120'] = df['dist_to_sma120_pct'].abs() < df['dist_to_sma120_pct'].shift(lookback).abs()

    # Position relativ zu SMA-120
    df['short_smas_below_120'] = df['short_sma_avg'] < df['sma_120']
    df['short_smas_above_120'] = df['short_sma_avg'] > df['sma_120']

    # Position relativ zu SMA-250 (1-Jahres-Trend)
    df['price_above_250'] = df['close'] > df['sma_250']
    df['price_below_250'] = df['close'] < df['sma_250']
    df['sma_120_above_250'] = df['sma_120'] > df['sma_250']
    df['sma_120_below_250'] = df['sma_120'] < df['sma_250']

    return df


def simulate_weekly_timeframe(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Simuliert Weekly-Timeframe für Multi-TF Bestätigung."""
    df = df.copy()

    # "Weekly" kurze SMAs (simuliert als längere Daily-Perioden)
    # Weekly SMA-3 ≈ Daily SMA-15, Weekly SMA-5 ≈ Daily SMA-25, etc.
    df['wsma_3'] = df['close'].rolling(15).mean()
    df['wsma_5'] = df['close'].rolling(25).mean()
    df['wsma_8'] = df['close'].rolling(40).mean()
    df['wsma_24'] = df['close'].rolling(120).mean()  # = SMA-120

    # Weekly kurzer Spread
    weekly_short = ['wsma_3', 'wsma_5', 'wsma_8']
    df['weekly_short_spread'] = (df[weekly_short].max(axis=1) - df[weekly_short].min(axis=1)) / df['close'] * 100
    df['weekly_spread_prev'] = df['weekly_short_spread'].shift(lookback)

    # Weekly Konvergenz
    df['weekly_converging'] = df['weekly_short_spread'] < df['weekly_spread_prev']

    # Weekly alle steigend
    df['wsma_3_rising'] = df['wsma_3'] > df['wsma_3'].shift(lookback)
    df['wsma_5_rising'] = df['wsma_5'] > df['wsma_5'].shift(lookback)
    df['wsma_8_rising'] = df['wsma_8'] > df['wsma_8'].shift(lookback)
    df['weekly_all_rising'] = df['wsma_3_rising'] & df['wsma_5_rising'] & df['wsma_8_rising']

    df['weekly_convergence_signal'] = df['weekly_converging'] & df['weekly_all_rising']

    return df


def find_signals(df: pd.DataFrame,
                 max_short_spread: float = 2.0,
                 require_weekly: bool = False,
                 require_below_120: bool = False,
                 require_above_120: bool = False,
                 require_above_250: bool = False,
                 require_below_250: bool = False,
                 min_rsi: float = 40,
                 max_rsi: float = 65) -> pd.DataFrame:
    """
    Findet Konvergenz-Signale.

    Args:
        max_short_spread: Max Spread zwischen kurzen SMAs in %
        require_weekly: Erfordert Weekly-Timeframe-Bestätigung
        require_below_120: Kurze SMAs müssen unter SMA-120 sein
        require_above_120: Kurze SMAs müssen über SMA-120 sein
        require_above_250: Preis muss über SMA-250 sein (bullisher Langfrist-Trend)
        require_below_250: Preis muss unter SMA-250 sein (bearisher Langfrist-Trend)
    """
    condition = (
        (df['short_sma_spread_pct'] < max_short_spread) &  # Kurze SMAs eng zusammen
        df['short_smas_converging'] &                       # UND konvergierend
        df['all_short_smas_rising'] &                       # UND alle steigend
        df['rsi_rising'] &                                  # RSI steigt
        (df['rsi'] >= min_rsi) &
        (df['rsi'] <= max_rsi)
    )

    if require_weekly:
        condition = condition & df['weekly_convergence_signal']

    if require_below_120:
        condition = condition & df['short_smas_below_120']

    if require_above_120:
        condition = condition & df['short_smas_above_120']

    if require_above_250:
        condition = condition & df['price_above_250']

    if require_below_250:
        condition = condition & df['price_below_250']

    return df[condition]


def analyze_results(df: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """Analysiert Trading-Performance."""
    results = []

    for idx in signals.index:
        try:
            pos = df.index.get_loc(idx)

            for days in [5, 10, 20, 30]:
                if pos + days >= len(df):
                    continue

                entry = df.iloc[pos]['close']
                exit_price = df.iloc[pos + days]['close']
                return_pct = (exit_price - entry) / entry * 100

                period = df.iloc[pos:pos + days + 1]['close']
                max_dd = ((period / period.cummax()) - 1).min() * 100
                max_gain = ((period.max() - entry) / entry) * 100

                results.append({
                    'date': idx,
                    'holding_days': days,
                    'return': return_pct,
                    'max_dd': max_dd,
                    'max_gain': max_gain,
                    'short_spread': df.iloc[pos]['short_sma_spread_pct'],
                    'conv_rate': df.iloc[pos]['convergence_rate'],
                    'dist_to_120': df.iloc[pos]['dist_to_sma120_pct'],
                    'rsi': df.iloc[pos]['rsi'],
                    'below_120': df.iloc[pos]['short_smas_below_120'],
                })
        except:
            continue

    return pd.DataFrame(results)


def run_analysis():
    """Hauptanalyse."""

    conn = sqlite3.connect(DB_PATH)

    print("Lade Preisdaten...")
    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    symbols = df['symbol'].unique()
    print(f"Analysiere {len(symbols)} Symbole...")

    # Test verschiedene Konfigurationen
    configs = [
        # Basis-Konfigurationen
        {'name': 'Kurze SMAs konvergieren (unter 120)', 'spread': 2.0, 'below120': True, 'above120': False, 'above250': False, 'below250': False, 'weekly': False},
        {'name': 'Kurze SMAs konvergieren (über 120)', 'spread': 2.0, 'below120': False, 'above120': True, 'above250': False, 'below250': False, 'weekly': False},

        # Mit SMA-250 Filter (Langfrist-Trend)
        {'name': 'Unter 120, ÜBER 250 (bullish LT)', 'spread': 2.0, 'below120': True, 'above120': False, 'above250': True, 'below250': False, 'weekly': False},
        {'name': 'Unter 120, UNTER 250 (bearish LT)', 'spread': 2.0, 'below120': True, 'above120': False, 'above250': False, 'below250': True, 'weekly': False},
        {'name': 'Über 120, ÜBER 250 (strong bull)', 'spread': 2.0, 'below120': False, 'above120': True, 'above250': True, 'below250': False, 'weekly': False},
        {'name': 'Über 120, UNTER 250 (bear rally)', 'spread': 2.0, 'below120': False, 'above120': True, 'above250': False, 'below250': True, 'weekly': False},

        # Mit Weekly-Bestätigung
        {'name': 'Unter 120 + Weekly + über 250', 'spread': 2.0, 'below120': True, 'above120': False, 'above250': True, 'below250': False, 'weekly': True},
        {'name': 'Über 120 + Weekly + über 250', 'spread': 2.0, 'below120': False, 'above120': True, 'above250': True, 'below250': False, 'weekly': True},

        # Lockerer Spread
        {'name': 'Spread 3%, unter 120, über 250', 'spread': 3.0, 'below120': True, 'above120': False, 'above250': True, 'below250': False, 'weekly': False},
    ]

    for config in configs:
        all_results = []

        for symbol in symbols:
            symbol_df = df[df['symbol'] == symbol].copy()
            symbol_df = symbol_df.set_index('date').sort_index()

            if len(symbol_df) < 280:  # Brauchen 250 Tage für SMA-250
                continue

            symbol_df = calculate_indicators(symbol_df)
            symbol_df = detect_short_sma_convergence(symbol_df)
            symbol_df = simulate_weekly_timeframe(symbol_df)

            signals = find_signals(
                symbol_df,
                max_short_spread=config['spread'],
                require_weekly=config['weekly'],
                require_below_120=config['below120'],
                require_above_120=config['above120'],
                require_above_250=config['above250'],
                require_below_250=config['below250']
            )

            if len(signals) > 0:
                results = analyze_results(symbol_df, signals)
                results['symbol'] = symbol
                all_results.append(results)

        print(f"\n{'='*70}")
        print(f"CONFIG: {config['name']}")
        print("="*70)

        if all_results:
            combined = pd.concat(all_results, ignore_index=True)

            for days in [5, 10, 20, 30]:
                subset = combined[combined['holding_days'] == days]['return'].dropna()
                if len(subset) >= 10:
                    wr = (subset > 0).mean() * 100
                    avg = subset.mean()
                    sharpe = avg / subset.std() if subset.std() > 0 else 0
                    print(f"  {days:2}d Hold: n={len(subset):4}, WR={wr:5.1f}%, Avg={avg:+6.2f}%, Sharpe={sharpe:.3f}")
        else:
            print("  Keine Signale gefunden")

    # Detailanalyse für beste Konfiguration
    print(f"\n{'='*70}")
    print("DETAILANALYSE: Kurze SMAs konvergieren UNTER SMA-120")
    print("="*70)

    all_results = []
    for symbol in symbols:
        symbol_df = df[df['symbol'] == symbol].copy()
        symbol_df = symbol_df.set_index('date').sort_index()

        if len(symbol_df) < 150:
            continue

        symbol_df = calculate_indicators(symbol_df)
        symbol_df = detect_short_sma_convergence(symbol_df)
        symbol_df = simulate_weekly_timeframe(symbol_df)

        signals = find_signals(symbol_df, max_short_spread=2.0, require_below_120=True)

        if len(signals) > 0:
            results = analyze_results(symbol_df, signals)
            results['symbol'] = symbol
            all_results.append(results)

    conn.close()

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)

        # Analyse nach Konvergenz-Rate
        print(f"\n--- Nach Konvergenz-Geschwindigkeit (20d Hold) ---")
        subset_20d = combined[combined['holding_days'] == 20].copy()

        if len(subset_20d) > 0:
            subset_20d['conv_bucket'] = pd.cut(
                subset_20d['conv_rate'],
                bins=[-100, 10, 20, 30, 50, 100],
                labels=['<10%', '10-20%', '20-30%', '30-50%', '>50%']
            )

            for bucket in ['<10%', '10-20%', '20-30%', '30-50%', '>50%']:
                bucket_data = subset_20d[subset_20d['conv_bucket'] == bucket]['return'].dropna()
                if len(bucket_data) >= 5:
                    wr = (bucket_data > 0).mean() * 100
                    avg = bucket_data.mean()
                    print(f"  Konvergenz {bucket}: n={len(bucket_data):3}, WR={wr:5.1f}%, Avg={avg:+6.2f}%")

        # Analyse nach Distanz zur SMA-120
        print(f"\n--- Nach Distanz zur SMA-120 (20d Hold) ---")
        if len(subset_20d) > 0:
            subset_20d['dist_bucket'] = pd.cut(
                subset_20d['dist_to_120'],
                bins=[-100, 0, 2, 5, 10, 100],
                labels=['Über 120', '0-2%', '2-5%', '5-10%', '>10%']
            )

            for bucket in ['Über 120', '0-2%', '2-5%', '5-10%', '>10%']:
                bucket_data = subset_20d[subset_20d['dist_bucket'] == bucket]['return'].dropna()
                if len(bucket_data) >= 5:
                    wr = (bucket_data > 0).mean() * 100
                    avg = bucket_data.mean()
                    print(f"  Distanz {bucket}: n={len(bucket_data):3}, WR={wr:5.1f}%, Avg={avg:+6.2f}%")

        # Top Symbole
        print(f"\n--- Top 15 Symbole (20d Hold) ---")
        symbol_stats = subset_20d.groupby('symbol').agg({
            'return': ['count', 'mean', lambda x: (x > 0).mean() * 100]
        }).round(2)
        symbol_stats.columns = ['signals', 'avg_return', 'win_rate']
        symbol_stats = symbol_stats[symbol_stats['signals'] >= 2]
        symbol_stats = symbol_stats.sort_values('avg_return', ascending=False)
        print(symbol_stats.head(15).to_string())


def compare_setups():
    """Vergleicht alle Kombinationen von SMA-120 und SMA-250 Positionen."""

    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    # Alle 4 Kombinationen testen
    setups = {
        'Unter 120 + Über 250': {'below120': True, 'above120': False, 'above250': True, 'below250': False},
        'Unter 120 + Unter 250': {'below120': True, 'above120': False, 'above250': False, 'below250': True},
        'Über 120 + Über 250': {'below120': False, 'above120': True, 'above250': True, 'below250': False},
        'Über 120 + Unter 250': {'below120': False, 'above120': True, 'above250': False, 'below250': True},
    }

    results_by_setup = {}

    for setup_name, params in setups.items():
        setup_results = []

        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol].copy()
            symbol_df = symbol_df.set_index('date').sort_index()

            if len(symbol_df) < 280:
                continue

            symbol_df = calculate_indicators(symbol_df)
            symbol_df = detect_short_sma_convergence(symbol_df)

            signals = find_signals(
                symbol_df,
                max_short_spread=2.0,
                require_below_120=params['below120'],
                require_above_120=params['above120'],
                require_above_250=params['above250'],
                require_below_250=params['below250']
            )

            if len(signals) > 0:
                results = analyze_results(symbol_df, signals)
                results['symbol'] = symbol
                setup_results.append(results)

        if setup_results:
            results_by_setup[setup_name] = pd.concat(setup_results, ignore_index=True)

    conn.close()

    print(f"\n{'='*70}")
    print("VERGLEICH: Alle Kombinationen SMA-120 x SMA-250")
    print("="*70)

    print(f"\n{'Setup':<30} {'Hold':<6} {'n':<6} {'WR%':<8} {'Avg%':<10} {'Sharpe':<8}")
    print("-" * 70)

    for setup_name, results_df in results_by_setup.items():
        for days in [10, 20]:
            subset = results_df[results_df['holding_days'] == days]['return'].dropna()
            if len(subset) >= 5:
                wr = (subset > 0).mean() * 100
                avg = subset.mean()
                sharpe = avg / subset.std() if subset.std() > 0 else 0
                print(f"{setup_name:<30} {days:<6} {len(subset):<6} {wr:<8.1f} {avg:<+10.2f} {sharpe:<8.3f}")

    # Beste Konfiguration identifizieren
    print(f"\n{'='*70}")
    print("BESTE KONFIGURATION (nach Sharpe, 10d Hold)")
    print("="*70)

    best_sharpe = -999
    best_name = None
    for setup_name, results_df in results_by_setup.items():
        subset = results_df[results_df['holding_days'] == 10]['return'].dropna()
        if len(subset) >= 10:
            sharpe = subset.mean() / subset.std() if subset.std() > 0 else 0
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_name = setup_name
                best_data = subset

    if best_name:
        print(f"\n{best_name}:")
        print(f"  Trades:     {len(best_data)}")
        print(f"  Win Rate:   {(best_data > 0).mean() * 100:.1f}%")
        print(f"  Avg Return: {best_data.mean():+.2f}%")
        print(f"  Sharpe:     {best_sharpe:.3f}")


if __name__ == "__main__":
    run_analysis()
    compare_setups()
