"""Telegram message formatting for OptionPlay scanner results.

Converts DailyPick objects into HTML-formatted Telegram messages
with inline keyboard buttons for shadow-trade actions.
"""

import html
from typing import Optional

# src/telegram/__init__.py ensures sys.modules["telegram"] = real python-telegram-bot
# before this module is imported, so the following import resolves correctly.
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Exit targets per PLAYBOOK (config/trading.yaml: profit_pct_normal=50, stop_loss_pct=200 of spread)
# TWS order display uses credit-relative targets:
_PROFIT_TARGET_PCT = 0.50  # Close at 50% of received credit (buy back at 50% debit)
_STOP_LOSS_PCT = 1.50      # Stop at 150% of received credit (buy back at 150% debit)

_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━"

_STRATEGY_LABELS = {
    "pullback": "Pullback",
    "bounce": "Bounce",
}

_TIER_ICONS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _esc(value: object) -> str:
    """HTML-escape any dynamic value."""
    return html.escape(str(value))


def format_pick_message(pick, vix: Optional[float] = None) -> str:
    """Format a DailyPick as HTML Telegram message.

    Args:
        pick: DailyPick object (from DailyRecommendationResult)
        vix: Current VIX value (optional, for context display)

    Returns:
        HTML-formatted string ready for bot.send_message(parse_mode='HTML')
    """
    strategy_label = _STRATEGY_LABELS.get(pick.strategy, _esc(pick.strategy).capitalize())
    grade = _esc(pick.reliability_grade) if pick.reliability_grade else "?"
    symbol = _esc(pick.symbol)
    sector = _esc(pick.sector) if pick.sector else "—"

    lines = []

    # Header
    lines.append(
        f"📊 <b>{symbol}</b> ({sector}) "
        f"🏆 Tier {grade} | {strategy_label} #{pick.rank}"
    )
    lines.append(_SEPARATOR)

    # Strikes block
    s = pick.suggested_strikes
    if s is not None:
        lines.append(f"🎯 SELL  ${s.short_strike:.1f}P  ←── SHORT")
        lines.append(f"🛡️  BUY   ${s.long_strike:.1f}P  ←── LONG")
        lines.append(
            f"📐 Spread: ${s.spread_width:.2f} | Aktie: ${pick.current_price:.2f}"
        )
        expiry_str = _esc(s.expiry) if s.expiry else "n/a"
        dte_str = f"({s.dte}d)" if s.dte is not None else ""
        lines.append(f"📅 Expiry: {expiry_str} {dte_str}".rstrip())
    else:
        lines.append(f"📐 Aktie: ${pick.current_price:.2f}")
        lines.append("⚠️ Strikes: n/a")

    lines.append(_SEPARATOR)

    # Credit + scoring
    if s is not None and s.estimated_credit is not None:
        lines.append(f"💰 Kredit: ~${s.estimated_credit:.2f}")

    score_line = f"📊 Score: {pick.score:.1f}"
    if pick.enhanced_score is not None:
        score_line += f" (Enhanced: {pick.enhanced_score:.1f})"
    lines.append(score_line)

    win_rate = f"{pick.historical_win_rate:.1f}%" if pick.historical_win_rate is not None else "n/a"
    lines.append(f"📈 Win Rate: {win_rate} | Stability: {pick.stability_score:.0f}")

    tier_icon = _TIER_ICONS.get(pick.liquidity_tier, "")
    tier_label = f"T{pick.liquidity_tier}" if pick.liquidity_tier is not None else "n/a"
    lines.append(f"⚡ Speed: {pick.speed_score:.1f} | Liquidity: {tier_icon}{tier_label}")

    # TWS order block (only when credit is known)
    if s is not None and s.estimated_credit is not None:
        credit = s.estimated_credit
        profit_debit = credit * _PROFIT_TARGET_PCT
        stop_debit = credit * _STOP_LOSS_PCT
        lines.append(_SEPARATOR)
        lines.append("📋 TWS ORDER:")
        lines.append(f"   Kredit:        ${credit:.2f}")
        lines.append(f"   Profit (+50%): ${profit_debit:.2f} Debit")
        lines.append(f"   Stop  (-50%):  ${stop_debit:.2f} Debit")
        lines.append("   GTC → Submit")

    # Warnings (appended at end, not crashing on empty list)
    if pick.warnings:
        lines.append(_SEPARATOR)
        for w in pick.warnings:
            lines.append(f"⚠️ {_esc(w)}")

    return "\n".join(lines)


