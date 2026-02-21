#!/usr/bin/env python3
"""
OptionPlay - Calculate Derived Metrics
======================================

Berechnet abgeleitete Metriken aus den vorhandenen Datenbank-Daten:
1. IV Rank (252 Tage) - aus options_greeks
2. IV Percentile (252 Tage) - aus options_greeks
3. SPY Correlation (60 Tage) - aus options_prices.underlying_price
4. Historical Volatility (30 Tage) - aus options_prices.underlying_price

Usage:
    # Alle Metriken für alle Symbole
    python scripts/calculate_derived_metrics.py

    # Nur bestimmte Symbole
    python scripts/calculate_derived_metrics.py --symbols AAPL MSFT

    # Nur IV-Metriken
    python scripts/calculate_derived_metrics.py --iv-only

    # Nur Correlation
    python scripts/calculate_derived_metrics.py --correlation-only
"""

import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import math

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def get_symbols_from_fundamentals() -> List[str]:
    """Holt alle Symbole aus symbol_fundamentals"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM symbol_fundamentals ORDER BY symbol")
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    return symbols


def get_symbols_from_options() -> List[str]:
    """Holt alle Symbole aus options_prices"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT underlying FROM options_prices ORDER BY underlying")
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    return symbols


# =============================================================================
# IV RANK & IV PERCENTILE
# =============================================================================

def calculate_iv_metrics(symbol: str, lookback_days: int = 252) -> Optional[Dict]:
    """
    Berechnet IV Rank und IV Percentile für ein Symbol.

    IV Rank = (Current IV - Min IV) / (Max IV - Min IV) * 100
    IV Percentile = % der Tage mit niedrigerer IV als heute

    Args:
        symbol: Ticker-Symbol
        lookback_days: Anzahl Tage für die Berechnung (default: 252 = 1 Jahr)

    Returns:
        Dict mit iv_rank, iv_percentile, current_iv oder None
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Hole ATM IV für jeden Tag (ca. Delta -0.5 für Puts oder +0.5 für Calls)
    # Vereinfacht: Nimm die durchschnittliche IV pro Tag
    cursor.execute("""
        SELECT
            og.quote_date,
            AVG(og.iv_calculated) as avg_iv
        FROM options_greeks og
        JOIN options_prices op ON og.options_price_id = op.id
        WHERE op.underlying = ?
          AND og.iv_calculated IS NOT NULL
          AND og.iv_calculated > 0
          AND og.iv_calculated < 3.0  -- Filter unrealistische Werte (>300%)
          AND op.quote_date >= date('now', ?)
        GROUP BY og.quote_date
        ORDER BY og.quote_date DESC
    """, (symbol.upper(), f'-{lookback_days} days'))

    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 20:  # Mindestens 20 Datenpunkte
        return None

    iv_values = [row[1] for row in rows]
    current_iv = iv_values[0]  # Neuester Wert

    min_iv = min(iv_values)
    max_iv = max(iv_values)

    # IV Rank
    if max_iv - min_iv > 0:
        iv_rank = (current_iv - min_iv) / (max_iv - min_iv) * 100
    else:
        iv_rank = 50.0  # Default wenn keine Range

    # IV Percentile (% der Werte die niedriger sind)
    lower_count = sum(1 for iv in iv_values if iv < current_iv)
    iv_percentile = lower_count / len(iv_values) * 100

    return {
        "iv_rank": round(iv_rank, 1),
        "iv_percentile": round(iv_percentile, 1),
        "current_iv": round(current_iv * 100, 1),  # Als Prozent
        "min_iv": round(min_iv * 100, 1),
        "max_iv": round(max_iv * 100, 1),
        "data_points": len(iv_values)
    }


# =============================================================================
# SPY CORRELATION
# =============================================================================

def get_daily_prices(symbol: str, days: int = 90) -> List[Tuple[str, float]]:
    """Holt tägliche Schlusskurse aus options_prices.underlying_price"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Hole die letzten N Tage relativ zum neuesten Datum in der DB
    cursor.execute("""
        SELECT quote_date, AVG(underlying_price) as price
        FROM options_prices
        WHERE underlying = ?
          AND underlying_price IS NOT NULL
          AND quote_date >= (SELECT date(MAX(quote_date), ?) FROM options_prices WHERE underlying = ?)
        GROUP BY quote_date
        ORDER BY quote_date ASC
    """, (symbol.upper(), f'-{days} days', symbol.upper()))

    rows = cursor.fetchall()
    conn.close()

    return [(row[0], row[1]) for row in rows]


