# OptionPlay — System-Snapshot (Vollständige Bestandsaufnahme)

**Erstellt:** 2026-04-06
**Version:** 4.2.0
**Codebase:** 221 Module | ~96,400 LOC (src/) | 160 Test-Dateien | 75 Scripts
**Datenbank:** ~8.6 GB SQLite (`~/.optionplay/trades.db`)
**Python:** 3.12 (`.venv/bin/python`)

---

## Abschnitt 1 — Projektstruktur

```
OptionPlay/
├── .env                           # API-Keys (MARKETDATA_API_KEY, TRADIER_API_KEY)
├── .github/workflows/ci.yml       # CI Pipeline (Black → isort → flake8 → mypy → tests)
├── .pre-commit-config.yaml        # Git Hooks
├── CLAUDE.md                      # Claude-Kontext: DB-Schema, API, Code-Konventionen
├── SKILL.md                       # MCP-Tool-Referenz (53 Tools + 55 Aliases)
├── README.md                      # Projekt-Readme
├── pyproject.toml                 # Projekt-Config, Tool-Settings (Black, isort, mypy, pytest)
├── requirements.txt               # ~180 Pakete (frozen)
├── requirements-dev.txt           # Linting, Formatting, Type Checking
├── requirements-test.txt          # pytest, hypothesis, freezegun
├── requirements-training.txt      # Minimale Training-Deps (numpy, pandas, scipy)
├── claude_desktop_config.json     # Claude Desktop MCP-Server-Registrierung
│
├── config/                        # *** YAML-Konfiguration (370+ externalisierte Parameter) ***
│   ├── settings.yaml              # Haupt-Config: Datenquellen, Filter, Scanner, Performance
│   ├── strategies.yaml            # VIX-Profile, Exit, Roll-Parameter, Trained Weights
│   ├── watchlists.yaml            # Watchlists nach GICS-Sektoren (268 Symbole default)
│   ├── analyzer_thresholds.yaml   # Schwellenwerte für alle 5 Analyzer (~150 Params)
│   ├── scoring_weights.yaml       # ML-trainierte Gewichte, Regime, Sektor, Ranking (~85 Params)
│   ├── scanner_config.yaml        # Stability-Tiers, Win-Rate, Drawdown-Filter (~30 Params)
│   ├── trading_rules.yaml         # Entry/Exit/Roll/Sizing/Discipline (~95 Params)
│   ├── validation_config.yaml     # Reliability, Statistical, Signal-Validation (~12 Params)
│   ├── enhanced_scoring.yaml      # Liquidity/Credit/Pullback/Stability Bonuses (~15 Params)
│   ├── rsi_thresholds.yaml        # Stability-basierte RSI-Neutral-Schwellen (~4 Params)
│   └── backups/                   # Trainings-Backups (2026-01-29)
│
├── docs/                          # Dokumentation
│   ├── ARCHITECTURE.md            # System-Architektur
│   ├── PLAYBOOK.md                # Trading-Regelwerk (Entry, Exit, Sizing, VIX, Disziplin)
│   ├── SCORING_SYSTEM.md          # Scoring-Referenz
│   ├── VALIDATION_RULES.md        # Validierungsregeln
│   ├── OPTIONPLAY_STRATEGIE_v4.2.md # Strategie-Dokument v4.2
│   ├── PHASE1_BRIEFING.md         # Phase-1-Briefing
│   ├── pullback_analyzer.md       # Pullback-Analyzer-Doku
│   ├── scoring_extraction.json    # Scoring-Extraktion
│   └── archive/                   # ~40 archivierte Dokumente
│
├── data_inventory/                # Trainings-Artefakte und Baseline-Daten
│   ├── baseline_*.json            # Baselines für Pullback, Bounce, ATH Breakout
│   ├── retrain_history/           # Retraining-Reports
│   └── trained_weights_v3_*.json  # Trainierte Gewichte (Regime, Sektor, Stability)
│
├── reports/                       # Generierte Reports
│   ├── backtest_results.json
│   └── shap/                      # SHAP-Analyse-Ergebnisse
│
├── scripts/                       # 75 Utility-Scripts
│   ├── daily_data_fetcher.py      # Täglicher VIX + OHLCV Cronjob
│   ├── populate_fundamentals.py   # Fundamentals + Stability
│   ├── collect_earnings_eps.py    # EPS-Daten
│   ├── collect_earnings_tradier.py # Earnings via Tradier
│   ├── calculate_derived_metrics.py # IV Rank, Correlation, HV
│   ├── sync_daily_to_price_data.py  # OHLCV: daily_prices → price_data
│   ├── classify_liquidity.py      # Liquidity-Tier-Klassifizierung
│   ├── full_walkforward_train.py  # Walk-Forward-Training (280 Jobs, ~45 Min)
│   ├── fast_weight_train.py       # Schnelles Component-Weight-Training
│   ├── fast_strategy_train.py     # Schnelles Strategy-Training
│   ├── train_stability_thresholds.py # Stability-Cutoffs
│   ├── morning_workflow.py        # Morning-Workflow-Automation
│   ├── validate_scoring_changes.py # Scoring-Validierung
│   └── ... (62 weitere Scripts)
│
├── src/                           # *** Haupt-Quellcode (221 Module, ~96,400 LOC) ***
│   ├── __init__.py
│   ├── __main__.py
│   ├── mcp_server.py              # MCP Server Klasse (OptionPlayServer)
│   ├── mcp_tool_registry.py       # Tool-Registrierung (53 Tools + 55 Aliases → 108 Endpoints)
│   ├── mcp_main.py                # Entrypoint (CLI: --interactive, --test)
│   ├── container.py               # ServiceContainer (DI, 11 Singletons)
│   ├── shadow_tracker.py          # Shadow-Trade-Tracker (SQLite-backed)
│   │
│   ├── analyzers/                 # Trading-Strategie-Analyzer (5 Strategien)
│   │   ├── base.py                # BaseAnalyzer (abstract)
│   │   ├── context.py             # AnalysisContext (Dataclass, slots=True)
│   │   ├── pullback.py            # PullbackAnalyzer (13 Scoring-Komponenten, max 14.0)
│   │   ├── pullback_scoring.py    # PullbackScoringMixin (Score-Methoden)
│   │   ├── bounce.py              # BounceAnalyzer (5 Komponenten + 6 Extensions, max 10.0)
│   │   ├── ath_breakout.py        # ATHBreakoutAnalyzer (4 Komponenten + 5 Extensions, max 10.0)
│   │   ├── earnings_dip.py        # EarningsDipAnalyzer (5 Komponenten + 7 Extensions, max 9.5)
│   │   ├── trend_continuation.py  # TrendContinuationAnalyzer (5 Komponenten, max 10.5)
│   │   ├── feature_scoring_mixin.py # Shared Feature-Scoring (VWAP, Market Context, Sector, Gap)
│   │   ├── score_normalization.py # 0-10 Normalisierung pro Strategie
│   │   ├── batch_scorer.py        # Batch-Scoring
│   │   └── pool.py                # Analyzer Object Pool
│   │
│   ├── backtesting/               # Backtesting Sub-Package (44 Module, 17,611 LOC)
│   │   ├── core/                  # Engine, Metrics, Simulator, DB
│   │   ├── simulation/            # Options-Simulator, Real-Backtester
│   │   ├── training/              # Walk-Forward, Regime, ML-Optimizer
│   │   ├── validation/            # Signal-Validation, Reliability
│   │   ├── ensemble/              # Meta-Learner, Rotation, Selector
│   │   ├── tracking/              # Trade-CRUD, Storage (Price/VIX/Options)
│   │   ├── models/                # 25 Dataclasses
│   │   └── data_collector.py      # Daten-Pipeline
│   │
│   ├── cache/                     # Cache-Manager
│   │   ├── cache_manager.py       # CacheManager (TTL, LRU, Circuit Breaker)
│   │   ├── earnings_cache.py      # EarningsCache
│   │   ├── earnings_history.py    # EarningsHistoryManager
│   │   ├── historical_cache.py    # HistoricalCache
│   │   ├── iv_cache.py            # IVCache
│   │   ├── vix_cache.py           # VixCacheManager
│   │   ├── symbol_fundamentals.py # SymbolFundamentalsManager
│   │   └── dividend_history.py    # DividendHistoryManager
│   │
│   ├── config/                    # Konfiguration-Loader
│   │   ├── core.py                # Haupt-Config-Loader
│   │   ├── loader.py              # RecursiveConfigResolver
│   │   ├── models.py              # Config-Dataclasses
│   │   ├── scoring_config.py      # ResolvedWeights (ML-Gewichte + Regime + Sektor)
│   │   ├── analyzer_thresholds.py # Analyzer-Schwellenwert-Loader
│   │   ├── watchlist_loader.py    # WatchlistLoader (Tier-basiert)
│   │   ├── liquidity_blacklist.py # Illiquide Symbole (230 Stück)
│   │   └── validation.py          # Config-Validierung
│   │
│   ├── constants/                 # Konstanten
│   │   ├── trading_rules.py       # VIXRegime Enum, ENTRY_*, Regime-Rules (v1+v2)
│   │   ├── risk_management.py     # Risiko-Konstanten
│   │   ├── strategy_parameters.py # Strategie-Parameter
│   │   ├── technical_indicators.py # Technische Indikatoren
│   │   ├── thresholds.py          # Schwellenwerte
│   │   └── performance.py         # Performance-Konstanten
│   │
│   ├── data_providers/            # Daten-Provider
│   │   ├── interface.py           # DataProvider Interface
│   │   ├── local_db.py            # LocalDBProvider (SQLite)
│   │   ├── ibkr_provider.py       # IBKRDataProvider
│   │   ├── fundamentals.py        # Fundamentals-Provider
│   │   └── yahoo_news.py          # Yahoo News Provider
│   │
│   ├── formatters/                # Output-Formatierung
│   │   ├── output_formatters.py   # Markdown-Formatierung
│   │   ├── pdf_report_generator.py # PDF-Report-Generator (ReportLab)
│   │   └── portfolio_formatter.py # Portfolio-Formatierung
│   │
│   ├── handlers/                  # MCP-Handler (Composition-basiert)
│   │   ├── handler_container.py   # HandlerContainer (zentrale Dispatch)
│   │   ├── base.py                # BaseHandler (Provider-Fallback-Chain)
│   │   ├── scan_composed.py       # ScanHandler (Scan, Daily Picks)
│   │   ├── analysis_composed.py   # AnalysisHandler (Analyze, Ensemble, Strikes)
│   │   ├── vix_composed.py        # VixHandler (VIX, Regime, Sector)
│   │   ├── quote_composed.py      # QuoteHandler (Quotes, Options, Historical)
│   │   ├── portfolio_composed.py  # PortfolioHandler (CRUD, P&L)
│   │   ├── ibkr_composed.py       # IBKRHandler (TWS Bridge)
│   │   ├── report_composed.py     # ReportHandler (PDF)
│   │   ├── risk_composed.py       # RiskHandler (Position Sizing, Spread Analysis)
│   │   ├── validate_composed.py   # ValidateHandler (Trade Validation)
│   │   ├── monitor_composed.py    # MonitorHandler (Position Monitor)
│   │   └── *.py (deprecated)      # Legacy Mixin-Handler (Test-Kompatibilität)
│   │
│   ├── ibkr/                      # IBKR/TWS Bridge
│   │   ├── bridge.py              # IBKRBridge
│   │   ├── connection.py          # Connection Manager
│   │   ├── market_data.py         # Market Data
│   │   └── portfolio.py           # Portfolio
│   │
│   ├── indicators/                # Technische Indikatoren
│   │   ├── momentum.py            # RSI, MACD, Stochastic
│   │   ├── trend.py               # SMA, EMA, ADX
│   │   ├── volatility.py          # ATR, Bollinger, Keltner
│   │   ├── volume_profile.py      # Volume Profile
│   │   ├── support_resistance.py  # Support/Resistance (Unified)
│   │   ├── sr_core.py             # S/R Core
│   │   ├── sr_advanced.py         # S/R Advanced
│   │   ├── gap_analysis.py        # Gap-Analyse
│   │   ├── events.py              # Event-Kalender
│   │   └── optimized.py           # Optimierte NumPy-Berechnungen
│   │
│   ├── models/                    # Datenmodelle
│   │   ├── base.py                # TradeSignal, SignalType, SignalStrength
│   │   ├── candidates.py          # DailyPick, ScanCandidate
│   │   ├── indicators.py          # Indikator-Modelle
│   │   ├── market_data.py         # MarketData, HistoricalBar
│   │   ├── options.py             # OptionData, OptionChain
│   │   ├── result.py              # Result-Typen
│   │   ├── strategy.py            # Strategy-Modelle
│   │   └── strategy_breakdowns.py # Score-Breakdown-Modelle
│   │
│   ├── options/                   # Options-Analyse
│   │   ├── black_scholes.py       # Black-Scholes Pricing
│   │   ├── spread_analyzer.py     # Spread-Analyse (Risk/Reward, P&L-Szenarien)
│   │   ├── strike_recommender.py  # Strike-Empfehlung (Delta → Support → OTM%)
│   │   ├── strike_recommender_calc.py # Berechnungen
│   │   ├── max_pain.py            # Max-Pain-Berechnung
│   │   └── liquidity.py           # Liquiditäts-Analyse
│   │
│   ├── portfolio/                 # Portfolio-Management
│   │   └── manager.py             # PortfolioManager (CRUD, P&L)
│   │
│   ├── pricing/                   # Pricing
│   │   └── black_scholes.py       # Black-Scholes (Fallback)
│   │
│   ├── risk/                      # Risiko-Management
│   │   └── position_sizing.py     # Position Sizing (Kelly Criterion)
│   │
│   ├── scanner/                   # Scanner-Engine
│   │   ├── multi_strategy_scanner.py # MultiStrategyScanner (Parallel, Pool)
│   │   ├── multi_strategy_ranker.py  # Ranking-Logik
│   │   ├── market_scanner.py      # MarketScanner (Legacy)
│   │   └── signal_aggregator.py   # Signal-Aggregation
│   │
│   ├── services/                  # Business-Services
│   │   ├── base.py                # BaseService
│   │   ├── recommendation_engine.py # DailyRecommendationEngine
│   │   ├── recommendation_ranking.py # Ranking-Berechnungen
│   │   ├── enhanced_scoring.py    # Enhanced Scoring (Multiplicative)
│   │   ├── vix_regime.py          # VIX Regime v2 (Continuous Interpolation)
│   │   ├── vix_strategy.py        # VIXStrategySelector
│   │   ├── vix_service.py         # VIX Service
│   │   ├── sector_rs.py           # SectorRSService (RRG Quadrants)
│   │   ├── scanner_service.py     # Scanner Service
│   │   ├── quote_service.py       # Quote Service
│   │   ├── options_service.py     # Options Service
│   │   ├── options_chain_validator.py # Chain-Validierung
│   │   ├── pick_formatter.py      # Pick-Formatierung
│   │   ├── entry_quality_scorer.py # Entry Quality Score (7 Faktoren)
│   │   ├── iv_analyzer.py         # IV-Analyse
│   │   ├── signal_filter.py       # Signal-Filter
│   │   ├── trade_validator.py     # Trade-Validierung (GO/NO-GO/WARNING)
│   │   ├── portfolio_constraints.py # Portfolio-Constraints
│   │   ├── position_monitor.py    # Position-Monitor
│   │   └── server_core.py         # Server-Core
│   │
│   ├── state/                     # Server-State
│   │   └── server_state.py        # ServerState (Cache, Connections)
│   │
│   ├── utils/                     # Utilities
│   │   ├── circuit_breaker.py     # Circuit Breaker Pattern
│   │   ├── rate_limiter.py        # Rate Limiter
│   │   ├── request_dedup.py       # Request Deduplication
│   │   ├── secure_config.py       # SecureConfig (.env Loading)
│   │   ├── error_handler.py       # Error Handler
│   │   ├── markdown_builder.py    # Markdown Builder
│   │   ├── provider_orchestrator.py # Provider Orchestrator
│   │   ├── scanner_config_loader.py # Scanner Config Loader
│   │   ├── structured_logging.py  # Structured Logging
│   │   ├── validation.py          # Validierung
│   │   ├── earnings_aggregator.py # Earnings-Aggregator
│   │   ├── historical_cache.py    # Historical Cache Utils
│   │   ├── metrics.py             # Metrics
│   │   └── deprecation.py         # Deprecation Warnings
│   │
│   └── visualization/             # Visualisierung
│       └── sr_chart.py            # Support/Resistance Chart
│
├── tests/                         # Test-Suite (160 Dateien)
│   ├── conftest.py                # Gemeinsame Fixtures
│   ├── conftest_analyzers.py      # Analyzer-Fixtures
│   ├── unit/                      # 65 Unit-Tests
│   ├── component/                 # 45 Component-Tests
│   ├── integration/               # 44 Integration-Tests
│   └── system/                    # 11 System-Tests
│
└── data/                          # Runtime-Daten
    └── shadow_trades.db           # Shadow-Trade-Datenbank
```

