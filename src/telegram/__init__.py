"""OptionPlay Telegram Bot.

Push-based scanner notifications with inline buttons for shadow-trade logging.

Components:
  - notifier: DailyPick -> Telegram message formatting
  - bot: Application setup, command handlers, callback handlers
  - scheduler: APScheduler integration, 3 daily scan jobs

Configuration: config/telegram.yaml + .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
"""
