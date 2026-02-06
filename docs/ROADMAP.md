# OptionPlay — Stabilisierungs-Roadmap

**Erstellt:** 2026-02-04
**Aktualisiert:** 2026-02-06 (nach Phase 6 + Code Review)
**Quelle:** Code Audit v4.0.0 + Code Review 2026-02-06
**Ziel:** Projekt von "funktional, aber fragil" zu "robust und wartbar" bringen — als Voraussetzung fuer spaeteren Service-Betrieb.
**Scope:** Keine neuen Features, kein Service-Umbau. Nur: aufraumen, absichern, konsolidieren.

---

## Uebersicht der Phasen

| Phase | Name | Fokus | Status |
|-------|------|-------|--------|
| **0** | Hygiene | Git-Bereinigung, Dead Code, Versionierung | ✅ |
| **1** | Absicherung | Exception-Handling, Thread-Safety, Sync-SQLite | ✅ |
| **2** | Duplikation eliminieren | Indikatoren, Black-Scholes, Earnings, Services | ⚠️ (2.1, 2.4 offen) |
| **3** | Architektur vereinfachen | RSI/ATR Dedup, Scanner-Cache, FeatureScoringMixin, Pick-Formatter | ✅ (3.1-3.5) |
| **4** | Qualitaetssicherung | 80.19% Coverage, mypy --strict, CI, DB-Benchmarks | ✅ |
| **5** | Backtesting-Architektur | Duplikation, Models extrahieren, Sub-Packages | ✅ |
| **6** | Backtesting-Monolithen | 4 Monolithen → 18 Module (Facade-Pattern) | ✅ |
| **7** | Verbleibende Monolithen + Weighting | 5x >1000 LOC aufbrechen, CIRC-01, WEIGHT-01 | ⬜ NEU |

---

## Phase 0 — Hygiene (1 Tag)

**Ziel:** Sauberer Ausgangszustand. Alles im Git, kein toter Code, konsistente Versionierung.

### 0.1 Versionierung synchronisieren

`pyproject.toml` sagt `3.4.0`, `CLAUDE.md` sagt `4.0.0`.

**Aktion:** Eine Version festlegen, ueberall angleichen (pyproject.toml, CLAUDE.md, ARCHITECTURE.md).

### 0.2 Untracked Files committen (DEBT-008)

111 Dateien (57 Tests, Rest Produktivcode/Scripts) sind nicht im Git.

**Aktion:** Alle relevanten Dateien reviewen und committen, `.gitignore` anpassen, nicht mehr benoetigte Dateien loeschen.

### 0.3 Archive-Verzeichnis entfernen (DEBT-009)

`archive/` enthaelt ~20 MB Dead Code (Pre-v3.6.0).

**Aktion:** Pruefen ob etwas davon noch referenziert wird. Wenn nein: komplett loeschen. Git-Historie behaelt den Code.

### 0.4 TECHNICAL_DEBT.md aktualisieren

- DEBT-002 (bare `except:`) scheint laut Grep bereits behoben — verifizieren und Status anpassen
- Neue Findings aus Audit ergaenzen (VixCacheManager Thread-Safety, Analyzer-Duplikation, fehlende Cache-Resets)

---

## Phase 1 — Absicherung ✅ ABGESCHLOSSEN

**Status:** Abgeschlossen (2026-02-04)

### 1.1 Exception-Handling bereinigen (DEBT-002) ⚠️ TEILWEISE

**Status:** Bare `except:` eliminiert. ~15 silent `except: pass` verbleiben (niedrige Prioritaet).

### 1.2 Thread-Safety nachruesten ✅

**Status:** Abgeschlossen — 10+ Module haben Locks implementiert:
- `VixCacheManager`: `threading.RLock()` + `_vix_manager_lock`
- `CacheManager`: `threading.RLock()` + `_cache_manager_lock`
- `IVCache`: `threading.RLock()`
- `EarningsCache`: `threading.RLock()`
- `HistoricalCache`: `threading.RLock()`
- `AnalyzerPool`: `threading.Lock()`

