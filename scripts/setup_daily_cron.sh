#!/bin/bash
#
# OptionPlay - Daily Data Fetcher Cronjob Setup
# ==============================================
#
# Sets up a cronjob to run the daily data fetcher after market close.
#
# Usage:
#     ./scripts/setup_daily_cron.sh          # Install cronjob
#     ./scripts/setup_daily_cron.sh --remove  # Remove cronjob
#     ./scripts/setup_daily_cron.sh --status  # Show current status
#
# Schedule:
#     - Runs at 18:00 ET (Eastern Time)
#     - Only on weekdays (Mon-Fri)
#     - Converts to UTC automatically (23:00 UTC in winter, 22:00 in summer)
#
# Note: macOS may require granting "Full Disk Access" to cron in
#       System Preferences > Security & Privacy > Privacy
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
FETCHER_SCRIPT="$SCRIPT_DIR/daily_data_fetcher.py"

# Python path (use the one from the virtual environment if available)
if [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif [ -f "$PROJECT_ROOT/venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/venv/bin/python"
else
    PYTHON="python3"
fi

# Log directory
LOG_DIR="$HOME/.optionplay/logs"
LOG_FILE="$LOG_DIR/daily_fetcher.log"

# Cron command
# Note: Using TZ=America/New_York for proper ET timezone handling
CRON_CMD="TZ=America/New_York 0 18 * * 1-5 cd $PROJECT_ROOT && $PYTHON $FETCHER_SCRIPT >> $LOG_FILE 2>&1"

# Identifier for our cron job
CRON_MARKER="# OptionPlay Daily Data Fetcher"

show_help() {
    echo "OptionPlay - Daily Data Fetcher Cronjob Setup"
    echo ""
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  (no option)   Install the cronjob"
    echo "  --remove      Remove the cronjob"
    echo "  --status      Show current status"
    echo "  --help        Show this help"
    echo ""
    echo "Schedule: Weekdays at 18:00 ET (after market close)"
}

show_status() {
    echo -e "${GREEN}OptionPlay Daily Data Fetcher - Status${NC}"
    echo "========================================"
    echo ""

    # Check if cron job exists
    if crontab -l 2>/dev/null | grep -q "daily_data_fetcher"; then
        echo -e "Cronjob: ${GREEN}INSTALLED${NC}"
        echo ""
        echo "Current cron entry:"
        crontab -l 2>/dev/null | grep -A1 "OptionPlay"
    else
        echo -e "Cronjob: ${YELLOW}NOT INSTALLED${NC}"
    fi

    echo ""

    # Check log file
    if [ -f "$LOG_FILE" ]; then
        echo -e "Log file: ${GREEN}EXISTS${NC} ($LOG_FILE)"
        echo ""
        echo "Last 5 log entries:"
        tail -5 "$LOG_FILE" 2>/dev/null || echo "(empty)"
    else
        echo -e "Log file: ${YELLOW}NOT CREATED YET${NC}"
    fi

    echo ""

    # Check database
    DB_PATH="$HOME/.optionplay/trades.db"
    if [ -f "$DB_PATH" ]; then
        echo -e "Database: ${GREEN}EXISTS${NC}"
        # Get last VIX date
        LAST_VIX=$(sqlite3 "$DB_PATH" "SELECT MAX(date) FROM vix_data" 2>/dev/null || echo "unknown")
        echo "Last VIX date: $LAST_VIX"
    else
        echo -e "Database: ${RED}NOT FOUND${NC}"
    fi
}

install_cron() {
    echo -e "${GREEN}Installing OptionPlay Daily Data Fetcher Cronjob${NC}"
    echo "================================================="
    echo ""

    # Check if script exists
    if [ ! -f "$FETCHER_SCRIPT" ]; then
        echo -e "${RED}Error: Fetcher script not found at $FETCHER_SCRIPT${NC}"
        exit 1
    fi

    # Create log directory
    mkdir -p "$LOG_DIR"
    echo "Log directory: $LOG_DIR"

    # Check if already installed
    if crontab -l 2>/dev/null | grep -q "daily_data_fetcher"; then
        echo -e "${YELLOW}Cronjob already installed. Updating...${NC}"
        # Remove existing entry
        crontab -l 2>/dev/null | grep -v "daily_data_fetcher" | grep -v "OptionPlay Daily" | crontab -
    fi

    # Add new cron job
    (crontab -l 2>/dev/null || true; echo "$CRON_MARKER"; echo "$CRON_CMD") | crontab -

    echo ""
    echo -e "${GREEN}Cronjob installed successfully!${NC}"
    echo ""
    echo "Schedule: Weekdays (Mon-Fri) at 18:00 ET"
    echo "Log file: $LOG_FILE"
    echo ""
    echo "To test manually:"
    echo "  $PYTHON $FETCHER_SCRIPT --status"
    echo ""
    echo "To view logs:"
    echo "  tail -f $LOG_FILE"
}

remove_cron() {
    echo -e "${YELLOW}Removing OptionPlay Daily Data Fetcher Cronjob${NC}"
    echo "==============================================="
    echo ""

    if crontab -l 2>/dev/null | grep -q "daily_data_fetcher"; then
        crontab -l 2>/dev/null | grep -v "daily_data_fetcher" | grep -v "OptionPlay Daily" | crontab -
        echo -e "${GREEN}Cronjob removed successfully.${NC}"
    else
        echo "No cronjob found."
    fi
}

# Main
case "${1:-}" in
    --help|-h)
        show_help
        ;;
    --status|-s)
        show_status
        ;;
    --remove|-r)
        remove_cron
        ;;
    "")
        install_cron
        ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
