# OptionPlay - Architecture

**Version:** 5.0.0
**Status:** Production MCP Server

---

## System Overview

OptionPlay is a Bull-Put-Spread analysis system operating as an MCP Server for Claude integration.

**3 Jobs:**

| Job | Beschreibung | Wann |
|-----|-------------|------|
| **Daily Picks** | 3-5 fertige Setups mit Strikes, Credit-Ziel, Stop-Loss | Morgens vor Marktöffnung |
| **Trade Validator** | GO / NO-GO / WARNING für eigene Trade-Ideen | Vor jedem Trade |
| **Position Manager** | Offene Trades überwachen, Exit-Signale, Roll-Empfehlungen | Täglich |

Alle Trading-Regeln → `docs/PLAYBOOK.md`
DB-Schema & Code-Details → `CLAUDE.md`

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           MCP SERVER                                 │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    OptionPlayServer                            │  │
│  │  (Composition-based handlers via HandlerContainer)            │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┼────────────────────────────────────┐  │
│  │                     HANDLER LAYER                              │  │
│  │  VIX │ Scan │ Quote │ Analysis │ Portfolio │ Risk              │  │
│  │  Validate │ Monitor │ Report │ IBKR                            │  │
│  └──────┼──────┼───────┼──────────┼──────────┼──────────────────┘  │
│         │      │       │          │          │                      │
│  ┌──────┴──────┴───────┴──────────┴──────────┴──────────────────┐  │
│  │                     SERVICE LAYER                              │  │
│  │  VIX │ VIXRegime │ SectorRS │ Scanner │ Recommender │ Monitor │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┼───────────────────────────────────┐  │
│  │                     ANALYZER LAYER                             │  │
│  │  Pullback │ Bounce                                            │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┼───────────────────────────────────┐  │
│  │                     DATA LAYER                                 │  │
│  │  IBKR Provider (Primär) │ Yahoo Finance │ Local DB Provider  │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┼───────────────────────────────────┐  │
│  │                     INFRASTRUCTURE                             │  │
│  │  Rate Limiter │ Circuit Breaker │ Cache │ Error Handler        │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         │                                           │
         ▼                                           ▼
┌─────────────────────┐              ┌─────────────────────┐
│  trades.db (8.6 GB) │              │   outcomes.db (ML)  │
│  options_prices 19M │              │  trade_outcomes 17K │
│  options_greeks 19M │              └─────────────────────┘
│  symbol_fundamentals│
│  earnings_history   │              ┌─────────────────────┐
│  vix_data           │              │  IBKR Bridge (opt.) │
└─────────────────────┘              │  News, Max Pain,    │
                                     │  Live VIX, Portfolio│
                                     └─────────────────────┘

