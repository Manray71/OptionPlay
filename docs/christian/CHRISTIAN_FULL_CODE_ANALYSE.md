# Christians Bull Put Scanner — Vollständige Code-Analyse

**Scope:** 22 Python-Dateien, 845KB, systematisch gelesen
**Fokus:** Was können wir lernen, das über die Breakout-Erkennung hinausgeht?

---

## 1. Self-Optimization Engine (optimizer.py, 23KB)

Das überraschendste Modul. Christian hat eine **zweistufige Selbstoptimierung** eingebaut:

### Stufe 1: Scoring-Gewichte anpassen

Analysiert alle geschlossenen Trades (mindestens 20) und berechnet Win-Rates nach Bucketing:
- IV Rank (Buckets: <30, 30-45, 45-60, 60+)
- DTE (Buckets: <21, 21-30, 30-40, 40+)
- PCR (Buckets: <0.6, 0.6-0.8, 0.8-1.0, 1.0+)
- Momentum Score, Tech Score, Sektor, Trend
- Dual-RRG-Kombination (z.B. "IMP+LEA" = Improving Classic + Leading Fast)
- VIX-Regime (LOW/NORMAL/HIGH)

Dann passt `adapt_weights()` die Scoring-Gewichte an:
- `LEARNING_RATE = 0.3` (konservativ)
- `MAX_WEIGHT_SHIFT = 8` Punkte pro Zyklus und Parameter
- Richtung basiert auf Differenz Win-Avg vs Loss-Avg

### Stufe 2: Filter-Parameter anpassen

Noch cleverer. Analysiert **warum** Kandidaten abgelehnt wurden (Skip-Gründe) und mappt:

```python
SKIP_TO_PARAM = {
    "credit_too_low":    "MIN_CREDIT",
    "roi_too_low":       "MIN_ROI",
    "no_delta":          "MIN_IV_RANK",
    "spread_too_narrow": "MIN_SPREAD_WIDTH",
    "bid_ask_too_wide":  None,  # nicht parametrisierbar
    "no_chain":          None,  # Watchlist-Problem
}
```

Entscheidungslogik:
- **Win-Rate < 76%:** MIN_SCORE wird erhöht (festziehen, Qualität sichern)
- **Lücke > 20% UND Win-Rate ≥ 78%:** Hauptengpass-Parameter wird gelockert
- **Harte Grenzen:** MIN_IV_RANK nie unter 25 oder über 55
- **Max 1 Parameter, 1 Schritt pro Zyklus**

**Lernung für OptionPlay:** Wir haben keinen Feedback-Loop. Unser Scoring ist statisch. Ein monatlicher Optimizer-Lauf der Shadow-Trade-Ergebnisse mit Scoring-Parametern korreliert wäre ein Game-Changer. Passt als eigenständiges Paket F.

---

## 2. Drei-Schichten-Exit-System (intraday_monitor.py, 36KB)

Christian hat drei zeitlich gestaffelte Exit-Regeln:

### Schicht 1: Normaler Stop (Woche 1-3, DTE > 21)
```
CLOSE_PROFIT_PCT = 0.50   # +50% → schliessen
CLOSE_LOSS_PCT   = 1.45   # -45% → Alert (5% Puffer vor -50%)
```

### Schicht 2: Gamma-Zone Stop (Woche 3-4, DTE < 21)
```
GAMMA_ZONE_DTE      = 21   # ab hier steigt Gamma stark
GAMMA_ZONE_LOSS_PCT = 30   # nur -30% → sofort raus
```
Logik: In den letzten 3 Wochen explodiert Gamma. Ein -30% Verlust mit DTE <21 wird fast sicher -100%.

### Schicht 3: Zeitlimit-Stop (nach 25 Tagen Haltedauer)
```
TIME_STOP_DAYS     = 25    # nach 25 Tagen halten...
TIME_STOP_LOSS_PCT = 20    # ...bei >20% Verlust → Exit
```
Logik: Verhindert "Hope-Holding". Position die nach 25 Tagen noch im Minus ist, wird nicht besser.

