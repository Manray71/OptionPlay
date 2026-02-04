#!/usr/bin/env python3
"""
SMA Convergence Strategy Analysis v2

Präzisierte These:
- Die KURZEN SMAs (12, 24, 36) müssen AUFWÄRTS zur SMA-120 konvergieren
- Multi-Timeframe-Bestätigung verstärkt das Signal
- RSI steigend bestätigt das Momentum

Timeframes:
- Daily: SMA 12, 24, 36, 120
- Weekly (simuliert): SMA 2, 4, 6, 20 (entspricht ~10, 20, 30, 100 Tage)
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Tuple

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

    # Preis über SMA-120 (bullish bias)
    df['price_above_sma120'] = df['close'] > df['sma_120']

    return df


def detect_upward_convergence(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """
    Erkennt AUFWÄRTS-Konvergenz der kurzen SMAs zur SMA-120.

    Kriterien:
    1. Kurze SMAs unter SMA-120 (Raum zum Konvergieren)
    2. Kurze SMAs steigen stärker als SMA-120 (nähern sich von unten)
    3. Spread wird kleiner (Konvergenz)
    4. Alle kurzen SMAs zeigen aufwärts
    """
    df = df.copy()

    # Spread zwischen kürzesten und längsten SMA (in % vom Preis)
    df['short_sma_avg'] = (df['sma_12'] + df['sma_24'] + df['sma_36']) / 3
    df['spread_pct'] = (df['sma_120'] - df['short_sma_avg']) / df['close'] * 100

    # Spread vor 'lookback' Tagen
    df['spread_prev'] = df['spread_pct'].shift(lookback)

    # Konvergenz: Spread wird kleiner (weniger negativ oder weniger positiv)
    df['spread_shrinking'] = df['spread_pct'].abs() < df['spread_prev'].abs()

    # Kurze SMAs steigen
    df['sma_12_rising'] = df['sma_12'] > df['sma_12'].shift(lookback)
    df['sma_24_rising'] = df['sma_24'] > df['sma_24'].shift(lookback)
    df['sma_36_rising'] = df['sma_36'] > df['sma_36'].shift(lookback)
    df['all_short_smas_rising'] = df['sma_12_rising'] & df['sma_24_rising'] & df['sma_36_rising']

    # Aufwärts-Konvergenz: Kurze SMAs unter SMA-120 aber steigend
    df['upward_convergence'] = (
        (df['short_sma_avg'] < df['sma_120']) &  # Kurze unter Langen
        df['all_short_smas_rising'] &             # Alle kurzen steigen
        df['spread_shrinking']                    # Spread schrumpft
    )

    # Stärke der Konvergenz (0-100)
    df['convergence_speed'] = (df['spread_prev'].abs() - df['spread_pct'].abs()) / df['spread_prev'].abs() * 100
    df['convergence_speed'] = df['convergence_speed'].clip(0, 100)

    return df


def simulate_weekly_timeframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simuliert Weekly-Timeframe durch längere SMAs.

    Weekly entspricht ca. 5 Handelstage, also:
    - Weekly SMA-4 ≈ Daily SMA-20
    - Weekly SMA-8 ≈ Daily SMA-40
    - Weekly SMA-12 ≈ Daily SMA-60
    - Weekly SMA-24 ≈ Daily SMA-120
    """
    df = df.copy()

    # "Weekly" SMAs (simuliert als längere Daily-Perioden)
    df['wsma_4'] = df['close'].rolling(20).mean()   # Weekly SMA-4
    df['wsma_8'] = df['close'].rolling(40).mean()   # Weekly SMA-8
    df['wsma_12'] = df['close'].rolling(60).mean()  # Weekly SMA-12
    df['wsma_24'] = df['close'].rolling(120).mean() # Weekly SMA-24 (= SMA-120)

    # Weekly Spread
    df['weekly_short_avg'] = (df['wsma_4'] + df['wsma_8'] + df['wsma_12']) / 3
    df['weekly_spread'] = (df['wsma_24'] - df['weekly_short_avg']) / df['close'] * 100

    # Weekly SMAs steigend
    lookback_weekly = 20  # ~4 Wochen
    df['wsma_4_rising'] = df['wsma_4'] > df['wsma_4'].shift(lookback_weekly)
    df['wsma_8_rising'] = df['wsma_8'] > df['wsma_8'].shift(lookback_weekly)
    df['wsma_12_rising'] = df['wsma_12'] > df['wsma_12'].shift(lookback_weekly)

    df['weekly_convergence'] = (
        (df['weekly_short_avg'] < df['wsma_24']) &
        df['wsma_4_rising'] &
        df['wsma_8_rising'] &
        df['wsma_12_rising']
    )

    return df