### 1.3 Sync-SQLite aus Async-Code eliminieren (DEBT-003) ✅

**Status:** Abgeschlossen — Hot-Path Module nutzen `asyncio.to_thread()`:
- `data_providers/local_db.py`
- `data_providers/tradier.py`
- `data_providers/marketdata.py`
- `handlers/vix.py`, `handlers/quote.py`

### 1.4 Fehlende Singleton-Resets nachruesten ✅

**Status:** Abgeschlossen — 15+ `reset_*()` Funktionen implementiert:
- `reset_vix_manager()`, `reset_cache_manager()`, `reset_iv_cache()`
- `reset_earnings_cache()`, `reset_earnings_history_manager()`
- `reset_fundamentals_manager()`, `reset_historical_cache()`
- `reset_watchlist_loader()`, `reset_config()`, `reset_analyzer_pool()`

---

## Phase 2 — Duplikation eliminieren (5-8 Tage)

**Ziel:** Jede Berechnung existiert genau einmal. Aenderungen an einem Indikator erfordern genau eine Code-Aenderung.

### 2.1 Indikator-Bibliothek extrahieren

**Ist-Zustand:** 5 Indikator-Berechnungen sind 4x kopiert ueber die Analyzer (~1.009 LOC Duplikation):

| Indikator | Duplikate | Duplizierte LOC |
|-----------|-----------|-----------------|
| `_calculate_macd()` | 4x (alle Analyzer) | ~160 |
| `_calculate_keltner_channel()` | 4x (alle Analyzer) | ~240 |
| `_calculate_atr()` | 4x (alle Analyzer) | ~128 |
| `_calculate_stochastic()` | 3x (bounce, pullback, earnings_dip) | ~120 |
| `_calculate_ema()` | 3x + 1 Variante (pullback) | ~36 |
| Scoring-Duplikation (diverse) | 2-4x | ~325 |
| **Gesamt** | | **~1.009** |

**Ziel-Architektur:**

```
src/indicators/
├── calculator.py          # NEU: Gemeinsame Berechnungen
│   ├── calculate_ema()
│   ├── calculate_atr()
│   ├── calculate_macd()
│   ├── calculate_stochastic()
│   └── calculate_keltner_channel()
├── momentum.py            # Besteht (513 LOC) — pruefen ob ueberlappend
├── optimized.py           # Besteht (648 LOC) — NumPy-Varianten
├── support_resistance.py  # Besteht (1,501 LOC)
└── ...
```

**Vorgehen:**
1. `src/indicators/calculator.py` mit den 5 Funktionen erstellen
2. Pullback-EMA harmonisieren — nutzt `np.mean()` und gibt `prices` statt `None` zurueck bei zu wenig Daten. Einheitliches Verhalten festlegen.
3. Alle 4 Analyzer refactoren: eigene `_calculate_*()` Methoden durch Imports ersetzen
4. Scoring-Methoden mit identischer Logik (`_score_rsi_divergence`, `_score_stochastic`) als Mixin oder in `feature_scoring_mixin.py` ergaenzen
5. Scoring-Methoden mit strategie-spezifischer Logik (`_score_keltner`, `_score_macd`) behalten, aber Keltner/MACD-Berechnung auslagern
6. Pruefen ob `indicators/optimized.py` (NumPy-Varianten) statt manueller Schleifen genutzt werden kann

**Aufwand:** 3-4 Tage (inkl. Test-Anpassung)

### 2.2 Black-Scholes konsolidieren (DEBT-001) ✅

**Status:** GELOEST (2026-02-04) — Bewusste Trennung dokumentiert

Die zwei Implementierungen dienen unterschiedlichen Zwecken:
- `src/pricing/black_scholes.py`: NumPy-vektorisiert fuer Batch-Backtesting
- `src/options/black_scholes.py`: OOP-basiert fuer interaktive Analyse

Merge wuerde 1,050 Zeilen kalibrierte IV-Daten riskieren ohne echten Gewinn.

### 2.3 Earnings-Systeme zusammenfuehren (DEBT-005) ✅