def calculate_returns(prices: List[Tuple[str, float]]) -> Dict[str, float]:
    """Berechnet tägliche Returns als {date: return}"""
    returns = {}
    for i in range(1, len(prices)):
        date_str = prices[i][0]
        prev_price = prices[i-1][1]
        curr_price = prices[i][1]
        if prev_price > 0:
            returns[date_str] = (curr_price - prev_price) / prev_price
    return returns


def calculate_correlation(returns1: Dict[str, float], returns2: Dict[str, float]) -> Optional[float]:
    """Berechnet Pearson Correlation zwischen zwei Return-Serien"""
    # Finde gemeinsame Daten
    common_dates = set(returns1.keys()) & set(returns2.keys())

    if len(common_dates) < 20:
        return None

    x = [returns1[d] for d in common_dates]
    y = [returns2[d] for d in common_dates]

    n = len(x)
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(x[i] * y[i] for i in range(n))
    sum_x2 = sum(xi ** 2 for xi in x)
    sum_y2 = sum(yi ** 2 for yi in y)

    numerator = n * sum_xy - sum_x * sum_y
    denominator = math.sqrt((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2))

    if denominator == 0:
        return None

    return numerator / denominator


def calculate_spy_correlation(symbol: str, days: int = 60) -> Optional[Dict]:
    """
    Berechnet Korrelation eines Symbols zu SPY.

    Args:
        symbol: Ticker-Symbol
        days: Anzahl Tage für die Berechnung

    Returns:
        Dict mit correlation, data_points oder None
    """
    if symbol.upper() == 'SPY':
        return {"correlation": 1.0, "data_points": 0}

    # Hole Preise für beide
    symbol_prices = get_daily_prices(symbol, days)
    spy_prices = get_daily_prices('SPY', days)

    if len(symbol_prices) < 20 or len(spy_prices) < 20:
        return None

    # Berechne Returns
    symbol_returns = calculate_returns(symbol_prices)
    spy_returns = calculate_returns(spy_prices)

    # Berechne Korrelation
    corr = calculate_correlation(symbol_returns, spy_returns)

    if corr is None:
        return None

    return {
        "correlation": round(corr, 3),
        "data_points": len(set(symbol_returns.keys()) & set(spy_returns.keys()))
    }


# =============================================================================
# HISTORICAL VOLATILITY
# =============================================================================

def calculate_historical_volatility(symbol: str, days: int = 30) -> Optional[Dict]:
    """
    Berechnet annualisierte Historical Volatility.

    HV = StdDev(daily returns) * sqrt(252)

    Args:
        symbol: Ticker-Symbol
        days: Anzahl Tage für die Berechnung

    Returns:
        Dict mit hv_30d oder None
    """
    prices = get_daily_prices(symbol, days + 20)  # Mehr Buffer für Feiertage

    if len(prices) < 15:  # Mindestens 15 Datenpunkte
        return None

    returns = calculate_returns(prices)
    return_values = list(returns.values())

    if len(return_values) < 15:  # Mindestens 15 Returns
        return None

    # Nimm die letzten verfügbaren Returns (maximal days)
    return_values = return_values[-min(days, len(return_values)):]

    # Berechne Standardabweichung
    mean = sum(return_values) / len(return_values)
    variance = sum((r - mean) ** 2 for r in return_values) / len(return_values)
    std_dev = math.sqrt(variance)

    # Annualisieren (252 Handelstage)
    hv = std_dev * math.sqrt(252) * 100  # Als Prozent

    return {
        "hv_30d": round(hv, 1),
        "data_points": len(return_values)
    }


# =============================================================================
# EARNINGS MOVE STATS
# =============================================================================