Alle 3 Kern-Services (Validator, Monitor, Recommender) sind implementiert.
```

---

## Module Structure

```
src/                                    156 Module | 67,723 LOC
├── mcp_server.py                       (Server-Klasse)
├── mcp_tool_registry.py                (25 Tools + 28 Aliases)
├── mcp_main.py                         (255 LOC — Entry Point)
├── container.py                        (451 LOC — DI Container)
├── ibkr_bridge.py                      (1,514 LOC — Interactive Brokers)
├── spread_analyzer.py                  (774 LOC — Spread-Bewertung)
├── strike_recommender.py               (1,289 LOC — Strike-Empfehlungen)
├── vix_strategy.py                     (739 LOC — VIX-Strategie-Logik)
├── watchlist_loader.py                 (277 LOC — Watchlist-Management)
│
├── handlers/                           14 Dateien — MCP Tool Handlers
│   ├── vix.py                         VIX, Regime, Strategy
│   ├── vix_composed.py                Komponierte VIX-Handler
│   ├── scan.py                        Scan + Daily Picks
│   ├── quote.py                       Quotes, Options, Historical
│   ├── analysis.py                    Symbol-Analyse
│   ├── portfolio.py                   Portfolio-Management
│   ├── risk.py                        Position Sizing, Stop Loss
│   ├── validate.py                    Trade Validator (GO/NO-GO)
│   ├── monitor.py                     Position Monitor (Exit-Signale)
│   ├── report.py                      PDF-Report-Generierung
│   ├── ibkr.py                        IBKR Bridge Handler
│   ├── base.py                        Abstrakte Basis (22 Interface-Methoden)
│   └── handler_container.py           Composition-based (Migration)
│
├── services/                           17 Dateien — Business Logic
│   ├── vix_service.py                 VIX-Daten + Regime-Erkennung
│   ├── vix_regime.py                  VIX Regime v2 (Interpolation, Term Structure)
│   ├── vix_strategy.py                VIX Strategy Selector (v1+v2 Pfad)
│   ├── sector_rs.py                   Sector RS mit RRG-Quadranten
│   ├── scanner_service.py             Multi-Strategy Scanning
│   ├── options_service.py             Options-Analyse
│   ├── recommendation_engine.py       Daily Picks + Strikes
│   ├── trade_validator.py             Trade Validator (PLAYBOOK-Regeln)
│   ├── position_monitor.py            Position Monitor (Exit-Signale)
│   ├── portfolio_constraints.py       Portfolio-Limits + Sizing
│   ├── enhanced_scoring.py            Enhanced Scoring (multiplicative)
│   ├── pick_formatter.py              Pick-Formatierung
│   └── options_chain_validator.py     Chain-Validierung
│
├── analyzers/                          9 Dateien — 2 Trading-Strategien
│   ├── pullback.py                    Pullback im Aufwärtstrend
│   ├── pullback_scoring.py            Pullback-Scoring-Komponenten
│   ├── bounce.py                      Support Bounce
│   ├── feature_scoring_mixin.py       ML-trained Scoring (VWAP, Market, Sector, Gap)
│   ├── score_normalization.py         Cross-Strategy Scoring (0-10 Skala)
│   ├── batch_scorer.py                Batch-Scoring für Scanner
│   ├── context.py                     Analysis-Kontext
│   ├── pool.py                        Analyzer-Pool (2 Factories)
│   └── base.py                        Abstrakte Basis
│
├── scanner/                            Multi-Strategy Scanner
│   ├── multi_strategy_scanner.py
│   ├── multi_strategy_ranker.py
│   └── signal_aggregator.py
│
├── cache/                              Caching Layer
│   ├── cache_manager.py               Zentrale Cache-Verwaltung
│   ├── earnings_cache.py              Earnings-Termine
│   ├── symbol_fundamentals.py         Fundamentals + Stability
│   ├── historical_cache.py            Price Data Cache
│   └── vix_cache.py                   VIX History
│
├── data_providers/                     Datenquellen-Abstraktion
│   ├── interface.py                   DataProvider ABC
│   ├── ibkr_provider.py              IBKR TWS (Primär, Port 7497)
│   ├── local_db.py                    SQLite Local DB (Historisch)
│   ├── fundamentals.py               Fundamentaldaten-Provider
│   └── yahoo_news.py                  Yahoo Finance News
│
├── constants/                          Zentrale Konfiguration
│   ├── trading_rules.py               Exit-Regeln, VIX-Regime, Sizing
│   ├── technical_indicators.py        Indikator-Parameter
│   ├── risk_management.py             Risiko-Parameter
│   ├── strategy_parameters.py         Strategie-Defaults
│   └── thresholds.py                  Score-Schwellen
│
├── models/                             Domain-Modelle
│   ├── base.py                        TradeSignal, SignalType
│   ├── candidates.py                  Kandidaten-Modelle
│   ├── options.py                     Options-Modelle
│   └── strategy.py                    Strategie-Modelle
│
└── utils/                              14 Dateien — Utilities
    ├── rate_limiter.py                Adaptive Rate Limiting
    ├── circuit_breaker.py             Fault Tolerance
    ├── error_handler.py               Exception Handling (12 Exception-Typen)
    ├── request_dedup.py               Request-Deduplication
    ├── provider_orchestrator.py       Provider-Failover
    └── structured_logging.py          Strukturiertes Logging
