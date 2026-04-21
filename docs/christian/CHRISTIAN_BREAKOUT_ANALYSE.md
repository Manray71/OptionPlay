# Christians Breakout-Erkennungssystem — Analyse für OptionPlay

**Quellen:** 22 Python-Dateien (845KB), Schwerpunkt `technical.py` (3.774 Zeilen, 70 Funktionen), `scanner.py` (1.744 Zeilen), `shadow_analyzer.py` (483 Zeilen)

---

## 1. Architektur-Überblick

Christians System erkennt Breakout-Kandidaten durch ein **zweistufiges Scoring** in `compute_final_scores()`:

```
final_score = bps_score + fast_score × 1.5
```

Der **Fast Score** (Breakout-Wahrscheinlichkeit) wird mit Faktor 1.5 gewichtet. Das heisst: Breakout-Signale haben 60% mehr Gewicht als ihr Rohwert. Ein Kandidat mit schwachem BPS-Score aber starkem Breakout-Profil kann damit einen konservativen Kandidaten ohne Momentum überholen.

Die SIGNAL_ICONS in `scanner.py` definieren eine explizite **Hierarchie der Breakout-Qualität**:

| Rang | Signal | Fast-Score-Punkte | Beschreibung |
|------|--------|-------------------|-------------|
| 1 | 🚩⚡ BREAKOUT IMMINENT | +25 | Bull Flag Stufe 2: höhere Tiefs + Volumen kontrahiert |
| 2 | 🎯 PRE-BREAKOUT | +20 | Wyckoff Phase 2: CMF↑ + MFI↑ + OBV über SMA20 + RSI 50-65 |
| 3 | 📊 VWAP Reclaim | +15 | Preis war unter Weekly VWAP, jetzt darüber mit Aufwärtsimpuls |
| 4 | 📅 PEAD | +15 | Post-Earnings Drift: akademisch belegte Anomalie in den ersten Tagen |
| 5 | 📈 3-Bar Play | +12 | Drei bullische Kerzen, steigendes Volumen, kein Docht |
| 6 | ⚙️ BB Squeeze released | +12 | Bollinger-Bänder im 20%-Perzentil, jetzt expandierend |
| 7 | 🚩 Bull Flag | +12 | Stufe 1: Fahnenstange ≥5%, Rücksetzer ≤30%, Volumen-Abnahme |
| 8 | 🕯️ NR7+Inside Bar | +10 | Kombination aus niedrigster 7-Tage-Range + Mutterkurz-Einschluss |
| 9 | ✧ Golden Pocket+ | +7-10 | Fibonacci 50-65% nur mit ≥2 Confluence-Signalen |

**Entfernte Signale (bewusst rausgeworfen):**
- Akkumulation Phase 1 (zu früh im Zyklus)
- BB Squeeze ohne Release (kein Trigger)
- NR7 allein, Inside Bar allein (keine Bestätigung)
- Über VWAP ohne Reclaim (Dauerzustand, kein Signal)

---

## 2. Die Breakout-Pattern im Detail

### 2.1 BREAKOUT IMMINENT — Bull Flag Stufe 2

Christians stärkstes Signal. Zweiteilige Erkennung in `bull_flag_analysis()`:

**Stufe 1 (Flagge identifiziert):**
- Fahnenstange: Peak in letzten 5-15 Tagen, mindestens +5% vom Tiefpunkt
- Rücksetzer: maximal 30% der Fahnenstange (streng, nicht 50% wie oft gelehrt)
- Volumen in Flagge ≥ 20% niedriger als in Fahnenstange
- Mindestens 3 Tage Flaggenformation

**Stufe 2 (Breakout steht bevor):**
Alle vier Sub-Signale werden geprüft. Pflicht sind höhere Tiefs + Volumen-Kontraktion, dazu mindestens eines der weiteren:

1. **Höhere Tiefs** in der Flagge (0.5% Toleranz pro Tag)
2. **Volumen kontrahiert**: letzte 2 Tage < 70% des Flaggen-Durchschnitts
3. **OBV steigt** trotz Seitwärtsbewegung (Smart Money kauft)
4. **RSI erholt sich** auf 50-65 (Platz nach oben, aber nicht überkauft)

Formel: `imminent = higher_lows AND vol_contracting AND (obv_rising OR rsi_recovering)`

**Was wir lernen:** Die Kombination aus Preis-Konsolidierung + Volumen-Kontraktion + OBV-Divergenz ist der Schlüssel. OptionPlay hat derzeit keinen Bull-Flag-Detector. Das ist das wertvollste einzelne Pattern, das wir übernehmen können.

### 2.2 PRE-BREAKOUT (Wyckoff Phase 2)

Erkennung durch gleichzeitiges Erfüllen von vier Money-Flow-Indikatoren in `score_technicals()`:

```python
_phase2 = (
    cmf_val > 0.10 and cmf_rising and
    mfi_val >= 50 and mfi_val <= 65 and mfi_rising and
    obv_above_sma20 and
    50 <= rsi <= 65
)
```

Die Logik: Wenn alle drei Geldfluss-Indikatoren (CMF, MFI, OBV) gleichzeitig positiv sind UND der RSI im idealen Bereich liegt, ist institutionelle Akkumulation fast abgeschlossen. Phase 1 (frühes Signal) wurde bewusst entfernt weil der Zeithorizont für Bull Put Spreads zu lang war.

**Was wir lernen:** Wir haben CMF, MFI und OBV bereits in OptionPlay. Was fehlt: die kombinierte Bedingung als explizites "Phase 2"-Signal. In E.2b.2 (Money Flow) können wir das direkt einbauen.

### 2.3 VWAP Reclaim

`weekly_vwap_reclaim()` berechnet den volumengewichteten Durchschnittspreis der letzten 10 Handelstage:

```
VWAP = Σ(typical_price × volume) / Σ(volume)
typical_price = (high + low + close) / 3
```

Reclaim-Bedingung: gestern oder vorgestern unter VWAP, heute darüber, und Preis steigt. Das Signal zeigt, dass institutionelle Käufer nach einem kurzen Rücksetzer wieder einsteigen.

**Was wir lernen:** Einfach zu implementieren, hohe Signalqualität. OptionPlay hat keine VWAP-Berechnung. Als Push-Indikator in E.2b.3 eingeplant.

### 2.4 Bollinger Squeeze + Release

`bollinger_squeeze()` nutzt Perzentil-Rang statt festen Schwellen:

- Squeeze: aktuelle Bandbreite im untersten 20%-Perzentil der letzten 50 Tage
- Release: Squeeze aktiv UND Bandbreite heute > gestern × 1.05 (5% Expansion)

Christian unterscheidet bewusst zwischen "Squeeze aktiv" (kein Score) und "Squeeze releasing" (+12 Punkte). Squeeze ohne Release ist Rauschen; erst die Expansion signalisiert den Breakout.

**Was wir lernen:** Unsere bestehende BB-Squeeze-Erkennung prüft nur ob Squeeze aktiv ist. Die 5%-Expansions-Schwelle für "releasing" fehlt. Kleiner aber wichtiger Unterschied.

### 2.5 3-Bar Play

`three_bar_play()` ist ein Candlestick-Muster mit fünf Bedingungen:

1. Alle 3 Kerzen bullisch (Close > Open)
2. Jede Kerze schliesst höher als die vorherige
3. Jeder Close in oberer Hälfte der Tagesrange
4. Steigendes Volumen über alle 3 Bars
5. Kein langer oberer Docht (Wick ≤ 50% des Body)

Prüft die letzten 3 Kerzen plus Offset 1-2 Tage (falls Pattern 1-2 Tage alt).

**Was wir lernen:** Kompaktes, handwerklich sauberes Pattern. OptionPlay hat keinen Candlestick-Analyzer. Relativ einfach zu implementieren. Guter Kandidat für E.2b.3 (Tech Score).