---

## Abschnitt 2 — Alle MCP-Tools

### Tool-Registrierung

Die Tool-Registrierung erfolgt in `src/mcp_tool_registry.py`. Jedes Tool wird über FastMCP (`@mcp.tool()`) registriert und dispatcht an den entsprechenden Handler via `server.handlers.<handler>.<method>()`.

**Gesamt: 53 Tools + 55 Aliases = 108 MCP-Endpoints**

3 Server-Level-Tools (nicht über Handler):
- `optionplay_health` — Server-Health-Check
- `optionplay_cache_stats` — Cache-Statistiken
- `optionplay_watchlist_info` — Watchlist-Info

### VIX-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_vix` | Aktuelles VIX-Level + Strategie-Empfehlung | keine | `vix.get_vix()` |
| `optionplay_strategy_for_stock` | Strategie-Empfehlung für Symbol basierend auf VIX | `symbol: str` | `vix.get_strategy_for_stock()` |
| `optionplay_regime_status` | VIX-Regime-Status (v1 oder v2) | `version: str = "v1"` | `vix.get_regime_status()` |
| `optionplay_events` | Upcoming Market Events (FOMC, OPEX, CPI, NFP) | `days: int = 30` | `vix.get_event_calendar()` |
| `optionplay_sector_status` | Sektor-Momentum (RRG-Quadranten) | keine | `vix.get_sector_status()` |

