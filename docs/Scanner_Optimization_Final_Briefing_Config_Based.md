# OptionPlay Scanner Optimization - Final Implementation Briefing
**Datum:** 13. Februar 2026  
**Version:** 4.0.0 → 4.1.0  
**Status:** Production Implementation Ready  

---

## Executive Summary

Die umfassende Validierung mit **35 Symbolen** hat gezeigt, dass der aktuelle Scanner nur **1.7% der Watchlist** (5 von 291) qualifiziert. Die Hauptursachen sind:

1. **Fixer RSI-Threshold von 50** → bestraft 34% der profitablen Setups (88.6% Win Rate!)
2. **Support Bounce: 5+ Tests erforderlich** → zu restriktiv für valide Setups
3. **Earnings Buffer: 45 Tage** → blockt gute Kandidaten

**Lösung:** Adaptive, **config-basierte** Thresholds statt Hardcoding.

**Erwarteter Impact:** +200-300% mehr Daily Picks bei gleichbleibender Qualität (>80% Win Rate).

---

## 1. Validierungs-Ergebnisse (35 Symbole)

### Sample Overview
- **35 Symbole** analysiert (Stability 62-92)
- **19 vollständige RSI-Datenpunkte**
- **Median RSI:** 40.4 (High Stab: 39.8, Medium Stab: 39.6)
- **Win Rate (RSI 40-50):** 88.6% durchschnittlich

### Kernproblem: Fixer RSI-Threshold = 50

**Falsch bestraft (12 von 35 = 34%):**

| Symbol | Stab | RSI | Current Score | Win Rate | Problem |
|--------|------|-----|---------------|----------|---------|
| LLY | 92 | 48.7 | 2.9 | 85% | RSI 48.7 ist normal! |
| MET | 82 | 48.6 | 4.0 | 94% | RSI 48.6 ist normal! |
| AAPL | 85 | 44.8 | 5.6 | 92% | Zu hart bestraft |
| JPM | 87 | 41.9 | 4.9 | 95% | Grenzwertig |
| C | 83 | 40.9 | 4.9 | 88% | Grenzwertig |
| BAC | 83 | 41.7 | 4.7 | 92% | Grenzwertig |
| AMD | 70 | 41.0 | 3.1 | 74% | Für Tech normal |

**Korrekt schwach (RSI < 38):**
- GOOGL (86, RSI 34.4), DHR (85, RSI 37.2), MS (85, RSI 34.8) ✅

---

## 2. Implementierungs-Strategie

### 2.1 Config-First Approach ✅

**KEIN Hardcoding in Python-Code!**

Alle Thresholds werden in **YAML-Config** abgelegt:
- `config/scanner_config.yaml` (globale Defaults)
- `config/regime_config.yaml` (optional: regime-spezifische Overrides)

**Vorteile:**
- Änderungen ohne Code-Deploy
- A/B Testing möglich
- Regime-spezifische Anpassungen
- Einfaches Rollback
- Dokumentation direkt in Config

---

## 3. Config-Struktur

### 3.1 Neue Config-Datei: `config/rsi_thresholds.yaml`

```yaml
# RSI Thresholds by Stability Score
# Based on 35-symbol validation study (Feb 2026)
# Median RSI: 40.4 across all stability levels

rsi_thresholds:
  description: "Adaptive RSI thresholds based on stock stability"
  validation_date: "2026-02-13"
  sample_size: 35
  
  # Threshold definitions
  thresholds:
    high_stability:
      min_stability: 85
      threshold: 42
      rationale: "High stability stocks (85+) have median RSI ~40, threshold at 42 allows normal pullbacks"
    
    medium_stability:
      min_stability: 70
      threshold: 40
      rationale: "Medium stability stocks (70-84) have median RSI ~40, threshold matches median"
    
    low_stability:
      min_stability: 60
      threshold: 38
      rationale: "Lower stability stocks have wider RSI ranges"
    
    very_low_stability:
      min_stability: 0
      threshold: 35
      rationale: "Very volatile stocks need lower threshold"
  
  # RSI bonus/penalty scoring
  scoring:
    severe_oversold:
      max_rsi: 30
      penalty: -1.5
      description: "Extremely oversold, potential falling knife"
    
    oversold:
      max_rsi: null  # Dynamic based on stability threshold
      penalty: -1.0
      description: "Below stability-based threshold"
    
    normal_pullback:
      min_rsi: null  # Dynamic based on stability threshold
      max_rsi: 50
      adjustment: 0
      description: "Normal pullback range, no penalty"
    
    sweet_spot:
      min_rsi: 50
      max_rsi: 60
      bonus: 0.5
      description: "Ideal momentum range"
    
    overbought:
      min_rsi: 70
      penalty: -0.5
      description: "Overbought, may reverse"
  
  # Optional: Regime-specific overrides
  regime_overrides:
    low_vix:  # VIX < 16
      enabled: false
      description: "In low VIX, could tighten thresholds slightly"
    
    elevated_vix:  # VIX 20-30
      enabled: false
      description: "Current regime, use default thresholds"
    
    high_vix:  # VIX > 30
      enabled: false
      description: "In high VIX, could loosen thresholds"
```