### 2.6 Golden Pocket mit Confluence-Filter

Christians wichtigste Einsicht: **Golden Pocket standalone ist unzuverlässig.** Er vergibt nur Punkte wenn mindestens 2 von 3 Confluence-Signalen bestätigen:

- (A) RSI erholt sich (Cross >50 oder bullische Divergenz oder RSI 40-55)
- (B) RRG nicht LAGGING (kein fallendes Messer)
- (C) Volumen steigt (RVOL ≥ 1.2)

Mit 2 Confluence: +7 Punkte. Mit 3 Confluence: +10 Punkte. Ohne: 0 Punkte.

**Was wir lernen:** Fibonacci-basierte Signale nur mit Multi-Faktor-Bestätigung verwenden. Deckt sich mit der Research-Literatur.

### 2.7 Inside Bar + NR7 Kombi

`inside_bar_nr7()` erkennt:
- **Inside Bar**: heutiges High ≤ gestriges High UND heutiges Low ≥ gestriges Low
- **NR7**: heutige Range ist die niedrigste der letzten 7 Tage

Einzeln: 0 oder 1 Punkt (NR7) oder 0.7 (Inside Bar). Kombiniert: 1.5 Punkte im Tech Score + 10 im Fast Score. Die Kombi signalisiert extreme Energie-Kompression.

**Was wir lernen:** Inside Bar allein und NR7 allein wurden explizit aus dem Signal-Set entfernt. Nur die Kombination ist signifikant genug. Das ist eine bewusste Designentscheidung.

---

## 3. Das Zusammenspiel: Breakout-Environment-Check

Christian prüft Breakout-Signale nicht isoliert. Drei Ebenen validieren das Umfeld:

### 3.1 Market Regime (5-Signal-Composite)

`market_regime()` berechnet einen gewichteten Score aus:

| Signal | Gewicht |
|--------|---------|
| SPY Trend (SMA 20/50/200 Stack) | ×3 |
| Sektor-Breadth (% positive Sektoren) | ×2 |
| SPY Momentum (RSI + ROC 20d) | ×2 |
| VIX Regime | ×1 |
| SPY OBV-Trend | ×1 |

Regimes: BULL (≥12), BULL_WEAK (≥7), NEUTRAL (≥2), BEAR_WATCH (≥-3), BEAR (<-3), CRASH (VIX≥35).

Breakout-Trades in NEUTRAL oder schlechter bekommen einen erhöhten MIN_SCORE (+8 bis +20 Punkte), was automatisch nur die stärksten Breakout-Setups durchlässt.

### 3.2 Post-Crash-Modus

Bei Stress-Score ≥ 4 dreht das System die Gewichtung:

```
Normal:     Classic 70% / Fast 30%
Post-Crash: Classic 30% / Fast 70%
```

Das heisst: nach einem Crash werden Breakout-/Momentum-Signale noch stärker gewichtet. Logisch, weil die schnellsten Erholungen die besten Bull-Put-Setups liefern.

### 3.3 K.O.-Kaskade

Bevor überhaupt ein Breakout-Score berechnet wird, durchläuft jeder Kandidat sechs K.O.-Filter in `phase2_score_only()`:

1. History < 55 Tage → Datenmangel
2. RSI > 80 → krass überkauft (Breakout zu spät)
3. RSI 65-80 fallend nach Peak ≥ 70 → Pullback-Setup (zu riskant)
4. Intraday ≤ -4% → aktiver Crash
5. Earnings < 12 Tage → Event-Risiko
6. IV Rank < 35 → kein Credit erreichbar

**Punkt 3 ist besonders clever:** Christian erkennt, dass ein RSI der von 72 auf 66 gefallen ist kein Kaufsignal ist, sondern ein Warnsignal. OptionPlay filtert derzeit nur RSI > 80.

---

## 4. Shadow-Validierung

