# Verschlankung E.1 — Quick Wins

**Branch:** `verschlankung/e1-quick-wins`
**Datum:** 2026-04-15
**Ziel:** Tote Module, Re-Export-Stubs und Architektur-Reste entfernen

---

## Gesamtergebnis

| Metrik | Wert |
|--------|------|
| Commits | 7 |
| Gelöschte Dateien (src/ + tests/) | 8 |
| Verschobene Dateien | 1 |
| Gelöschte LOC (brutto) | −3,869 |
| Neue LOC (Inlining, Tests-Update) | +450 |
| **Netto LOC** | **−3,419** |
| Entfernte Tests | −108 (56 + 51 gelöschte Testmethoden) |
| Tests vorher (Baseline) | 5,918 passed |
| Tests nachher | 5,805 passed |
| Neue Failures | 0 |

---

## Commits

| Hash | Beschreibung |
|------|-------------|
| `6505959` | Remove structured_logging.py — 0 production callers |
| `3ffa426` | Remove iv_analyzer.py wrapper — superseded by iv_cache_impl |
| `296826b` | Remove cache re-export stubs — direct imports from _impl |
| `aaed31f` | Inline iv_calculator into iv_cache_impl |
| `5b83e13` | Move pick_formatter from services/ to formatters/ |
| `8c2a8e0` | Remove numpy try/except guard from analyzers/__init__.py |
| `fe51df1` | Remove unused yahoo_news data provider; add E1_RESULT.md |

---

## Schritte im Detail

### Schritt 1 — `structured_logging.py` gelöscht

**Commit:** `6505959`

- **Gelöscht:** `src/utils/structured_logging.py` (454 LOC)
- **Gelöscht:** `tests/unit/test_structured_logging.py` (1,112 LOC, 57 Tests)
- **Geändert:** `src/utils/__init__.py` — 7 Imports + 7 `__all__`-Einträge entfernt
- **Grund:** `grep -rn "structured_logging|StructuredLogger|get_logger" src/ scripts/` → 0 Treffer außerhalb der Datei selbst

### Schritt 2 — `iv_analyzer.py` gelöscht

**Commit:** `3ffa426`

- **Gelöscht:** `src/services/iv_analyzer.py` (420 LOC)
- **Gelöscht:** `tests/component/test_iv_analyzer.py` (1,018 LOC, 51 Tests)
- **Grund:** `grep -rn "IVAnalyzer|iv_analyzer" src/ scripts/` → 0 Produktions-Caller; alle IV-Funktionalität lebt in `iv_cache_impl.py`

### Schritt 3 — Cache Re-Export-Stubs entfernt

**Commit:** `296826b`

- **Gelöscht:** `src/cache/earnings_cache.py` (43 LOC)
- **Gelöscht:** `src/cache/iv_cache.py` (57 LOC)
- **Geändert:** `src/cache/__init__.py` — importiert jetzt direkt aus `earnings_cache_impl` und `iv_cache_impl`
- **Geändert:** 3 Testdateien auf direkte `src.cache`-Imports umgestellt:
  - `tests/component/test_earnings_cache.py`
  - `tests/component/test_iv_cache.py`
  - `tests/component/test_cache_thread_safety.py` (inline `retry_on_failure` via `earnings_cache_impl`)

### Schritt 4 — `iv_calculator.py` in `iv_cache_impl.py` eingebettet

**Commit:** `aaed31f`

- **Gelöscht:** `src/cache/iv_calculator.py` (152 LOC)
- **Geändert:** `src/cache/iv_cache_impl.py` — 4 Math-Funktionen unter Sektion `# === IV Math (formerly iv_calculator.py) ===` eingefügt; die beiden Delegation-Methoden in `HistoricalIVFetcher` rufen jetzt direkt die modul-level Funktionen
- **Grund:** Einziger Caller war `iv_cache_impl.py` selbst (2 lazy imports + 1 top-level import)

### Schritt 5 — `pick_formatter.py` von `services/` nach `formatters/` verschoben

**Commit:** `5b83e13`

- **Verschoben:** `src/services/pick_formatter.py` → `src/formatters/pick_formatter.py`
- **Geändert:** `src/services/recommendation_engine.py` — Import von `from .pick_formatter` auf `from ..formatters.pick_formatter` aktualisiert
- **Geändert:** `src/formatters/__init__.py` — 4 Symbole ergänzt: `format_picks_markdown`, `format_picks_v2`, `format_single_pick`, `format_single_pick_v2`

