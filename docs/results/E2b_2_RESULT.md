# E.2b.2 Result — Money Flow + Divergenz + PRE-BREAKOUT
**Datum:** 2026-04-21
**Branch:** `feature/e2b-alpha-composite`
**Commit:** 89d7c1e

---

## Status

Alle Akzeptanzkriterien erfüllt.

---

## Implementierte Komponenten

### Money Flow Score

Gewichtete Kombination aus drei Indikatoren (Gewichte YAML-konfigurierbar):

| Indikator | Gewicht | Methode |
|-----------|---------|---------|
| OBV | 40% | `_obv_component()` |
| MFI | 35% | `_mfi_component()` |
| CMF | 25% | `_cmf_component()` |

OBV-Score: +1.0 bei OBV > SMA20, +0.5 Crossover-Bonus wenn Kreuzung in letzten 3 Bars, -0.5 bei Distribution. Bearish-Divergenz-Abzug -1.0 wenn Preis steigt und OBV fällt (5-Bar-Fenster).

MFI-Score: +1.5 bei Reversal (< 30, steigend), +1.0 bei 40-60 steigend, +0.5 bei > 60, -0.5 bei > 80, -1.0 bei < 30 fallend.

CMF-Score: +1.5 bei > 0.10 steigend bis -1.5 bei < -0.10. Fünf Stufen plus Edge-Case CMF=0 → 0.0.

### Divergenz-Penalty

Christians Skala auf dem Composite (unabhängig von Pullback-Analyzer):

| Aktive Checks | Penalty |
|---------------|---------|
| 0 | 0 |
| 1 | -6 |
| 2-3 | -12 |
| 4+ | -20 |

Nutzt 5 vorhandene Checks aus `divergence.py` (price_rsi, price_obv, price_mfi, cmf_macd_falling, cmf_early_warning). Werte YAML-konfigurierbar unter `alpha_composite.divergence_penalties`.

### PRE-BREAKOUT Phase-2-Signal

Diskretes Bool-Flag nach Christians `score_technicals()` L1914-1934:

```
cmf > 0.10 and cmf_rising and
50 <= mfi <= 65 and mfi_rising and
obv > sma20_obv and
50 <= rsi <= 65
```

Gespeichert als `CompositeScore.pre_breakout`. Score-Bonus +20 wird in E.2b.4 eingebaut.

### compute() Update

Alle E.2b.2-Komponenten in `total` integriert mit YAML-Gewichten:

```python
total = rsi_sc * w["rsi"] + mf_sc * w["money_flow"] + div_pen * w["divergence"] + quad_sc * w["quadrant_combo"]
```

---

## Akzeptanzkriterien

| Kriterium | Status |
|-----------|--------|
| `money_flow_score` != 0 für typische Daten | ✅ |
| `divergence_penalty` negativ bei Divergenzen | ✅ |
| `pre_breakout` True bei synthetischen Daten | ✅ |
| `total` reagiert auf Money Flow und Divergenz | ✅ |
| Mindestens 15 neue Tests grün | ✅ 39 neue Tests (58 gesamt) |
| Gesamtsuite: 5820+ passed, 0 failed | ✅ 5859 passed, 29 skipped |
| `black --check` sauber | ✅ |
| Kein Import von `alpha_scorer.py` | ✅ (Test verifiziert) |

---

## Technische Entscheidungen

**Volumes als int casten:** `_divergence_penalty` und die Momentum-Funktionen erwarten `List[int]`. TechnicalComposite verwendet `List[float]` öffentlich. Interner Cast `[int(v) for v in volumes]` vor Übergabe an divergence.py-Funktionen.

**Patch-Pfad für Tests:** `calculate_rsi` in `_pre_breakout_check` wird per Function-Level Import eingebunden. Tests müssen bei `src.indicators.momentum.calculate_rsi` patchen, nicht bei `src.services.technical_composite.calculate_rsi`.

**CMF=0 Edge-Case:** Symmetrische OHLC-Daten (High = Close + x, Low = Close - x) produzieren CMF=0. Explizites `return 0.0` für diesen Fall, kein fall-through zu -0.3.

---

## Geänderte Dateien

| Datei | Änderung |
|-------|---------|
| `src/services/technical_composite.py` | +240 LOC: 6 neue Methoden, CompositeScore.pre_breakout, compute() mit Gewichten |
| `tests/unit/test_technical_composite.py` | +39 neue Tests in 7 Klassen (OBV, MFI, CMF, Money Flow, Divergenz, PRE-BREAKOUT, Integration) |
| `config/trading.yaml` | +12 Zeilen: `divergence_penalties` und `money_flow_scoring` Sektionen |

---

## Nächste Phase

E.2b.3 — Tech Score (SMA-Alignment, Bollinger, ADX) + Breakout-Patterns (Bull Flag, BB Squeeze, VWAP Reclaim, 3-Bar Play, Golden Pocket, NR7+Inside Bar) + Earnings (+12/-28) + Seasonality.
Referenz: `docs/reference/christian_patterns.py`