### Zusätzliche Signal-Exits:
- **OBV-Divergenz Exit:** OBV unter SMA20 + RSI-Bestätigung → frühzeitiger Exit
- **RSI Failure Swing Exit:** Bearisher Failure Swing erkannt → sofort raus
- **Greeks Exit:** Delta weit über Entry-Delta + Vega-Risiko → Exit empfohlen
- **RRG Rotation Exit:** Stock wandert von LEADING → WEAKENING (Warnung) → LAGGING (Exit)

**Lernung für OptionPlay:** Unsere Exit-Logik ist rudimentär (50% Profit, 50% Stop). Der Gamma-Zone-Stop allein verhindert vermutlich 30% der grossen Verluste. Die RRG-basierte Exit-Empfehlung nutzt unsere Dual-RRG-Infrastruktur die bereits existiert.

---

## 3. Risk-Budget Portfolio-Management (portfolio.py, 14KB)

Christian nutzt kein festes Position-Count-Limit, sondern ein **Risikobudget:**

```
budget_total     = TARGET_POSITIONS × live_risk_per_trade
budget_available = budget_total × 0.95 - sum(open_risk)
trades_by_budget = budget_available / risk_per_trade
```

Wenn ein Trade mit reduzierter Grösse eröffnet wird (z.B. wegen Korrelation: 50% size), bleibt Budget für zusätzliche Trades. Das Portfolio füllt sich dichter als bei einem starren Positionslimit.

**VIX-basierte Trade-Slots (dynamisch):**
```
VIX < 15:   10 Slots/Tag (BULL)
VIX 15-18:  10 Slots/Tag (BULL_WEAK)
VIX 18-20:   6 Slots/Tag (NORMAL)
VIX 20-22:   3 Slots/Tag (NORMAL_LIGHT)
VIX 22-25:   2 Slots/Tag (BEAR_WATCH)
VIX > 25:    0 Slots/Tag (BEAR/CRASH)
```

**Modifier 1:** Margin > 60% → 0 Trades (Hard Stop)
**Modifier 2:** Margin 50-60% → max 3 Trades
**Modifier 3:** Portfolio-Lücke < 5 → max 2 Trades

**Lernung für OptionPlay:** Unsere Position-Sizing ist fixes €-Budget pro Trade. Der Budget-Pool-Ansatz mit dynamischen VIX-Slots wäre eine signifikante Verbesserung der Kapitaleffizienz.

---

## 4. Quality-Based Correlation Analysis (technical.py)

Christians Philosophie: **"Keine harten Limits — Qualität kann Konzentration rechtfertigen."**

Statt: "Max 2 pro Sektor, Punkt"
Christians Ansatz:
- Sektor 3× vorhanden + Score ≥ 90 → erlaubt mit 50% Grösse
- Sektor 3× vorhanden + Score ≥ 82 → erlaubt mit 35% Grösse
- Sektor 3× vorhanden + Score < 82 → abgelehnt
- Portfolio-Korrelation > 0.65 + Score ≥ 90 → erlaubt mit 50%
- Portfolio-Korrelation > 0.65 + Score < 90 → abgelehnt
- Niedrige Korrelation (< 0.30) → Diversifikationsbonus (+1.0 Score)

**Lernung für OptionPlay:** Wir haben feste Sektor-Limits. Der quality-gated Ansatz ist eleganter und verhindert, dass ein Top-Kandidat wegen eines starren Limits abgelehnt wird.

---

## 5. Macro-Kalender Warning (intraday_monitor.py)

Hardcodierte FOMC/CPI/NFP-Termine für 2026. Einen Tag vorher:

```
📅 MACRO MORGEN: FOMC
Erhöhtes Gap-Risiko für alle offenen Positionen.
Offene Spreads prüfen und ggf. reduzieren.
```

Simpel aber effektiv. OptionPlay hat keinen Macro-Kalender.

---

## 6. Jade Lizard Strategie-Auswahl (jade_lizard.py, 7.5KB)

Automatische Upgrade-Entscheidung: Wenn ein Bull-Put-Kandidat bestimmte Kriterien erfüllt, wird stattdessen ein Jade Lizard eröffnet (Bull Put + nackter Short Call):

Bedingungen:
1. IV Rank > 55 (genug Call-Prämie)
2. RRG = LEADING (stabil, kein Ausbruchsmomentum)
3. Nicht innerhalb 5% des 52W-Hochs (Call-Risiko)
4. Earnings > 30 Tage

