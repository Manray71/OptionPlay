# Earnings Filter Fix — Result (2026-04-17)

Branch: `fix/earnings-filter-db`

---

## Commits

| Hash | Dateien | LOC | Änderung |
|------|---------|-----|----------|
| `68135ae` | `src/handlers/scan_composed.py` | +55 / -8 | Commit 1: `_apply_earnings_prefilter()` auf DB umgestellt |
| `2c3a5fe` | `src/cache/earnings_history.py`, `src/handlers/scan_composed.py` | +69 / -11 | Commit 2: Scanner-Cache Batch-Pre-Fetch aus DB |
| `cbc4691` | `tests/integration/test_earnings_filter.py` | +310 / 0 | Commit 3: 17 Integrationstests |
| `3be66f3` | `docs/EARNINGS_FILTER_DIAGNOSIS.md` | +203 / 0 | Commit 4: Dokumentation |

---

## Verifikation

| Symbol | Situation | Ausgeschlossen? |
|--------|-----------|-----------------|
| BX | Earnings heute (AMC, `2026-04-17`) | **JA** — reason `earnings_amc_today` |
| TSLA | Earnings in 4 Tagen (`2026-04-21`) | **JA** — reason `too_close_4d` |
| SPY | Kein Earnings-Eintrag (ETF) | **NEIN** — reason `no_earnings_data`, passiert |

---

## Tests vorher / nachher

| Scope | Vorher | Nachher |
|-------|--------|---------|
| Earnings-Tests (`-k earnings`) | 269 passed | 286 passed (+17) |
| Gesamtsuite (ohne e2e) | 5704 passed | 5721 passed (+17) |
| Skipped | 29 | 29 |

---

## Geänderte Logik

### Prefilter (`_apply_earnings_prefilter`)

**Alt (fail-open):**
- Quelle: `EarningsFetcher.cache` (JSON, kann veraltet sein)
- Kein Cache-Hit → Symbol passiert (gefährlich)

**Neu (fail-closed):**
- Quelle: `EarningsHistoryManager.is_earnings_day_safe_batch_async()` (DB, immer aktuell)
- Einzelne SQL-Query für alle Symbole (O(N) statt N einzelne Queries)
- `(False, None, "no_earnings_data")` → passiert (ETF/ADR ohne Earnings-Historie)
- Alle anderen `False`-Resultate → Symbol blockiert
- Bei DB-Exception: Fallback auf JSON-Cache (alter Pfad)

### Scanner-Cache (`_execute_scan`, ex Zeilen 149–156)

**Alt:**
- Loop über `earnings_fetcher.cache.get(symbol)` pro Symbol
- JSON-Cache konnte veraltet sein → `_should_skip_for_earnings()` blockierte nicht

**Neu:**
- Neue Methode `get_next_earnings_dates_batch()` in `EarningsHistoryManager`
- `SELECT symbol, MIN(earnings_date) FROM earnings_history WHERE earnings_date >= date('now') GROUP BY symbol`
- Befüllt `scanner._earnings_cache` mit Live-Daten → `_should_skip_for_earnings()` arbeitet korrekt
- Bei DB-Exception: Fallback auf JSON-Cache-Loop

---

## Offene Punkte

- **Fehlende DB-Einträge**: JPM, BAC, BLK, NFLX, SCHW u.a. haben keine zukünftigen Earnings in `earnings_history`. Diese Symbole bekommen `reason == "no_earnings_data"` und passieren den Filter (wie ETFs). Mitigation: `scripts/collect_earnings_eps.py` regelmäßig für alle Watchlist-Symbole ausführen.
- **Kein Merge**: Branch bleibt offen für Review.
