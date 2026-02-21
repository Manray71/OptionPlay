# OptionPlay Analyzer-Verbesserungen — Implementierungs-Briefing

## Zweck dieses Dokuments

Basierend auf einer systematischen Literaturrecherche zu Support-Bounce- und ATH-Breakout-Strategien dokumentiert dieses Briefing alle identifizierten Verbesserungspotenziale für die beiden Analyzer. Jede Maßnahme enthält: Priorität, Quellenreferenz, Implementierungsvorschlag und erwartete Wirkung.

**Scope:** `src/analyzers/bounce.py` und `src/analyzers/ath_breakout.py`  
**Config:** `config/analyzer_thresholds.yaml`  
**Datum:** 2025-02-20

---

## Teil 1: Support Bounce Analyzer

### Status Quo

Der Bounce Analyzer deckt die Kern-Literaturkriterien ab: Support-Identifikation (≥2 Touches), Candlestick-Bestätigung (Hammer, Engulfing, Doji), Volume-Analyse, RSI/MACD-Momentum und Dead-Cat-Bounce-Filtering. Das Scoring ist plausibel kalibriert.

### Maßnahme B1: Fibonacci-Retracement als DCB-Filter

**Priorität:** HOCH  
**Komponente:** Filter 4 (Dead Cat Bounce) + neues Scoring-Signal  
**Quelle:** Capital.com, FXOpen DCB-Analyse — flache Retracements (< 38.2%) deuten auf Dead Cat Bounce hin; stärkere Bounces (> 61.8%) zeigen substanzielleres Erholungspotenzial.

**Aktuelles Problem:**  
Der DCB-Filter nutzt nur Volume, RSI und Kerzenfarbe. Ein Bounce, der nur 20% des vorherigen Rückgangs retracet, wird genauso behandelt wie einer, der 50% retracet.

**Implementierung:**

```
Berechnung:
  recent_swing_high = max(prices[-30:-5])  # Hoch vor dem Pullback
  recent_swing_low  = min(prices[-10:])     # Tiefpunkt des Pullbacks
  decline = recent_swing_high - recent_swing_low
  retracement_pct = (current_price - recent_swing_low) / decline * 100

DCB-Risiko-Bewertung:
  retracement < 23.6%  → DCB-Risiko "very high"  → WARNING
  retracement 23.6-38.2% → DCB-Risiko "elevated" → WARNING  
  retracement 38.2-50.0% → neutral
  retracement 50.0-61.8% → positiv
  retracement > 61.8%    → stark positiv
```

**Scoring-Integration (Bounce Confirmation Komponente):**

| Signal | Bedingung | Score |
|--------|-----------|-------|
| Fibonacci Strong | Retracement > 50% | +0.5 |
| Fibonacci Weak | Retracement < 23.6% | -0.5 (neues Penalty) |

**Config-Erweiterung (analyzer_thresholds.yaml):**

```yaml
bounce:
  fib_dcb_warning: 38.2     # Unter diesem Wert: DCB-Warning
  fib_strong_threshold: 50.0 # Über diesem Wert: Bonus
  fib_lookback_high: 30      # Tage für Swing-High-Suche
  fib_lookback_low: 10       # Tage für Swing-Low-Suche
```

**Erwartete Wirkung:** Reduziert False Positives bei schwachen Bounces in Abwärtstrends um geschätzt 15-20%. Besonders effektiv in Kombination mit dem bestehenden Volume-DCB-Check.

---

### Maßnahme B2: SMA 20/50 Rückeroberung als Bounce-Qualitätsindikator

**Priorität:** HOCH  
**Komponente:** Bounce Confirmation (Komponente 3) — neues positives Signal  
**Quelle:** Mehrere Quellen empfehlen übereinstimmend, dass ein Bounce erst als echt gilt, wenn der Preis über einem kurzfristigen MA schließt. Spezifisch: RSI-Crossover über 50 und ein Close über dem 20-Tage-MA eliminieren über 80% falscher Signale.

**Aktuelles Problem:**  
Die Bounce Confirmation nutzt nur Kerzen-Patterns, Close-Vergleich, Green Days, RSI und MACD. Ein Bounce, der den SMA 20 nicht zurückerobert, hat in der Literatur eine deutlich niedrigere Erfolgsquote.

**Implementierung:**

```
Neue Signale für Bounce Confirmation:

Positiv:
  Close > SMA 20              → +0.5 ("Short-term reclaim")
  Close > SMA 50              → +0.25 (additiv zu SMA 20)

Penalty:  
  Close < SMA 20 UND SMA 50   → -0.25 ("Below both short-term MAs")
```

**Berechnung:**  
SMA 20 und SMA 50 sind vermutlich bereits im Context verfügbar (werden im Trend Context für SMA 200 verwendet). Falls nicht, berechnen:

```python
sma_20 = np.mean(prices[-20:])
sma_50 = np.mean(prices[-50:])
```

**Cap-Anpassung:**  
Bounce Confirmation Cap von 2.5 beibehalten. Die neuen Signale ergänzen die bestehenden, sodass ein starker Bounce jetzt mehrere unabhängige Bestätigungen braucht, um den Cap zu erreichen.

**Config-Erweiterung:**

```yaml
bounce:
  sma_reclaim_20_bonus: 0.5
  sma_reclaim_50_bonus: 0.25
  sma_below_both_penalty: -0.25
```

