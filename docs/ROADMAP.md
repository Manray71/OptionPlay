# OptionPlay — Stabilisierungs-Roadmap

**Erstellt:** 2026-02-04
**Quelle:** Code Audit v4.0.0
**Ziel:** Projekt von "funktional, aber fragil" zu "robust und wartbar" bringen — als Voraussetzung fuer spaeteren Service-Betrieb.
**Scope:** Keine neuen Features, kein Service-Umbau. Nur: aufraumen, absichern, konsolidieren.

---

## Uebersicht der Phasen

| Phase | Name | Fokus | Dauer (geschaetzt) | Abhaengigkeiten |
|-------|------|-------|---------------------|-----------------|
| **0** | Hygiene | Git-Bereinigung, Dead Code, Versionierung | 1 Tag | Keine |
| **1** | Absicherung | Exception-Handling, Thread-Safety, Sync-SQLite | 3-5 Tage | Keine |
| **2** | Duplikation eliminieren | Indikatoren, Black-Scholes, Earnings, Services | 5-8 Tage | Phase 1 |
| **3** | Architektur vereinfachen | Config-Konsolidierung, Handler-Refactoring, Monolithen | 5-8 Tage | Phase 2 |
| **4** | Qualitaetssicherung | Test-Coverage, Typing, CI-Pipeline | Laufend | Phase 2+ |

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

## Phase 1 — Absicherung (3-5 Tage)

**Ziel:** Keine stillen Fehler mehr, kein Event-Loop-Blocking, keine Race Conditions. Das System verhaelt sich vorhersagbar.

### 1.1 Exception-Handling bereinigen (DEBT-002)

**Status pruefen:** Grep zeigt keine bare `except:` mehr — aber TECHNICAL_DEBT.md listet sie noch. Erst verifizieren, dann ggf. schliessen.

**Verbleibende Aufgaben:**
- Alle `except Exception as e: pass` durch `except Exception as e: logger.warning(...)` ersetzen
- Einheitliches Error-Response-Format festlegen: **MarkdownBuilder** als Standard
- 3 verschiedene Formate (MarkdownBuilder, Formatter-Bibliothek, Raw-String) auf eines reduzieren

**Betroffene Dateien:**
```
src/ibkr_bridge.py
src/options/max_pain.py
src/indicators/sr_chart.py
src/handlers/validate.py
src/services/vix_service.py
src/services/recommendation_engine.py
src/strike_recommender.py
src/utils/secure_config.py
```

**Aufwand:** 0.5-1 Tag

### 1.2 Thread-Safety nachruesten

| Komponente | Problem | Aktion |
|------------|---------|--------|
| `VixCacheManager` (`cache/vix_cache.py`) | Kein Lock, `_cache` und `_cache_loaded` ohne Synchronisierung | `threading.RLock()` hinzufuegen, analog zu `EarningsHistoryManager` |
| `WatchlistLoader` (`config/watchlist_loader.py`) | `_loader_instance` ohne Lock | `threading.Lock()` fuer Singleton-Erstellung |
| `ConfigLoader` (`config/config_loader.py`) | `_config` Singleton ohne Lock | `threading.Lock()` fuer Singleton-Erstellung |

**Aufwand:** 0.5 Tag

### 1.3 Sync-SQLite aus Async-Code eliminieren (DEBT-003)

**Problem:** 8 Dateien mit `sqlite3.connect()` — teilweise aufgerufen aus async Handlern. Blockiert den Event Loop fuer 5-50ms pro Query.

**Pragmatische Loesung:** `asyncio.to_thread()` Wrapper

```python
async def async_db_call(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)
```

**Reihenfolge nach Impact:**

| Prio | Modul | Im Hot Path? |
|------|-------|-------------|
| 1 | `cache/vix_cache.py` | Ja (jeder Request) |
| 2 | `cache/symbol_fundamentals.py` | Ja (Scans, Validation) |
| 3 | `cache/earnings_history.py` | Ja (Validation) |
| 4 | `services/trade_validator.py` | Ja (bereits teilweise mit to_thread) |
| 5 | `data_providers/local_db.py` | Ja (Options-Queries) |
| 6 | `services/iv_analyzer.py` | Mittel |
| 7 | `backtesting/real_options_backtester.py` | Nein (Batch-Job) — vorerst auslassen |
| 8 | `backtesting/trade_tracker.py` | Nein (Batch-Job) — vorerst auslassen |

**Aufwand:** 2-3 Tage

### 1.4 Fehlende Singleton-Resets nachruesten

**Problem:** `EarningsCache`, `EarningsFetcher`, `IVCache`, `IVFetcher` haben keine `reset_*()` Funktion — Tests koennen Singletons nicht sauber isolieren.

**Aktion:** Fuer jedes Modul `reset_earnings_cache()`, `reset_iv_cache()` etc. analog zu bestehenden Patterns ergaenzen.

**Aufwand:** 0.5 Tag

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

### 2.2 Black-Scholes konsolidieren (DEBT-001)

**Ist-Zustand:**
- `src/pricing/black_scholes.py` (1.419 LOC) — umfangreich
- `src/options/black_scholes.py` (937 LOC) — zweite Implementierung

**Vorgehen:**
1. Feature-Diff identifizieren: Welche Funktionen hat die eine, die die andere nicht hat?
2. `src/pricing/black_scholes.py` als kanonische Implementierung waehlen (groesser, vermutlich vollstaendiger)
3. Fehlende Features aus `src/options/` portieren
4. `src/options/black_scholes.py` durch Re-Exports ersetzen (Abwaertskompatibilitaet)
5. Alle direkten Imports auf `src/pricing/` umstellen
6. Re-Export-Datei in Phase 3 entfernen

**Aufwand:** 1-2 Tage

