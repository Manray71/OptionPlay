#!/usr/bin/env python3
"""
Historical Backtest: Trend Continuation Analyzer
Tests candidate count across different market phases.
"""

import sys, os, sqlite3, time, logging
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TREND_MIN_SCORE
from src.models.base import SignalType

logging.basicConfig(level=logging.WARNING)

DB_PATH = os.path.expanduser("~/.optionplay/trades.db")
MIN_DATA_POINTS = 220
HISTORY_DAYS = 500

TEST_DATES = [
    ("2024-07-15", "Bull Market mid-2024", "10-20"),
    ("2024-11-15", "Bull Market post-election", "10-20"),
    ("2022-09-15", "Bear Market (high VIX)", "~0"),
    ("2023-06-15", "Recovery (AI rally)", "some"),
]


def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_vix(conn, dt):
    r = conn.execute(
        "SELECT value FROM vix_data WHERE date <= ? ORDER BY date DESC LIMIT 1", (dt,)
    ).fetchone()
    return float(r["value"]) if r else None


def get_symbols(conn, dt):
    rows = conn.execute(
        "SELECT DISTINCT underlying FROM options_prices WHERE quote_date = ?", (dt,)
    ).fetchall()
    return [r["underlying"] for r in rows]


def get_nearest_trading_day(conn, dt):
    r = conn.execute(
        "SELECT DISTINCT quote_date FROM options_prices WHERE quote_date <= ? ORDER BY quote_date DESC LIMIT 1",
        (dt,),
    ).fetchone()
    return r["quote_date"] if r else dt


def get_prices(conn, sym, dt):
    rows = conn.execute(
        "SELECT DISTINCT quote_date, underlying_price FROM options_prices "
        "WHERE underlying=? AND quote_date<=? AND quote_date>=date(?,'-' || ? || ' days') AND underlying_price>0 "
        "ORDER BY quote_date ASC",
        (sym, dt, dt, str(HISTORY_DAYS)),
    ).fetchall()
    return [float(r["underlying_price"]) for r in rows]


def build_ohlcv(closes):
    n = len(closes)
    if n < 2:
        return closes, [], closes, closes
    opens = [closes[0]] + closes[:-1]
    highs, lows, vols = [], [], []
    for i in range(n):
        c, o = closes[i], opens[i]
        ret = abs(c - closes[i - 1]) / closes[i - 1] if i > 0 else 0.005
        noise = max(ret * 0.5, 0.002)
        highs.append(max(o, c) * (1 + noise))
        lows.append(min(o, c) * (1 - noise))
        vols.append(1_500_000)
    return closes, vols, highs, lows


def main():
    print("\n" + "=" * 80)
    print("  Trend Continuation Historical Backtest")
    print("=" * 80)

    conn = get_db()
    analyzer = TrendContinuationAnalyzer()
    summary = []

    for dt, label, expected in TEST_DATES:
        symbols = get_symbols(conn, dt)
        if not symbols:
            actual = get_nearest_trading_day(conn, dt)
            print(f"  [{dt}] Not a trading day, using {actual}")
            symbols = get_symbols(conn, actual)
            dt = actual

        vix = get_vix(conn, dt)
        candidates = []
        analyzed = 0
        skipped = 0
        dq_reasons = defaultdict(int)
        t0 = time.time()

        for sym in symbols:
            closes = get_prices(conn, sym, dt)
            if len(closes) < MIN_DATA_POINTS:
                skipped += 1
                continue
            analyzed += 1
            prices, vols, highs, lows = build_ohlcv(closes)
            try:
                sig = analyzer.analyze(sym, prices, vols, highs, lows, vix=vix)
                if sig.signal_type == SignalType.LONG and sig.score >= TREND_MIN_SCORE:
                    candidates.append((sym, sig.score, sig.reason[:80]))
                else:
                    r = sig.reason
                    if "SMA" in r:
                        dq_reasons["SMA alignment"] += 1
                    elif "VIX" in r.upper():
                        dq_reasons["High VIX"] += 1
                    elif "buffer" in r.lower():
                        dq_reasons["Buffer"] += 1
                    elif "RSI" in r or "Overbought" in r:
                        dq_reasons["Overbought"] += 1
                    elif "ADX" in r:
                        dq_reasons["No trend (ADX)"] += 1
                    elif sig.score > 0 and sig.score < TREND_MIN_SCORE:
                        dq_reasons["Score < min"] += 1
                    else:
                        dq_reasons["Other"] += 1
            except Exception as e:
                dq_reasons[f"Error"] += 1

        elapsed = time.time() - t0
        candidates.sort(key=lambda x: x[1], reverse=True)

        print(f"\n{'─' * 80}")
        print(f"  {label}  |  {dt}  |  VIX: {vix:.1f}")
        print(f"  Symbols: {len(symbols)} total, {analyzed} analyzed, {skipped} skipped")
        print(f"  CANDIDATES: {len(candidates)}  (expected: {expected})  [{elapsed:.1f}s]")
        if candidates:
            for sym, score, reason in candidates[:10]:
                print(f"    {sym:<8} {score:>5.1f}  {reason}")
            if len(candidates) > 10:
                print(f"    ... +{len(candidates)-10} more")
        print(f"  Disqualifications: {dict(sorted(dq_reasons.items(), key=lambda x: -x[1]))}")

        summary.append((dt, label, vix, analyzed, len(candidates), expected, elapsed))

    print(f"\n{'=' * 80}")
    print("  SUMMARY")
    print(f"{'=' * 80}")
    print(f"  {'Date':<12} {'VIX':>5} {'Analyzed':>9} {'Found':>6} Expected")
    print(f"  {'─' * 60}")
    for dt, label, vix, analyzed, found, expected, elapsed in summary:
        print(f"  {dt:<12} {vix:>5.1f} {analyzed:>9} {found:>6} {expected}")
    print()
    conn.close()


if __name__ == "__main__":
    main()