**Erwartete Wirkung:** Filtert schwache Bounces, die zwar am Support abprallen, aber den kurzfristigen Trend nicht umkehren. Verbessert die Signal-Qualität besonders in Seitwärtsmärkten.

---

### Maßnahme B3: RSI-Divergenz-Erkennung (Bullisch)

**Priorität:** MITTEL  
**Komponente:** Bounce Confirmation (Komponente 3) — neues positives Signal  
**Quelle:** TradingSim ATH-Analyse — Technische Oszillatoren wie der RSI können potenzielle Korrekturen zum Trend anzeigen. Divergenzen sind ein klassisches Signal für Trendwenden am Support.

**Aktuelles Problem:**  
Im Briefing bereits als Limitierung 5 dokumentiert. Der Bounce Analyzer prüft nur absolute RSI-Werte und RSI-Richtung, nicht die Divergenz zwischen Preis und RSI.

**Implementierung:**

```
Bullische RSI-Divergenz:
  Bedingung: Preis macht neues Tief (oder gleiches Tief am Support)
             UND RSI macht höheres Tief als beim letzten Support-Test
  
  Erkennung:
    price_low_1 = min(prices[-20:-10])   # Erster Test-Bereich
    price_low_2 = min(prices[-10:])       # Aktueller Test-Bereich
    rsi_at_low_1 = RSI zum Zeitpunkt von price_low_1
    rsi_at_low_2 = aktueller RSI
    
    bullish_divergence = (price_low_2 <= price_low_1 * 1.01) AND (rsi_at_low_2 > rsi_at_low_1 + 2)
```

**Scoring:**

| Signal | Bedingung | Score |
|--------|-----------|-------|
| RSI Bullish Divergence | Preis gleiches/tieferes Tief, RSI höheres Tief | +0.75 |

**Config-Erweiterung:**

```yaml
bounce:
  rsi_divergence_lookback: 20   # Tage für Divergenz-Suche
  rsi_divergence_threshold: 2.0 # Min RSI-Differenz für Divergenz
  rsi_divergence_bonus: 0.75
```

**Erwartete Wirkung:** Erkennt institutionelle Akkumulation am Support, die sich als Divergenz manifestiert. Besonders wertvoll bei wiederholten Support-Tests.

---

### Maßnahme B4: Verschärfter Downtrend-Filter (Optional Uptrend-Gate)

**Priorität:** MITTEL  
**Komponente:** Neuer Pre-Filter oder verschärfter Trend Context  
**Quelle:** Cycle-Theorie-Analyse — Bounces sollten während Korrekturen erwartet werden, nicht als Umkehrsignale interpretiert werden. Ohne Intermediate-Cycle-Bestätigung ist der Bounce nur mechanische Erleichterung, keine verdiente Umkehr.

**Aktuelles Problem:**  
Im Briefing als Limitierung 3 dokumentiert. Anders als der Pullback-Analyzer hat der Bounce kein hartes Uptrend-Gate. Ein starker Downtrend (-2.0 Trend Score) kann durch hohe Scores in anderen Komponenten kompensiert werden.

**Zwei Optionen:**

**Option A — Verschärfter Gradient-Penalty (konservativ):**

```
Aktuelle Logik:
  SMA 200 falling, steep (slope < -1.0%) → -2.0

Neue Logik:
  SMA 200 falling, steep (slope < -1.0%) UND Kurs > 10% unter SMA 200 → Disqualifikation
  SMA 200 falling, steep (slope < -1.0%) UND Kurs 5-10% unter SMA 200 → -2.5 (verschärft)
  SMA 200 falling, moderate → bleibt bei -1.5
```

**Option B — Soft Uptrend-Gate (aggressiver):**

```
Neuer Pre-Filter:
  WENN SMA 200 falling UND Kurs > 8% unter SMA 200:
    → Disqualifikation mit Reason "Strong downtrend — bounce strategy not suitable"
```

**Empfehlung:** Option A — behält die Flexibilität der Bounce-Strategie bei starken Support-Levels, verschärft aber die Penalties in extremen Downtrends.

**Config-Erweiterung:**

```yaml
bounce:
  downtrend_disqualify_below_sma200_pct: 10.0  # Option A: Disqualifikation
  downtrend_severe_penalty: -2.5                 # Verschärfter Penalty
```

**Erwartete Wirkung:** Eliminiert die riskantesten Setups (Bounce in einem Crash-Szenario), behält aber die Fähigkeit, Bounces in moderaten Korrekturen zu erkennen.

---

### Maßnahme B5: Sektor- und Markt-Context

**Priorität:** NIEDRIG  
**Komponente:** Neuer Modifier auf Gesamtscore  
**Quelle:** Allgemeine Best Practice — Die meisten Aktien folgen dem Gesamtmarkt. Ein Bounce gegen den Markttrend hat eine signifikant niedrigere Erfolgsquote.

**Aktuelles Problem:**  
Im Briefing als Limitierung 7 dokumentiert. SPY-Marktkontext und Sektor-Bewertung werden nicht berücksichtigt.

**Implementierung:**

```
SPY-Context (bereits im System vorhanden über sector_status):
  SPY über SMA 50 UND SMA 200 → Markt bullisch → kein Modifier
  SPY unter SMA 50, über SMA 200 → Markt neutral → Score × 0.9
  SPY unter SMA 50 UND SMA 200 → Markt bärisch → Score × 0.8

Optional: Sektor-Modifier
  Sektor-RS > 0 → kein Modifier
  Sektor-RS < 0 → Score × 0.9
```

