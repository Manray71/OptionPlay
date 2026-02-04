#!/usr/bin/env python3
"""
SMA Convergence Strategy Analysis v3

Neue Interpretation der These:
- SMAs konvergieren (kommen alle zusammen) - ENGE SPREIZUNG
- Preis liegt ÜBER allen SMAs (bullisher Kontext)
- RSI steigt = Momentum baut sich auf
- → Ausbruch nach oben erwartet

Dies ist eine "Consolidation before Breakout" Strategie.
Multi-Timeframe-Bestätigung = noch stärkeres Signal.
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

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # RSI steigend über 3 Tage
    df['rsi_rising'] = df['rsi'] > df['rsi'].shift(3)

    return df


def detect_bullish_convergence(df: pd.DataFrame, max_spread_pct: float = 3.0) -> pd.DataFrame:
    """
    Erkennt bullishe Konvergenz - alle SMAs eng zusammen, Preis darüber.

    Bullish Setup:
    1. Preis über ALLEN SMAs (klarer Aufwärtstrend)
    2. SMAs liegen eng zusammen (Konsolidierung)
    3. SMAs in richtiger Reihenfolge: SMA-12 > SMA-24 > SMA-36 > SMA-120
    """
    df = df.copy()

    # Spread zwischen allen SMAs (Max - Min) als % vom Preis
    sma_cols = ['sma_12', 'sma_24', 'sma_36', 'sma_120']
    df['sma_max'] = df[sma_cols].max(axis=1)
    df['sma_min'] = df[sma_cols].min(axis=1)
    df['sma_spread_pct'] = (df['sma_max'] - df['sma_min']) / df['close'] * 100

    # Preis über allen SMAs
    df['price_above_all'] = (
        (df['close'] > df['sma_12']) &
        (df['close'] > df['sma_24']) &
        (df['close'] > df['sma_36']) &
        (df['close'] > df['sma_120'])
    )

    # SMAs in bullisher Reihenfolge (kurz über lang)
    df['smas_aligned'] = (
        (df['sma_12'] > df['sma_24']) &
        (df['sma_24'] > df['sma_36']) &
        (df['sma_36'] > df['sma_120'])
    )

    # SMAs alle steigend
    lookback = 5
    df['sma_12_up'] = df['sma_12'] > df['sma_12'].shift(lookback)
    df['sma_24_up'] = df['sma_24'] > df['sma_24'].shift(lookback)
    df['sma_36_up'] = df['sma_36'] > df['sma_36'].shift(lookback)
    df['sma_120_up'] = df['sma_120'] > df['sma_120'].shift(lookback)
    df['all_smas_rising'] = df['sma_12_up'] & df['sma_24_up'] & df['sma_36_up'] & df['sma_120_up']

    # Spread schrumpft (Konvergenz)
    df['spread_shrinking'] = df['sma_spread_pct'] < df['sma_spread_pct'].shift(5)

    # Bullish Convergence Signal
    df['bullish_convergence'] = (
        (df['sma_spread_pct'] < max_spread_pct) &  # Enge Spreizung
        df['price_above_all'] &                     # Preis über allen
        df['smas_aligned'] &                        # Richtige Reihenfolge
        df['all_smas_rising']                       # Alle steigen
    )

    return df


def simulate_weekly_timeframe(df: pd.DataFrame, max_spread_pct: float = 5.0) -> pd.DataFrame:
    """Simuliert Weekly-Timeframe für Multi-TF Bestätigung."""
    df = df.copy()

    # "Weekly" SMAs
    df['wsma_4'] = df['close'].rolling(20).mean()
    df['wsma_8'] = df['close'].rolling(40).mean()
    df['wsma_12'] = df['close'].rolling(60).mean()
    df['wsma_24'] = df['close'].rolling(120).mean()

    # Weekly Spread
    wsma_cols = ['wsma_4', 'wsma_8', 'wsma_12', 'wsma_24']
    df['wsma_spread'] = (df[wsma_cols].max(axis=1) - df[wsma_cols].min(axis=1)) / df['close'] * 100

    # Weekly bullish alignment
    df['weekly_aligned'] = (
        (df['wsma_4'] > df['wsma_8']) &
        (df['wsma_8'] > df['wsma_12']) &
        (df['wsma_12'] > df['wsma_24']) &
        (df['close'] > df['wsma_4'])
    )

    df['weekly_convergence'] = (
        (df['wsma_spread'] < max_spread_pct) &
        df['weekly_aligned']
    )

    return df


def find_signals(df: pd.DataFrame, require_weekly: bool = False,
                 min_rsi: float = 45, max_rsi: float = 65) -> pd.DataFrame:
    """Findet Trading-Signale."""

    condition = (
        df['bullish_convergence'] &
        df['rsi_rising'] &
        (df['rsi'] >= min_rsi) &
        (df['rsi'] <= max_rsi)
    )

    if require_weekly:
        condition = condition & df['weekly_convergence']

    return df[condition]


def analyze_results(df: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """Analysiert Trading-Performance."""
    results = []

    for idx in signals.index:
        try:
            pos = df.index.get_loc(idx)

            for days in [10, 20, 30]:
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
                    'entry': entry,
                    'return': return_pct,
                    'max_dd': max_dd,
                    'max_gain': max_gain,
                    'rsi': df.iloc[pos]['rsi'],
                    'spread': df.iloc[pos]['sma_spread_pct']
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

    all_daily_results = []
    all_combined_results = []

    for spread_threshold in [2.0, 2.5, 3.0, 3.5]:
        daily_results = []
        combined_results = []

        for symbol in symbols:
            symbol_df = df[df['symbol'] == symbol].copy()
            symbol_df = symbol_df.set_index('date').sort_index()

            if len(symbol_df) < 150:
                continue

            symbol_df = calculate_indicators(symbol_df)
            symbol_df = detect_bullish_convergence(symbol_df, max_spread_pct=spread_threshold)
            symbol_df = simulate_weekly_timeframe(symbol_df)

            # Daily Only
            signals = find_signals(symbol_df, require_weekly=False)
            if len(signals) > 0:
                results = analyze_results(symbol_df, signals)
                results['symbol'] = symbol
                daily_results.append(results)

            # Daily + Weekly
            signals = find_signals(symbol_df, require_weekly=True)
            if len(signals) > 0:
                results = analyze_results(symbol_df, signals)
                results['symbol'] = symbol
                combined_results.append(results)

        # Zusammenfassung für diese Parameter
        print(f"\n{'='*70}")
        print(f"SPREAD THRESHOLD: {spread_threshold}%")
        print("="*70)

        if daily_results:
            daily_df = pd.concat(daily_results, ignore_index=True)

            for days in [10, 20, 30]:
                subset = daily_df[daily_df['holding_days'] == days]['return'].dropna()
                if len(subset) > 20:
                    wr = (subset > 0).mean() * 100
                    avg = subset.mean()
                    sharpe = avg / subset.std() if subset.std() > 0 else 0

                    print(f"Daily Only   ({days}d): n={len(subset):4}, WR={wr:5.1f}%, Avg={avg:+6.2f}%, Sharpe={sharpe:.3f}")

        if combined_results:
            combined_df = pd.concat(combined_results, ignore_index=True)

            for days in [10, 20, 30]:
                subset = combined_df[combined_df['holding_days'] == days]['return'].dropna()
                if len(subset) > 10:
                    wr = (subset > 0).mean() * 100
                    avg = subset.mean()
                    sharpe = avg / subset.std() if subset.std() > 0 else 0

                    print(f"Daily+Weekly ({days}d): n={len(subset):4}, WR={wr:5.1f}%, Avg={avg:+6.2f}%, Sharpe={sharpe:.3f}")

            # Beste Parameter speichern
            if spread_threshold == 3.0:
                all_daily_results = daily_results
                all_combined_results = combined_results

    conn.close()

    # Detailanalyse für beste Parameter
    if all_combined_results:
        combined_df = pd.concat(all_combined_results, ignore_index=True)
        subset_20d = combined_df[combined_df['holding_days'] == 20]

        print(f"\n{'='*70}")
        print("TOP 15 SYMBOLE (Daily + Weekly, 20-Tage Hold, Spread < 3%)")
        print("="*70)

        symbol_stats = subset_20d.groupby('symbol').agg({
            'return': ['count', 'mean', lambda x: (x > 0).mean() * 100]
        }).round(2)
        symbol_stats.columns = ['signals', 'avg_return', 'win_rate']
        symbol_stats = symbol_stats[symbol_stats['signals'] >= 2]
        symbol_stats = symbol_stats.sort_values('avg_return', ascending=False)
        print(symbol_stats.head(15).to_string())

        print(f"\n{'='*70}")
        print("ANALYSE NACH SPREAD-STÄRKE (Daily + Weekly, 20d)")
        print("="*70)

        subset_20d = subset_20d.copy()
        subset_20d['spread_bucket'] = pd.cut(
            subset_20d['spread'],
            bins=[0, 1, 1.5, 2, 2.5, 3],
            labels=['<1%', '1-1.5%', '1.5-2%', '2-2.5%', '2.5-3%']
        )

        for bucket in subset_20d['spread_bucket'].dropna().unique():
            bucket_data = subset_20d[subset_20d['spread_bucket'] == bucket]['return'].dropna()
            if len(bucket_data) >= 5:
                wr = (bucket_data > 0).mean() * 100
                avg = bucket_data.mean()
                print(f"Spread {bucket}: n={len(bucket_data)}, WR={wr:.1f}%, Avg={avg:+.2f}%")

    return all_daily_results, all_combined_results


def compare_to_baseline():
    """Vergleicht gegen Random Entry Baseline."""

    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT underlying as symbol, quote_date as date, underlying_price as close
        FROM options_prices
        WHERE quote_date >= '2021-06-01'
        GROUP BY underlying, quote_date
        ORDER BY underlying, quote_date
    """
    df = pd.read_sql_query(query, conn)
    df['date'] = pd.to_datetime(df['date'])

    random_returns = []
    for symbol in df['symbol'].unique():
        symbol_df = df[df['symbol'] == symbol].set_index('date').sort_index()
        if len(symbol_df) < 150:
            continue

        for i in range(120, len(symbol_df) - 20, 30):
            entry = symbol_df.iloc[i]['close']
            exit_20d = symbol_df.iloc[i + 20]['close']
            random_returns.append((exit_20d - entry) / entry * 100)

    conn.close()

    random_returns = pd.Series(random_returns)
    print(f"\n{'='*70}")
    print("BASELINE (Systematische Einstiege alle 30 Tage, 20d Hold)")
    print("="*70)
    print(f"Trades:     {len(random_returns)}")
    print(f"Win Rate:   {(random_returns > 0).mean() * 100:.1f}%")
    print(f"Avg Return: {random_returns.mean():+.2f}%")
    print(f"Median:     {random_returns.median():+.2f}%")
    print(f"Sharpe:     {random_returns.mean() / random_returns.std():.3f}")


if __name__ == "__main__":
    run_analysis()
    compare_to_baseline()
