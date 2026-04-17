"""Unit tests for src/telegram/scheduler.py.

Tests APScheduler/JobQueue integration WITHOUT live Telegram API.
All heavy dependencies (bot, server, JobQueue) are mocked.
"""

import importlib
import os
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Bootstrap real ptb before any src.telegram import
importlib.import_module("src.telegram")

import src.telegram.scheduler as scheduler_module
from src.telegram.scheduler import _load_telegram_config, scheduled_scan, setup_scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(chat_id: int = 123456, data: dict | None = None) -> MagicMock:
    job = MagicMock()
    job.chat_id = chat_id
    job.data = data or {}
    return job


def _make_context(chat_id: int = 123456) -> MagicMock:
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot_data = {}
    ctx.job = _make_job(chat_id=chat_id, data={"scan_type": "Morning Scan (16:00 DE)"})
    return ctx


def _make_app() -> MagicMock:
    app = MagicMock()
    app.job_queue = MagicMock()
    app.job_queue.run_daily = MagicMock()
    return app


# ---------------------------------------------------------------------------
# Test 1: Config-Datei ist lesbar und enthält die 3 Scan-Slots
# ---------------------------------------------------------------------------


def test_load_telegram_config_has_three_slots():
    cfg = _load_telegram_config()
    schedule = cfg.get("scan_schedule", {})
    assert len(schedule) == 3, f"Expected 3 scan slots, got {len(schedule)}: {list(schedule)}"
    assert "morning" in schedule
    assert "midday" in schedule
    assert "evening" in schedule


# ---------------------------------------------------------------------------
# Test 2: setup_scheduler registriert genau 3 Jobs
# ---------------------------------------------------------------------------


def test_setup_scheduler_adds_three_jobs(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
    app = _make_app()
    setup_scheduler(app)
    assert app.job_queue.run_daily.call_count == 3


# ---------------------------------------------------------------------------
# Test 3: Alle Jobs sind auf Mo-Fr begrenzt (days=(0,1,2,3,4))
# ---------------------------------------------------------------------------


def test_setup_scheduler_weekdays_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
    app = _make_app()
    setup_scheduler(app)
    for call in app.job_queue.run_daily.call_args_list:
        _, kwargs = call
        days = kwargs.get("days")
        assert days == (0, 1, 2, 3, 4), f"Expected Mon-Fri days, got {days}"


# ---------------------------------------------------------------------------
# Test 4: Korrekte Uhrzeiten 10:00, 13:00 und 15:30 ET
# ---------------------------------------------------------------------------


def test_setup_scheduler_correct_times(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
    app = _make_app()
    setup_scheduler(app)

    times_set = set()
    for call in app.job_queue.run_daily.call_args_list:
        _, kwargs = call
        t: dt_time = kwargs.get("time")
        times_set.add((t.hour, t.minute))

    assert (10, 0) in times_set, f"Missing 10:00 in {times_set}"
    assert (13, 0) in times_set, f"Missing 13:00 in {times_set}"
    assert (15, 30) in times_set, f"Missing 15:30 in {times_set}"


# ---------------------------------------------------------------------------
# Test 5: scheduled_scan delegiert an _run_scan_and_notify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_scan_calls_run_scan_and_notify():
    ctx = _make_context(chat_id=42)
    with patch("src.telegram.scheduler.scheduled_scan.__module__"), \
         patch("src.telegram.bot._run_scan_and_notify", new_callable=AsyncMock) as mock_run:
        # Import after patch so the lazy import inside scheduled_scan picks it up
        from src.telegram.bot import _run_scan_and_notify  # noqa: F401
        await scheduled_scan(ctx)
        mock_run.assert_awaited_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["chat_id"] == 42
        assert call_kwargs["bot"] is ctx.bot


# ---------------------------------------------------------------------------
# Test 6: scheduled_scan sendet Fehlermeldung wenn _run_scan_and_notify wirft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_scan_sends_error_on_exception():
    ctx = _make_context(chat_id=77)

    async def _boom(**kwargs):
        raise RuntimeError("backend exploded")

    with patch("src.telegram.bot._run_scan_and_notify", new_callable=AsyncMock, side_effect=_boom):
        await scheduled_scan(ctx)

    ctx.bot.send_message.assert_awaited_once()
    args, kwargs = ctx.bot.send_message.call_args
    assert kwargs["chat_id"] == 77
    assert "Fehlgeschlagen" in kwargs["text"] or "fehlgeschlagen" in kwargs["text"]


# ---------------------------------------------------------------------------
# Test 7: setup_scheduler warnt (kein Absturz) wenn JobQueue None ist
# ---------------------------------------------------------------------------


def test_setup_scheduler_no_crash_when_job_queue_none(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
    app = MagicMock()
    app.job_queue = None
    import logging
    with caplog.at_level(logging.ERROR, logger="src.telegram.scheduler"):
        setup_scheduler(app)  # must not raise
    assert "JobQueue not available" in caplog.text


# ---------------------------------------------------------------------------
# Test 8: setup_scheduler übergibt chat_id aus Umgebungsvariable an jeden Job
# ---------------------------------------------------------------------------


def test_setup_scheduler_passes_chat_id_to_jobs(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    app = _make_app()
    setup_scheduler(app)
    for call in app.job_queue.run_daily.call_args_list:
        _, kwargs = call
        assert kwargs.get("chat_id") == 555
