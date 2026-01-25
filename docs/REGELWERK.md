# OptionPlay - Trading-Regelwerk

Dieses Dokument beschreibt die komplette Logik für das Options-Trading mit Bull-Put-Spreads.

---

## 1. Übersicht: 3-Stufen-Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  STUFE 1: SCREENING                                             │
│  ─────────────────────────────────────────────────────────────  │
│  Tool:   scan_pullback_candidates                               │
│  Input:  Watchlist (275 Symbole, 11 GICS-Sektoren)              │
│  Output: Pullback-Score (0-10) pro Symbol                       │
│                                                                 │
│  Analysiert:                                                    │
│  • RSI (Oversold-Signale)                                       │
│  • Support-Nähe                                                 │
│  • Fibonacci-Retracements                                       │
│  • Moving Average Trend                                         │
│  • Volumen-Anomalien                                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STUFE 2: FILTER & VALIDIERUNG                                  │
│  ─────────────────────────────────────────────────────────────  │
│  Tool:   filter_candidates                                      │
│  Input:  Kandidaten aus Stufe 1                                 │
│  Output: Validierte Kandidaten (10-20 Symbole)                  │
│                                                                 │
│  Prüft:                                                         │
│  • Earnings-Datum (>60 Tage)                                    │
│  • Preis-Range ($20-$500)                                       │
│  • Tagesvolumen (>500k)                                         │
│  • IV-Rank (30-80%)                                             │
│  • VIX-basierte Strategie-Auswahl                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STUFE 3: OPTIONS-ANALYSE                                       │
│  ─────────────────────────────────────────────────────────────  │
│  Tool:   fetch_options_data                                     │
│  Input:  Validierte Kandidaten                                  │
│  Output: Trade-Empfehlungen mit Strike-Preisen                  │
│                                                                 │
│  Liefert:                                                       │
│  • Options-Chain (Bid/Ask, IV, Greeks)                          │
│  • Strike-Empfehlungen (Short/Long Put)                         │
│  • Premium-Berechnung                                           │
│  • Risk/Reward-Analyse                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. VIX-Basierte Strategie-Auswahl

Der VIX (CBOE Volatility Index) bestimmt automatisch das optimale Strategy-Profil.

### VIX-Schwellenwerte

| VIX Level | Regime | Bedeutung | Empfohlenes Profil |
|-----------|--------|-----------|-------------------|
| < 15 | `low_vol` | Niedrige Volatilität | `conservative` |
| 15 - 20 | `normal` | Normale Volatilität | `standard` |
| 20 - 30 | `elevated` | Erhöhte Volatilität | `aggressive` |
| > 30 | `high_vol` | Hohe Volatilität | `high_volatility` |

### Warum VIX-basiert?

- **Niedriger VIX (< 15):** Optionsprämien sind niedrig → Konservativeres Delta (-0.20) nötig
- **Normaler VIX (15-20):** Standard-Bedingungen → Standard-Delta (-0.30)
- **Erhöhter VIX (20-30):** Prämien sind attraktiv → Aggressiveres Delta (-0.35) möglich
- **Hoher VIX (> 30):** Crash-Modus → Sehr selektiv, breite Spreads, konservatives Delta

### Profil-Parameter (aus strategies.yaml)

| Profil | VIX | Delta | Spread | Min-Score | Earnings |
|--------|-----|-------|--------|-----------|----------|
| Conservative | 0-15 | -0.20 | $2.50 | 6 | 90 Tage |
| Standard | 15-20 | -0.30 | $5.00 | 5 | 60 Tage |
| Aggressive | 20-30 | -0.35 | $5.00 | 4 | 45 Tage |
| High Vol | 30+ | -0.20 | $10.00 | 7 | 90 Tage |

---

## 3. Pullback-Scoring (Stufe 1)

### Score-Zusammensetzung (0-10 Punkte)

| Komponente | Max. Punkte | Beschreibung |
|------------|-------------|--------------|
| RSI-Signal | 3 | Oversold-Erkennung |
| Support-Nähe | 2 | Abstand zu Support-Level |
| Fibonacci | 2 | Position bei Fib-Retracement |
| MA-Trend | 2 | Dip im Aufwärtstrend |
| Volumen | 1 | Überdurchschnittliches Volumen |

### 3.1 RSI-Score (0-3 Punkte)

