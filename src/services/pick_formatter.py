# OptionPlay - Pick Formatter
# ===========================
"""
Markdown-Formatierung für DailyPicks und DailyRecommendationResult.

Extrahiert aus recommendation_engine.py (Phase 3.2).
Enthält reine Präsentationslogik ohne Geschäftslogik.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def format_picks_markdown(result) -> str:
    """
    Formatiert die Picks als Markdown.

    Args:
        result: DailyRecommendationResult

    Returns:
        Markdown-formatierter String
    """
    if not result:
        return "Keine Empfehlungen verfügbar."

    # Import here to avoid circular imports
    try:
        from ..vix_strategy import MarketRegime
    except ImportError:
        from vix_strategy import MarketRegime

    lines = [
        f"# 📊 Daily Picks - {result.timestamp.strftime('%Y-%m-%d')}",
        "",
    ]

    # Markt-Übersicht
    if result.vix_level:
        regime_emoji = {
            MarketRegime.LOW_VOL: "🟢",
            MarketRegime.NORMAL: "🟢",
            MarketRegime.DANGER_ZONE: "🟡",
            MarketRegime.ELEVATED: "🟠",
            MarketRegime.HIGH_VOL: "🔴",
        }.get(result.market_regime, "⚪")

        lines.extend([
            f"**Markt-Regime:** {regime_emoji} {result.market_regime.value.replace('_', ' ').title()}",
            f"**VIX:** {result.vix_level:.2f}",
            "",
        ])

    # Warnungen
    if result.warnings:
        lines.append("### ⚠️ Warnungen")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    # Picks
    lines.append("## Empfehlungen")
    lines.append("")

    if not result.picks:
        lines.append("*Keine geeigneten Kandidaten gefunden.*")
    else:
        for pick in result.picks:
            lines.extend(format_single_pick(pick))
            lines.append("")

    # Statistiken
    lines.extend([
        "---",
        f"*Gescannt: {result.symbols_scanned} Symbole | "
        f"Signale: {result.signals_found} | "
        f"Nach Stabilität: {result.after_stability_filter} | "
        f"Zeit: {result.generation_time_seconds:.1f}s*",
    ])

    return "\n".join(lines)


def format_single_pick(pick) -> List[str]:
    """Formatiert einen einzelnen Pick als Markdown."""
    # Grade Badge
    grade_badge = ""
    if pick.reliability_grade:
        grade_colors = {'A': '🟢', 'B': '🟢', 'C': '🟡', 'D': '🟠', 'F': '🔴'}
        grade_badge = f" {grade_colors.get(pick.reliability_grade, '')}[{pick.reliability_grade}]"

    lines = [
        f"### {pick.rank}. **{pick.symbol}** - {pick.strategy.replace('_', ' ').title()}{grade_badge}",
        "",
        f"| Metrik | Wert |",
        f"|--------|------|",
        f"| **Preis** | ${pick.current_price:.2f} |",
        f"| **Score** | {pick.score:.1f}/10 |",
        f"| **Stability** | {pick.stability_score:.0f}/100 |",
    ]

    if pick.historical_win_rate:
        lines.append(f"| **Hist. Win Rate** | {pick.historical_win_rate:.0f}% |")

    if pick.sector:
        lines.append(f"| **Sektor** | {pick.sector} |")

    lines.append("")

    # Strike-Empfehlung
    if pick.suggested_strikes:
        s = pick.suggested_strikes
        lines.extend([
            f"**Strike-Empfehlung:**",
        ])
        if s.expiry:
            dte_str = f" ({s.dte} DTE)" if s.dte is not None else ""
            lines.append(f"- Expiry: {s.expiry}{dte_str}")
        if s.dte_warning:
            lines.append(f"  ⚠️ {s.dte_warning}")
        lines.extend([
            f"- Short Put: ${s.short_strike:.2f}"
            + (f" (OI: {s.short_oi:,})" if s.short_oi else ""),
            f"- Long Put: ${s.long_strike:.2f}"
            + (f" (OI: {s.long_oi:,})" if s.long_oi else ""),
            f"- Spread Width: ${s.spread_width:.2f}",
        ])
        if s.estimated_credit:
            lines.append(f"- Est. Credit: ${s.estimated_credit:.2f}")
        if s.prob_profit:
            lines.append(f"- P(Profit): {s.prob_profit:.0f}%")
        # Tradeable status
        status_badges = {
            "READY": "READY",
            "WARNING": "WARNING",
            "NOT_TRADEABLE": "NOT TRADEABLE",
        }
        status_str = status_badges.get(s.tradeable_status, s.tradeable_status)
        if s.tradeable_status != "unknown":
            lines.append(f"- Status: {status_str}")
        lines.append("")

    # Begründung
    if pick.reason:
        lines.append(f"**Begründung:** {pick.reason}")
        lines.append("")

    # Warnungen
    if pick.warnings:
        for warning in pick.warnings:
            lines.append(f"⚠️ {warning}")

    return lines
