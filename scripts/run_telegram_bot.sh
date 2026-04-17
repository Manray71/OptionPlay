#!/bin/bash
# OptionPlay Telegram Bot Startup
# Usage: ./scripts/run_telegram_bot.sh

set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "Starting OptionPlay Telegram Bot..."
python -m src.telegram.bot
