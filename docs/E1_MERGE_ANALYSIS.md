# E.1 Merge Analysis

**Datum**: 2026-04-16  
**Branch**: `verschlankung/e1-quick-wins` → `main`  
**Ergebnis**: 5 Konflikte — **trivial auflösbar, kein Lars-Review nötig**

---

## Konflikte Übersicht

| Datei | Typ | E.1-Änderung | main-Änderung |
|-------|-----|--------------|---------------|
| `src/handlers/ibkr.py` | modify/delete | 3 Strings: "Yahoo/Marketdata" → "Yahoo" | E.3 hat Datei gelöscht (`351ad92`) |
| `src/handlers/quote.py` | modify/delete | `"marketdata"` → `"ibkr"` in source-Strings, `fetch_marketdata` → `fetch_ibkr` | E.3 hat Datei gelöscht (`b49256e`) |
| `src/handlers/vix.py` | modify/delete | Kleine String-Änderungen (Tradier-Refs) | E.3 hat Datei gelöscht (`64edfe6`) |
| `tests/integration/test_quote_handler.py` | modify/delete | 1 Assertion: `source == "marketdata"` → `"ibkr"` | E.3 hat Datei gelöscht (`b49256e`) |
| `tests/system/test_mcp_server_e2e.py` | content | Marketdata-Refs entfernt (env-patch, limiter-mock, Assertion) | E.3 fix: VIX-Mocks nach vix_composed-Refactor (`d5ca12c`) |

---

## Analyse

### Konflikte 1–4: modify/delete (Mixin-Handler + Test)

**Ursache**: E.1 hat am 2026-04-15 noch in den alten Mixin-Handlern (`src/handlers/ibkr.py`, `quote.py`, `vix.py`) Marketdata-Referenzen bereinigt. E.3 hat diese Dateien kurz danach komplett gelöscht (Legacy-Mixin-Migration).

**E.1-Änderungen in diesen Dateien** (alle aus Commit `296826b`):
- `ibkr.py`: "Yahoo/Marketdata" → "Yahoo" (3×)
- `quote.py`: `source="marketdata"` → `"ibkr"`, `fetch_marketdata()` → `fetch_ibkr()`
- `test_quote_handler.py`: `assert ... == "marketdata"` → `"ibkr"`

**Resolution**: Lösche E.1-Versionen — keep main's deletion. Die Inhalte sind durch E.3 überholt (Dateien existieren auf main nicht mehr).

### Konflikt 5: test_mcp_server_e2e.py (content)

**E.1-Änderungen** (Commit `296826b`):
1. `mock_api_key` fixture: `MARKETDATA_API_KEY` aus env-patch entfernt
2. `server` fixture: `patch('src.mcp_server.get_marketdata_limiter')` Wrapper entfernt (11 LOC)
3. `test_init_with_api_key`: `assert server._ibkr_provider is None or server._provider is None` → `assert server._provider is None`

**E.3-Änderungen** (Commit `d5ca12c` — nach E.1-Branch-Abspaltung):
- VIX-Mock-Fix: `mock IBKRBridge.get_vix_value` at bridge level instead of `qualifyContracts`

**Überschneidung**: Beide Commits ändern verschiedene Teile der Datei (verschiedene Fixtures/Tests). Kein semantischer Widerspruch.

**Resolution**: E.1-Änderungen manuell auf main's aktuelle Version anwenden.

---

## Empfehlung: Merge jetzt durchführen

Alle 5 Konflikte haben klare, nicht-destruktive Resolutions:

1. **4× modify/delete**: `git rm` die E.1-Versionen (Dateien sollen weg bleiben)
2. **1× content**: E.1-Marketdata-Cleanup auf main's E2E-Test anwenden

**Strategie**:
```bash
git merge --no-ff verschlankung/e1-quick-wins

# 4 modify/delete → keep main's deletion:
git rm src/handlers/ibkr.py src/handlers/quote.py src/handlers/vix.py
git rm tests/integration/test_quote_handler.py

# test_mcp_server_e2e.py → manuell E.1-Änderungen einbauen
# (MARKETDATA_API_KEY aus mock entfernen, get_marketdata_limiter-patch weg)
git add tests/system/test_mcp_server_e2e.py

git commit
```

**Was von E.1 verloren geht**: Nur die String-Änderungen in den gelöschten Mixin-Handler-Dateien — diese sind irrelevant, da die Dateien auf main nicht existieren.

**Was von E.1 erhalten bleibt**: Alle anderen 7 Commits (cache stub removal, etc.) kommen vollständig rein.