**Status:** GELOEST (2026-02-04) — DB-first + API-Fallback mit Write-Through

Etablierte Strategie in `TradeValidator`:
1. **DB-First**: Schnell, offline, BMO/AMC-Handling
2. **API-Fallback**: Wenn DB "no_earnings_data" liefert
3. **Write-Through**: API-Ergebnisse werden automatisch in DB gespeichert

### 2.4 Service-Duplikation aufloesen (~450 LOC)

**Problem:** Gleiche Logik in mehreren Services kopiert:

| Logik | Vorkommen | Dateien |
|-------|-----------|---------|
| Stability-Filterung (VIX-adjusted) | 3x | recommendation_engine, trade_validator, position_monitor |
| VIX-Regime-Lookup + Schwellen | 5x | recommendation_engine, trade_validator, position_monitor, portfolio_constraints, handlers |
| Blacklist-Check | 2x im selben File | analysis.py (Zeile 46-51 und 159-164) |

**Vorgehen:**
1. `src/services/trading_checks.py` erstellen mit:
   - `check_stability(symbol, vix_level) -> CheckResult`
   - `check_earnings_safety(symbol, target_date) -> CheckResult`
   - `get_vix_regime(vix_value) -> VIXRegime` (existiert teilweise in trading_rules.py)
   - `is_blacklisted(symbol) -> bool`
2. Alle Services refactoren, um diese Utilities zu nutzen
3. Doppelten Blacklist-Check in `analysis.py` eliminieren

**Aufwand:** 1-2 Tage

---

## Phase 3 — Architektur vereinfachen (5-8 Tage)

**Ziel:** Die Struktur des Codes spiegelt die Struktur der Domaene wider. Jede Datei hat eine klare Verantwortung unter 800 LOC.

### 3.1 Config-Konsolidierung (DEBT-006)

**Ist-Zustand:** Trading-Konstanten ueber 7+ Quellen verteilt:

| Quelle | Inhalt |
|--------|--------|
| `constants/trading_rules.py` | Entry/Exit Rules |
| `constants/thresholds.py` | Score Thresholds |
| `constants/strategy_parameters.py` | Strategy Params |
| `constants/risk_management.py` | Risk Limits |
| `constants/technical_indicators.py` | Indicator Params |
| `constants/performance.py` | Performance Params |
| `config/settings.yaml` | Runtime Config |
| Analyzer-Klassen | Hardcodierte Magic Numbers (45+) |

**Ziel-Struktur:**

```
src/constants/              -> Alle statischen Werte (PLAYBOOK-abgeleitet)
├── trading_rules.py        -> Entry, Exit, VIX, Sizing, Discipline (besteht, gut)
├── strategy_parameters.py  -> Strategie-spezifische Schwellen (besteht)
├── technical_indicators.py -> Indikator-Parameter (RSI-Perioden, EMA-Laengen etc.)
└── scoring.py              -> Score-Schwellen (zusammengefuehrt aus thresholds.py)

config/                     -> Nur Runtime/Umgebung
├── settings.yaml           -> API Keys, Paths, Rate Limits
├── strategies.yaml         -> VIX-basierte Strategy-Profile
├── watchlists.yaml         -> Symbol-Listen
└── trained_weights.yaml    -> ML-Gewichte
```

**Vorgehen:**
1. Alle 45+ Magic Numbers in Analyzern identifizieren und nach `constants/` migrieren
2. `constants/thresholds.py` in `constants/scoring.py` umbenennen, inhaltlich pruefen
3. Redundanzen zwischen `constants/risk_management.py` und `trading_rules.py` (SIZING_*) aufloesen
4. Referenz auf PLAYBOOK-Sektion in Kommentaren sicherstellen

**Aufwand:** 2-3 Tage

### 3.2 Monolith-Dateien aufbrechen (DEBT-004) — selektiv

Nicht alle 20 Dateien >1000 LOC muessen aufgeteilt werden. Backtesting-Module sind eigenstaendige Batch-Jobs. Fokus auf die im MCP-Server aktiven Dateien:

| Datei | LOC | Aktion |
|-------|-----|--------|
| `mcp_tool_registry.py` | 1.078 | Aufteilen nach Tool-Kategorie (Scan, Quote, Analysis, Portfolio) |
| `recommendation_engine.py` | 1.298 | Filter-Logik extrahieren (nach 2.4 bereits kleiner) |
| `strike_recommender.py` | 1.289 | Berechnung vs. Formatierung trennen |
| `ibkr_bridge.py` | 1.514 | Connection, Portfolio, Orders trennen |
| `support_resistance.py` | 1.501 | Berechnung vs. Visualisierung trennen |
| `config_loader.py` | 1.542 | Validation in eigene Klasse, Loader-Logik reduzieren |
| `pullback.py` | 1.496 | Nach Phase 2.1 automatisch ~700 LOC kleiner |

**Nicht anfassen (vorerst):**
- `backtesting/*.py` — eigenstaendige Pipeline, kein MCP-Impact
- `pricing/black_scholes.py` — wird in 2.2 konsolidiert

**Aufwand:** 3-5 Tage

### 3.3 Handler-Architektur modernisieren

**Ist-Zustand:** 10 Mixins per MRO zusammengesetzt:
```python
class OptionPlayServer(VixHandlerMixin, ScanHandlerMixin, QuoteHandlerMixin,
    AnalysisHandlerMixin, PortfolioHandlerMixin, IbkrHandlerMixin,
    ReportHandlerMixin, RiskHandlerMixin, ValidateHandlerMixin,
    MonitorHandlerMixin):
```

**Problem:** Python MRO bei 10 Parents fragil, kein Runtime-Check ob alle abstrakten Methoden implementiert sind, Handler-Registrierung in `mcp_tool_registry.py` (1.078 LOC) monolithisch.

**Ziel:** Composition over Inheritance:
```python
class OptionPlayServer:
    def __init__(self):
        self.vix = VixHandler(self.container)
        self.scan = ScanHandler(self.container)
        # ... Handler als eigenstaendige Klassen

    def register_tools(self):
        for handler in [self.vix, self.scan, ...]:
            handler.register(self.server)
```

**Vorgehen:**
1. Jeden Mixin zu eigenstaendiger Handler-Klasse mit `register()` Methode refactoren
2. `OptionPlayServer` nutzt Composition statt Vererbung
3. `mcp_tool_registry.py` entfaellt — jeder Handler registriert eigene Tools
4. Einheitliche Validierung an der MCP-Boundary (ein Decorator)

**Aufwand:** 3-5 Tage (kann ueber mehrere Sprints verteilt werden)

---

## Phase 4 — Qualitaetssicherung (laufend)

**Ziel:** Refactoring aus Phase 1-3 absichern, Regressionen verhindern, Confidence fuer spaetere Service-Migration aufbauen.

**Status (2026-02-05): ABGESCHLOSSEN**

Bisherige Ergebnisse:
- ✅ 4.1 Coverage: **80.19%** erreicht — Ziel von 80% erfuellt (6.740 Tests, 132 Testdateien)
- ✅ 4.2 Typing: `warn_unreachable = true` aktiviert, 3 unreachable Code-Stellen behoben
- ✅ 4.3 CI-Pipeline: `.github/workflows/ci.yml` erstellt (lint, type-check, security, test Jobs)
- ✅ 4.4 Cache-Kohaerenz: Toter Code aus `VixCacheManager` entfernt (`_cache`, `_cache_loaded`)
- ✅ 4.5 Handler-API-Fixes: risk.py Handler korrigiert

Recursive-Logic Haertung (Welle 4):
- ✅ Test-Struktur: 132 Dateien in unit/component/integration/system reorganisiert
- ✅ Type Hints: 27 Quelldateien mit `from __future__ import annotations` und mypy --strict
- ✅ DB-Benchmarks: 17 Benchmarks fuer 10 DB-Hotspots, Hauptengpass identifiziert (options_prices)

**Finale Tests:** 6.698 bestanden, 4 uebersprungen, 0 fehlgeschlagen
**Details:** siehe `docs/PHASE4_RESULTS.md`

