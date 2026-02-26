#!/usr/bin/env python3
"""
Backtest Validation for Scoring Rebalancing (Schritte 1-7)

Validates that scoring changes (normalization, ranking, VIX harmonization,
event-priority, enhanced scoring) have not degraded performance.

Usage:
    python scripts/validate_scoring_changes.py

Reads from ~/.optionplay/outcomes.db and outputs a comparison report.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTCOME_DB = Path.home() / ".optionplay" / "outcomes.db"

# Expected OOS Win Rates (from walk-forward training, 2026-02-09)
EXPECTED_WIN_RATES = {
    "pullback": 88.3,
    "bounce": 91.6,
    "ath_breakout": 88.9,
    "earnings_dip": 86.7,
    "trend_continuation": 87.7,
}

# Normalization max_possible values (current, post-Schritt 4)
MAX_POSSIBLE = {
    "pullback": 14.0,
    "bounce": 10.0,
    "ath_breakout": 10.0,
    "earnings_dip": 9.5,
    "trend_continuation": 10.5,
}

# Signal strength thresholds
STRONG_THRESHOLD = 7.0
MODERATE_THRESHOLD = 5.0

# Tolerance for win rate comparison
WIN_RATE_TOLERANCE = 2.0  # ±2%


STRATEGY_SCORE_COLUMNS = {
    "pullback": "pullback_score",
    "bounce": "bounce_score",
    "ath_breakout": "ath_breakout_score",
    "earnings_dip": "earnings_dip_score",
    "trend_continuation": "trend_continuation_score",
}


def load_outcomes() -> pd.DataFrame:
    """Load trade outcomes from outcomes.db.

    The DB has no 'strategy' or 'score' column. Strategy is inferred from
    which *_score column is non-null. The score is the value of that column.
    """
    if not OUTCOME_DB.exists():
        print(f"ERROR: Outcome database not found at {OUTCOME_DB}")
        sys.exit(1)

    score_cols = list(STRATEGY_SCORE_COLUMNS.values())
    conn = sqlite3.connect(str(OUTCOME_DB))
    df = pd.read_sql_query(
        f"""
        SELECT symbol, entry_date, was_profitable,
               pnl_pct, max_drawdown_pct, vix_at_entry, vix_regime,
               outcome, dte_at_entry,
               {', '.join(score_cols)}
        FROM trade_outcomes
        """,
        conn,
    )
    conn.close()

    # Derive strategy and score from the non-null score column
    rows = []
    for _, row in df.iterrows():
        for strategy, col in STRATEGY_SCORE_COLUMNS.items():
            val = row[col]
            if pd.notna(val) and val > 0:
                r = row.to_dict()
                r["strategy"] = strategy
                r["score"] = val
                rows.append(r)
                break  # Take the first non-null strategy score

    result = pd.DataFrame(rows)
    # Drop the individual score columns
    for col in score_cols:
        if col in result.columns:
            result.drop(columns=[col], inplace=True)

    print(f"Loaded {len(result):,} trades from {OUTCOME_DB}")
    return result


def normalize_score(raw_score: float, strategy: str) -> float:
    """Normalize raw score to 0-10 scale."""
    max_p = MAX_POSSIBLE.get(strategy, 10.0)
    if max_p <= 0:
        return 0.0
    return min(10.0, max(0.0, (raw_score / max_p) * 10.0))


def report_overall_stats(df: pd.DataFrame) -> None:
    """Print overall statistics per strategy."""
    print("\n" + "=" * 80)
    print("1. OVERALL STATISTICS PER STRATEGY")
    print("=" * 80)

    stats = (
        df.groupby("strategy")
        .agg(
            trades=("was_profitable", "count"),
            wins=("was_profitable", "sum"),
            win_rate=("was_profitable", "mean"),
            avg_score=("score", "mean"),
            median_score=("score", "median"),
            p25_score=("score", lambda x: np.percentile(x, 25)),
            p75_score=("score", lambda x: np.percentile(x, 75)),
            avg_pnl=("pnl_pct", "mean"),
        )
        .reset_index()
    )
    stats["win_rate"] = stats["win_rate"] * 100

    print(
        f"\n{'Strategy':<22} {'Trades':>7} {'WR%':>7} {'Avg Score':>10} "
        f"{'Median':>8} {'P25':>6} {'P75':>6} {'Avg PnL%':>9}"
    )
    print("-" * 80)

    for _, row in stats.iterrows():
        strat = row["strategy"]
        expected = EXPECTED_WIN_RATES.get(strat, 0)
        delta = row["win_rate"] - expected
        flag = " ✓" if abs(delta) <= WIN_RATE_TOLERANCE else " ⚠"
        print(
            f"{strat:<22} {int(row['trades']):>7} {row['win_rate']:>6.1f}% "
            f"{row['avg_score']:>10.2f} {row['median_score']:>8.2f} "
            f"{row['p25_score']:>6.2f} {row['p75_score']:>6.2f} "
            f"{row['avg_pnl']:>8.2f}%{flag}"
        )

    print(f"\n  ✓ = within ±{WIN_RATE_TOLERANCE}% of expected  |  ⚠ = outside tolerance")


def report_strong_signals(df: pd.DataFrame) -> None:
    """Check win rate for STRONG signals (>= 7.0) per strategy."""
    print("\n" + "=" * 80)
    print("2. STRONG SIGNAL ANALYSIS (score >= 7.0)")
    print("=" * 80)

    for strategy in sorted(df["strategy"].unique()):
        sdf = df[df["strategy"] == strategy]
        strong = sdf[sdf["score"] >= STRONG_THRESHOLD]
        moderate = sdf[(sdf["score"] >= MODERATE_THRESHOLD) & (sdf["score"] < STRONG_THRESHOLD)]
        weak = sdf[sdf["score"] < MODERATE_THRESHOLD]

        total = len(sdf)
        n_strong = len(strong)
        pct_strong = (n_strong / total * 100) if total > 0 else 0

        print(f"\n  {strategy}:")
        print(
            f"    Total: {total} | Strong: {n_strong} ({pct_strong:.1f}%) | "
            f"Moderate: {len(moderate)} | Weak: {len(weak)}"
        )

        if n_strong > 0:
            wr = strong["was_profitable"].mean() * 100
            print(f"    Strong WR: {wr:.1f}% ({int(strong['was_profitable'].sum())}/{n_strong})")
        if len(moderate) > 0:
            wr = moderate["was_profitable"].mean() * 100
            print(
                f"    Moderate WR: {wr:.1f}% ({int(moderate['was_profitable'].sum())}/{len(moderate)})"
            )


def report_vix_regime(df: pd.DataFrame) -> None:
    """VIX regime breakdown."""
    print("\n" + "=" * 80)
    print("3. VIX REGIME BREAKDOWN")
    print("=" * 80)

    if "vix_regime" not in df.columns or df["vix_regime"].isna().all():
        print("  No VIX regime data available.")
        return

    for regime in ["low", "medium", "normal", "high", "extreme", "elevated", "danger"]:
        rdf = df[df["vix_regime"] == regime]
        if len(rdf) == 0:
            continue
        wr = rdf["was_profitable"].mean() * 100
        print(f"\n  {regime.upper()} regime: {len(rdf)} trades, WR {wr:.1f}%")

        by_strat = (
            rdf.groupby("strategy")
            .agg(trades=("was_profitable", "count"), wr=("was_profitable", "mean"))
            .reset_index()
        )
        for _, row in by_strat.iterrows():
            print(
                f"    {row['strategy']:<20} {int(row['trades']):>5} trades  WR {row['wr']*100:.1f}%"
            )


def report_score_distributions(df: pd.DataFrame) -> None:
    """Compare score distributions across strategies."""
    print("\n" + "=" * 80)
    print("4. SCORE DISTRIBUTION COMPARISON")
    print("=" * 80)

    print(
        f"\n{'Strategy':<22} {'Min':>6} {'P10':>6} {'P25':>6} {'P50':>6} "
        f"{'P75':>6} {'P90':>6} {'Max':>6} {'StdDev':>7}"
    )
    print("-" * 80)

    for strategy in sorted(df["strategy"].unique()):
        scores = df[df["strategy"] == strategy]["score"]
        print(
            f"{strategy:<22} {scores.min():>6.2f} "
            f"{np.percentile(scores, 10):>6.2f} "
            f"{np.percentile(scores, 25):>6.2f} "
            f"{scores.median():>6.2f} "
            f"{np.percentile(scores, 75):>6.2f} "
            f"{np.percentile(scores, 90):>6.2f} "
            f"{scores.max():>6.2f} "
            f"{scores.std():>7.2f}"
        )


def report_event_vs_trend(df: pd.DataFrame) -> None:
    """Compare event-based vs. state-based strategy frequency."""
    print("\n" + "=" * 80)
    print("5. EVENT vs. TREND BALANCE")
    print("=" * 80)

    event_strategies = {"pullback", "bounce", "ath_breakout", "earnings_dip"}
    tc_mask = df["strategy"] == "trend_continuation"
    event_mask = df["strategy"].isin(event_strategies)

    n_tc = tc_mask.sum()
    n_event = event_mask.sum()
    total = len(df)
    tc_pct = (n_tc / total * 100) if total > 0 else 0

    print(f"\n  Event strategies:        {n_event:>6} trades ({n_event/total*100:.1f}%)")
    print(f"  Trend continuation:      {n_tc:>6} trades ({tc_pct:.1f}%)")

    if tc_pct > 50:
        print("  ⚠ Trend continuation represents >50% of all trades!")
    else:
        print("  ✓ Trend continuation is balanced (<50%)")


def report_validation_summary(df: pd.DataFrame) -> None:
    """Print validation pass/fail summary."""
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    checks = []

    # Check 1: Win rates within tolerance
    for strategy in sorted(df["strategy"].unique()):
        sdf = df[df["strategy"] == strategy]
        wr = sdf["was_profitable"].mean() * 100
        expected = EXPECTED_WIN_RATES.get(strategy, wr)
        passed = abs(wr - expected) <= WIN_RATE_TOLERANCE
        checks.append((f"WR {strategy}", passed, f"{wr:.1f}% (expected {expected:.1f}%)"))

    # Check 2: Strong signals exist for pullback
    pb = df[df["strategy"] == "pullback"]
    n_strong_pb = len(pb[pb["score"] >= STRONG_THRESHOLD])
    passed = n_strong_pb > 0
    checks.append(("Pullback STRONG signals", passed, f"{n_strong_pb} trades"))

    # Check 3: TC not >60% of all trades
    tc_pct = len(df[df["strategy"] == "trend_continuation"]) / len(df) * 100 if len(df) > 0 else 0
    passed = tc_pct < 60
    checks.append(("TC not dominant", passed, f"{tc_pct:.1f}%"))

    # Print results
    all_pass = True
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}: {detail}")

    print()
    if all_pass:
        print("  ✓ ALL CHECKS PASSED — No performance regression detected.")
    else:
        print("  ⚠ SOME CHECKS FAILED — Review findings above.")


def main():
    """Run the full validation report."""
    print("=" * 80)
    print("SCORING REBALANCING VALIDATION (Schritte 1-7)")
    print(f"Database: {OUTCOME_DB}")
    print("=" * 80)

    df = load_outcomes()

    if len(df) == 0:
        print("ERROR: No trades found in outcomes database.")
        sys.exit(1)

    report_overall_stats(df)
    report_strong_signals(df)
    report_vix_regime(df)
    report_score_distributions(df)
    report_event_vs_trend(df)
    report_validation_summary(df)


if __name__ == "__main__":
    main()
