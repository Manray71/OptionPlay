# OptionPlay - Trade Tracking Analytics
# ======================================
# Formatierung und Hilfsfunktionen für Trade-Statistiken
#
# Extrahiert aus trade_tracker.py im Rahmen des Recursive Logic Refactorings (Phase 2.3)

from typing import Optional

from .models import TradeStats


def format_trade_stats(stats: TradeStats) -> str:
    """Formatiert TradeStats als lesbaren Text"""
    lines = [
        "=" * 50,
        "TRADE STATISTICS",
        "=" * 50,
        "",
        f"Total Trades:    {stats.total_trades}",
        f"Open Trades:     {stats.open_trades}",
        f"Closed Trades:   {stats.closed_trades}",
        "",
        f"Wins:            {stats.wins}",
        f"Losses:          {stats.losses}",
        f"Breakeven:       {stats.breakeven}",
        "",
        f"Win Rate:        {stats.win_rate:.1f}%",
        f"Avg P&L:         {stats.avg_pnl_percent:.2f}%",
        f"Total P&L:       ${stats.total_pnl:,.2f}",
        f"Avg Holding:     {stats.avg_holding_days:.1f} days",
        f"Avg Score:       {stats.avg_score:.1f}",
    ]

    if stats.by_score_bucket:
        lines.extend(["", "BY SCORE BUCKET:", "-" * 30])
        for bucket, data in sorted(stats.by_score_bucket.items()):
            lines.append(f"  {bucket}: {data['count']} trades, {data['win_rate']:.1f}% win rate")

    if stats.by_strategy:
        lines.extend(["", "BY STRATEGY:", "-" * 30])
        for strategy, data in sorted(stats.by_strategy.items()):
            lines.append(f"  {strategy}: {data['count']} trades, {data['win_rate']:.1f}% win rate")

    return "\n".join(lines)


def create_tracker(db_path: Optional[str] = None) -> "TradeTracker":
    """
    Factory-Funktion für TradeTracker.

    Args:
        db_path: Optionaler Pfad zur SQLite-Datenbank

    Returns:
        TradeTracker-Instanz
    """
    from .tracker import TradeTracker

    return TradeTracker(db_path)