### 4.1 Test-Coverage auf 80% anheben (DEBT-007) ✅

**Status:** ABGESCHLOSSEN (2026-02-05)

**Erreicht:** 80.19% Coverage (Ziel: 80%)
- 6.740 Tests bestanden
- 132 Testdateien
- 41 neue Testdateien am 2026-02-05 erstellt

**Neu getestete Module:**

| Kategorie | Neue Testdateien |
|-----------|------------------|
| Analyzers | `test_bounce_analyzer.py`, `test_ath_breakout_analyzer.py`, `test_earnings_dip_analyzer.py` |
| Handlers | `test_quote_handler.py`, `test_scan_handler.py`, `test_portfolio_handler.py` |
| Services | `test_scanner_service.py`, `test_vix_service.py`, `test_recommendation_engine.py`, `test_position_monitor.py`, `test_trade_validator.py` |
| Backtesting | `test_backtest_engine.py`, `test_backtesting_metrics.py`, `test_reliability.py`, `test_data_collector.py`, `test_trade_tracker.py`, `test_walk_forward.py`, `test_signal_validation.py` |
| Indicators | `test_indicators_momentum.py`, `test_indicators_trend.py`, `test_indicators_volatility.py`, `test_support_resistance.py`, `test_gap_analysis.py` |
| Utilities | `test_utils_validation.py`, `test_rate_limiter.py`, `test_utils_metrics.py`, `test_provider_orchestrator.py`, `test_historical_cache.py`, `test_earnings_aggregator.py`, `test_secure_config.py`, `test_structured_logging.py` |
| Andere | `test_pricing.py`, `test_tradier_provider.py`, `test_strike_recommender.py`, `test_spread_analyzer.py`, `test_vix_strategy.py`, `test_multi_strategy_scanner.py`, `test_cache_manager.py`, `test_context.py` |

**Naechste Schritte (optional fuer 85%):**
- `indicators/volume_profile.py` (60% Coverage)
- `visualization/sr_chart.py` (60% Coverage)
- `portfolio/manager.py` (78% Coverage)

### 4.2 Typing verschaerfen

**Ist-Zustand:**
```toml
[tool.mypy]
ignore_missing_imports = true    # Alle fehlenden Stubs werden ignoriert
no_strict_optional = true        # Optional[X] nicht erzwungen
```

**Schrittweise verschaerfen:**

| Schritt | Aenderung | Auswirkung |
|---------|----------|------------|
| 1 | `no_strict_optional = false` | Erzwingt explizite `Optional[X]` Typen |
| 2 | `warn_unreachable = true` | Findet toten Code |
| 3 | `disallow_untyped_defs = true` fuer `constants/` | Alle Konstanten typisiert |
| 4 | `ignore_missing_imports = false` + Stubs installieren | Volle Typpruefung |

**Aufwand:** 0.5 Tag pro Schritt, verteilt ueber Phasen

### 4.3 CI-Pipeline haerten

**Ist-Zustand:** Bandit konfiguriert, pytest/coverage vorhanden, aber kein CI sichtbar.

**Ziel-Pipeline:**
```
Pre-Commit:
  ├── black (Formatierung)
  ├── isort (Import-Sortierung)
  └── flake8 (Linting)

CI (auf jedem Push):
  ├── pytest --cov --cov-fail-under=80
  ├── mypy src/
  ├── bandit -r src/
  └── Coverage-Report als Artefakt
```

**Aufwand:** 1 Tag fuer Setup, danach Wartung bei Regelaenderungen

### 4.4 Cache-Kohaerenz sicherstellen

**Ist-Zustand:** 6 verschiedene Cache-Systeme mit unterschiedlichen TTLs, teilweise ohne jede Invalidierung:

| Cache | TTL | Invalidierung |
|-------|-----|---------------|
| CacheManager (zentral) | 60s-30d je Policy | Dependency-Graph |
| EarningsCache | 4 Wochen / 24h | Nur bei Neuladen |
| IVCache | Per Entry | Nur bei Neuladen |
| HistoricalCache | 300s | LRU + TTL |
| VixCacheManager | unendlich (forever nach Laden) | Keine |
| SymbolFundamentals | unendlich (forever nach Laden) | Keine |

