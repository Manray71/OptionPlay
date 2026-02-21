# Trend Continuation Analyzer — Code-Briefing

## Kontext

Literatur-Recherche zu Trend-Continuation / Trend-Following-Strategien (Schwab, Fidelity, StockCharts, QuantInsti, LuxAlgo, CME Group, AvaTrade, IBKR u.a.) wurde durchgeführt und mit der aktuellen Implementierung in `src/analyzers/trend_continuation.py` verglichen. Dieses Briefing fasst die Änderungen zusammen, die auf Basis der Literatur vorgenommen werden sollten.

**Dateien:**
- `src/analyzers/trend_continuation.py` — Hauptlogik
- `config/analyzer_thresholds.yaml` — Sektion `trend_continuation:`

---

## 🔴 KRITISCH: YAML-Weight-Kalibrierung (Prio 1)

### Problem
Die trainierten YAML-Weights reduzieren die effektiven Scores um ~70%. Die Signal-Schwelle von 5.0 ist mit den aktuellen Weights mathematisch fast unerreichbar (bräuchte ~16.7 ungewichtet, Maximum ist 10.5). Die Strategie erzeugt de facto keine Signale.

### Skalierungsfaktoren (aktuell)
| Komponente | Default Max | YAML Weight | Skalierung |
|-----------|------------|-------------|------------|
| sma_alignment | 2.5 | 0.75 | 0.30 |
| trend_stability | 2.5 | 0.60 | 0.24 |
| trend_buffer | 2.0 | 0.60 | 0.30 |
| momentum_health | 2.0 | 0.60 | 0.30 |
| volatility | 1.5 | 1.40 | 0.93 |

### Lösung (Option A — bevorzugt)
Signal-Schwelle (`min_score`) proportional zu den Weights anpassen. Bei einem perfekten Score von ~3.5 (nach Weights) sollte die Schwelle bei **2.0–2.5** liegen, damit "Strong Trends" durchkommen.

### Lösung (Option B)
YAML-Weights nach oben korrigieren, sodass die native Skalierung wieder näher an 1.0 liegt. Z.B.:
| Komponente | Neuer Weight |
|-----------|-------------|
| sma_alignment | 2.00 |
| trend_stability | 2.00 |
| trend_buffer | 1.60 |
| momentum_health | 1.60 |
| volatility | 1.50 |

**Beide `normal` und `low` Regime-Weights betroffen.**

### Lösung (Option C)
Kombination: Weights moderat anheben UND min_score auf 3.5 senken.

---

## ⚠️ WICHTIG: ADX-Schwelle anheben (Prio 2)

### Problem
Aktuelle Disqualifikations-Schwelle: ADX < 15. Die Literatur (Schwab, AvaTrade, QuantInsti) definiert:
- ADX < 20 = kein Trend vorhanden
- ADX 20–25 = schwacher Trend
- ADX > 25 = starker Trend

Mit ADX 15 lässt der Analyzer Aktien durch, die in der Fachliteratur als "trendlos" gelten.

### Änderung in `analyzer_thresholds.yaml`
```yaml
trend_continuation:
  disqualification:
    adx_min: 20  # war: 15
```

### Änderung im Scoring (Komponente 4: Momentum Health)
```
ADX Strong:   ADX > 30   → +1.0  (war: > 35)
ADX Moderate: ADX 20–30  → +0.5  (war: 25–35)
```

**Begründung:** Die Literatur setzt "strong trend" bei ADX > 25. Die Schwelle 35 ist in der Praxis sehr selten erreicht. Anpassung auf 30/20 bringt mehr Signale ohne Qualitätsverlust.

---

## ⚠️ WICHTIG: MACD Signal-Linie korrigieren (Prio 2)

### Problem
Die Signal-Linie wird als **SMA(9)** der letzten MACD-Werte berechnet. Die Standard-Berechnung nach Gerald Appel (und bei TradingView, StockCharts, Fidelity, IBKR) ist **EMA(9)**.

### Änderung in `trend_continuation.py`
Ersetze die SMA(9)-Berechnung der Signal-Linie durch EMA(9):

```python
# ALT (vermutlich):
signal_line = sum(macd_values[-9:]) / 9

# NEU:
def ema(values, period):
    multiplier = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = (v - ema_val) * multiplier + ema_val
    return ema_val

signal_line = ema(macd_values[-9:], 9)
```

**Hinweis:** Die EMA-Berechnung für die Signal-Linie sollte idealerweise über die gesamte MACD-History laufen, nicht nur die letzten 9 Werte. Prüfe die aktuelle Implementierung und korrigiere entsprechend.

---

## ⚠️ RSI-Overbought-Logik anpassen (Prio 3)

### Problem
Die Literatur (Schwab) sagt explizit: Bei starkem ADX (starker Trend) sollte der Trend Vorrang vor RSI-Overbought-Signalen haben. Aktuell:
- RSI > 80 → Disqualifikation (hart)
- RSI > 75 → -0.5 Penalty

