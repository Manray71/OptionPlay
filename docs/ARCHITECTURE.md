# OptionPlay - Architecture

**Version:** 4.0.0
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
│  │  (Mixin-based handlers, Composition migration planned)        │  │
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
│  │  VIX │ Scanner │ Options │ Recommender │ Validator │ Monitor  │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┼───────────────────────────────────┐  │
│  │                     ANALYZER LAYER                             │  │
│  │  Pullback │ Bounce │ ATH Breakout │ Earnings Dip              │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┼───────────────────────────────────┐  │
│  │                     DATA LAYER                                 │  │
│  │  Tradier Provider │ MarketData Provider │ Local DB Provider    │  │
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
src/                                    183 Module | 80,184 LOC
├── mcp_server.py                       (905 LOC — Server-Klasse)
├── mcp_tool_registry.py                (1,081 LOC — 108 Tool-Registrierungen)
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
├── services/                           15 Dateien — Business Logic
│   ├── vix_service.py                 VIX-Daten + Regime-Erkennung
│   ├── scanner_service.py             Multi-Strategy Scanning
│   ├── options_service.py             Options-Analyse
│   ├── recommendation_engine.py       Daily Picks + Strikes
│   ├── trade_validator.py             Trade Validator (PLAYBOOK-Regeln)
│   ├── position_monitor.py            Position Monitor (Exit-Signale)
│   ├── portfolio_constraints.py       Portfolio-Limits + Sizing
│   ├── entry_quality_scorer.py        Entry-Qualitäts-Score
│   ├── iv_analyzer.py                 IV-Analyse
│   ├── signal_filter.py               Signal-Filterung
│   ├── pick_formatter.py              Pick-Formatierung
│   └── options_chain_validator.py     Chain-Validierung
│
├── analyzers/                          10 Dateien — 4 Trading-Strategien
│   ├── pullback.py                    Pullback im Aufwärtstrend
│   ├── bounce.py                      Support Bounce
│   ├── ath_breakout.py                All-Time-High Breakout
│   ├── earnings_dip.py                Post-Earnings Dip
│   ├── feature_scoring_mixin.py       ML-trained Scoring (VWAP, Market, Sector, Gap)
│   ├── score_normalization.py         Cross-Strategy Scoring (0-10 Skala)
│   ├── context.py                     Analysis-Kontext
│   ├── pool.py                        Analyzer-Pool
│   └── base.py                        Abstrakte Basis
│
├── backtesting/                        44 Dateien | 17,611 LOC | 7 Sub-Packages
│   ├── core/                          Engine, Metrics, Simulator, DB, Spread
│   ├── simulation/                    Options-Simulator, Real-Backtester
│   ├── training/                      Walk-Forward, Regime, ML-Optimizer
│   ├── validation/                    Signal-Validation, Reliability
│   ├── ensemble/                      Meta-Learner, Rotation, Selector
│   ├── tracking/                      Trade-CRUD, Price/VIX/Options-Storage
│   ├── models/                        Reine Dataclasses (25 Klassen)
│   └── data_collector.py              Daten-Pipeline (VIX, Prices)
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
│   ├── interface.py                   DataProvider ABC (16 Methoden)
│   ├── tradier.py                     Tradier API (Primär)
│   ├── marketdata.py                  MarketData.app API (Sekundär)
│   ├── local_db.py                    SQLite Local DB (Fallback)
│   └── fundamentals.py               Fundamentaldaten-Provider
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

Alle Parameter extern in YAML:

| Datei | Inhalt |
|-------|--------|
| `config/settings.yaml` | Technische Parameter (API, Filter, Scanner) |
| `config/strategies.yaml` | VIX-basierte Strategy Profiles |
| `config/watchlists.yaml` | Watchlist (275 Symbole, 11 GICS-Sektoren) |

---

## Codebase-Metriken (Stand 2026-02-06)