**Aktionen:**
1. `VixCacheManager`: TTL von 1h einfuehren (VIX aendert sich taeglich)
2. `SymbolFundamentalsManager`: TTL von 24h (Fundamentals aendern sich selten)
3. Alle Cache-Manager im `CacheManager` registrieren und dessen Dependency-Graph nutzen
4. Einheitliche `refresh()` API auf allen Managern

**Aufwand:** 1-2 Tage

### 4.5 Handler-API-Inkompatibilitaeten beheben ✅

**Status:** ABGESCHLOSSEN (2026-02-04)

**Problem:** Mehrere Handler in `src/handlers/` verwendeten veraltete oder nicht existierende API-Felder von Dataclasses.

**Durchgefuehrte Fixes (Strategy A: Handler anpassen):**

| Handler | Methode | Problem | Loesung |
|---------|---------|---------|---------|
| `risk.py` | `calculate_position_size()` | `result.vix_regime` nicht vorhanden | VIX-Regime direkt vom Sizer geholt (`sizer.get_vix_regime()`) |
| `risk.py` | `recommend_stop_loss()` | Dict-Keys nicht korrekt | Angepasst: `stop_loss_price` statt `stop_price`, `max_possible_loss` lokal berechnet |
| `risk.py` | `analyze_spread()` | `analysis.breakeven` falsch | Korrigiert zu `analysis.break_even` |
| `risk.py` | `analyze_spread()` | `roi_percent`/`annualized_roi` fehlen | ROI lokal im Handler berechnet |
| `risk.py` | `run_monte_carlo()` | `PriceSimulator` Constructor falsch | Statische Methode `generate_price_path()` verwendet |

**Ergebnis:**
- Alle 12 Risk-Handler-Tests bestanden
- Alle 255 Handler-Tests bestanden
- Alle 3973 Tests bestanden (1 skipped, 2 Warnungen)

**Aufwand:** 1 Tag (weniger als geschaetzt)

---

## Phase 5 — Backtesting-Architektur ✅ ABGESCHLOSSEN

**Status:** Abgeschlossen (2026-02-05)

- ✅ Duplikation in backtesting/ eliminiert
- ✅ Reine Datenmodelle in `backtesting/models/` extrahiert (25 Klassen)
- ✅ Sub-Package-Struktur: core/, simulation/, training/, validation/, ensemble/, tracking/, models/
- ✅ Commit: `6820e79` (Phase 5+6a)

---

## Phase 6 — Backtesting-Monolithen aufbrechen ✅ ABGESCHLOSSEN

**Status:** Abgeschlossen (2026-02-06)

4 Monolithen in 18 Module via Facade-Pattern aufgebrochen:

| Phase | Monolith | Vorher LOC | Nachher | Commit |
|-------|----------|-----------|---------|--------|
| 6b | `trade_tracker.py` | 1,530 → 485 (Facade) + 5 Module | TradeCRUD, TradeAnalysis, PriceStorage, VixStorage, OptionsStorage | `f72b92f` |
| 6c | `real_options_backtester.py` | 1,666 → 76 (Re-export Stub) | core/ + simulation/ | `017cebe` |
| 6d | `ensemble_selector.py` | 1,205 → 18 (Re-export Stub) | ensemble/ (Selector, MetaLearner, RotationEngine) | `a88e4f1` |
| 6e | `regime_trainer.py` | 1,076 → 28 (Re-export Stub) | training/ (DataPrep, EpochRunner, PerformanceAnalyzer, Optimizer) | `d53989e` |

**Ergebnis:** 10,062 Zeilen hinzugefuegt, 7,179 entfernt, 116 Dateien geaendert. Backward-Kompatibilitaet via Re-export Stubs.

---

## Phase 7 — Weiterentwicklung (GEPLANT)