### Schritt 6 — numpy `try/except`-Guard entfernt

**Commit:** `8c2a8e0`

- **Geändert:** `src/analyzers/__init__.py` — `try/except ImportError` um `BatchScorer`-Import auf direkten Import reduziert
- **Grund:** `numpy==2.3.5` ist Hard-Dependency in `requirements.txt`; der Guard war ein totes Code-Pfad. Der Feature-Flag-basierte Guard im Scanner (`enable_batch_scoring`) bleibt unberührt.

### Schritt 7 — `yahoo_news.py` gelöscht

**Commit:** `fe51df1`

- **Gelöscht:** `src/data_providers/yahoo_news.py` (152 LOC)
- **Grund:** `grep -rn "yahoo_news|YahooNews" src/ tests/ scripts/` → 0 Treffer; kein Re-Export in `data_providers/__init__.py`

### Schritt 8 — `mcp_main.py`: STOP (kein Dead Code)

**Commit:** keiner

- **Entscheidung:** Nicht gelöscht
- **Befund:** `claude_desktop_config.json` → `scripts/run_mcp.sh` → `python -m src.mcp_main` — die Datei ist der **aktive Claude Desktop Entry Point**
- `mcp_main.py` enthält den einzigen `app = Server("optionplay")`-Block mit `@app.list_tools()`, `@app.call_tool()`, `@app.list_prompts()` und `stdio_server()`
- `src/mcp_server.py` ist die `OptionPlayServer`-Klasse + interaktives CLI (`--interactive`, `--test`) — kein MCP-Transport
- `src/__main__.py` ruft `mcp_server.main()` auf, nicht `mcp_main.main()`
- **Die Annahme im ursprünglichen Plan war falsch:** "Aktiver Einstiegspunkt ist `src/mcp_server.py` via `python -m src`"

---

## Gelöschte Dateien (Übersicht)

| Datei | LOC | Typ | Grund |
|-------|-----|-----|-------|
| `src/utils/structured_logging.py` | 454 | Modul | 0 Produktions-Caller |
| `src/services/iv_analyzer.py` | 420 | Modul | 0 Produktions-Caller |
| `src/data_providers/yahoo_news.py` | 152 | Modul | 0 Caller |
| `src/cache/iv_calculator.py` | 152 | Modul | Eingebettet in `iv_cache_impl.py` |
| `src/cache/iv_cache.py` | 57 | Re-Export-Stub | Direkt-Import aus `_impl` |
| `src/cache/earnings_cache.py` | 43 | Re-Export-Stub | Direkt-Import aus `_impl` |
| `tests/component/test_iv_analyzer.py` | 1,018 | Testdatei | Modul gelöscht |
| `tests/unit/test_structured_logging.py` | 1,112 | Testdatei | Modul gelöscht |
| **Gesamt** | **3,408** | | |

---

## Architektur-Änderungen

```
VORHER                                NACHHER

src/cache/earnings_cache.py  ──────►  (gelöscht)
  └── re-exportiert _impl
src/cache/__init__.py                 src/cache/__init__.py
  └── from .earnings_cache import       └── from .earnings_cache_impl import

src/cache/iv_cache.py  ────────────►  (gelöscht)
  └── re-exportiert _impl
src/cache/__init__.py                 src/cache/__init__.py
  └── from .iv_cache import              └── from .iv_cache_impl import

src/cache/iv_calculator.py  ───────►  (gelöscht, Inhalt in iv_cache_impl.py)
  └── 4 Math-Funktionen
src/cache/iv_cache_impl.py            src/cache/iv_cache_impl.py
  └── from .iv_calculator import ...    └── # === IV Math ===
                                          def calculate_iv_rank(...)
                                          def calculate_iv_percentile(...)
                                          def _calculate_historical_volatility(...)
                                          def _estimate_iv_from_hv(...)

src/services/pick_formatter.py  ───►  src/formatters/pick_formatter.py
  └── 1 Caller: recommendation_engine  └── recommendation_engine importiert
      via from .pick_formatter              via from ..formatters.pick_formatter
```
