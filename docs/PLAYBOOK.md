# OptionPlay PLAYBOOK

Einziges, verbindliches Regelwerk für Bull-Put-Spread Trading.
Alle anderen Dokumente verweisen hierher. Bei Widersprüchen gilt dieses Dokument.

**Letzte Aktualisierung:** 2026-04-07
**Version:** 5.0.0
**Konsolidiert aus:** REGELWERK.md, ML-Training (Jan 2026), Verlustanalyse, Backtest-Ergebnisse

---

## 1. ENTRY-REGELN

Jeder Trade muss ALLE harten Filter bestehen. Kein Filter darf übersprungen werden.

### Harte Filter (GO / NO-GO)

| Filter | Schwelle | Aktion bei Verletzung |
|--------|----------|----------------------|
| Stability Score | ≥ 70 | NO-GO für Trade Execution. Scanner zeigt Signale ab ≥50 (mit höherer Score-Hürde) |
| Earnings-Abstand | > 45 Tage | NO-GO, keine Ausnahme (siehe Earnings Pre-Filter Details unten) |
| VIX | < 30 | NO-GO für neue Trades (> 35 = kein Trading) |
| Blacklist | Symbol nicht auf Liste | NO-GO, keine Ausnahme |
| Preis | $20 – $1500 | NO-GO |
| Tagesvolumen | > 500.000 | NO-GO |

### Weiche Filter (WARNING)

| Filter | Schwelle | Aktion bei Verletzung |
|--------|----------|----------------------|
| IV Rank | 50% – 80% | WARNING — Trade möglich, aber Prämie prüfen |
| Open Interest | ✅ >700 (hoch) ⚠️ 100–700 (niedrig) ❌ <100 (sehr niedrig) | WARNING/REJECT — Liquiditätsrisiko |
| Bid-Ask Spread | < $0.20 | WARNING — Ausführungsrisiko |

### Prüf-Reihenfolge

```
1. Blacklist-Check     → sofort raus wenn gelistet
2. Stability ≥ 70     → NO-GO bei Trade Execution (Scanner: ≥50 mit Tier-System)
3. Earnings > 45 Tage → sofort raus wenn zu nah
4. VIX < 30           → sofort raus wenn ≥ 30
5. Preis $20-$1500     → sofort raus wenn außerhalb
6. Volumen > 500k     → sofort raus wenn zu dünn
7. IV Rank 50-80%     → WARNING wenn außerhalb
8. Score-Ranking       → sortieren, beste zuerst
```

Die Reihenfolge ist optimiert: günstigste Checks zuerst, teure API-Calls zuletzt.

### Earnings Pre-Filter Details

Der Scanner filtert Symbole mit Earnings innerhalb von 45 Tagen VOR dem Scan (Pre-Filter). Dies geschieht in zwei Stufen:

1. **Pre-Filter** (`_apply_earnings_prefilter`): Entfernt Symbole mit anstehenden Earnings < 45 Tage aus der Scan-Liste, BEVOR die Analyse startet. Spart Rechenzeit.
2. **Per-Symbol-Filter** (`_should_skip_for_earnings`): Prüft jedes Symbol nochmals einzeln während des Scans.

**~~Ausnahme Earnings-Dip-Strategie~~ [GELOSCHT]:** Die Earnings-Dip-Strategie wurde in v5.0.0 entfernt. Der Pre-Filter gilt nun ausnahmslos für alle Strategien.

**Wichtig:** Der 45-Tage-Abstand bezieht sich auf das nächste Earnings-Datum ab dem Scan-Zeitpunkt. Liegt das Earnings-Datum in der Vergangenheit (bereits berichtet), greift der Filter nicht.

### Dividend-Gap-Handling (E.5)

Ex-Dividend-Tage verursachen einen Kursrückgang in Höhe der Dividende. Ohne Erkennung kann dies als Pullback/Dip fehlinterpretiert werden.

