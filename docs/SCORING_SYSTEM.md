# OptionPlay — Complete Scoring System Reference

**Stand:** 2026-02-21 | **Version:** 4.1.0

Vollständige Dokumentation aller Scoring-Komponenten, Normalisierung, Schwellen und
Cross-Strategy-Ranking. Zielgruppe: Analyse und Kalibrierung der 5 Strategien.

---

## Inhaltsverzeichnis

1. [Übersicht: Alle Strategien im Vergleich](#1-übersicht-alle-strategien-im-vergleich)
2. [Pullback Analyzer](#2-pullback-analyzer)
3. [Support Bounce Analyzer](#3-support-bounce-analyzer)
4. [ATH Breakout Analyzer](#4-ath-breakout-analyzer)
5. [Earnings Dip Analyzer](#5-earnings-dip-analyzer)
6. [Trend Continuation Analyzer](#6-trend-continuation-analyzer)
7. [Score-Normalisierung (0-10 Skala)](#7-score-normalisierung)
8. [Cross-Strategy Ranking](#8-cross-strategy-ranking)
9. [Scanner: Overlap & Filterung](#9-scanner-overlap--filterung)
10. [Enhanced Scoring (Daily Picks)](#10-enhanced-scoring-daily-picks)
11. [Strategie-Interaktion & Balance](#11-strategie-interaktion--balance)
12. [Balancierungs-Aufgaben](#12-balancierungs-aufgaben)

---

## 1. Übersicht: Alle Strategien im Vergleich

### Signal-Schwellen (normalisierte 0-10 Skala)

| Strategie | max_possible | Min Score | Weak | Moderate | Strong | WF Threshold | OOS WR |
|-----------|-------------|-----------|------|----------|--------|-------------|--------|
| **Pullback** | 14.0 (P95) | 3.5 | 3.0 | 5.0 | 7.0 | 4.5 | 88.3% |
| **Bounce** | 10.0 | 3.5 | 3.5 | 5.0 | 7.0 | 6.0 | 91.6% |
| **ATH Breakout** | 10.0 | 4.0 | 4.0 | 5.5 | 7.0 | 6.0 | 88.9% |
| **Earnings Dip** | 9.5 | 3.5 | 3.5 | 5.0 | 6.5 | 5.0 | 86.7% |
| **Trend Cont.** | 10.5 | 3.5 | 3.5 | 5.0 | 7.5 | 5.5 | 87.7% |

**Hinweis:** Pullback max_possible ist 14.0 (95. Perzentil der historischen Score-Verteilung), nicht die theoretische Summe aller Komponenten (~27). Dies verhindert Score-Kompression und macht Pullback-Scores vergleichbar mit anderen Strategien.

### Scoring-Komponenten pro Strategie

| Strategie | Komponenten | Max Positiv | Max Negativ | Netto Range |
|-----------|-------------|-------------|-------------|-------------|
| **Pullback** | 14 | ~27.0 | ~-2.0 | -2.0 bis 27.0 |
| **Bounce** | 5 | 10.0 | -3.0 | -3.0 bis 10.0 |
| **ATH Breakout** | 4 + 5 Enhancements | ~10.0 | -2.75 | -2.75 bis 10.0 |
| **Earnings Dip** | 5 + Penalties | 9.5 | -3.0 | -3.0 bis 9.5 |
| **Trend Cont.** | 5 | 10.5 | -1.0 | -1.0 bis 10.5 |

*Für Normalisierung wird `max_possible` verwendet, nicht die theoretische Max-Summe. Siehe [Sektion 7](#7-score-normalisierung).*

### Disqualifikations-Kriterien (Sofort NEUTRAL)

| Kriterium | PB | BO | ATH | ED | TC |
|-----------|----|----|-----|----|----|
| SMA-Alignment gebrochen | - | - | - | - | **Ja** |
| Kein Support | - | **Ja** | - | - | - |
| Kein ATH-Breakout | - | - | **Ja** | - | - |
| Kein Earnings-Dip | - | - | - | **Ja** | - |
| RSI Overbought | >70 | >70 | >80 | - | >80 (ADX<25) |
| ADX zu niedrig | - | - | - | - | <20 |
| Buffer zu klein | - | - | - | - | <3% |
| Volumen zu gering | - | DCB | <1.0x | - | **Ja** |
| Stability zu niedrig | - | - | - | <60 | <70 |
| Earnings zu nah | - | - | - | - | <14d |
| VIX HIGH | **disabled** | **disabled** | **disabled** | **disabled** | **disabled** |
| Unter SMA200 | **Ja** | extrem | - | penalty | - |

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

Zentrale VIX-Multiplikatoren aus `scoring_weights.yaml` (angewendet im Scanner):
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

## 4. ATH Breakout Analyzer

**Datei:** `src/analyzers/ath_breakout.py`
**Trigger:** Event-basiert (Preis bricht über ATH aus)

### 4.1 Scoring-Komponenten (4 Basis + 5 Enhancements)

| # | Komponente | Range | Scoring-Logik |
|---|-----------|-------|---------------|
| 1 | **Consolidation Quality** | 0–3.0 | Tight range (<8%, >30d): 2.5, moderate (<12%): 1.5-2.0, wide (<15%): 1.0. ATH-Test Bonus +0.5 |
| 2 | **Breakout Strength** | 0–2.5 | Schwach (1%): 1.0, moderat (3%): 1.5, stark (5%): 2.0. Confirmation >2d: +0.5 |
| 3 | **Volume** | -1.0–2.5 | Exceptional (2.5x): 2.5, strong (2x): 2.0, good (1.5x): 1.5, adequate (1x): 0.5, weak (<1x): -1.0 |
| 4 | **Momentum/Trend** | -1.5–2.0 | SMA-Alignment: +0.5, MACD bullish: +0.5, RSI 50-70: +0.5. RSI >75: -0.5, SMA200 declining: -0.5 |

### 4.2 Enhancements (A1–A5)

| Enhancement | Range | Beschreibung |
|-------------|-------|-------------|
| **A1: VCP Contraction** | -0.25–+0.5 | Kontrahierendes Volumen in Konsolidierung: +0.5 |
| **A2: Consol Volume** | -0.25–+0.5 | Volume Dryup (Absorption): +0.5, Distribution: -0.25 |
| **A3: RS vs SPY** | -0.5–+0.5 | Relative Stärke 60d: Outperformance >20%: +0.5, <-10%: -0.5 |
| **A4: Candle Quality** | varies | Marubozu: +0.5, Wide Range: +0.25, Long Wick: -0.5 |
| **A5: Gap Analysis** | 0–+0.5 | Power Gap (>3%): +0.5, Standard Gap (>1%): +0.25 |

### 4.3 YAML-Weights (Default)

```yaml
ath_breakout:
  weights:
    ath: 1.03      volume: 2.0     trend: 1.06     rsi: 0.92
    rs: 2.0        momentum: 1.97  macd: 2.02      keltner: 2.0
    vwap: 3.06     market_context: 1.9   sector: 1.0   gap: 1.0
  max_possible: 23.0
```

### 4.4 Disqualifikation

- Kein ATH erreicht
- Konsolidierung < 20 Tage oder Range > 15%
- Close nicht über ATH
- Volume < 1.0x auf Breakout-Tag
- RSI >= 80 (überhitzt)

### 4.5 VIX-Regime

- `elevated`: min_stability 90
- `danger`: min_stability 85, Volume↑, Trend↑
- `high`: **deaktiviert** (enabled: false)

---

## 5. Earnings Dip Analyzer

**Datei:** `src/analyzers/earnings_dip.py`
**Trigger:** Event-basiert (Earnings-bedingter Kursrückgang 5-25%)

### 5.1 Scoring-Komponenten (5 + Penalties)

| # | Komponente | Range | Scoring-Logik |
|---|-----------|-------|---------------|
| 1 | **Drop Magnitude** | 0–2.0 | Minor (5-7%): 0.5, moderate (7-10%): 1.0, ideal (10-15%): 1.5-2.0, extreme (>20%): 1.0 |
| 2 | **Stabilization** | 0–2.5 | Multi-green candles: 1.5, single green: 1.0, higher low: 1.0, volume decline: 0.5, hammer: 0.5 |
| 3 | **Fundamental Strength** | 0–2.0 | Stability >=90: 1.5, >=80: 1.0, >=70: 0.5. Above SMA200: +0.5 |
| 4 | **Overreaction** | 0–2.0 | RSI extreme oversold (<30): 0.5/component, panic volume (3x): 0.5, historical move excess: 0.5 |
| 5 | **BPS Suitability** | 0–1.0 | Earnings-spezifisch: +0.5 Basis |
| 6 | **Penalties** | -3.0–0 | Under SMA200: -1.0, continued decline: -1.5, new lows: -penalty, RSI not extreme: -0.5 |

### 5.2 Enhancements (B1–B7)

| Enhancement | Beschreibung |
|-------------|-------------|
| **B1: Z-Score Relative Scoring** | Drop relativ zu historischen Earnings-Moves. Z>=2.0 ideal: 2.0 pts |
| **B2: Sector Context** | Defensive Sektoren (factor>1.05): +0.5, volatile (<0.95): 0. Beat rate >=75%: +0.25 |
| **B3: Dynamic Timing** | Stabilisierung: 2d für Dips <15%, 3d für Dips >=15% |
| **B4: Graduated Decline** | Mild (<2%): -0.5, moderate (<5%): -1.0, severe: -1.5 |
| **B5: Contextual RSI** | RSI <=55 im Uptrend: keine Penalty |
| **B7: Dynamic Recovery** | Strong Signal: 60% recovery, default: 50%, weak: 40% |

### 5.3 YAML-Weights (Default)

```yaml
earnings_dip:
  weights:
    dip: 3.0       gap: 2.0       rsi: 2.0       stabilization: 2.0
    volume: 2.0    trend: 2.0     macd: 2.0      stoch: 2.0
    keltner: 2.0   vwap: 3.0      market_context: 2.0   sector: 1.0
  max_possible: 21.0
```

### 5.4 Disqualifikation

- Drop < 5% (kein echter Dip) oder > 25% (zu riskant)
- Stability Score < 60
- Ungenügende Stabilisierung
- Preis unter SMA200 (Penalty, nicht DQ)

### 5.5 VIX-Regime

- `elevated`: min_stability 75
- `danger`: min_stability 70
- `high`: min_stability 80
- Stability-Threshold per Sector: Technology 65, Healthcare 70, Industrials 70

---

## 6. Trend Continuation Analyzer

**Datei:** `src/analyzers/trend_continuation.py`
**Trigger:** State-basiert (kein Event nötig — stabiler Aufwärtstrend)

### 6.1 Scoring-Komponenten (5)

| # | Komponente | Range | Scoring-Logik |
|---|-----------|-------|---------------|
| 1 | **SMA Alignment** | 0–2.5 | All rising: 2.0, partial (50+200): 1.5, basic: 1.0. Spread >5%: +0.5, <3%: -0.5 |
| 2 | **Trend Stability** | 0–2.5 | 0 closes below SMA50/60d: 2.0, 1-2: 1.5, 3-5: 0.5. Golden Cross >=120d: +0.5 |
| 3 | **Trend Buffer** | 0–2.0 | >10%: 2.0, 8-10%: 1.5, 5-8%: 1.0, 3-5%: 0.5 |
| 4 | **Momentum Health** | -1.0–2.0 | RSI 50-75: +0.5, ADX >30: +1.0, >20: +0.5, MACD bullish: +0.5. RSI >75: -0.5, MACD divergence: -1.0, Volume div: -0.5 |
| 5 | **Volatility** | 0–1.5 | ATR% <1.0: 1.5, 1.0-1.5: 1.0, 1.5-2.0: 0.5, >2.0: 0.0 |

### 6.2 YAML-Weights (Default / Low / Normal Regime)

```yaml
# Default:
sma_alignment: 2.00   trend_stability: 2.00   trend_buffer: 1.60
momentum_health: 1.60  volatility: 1.50        # Sum = 8.70

# Low VIX:
sma_alignment: 1.60   trend_stability: 1.80   trend_buffer: 1.60
momentum_health: 1.60  volatility: 1.50        # Sum = 8.10

# Normal VIX:
sma_alignment: 1.60   trend_stability: 2.00   trend_buffer: 1.60
momentum_health: 1.60  volatility: 1.50        # Sum = 8.30
```

### 6.3 Disqualifikation

- SMA-Alignment gebrochen (Close <= SMA20 oder SMA20 <= SMA50 oder SMA50 <= SMA200)
- >5 Closes unter SMA50 in 60 Tagen
- Buffer < 3% über SMA50
- ADX < 20 (kein Trend)
- RSI > 80 **und** ADX < 25 (overbought ohne starken Trend)
- Volume zu gering
- Stability Score < 70
- Earnings innerhalb 14 Tagen

### 6.4 VIX-Regime (zentralisiert in scoring_weights.yaml)

VIX-Multiplikatoren sind seit v4.1.0 für **alle 5 Strategien** zentral in `config/scoring_weights.yaml` konfiguriert. Der Scanner wendet sie nach dem Scoring an. Die Analyzer selbst enthalten keine VIX-Logik mehr.

| Regime | PB | BO | ATH | ED | TC |
|--------|------|------|------|------|------|
| Low | 1.0× | 1.0× | 1.0× | 1.0× | 1.05× |
| Normal | 1.0× | 1.0× | 1.0× | 1.0× | 1.0× |
| Danger | 0.95× | 0.95× | 0.85× | 1.0× | 0.75× |
| Elevated | 0.90× | 0.90× | 0.80× | 0.95× | 0.70× |
| High | disabled | disabled | disabled | disabled | disabled |

Rationale:
- **ATH/TC**: Stärkste Penalty (Breakouts und Trends brechen bei hoher Volatilität zuerst)
- **Earnings Dip**: Minimale Penalty (erhöhte IV hilft Credit Spreads)
- **High**: Alle disabled (Recommendation Engine blockiert ohnehin bei VIX ≥ 30)

### 6.5 Market Context Multiplikator

| SPY Trend | Multiplikator |
|-----------|--------------|
| Strong Uptrend | 1.05x |
| Uptrend | 1.00x |
| Sideways | 1.00x |
| Downtrend | 0.90x |
| Strong Downtrend | 0.80x |

### 6.6 Candlestick-Warnungen

- **Shooting Star**: Upper shadow > 60% der Range, Close im unteren 30% → Warnung
- **Bearish Engulfing**: Aktuelle Range > 120% der vorherigen, Close unter Vortags-Low → Warnung

---

## 7. Score-Normalisierung

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
| ATH Breakout | 10.0 | ÷ 1.00 | 7.0 |
| Earnings Dip | 9.5 | ÷ 0.95 | 7.4 |
| Trend Cont. | 10.5 | ÷ 1.05 | 6.7 |

**Pullback P95-Normalisierung (Schritt 4):** Pullback hat 14 Komponenten mit theoretischem Maximum ~27. Historische Analyse zeigt: 95% aller Trades scoren unter 14.0 Raw. Daher wird `max_possible = 14.0` (P95) verwendet statt der theoretischen Summe. Dies verhindert die starke Score-Kompression (vorher: Raw 7.0 → 2.6; jetzt: Raw 7.0 → 5.0).

### Dynamic effective_max

Trend Continuation verwendet einen dynamischen `effective_max` basierend auf den Summen der YAML-Weights (statt dem statischen 10.5). Dies ermöglicht Regime-abhängige Normalisierung.

---

## 8. Cross-Strategy Ranking

**Datei:** `src/services/recommendation_engine.py`
**Config:** `config/scoring_weights.yaml` → Sektion `ranking:`

### 8.1 Ranking-Formel

```
base_score = 0.85 × signal_score + 0.15 × (stability_score / 10)

speed_multiplier = (0.5 + speed_score / 10) ^ 0.3

event_bonus = signal_type_bonus[strategy]   # 0.5 für Event-Strategien, 0.0 für TC

combined_score = base_score × speed_multiplier + event_bonus
```

**Schritt 5 (Stability 30% → 15%):** Stability-Gewicht von 30% auf 15% reduziert, um Stability-Double-Counting zu verringern (Stability fließt bereits in Analyzer-DQ + Post-Filter ein).

**Config:** `ranking.stability_weight: 0.15` in `config/scoring_weights.yaml`

### 8.2 Speed-Score (0–10)

| Komponente | Gewicht | Logik |
|-----------|---------|-------|
| DTE-Nähe zu 60d | 3.0 | Näher an 60 DTE = schnellere Resolution |
| Stability | 2.5 | Höhere Stability = schnellere Mean Reversion |
| Sector Speed | 1.5 | Sektor-spezifisch (Tech=0.1 schnell, Utilities=1.0 langsam) |
| Pullback Score | 1.5 | Tieferer Pullback = schnellere Recovery |
| Market Context | 1.5 | Bullish = schnellere Resolution |

### 8.3 Speed-Multiplikator-Auswirkung

| Speed Score | Multiplikator |
|-------------|--------------|
| 0 (langsam) | 0.81x |
| 5 (mittel) | 1.00x |
| 10 (schnell) | 1.13x |

### 8.4 Minimum

- `min_signal_score: 3.5` (aus scoring_weights.yaml)

---

## 9. Scanner: Overlap & Filterung

**Datei:** `src/scanner/multi_strategy_scanner.py`

### 9.1 Scan-Modi

| Modus | Verhalten | Overlap |
|-------|----------|---------|
| BEST_SIGNAL | Alle 5 Strategien, nur bestes Signal pro Symbol | `_keep_best_per_symbol()` |
| ALL | Alle Strategien, max 2 Signale pro Symbol | `max_symbol_appearances: 2` |
| Einzeln | Eine Strategie | Kein Overlap |

### 9.2 Stability-First Post-Filter (nach Scan)

Vereinfachtes 2-Tier-System (seit v4.1.0):

| Tier | Stability Score | Min Signal Score |
|------|----------------|-----------------|
| Qualified | >= 60 | 3.5 |
| Blacklist | < 60 | **Komplett gefiltert** |

*Vorher: 5 Tiers (Premium/Good/Acceptable/OK/Blacklist). Vereinfacht, weil Signal-Qualität und WF-Thresholds bereits effektiv filtern.*

### 9.3 Fundamentals Pre-Filter (vor Scan)

- `min_stability >= 50`
- `min_win_rate >= 65`

### 9.4 Pipeline-Reihenfolge

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

## 10. Enhanced Scoring (Daily Picks)

**Datei:** `src/services/enhanced_scoring.py`
**Config:** `config/enhanced_scoring.yaml`

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

**Config:** `mode: multiplicative` in `config/enhanced_scoring.yaml`. Fallback `mode: additive` für Legacy-Verhalten.

### 10.3 Overfetch

- Faktor: 5x (5× so viele Picks anfordern, filtern, re-ranken)

---

## 11. Strategie-Interaktion & Balance

### 11.1 Event-Priority-System (Schritt 3)

**Problem:** Trend Continuation (State-basiert) generiert in ruhigen Märkten für viele Symbole Signale und kann Event-basierte Strategien verdrängen.

**Lösung:** Drei Mechanismen in `config/scoring_weights.yaml` → `ranking.strategy_balance`:

```yaml
strategy_balance:
  signal_type_bonus:        # Event-Bonus im Ranking
    pullback: 0.5
    bounce: 0.5
    ath_breakout: 0.5
    earnings_dip: 0.5
    trend_continuation: 0.0  # Kein Bonus (State-basiert)

  strategy_caps:            # Max Signale pro Strategie in daily_picks
    trend_continuation: 3
    default: 5

  min_strategies_in_picks: 2  # Mindestens 2 verschiedene Strategien in Top-N
```

### 11.2 Wie Strategien konkurrieren

Im `BEST_SIGNAL`-Modus (daily_picks) gewinnt pro Symbol nur das höchste Signal. Die Strategien konkurrieren über ihren **normalisierten Score auf der 0-10 Skala** + Event-Bonus.

```
Beispiel: AAPL hat gleichzeitig:
  Pullback:  Raw 9.0 / 14.0 → Normalized 6.4 (MODERATE) + 0.5 Event-Bonus
  Trend:     Raw  8.0 / 10.5 → Normalized 7.6 (STRONG) + 0.0 Event-Bonus
  → Ranking: Pullback 6.9 × speed vs. Trend 7.6 × speed
```

### 11.3 Gelöste Balance-Probleme (v4.1.0)

| Problem | Lösung | Schritt |
|---------|--------|---------|
| **Pullback-Kompression** | max_possible 27.0 → 14.0 (P95). Raw 14 normalisiert jetzt auf 10.0 statt 5.2. | Schritt 4 |
| **Trend Cont. VIX-Killer** | VIX-Multiplikatoren zentralisiert. HIGH = disabled für alle Strategien. | Schritt 7 |
| **Event vs. State** | Event-Bonus +0.5, TC Cap 3, min_strategies_in_picks 2. | Schritt 3 |
| **Stability Double-Count** | Ranking-Weight 30% → 15%. Post-Filter auf 2 Tiers vereinfacht. | Schritt 5 |
| **Enhanced Scoring Bias** | Additiv → multiplikativ (max ×1.28). Starkes Signal > schwaches mit Bonus. | Schritt 6 |

### 11.4 Verbleibende Balance-Hinweise

| Hinweis | Beschreibung |
|---------|-------------|
| **Bounce/ATH 1:1 Mapping** | Raw Max = 10.0, Normalisierung quasi identisch (÷1.0). |
| **ML-Weight-Asymmetrie** | Trend Cont. hat manuell kalibrierte Weights (kein Walk-Forward-Training). |

### 11.5 Score-Verteilungen (theoretisch)

| Strategie | Typischer Score-Range | "Guter" Score | "Exzellenter" Score |
|-----------|----------------------|---------------|-------------------|
| Pullback | 4.0–7.0 | 5.5–7.0 | >7.5 |
| Bounce | 4.0–7.0 | 5.5–6.5 | >7.5 |
| ATH Breakout | 4.5–7.5 | 6.0–7.0 | >8.0 |
| Earnings Dip | 3.5–7.0 | 5.0–6.5 | >7.5 |
| Trend Cont. | 3.5–8.0 | 5.5–7.0 | >8.0 |

---

## 12. Balancierungs-Aufgaben (Status)

### ✅ Task 1: Pullback Score-Range analysieren → **Erledigt (Schritt 2+4)**

`max_possible` von 27.0 auf 14.0 (P95) gesetzt. Pullback produziert jetzt vergleichbare normalisierte Scores.

### ✅ Task 2: Cross-Strategy Score-Distribution vergleichen → **Erledigt (Schritt 2)**

Empirische Score-Verteilungen analysiert. Alle Strategien jetzt im ähnlichen Bereich (4.0–8.0 normalized).

### ✅ Task 3: Event vs. State balancieren → **Erledigt (Schritt 3)**

Event-Priority-System: +0.5 Bonus für Event-Strategien, TC Cap 3, min_strategies_in_picks 2. Siehe [Sektion 11.1](#111-event-priority-system-schritt-3).

### ⬜ Task 4: Walk-Forward Training für Trend Continuation

**Offen.** TC hat manuell kalibrierte Weights. Walk-Forward-Training steht noch aus.

### ✅ Task 5: Stability Double-Counting → **Erledigt (Schritt 5)**

Ranking Stability-Weight 30% → 15%. Post-Filter auf 2 Tiers vereinfacht.

### ✅ Task 6: Enhanced Scoring Bias → **Erledigt (Schritt 6)**

Multiplikativer Ansatz: max ×1.28 statt +5.5. Signal-Qualität dominiert.

### ✅ Task 7: VIX-Regime harmonisieren → **Erledigt (Schritt 7)**

Zentrale `vix_score_multiplier` per Strategy×Regime in `scoring_weights.yaml`. Scanner wendet an. Analyzer VIX-frei.

### ⬜ Task 8: Dynamic Max Verzerrung quantifizieren

**Niedrige Priorität.** TC effective_max variiert leicht zwischen Regimen (8.1–8.7). Impact gering durch P95-basierte Normalisierung bei Pullback.
