#!/bin/bash
# OptionPlay Telegram Bot
# Usage: ./scripts/run_telegram_bot.sh
#
# Starts the bot with polling + 3 daily scheduled scans.
# Requires: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
#
# To run as background service:
#   nohup ./scripts/run_telegram_bot.sh >> ~/.optionplay/logs/telegram_bot.log 2>&1 &

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
source .venv/bin/activate

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Verify token exists
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN not set in .env"
    exit 1
fi

echo "Starting OptionPlay Telegram Bot ($(date))"
echo "Scans: Morning 10:00 ET, Midday 13:00 ET, Evening 15:30 ET"
python -m src.telegram.bot