**Hinweis:** Abhängig von der Verfügbarkeit der SPY/Sektor-Daten im Analyzer-Context. Möglicherweise ist ein separater Refactoring-Schritt nötig, um den Market-Context in die Analyzer-Pipeline zu integrieren.

**Config-Erweiterung:**

```yaml
bounce:
  market_context_enabled: true
  market_bearish_multiplier: 0.8
  market_neutral_multiplier: 0.9
  sector_weak_multiplier: 0.9
```

**Erwartete Wirkung:** Reduziert False Positives in Bärenmärkten. Niedrige Priorität, weil der Trend-Context-Score teilweise bereits einen ähnlichen Effekt hat.

---

### Maßnahme B6: Bollinger-Band-Proximity als Support-Confluence

**Priorität:** NIEDRIG  
**Komponente:** Support Quality (Komponente 1) — zusätzlicher Confluence-Bonus  
**Quelle:** Mehrere Quellen empfehlen die Kombination von horizontalem Support mit dynamischen Indikatoren wie Bollinger Bands. Wenn ein Kurs das untere Bollinger-Band berührt und gleichzeitig an einem horizontalen Support ist, verstärkt das die Signalstärke.

**Implementierung:**

```
Bollinger Band Berechnung:
  bb_middle = SMA(20)
  bb_std = std(prices[-20:])
  bb_lower = bb_middle - 2 * bb_std

Confluence-Check:
  WENN current_price innerhalb 1% des bb_lower
  UND current_price innerhalb proximity_max des Support-Levels:
    → +0.25 Bonus auf Support Quality

Alternativ: Bollinger-Band-Squeeze als Vorbedingung:
  bb_width = (bb_upper - bb_lower) / bb_middle
  WENN bb_width < historisches 20%-Perzentil:
    → Volatilitäts-Kontraktion → stärkerer Bounce-Kandidat
```

**Config-Erweiterung:**

```yaml
bounce:
  bb_confluence_enabled: false    # Default aus, opt-in
  bb_confluence_tolerance: 1.0    # % Toleranz zum unteren Band
  bb_confluence_bonus: 0.25
  bb_squeeze_enabled: false
  bb_squeeze_percentile: 20
```

**Erwartete Wirkung:** Marginale Verbesserung der Support-Qualitäts-Bewertung. Niedrige Priorität wegen hohem Implementierungsaufwand relativ zum Nutzen.

---

### Zusammenfassung Bounce Analyzer

| ID | Maßnahme | Priorität | Neue Punkte | Betrifft |
|----|----------|-----------|-------------|----------|
| B1 | Fibonacci-Retracement DCB-Filter | HOCH | +0.5 / -0.5 | Filter 4 + Komponente 3 |
| B2 | SMA 20/50 Rückeroberung | HOCH | +0.5 / +0.25 / -0.25 | Komponente 3 |
| B3 | RSI Bullische Divergenz | MITTEL | +0.75 | Komponente 3 |
| B4 | Verschärfter Downtrend-Filter | MITTEL | Disqualifikation/-2.5 | Filter/Komponente 5 |
| B5 | Sektor/Markt-Context | NIEDRIG | Score-Multiplier | Gesamtscore |
| B6 | Bollinger-Band-Confluence | NIEDRIG | +0.25 | Komponente 1 |

**Cap-Auswirkung auf Bounce Confirmation (Komponente 3):**  
Mit B1, B2 und B3 kommen theoretisch +1.75 neue Bonus-Punkte und -0.75 neue Penalty-Punkte hinzu. Der aktuelle Cap von 2.5 reicht aus — die neuen Signale machen es schwieriger, aber nicht unmöglich, den Cap zu erreichen. Ein perfekter Bounce braucht jetzt mehrere unabhängige Bestätigungen.

---

## Teil 2: ATH Breakout Analyzer

### Status Quo

Der ATH Breakout Analyzer deckt die Kernmechanik korrekt ab: ATH-Identifikation (252-Tage), Close-Confirmation, Volume-Bestätigung, RSI-Filter und SMA-Trend-Kontext. Das Scoring ist plausibel, das praktische Maximum liegt bei ~8.5.

### Maßnahme A1: Volatilitätskontraktion (VCP-inspiriert)

**Priorität:** HOCH  
**Komponente:** Consolidation Quality (Komponente 1) — neuer Sub-Score  
**Quelle:** Mark Minervini VCP — Jeder Pullback wird kleiner, die Volatilität kontrahiert progressiv. Dies ist DAS Unterscheidungsmerkmal zwischen zufälliger Konsolidierung und institutioneller Akkumulation.

**Aktuelles Problem:**  
Im Briefing als Limitierung 6 dokumentiert. Die Konsolidierung wird rein über High-Low-Range geprüft. Ob die Volatilität innerhalb der Konsolidierung abnimmt, wird nicht geprüft.

**Implementierung:**

