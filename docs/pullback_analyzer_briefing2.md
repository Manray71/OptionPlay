# Briefing: Pullback Analyzer — Literaturabgleich & Anpassungsplan

**Datum:** Februar 2026  
**Kontext:** OptionPlay System — `src/analyzers/pullback.py`  
**Basis:** Analyse der aktuellen Logik gegen Standard-Literatur (Murphy, Schwager, aktuelle TA-Ressourcen)

---

## 1. Gesamtbewertung

Der Pullback Analyzer ist konzeptionell solide und in mehreren Punkten **besser als der Literaturstandard**. Die drei Entry-Gates eliminieren die häufigsten Fehler-Signale (Momentum-Stocks, Downtrend-Rebounds, Pure-Momentum ohne Dip) proaktiv. Adaptive RSI-Schwellen und Intraday-Volumenkorrektur sind Differenzierungsmerkmale, die in den meisten kommerziellen Screenern fehlen.

Es bestehen jedoch **vier konkrete Lücken**, die mit überschaubarem Aufwand geschlossen werden können.

---

## 2. Stärken — Was die Literatur bestätigt

### Entry Gates: Korrekt und ausreichend

| Gate | Logik | Literatur-Deckung |
|------|-------|-------------------|
| RSI > 70 → Disqualifizierung | Overbought = kein Pullback, sondern Momentum | ✅ Capital.com, XS.com: RSI >70 schließt Pullback aus |
| Price < SMA200 → Disqualifizierung | Kein Uptrend, kein Pullback | ✅ Kernaussage jeder TA-Ressource |
| RSI > 50 + über SMA20 → Disqualifizierung | Kein Dip nachweisbar | ✅ Expliziter als Literatur, pragmatisch korrekt |

Die Gate-Logik verhindert die zwei häufigsten Fehler im Pullback-Trading: Einstieg in Momentum-Stocks und Einstieg in laufende Abwärtstrends.

### Scoring-Komponenten: Vollständige Abdeckung der Kernliteratur

Die Literatur nennt konsistent folgende Instrumente zur Pullback-Identifikation: Moving Averages, Fibonacci-Levels, RSI, Stochastik, MACD, Support-Levels, Volumen und Marktkontext. Alle sind im Analyzer implementiert:

- **RSI** (Component #1) — Kerninstrument laut aller Quellen ✅
- **Support-Proximity** (Component #3) — Literatur: "Bounce off support = Hauptsignal" ✅
- **Fibonacci 38.2/50/61.8%** (Component #4) — Standardreferenzpunkte ✅
- **Trend-Stärke / SMA-Alignment** (Component #5 + #6) — Uptrend-Bestätigung ✅
- **Volumen sinkend im Pullback** (Component #7) — Literatur: "Low volume = healthy correction" ✅
- **MACD-Kreuzung** (Component #8) — Trendfortsetzungs-Signal ✅
- **Stochastik** (Component #9) — Übersold-Bestätigung ✅
- **Marktkontext SPY** (Component #12) — Systematisch korrekt ✅

### Adaptive RSI-Schwellen: Überlegen gegenüber Literatur

Die Literatur nennt pauschal RSI < 30 als Pullback-Schwelle. Das bestraft stabile Bluechips (z.B. AAPL, MSFT), die normalerweise nur auf RSI 42–50 zurücksetzen und dort bereits attraktive Einstiegspunkte bieten. Die Stability-basierten Schwellen (35–50 je nach Tier) sind **methodisch fundierter** als der pauschale Literaturansatz.

### Intraday-Volumenkorrektur: Praxisrelevanter Vorteil

Die Skalierung des Teiltagsvolumens (`scale = 390 / elapsed_minutes`) verhindert das systematische Untergewichten aller Intraday-Scans. In der Literatur nicht explizit erwähnt, aber operational notwendig für jede Live-Analyse.

### Dynamische Score-Normalisierung: Konzeptionell richtig

Der Wechsel von statischem Max (27.3) zu dynamischen aktiven Komponenten löst das Problem gegenseitig exklusiver Indikatoren: Ein perfekter Pullback feuert realistisch 5–8 von 14 Komponenten. Die Floor-Regel (50% des Full Max) verhindert Inflation bei wenigen aktiven Komponenten.

---

## 3. Lücken gegenüber Literatur

### Lücke 1: Fehlende Candlestick-Bestätigung ⚠️ (hoch)

**Was die Literatur sagt:**  
Alle konsultierten Quellen nennen Reversal-Candlesticks als wichtigstes Einstiegssignal. XS.com: *"Look for hammer candlesticks, doji, or bullish engulfing at pullback levels — they show rejection of counter-trend pressure."* Capital.com verweist explizit auf Candlestick-Muster zur Bestätigung des Pullback-Endes.

**Was fehlt:**  
Der Analyzer bewertet, *ob* ein Pullback vorliegt — nicht, *ob der Pullback bereits endet*. Ohne Kerzenmuster ist unklar, ob der Einstieg zu früh erfolgt (Aktie fällt weiter) oder ob tatsächlich eine Trendumkehr beginnt.

**Relevante Muster:**
- Hammer / Inverted Hammer an Support
- Bullish Engulfing
- Doji mit unterem Schatten an Fibonacci-Level
- Morning Star

**Empfehlung:** Als Component #15 implementieren, Max Score 2.0, nur auslösen wenn gleichzeitig Support oder Fibonacci aktiv ist (Kombi-Bedingung).

---

### Lücke 2: VWAP-Gewichtung zu hoch für Swing-Trades ⚠️ (mittel)

**Was die Literatur sagt:**  
VWAP ist ein primär **intraday** genutztes Instrument (Daytrader, Market Maker Referenz). Für Swing-Trades mit 60–90 DTE findet sich in der Literatur keine Empfehlung für VWAP als zentralen Indikator.

**Aktueller Stand:**  
Component #11 (VWAP) hat Max Score 3.0 — identisch mit RSI und RSI Divergence, den stärksten Pullback-Signalen laut Literatur.

**Empfehlung:** VWAP-Gewicht von 3.0 auf 1.5 reduzieren. Die freie Gewichtung auf Support (#3) oder Fibonacci (#4) verschieben, da diese für Swing-Trades die stärkste Literatur-Unterstützung haben.

---

### Lücke 3: RSI-Wendepunkt nicht explizit bewertet ⚠️ (mittel)

**Was die Literatur sagt:**  
Capital.com: *"A pullback in an uptrend should move the RSI toward oversold (below 30). You enter when the RSI turns up from this area."* Der Fokus liegt auf dem *Drehen* des RSI, nicht nur auf dem Stand.

**Aktueller Stand:**  
Component #1 bewertet den RSI-Stand. Component #2 (RSI Divergence) erfasst bullische Divergenz (niedrigeres Preistief, höheres RSI-Tief), was verwandt ist — aber nicht identisch mit einem RSI-Hook (RSI dreht nach oben aus überverkauft).

**Empfehlung:** RSI-Hook als Sub-Kondition in Component #1 integrieren: wenn RSI in letzten 2 Tagen von Tief dreht (+2 Punkte Anstieg), Bonus-Score +0.5 innerhalb der Component.

---

### Lücke 4: Gap-Fill konzeptionell deplatziert ⚠️ (niedrig)

**Was die Literatur sagt:**  
Gap-Fill ist ein Price-Action-Szenario mit eigenem Kontext (Eröffnungsgap nach Earnings, nachträgliche Schließung). Es wird in der Pullback-Literatur nicht als Pullback-Kriterium geführt, sondern als eigenständiges Setup.

**Aktueller Stand:**  
Component #14 (Gap, Max 1.0) ist im Pullback Analyzer inkludiert. Einfluss ist klein (1.0), aber konzeptionell nicht kohärent.

**Empfehlung:** Gap-Fill aus Pullback Analyzer entfernen und als eigenständige Komponente im Bounce Analyzer oder als separates Gap-Strategy-Modul pflegen. Alternativ: Gewicht auf 0.5 reduzieren und nur bei gleichzeitigem Support-Signal aktivieren.

---

## 4. Implementierungsplan

### Priorität 1 — Candlestick Component (Component #15)

```python
# Neue Komponente in pullback_scoring.py

def score_candlestick_reversal(self, context: AnalysisContext) -> float:
    """
    Erkennt Reversal-Candlestick-Muster an relevanten Levels.
    Nur sinnvoll wenn gleichzeitig Support oder Fibonacci aktiv.
    
    Muster:
    - Hammer: unterer Schatten > 2x Körper, oberer Schatten minimal
    - Bullish Engulfing: heutiger Körper umschließt gestrigen Körper (rot→grün)
    - Doji mit unterem Schatten: Körper < 0.3% des Preises
    
    Rückgabe: 0.0 – 2.0
    """
    ...
```

**Scoring-Logik:**
- Hammer an Support-Level: 2.0
- Bullish Engulfing: 1.5
- Doji mit unterem Schatten: 1.0
- Kein Muster: 0.0

**Abhängigkeit:** Score auf 0 setzen wenn weder Support (#3) noch Fibonacci (#4) > 0 — verhindert Candlestick-Signal ohne kontextuellen Anker.

---

### Priorität 2 — VWAP-Gewicht anpassen

In `config/scoring_weights.yaml`:

```yaml
# Vorher
vwap:
  default_max: 3.0

# Nachher  
vwap:
  default_max: 1.5

# Kompensation: Support und Fibonacci aufwerten
support:
  default_max: 3.0   # vorher 2.5

fibonacci:
  default_max: 2.5   # vorher 2.0
```

**Erwarteter Effekt:** Swing-Trade-relevante Indikatoren (Support, Fib) erhalten mehr Gewicht. Intraday-VWAP verliert unverhältnismäßigen Einfluss auf 60-90 DTE Scores.

---

### Priorität 3 — RSI-Hook Sub-Kondition

In `pullback_scoring.py`, Methode `score_rsi()`:

```python
# Zusatz nach bestehender RSI-Bewertung

# RSI-Hook: dreht RSI in letzten 2 Tagen aufwärts?
if len(rsi_series) >= 3:
    rsi_delta = rsi_series[-1] - rsi_series[-3]  # 2-Tage-Anstieg
    if rsi_delta >= 2.0 and rsi_series[-1] < adaptive_threshold + 10:
        raw_score += 0.5  # Hook-Bonus (bleibt innerhalb Component-Max)
```

---

### Priorität 4 — Gap-Fill bereinigen

Option A (empfohlen): Component #14 aus `pullback.py` entfernen, `bounce_scoring.py` hinzufügen.  
Option B: Gewicht auf 0.5 reduzieren, Kondition auf `support_score > 0` beschränken.

---

## 5. Zusammenfassung der Änderungen

| Änderung | Priorität | Aufwand | Impact |
|----------|-----------|---------|--------|
| Candlestick Component #15 hinzufügen | Hoch | ~4h | Entry-Timing verbessert |
| VWAP-Gewicht 3.0 → 1.5 | Mittel | 15min | Score-Qualität für Swing-Trades |
| RSI-Hook Sub-Kondition | Mittel | 1h | Weniger Frühentries |
| Gap-Fill aus Pullback entfernen | Niedrig | 30min | Konzeptionelle Kohärenz |
| Support-Gewicht 2.5 → 3.0 | Mittel | 15min | Literatur-Alignment |
| Fibonacci-Gewicht 2.0 → 2.5 | Mittel | 15min | Literatur-Alignment |

**Gesamtaufwand:** ~6h  
**Erwartetes Ergebnis:** Höhere Präzision im Entry-Timing, weniger Frühentries in laufende Pullbacks, bessere Gewichtung für Swing-Trade-relevante Indikatoren.

---

*Erstellt auf Basis: pullback_analyzer.md (Feb 2026) + Literaturrecherche TA-Standardquellen*
