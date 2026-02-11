# OptionPlay - Pick Formatter
# ===========================
"""
Markdown-Formatierung für DailyPicks und DailyRecommendationResult.

Extrahiert aus recommendation_engine.py (Phase 3.2).
Enthält reine Präsentationslogik ohne Geschäftslogik.
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from ..constants.trading_rules import EXIT_PROFIT_PCT_NORMAL, EXIT_STOP_LOSS_MULTIPLIER

logger = logging.getLogger(__name__)

try:
    from ..utils.markdown_builder import MarkdownBuilder, truncate
except ImportError:
    from utils.markdown_builder import MarkdownBuilder, truncate  # type: ignore[no-redef]  # fallback for non-package execution


def format_picks_markdown(result: Any) -> str:
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
        from vix_strategy import MarketRegime  # type: ignore[no-redef]  # fallback for non-package execution

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


def format_single_pick(pick: Any) -> list[str]:
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


# =============================================================================
# V2 FORMAT — MarkdownBuilder-basiert (für MCP daily picks)
# =============================================================================

_REGIME_DISPLAY = {
    'low_vol': 'Normal',
    'normal': 'Normal',
    'danger_zone': 'Danger Zone',
    'elevated': 'Elevated',
    'high_vol': 'High Volatility',
    'unknown': 'Unknown',
}

_STRATEGY_DISPLAY = {
    "pullback": "Pullback",
    "bounce": "Bounce",
    "ath_breakout": "ATH Breakout",
    "earnings_dip": "Earnings Dip",
}


def format_picks_v2(
    result: Any,
    duration: float = 0.0,
    excluded_by_earnings: int = 0,
) -> str:
    """
    Formatiert Picks im v2-Format mit MarkdownBuilder.

    Dieses Format wird vom MCP daily picks Tool verwendet und enthält
    Chain-validierte Spread-Daten, Entry Quality, Checklists.

    Args:
        result: DailyRecommendationResult
        duration: Scan-Dauer in Sekunden
        excluded_by_earnings: Anzahl durch Earnings ausgeschlossener Symbole

    Returns:
        Markdown-formatierter String
    """
    b = MarkdownBuilder()
    today_str = date.today().isoformat()

    # Header
    b.h1(f"Daily Picks -- {today_str}").blank()

    # Market Overview (compact single-line)
    if result.vix_level:
        regime_str = _REGIME_DISPLAY.get(
            result.market_regime.value, result.market_regime.value
        )
        b.kv("Regime", f"{regime_str} (VIX {result.vix_level:.2f})")

    b.kv("Scanned", f"{result.symbols_scanned} symbols | Duration: {duration:.1f}s")
    b.blank()

    # Warnings (compact)
    if result.warnings:
        for warning in result.warnings:
            b.bullet(warning)
        b.blank()

    # Picks — detailed v2 format
    if result.picks:
        for pick in result.picks:
            format_single_pick_v2(b, pick)
    else:
        b.hint("No candidates found matching criteria.")

    return b.build()


def format_single_pick_v2(b: MarkdownBuilder, pick: Any) -> None:
    """
    Formatiert einen einzelnen Pick im v2-Format mit Chain-Daten.

    Args:
        b: MarkdownBuilder-Instanz (wird in-place modifiziert)
        pick: DailyPick
    """
    strategy_str = _STRATEGY_DISPLAY.get(
        pick.strategy, pick.strategy.replace('_', ' ').title()
    )

    # EQS display
    eqs_str = ""
    if pick.entry_quality and hasattr(pick.entry_quality, 'eqs_total'):
        eqs_str = f" | EQS {pick.entry_quality.eqs_total:.0f}"

    # Header
    b.h2(f"#{pick.rank} -- {pick.symbol} | {strategy_str} | Score {pick.score:.1f}{eqs_str}")
    b.blank()

    # Chain-validated spread data (if available from SpreadValidation)
    sv = pick.spread_validation
    if sv and sv.tradeable:
        # Legs table
        short = sv.short_leg
        long = sv.long_leg

        leg_rows = [
            [
                f"${short.strike:.0f}",
                f"{short.delta:.2f}",
                f"{short.iv * 100:.1f}%" if short.iv else "-",
                f"{short.open_interest:,}",
                f"${short.bid:.2f}/${short.ask:.2f}",
            ],
            [
                f"${long.strike:.0f}",
                f"{long.delta:.2f}",
                f"{long.iv * 100:.1f}%" if long.iv else "-",
                f"{long.open_interest:,}",
                f"${long.bid:.2f}/${long.ask:.2f}",
            ],
        ]
        b.table(
            ["Strike", "Delta", "IV", "OI", "Bid/Ask"],
            leg_rows
        )
        b.blank()

        # Spread details
        b.text(
            f"**Spread:** ${sv.spread_width:.0f} breit | "
            f"**Expiry:** {sv.expiration} ({sv.dte} DTE)"
        )

        # Credit line
        credit_check = "OK" if sv.credit_pct and sv.credit_pct >= 10 else "LOW"
        b.text(
            f"**Credit:** ${sv.credit_bid:.2f} (Bid) -- "
            f"${sv.credit_mid:.2f} (Mid) | "
            f"**Credit/Breite:** {sv.credit_pct:.1f}% {credit_check}"
        )

        # Risk targets
        max_loss = sv.max_loss_per_contract if sv.max_loss_per_contract else 0
        profit_target_50 = sv.credit_bid * (EXIT_PROFIT_PCT_NORMAL / 100) if sv.credit_bid else 0
        stop_loss_200 = sv.credit_bid * EXIT_STOP_LOSS_MULTIPLIER if sv.credit_bid else 0
        b.text(
            f"**Max Loss:** ${max_loss:.0f}/Kontrakt | "
            f"**50% Target:** ${profit_target_50:.2f} | "
            f"**200% Stop:** ${stop_loss_200:.2f}"
        )
        b.blank()

    elif pick.suggested_strikes:
        # Fallback: theoretical strikes (no chain data)
        s = pick.suggested_strikes
        b.text(
            f"**Strikes:** Short ${s.short_strike:.0f} / Long ${s.long_strike:.0f} "
            f"| Width ${s.spread_width:.0f}"
        )
        if s.estimated_credit:
            b.text(f"**Est. Credit:** ${s.estimated_credit:.2f}")
        if s.expiry:
            dte_str = f" ({s.dte} DTE)" if s.dte is not None else ""
            b.text(f"**Expiry:** {s.expiry}{dte_str}")
        if s.tradeable_status and s.tradeable_status != "unknown":
            b.text(f"**Status:** {s.tradeable_status}")
        b.blank()

    # Entry Quality line (if EQS available)
    eq = pick.entry_quality
    if eq and hasattr(eq, 'iv_rank'):
        parts = []
        if eq.iv_rank is not None:
            parts.append(f"IV Rank {eq.iv_rank:.0f}%")
        if eq.iv_percentile is not None:
            parts.append(f"IV Pctl {eq.iv_percentile:.0f}%")
        if eq.rsi is not None:
            rsi_label = ""
            if eq.rsi < 35:
                rsi_label = " (oversold)"
            elif eq.rsi > 65:
                rsi_label = " (overbought)"
            parts.append(f"RSI {eq.rsi:.0f}{rsi_label}")
        if eq.pullback_pct is not None:
            parts.append(f"Pullback {eq.pullback_pct:.1f}%")
        if sv and sv.spread_theta:
            parts.append(f"Theta ${sv.spread_theta:.3f}/d")

        if parts:
            b.text(f"**Entry:** {' | '.join(parts)}")
            b.blank()

    # Checklist line
    checklist_parts = []
    if pick.stability_score:
        checklist_parts.append(f"Stab({pick.stability_score:.0f})")
    if pick.current_price:
        checklist_parts.append(f"Preis(${pick.current_price:.0f})")
    if sv and sv.dte:
        checklist_parts.append(f"DTE({sv.dte})")
    if sv and sv.credit_pct:
        checklist_parts.append(f"Credit({sv.credit_pct:.1f}%)")
    if pick.sector:
        checklist_parts.append(pick.sector[:12])

    if checklist_parts:
        b.text(f"**Checks:** {' | '.join(checklist_parts)}")

    # Signal reason
    if pick.reason:
        b.text(f"**Signal:** {truncate(pick.reason, 120)}")

    # Warnings
    if pick.warnings:
        for warning in pick.warnings:
            b.bullet(f"Warning: {warning}")

    b.blank()