```
Volatilitätskontraktion messen:
  Teile das Konsolidierungsfenster in zwei Hälften:
    first_half_range = (max(highs[:mid]) - min(lows[:mid])) / max(highs[:mid]) * 100
    second_half_range = (max(highs[mid:]) - min(lows[mid:])) / max(highs[mid:]) * 100
    
  Kontraktion = first_half_range / second_half_range
  
  Alternativ (ATR-basiert, präziser):
    atr_first_half = mean(ATR(14) über erste Hälfte)
    atr_second_half = mean(ATR(14) über zweite Hälfte)
    contraction_ratio = atr_first_half / atr_second_half

Bewertung:
  contraction_ratio > 2.0  → "strong contraction" → +0.5 Bonus
  contraction_ratio > 1.5  → "moderate contraction" → +0.25 Bonus
  contraction_ratio > 1.0  → "some contraction" → 0
  contraction_ratio ≤ 1.0  → "expanding volatility" → -0.25 Penalty (WARNING)
```

**Scoring-Integration:**  
Als Sub-Score innerhalb von Consolidation Quality, separat vom Range/Duration-Score:

```
Consolidation Quality = Range_Duration_Score + ATH_Test_Bonus + VCP_Contraction_Bonus
Cap: 3.0 (erhöht von 2.5, um Platz für den neuen Sub-Score zu schaffen)
```

**Config-Erweiterung:**

```yaml
ath_breakout:
  vcp_enabled: true
  vcp_contraction_strong: 2.0
  vcp_contraction_moderate: 1.5
  vcp_contraction_bonus_strong: 0.5
  vcp_contraction_bonus_moderate: 0.25
  vcp_expanding_penalty: -0.25
```

**Max-Score-Anpassung:**  
Mit dem neuen Cap von 3.0 für Consolidation Quality steigt das theoretische Maximum von 8.5 auf 9.0 (3.0 + 2.0 + 2.5 + 1.5). Dies nähert sich dem konfigurierten `max_score` von 9.5 sinnvoll an.

**Erwartete Wirkung:** Identifiziert die höchstwahrscheinlichen Breakout-Setups (enge finale Konsolidierung nach Volatilitäts-Abnahme). In der Literatur zeigen VCP-Muster signifikant höhere Follow-Through-Raten als reine Range-Breakouts.

---

### Maßnahme A2: Konsolidierungs-Volumen-Profil

**Priorität:** HOCH  
**Komponente:** Volume Confirmation (Komponente 3) — neuer Sub-Score  
**Quelle:** O'Neil CANSLIM, Minervini VCP — "Look for relatively quiet volume as the stock builds the left side of the cup. Volume drops off during the consolidation." Abnehmedes Volumen während der Konsolidierung zeigt, dass Verkäufer austrocknen (Supply Drying Up).

**Aktuelles Problem:**  
Der Volume-Check prüft nur das Breakout-Day-Volumen vs. 20-Tage-Durchschnitt. Ob das Volumen während der Konsolidierung abgenommen hat (institutionelle Akkumulation), wird nicht geprüft.

**Implementierung:**

```
Konsolidierungs-Volumen-Analyse:
  consol_volumes = volumes[consol_start:consol_end]  # Volumen während der Base
  
  Methode 1 — Trendvergleich:
    first_half_avg = mean(consol_volumes[:mid])
    second_half_avg = mean(consol_volumes[mid:])
    vol_contraction = first_half_avg / second_half_avg
    
  Methode 2 — Einfacher: Vergleich mit Pre-Consolidation
    pre_consol_avg = mean(volumes vor Konsolidierung, 20 Tage)
    consol_avg = mean(consol_volumes)
    vol_dryup_ratio = pre_consol_avg / consol_avg

Bewertung:
  vol_dryup_ratio > 1.5  → "strong dryup" → +0.5 Bonus
  vol_dryup_ratio > 1.2  → "moderate dryup" → +0.25 Bonus
  vol_dryup_ratio < 0.8  → "increasing volume in base" → -0.25 (Distribution-Warning)
```

**Scoring-Integration:**  
Als zusätzlicher Sub-Score in der Volume-Komponente:

```
Volume Score = Breakout_Volume_Score + Consol_Volume_Profile_Score
Cap: 3.0 (erhöht von 2.5)
```

**Config-Erweiterung:**

```yaml
ath_breakout:
  consol_volume_profile_enabled: true
  consol_vol_dryup_strong: 1.5
  consol_vol_dryup_moderate: 1.2
  consol_vol_dryup_strong_bonus: 0.5
  consol_vol_dryup_moderate_bonus: 0.25
  consol_vol_distribution_penalty: -0.25
```

**Erwartete Wirkung:** Unterscheidet zwischen Konsolidierungen mit Akkumulation (bullisch — Volumen trocknet aus) und solchen mit Distribution (bärisch — Volumen steigt während der Base). CFA-Institute-Studien zeigen, dass Breakouts mit vorheriger Volume-Kontraktion eine um ~15 Prozentpunkte höhere Follow-Through-Rate haben.

---

### Maßnahme A3: Relative Strength vs. Markt (SPY)

**Priorität:** HOCH  
**Komponente:** Momentum/Trend (Komponente 4) — neuer Sub-Score  
**Quelle:** Green Line Breakout-Methode — "Kombiniere den GLB-Screen mit Relative-Stärke-Analyse. Aktien, die in neue Hochs ausbrechen während der Gesamtmarkt konsolidiert oder fällt, zeigen außergewöhnliche Stärke und werden oft die größten Gewinner." Minervini Trend Template: RS-Rating > 70 erforderlich.