**Quelle:** Code Review 2026-02-06
**Ziel:** Verbleibende Monolithen aufbrechen, kritische Architektur-Issues loesen, Weighting-Flexibilitaet verbessern.

### 7.0 Kritische Fixes (sofort)

| Aufgabe | Aufwand | Impact |
|---------|---------|--------|
| **CIRC-01 loesen**: Lazy Import in `validation/reliability.py` | 30 Min | Eliminiert fragile Import-Reihenfolge |
| **VER-01 loesen**: Version auf 4.0.0 vereinheitlichen | 10 Min | Konsistenz |

### 7.1 Scoring-Gewichte externalisieren (WEIGHT-01)

**Problem:** Komponenten-Gewichte (RSI: 3, Support: 2.5, etc.) sind hardcoded in Analyzer-Klassen und `score_normalization.py`.

**Loesung:**
1. `config/scoring_weights.yaml` erstellen mit allen Punkt-Allokationen pro Strategie
2. `score_normalization.py:max_possible` automatisch aus Config berechnen
3. Analyzer laden Gewichte aus Config statt hardcoded

**Aufwand:** 2-3 Tage
**Impact:** Groesster Hebel fuer Tuning ohne Code-Aenderung

### 7.2 Verbleibende >1000 LOC Dateien aufbrechen

Reihenfolge nach Impact:

| Datei | LOC | Aufteilung |
|-------|-----|-----------|
| `core/engine.py` | 1,240 | BacktestEngine → Simulation + Reporting + Core |
| `training/walk_forward.py` | 1,131 | Config + TrainingLoop + ResultsProcessor |
| `training/ml_weight_optimizer.py` | 1,093 | FeatureExtractor + Optimizer + WeightedScorer |
| `validation/signal_validation.py` | 1,076 | SignalValidator + StatisticalCalculator |
| `simulation/options_backtest.py` | 1,196 | Backtester + ConvenienceFunctions |

**Aufwand:** 3-5 Tage

### 7.3 Mixin → Composition abschliessen (DEBT-004)

**Problem:** 11 Mixins mit 22 Interface-Methoden in BaseHandlerMixin. MRO-Komplexitaet.

**Loesung:**
1. `handler_container.py` (existiert) als primaeres Pattern aktivieren
2. Jedes Mixin zu eigenstaendiger Handler-Klasse mit expliziten Dependencies
3. `OptionPlayServer` nutzt Composition statt Vererbung

**Aufwand:** 3-5 Tage

### 7.4 ServerState integrieren (STATE-01)

**Problem:** `ServerState` Dataclass definiert aber `mcp_server.py` nutzt gestreute Variablen (`_connected`, `_quote_cache_hits`, etc.)

**Loesung:** Gestreute Variablen in ServerState migrieren.

**Aufwand:** 1 Tag

---

## Abhaengigkeitsgraph

