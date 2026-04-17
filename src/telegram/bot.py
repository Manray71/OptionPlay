"""OptionPlay Telegram Bot.

Application setup, command handlers, and callback handlers.
Runs as a standalone process via scripts/run_telegram_bot.sh.

Commands: /start, /status, /scan, /top15, /vix, /open, /pnl,
          /sync, /earnings, /export, /help

Buttons: SHADOW LOGGEN, SKIP, SPÄTER
"""

import asyncio
import csv
import io
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .notifier import (
    format_later_confirmation,
    format_no_picks_message,
    format_pick_buttons,
    format_pick_message,
    format_scan_summary,
    format_shadow_confirmation,
    format_skip_confirmation,
    format_status_message,
    format_vix_message,
)

logger = logging.getLogger(__name__)

# === Config ===


def _get_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")
    return token


def _get_chat_id() -> int:
    cid = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not cid:
        raise RuntimeError("TELEGRAM_CHAT_ID not set in environment")
    return int(cid)


# === Server Singleton ===

_server = None


async def _get_server():
    """Lazy-init OptionPlayServer singleton."""
    global _server
    if _server is None:
        from src.mcp_server import OptionPlayServer

        _server = OptionPlayServer()
    return _server


# === Helpers ===


def _vix_to_regime_label(vix: Optional[float]) -> str:
    if vix is None:
        return "Unknown"
    if vix < 15:
        return "Low Vol"
    if vix < 20:
        return "Normal"
    if vix < 25:
        return "Elevated"
    if vix < 30:
        return "Danger Zone"
    return "High Vol"


def _pick_to_cache_dict(pick, vix: Optional[float], regime: Optional[str]) -> dict:
    """Extract cacheable fields from a DailyPick for button callbacks."""
    d = {
        "score": pick.score,
        "current_price": pick.current_price,
        "stability_score": pick.stability_score,
        "enhanced_score": getattr(pick, "enhanced_score", None),
        "liquidity_tier": getattr(pick, "liquidity_tier", None),
        "vix": vix,
        "regime": regime,
        # strike defaults (overwritten below if available)
        "short_strike": 0.0,
        "long_strike": 0.0,
        "spread_width": 0.0,
        "est_credit": 0.0,
        "expiration": "",
        "dte": 0,
    }
    ss = getattr(pick, "suggested_strikes", None)
    if ss is not None:
        d.update(
            {
                "short_strike": getattr(ss, "short_strike", 0.0) or 0.0,
                "long_strike": getattr(ss, "long_strike", 0.0) or 0.0,
                "spread_width": getattr(ss, "spread_width", 0.0) or 0.0,
                "est_credit": getattr(ss, "estimated_credit", 0.0) or 0.0,
                "expiration": getattr(ss, "expiry", "") or "",
                "dte": getattr(ss, "dte", 0) or 0,
            }
        )
    return d


