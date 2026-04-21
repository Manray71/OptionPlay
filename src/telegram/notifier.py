"""Telegram message formatting for OptionPlay scanner results.

Converts DailyPick objects into HTML-formatted Telegram messages
with inline keyboard buttons for shadow-trade actions.
"""

import html
from typing import Any, Dict, List, Optional, Sequence

# src/telegram/__init__.py ensures sys.modules["telegram"] = real python-telegram-bot
# before this module is imported, so the following import resolves correctly.
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Exit targets per PLAYBOOK (config/trading.yaml: profit_pct_normal=50, stop_loss_pct=200 of spread)
# TWS order display uses credit-relative targets:
_PROFIT_TARGET_PCT = 0.50  # Close at 50% of received credit (buy back at 50% debit)
_STOP_LOSS_PCT = 1.50  # Stop at 150% of received credit (buy back at 150% debit)

_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━"

_STRATEGY_LABELS = {
    "pullback": "Pullback",
    "bounce": "Bounce",
}

_TIER_ICONS = {1: "🥇", 2: "🥈", 3: "🥉"}

# E.5 — Breakout signal icons (from Christians SIGNAL_ICONS reference)
_SIGNAL_ICONS: Dict[str, str] = {
    "BREAKOUT_IMMINENT": "🚩⚡",
    "PRE_BREAKOUT": "🎯",
    "VWAP_RECLAIM": "📊",
    "THREE_BAR_PLAY": "📈",
    "BB_SQUEEZE": "⚙️↑",
    "BULL_FLAG": "🚩",
    "NR7_INSIDE": "🕯️",
    "GOLDEN_POCKET": "✧",
}

# Human-readable labels for compact signal display (E.5.3)
_SIGNAL_LABELS: Dict[str, str] = {
    "BREAKOUT_IMMINENT": "BREAKOUT IMMINENT",
    "PRE_BREAKOUT": "PRE-BREAKOUT",
    "VWAP_RECLAIM": "VWAP Reclaim",
    "THREE_BAR_PLAY": "3-Bar Play",
    "BB_SQUEEZE": "BB Squeeze released",
    "BULL_FLAG": "Bull Flag",
    "NR7_INSIDE": "NR7+Inside Bar",
    "GOLDEN_POCKET": "Golden Pocket+",
}

