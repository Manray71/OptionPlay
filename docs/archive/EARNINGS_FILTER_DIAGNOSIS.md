# Earnings-Filter Diagnose — 2026-04-17

## Abfrage 1: Symbole mit Earnings in den nächsten 30 Tagen (DB)

Die `earnings_history`-Tabelle enthält 30+ Symbole mit Earnings bis 2026-05-17:

```
BX      2026-04-17  (source: tradier)
FITB    2026-04-17  (source: ibkr)
RF      2026-04-17  (source: ibkr)
TFC     2026-04-17  (source: ibkr)
GE      2026-04-20/21 (ibkr + marketdata)
TSLA    2026-04-21  (source: marketdata)
ELV     2026-04-21  (source: marketdata)
LMT, NEE, NVR, PHM, VZ, CB, COF, DHI, DHR, EQT, HAL, IBKR, ISRG, MMM, NOC, RTX, SYF, UAL, UNH
GD      2026-04-22  ...
```

DB-Status: 626 zukünftige Earnings-Einträge, **zuletzt aktualisiert: 2026-04-17T17:18** (heute, aktuell).

---

## Abfrage 2: Wo sitzt der Filter, welcher Schwellwert

**Zwei unabhängige Filter-Schichten:**

### Layer 1: Pre-Filter (vor dem Scan)
- **Ort**: `src/handlers/scan_composed.py:_apply_earnings_prefilter()` (Zeile 1042)
- **Aufgerufen in**: `daily_picks()` (Zeile 440) und `scan()` (Zeile 106)
- **Datenquelle**: `EarningsFetcher.cache` → JSON-Datei `~/.optionplay/earnings_cache.json`
- **Schwellwert**: `scanner_config.earnings_prefilter_min_days = 45` (aus `config/system.yaml`)
- **Fail-open Logik**: Symbol nicht im Cache oder Cache-Eintrag abgelaufen → `safe.append(symbol)` → **Symbol passiert durch**

### Layer 2: Scanner-interner Check (pro Strategy)
- **Ort**: `src/scanner/multi_strategy_scanner.py:_should_skip_for_earnings()` (Zeile 844)
- **Datenquelle**: `scanner._earnings_cache` — gefüllt durch `scanner.set_earnings_date()` aus `earnings_fetcher.cache`
- **Fail-open Logik**: Kein Datum im Scanner-Cache → `return False` → **Symbol passiert durch** (Zeile 862-866)
- **Schwellwert**: `ScanConfig.exclude_earnings_within_days = 45`

**Beide Layer teilen dieselbe fehlerhafte Datenquelle.**

---

## Abfrage 3: Wird der Filter im daily_picks-Pfad aufgerufen?

**JA** — beide Layer werden aufgerufen.

In `scan_composed.py:daily_picks()`:
1. **Zeile 440–445**: `_apply_earnings_prefilter()` wird aufgerufen wenn `auto_earnings_prefilter=True`
2. **Zeile 466–471**: Scanner wird erzeugt
3. **Zeile 149–156** (via `scan()`-Pfad): Earnings-Daten werden in den Scanner geladen (`scanner.set_earnings_date()`)

**ABER**: Beide Aufrufe ziehen Daten aus `earnings_fetcher.cache` (JSON), nicht aus der DB. Da der JSON-Cache nahezu komplett veraltet ist, greifen beide Layer faktisch nicht.

---

## Abfrage 4: Wie aktuell sind die Earnings-Daten

| Quelle | Einträge | Letzte Aktualisierung | Status |
|--------|----------|----------------------|--------|
| `earnings_history` DB | 626 zukünftige | 2026-04-17T17:18 (heute) | ✅ AKTUELL |
| `earnings_cache.json` | 124 gesamt | Max: 2026-04-06, Min: 2026-02-08 | ❌ VERALTET |
| Davon frisch (< 28 Tage) | 5 | — | 119/124 abgelaufen |

Der JSON-Cache hat nur **5 von 124 Einträgen** innerhalb seiner eigenen 28-Tage-TTL.
Von den 357 Symbolen in `symbol_fundamentals` sind nur ~124 überhaupt im JSON-Cache — **233 fehlen völlig**.

---

## Abfrage 5: Konkretes Symbol — wird es durchgelassen obwohl Earnings nah?

