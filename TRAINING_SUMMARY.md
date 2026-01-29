# OptionPlay Training Summary
**Date:** 2026-01-28

## Training Phases Completed

### 1. Exit Strategy Optimization
**File:** `scripts/exit_strategy_training.py`

| Parameter | Old Value | New Value | Reason |
|-----------|-----------|-----------|--------|
| Profit Target | 75% | **100%** | Maximizes P&L |
| Stop Loss | 100% | **150%** | Tight stops hurt returns |
| DTE Exit | 7 | **7** | Gamma risk management |

**Key Finding:** Stop-loss at 100% triggers too often during normal volatility, cutting winners short.

### 2. Component Weight Training
**File:** `scripts/component_weight_training.py`
**Output:** `~/.optionplay/models/COMPONENT_WEIGHTS_TRAINED.json`

Tested 57 weight variations across 343 symbols (42,393 trades).

| Component | Weight | Impact |
|-----------|--------|--------|
| RSI | 1.0 | Standard |
| Support | 1.0 | Standard |
| Fibonacci | 1.0 | Standard |
| MA | 1.0 | Standard |
| Trend Strength | 1.0 | Standard |
| Volume | 1.0 | Standard |
| MACD | 1.0 | Standard |
| Stochastic | 1.0 | Standard |
| Keltner | 1.0 | Standard |
| VWAP | 1.0 | Standard |
| **Market Context** | **0.5** | Reduced - less predictive |
| **Sector** | **0.0** | Removed - not predictive |

### 3. Ensemble Re-Training (V2)
**File:** `scripts/train_ensemble_v2.py`
**Output:** `~/.optionplay/models/ENSEMBLE_V2_TRAINED.json`

52,935 trades across 343 symbols.

**Strategy Performance:**
| Strategy | Win Rate | Trades |
|----------|----------|--------|
| Pullback | 55.8% | 16,476 |
| Bounce | 54.4% | 13,442 |
| ATH Breakout | 55.1% | 10,419 |
| Earnings Dip | 55.5% | 12,598 |

**Feature Impact Analysis:**
| Feature | Best Condition | Win Rate |
|---------|----------------|----------|
| VWAP | Medium distance | 59.8% |
| Market Context | Sideways | 59.2% |
| **Sector** | **Favorable** | **74.9%** |

### 4. Symbol Clustering
**File:** `scripts/train_symbol_clustering.py`
**Output:** `~/.optionplay/models/SYMBOL_CLUSTERS.json`

343 symbols clustered into 9 groups.

**Best Performing Clusters:**
| Cluster | Symbols | Best Strategy | Win Rate |
|---------|---------|---------------|----------|
| **Steady Medium** | 24 | Bounce | **80.9%** |
| **Steady High** | 7 | Bounce | **80.0%** |
| **Steady Low** | 6 | Earnings Dip | **76.5%** |
| Moderate High | 64 | ATH Breakout | 65.4% |
| Moderate Medium | 99 | Bounce | 64.3% |

**Key Insight:** Low-volatility stocks (Utilities, Consumer Staples) have 80%+ win rates with Bounce strategy!

**Top Steady Cluster Symbols:**
- ATO, KO, PG, ED, DUK, JNJ, MCD, SPY, WM, LIN

### 5. Comprehensive Backtest
**File:** `scripts/backtest_trained_system.py`
**Output:** `~/.optionplay/models/BACKTEST_RESULTS.json`

Out-of-sample testing (last 30% of data).

**Results:**
| Metric | Baseline | Trained | Change |
|--------|----------|---------|--------|
| Win Rate | 79.4% | 80.7% | +1.3% |
| Sharpe Ratio | 0.30 | 0.17 | -43% |

**Strategy Breakdown (Trained System):**
| Strategy | Win Rate | Avg P&L |
|----------|----------|---------|
| **ATH Breakout** | **84.2%** | **13.04%** |
| **Bounce** | **81.9%** | **10.01%** |
| Earnings Dip | 69.7% | -5.34% |
| Pullback | 68.9% | -6.02% |

---

## Recommendations

### 1. Focus on Best Strategies
- **Primary:** ATH Breakout (84.2% WR)
- **Secondary:** Bounce (81.9% WR)
- **Avoid:** Pullback and Earnings Dip (lower performance)

### 2. Target Best Clusters
- **Priority:** Steady (low vol) stocks → 80%+ win rate
- Focus on: Utilities, Consumer Staples, Large-cap defensive names

### 3. Exit Strategy
- Hold to expiration (PT=100%)
- Wide stop-loss (SL=150%)
- Close at 7 DTE for gamma risk

### 4. Symbol Selection Priority
1. Check if symbol is in "Steady" cluster → Use Bounce
2. Check if near ATH with volume → Use ATH Breakout
3. Avoid volatile low-price stocks

---

## Model Files

| File | Description |
|------|-------------|
| `COMPONENT_WEIGHTS_TRAINED.json` | Optimal indicator weights |
| `ENSEMBLE_V2_TRAINED.json` | Symbol preferences, feature impact |
| `SYMBOL_CLUSTERS.json` | Symbol-to-cluster mapping |
| `BACKTEST_RESULTS.json` | Full backtest results |

---

## Next Steps

1. **Paper Trading:** Test system with live data
2. **Walk-Forward:** Regular retraining (monthly)
3. **Risk Management:** Position sizing based on cluster confidence