# === Command Handlers ===


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Begrüssung + Command-Übersicht."""
    text = (
        "🎯 <b>OptionPlay Scanner Bot</b>\n\n"
        "Befehle:\n"
        "/scan — Manueller Scan starten\n"
        "/status — Portfolio-Übersicht\n"
        "/vix — VIX + Regime-Status\n"
        "/top15 — Top 15 technische Kandidaten\n"
        "/open — Offene Shadow-Positionen\n"
        "/pnl — Shadow-P&L-Übersicht\n"
        "/sync — IBKR-Portfolio-Sync\n"
        "/earnings — Earnings-Kalender\n"
        "/export — CSV-Export Shadow-Trades\n"
        "/help — Diese Hilfe\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gleich wie /start."""
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — Portfolio-Übersicht (VIX + offene Shadow-Positionen)."""
    try:
        server = await _get_server()
        vix = await server.handlers.vix.get_vix()
        regime = _vix_to_regime_label(vix)

        max_pos = 0
        if vix is not None:
            from src.services.vix_regime import get_regime_params

            params = get_regime_params(vix)
            max_pos = params.max_positions

        from src.shadow_tracker import ShadowTracker, get_stats

        st = ShadowTracker()
        open_count = len(st.get_open_trades())

        raw_stats = get_stats(st)
        totals = raw_stats.get("totals", {})
        shadow_stats = {
            "total": totals.get("total", 0),
            "wins": totals.get("wins", 0),
        }

        msg = format_status_message(vix, regime, open_count, max_pos, shadow_stats)
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"cmd_status error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def _run_scan_and_notify(
    bot,
    chat_id: int,
    bot_data: dict,
    scan_type: str = "manual",
) -> None:
    """Shared scan logic for cmd_scan and scheduled_scan.

    Sends status message, runs daily_picks, formats and sends each pick
    with action buttons, and caches pick data in bot_data for callbacks.
    """
    await bot.send_message(chat_id=chat_id, text="🔍 Scan läuft...")

    server = await _get_server()
    result = await server.handlers.scan.daily_picks_result()

    vix = result.vix_level
    regime = _vix_to_regime_label(vix)
    picks = result.picks

    if not picks:
        msg = format_no_picks_message(vix=vix, scan_type=scan_type)
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        return

    summary = format_scan_summary(picks, vix=vix, scan_type=scan_type)
    await bot.send_message(chat_id=chat_id, text=summary, parse_mode="HTML")
    await asyncio.sleep(0.3)

    for pick in picks:
        text = format_pick_message(pick, vix=vix)
        buttons = format_pick_buttons(pick)
        await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=buttons
        )

        pick_key = f"pick:{pick.symbol}:{pick.strategy}:{pick.rank}"
        bot_data[pick_key] = _pick_to_cache_dict(pick, vix, regime)

        await asyncio.sleep(0.5)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/scan — Manueller Scan, Ergebnisse als Picks mit Buttons."""
    try:
        await _run_scan_and_notify(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            bot_data=context.bot_data,
            scan_type="manual",
        )
    except Exception as e:
        logger.error(f"cmd_scan error: {e}")
        await update.message.reply_text(f"❌ Scan-Fehler: {e}")


