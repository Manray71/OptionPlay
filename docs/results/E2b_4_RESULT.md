# E.2b.4 — AlphaScorer-Umbau + Post-Crash + Batch-Loading
**Datum:** 2026-04-21
**Branch:** `feature/e2b-alpha-composite`
**Status:** Akzeptanzkriterien erfüllt ✅

---

## Änderungen

### 1. AlphaScorer (`src/services/alpha_scorer.py`)

Neuer `composite_config`-Parameter in `__init__`. Wenn `alpha_composite.enabled = true`:
- `TechnicalComposite` wird lazy importiert und instanziiert (kein Zirkelimport)
- `generate_longlist()` lädt OHLCV via Batch-Loader, ruft `compute()` für Classic (135 Bars) und Fast (30 Bars) auf
- `alpha_raw = b_score.total + f_score.total * 1.5` (normal) oder Post-Crash-Gewichte
- Symbole mit < 30 OHLCV-Bars fallen auf RS-Fallback zurück (kein Crash)

Neue `vix`-Parameter in `generate_longlist()` für Post-Crash-Erkennung.

### 2. AlphaCandidate (`src/models/alpha.py`)

Vier neue optionale Felder (backward-kompatibel, alle mit Default):
- `b_composite: Optional[float]` — Classic-Fenster CompositeScore.total
- `f_composite: Optional[float]` — Fast-Fenster CompositeScore.total
- `breakout_signals: Tuple[str, ...]` — Kombinierte Breakout-Signale (Fast + Classic)
- `pre_breakout: bool` — True wenn PRE-BREAKOUT Phase 2 aktiv

### 3. LocalDBProvider (`src/data_providers/local_db.py`)

`get_batch_ohlcv(symbols, limit=260)` — öffnet **eine** DB-Verbindung für alle Symbole.
Rückgabe: `{symbol: (closes, volumes, highs, lows, opens)}` oder `{symbol: None}`.

### 4. Config (`config/trading.yaml`)

Neuer `post_crash`-Abschnitt unter `alpha_composite`:
```yaml
post_crash:
  classic_weight: 0.3
  fast_weight_adj: 0.7
  score_adjustment: -8
```

---

## Feature-Flag-Status

```yaml
alpha_composite:
  enabled: false   # bleibt false bis E.2b.5 Verifikation
```

Wenn `false`: originale RS-Berechnung (`b_raw + 1.5*f_raw`) läuft unverändert.
Wenn `true`: TechnicalComposite für Classic + Fast, Quadrant-Werte uppercase übergeben.

---

## Post-Crash-Modus

Vereinfachte Implementierung (E.2b.5 bringt vollständigen 7-Signal Stress-Score):

| VIX | Modus | Formel |
|-----|-------|--------|
| < 25 | Normal | `b.total + f.total * 1.5` |
| ≥ 25 | Post-Crash | `b.total * 0.3 + f.total * 0.7 * 1.5` |

Beispiel VIX=30, b=20, f=10:
- Normal: 20 + 15 = 35
- Post-Crash: 6 + 10.5 = 16.5

---

## Batch-OHLCV Performance

Ziel: < 30 Sekunden für 381 Symbole (CPU-bound Indikator-Berechnung, nicht IO-bound).

Methode: Eine SQLite-Verbindung, sequentielles SELECT pro Symbol innerhalb dieser Verbindung.
Erspart 381 Connection-Open/Close-Zyklen gegenüber naiver Implementierung.

**Nicht gemessen in E.2b.4** (Feature-Flag = false, kein echter Scan). Timing-Messung erfolgt in E.2b.5 nach Aktivierung.

---

## Vergleich: Top-10 RS-only vs. Composite

**Nicht ausführbar in E.2b.4** (`alpha_composite.enabled = false`).
Vergleich folgt in E.2b.5 mit aktivem Flag und echten DB-Daten.

---

## Neue Tests (14 neue + alle alten bestehen)

| Klasse | Tests | Thema |
|--------|-------|-------|
| `TestCompositeFeatureFlag` | 8 | Feature-Flag, Post-Crash, Regression |
| `TestBatchOHLCV` | 3 | Batch-Struktur, Slicing, Kurzdata-Fallback |
| `TestCompositeIntegration` | 3 | Ranking-Plausibilität, Toggle, Import-Check |

**Gesamt:** 5914 passed, 29 skipped, 0 failed (vorher 5900 passed)

---

## Akzeptanzkriterien

| # | Kriterium | Status |
|---|-----------|--------|
| 1 | `alpha_composite.enabled = true` → TechnicalComposite genutzt | ✅ |
| 2 | `alpha_composite.enabled = false` → alte Berechnung unverändert | ✅ |
| 3 | Post-Crash-Modus schaltbar (VIX-basiert) | ✅ |
| 4 | Batch-OHLCV: ein DB-Open für alle Symbole | ✅ |
| 5 | `get_alpha_filtered_symbols()` korrekte Ausgabe | ✅ |
| 6 | Pipeline-Tests grün (Regression) | ✅ |
| 7 | Mindestens 14 neue Tests | ✅ (14) |
| 8 | Gesamtsuite: 5900+ passed, 0 failed | ✅ (5914) |
| 9 | `black --check` sauber | ✅ |

---

## Nächste Phase

E.2b.5 — Verifikation + Kalibrierung:
- `alpha_composite.enabled = true` setzen
- 20-Symbol-Smoke-Test gegen echte DB
- Score-Range-Analyse (BPS vs Fast getrennt)
- Breakout-Pattern-Verifikation gegen historische Setups (NVDA Bull Flag, AAPL BB Squeeze)
- Timing-Messung für 381-Symbol-Scan
- Gewichts-Tuning falls nötig
- E2b_RESULT.md + PR-Merge nach main
