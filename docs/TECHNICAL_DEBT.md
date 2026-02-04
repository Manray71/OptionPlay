# OptionPlay - Technical Debt Register

**Erstellt:** 2026-02-04
**Status:** Aktiv
**Quelle:** Code Audit nach v3.7.0
**Aktualisiert:** 2026-02-04 (Phase 0 + Phase 1 abgeschlossen)

---

## Uebersicht

| ID | Titel | Prio | Aufwand | Status |
|----|-------|------|---------|--------|
| DEBT-001 | Black-Scholes Duplikation | HIGH | Mittel | Offen |
| DEBT-002 | Unsichere Exception-Handler | HIGH | Klein | **Erledigt** (0 bare except, 0 silent pass) |
| DEBT-003 | SQLite blockiert Async Event Loop | HIGH | Gross | **Erledigt** (Hot-Path Module mit asyncio.to_thread) |
| DEBT-004 | Monolith-Dateien >1000 LOC | MEDIUM | Gross | Offen |
| DEBT-005 | Parallele Earnings-Systeme | MEDIUM | Mittel | Offen |
| DEBT-006 | Config-Sprawl | MEDIUM | Mittel | Offen |
| DEBT-007 | Test-Coverage-Luecken | MEDIUM | Mittel | Offen |
| DEBT-008 | 111 Untracked Files | LOW | Klein | **Erledigt** (v4.0.0 Commit) |
| DEBT-009 | Archive-Verzeichnis (Dead Code) | LOW | Klein | **Erledigt** (geloescht) |

---

## DEBT-001: Black-Scholes Duplikation

**Prioritaet:** HIGH
**Aufwand:** Mittel

### Problem

Zwei separate Black-Scholes-Implementierungen mit ueberlappender Funktionalitaet:

| Datei | LOC | Inhalt |
|-------|-----|--------|
| `src/pricing/black_scholes.py` | 1,419 | Umfangreiche Implementierung |
| `src/options/black_scholes.py` | 937 | Zweite Implementierung |

### Risiko

- Divergierende Berechnungsergebnisse moeglich
- Doppelter Wartungsaufwand bei Bugfixes
- Unklar welches Modul die "richtige" Quelle ist

### Empfohlene Loesung

1. Beide Implementierungen vergleichen und Feature-Differenz identifizieren
2. Eine kanonische Implementierung waehlen (vermutlich `src/pricing/`)
3. Fehlende Features portieren
4. Zweite Datei durch Re-Exports ersetzen, dann entfernen
5. Alle Imports anpassen

---

## DEBT-002: Unsichere Exception-Handler

**Prioritaet:** HIGH
**Aufwand:** Klein

### Problem

**Bare `except:` — BEHOBEN** (keine mehr in src/)

**15x Silent `except ...: pass` verbleiben (Stand 2026-02-04):**
- `src/ibkr_bridge.py` (2x)
- `src/strike_recommender.py` (2x, davon 1x ImportError)
- `src/visualization/sr_chart.py` (3x)
- `src/services/vix_service.py` (3x)
- `src/services/recommendation_engine.py` (1x)
- `src/backtesting/ml_weight_optimizer.py` (1x ValueError)
- `src/config/watchlist_loader.py` (1x ImportError)
- `src/utils/earnings_aggregator.py` (1x ValueError)
- `src/services/trade_validator.py` (1x ImportError)

### Risiko

- Fehler werden verschluckt, kein Logging
- Debugging extrem erschwert
- Bare `except:` kann Ctrl+C und sys.exit() abfangen

### Empfohlene Loesung

1. Alle `except:` durch `except Exception:` ersetzen
2. `except Exception: pass` durch `except Exception as e: logger.debug(...)` ersetzen
3. Wo moeglich: spezifische Exceptions fangen statt generische

### Betroffene Dateien

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

---

## DEBT-003: SQLite blockiert Async Event Loop

**Prioritaet:** HIGH
**Aufwand:** Gross