**Aktuelles Problem:**  
Im Briefing als Limitierung 4 dokumentiert. Kein Vergleich mit dem Gesamtmarkt. Ein ATH-Breakout in einer schwachen Aktie, die nur wegen eines allgemeinen Marktanstiegs neue Hochs erreicht, wird genauso behandelt wie ein Breakout einer Aktie mit genuiner relativer Stärke.

**Implementierung:**

```
Relative-Strength-Berechnung (vereinfacht):
  stock_perf_3m = (current_price / price_60_days_ago - 1) * 100
  spy_perf_3m = (spy_current / spy_60_days_ago - 1) * 100
  
  rs_vs_spy = stock_perf_3m - spy_perf_3m

Bewertung:
  rs_vs_spy > 20%  → "strong outperformance" → +0.5
  rs_vs_spy > 10%  → "moderate outperformance" → +0.25
  rs_vs_spy > 0%   → "in-line" → 0
  rs_vs_spy < -10% → "underperformance" → -0.5 (WARNING: "Laggard breakout")
```

**Datenquelle:**  
SPY-Daten sind vermutlich über die bestehende `optionplay_historical` API verfügbar. Alternativ Cache der SPY-Performance.

**Scoring-Integration:**  
Als neues Signal innerhalb Momentum/Trend:

```
Momentum Score = SMA_Alignment + MACD + RSI + Relative_Strength
Floor: -1.5 (angepasst von -1.0)
Cap: 2.0 (erhöht von 1.5)
```

**Config-Erweiterung:**

```yaml
ath_breakout:
  relative_strength_enabled: true
  rs_lookback_days: 60
  rs_strong_outperformance: 20.0
  rs_moderate_outperformance: 10.0
  rs_underperformance: -10.0
  rs_strong_bonus: 0.5
  rs_moderate_bonus: 0.25
  rs_underperformance_penalty: -0.5
```

**Erwartete Wirkung:** Filtert "Mitläufer-Breakouts" (Aktien, die nur wegen einer allgemeinen Marktrallye neue Hochs erreichen). In der Literatur haben Breakouts in Aktien mit hoher RS eine signifikant höhere Follow-Through-Rate und größere Average Gains.

---

### Maßnahme A4: Breakout-Kerzenform-Analyse

**Priorität:** MITTEL  
**Komponente:** Breakout Strength (Komponente 2) — neuer Sub-Score  
**Quelle:** Trade That Swing — "Der Kandidat sollte einen starken Breakout gehabt haben: die Tageskerze schließt nahe ihrem Hoch und das Volumen hat am Breakout-Tag zugenommen." Trade with the Pros — "Saubere Breaks über dem Widerstand mit minimalen Dochten an Breakout-Kerzen."

**Aktuelles Problem:**  
Im Briefing als Limitierung 5 dokumentiert. Nur der Close-Abstand zum ATH wird bewertet. Die Form der Breakout-Kerze (Close nahe High, minimaler oberer Docht) wird ignoriert.

**Implementierung:**

```
Breakout-Kerzen-Analyse:
  body = abs(close - open_approx)       # open_approx = prices[-2] wie im Bounce
  total_range = high - low
  upper_wick = high - max(close, open_approx)
  lower_wick = min(close, open_approx) - low
  
  close_position = (close - low) / total_range  # 0 = Close am Low, 1 = Close am High

Kerzenqualität:
  Marubozu (Close = High, kein oberer Docht):
    upper_wick < 0.05 * total_range UND close > open_approx
    → "Strong conviction candle" → +0.5
    
  Wide Range Bar (überdurchschnittlich groß):
    total_range > 1.5 * ATR(14)
    → "Wide range breakout bar" → +0.25
    
  Close nahe High:
    close_position > 0.8
    → +0.25
    
  Schwache Kerze (langer oberer Docht):
    upper_wick > 0.5 * total_range
    → "Long upper wick — selling into breakout" → -0.5
```

**Scoring-Integration:**

```
Breakout Strength = PCT_Above_Score + Multi_Day_Bonus + Candle_Quality
Cap: 2.5 (erhöht von 2.0)
```

**Config-Erweiterung:**

```yaml
ath_breakout:
  candle_analysis_enabled: true
  marubozu_wick_max_pct: 5.0     # Max oberer Docht in % der Range
  wide_range_atr_mult: 1.5       # ATR-Multiplikator für WRB
  close_near_high_threshold: 0.8 # Close-Position > 80%
  long_wick_threshold: 0.5       # Oberer Docht > 50% der Range
  marubozu_bonus: 0.5
  wide_range_bonus: 0.25
  close_high_bonus: 0.25
  long_wick_penalty: -0.5
```

**Erwartete Wirkung:** Unterscheidet zwischen Breakouts mit starker institutioneller Überzeugung (Close = High, großer Body) und schwachen Breakouts (langer oberer Docht = Selling Into Strength). In der Praxis ist die Kerzenform einer der besten Early Indicators für Breakout-Follow-Through.

---

### Maßnahme A5: Gap-Up-Erkennung

**Priorität:** MITTEL  
**Komponente:** Breakout Strength (Komponente 2) — neuer Sub-Score  
**Quelle:** Allgemeine Breakout-Literatur — "Ein Gap-Breakout signalisiert eine fundamentale Verschiebung in Angebot und Nachfrage." Gap-Ups über das ATH sind besonders stark, da sie zeigen, dass die Nachfrage bereits vor Markteröffnung das Angebot übersteigt.