async def cmd_top15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/top15 — Top 15 technische Kandidaten (kompakte Liste, keine Buttons)."""
    try:
        await update.message.reply_text("🔍 Top-15-Scan läuft...")
        server = await _get_server()
        result_str = await server.handlers.scan.scan_multi_strategy(max_results=15)
        # scan_multi_strategy returns Markdown — send as plain text
        await update.message.reply_text(result_str)
    except Exception as e:
        logger.error(f"cmd_top15 error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def cmd_vix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vix — VIX + Regime-Status."""
    try:
        server = await _get_server()
        vix = await server.handlers.vix.get_vix()

        if vix is None:
            await update.message.reply_text("❌ VIX-Daten nicht verfügbar")
            return

        regime = _vix_to_regime_label(vix)

        from src.services.vix_regime import get_regime_params

        params = get_regime_params(vix)
        regime_params = {
            "max_positions": params.max_positions,
            "min_score": params.min_score,
            "spread_width": params.spread_width,
        }

        msg = format_vix_message(vix, regime, regime_params)
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"cmd_vix error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def cmd_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/open — Offene Shadow-Positionen."""
    try:
        from src.shadow_tracker import ShadowTracker

        st = ShadowTracker()
        trades = st.get_open_trades()

        if not trades:
            await update.message.reply_text("📭 Keine offenen Shadow-Positionen")
            return

        lines = ["📂 <b>Offene Shadow-Positionen</b>"]
        for t in trades:
            symbol = t.get("symbol", "?")
            strategy = t.get("strategy", "?")
            short_k = t.get("short_strike", 0)
            long_k = t.get("long_strike", 0)
            expiry = t.get("expiration", "?")
            score = t.get("score", 0)
            logged = (t.get("logged_at") or "")[:10]
            lines.append(
                f"• <b>{symbol}</b> {strategy} | "
                f"{short_k}/{long_k} exp {expiry} | "
                f"Score {score:.1f} | {logged}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"cmd_open error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pnl — Shadow-P&L-Übersicht."""
    try:
        from src.shadow_tracker import ShadowTracker, get_stats

        st = ShadowTracker()
        raw = get_stats(st)
        totals = raw.get("totals", {})
        groups = raw.get("groups", [])

        total = totals.get("total", 0)
        wins = totals.get("wins", 0)
        wr = totals.get("win_rate", 0.0)
        pnl = totals.get("total_pnl", 0.0)

        lines = [
            "📊 <b>Shadow P&L</b>",
            f"Gesamt: {total} Trades | WR: {wr:.1f}% | P&L: ${pnl:+.2f}",
        ]

        if groups:
            lines.append("")
            lines.append("<b>Nach Strategie:</b>")
            for g in groups:
                key = g.get("key", "?")
                g_total = g.get("total", 0)
                g_wr = g.get("win_rate", 0.0)
                g_pnl = g.get("total_pnl", 0.0)
                lines.append(
                    f"• {key}: {g_total} Trades | WR {g_wr:.1f}% | ${g_pnl:+.2f}"
                )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"cmd_pnl error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sync — IBKR-Portfolio-Sync (zeigt aktuelle offene Positionen)."""
    try:
        await update.message.reply_text("🔄 IBKR Sync läuft...")
        server = await _get_server()
        result_str = server.handlers.portfolio.portfolio_positions("open")
        await update.message.reply_text(result_str or "Keine offenen Positionen")
    except Exception as e:
        logger.error(f"cmd_sync error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def cmd_earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/earnings — Earnings-Kalender (nächste 14 Tage)."""
    try:
        db_path = Path.home() / ".optionplay" / "trades.db"
        today = date.today()
        end = today + timedelta(days=14)

        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT symbol, earnings_date, time_of_day, fiscal_quarter
                FROM earnings_history
                WHERE earnings_date BETWEEN ? AND ?
                ORDER BY earnings_date, symbol
                """,
                (today.isoformat(), end.isoformat()),
            ).fetchall()

        if not rows:
            await update.message.reply_text(
                f"📅 Keine Earnings in den nächsten 14 Tagen ({today} – {end})"
            )
            return

        lines = [f"📅 <b>Earnings {today} – {end}</b>"]
        current_date = None
        for symbol, edate, tod, quarter in rows:
            if edate != current_date:
                current_date = edate
                lines.append(f"\n<b>{edate}</b>")
            tod_str = f" ({tod})" if tod else ""
            q_str = f" {quarter}" if quarter else ""
            lines.append(f"  • {symbol}{q_str}{tod_str}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"cmd_earnings error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/export — CSV-Export aller Shadow-Trades."""
    try:
        from src.shadow_tracker import ShadowTracker

        st = ShadowTracker()
        trades = st.get_trades(days_back=9999)

        if not trades:
            await update.message.reply_text("📭 Keine Shadow-Trades zum Exportieren")
            return

        columns = [
            "id", "symbol", "strategy", "status", "score",
            "short_strike", "long_strike", "spread_width", "est_credit",
            "expiration", "dte", "price_at_log", "vix_at_log",
            "regime_at_log", "stability_at_log", "logged_at",
            "theoretical_pnl",
        ]

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for t in trades:
            writer.writerow({col: t.get(col, "") for col in columns})

        csv_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
        filename = f"shadow_trades_{date.today().isoformat()}.csv"
        await update.message.reply_document(document=csv_bytes, filename=filename)
    except Exception as e:
        logger.error(f"cmd_export error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}")


# === Callback Handler (Buttons) ===


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses (shadow/skip/later)."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    action = parts[0] if parts else ""

    if action == "shadow" and len(parts) >= 4:
        symbol, strategy, rank = parts[1], parts[2], int(parts[3])
        await _handle_shadow_log(query, symbol, strategy, rank, context)
    elif action == "skip" and len(parts) >= 3:
        symbol = parts[1]
        await _handle_skip(query, symbol)
    elif action == "later" and len(parts) >= 3:
        symbol, rank = parts[1], int(parts[2])
        await _handle_later(query, symbol, rank, context)
    else:
        logger.warning(f"Unknown callback action: {action!r} (data={data!r})")


async def _handle_shadow_log(query, symbol, strategy, rank, context):
    """Log shadow trade via ShadowTracker."""
    try:
        from src.shadow_tracker import ShadowTracker

        pick_key = f"pick:{symbol}:{strategy}:{rank}"
        pick_data = context.bot_data.get(pick_key)

        if pick_data is None:
            await query.edit_message_text(
                "❌ Pick-Daten nicht mehr verfügbar (Session abgelaufen)"
            )
            return

        st = ShadowTracker()
        trade_id = st.log_trade(
            source="telegram_bot",
            symbol=symbol,
            strategy=strategy,
            score=pick_data.get("score", 0),
            short_strike=pick_data.get("short_strike", 0),
            long_strike=pick_data.get("long_strike", 0),
            spread_width=pick_data.get("spread_width", 0),
            est_credit=pick_data.get("est_credit", 0),
            expiration=pick_data.get("expiration", ""),
            dte=pick_data.get("dte", 0),
            price_at_log=pick_data.get("current_price", 0),
            enhanced_score=pick_data.get("enhanced_score"),
            liquidity_tier=pick_data.get("liquidity_tier"),
            vix_at_log=pick_data.get("vix"),
            regime_at_log=pick_data.get("regime"),
            stability_at_log=pick_data.get("stability_score"),
        )

        msg = format_shadow_confirmation(symbol, trade_id or "?", strategy)
        await query.edit_message_text(msg, parse_mode="HTML")
        context.bot_data.pop(pick_key, None)

    except Exception as e:
        logger.error(f"shadow_log error for {symbol}: {e}")
        await query.edit_message_text(f"❌ Shadow-Log-Fehler: {e}")


async def _handle_skip(query, symbol):
    """Handle SKIP button."""
    msg = format_skip_confirmation(symbol)
    await query.edit_message_text(msg, parse_mode="HTML")


async def _handle_later(query, symbol, rank, context):
    """Handle SPÄTER button — schedule reminder via JobQueue."""
    cfg_path = Path(__file__).parent.parent.parent / "config" / "telegram.yaml"
    remind_minutes = 120
    try:
        import yaml

        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        remind_minutes = int(cfg.get("remind_delay_minutes", 120))
    except Exception:
        pass

    chat_id = _get_chat_id()

    async def remind_callback(ctx: ContextTypes.DEFAULT_TYPE):
        # Find pick data for this symbol/rank (strategy is not in the callback data)
        pick_data = None
        for key, val in list(ctx.bot_data.items()):
            if key.startswith(f"pick:{symbol}:") and key.endswith(f":{rank}"):
                pick_data = val
                break

        if pick_data:
            price = pick_data.get("current_price", 0)
            score = pick_data.get("score", 0)
            text = (
                f"⏰ <b>Erinnerung:</b> {symbol}\n"
                f"Kurs: ${price:.2f} | Score: {score:.1f}\n"
                "Bitte erneut prüfen."
            )
        else:
            text = f"⏰ <b>Erinnerung:</b> {symbol} — Pick-Daten abgelaufen"

        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

    context.job_queue.run_once(
        remind_callback,
        when=remind_minutes * 60,
        name=f"remind_{symbol}_{rank}",
        chat_id=chat_id,
    )

    msg = format_later_confirmation(symbol, remind_minutes)
    await query.edit_message_text(msg, parse_mode="HTML")


# === Application Setup ===


def create_application() -> Application:
    """Create and configure the Telegram bot application."""
    token = _get_token()
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("top15", cmd_top15))
    app.add_handler(CommandHandler("vix", cmd_vix))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("earnings", cmd_earnings))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CallbackQueryHandler(button_callback))

    return app


def main():
    """Entry point for the Telegram bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting OptionPlay Telegram Bot")

    app = create_application()

    from .scheduler import setup_scheduler
    setup_scheduler(app)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
