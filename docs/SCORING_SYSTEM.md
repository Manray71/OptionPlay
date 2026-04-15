# OptionPlay — Complete Scoring System Reference

**Stand:** 2026-04-07 | **Version:** 5.0.0

Vollständige Dokumentation aller Scoring-Komponenten, Normalisierung, Schwellen und
Cross-Strategy-Ranking. Zielgruppe: Analyse und Kalibrierung der 2 aktiven Strategien (Pullback + Bounce).

*v5.0.0: ATH Breakout, Earnings Dip und Trend Continuation wurden entfernt.*

---

## Inhaltsverzeichnis

1. [Übersicht: Beide Strategien im Vergleich](#1-übersicht-beide-strategien-im-vergleich)
2. [Pullback Analyzer](#2-pullback-analyzer)
3. [Support Bounce Analyzer](#3-support-bounce-analyzer)
4. [Score-Normalisierung (0-10 Skala)](#4-score-normalisierung)
5. [Cross-Strategy Ranking](#5-cross-strategy-ranking)
6. [Scanner: Overlap & Filterung](#6-scanner-overlap--filterung)
7. [Enhanced Scoring (Daily Picks)](#7-enhanced-scoring-daily-picks)

---

## 1. Übersicht: Beide Strategien im Vergleich

### Signal-Schwellen (normalisierte 0-10 Skala)

| Strategie | max_possible | Min Score | Weak | Moderate | Strong | WF Threshold | OOS WR |
|-----------|-------------|-----------|------|----------|--------|-------------|--------|
| **Pullback** | 14.0 (P95) | 3.5 | 3.0 | 5.0 | 7.0 | 4.5 | 88.3% |
| **Bounce** | 10.0 | 3.5 | 3.5 | 5.0 | 7.0 | 6.0 | 91.6% |

**Hinweis:** Pullback max_possible ist 14.0 (95. Perzentil der historischen Score-Verteilung), nicht die theoretische Summe aller Komponenten (~27). Dies verhindert Score-Kompression und macht Pullback-Scores vergleichbar mit Bounce.

### Scoring-Komponenten pro Strategie

| Strategie | Komponenten | Max Positiv | Max Negativ | Netto Range |
|-----------|-------------|-------------|-------------|-------------|
| **Pullback** | 14 | ~27.0 | ~-2.0 | -2.0 bis 27.0 |
| **Bounce** | 5 | 10.0 | -3.0 | -3.0 bis 10.0 |

*Für Normalisierung wird `max_possible` verwendet, nicht die theoretische Max-Summe. Siehe [Sektion 4](#4-score-normalisierung).*

### Disqualifikations-Kriterien (Sofort NEUTRAL)

| Kriterium | PB | BO |
|-----------|----|----|
| Kein Support | - | **Ja** |
| RSI Overbought | >70 | >70 |
| Volumen zu gering | - | DCB |
| VIX HIGH | **disabled** | **disabled** |
| Unter SMA200 | **Ja** | extrem |

---

## 2. Pullback Analyzer

**Dateien:** `src/analyzers/pullback.py`, `src/analyzers/pullback_scoring.py`
**Trigger:** Event-basiert (RSI-Dip in Aufwärtstrend)

### 2.1 Scoring-Komponenten (14)

| # | Komponente | Range | Scoring-Logik |
|---|-----------|-------|---------------|
| 1 | **RSI** | 0–3.0 | Adaptiver Neutral-Threshold (Stability 85+=50, 70+=45, 60+=40, <60=35). Deep oversold (<30): 3.0, oversold: 2.0, near: 1.0. RSI-Hook Bonus +0.5 |
| 2 | **RSI Divergenz** | 0–3.0 | Price lower low + RSI higher low = bullish divergence. Strong: 3.0, moderate: 2.0, weak: 1.0 |
| 3 | **Support** | 0–2.5 | Nähe zu Support-Zone: within 2%: 2.5, within 5%: 1.5, within 10%: 0.5 |
| 4 | **Fibonacci** | 0–2.0 | Retracement-Level: 61.8%: 2.0, 50%: 1.5, 38.2%: 1.0 |
| 5 | **Moving Average** | 0–2.0 | Dip-in-Uptrend: above SMA20 pulled back: 2.0, above SMA50: 1.5, above SMA200: 1.0 |
| 6 | **Trend Strength** | 0–2.0 | SMA20>50>200 all rising: 2.0, partial: 1.0 |
| 7 | **Volume** | 0–1.0 | Declining volume during pullback (healthy): positive |
| 8 | **MACD** | 0–2.0 | Bullish cross: 2.0, histogram positive: 1.0 |
| 9 | **Stochastic** | 0–2.0 | Oversold + bullish cross: 2.0, oversold only: 1.0 |
| 10 | **Keltner** | 0–2.0 | Price at lower Keltner band: 2.0, near: 1.0 |
| 11 | **VWAP** | 0–3.0 | Strong above VWAP: 3.0, above: 2.0, near: 1.0 |
| 12 | **Market Context** | -1.0–+2.0 | SPY SMA20/50: strong uptrend +2.0, downtrend -0.5, strong downtrend -1.0 |
| 13 | **Sector** | -1.0–+1.0 | Sektor-Momentum vs. SPY |
| 14 | **Candlestick** | 0–2.0 | Reversal-Pattern (Hammer, Engulfing): bis 2.0 |

### 2.2 YAML-Weights (Default)

```yaml
pullback:
  weights:
    rsi: 3.7            rsi_divergence: 3.6    support: 3.0
    fibonacci: 2.5       ma: 1.06               trend_strength: 2.05
    volume: 1.0          macd: 2.4              stoch: 1.2
    keltner: 2.0         vwap: 1.5              market_context: 1.7
    sector: 1.0          candlestick: 2.0
  max_possible: 27.65
```

### 2.3 Disqualifikation

- RSI > Overbought-Schwelle (~70)
- Preis unter SMA200
- Kein Dip (RSI > 50, kein Pullback zu SMA20)

### 2.4 VIX-Regime

Zentrale VIX-Multiplikatoren aus `scoring.yaml` (angewendet im Scanner):
- `danger`: 0.95× Score-Multiplikator
- `elevated`: 0.90× Score-Multiplikator
- `high`: **disabled** (enabled: false)

Zusätzlich ML-Layer Regime-Adjustments: `elevated` min_stability 85, `danger`/`high` min_stability 80.

---

## 3. Support Bounce Analyzer

**Datei:** `src/analyzers/bounce.py`
**Trigger:** Event-basiert (Preis an Support-Zone)

### 3.1 Scoring-Komponenten (5)

| # | Komponente | Range | Scoring-Logik |
|---|-----------|-------|---------------|
| 1 | **Support Quality** | 0–2.5 | Touches: 5+: 2.0, 4: 1.5, 3: 1.0. SMA200-Confluence Bonus +0.5 |
| 2 | **Proximity** | 0–2.0 | Am Support (±1%): 2.0, nah (1-2%): 1.5, nähernd (2-3%): 1.0, fern (3-5%): 0.5, darunter: 1.0 |
| 3 | **Bounce Confirmation** | 0–2.5 | Reversal-Candle: 1.0, Close up: 0.5, Green sequence: 1.0, RSI turn: 0.5, MACD cross: 0.5. Max 2.5 |
| 4 | **Volume** | -1.0–1.5 | Strong (2x): 1.5, moderate (1.5x): 1.0, adequate (1x): 0.5. DCB penalty: -1.0 |
| 5 | **Trend Context** | -2.5–1.5 | Uptrend: 1.5, above SMA200: 1.0, near SMA200: 0.5. Steep down: -2.5, moderate: -1.5, mild: -1.0 |

### 3.2 Enhancements (B1–B6)

| Enhancement | Wirkung |
|-------------|---------|
| **B1: Fibonacci DCB Filter** | < 38.2% retracement = DCB-Warnung, < 23.6% = Penalty -0.5 |
| **B2: SMA Reclaim** | Reclaim SMA20: +0.5, SMA50: +0.25, under both: -0.25 |
| **B3: RSI Divergence** | Bullish divergence am Support: +0.75 |
| **B4: Downtrend Filter** | >10% unter fallender SMA200 = DQ, severe penalty -2.5 |
| **B5: Market Context** | **Deaktiviert** (bearish: 0.8x, neutral: 0.9x) |
| **B6: Bollinger Confluence** | **Deaktiviert** (near lower band: +0.25) |

### 3.3 YAML-Weights (Default)

```yaml
bounce:
  weights:
    support: 1.05    rsi: 2.7         rsi_divergence: 3.6
    candlestick: 2.0 volume: 2.0      trend: 0.99
    macd: 2.4        stoch: 1.3       keltner: 2.0
    vwap: 2.99       market_context: 1.58  sector: 1.0   gap: 1.0
  max_possible: 28.57
```

### 3.4 Disqualifikation

- < 2 Support-Touches
- Preis nicht in Proximity (-1% bis +7% vom Support)
- Keine Bounce-Bestätigung (0 Reversal-Signale)
- DCB-Filter: Volume < 0.5x am Support
- RSI > 70 nach Bounce (Erschöpfung)
- >10% unter fallender SMA200 (Downtrend-Filter B4)

---

## 4. Score-Normalisierung

**Datei:** `src/analyzers/score_normalization.py`

### Formel

```
normalized = (raw_score / max_possible) * 10.0
normalized = clamp(normalized, 0.0, 10.0)
```

### Normalisierungs-Faktoren (max_possible)

| Strategie | max_possible | Faktor | Beispiel: Raw 7.0 → Normalized |
|-----------|-------------|--------|-------------------------------|
| Pullback | 14.0 (P95) | ÷ 1.40 | 5.0 |
| Bounce | 10.0 | ÷ 1.00 | 7.0 |

**Pullback P95-Normalisierung:** Pullback hat 14 Komponenten mit theoretischem Maximum ~27. Historische Analyse zeigt: 95% aller Trades scoren unter 14.0 Raw. Daher `max_possible = 14.0` (P95). Verhindert starke Score-Kompression (vorher: Raw 7.0 → 2.6; jetzt: Raw 7.0 → 5.0).

### Dynamic effective_max (Bounce)

Bounce verwendet einen dynamischen `effective_max` basierend auf den Summen der YAML-Weights. Dies ermöglicht Regime-abhängige Normalisierung.

---

## 5. Cross-Strategy Ranking

**Datei:** `src/services/recommendation_engine.py`
**Config:** `config/scoring.yaml` → Sektion `ranking:`

### 5.1 Ranking-Formel

```
base_score = 0.85 × signal_score + 0.15 × (stability_score / 10)

speed_multiplier = (0.5 + speed_score / 10) ^ 0.3

event_bonus = signal_type_bonus[strategy]   # 0.5 für Pullback/Bounce

combined_score = base_score × speed_multiplier + event_bonus
```

**Stability-Gewicht:** 15% (Stability-Double-Counting vermieden — fließt bereits in Analyzer-DQ + Post-Filter ein).

**Config:** `ranking.stability_weight: 0.15` in `config/scoring.yaml`

### 5.2 Speed-Score (0–10)

| Komponente | Gewicht | Logik |
|-----------|---------|-------|
| DTE-Nähe zu 60d | 3.0 | Näher an 60 DTE = schnellere Resolution |
| Stability | 2.5 | Höhere Stability = schnellere Mean Reversion |
| Sector Speed | 1.5 | Sektor-spezifisch (Tech=0.1 schnell, Utilities=1.0 langsam) |
| Pullback Score | 1.5 | Tieferer Pullback = schnellere Recovery |
| Market Context | 1.5 | Bullish = schnellere Resolution |

### 5.3 Speed-Multiplikator-Auswirkung

| Speed Score | Multiplikator |
|-------------|--------------|
| 0 (langsam) | 0.81x |
| 5 (mittel) | 1.00x |
| 10 (schnell) | 1.13x |

### 5.4 Minimum

- `min_signal_score: 3.5` (aus `config/scoring.yaml`)

---

## 6. Scanner: Overlap & Filterung

**Datei:** `src/scanner/multi_strategy_scanner.py`

### 6.1 Scan-Modi

| Modus | Verhalten | Overlap |
|-------|----------|---------|
| BEST_SIGNAL | Beide Strategien, nur bestes Signal pro Symbol | `_keep_best_per_symbol()` |
| ALL | Beide Strategien, max 2 Signale pro Symbol | `max_symbol_appearances: 2` |
| Einzeln | Eine Strategie | Kein Overlap |

### 6.2 Stability-First Post-Filter (nach Scan)

Vereinfachtes 2-Tier-System (seit v4.1.0):

| Tier | Stability Score | Min Signal Score |
|------|----------------|-----------------|
| Qualified | >= 60 | 3.5 |
| Blacklist | < 60 | **Komplett gefiltert** |

*Vorher: 5 Tiers (Premium/Good/Acceptable/OK/Blacklist). Vereinfacht, weil Signal-Qualität und WF-Thresholds bereits effektiv filtern.*

### 6.3 Fundamentals Pre-Filter (vor Scan)

- `min_stability >= 50`
- `min_win_rate >= 65`

### 6.4 Pipeline-Reihenfolge

```
1. Fundamentals Pre-Filter (min_stability 50)
2. Earnings-Filter (per Strategy)
3. Scan (alle aktiven Strategien parallel)
4. Overlap-Auflösung (BEST_SIGNAL oder max_appearances)
5. Stability-First Post-Filter (Tiered)
6. Sector Diversification
7. Ranking (Combined Score)
8. Enhanced Scoring (nur daily_picks)
```

---

## 7. Enhanced Scoring (Daily Picks)

**Datei:** `src/services/enhanced_scoring.py`
**Config:** `config/scoring.yaml` (Sektion `enhanced_scoring`)

Gilt **nur** für `daily_picks()`, nicht für reguläre Scans.

### 10.1 Multiplikatoren (max ×1.28)

| Multiplier | Range | Schwellen |
|------------|-------|-----------|
| **Liquidity** | 0–0.10 | OI >=5000: 0.10, >=700: 0.10, >=100: 0.05, <100: **rejected** |
| **Credit** | 0–0.08 | Return >=10%: 0.08, >=7%: 0.05, >=4%: 0.03 |
| **Pullback** | 0–0.05 | Above SMA20+SMA200: 0.05, above SMA200 only: 0.03 |
| **Stability** | 0–0.05 | Stability >=85: 0.05, >=75: 0.03 |

### 10.2 Formel (Multiplicative Mode)

```
factor = 1.0 + liquidity_mult + credit_mult + pullback_mult + stability_mult
enhanced_score = signal_score × factor     # max factor = 1.28
```

**Schritt 6:** Umgestellt von additiv (+5.5 max) auf multiplikativ (×1.28 max). Zentrale Eigenschaft: **Ein starkes Signal ohne Bonuses schlägt immer ein schwaches mit max Bonuses** (8.0×1.0 > 4.0×1.28).

Display: `7.69 (6.3 ×1.22)` statt `11.3 (base 6.3)`

**Config:** `mode: multiplicative` in `config/scoring.yaml`. Fallback `mode: additive` für Legacy-Verhalten.

### 7.3 Overfetch

- Faktor: 5x (5× so viele Picks anfordern, filtern, re-ranken)

---

## Score-Verteilungen (Referenz)

| Strategie | Typischer Score-Range | "Guter" Score | "Exzellenter" Score |
|-----------|----------------------|---------------|-------------------|
| Pullback | 4.0–7.0 | 5.5–7.0 | >7.5 |
| Bounce | 4.0–7.0 | 5.5–6.5 | >7.5 |