### Scan-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_scan` | Pullback-Scan | `symbols: list, min_score: float, max_results: int, list_type: str` | `scan.scan_pullback_candidates()` |
| `optionplay_scan_bounce` | Support-Bounce-Scan | wie oben | `scan.scan_bounce()` |
| `optionplay_scan_breakout` | ATH-Breakout-Scan | wie oben | `scan.scan_ath_breakout()` |
| `optionplay_scan_earnings_dip` | Earnings-Dip-Scan | wie oben | `scan.scan_earnings_dip()` |
| `optionplay_scan_trend` | Trend-Continuation-Scan | wie oben | `scan.scan_trend_continuation()` |
| `optionplay_scan_multi` | Multi-Strategy-Scan (bestes Signal pro Symbol) | wie oben | `scan.scan_multi_strategy()` |
| `optionplay_daily_picks` | Top 5 Daily Picks (mit Strikes) | `max_picks: int, min_score: float, min_stability: float, symbols: list, include_strikes: bool` | `scan.daily_picks()` |
| `optionplay_earnings_prefilter` | Earnings-Pre-Filter (vor Scan) | `symbols: list, min_days: int, show_excluded: bool` | `scan._apply_earnings_prefilter()` |

### Quote-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_quote` | Stock-Quote (Bid/Ask/Volume) | `symbol: str` | `quote.get_quote()` |
| `optionplay_options` | Options-Chain mit Greeks/IV | `symbol: str, dte_min: int, dte_max: int, right: str` | `quote.get_options_chain()` |
| `optionplay_historical` | Historische Preisdaten | `symbol: str, days: int` | `quote.get_historical()` |
| `optionplay_earnings` | Earnings-Check (Safety-Status) | `symbol: str, min_days: int` | `quote.get_earnings()` |
| `optionplay_expirations` | Options-Expirations-Daten | `symbol: str` | `quote.get_expirations()` |
| `optionplay_max_pain` | Max-Pain-Level | `symbols: list` | `quote.get_max_pain()` |
| `optionplay_news` | News-Headlines via IBKR | `symbols: list, days: int` | `quote.get_news()` |

### Analysis-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_analyze` | Bull-Put-Spread-Analyse | `symbol: str` | `analysis.analyze_symbol()` |
| `optionplay_analyze_multi` | Multi-Strategy-Analyse | `symbol: str` | `analysis.analyze_multi_strategy()` |
| `optionplay_ensemble` | Ensemble-Empfehlung (Meta-Learner) | `symbol: str` | `analysis.get_ensemble_recommendation()` |
| `optionplay_ensemble_status` | Ensemble-Status | keine | `analysis.get_ensemble_status()` |
| `optionplay_recommend_strikes` | Optimale Strike-Empfehlung | `symbol: str, dte_min: int, dte_max: int, num_alternatives: int` | `analysis.recommend_strikes()` |

### Risk-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_spread_analysis` | Spread Risk/Reward Analyse | `symbol, short_strike, long_strike, net_credit, dte, contracts` | `risk.spread_analysis()` |
| `optionplay_monte_carlo` | Monte-Carlo-Simulation | `symbol, short_strike, long_strike, net_credit, dte, num_simulations, volatility` | `risk.monte_carlo()` |
| `optionplay_position_size` | Kelly-Criterion Position Sizing | `account_size, max_loss_per_contract, ...` | `risk.position_size()` |
| `optionplay_stop_loss` | Stop-Loss-Empfehlung | `net_credit, spread_width` | `risk.stop_loss()` |