**Lösung:** Der Scanner prüft vor der Analyse, ob ein Symbol nahe an einem Ex-Dividend-Datum liegt:
- `DividendHistoryManager` speichert historische Ex-Dividend-Daten (via `scripts/collect_dividends.py`)
- `AnalysisContext.is_near_ex_dividend` wird gesetzt wenn Ex-Date ±2 Tage entfernt
- `AnalysisContext.ex_dividend_amount` enthält den Dividendenbetrag
- **Pullback-Analyzer:** Wenn der beobachtete Gap dem erwarteten Dividenden-Gap entspricht (±50%), wird der Gap-Score neutralisiert
- **Heuristik-Fallback:** Ohne Dividend-Daten wird ein Gap von -1% bis -3% bei niedrigem Volumen als potentieller Dividend-Gap gewarnt

**Datenquelle:** `yfinance ticker.dividends` → `dividend_history` Tabelle in `trades.db`

---

## 2. SPREAD-PARAMETER

### Kern-Parameter

| Parameter | Wert | Toleranz |
|-----------|------|----------|
| **DTE** | 35–50 Tage | Optimal: 45 |
| **Short Put Delta** | -0.16 bis -0.20 je VIX-Profil | ±0.03 |
| **Long Put Delta** | -0.05 | ±0.02 (Bereich -0.03 bis -0.07) |
| **Spread-Breite** | Dynamisch | Ergibt sich aus Delta-Differenz |
| **Min Credit** | 10% der Spread-Breite | Unter 10% → kein Trade |

### Delta-Logik

Die Spread-Breite ist KEIN fixer Dollar-Betrag und KEIN fixer Prozentsatz. Sie ergibt sich dynamisch aus der Platzierung von Short Put (Delta -0.16 bis -0.20 je VIX-Profil) und Long Put (Delta -0.05).

**Beispiel AAPL bei $185:**
- Short Put: $175 (Delta ≈ -0.20) 
- Long Put: $165 (Delta ≈ -0.05)
- Spread-Breite: $10
- Min Credit: $1.00 (10% von $10)

**Beispiel SPY bei $480:**
- Short Put: $460 (Delta ≈ -0.20)
- Long Put: $445 (Delta ≈ -0.05)
- Spread-Breite: $15
- Min Credit: $1.50 (10% von $15)

### Delta ist heilig

Das Delta darf NICHT über -0.20 hinaus angepasst werden um höhere Credits zu erzielen. Der Bereich -0.16 bis -0.20 wird vom VIX-Profil bestimmt. Wenn die Prämie zu niedrig ist, ist das Symbol für die aktuelle Marktlage nicht geeignet. Symbol wechseln, nicht Delta anpassen.

### DTE-Auswahl

| DTE | Bewertung |
|-----|-----------|
| < 21 | ZU KURZ — Gamma-Risiko zu hoch |
| 21-34 | UNERWÜNSCHT — nur wenn 35+ nicht verfügbar |
| **35-50** | **OPTIMAL** — bester Theta-Decay bei überschaubarem Risiko |
| > 50 | ZU LANG — zu wenig Zeitverfall pro Tag |

---

## 3. VIX-REGIME

5 Stufen, basierend auf ML-Training-Ergebnissen (Jan 2026).

### Regime-Übersicht

| VIX | Regime | Stability-Min | Neue Trades | Besonderheiten |
|-----|--------|--------------|-------------|----------------|
| < 15 | **LOW VOL** | 70 | ✅ Ja | Niedrigere Prämien akzeptieren |
| 15–20 | **NORMAL** | 70 | ✅ Ja | Standard-Parameter |
| 20–25 | **DANGER ZONE** | **80** | ⚠️ Eingeschränkt | Nur Premium-Symbole |
| 25–30 | **ELEVATED** | **80** | ⚠️ Sehr selektiv | Breitere Spreads, Top-Symbole only |
| > 30 | **HIGH VOL** | — | ❌ Keine neuen Trades | Nur Bestand managen |
| > 35 | **KEIN TRADING** | — | ❌ Komplett | Alles mit Verlust-Limit schließen |

### Regime-Details

**LOW VOL (VIX < 15)**
- Standard-Parameter gelten
- Credits werden niedriger sein → akzeptieren wenn Min-Credit erfüllt
- Gute Zeit für Aufbau von Positionen

**NORMAL (VIX 15–20)**
- Ideales Umfeld für Bull-Put-Spreads
- Alle Standard-Parameter wie definiert
- Volle Watchlist nutzen

