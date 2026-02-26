#!/usr/bin/env python3
"""
Phase 5a + 5b: Speed Score berechnen und Exponenten-Backtest mit Walk-Forward Validation.

Berechnet Speed Score für alle Trades, dann testet verschiedene Exponenten
für die Integration in das Ranking: signal_score * stability * speed^exponent.

Walk-Forward: Train <2024, Test >=2024.
Sicherheitsschwelle: Win Rate >= 83%.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"
TRADES_DB = Path.home() / ".optionplay" / "trades.db"

# Sektor-Speed-Map aus Phase 4 Analyse
SECTOR_SPEED = {
    "Utilities": 1.0,
    "Healthcare": 0.9,
    "Real Estate": 0.85,
    "Consumer Defensive": 0.7,
    "Financial Services": 0.6,
    "Industrials": 0.5,
    "Consumer Cyclical": 0.4,
    "Communication Services": 0.3,
    "Energy": 0.2,
    "Technology": 0.1,
    "Basic Materials": 0.0,
}

# Score-Spalten für signal_score Rekonstruktion
SIGNAL_SCORE_COLS = [
    "rsi_score",
    "support_score",
    "fibonacci_score",
    "ma_score",
    "volume_score",
    "macd_score",
    "stoch_score",
    "keltner_score",
    "trend_strength_score",
    "momentum_score",
    "rs_score",
    "candlestick_score",
    "vwap_score",
    "market_context_score",
    "sector_score",
    "gap_score",
    "pullback_score",
    "bounce_score",
    "ath_breakout_score",
    "earnings_dip_score",
]


def load_data():
    """Lade Trades und Fundamentals, merge und berechne abgeleitete Features."""
    conn_out = sqlite3.connect(str(OUTCOMES_DB))
    conn_t = sqlite3.connect(str(TRADES_DB))

    df = pd.read_sql_query("SELECT * FROM trade_outcomes", conn_out)
    fundamentals = pd.read_sql_query(
        "SELECT symbol, sector, stability_score FROM symbol_fundamentals", conn_t
    )

    conn_out.close()
    conn_t.close()

    df = df.merge(fundamentals, on="symbol", how="left")

    # Signal Score = Summe aller Einzelscores
    df["signal_score"] = df[SIGNAL_SCORE_COLS].sum(axis=1, skipna=True)

    # Für Trades ohne Scores: Median als Fallback
    median_signal = df.loc[df["signal_score"] > 0, "signal_score"].median()
    df.loc[df["signal_score"] == 0, "signal_score"] = median_signal

    # Stability Fallback
    median_stability = df["stability_score"].median()
    df["stability_score"] = df["stability_score"].fillna(median_stability)

    return df


def compute_speed_score(row):
    """Speed Score nach Phase 5a Design. 0-10 Skala."""
    score = 0.0

    # 1. DTE-Bonus: Näher an 60 = schneller (Max 3.0)
    dte = row.get("dte_at_entry", 75)
    dte_factor = max(0.0, 1.0 - (dte - 60) / 30)
    score += dte_factor * 3.0

    # 2. Stability-Bonus: Höher = schneller (Max 2.5)
    stab = row.get("stability_score", 75)
    stab_factor = max(0.0, (stab - 70) / 30)
    score += stab_factor * 2.5

    # 3. Sektor-Bonus (Max 1.5)
    sector = row.get("sector", "")
    score += SECTOR_SPEED.get(sector, 0.5) * 1.5

    # 4. Pullback-Score-Bonus (Max 1.5)
    pb = row.get("pullback_score")
    if pd.notna(pb):
        score += min(pb / 10, 1.0) * 1.5

    # 5. Market-Context-Bonus (Max 1.5)
    mc = row.get("market_context_score")
    if pd.notna(mc):
        score += min(max(mc, 0) / 10, 1.0) * 1.5

    return min(score, 10.0)


def final_ranking_score(signal, stability, speed, exponent):
    """Ranking mit gedämpftem Speed-Faktor."""
    speed_normalized = 0.5 + (speed / 10.0)  # 0→0.5, 10→1.5
    return signal * stability * (speed_normalized**exponent)


def backtest_exponent(df, exponent):
    """Backtest für einen bestimmten Exponenten."""
    df = df.copy()

    df["rank_score"] = df.apply(
        lambda r: final_ranking_score(
            r["signal_score"], r["stability_score"], r["speed_score"], exponent
        ),
        axis=1,
    )

    # Top-5 pro Entry-Datum
    daily_picks = (
        df.sort_values(["entry_date", "rank_score"], ascending=[True, False])
        .groupby("entry_date")
        .head(5)
    )

    n = len(daily_picks)
    win_rate = daily_picks["was_profitable"].mean() * 100

    # Capital Efficiency: nur für Trades mit playbook_exit
    has_exit = daily_picks["days_to_playbook_exit"].notna()
    if has_exit.sum() > 0:
        avg_days = daily_picks.loc[has_exit, "days_to_playbook_exit"].mean()
        total_pnl = daily_picks.loc[has_exit, "pnl"].sum()
        total_days = daily_picks.loc[has_exit, "days_to_playbook_exit"].sum()
        cap_eff = total_pnl / total_days if total_days > 0 else 0
    else:
        avg_days = np.nan
        cap_eff = 0

    avg_pnl = daily_picks["pnl"].mean()
    avg_dd = daily_picks["max_drawdown_pct"].mean()

    # Anteil mit Playbook-Exit
    exit_rate = has_exit.sum() / n * 100 if n > 0 else 0

    return {
        "exponent": exponent,
        "n_trades": n,
        "win_rate": win_rate,
        "avg_days": avg_days,
        "avg_pnl": avg_pnl,
        "capital_efficiency": cap_eff,
        "avg_drawdown": avg_dd,
        "exit_rate": exit_rate,
    }


def print_results(results, label=""):
    """Ergebnis-Tabelle drucken."""
    print(f"\n{'='*85}")
    print(f"  {label}")
    print(f"{'='*85}")
    print(
        f"  {'Exp':>5s}  {'n':>6s}  {'WinRate':>8s}  {'AvgDays':>8s}  "
        f"{'AvgP&L':>8s}  {'CapEff':>8s}  {'AvgDD':>7s}  {'ExitRate':>8s}"
    )
    print(f"  {'-'*5}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*8}")

    baseline = results[0] if results else None

    for r in results:
        marker = ""
        if baseline and r["exponent"] == 0.0:
            marker = " ← Baseline"
        elif baseline and r["win_rate"] < 83.0:
            marker = " ← UNTER 83%!"

        days_s = f"{r['avg_days']:.1f}" if not np.isnan(r["avg_days"]) else "n/a"

        print(
            f"  {r['exponent']:5.2f}  {r['n_trades']:6d}  {r['win_rate']:7.1f}%  "
            f"{days_s:>8s}  ${r['avg_pnl']:7.2f}  ${r['capital_efficiency']:7.4f}  "
            f"{r['avg_drawdown']:6.1f}%  {r['exit_rate']:7.1f}%{marker}"
        )

    if len(results) >= 2 and baseline:
        best = max(
            (r for r in results if r["win_rate"] >= 83.0),
            key=lambda r: r["capital_efficiency"],
            default=None,
        )
        if best and best["exponent"] != 0.0:
            delta_eff = (
                (best["capital_efficiency"] - baseline["capital_efficiency"])
                / abs(baseline["capital_efficiency"])
                * 100
                if baseline["capital_efficiency"] != 0
                else 0
            )
            delta_days = best["avg_days"] - baseline["avg_days"]
            delta_wr = best["win_rate"] - baseline["win_rate"]
            print(f"\n  Bester Exponent (WR>=83%): {best['exponent']}")
            print(f"    Cap. Efficiency: {delta_eff:+.1f}% vs Baseline")
            print(f"    Avg Days: {delta_days:+.1f} Tage")
            print(f"    Win Rate: {delta_wr:+.1f}%")


def main():
    print("Lade Daten...")
    df = load_data()
    print(f"  {len(df)} Trades geladen")
    print(
        f"  Signal Score: mean={df['signal_score'].mean():.2f}, std={df['signal_score'].std():.2f}"
    )
    print(
        f"  Stability: mean={df['stability_score'].mean():.1f}, std={df['stability_score'].std():.1f}"
    )

    # Speed Score berechnen
    print("\nBerechne Speed Score...")
    df["speed_score"] = df.apply(compute_speed_score, axis=1)
    print(f"  Speed Score: mean={df['speed_score'].mean():.2f}, std={df['speed_score'].std():.2f}")
    print(f"  Min={df['speed_score'].min():.2f}, Max={df['speed_score'].max():.2f}")

    # Korrelation Speed Score vs tatsächlichem days_to_playbook_exit
    has_exit = df["days_to_playbook_exit"].notna()
    corr = df.loc[has_exit, ["speed_score", "days_to_playbook_exit"]].corr().iloc[0, 1]
    print(f"  Korrelation Speed Score vs days_to_playbook_exit: {corr:.3f}")
    print(f"  (Negativ = gut, höherer Score = schnellerer Exit)")

    exponents = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]

    # === GESAMT-BACKTEST ===
    print("\n" + "#" * 85)
    print("  GESAMT-BACKTEST (alle Daten)")
    print("#" * 85)

    all_results = [backtest_exponent(df, exp) for exp in exponents]
    print_results(all_results, "Gesamt: Alle 17K Trades")

    # === WALK-FORWARD VALIDATION ===
    print("\n" + "#" * 85)
    print("  WALK-FORWARD VALIDATION")
    print("#" * 85)

    train = df[df["entry_date"] < "2024-01-01"].copy()
    test = df[df["entry_date"] >= "2024-01-01"].copy()
    print(f"\n  Train: {len(train)} Trades (< 2024)")
    print(f"  Test:  {len(test)} Trades (>= 2024)")

    # Train
    train_results = [backtest_exponent(train, exp) for exp in exponents]
    print_results(train_results, "TRAIN (2021-2023)")

    # Besten Exponenten auf Train finden (WR >= 83%, max Cap Eff)
    valid_train = [r for r in train_results if r["win_rate"] >= 83.0]
    if valid_train:
        best_exp = max(valid_train, key=lambda r: r["capital_efficiency"])["exponent"]
    else:
        best_exp = 0.0
    print(f"\n  → Bester Train-Exponent: {best_exp}")

    # Test mit Baseline und bestem Exponenten
    test_exponents = sorted(set([0.0, best_exp, 0.3, 0.5]))
    test_results = [backtest_exponent(test, exp) for exp in test_exponents]
    print_results(test_results, f"TEST (2024-2026) — Validierung mit Train-Best={best_exp}")

    # === VIX-REGIME SPLIT ===
    print("\n" + "#" * 85)
    print("  VIX-REGIME SPLIT")
    print("#" * 85)

    low_vix = df[df["vix_at_entry"] < 20].copy()
    high_vix = df[df["vix_at_entry"] >= 20].copy()

    key_exponents = [0.0, 0.3, 0.5, 1.0]

    low_results = [backtest_exponent(low_vix, exp) for exp in key_exponents]
    print_results(low_results, f"VIX < 20 ({len(low_vix)} Trades, 50% Target)")

    high_results = [backtest_exponent(high_vix, exp) for exp in key_exponents]
    print_results(high_results, f"VIX >= 20 ({len(high_vix)} Trades, 30% Target)")

    # === SPEED SCORE in outcomes.db speichern ===
    print("\n\nSpeichere speed_score in outcomes.db...")
    conn = sqlite3.connect(str(OUTCOMES_DB))
    cursor = conn.cursor()

    # Spalte anlegen
    try:
        cursor.execute("ALTER TABLE trade_outcomes ADD COLUMN speed_score REAL")
        print("  Spalte speed_score angelegt")
    except Exception:
        print("  Spalte speed_score existiert bereits")

    # Werte schreiben
    for _, row in df[["id", "speed_score"]].iterrows():
        cursor.execute(
            "UPDATE trade_outcomes SET speed_score = ? WHERE id = ?",
            (row["speed_score"], row["id"]),
        )
    conn.commit()

    # Verifizierung
    cursor.execute("SELECT COUNT(*) FROM trade_outcomes WHERE speed_score IS NOT NULL")
    saved = cursor.fetchone()[0]
    print(f"  {saved} Trades mit speed_score gespeichert")

    conn.close()
    print("\nFertig.")


if __name__ == "__main__":
    main()