### 3.2 Erweitere `config/scanner_config.yaml`

```yaml
# Scanner Configuration
scanner:
  # Earnings Buffer
  earnings_buffer:
    default: 45  # Days
    conservative: 45
    standard: 30
    aggressive: 20
    current_mode: "standard"  # Change to 30 days
  
  # Support Bounce Requirements
  support_bounce:
    min_tests:
      default: 3  # Changed from 5
      strong: 5
      weak: 2
    
    min_touch_quality:
      description: "How close price must be to support level"
      percentage: 2.0  # Within 2% of support
  
  # IV Rank Filter
  iv_rank:
    enabled: true
    min: 30
    max: 80
  
  # General Scoring
  min_score:
    default: 3.5
    conservative: 5.5
    current: 3.5
  
  # Position Limits
  constraints:
    max_positions: 10
    max_sector_concentration: 0.3
    max_daily_risk_usd: 2500
    max_weekly_risk_usd: 5000

# Reference to RSI Config
rsi_config_file: "config/rsi_thresholds.yaml"
```

### 3.3 Optional: `config/regime_config.yaml` Enhancement

```yaml
# VIX Regime Configuration
regimes:
  low:
    vix_range: [0, 16]
    rsi_adjustment: 0  # No change to thresholds
    earnings_buffer: 45
    
  elevated:
    vix_range: [16, 25]
    rsi_adjustment: 0  # No change to thresholds
    earnings_buffer: 30  # More aggressive
    
  high:
    vix_range: [25, 100]
    rsi_adjustment: -2  # Loosen thresholds by 2 points
    earnings_buffer: 20  # Very aggressive
```

---

## 4. Code-Änderungen

### 4.1 Config-Loader (Neu): `utils/config_loader.py`