### Validate-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_validate` | Symbol-Sicherheits-Check | `symbol: str` | `validate.validate_symbol()` |
| `optionplay_validate_trade` | Trade-Validierung (GO/NO-GO/WARNING) | `symbol, short_strike, long_strike, expiration, credit, contracts, portfolio_value` | `validate.validate_trade()` |

### Portfolio-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_portfolio` | Portfolio-Summary | keine | `portfolio.get_summary()` |
| `optionplay_portfolio_positions` | Positions-Liste | `status: str` | `portfolio.get_positions()` |
| `optionplay_portfolio_position` | Position-Detail | `position_id: str` | `portfolio.get_position()` |
| `optionplay_portfolio_add` | Position hinzufügen | `symbol, short_strike, long_strike, expiration, credit, contracts, notes` | `portfolio.add_position()` |
| `optionplay_portfolio_close` | Position schließen | `position_id, close_premium, notes` | `portfolio.close_position()` |
| `optionplay_portfolio_expire` | Position als expired markieren | `position_id` | `portfolio.expire_position()` |
| `optionplay_portfolio_expiring` | Bald ablaufende Positionen | `days: int` | `portfolio.get_expiring()` |
| `optionplay_portfolio_check` | Portfolio-Constraint-Check | `symbol, max_risk` | `portfolio.check_constraints()` |
| `optionplay_portfolio_constraints` | Constraint-Status | keine | `portfolio.get_constraints()` |
| `optionplay_portfolio_trades` | Trade-History | `limit: int` | `portfolio.get_trades()` |
| `optionplay_portfolio_monthly` | Monatlicher P&L-Report | keine | `portfolio.get_monthly()` |
| `optionplay_portfolio_pnl` | P&L nach Symbol | keine | `portfolio.get_pnl()` |

### Monitor-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_monitor_positions` | Exit-Signal-Monitor (CLOSE/ROLL/ALERT/HOLD) | keine | `monitor.monitor_all()` |

### Report-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_report` | PDF-Report für Symbol | `symbol, strategy, include_options, include_news` | `report.generate_report()` |
| `optionplay_scan_report` | Multi-Symbol PDF-Scan-Report (13 Seiten) | `symbols, strategy, min_score, max_candidates` | `report.generate_scan_report()` |

### IBKR-Handler Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_ibkr_status` | TWS-Connection-Status | keine | `ibkr.get_status()` |
| `optionplay_ibkr_portfolio` | Live-Portfolio aus TWS | keine | `ibkr.get_portfolio()` |
| `optionplay_ibkr_spreads` | Identifizierte Spread-Positionen | keine | `ibkr.get_spreads()` |
| `optionplay_ibkr_quotes` | Batch-Quotes via IBKR | `symbols: list, batch_size: int` | `ibkr.get_quotes()` |
| `optionplay_ibkr_vix` | Live VIX via IBKR | keine | `ibkr.get_vix()` |

### Shadow-Tracker Tools

| Tool | Zweck | Input | Handler |
|------|-------|-------|---------|
| `optionplay_shadow_review` | Shadow-Trades reviewen | `days_back, resolve, status_filter, strategy_filter` | Direkt in `mcp_tool_registry.py` |
| `optionplay_shadow_log` | Manuellen Shadow-Trade loggen | `symbol, strategy, score, short_strike, long_strike, expiration, price_at_log` | Direkt |
| `optionplay_shadow_detail` | Shadow-Trade-Detail | `trade_id: str` | Direkt |
| `optionplay_shadow_stats` | Aggregierte Statistiken | `group_by: str, min_trades: int` | Direkt |

---

## Abschnitt 3 — Score-System (vollständig)

### Überblick: 3-Stufen-Scoring

1. **Stufe 1: Komponenten-Scoring** — Jeder Analyzer vergibt Punkte pro Indikator
2. **Stufe 2: ML-Weight-Anwendung** — `FeatureScoringMixin` + `ResolvedWeights` (regime- & sektor-spezifisch)
3. **Stufe 3: Ranking** — `DailyRecommendationEngine` kombiniert Signal + Stability + Speed

### Strategie-spezifische Score-Konfigurationen

| Strategie | Max Possible | Effective Max | Normalisiert auf | Signal-Schwellen |
|-----------|-------------|---------------|-------------------|------------------|
| Pullback | 14.0 | 14.0 | 0-10 | Strong ≥7.0, Moderate ≥5.0, Weak ≥3.5 |
| Bounce | 10.0 | 10.0 | 0-10 | Strong ≥7.0, Moderate ≥5.0, Weak ≥3.5 |
| ATH Breakout | 10.0 | 10.0 | 0-10 | Strong ≥7.0, Moderate ≥5.0, Weak ≥4.0 |
| Earnings Dip | 9.5 | 9.5 | 0-10 | Strong ≥7.0, Moderate ≥5.0, Weak ≥3.5 |
| Trend Continuation | 10.5 | 10.5 | 0-10 | Strong ≥7.0, Moderate ≥5.0, Weak ≥3.5 |

### Pullback-Scoring (13 Komponenten)

Aus `src/analyzers/pullback_scoring.py` + `src/analyzers/pullback.py`:

| Komponente | Max Punkte | Gewicht (scoring_weights.yaml) | Beschreibung |
|-----------|-----------|-------------------------------|-------------|
| RSI | 3.0 | 3.7 | RSI < 30 → 3, < 40 → 2, < 50 → 1 (adaptiv nach Stability) |
| RSI Divergence | 3.0 | 3.6 | Bullische RSI-Divergenz |
| Support | 2.0 | 3.0 | Preis-Nähe zu Support + Touch-Count |
| Fibonacci | 2.0 | 2.5 | Retracement an 61.8%, 50%, 38.2% |
| Moving Averages | 2.0 | 1.06 | Dip im Aufwärtstrend (Preis > SMA200, < SMA20) |
| Trend Strength | 2.0 | 2.05 | SMA-Alignment + Steigung |
| Volume | 1.0 | 1.0 | Volume-Spike > 1.5x Durchschnitt |
| MACD | 2.0 | 2.4 | Histogram + Crossover |
| Stochastic | 2.0 | 1.2 | %K < 20 = oversold |
| Keltner | 2.0 | 2.0 | Lower-Band-Touch |
| VWAP | 3.0 | 1.5 | Preis-Relation zu VWAP |
| Market Context | 2.0 | 1.7 | SPY-SMA-Trend |
| Candlestick | 2.0 | 2.0 | Reversal-Patterns (Hammer, Engulfing) |

**Gesamt gewichtet:** Dynamisch via `max_possible: 14.0` (P95-Normalisierung)

### Bounce-Scoring (5 Basis + 6 Extensions)

Aus `src/analyzers/bounce.py`:

| Komponente | Max Punkte | Gewicht | Beschreibung |
|-----------|-----------|---------|-------------|
| Support Quality | 2.5 | 1.05 | Stärke, Touch-Count, Alter |
| Proximity | 2.0 | 2.7 (rsi) | Abstand zum Support |
| Bounce Confirmation | 2.5 | 2.0 (candlestick) | Reversal-Candle, Close > Support |
| Volume | 1.5 | 2.0 | Volumen-Bestätigung (Spike + Divergenz) |
| Trend Context | 1.5 | 0.99 (trend) | SMA-basierter Trend |

Extensions: B1 (Fibonacci DCB), B2 (SMA Reclaim), B3 (RSI Divergence), B4 (Downtrend Filter), B5 (Market Context), B6 (Bollinger)

### ATH-Breakout-Scoring (4 Basis + 5 Extensions)

Aus `src/analyzers/ath_breakout.py`:

| Komponente | Max Punkte | Gewicht | Beschreibung |
|-----------|-----------|---------|-------------|
| Consolidation Quality | 3.0 | 1.03 (ath) | Konsolidierungslänge, Tightness |
| Breakout Strength | 2.5 | 2.0 (volume) | Breakout-Abstand, Close-Position |
| Volume | 3.0 | 1.97 (momentum) | Volume-Ratio, Distribution |
| Momentum/Trend | 2.0 | 2.02 (macd) | RSI, MACD-Bestätigung |

Extensions: A1 (VCP Contraction), A2 (Consolidation Volume Profile), A3 (Relative Strength), A4 (Candle Quality), A5 (Gap Analysis)

### Earnings-Dip-Scoring (5 Basis + Penalties)

Aus `src/analyzers/earnings_dip.py`:

| Komponente | Max Punkte | Gewicht | Beschreibung |
|-----------|-----------|---------|-------------|
| Drop Magnitude | 2.0 | 3.0 (dip) | Stärke des Earnings-Drops (5-15%) |
| Stabilization | 2.5 | 2.0 | Stabilisierungs-Muster nach Drop |
| Fundamental Strength | 2.0 | 2.0 (trend) | Market Cap, EPS Beat Rate |
| Overreaction Indicators | 2.0 | 2.0 (rsi) | RSI-Übertreibung, Z-Score |
| BPS Suitability | 1.0 | 2.0 (stoch) | Bull-Put-Spread-Eignung |
| **Penalties** | -3.0 max | — | Continued Decline, RSI-Penalty |

Extensions: B1-B7 (Z-Score, Sector Context, Dynamic Stabilization, etc.)

### Trend-Continuation-Scoring (5 Komponenten)

Aus `src/analyzers/trend_continuation.py`:

| Komponente | Max Punkte | Gewicht | Beschreibung |
|-----------|-----------|---------|-------------|
| SMA Alignment | 2.5 | 2.00 | Price > SMA20 > SMA50 > SMA200 |
| Trend Stability | 2.5 | 2.00 | SMA-Slope-Konsistenz |
| Trend Buffer | 2.0 | 1.60 | Abstand Price zu SMA200 |
| Momentum Health | 2.0 | 1.60 | ADX, MACD, RSI |
| Volatility | 1.5 | 1.50 | Niedrige ATR% = gut |

### ML-Weight-Anwendung (Stufe 2)

Aus `src/config/scoring_config.py` → `ResolvedWeights`:

1. **Base Weights**: Aus `scoring_weights.yaml` pro Strategie
2. **Regime Override**: Wenn VIX-Regime vorhanden, werden spezifische Gewichte gemerged
3. **Sector Override**: Wenn Sektor bekannt, werden sector-spezifische Gewichte gemerged
4. **Sector Factor**: Multiplikator (0.6-1.2) pro Strategie × Sektor
5. **VIX Score Multiplier**: 0.0-1.5, per Strategie × Regime (z.B. TC elevated: 0.70)
6. **Enabled Flag**: `false` bei HIGH Regime für alle Strategien

Berechnung: `raw_score = Σ(component × weight)`, dann `normalized = (raw / max_possible) × 10`

### Ranking (Stufe 3)

Aus `src/services/recommendation_engine.py`:

```
base_score = (1 - stability_weight) × signal + stability_weight × (stability / 10)
speed_normalized = speed_score / speed_max
combined = base_score × speed_normalized^speed_exponent + event_bonus
```

Parameter aus `scoring_weights.yaml → ranking`:
- `stability_weight: 0.15` (15% Stability, 85% Signal)
- `speed_exponent: 0.3`
- `event_bonus: 0.5` für Event-Strategien (Pullback, Bounce, ATH, Dip)
- TC cap: max 3 in daily_picks
- `min_strategies_in_picks: 2`

### Enhanced Scoring (nur daily_picks)

Aus `src/services/enhanced_scoring.py`:

Modus: **Multiplicative** (default)
`enhanced = base × (1 + Σ(multipliers))`, max Faktor ×1.28

| Multiplier | Max | Basis |
|-----------|-----|-------|
| Liquidity | +0.10 | OI ≥ 5000 excellent, ≥ 700 good, ≥ 100 fair |
| Credit | +0.08 | Credit als % der Spread-Breite |
| Pullback | +0.05 | Pullback-Tiefe |
| Stability | +0.05 | Stability Score ≥ 80 |

---

## Abschnitt 4 — VIX-Profile (vollständig)

### Profil-System (Legacy v1 — strategies.yaml)

| Profil | VIX-Range | Min Score | IV Rank | Spread-Breite | Warnings |
|--------|-----------|-----------|---------|---------------|----------|
| Conservative | 0-15 | 6 | 20-50 | $5.00 | — |
| Standard | 15-20 | 5 | 30-70 | $5.00 | — |
| Aggressive | 20-30 | 5 | 40-80 | $7.50 | Positionsgrößen reduzieren |
| High Volatility | 30-100 | 6 | 60-95 | $10.00 | 50% Positionsgrößen, tägliche Überwachung |

**Alle Profile teilen:**
- DTE: 60-90 Tage
- Short Put Delta: -0.20 (±0.03)
- Long Put Delta: -0.05 (±0.02)
- Min Credit: 25-30% der Spread-Breite

### VIX Regime v2 — Kontinuierliche Interpolation

Aus `src/services/vix_regime.py`:

**Ankerpunkte** (7 Punkte, linear interpoliert):

| VIX | Spread Width | Min Score | Max Positions | Stability Min |
|-----|-------------|-----------|---------------|---------------|
| 10 | $2.50 | 3.5 | 6 | 60 |
| 15 | $5.00 | 4.0 | 5 | 65 |
| 20 | $5.00 | 4.5 | 4 | 70 |
| 25 | $7.50 | 5.0 | 3 | 80 |
| 30 | $7.50 | 5.5 | 2 | 85 |
| 35 | $10.00 | 6.5 | 1 | 90 |
| 40 | $10.00 | 7.0 | 0 | 100 |

**Delta bleibt fix** bei -0.20 (±0.03) — "Delta ist heilig"

**Term Structure Overlay** (nur VIX > 20):
- Contango → Score -0.5
- Backwardation → Score +1.0

**Feature-Flag:** `config/strategies.yaml → vix_regime_v2.enabled: false` (aktuell deaktiviert)

### VIX Regime Enum (trading_rules.py)

```python
class VIXRegime(Enum):
    LOW_VOL = "low_vol"           # VIX < 15
    NORMAL = "normal"             # VIX 15-20
    DANGER_ZONE = "danger_zone"   # VIX 20-25
    ELEVATED = "elevated"         # VIX 25-30
    HIGH_VOL = "high_vol"         # VIX 30-35
    NO_TRADING = "no_trading"     # VIX > 35
```