Simulation von `_apply_earnings_prefilter()` für Symbole mit Earnings in ≤ 7 Tagen:

| Symbol | Earnings | JSON-Cache | Ergebnis Pre-Filter |
|--------|----------|------------|---------------------|
| BX     | 2026-04-17 (HEUTE) | ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| FITB   | 2026-04-17 (HEUTE) | ⚠️ Stale seit 2026-02-13 | → **PASSIERT** (cache.get()=None) |
| RF     | 2026-04-17 (HEUTE) | ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| TFC    | 2026-04-17 (HEUTE) | ⚠️ Stale seit ~Feb | → **PASSIERT** (cache.get()=None) |
| TSLA   | 2026-04-21 (4 Tage)| ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| GE     | 2026-04-21 (4 Tage)| ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| UNH    | 2026-04-21 (4 Tage)| ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| ISRG   | 2026-04-21 (4 Tage)| ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| RTX    | 2026-04-21 (4 Tage)| ⚠️ Stale seit ~Feb | → **PASSIERT** (cache.get()=None) |
| UAL    | 2026-04-21 (4 Tage)| ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |
| LMT    | 2026-04-21 (4 Tage)| ❌ NICHT IM CACHE | → **PASSIERT** (unsafe) |

**Ergebnis: 100% der getesteten Symbole mit bevorstehenden Earnings passieren den Filter.**

---

## ROOT CAUSE

### Problem: Zwei-Datenquellen-Divergenz

Der Earnings-Filter benutzt die **falsche Datenquelle**.

```
earnings_history DB (626 Einträge, aktuell)   ← NICHT VERWENDET vom Filter
       ↕ (kein gemeinsamer Code-Pfad)
earnings_cache.json (5 frische von 124)        ← WIRD VERWENDET vom Filter
```

**Konkret**: `_apply_earnings_prefilter()` ruft `self._ctx.earnings_fetcher.cache.get(symbol)` auf. Dies liest die JSON-Datei `~/.optionplay/earnings_cache.json`. Wenn ein Symbol dort **nicht vorhanden** oder der Eintrag **abgelaufen** ist (TTL = 28 Tage), gibt `cache.get()` `None` zurück. Der Filter-Code reagiert darauf mit `safe.append(symbol)` — das Symbol passiert ohne Prüfung.

Dasselbe gilt für `_should_skip_for_earnings()` im Scanner.

### Warum ist der JSON-Cache so leer/veraltet?

Der `EarningsFetcher` füllt seinen JSON-Cache **on-demand** über yfinance, wenn `fetcher.fetch(symbol)` aufgerufen wird. Dieses Fetch findet nur statt wenn der Cache **nicht** bedient hat. Da der Cache nahezu nie warm gehalten wird (kein regelmäßiges Pre-Warming), sind fast alle Einträge abgelaufen.

Die `earnings_history`-DB hingegen wird aktiv durch `scripts/collect_earnings_eps.py` (via IBKR/marketdata) gepflegt — sie war heute noch um 17:18 Uhr aktualisiert. Diese reichhaltige Quelle wird vom Filter ignoriert.

### Bekanntes Design-Intent vs. Realität

Kommentar in `_should_skip_for_earnings()` (Zeile 853):
> "Die primäre Filterung erfolgt im MCP-Server via `_apply_earnings_prefilter()`"

Beide Schichten sind als Sicherheitsnetz konzipiert — aber beide versagen, weil sie auf dieselbe unzuverlässige JSON-Cache-Quelle vertrauen.

---

## FIX-EMPFEHLUNG

### Kurzfristig (1-2h): `_apply_earnings_prefilter()` auf `EarningsHistoryManager` umstellen

Ersetze in `scan_composed.py:_apply_earnings_prefilter()` die JSON-Cache-Abfrage durch einen direkten DB-Lookup via `EarningsHistoryManager`:

```python
# Statt:
cached = self._ctx.earnings_fetcher.cache.get(symbol)
if cached and cached.days_to_earnings is not None:
    if cached.days_to_earnings >= min_days:
        safe.append(symbol)

# Besser: EarningsHistoryManager.is_earnings_day_safe()
from ..cache import get_earnings_history_manager
ehm = get_earnings_history_manager()
if ehm.is_earnings_day_safe(symbol, buffer_days=min_days):
    safe.append(symbol)
else:
    excluded += 1
```