# Alpha fast weight — must match sector_rs config (default 1.5)
_ALPHA_FAST_WEIGHT = 1.5


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
        f"📊 <b>{symbol}</b> ({sector}) " f"🏆 Tier {grade} | {strategy_label} #{pick.rank}"
    )
    lines.append(_SEPARATOR)

    # Strikes block
    s = pick.suggested_strikes
    if s is not None:
        lines.append(f"🎯 SELL  ${s.short_strike:.1f}P  ←── SHORT")
        lines.append(f"🛡️  BUY   ${s.long_strike:.1f}P  ←── LONG")
        lines.append(f"📐 Spread: ${s.spread_width:.2f} | Aktie: ${pick.current_price:.2f}")
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

    # E.5.1 — Alpha composite breakdown (only when available)
    b = getattr(pick, "b_raw", None)
    f_ = getattr(pick, "f_raw", None)
    alpha_raw = getattr(pick, "alpha_raw", None)
    dual_label = getattr(pick, "dual_label", None)
    if alpha_raw is not None and b is not None and f_ is not None:
        composite_str = f"{alpha_raw:.0f} (B:{b:.0f} + F:{f_:.0f}×{_ALPHA_FAST_WEIGHT})"
        rrg_str = f" | {_esc(dual_label)}" if dual_label else ""
        lines.append(f"📡 Alpha: {composite_str}{rrg_str}")

    # E.5.1 — Breakout signals
    breakout_signals = getattr(pick, "breakout_signals", ()) or ()
    pre_breakout = getattr(pick, "pre_breakout", False)
    if pre_breakout and "PRE_BREAKOUT" not in breakout_signals:
        breakout_signals = ("PRE_BREAKOUT",) + tuple(breakout_signals)
    if breakout_signals:
        signal_parts = []
        for sig in breakout_signals:
            icon = _SIGNAL_ICONS.get(sig, "")
            label = _SIGNAL_LABELS.get(sig, sig)
            signal_parts.append(f"{icon} {label}" if icon else label)
        lines.append(" | ".join(signal_parts))

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
    scan_stats: Optional[Dict[str, Any]] = None,
) -> str:
    """Format scan header message sent before individual pick messages.

    Args:
        picks: List of DailyPick objects.
        vix: Current VIX value.
        scan_type: 'morning' or 'scheduled'.
        scan_stats: Optional dict with E.5.4 breakout statistics:
            symbols_scanned, duration, breakout_total, breakout_breakdown,
            top_b_symbol, top_b_score, top_f_symbol, top_f_score, post_crash.
    """
    scan_label = "Morning Scan" if scan_type == "morning" else "OptionPlay Scan"
    lines = [f"🔍 {scan_label}"]
    if vix is not None:
        lines.append(f"📊 VIX: {vix:.2f}")
    n = len(picks)
    lines.append(f"📋 {n} Empfehlung{'en' if n != 1 else ''} gefunden")

    # E.5.4 — Scan-Summary with breakout statistics
    if scan_stats:
        sym_count = scan_stats.get("symbols_scanned")
        duration = scan_stats.get("duration")
        if sym_count is not None and duration is not None:
            lines.append(f"📊 Scan: {sym_count} Symbole | {duration:.1f}s")

        breakout_total = scan_stats.get("breakout_total", 0)
        breakdown: Dict[str, int] = scan_stats.get("breakout_breakdown", {})
        if breakout_total:
            breakdown_str = " | ".join(
                f"{count}× {_SIGNAL_LABELS.get(k, k)}"
                for k, count in breakdown.items()
                if count > 0
            )
            lines.append(
                f"🚩 Breakout-Signals: {breakout_total} aktiv"
                + (f" ({breakdown_str})" if breakdown_str else "")
            )
        else:
            lines.append("🚩 Breakout-Signals: keine")

        top_b = scan_stats.get("top_b_symbol")
        top_b_score = scan_stats.get("top_b_score")
        top_f = scan_stats.get("top_f_symbol")
        top_f_score = scan_stats.get("top_f_score")
        if top_b and top_b_score is not None:
            b_part = f"Top B: {_esc(top_b)} {top_b_score:.0f}"
            f_part = (
                f" | Top F: {_esc(top_f)} {top_f_score:.0f}"
                if top_f and top_f_score is not None
                else ""
            )
            lines.append(b_part + f_part)

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


# =============================================================================
# E.5.2 — Top-15 Alpha-Composite Table
# =============================================================================


def format_top15_alpha(candidates: Sequence[Any]) -> str:
    """Format Alpha-Longlist as compact HTML Telegram table (E.5.2).

    Args:
        candidates: Sequence of AlphaCandidate objects (or any object with
                    symbol, alpha_raw, b_raw, f_raw, breakout_signals attrs).

    Returns:
        HTML-formatted Telegram message.
    """
    if not candidates:
        return "📊 <b>Top 15 Alpha-Composite</b>\n\n<i>Keine Kandidaten verfügbar.</i>"

    lines = ["📊 <b>Top 15 Alpha-Composite</b>", ""]
    # Header
    lines.append("<code> #   Symbol   Total    B    F   Signals</code>")

    for i, c in enumerate(candidates[:15], start=1):
        sym = _esc(getattr(c, "symbol", "?"))
        total = getattr(c, "alpha_raw", 0.0) or 0.0
        b = getattr(c, "b_raw", 0.0) or 0.0
        f_ = getattr(c, "f_raw", 0.0) or 0.0
        signals: tuple[str, ...] = getattr(c, "breakout_signals", ()) or ()
        pre_bo = getattr(c, "pre_breakout", False)
        if pre_bo and "PRE_BREAKOUT" not in signals:
            signals = ("PRE_BREAKOUT",) + tuple(signals)
        icons = "".join(_SIGNAL_ICONS.get(s, "") for s in signals)

        row = (
            f"<code>{i:2d}  {sym:<8s} {total:5.0f}  {b:4.0f} {f_:4.0f}</code>"
            + (f"  {icons}" if icons else "")
        )
        lines.append(row)

    return "\n".join(lines)