`shadow_analyzer.py` implementiert eine systematische Auswertung:

- **Ranking-Qualität:** Gruppiert Kandidaten nach Position (1-5, 6-10, 11-15) und misst 14-Tage-Returns
- **Signal-Impact:** Misst welche Pattern-Icons mit positiven Returns korrelieren
- **Warning-Impact:** Prüft ob Warnungen tatsächlich Performance reduzieren

Mindest-Stichproben: 10 für Reports, 15 für Trade-Outcomes, 30 für belastbare Aussagen.

**Was wir lernen:** Christians System validiert sich selbst. OptionPlay hat Shadow-Tracking (seit Paket C), aber keinen automatischen Signal-Impact-Analyzer. Das ist ein Feature für nach E.2b.

---

## 5. Konkrete Übernahme-Empfehlungen für OptionPlay

### Sofort umsetzbar (E.2b.2 und E.2b.3)

| Pattern | Aufwand | E.2b-Phase | Priorität |
|---------|---------|------------|-----------|
| PRE-BREAKOUT Phase 2 (CMF+MFI+OBV+RSI Kombi) | Klein | E.2b.2 Money Flow | HOCH |
| BB Squeeze Release (5% Expansion) | Minimal | E.2b.3 Tech Score | HOCH |
| RSI Peak-Drop K.O. (65-80, fallend nach Peak ≥70) | Klein | E.2b.1 RSI-Score | HOCH |

### Mittlerer Aufwand (E.2b.3)

| Pattern | Aufwand | E.2b-Phase | Priorität |
|---------|---------|------------|-----------|
| Bull Flag Stufe 1+2 | Mittel | E.2b.3 Tech Score | HOCH |
| VWAP Reclaim (Weekly) | Klein | E.2b.3 Tech Score | MITTEL |
| 3-Bar Play | Klein | E.2b.3 Tech Score | MITTEL |
| Golden Pocket + Confluence | Mittel | E.2b.3 Tech Score | MITTEL |

### Architektur-Lernung (E.2b.4)

| Konzept | Beschreibung |
|---------|-------------|
| Post-Crash-Gewichtungs-Flip | 70/30 → 30/70 bei Stress ≥ 4 |
| Market Regime MIN_SCORE-Anpassung | Schwaches Regime = höhere Schwelle |
| Shadow Signal-Impact Analyzer | Automatische Auswertung welche Patterns tatsächlich performen |

### Explizit NICHT übernehmen

- Parallelisierung via ThreadPoolExecutor (OptionPlay ist async)
- IBKR-direkte API-Calls (OptionPlay nutzt Marketdata.app + IBKR Bridge)
- Jade Lizard Strategie (anderer Scope)
- Die festen Score-Punkte (müssen für unser System rekalibriert werden)

---

## 6. Kern-Erkenntnis

Christians System identifiziert Pre-Breakout-Setups durch eine **vier-schichtige Validierung**:

1. **Market Regime** filtert das Gesamtumfeld (nur BULL/BULL_WEAK erlaubt volle Scans)
2. **K.O.-Kaskade** eliminiert Fallen (RSI-Peaks, Earnings, IV-Mangel)
3. **Breakout-Pattern** erkennen 9 spezifische Muster mit klarer Rangfolge
4. **Confluence-Filter** verhindern False Positives (Golden Pocket, NR7/IB einzeln)

Das wichtigste einzelne Muster ist **BREAKOUT IMMINENT**: höhere Tiefs + Volumen-Kontraktion + OBV-Divergenz in einer Bull Flag. Dieses Pattern existiert in OptionPlay nicht und sollte Priorität 1 in E.2b.3 sein.

Die zweitwichtigste Erkenntnis ist die **Wyckoff Phase 2 Erkennung** durch gleichzeitige CMF+MFI+OBV Bestätigung. Die Einzelindikatoren haben wir bereits; was fehlt ist die kombinierte Auswertung als diskretes Signal. Das passt exakt in E.2b.2.
