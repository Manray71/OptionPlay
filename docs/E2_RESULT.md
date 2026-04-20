# E.2 Result — AlphaScorer + Longlist

**Branch:** `feature/alpha-engine-e1`
**Date:** 2026-04-20

---

## New Files

| File | Purpose |
|------|---------|
| `src/models/alpha.py` | `AlphaCandidate` frozen dataclass |
| `src/services/alpha_scorer.py` | `AlphaScorer` service (composite, percentile, ampel) |
| `tests/unit/test_alpha_scorer.py` | 37 unit tests |

## Modified Files

| File | Change |
|------|--------|
| `src/models/__init__.py` | Register `AlphaCandidate` export |
| `config/trading.yaml` | Add `alpha_longlist_size: 30` under `sector_rs` |

---

## AlphaCandidate Fields

| Field | Type | Source |
|-------|------|--------|
| `symbol` | str | Input |
| `b_raw` | float | StockRS (slow RS-Ratio - 100) |
| `f_raw` | float | StockRS (fast RS-Ratio - 100) |
| `alpha_raw` | float | Computed: `b_raw + 1.5 * f_raw` |
| `alpha_percentile` | int | Percentile-Rank 0-100 |
| `quadrant_slow` | RSQuadrant | StockRS passthrough |
| `quadrant_fast` | RSQuadrant | StockRS passthrough |
| `dual_label` | str | StockRS passthrough (e.g. "LAG->IMP") |
| `sector` | str | Fundamentals DB lookup |

---

## Percentile Calculation

Rank-based percentile: `position / (N-1) * 100`, rounded to integer. Highest score gets P100, lowest gets P0. Single symbol defaults to P50.

---

## Ampel Matrix

| Slow Window | Fast Window | Ampel | Text |
|-------------|-------------|-------|------|
| Bullish (IMP/LEAD) | Bullish (IMP/LEAD) | **green** | Tradeable |
| Bearish (WEAK/LAG) | Bullish (IMP/LEAD) | **yellow** | Vorsicht — 100d noch schwach |
| Bullish (IMP/LEAD) | Bearish (WEAK/LAG) | **yellow** | Vorsicht — 20d schwacht sich ab |
| Bearish (WEAK/LAG) | Bearish (WEAK/LAG) | **red** | Not tradeable |

---

## Test Count

| | Before | After |
|--|--------|-------|
| Tests | 5,746 | 5,783 (+37) |
| Failures | 0 | 0 |
| Skipped | 29 | 29 |

---

## Architecture Notes

- `AlphaCandidate` uses `TYPE_CHECKING` guard for `RSQuadrant` import to avoid circular dependency (models -> services -> analyzers -> models)
- Sector lookup uses `get_fundamentals_batch()` for efficient bulk DB access
- `AlphaScorer._compute_ampel()` is a static method (stateless, testable in isolation)
- Config loaded via standard YAML loader pattern (same as `sector_rs.py`)

---

## Open Points

- E.3 will add Telegram/Web integration for longlist display
- Sector alpha summary (`get_sector_alpha_summary()`) ready for RRG-Chart frontend