| Bereich | Python-Dateien | Zeilen |
|---------|---------------|--------|
| **src/** | 183 | 80,184 |
| **tests/** | 133 | ~57,000 |

### Größte Subsysteme in src/

| Subsystem | Dateien | LOC | Beschreibung |
|-----------|---------|-----|--------------|
| backtesting/ | 44 | 17,611 | ML-Training, Backtesting Engine (7 Sub-Packages nach Phase 6) |
| handlers/ | 14 | ~4,500 | MCP Tool Handler (Mixin + Composition) |
| services/ | 15 | ~5,000 | VIX, Scanner, Options, Recommender, Validator, Monitor |
| analyzers/ | 10 | ~3,500 | 4 Strategy Analyzer + FeatureScoringMixin |
| indicators/ | 9 | ~2,800 | Support/Resistance, MACD, RSI, etc. |
| data_providers/ | 7 | ~2,500 | Tradier, MarketData, Local DB |
| cache/ | 10 | ~2,000 | Earnings, IV, Fundamentals, VIX |
| models/ | 9 | ~1,800 | Domain-Modelle |
| config/ | 8 | ~1,500 | Konfiguration |
| constants/ | 7 | ~1,200 | Trading-Konstanten |
| utils/ | 14 | ~2,500 | Rate Limiter, Error Handler, etc. |
| Top-Level (src/) | 8 | ~8,000 | MCP Server, Container, IBKR Bridge, etc. |

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
| **DEBT-004** | Mixin → Composition Migration | Medium | Groß | `HandlerContainer` existiert, 11 Mixins mit 22 Interface-Methoden noch aktiv |
| **DEBT-009** | 5 Dateien >1000 LOC im Backtesting | Medium | Mittel | engine.py, walk_forward.py, ml_weight_optimizer.py, signal_validation.py, options_backtest.py |
| **DEBT-015** | Duale Black-Scholes-Implementierung | Medium | Mittel | `pricing/` (batch) + `options/` (OOP) — bewusste Trennung, aber Doku fehlt |
| **WEIGHT-01** | ~~Komponenten-Gewichte hardcoded~~ | ✅ GELÖST | — | `config/scoring_weights.yaml` + RecursiveConfigResolver (4-Layer). Alle Analyzer nutzen `self.get_weights()`. Training via `retrain_weights.py --apply`. |
| **STATE-01** | ServerState nicht integriert | Low | Klein | Dataclass definiert, mcp_server.py nutzt gestreute Variablen |

### Neu identifiziert (Code-Scan 2026-02-03)

| ID | Problem | Priorität | Aufwand | Details |
|----|---------|-----------|---------|---------|
| **DEBT-013** | Root-Level-Module nicht umgezogen | High | Mittel | 6 Module in `src/` Root statt in Subdirectories (siehe Reduktionsstrategie) |
| ~~DEBT-014~~ | `src/providers/` Stub-Package | — | — | v4.0.0 entfernt, Import auf `data_providers` umgestellt |
| **DEBT-015** | Duale Black-Scholes-Implementierung | Medium | Mittel | `pricing/black_scholes.py` (1,419 LOC, batch) + `options/black_scholes.py` (937 LOC, OOP) |
| ~~DEBT-016~~ | Orphaned `src/pullback_analyzer.py` | — | — | v4.0.0 gelöscht (876 LOC) |
| **DEBT-017** | Verwaiste Test-Dateien | Medium | Klein | ~2,280 LOC Tests für gelöschte Module (vix_strategy_fixes, config_loader, etc.) |
| **DEBT-018** | Test-Fixture-Duplikation | Low | Mittel | `temp_db` in 5 Dateien, `sample_prices` in 4 Dateien — gehört in `conftest.py` |
| **DEBT-019** | Scripts-Duplikation | Medium | Mittel | 4x SMA-Convergence-Analyse, 3x Options-Collector, 2x Diagonal-Backtest |
| **DEBT-020** | Archive-Verzeichnis im Repo | Low | Klein | 23,596 LOC veralteter Training-Code, 20 MB |
| **DEBT-021** | Cache-Schichten unklar | Low | Klein | `*_impl.py` + `*.py` Pattern in cache/ für Backwards-Compat |

### Dateien > 1,000 LOC (DEBT-009)

**Nach Phase 6 (Backtesting-Refactoring) — aktualisiert 2026-02-06:**

| Datei | LOC | Status |
|-------|-----|--------|
| `ibkr_bridge.py` | 1,514 | Top-Level, schwer testbar — Phase 7 Kandidat |
| `strike_recommender.py` | 1,289 | Top-Level — Berechnung vs Formatierung trennen |
| `backtesting/core/engine.py` | 1,240 | Phase 7 Kandidat (BacktestEngine) |
| `backtesting/simulation/options_backtest.py` | 1,196 | Phase 7 Kandidat |
| `backtesting/training/walk_forward.py` | 1,131 | Phase 7 Kandidat |
| `backtesting/training/ml_weight_optimizer.py` | 1,093 | Phase 7 Kandidat |
| `mcp_tool_registry.py` | 1,081 | 108 Tool-Registrierungen — kohärent |
| `backtesting/validation/signal_validation.py` | 1,076 | Phase 7 Kandidat |

*Phase 6 hat 4 Monolithen in 18 Module aufgebrochen (trade_tracker, real_options_backtester, ensemble_selector, regime_trainer)*

---

## Reduktionsstrategie

Siehe `docs/REDUKTIONSSTRATEGIE.md` für den vollständigen Plan.

**Zusammenfassung:**

| Phase | Aktion | LOC-Reduktion |
|-------|--------|---------------|
| Phase 1: Dead Code entfernen | Orphaned Module, verwaiste Tests | ~4,000 |
| Phase 2: Archive aufräumen | `archive/` ins Git-Archiv, `reports/` in .gitignore | ~23,600 |
| Phase 3: Scripts konsolidieren | Duplikate zusammenführen, Research archivieren | ~15,000 |
| Phase 4: Root-Module umziehen | 6 Module in korrekte Packages verschieben | 0 (Reorg) |
| Phase 5: Stubs entfernen | `src/providers/`, Cache-Compat-Layer | ~500 |
| **Geschätzte Reduktion** | | **~43,000 LOC** |

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
│  ─ Pullback: 26 Max, Bounce: 27, Breakout: 23, Dip: 21  │
│  ─ Normalisierung auf 0-10 via score_normalization.py    │
├──────────────────────────────────────────────────────────┤
│  Stufe 2: ML-Trained Weights (FeatureScoringMixin)       │
│  ─ Gewichte aus ~/.optionplay/models/weights_*.json      │
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
| ML-Weights editieren | `~/.optionplay/models/weights_*.json` | Gering |
| Stability/Speed-Gewichtung | Config-Dict in recommendation_engine | Gering |
| Strategie-Parameter (RSI etc.) | `constants/strategy_parameters.py` | Gering |
| Komponenten-Punktzahlen | Analyzer-Code + score_normalization.py | Mittel |
| ML-Weights Retraining | MLWeightOptimizer Pipeline | Hoch |

**WEIGHT-01 — GELÖST:** Komponenten-Gewichte sind in `config/scoring_weights.yaml` externalisiert. RecursiveConfigResolver bietet 4-Layer Auflösung (Base → Regime → Sector → Regime×Sector). Alle 4 Analyzer nutzen `self.get_weights()`. Training-Pipeline (`retrain_weights.py --apply`) schreibt trainierte Werte direkt in YAML.

---

## Refactoring-Historie (Phase 1-6)

| Phase | Beschreibung | Status |
|-------|-------------|--------|
| **Phase 0** | Hygiene — Git, Dead Code, Versionierung | ✅ |
| **Phase 1** | Absicherung — Exceptions, Thread-Safety, async SQLite | ✅ |
| **Phase 2** | Duplikation — Indikatoren, BS, Earnings | ⚠️ Teilweise (2.1, 2.4 offen) |
| **Phase 3** | Architektur — RSI/ATR Dedup, Scanner-Cache, FeatureScoringMixin, Pick-Formatter | ✅ (3.1-3.5) |
| **Phase 4** | Qualität — 80.19% Coverage, mypy --strict, CI, DB-Benchmarks | ✅ |
| **Phase 5** | Backtesting — Duplikation, Architektur, Performance | ✅ |
| **Phase 6** | Backtesting-Monolith aufbrechen (4 Monolithen → 18 Module) | ✅ |
| **Phase 7** | Verbleibende >1000 LOC Dateien aufbrechen | ⬜ Geplant |

---

*Alle Trading-Regeln, VIX-Regime-Details, Watchlist und Blacklist → `docs/PLAYBOOK.md`*