**DANGER ZONE (VIX 20–25)**
- Stability-Anforderung steigt auf ≥ 80
- Nur die besten 20 Symbole (Top-Stability)
- Profit-Exit auf 30% senken (schneller raus)
- Maximale 5 offene Positionen (statt 10)

**ELEVATED (VIX 25–30)**
- Nur die Top-10 stabilsten Symbole
- Stability ≥ 80 zwingend
- Max 3 offene Positionen
- Profit-Exit auf 30%
- Keine neuen Sektoren eröffnen

**HIGH VOL (VIX > 30)**
- KEINE neuen Trades eröffnen
- Bestehende Positionen managen:
  - Gewinn-Positionen → sofort schließen
  - Verlust-Positionen → Stop-Loss beachten
  - DTE < 30 → schließen

---

## 4. EXIT-REGELN

### Gewinn-Exits

| Bedingung | Aktion | Priorität |
|-----------|--------|-----------|
| **50% Profit erreicht** | SCHLIESSEN | Standard (VIX < 20) |
| **30% Profit erreicht** | SCHLIESSEN | Bei VIX ≥ 20 |

Warum 50% und nicht mehr warten: Die Verlustanalyse zeigt, dass Trades die bei 50% geschlossen werden eine signifikant bessere Gesamtperformance liefern als Trades die bis 80-100% laufen.

### Verlust-Exits

| Bedingung | Aktion | Priorität |
|-----------|--------|-----------|
| **200% des Credits verloren** | SOFORT SCHLIESSEN | Keine Diskussion |
| **Support gebrochen** | SCHLIESSEN | Innerhalb der Sitzung |
| **Earnings angekündigt** | SOFORT SCHLIESSEN | Egal welcher P&L-Stand |

**Stop Loss Berechnung:**
- Credit erhalten: $1.50
- 200% Stop = $1.50 × 2 = $3.00 Verlust
- Spread kostet dann: $1.50 (Credit) + $3.00 (Verlust) = $4.50 zum Schließen

### Zeit-Exits

| DTE | Aktion |
|-----|--------|
| **21 DTE** | ENTSCHEIDUNG: Rollen auf neues Expiration ODER Schließen |
| **7 DTE** | SOFORT SCHLIESSEN — egal welcher Stand |

### Roll-Regeln (bei 21 DTE)

Rollen ist nur erlaubt wenn:
1. Position ist profitabel oder maximal am Break-Even
2. Das Symbol besteht noch alle Entry-Filter (Stability, Earnings, VIX)
3. Neues Expiration liegt 35-50 DTE entfernt
4. Neuer Credit ist akzeptabel (≥ 10% Spread-Breite)

Rollen ist NICHT erlaubt wenn:
- Position ist im Verlust → schließen
- Earnings fallen ins neue DTE-Fenster → schließen
- VIX ist in Danger Zone oder höher und Symbol hat Stability < 80 → schließen

---

## 5. POSITION SIZING

### Grundregeln

| Parameter | Limit |
|-----------|-------|
| **Max Risiko pro Trade** | 2% des Portfolios |
| **Max offene Positionen** | 10 (bei VIX < 20) |
| **Max Positionen pro Sektor** | 4 |
| **Max neue Trades pro Tag** | 2 |

### VIX-Adjustierung

| VIX-Regime | Max Positionen | Max pro Sektor | Risiko pro Trade |
|------------|---------------|----------------|-----------------|
| Low Vol / Normal | 10 | 2 | 2% |
| Danger Zone | 5 | 1 | 1.5% |
| Elevated | 3 | 1 | 1% |
| High Vol | 0 (keine neuen) | — | — |

### Risiko-Berechnung

```
Max Verlust pro Kontrakt = (Spread-Breite - Credit) × 100
Anzahl Kontrakte = (Portfolio × Max-Risiko%) / Max Verlust pro Kontrakt

Beispiel:
  Portfolio: $80.000
  Spread: $10 breit, Credit $2.00
  Max Verlust: ($10 - $2) × 100 = $800 pro Kontrakt
  Max Risiko 2%: $80.000 × 0.02 = $1.600
  Kontrakte: $1.600 / $800 = 2 Kontrakte
```

