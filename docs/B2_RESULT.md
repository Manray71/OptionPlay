# B2 Earnings-Surprise Modifier — Implementierungsergebnis

**Branch:** `verschlankung/b2-earnings-surprise`
**Datum:** 2026-04-17

---

## Commits

| # | Hash | Beschreibung | Dateien | LOC |
|---|------|--------------|---------|-----|
| 1 | f797615 | Add earnings_surprise config to scoring.yaml | `config/scoring.yaml` | +16 |
| 2 | 2f33275 | Add EarningsQualityService: 4-quarter beat/miss pattern scoring | `src/services/earnings_quality.py`, `tests/unit/test_earnings_quality.py` | +440 |
| 3 | 5479fad | Integrate earnings-surprise modifier into Bounce and Pullback | `src/analyzers/bounce.py`, `src/analyzers/pullback.py`, 2 test files | +93 |
| 4 | eaef329 | Regression tests: earnings-surprise thresholds read from YAML | `tests/integration/test_earnings_surprise_yaml.py` | +131 |

---

## Pattern-Stufen (implementiert)

| Pattern | Bedingung (n=4) | Modifier |
|---------|----------------|----------|
| all_beats | 4/4 Beats, 0 Misses | +1.2 |
| mostly_beats | 3/4 Beats, 0 Misses (1 Meet) | +0.6 |
| mixed | beats >= misses (kein klarer Verlierer) | 0.0 |
| mostly_misses | misses > beats | -1.0 |
| many_misses | misses >= n-1 (z.B. 3/4) | -1.8 |
| all_misses | misses == n (4/4) | -2.8 |

Alle Schwellenwerte in `config/scoring.yaml → earnings_surprise.thresholds`.

**Disambiguierung 2b/2m:** `misses > beats` (nicht `misses >= 2`) — 2 beats + 2 misses → mixed (0.0), nicht mostly_misses.

---

## Verifikation

### 4/4 beats → +1.2

```
tests/unit/test_earnings_quality.py::TestAllBeats::test_all_beats_4_of_4 PASSED
  beats=4, misses=0, modifier=1.2, pattern='4/4 beats'
```

### 4/4 misses → -2.8

```
tests/unit/test_earnings_quality.py::TestAllMisses::test_all_misses_4_of_4 PASSED
  beats=0, misses=4, modifier=-2.8, pattern='4/4 misses'
```

### Insufficient data (< 4 Quartale) → 0.0

```
tests/unit/test_earnings_quality.py::TestInsufficientData::test_insufficient_data_3_quarters_min_4 PASSED
  total=3, modifier=0.0, pattern='insufficient data (3/4 quarters)'
```

### YAML-Regression-Test grün

```
tests/integration/test_earnings_surprise_yaml.py::TestEarningsThresholdFromYaml::test_earnings_threshold_all_beats_from_yaml PASSED
tests/integration/test_earnings_surprise_yaml.py::TestEarningsThresholdFromYaml::test_earnings_threshold_all_misses_from_yaml PASSED
tests/integration/test_earnings_surprise_yaml.py::TestEarningsThresholdFromYaml::test_earnings_n_quarters_from_yaml PASSED
tests/integration/test_earnings_surprise_yaml.py::TestEarningsThresholdFromYaml::test_thresholds_are_ordered PASSED
```

---

## Tests vorher / nachher

| Zustand | Passed | Failed | Skipped |
|---------|--------|--------|---------|
| Baseline (main, ohne hypothesis_pbt) | 5482 | 5 | 35 |
| Nach 4 Commits | 5597 | 5 | 29 |
| **Delta** | **+115** | **0** | — |

Neue Tests gesamt: +30 Tests
- `tests/unit/test_earnings_quality.py`: 19 Tests
- `tests/component/test_bounce_analyzer.py`: 2 Tests (TestBounceEarningsSurpriseModifier)
- `tests/component/test_pullback_analyzer.py`: 2 Tests (TestPullbackEarningsSurpriseModifier)
- `tests/integration/test_earnings_surprise_yaml.py`: 7 Tests

Die 5 pre-existing Failures (`test_shadow_tracker.py`) sind unverändert.

---

## Technische Entscheidungen

**Circular Import:** `src/services/__init__.py` re-exportiert `recommendation_engine`, das transitiv `BounceAnalyzer` importiert. Lösung: Lazy Import in beiden Analyzern (innerhalb der Methode), analog zu `sector_rs` in `multi_strategy_scanner.py`.

**Pattern-Mapping:** `misses > beats` statt `misses >= 2` für `mostly_misses`. Begründung: 2b/2m ist ein 50/50-Split → neutral (0.0). Erst wenn Misses die Mehrzahl bilden, greift die Strafe.

---

## Offene Punkte

Keine.