```python
"""
Config Loader for Scanner Parameters
Centralizes all config loading with validation
"""
import yaml
from pathlib import Path
from typing import Dict, Optional

class ScannerConfig:
    """Loads and manages scanner configuration"""
    
    def __init__(self, base_path: str = "config"):
        self.base_path = Path(base_path)
        self.scanner_config = self._load_yaml("scanner_config.yaml")
        self.rsi_config = self._load_yaml("rsi_thresholds.yaml")
        self.regime_config = self._load_yaml("regime_config.yaml")
    
    def _load_yaml(self, filename: str) -> Dict:
        """Load YAML config file"""
        filepath = self.base_path / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")
        
        with open(filepath, 'r') as f:
            return yaml.safe_load(f)
    
    def get_rsi_threshold(self, stability_score: int) -> int:
        """
        Get RSI threshold based on stability score.
        Uses config-defined thresholds, no hardcoding.
        """
        thresholds = self.rsi_config['rsi_thresholds']['thresholds']
        
        # Find matching threshold tier
        if stability_score >= thresholds['high_stability']['min_stability']:
            return thresholds['high_stability']['threshold']
        elif stability_score >= thresholds['medium_stability']['min_stability']:
            return thresholds['medium_stability']['threshold']
        elif stability_score >= thresholds['low_stability']['min_stability']:
            return thresholds['low_stability']['threshold']
        else:
            return thresholds['very_low_stability']['threshold']
    
    def get_rsi_score_adjustment(self, rsi: float, threshold: int) -> tuple[float, str]:
        """
        Get score adjustment and reason based on RSI value.
        Returns: (score_adjustment, reason)
        """
        scoring = self.rsi_config['rsi_thresholds']['scoring']
        
        # Severe oversold
        if rsi < scoring['severe_oversold']['max_rsi']:
            return (scoring['severe_oversold']['penalty'], 
                    f"RSI {rsi:.1f} severely oversold")
        
        # Below stability threshold
        if rsi < threshold:
            return (scoring['oversold']['penalty'],
                    f"RSI {rsi:.1f} below threshold {threshold}")
        
        # Normal pullback range
        if threshold <= rsi < scoring['normal_pullback']['max_rsi']:
            return (0, f"RSI {rsi:.1f} in normal pullback range")
        
        # Sweet spot
        if scoring['sweet_spot']['min_rsi'] <= rsi <= scoring['sweet_spot']['max_rsi']:
            return (scoring['sweet_spot']['bonus'],
                    f"RSI {rsi:.1f} in sweet spot")
        
        # Overbought
        if rsi >= scoring['overbought']['min_rsi']:
            return (scoring['overbought']['penalty'],
                    f"RSI {rsi:.1f} overbought")
        
        # Default: neutral
        return (0, f"RSI {rsi:.1f}")
    
    def get_support_min_tests(self) -> int:
        """Get minimum support tests required"""
        return self.scanner_config['scanner']['support_bounce']['min_tests']['default']
    
    def get_earnings_buffer(self, mode: Optional[str] = None) -> int:
        """Get earnings buffer in days"""
        earnings_cfg = self.scanner_config['scanner']['earnings_buffer']
        mode = mode or earnings_cfg.get('current_mode', 'default')
        return earnings_cfg.get(mode, earnings_cfg['default'])

# Global config instance
_config = None

def get_config() -> ScannerConfig:
    """Get global config instance (singleton)"""
    global _config
    if _config is None:
        _config = ScannerConfig()
    return _config
```

---

### 4.2 Strategy-Scorer Updates

**File:** `strategies/pullback.py`

```python
"""
Pullback Strategy Scorer
Uses config-based RSI thresholds - NO HARDCODING
"""
from utils.config_loader import get_config

class PullbackScorer:
    def __init__(self):
        self.config = get_config()
    
    def score(self, data: dict) -> tuple[float, list[str]]:
        """Score pullback candidate"""
        score = 5.0  # Base score
        reasons = []
        
        # Get stability and RSI
        stability = data.get('stability', 70)
        rsi = data.get('rsi')
        
        if rsi is None:
            return (score, ["RSI data unavailable"])
        
        # Get adaptive threshold from CONFIG
        rsi_threshold = self.config.get_rsi_threshold(stability)
        
        # Get score adjustment from CONFIG
        adjustment, reason = self.config.get_rsi_score_adjustment(rsi, rsi_threshold)
        
        score += adjustment
        reasons.append(reason)
        
        # ... rest of scoring logic ...
        
        return (score, reasons)
```

**Gleiche Änderungen in:**
- `strategies/bounce.py`
- `strategies/trend_continuation.py`
- `strategies/ath_breakout.py` (wenn RSI verwendet)
- `strategies/earnings_dip.py` (wenn RSI verwendet)

---

### 4.3 Support Bounce Updates

**File:** `strategies/bounce.py`

```python
"""
Support Bounce Strategy Scorer
Uses config-based support test requirements - NO HARDCODING
"""
from utils.config_loader import get_config

class BounceScorer:
    def __init__(self):
        self.config = get_config()
    
    def score(self, data: dict) -> tuple[float, list[str]]:
        """Score bounce candidate"""
        score = 5.0
        reasons = []
        
        support_tests = data.get('support_tests', 0)
        
        # Get minimum tests from CONFIG
        min_tests = self.config.get_support_min_tests()
        
        if support_tests < min_tests:
            score -= 1.0
            reasons.append(f"Support only {support_tests}x tested (min: {min_tests})")
        elif support_tests >= min_tests and support_tests < 5:
            # Acceptable, no penalty
            reasons.append(f"Support {support_tests}x tested (acceptable)")
        elif support_tests >= 5:
            score += 0.5
            reasons.append(f"Strong support ({support_tests}x tested)")
        
        # ... rest of scoring logic ...
        
        return (score, reasons)
```