---

## 6. DISZIPLIN-REGELN

### Frequenz-Limits

| Regel | Limit | Begründung |
|-------|-------|------------|
| **Max Trades pro Monat** | 25 | Overtrading vermeiden |
| **Max neue Trades pro Tag** | 2 | Keine FOMO-Trades |
| **Max neue Trades pro Woche** | 8 | Gleichmäßiger Aufbau |

### Verlust-Management

| Situation | Aktion |
|-----------|--------|
| **3 Verluste in Folge** | 7 Tage Pause — kein neuer Trade |
| **5 Verluste im Monat** | Rest des Monats pausieren |
| **Portfolio -5% im Monat** | Rest des Monats pausieren |

### Vor jedem Trade

Jeder Trade braucht eine schriftliche Begründung VOR dem Entry:

```
Symbol:     ___________
Datum:      ___________
Begründung: Warum JETZT dieses Symbol?
Setup:      Welche Strategie (Pullback/Bounce)?
Stability:  ___ (≥70?)
Earnings:   ___ Tage (>45?)
VIX:        ___ (Regime: ___)
Short Put:  $___  (Delta: ___)
Long Put:   $___  (Delta: ___)
Credit:     $___  (≥10% Spread?)
Max Loss:   $___  (≤2% Portfolio?)
Profit-Ziel: 50% → $___
Stop-Loss:   200% → $___
```

### Verboten

- Trades ohne schriftliche Begründung eröffnen
- Delta anpassen um höhere Credits zu bekommen
- "Nur noch diesen einen" — wenn das Limit erreicht ist, ist es erreicht
- Earnings-Trades (IV-Crush-Risiko zu hoch)
- Nach Verlusten die Position verdoppeln
- Hoffnungs-Trades: "Wird schon wieder" ist kein Exit-Plan

---

## 7. WATCHLIST

### Primär-Watchlist: Top 20 (Stability ≥ 80)

Diese Symbole haben in Backtests die höchste Win Rate und konsistenteste Profitabilität gezeigt.

| Symbol | Stability | Backtest WR | Sektor |
|--------|-----------|-------------|--------|
| SPY | 91 | 96% | ETF / Index |
| TJX | 88 | 100% | Consumer Discretionary |
| QQQ | 87 | 94% | ETF / Index |
| JNJ | 87 | 98% | Healthcare |
| JPM | 86 | 99% | Financials |
| IWM | 85 | 96% | ETF / Index |
| UNP | 84 | 97% | Industrials |
| ADI | 84 | 98% | Technology |
| LOW | 84 | 96% | Consumer Discretionary |
| GILD | 84 | 94% | Healthcare |
| V | 84 | 96% | Financials |
| WMT | 83 | 96% | Consumer Staples |
| MSFT | 83 | 95% | Technology |
| HLT | 83 | 100% | Consumer Discretionary |
| WDAY | 82 | 100% | Technology |
| GOOGL | 82 | 93% | Communication Services |
| MRK | 82 | 97% | Healthcare |
| AAPL | 82 | 93% | Technology |
| MS | 82 | 94% | Financials |
| XOM | 81 | 97% | Energy |

**Hinweis:** Win Rates basieren auf Backtests mit DTE 45, Delta -0.20. Live-Ergebnisse können abweichen.

### Sekundär-Watchlist: Stability 70–80

Symbole mit Stability 70–80 sind für Normal- und Low-Vol-Regime geeignet. Sie werden NICHT in Danger Zone oder Elevated verwendet. Die vollständige Liste wird vom Scanner dynamisch aus der Datenbank gezogen.

### Blacklist: NIEMALS traden

| Symbol | Stability | Backtest WR | Grund |
|--------|-----------|-------------|-------|
| ROKU | 24 | 61% | Streaming-Volatilität |
| SNAP | 13 | 64% | Social Media Hype |
| UPST | 15 | 60% | Fintech-Volatilität |
| AFRM | 18 | 66% | BNPL-Risiko |
| MRNA | 30 | 64% | Biotech-Event-Risiko |
| RUN | 0 | 40% | Solar-Volatilität |
| MSTR | 37 | 58% | Bitcoin-Exposure |
| TSLA | 41 | 78% | Meme-Stock-Dynamik |
| COIN | 33 | 73% | Crypto-Korrelation |
| SQ | 36 | 68% | Fintech-Volatilität |
| IONQ | — | ~30% | Quantum, >100% Volatilität |
| QBTS | — | ~30% | Quantum, >100% Volatilität |
| RGTI | — | ~30% | Quantum, >100% Volatilität |
| DAVE | — | ~30% | Fintech, >100% Volatilität |

