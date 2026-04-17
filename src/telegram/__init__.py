"""OptionPlay Telegram Bot.

Push-based scanner notifications with inline buttons for shadow-trade logging.

Components:
  - notifier: DailyPick -> Telegram message formatting
  - bot: Application setup, command handlers, callback handlers
  - scheduler: APScheduler integration, 3 daily scan jobs

Configuration: config/telegram.yaml + .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
"""

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

__all__ = [
    "format_pick_message",
    "format_pick_buttons",
    "format_scan_summary",
    "format_no_picks_message",
    "format_shadow_confirmation",
    "format_skip_confirmation",
    "format_later_confirmation",
    "format_status_message",
    "format_vix_message",
]