---

### 4.4 Earnings Filter Update

**File:** `scanner.py` or `filters/earnings_filter.py`

```python
"""
Earnings Pre-Filter
Uses config-based buffer - NO HARDCODING
"""
from utils.config_loader import get_config

class EarningsFilter:
    def __init__(self):
        self.config = get_config()
    
    def filter_symbols(self, symbols: list[str], mode: str = None) -> list[str]:
        """
        Filter symbols by earnings date.
        
        Args:
            symbols: List of symbols to filter
            mode: 'conservative', 'standard', 'aggressive', or None (uses config default)
        """
        buffer_days = self.config.get_earnings_buffer(mode)
        
        filtered = []
        for symbol in symbols:
            days_to_earnings = get_days_to_earnings(symbol)
            
            if days_to_earnings is None or days_to_earnings > buffer_days:
                filtered.append(symbol)
        
        return filtered
```

---

## 5. Migration Steps

### Phase 1: Config Setup (30 min)

```bash
# 1. Create new config files
cd ~/OptionPlay/config/

# 2. Create rsi_thresholds.yaml
cat > rsi_thresholds.yaml << 'EOF'
# [Insert full YAML from section 3.1]
EOF

# 3. Update scanner_config.yaml
# Add sections from 3.2

# 4. Update regime_config.yaml (optional)
# Add regime-specific overrides if desired
```

### Phase 2: Code Updates (1 hour)

```bash
# 1. Create config loader
cat > utils/config_loader.py << 'EOF'
# [Insert code from section 4.1]
EOF

# 2. Update strategy scorers
# Edit files in strategies/ directory
# Replace hardcoded thresholds with config calls

# 3. Update earnings filter
# Replace hardcoded 45 with config call

# 4. Add unit tests
cat > tests/test_config_loader.py << 'EOF'
import pytest
from utils.config_loader import ScannerConfig

def test_rsi_thresholds():
    config = ScannerConfig()
    
    assert config.get_rsi_threshold(92) == 42  # High stability
    assert config.get_rsi_threshold(85) == 42
    assert config.get_rsi_threshold(75) == 40  # Medium
    assert config.get_rsi_threshold(65) == 38  # Low
    assert config.get_rsi_threshold(50) == 35  # Very low

def test_support_tests():
    config = ScannerConfig()
    assert config.get_support_min_tests() == 3

def test_earnings_buffer():
    config = ScannerConfig()
    assert config.get_earnings_buffer('standard') == 30
    assert config.get_earnings_buffer('conservative') == 45
EOF

pytest tests/test_config_loader.py
```

### Phase 3: Validation (1 hour)

```bash
# 1. Restart MCP Server
cd ~/OptionPlay
pkill -f "optionplay"
python -m optionplay.server &

# 2. Run Daily Picks
# Should see 11-15 picks instead of 5

# 3. Verify specific symbols are recovered
# LLY, AAPL, MET should appear

# 4. Check logs for config loading
grep "Config loaded" logs/optionplay.log
grep "RSI threshold" logs/optionplay.log
```

### Phase 4: Monitoring (2-3 days)

```bash
# Track results
echo "Date,Picks,Top_Score,Avg_Score" > validation_log.csv

# Daily monitoring
python scripts/monitor_picks.py >> validation_log.csv
```

---

## 6. Config Management Best Practices

### 6.1 Version Control

```bash
# Commit config changes with clear messages
git add config/rsi_thresholds.yaml
git commit -m "feat: Add adaptive RSI thresholds based on 35-symbol validation"

git add config/scanner_config.yaml
git commit -m "feat: Reduce earnings buffer to 30d, support tests to 3"
```

### 6.2 Config Validation Script

**File:** `scripts/validate_config.py`

