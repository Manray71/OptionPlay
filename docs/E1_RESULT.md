# Verschlankung E.1 — Quick Wins

**Branch:** `verschlankung/e1-quick-wins`
**Datum:** 2026-04-15
**Ziel:** Tote Module, Re-Export-Stubs und Architektur-Reste entfernen

---

## Ergebnis

| Metrik | Wert |
|--------|------|
| Commits | 7 |
| Dateien geändert (src/ + tests/) | 50 |
| Gelöschte LOC | −3,869 |
| Neue LOC (Inlining etc.) | +450 |
| **Netto** | **−3,419 LOC** |
| Tests vorher | 5,918 passed |
| Tests nachher | 5,802 passed |
| Delta Tests | −116 (gelöschte Tests) |
| Neue Failures | 0 (3 pre-existing VIX-System-Tests unverändert) |

---

## Schritte

### Schritt 1 — `structured_logging.py` gelöscht (`6505959`)

- **Gelöscht:** `src/utils/structured_logging.py` (454 LOC)
- **Gelöscht:** `tests/unit/test_structured_logging.py` (1,112 LOC, 56 Tests)
- **Geändert:** `src/utils/__init__.py` — 7 Imports + 7 `__all__`-Einträge entfernt
- **Grund:** 0 Produktions-Caller in `src/` oder `scripts/`

### Schritt 2 — `iv_analyzer.py` gelöscht (`3ffa426`)

- **Gelöscht:** `src/services/iv_analyzer.py` (420 LOC)
- **Gelöscht:** `tests/component/test_iv_analyzer.py` (1,018 LOC, 60 Tests)
- **Grund:** 0 Produktions-Caller; alle IV-Funktionalität lebt in `iv_cache_impl.py`

### Schritt 3 — Cache Re-Export-Stubs entfernt (`296826b`)

- **Gelöscht:** `src/cache/earnings_cache.py` (43 LOC Stub)
- **Gelöscht:** `src/cache/iv_cache.py` (57 LOC Stub)
- **Geändert:** `src/cache/__init__.py` — importiert jetzt direkt aus `_impl`
- **Geändert:** `tests/component/test_earnings_cache.py` — `from src.cache import ...`
- **Geändert:** `tests/component/test_iv_cache.py` — `from src.cache import ...`
- **Geändert:** `tests/component/test_cache_thread_safety.py` — `from src.cache import ...` / `from src.cache.earnings_cache_impl import retry_on_failure`

### Schritt 4 — `iv_calculator.py` in `iv_cache_impl.py` eingebettet (`aaed31f`)

- **Gelöscht:** `src/cache/iv_calculator.py` (152 LOC)
- **Geändert:** `src/cache/iv_cache_impl.py` — 4 Math-Funktionen unter Sektion `# === IV Math (formerly iv_calculator.py) ===` eingefügt; Delegation-Methoden in `HistoricalIVFetcher` rufen nun direkt die Modul-Level-Funktionen
- **Grund:** Einziger Caller war `iv_cache_impl.py` selbst

### Schritt 5 — `pick_formatter.py` von `services/` nach `formatters/` (`5b83e13`)

- **Verschoben:** `src/services/pick_formatter.py` → `src/formatters/pick_formatter.py`
- **Geändert:** `src/services/recommendation_engine.py` — Import auf `..formatters.pick_formatter` aktualisiert
- **Geändert:** `src/formatters/__init__.py` — 4 Symbole re-exportiert (`format_picks_markdown`, `format_picks_v2`, `format_single_pick`, `format_single_pick_v2`)

### Schritt 6 — numpy `try/except`-Guard entfernt (`8c2a8e0`)

- **Geändert:** `src/analyzers/__init__.py` — `try/except ImportError` um `BatchScorer`-Import entfernt
- **Grund:** `numpy==2.3.5` ist Hard-Dependency in `requirements.txt`; Guard war totes Code-Pfad

### Schritt 7 — `yahoo_news.py` gelöscht

- **Gelöscht:** `src/data_providers/yahoo_news.py` (152 LOC)
- **Grund:** 0 Caller in `src/`, `tests/`, `scripts/`; kein Re-Export in `data_providers/__init__.py`

### Schritt 8 — `mcp_main.py` NICHT gelöscht (Fehlbefund im Plan)

- **Entscheidung:** STOP — Datei ist aktiver Entry Point, nicht dead code
- **Befund:** `claude_desktop_config.json` → `scripts/run_mcp.sh` → `python -m src.mcp_main`
- `mcp_main.py` enthält den einzigen `app = Server("optionplay")`-Block mit `@app.list_tools()`, `@app.call_tool()`, `@app.list_prompts()` und `stdio_server()`
- `src/mcp_server.py` ist die `OptionPlayServer`-Klasse + interaktives CLI — **kein** MCP-Transport
- `src/__main__.py` ruft `mcp_server.main()` auf (nur für `--interactive`/`--test`)
- Die Annahme im ursprünglichen Plan ("Aktiver Einstiegspunkt ist `src/mcp_server.py`") war falsch

---

## Gelöschte Dateien (gesamt)

| Datei | LOC | Grund |
|-------|-----|-------|
| `src/utils/structured_logging.py` | 454 | 0 Produktions-Caller |
| `src/services/iv_analyzer.py` | 420 | 0 Produktions-Caller |
| `src/data_providers/yahoo_news.py` | 152 | 0 Caller |
| `src/cache/iv_calculator.py` | 152 | Eingebettet in `iv_cache_impl.py` |
| `src/cache/earnings_cache.py` | 43 | Re-Export-Stub |
| `src/cache/iv_cache.py` | 57 | Re-Export-Stub |
| `tests/unit/test_structured_logging.py` | 1,112 | Modul gelöscht |
| `tests/component/test_iv_analyzer.py` | 1,018 | Modul gelöscht |

---

## Architektur-Änderungen

```
vorher:                              nachher:
src/cache/earnings_cache.py          (gelöscht)
  └── re-exportiert earnings_cache_impl
src/cache/__init__.py                src/cache/__init__.py
  └── from .earnings_cache import      └── from .earnings_cache_impl import

src/cache/iv_cache.py                (gelöscht)
  └── re-exportiert iv_cache_impl
src/cache/__init__.py                src/cache/__init__.py
  └── from .iv_cache import            └── from .iv_cache_impl import

src/cache/iv_calculator.py           (gelöscht, Inhalt in iv_cache_impl.py)
  └── 4 Math-Funktionen
src/cache/iv_cache_impl.py           src/cache/iv_cache_impl.py
  └── from .iv_calculator import ...   └── # === IV Math ===
                                         └── def calculate_iv_rank(...)
                                         └── def calculate_iv_percentile(...)
                                         └── def _calculate_historical_volatility(...)
                                         └── def _estimate_iv_from_hv(...)

src/services/pick_formatter.py       src/formatters/pick_formatter.py
  └── importiert von recommendation_engine via .pick_formatter
```