`EarningsHistoryManager.is_earnings_day_safe()` liest direkt aus `earnings_history` DB, berücksichtigt AMC/BMO-Logik und ist immer aktuell.

### Mittelfristig: `EarningsFetcher.cache` als primäre Datenquelle durch DB ersetzen

Der `EarningsFetcher` (yfinance-basiert) sollte `earnings_history` als erste Quelle abfragen, yfinance nur als Fallback für Symbole die nicht in der DB sind. Dies würde auch `_should_skip_for_earnings()` im Scanner reparieren.

### Nebenproblem: 35 Symbole ohne DB-Einträge

Die meisten sind ETFs (SPY, QQQ, XLP, XLV etc.) — die haben keine Earnings, das ist korrekt. Einige Aktien wie JPM, BAC, BLK, NFLX, SCHW fehlen in `earnings_history` für zukünftige Termine — deren nächste Earnings sollten via `collect_earnings_eps.py` nachgepflegt werden.

---

*Erstellt: 2026-04-17 | Diagnose-Only, kein Code-Eingriff*

---

## Resolution — 2026-04-17 (branch `fix/earnings-filter-db`)

### Commits

| Hash | Datei | LOC | Änderung |
|------|-------|-----|----------|
| `68135ae` | `src/handlers/scan_composed.py` | +55 / -8 | Prefilter auf DB (Commit 1) |
| `2c3a5fe` | `src/cache/earnings_history.py`, `scan_composed.py` | +69 / -11 | Scanner-Cache Batch-Pre-Fetch (Commit 2) |
| `cbc4691` | `tests/integration/test_earnings_filter.py` | +310 / 0 | 17 Integrationstests (Commit 3) |

### Was wurde geändert

**Commit 1 — `_apply_earnings_prefilter()` auf DB umgestellt**

- Primärquelle: `EarningsHistoryManager.is_earnings_day_safe_batch_async()` — eine einzige SQL-Query für alle Symbole.
- Fail-closed: Nur Symbole mit `reason == "no_earnings_data"` (keine Earnings-Historie = ETFs/ADRs) passieren bei fehlendem Eintrag. Alle anderen `False`-Resultate blockieren das Symbol.
- Fallback: JSON-Cache (`EarningsFetcher.cache`) bleibt aktiv, wenn die DB eine Exception wirft.

**Commit 2 — Scanner-Cache Batch-Pre-Fetch**

- Neue Methode `EarningsHistoryManager.get_next_earnings_dates_batch()`: eine einzige `SELECT MIN(earnings_date) ... GROUP BY symbol`-Query für alle Scan-Symbole.
- Ersetzt den JSON-Cache-Loop (Zeilen 149–156) in `_execute_scan()`, der `scanner.set_earnings_date()` mit veralteten Daten befüllte.
- `_should_skip_for_earnings()` im Scanner profitiert automatisch: sein `_earnings_cache` enthält jetzt Live-DB-Daten.

### Verifikation

| Symbol | Situation | Ergebnis |
|--------|-----------|---------|
| BX | Earnings heute (AMC) | **JA, ausgeschlossen** (DB-Eintrag `2026-04-17`, reason `earnings_amc_today`) |
| TSLA | Earnings in 4 Tagen | **JA, ausgeschlossen** (DB-Eintrag `2026-04-21`, reason `too_close_4d`) |
| SPY | Kein Earnings-Eintrag (ETF) | **JA, passiert** (reason `no_earnings_data` → pass-through) |

### Tests vorher / nachher

| Scope | Vorher | Nachher |
|-------|--------|---------|
| Earnings-Tests gesamt | 269 passed | 286 passed (+17) |
| Gesamtsuite (ohne e2e) | 5704 passed | 5721 passed |

### Offene Punkte

- **Fehlende DB-Einträge**: JPM, BAC, BLK, NFLX, SCHW u.a. haben keine zukünftigen Earnings in `earnings_history`. `scripts/collect_earnings_eps.py` nachführen.
- **Fail-open für unbekannte Symbole**: Symbole ohne jegliche Earnings-Historie (`no_earnings_data`) passieren den Filter — das ist für ETFs korrekt, kann aber für Aktien mit Datenlücken gefährlich sein. Mitigation: Watchlist-Coverage mit `collect_earnings_eps.py` verbessern.