def find_convergence_signals(df: pd.DataFrame,
                             require_weekly: bool = False) -> pd.DataFrame:
    """
    Findet Konvergenz-Signale.

    Args:
        require_weekly: Wenn True, muss auch Weekly-Timeframe konvergieren
    """
    # Basis-Signal: Daily aufwärts-konvergierend + RSI steigend
    condition = (
        df['upward_convergence'] &
        df['rsi_rising'] &
        (df['rsi'] >= 40) &
        (df['rsi'] <= 65)  # Nicht überkauft
    )

    if require_weekly:
        condition = condition & df['weekly_convergence']

    return df[condition]


def analyze_breakouts(df: pd.DataFrame, signals: pd.DataFrame,
                      holding_days: int = 20) -> pd.DataFrame:
    """Analysiert Performance nach Signalen."""
    results = []

    for idx in signals.index:
        try:
            pos = df.index.get_loc(idx)
            if pos + holding_days >= len(df):
                continue

            entry_price = df.iloc[pos]['close']
            exit_price = df.iloc[pos + holding_days]['close']
            return_pct = (exit_price - entry_price) / entry_price * 100

            # Max Drawdown
            period = df.iloc[pos:pos + holding_days + 1]['close']
            max_dd = ((period / period.cummax()) - 1).min() * 100

            # Max Gain
            max_gain = ((period.max() - entry_price) / entry_price) * 100

            results.append({
                'date': idx,
                'entry': entry_price,
                'exit': exit_price,
                'return_20d': return_pct,
                'max_dd': max_dd,
                'max_gain': max_gain,
                'rsi': df.iloc[pos]['rsi'],
                'spread': df.iloc[pos]['spread_pct'],
                'conv_speed': df.iloc[pos].get('convergence_speed', 0)
            })
        except:
            continue

    return pd.DataFrame(results)