# =============================================================================
# E.5.3 — Exit-Alerts (G.1-G.4)
# =============================================================================


def format_exit_signal(signal: Any, snap: Optional[Any] = None) -> str:
    """Format a PositionSignal as HTML Telegram exit-alert message (E.5.3).

    Args:
        signal: PositionSignal with action, reason, priority, symbol, dte, pnl_pct.
        snap: Optional PositionSnapshot for extra context (expiration, short/long strike).

    Returns:
        HTML-formatted string.
    """
    from ..constants.trading_rules import ExitAction

    symbol = _esc(getattr(signal, "symbol", "?"))
    dte = getattr(signal, "dte", None)
    pnl = getattr(signal, "pnl_pct", None)
    priority = getattr(signal, "priority", 0)
    action = getattr(signal, "action", None)

    # Determine header based on priority / action type
    if priority == 5:
        header = f"🔴 <b>GAMMA-ZONE EXIT — {symbol}</b>"
    elif priority == 6:
        header = f"🟡 <b>TIME-STOP — {symbol}</b>"
    elif priority == 10 and action == ExitAction.CLOSE:
        header = f"🔴 <b>RRG LAGGING — {symbol}</b>"
    elif priority == 10 and action == ExitAction.ALERT:
        header = f"🟡 <b>RRG ROTATION — {symbol}</b>"
    elif action == ExitAction.CLOSE:
        header = f"🔴 <b>EXIT — {symbol}</b>"
    elif action == ExitAction.ROLL:
        header = f"🔄 <b>ROLL — {symbol}</b>"
    else:
        header = f"⚠️ <b>ALERT — {symbol}</b>"

    lines = [header]

    # Position details from snapshot
    if snap is not None:
        short_k = getattr(snap, "short_strike", None)
        long_k = getattr(snap, "long_strike", None)
        expiry = getattr(snap, "expiration", None)
        if short_k and long_k and expiry:
            dte_str = f" | DTE {dte}" if dte is not None else ""
            lines.append(f"${short_k:.0f}/${long_k:.0f}P exp {_esc(expiry)}{dte_str}")
    elif dte is not None:
        lines.append(f"DTE {dte}")

    # P&L
    if pnl is not None:
        pnl_str = f"{pnl:+.0f}%"
        lines.append(f"P&L: {pnl_str}")

    # Reason / signal text
    reason = _esc(getattr(signal, "reason", ""))
    if reason:
        lines.append(reason)

    # Action recommendation
    if action == ExitAction.CLOSE:
        lines.append("→ Jetzt schliessen")
    elif action == ExitAction.ROLL:
        lines.append("→ Roll prüfen")
    elif action == ExitAction.ALERT:
        lines.append("→ Position beobachten")

    return "\n".join(lines)


def format_macro_alert(events: List[str]) -> str:
    """Format a G.4 macro-calendar alert for upcoming FOMC/CPI/NFP (E.5.3).

    Args:
        events: List of event names, e.g. ["FOMC", "CPI"].

    Returns:
        HTML-formatted string, or empty string if no events.
    """
    if not events:
        return ""
    event_str = " + ".join(_esc(e) for e in events)
    return (
        f"📅 <b>MACRO MORGEN: {event_str}</b>\n"
        "Erhöhtes Gap-Risiko für alle offenen Positionen.\n"
        "Offene Spreads prüfen."
    )
