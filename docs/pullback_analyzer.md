# Pullback Analyzer — Complete Logic

## Overview

The pullback analyzer identifies stocks in an **uptrend** that have temporarily pulled back to a support level or oversold condition, providing a favorable entry point for Bull-Put-Spreads.

**Key files:**
- `src/analyzers/pullback.py` — Main analyzer with gates and scoring orchestration
- `src/analyzers/pullback_scoring.py` — Individual scoring component methods
- `config/scoring_weights.yaml` — Trained weights per regime/sector
- `config/scanner_config.yaml` — Stability tiers and min_score thresholds
- `config/rsi_thresholds.yaml` — Adaptive RSI thresholds by stability

---

## Entry Gates

Any gate failure immediately disqualifies the symbol (score = 0). Gates are checked **before** scoring to avoid wasting computation.

| Gate | Condition | Rationale | Example |
|------|-----------|-----------|---------|
| **1. RSI Overbought** | RSI > 70 | Stock is overbought, not pulling back — likely reversal | JNJ (RSI 72) |
| **2. Uptrend Required** | Price must be > SMA200 | Pullback requires a prior uptrend; below SMA200 = downtrend → use bounce strategy instead | ZS, DELL |
| **3. Pullback Evidence** | If RSI > 50: price must be < SMA20 | RSI not oversold + price above SMA20 = pure momentum with no dip — not a pullback | KO (RSI 69, above SMA20) |

---

## 14 Scoring Components

If all gates pass, each component is evaluated independently. Components that don't apply score 0 (not a penalty).

| # | Component | Max Score | What it measures |
|---|-----------|-----------|-----------------|
| 1 | **RSI** | 3.0 | Oversold level — adaptive threshold based on stock stability (see `rsi_thresholds.yaml`) |
| 2 | **RSI Divergence** | 3.0 | Bullish divergence: price makes lower low while RSI makes higher low |
| 3 | **Support** | 2.5 | Proximity to support level + number of historical touches |
| 4 | **Fibonacci** | 2.0 | Price near key fib retracement levels (38.2%, 50%, 61.8%) |
| 5 | **Moving Averages** | 2.0 | Dip in uptrend: price > SMA200 but < SMA20 |
| 6 | **Trend Strength** | 2.0 | SMA alignment quality (SMA20 > SMA50 > SMA200, rising) |
| 7 | **Volume** | 2.0 | Low volume on pullback = healthy selling exhaustion (intraday-adjusted) |
| 8 | **MACD** | 2.0 | Bullish crossover or histogram turning positive |
| 9 | **Stochastic** | 2.0 | Oversold stochastic K/D cross |
| 10 | **Keltner** | 2.0 | Price near lower Keltner Channel band |
| 11 | **VWAP** | 3.0 | Position relative to VWAP |
| 12 | **Market Context** | 2.0 | SPY trend: uptrend = +2, sideways = 0, downtrend = -0.5 |
| 13 | **Sector** | 1.0 | Sector-specific win rate adjustment from trained weights |
| 14 | **Gap** | 1.0 | Down-gap fill opportunity |

### Adaptive RSI Thresholds (`rsi_thresholds.yaml`)

RSI "neutral" threshold varies by stock stability to avoid penalizing normal pullbacks in stable stocks:

| Stability | Neutral Threshold | Rationale |
|-----------|-------------------|-----------|
| High (≥85) | 50 | RSI 40–50 is normal pullback territory for blue chips |
| Medium (≥70) | 45 | RSI up to 45 qualifies as pullback |
| Low (≥60) | 40 | Needs clearer oversold signal |
| Very Low (<60) | 35 | Volatile stocks need low RSI to confirm |

### Intraday Volume Adjustment

During market hours, partial-day volume is scaled to a full-day estimate to avoid systematic under-counting:

```
scale = 390 / elapsed_minutes_since_open   (capped at 10x)
adjusted_volume = current_volume * scale
volume_ratio = adjusted_volume / avg_volume_20d
```

---

## Score Normalization

### Weight Application

Trained YAML weights from `scoring_weights.yaml` are applied per component. Weights vary by market regime (low/normal/high volatility) and sector.