```
Phase 0 (Hygiene) ✅
    │
    ▼
Phase 1 (Absicherung) ✅
    ├── 1.1 Exception-Handling ✅ (bare except eliminiert)
    ├── 1.2 Thread-Safety ✅ (10+ Module mit Locks)
    ├── 1.3 Sync-SQLite -> asyncio.to_thread() ✅
    └── 1.4 Singleton-Resets ✅ (15+ reset_* Funktionen)
                                                     │
Phase 2 (Duplikation)                                │
    ├── 2.1 Indikator-Bibliothek ⬜ (26 Duplikate verbleiben)
    ├── 2.2 Black-Scholes ✅ (bewusste Trennung dokumentiert)
    ├── 2.3 Earnings-Service ✅ (DB-first + API-Fallback)
    └── 2.4 Service-Utilities ⬜
            │
Phase 3 (Architektur) ✅
    ├── 3.1 RSI/ATR Duplikation eliminiert ✅
    ├── 3.2 SQL-Konstanten extrahiert ✅ (26 Konstanten)
    ├── 3.3 Scanner-Caches → @cached_property ✅
    ├── 3.4 FeatureScoringMixin ✅
    └── 3.5 Pick-Formatter extrahiert ✅
            │
Phase 4 (Qualitaet) ✅
    ├── 4.1 Test-Coverage ✅ (80.19% erreicht, 6.748 Tests)
    ├── 4.2 Typing ✅ (warn_unreachable + mypy --strict fuer 27 Dateien)
    ├── 4.3 CI-Pipeline ✅ (GitHub Actions erstellt)
    ├── 4.4 Cache-Kohaerenz ✅ (toter Code entfernt)
    ├── 4.5 Handler-API-Fixes ✅ (risk.py Handler korrigiert)
    ├── Test-Reorg ✅ (133 Dateien → unit/component/integration/system)
    ├── Type Hints ✅ (27 src + 4 test Dateien)
    └── DB-Benchmarks ✅ (17 Benchmarks, 10 Hotspots)
            │
Phase 5 (Backtesting-Architektur) ✅
    └── Models extrahiert, Sub-Packages erstellt
            │
Phase 6 (Backtesting-Monolithen) ✅
    ├── 6b TradeTracker → Facade + 5 Module ✅
    ├── 6c RealOptionsBacktester → core/ + simulation/ ✅
    ├── 6d EnsembleSelector → ensemble/ ✅
    └── 6e RegimeTrainer → training/ Sub-Module ✅
            │
Phase 7 (Weiterentwicklung) ⬜
    ├── 7.0 CIRC-01 + VER-01 loesen ✅
    ├── 7.1 Scoring-Gewichte externalisieren (WEIGHT-01) ⬜
    ├── 7.2 Verbleibende >1000 LOC aufbrechen ⬜
    ├── 7.3 Mixin → Composition (DEBT-004) ⬜
    └── 7.4 ServerState integrieren (STATE-01) ⬜
```

---

## Abschlusskriterien (Definition of Done)

Bevor das Projekt als "service-ready" gilt, muessen alle folgenden Kriterien erfuellt sein:

| # | Kriterium | Messbar | Status |
|---|-----------|---------|--------|
| 1 | Keine sync-SQLite-Aufrufe im async Hot Path | `grep sqlite3.connect` in Handlern = 0 | ✅ (asyncio.to_thread) |
| 2 | Alle Singletons thread-safe | Jeder `_instance` hat Lock | ✅ (10+ Module) |
| 3 | Keine silent `except: pass` | `grep "except.*pass"` in src/ = 0 | ⚠️ (~15 verbleiben) |
| 4 | Jede Indikator-Berechnung existiert genau 1x | Keine `_calculate_macd/ema/atr/stochastic/keltner` in Analyzern | ⬜ (26 Duplikate) |
| 5 | Eine Black-Scholes-Implementierung | Bewusste Trennung batch vs OOP | ✅ (dokumentiert) |
| 6 | Ein Earnings-System | DB-first + API-Fallback + Write-Through | ✅ |
| 7 | Test-Coverage >= 80% | `pytest --cov-fail-under=80` | ✅ (80.19%, 6.748 Tests) |
| 8 | Keine Datei im Hot Path > 1.000 LOC | Ausnahme: Backtesting (Phase 7) | ⬜ (5 Dateien verbleiben) |
| 9 | Alle Caches mit TTL | Kein "forever cached" ausser immutable Daten | ✅ |
| 10 | mypy ohne `ignore_missing_imports` | `mypy src/` = 0 errors | ⬜ |
| 11 | Alle Dateien im Git | `git status` = clean | ⬜ |
| 12 | Version konsistent | Eine Versionsnummer ueberall | ⬜ (VER-01 offen) |
| 13 | Handler-APIs synchronisiert | Keine AttributeError in Handlern | ✅ |
| 14 | Keine zirkulaeren Imports | Kein fragile Import-Reihenfolge | ⬜ (CIRC-01 offen) |
| 15 | Scoring-Gewichte konfigurierbar | Alle Punkt-Allokationen in Config | ⬜ (WEIGHT-01 offen) |
| 16 | Backtesting-Monolithen aufgebrochen | Alle Dateien <1000 LOC | ⬜ (Phase 7.2) |