def format_pick_buttons(pick) -> InlineKeyboardMarkup:
    """Create inline keyboard with SHADOW/SKIP/LATER buttons.

    Callback data format: "action:symbol:strategy:rank"
    Max 64 bytes per callback_data.
    """
    symbol = pick.symbol
    strategy = pick.strategy
    rank = pick.rank

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ SHADOW LOGGEN",
                callback_data=f"shadow:{symbol}:{strategy}:{rank}",
            ),
            InlineKeyboardButton(
                "⏭ SKIP",
                callback_data=f"skip:{symbol}:{rank}",
            ),
            InlineKeyboardButton(
                "⏰ SPÄTER",
                callback_data=f"later:{symbol}:{rank}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_scan_summary(
    picks: list,
    vix: Optional[float] = None,
    scan_type: str = "scheduled",
) -> str:
    """Format scan header message sent before individual pick messages."""
    scan_label = "Morning Scan" if scan_type == "morning" else "OptionPlay Scan"
    lines = [f"🔍 {scan_label}"]
    if vix is not None:
        lines.append(f"📊 VIX: {vix:.2f}")
    n = len(picks)
    lines.append(f"📋 {n} Empfehlung{'en' if n != 1 else ''} gefunden")
    return "\n".join(lines)


def format_no_picks_message(
    vix: Optional[float] = None,
    scan_type: str = "scheduled",
) -> str:
    """Message when scan found no qualifying picks."""
    scan_label = "Morning Scan" if scan_type == "morning" else "OptionPlay Scan"
    lines = [f"🔍 {scan_label}"]
    if vix is not None:
        lines.append(f"📊 VIX: {vix:.2f}")
    lines.append("❌ Keine qualifizierten Setups gefunden")
    return "\n".join(lines)


def format_shadow_confirmation(
    symbol: str,
    trade_id: str,
    strategy: str,
) -> str:
    """Confirmation message after shadow trade was logged."""
    strategy_label = _STRATEGY_LABELS.get(strategy, strategy.capitalize())
    return (
        f"✅ Shadow-Trade geloggt\n"
        f"📊 {_esc(symbol)} ({strategy_label})\n"
        f"🆔 Trade-ID: <code>{_esc(trade_id)}</code>"
    )


def format_skip_confirmation(symbol: str) -> str:
    """Brief confirmation after skip."""
    return f"⏭ {_esc(symbol)} übersprungen"


def format_later_confirmation(symbol: str, remind_minutes: int) -> str:
    """Confirmation after LATER with remind time."""
    return f"⏰ {_esc(symbol)} — Erinnerung in {remind_minutes} Min"


# === Status / Command Formatters ===


def format_status_message(
    vix: Optional[float],
    regime: Optional[str],
    open_positions: int,
    max_positions: int,
    shadow_stats: Optional[dict] = None,
) -> str:
    """Format /status response."""
    lines = ["📡 <b>OptionPlay Status</b>"]
    if vix is not None:
        regime_str = f" ({_esc(regime)})" if regime else ""
        lines.append(f"📊 VIX: {vix:.2f}{regime_str}")
    lines.append(f"📂 Positionen: {open_positions}/{max_positions}")
    if shadow_stats:
        total = shadow_stats.get("total", 0)
        wins = shadow_stats.get("wins", 0)
        wr = (wins / total * 100) if total else 0.0
        lines.append(f"🔍 Shadow: {total} Trades | WR: {wr:.1f}%")
    return "\n".join(lines)


def format_vix_message(
    vix: float,
    regime: str,
    regime_params: Optional[dict] = None,
) -> str:
    """Format /vix response."""
    lines = [
        f"📊 <b>VIX: {vix:.2f}</b>",
        f"🔰 Regime: {_esc(regime)}",
    ]
    if regime_params:
        if "max_positions" in regime_params:
            lines.append(f"📂 Max Positionen: {regime_params['max_positions']}")
        if "min_score" in regime_params:
            lines.append(f"🎯 Min Score: {regime_params['min_score']}")
        if "spread_width" in regime_params:
            lines.append(f"📐 Spread Width: ${regime_params['spread_width']:.2f}")
    return "\n".join(lines)
