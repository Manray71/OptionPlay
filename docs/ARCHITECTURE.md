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
src/
├── mcp_server.py                  # MCP Server Entry Point
├── mcp_tool_registry.py           # Tool-Definitionen
├── container.py                   # Dependency Injection
│
├── handlers/                      # MCP Tool Handlers (Mixin-based)
│   ├── vix.py                    # VIX, Regime, Strategy
│   ├── scan.py                   # Scan + Daily Picks
│   ├── quote.py                  # Quotes, Options, Historical
│   ├── analysis.py               # Symbol-Analyse
│   ├── portfolio.py              # Portfolio-Management
│   ├── risk.py                   # Position Sizing, Stop Loss
│   ├── validate.py               # Trade Validator (GO/NO-GO)
│   ├── monitor.py                # Position Monitor (Exit-Signale)
│   ├── report.py                 # PDF-Report-Generierung
│   ├── ibkr.py                   # IBKR Bridge Handler
│   └── handler_container.py      # Composition-based (Migration)
│
├── services/                      # Business Logic
│   ├── vix_service.py            # VIX-Daten + Regime-Erkennung
│   ├── scanner_service.py        # Multi-Strategy Scanning
│   ├── options_service.py        # Options-Analyse
│   ├── recommendation_engine.py  # Daily Picks + Strikes
│   ├── trade_validator.py        # Trade Validator (PLAYBOOK-Regeln)
│   ├── position_monitor.py       # Position Monitor (Exit-Signale)
│   └── portfolio_constraints.py  # Portfolio-Limits + Sizing
│
├── analyzers/                     # 4 Trading-Strategien
│   ├── pullback.py               # Pullback im Aufwärtstrend
│   ├── bounce.py                 # Support Bounce
│   ├── ath_breakout.py           # All-Time-High Breakout
│   ├── earnings_dip.py           # Post-Earnings Dip
│   └── score_normalization.py    # Cross-Strategy Scoring
│
├── scanner/                       # Multi-Strategy Scanner
│   ├── multi_strategy_scanner.py
│   └── signal_aggregator.py
│
├── cache/                         # Caching Layer
│   ├── earnings_history.py       # Earnings DB
│   ├── symbol_fundamentals.py    # Fundamentals + Stability
│   ├── historical_cache.py       # Price Data Cache
│   └── vix_cache.py              # VIX History
│
├── data_providers/                # Datenquellen-Abstraktion
│   ├── tradier.py                # Tradier API
│   ├── marketdata.py             # MarketData.app API
│   └── local_db.py               # SQLite Local DB
│
├── constants/                     # Zentrale Konfiguration
│   ├── trading_rules.py          # Exit-Regeln, VIX-Regime, Sizing
│   ├── technical_indicators.py
│   ├── risk_management.py
│   ├── strategy_parameters.py
│   └── thresholds.py
│
└── utils/                         # Utilities
    ├── rate_limiter.py           # Adaptive Rate Limiting
    ├── circuit_breaker.py        # Fault Tolerance
    └── error_handler.py          # Exception Handling
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

## Codebase-Metriken (Stand 2026-02-03)

| Bereich | Python-Dateien | Zeilen | Anteil |
|---------|---------------|--------|--------|
| **src/** | 150 | 76,414 | 37% |
| **tests/** | 112 | 56,981 | 28% |
| **scripts/** | 46 | 48,686 | 24% |
| **archive/** | 33 | 23,596 | 11% |
| **Gesamt** | **341** | **205,677** | 100% |

### Größte Subsysteme in src/

| Subsystem | Dateien | Zeilen | Beschreibung |
|-----------|---------|--------|--------------|
| backtesting/ | 16 | 16,419 | ML-Training, Backtesting Engine |
| src/ Root | 13 | 8,397 | MCP Server, Legacy Root-Module |
| analyzers/ | 10 | 6,251 | 4 Strategy Analyzer |
| utils/ | 14 | 5,456 | Rate Limiter, Error Handler, etc. |
| cache/ | 10 | 5,372 | Earnings, IV, Fundamentals, VIX |
| services/ | 11 | 5,290 | VIX, Scanner, Options, Recommender |
| indicators/ | 9 | 4,721 | Support/Resistance, MACD, RSI, etc. |
| handlers/ | 14 | 4,625 | MCP Tool Handler (Mixin + Composition) |
| data_providers/ | 7 | 3,755 | Tradier, MarketData, Local DB |

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
| **DEBT-003** | Blocking SQLite in async handlers | Medium | Mittel | `aiosqlite` oder Thread-Pool für DB-Zugriffe in Handlers |
| **DEBT-004** | Mixin → Composition Migration | Medium | Groß | `HandlerContainer` existiert, aber `OptionPlayServer` nutzt noch Mixins |
| **DEBT-008** | Connection Pooling fehlt | Low | Klein | Tradier/MarketData-Provider ohne Pool |
| **DEBT-009** | Große Dateien aufteilen | Low | Mittel | 9 Dateien > 1,000 LOC (siehe unten) |
| **DEBT-012** | Structured Logging einführen | Low | Mittel | Aktuell `print()` + `logging.info()` gemischt |

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

| Datei | LOC | Begründung |
|-------|-----|------------|
| `backtesting/real_options_backtester.py` | 1,899 | Komplex aber kohärent |
| `backtesting/trade_tracker.py` | 1,817 | Könnte P&L-Calc abtrennen |
| `scanner/multi_strategy_scanner.py` | 1,678 | Könnte Filter/Ranking trennen |
| `backtesting/ensemble_selector.py` | 1,566 | ML-Modell, schwer teilbar |
| `config/config_loader.py` | 1,556 | YAML-Parsing + Validation + A/B |
| `indicators/support_resistance.py` | 1,501 | Fibonacci/Clustering/Detection |
| `analyzers/pullback.py` | 1,496 | Scoring + Signals |
| `backtesting/regime_trainer.py` | 1,423 | Walk-Forward-Training |
| `pricing/black_scholes.py` | 1,419 | Batch-Pricing (Performance-kritisch) |

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

*Alle Trading-Regeln, VIX-Regime-Details, Watchlist und Blacklist → `docs/PLAYBOOK.md`*