| RSI-Wert | Punkte | Bedeutung |
|----------|--------|-----------|
| < 30 | 3 | Extrem überverkauft |
| 30 - 40 | 2 | Überverkauft |
| 40 - 50 | 1 | Neutral-niedrig |
| ≥ 50 | 0 | Nicht überverkauft |

**Formel:** RSI mit 14-Tage-Periode (Wilder's Smoothing)

### 3.2 Support-Score (0-2 Punkte)

| Abstand zu Support | Punkte | Bedeutung |
|-------------------|--------|-----------|
| ≤ 3% | 2 | Direkt am Support |
| 3% - 5% | 1 | Nahe Support |
| > 5% | 0 | Zu weit vom Support |

**Support-Erkennung:** Swing-Lows der letzten 60 Tage, gruppiert nach Preis-Clustern

### 3.3 Fibonacci-Score (0-2 Punkte)

| Fib-Level | Toleranz | Punkte |
|-----------|----------|--------|
| 61.8% | ±2% | 2 |
| 50.0% | ±2% | 2 |
| 38.2% | ±2% | 1 |

**Berechnung:** Basierend auf 90-Tage High/Low

### 3.4 Moving Average Score (0-2 Punkte)

| Bedingung | Punkte | Bedeutung |
|-----------|--------|-----------|
| Preis > SMA200 UND Preis < SMA20 | 2 | Dip im Aufwärtstrend |
| Preis > SMA200 UND Preis > SMA20 | 0 | Kein Pullback |
| Preis < SMA200 | 0 | Kein Aufwärtstrend |

**Ideal für Bull-Put-Spreads:** Temporärer Rücksetzer in einem übergeordneten Aufwärtstrend

### 3.5 Volumen-Score (0-1 Punkt)

| Volumen vs. 20-Tage-Avg | Punkte | Bedeutung |
|------------------------|--------|-----------|
| ≥ 1.5x | 1 | Erhöhtes Interesse |
| < 1.5x | 0 | Normales Volumen |

---

## 4. Filter-Kriterien (Stufe 2)

### 4.1 Earnings-Filter ⚠️ KRITISCH

| Parameter | Wert | Begründung |
|-----------|------|------------|
| Min. Tage bis Earnings | 60 | Vermeidet IV-Crush und Gap-Risiko |

**Warum 60 Tage?**
- Bull-Put-Spreads mit 30-60 DTE
- Spread verfällt VOR Earnings
- Kein unvorhersehbares Gap-Risiko

### 4.2 Preis-Filter

| Parameter | Default | Begründung |
|-----------|---------|------------|
| Min. Preis | $20 | Keine Penny Stocks |
| Max. Preis | $500 | Kapitaleffizienz |

### 4.3 Volumen-Filter

| Parameter | Default | Begründung |
|-----------|---------|------------|
| Min. Tagesvolumen | 500.000 | Liquidität für Ein-/Ausstieg |
| Min. 20-Tage-Avg | 300.000 | Konsistente Liquidität |

### 4.4 IV-Filter

| Parameter | Default | Begründung |
|-----------|---------|------------|
| IV-Rank Min | 30% | Ausreichende Prämie |
| IV-Rank Max | 80% | Nicht zu hohes Risiko |

---

## 5. Options-Analyse (Stufe 3)

### 5.1 DTE-Auswahl (Days to Expiration)

| Parameter | Wert | Begründung |
|-----------|------|------------|
| Minimum | 30 Tage | Genug Zeit für Theta-Decay |
| Target | 45 Tage | Optimaler Sweet Spot |
| Maximum | 60 Tage | Nicht zu weit weg |

**Warum 30-60 Tage?**
- < 30: Zu viel Gamma-Risiko
- 30-45: Bester Theta-Decay für Credit Spreads
- > 60: Zu wenig Zeitverfall pro Tag

### 5.2 Delta-Targeting für Short Put

| Parameter | Wert | Bedeutung |
|-----------|------|-----------|
| Min Delta | -0.35 | Nicht zu aggressiv |
| Target | -0.30 | ~70% Gewinn-Wahrscheinlichkeit |
| Max Delta | -0.20 | Nicht zu konservativ |

**Delta-Interpretation:**
- Delta -0.30 ≈ 30% Wahrscheinlichkeit ITM bei Verfall
- Delta -0.30 ≈ 70% Wahrscheinlichkeit OTM (Gewinn)

### 5.3 Spread-Konfiguration

Die Spread-Breite wird automatisch basierend auf dem Underlying-Preis gewählt.
Diese Logik ist in `strike_recommender.py` implementiert.

| Underlying-Preis | Empfohlene Spread-Breiten | Max. Verlust (pro Kontrakt) |
|------------------|---------------------------|-----------------------------|
| < $50 | $2.50 oder $5.00 | $250 - $500 |
| $50 - $150 | $5.00 | $500 |
| $150 - $300 | $5.00 oder $10.00 | $500 - $1000 |
| > $300 | $10.00 oder $20.00 | $1000 - $2000 |

**Hinweis:** Die Strategy-Profile (`strategies.yaml`) können diese Defaults überschreiben:
- Conservative: bevorzugt $2.50 (weniger Risiko)
- Standard/Aggressive: bevorzugt $5.00 (ausgewogen)
- High Volatility: bevorzugt $10.00 (mehr Puffer bei hoher Vol)

### 5.4 Premium-Anforderungen

| Parameter | Wert | Begründung |
|-----------|------|------------|
| Min. Credit | $0.50 | Mindest-Prämie |
| Min. Credit % | 20% | Credit / Spread-Breite |
| Target % | 33% | 1/3 der Spread-Breite |

**Beispiel für $5 Spread:**
- Min. Credit: $1.00 (20%)
- Target Credit: $1.65 (33%)

### 5.5 Strike-Platzierung

**Short Put Strike:**
1. Unter stärkstem Support-Level
2. Bei Delta-Target (-0.30)
3. Mit 3-5% Sicherheitspuffer

**Long Put Strike:**
- Short Strike minus Spread-Breite
- Beispiel: Short $95, Long $90 = $5 Spread

---

## 6. Risk Management

### 6.1 Position Sizing

| Parameter | Empfehlung | Begründung |
|-----------|------------|------------|
| Max. pro Trade | 5% Portfolio | Einzelrisiko begrenzen |
| Max. pro Sektor | 20% Portfolio | Sektor-Diversifikation |
| Max. gleichzeitig | 10 Positionen | Überschaubar |

### 6.2 Exit-Regeln

| Situation | Aktion |
|-----------|--------|
| 50% Gewinn erreicht | Position schließen |
| 21 DTE erreicht | Evaluieren (Roll oder Close) |
| Underlying durchbricht Short Strike | Stop-Loss evaluieren |

---

## 7. Checkliste vor Trade-Eröffnung

```
☐ Pullback-Score ≥ 5 (oder höher je nach Profil)
☐ Earnings > 60 Tage entfernt
☐ Preis zwischen $20 und $500
☐ Tagesvolumen > 500.000
☐ IV-Rank zwischen 30% und 80%
☐ Short Strike unter Support
☐ Delta zwischen -0.20 und -0.35
☐ Credit ≥ 20% der Spread-Breite
☐ Open Interest > 100 pro Strike
☐ Bid-Ask-Spread < $0.20
☐ Keine bestehende Position im Underlying
```

---

## 8. Glossar

| Begriff | Definition |
|---------|------------|
| **Bull-Put-Spread** | Credit Spread: Short Put (höherer Strike) + Long Put (niedrigerer Strike) |
| **DTE** | Days to Expiration - Tage bis zum Verfall |
| **Delta** | Optionsgrieche: Preisänderung der Option pro $1 im Underlying |
| **IV** | Implied Volatility - vom Markt erwartete Volatilität |
| **IV-Rank** | Position der aktuellen IV im 52-Wochen-Range (0-100%) |
| **OTM** | Out of the Money - Strike außerhalb des Geldes |
| **Pullback** | Temporärer Kursrückgang in einem übergeordneten Aufwärtstrend |
| **Support** | Preisniveau mit historischer Kaufnachfrage |
| **Theta** | Zeitwertverlust der Option pro Tag |
| **VIX** | CBOE Volatility Index - "Angstbarometer" des Marktes |

---

## 9. Konfigurationsdateien

Alle Parameter sind extern konfigurierbar:

| Datei | Inhalt |
|-------|--------|
| `config/settings.yaml` | Alle technischen Parameter |
| `config/strategies.yaml` | 4 Strategy-Profile |
| `config/watchlists.yaml` | 275 Symbole in 11 Sektoren |

Änderungen an der Strategie erfordern **keinen Code-Änderungen** - nur YAML-Anpassungen.