```python
#!/usr/bin/env python3
"""
Validate scanner configuration
Ensures all required fields are present and values are sane
"""
import yaml
from pathlib import Path

def validate_rsi_config(config_path: Path):
    """Validate RSI threshold config"""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    
    thresholds = cfg['rsi_thresholds']['thresholds']
    
    # Check all tiers exist
    assert 'high_stability' in thresholds
    assert 'medium_stability' in thresholds
    assert 'low_stability' in thresholds
    
    # Check thresholds are descending
    high = thresholds['high_stability']['threshold']
    med = thresholds['medium_stability']['threshold']
    low = thresholds['low_stability']['threshold']
    
    assert high >= med >= low, "Thresholds must be descending"
    
    # Check reasonable ranges
    assert 30 <= high <= 55, f"High threshold {high} out of range"
    assert 30 <= med <= 55, f"Med threshold {med} out of range"
    
    print("✅ RSI config valid")

def validate_scanner_config(config_path: Path):
    """Validate scanner config"""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    
    # Check earnings buffer
    earnings = cfg['scanner']['earnings_buffer']
    assert 20 <= earnings['default'] <= 60
    
    # Check support bounce
    bounce = cfg['scanner']['support_bounce']
    assert 2 <= bounce['min_tests']['default'] <= 10
    
    print("✅ Scanner config valid")

if __name__ == "__main__":
    base = Path("config")
    validate_rsi_config(base / "rsi_thresholds.yaml")
    validate_scanner_config(base / "scanner_config.yaml")
    print("\n✅ All configs valid!")
```

### 6.3 Config Documentation

**File:** `docs/CONFIGURATION.md`

```markdown
# OptionPlay Configuration Guide

## RSI Thresholds (`config/rsi_thresholds.yaml`)

Adaptive RSI thresholds based on stock stability score.

### How to modify:

1. Edit `config/rsi_thresholds.yaml`
2. Run `python scripts/validate_config.py`
3. Restart MCP server
4. Monitor Daily Picks for 2-3 days

### Example: Tighten thresholds for High Stability

```yaml
high_stability:
  min_stability: 85
  threshold: 44  # Changed from 42
```

### Example: Loosen thresholds for Low Stability

```yaml
low_stability:
  min_stability: 60
  threshold: 36  # Changed from 38
```

## Scanner Config (`config/scanner_config.yaml`)

### Earnings Buffer

Modes:
- `conservative`: 45 days (very safe)
- `standard`: 30 days (recommended)
- `aggressive`: 20 days (higher risk)

Change current mode:
```yaml
earnings_buffer:
  current_mode: "standard"  # or "conservative" or "aggressive"
```

### Support Bounce

Minimum support tests required:
```yaml
support_bounce:
  min_tests:
    default: 3  # Recommended
```

Increase for more conservative bounces:
```yaml
min_tests:
  default: 5
```
```

---

## 7. Rollback Plan

### If Win Rate < 75% after 20 trades:

```bash
# 1. Revert to conservative settings
cd ~/OptionPlay/config/

# 2. Backup current config
cp rsi_thresholds.yaml rsi_thresholds.yaml.backup
cp scanner_config.yaml scanner_config.yaml.backup

# 3. Restore previous version
git checkout HEAD~1 config/rsi_thresholds.yaml
git checkout HEAD~1 config/scanner_config.yaml

# 4. Restart server
pkill -f "optionplay"
python -m optionplay.server &

# 5. Verify rollback
python scripts/daily_picks.py
# Should see 5 picks again
```

### Alternative: Gradual Rollback

```yaml
# In rsi_thresholds.yaml - meet halfway
thresholds:
  high_stability:
    threshold: 45  # Between 42 and 50
  medium_stability:
    threshold: 43  # Between 40 and 50
```

---

## 8. Success Metrics

### KPIs to Monitor

**Quantitative (Track Daily):**
```bash
# Create monitoring script
cat > scripts/track_metrics.py << 'EOF'
#!/usr/bin/env python3
import json
from datetime import date

def log_metrics():
    # Run daily picks
    picks = get_daily_picks()
    
    metrics = {
        "date": str(date.today()),
        "num_picks": len(picks),
        "avg_score": sum(p['score'] for p in picks) / len(picks),
        "top_score": max(p['score'] for p in picks),
        "strategies": list(set(p['strategy'] for p in picks)),
        "stability_avg": sum(p['stability'] for p in picks) / len(picks)
    }
    
    with open("metrics.jsonl", "a") as f:
        f.write(json.dumps(metrics) + "\n")
    
    print(f"Date: {metrics['date']}")
    print(f"Picks: {metrics['num_picks']}")
    print(f"Avg Score: {metrics['avg_score']:.1f}")
    print(f"Top Score: {metrics['top_score']:.1f}")

if __name__ == "__main__":
    log_metrics()
EOF

# Run daily
python scripts/track_metrics.py
```