Call-Kredit >= $0.50 als Minimum. Gesamtkredit steigt, Max-Risk sinkt.

**Lernung für OptionPlay:** Nicht für sofortige Übernahme (anderer Scope), aber die Entscheidungslogik zeigt wie man automatisch zwischen Strategien wechselt. Kann ein Vorbild für zukünftige Multi-Strategy-Erweiterung sein.

---

## 7. Shadow-Evaluierung als Feedback-Loop

Zwei Module arbeiten zusammen:

**shadow_analyzer.py:** Statistik-Reports
- Ranking-Qualität: Performen Top-5 wirklich besser als Top-11-15?
- Signal-Impact: Welche Icons korrelieren mit positiven Returns?
- Min-Stichprobe: 10 für Reports, 30 für belastbare Aussagen

**shadow_evaluator.py:** Automatische 14-Tage-Return-Berechnung
- Jeden Shadow-Candidate nach 14 Tagen neu bewerten
- Return berechnen und in DB speichern
- Wird direkt nach jedem Morning-Scan ausgeführt

**Lernung für OptionPlay:** Wir haben Shadow-Tracking (Paket C), aber keine automatische Auswertung. Der Evaluator-Job der 14d-Returns in die DB schreibt, ist Voraussetzung für den Optimizer (Punkt 1).

---

## 8. Position Sync mit IBKR (intraday_monitor.py)

Christian erkennt automatisch manuell geschlossene Positionen:

```python
ibkr_puts = ibkr.get_open_short_puts()
sync_result = db.sync_positions_with_ibkr(normalized)
if sync_result["closed"]:
    notifier.send("🔄 Position Sync: X manuell geschlossene Positionen erkannt")
```

**Lernung für OptionPlay:** Unsere IBKR-Bridge ist read-only. Position-Sync die DB-Status automatisch aktualisiert wenn der User in TWS manuell schliesst, fehlt.

---

## 9. Config-Architektur (config.py, 11KB)

Bemerkenswerte Parameter:
- `DEPOT_SIZE = 500.000 EUR` (Christians echtes Depot)
- `MAX_RISK_PCT = 0.025` (2.5% pro Trade)
- `TARGET_OPEN_POSITIONS = 32` mit `MAX = 37`
- `MAX_NEW_TRADES_PER_DAY = 6`
- 3-Phasen Scaling Roadmap in Kommentaren (2.5% → 3.0% → 3.5%)
- Account-2-Support vorbereitet (disabled)
- Alle Schwellen parametrisiert und vom Optimizer überschreibbar

**Lernung für OptionPlay:** Christians System skaliert bewusst. Die Roadmap-Kommentare zeigen wie er plant von €13k/Monat auf €19.5k/Monat zu kommen. Unsere Config ist weniger durchdacht.

---

## 10. Zusammenfassung: Prioritäten für OptionPlay

### Hoher Impact, machbar in 1-2 Sprints:
1. **Gamma-Zone-Stop** (DTE < 21, -30% statt -50%) → direkt in Intraday-Monitor
2. **RRG-basierter Exit** → nutzt existierende Dual-RRG-Infrastruktur
3. **Macro-Kalender-Warnung** → FOMC/CPI/NFP Alerts, einfach zu bauen
4. **BB Squeeze Release** (5% Expansion) → minimale Änderung an bestehendem Code

### Hoher Impact, mittlerer Aufwand:
5. **Bull Flag Stufe 1+2** → neues Pattern, ~200 Zeilen
6. **PRE-BREAKOUT Phase 2** → CMF+MFI+OBV+RSI Kombi-Signal
7. **Quality-gated Korrelation** → Umbau der Sektor-Limits
8. **Shadow-Evaluator** → 14d-Return automatisch berechnen

### Strategischer Impact, grosser Aufwand:
9. **Self-Optimization Engine** → Scoring-Gewichte aus echten Trade-Daten lernen
10. **Risk-Budget Portfolio** → Budget-Pool statt feste Position-Count
11. **Filter-Parameter-Optimizer** → Schwellen automatisch an Markt anpassen
12. **Position-Sync** → IBKR-Abgleich für DB-Konsistenz
