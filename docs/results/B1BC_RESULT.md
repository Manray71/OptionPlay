# B.1bc — Divergence Checks: Implementation Result

**Branch:** `verschlankung/b1bc-divergence-checks`
**Date:** 2026-04-16
**Status:** ✅ Complete

---

## Per-Commit Summary

| # | Hash | Message | Files Changed | Tests Added |
|---|------|---------|---------------|-------------|
| 1 | afb0790 | Add divergence.py skeleton: DivergenceSignal + _series_falling_n_bars | 2 new | 13 |
| 2–8 | 199e80b–149fbdd | Checks 1–7 (empty marker commits) | 0 | 0 |
| 9 | 511270d | Export divergence checks in src.indicators | 1 | 0 |
| 10 | f24779d | Add divergence penalty constants to config/scoring.yaml | 1 | 0 |
| 11 | 19e4023 | Integrate into Bounce analyzer | 2 | 4 |
| 12 | b52ef83 | Integrate into Pullback analyzer | 2 | 4 |
| 13 | 8082b77 | Regression tests: YAML penalties read | 1 new | 5 |

**LOC added (net):** ~650 (src/) + ~450 (tests/)

---

## All 7 Checks — Implementation Status

| Check | Function | Status |
|-------|----------|--------|
| 1 | `check_price_rsi_divergence` | ✅ Wraps `calculate_rsi_divergence` (bearish divergence_type) |
| 2 | `check_price_obv_divergence` | ✅ find_swing_highs + OBV comparison |
| 3 | `check_price_mfi_divergence` | ✅ With index alignment (MFI is shorter by `mfi_period`) |
| 4 | `check_cmf_and_macd_falling` | ✅ Both falling n bars (uses dict['line'] from calculate_macd_series) |
| 5 | `check_momentum_divergence` | ✅ MFI stable + CMF + RSI falling n bars |
| 6 | `check_distribution_pattern` | ✅ OBV + MFI + CMF all falling (strongest bearish signal) |
| 7 | `check_cmf_early_warning` | ✅ CMF falling n bars but still positive |

---

## Penalty Table

| Check | Name | Penalty | Applies To |
|-------|------|---------|------------|
| 1 | price_rsi | -2.0 | Both |
| 2 | price_obv | -1.5 | Both |
| 3 | price_mfi | -1.5 | Both |
| 4 | cmf_macd_falling | -1.0 | Both |
| 5 | momentum_divergence | -1.5 | Both |
| 6 | distribution_pattern | -3.0 | Both |
| 7 | cmf_early_warning | -1.0 | Both |

**All penalties sourced from:**
- `bounce.divergence.*` in `config/scoring.yaml`
- `pullback.divergence.*` in `config/scoring.yaml`

---

## Worst-Case Scenario

If all 7 bearish divergence checks fire simultaneously:

```
-2.0 + -1.5 + -1.5 + -1.0 + -1.5 + -3.0 + -1.0 = -11.5
```

This is an additive penalty applied to the raw score **before** normalization to 0-10 scale.
A maximum-scoring Bounce signal (10.0) with all 7 checks active would score -1.5 raw,
which normalizes to 0.0 (clamped at 0 by `clamp_score`).

---

## Application Points

### Bounce Analyzer (`src/analyzers/bounce.py`)
- Applied **after** B5 market context multiplier, **before** `clamp_score(total_score, BOUNCE_MAX_SCORE)`
- Method: `BounceAnalyzer._apply_divergence_penalties(prices, highs, lows, volumes, score)`
- Constants: `BOUNCE_DIV_PENALTY_*` (7 module-level constants from YAML)

### Pullback Analyzer (`src/analyzers/pullback.py`)
- Applied **after** component sum + sector_factor, **before** dynamic `max_possible` calculation
- Method: `PullbackAnalyzer._apply_divergence_penalties(prices, highs, lows, volumes, score)`
- Constants: `PULLBACK_DIV_PENALTY_*` (7 module-level constants from YAML)
- **Note:** The existing bullish RSI divergence check (via `_score_rsi_divergence`) is preserved.
  The new check adds BEARISH divergence detection — conceptually separate, no conflict.

---

## Regression Test Result

All 5 regression tests in `tests/integration/test_divergence_penalty_yaml.py` pass:
- Custom severity parameter respected when divergence detected
- Default severity is negative for all 7 functions (verified via `inspect`)
- Bounce/Pullback module constants match YAML values (via direct YAML parse + importlib.reload)

---

## Test Count

| Baseline (before this branch) | Final | Delta |
|-------------------------------|-------|-------|
| 5533 passed | 5591 passed | +58 |

Breakdown of new tests:
- `tests/unit/test_indicators_divergence.py`: 45 tests (DivergenceSignal, 7 check functions)
- `tests/component/test_bounce_analyzer.py`: +4 tests (TestBounceDivergencePenalties)
- `tests/component/test_pullback_analyzer.py`: +4 tests (TestPullbackDivergencePenalties)
- `tests/integration/test_divergence_penalty_yaml.py`: 5 tests (YAML regression)

---

## Architecture Notes

### `_series_falling_n_bars(series, n=3)`
Helper used by checks 4, 5, 6, 7. Returns True if the last n values are strictly
monotonically decreasing. Returns False if `len(series) < n`.

### Index Alignment (Check 3 — MFI)
`calculate_mfi_series` returns `len(closes) - mfi_period` values. The first MFI value
corresponds to `closes[mfi_period]`. For a swing high at price index `i`, the corresponding
MFI index is `i - mfi_period`. Guard conditions prevent out-of-range access.

### API Key Facts (from reading momentum.py)
- `find_swing_highs(values, window, lookback) -> List[Tuple[int, float]]` — (index, value)
- `calculate_obv_series(closes, volumes) -> List[float]` — same length as closes
- `calculate_mfi_series(highs, lows, closes, volumes, period) -> List[float]` — length = `len(closes) - period`
- `calculate_cmf_series(highs, lows, closes, volumes, period) -> List[float]` — length = `len(closes) - period + 1`
- `calculate_macd_series(prices) -> Optional[Dict[str, List[float]]]` — keys: 'line', 'signal', 'histogram'
- `calculate_rsi_series(prices, period) -> List[float]` — same length as prices
- `calculate_rsi_divergence(...) -> Optional[RSIDivergenceResult]` — fields: divergence_type, price_pivot_1/2, rsi_pivot_1/2, strength, formation_days

---

## Known Limitations

1. **Double RSI check in Pullback**: The existing `_score_rsi_divergence` checks for bullish
   divergence (positive signal). `check_price_rsi_divergence` checks for bearish divergence
   (negative penalty). These are logically distinct and can coexist, but RSI data is
   calculated twice (minor performance cost).

2. **Detection rate**: Detection of actual divergences depends on having sufficient swing
   highs/lows within the lookback window. Short or flat price series return `detected=False`.

3. **Interaction with VIX clamp**: Penalties are applied before `clamp_score`, so extreme
   negative scores are clamped to 0. A signal below 0 raw score is silently 0.

4. **Pullback max_possible**: Bearish penalties reduce `breakdown.total_score` but `max_possible`
   is calculated from the unchanged `_components` dict. This means normalization still uses
   the unpenalized reference maximum, which is the correct behavior (penalties are additive
   adjustments, not component removals).