`MarketRegime = VIXRegime` (Alias). `UNKNOWN` entfernt → `Optional[VIXRegime] = None`.

### VIX-Regime-Regeln (trading_rules.yaml)

| Regime | Stability Min | Neue Trades | Max Positions | Max/Sektor | Risk/Trade | Profit Exit |
|--------|--------------|-------------|---------------|-----------|------------|-------------|
| Low Vol | 65.0 | ✅ | 10 | 2 | 2.0% | 50% |
| Normal | 65.0 | ✅ | 10 | 2 | 2.0% | 50% |
| Danger Zone | 80.0 | ✅ | 5 | 1 | 1.5% | 30% |
| Elevated | 80.0 | ✅ | 3 | 1 | 1.0% | 30% |
| High Vol | 100.0 | ❌ | 0 | 0 | 0% | 0% |
| No Trading | 100.0 | ❌ | 0 | 0 | 0% | 0% |

### VIX Score Multiplier Matrix (scoring_weights.yaml)

| Strategie | Low | Normal | Elevated | Danger | High |
|-----------|-----|--------|----------|--------|------|
| Pullback | 1.0 | 1.0 | 0.90 | 0.95 | disabled |
| Bounce | 1.0 | 1.0 | 0.90 | 0.95 | disabled |
| ATH Breakout | 1.0 | 1.0 | 0.80 | 0.85 | disabled |
| Earnings Dip | 1.0 | 1.0 | 0.95 | 1.0 | disabled |
| Trend Continuation | 1.05 | 1.0 | 0.70 | 0.75 | disabled |

---

## Abschnitt 5 — Filter-Logik

### Übersicht aller aktiven Filter

| # | Filter | Schwellenwert | Wo implementiert | Konfigurierbar | Typ |
|---|--------|--------------|-----------------|----------------|-----|
| 1 | **Blacklist** | 17 Symbole | `settings.yaml → blacklist_symbols` | ✅ YAML | Harter Ausschluss |
| 2 | **Liquidity Blacklist** | 230 Symbole | `src/config/liquidity_blacklist.py` | ❌ Hardcoded | Harter Ausschluss |
| 3 | **Stability Pre-Filter** | ≥ 50 | `settings.yaml → min_stability_score` | ✅ YAML | Harter Ausschluss |
| 4 | **Stability-First Post-Filter** | ≥ 60 → min_score 3.5 | `settings.yaml → scanner` | ✅ YAML | Score-Gate |
| 5 | **Liquidity Tier Gate** | max_tier per Strategy | `scoring_weights.yaml → max_tier` | ✅ YAML | Harter Ausschluss |
| 6 | **Earnings Pre-Filter** | ≥ 45 Tage | `settings.yaml → earnings_prefilter_min_days` | ✅ YAML | Harter Ausschluss |
| 7 | **Earnings In-Analyzer** | ≥ 60 Tage (per Strategy) | `multi_strategy_scanner.py:_should_skip_for_earnings()` | ✅ Code | Harter Ausschluss |
| 8 | **Price Filter** | $20-$1500 | `trading_rules.yaml → entry.price_min/max` | ✅ YAML | Harter Ausschluss |
| 9 | **Volume Filter** | ≥ 500,000 | `trading_rules.yaml → entry.volume_min` | ✅ YAML | Harter Ausschluss |
| 10 | **IV Rank Filter** | 30-80 | `trading_rules.yaml → entry.iv_rank_min/max` | ✅ YAML | Soft (Warning) |
| 11 | **VIX Max New Trades** | ≤ 30 | `trading_rules.yaml → entry.vix_max_new_trades` | ✅ YAML | Harter Ausschluss |
| 12 | **VIX No Trading** | ≤ 35 | `trading_rules.yaml → entry.vix_no_trading` | ✅ YAML | Harter Ausschluss |
| 13 | **Strategy Enabled** | per Regime | `scoring_weights.yaml → regimes.high.enabled: false` | ✅ YAML | Harter Ausschluss |
| 14 | **VIX Score Multiplier** | 0.0-1.5 | `scoring_weights.yaml → regimes.*.vix_score_multiplier` | ✅ YAML | Score-Modifier |
| 15 | **Sector Factor** | 0.6-1.2 | `scoring_weights.yaml → sectors.*.sector_factor` | ✅ YAML | Score-Modifier |
| 16 | **Sector RS Modifier** | ±0.5 | `strategies.yaml → sector_rs.score_modifiers` | ✅ YAML | Score-Modifier |
| 17 | **Term Structure Overlay** | -0.5 / +1.0 | `src/services/vix_regime.py` | ✅ YAML | Score-Modifier |
| 18 | **Min Data Points** | ≥ 60 | `settings.yaml → scanner.min_data_points` | ✅ YAML | Harter Ausschluss |
| 19 | **Enhanced Scoring Liquidity** | min_quality "fair" | `scoring_weights.yaml → min_quality_daily_picks` | ✅ YAML | Score-Modifier |
| 20 | **WF-Trained Stability Thresholds** | per Strategy × Regime × Sector | `scoring_weights.yaml → stability_thresholds` | ✅ YAML | Score-Gate |

### Filter-Reihenfolge im Scanner

1. Blacklist-Check (Symbol auf Blacklist? → Skip)
2. Liquidity-Blacklist-Check (illiquid? → Skip)
3. Fundamentals Pre-Filter (Stability ≥ 50 → OK)
4. Liquidity Tier Gate (max_tier per Strategy → Skip)
5. Earnings Pre-Filter (≥ 45 Tage → OK)
6. Strategie-spezifischer Earnings-Filter (≥ 60 Tage → OK)
7. Strategy Enabled Check (VIX Regime → enabled/disabled)
8. Analyzer-Ausführung (Score-Berechnung)
9. VIX Score Multiplier (Score × Multiplier)
10. Sector Factor (Score × Factor)
11. Min-Score-Gate (normalized ≥ threshold)
12. Stability-First Post-Filter (Tiered: Premium ≥80→4.0, Good ≥70→5.0, OK ≥50→6.0)

---

## Abschnitt 6 — Watchlist

### Gesamtzahl

**Default Watchlist (`default_275`):** 268 Symbole aus 14 Gruppen

### Sektor-Verteilung

| GICS-Sektor / Gruppe | Anzahl Symbole |
|-----------------------|---------------|
| Information Technology | 24 |
| Health Care | 25 |
| Financials | 23 |
| Consumer Discretionary | 25 |
| Communication Services | 17 |
| Industrials | 22 |
| Consumer Staples | 20 |
| Energy | 17 |
| Utilities | 8 |
| Materials | 14 |
| Real Estate | 10 |
| ETFs (Index & Sektor) | 13 |
| Echtgelddepot Extras | 24 |
| UMWA Watchlist Extras | 26 |

### Weitere Watchlists (in watchlists.yaml definiert, aber leer)

- `tech_focus`: 10 Symbole (nur IT)
- `high_liquidity`: 0 (Platzhalter)
- `sp500_complete`: 0 (Platzhalter)
- `extended_600`: 0 (Platzhalter)

### Aktive Watchlist