### Problem

15x direkte `sqlite3.connect()` Aufrufe in Code der von async Handlern aufgerufen wird.
SQLite-Operationen sind blockierend und halten den Event Loop an.

### Betroffene Module

| Modul | Stellen |
|-------|---------|
| `src/cache/earnings_history.py` | Mehrere |
| `src/cache/symbol_fundamentals.py` | Mehrere |
| `src/cache/vix_cache.py` | Mehrere |
| `src/data_providers/local_db.py` | Mehrere |
| `src/services/trade_validator.py` | 1 (neu mit asyncio.to_thread) |
| `src/backtesting/engine.py` | Mehrere |

### Risiko

- Event Loop blockiert waehrend DB-Zugriff (typisch 5-50ms, bei grossen Queries mehr)
- Bei gleichzeitigen MCP-Anfragen: Latenz-Spikes
- Kein echtes Concurrent Processing moeglich

### Empfohlene Loesung

**Option A: `asyncio.to_thread()` Wrapper (pragmatisch)**
- Alle DB-Methoden in `asyncio.to_thread()` wrappen
- Minimale Code-Aenderungen
- Nutzt ThreadPool, blockiert Event Loop nicht mehr

**Option B: `aiosqlite` (sauberer)**
- Migration zu `aiosqlite` fuer native async DB-Zugriffe
- Groesserer Umbau, aber langfristig besser
- Erfordert async Context Manager fuer Connections

### Empfehlung

Option A zuerst (schneller Gewinn), spaeter auf Option B migrieren.

---

## DEBT-004: Monolith-Dateien >1000 LOC

**Prioritaet:** MEDIUM
**Aufwand:** Gross

### Problem

20 Dateien mit mehr als 1000 Zeilen Code:

| Datei | LOC |
|-------|-----|
| `src/backtesting/real_options_backtester.py` | 1,899 |
| `src/pricing/black_scholes.py` | 1,419 |
| `src/ibkr_bridge.py` | 1,350+ |
| `src/mcp_server.py` | 1,200+ |
| `src/strike_recommender.py` | 1,100+ |
| `src/formatters/pdf_report_generator.py` | 1,100+ |
| ... | ... |

### Risiko

- Schwer zu verstehen und zu warten
- Merge-Konflikte wahrscheinlicher
- Tests werden komplex

### Empfohlene Loesung

Schrittweises Refactoring der groessten Dateien:
1. `real_options_backtester.py`: Aufteilen in Engine, Reporter, DataLoader
2. `ibkr_bridge.py`: Aufteilen in Connection, Portfolio, Orders
3. `mcp_server.py`: Weitere Handler-Mixins extrahieren

---

## DEBT-005: Parallele Earnings-Systeme

**Prioritaet:** MEDIUM
**Aufwand:** Mittel

### Problem

Zwei separate Earnings-Systeme mit unterschiedlicher Datenquelle:

| System | Datei | Datenquelle |
|--------|-------|-------------|
| `EarningsCache` | `src/cache/earnings_cache.py` | Live APIs (yfinance, Yahoo) |
| `EarningsHistoryManager` | `src/cache/earnings_history.py` | SQLite DB |

Der `TradeValidator` nutzt `EarningsHistoryManager` (DB), der `QuoteHandler` nutzt `EarningsCache` (API).
Dies fuehrte zu Bug #1: Validator zeigte "Earnings unbekannt" weil DB keine Zukunfts-Earnings hatte.

### Aktueller Workaround

Fix vom 2026-02-04: API-Fallback im TradeValidator wenn DB keine Daten hat.

### Empfohlene Loesung

1. Ein einheitliches Earnings-Interface definieren
2. Strategie: DB first, API fallback (bereits teilweise implementiert)
3. Langfristig: `EarningsCache` und `EarningsHistoryManager` zu einem `EarningsService` zusammenfuehren
4. Write-Through: API-Ergebnisse immer in DB speichern