### 2.3 Earnings-Systeme zusammenfuehren (DEBT-005)

**Ist-Zustand:**
- `EarningsCache` (API-basiert, JSON-Datei) — fuer QuoteHandler
- `EarningsHistoryManager` (SQLite-basiert) — fuer TradeValidator
- Workaround existiert: API-Fallback im Validator wenn DB leer

**Ziel:** Ein `EarningsService` mit klarer Schichtung:
```
EarningsService
├── get_next_earnings(symbol) -> EarningsInfo
├── is_earnings_safe(symbol, min_days=60) -> bool
└── Intern: DB first -> API fallback -> Write-Through in DB
```

**Vorgehen:**
1. `EarningsService` Interface definieren (Fassade ueber beide Systeme)
2. DB-first, API-fallback Logik im Service implementieren
3. Write-Through: API-Ergebnisse immer in DB speichern
4. QuoteHandler und TradeValidator auf `EarningsService` umstellen
5. Alte direkte Zugriffe auf `EarningsCache`/`EarningsHistoryManager` deprecaten

**Aufwand:** 1-2 Tage

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

### 4.1 Test-Coverage auf 80% anheben (DEBT-007)

**Ist-Zustand:** 72% (Minimum 70%)
**Ziel:** 80% Coverage, 85% fuer kritische Module

**Ungetestete Module (hoechste Prioritaet):**

| Modul | LOC | Impact | Prio |
|-------|-----|--------|------|
| `indicators/momentum.py` | 513 | Basis fuer alle Analyzer | 1 |
| `indicators/optimized.py` | 648 | NumPy-Berechnungen | 2 |
| `indicators/trend.py` | 154 | Trend-Erkennung | 2 |
| `indicators/volatility.py` | 128 | Volatilitaets-Berechnung | 2 |
| `indicators/volume_profile.py` | 426 | VWAP, Sektoranalyse | 3 |
| `models/market_data.py` | ? | Basis-Datenmodelle | 3 |
| `models/strategy_breakdowns.py` | ? | Score-Modelle | 3 |

**Nach Indikator-Extraktion (Phase 2.1):**
- Die neue `indicators/calculator.py` bekommt umfangreiche Unit-Tests
- Property-based Tests mit Hypothesis fuer mathematische Korrektheit
- Edge Cases: leere Arrays, NaN-Werte, Extremwerte, Single-Element

**Test-Infrastruktur-Verbesserungen:**
- `conftest.py` mit gemeinsamen Fixtures (reduziert 25-30% Test-Duplikation)
- `freezegun` statt `time.sleep()` fuer zeitabhaengige Tests
- `pytest-timeout = 30s` in pyproject.toml hinzufuegen
- `pytest-xdist` fuer parallele Ausfuehrung evaluieren

**Aufwand:** Laufend, ca. 1 Tag pro Modul

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

---

## Abhaengigkeitsgraph

```
Phase 0 (Hygiene)
    │
    ▼
Phase 1 (Absicherung)
    ├── 1.1 Exception-Handling ──────────────────────┐
    ├── 1.2 Thread-Safety ──────────────────────────┤
    ├── 1.3 Sync-SQLite -> asyncio.to_thread() ─────┤
    └── 1.4 Singleton-Resets ───────────────────────┤
                                                     │
Phase 2 (Duplikation)                                │
    ├── 2.1 Indikator-Bibliothek ◄──────────────────┘
    │       (haengt ab von 1.x fuer stabile Basis)
    ├── 2.2 Black-Scholes (unabhaengig)
    ├── 2.3 Earnings-Service (unabhaengig)
    └── 2.4 Service-Utilities (unabhaengig)
            │
Phase 3 (Architektur)
    ├── 3.1 Config-Konsolidierung (nach 2.4)
    ├── 3.2 Monolithen aufbrechen (nach 2.1, profitiert davon)
    └── 3.3 Handler Composition (nach 3.2)
            │
Phase 4 (Qualitaet) ─── laeuft parallel ab Phase 2
    ├── 4.1 Test-Coverage (nach 2.1 -> Tests fuer calculator.py)
    ├── 4.2 Typing (laufend)
    ├── 4.3 CI-Pipeline (einmalig, frueh)
    └── 4.4 Cache-Kohaerenz (nach 1.2)
```

---

## Abschlusskriterien (Definition of Done)

Bevor das Projekt als "service-ready" gilt, muessen alle folgenden Kriterien erfuellt sein:

| # | Kriterium | Messbar |
|---|-----------|---------|
| 1 | Keine sync-SQLite-Aufrufe im async Hot Path | `grep sqlite3.connect` in Handlern = 0 |
| 2 | Alle Singletons thread-safe | Jeder `_instance` hat Lock |
| 3 | Keine silent `except: pass` | `grep "except.*pass"` in src/ = 0 |
| 4 | Jede Indikator-Berechnung existiert genau 1x | Keine `_calculate_macd/ema/atr/stochastic/keltner` in Analyzern |
| 5 | Eine Black-Scholes-Implementierung | `src/options/black_scholes.py` = nur Re-Exports oder geloescht |
| 6 | Ein Earnings-System | `EarningsService` als einzige oeffentliche API |
| 7 | Test-Coverage >= 80% | `pytest --cov-fail-under=80` |
| 8 | Keine Datei im Hot Path > 1.000 LOC | Ausnahme: `support_resistance.py`, Backtesting |
| 9 | Alle Caches mit TTL | Kein "forever cached" ausser immutable Daten |
| 10 | mypy ohne `ignore_missing_imports` | `mypy src/` = 0 errors |
| 11 | Alle Dateien im Git | `git status` = clean |
| 12 | Version konsistent | Eine Versionsnummer ueberall |