**Aktuelles Problem:**  
Im Briefing als Limitierung 8 dokumentiert. Open-Daten stehen zur Verfügung (`opens` im Context), werden aber nicht verwendet.

**Implementierung:**

```
Gap-Up-Erkennung:
  WENN opens verfügbar:
    gap_pct = (open_today - prev_close) / prev_close * 100
    gap_above_ath = (open_today > prev_ath)  # Open bereits über dem ATH
    
  Bewertung:
    gap_above_ath UND gap_pct > 3%  → "Power Gap" → +0.5
    gap_above_ath UND gap_pct 1-3%  → "Gap Up Breakout" → +0.25
    gap_pct < 0 (Gap Down) UND Close > ATH → "Reversal Breakout" → +0.25
```

**Scoring-Integration:**  
Teil der Breakout Strength-Komponente. Kann mit A4 (Kerzenform) kombiniert werden:

```
Breakout Strength = PCT_Above + Multi_Day + Candle_Quality + Gap_Bonus
Cap: 2.5 (wie bei A4)
```

**Config-Erweiterung:**

```yaml
ath_breakout:
  gap_analysis_enabled: true
  gap_power_threshold: 3.0     # % für Power Gap
  gap_standard_threshold: 1.0  # % für Standard Gap
  gap_power_bonus: 0.5
  gap_standard_bonus: 0.25
```

**Hinweis:** Nur aktivieren, wenn `opens` zuverlässig im Context vorhanden sind. Fallback: Feature deaktiviert, kein Impact auf bestehende Logik.

**Erwartete Wirkung:** Erkennt die stärksten Breakout-Varianten (institutionelle Pre-Market-Käufe). Power Gaps über das ATH haben historisch die höchsten Follow-Through-Raten.

---

### Maßnahme A6: Konsolidierungsdauer-Erweiterung

**Priorität:** MITTEL  
**Komponente:** Filter 1 + Consolidation Quality  
**Quelle:** Green Line Breakout (Dr. Eric Wish) — "Vor dem Ausbruch sollte die Aktie mindestens drei Monate seitwärts gelaufen sein." O'Neil — Cup-with-Handle dauert typischerweise 7+ Wochen.

**Aktuelles Problem:**  
Der Lookback ist auf 60 Tage begrenzt (`consol_lookback: 60`). Die GLB-Literatur empfiehlt mindestens 3 Monate (≈63 Handelstage). Längere Konsolidierungen (3-6 Monate) können besonders starke Breakouts produzieren.

**Implementierung:**

```
Erweiterung der Fenstersuche:
  consol_lookback: 120    # Erhöht von 60 auf 120 Tage (≈6 Monate)
  consol_min_days: 20     # Bleibt bei 20

Scoring-Anpassung für längere Bases:
  Aktuell: ≥ 30 Tage = "long" (Bonus)
  
  Neu:
  ≥ 60 Tage (3 Monate) = "very long" → zusätzlicher Duration-Bonus
```

**Scoring-Erweiterung:**

| Range | Dauer | Score (NEU) |
|-------|-------|-------------|
| ≤ 8% (tight) | ≥ 60 Tage | 2.5 + Duration-Bonus (bereits am Cap) |
| ≤ 8% (tight) | ≥ 30 Tage | 2.5 |
| 8–12% (moderate) | ≥ 60 Tage | 2.5 (erhöht von 2.0) |
| 8–12% (moderate) | ≥ 30 Tage | 2.0 |
| Rest | — | wie bisher |

**Config-Anpassung:**

```yaml
ath_breakout:
  consol_lookback: 120          # Erhöht von 60
  consol_duration_very_long: 60 # Neuer Schwellenwert
```

**Erwartete Wirkung:** Erkennt die "Power Bases" (3-6 Monate enge Konsolidierung), die laut GLB-Literatur die stärksten Breakouts produzieren. Kein Downside, da kürzere Bases weiterhin erkannt werden.

---

### Maßnahme A7: Re-Test/Pullback-Erkennung (Future Enhancement)

**Priorität:** NIEDRIG  
**Komponente:** Neuer alternativer Entry-Modus  
**Quelle:** TradingSim — "Sobald ein Breakout über das vorherige ATH auftritt, sollte man auf einen Pullback warten, bevor man den Trade eingeht."

**Aktuelles Problem:**  
Im Briefing als Limitierung 7 dokumentiert. Nur der initiale Breakout wird bewertet. Das klassische Breakout-Pullback-Retest-Muster wird nicht erkannt.

**Konzept (kein konkreter Implementierungsvorschlag):**

```
Re-Test-Erkennung (Multi-Day):
  Tag 1: Breakout über ATH (normaler ATH-Breakout-Scan)
  Tag 2-5: Pullback Richtung ATH
  Tag 6+: Preis testet ATH als Support und hält (Close > ATH)
  
  → Signal: "ATH Re-Test Buy" mit eigener Scoring-Logik
```

**Warum niedrige Priorität:**  
Erfordert Multi-Day-State-Tracking, das über die aktuelle Single-Day-Scan-Architektur hinausgeht. Die Position-Monitoring-Logik müsste erweitert werden, um "pending re-test" Zustände zu tracken. Das ist ein architektonischer Change, kein einfacher Feature-Add.