def calculate_earnings_move_stats(symbol: str) -> Optional[Dict]:
    """
    Berechnet durchschnittliche und Standardabweichung der absoluten
    Kursreaktion auf Earnings-Events.

    Kreuzt earnings_history.earnings_date mit daily_prices,
    berechnet abs(close[T+1]/close[T-1] - 1) * 100 für jeden Event.

    Args:
        symbol: Ticker-Symbol

    Returns:
        Dict mit avg_earnings_move_pct, std_earnings_move_pct oder None
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Hole alle Earnings-Dates für dieses Symbol
    cursor.execute("""
        SELECT earnings_date FROM earnings_history
        WHERE symbol = ? AND earnings_date IS NOT NULL
        ORDER BY earnings_date
    """, (symbol.upper(),))
    earnings_dates = [row[0] for row in cursor.fetchall()]

    if len(earnings_dates) < 2:
        conn.close()
        return None

    moves = []
    for ed in earnings_dates:
        # Hole close T-1 (letzter Handelstag vor Earnings)
        cursor.execute("""
            SELECT close FROM daily_prices
            WHERE symbol = ? AND date < ?
            ORDER BY date DESC LIMIT 1
        """, (symbol.upper(), ed))
        row_before = cursor.fetchone()

        # Hole close T+1 (erster Handelstag nach Earnings)
        cursor.execute("""
            SELECT close FROM daily_prices
            WHERE symbol = ? AND date > ?
            ORDER BY date ASC LIMIT 1
        """, (symbol.upper(), ed))
        row_after = cursor.fetchone()

        if row_before and row_after and row_before[0] > 0:
            move = abs(row_after[0] / row_before[0] - 1) * 100
            moves.append(move)

    conn.close()

    if len(moves) < 2:
        return None

    avg_move = sum(moves) / len(moves)

    # Std dev (min 4 events for meaningful std)
    std_move = None
    if len(moves) >= 4:
        variance = sum((m - avg_move) ** 2 for m in moves) / (len(moves) - 1)
        std_move = math.sqrt(variance)

    result = {"avg_earnings_move_pct": round(avg_move, 2)}
    if std_move is not None:
        result["std_earnings_move_pct"] = round(std_move, 2)

    return result


# =============================================================================
# UPDATE DATABASE
# =============================================================================

def _ensure_earnings_columns(cursor) -> None:
    """Adds avg_earnings_move_pct and std_earnings_move_pct columns if missing."""
    for col in ("avg_earnings_move_pct", "std_earnings_move_pct"):
        try:
            cursor.execute(f"SELECT {col} FROM symbol_fundamentals LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(
                f"ALTER TABLE symbol_fundamentals ADD COLUMN {col} REAL"
            )
            logger.info(f"Added column {col} to symbol_fundamentals")


def update_fundamentals(symbol: str, metrics: Dict) -> bool:
    """Aktualisiert symbol_fundamentals mit berechneten Metriken"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Ensure new columns exist
    if 'avg_earnings_move_pct' in metrics or 'std_earnings_move_pct' in metrics:
        _ensure_earnings_columns(cursor)
        conn.commit()

    try:
        # Check ob Symbol existiert
        cursor.execute("SELECT 1 FROM symbol_fundamentals WHERE symbol = ?", (symbol.upper(),))
        if cursor.fetchone() is None:
            # Insert neuen Eintrag
            cursor.execute("""
                INSERT INTO symbol_fundamentals (symbol, updated_at)
                VALUES (?, datetime('now'))
            """, (symbol.upper(),))

        # Update Metriken
        updates = []
        values = []

        if 'iv_rank' in metrics:
            updates.append("iv_rank_252d = ?")
            values.append(metrics['iv_rank'])
        if 'iv_percentile' in metrics:
            updates.append("iv_percentile_252d = ?")
            values.append(metrics['iv_percentile'])
        if 'correlation' in metrics:
            updates.append("spy_correlation_60d = ?")
            values.append(metrics['correlation'])
        if 'hv_30d' in metrics:
            updates.append("historical_volatility_30d = ?")
            values.append(metrics['hv_30d'])
        if 'avg_earnings_move_pct' in metrics:
            updates.append("avg_earnings_move_pct = ?")
            values.append(metrics['avg_earnings_move_pct'])
        if 'std_earnings_move_pct' in metrics:
            updates.append("std_earnings_move_pct = ?")
            values.append(metrics['std_earnings_move_pct'])

        if updates:
            updates.append("updated_at = datetime('now')")
            sql = f"UPDATE symbol_fundamentals SET {', '.join(updates)} WHERE symbol = ?"
            values.append(symbol.upper())
            cursor.execute(sql, values)

        conn.commit()
        return True

    except sqlite3.Error as e:
        logger.error(f"Fehler beim Update von {symbol}: {e}")
        return False
    finally:
        conn.close()