**Regel:** Symbole mit Stability < 40 ODER Backtest Win Rate < 70% ODER annualisierter Volatilität > 100% kommen auf die Blacklist. Kein Ermessensspielraum.

---

## Anhang A: Checkliste (Kurzform)

```
ENTRY:
  ☐ Blacklist-Check bestanden
  ☐ Stability ≥ 70 (≥80 wenn VIX > 20)
  ☐ Earnings > 45 Tage
  ☐ VIX < 30
  ☐ Preis $20-$1500, Volumen > 500k
  ☐ DTE 35-50
  ☐ Short Delta ≈ -0.16 bis -0.20 (je VIX-Profil), Long Delta ≈ -0.05
  ☐ Credit ≥ 10% Spread-Breite
  ☐ Max 2% Portfolio-Risiko
  ☐ Sektor-Limit nicht überschritten
  ☐ Begründung dokumentiert

WÄHREND DES TRADES:
  ☐ Täglicher P&L-Check
  ☐ 50% Profit → schließen (30% bei VIX > 20)
  ☐ 200% Verlust → sofort schließen
  ☐ Support-Break → schließen
  ☐ Earnings-Surprise → sofort schließen
  ☐ 21 DTE → Entscheidung: Roll oder Close
  ☐ 7 DTE → schließen, keine Ausnahme
```

---

## Anhang B: Herkunft der Regeln

| Regel | Quelle | Frühere Werte |
|-------|--------|--------------|
| DTE 35-50 | v5.0.0 Optimierung | v4: 60-90, REGELWERK: 30-60 |
| Delta -0.16 bis -0.20 | v5.0.0 VIX-Profil | v4: fix -0.20, REGELWERK: -0.30 |
| Stability ≥ 70 | ML-Training (r=0.24) | Nicht in REGELWERK vorhanden |
| Exit 50% | Verlustanalyse | TRAINING_SUMMARY hatte 100% |
| Stop Loss 200% flat | Manuelle Entscheidung | REGELWERK hatte VIX-Staffelung |
| 5 VIX-Stufen | ML-Training | REGELWERK hatte 4 Stufen |
| Danger Zone 20-25 | ML-Training | REGELWERK hatte keine Danger Zone |
| Blacklist | ML-Training + Backtests | Nicht in REGELWERK vorhanden |
| Max 25 Trades/Monat | Verlustanalyse | Nicht in REGELWERK vorhanden |
| 3 Verluste → Pause | Verlustanalyse | Nicht in REGELWERK vorhanden |

## Anhang C: Daten-Integrität

### Stock-Splits (E.7)

Historische Preisdaten via Tradier API sind **split-adjustiert** (API-Standard).
Bei Stock-Splits (z.B. NVDA 10:1) werden alle historischen Preise automatisch
angepasst. Manuelle Korrektur nicht nötig.

### Dividend-Gap Warnung (E.5)

Keine Dividenden-Datenbank vorhanden (Tradier bietet kein Dividend-Endpoint).
Der Pullback-Analyzer erkennt verdächtige Gap-Signaturen (-1% bis -3% Overnight-Gap
bei unterdurchschnittlichem Volumen) und gibt eine Warnung aus. Kein automatischer
Filter — manuelle Prüfung empfohlen.

### Survivorship Bias (E.6)

Backtests enthalten nur überlebende Unternehmen. Delisted-Symbole können via
`scripts/mark_delisted.py SYMBOL YYYY-MM-DD` markiert werden. Die BacktestEngine
filtert delisted Symbole per Default (`include_delisted=False`).
Bekannte Limitation: Manuelles Tracking, keine automatische Delist-Erkennung.

---

Dieses Dokument ersetzt REGELWERK.md vollständig. REGELWERK.md wird archiviert.
