# OptionPlay Validierungsregeln

Verbindliche Regeln zur Prüfung von Trade-Kandidaten.
Quelle: `docs/PLAYBOOK.md` (einziges Regelwerk, bei Widersprüchen gilt PLAYBOOK.md)

---

## Harte Filter (GO / NO-GO)

Jeder Trade MUSS alle harten Filter bestehen. Kein Filter darf übersprungen werden.

| # | Filter | Schwelle | Bei Verletzung |
|---|--------|----------|----------------|
| 1 | **Blacklist** | Symbol nicht auf Blacklist | NO-GO, keine Ausnahme |
| 2 | **Stability Score** | ≥ 70 (≥ 80 wenn VIX > 20) | NO-GO, keine Ausnahme |
| 3 | **Earnings-Abstand** | **> 45 Tage** | NO-GO, keine Ausnahme |
| 4 | **VIX** | < 30 (> 35 = kein Trading) | NO-GO für neue Trades |
| 5 | **Preis** | $20 – $1.500 | NO-GO |
| 6 | **Tagesvolumen** | > 500.000 | NO-GO |

**Prüf-Reihenfolge:** 1 → 2 → 3 → 4 → 5 → 6 (günstigste Checks zuerst)

### Hinweise zur Prüfung

- **Blacklist zuerst prüfen.** Wenn ein Symbol auf der Blacklist steht, sofort NO-GO melden. Keine weitere Analyse nötig. (Beispiel: DAVE steht auf der Blacklist — egal was die Technicals sagen.)
- **Stability Score MUSS immer explizit geprüft und genannt werden.** Wenn der Analyzer den Stability Score nicht liefert, separat aus `symbol_fundamentals` abrufen. Niemals einen Filter überspringen, nur weil das Tool ihn nicht anzeigt.
- **Earnings-Abstand ist > 45 Tage.** Alle Tools verwenden `ENTRY_EARNINGS_MIN_DAYS = 45` als einheitlichen Default.
- **Alle 6 Filter müssen explizit im Ergebnis erscheinen.** Wenn ein Filter nicht geprüft werden konnte → als UNBEKANNT melden, nicht stillschweigend überspringen.
- **Volumen MUSS geprüft werden.** Das Analyze-Tool liefert kein Volumen. Volumen separat über Quote abrufen und gegen > 500.000 prüfen. (Beispiel: Bei JPM wurde das Volumen nicht geprüft — das ist ein unvollständiger Check.)

---

## Weiche Filter (WARNING)

| Filter | Schwelle | Bei Verletzung |
|--------|----------|----------------|
| IV Rank | 30% – 80% | WARNING — Trade möglich, Prämie prüfen |
| Open Interest | ✅ >700 (hoch) ⚠️ 100–700 (niedrig) ❌ <100 (sehr niedrig) | WARNING/REJECT — Liquiditätsrisiko |
| Bid-Ask Spread | < $0.20 | WARNING — Ausführungsrisiko |

---

## Spread-Parameter

| Parameter | Wert | Toleranz |
|-----------|------|----------|
| **DTE** | 60–90 Tage | Optimal: 75 |
| **Short Put Delta** | -0.20 | ±0.03 (-0.17 bis -0.23) |
| **Long Put Delta** | -0.05 | ±0.02 (-0.03 bis -0.07) |
| **Spread-Breite** | Dynamisch | Ergibt sich aus Delta-Differenz |
| **Min Credit** | 20% der Spread-Breite | Unter 20% = kein Trade |

**Delta ist heilig:** Delta darf NICHT verändert werden um höhere Credits zu erzielen. Wenn bei Delta -0.20 die Prämie zu niedrig ist → Symbol wechseln, nicht Delta anpassen.

---

## VIX-Regime

| VIX | Regime | Stability-Min | Max Positionen | Neue Trades |
|-----|--------|--------------|----------------|-------------|
| < 15 | LOW VOL | 70 | 10 | Ja |
| 15–20 | NORMAL | 70 | 10 | Ja |
| 20–25 | DANGER ZONE | **80** | 5 | Eingeschränkt |
| 25–30 | ELEVATED | **80** | 3 | Sehr selektiv |
| > 30 | HIGH VOL | — | 0 | Keine neuen |
| > 35 | KEIN TRADING | — | 0 | Alles schließen |

---

## Exit-Regeln

| Bedingung | Aktion |
|-----------|--------|
| 50% Profit (30% bei VIX ≥ 20) | SCHLIESSEN |
| 200% des Credits verloren | SOFORT SCHLIESSEN |
| Support gebrochen | SCHLIESSEN |
| Earnings angekündigt | SOFORT SCHLIESSEN |
| 21 DTE | Entscheidung: Roll oder Close |
| 7 DTE | SOFORT SCHLIESSEN, keine Ausnahme |

---

## Position Sizing

| Parameter | Limit |
|-----------|-------|
| Max Risiko pro Trade | 2% des Portfolios |
| Max offene Positionen | 10 (VIX-abhängig, siehe oben) |
| Max pro Sektor | 2 (1 bei VIX > 20) |
| Max neue Trades pro Tag | 2 |
| Max neue Trades pro Woche | 8 |
| Max Trades pro Monat | 25 |

---

## Disziplin

| Situation | Aktion |
|-----------|--------|
| 3 Verluste in Folge | 7 Tage Pause |
| 5 Verluste im Monat | Rest des Monats pausieren |
| Portfolio -5% im Monat | Rest des Monats pausieren |

---

## Blacklist (NIEMALS traden)

ROKU, SNAP, UPST, AFRM, MRNA, RUN, MSTR, TSLA, COIN, SQ, IONQ, QBTS, RGTI, DAVE

**Regel:** Stability < 40 ODER Backtest Win Rate < 70% ODER Volatilität > 100% → Blacklist.
