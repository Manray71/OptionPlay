#!/usr/bin/env python3
"""
Black-Scholes vs Market Price Comparison
=========================================

Vergleicht die Black-Scholes Preise mit den echten Marktpreisen
aus der Tradier-Datensammlung.

Analysiert:
- Pricing Accuracy (MAE, RMSE, MAPE)
- IV Comparison (BS-estimated vs Market)
- Fehler nach Moneyness (OTM, ATM, ITM)
- Fehler nach DTE
- Fehler nach Symbol/Sektor
"""

import sys
from pathlib import Path
from datetime import date, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import logging

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.trade_tracker import TradeTracker, OptionBar
from src.pricing.black_scholes import (
    black_scholes_put,
    implied_volatility,
    batch_historical_volatility,
    batch_estimate_iv,
    estimate_iv_calibrated,
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    """Einzelner Vergleichspunkt"""
    symbol: str
    occ_symbol: str
    trade_date: date
    expiry: date
    strike: float
    spot_price: float
    dte: int
    moneyness: float  # strike / spot

    market_price: float
    bs_price: float
    bs_iv_used: float

    market_iv: Optional[float]

    error: float  # bs_price - market_price
    pct_error: float  # error / market_price * 100


def load_comparison_data(tracker: TradeTracker, limit: int = 50000) -> pd.DataFrame:
    """
    Lädt Options- und Preisdaten für den Vergleich.
    """
    logger.info("Loading options data from database...")

    # Query alle Options-Daten
    with tracker._get_connection() as conn:
        query = """
            SELECT
                o.occ_symbol,
                o.underlying,
                o.strike,
                o.expiry,
                o.option_type,
                o.trade_date,
                o.close as option_close,
                o.volume
            FROM options_data o
            WHERE o.option_type = 'P'  -- Nur Puts für Bull-Put-Spreads
            AND o.close > 0.01  -- Mindestpreis
            AND o.volume > 0    -- Nur mit Volumen
            ORDER BY o.trade_date DESC
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))

    logger.info(f"Loaded {len(df)} option price records")
    return df


def get_spot_prices(tracker: TradeTracker, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Lädt Spot-Preise für alle Symbole.
    """
    logger.info(f"Loading spot prices for {len(symbols)} symbols...")

    spot_data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            df = pd.DataFrame([
                {'date': bar.date, 'close': bar.close}
                for bar in price_data.bars
            ])
            df['date'] = pd.to_datetime(df['date']).dt.date
            spot_data[symbol] = df.set_index('date')['close'].to_dict()

    return spot_data


def calculate_hv_for_date(
    spot_prices: Dict[date, float],
    target_date: date,
    window: int = 20
) -> Optional[float]:
    """
    Berechnet Historical Volatility für ein bestimmtes Datum.
    """
    # Hole die letzten 'window + 5' Tage (Buffer für Wochenenden)
    dates = sorted([d for d in spot_prices.keys() if d <= target_date], reverse=True)

    if len(dates) < window + 1:
        return None

    prices = np.array([spot_prices[d] for d in dates[:window + 1]])

    # Log-Returns
    returns = np.log(prices[:-1] / prices[1:])

    # Annualisierte Volatilität
    hv = np.std(returns, ddof=1) * np.sqrt(252)

    return float(hv)


def run_comparison(
    df: pd.DataFrame,
    spot_data: Dict[str, Dict[date, float]],
    vix_data: Optional[Dict[date, float]] = None
) -> List[ComparisonResult]:
    """
    Führt den Vergleich zwischen Black-Scholes und Marktpreisen durch.
    """
    results = []

    # Konvertiere Datumsformate
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    df['expiry'] = pd.to_datetime(df['expiry']).dt.date

    total = len(df)
    processed = 0
    skipped = 0

    logger.info(f"Running comparison for {total} option prices...")

    for idx, row in df.iterrows():
        symbol = row['underlying']
        trade_date = row['trade_date']
        expiry = row['expiry']
        strike = row['strike']
        market_price = row['option_close']

        # Skip wenn keine Spot-Daten
        if symbol not in spot_data:
            skipped += 1
            continue

        symbol_spots = spot_data[symbol]

        if trade_date not in symbol_spots:
            skipped += 1
            continue

        spot_price = symbol_spots[trade_date]

        # DTE berechnen
        dte = (expiry - trade_date).days
        if dte <= 0:
            skipped += 1
            continue

        # Moneyness
        moneyness = strike / spot_price

        # Historical Volatility berechnen
        hv = calculate_hv_for_date(symbol_spots, trade_date)
        if hv is None:
            skipped += 1
            continue

        # VIX für Datum (falls verfügbar)
        vix = vix_data.get(trade_date) if vix_data else None

        # Kalibrierte IV-Schätzung verwenden
        iv_estimate = estimate_iv_calibrated(
            historical_volatility=hv,
            symbol=symbol,
            vix=vix,
            moneyness=moneyness,
            dte=dte,
        )

        # Black-Scholes Preis
        T = dte / 365.0
        bs_price = black_scholes_put(spot_price, strike, T, 0.05, iv_estimate)

        # Market IV berechnen (Newton-Raphson)
        market_iv = implied_volatility(
            market_price, spot_price, strike, T, 0.05, "P"
        )

        # Error berechnen
        error = bs_price - market_price
        pct_error = (error / market_price * 100) if market_price > 0 else 0

        results.append(ComparisonResult(
            symbol=symbol,
            occ_symbol=row['occ_symbol'],
            trade_date=trade_date,
            expiry=expiry,
            strike=strike,
            spot_price=spot_price,
            dte=dte,
            moneyness=moneyness,
            market_price=market_price,
            bs_price=bs_price,
            bs_iv_used=iv_estimate,
            market_iv=market_iv,
            error=error,
            pct_error=pct_error,
        ))

        processed += 1

        if processed % 5000 == 0:
            logger.info(f"  Processed {processed}/{total}...")

    logger.info(f"Comparison complete: {processed} processed, {skipped} skipped")
    return results


def analyze_results(results: List[ComparisonResult]) -> Dict:
    """
    Analysiert die Vergleichsergebnisse.
    """
    if not results:
        return {}

    df = pd.DataFrame([r.__dict__ for r in results])

    # Grundlegende Metriken
    errors = df['error'].values
    pct_errors = df['pct_error'].values

    mae = np.mean(np.abs(errors))
    rmse = np.sqrt(np.mean(errors ** 2))
    mape = np.mean(np.abs(pct_errors))
    bias = np.mean(errors)

    # IV Vergleich
    iv_df = df[df['market_iv'].notna()]
    if len(iv_df) > 0:
        iv_diff = iv_df['bs_iv_used'] - iv_df['market_iv']
        iv_mae = np.mean(np.abs(iv_diff))
        iv_bias = np.mean(iv_diff)
    else:
        iv_mae = None
        iv_bias = None

    # Nach Moneyness
    df['moneyness_bucket'] = pd.cut(
        df['moneyness'],
        bins=[0, 0.90, 0.95, 1.00, 1.05, 10.0],
        labels=['Deep OTM (<90%)', 'OTM (90-95%)', 'ATM (95-100%)', 'ITM (100-105%)', 'Deep ITM (>105%)']
    )
    by_moneyness = df.groupby('moneyness_bucket').agg({
        'error': ['mean', 'std', 'count'],
        'pct_error': 'mean'
    }).round(4)

    # Nach DTE
    df['dte_bucket'] = pd.cut(
        df['dte'],
        bins=[0, 14, 30, 45, 60, 500],
        labels=['0-14', '15-30', '31-45', '46-60', '>60']
    )
    by_dte = df.groupby('dte_bucket').agg({
        'error': ['mean', 'std', 'count'],
        'pct_error': 'mean'
    }).round(4)

    # Nach Symbol
    by_symbol = df.groupby('symbol').agg({
        'error': ['mean', 'std', 'count'],
        'pct_error': 'mean'
    }).round(4)
    by_symbol.columns = ['mean_error', 'std_error', 'count', 'mean_pct_error']
    by_symbol = by_symbol.sort_values('count', ascending=False)

    return {
        'total_comparisons': len(results),
        'overall': {
            'mae': mae,
            'rmse': rmse,
            'mape': mape,
            'bias': bias,
        },
        'iv_comparison': {
            'iv_mae': iv_mae,
            'iv_bias': iv_bias,
            'samples_with_market_iv': len(iv_df),
        },
        'by_moneyness': by_moneyness,
        'by_dte': by_dte,
        'by_symbol': by_symbol,
        'df': df,  # Für weitere Analyse
    }


def print_report(analysis: Dict):
    """
    Druckt einen formatierten Bericht.
    """
    print("\n" + "=" * 70)
    print("BLACK-SCHOLES vs MARKET PRICE COMPARISON REPORT")
    print("=" * 70)

    print(f"\nTotal Comparisons: {analysis['total_comparisons']:,}")

    print("\n" + "-" * 70)
    print("OVERALL ACCURACY")
    print("-" * 70)
    overall = analysis['overall']
    print(f"  Mean Absolute Error (MAE):     ${overall['mae']:.4f}")
    print(f"  Root Mean Square Error (RMSE): ${overall['rmse']:.4f}")
    print(f"  Mean Absolute % Error (MAPE):  {overall['mape']:.2f}%")
    print(f"  Bias (avg error):              ${overall['bias']:.4f}")
    print(f"    {'(BS overprices)' if overall['bias'] > 0 else '(BS underprices)'}")

    iv = analysis['iv_comparison']
    print("\n" + "-" * 70)
    print("IMPLIED VOLATILITY COMPARISON")
    print("-" * 70)
    print(f"  Samples with Market IV:        {iv['samples_with_market_iv']:,}")
    if iv['iv_mae'] is not None:
        print(f"  IV MAE:                        {iv['iv_mae'] * 100:.2f}%")
        print(f"  IV Bias:                       {iv['iv_bias'] * 100:.2f}%")
        print(f"    {'(BS IV estimate too high)' if iv['iv_bias'] > 0 else '(BS IV estimate too low)'}")

    print("\n" + "-" * 70)
    print("BY MONEYNESS (Strike / Spot)")
    print("-" * 70)
    print(f"{'Category':<22} {'Mean Err':>10} {'Std Err':>10} {'% Err':>10} {'Count':>8}")
    print("-" * 70)
    by_money = analysis['by_moneyness']
    for bucket in by_money.index:
        row = by_money.loc[bucket]
        mean_err = row[('error', 'mean')]
        std_err = row[('error', 'std')]
        pct_err = row[('pct_error', 'mean')]
        count = row[('error', 'count')]
        print(f"{str(bucket):<22} ${mean_err:>9.4f} ${std_err:>9.4f} {pct_err:>9.1f}% {count:>8.0f}")

    print("\n" + "-" * 70)
    print("BY DAYS TO EXPIRATION")
    print("-" * 70)
    print(f"{'DTE Range':<12} {'Mean Err':>10} {'Std Err':>10} {'% Err':>10} {'Count':>8}")
    print("-" * 70)
    by_dte = analysis['by_dte']
    for bucket in by_dte.index:
        row = by_dte.loc[bucket]
        mean_err = row[('error', 'mean')]
        std_err = row[('error', 'std')]
        pct_err = row[('pct_error', 'mean')]
        count = row[('error', 'count')]
        print(f"{str(bucket):<12} ${mean_err:>9.4f} ${std_err:>9.4f} {pct_err:>9.1f}% {count:>8.0f}")

    print("\n" + "-" * 70)
    print("TOP 15 SYMBOLS BY DATA VOLUME")
    print("-" * 70)
    print(f"{'Symbol':<8} {'Mean Err':>10} {'Std Err':>10} {'% Err':>10} {'Count':>8}")
    print("-" * 70)
    by_symbol = analysis['by_symbol'].head(15)
    for symbol in by_symbol.index:
        row = by_symbol.loc[symbol]
        print(f"{symbol:<8} ${row['mean_error']:>9.4f} ${row['std_error']:>9.4f} "
              f"{row['mean_pct_error']:>9.1f}% {row['count']:>8.0f}")

    print("\n" + "-" * 70)
    print("INTERPRETATION")
    print("-" * 70)

    mae = overall['mae']
    mape = overall['mape']
    bias = overall['bias']

    if mape < 10:
        accuracy_rating = "EXCELLENT"
    elif mape < 20:
        accuracy_rating = "GOOD"
    elif mape < 30:
        accuracy_rating = "MODERATE"
    else:
        accuracy_rating = "NEEDS IMPROVEMENT"

    print(f"  Overall Accuracy Rating: {accuracy_rating}")
    print()

    if abs(bias) > mae * 0.5:
        if bias > 0:
            print("  NOTE: Significant positive bias detected.")
            print("        Black-Scholes consistently overprices options.")
            print("        Consider reducing IV estimate multiplier.")
        else:
            print("  NOTE: Significant negative bias detected.")
            print("        Black-Scholes consistently underprices options.")
            print("        Consider increasing IV estimate multiplier.")

    # Moneyness-spezifische Empfehlungen
    print()
    print("  Moneyness Analysis:")
    for bucket in by_money.index:
        row = by_money.loc[bucket]
        pct_err = row[('pct_error', 'mean')]
        if abs(pct_err) > 20:
            print(f"    - {bucket}: {pct_err:.1f}% error - needs calibration")

    print("\n" + "=" * 70)


def main():
    logger.info("Starting Black-Scholes vs Market comparison...")

    tracker = TradeTracker()

    # Daten laden
    df = load_comparison_data(tracker, limit=100000)

    if df.empty:
        logger.error("No options data found!")
        return

    # Unique symbols
    symbols = df['underlying'].unique().tolist()
    logger.info(f"Found {len(symbols)} unique symbols")

    # Spot-Preise laden
    spot_data = get_spot_prices(tracker, symbols)
    logger.info(f"Loaded spot prices for {len(spot_data)} symbols")

    # VIX-Daten laden
    vix_data = {}
    vix_points = tracker.get_vix_data()
    for point in vix_points:
        vix_data[point.date] = point.value
    logger.info(f"Loaded {len(vix_data)} VIX data points")

    # Vergleich durchführen
    results = run_comparison(df, spot_data, vix_data)

    if not results:
        logger.error("No comparison results generated!")
        return

    # Analyse
    analysis = analyze_results(results)

    # Bericht ausgeben
    print_report(analysis)

    # Optional: DataFrame für weitere Analyse speichern
    if 'df' in analysis:
        output_path = Path(__file__).parent.parent / 'reports' / 'bs_comparison.csv'
        output_path.parent.mkdir(exist_ok=True)
        analysis['df'].to_csv(output_path, index=False)
        logger.info(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    main()