**Empfehlung:** Als separater Analyzer oder als Erweiterung des Monitoring-Systems implementieren, nicht als Teil des bestehenden ATH-Breakout-Scanners.

---

### Zusammenfassung ATH Breakout Analyzer

| ID | Maßnahme | Priorität | Neue Punkte | Betrifft |
|----|----------|-----------|-------------|----------|
| A1 | Volatilitätskontraktion (VCP) | HOCH | +0.5 / +0.25 / -0.25 | Komponente 1 |
| A2 | Konsolidierungs-Volumen-Profil | HOCH | +0.5 / +0.25 / -0.25 | Komponente 3 |
| A3 | Relative Strength vs. SPY | HOCH | +0.5 / +0.25 / -0.5 | Komponente 4 |
| A4 | Breakout-Kerzenform | MITTEL | +0.5 / +0.25 / -0.5 | Komponente 2 |
| A5 | Gap-Up-Erkennung | MITTEL | +0.5 / +0.25 | Komponente 2 |
| A6 | Konsolidierungsdauer-Erweiterung | MITTEL | Score-Adjustment | Komponente 1 |
| A7 | Re-Test/Pullback (Konzept) | NIEDRIG | n/a | Neuer Modus |

---

## Teil 3: Score-Architektur-Anpassungen

### Neue Max-Score-Kalkulation nach Implementierung

**Bounce Analyzer (nach B1-B4):**

| Komponente | Aktuell Max | Neu Max | Änderung |
|-----------|------------|---------|----------|
| Support Quality | 2.5 | 2.5 | — |
| Proximity | 2.0 | 2.0 | — |
| Bounce Confirmation | 2.5 | 2.5 | Mehr Signale, gleicher Cap |
| Volume | 1.5 | 1.5 | — |
| Trend Context | 1.5 | 1.5 | — |
| **Gesamt** | **10.0** | **10.0** | **Keine Änderung am Maximum** |

Die neuen Signale machen es **schwieriger, den Cap zu erreichen** (mehr unabhängige Bestätigungen nötig), aber ändern das theoretische Maximum nicht. Der Haupteffekt ist eine bessere Differenzierung zwischen starken und schwachen Bounces.

**ATH Breakout Analyzer (nach A1-A6):**

| Komponente | Aktuell Max | Neu Max | Änderung |
|-----------|------------|---------|----------|
| Consolidation Quality | 2.5 | 3.0 | +0.5 (VCP) |
| Breakout Strength | 2.0 | 2.5 | +0.5 (Kerze/Gap) |
| Volume Confirmation | 2.5 | 3.0 | +0.5 (Consol-Profile) |
| Momentum/Trend | 1.5 | 2.0 | +0.5 (RS) |
| **Gesamt** | **8.5** | **10.5** | **+2.0 → clamped auf 10.0** |

**Wichtig:** Das praktische Maximum steigt von 8.5 auf ~10.0-10.5, womit der konfigurierte `max_score` von 9.5 jetzt tatsächlich erreichbar wird. Das ist eine signifikante Verbesserung der Score-Dynamik, da bisher die oberen 15% der Skala nie genutzt wurden.

**Empfehlung:** `max_score` auf 10.0 anpassen (wie beim Bounce), damit die Normalisierung konsistent bleibt.

---

### Normalisierung

Beide Analyzer verwenden `max_possible = 10.0` mit der Identitäts-Normalisierung. Nach den Anpassungen bleibt dies konsistent — beide Analyzer haben ein theoretisches Maximum, das die 10.0 erreicht oder leicht übersteigt (Clamping).

Falls gewünscht, könnte eine **dynamische Normalisierung** wie beim Pullback-Analyzer eingeführt werden:

```python
max_dynamic = max(actual_component_sum, max_possible * 0.5)
normalized = (raw_score / max_dynamic) * 10.0
```

Das hätte den Vorteil, dass Scores vergleichbarer werden, wenn bestimmte Komponenten durch fehlende Daten nicht berechenbar sind.

---

## Teil 4: Implementierungs-Reihenfolge

### Phase 1 — Quick Wins (HOCH-Priorität, moderate Komplexität)

| Reihenfolge | ID | Geschätzte Komplexität | Abhängigkeiten |
|-------------|-----|----------------------|----------------|
| 1 | A6 | Gering — Config-Änderung | Keine |
| 2 | B2 | Gering — SMA bereits berechnet | Keine |
| 3 | B1 | Mittel — Fibonacci-Logik | Keine |
| 4 | A4 | Mittel — Kerzen-Analyse | Opens im Context |

### Phase 2 — Substanzielle Verbesserungen (HOCH-Priorität, höhere Komplexität)

| Reihenfolge | ID | Geschätzte Komplexität | Abhängigkeiten |
|-------------|-----|----------------------|----------------|
| 5 | A1 | Mittel — ATR-Berechnung | Keine |
| 6 | A2 | Mittel — Volume-Analyse | Konsolidierungs-Fenster |
| 7 | A3 | Hoch — SPY-Daten nötig | Market-Data-Provider |

### Phase 3 — Feintuning (MITTEL/NIEDRIG-Priorität)