```
scaled_score = raw_score * (yaml_weight / default_max)
total_score = sum of all scaled component scores
```

### Dynamic max_possible

Instead of dividing by the theoretical maximum of all 14 components (27.3), the normalizer uses only the components that actually contributed:

```
active_maxes = max weights for components that scored > 0
dynamic_max  = sum(active_maxes)

Constraints:
  - Minimum 3 active components required (avoids single-indicator inflation)
  - Floor at 50% of full max (prevents score inflation with few components)

max_possible = max(dynamic_max, full_max * 0.5)
```

### Final Normalization

```
normalized_score = (total_score / max_possible) * 10   [clamped 0–10]
```

**Rationale:** Many components are mutually exclusive during a pullback (e.g., MACD bullish cross conflicts with RSI oversold). A perfect pullback realistically fires 5–8 of 14 components. Dynamic normalization prevents the silent majority of zero-scoring components from diluting the signal.

---

## Post-Score Adjustments

Applied by the scanner after normalization:

| Adjustment | Formula | Effect |
|------------|---------|--------|
| **Stability boost** | +0.5 for stability ≥ 70 | Rewards proven symbols |
| **Win rate multiplier** | `score * (0.7 + win_rate / 300)` | WR 90% = full strength, WR 50% = -13% |
| **Drawdown penalty** | `(drawdown - 10%) * 0.02`, max 30% reduction | Penalizes historically volatile entries |

---

## Qualification Thresholds

Stability-tiered minimum scores from `scanner_config.yaml`. Higher stability = lower bar (proven track record):

| Stability Tier | Threshold | Min Score | Win Rate Basis |
|----------------|-----------|-----------|----------------|
| Premium | ≥ 80 | 2.5 | 94.5% WR from walk-forward |
| Good | ≥ 70 | 3.5 | 86.1% WR |
| Acceptable | ≥ 65 | 4.0 | ~80% WR |
| OK | ≥ 50 | 5.0 | ~75% WR |
| Below 50 | — | Blacklisted | — |

---

## Signal Strength

Based on normalized score (0–10 scale):

| Score Range | Strength |
|-------------|----------|
| ≥ 7.0 | **Strong** |
| ≥ 5.0 | **Moderate** |
| ≥ 3.0 | **Weak** |
| < 3.0 | None (filtered) |

---

## Data Flow

```
Scanner (/api/json/scan)
  └─ scan_handler._fetch_historical_cached(symbol)
       └─ TradierProvider.get_historical_for_scanner() → Tradier API
  └─ AnalysisContext.from_data() — pre-computes indicators
  └─ SPY market_context pre-fetched for batch
  └─ PullbackAnalyzer.analyze(symbol, prices, volumes, highs, lows, context)
       ├─ Gate 1: RSI > 70? → disqualify
       ├─ Gate 2: Price < SMA200? → disqualify
       ├─ Gate 3: RSI > 50 + above SMA20? → disqualify
       ├─ Score 14 components
       ├─ Apply YAML weights
       ├─ Dynamic normalization
       └─ Return PullbackCandidate
  └─ Stability/WR/drawdown adjustments
  └─ Filter by tiered min_score
  └─ Sort, deduplicate, output top N
```

---

## Changes Log (Feb 2026)

| Change | Reason |
|--------|--------|
| Added RSI overbought gate (>70) | JNJ at RSI 72 scored 7.4 as pullback |
| Added uptrend gate (SMA200) | ZS in downtrend scored 8.2 as pullback |
| Added pullback evidence gate (RSI>50 + above SMA20) | KO at RSI 69 with pure momentum scored 8.3 |
| Dynamic normalization (active components only) | Old static max=27.3 crushed scores to 2–3 |
| Floor at 50% of full max | Prevented 3-component inflation to 10+ |
| Adaptive RSI thresholds by stability | RSI 42–50 unfairly penalized stable stocks |
| Intraday volume scaling | Partial-day volume systematically penalized all stocks |
| SPY market_context in single-symbol analysis | Was missing from /analyze endpoint |
| Stability tier min_scores lowered | Premium 3.5→2.5, Good 4.0→3.5, Acceptable 4.5→4.0 |
