"""APScheduler integration for OptionPlay Telegram Bot.

Schedules 3 daily scans that push results to Telegram.
Runs inside the bot process (no separate cron).

Schedule (config/telegram.yaml):
  Morning:  10:00 ET (16:00 DE)
  Midday:   13:00 ET (19:00 DE)
  Evening:  15:30 ET (21:30 DE)
"""

import logging
import os
from datetime import time as dt_time
from pathlib import Path

import pytz
import yaml

from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)


def _load_telegram_config() -> dict:
    cfg_path = Path(__file__).parent.parent.parent / "config" / "telegram.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a scan and push results to Telegram.

    Called by PTB JobQueue 3x daily (Mon-Fri). Delegates to
    _run_scan_and_notify so logic is not duplicated with cmd_scan.
    """
    chat_id = context.job.chat_id if context.job else 0
    if not chat_id:
        chat_id = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
    if not chat_id:
        logger.error("scheduled_scan: no chat_id available")
        return

    scan_type = (
        (context.job.data or {}).get("scan_type", "scheduled") if context.job else "scheduled"
    )
    logger.info("Starting scheduled scan: %s (chat_id=%s)", scan_type, chat_id)

    try:
        from .bot import _run_scan_and_notify

        await _run_scan_and_notify(
            bot=context.bot,
            chat_id=chat_id,
            bot_data=context.bot_data,
            scan_type=scan_type,
        )
    except Exception as e:
        logger.error("Scheduled scan error: %s", e, exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Scheduled Scan fehlgeschlagen:\n<code>{e}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


def setup_scheduler(app: Application) -> None:
    """Configure 3 daily scan jobs via python-telegram-bot's JobQueue.

    Uses app.job_queue.run_daily() (PTB v20+, backed by APScheduler)
    instead of raw APScheduler to stay within the PTB event loop.
    """
    job_queue = app.job_queue
    if job_queue is None:
        logger.error("JobQueue not available — install python-telegram-bot[job-queue]")
        return

    chat_id = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID not set — scheduled scans will have no target")

    cfg = _load_telegram_config()
    schedule = cfg.get("scan_schedule", {})

    for slot_name, slot_cfg in schedule.items():
        hour = slot_cfg.get("hour", 10)
        minute = slot_cfg.get("minute", 0)
        tz_name = slot_cfg.get("timezone", "America/New_York")
        description = slot_cfg.get("description", slot_name)

        tz = pytz.timezone(tz_name)
        run_time = dt_time(hour=hour, minute=minute, tzinfo=tz)

        job_queue.run_daily(
            callback=scheduled_scan,
            time=run_time,
            days=(0, 1, 2, 3, 4),  # Mon-Fri only
            name=f"scan_{slot_name}",
            chat_id=chat_id,
            data={"scan_type": description},
        )

        logger.info(
            "Scheduled: %s at %02d:%02d %s (Mon-Fri)",
            description,
            hour,
            minute,
            tz_name,
        )

    logger.info("Scheduler configured: %d daily jobs", len(schedule))
