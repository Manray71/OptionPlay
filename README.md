[![CI](https://github.com/Manray71/OptionPlay/actions/workflows/ci.yml/badge.svg)](https://github.com/Manray71/OptionPlay/actions/workflows/ci.yml)

# OptionPlay

Quantitative options trading system specialized for bull-put credit spreads. Combines multi-strategy signal analysis, VIX-regime awareness, machine-learning-optimized scoring, and a Telegram bot for mobile interaction.

**Version:** 5.0.0 | **Modules:** 144 | **LOC:** ~63,260 | **Tests:** ~5,550

## Key Results

Walk-forward out-of-sample backtesting (2020-2025):

| Strategy | Win Rate | Trades |
|----------|----------|--------|
| Pullback | 88.3% | — |
| Support Bounce | 91.6% | — |
| **Overall** | **89.1%** | **4,112** |

*ATH Breakout, Earnings Dip, and Trend Continuation strategies were removed in v5.0.0.*

## Features

- **2 Active Trading Strategies** -- Pullback, Support Bounce
- **VIX-Regime Aware** -- Continuous interpolation (v2) across 7 anchor points (VIX 10-40); parameters scale smoothly rather than stepping through discrete tiers
- **ML-Optimized Scoring** -- Walk-forward training (18/6/6 months, 7 epochs, 2020-2025) with sector-specific factors and regime adjustments
- **Multi-Strategy Scanner** -- Scans watchlist, ranks by composite score, filters by stability tier and liquidity tier
- **Bearish Divergence Checks** -- 7 checks (price/RSI, price/OBV, price/MFI, CMF+MACD falling, momentum, distribution, CMF early warning) applied as score penalties
- **Earnings Surprise Modifier** -- Historical EPS surprise rate adjusts signal score at entry
- **Trade Recommendations** -- Automated strike selection, credit estimation, risk/reward analysis
- **MCP Server** -- 25 tools (+ 28 aliases) for Claude Desktop integration
- **Telegram Bot** -- 11 commands, 3 button callbacks, 3 scheduled daily scans
- **Portfolio Constraints** -- 2% max risk per trade, 50% max portfolio allocation, sector limits, VIX-scaled sizing
- **Shadow Tracker** -- Paper-trade log with P&L tracking

## Architecture

```
src/
├── analyzers/        # Pullback + Support Bounce strategy implementations
├── cache/            # Fundamentals, earnings, VIX, options pricing managers
├── config/           # YAML-based scoring weights and thresholds
├── constants/        # Trading rules, VIX regimes, enums
├── container.py      # Dependency injection (11 singletons)
├── data_providers/   # IBKR TWS bridge, Yahoo Finance
├── formatters/       # Pick, portfolio, output formatters
├── handlers/         # MCP request handlers (composition-based only)
├── ibkr/             # IBKR TWS bridge implementation
├── indicators/       # RSI, Bollinger, MACD, OBV, MFI, CMF, divergence checks
├── models/           # Data models and types
├── options/          # Greeks, pricing models
├── portfolio/        # Portfolio state management
├── risk/             # Position sizing (PositionSizerConfig.from_yaml()), constraints
├── scanner/          # Multi-strategy signal scanner
├── services/         # Scoring, ranking, earnings quality, VIX regime, sector RS
├── shadow_tracker.py # Paper-trade logging
├── state/            # Application state
├── telegram/         # Telegram bot (bot.py, notifier.py, scheduler.py)
└── utils/            # Validators, helpers, markdown builder
```

## Telegram Bot

The bot runs as a separate process alongside the MCP server.

**Commands:** `/start`, `/status`, `/scan`, `/top15`, `/vix`, `/open`, `/pnl`, `/sync`, `/earnings`, `/export`, `/help`

**Button callbacks:** SHADOW LOGGEN, SKIP, SPAETER

**Scheduled scans:** 10:00, 13:00, 15:30 ET (via APScheduler through `python-telegram-bot[job-queue]`)

```bash
# Start bot (foreground)
bash scripts/run_telegram_bot.sh

# macOS autostart via LaunchAgent
cp scripts/com.optionplay.telegram.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.optionplay.telegram.plist
```

Bot token and chat ID are set in `.env` only -- never in config files.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Core | NumPy, aiohttp, PyYAML, Pydantic 2.0 |
| Database | SQLite (~8.6 GB, 19.3M options records, 442k OHLCV bars) |
| Live Data | IBKR TWS (port 7497, sole live provider) |
| MCP | Model Context Protocol (mcp, fastmcp) |
| Telegram | python-telegram-bot[job-queue] >= 20.0 |
| Testing | pytest (~5,550 tests) |
| CI/CD | GitHub Actions (lint, type-check, security, test) |

## Getting Started

### Prerequisites

- Python 3.12
- IBKR TWS running on localhost:7497
- Telegram bot token (optional, for Telegram bot)

### Installation

```bash
git clone https://github.com/Manray71/OptionPlay.git
cd OptionPlay
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

### Usage

```bash
# Start MCP server (for Claude Desktop)
python -m src.mcp_main

# Start Telegram bot
bash scripts/run_telegram_bot.sh

# Run scanner directly
python -m src.scanner.multi_strategy_scanner

# Run tests
pytest --cov=src --cov-fail-under=70
```

### Data Pipeline

```bash
python scripts/populate_fundamentals.py       # Stability scores
python scripts/collect_earnings_eps.py        # EPS data
python scripts/calculate_derived_metrics.py   # IV Rank, HV, correlation
python scripts/daily_data_fetcher.py          # Daily VIX update
python scripts/classify_liquidity.py          # Options liquidity tier classification
python scripts/sync_daily_to_price_data.py    # Sync OHLCV to price_data table
```

## Configuration

All settings live in `config/` as YAML files:

- `trading.yaml` -- Trading rules, VIX profiles, roll strategy, regime v2, sector RS
- `scoring.yaml` -- Scoring weights, analyzer thresholds, enhanced scoring, RSI, validation
- `system.yaml` -- Settings, scanner config, liquidity blacklist
- `watchlists.yaml` -- Symbol universe (default_275, extended_600)
- `telegram.yaml` -- Scan schedule (times only; token/chat ID in `.env`)

## MCP Server (Claude Desktop)

25 registered tools plus 28 short-name aliases (53 endpoints total).

```json
{
  "mcpServers": {
    "optionplay": {
      "command": "python3",
      "args": ["-m", "src.mcp_main"],
      "cwd": "/path/to/OptionPlay"
    }
  }
}
```

See `SKILL.md` for the full tool reference.

## Handler Architecture

All MCP request handlers use composition (no mixins):

```python
server.handlers.scan.daily_picks()
server.handlers.vix.get_vix()
server.handlers.portfolio.get_positions()
```

`handler_container.py` wires all composed handlers. Mixin-based handlers were removed in v5.0.0.

## Related

- [OptionPlay-Web](https://github.com/Manray71/OptionPlay-Web) -- Web interface with dashboard, scanner UI, analysis pages, and PDF export

## License

[MIT](LICENSE)