def process_symbol(symbol: str, calc_iv: bool = True, calc_corr: bool = True, calc_hv: bool = True, calc_earnings: bool = True) -> Dict:
    """Berechnet alle Metriken für ein Symbol"""
    result = {"symbol": symbol}

    if calc_iv:
        iv_metrics = calculate_iv_metrics(symbol)
        if iv_metrics:
            result.update({
                "iv_rank": iv_metrics["iv_rank"],
                "iv_percentile": iv_metrics["iv_percentile"]
            })

    if calc_corr:
        corr_metrics = calculate_spy_correlation(symbol)
        if corr_metrics:
            result["correlation"] = corr_metrics["correlation"]

    if calc_hv:
        hv_metrics = calculate_historical_volatility(symbol)
        if hv_metrics:
            result["hv_30d"] = hv_metrics["hv_30d"]

    if calc_earnings:
        em_metrics = calculate_earnings_move_stats(symbol)
        if em_metrics:
            result.update(em_metrics)

    return result


def main():
    parser = argparse.ArgumentParser(description="Calculate Derived Metrics")

    parser.add_argument(
        '--symbols', '-s',
        nargs='+',
        help='Spezifische Symbole'
    )
    parser.add_argument(
        '--iv-only',
        action='store_true',
        help='Nur IV-Metriken berechnen'
    )
    parser.add_argument(
        '--correlation-only',
        action='store_true',
        help='Nur SPY Correlation berechnen'
    )
    parser.add_argument(
        '--hv-only',
        action='store_true',
        help='Nur Historical Volatility berechnen'
    )
    parser.add_argument(
        '--earnings-move-only',
        action='store_true',
        help='Nur Earnings Move Stats berechnen'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Nur berechnen, nicht speichern'
    )

    args = parser.parse_args()

    # Bestimme was berechnet werden soll
    if args.iv_only:
        calc_iv, calc_corr, calc_hv, calc_earnings = True, False, False, False
    elif args.correlation_only:
        calc_iv, calc_corr, calc_hv, calc_earnings = False, True, False, False
    elif args.hv_only:
        calc_iv, calc_corr, calc_hv, calc_earnings = False, False, True, False
    elif args.earnings_move_only:
        calc_iv, calc_corr, calc_hv, calc_earnings = False, False, False, True
    else:
        calc_iv, calc_corr, calc_hv, calc_earnings = True, True, True, True

    # Symbole bestimmen
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        # Symbole die in beiden Tabellen sind
        fund_symbols = set(get_symbols_from_fundamentals())
        opt_symbols = set(get_symbols_from_options())
        symbols = sorted(fund_symbols & opt_symbols)

    logger.info(f"Verarbeite {len(symbols)} Symbole")
    logger.info(f"Berechne: IV={'✓' if calc_iv else '✗'}, Corr={'✓' if calc_corr else '✗'}, HV={'✓' if calc_hv else '✗'}, EM={'✓' if calc_earnings else '✗'}")

    if args.dry_run:
        logger.info("DRY RUN - keine Änderungen werden gespeichert")

    # Verarbeite Symbole
    results = {
        "iv_success": 0,
        "corr_success": 0,
        "hv_success": 0,
        "em_success": 0,
        "total": len(symbols)
    }

    for i, symbol in enumerate(symbols, 1):
        metrics = process_symbol(symbol, calc_iv, calc_corr, calc_hv, calc_earnings)

        # Logging
        parts = []
        if 'iv_rank' in metrics:
            parts.append(f"IV Rank={metrics['iv_rank']:.0f}")
            results["iv_success"] += 1
        if 'correlation' in metrics:
            parts.append(f"Corr={metrics['correlation']:.2f}")
            results["corr_success"] += 1
        if 'hv_30d' in metrics:
            parts.append(f"HV={metrics['hv_30d']:.0f}%")
            results["hv_success"] += 1
        if 'avg_earnings_move_pct' in metrics:
            parts.append(f"EM={metrics['avg_earnings_move_pct']:.1f}%")
            results["em_success"] += 1

        if parts:
            logger.info(f"[{i}/{len(symbols)}] {symbol}: {', '.join(parts)}")

            if not args.dry_run:
                update_fundamentals(symbol, metrics)
        else:
            logger.debug(f"[{i}/{len(symbols)}] {symbol}: keine Daten")

    # Ergebnis
    logger.info(f"\n{'='*60}")
    logger.info("ERGEBNIS")
    logger.info(f"{'='*60}")
    if calc_iv:
        logger.info(f"IV Rank/Percentile: {results['iv_success']}/{results['total']}")
    if calc_corr:
        logger.info(f"SPY Correlation: {results['corr_success']}/{results['total']}")
    if calc_hv:
        logger.info(f"Historical Volatility: {results['hv_success']}/{results['total']}")
    if calc_earnings:
        logger.info(f"Earnings Move Stats: {results['em_success']}/{results['total']}")


if __name__ == "__main__":
    main()