In starken Aufwärtstrends kann RSI wochenlang über 70–80 liegen. Die harte Disqualifikation bei 80 schließt potenziell die besten Trends aus.

### Änderung
RSI-Disqualifikation kontextabhängig machen:

```python
# VORHER:
if rsi > 80:
    return disqualified("RSI overbought")

# NACHHER:
if rsi > 80 and adx < 25:
    return disqualified("RSI overbought without strong trend")
elif rsi > 80 and adx >= 25:
    # Starker Trend — RSI overbought ist tolerierbar, nur Penalty
    momentum_score -= 0.5
    warnings.append(f"RSI {rsi:.0f} overbought but ADX {adx:.0f} confirms strong trend")
```

Alternativ die Schwelle auf 85 anheben:
```yaml
disqualification:
  rsi_overbought: 85  # war: 80
```

---

## 💡 OPTIONAL: Markt-Kontext hinzufügen (Prio 4)

### Problem
Der Pullback-Analyzer nutzt SPY-Context, der Trend Continuation nicht. In Bärenmärkten können einzelne Aktien scheinbar perfekte SMA-Alignments zeigen, während der Gesamtmarkt kippt.

### Mögliche Implementierung
Prüfe ob der Pullback-Analyzer bereits eine `get_market_context()` oder ähnliche Funktion hat. Falls ja, analog einbinden:

```python
# Pseudo-Code
spy_trend = get_market_context("SPY")
if spy_trend == "bearish":
    score *= 0.85  # 15% Abzug bei bearischem Gesamtmarkt
    warnings.append("Bearish market context — reduced confidence")
```

---

## 💡 OPTIONAL: Candlestick-Warnung (Prio 5)

### Problem
Die Literatur betont Reversal-Candlestick-Pattern (Evening Star, Shooting Star, Bearish Engulfing) als Frühwarnung. Aktuell werden Kerzenmuster komplett ignoriert.

### Minimal-Implementierung (ohne volle Pattern-Erkennung)
Erkennung einfacher Reversal-Signale als Warnung (nicht Scoring):

```python
# Shooting Star / Hanging Man: Langer oberer Schatten, kleiner Körper
last_candle = data[-1]
body = abs(last_candle['close'] - last_candle['open'])
upper_shadow = last_candle['high'] - max(last_candle['close'], last_candle['open'])
lower_shadow = min(last_candle['close'], last_candle['open']) - last_candle['low']
total_range = last_candle['high'] - last_candle['low']

if total_range > 0 and upper_shadow / total_range > 0.6 and body / total_range < 0.2:
    warnings.append("Shooting star candle detected — potential reversal signal")
```

---

## 💡 OPTIONAL: Exit-Signal (Prio 5)

### Problem
Die Strategie erkennt nur Entry, kein aktives Exit-Signal. Wenn der Trend dreht, gibt es keine Warnung.

### Minimal-Implementierung
Im Monitor/Position-Check zusätzliche Prüfung:

```python
# Exit-Signal wenn SMA-Alignment bricht
if close < sma20 or sma20 < sma50:
    signal = "EXIT"
    reason = "SMA alignment broken — trend may be reversing"
```

---

## Zusammenfassung der Prioritäten

| Prio | Änderung | Dateien | Aufwand |
|------|----------|---------|---------|
| 1 | YAML-Weights / min_score kalibrieren | `analyzer_thresholds.yaml` | Klein |
| 2 | ADX-Schwelle 15→20, Scoring 35→30 | `analyzer_thresholds.yaml`, `trend_continuation.py` | Klein |
| 2 | MACD Signal-Linie SMA→EMA | `trend_continuation.py` | Mittel |
| 3 | RSI Disqualifikation ADX-abhängig | `trend_continuation.py` | Klein |
| 4 | SPY/Markt-Kontext einbinden | `trend_continuation.py` | Mittel |
| 5 | Candlestick-Warnung (minimal) | `trend_continuation.py` | Klein |
| 5 | Exit-Signal | `trend_continuation.py` / Monitor | Mittel |

---

## Testplan nach Änderungen

1. **Scan laufen lassen** mit `optionplay_scan_trend` — prüfen ob jetzt Signale kommen
2. **Bekannte Trend-Aktien testen** (z.B. AAPL, MSFT, NVDA in Aufwärtstrend-Phasen) mit `optionplay_analyze_multi` — Score sollte bei starken Trends 3.0+ erreichen
3. **Vergleich Multi-Scanner** — Trend Continuation sollte neben Pullback und Bounce sichtbar sein, aber nicht dominieren
4. **Edge Cases prüfen:**
   - Aktie mit RSI 82 und ADX 35 → sollte durchkommen (nicht disqualifiziert)
   - Aktie mit ADX 17 → sollte jetzt disqualifiziert werden (war vorher erlaubt)
   - MACD-Crossover-Timing vs. TradingView vergleichen (EMA vs. SMA Signal-Linie)