`settings.yaml → watchlist.default_list: "extended_600"` — Da `extended_600` leer ist, wird auf `default_275` zurückgefallen.

### Stability-basierte Aufteilung

Automatisch via `settings.yaml → watchlist.stability_split`:
- `stable_list`: Symbole mit Stability ≥ 58.0
- `risk_list`: Symbole mit Stability < 58.0
- Blacklist-Symbole werden komplett ausgeschlossen
- Symbole ohne Score → `stable_list` (per `include_unknown_in_risk: false`)

### Scan-Verwendung

- **`/scan`** → scannt nur `stable_list` (schnell, hohe Qualität)
- **`/scan --risk`** → scannt nur `risk_list` (Spekulation)
- **`/scan --all`** → scannt beide Listen
- **`daily_picks`** → Scant Tier 1 Symbole zuerst (`WatchlistLoader.get_symbols_by_tier(max_tier=1)`), Fallback auf stable_list
- **Max Batch-Größe:** 50 Symbole pro Scan-Batch (`settings.yaml → max_symbols_per_scan: 50`)

---

## Abschnitt 7 — Datenfluss

### Standard-Scan (z.B. `optionplay_scan`)

```
1. MCP-Tool-Aufruf
   └→ mcp_tool_registry.py → server.handlers.scan.scan_pullback_candidates()

2. Handler: ScanHandler (scan_composed.py)
   ├→ Earnings Pre-Filter (_apply_earnings_prefilter)
   │   └→ EarningsCache.get_next_earnings(symbol)
   │       └→ Tradier API (mit 4-Wochen-Cache)
   ├→ Scanner initialisieren (_get_multi_scanner)
   │   └→ MultiStrategyScanner(analyzer_pool, scan_config)
   └→ _execute_scan(symbols, strategy, mode)

3. Scanner: MultiStrategyScanner (multi_strategy_scanner.py)
   ├→ Fundamentals Pre-Filter (Stability ≥ 50)
   │   └→ SymbolFundamentalsManager (SQLite: symbol_fundamentals)
   ├→ Liquidity Tier Gate (max_tier per Strategy)
   │   └→ SymbolFundamentalsManager.get_fundamentals(symbol).liquidity_tier
   ├→ Strategy Enabled Check (VIX Regime → scoring_weights.yaml)
   │   └→ VixCacheManager → aktuelle VIX → Regime-Bestimmung
   │
   ├→ FÜR JEDES SYMBOL (parallel, max 50 concurrent):
   │   ├→ Historical Data laden
   │   │   ├→ 1. Lokale DB (LocalDBProvider → daily_prices Tabelle)
   │   │   └→ 2. Tradier API (Fallback)
   │   │
   │   ├→ AnalysisContext erstellen (context.py)
   │   │   └→ Berechnet: RSI, SMA(20/50/200), EMA, MACD, Stochastic,
   │   │       Fibonacci, ATR, Support/Resistance, Volume, ATH, Trend
   │   │
   │   ├→ Analyzer ausführen (z.B. PullbackAnalyzer.analyze())
   │   │   ├→ Gates prüfen (RSI overbought, SMA200, pullback evidence)
   │   │   ├→ Scoring-Komponenten berechnen (13 für Pullback)
   │   │   ├→ ML-Weights anwenden (ResolvedWeights)
   │   │   ├→ VIX Score Multiplier anwenden
   │   │   └→ Score normalisieren (0-10)
   │   │
   │   └→ TradeSignal zurückgeben (oder None bei Nicht-Qualifizierung)
   │
   └→ Ergebnisse sammeln, nach Score sortieren

4. Post-Processing (zurück im Handler)
   ├→ Stability-First Post-Filter
   ├→ Ergebnisse formatieren (Markdown)
   └→ Rückgabe an MCP-Client
```

### Daily Picks (spezieller Ablauf)

```
1. optionplay_daily_picks → scan.daily_picks()

2. ScanHandler.daily_picks()
   ├→ Overfetch: 5× max_picks Kandidaten scannen (Multi-Strategy, BEST_SIGNAL mode)
   ├→ Enhanced Scoring anwenden (multiplicative, nur für daily_picks)
   │   └→ EnhancedScoringConfig: Liquidity + Credit + Pullback + Stability
   ├→ Re-Sort nach enhanced Score
   ├→ Strategy-Balance: Event-Bonus, TC cap (3), min_strategies (2)
   │
   ├→ Für jeden Pick:
   │   ├→ Strike-Empfehlung laden (recommend_strikes)
   │   │   ├→ Options-Chain laden (Tradier → IBKR Fallback)
   │   │   ├→ Delta-basierte Strike-Auswahl (-0.20 Short, -0.05 Long)
   │   │   ├→ Fallback: Support-basiert → OTM%-basiert (12%)
   │   │   └→ Quality Score berechnen (0-100)
   │   │
   │   ├→ Spread-Analyse (SpreadAnalyzer)
   │   └→ Stop-Loss berechnen (VIX-regime-adjusted)
   │
   ├→ Shadow Logging (wenn enabled, auto_log_min_score ≥ 8.0)
   │   ├→ Tradability Check (live Options-Chain)
   │   │   └→ min_net_credit $2, min_OI 100, min_bid $0.10, max_spread 30%
   │   └→ SQLite: shadow_trades.db
   │
   └→ Formatierung (_format_single_pick_v2)
       └→ Markdown mit Score, Strikes, Credit, Stop-Loss, Speed, Tier-Badge
```

### Cache-Architektur

| Cache | TTL | Max Entries | Inhalt |
|-------|-----|-------------|--------|
| Historical Data | 900s (15 Min) | 500 | OHLCV-Bars |
| Live Quotes | 300s (5 Min) | — | Bid/Ask/Volume |
| VIX | 300s (5 Min) | — | VIX-Wert |
| Earnings | 4 Wochen | — | Next Earnings Date |
| Fundamentals | Session | — | Stability, Win Rate, etc. |
| Options Chain | Request-Dedup | — | Deduplizierte gleichzeitige Requests |

### Provider-Fallback-Chain

```
Historische Daten:  LocalDB → Tradier API → Yahoo Finance
Options-Chain:      Tradier → IBKR
VIX:                Tradier → IBKR → Yahoo Finance
Quotes:             Tradier → IBKR
Earnings:           Tradier → Yahoo Finance
```

---

## Abschnitt 8 — Bekannte Limitierungen

### TODOs im Code

| Datei | Zeile | TODO |
|-------|-------|------|
| `src/analyzers/pool.py` | 280 | `TODO: Implementiere block_on_empty mit Condition Variable` |

### Fehlende Implementierungen

1. **VIX Regime v2 deaktiviert**: `strategies.yaml → vix_regime_v2.enabled: false` — Feature-Flag ist off
2. **Sector RS deaktiviert**: `strategies.yaml → sector_rs.enabled: false` — Feature-Flag ist off
3. **Extended Watchlists leer**: `extended_600`, `sp500_complete`, `high_liquidity` in watchlists.yaml sind als Platzhalter definiert, aber enthalten keine Symbole
4. **aiosqlite deferred**: Phase G.4 (async SQLite) wurde als LOW ROI markiert und nicht implementiert
5. **Phase H nicht gestartet**: Audit Roadmap Phase H ist noch offen
6. **pyproject.toml Version**: `4.1.0` statt `4.2.0` (CLAUDE.md sagt 4.2.0)