```

---

## Database Overview

| DB | Tabelle | Records | Zweck |
|----|---------|---------|-------|
| trades.db | `options_prices` | 19.3M | Historische Optionspreise |
| trades.db | `options_greeks` | 19.6M | Greeks (Delta, Gamma, Theta, Vega, IV) |
| trades.db | `symbol_fundamentals` | 357 | Fundamentals + Stability Scores |
| trades.db | `earnings_history` | 8,500 | Earnings mit EPS |
| trades.db | `vix_data` | 1,385 | VIX-Tageswerte |
| outcomes.db | `trade_outcomes` | 17,438 | Backtestete Trades (ML-Training) |

**Zeitraum:** 2021-01 bis 2026-01 | **Detailliertes Schema** → `CLAUDE.md`

---

## Configuration

Alle Parameter extern in YAML (konsolidiert in v5.0.0):

| Datei | Inhalt |
|-------|--------|
| `config/trading.yaml` | Trading Rules + VIX-Profile + Roll-Strategie + Sector RS |
| `config/scoring.yaml` | Scoring Weights + Analyzer Thresholds + Enhanced Scoring + RSI + Validation |
| `config/system.yaml` | Settings + Scanner Config + Liquidity Blacklist |
| `config/watchlists.yaml` | Symbol-Listen (default_275, extended_600) |

---

## Codebase-Metriken (Stand 2026-04-07, v5.0.0)

| Bereich | Python-Dateien | Zeilen |
|---------|---------------|--------|
| **src/** | 156 | 67,723 |
| **tests/** | 135 | ~50,000 |

### Größte Subsysteme in src/

| Subsystem | Dateien | Beschreibung |
|-----------|---------|--------------|
| handlers/ | ~14 | MCP Tool Handler (Composition via HandlerContainer) |
| services/ | ~17 | VIX, Scanner, Options, Recommender, Validator, Monitor |
| analyzers/ | 9 | 2 Strategy Analyzer + FeatureScoringMixin + Utilities |
| indicators/ | ~9 | Support/Resistance, MACD, RSI, etc. |
| data_providers/ | 5 | IBKR TWS (Primär), Local DB, Yahoo News |
| cache/ | ~10 | Earnings, IV, Fundamentals, VIX, Dividends |
| models/ | ~9 | Domain-Modelle |
| constants/ | ~7 | Trading-Konstanten (YAML-externalisiert) |
| utils/ | ~14 | Rate Limiter, Error Handler, etc. |
| Top-Level (src/) | ~8 | MCP Server, Container, IBKR Bridge, etc. |

---

## Technical Debt

### Erledigt (seit v3.5.0)

| ID | Problem | Erledigt in |
|----|---------|-------------|
| ~~DEBT-001~~ | Score-Predictivity unklar | v3.6.0 (Stability-basiert) |
| ~~DEBT-002~~ | Training-Scripts chaotisch | v3.6.0 (23 Scripts → 2 fast_*) |
| ~~DEBT-005~~ | Singleton-Pattern überall | v3.6.0 (DI Container) |
| ~~DEBT-006~~ | Keine einheitliche Error-Hierarchy | v3.6.0 (MCPError-Baum) |
| ~~DEBT-007~~ | Fehlende Datenmodelle | v3.6.0 (models/ Package) |
| ~~DEBT-010~~ | Kein Earnings-Prefilter | v3.5.0 (earnings_prefilter Tool) |
| ~~DEBT-011~~ | Redundante Config-Quellen | v3.6.0 (settings.yaml zentral) |

### Offen

| ID | Problem | Priorität | Aufwand | Details |
|----|---------|-----------|---------|---------|
| **CIRC-01** | ~~Zirkulärer Import validation ↔ training~~ | ✅ GELÖST | Klein | Lazy Import in `reliability.py:from_trained_model()` |
| **VER-01** | ~~Versionskonflikt 3.7.0 vs 4.0.0~~ | ✅ GELÖST | Klein | Vereinheitlicht auf 4.0.0 |
| **DEBT-003** | Blocking SQLite in async handlers | Medium | Mittel | `asyncio.to_thread()` als Workaround, `aiosqlite` für langfristige Lösung |
| **DEBT-004** | ~~Mixin → Composition Migration~~ | ✅ GELÖST | — | Composition via `HandlerContainer` aktiv, Mixins nur noch für Test-Kompatibilität |
| **WEIGHT-01** | ~~Komponenten-Gewichte hardcoded~~ | ✅ GELÖST | — | `config/scoring.yaml` + RecursiveConfigResolver (4-Layer). Alle Analyzer nutzen `self.get_weights()`. |
| **STATE-01** | ServerState nicht integriert | Low | Klein | Dataclass definiert, mcp_server.py nutzt gestreute Variablen |

### Offen (nach v5.0.0-Cleanup)

| ID | Problem | Priorität | Details |
|----|---------|-----------|---------|
| **DEBT-003** | Blocking SQLite in async handlers | Medium | `asyncio.to_thread()` als Workaround |
| **DEBT-018** | Test-Fixture-Duplikation | Low | `temp_db` in mehreren Dateien — gehört in `conftest.py` |
| **DEBT-021** | Cache-Schichten unklar | Low | `*_impl.py` + `*.py` Pattern in cache/ für Backwards-Compat |

---

## Kern-Services (implementiert)

| Service | Dateien | Beschreibung |
|---------|---------|-------------|
| **Trade Validator** | `services/trade_validator.py` + `handlers/validate.py` | GO/NO-GO/WARNING gegen PLAYBOOK-Regeln |
| **Position Monitor** | `services/position_monitor.py` + `handlers/monitor.py` | HOLD/CLOSE/ROLL/ALERT Exit-Signale |
| **Daily Picks** | `services/recommendation_engine.py` + `handlers/scan.py` | 3-5 fertige Setups mit Strikes |

---

## Scoring & Weighting-Architektur

### Dreistufiges Scoring-System

```
┌──────────────────────────────────────────────────────────┐
│  Stufe 1: Komponenten-Scoring (pro Strategie)            │
│  ─ Jeder Analyzer vergibt Punkte pro Indikator           │
│  ─ Pullback: 14.0 (P95), Bounce: 10.0 (max_possible)   │
│  ─ Normalisierung auf 0-10 via score_normalization.py    │
├──────────────────────────────────────────────────────────┤
│  Stufe 2: ML-Trained Weights (FeatureScoringMixin)       │
│  ─ Gewichte aus ~/.optionplay/models/component_weights.json │
│  ─ Per Strategie + VIX-Regime unterschiedlich             │
│  ─ Training via MLWeightOptimizer (Walk-Forward)          │
│  ─ Features: VWAP, Market Context, Sector Speed, Gap     │
├──────────────────────────────────────────────────────────┤
│  Stufe 3: Ranking (DailyRecommendationEngine)            │
│  ─ base = 0.7 * signal + 0.3 * stability                │
│  ─ final = base * speed_multiplier                        │
│  ─ stability_weight + speed_exponent konfigurierbar      │
└──────────────────────────────────────────────────────────┘
```

### Weighting-Flexibilität

| Anpassung | Ort | Aufwand |
|-----------|-----|---------|
| ML-Weights editieren | `~/.optionplay/models/component_weights.json` | Gering |
| Stability/Speed-Gewichtung | Config-Dict in recommendation_engine | Gering |
| Strategie-Parameter (RSI etc.) | `constants/strategy_parameters.py` | Gering |
| Komponenten-Punktzahlen | Analyzer-Code + score_normalization.py | Mittel |
| ML-Weights Retraining | MLWeightOptimizer Pipeline | Hoch |

**WEIGHT-01 — GELÖST:** Komponenten-Gewichte sind in `config/scoring.yaml` externalisiert. RecursiveConfigResolver bietet 4-Layer Auflösung (Base → Regime → Sector → Regime×Sector). Beide Analyzer nutzen `self.get_weights()`. Trainierte Werte liegen in `~/.optionplay/models/`.

---

## Refactoring-Historie

| Phase | Beschreibung | Status |
|-------|-------------|--------|
| **Phases 1-6** | Exceptions, Thread-Safety, Duplikation, Architektur, Qualität, Backtesting | ✅ |
| **Audit A-G** | Security, Performance, Code Quality, Architecture, Trading Logic, Testing, Optimization | ✅ |
| **v5.0.0** | Radical Cleanup: 3 Analyzer gelöscht, Backtesting entfernt, 67 Scripts auf 8 reduziert, YAML auf 4 Dateien konsolidiert, Tradier entfernt, IBKR TWS als Primär-Provider | ✅ |

---

*Alle Trading-Regeln, VIX-Regime-Details, Watchlist und Blacklist → `docs/PLAYBOOK.md`*
