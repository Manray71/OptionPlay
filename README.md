[![CI](https://github.com/Manray71/OptionPlay/actions/workflows/ci.yml/badge.svg)](https://github.com/Manray71/OptionPlay/actions/workflows/ci.yml)

# OptionPlay

Quantitative options trading system specialized for bull-put credit spreads. Combines multi-strategy signal analysis, VIX-regime awareness, machine-learning-optimized scoring, and a comprehensive backtesting framework.

## Key Results

Walk-Forward out-of-sample backtesting (2020-2025):

| Strategy | Win Rate | Trades |
|----------|----------|--------|
| Pullback | 88.3% | — |
| Support Bounce | 91.6% | — |
| ATH Breakout | 88.9% | — |
| Earnings Dip | 86.7% | — |
| Trend Continuation | 87.7% | — |
| **Overall** | **89.1%** | **4,112** |

## Features

- **5 Trading Strategies** &mdash; Pullback, Support Bounce, ATH Breakout, Earnings Dip, Trend Continuation
- **VIX-Regime Aware** &mdash; Dynamic scoring adjustments for normal, elevated, high, and extreme volatility
- **ML-Optimized Scoring** &mdash; Walk-forward training (18/6/6 months, 7 epochs, 2020-2025) with sector-specific factors
- **Multi-Strategy Scanner** &mdash; Scans 267-symbol watchlist, ranks by composite score, filters by quality
- **Trade Recommendations** &mdash; Automated strike selection, credit estimation, risk/reward analysis
- **Backtesting Framework** &mdash; Walk-forward validation, ensemble methods, regime-aware simulation
- **MCP Server** &mdash; 53 tools for Claude Desktop integration
- **Portfolio Constraints** &mdash; Daily/weekly risk budgets, position sizing, sector limits

## Architecture

```
src/
├── analyzers/        # 5 strategy implementations
├── backtesting/      # Walk-forward training, simulation, validation
├── cache/            # Fundamentals, earnings, VIX, options pricing
├── config/           # YAML-based scoring weights and thresholds
├── data_providers/   # Market data API integrations
├── handlers/         # MCP server request handlers
├── indicators/       # Technical analysis (RSI, Bollinger, MACD, etc.)
├── options/          # Greeks, pricing models
├── risk/             # Position sizing, portfolio constraints
├── scanner/          # Multi-strategy signal scanner
├── services/         # Core scoring, ranking, recommendation engine
└── utils/            # Validators, formatters, helpers
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Core | NumPy, aiohttp, PyYAML, Pydantic 2.0 |
| Database | SQLite (19.3M options records, 442k OHLCV bars) |
| MCP | Model Context Protocol (mcp, fastmcp) |
| Testing | pytest (7,635 tests, 80%+ coverage) |
| CI/CD | GitHub Actions (lint, type-check, security, test) |

## Getting Started

### Prerequisites

- Python 3.11+
- Marketdata.app API key (for options data)

### Installation

```bash
git clone https://github.com/Manray71/OptionPlay.git
cd OptionPlay
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Usage

```bash
# Start MCP server (for Claude Desktop)
python -m src.mcp_main

# Run scanner
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
```

### ML Training

```bash
python scripts/full_walkforward_train.py      # Full walk-forward (~45 min)
python scripts/fast_weight_train.py           # Component weights
python scripts/fast_strategy_train.py         # Strategy scoring
```

## Configuration

All settings live in `config/` as YAML files:

- `scoring_weights.yaml` &mdash; ML-trained component weights and regime adjustments
- `analyzer_thresholds.yaml` &mdash; Strategy-specific score cutoffs
- `scanner_config.yaml` &mdash; Scanner parameters and filters
- `trading_rules.yaml` &mdash; Entry/exit criteria and position sizing
- `watchlists.yaml` &mdash; Symbol universe and blacklists
- `strategies.yaml` &mdash; Strategy definitions and parameters

## Related

- [OptionPlay-Web](https://github.com/Manray71/OptionPlay-Web) &mdash; Web interface with dashboard, scanner UI, analysis pages, and PDF export

## License

[MIT](LICENSE)