### Architektonische Einschränkungen

1. **Liquidity Blacklist hardcoded**: `src/config/liquidity_blacklist.py` enthält 230 Symbole direkt im Code, nicht in YAML
2. **Legacy Mixin-Handler**: Die alten `src/handlers/*.py` (ohne `_composed`) existieren noch für Test-Kompatibilität
3. **SQLite Single-Writer**: Kein async SQLite (aiosqlite deferred), alle DB-Zugriffe über `asyncio.to_thread()`
4. **Shadow-Tracker-DB separat**: `data/shadow_trades.db` ist eine separate Datenbank, nicht in `trades.db` integriert

---

## Abschnitt 9 — Abhängigkeiten

### Python-Packages (Kern-Abhängigkeiten)

| Package | Version | Zweck |
|---------|---------|-------|
| `fastmcp` | 3.2.0 | MCP Server Framework |
| `mcp` | 1.26.0 | MCP Protocol |
| `pydantic` | 2.12.5 | Datenvalidierung |
| `aiohttp` | 3.13.5 | Async HTTP (Tradier API) |
| `numpy` | 2.3.5 | Numerische Berechnungen |
| `pandas` | 3.0.0 | Datenverarbeitung |
| `scipy` | 1.17.0 | Statistische Berechnungen |
| `scikit-learn` | 1.8.0 | ML (Walk-Forward Training) |
| `xgboost` | 3.1.3 | Gradient Boosting |
| `shap` | 0.50.0 | Feature Importance |
| `pyyaml` | 6.0.3 | YAML-Config-Parsing |
| `python-dotenv` | 1.2.1 | .env-Loading |
| `ib-insync` | 0.9.86 | IBKR/TWS Integration |
| `nest-asyncio` | 1.6.0 | Nested Asyncio Loops |
| `yfinance` | 1.2.0 | Yahoo Finance (VIX, Earnings Fallback) |
| `reportlab` | 4.4.9 | PDF-Report-Generierung |
| `matplotlib` | 3.10.8 | Charts |
| `numba` | 0.63.1 | JIT-Compilation für Performance |
| `hypothesis` | 6.151.4 | Property-based Testing |
| `requests` | 2.33.1 | HTTP Requests |
| `rich` | 14.3.1 | Terminal-Formatierung |
| `diskcache` | 5.6.3 | Disk-Cache |

### Dev/Test-Packages

| Package | Zweck |
|---------|-------|
| `pytest` | Test Framework |
| `pytest-asyncio` | Async Test Support |
| `pytest-cov` | Coverage |
| `pytest-timeout` | Test Timeouts |
| `black` | Code Formatter |
| `isort` | Import Sorter |
| `flake8` + Plugins | Linting |
| `mypy` | Type Checking |
| `bandit` | Security Linting |
| `pre-commit` | Git Hooks |
| `freezegun` | Time Mocking |

### Externe APIs

| API | Zweck | Auth | Status |
|-----|-------|------|--------|
| **Tradier** | Options Chains, ORATS Greeks, Quotes, Historical | API Key (`.env: TRADIER_API_KEY`) | Primär |
| **IBKR/TWS** | Live Options, Quotes, Portfolio, News | localhost:4001 | Optional (Fallback) |
| **Yahoo Finance** | VIX-Daten, Earnings (Fallback) | Keine | Aktiv (Fallback) |
| **Marketdata.app** | — | API Key (`.env: MARKETDATA_API_KEY`) | Nicht mehr aktiv verwendet |

### .env-Schlüssel

| Key | Zweck |
|-----|-------|
| `MARKETDATA_API_KEY` | Marketdata.app (legacy, nicht mehr aktiv) |
| `TRADIER_API_KEY` | Tradier API (primärer Daten-Provider) |

### Optionale Komponenten

**IBKR Bridge:**
- Aktiviert wenn: TWS/Gateway auf localhost:4001 erreichbar
- Deaktiviert wenn: `OPTIONPLAY_NO_IBKR` env var gesetzt, oder TWS nicht gestartet
- Lazy Connection: `_ensure_tradier_connected()` / IBKR nur bei Bedarf
- Fallback: Tradier → IBKR für Options-Daten

---

## Abschnitt 10 — Offene Fragen an den Entwickler

1. **VIX Regime v2 vs v1**: Beide Systeme existieren parallel. `strategies.yaml → vix_regime_v2.enabled: false` und `sector_rs.enabled: false`. Wann sollen v2 und Sector RS produktiv geschaltet werden? Oder sind sie bereits über einen anderen Pfad aktiv (CLAUDE.md erwähnt `scanner.vix_regime_version: 2` als Feature-Flag)?

2. **Extended Watchlists**: `extended_600` ist als Default konfiguriert (`settings.yaml → default_list: "extended_600"`), aber in `watchlists.yaml` sind 0 Symbole definiert. Wird die Extended-Liste extern generiert oder dynamisch befüllt? Oder ist `default_275` die tatsächlich aktive Liste?

3. **Version Inkonsistenz**: `CLAUDE.md` sagt Version 4.2.0, aber `pyproject.toml` zeigt `4.1.0`. Welche ist korrekt?

4. **Earnings Min Days Diskrepanz**: `trading_rules.yaml → entry.earnings_min_days: 30`, aber `settings.yaml → earnings_prefilter_min_days: 45`. Gleichzeitig sagt PLAYBOOK §1 "≥ 45 Tage". Welcher Wert ist der tatsächlich aktive Entry-Filter?

5. **Roll-Parameter-Duplikation**: `settings.yaml` und `strategies.yaml` definieren beide `roll_strategy`-Parameter mit teils unterschiedlichen Werten (z.B. Pullback trigger_pct: -42.6 vs -65.0). Welche Quelle hat Vorrang?

6. **Stability Split Threshold**: `settings.yaml` sagt `stable_min_score: 58.0`, aber an anderen Stellen im Code werden 60 und 65 als Stability-Schwellen verwendet. Ist 58 der bewusst gewählte Wert?

7. **`min_quality_daily_picks: "fair"`**: Enhanced Scoring filtert "poor" Liquidität aus daily_picks. Was ist die Schwelle für "poor"? Ist das < 100 OI?

8. **Sector RS vs Sector Momentum**: `scoring_weights.yaml → sector_momentum` und `strategies.yaml → sector_rs` scheinen verschiedene Systeme zu sein. Sector Momentum verwendet ETF-basierte Relative Strength, Sector RS verwendet RRG-Quadranten. Welches ist aktiv?

9. **Shadow Tracker auto_log_min_score**: `settings.yaml → auto_log_min_score: 8.0` scheint hoch. Werden damit die meisten daily_picks ignoriert (typische Scores 4-7)?

10. **Training Data Freshness**: Die trainierten Modelle stammen von 2026-02-09 (`scoring_weights.yaml → trained: '2026-02-09'`). Gibt es einen Plan oder Zeitplan für Retraining? Die DB-Daten reichen bis 2026-01, was ~2 Monate vor dem aktuellen Datum liegt.

11. **IBKR Port Diskrepanz**: `settings.yaml` sagt `port: 4001` (Gateway Live), aber CLAUDE.md erwähnt `localhost:7497` (TWS Paper). Welcher Port ist aktuell aktiv?
