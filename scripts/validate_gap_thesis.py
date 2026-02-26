#!/usr/bin/env python3
"""
OptionPlay - Gap Thesis Validation
==================================

Validiert die These:
- Up-Gaps sind schlecht für Bull-Put-Spreads (Euphorie, Überkauft)
- Down-Gaps sind gut für Bull-Put-Spreads (Überreaktion, Einstiegschance)

Verwendet historische Daten aus der TradeTracker-Datenbank.

Usage:
    python scripts/validate_gap_thesis.py
    python scripts/validate_gap_thesis.py --min-samples 20
    python scripts/validate_gap_thesis.py --output results.json
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np

from src.backtesting import TradeTracker
from src.indicators.gap_analysis import (
    detect_gap,
    calculate_gap_statistics,
    MIN_GAP_THRESHOLD_PCT,
)


@dataclass
class GapEvent:
    """Ein einzelnes Gap-Event mit Forward-Returns."""

    symbol: str
    date: date
    gap_type: str
    gap_size_pct: float
    is_filled: bool
    fill_pct: float
    return_1d: float
    return_3d: float
    return_5d: float
    return_10d: float
    return_30d: float
    return_60d: float


@dataclass
class ThesisValidationResult:
    """Ergebnis der Gap-These-Validierung."""

    # Datenbasis
    total_symbols: int
    symbols_with_data: int
    total_trading_days: int
    analysis_period: str

    # Gap-Counts
    total_gaps: int
    up_gaps: int
    down_gaps: int
    partial_up_gaps: int
    partial_down_gaps: int

    # Performance nach Gap-Typ
    avg_return_1d_after_up_gap: float
    avg_return_1d_after_down_gap: float
    avg_return_5d_after_up_gap: float
    avg_return_5d_after_down_gap: float
    avg_return_10d_after_up_gap: float
    avg_return_10d_after_down_gap: float
    avg_return_30d_after_up_gap: float
    avg_return_30d_after_down_gap: float
    avg_return_60d_after_up_gap: float
    avg_return_60d_after_down_gap: float

    # Win-Rates (positive Returns)
    win_rate_1d_after_up_gap: float
    win_rate_1d_after_down_gap: float
    win_rate_5d_after_up_gap: float
    win_rate_5d_after_down_gap: float
    win_rate_10d_after_up_gap: float
    win_rate_10d_after_down_gap: float
    win_rate_30d_after_up_gap: float
    win_rate_30d_after_down_gap: float
    win_rate_60d_after_up_gap: float
    win_rate_60d_after_down_gap: float

    # Gap-Fill-Statistiken
    up_gap_fill_rate_intraday: float
    down_gap_fill_rate_intraday: float

    # Gap-Größen-Analyse
    avg_up_gap_size: float
    avg_down_gap_size: float

    # These-Validierung
    thesis_supported_1d: bool
    thesis_supported_5d: bool
    thesis_supported_10d: bool
    thesis_supported_30d: bool
    thesis_supported_60d: bool
    confidence_score: float  # 0-1, basierend auf Sample-Size und Konsistenz

    # Empfohlene Gewichtung
    recommended_gap_weight: float  # Für Score-Integration


def collect_gap_events(
    tracker: TradeTracker,
    min_gap_pct: float = MIN_GAP_THRESHOLD_PCT,
    forward_days: int = 60,
) -> Tuple[List[GapEvent], Dict[str, int]]:
    """
    Sammelt alle Gap-Events aus der Datenbank.

    Returns:
        Tuple: (List[GapEvent], stats_dict)
    """
    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s["symbol"] for s in symbol_info]

    all_events: List[GapEvent] = []
    stats = {
        "total_symbols": len(symbols),
        "symbols_with_data": 0,
        "total_days": 0,
    }

    for symbol in symbols:
        symbol_data = tracker.get_price_data(symbol)

        if not symbol_data or len(symbol_data.bars) < forward_days + 20:
            continue

        price_data = symbol_data.bars
        stats["symbols_with_data"] += 1
        stats["total_days"] += len(price_data)

        # Konvertiere zu Listen
        opens = [bar.open for bar in price_data]
        highs = [bar.high for bar in price_data]
        lows = [bar.low for bar in price_data]
        closes = [bar.close for bar in price_data]
        dates = [bar.date for bar in price_data]

        # Scanne nach Gaps
        for i in range(1, len(price_data) - forward_days):
            gap_type, gap_size, _, is_filled, fill_pct = detect_gap(
                prev_open=opens[i - 1],
                prev_high=highs[i - 1],
                prev_low=lows[i - 1],
                prev_close=closes[i - 1],
                curr_open=opens[i],
                curr_high=highs[i],
                curr_low=lows[i],
                curr_close=closes[i],
                min_gap_pct=min_gap_pct,
            )

            if gap_type == "none":
                continue

            # Forward-Returns berechnen
            entry_price = closes[i]

            def calc_return(days_forward: int) -> float:
                if i + days_forward < len(closes):
                    exit_price = closes[i + days_forward]
                    return ((exit_price - entry_price) / entry_price) * 100
                return 0.0

            event = GapEvent(
                symbol=symbol,
                date=dates[i],
                gap_type=gap_type,
                gap_size_pct=gap_size,
                is_filled=is_filled,
                fill_pct=fill_pct,
                return_1d=calc_return(1),
                return_3d=calc_return(3),
                return_5d=calc_return(5),
                return_10d=calc_return(10),
                return_30d=calc_return(30),
                return_60d=calc_return(60),
            )
            all_events.append(event)

    return all_events, stats


def analyze_gap_events(
    events: List[GapEvent],
    stats: Dict[str, int],
    min_samples: int = 10,
) -> ThesisValidationResult:
    """
    Analysiert Gap-Events und validiert die These.
    """
    # Gruppiere nach Gap-Typ
    up_gaps = [e for e in events if e.gap_type == "up"]
    down_gaps = [e for e in events if e.gap_type == "down"]
    partial_up = [e for e in events if e.gap_type == "partial_up"]
    partial_down = [e for e in events if e.gap_type == "partial_down"]

    # Kombiniere für Hauptanalyse
    all_up = up_gaps + partial_up
    all_down = down_gaps + partial_down

    def safe_mean(values: List[float]) -> float:
        return float(np.mean(values)) if values else 0.0

    def win_rate(values: List[float]) -> float:
        if not values:
            return 0.0
        return sum(1 for v in values if v > 0) / len(values)

    # Berechne Metriken
    up_returns_1d = [e.return_1d for e in all_up]
    up_returns_5d = [e.return_5d for e in all_up]
    up_returns_10d = [e.return_10d for e in all_up]
    up_returns_30d = [e.return_30d for e in all_up]
    up_returns_60d = [e.return_60d for e in all_up]

    down_returns_1d = [e.return_1d for e in all_down]
    down_returns_5d = [e.return_5d for e in all_down]
    down_returns_10d = [e.return_10d for e in all_down]
    down_returns_30d = [e.return_30d for e in all_down]
    down_returns_60d = [e.return_60d for e in all_down]

    # Gap-Fill-Raten
    up_fill_rate = sum(1 for e in all_up if e.is_filled) / len(all_up) if all_up else 0.0
    down_fill_rate = sum(1 for e in all_down if e.is_filled) / len(all_down) if all_down else 0.0

    # Gap-Größen
    avg_up_size = safe_mean([abs(e.gap_size_pct) for e in all_up])
    avg_down_size = safe_mean([abs(e.gap_size_pct) for e in all_down])

    # These-Validierung
    # These: Down-Gaps sollten bessere Returns haben als Up-Gaps
    thesis_1d = safe_mean(down_returns_1d) > safe_mean(up_returns_1d)
    thesis_5d = safe_mean(down_returns_5d) > safe_mean(up_returns_5d)
    thesis_10d = safe_mean(down_returns_10d) > safe_mean(up_returns_10d)
    thesis_30d = safe_mean(down_returns_30d) > safe_mean(up_returns_30d)
    thesis_60d = safe_mean(down_returns_60d) > safe_mean(up_returns_60d)

    # Confidence Score
    sample_confidence = min(1.0, min(len(all_up), len(all_down)) / 100)
    consistency = sum([thesis_1d, thesis_5d, thesis_10d, thesis_30d, thesis_60d]) / 5
    confidence = sample_confidence * 0.5 + consistency * 0.5

    # Empfohlene Gewichtung
    # Basierend auf der Differenz der Returns und Confidence
    if len(all_down) >= min_samples and len(all_up) >= min_samples:
        return_diff_5d = safe_mean(down_returns_5d) - safe_mean(up_returns_5d)
        # Normalisiere auf 0-1 Skala (±2% Differenz = max Gewicht)
        recommended_weight = min(1.0, max(0.0, (return_diff_5d + 2) / 4)) * confidence
    else:
        recommended_weight = 0.0

    # Bestimme Analyseperiode
    if events:
        min_date = min(e.date for e in events)
        max_date = max(e.date for e in events)
        period = f"{min_date} to {max_date}"
    else:
        period = "N/A"

    return ThesisValidationResult(
        total_symbols=stats["total_symbols"],
        symbols_with_data=stats["symbols_with_data"],
        total_trading_days=stats["total_days"],
        analysis_period=period,
        total_gaps=len(events),
        up_gaps=len(up_gaps),
        down_gaps=len(down_gaps),
        partial_up_gaps=len(partial_up),
        partial_down_gaps=len(partial_down),
        avg_return_1d_after_up_gap=safe_mean(up_returns_1d),
        avg_return_1d_after_down_gap=safe_mean(down_returns_1d),
        avg_return_5d_after_up_gap=safe_mean(up_returns_5d),
        avg_return_5d_after_down_gap=safe_mean(down_returns_5d),
        avg_return_10d_after_up_gap=safe_mean(up_returns_10d),
        avg_return_10d_after_down_gap=safe_mean(down_returns_10d),
        avg_return_30d_after_up_gap=safe_mean(up_returns_30d),
        avg_return_30d_after_down_gap=safe_mean(down_returns_30d),
        avg_return_60d_after_up_gap=safe_mean(up_returns_60d),
        avg_return_60d_after_down_gap=safe_mean(down_returns_60d),
        win_rate_1d_after_up_gap=win_rate(up_returns_1d),
        win_rate_1d_after_down_gap=win_rate(down_returns_1d),
        win_rate_5d_after_up_gap=win_rate(up_returns_5d),
        win_rate_5d_after_down_gap=win_rate(down_returns_5d),
        win_rate_10d_after_up_gap=win_rate(up_returns_10d),
        win_rate_10d_after_down_gap=win_rate(down_returns_10d),
        win_rate_30d_after_up_gap=win_rate(up_returns_30d),
        win_rate_30d_after_down_gap=win_rate(down_returns_30d),
        win_rate_60d_after_up_gap=win_rate(up_returns_60d),
        win_rate_60d_after_down_gap=win_rate(down_returns_60d),
        up_gap_fill_rate_intraday=up_fill_rate,
        down_gap_fill_rate_intraday=down_fill_rate,
        avg_up_gap_size=avg_up_size,
        avg_down_gap_size=avg_down_size,
        thesis_supported_1d=thesis_1d,
        thesis_supported_5d=thesis_5d,
        thesis_supported_10d=thesis_10d,
        thesis_supported_30d=thesis_30d,
        thesis_supported_60d=thesis_60d,
        confidence_score=confidence,
        recommended_gap_weight=recommended_weight,
    )


def print_results(result: ThesisValidationResult, events: List[GapEvent]):
    """Gibt Ergebnisse formatiert aus."""
    print("\n" + "=" * 70)
    print("GAP THESIS VALIDATION RESULTS")
    print("=" * 70)

    print(f"\n{'DATA BASIS':^70}")
    print("-" * 70)
    print(f"  Symbols analyzed:     {result.symbols_with_data} / {result.total_symbols}")
    print(f"  Total trading days:   {result.total_trading_days:,}")
    print(f"  Analysis period:      {result.analysis_period}")

    print(f"\n{'GAP COUNTS':^70}")
    print("-" * 70)
    print(f"  Total gaps:           {result.total_gaps:,}")
    print(f"  Full Up-Gaps:         {result.up_gaps:,}")
    print(f"  Full Down-Gaps:       {result.down_gaps:,}")
    print(f"  Partial Up-Gaps:      {result.partial_up_gaps:,}")
    print(f"  Partial Down-Gaps:    {result.partial_down_gaps:,}")

    print(f"\n{'GAP CHARACTERISTICS':^70}")
    print("-" * 70)
    print(f"  Avg Up-Gap size:      {result.avg_up_gap_size:+.2f}%")
    print(f"  Avg Down-Gap size:    {result.avg_down_gap_size:+.2f}%")
    print(f"  Up-Gap fill rate:     {result.up_gap_fill_rate_intraday:.1%}")
    print(f"  Down-Gap fill rate:   {result.down_gap_fill_rate_intraday:.1%}")

    print(f"\n{'FORWARD RETURNS (Avg)':^70}")
    print("-" * 70)
    print(f"  {'':20} {'After Up-Gap':>15} {'After Down-Gap':>15} {'Diff':>10}")
    print(
        f"  {'1-Day Return':20} {result.avg_return_1d_after_up_gap:>+14.3f}% {result.avg_return_1d_after_down_gap:>+14.3f}% {result.avg_return_1d_after_down_gap - result.avg_return_1d_after_up_gap:>+9.3f}%"
    )
    print(
        f"  {'5-Day Return':20} {result.avg_return_5d_after_up_gap:>+14.3f}% {result.avg_return_5d_after_down_gap:>+14.3f}% {result.avg_return_5d_after_down_gap - result.avg_return_5d_after_up_gap:>+9.3f}%"
    )
    print(
        f"  {'10-Day Return':20} {result.avg_return_10d_after_up_gap:>+14.3f}% {result.avg_return_10d_after_down_gap:>+14.3f}% {result.avg_return_10d_after_down_gap - result.avg_return_10d_after_up_gap:>+9.3f}%"
    )
    print(
        f"  {'30-Day Return':20} {result.avg_return_30d_after_up_gap:>+14.3f}% {result.avg_return_30d_after_down_gap:>+14.3f}% {result.avg_return_30d_after_down_gap - result.avg_return_30d_after_up_gap:>+9.3f}%"
    )
    print(
        f"  {'60-Day Return':20} {result.avg_return_60d_after_up_gap:>+14.3f}% {result.avg_return_60d_after_down_gap:>+14.3f}% {result.avg_return_60d_after_down_gap - result.avg_return_60d_after_up_gap:>+9.3f}%"
    )

    print(f"\n{'WIN RATES (% positive returns)':^70}")
    print("-" * 70)
    print(f"  {'':20} {'After Up-Gap':>15} {'After Down-Gap':>15} {'Diff':>10}")
    print(
        f"  {'1-Day Win Rate':20} {result.win_rate_1d_after_up_gap:>14.1%} {result.win_rate_1d_after_down_gap:>14.1%} {(result.win_rate_1d_after_down_gap - result.win_rate_1d_after_up_gap)*100:>+9.1f}pp"
    )
    print(
        f"  {'5-Day Win Rate':20} {result.win_rate_5d_after_up_gap:>14.1%} {result.win_rate_5d_after_down_gap:>14.1%} {(result.win_rate_5d_after_down_gap - result.win_rate_5d_after_up_gap)*100:>+9.1f}pp"
    )
    print(
        f"  {'10-Day Win Rate':20} {result.win_rate_10d_after_up_gap:>14.1%} {result.win_rate_10d_after_down_gap:>14.1%} {(result.win_rate_10d_after_down_gap - result.win_rate_10d_after_up_gap)*100:>+9.1f}pp"
    )
    print(
        f"  {'30-Day Win Rate':20} {result.win_rate_30d_after_up_gap:>14.1%} {result.win_rate_30d_after_down_gap:>14.1%} {(result.win_rate_30d_after_down_gap - result.win_rate_30d_after_up_gap)*100:>+9.1f}pp"
    )
    print(
        f"  {'60-Day Win Rate':20} {result.win_rate_60d_after_up_gap:>14.1%} {result.win_rate_60d_after_down_gap:>14.1%} {(result.win_rate_60d_after_down_gap - result.win_rate_60d_after_up_gap)*100:>+9.1f}pp"
    )

    print(f"\n{'THESIS VALIDATION':^70}")
    print("-" * 70)
    print(f"  These: 'Down-Gaps führen zu besseren Returns als Up-Gaps'")
    print()

    def check_mark(val: bool) -> str:
        return "✓ SUPPORTED" if val else "✗ NOT SUPPORTED"

    print(f"  1-Day horizon:        {check_mark(result.thesis_supported_1d)}")
    print(f"  5-Day horizon:        {check_mark(result.thesis_supported_5d)}")
    print(f"  10-Day horizon:       {check_mark(result.thesis_supported_10d)}")
    print(f"  30-Day horizon:       {check_mark(result.thesis_supported_30d)}")
    print(f"  60-Day horizon:       {check_mark(result.thesis_supported_60d)}")
    print()
    print(f"  Confidence Score:     {result.confidence_score:.1%}")
    print(f"  Recommended Weight:   {result.recommended_gap_weight:.2f}")

    # Detailanalyse nach Gap-Größe
    print(f"\n{'ANALYSIS BY GAP SIZE':^70}")
    print("-" * 70)

    size_buckets = [
        ("Small (0.5-1%)", 0.5, 1.0),
        ("Medium (1-2%)", 1.0, 2.0),
        ("Large (2-3%)", 2.0, 3.0),
        ("Very Large (>3%)", 3.0, 100.0),
    ]

    for bucket_name, min_size, max_size in size_buckets:
        up_in_bucket = [
            e
            for e in events
            if e.gap_type in ("up", "partial_up") and min_size <= abs(e.gap_size_pct) < max_size
        ]
        down_in_bucket = [
            e
            for e in events
            if e.gap_type in ("down", "partial_down") and min_size <= abs(e.gap_size_pct) < max_size
        ]

        if up_in_bucket or down_in_bucket:
            up_ret = np.mean([e.return_5d for e in up_in_bucket]) if up_in_bucket else 0
            down_ret = np.mean([e.return_5d for e in down_in_bucket]) if down_in_bucket else 0
            print(
                f"  {bucket_name:20} Up(n={len(up_in_bucket):3}): {up_ret:+.2f}%  Down(n={len(down_in_bucket):3}): {down_ret:+.2f}%"
            )

    print("\n" + "=" * 70)

    # Fazit
    supported_count = sum(
        [
            result.thesis_supported_1d,
            result.thesis_supported_5d,
            result.thesis_supported_10d,
            result.thesis_supported_30d,
            result.thesis_supported_60d,
        ]
    )
    if supported_count >= 2 and result.confidence_score >= 0.5:
        print("FAZIT: Die Gap-These wird durch die Daten UNTERSTÜTZT.")
        print(
            f"       Empfehlung: Gap-Score mit Gewicht {result.recommended_gap_weight:.2f} integrieren."
        )
    elif supported_count >= 1:
        print("FAZIT: Die Gap-These wird TEILWEISE unterstützt.")
        print("       Empfehlung: Gap-Score mit reduziertem Gewicht testen.")
    else:
        print("FAZIT: Die Gap-These wird NICHT unterstützt.")
        print("       Empfehlung: Gap-Score nicht oder mit sehr geringem Gewicht verwenden.")

    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Validate Gap Trading Thesis")
    parser.add_argument(
        "--min-gap-pct", type=float, default=0.5, help="Minimum gap size in %% (default: 0.5)"
    )
    parser.add_argument(
        "--min-samples", type=int, default=10, help="Minimum samples per category (default: 10)"
    )
    parser.add_argument("--output", type=str, help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("GAP THESIS VALIDATION")
    print("=" * 70)
    print(f"\nLoading historical data from database...")

    tracker = TradeTracker()

    # Sammle Gap-Events
    print(f"Scanning for gaps (min size: {args.min_gap_pct}%)...")
    events, stats = collect_gap_events(
        tracker=tracker,
        min_gap_pct=args.min_gap_pct,
    )

    print(f"Found {len(events):,} gap events across {stats['symbols_with_data']} symbols")

    if len(events) < args.min_samples * 2:
        print(
            f"\nERROR: Not enough gap events ({len(events)}). Need at least {args.min_samples * 2}."
        )
        print("Try collecting more historical data or reducing --min-gap-pct")
        sys.exit(1)

    # Analysiere Events
    print("Analyzing gap performance...")
    result = analyze_gap_events(events, stats, args.min_samples)

    # Ausgabe
    print_results(result, events)

    # Optional: JSON speichern
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(asdict(result), f, indent=2, default=str)
        print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