---

## DEBT-006: Config-Sprawl

**Prioritaet:** MEDIUM
**Aufwand:** Mittel

### Problem

Trading-Konstanten und Konfiguration verteilt ueber 7+ Quellen:

| Quelle | Inhalt |
|--------|--------|
| `src/constants/trading_rules.py` | Entry/Exit Rules |
| `src/constants/thresholds.py` | Score Thresholds |
| `src/constants/strategy_parameters.py` | Strategy Params |
| `src/constants/risk_management.py` | Risk Limits |
| `src/constants/technical_indicators.py` | Indicator Params |
| `src/constants/performance.py` | Performance Params |
| `config/settings.yaml` | Runtime Config |
| Analyzer-Klassen | Hardcodierte Werte |

### Risiko

- Gleiche Konstante an mehreren Stellen definiert
- Aenderungen muessen in mehreren Dateien gemacht werden
- Schwer zu ueberpruefen ob alle Werte konsistent sind

### Empfohlene Loesung

1. Alle Trading-Konstanten in `src/constants/` zentralisieren
2. `config/settings.yaml` fuer Runtime-Settings (API Keys, Paths)
3. Hardcodierte Werte in Analyzern durch Constants ersetzen
4. Single Source of Truth: `docs/PLAYBOOK.md` -> `src/constants/`

---

## DEBT-007: Test-Coverage-Luecken

**Prioritaet:** MEDIUM
**Aufwand:** Mittel

### Problem

Mehrere Module in `src/indicators/` und `src/models/` haben keine oder minimale Tests:

| Modul | Tests vorhanden |
|-------|----------------|
| `src/indicators/momentum.py` | Nein |
| `src/indicators/trend.py` | Nein |
| `src/indicators/volatility.py` | Nein |
| `src/indicators/optimized.py` | Nein |
| `src/indicators/volume_profile.py` | Minimal |
| `src/models/market_data.py` | Nein |
| `src/models/strategy_breakdowns.py` | Nein |

### Risiko

- Regressionen bei Refactoring nicht erkannt
- Indicator-Berechnungen koennen fehlerhafte Ergebnisse liefern ohne Warnung
- Basis-Modelle ohne Validierung

### Empfohlene Loesung

1. Unit-Tests fuer alle Indicator-Module schreiben
2. Property-based Tests fuer mathematische Berechnungen
3. Edge-Case Tests (leere Daten, NaN, Extremwerte)
4. Coverage-Report in CI einbauen (Ziel: >80%)

---

## DEBT-008: 111 Untracked Files — ERLEDIGT

**Status:** Erledigt (2026-02-04, v4.0.0 Commit)

Alle 255 Dateien (neue + modifizierte + geloeschte) committed. `.gitignore` aktualisiert.

---

## DEBT-009: Archive-Verzeichnis (Dead Code) — ERLEDIGT

**Status:** Erledigt (2026-02-04)

`archive/` (20 MB) geloescht. Keine Referenzen im aktiven Code. In `.gitignore` aufgenommen.
Git-Historie behaelt den Code.

---

## Arbeitsreihenfolge (Empfehlung)

1. **DEBT-002** (Exception-Handler) — 15x silent pass verbleiben, schneller Gewinn
2. **DEBT-001** (Black-Scholes) — Duplikation entfernen reduziert Wartung
3. **DEBT-005** (Earnings) — Bereits teilweise gefixt, zu Ende fuehren
4. **DEBT-003** (SQLite async) — Schrittweise mit `asyncio.to_thread()`
5. **DEBT-006** (Config) — Bei naechstem Config-Change anpacken
6. **DEBT-007** (Tests) — Laufend bei jedem Feature-Ticket
7. ~~**DEBT-008** (Untracked)~~ — **Erledigt**
8. ~~**DEBT-009** (Archive)~~ — **Erledigt**
9. **DEBT-004** (Monolithen) — Langfristig, bei Gelegenheit
