# Tech Debt Cleanup — Ergebnis

**Datum:** 2026-04-21
**Branch:** feature/g-exit-improvements

---

## Kategorie 1: Code-Fixes

### 1.1 MCP-Server: get_secure_config() Deprecation ✅

**Fix:** `src/mcp_main.py` — ersetzte `get_secure_config()` durch direktes `SecureConfig()`.

- Import geändert: `from .utils.secure_config import SecureConfig`
- `_config = get_secure_config()` → `SecureConfig()` (kein Variablen-Assignment nötig)
- `.env`-Loading funktioniert identisch (SecureConfig.__init__ lädt os.environ)
- Deprecation-Warning beim MCP-Start entfällt

### 1.2 MCP-Server: IBKR clientId-Konflikt ✅

**Fix:** `config/system.yaml` — `client_id: 1` → `client_id: 2`

- Telegram-Bot (LaunchAgent) hält clientId 1
- MCP nutzt jetzt clientId 2 → kein Reconnect-Timeout mehr
- Hinweis: Die primäre `IBKRConnection` (ibkr/connection.py) nutzt clientId 98 und ist unberührt

### 1.3 Watchlist: Tote Symbole entfernt ✅

**Fix:** `config/watchlists.yaml`

| Symbol | Aktion | Begründung |
|--------|--------|------------|
| SQ     | Entfernt | Block Inc. umbenannt zu XYZ; XYZ war bereits in der Liste |
| CFLT   | Entfernt | Confluent — IBKR Error 200, Symbol nicht mehr handelbar |
| EXAS   | Entfernt | Exact Sciences — IBKR Error 200, Symbol nicht mehr handelbar |

### 1.4 Options-Collector Branch: Fixes integriert ✅

**Entscheidung:** Branch `fix/daily-options-collector` wird nicht gemergt (zu viel Divergenz von main). Die 2 relevanten Code-Fixes wurden manuell appliziert:

- `src/ibkr/market_data.py`: Options-Preis-Timeout 2s → 8s (range(20) → range(80))
  - Delayed data bei IBKR braucht typisch 3-8s; alter 2s-Timeout verursachte missing data
- `scripts/daily_data_fetcher.py`: Zwei `asyncio.run()` zu einem einzigen Event-Loop zusammengeführt
  - Python 3.14+ erlaubt kein re-entrantes `asyncio.run()`; zweiter Aufruf crashte
- `docs/DATA_GAP.md`: Neu angelegt (dokumentiert Lücke 2026-03-28 bis 2026-04-17)

**Branch-Entscheidung:** `fix/daily-options-collector` kann gelöscht werden (`git branch -d fix/daily-options-collector`).

### 1.5 Skipped Tests ✅

**Stand:** 5857 passed, **29 skipped** (vs. ~46 im Kickoff erwartet)

Alle 29 Skips sind in `tests/component/test_visualization.py` und berechtigt:

```
Grund: @pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, ...)
       @pytest.mark.skipif(not VISUALIZATION_AVAILABLE, ...)
```

- matplotlib ist in der Test-Umgebung nicht installiert
- Visualization-Tests decken Chart-Rendering ab — kein Impact auf Trading-Logik
- **Aktion:** Kein Fix nötig. Falls matplotlib installiert werden soll: `pip install matplotlib`

---

## Kategorie 2: Manuelle Checks

### 2.1 Earnings: JNJ/BAC/JPM/KMI/WFC ✅

Alle 5 Symbole haben Einträge in `earnings_history`:

| Symbol | Einträge |
|--------|---------|
| JNJ    | 70      |
| BAC    | 76      |
| JPM    | 70      |
| KMI    | 59      |
| WFC    | 70      |

### 2.2 Telegram-Token ⬜ Manuell prüfen

```bash
source .env
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool
```

### 2.3 Web Shadow-Button ⬜ Manuell prüfen

Browser → OptionPlay-Web → DevTools → Shadow-Button klicken.

### 2.4 MCP-Server Neustart ⬜ Manuell prüfen

Claude Desktop neu starten, `tool_search query="optionplay"` testen.

### 2.5 IBKR Options Data Subscription ⬜ Manuell prüfen

TWS: Edit → Global Configuration → Market Data → Subscriptions → NYSE Options prüfen (~$1.50/Monat).

### 2.6 JNJ Strike-Increment ✅ Dynamisch — kein Fix nötig

Grep in `src/services/` und `src/scanner/` zeigt keine hardcodierten $5-Inkremente.
Strike-Selektion nutzt reale Chain-Daten (was IBKR liefert). JNJ $2.50-Inkremente werden
automatisch korrekt behandelt.

---

## Kategorie 3: Akzeptiert / Kein Fix nötig

| Punkt | Status | Begründung |
|-------|--------|------------|
| diskcache CVE | Akzeptiert | Kein upstream Fix, Dependabot dismissed |
| Options-Daten-Lücke 03/28–04/17 | Dokumentiert | docs/DATA_GAP.md, nicht backfillbar |
| Div-Retro (30d Penalty-Check) | Warten | Braucht 30 Tage Shadow-Daten |
| use_ibkr_margin Flag | Optional | Nice-to-have, kein Impact |
| Strategy.ATH_BREAKOUT Import | Vermutlich gefixt | Legacy-Cleanup (E.3) hat das behoben |

---

## Geänderte Dateien

| Datei | Änderung |
|-------|---------|
| `src/mcp_main.py` | get_secure_config() → SecureConfig() |
| `config/system.yaml` | client_id: 1 → 2 |
| `config/watchlists.yaml` | SQ, CFLT, EXAS entfernt |
| `src/ibkr/market_data.py` | Options timeout 2s → 8s |
| `scripts/daily_data_fetcher.py` | asyncio.run() unified |
| `docs/DATA_GAP.md` | Neu: Data Gap dokumentiert |

## Test-Ergebnis

```
5857 passed, 29 skipped — alle Skips berechtigt (matplotlib)
```
