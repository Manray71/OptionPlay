# B1A Result: Indicator Foundation

Branch: `verschlankung/b1a-indicator-foundation`
Datum: 2026-04-16

---

## Commits

| # | Hash | Commit-Nachricht | Geaenderte Dateien | LOC+ | Neue Tests |
|---|------|-------------------|--------------------|------|------------|
| 1 | 5e09852 | Add OBV indicator (calculate_obv_series) with 6 unit tests | momentum.py, test_indicators_momentum.py | +31 impl / +65 tests | 7 |
| 2 | 86a21b8 | Add MFI indicator (calculate_mfi_series) with 7 unit tests | momentum.py, test_indicators_momentum.py | +46 impl / +80 tests | 7 |
| 3 | 450811f | Add CMF indicator (calculate_cmf_series) with 8 unit tests | momentum.py, test_indicators_momentum.py | +46 impl / +87 tests | 8 |
| 4 | e572c84 | Add MACD series function (calculate_macd_series) returning dict of line/signal/histogram; 6 unit tests | momentum.py, test_indicators_momentum.py | +56 impl / +51 tests | 6 |
| 5 | 5ec7e0f | Export new volume indicators in src.indicators.__init__ | __init__.py | +10 | 0 |

Gesamt LOC-Delta: +179 (src/indicators/momentum.py), +283 (tests/unit/test_indicators_momentum.py), +10 (src/indicators/__init__.py)

---

## Neue Tests

| Indikator | Tests |
|-----------|-------|
| OBV | 7 |
| MFI | 7 |
| CMF | 8 |
| MACD-Serie | 6 |
| **Total** | **28** |

Tests vorher (test_indicators_momentum.py): 95 | Suite gesamt: 5.401
Tests nachher (test_indicators_momentum.py): 123 | Suite gesamt: 5.514 (verifiziert, .venv/bin/python -m pytest)

---

## Exportierte API

Alle vier Funktionen sind ab `src.indicators` importierbar:

```python
from src.indicators import (
    calculate_obv_series,
    calculate_mfi_series,
    calculate_cmf_series,
    calculate_macd_series,
)
```

### Beispiel-Aufrufe

```python
# OBV
obv = calculate_obv_series(closes=[100.0, 101.0, 100.5], volumes=[1000, 1200, 800])
# → [0.0, 1200.0, 400.0]

# MFI (period=14, braucht mindestens 15 Bars)
mfi = calculate_mfi_series(highs, lows, closes, volumes, period=14)
# → [78.3, 81.2, ...] (Werte 0-100)

# CMF (period=20, braucht mindestens 20 Bars)
cmf = calculate_cmf_series(highs, lows, closes, volumes, period=20)
# → [0.32, 0.28, ...] (typisch -1.0 bis 1.0)

# MACD-Serie
result = calculate_macd_series(closes, fast_period=12, slow_period=26, signal_period=9)
# → {'line': [...], 'signal': [...], 'histogram': [...]}
# Alle drei Listen gleicher Laenge; result['line'][-1] == calculate_macd(closes).macd_line
```

---

## Smoke-Tests

```
$ python -c "from src.indicators import calculate_obv_series, calculate_mfi_series, calculate_cmf_series, calculate_macd_series; print('all imports OK')"
all imports OK

$ python -m src.mcp_main  (3s boot check)
# Keine Fehler. Eine DeprecationWarning fuer get_secure_config() — pre-existing, nicht durch diese Aenderungen verursacht.
```

---

## Implementierungshinweise

- **OBV**: Erster Wert ist 0.0 per Konvention. Laenge == len(closes).
- **MFI**: Ausgabelaenge = len(closes) - period. Positive-flow-only-Edge-Case (alle TPs steigen) → 100.0.
- **CMF**: Ausgabelaenge = len(closes) - period + 1. H==L und volume==0 schutzen gegen Division-by-Zero (→ 0.0). Bereich theoretisch -1.0 bis 1.0.
- **MACD-Serie**: Ausgabelaenge = len(prices) - slow_period - signal_period + 2. Letzter Wert jeder Serie ist konsistent mit `calculate_macd()` Skalar (getestet via `test_macd_series_last_value_matches_scalar_macd`). `Dict` statt `Optional[Tuple]` fuer klare Lesbarkeit.
- `calculate_macd()` (Skalar) bleibt unveraendert — keine Backward-Compatibility-Risiken.
- `typing.Dict` als Import ergaenzt (war vorher nicht in momentum.py).

---

## Offene Punkte

Keine. Alle Edge Cases abgedeckt, alle Tests gruen.
Naechster Schritt: B1b/B1c — Divergenz-Checks in bounce.py / pullback.py integrieren.