def run_full_analysis():
    """Führt vollständige Analyse durch."""

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

    # Ergebnisse sammeln
    daily_only_results = []
    daily_weekly_results = []

    for symbol in symbols:
        symbol_df = df[df['symbol'] == symbol].copy()
        symbol_df = symbol_df.set_index('date').sort_index()

        if len(symbol_df) < 150:
            continue

        # Indikatoren berechnen
        symbol_df = calculate_indicators(symbol_df)
        symbol_df = detect_upward_convergence(symbol_df)
        symbol_df = simulate_weekly_timeframe(symbol_df)

        # Daily-Only Signale
        daily_signals = find_convergence_signals(symbol_df, require_weekly=False)
        if len(daily_signals) > 0:
            results = analyze_breakouts(symbol_df, daily_signals)
            results['symbol'] = symbol
            results['signal_type'] = 'daily_only'
            daily_only_results.append(results)

        # Daily + Weekly Signale (stärker)
        combined_signals = find_convergence_signals(symbol_df, require_weekly=True)
        if len(combined_signals) > 0:
            results = analyze_breakouts(symbol_df, combined_signals)
            results['symbol'] = symbol
            results['signal_type'] = 'daily_weekly'
            daily_weekly_results.append(results)

    conn.close()

    # Ergebnisse zusammenführen
    print("\n" + "="*70)
    print("ERGEBNISSE: SMA AUFWÄRTS-KONVERGENZ STRATEGIE")
    print("="*70)

    # Daily-Only Analyse
    if daily_only_results:
        daily_df = pd.concat(daily_only_results, ignore_index=True)
        print(f"\n--- DAILY TIMEFRAME ONLY ---")
        print(f"Anzahl Signale:  {len(daily_df)}")
        print(f"Symbole:         {daily_df['symbol'].nunique()}")

        valid = daily_df['return_20d'].dropna()
        print(f"Win Rate:        {(valid > 0).mean() * 100:.1f}%")
        print(f"Avg Return:      {valid.mean():+.2f}%")
        print(f"Median Return:   {valid.median():+.2f}%")
        print(f"Std Dev:         {valid.std():.2f}%")
        print(f"Sharpe:          {valid.mean() / valid.std():.3f}")
        print(f"Avg Max DD:      {daily_df['max_dd'].mean():.2f}%")
        print(f"Avg Max Gain:    {daily_df['max_gain'].mean():.2f}%")

    # Daily + Weekly Analyse
    if daily_weekly_results:
        combined_df = pd.concat(daily_weekly_results, ignore_index=True)
        print(f"\n--- DAILY + WEEKLY CONFIRMATION ---")
        print(f"Anzahl Signale:  {len(combined_df)}")
        print(f"Symbole:         {combined_df['symbol'].nunique()}")

        valid = combined_df['return_20d'].dropna()
        print(f"Win Rate:        {(valid > 0).mean() * 100:.1f}%")
        print(f"Avg Return:      {valid.mean():+.2f}%")
        print(f"Median Return:   {valid.median():+.2f}%")
        print(f"Std Dev:         {valid.std():.2f}%")
        print(f"Sharpe:          {valid.mean() / valid.std():.3f}")
        print(f"Avg Max DD:      {combined_df['max_dd'].mean():.2f}%")
        print(f"Avg Max Gain:    {combined_df['max_gain'].mean():.2f}%")

        # Vergleich
        if daily_only_results:
            daily_wr = (daily_df['return_20d'].dropna() > 0).mean() * 100
            combined_wr = (valid > 0).mean() * 100
            daily_avg = daily_df['return_20d'].dropna().mean()
            combined_avg = valid.mean()

            print(f"\n--- VERGLEICH ---")
            print(f"Win Rate Improvement:   {combined_wr - daily_wr:+.1f}pp")
            print(f"Avg Return Improvement: {combined_avg - daily_avg:+.2f}%")

    # Top Symbole bei Combined Signal
    if daily_weekly_results:
        print(f"\n{'='*70}")
        print("TOP 15 SYMBOLE (Daily + Weekly Convergence)")
        print("="*70)

        symbol_stats = combined_df.groupby('symbol').agg({
            'return_20d': ['count', 'mean', lambda x: (x > 0).mean() * 100]
        }).round(2)
        symbol_stats.columns = ['signals', 'avg_return', 'win_rate']
        symbol_stats = symbol_stats[symbol_stats['signals'] >= 2]  # Min 2 Signale
        symbol_stats = symbol_stats.sort_values('avg_return', ascending=False)
        print(symbol_stats.head(15).to_string())

    # Analyse nach Konvergenz-Geschwindigkeit
    if daily_weekly_results:
        print(f"\n{'='*70}")
        print("ANALYSE NACH KONVERGENZ-GESCHWINDIGKEIT")
        print("="*70)

        combined_df['speed_bucket'] = pd.cut(
            combined_df['conv_speed'],
            bins=[0, 20, 40, 60, 80, 100],
            labels=['0-20%', '20-40%', '40-60%', '60-80%', '80-100%']
        )

        for bucket in combined_df['speed_bucket'].dropna().unique():
            bucket_data = combined_df[combined_df['speed_bucket'] == bucket]['return_20d'].dropna()
            if len(bucket_data) >= 5:
                wr = (bucket_data > 0).mean() * 100
                avg = bucket_data.mean()
                print(f"Speed {bucket}: n={len(bucket_data)}, WR={wr:.1f}%, Avg={avg:+.2f}%")

    return daily_df if daily_only_results else None, combined_df if daily_weekly_results else None


def analyze_holding_periods():
    """Analysiert optimale Halteperiode für die Strategie."""

    conn = sqlite3.connect(DB_PATH)

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

        symbol_df = calculate_indicators(symbol_df)
        symbol_df = detect_upward_convergence(symbol_df)
        symbol_df = simulate_weekly_timeframe(symbol_df)

        # Nur starke Signale (Daily + Weekly)
        signals = find_convergence_signals(symbol_df, require_weekly=True)

        for idx in signals.index:
            try:
                pos = symbol_df.index.get_loc(idx)
                entry = symbol_df.iloc[pos]['close']

                for days in holding_results.keys():
                    if pos + days < len(symbol_df):
                        exit_price = symbol_df.iloc[pos + days]['close']
                        return_pct = (exit_price - entry) / entry * 100
                        holding_results[days].append(return_pct)
            except:
                continue

    conn.close()

    print(f"\n{'='*70}")
    print("OPTIMALE HALTEPERIODE (Daily + Weekly Signals)")
    print("="*70)
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
    daily_results, combined_results = run_full_analysis()
    analyze_holding_periods()
