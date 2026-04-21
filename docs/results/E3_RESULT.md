# E.3 Result — Alpha-Engine Pipeline-Verdrahtung

**Branch:** feature/alpha-engine-e1
**Datum:** 2026-04-20

---

## Architektur: Vorher vs. Nachher

```
VORHER:
  Default-Watchlist (275) -> Scanner (Filter + Score) -> Ranking -> Top Picks

NACHHER:
  ALL Watchlists (418 merged, deduplicated)
    -> AlphaScorer (B+1.5F, Percentile) -> Longlist (30)
      -> Scanner (Filter + Score) -> Ranking -> Top Picks
         mit alpha_percentile, dual_label in der Ausgabe
```

---

## Geaenderte Dateien

| Datei | Aenderung | LOC Delta |
|-------|-----------|-----------|
| `config/trading.yaml` | `alpha_engine_enabled: true` flag | +1 |
| `src/services/alpha_scorer.py` | `get_alpha_filtered_symbols()` shared helper | +38 |
| `src/services/recommendation_engine.py` | DailyPick alpha fields + to_dict() | +12 |
| `src/handlers/scan_composed.py` | Alpha wiring in `_daily_picks_core()` + `_run_scan_core()` + `_load_trading_config()` | +62 |
| `tests/integration/test_alpha_pipeline.py` | 18 integration tests | +290 (new) |

---

## Feature-Flag Verhalten

| Zustand | Verhalten |
|---------|-----------|
| `alpha_engine_enabled: true` | Merge default_275 + extended_600, run AlphaScorer, pass Top-30 to Scanner |
| `alpha_engine_enabled: false` | Fall back to previous behavior (Tier-1 / stable watchlist) |
| Alpha-Engine throws Exception | Graceful degradation -> full watchlist (logged as error) |
| Alpha-Longlist returns [] | Graceful degradation -> full watchlist (logged as warning) |

---

## Pfade die Alpha nutzen

| Pfad | Handler | Alpha-Integration |
|------|---------|-------------------|
| `/daily` (daily_picks) | `scan_composed._daily_picks_core()` | Full: filter + enrich picks |
| `/scan` (multi_strategy) | `scan_composed._run_scan_core()` | Filter only (no pick enrichment) |
| `daily_picks_result()` (Telegram) | via `_daily_picks_core()` | Full: filter + enrich picks |

---

## Pfade die NICHT geaendert wurden

- `MultiStrategyScanner` -- unchanged, receives narrower symbol list
- `PullbackAnalyzer` / `BounceAnalyzer` -- unchanged
- `pick_formatter.py` -- unchanged (alpha fields are Optional, None when disabled)
- `recommendation_ranking.py` -- unchanged
- `signal_filter.py` -- unchanged
- `enhanced_scoring.py` -- unchanged

---

## Test-Count

- Vorher: 5783 passed, 29 skipped
- Nachher: 5801 passed, 29 skipped (+18 new alpha pipeline tests)

---

## Smoke-Test Output

```
# Feature-Flag Off:
Feature-Flag Off: OK (full watchlist, no alpha)

# Pipeline (IBKR unavailable -- graceful degradation):
default_275: 268, extended_600: 383, merged: 418
Alpha-Longlist empty, falling back to full watchlist
After Alpha: 418 symbols from 418 input
```

---

## Offene Punkte

- E.4: Frontend-Anzeige der Alpha-Felder (quadrant badges, percentile bar)
- E.5: Telegram-Formatter zeigt dual_label und alpha_percentile
- Alpha-Longlist wird erst produktiv wenn IBKR/SPY-Daten verfuegbar (RS braucht Marktdaten)
