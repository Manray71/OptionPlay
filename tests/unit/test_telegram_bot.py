"""Unit tests for src/telegram/bot.py.

Tests command handlers and button callbacks WITHOUT a live Telegram API.
All heavy dependencies (OptionPlayServer, ShadowTracker, etc.) are mocked.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: ensure real python-telegram-bot is importable before bot import
# ---------------------------------------------------------------------------
# src/telegram/__init__.py does this at import time; importing it first is
# sufficient because it patches sys.modules["telegram"].
import importlib

# Import the bootstrap package so its __init__ runs
importlib.import_module("src.telegram")

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import src.telegram.bot as bot_module
from src.telegram.bot import (
    _get_chat_id,
    _get_token,
    _pick_to_cache_dict,
    _vix_to_regime_label,
    button_callback,
    cmd_help,
    cmd_start,
    create_application,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_update(text: str = "/start") -> MagicMock:
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.text = text
    return update


def _make_context(bot_data: dict | None = None) -> MagicMock:
    ctx = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    ctx.bot_data = bot_data if bot_data is not None else {}
    ctx.job_queue = MagicMock()
    ctx.job_queue.run_once = MagicMock()
    ctx.bot = AsyncMock()
    return ctx


def _make_callback_query(data: str) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    return query


# ---------------------------------------------------------------------------
# 1. cmd_start returns command list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_start_returns_command_list():
    update = _make_update("/start")
    ctx = _make_context()

    await cmd_start(update, ctx)

    update.message.reply_text.assert_awaited_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "/scan" in call_text
    assert "/vix" in call_text
    assert "/status" in call_text
    assert "HTML" in str(update.message.reply_text.call_args)


# ---------------------------------------------------------------------------
# 2. cmd_help is identical to cmd_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_help_same_as_start():
    u1, u2 = _make_update("/start"), _make_update("/help")
    c1, c2 = _make_context(), _make_context()

    await cmd_start(u1, c1)
    await cmd_help(u2, c2)

    text_start: str = u1.message.reply_text.call_args[0][0]
    text_help: str = u2.message.reply_text.call_args[0][0]
    assert text_start == text_help


# ---------------------------------------------------------------------------
# 3. _get_token raises without env var
# ---------------------------------------------------------------------------


def test_get_token_raises_without_env():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            _get_token()


# ---------------------------------------------------------------------------
# 4. _get_token returns value when set
# ---------------------------------------------------------------------------


def test_get_token_returns_value():
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc123"}):
        assert _get_token() == "abc123"


# ---------------------------------------------------------------------------
# 5. _get_chat_id raises without env var
# ---------------------------------------------------------------------------


def test_get_chat_id_raises_without_env():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
            _get_chat_id()


# ---------------------------------------------------------------------------
# 6. create_application registers all handlers
# ---------------------------------------------------------------------------


def test_create_application_registers_all_handlers():
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token-123:ABC"}):
        app = create_application()

    handler_names = set()
    for handler in app.handlers.get(0, []):
        if isinstance(handler, CommandHandler):
            handler_names.update(handler.commands)
        elif isinstance(handler, CallbackQueryHandler):
            handler_names.add("__callback__")

    expected_commands = {
        "start", "help", "status", "scan", "top15",
        "vix", "open", "pnl", "sync", "earnings", "export",
    }
    assert expected_commands <= handler_names
    assert "__callback__" in handler_names


# ---------------------------------------------------------------------------
# 7. button_callback — shadow log (pick data present)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_button_callback_shadow_log():
    query = _make_callback_query("shadow:AAPL:pullback:1")
    update = MagicMock(spec=Update)
    update.callback_query = query

    bot_data = {
        "pick:AAPL:pullback:1": {
            "score": 7.5,
            "current_price": 195.0,
            "stability_score": 80.0,
            "enhanced_score": 8.1,
            "liquidity_tier": 1,
            "vix": 18.5,
            "regime": "Normal",
            "short_strike": 190.0,
            "long_strike": 185.0,
            "spread_width": 5.0,
            "est_credit": 1.20,
            "expiration": "2026-05-16",
            "dte": 29,
        }
    }
    ctx = _make_context(bot_data)

    mock_tracker = MagicMock()
    mock_tracker.log_trade.return_value = "trade-uuid-001"

    with patch("src.shadow_tracker.ShadowTracker", return_value=mock_tracker):
        await button_callback(update, ctx)

    query.answer.assert_awaited_once()
    mock_tracker.log_trade.assert_called_once()
    call_kwargs = mock_tracker.log_trade.call_args[1]
    assert call_kwargs["symbol"] == "AAPL"
    assert call_kwargs["strategy"] == "pullback"
    assert call_kwargs["score"] == 7.5

    query.edit_message_text.assert_awaited_once()
    edit_text: str = query.edit_message_text.call_args[0][0]
    assert "trade-uuid-001" in edit_text

    # Pick removed from cache after logging
    assert "pick:AAPL:pullback:1" not in ctx.bot_data


# ---------------------------------------------------------------------------
# 8. button_callback — shadow log (pick data missing / expired)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_button_callback_shadow_log_missing_data():
    query = _make_callback_query("shadow:TSLA:bounce:2")
    update = MagicMock(spec=Update)
    update.callback_query = query
    ctx = _make_context({})  # empty bot_data — pick expired

    with patch("src.shadow_tracker.ShadowTracker"):
        await button_callback(update, ctx)

    query.edit_message_text.assert_awaited_once()
    msg: str = query.edit_message_text.call_args[0][0]
    assert "nicht mehr verfügbar" in msg or "abgelaufen" in msg


# ---------------------------------------------------------------------------
# 9. button_callback — skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_button_callback_skip():
    query = _make_callback_query("skip:MSFT:3")
    update = MagicMock(spec=Update)
    update.callback_query = query
    ctx = _make_context()

    await button_callback(update, ctx)

    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once()
    edit_text: str = query.edit_message_text.call_args[0][0]
    assert "MSFT" in edit_text


# ---------------------------------------------------------------------------
# 10. button_callback — later schedules job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_button_callback_later_schedules_job():
    query = _make_callback_query("later:NVDA:1")
    update = MagicMock(spec=Update)
    update.callback_query = query
    ctx = _make_context()

    with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "99999"}):
        # Patch yaml and builtins.open so config file is not required
        with patch("yaml.safe_load", return_value={"remind_delay_minutes": 30}):
            with patch("builtins.open", MagicMock()):
                await button_callback(update, ctx)

    query.answer.assert_awaited_once()
    ctx.job_queue.run_once.assert_called_once()
    call_kwargs = ctx.job_queue.run_once.call_args[1]
    assert call_kwargs["when"] == 30 * 60
    assert "NVDA" in call_kwargs["name"]


# ---------------------------------------------------------------------------
# 11. button_callback — unknown action (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_button_callback_unknown_action():
    query = _make_callback_query("bogus:FOO:1")
    update = MagicMock(spec=Update)
    update.callback_query = query
    ctx = _make_context()

    # Must not raise
    await button_callback(update, ctx)
    query.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# 12. _vix_to_regime_label boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vix,expected",
    [
        (None, "Unknown"),
        (12.0, "Low Vol"),
        (17.5, "Normal"),
        (22.0, "Elevated"),
        (27.0, "Danger Zone"),
        (35.0, "High Vol"),
    ],
)
def test_vix_to_regime_label(vix, expected):
    assert _vix_to_regime_label(vix) == expected


# ---------------------------------------------------------------------------
# 13. _pick_to_cache_dict extracts strikes
# ---------------------------------------------------------------------------


def test_pick_to_cache_dict_with_strikes():
    ss = MagicMock()
    ss.short_strike = 190.0
    ss.long_strike = 185.0
    ss.spread_width = 5.0
    ss.estimated_credit = 1.20
    ss.expiry = "2026-05-16"
    ss.dte = 29

    pick = MagicMock()
    pick.score = 7.5
    pick.current_price = 195.0
    pick.stability_score = 80.0
    pick.enhanced_score = 8.1
    pick.liquidity_tier = 1
    pick.suggested_strikes = ss

    d = _pick_to_cache_dict(pick, vix=18.5, regime="Normal")

    assert d["short_strike"] == 190.0
    assert d["long_strike"] == 185.0
    assert d["est_credit"] == 1.20
    assert d["expiration"] == "2026-05-16"
    assert d["vix"] == 18.5
    assert d["regime"] == "Normal"


def test_pick_to_cache_dict_without_strikes():
    pick = MagicMock()
    pick.score = 5.0
    pick.current_price = 100.0
    pick.stability_score = 70.0
    pick.enhanced_score = None
    pick.liquidity_tier = None
    pick.suggested_strikes = None

    d = _pick_to_cache_dict(pick, vix=None, regime=None)

    assert d["short_strike"] == 0.0
    assert d["expiration"] == ""