| Reihenfolge | ID | Geschätzte Komplexität | Abhängigkeiten |
|-------------|-----|----------------------|----------------|
| 8 | B3 | Mittel — RSI-History nötig | Keine |
| 9 | B4 | Gering — Schwellenwert-Anpassung | Keine |
| 10 | A5 | Gering — Opens im Context | Opens-Daten |
| 11 | B5 | Hoch — Architektur-Change | Sector-Status-Integration |
| 12 | B6 | Mittel — Bollinger-Berechnung | Keine |

---

## Teil 5: Config-Gesamtübersicht (Neue Parameter)

### analyzer_thresholds.yaml — Bounce-Erweiterungen

```yaml
bounce:
  # B1: Fibonacci DCB Filter
  fib_dcb_enabled: true
  fib_dcb_warning: 38.2
  fib_strong_threshold: 50.0
  fib_lookback_high: 30
  fib_lookback_low: 10
  fib_strong_bonus: 0.5
  fib_weak_penalty: -0.5

  # B2: SMA Reclaim
  sma_reclaim_enabled: true
  sma_reclaim_20_bonus: 0.5
  sma_reclaim_50_bonus: 0.25
  sma_below_both_penalty: -0.25

  # B3: RSI Divergence
  rsi_divergence_enabled: true
  rsi_divergence_lookback: 20
  rsi_divergence_threshold: 2.0
  rsi_divergence_bonus: 0.75

  # B4: Downtrend Filter
  downtrend_disqualify_below_sma200_pct: 10.0
  downtrend_severe_penalty: -2.5

  # B5: Market Context
  market_context_enabled: false  # Default aus
  market_bearish_multiplier: 0.8
  market_neutral_multiplier: 0.9
  sector_weak_multiplier: 0.9

  # B6: Bollinger Confluence
  bb_confluence_enabled: false  # Default aus
  bb_confluence_tolerance: 1.0
  bb_confluence_bonus: 0.25
```

### analyzer_thresholds.yaml — ATH-Breakout-Erweiterungen

```yaml
ath_breakout:
  # A1: VCP Contraction
  vcp_enabled: true
  vcp_contraction_strong: 2.0
  vcp_contraction_moderate: 1.5
  vcp_contraction_bonus_strong: 0.5
  vcp_contraction_bonus_moderate: 0.25
  vcp_expanding_penalty: -0.25

  # A2: Consolidation Volume Profile
  consol_volume_profile_enabled: true
  consol_vol_dryup_strong: 1.5
  consol_vol_dryup_moderate: 1.2
  consol_vol_dryup_strong_bonus: 0.5
  consol_vol_dryup_moderate_bonus: 0.25
  consol_vol_distribution_penalty: -0.25

  # A3: Relative Strength
  relative_strength_enabled: true
  rs_lookback_days: 60
  rs_strong_outperformance: 20.0
  rs_moderate_outperformance: 10.0
  rs_underperformance: -10.0
  rs_strong_bonus: 0.5
  rs_moderate_bonus: 0.25
  rs_underperformance_penalty: -0.5

  # A4: Candle Analysis
  candle_analysis_enabled: true
  marubozu_wick_max_pct: 5.0
  wide_range_atr_mult: 1.5
  close_near_high_threshold: 0.8
  long_wick_threshold: 0.5
  marubozu_bonus: 0.5
  wide_range_bonus: 0.25
  close_high_bonus: 0.25
  long_wick_penalty: -0.5

  # A5: Gap Analysis
  gap_analysis_enabled: true
  gap_power_threshold: 3.0
  gap_standard_threshold: 1.0
  gap_power_bonus: 0.5
  gap_standard_bonus: 0.25

  # A6: Extended Lookback
  consol_lookback: 120          # Erhöht von 60
  consol_duration_very_long: 60

  # Score Caps (angepasst)
  consolidation_cap: 3.0        # Erhöht von 2.5
  breakout_strength_cap: 2.5    # Erhöht von 2.0
  volume_cap: 3.0               # Erhöht von 2.5
  momentum_cap: 2.0             # Erhöht von 1.5
  momentum_floor: -1.5          # Angepasst von -1.0
  max_score: 10.0               # Angepasst von 9.5
```

---

## Teil 6: Testplan

### Regressionstests

Für jede Maßnahme:

1. **Bestehende Signale:** Alle aktuellen Scan-Ergebnisse müssen weiterhin erkannt werden (kein Signal-Verlust durch neue Filter)
2. **Score-Stabilität:** Durchschnittlicher Score-Change über die Watchlist sollte < 0.5 Punkte sein
3. **Neue Feature disabled:** Mit `*_enabled: false` muss das Verhalten identisch zum aktuellen Stand sein

### Validierungstests

1. **Bekannte gute Setups:** 5-10 historische Trades mit positivem Outcome → Score muss steigen oder stabil bleiben
2. **Bekannte schlechte Setups:** 5-10 historische Trades mit negativem Outcome → Score muss fallen oder Disqualifikation
3. **Edge Cases:** Aktien mit fehlenden Daten (Volume = 0, < 50 Tage History) → keine Crashes, graceful Degradation

### Backtesting-Empfehlung

Nach Implementierung aller Phase-1-Maßnahmen einen Backtest über 6-12 Monate Watchlist-History durchführen:

- Win-Rate vorher vs. nachher
- Average Score der Gewinner vs. Verlierer
- False-Positive-Rate (Signale, die sofort gestoppt werden)
- Score-Distribution (sollte breiter sein als vorher)