**Targets:**
- Daily Picks: 10-20 (from 5)
- Avg Enhanced Score: 4.5-7.0
- Strategy Mix: ≥3 strategies represented
- Stability Avg: ≥70

**Qualitative (After 10-20 Trades):**
- Win Rate: ≥75%
- Avg P&L per Trade: ≥$50
- Max Drawdown: ≤$500

---

## 9. Future Enhancements (Phase 4)

### 9.1 RSI Percentile Approach

```yaml
# Future: config/rsi_percentile.yaml
rsi_percentile:
  enabled: false
  description: "Use historical RSI percentile instead of absolute values"
  
  lookback_days: 252
  
  thresholds:
    oversold_percentile: 20  # Bottom 20% for this stock
    overbought_percentile: 80
```

### 9.2 VIX-Adaptive Thresholds

```yaml
# In regime_config.yaml
regimes:
  high:
    vix_range: [25, 100]
    rsi_threshold_adjustment: -2  # Loosen by 2 points
    support_min_tests_adjustment: -1  # Require 1 less test
```

### 9.3 Machine Learning Integration

```yaml
# Future: config/ml_config.yaml
ml_scoring:
  enabled: false
  model_path: "models/rsi_threshold_predictor.pkl"
  features:
    - stability
    - sector
    - market_cap
    - 52w_volatility
```

---

## 10. Summary

### Changes to Implement:

**✅ Config Files (NO CODE HARDCODING):**
1. Create `config/rsi_thresholds.yaml` (Adaptive RSI 42/40/38)
2. Update `config/scanner_config.yaml` (Earnings 30d, Support 3 tests)
3. Optional: `config/regime_config.yaml` (VIX overrides)

**✅ Code Changes:**
1. Create `utils/config_loader.py` (Centralized config)
2. Update `strategies/*.py` (Use config, remove hardcoding)
3. Update `filters/earnings_filter.py` (Use config)
4. Create `scripts/validate_config.py` (Validation)

**✅ Testing:**
1. Unit tests for config loader
2. Daily Picks validation (expect 11-15 picks)
3. Monitor first 10-20 trades

**✅ Documentation:**
1. `docs/CONFIGURATION.md` (How to adjust configs)
2. Config comments (YAML documentation)
3. Rollback procedures

### Expected Outcomes:

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Daily Picks | 5 | 11-15 | +120-200% |
| Scan Coverage | 291 symbols | 340+ symbols | +17% |
| Win Rate | 81.1% | 80%+ | Maintained |
| Avg Enhanced Score | 7.0-10.5 | 4.5-10.5 | Wider range |

---

## 11. Implementation Checklist

```bash
# Phase 1: Config Setup
[ ] Create config/rsi_thresholds.yaml
[ ] Update config/scanner_config.yaml
[ ] Run python scripts/validate_config.py

# Phase 2: Code Updates
[ ] Create utils/config_loader.py
[ ] Update strategies/pullback.py
[ ] Update strategies/bounce.py
[ ] Update strategies/trend_continuation.py
[ ] Update filters/earnings_filter.py
[ ] Create tests/test_config_loader.py
[ ] Run pytest

# Phase 3: Deployment
[ ] Commit changes to git
[ ] Restart MCP server
[ ] Verify config loading in logs
[ ] Run Daily Picks (expect 11-15)

# Phase 4: Validation
[ ] Monitor for 2-3 days
[ ] Track metrics (picks, scores, strategies)
[ ] Execute 10-20 trades
[ ] Evaluate Win Rate

# Phase 5: Documentation
[ ] Update docs/CONFIGURATION.md
[ ] Document rollback procedure
[ ] Create config change log
```

---

**Prepared by:** Claude + Lars Christiansen  
**Based on:** 35-symbol validation study  
**Confidence Level:** VERY HIGH  
**Implementation Time:** 2-3 hours  
**Validation Period:** 2-3 days  

**Ready for Implementation:** ✅
