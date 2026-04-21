# C.4 Smoke Test Results — 2026-04-17

## Bot Startup

```
INFO: Starting OptionPlay Telegram Bot
INFO: Scheduled: Morning Scan (16:00 DE) at 10:00 America/New_York (Mon-Fri)
INFO: Scheduled: Midday Scan (19:00 DE) at 13:00 America/New_York (Mon-Fri)
INFO: Scheduled: Evening Check (21:30 DE) at 15:30 America/New_York (Mon-Fri)
INFO: Scheduler configured: 3 daily jobs
INFO: Added job "scan_morning" to job store "default"
INFO: Added job "scan_midday" to job store "default"
INFO: Added job "scan_evening" to job store "default"
INFO: Scheduler started
INFO: Application started
```

Bot connects to Telegram API, all 3 APScheduler jobs registered and added to job store.

## Command Handlers (programmatic, all mocked)

| Command   | Status | Notes |
|-----------|--------|-------|
| /start    | ✅ OK | Sends HTML welcome + command list |
| /help     | ✅ OK | Delegates to cmd_start |
| /vix      | ✅ OK | VIX 18.5, regime params formatted |
| /status   | ✅ OK | VIX + open positions + shadow stats |
| /open     | ✅ OK | "Keine offenen Shadow-Positionen" (empty) |
| /pnl      | ✅ OK | 0 trades, 0% WR, $0.00 P&L |
| /scan     | ✅ OK | "Scan läuft..." + no-picks message (bot.send_message path) |
| /sync     | ✅ OK | Calls portfolio_positions, relays result |
| /earnings | ✅ OK | Queries trades.db earnings_history |
| /export   | ✅ OK | "Keine Shadow-Trades" (empty) |
| /top15    | ✅ OK | Calls scan_multi_strategy, sends result |

## Key Verification Points

**Scheduler jobs**: All 3 appear in APScheduler log before `Application started`.
APScheduler log line `Added job "scan_X"` confirms PTB JobQueue wired correctly.

**_run_scan_and_notify**: Used by both `/scan` (cmd_scan) and `scheduled_scan`.
No code duplication — verified via handler test (scan sends via `bot.send_message`,
not `update.message.reply_text`).

**Button callbacks**: SHADOW LOGGEN / SKIP / SPÄTER paths tested in
`test_telegram_bot.py` (existing 42 tests, all green).

## Test Suite

```
5671 passed, 29 skipped, 0 failures
(includes 8 new tests in test_telegram_scheduler.py)
```

## Known Limitations

- Live interactive Telegram test (actual button presses) not performed in this session.
  The bot was started against the real API and connected successfully (getMe + deleteWebhook
  HTTP 200), but no manual commands were sent via Telegram client.
- `/sync` depends on IBKR TWS connection (localhost:7497); will return error if TWS not running.
