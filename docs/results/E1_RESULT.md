# E.1 Result — Dual-Window RS (Slow 50/14 + Fast 10/5)

**Branch:** `feature/alpha-engine-e1`
**Date:** 2026-04-20

---

## Changed Files

| File | Change | LOC delta |
|------|--------|-----------|
| `config/trading.yaml` | sector_rs section updated + new fast keys | +14 / -3 |
| `src/services/sector_rs.py` | Dual-window logic, new dataclasses, batch stock method | +225 / -12 |
| `tests/unit/test_sector_rs.py` | E.1 test classes added | +325 / -13 |

---

## Config Diff (sector_rs)

```yaml
# BEFORE
sector_rs:
  enabled: true
  benchmark: "SPY"
  lookback_days: 60       # → 120
  ema_fast: 10            # removed (moved to fast_ema)
  ema_slow: 30            # → 50
  momentum_lookback: 5    # → 14
  cache_ttl_hours: 8
  score_modifiers: ...

# AFTER
sector_rs:
  enabled: true
  benchmark: "SPY"
  # Slow window (B)
  lookback_days: 120
  ema_slow: 50            # was 30 — affects score_modifier quadrant boundary
  momentum_lookback: 14   # was 5
  # Fast window (F) — NEW
  fast_window: 20
  fast_ema: 10
  fast_momentum_lookback: 5
  fast_weight: 1.5        # B + 1.5*F (used in E.2)
  cache_ttl_hours: 8
  score_modifiers: ...    # unchanged (slow-quadrant based)
```

---

## New API Surface

### `SectorRS` (extended, backward-compatible defaults)
```python
rs_ratio_fast: float = 100.0
rs_momentum_fast: float = 100.0
quadrant_fast: RSQuadrant = RSQuadrant.LEADING
dual_label: str = ""       # e.g. "LAG→IMP", "LEADING"
```

### `StockRS` (new dataclass)
```python
symbol, rs_ratio, rs_momentum, quadrant,
rs_ratio_fast, rs_momentum_fast, quadrant_fast,
dual_label, b_raw, f_raw
```

### `_compute_dual_label(slow, fast) -> str`
Returns `slow.value.upper()` when equal, else `"LEAD→WEAK"` format.

### `SectorRSService.get_all_stock_rs(symbols) -> dict[str, StockRS]`
Batch-optimised: fetches SPY once + all symbols in one parallel gather.

### `get_all_sector_rs_with_trail()` output (extended)
```json
{
  "XLK": {
    "rs_ratio": 102.3, "rs_momentum": 101.1, "quadrant": "leading",
    "rs_ratio_fast": 103.5, "rs_momentum_fast": 102.0,
    "quadrant_fast": "leading", "dual_label": "LEADING",
    "score_modifier": 0.5,
    "trail": [...],
    "trail_fast": [...]
  }
}
```

---

## Smoke Test Output

No live IBKR connection in dev — neutral fallback fires (expected behaviour):
```
No SPY data, returning neutral RS
XLC   Slow: 100.00/100.00 leading     Fast: 100.00/100.00 leading     LEADING
XLY   Slow: 100.00/100.00 leading     Fast: 100.00/100.00 leading     LEADING
...
```

Stock-level: `No SPY data for stock RS batch` — same reason, struct correct.

---

## Test Count

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| `test_sector_rs.py` | 34 | 66 | +32 |
| Full suite (excl. broken collection) | 5549 | 5667 | +118 |
| Pre-existing failures | 8 | 8 | 0 |

---

## Open Points

- E.2 AlphaScorer: consume `b_raw` / `f_raw` from `StockRS` for composite `B + 1.5*F`
- Percentile-rank normalisation deferred to E.2 (by design)
- Smoke test with live IBKR data not possible in dev; unit tests fully cover the logic
