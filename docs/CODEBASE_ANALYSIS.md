# OptionPlay Codebase Analysis Report

**Generated:** 2026-02-05
**Version:** 4.0.0
**Total Files Analyzed:** 335 Python files

---

## Table of Contents

1. [File Inventory by Language and Size](#1-file-inventory-by-language-and-size)
2. [Function Definitions Summary](#2-function-definitions-summary)
3. [Dependency Graph](#3-dependency-graph)
4. [Hotspot Functions](#4-hotspot-functions)
5. [Orphan Functions](#5-orphan-functions)
6. [Prioritized Documentation List](#6-prioritized-functions-to-document-first)
7. [Summary Statistics](#7-summary-statistics)
8. [Recommendations](#8-recommendations)

---

## 1. File Inventory by Language and Size

### Python Files (335 files, ~45 MB total)

| Directory | Files | Size | Purpose |
|-----------|-------|------|---------|
| **src/** | 152 | 13 MB | Main application code |
| **tests/** | 140+ | 31 MB | Test suite (2:1 test-to-code ratio) |
| **scripts/** | 50 | 1.4 MB | Data collection, backtesting utilities |
| **config/** | 8 | 19 MB | Settings + training data backups |

### Top 20 Largest Source Files

| Rank | File | Size | Lines (est.) |
|------|------|------|--------------|
| 1 | `src/scanner/multi_strategy_scanner.py` | 67K | ~2,000 |
| 2 | `src/config/config_loader.py` | 61K | ~1,800 |
| 3 | `src/backtesting/real_options_backtester.py` | 59K | ~1,900 |
| 4 | `src/backtesting/trade_tracker.py` | 58K | ~1,800 |
| 5 | `src/backtesting/ensemble_selector.py` | 56K | ~1,700 |
| 6 | `src/ibkr_bridge.py` | 55K | ~1,600 |
| 7 | `src/analyzers/pullback.py` | 51K | ~1,500 |
| 8 | `src/backtesting/regime_trainer.py` | 50K | ~1,500 |
| 9 | `src/strike_recommender.py` | 47K | ~1,400 |
| 10 | `src/backtesting/engine.py` | 46K | ~1,400 |
| 11 | `src/indicators/support_resistance.py` | 46K | ~1,400 |
| 12 | `src/pricing/black_scholes.py` | 41K | ~1,300 |
| 13 | `src/services/recommendation_engine.py` | 39K | ~1,200 |
| 14 | `src/backtesting/walk_forward.py` | 39K | ~1,200 |
| 15 | `src/mcp_tool_registry.py` | 37K | ~1,100 |
| 16 | `src/data_providers/tradier.py` | 37K | ~1,100 |
| 17 | `src/backtesting/signal_validation.py` | 36K | ~1,100 |
| 18 | `src/backtesting/ml_weight_optimizer.py` | 36K | ~1,100 |
| 19 | `src/handlers/scan.py` | 35K | ~1,000 |
| 20 | `src/visualization/sr_chart.py` | 34K | ~1,000 |

### Configuration & Documentation Files

| Type | Files | Size |
|------|-------|------|
| YAML (.yaml) | 8 | ~75K |
| JSON (.json) | 3 | ~18 MB |
| Markdown (.md) | 40+ | ~524K |
| TOML (.toml) | 1 | 3.3K |

### Module Size Distribution

```
src/backtesting/     500+ KB (16 files) - Largest module
src/scanner/         ~90K   (4 files)
src/handlers/        ~150K  (14 files)
src/services/        ~200K  (16 files)
src/analyzers/       ~200K  (10 files)
src/cache/           ~170K  (10 files)
src/indicators/      ~145K  (9 files)
src/utils/           ~140K  (14 files)
src/data_providers/  ~120K  (7 files)
src/models/          ~70K   (9 files)
src/config/          ~85K   (5 files)
src/formatters/      ~67K   (4 files)
src/pricing/         ~43K   (2 files)
src/options/         ~36K   (3 files)
```

---

## 2. Function Definitions Summary

**Total Functions Extracted: 600+**

### Functions by Module

| Module | Function Count | Key Classes |
|--------|----------------|-------------|
| `analyzers/` | 148 | PullbackAnalyzer, BounceAnalyzer, AthBreakoutAnalyzer, EarningsDipAnalyzer |
| `services/` | 139 | RecommendationEngine, TradeValidator, VixService, PositionMonitor |
| `backtesting/` | 100+ | BacktestEngine, TradeTracker, RegimeTrainer, EnsembleSelector |
| `cache/` | 98 | CacheManager, EarningsCache, SymbolFundamentals, VixCache |
| `handlers/` | 95 | VixHandler, ScanHandler, QuoteHandler, AnalysisHandler |
| `scanner/` | 60+ | MultiStrategyScanner, SignalAggregator, MultiStrategyRanker |
| `indicators/` | 69 | Support/Resistance, Gap Analysis, Momentum, Volatility |
| `utils/` | 57 | CircuitBreaker, RateLimiter, MarkdownBuilder, Validation |

### Key Class Hierarchies

#### Analyzers
```
BaseAnalyzer (abstract)
├── PullbackAnalyzer
├── BounceAnalyzer
├── AthBreakoutAnalyzer
└── EarningsDipAnalyzer
    └── Uses: FeatureScoringMixin
```

#### Handlers (Mixin Pattern)
```
OptionPlayServer
├── VixHandlerMixin
├── ScanHandlerMixin
├── QuoteHandlerMixin
├── PortfolioHandlerMixin
├── AnalysisHandlerMixin
├── ReportHandlerMixin
├── RiskHandlerMixin
├── IbkrHandlerMixin
├── ValidateHandlerMixin
├── MonitorHandlerMixin
└── BaseHandlerMixin
```

#### Services
```
BaseService
├── VixService
├── QuoteService
├── OptionsService
├── ScannerService
└── (Others use composition)
```

---

## 3. Dependency Graph

### Visual Architecture

```
                              ┌─────────────────────────────────────┐
                              │          MCP LAYER                  │
                              │    mcp_server.py (Entry Point)      │
                              │    mcp_tool_registry.py             │
                              └────────────────┬────────────────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
                    ▼                          ▼                          ▼
         ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
         │   HANDLERS       │      │    SERVICES      │      │   FORMATTERS     │
         │   (14 files)     │      │   (16 files)     │      │   (4 files)      │
         ├──────────────────┤      ├──────────────────┤      ├──────────────────┤
         │ base.py (HUB)    │◄────►│ server_core.py   │      │ output_formatters│
         │ vix.py           │      │ vix_service.py   │      │ pdf_report_gen   │
         │ scan.py          │      │ quote_service.py │      │ portfolio_fmt    │
         │ quote.py         │      │ options_service  │      └────────┬─────────┘
         │ analysis.py      │      │ scanner_service  │               │
         │ portfolio.py     │      │ trade_validator  │               │
         │ monitor.py       │      │ recommendation   │               │
         │ risk.py          │      │   _engine        │               │
         │ report.py        │      │ position_monitor │               │
         │ validate.py      │      │ portfolio_constr │               │
         │ ibkr.py          │      └────────┬─────────┘               │
         └────────┬─────────┘               │                         │
                  │                         │                         │
                  └─────────────┬───────────┴─────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    ANALYZERS     │  │    SCANNER       │  │  DATA PROVIDERS  │
│    (10 files)    │  │   (4 files)      │  │   (7 files)      │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│ base.py (HUB)    │  │ multi_strategy   │  │ interface.py     │
│ context.py (HUB) │  │   _scanner.py    │  │ tradier.py       │
│ pullback.py      │  │ signal_aggreg    │  │ marketdata.py    │
│ bounce.py        │  │ multi_strat_rank │  │ local_db.py      │
│ ath_breakout.py  │  │ market_scanner   │  │ fundamentals.py  │
│ earnings_dip.py  │  └────────┬─────────┘  │ yahoo_news.py    │
│ pool.py          │           │            └────────┬─────────┘
│ score_normal.py  │           │                     │
│ feature_scoring  │           │                     │
└────────┬─────────┘           │                     │
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│     CACHE        │  │   INDICATORS     │  │   BACKTESTING    │
│   (10 files)     │  │   (9 files)      │  │   (16 files)     │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│ cache_manager.py │  │ support_resist   │  │ engine.py        │
│ vix_cache.py     │  │ gap_analysis.py  │  │ trade_tracker    │
│ historical_cache │  │ momentum.py      │  │ regime_trainer   │
│ symbol_fundament │  │ volatility.py    │  │ regime_model     │
│ earnings_history │  │ trend.py         │  │ walk_forward     │
│ earnings_cache   │  │ volume_profile   │  │ signal_valid     │
│ iv_cache_impl    │  │ events.py        │  │ ml_weight_opt    │
└────────┬─────────┘  │ optimized.py     │  │ ensemble_select  │
         │            └────────┬─────────┘  │ reliability      │
         │                     │            │ options_sim      │
         │                     │            └────────┬─────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    UTILITIES     │  │    MODELS        │  │    CONFIG        │
│   (14 files)     │  │   (9 files)      │  │   (5 files)      │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│ error_handler    │  │ base.py          │  │ config_loader    │
│   (9 imports)    │  │ result.py (HUB)  │  │ watchlist_loader │
│ markdown_builder │  │ candidates.py    │  │ fundamentals_    │
│   (8 imports)    │  │ strategy.py      │  │   constants      │
│ validation.py    │  │ options.py       │  │ liquidity_       │
│   (6 imports)    │  │ indicators.py    │  │   blacklist      │
│ circuit_breaker  │  │ market_data.py   │  └──────────────────┘
│ rate_limiter     │  └──────────────────┘
│ provider_orch    │
│ struct_logging   │
│ secure_config    │
│ metrics.py       │
│ earnings_aggreg  │
└──────────────────┘

LEGEND:
  ────► = imports/depends on
  (HUB) = High-import-count module (6+ importers)
```

### Import Dependency Statistics

| Hub Module | Imported By | Description |
|------------|-------------|-------------|
| `handlers/base.py` | 11 files | Base mixin for all handlers |
| `utils/error_handler.py` | 9 files | `mcp_endpoint`, `sync_endpoint` decorators |
| `utils/markdown_builder.py` | 8+ files | Output formatting |
| `analyzers/base.py` | 6 files | Base analyzer interface |
| `utils/validation.py` | 6 files | Input validation utilities |
| `models/result.py` | 5 files | Service result wrappers |
| `analyzers/context.py` | 5 files | Analysis context dataclass |

### Layer Dependencies (Good Practices Observed)

- Handlers → Services (correct)
- Services → Cache (correct)
- Utils used everywhere (acceptable cross-cutting concern)
- Config centralized (correct)
- No circular dependencies detected

---

## 4. Hotspot Functions

### Tier 1: Critical Hotspots (100+ calls)

| Function/Pattern | Call Count | Primary Files |
|------------------|------------|---------------|
| `logger.*()` | 645 | All modules (structured logging) |
| `await` keyword | 478 | All async modules |
| `format_*()` methods | 184 | handlers/, formatters/ |
| `cursor.execute()` | 127 | trade_tracker.py (50), backtesting/ |
| `.to_dict()` | 109 | models/, handlers/ |

### Tier 2: High-Priority Functions (20-50 calls)

| Function | Calls | Files Using It |
|----------|-------|----------------|
| `get_portfolio_manager()` | 13 | handlers/portfolio.py, monitor.py, analysis.py |
| `sync_endpoint()` | 13 | All 13 handler files |
| `get_fundamentals_manager()` | 9 | scanner, trade_validator, cache |
| `get_config()` | 11 | mcp_server, container, analyzers, services |
| `get_earnings_fetcher()` | 14 | handlers/quote, report, analysis, scan |
| `asyncio.to_thread()` | 19 | All async SQLite wrappers |

### Tier 3: Core Business Logic (5-20 calls)

| Function | Calls | Purpose |
|----------|-------|---------|
| `.analyze()` | 16 | Strategy analysis entry point |
| `.score()` | 7 | Signal scoring |
| `.fetch()` | 6 | Data retrieval |
| `normalize_score()` | 6 | Score standardization |
| `.validate()` | 5 | Input validation |

### Database Hotspots (Optimization Candidates)

| File | `execute()` Calls | Notes |
|------|-------------------|-------|
| `backtesting/trade_tracker.py` | 50 | Heavy DB operations |
| `backtesting/real_options_backtester.py` | 20 | Batch operations |
| `cache/symbol_fundamentals.py` | 22 | Fundamentals queries |

---

## 5. Orphan Functions

**Total Orphan Functions Identified: 349**

### By Category

| Category | Count | Action Recommended |
|----------|-------|-------------------|
| **True Orphans** (likely dead code) | ~50 | Safe to remove |
| **API Exports** (intended for external use) | ~100 | Document as public API |
| **Singleton Factories** (dynamically called) | ~87 | Mark as factory pattern |
| **MCP Tool Handlers** (registered dynamically) | ~13 | False positive |
| **Test/Debug Utilities** | ~30 | Consider removing or documenting |
| **Future Features** (partially implemented) | ~70 | Document or remove |

### Top Orphan Concentrations

| Module | Orphan Count | Examples |
|--------|--------------|----------|
| `indicators/` | 69 | `calculate_rsi()`, `calculate_macd()`, `find_support_levels()` |
| `utils/` | 57 | `format_price()`, `validate_symbol()`, `get_logger()` |
| `backtesting/` | 49 | `calculate_metrics()`, `format_trade_stats()`, `quick_backtest()` |
| `cache/` | 28 | `get_cache_manager()`, `get_earnings_cache()`, `reset_*()` |
| `pricing/` | 23 | `black_scholes_call()`, `implied_volatility()`, `create_pricer()` |
| `data_providers/` | 20 | `get_analyst_data()`, `get_fundamentals()`, `parse_occ_symbol()` |
| `services/` | 20 | `get_trade_validator()`, `get_position_monitor()`, `create_*()` |

### Singleton Factory Functions (87 total)

These follow the pattern `get_*()` and `reset_*()` for dependency injection:

```python
# Cache layer
get_cache_manager()          reset_cache_manager()
get_fundamentals_manager()   reset_fundamentals_manager()
get_earnings_cache()         reset_earnings_cache()
get_earnings_history_manager() reset_earnings_history_manager()
get_vix_manager()            reset_vix_manager()
get_historical_cache()       reset_historical_cache()
get_iv_cache()               reset_iv_cache()

# Services layer
get_trade_validator()        reset_trade_validator()
get_constraint_checker()     reset_constraint_checker()
get_position_monitor()       reset_position_monitor()
get_entry_scorer()           reset_entry_scorer()
get_iv_analyzer()            reset_iv_analyzer()

# Config layer
get_config()                 reset_config()
get_watchlist_loader()       reset_watchlist_loader()
get_container()              reset_container()

# Utils layer
get_circuit_breaker()        reset_circuit_breakers()
get_orchestrator()
get_limiter()
get_logger()
get_secure_config()          reset_secure_config()
```

### Orphan Functions by File (Selected)

<details>
<summary><strong>indicators/ (69 orphans)</strong></summary>

```
src/indicators/momentum.py:14 - calculate_rsi()
src/indicators/momentum.py:46 - calculate_macd()
src/indicators/momentum.py:112 - calculate_rsi_series()
src/indicators/momentum.py:148 - find_swing_lows()
src/indicators/momentum.py:186 - find_swing_highs()
src/indicators/momentum.py:224 - calculate_rsi_divergence()
src/indicators/momentum.py:433 - calculate_stochastic()
src/indicators/trend.py:9 - calculate_sma()
src/indicators/trend.py:25 - calculate_ema()
src/indicators/trend.py:49 - calculate_adx()
src/indicators/trend.py:130 - get_trend_direction()
src/indicators/volatility.py:14 - calculate_atr()
src/indicators/volatility.py:63 - calculate_bollinger_bands()
src/indicators/volatility.py:145 - calculate_keltner_channel()
src/indicators/volatility.py:231 - is_volatility_squeeze()
src/indicators/support_resistance.py:444 - find_support_levels()
src/indicators/support_resistance.py:480 - find_resistance_levels()
src/indicators/support_resistance.py:686 - analyze_support_resistance()
src/indicators/support_resistance.py:885 - calculate_fibonacci()
src/indicators/gap_analysis.py:52 - detect_gap()
src/indicators/gap_analysis.py:132 - analyze_gap()
src/indicators/volume_profile.py:37 - calculate_vwap()
src/indicators/volume_profile.py:177 - calculate_spy_trend()
src/indicators/optimized.py:71 - calc_rsi_numpy()
src/indicators/optimized.py:260 - calc_macd_numpy()
```

</details>

<details>
<summary><strong>backtesting/ (49 orphans)</strong></summary>

```
src/backtesting/metrics.py:193 - calculate_metrics()
src/backtesting/metrics.py:341 - calculate_sharpe_ratio()
src/backtesting/metrics.py:416 - calculate_sortino_ratio()
src/backtesting/metrics.py:485 - calculate_max_drawdown()
src/backtesting/metrics.py:531 - calculate_profit_factor()
src/backtesting/metrics.py:549 - calculate_kelly_criterion()
src/backtesting/options_simulator.py:508 - quick_spread_pnl()
src/backtesting/options_simulator.py:616 - batch_calculate_pnl()
src/backtesting/real_options_backtester.py:952 - quick_backtest()
src/backtesting/real_options_backtester.py:1152 - save_outcomes_to_db()
src/backtesting/real_options_backtester.py:1276 - load_outcomes_for_training()
src/backtesting/regime_config.py:364 - create_percentile_regimes()
src/backtesting/regime_config.py:451 - get_regime_for_vix()
src/backtesting/regime_model.py:665 - get_regime_recommendation()
src/backtesting/signal_validation.py:1040 - format_reliability_report()
src/backtesting/trade_tracker.py:1781 - format_trade_stats()
src/backtesting/walk_forward.py:1129 - format_training_summary()
```

</details>

<details>
<summary><strong>pricing/ (23 orphans)</strong></summary>

```
src/pricing/black_scholes.py:187 - black_scholes_call_np()
src/pricing/black_scholes.py:233 - black_scholes_put_np()
src/pricing/black_scholes.py:279 - black_scholes_call()
src/pricing/black_scholes.py:290 - black_scholes_put()
src/pricing/black_scholes.py:301 - black_scholes_price()
src/pricing/black_scholes.py:343 - black_scholes_greeks()
src/pricing/black_scholes.py:422 - implied_volatility()
src/pricing/black_scholes.py:490 - find_strike_for_delta()
src/pricing/black_scholes.py:886 - create_pricer()
src/pricing/black_scholes.py:1212 - quick_put_price()
src/pricing/black_scholes.py:1236 - quick_spread_credit()
src/pricing/black_scholes.py:1299 - batch_spread_pnl()
```

</details>

---

## 6. Prioritized Functions to Document First

### Priority 1: Critical Infrastructure (Document Immediately)

| Function | File:Line | Reason |
|----------|-----------|--------|
| `sync_endpoint()` | utils/error_handler.py:381 | Decorator on all 13 handlers |
| `mcp_endpoint()` | utils/error_handler.py:330 | Async error handling decorator |
| `get_config()` | config/config_loader.py:1423 | Central configuration access |
| `get_fundamentals_manager()` | cache/symbol_fundamentals.py:958 | Stability/win-rate data |
| `get_portfolio_manager()` | portfolio/manager.py:788 | Position tracking |

### Priority 2: Core Business Logic

| Function | File:Line | Reason |
|----------|-----------|--------|
| `analyze()` | analyzers/pullback.py:~200 | Main strategy analysis |
| `scan_async()` | scanner/multi_strategy_scanner.py:~1400 | Core scanning engine |
| `get_daily_picks()` | services/recommendation_engine.py:~400 | Trading recommendations |
| `validate()` | services/trade_validator.py:~300 | Trade validation logic |
| `get_vix()` | handlers/vix.py:~100 | VIX data retrieval |

### Priority 3: Data Access Layer

| Function | File:Line | Reason |
|----------|-----------|--------|
| `execute()` patterns | backtesting/trade_tracker.py | 50 calls, DB operations |
| `_fetch_historical_cached()` | handlers/base.py:~50 | Price data caching |
| `_get_quote_cached()` | handlers/base.py:~80 | Quote data caching |
| `_fetch_vix_yahoo()` | handlers/vix.py:~150 | External API call |

### Priority 4: Output Formatting

| Function | File:Line | Reason |
|----------|-----------|--------|
| `format_picks_markdown()` | services/recommendation_engine.py:~900 | Daily picks output |
| `MarkdownBuilder.build()` | utils/markdown_builder.py:~400 | All markdown output |
| `_format_single_pick_v2()` | handlers/scan.py:~800 | Pick formatting |

### Priority 5: Analyzer Internals

| Function Pattern | Files | Reason |
|------------------|-------|--------|
| `_score_*()` methods | All analyzers | Scoring components (30+ methods) |
| `_calculate_*()` methods | All analyzers | Indicator calculations (20+ methods) |
| `apply_trained_weights()` | analyzers/feature_scoring_mixin.py | ML weight application |

---

## 7. Summary Statistics

| Metric | Value |
|--------|-------|
| Total Python Files | 335 |
| Source Files (src/) | 152 |
| Test Files (tests/) | 140+ |
| Script Files (scripts/) | 50 |
| Total Lines of Code (src/) | ~40,000 |
| Test Lines of Code | ~80,000 |
| Total Functions | 600+ |
| Hub Modules (6+ imports) | 7 |
| Hotspot Functions (10+ calls) | 15 |
| Orphan Functions | 349 |
| Singleton Factories | 87 |
| Test-to-Code Ratio | 2:1 |
| Architecture Quality Score | 8/10 |

### Code Distribution by Layer

```
Backtesting    ████████████████████  500K (largest)
Services       ████████████          200K
Analyzers      ████████████          200K
Cache          ██████████            170K
Handlers       █████████             150K
Indicators     █████████             145K
Utils          █████████             140K
Data Providers ███████               120K
Config         █████                 85K
Models         ████                  70K
Formatters     ████                  67K
Pricing        ███                   43K
Options        ██                    36K
```

---

## 8. Recommendations

### Immediate Actions

1. **Document Critical Infrastructure**
   - Add docstrings to `sync_endpoint()`, `mcp_endpoint()`, `get_config()`
   - These are used everywhere but lack documentation

2. **Review Orphan Functions**
   - ~50 true orphans can likely be removed
   - Many indicator functions appear unused - verify before deletion
   - Singleton factories are false positives (dynamically called)

3. **Optimize Database Hotspots**
   - `trade_tracker.py` has 50 `execute()` calls - consider prepared statements
   - Batch operations in `real_options_backtester.py` could use executemany()

### Medium-Term Improvements

4. **Consolidate Indicators**
   - Many indicator functions duplicate each other (RSI calculated in 4 places)
   - Consider consolidating into single source of truth

5. **Modernize Dependency Injection**
   - 87 singleton factory functions suggest DI could be improved
   - Consider using a proper DI container

6. **Cache Manager References**
   - `handlers/portfolio.py` calls `get_portfolio_manager()` 13 times
   - Cache reference at class level instead

### Long-Term Architecture

7. **Consider Breaking Up Large Files**
   - `multi_strategy_scanner.py` (67K) could be split
   - `config_loader.py` (61K) has too many responsibilities

8. **Standardize Error Handling**
   - `mcp_endpoint()` and `sync_endpoint()` overlap
   - Could be unified into single decorator

9. **Add Type Hints**
   - Many functions lack return type annotations
   - Would improve IDE support and documentation

---

## Appendix: File Locations Reference

```
/Users/larschristiansen/OptionPlay/
├── src/
│   ├── analyzers/       # Strategy analyzers (10 files)
│   ├── backtesting/     # Backtesting engine (16 files)
│   ├── cache/           # Data caching (10 files)
│   ├── config/          # Configuration (5 files)
│   ├── constants/       # Trading constants (7 files)
│   ├── data_providers/  # External data (7 files)
│   ├── formatters/      # Output formatting (4 files)
│   ├── handlers/        # MCP handlers (14 files)
│   ├── indicators/      # Technical indicators (9 files)
│   ├── models/          # Data models (9 files)
│   ├── options/         # Options pricing (3 files)
│   ├── portfolio/       # Portfolio management (1 file)
│   ├── pricing/         # Black-Scholes (2 files)
│   ├── risk/            # Position sizing (1 file)
│   ├── scanner/         # Strategy scanning (4 files)
│   ├── services/        # Business logic (16 files)
│   ├── state/           # Server state (1 file)
│   ├── utils/           # Utilities (14 files)
│   └── visualization/   # Charts (1 file)
├── tests/               # Test suite (140+ files)
├── scripts/             # Utilities (50 files)
├── config/              # Configuration files
└── docs/                # Documentation
```

---

*This analysis was generated automatically. Last updated: 2026-02-05*
