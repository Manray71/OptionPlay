# OptionPlay — Vollständige Projektdokumentation

**Stand:** 6. Februar 2026
**Version:** 4.0.0 (src), 3.7.0 (pyproject.toml)
**Python:** ≥3.11
**Test-Coverage:** 80.19% (6.748 Tests)
**Gesamtumfang:** 88.186 LOC (155 Module in src/)

---

## Inhaltsverzeichnis

1. [Projektübersicht](#1-projektübersicht)
2. [Architektur](#2-architektur)
3. [Verzeichnisstruktur](#3-verzeichnisstruktur)
4. [Modul-Referenz](#4-modul-referenz)
5. [Backtesting Sub-Packages (Phase 6)](#5-backtesting-sub-packages-phase-6)
6. [Datenbank-Schema](#6-datenbank-schema)
7. [Abhängigkeiten](#7-abhängigkeiten)
8. [Import-Graph & Zirkuläre Risiken](#8-import-graph--zirkuläre-risiken)
9. [Klassen-Inventar (src/backtesting/)](#9-klassen-inventar-srcbacktesting)
10. [Code-Metriken](#10-code-metriken)
11. [Test-Architektur](#11-test-architektur)
12. [Refactoring-Historie (Phase 1–6)](#12-refactoring-historie-phase-1-6)
13. [Bekannte Probleme & Technische Schulden](#13-bekannte-probleme--technische-schulden)
14. [Empfehlungen für Code Review](#14-empfehlungen-für-code-review)

---

## 1. Projektübersicht

OptionPlay ist ein **MCP-Server (Model Context Protocol)** für Options-Trading-Analyse, spezialisiert auf **Bull-Put-Spreads**. Das System kombiniert:

- **4 Strategien:** Pullback, Bounce, ATH-Breakout, Earnings-Dip
- **5 VIX-Regime:** Low (<15), Normal (15–20), Danger Zone (20–25), Elevated (25–30), High (>30)
- **53 MCP-Tools + 55 Aliase** = 108 Endpoints
- **Backtesting-Engine** mit Walk-Forward-Training, Regime-Optimierung und ML-Gewichtsoptimierung
- **IBKR-Integration** (Interactive Brokers TWS) für Live-Portfolio-Monitoring

### Kernfunktionen

| Funktion | Beschreibung |
|----------|-------------|
| **Daily Picks** | Top-5 Trades pro Tag basierend auf Score, Stability und VIX |
| **Trade Validator** | GO/NO-GO Entscheidung anhand PLAYBOOK-Regeln |
| **Position Monitor** | HOLD/CLOSE/ROLL/ALERT für offene Positionen |
| **Multi-Strategy Scan** | Paralleler Scan aller 4 Strategien über Watchlist |
| **Regime Model** | VIX-basierte Parameter-Anpassung (trained via Walk-Forward) |
| **Ensemble Selector** | Meta-Learner + Rotation für Strategy-Auswahl pro Symbol |

---

## 2. Architektur

### Layer-Modell

```
┌─────────────────────────────────────────────────────┐
│                   MCP Protocol Layer                 │
│            (mcp_server.py, mcp_tool_registry.py)     │
├─────────────────────────────────────────────────────┤
│                   Handler Layer                      │
│   (vix, scan, quote, analysis, portfolio, ibkr,     │
│    report, risk, validate, monitor)                  │
├─────────────────────────────────────────────────────┤
│                   Service Layer                      │
│   (vix_service, quote_service, scanner_service,     │
│    options_service, recommendation_engine,            │
│    trade_validator, position_monitor)                 │
├─────────────────────────────────────────────────────┤
│                  Analyzer Layer                      │
│   (pullback, bounce, ath_breakout, earnings_dip,    │
│    feature_scoring_mixin, score_normalization)        │
├─────────────────────────────────────────────────────┤
│                 Provider Layer                       │
│   (tradier, marketdata, local_db, yahoo_news,       │
│    fundamentals)                                     │
├─────────────────────────────────────────────────────┤
│              Infrastructure Layer                    │
│   (cache, config, constants, utils, state)          │
├─────────────────────────────────────────────────────┤
│              Backtesting Module                      │
│   (core, simulation, training, validation,          │
│    ensemble, tracking, models)                       │
└─────────────────────────────────────────────────────┘
```

### Handler-Pattern (Mixin-basiert)

```python
class OptionPlayServer(
    VixHandlerMixin,
    ScanHandlerMixin,
    QuoteHandlerMixin,
    AnalysisHandlerMixin,
    PortfolioHandlerMixin,
    IBKRHandlerMixin,
    ReportHandlerMixin,
    RiskHandlerMixin,
    ValidateHandlerMixin,
    MonitorHandlerMixin,
    BaseHandlerMixin,
):
    pass
```

Jeder Handler delegiert an Services, die wiederum Analyzer und Provider nutzen.

### Singleton-Pattern

Thread-safe Singletons mit `RLock` für:
- `CacheManager` (Earnings, IV, VIX, Historical)
- `ServerState` (aktiver Zustand des MCP-Servers)
- `Container` (Dependency Injection)

---

## 3. Verzeichnisstruktur

```
src/                                    88.186 LOC | 155 Module
├── __init__.py                         (261 LOC — Re-export Facade)
├── mcp_server.py                       (905 LOC — Server-Klasse)
├── mcp_tool_registry.py                (1.081 LOC — 108 Tool-Registrierungen)
├── mcp_main.py                         (255 LOC — Entry Point)
├── container.py                        (451 LOC — DI Container)
├── ibkr_bridge.py                      (1.514 LOC — Interactive Brokers)
├── spread_analyzer.py                  (774 LOC — Spread-Bewertung)
├── strike_recommender.py               (1.289 LOC — Strike-Empfehlungen)
├── vix_strategy.py                     (739 LOC — VIX-Strategie-Logik)
├── watchlist_loader.py                 (277 LOC — Watchlist-Management)
│
├── analyzers/                          4 Strategie-Analyzer + Utilities
│   ├── pullback.py                     Pullback-Analyse
│   ├── bounce.py                       Support-Bounce-Analyse
│   ├── ath_breakout.py                 All-Time-High Breakout
│   ├── earnings_dip.py                 Earnings-Dip-Analyse
│   ├── feature_scoring_mixin.py        Scoring-Framework (gemeinsam)
│   ├── score_normalization.py          Score-Normalisierung
│   ├── context.py                      Analysis-Kontext
│   ├── pool.py                         Analyzer-Pool
│   └── base.py                         Abstrakte Basis
│
├── backtesting/                        17.611 LOC | 44 Module | 83 Klassen
│   ├── core/                           Engine, Metrics, Simulator, DB, Spread
│   ├── simulation/                     Options-Simulator, Real-Backtester
│   ├── training/                       Walk-Forward, Regime, ML-Optimizer
│   ├── validation/                     Signal-Validation, Reliability
│   ├── ensemble/                       Meta-Learner, Rotation, Selector
│   ├── tracking/                       Trade-CRUD, Price/VIX/Options-Storage
│   ├── models/                         Datenmodelle (reine Dataclasses)
│   └── data_collector.py               Daten-Sammlung (VIX, Prices)
│
├── cache/                              Caching-Layer
│   ├── cache_manager.py                Zentrale Cache-Verwaltung
│   ├── earnings_cache.py               Earnings-Termine
│   ├── historical_cache.py             Historische Preisdaten
│   ├── iv_cache.py                     Implied-Volatility-Cache
│   ├── symbol_fundamentals.py          Stability, Sector, Beta
│   └── vix_cache.py                    VIX-Daten-Cache
│
├── config/                             Konfiguration
│   ├── core.py                         Zentrale Config-Klasse
│   ├── loader.py                       YAML-Loader
│   ├── models.py                       Config-Datenmodelle
│   ├── validation.py                   Config-Validierung
│   ├── fundamentals_constants.py       Stability-Schwellen
│   └── liquidity_blacklist.py          Blacklisted Symbole
│
├── constants/                          Trading-Konstanten
│   ├── performance.py                  Performance-Schwellen
│   ├── risk_management.py              Risiko-Parameter
│   ├── strategy_parameters.py          Strategie-Defaults
│   ├── technical_indicators.py         Indikator-Parameter
│   ├── thresholds.py                   Score-Schwellen
│   └── trading_rules.py               PLAYBOOK-Regeln als Code
│
├── data_providers/                     Daten-Quellen
│   ├── tradier.py                      Tradier API (Options, Quotes)
│   ├── marketdata.py                   MarketData API (Backup)
│   ├── local_db.py                     Lokale SQLite-Daten
│   ├── fundamentals.py                 Fundamentaldaten-Provider
│   ├── yahoo_news.py                   Yahoo Finance News
│   └── interface.py                    Abstrakte Provider-Schnittstelle
│
├── formatters/                         Ausgabe-Formatierung
│   ├── output_formatters.py            Markdown-Formatierung
│   ├── pdf_report_generator.py         PDF-Report-Generator
│   └── portfolio_formatter.py          Portfolio-Darstellung
│
├── handlers/                           MCP-Handler (13 Mixins)
│   ├── vix.py                          VIX-Tools (vix, regime, events)
│   ├── vix_composed.py                 Komponierte VIX-Handler
│   ├── scan.py                         Scan-Tools (pullback, bounce, etc.)
│   ├── quote.py                        Quote/Options/Earnings-Tools
│   ├── analysis.py                     Analyse-Tools (analyze, ensemble)
│   ├── portfolio.py                    Portfolio-Management-Tools
│   ├── ibkr.py                         IBKR-Tools (live portfolio)
│   ├── report.py                       Report-Generation-Tools
│   ├── risk.py                         Risk-Tools (position_size, stop_loss)
│   ├── validate.py                     Trade-Validierung-Tools
│   ├── monitor.py                      Position-Monitor-Tools
│   ├── base.py                         Base-Handler (health, watchlist)
│   └── handler_container.py            Handler-Container
│
├── indicators/                         Technische Indikatoren
│   ├── momentum.py                     RSI, MACD, Stochastic
│   ├── trend.py                        SMA, EMA, ADX
│   ├── volatility.py                   ATR, Bollinger Bands
│   ├── support_resistance.py           S/R-Levels
│   ├── volume_profile.py              Volume-Profile
│   ├── gap_analysis.py                Gap-Erkennung
│   ├── events.py                       Event-Detection
│   └── optimized.py                    NumPy-optimierte Berechnung
│
├── models/                             Domain-Modelle
│   ├── base.py                         TradeSignal, SignalType
│   ├── candidates.py                   Kandidaten-Modelle
│   ├── indicators.py                   Indikator-Datentypen
│   ├── market_data.py                  Marktdaten-Modelle
│   ├── options.py                      Options-Modelle
│   ├── result.py                       Ergebnis-Typen
│   ├── strategy.py                     Strategie-Modelle
│   └── strategy_breakdowns.py          Strategie-Detail-Modelle
│
├── options/                            Options-Pricing
│   ├── black_scholes.py                Black-Scholes-Modell
│   ├── liquidity.py                    Liquiditäts-Analyse
│   └── max_pain.py                     Max-Pain-Berechnung
│
├── portfolio/                          Portfolio-Management
│   └── manager.py                      Portfolio-Manager
│
├── pricing/                            Pricing-Utilities
│   └── black_scholes.py                BS-Batch-Funktionen (NumPy)
│
├── risk/                               Risiko-Management
│   └── position_sizing.py              Kelly-Criterion, Position Sizing
│
├── scanner/                            Multi-Strategy-Scanner
│   ├── market_scanner.py               Watchlist-Scanner
│   ├── multi_strategy_scanner.py       Paralleler Multi-Strategie-Scan
│   ├── multi_strategy_ranker.py        Ranking-Logik
│   └── signal_aggregator.py            Signal-Aggregation
│
├── services/                           Business-Logik-Services
│   ├── vix_service.py                  VIX-Daten + Regime
│   ├── quote_service.py                Quotes + Historical
│   ├── options_service.py              Options-Chain + Greeks
│   ├── scanner_service.py              Scan-Orchestrierung
│   ├── recommendation_engine.py        Daily-Picks-Engine
│   ├── trade_validator.py              PLAYBOOK-Validierung
│   ├── position_monitor.py             Position-Monitoring
│   ├── entry_quality_scorer.py         Entry-Qualitäts-Score
│   ├── iv_analyzer.py                  IV-Analyse
│   ├── portfolio_constraints.py        Portfolio-Constraints
│   ├── signal_filter.py                Signal-Filterung
│   ├── pick_formatter.py               Pick-Formatierung
│   ├── options_chain_validator.py       Chain-Validierung
│   ├── server_core.py                  Server-Utilities
│   └── base.py                         Service-Basis
│
├── state/                              Server-Zustand
│   └── server_state.py                 Globaler State (Singleton)
│
├── utils/                              Utilities
│   ├── circuit_breaker.py              Circuit-Breaker-Pattern
│   ├── rate_limiter.py                 Rate-Limiting
│   ├── request_dedup.py                Request-Deduplication
│   ├── error_handler.py                Zentrale Fehlerbehandlung
│   ├── markdown_builder.py             Markdown-Builder
│   ├── structured_logging.py           Strukturiertes Logging
│   ├── provider_orchestrator.py        Provider-Failover
│   ├── validation.py                   Input-Validierung
│   ├── secure_config.py                Sichere Config-Handhabung
│   ├── deprecation.py                  Deprecation-Warnings
│   ├── earnings_aggregator.py          Earnings-Aggregation
│   ├── historical_cache.py             Historical-Cache-Utility
│   └── metrics.py                      Performance-Metriken
│
└── visualization/                      Charts
    └── sr_chart.py                     Support/Resistance-Charts
```

---

## 4. Modul-Referenz

### Top-Level-Module (src/)

| Modul | LOC | Verantwortlichkeit |
|-------|-----|-------------------|
| `ibkr_bridge.py` | 1.514 | Interactive Brokers TWS/Gateway Integration |
| `strike_recommender.py` | 1.289 | Optimale Strike-Auswahl (Fibonacci, Support, Delta) |
| `mcp_tool_registry.py` | 1.081 | 108 MCP-Tool-Registrierungen |
| `mcp_server.py` | 905 | Server-Klasse mit Mixin-Composition |
| `spread_analyzer.py` | 774 | Bull-Put-Spread-Bewertung |
| `vix_strategy.py` | 739 | VIX-basierte Strategie-Auswahl |
| `data_collector.py` | 482 | Daten-Pipeline (VIX, Prices) |
| `container.py` | 451 | Dependency-Injection-Container |

### Package-Übersicht

| Package | Module | LOC | Zweck |
|---------|--------|-----|-------|
| `backtesting/` | 44 | 17.611 | Backtesting-Engine + Training |
| `handlers/` | 13 | ~4.500 | MCP-Handler (Mixins) |
| `services/` | 15 | ~5.000 | Business-Logik |
| `analyzers/` | 10 | ~3.500 | Strategie-Analyse |
| `indicators/` | 9 | ~2.800 | Technische Indikatoren |
| `data_providers/` | 7 | ~2.500 | Datenquellen |
| `cache/` | 10 | ~2.000 | Caching-Layer |
| `models/` | 9 | ~1.800 | Domain-Modelle |
| `config/` | 8 | ~1.500 | Konfiguration |
| `constants/` | 7 | ~1.200 | Trading-Konstanten |
| `utils/` | 14 | ~2.500 | Hilfs-Utilities |
| `formatters/` | 3 | ~1.000 | Ausgabe-Formatierung |

---

## 5. Backtesting Sub-Packages (Phase 6)

### Gesamtstruktur nach Refactoring

```
src/backtesting/                         17.611 LOC | 7 Sub-Packages | 83 Klassen
│
├── models/                              2.849 LOC — Reine Datenmodelle
│   ├── regime_config.py     (904)       RegimeConfig, RegimeType, FIXED_REGIMES, etc.
│   ├── regime_model.py      (752)       RegimeModel, TradingParameters, TradeDecision
│   ├── ensemble_models.py   (414)       StrategyScore, EnsembleRecommendation, etc.
│   ├── training_models.py   (381)       RegimeTrainingConfig, StrategyPerformance, etc.
│   ├── outcomes.py          (265)       SpreadOutcome, OptionQuote, SpreadEntry, etc.
│   ├── ensemble_selector.py  (18)       ← Re-export Stub (Phase 6d)
│   └── __init__.py          (135)       Aggregiert alle Models
│
├── core/                                2.788 LOC — Engine + Fundamentals
│   ├── engine.py          (1.240)       BacktestEngine (Walk-Forward-Loop)
│   ├── metrics.py           (692)       PerformanceMetrics, Sharpe, Sortino, etc.
│   ├── simulator.py         (546)       TradeSimulator, PriceSimulator
│   ├── spread_engine.py     (250)       SpreadFinder, OutcomeCalculator
│   ├── database.py          (192)       OptionsDatabase (SQLite-Zugriff)
│   └── __init__.py           (68)       Re-exports
│
├── simulation/                          2.109 LOC — Options-Simulation
│   ├── options_backtest.py (1.196)      RealOptionsBacktester + 15 Convenience-Funktionen
│   ├── options_simulator.py  (746)      OptionsSimulator (Black-Scholes + NumPy-Batch)
│   ├── real_options_backtester.py (76)  ← Re-export Stub (Phase 6c)
│   └── __init__.py           (91)       Re-exports
│
├── training/                            3.390 LOC — Walk-Forward + ML
│   ├── walk_forward.py    (1.131)       WalkForwardTrainer (epoch-basiert)
│   ├── ml_weight_optimizer.py (1.093)   MLWeightOptimizer (Component-Gewichte)
│   ├── trainer.py           (534)       RegimeTrainer Facade (Phase 6e)
│   ├── epoch_runner.py      (240)       EpochRunner (Epoch-Generierung + Simulation)
│   ├── optimizer.py         (200)       ParameterOptimizer + ResultProcessor
│   ├── data_prep.py         (129)       DataPrep (VIX-Normalisierung, Segmentierung)
│   ├── performance.py       (122)       PerformanceAnalyzer (Metriken, Overfit)
│   ├── regime_trainer.py     (28)       ← Re-export Stub (Phase 6e)
│   └── __init__.py           (73)       Re-exports
│
├── validation/                          1.840 LOC — Signal-Validierung
│   ├── signal_validation.py (1.076)     SignalValidator, StatisticalCalculator
│   ├── reliability.py       (725)       ReliabilityScorer (Score-Zuverlässigkeit)
│   └── __init__.py           (39)       Re-exports
│
├── ensemble/                            1.144 LOC — Strategy-Auswahl
│   ├── selector.py          (706)       EnsembleSelector (5 Selection-Methoden)
│   ├── meta_learner.py      (268)       MetaLearner (Symbol-spezifisch)
│   ├── rotation_engine.py   (152)       StrategyRotationEngine (Performance-Tracking)
│   └── __init__.py           (18)       Re-exports
│
├── tracking/                            2.294 LOC — Trade-Tracking + Storage
│   ├── tracker.py           (485)       TradeTracker Facade (Phase 6b)
│   ├── trade_crud.py        (383)       TradeCRUD (add, get, close, update, delete)
│   ├── trade_analysis.py    (325)       TradeAnalysis (Stats, Export, Buckets)
│   ├── options_storage.py   (313)       OptionsStorage (Option-Bars)
│   ├── models.py            (282)       TrackedTrade, TradeStats, PriceBar, etc.
│   ├── price_storage.py     (216)       PriceStorage (zlib-komprimiert)
│   ├── vix_storage.py       (166)       VixStorage
│   ├── analytics.py          (58)       Analytics-Utilities
│   └── __init__.py           (66)       Re-exports
│
└── data_collector.py                      482 LOC — Daten-Pipeline
```

### Facade-Pattern-Übersicht

| Facade | Datei | Delegiert an | Methoden |
|--------|-------|-------------|----------|
| `TradeTracker` | `tracking/tracker.py` | TradeCRUD, TradeAnalysis, PriceStorage, VixStorage, OptionsStorage | 36 One-Line-Delegates |
| `RegimeTrainer` | `training/trainer.py` | DataPrep, EpochRunner, PerformanceAnalyzer, ParameterOptimizer, ResultProcessor | train(), save(), load(), get_current_regime() |
| `EnsembleSelector` | `ensemble/selector.py` | MetaLearner, StrategyRotationEngine | get_recommendation(), update_with_result(), 5 Selection-Methoden |

### Re-Export Stubs (Backward-Kompatibilität)

| Stub | Zeilen | Original LOC | Phase |
|------|--------|-------------|-------|
| `simulation/real_options_backtester.py` | 76 | 1.666 | 6c |
| `models/ensemble_selector.py` | 18 | 1.205 | 6d |
| `training/regime_trainer.py` | 28 | 1.076 | 6e |

---

## 6. Datenbank-Schema

### `~/.optionplay/trades.db` (~8.6 GB, SQLite)

| Tabelle | Datensätze | Zeitraum |
|---------|-----------|----------|
| `options_prices` | 19.3 Mio | 2021-01 – 2026-01 |
| `options_greeks` | 19.6 Mio | 2021-01 – 2026-01 |
| `earnings_history` | ~8.500 | 343 Symbole |
| `symbol_fundamentals` | 357 | Stability, Beta, etc. |
| `vix_data` | 1.385 | 2020-07 – 2026-01 |

### `~/.optionplay/outcomes.db`

| Tabelle | Datensätze | Beschreibung |
|---------|-----------|-------------|
| `trade_outcomes` | 17.438 | Backtestete Bull-Put-Spreads |

### Wichtige Gotchas

- **VIX-Spalte:** `vix_data.value` (NICHT `close`)
- **Underlying-Preise:** `options_prices.underlying_price` verwenden (NICHT `price_data`)
- **Greeks-Join:** `options_greeks.options_price_id = options_prices.id`
- **Earnings AMC:** Bei After-Market-Close am Tag X ist Tag X NICHT sicher (Reaktion erst X+1)

---

## 7. Abhängigkeiten

### Produktions-Abhängigkeiten (7 Packages — minimaler Footprint)

| Package | Version | Zweck |
|---------|---------|-------|
| `aiohttp` | ≥3.9.0 | Async HTTP für API-Calls |
| `numpy` | ≥1.24.0 | Numerische Berechnung, Batch-Operations |
| `pyyaml` | ≥6.0 | YAML-Konfiguration |
| `mcp` | ≥1.0.0 | Model Context Protocol |
| `fastmcp` | ≥0.1.0 | Fast MCP Server |
| `pydantic` | ≥2.0.0 | Datenvalidierung |
| `python-dotenv` | ≥1.0.0 | Environment-Variablen |

### Training-only (6 Packages — nicht in Production)

| Package | Zweck |
|---------|-------|
| `pandas` | Datenmanipulation |
| `scipy` | Wissenschaftliche Berechnung |
| `yfinance` | Yahoo Finance Daten |
| `requests` | HTTP-Requests |
| `tqdm` | Progress-Bars |
| `python-dateutil` | Datum-Handling |

### Test-Abhängigkeiten

| Package | Zweck |
|---------|-------|
| `pytest` | Test-Runner |
| `pytest-asyncio` | Async-Test-Support |
| `pytest-cov` | Coverage-Reporting |
| `hypothesis` | Property-based Testing |
| `aioresponses` | HTTP-Mocking |
| `freezegun` | Time-Freezing |

### Dev-Tools

`black`, `isort`, `flake8` (+bugbear, +comprehensions), `bandit`, `mypy`, `pre-commit`

---

## 8. Import-Graph & Zirkuläre Risiken

### Sub-Package Abhängigkeitsrichtung

```
models/          ← KEINE Abhängigkeiten (reine Dataclasses)
  ↑
  ├── core/      ← models
  ├── ensemble/  ← models
  ├── tracking/  ← (self-contained, keine cross-package imports)
  │
  ├── simulation/ ← models, core
  │
  ├── training/  ← models, core, validation (!)
  │     ↕
  └── validation/ ← training (!)
```

### Zirkuläres Risiko: `validation/` ↔ `training/`

```
training/walk_forward.py  ──imports──→  validation/ (SignalValidator)
validation/reliability.py ──imports──→  training/   (WalkForwardTrainer)
```

**Risikostufe: MITTEL.** Beide sind Top-Level-Imports (nicht lazy/deferred). Funktioniert aktuell wegen Python's Module-Caching, aber die Import-Reihenfolge in `backtesting/__init__.py` ist kritisch.

**Empfehlung:** `reliability.py`s Import von `WalkForwardTrainer` lazy machen (inside Funktionskörper) oder gemeinsame Typen in `models/` extrahieren.

### Externe Abhängigkeiten aus Backtesting

| Modul | Importiert aus (außerhalb backtesting) |
|-------|---------------------------------------|
| `core/engine.py` | `src.pricing` (batch_historical_volatility, etc.) |
| `core/simulator.py` | `src.options` (BlackScholes — try/except) |
| `simulation/options_simulator.py` | `src.pricing` (batch_bs_price, etc.) |
| `data_collector.py` | `src.data_providers` (MarketDataProvider) |

---

## 9. Klassen-Inventar (src/backtesting/)

### 83 Klassen in 24 Dateien

#### core/ (9 Klassen)

| Klasse | Datei | Typ | LOC (ca.) |
|--------|-------|-----|-----------|
| `BacktestEngine` | engine.py:400 | Logic | ~840 |
| `BacktestConfig` | engine.py:63 | Dataclass | ~66 |
| `BacktestResult` | engine.py:183 | Dataclass | ~217 |
| `TradeResult` | engine.py:129 | Dataclass | ~54 |
| `TradeOutcome` | engine.py:41 | Enum | ~11 |
| `ExitReason` | engine.py:52 | Enum | ~11 |
| `PerformanceMetrics` | metrics.py:36 | Dataclass | ~656 |
| `TradeSimulator` | simulator.py:184 | Logic | ~362 |
| `PriceSimulator` | simulator.py:106 | Logic | ~78 |
| `SimulatedTrade` | simulator.py:56 | Dataclass | ~50 |
| `OptionsDatabase` | database.py:20 | Logic | ~172 |
| `SpreadFinder` | spread_engine.py:22 | Logic | ~136 |
| `OutcomeCalculator` | spread_engine.py:158 | Logic | ~93 |

#### models/ (25 Klassen)

| Klasse | Datei | Typ |
|--------|-------|-----|
| `RegimeConfig` | regime_config.py | Dataclass |
| `RegimeType` | regime_config.py | Enum |
| `RegimeBoundaryMethod` | regime_config.py | Enum |
| `RegimeState` | regime_config.py | Dataclass |
| `RegimeTransition` | regime_config.py | Dataclass |
| `TrainedStrategyConfig` | regime_config.py | Dataclass |
| `TrainedRegimeConfig` | regime_config.py | Dataclass |
| `TrainedModelLoader` | regime_config.py | Logic |
| `RegimeModel` | regime_model.py | Logic |
| `TradingParameters` | regime_model.py | Dataclass |
| `TradeDecision` | regime_model.py | Dataclass |
| `RegimeStatus` | regime_model.py | Dataclass |
| `SelectionMethod` | ensemble_models.py | Enum |
| `RotationTrigger` | ensemble_models.py | Enum |
| `StrategyScore` | ensemble_models.py | Dataclass |
| `EnsembleRecommendation` | ensemble_models.py | Dataclass |
| `SymbolPerformance` | ensemble_models.py | Dataclass |
| `RotationState` | ensemble_models.py | Dataclass |
| `RegimeTrainingConfig` | training_models.py | Dataclass |
| `StrategyPerformance` | training_models.py | Dataclass |
| `RegimeEpochResult` | training_models.py | Dataclass |
| `RegimeTrainingResult` | training_models.py | Dataclass |
| `FullRegimeTrainingResult` | training_models.py | Dataclass |
| `SpreadOutcome` | outcomes.py | Enum |
| `OptionQuote` | outcomes.py | Dataclass |
| `SpreadEntry` | outcomes.py | Dataclass |
| `SpreadOutcomeResult` | outcomes.py | Dataclass |
| `SetupFeatures` | outcomes.py | Dataclass |
| `BacktestTradeRecord` | outcomes.py | Dataclass |

#### ensemble/ (3 Klassen)

| Klasse | Datei | Methoden |
|--------|-------|----------|
| `EnsembleSelector` | selector.py | get_recommendation, 5 Selection-Methoden, scoring, insights |
| `MetaLearner` | meta_learner.py | predict_best_strategy, update_performance, save, load |
| `StrategyRotationEngine` | rotation_engine.py | record_trade_result, check_rotation, get_preferences |

#### tracking/ (8 Klassen)

| Klasse | Datei | Methoden |
|--------|-------|----------|
| `TradeTracker` | tracker.py | 36 delegate-Methoden (Facade) |
| `TradeCRUD` | trade_crud.py | add, get, close, update, delete, query, count |
| `TradeAnalysis` | trade_analysis.py | stats, export, buckets |
| `PriceStorage` | price_storage.py | store, get, list, delete (zlib) |
| `VixStorage` | vix_storage.py | store, get, get_at_date, range, count |
| `OptionsStorage` | options_storage.py | store, get, list, delete, count |
| `TrackedTrade` | models.py | Dataclass |
| `TradeStats` | models.py | Dataclass |

#### training/ (12 Klassen)

| Klasse | Datei | Typ |
|--------|-------|-----|
| `RegimeTrainer` | trainer.py | Facade |
| `DataPrep` | data_prep.py | Logic |
| `EpochRunner` | epoch_runner.py | Logic |
| `PerformanceAnalyzer` | performance.py | Logic |
| `ParameterOptimizer` | optimizer.py | Logic |
| `ResultProcessor` | optimizer.py | Logic |
| `WalkForwardTrainer` | walk_forward.py | Logic |
| `MLWeightOptimizer` | ml_weight_optimizer.py | Logic |
| `WeightedScorer` | ml_weight_optimizer.py | Logic |
| `FeatureExtractor` | ml_weight_optimizer.py | Logic |
| `TrainingConfig` | walk_forward.py | Dataclass |
| `TrainingResult` | walk_forward.py | Dataclass |

#### validation/ (7 Klassen)

| Klasse | Datei | Typ |
|--------|-------|-----|
| `SignalValidator` | signal_validation.py | Logic |
| `StatisticalCalculator` | signal_validation.py | Logic |
| `ScoreBucketStats` | signal_validation.py | Dataclass |
| `ComponentCorrelation` | signal_validation.py | Dataclass |
| `RegimeBucketStats` | signal_validation.py | Dataclass |
| `SignalReliability` | signal_validation.py | Dataclass |
| `ReliabilityScorer` | reliability.py | Logic |

---

## 10. Code-Metriken

### Gesamtübersicht

| Metrik | Wert |
|--------|------|
| **Gesamt-LOC (src/)** | 88.186 |
| **Module (src/)** | 155 |
| **Packages** | 18 |
| **Klassen (backtesting/)** | 83 |
| **Test-Dateien** | 133 |
| **Test-Funktionen** | 6.748 |
| **Test-Coverage** | 80.19% |
| **MCP-Tools** | 53 + 55 Aliase |

### Größte Dateien (src/)

| Datei | LOC | Anmerkung |
|-------|-----|-----------|
| `ibkr_bridge.py` | 1.514 | IBKR-Integration (Phase 7 Kandidat) |
| `strike_recommender.py` | 1.289 | Strike-Empfehlungen |
| `core/engine.py` | 1.240 | Backtesting-Engine (Phase 7 Kandidat) |
| `simulation/options_backtest.py` | 1.196 | Real-Options-Backtester |
| `training/walk_forward.py` | 1.131 | Walk-Forward-Trainer (Phase 7 Kandidat) |
| `training/ml_weight_optimizer.py` | 1.093 | ML-Optimizer (Phase 7 Kandidat) |
| `validation/signal_validation.py` | 1.076 | Signal-Validierung |
| `mcp_tool_registry.py` | 1.081 | Tool-Registrierungen |

### LOC-Verteilung nach Package

| Package | LOC | Anteil |
|---------|-----|--------|
| `backtesting/` | 17.611 | 20.0% |
| `handlers/` | ~4.500 | 5.1% |
| `services/` | ~5.000 | 5.7% |
| `analyzers/` | ~3.500 | 4.0% |
| `indicators/` | ~2.800 | 3.2% |
| `data_providers/` | ~2.500 | 2.8% |
| Top-Level-Module | 8.002 | 9.1% |
| Restliche Packages | ~44.273 | 50.1% |

### Refactoring-Ergebnis (Phase 6)

| Metrik | Vorher | Nachher |
|--------|--------|---------|
| Größte Datei (backtesting/) | 1.899 LOC | 1.240 LOC* |
| Sub-Packages | 0 (flach) | 7 |
| Monolithische Dateien (>1000 LOC) | 5 | 5** |
| Re-export Stubs | 0 | 3 |
| Klassen pro größte Datei | 4+ | 1–2 |

\* `core/engine.py` (Phase 7 Kandidat)
\** Noch in `walk_forward.py`, `ml_weight_optimizer.py`, `signal_validation.py`, `options_backtest.py`, `engine.py` — Phase 7 Scope

---

## 11. Test-Architektur

### Verzeichnisstruktur (Phase 4.1 reorganisiert)

```
tests/
├── conftest.py                   Shared Fixtures
├── unit/          35 Dateien     Isolierte Funktions-Tests
├── component/     36 Dateien     Modul-Integrations-Tests
├── integration/   51 Dateien     Cross-Modul-Tests
└── system/        11 Dateien     End-to-End-Tests
```

### Test-Verteilung

| Kategorie | Dateien | Funktionen | Fokus |
|-----------|---------|------------|-------|
| `unit/` | 35 | 2.017 | Einzelne Funktionen, Berechnungen |
| `component/` | 36 | 1.596 | Einzelne Module, Klassen |
| `integration/` | 51 | 2.802 | Cross-Modul-Interaktion |
| `system/` | 11 | 333 | E2E-Workflows, MCP-Server |
| **Gesamt** | **133** | **6.748** | |

### Test-Frameworks

- **pytest** + pytest-asyncio (async tests)
- **hypothesis** (Property-based Testing)
- **freezegun** (Zeitabhängige Tests)
- **aioresponses** (HTTP-Mocking)

### Bekannte Test-Failures

18 E2E-Tests in `tests/system/test_mcp_server_e2e.py` schlagen fehl — diese benötigen eine aktive Netzwerk-/API-Verbindung und sind Infrastruktur-Tests, keine Code-Bugs.

---

## 12. Refactoring-Historie (Phase 1–6)

### Chronologische Commit-Historie

| Commit | Phase | Beschreibung |
|--------|-------|-------------|
| `1aeb9d2` | 4 | 80.19% Test Coverage erreicht |
| `d53c4b3` | 4.2-4.4 | mypy --strict Type Hints |
| `878acc0` | 4.1 | 132 Test-Dateien reorganisiert |
| `416b9f3` | 4.5 | DB Performance Benchmarks |
| `da4fc7a` | 3.1 | RSI/ATR Duplikation eliminiert |
| `f522572` | 3.2 | 26 SQL-Konstanten extrahiert |
| `7aa54d9` | 3.3 | Scanner-Caches → @cached_property |
| `2a715ee` | 3.4 | FeatureScoringMixin |
| `89f518c` | 3.5 | Pick-Formatter extrahiert |
| `c9a497a` | 5 | Duplikation, Architektur, Performance |
| `6820e79` | 5+6a | Sub-Packages + Models extrahiert |
| `f72b92f` | 6b | TradeTracker → Facade + 5 Module |
| `017cebe` | 6c | RealOptionsBacktester → core/ + simulation/ |
| `a88e4f1` | 6d | EnsembleSelector → ensemble/ |
| `d53989e` | 6e | RegimeTrainer → training/ Sub-Module |

### Phase 6 Statistiken

| Phase | Dateien geändert | +Zeilen | -Zeilen | Monolith aufgebrochen |
|-------|-----------------|---------|---------|----------------------|
| 5+6a | 92 | 4.427 | 3.132 | Models extrahiert |
| 6b | 7 | 1.494 | 1.116 | TradeTracker (1.530→485) |
| 6c | 5 | 1.719 | 1.657 | RealOptionsBacktester (1.666→76) |
| 6d | 5 | 1.162 | 1.205 | EnsembleSelector (1.205→18) |
| 6e | 7 | 1.260 | 1.069 | RegimeTrainer (1.076→28) |
| **Σ** | **116** | **10.062** | **7.179** | **4 Monolithen → 18 Module** |

---

## 13. Bekannte Probleme & Technische Schulden

### KRITISCH

| ID | Problem | Betrifft |
|----|---------|---------|
| **CIRC-01** | Zirkuläre Imports: `validation/reliability.py` ↔ `training/walk_forward.py` | Import-Reihenfolge-sensitiv |

### HOCH

| ID | Problem | LOC | Empfehlung |
|----|---------|-----|------------|
| **SIZE-01** | `core/engine.py` — 1.240 LOC, 1 große Klasse | Phase 7 | Aufbrechen |
| **SIZE-02** | `training/walk_forward.py` — 1.131 LOC | Phase 7 | Aufbrechen |
| **SIZE-03** | `training/ml_weight_optimizer.py` — 1.093 LOC | Phase 7 | Aufbrechen |
| **SIZE-04** | `validation/signal_validation.py` — 1.076 LOC | Phase 7 | Aufbrechen |
| **SIZE-05** | `simulation/options_backtest.py` — 1.196 LOC | Phase 7 | Aufbrechen |
| **DEBT-003** | Blocking SQLite in async handlers (asyncio.to_thread) | Performance | Async SQLite (aiosqlite) |
| **DEBT-005** | Mixin→Composition Migration nicht abgeschlossen | Architektur | handler_container.py |

### MITTEL

| ID | Problem | Empfehlung |
|----|---------|------------|
| **VER-01** | Versionskonflikt: `pyproject.toml` sagt 3.7.0, `src/__init__.py` sagt 4.0.0 | Vereinheitlichen |
| **DEBT-012** | 5 Dateien >1000 LOC in backtesting/ (Phase 7 Scope) | Priorisieren |
| **DEBT-015** | `ibkr_bridge.py` — 1.514 LOC, schwer testbar | Aufbrechen |
| **DEBT-018** | `strike_recommender.py` — 1.289 LOC | Aufbrechen |
| **E2E-01** | 18 E2E-Tests benötigen Netzwerk/API | Mocking oder Skip-Marker |

### NIEDRIG

| ID | Problem |
|----|---------|
| **LANG-01** | Gemischte Sprache: Deutsch (Docstrings in backtesting/) + Englisch |
| **INIT-01** | Große `__init__.py` Dateien (bis 372 LOC) — potenziell langsamer Import |

---

## 14. Empfehlungen für Code Review

### Architektur-Review Fokuspunkte

1. **Zirkuläre Import-Auflösung** (CIRC-01): `validation/reliability.py` → `training/` Import lazy machen
2. **Phase 7 Priorisierung**: Die 5 verbleibenden >1000 LOC Dateien sollten in der Reihenfolge `engine.py` → `walk_forward.py` → `ml_weight_optimizer.py` aufgebrochen werden
3. **Async SQLite**: `asyncio.to_thread()` als Workaround evaluieren vs. `aiosqlite` Migration
4. **Mixin→Composition**: `handler_container.py` existiert bereits — Migration der 13 Mixins prüfen

### Code-Quality Highlights (positiv)

- **Saubere Facade-Pattern** in tracking/, training/, ensemble/
- **Strikte Backward-Kompatibilität** via Re-export Stubs
- **80.19% Test Coverage** mit 6.748 Tests
- **mypy --strict** auf Hub-Modulen
- **Klare Schichten-Trennung**: Handler → Service → Analyzer → Provider
- **Minimaler Production-Footprint**: Nur 7 Dependencies

### Vorgeschlagene Review-Reihenfolge

1. `src/backtesting/models/` — Datenmodelle als Basis verstehen
2. `src/backtesting/core/engine.py` — Zentraler Algorithmus
3. `src/backtesting/ensemble/selector.py` — Strategy-Auswahl-Logik
4. `src/handlers/` + `src/services/` — Request-Flow verstehen
5. `src/analyzers/` — Strategy-Implementierungen
6. `src/backtesting/training/` — ML/Training-Pipeline
7. `tests/integration/` — Wie das System zusammenspielt

---

## 15. Code Review Ergebnisse (2026-02-06)

### Gesamtbewertung

| Kategorie | Note | Begründung |
|-----------|------|------------|
| **Code-Qualität** | **B+** | Saubere Patterns, gute SoC, konsequente Fehlerbehandlung. Abzug: >1000 LOC Dateien, gemischte Sprachen |
| **Logik / Korrektheit** | **A-** | Solide Trading-Logik, ML-validierte Scoring-Formeln, Walk-Forward korrekt. Abzug: CIRC-01 |
| **Architektur** | **A-** | Excellente Schichtenarchitektur, DI-Container, Facade-Pattern. Abzug: Mixin-Migration unvollständig |
| **Weighting-Flexibilität** | **B** | Dreistufiges System (ML-Weights + Rule-Based), aber Komponenten-Gewichte hardcoded |

### Architektur-Stärken

- **Klare Schichtenarchitektur**: Handler → Service → Analyzer → Provider
- **DI-Container** mit 3 Factory-Methoden (default, testing, minimal)
- **Resilience-Patterns**: Circuit Breaker + Rate Limiter + Request Dedup + Multi-Provider-Fallback
- **Facade-Pattern im Backtesting**: TradeTracker, RegimeTrainer, EnsembleSelector
- **Minimaler Production-Footprint**: Nur 7 Runtime-Dependencies
- **Fehlerbehandlung**: 12 Exception-Typen mit retryable-Flag und User-Formatting
- **80.19% Test Coverage** mit hypothesis Property-based Testing

### Identifizierte Issues

| ID | Schwere | Problem | Empfehlung |
|----|---------|---------|------------|
| **CIRC-01** | KRITISCH | Zirkulärer Import validation ↔ training | Lazy Import in reliability.py |
| **VER-01** | Mittel | Version 3.7.0 vs 4.0.0 | Vereinheitlichen |
| **WEIGHT-01** | Mittel | Scoring-Gewichte hardcoded in Analyzern | Externalisieren in YAML/JSON Config |
| **STATE-01** | Niedrig | ServerState Dataclass nicht in mcp_server.py integriert | Migration der gestreuten Variablen |
| **DEBT-004** | Mittel | 11 Mixins mit 22 Interface-Methoden, Composition-Bridge ungenutzt | Composition primär machen |

### Scoring-System Detailanalyse

**Dreistufig:**
1. Komponenten-Scoring (Pullback: 26 Max, Bounce: 27, Breakout: 23, Dip: 21)
2. ML-Trained Weights via FeatureScoringMixin (VWAP, Market Context, Sector, Gap)
3. Ranking: `0.7 * signal + 0.3 * stability × speed_multiplier`

**Flexibilität:**
- ML-Weights per JSON editierbar (geringer Aufwand, hoher Impact)
- Stability/Speed-Gewichtung als Config-Parameter (geringer Aufwand)
- Komponenten-Punktzahlen hardcoded (mittlerer Aufwand, hoher Impact) → WEIGHT-01
- ML-Retraining via Pipeline (hoher Aufwand, hoher Impact)

### Empfohlene Prioritäten für Phase 7

1. **CIRC-01 lösen** — 30 Min Aufwand, eliminiert kritischstes Risiko
2. **WEIGHT-01** — Komponenten-Gewichte in Config auslagern (größter Hebel für Weighting-Flexibilität)
3. **VER-01** — Version vereinheitlichen
4. **engine.py aufbrechen** — 1,240 LOC → Simulation + Reporting + Core
5. **walk_forward.py aufbrechen** — 1,131 LOC → Config + Training + Validation

---

*Generiert am 6. Februar 2026 nach Abschluss von Phase 6 (Backtesting-Monolith aufbrechen).*
*Code Review am 6. Februar 2026 durchgeführt.*
