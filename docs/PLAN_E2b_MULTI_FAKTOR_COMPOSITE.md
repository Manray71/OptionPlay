# Paket E.2b — Multi-Faktor Alpha-Composite (v2)
**Stand:** 2026-04-21 | **Status:** E.2b.0 abgeschlossen, E.2b.1 Kickoff bereit
**Änderung v2:** Integration der Erkenntnisse aus Christians vollständigem Quellcode (22 Dateien, 845KB)

---

## Änderungsprotokoll v1 → v2

| Was | v1 (20. April) | v2 (21. April) |
|-----|----------------|-----------------|
| E.2b.3 Scope | SMA-Alignment + Earnings + Seasonality | Erweitert um 6 Breakout-Patterns + BB Squeeze Release + RSI Peak-Drop K.O. |
| E.2b.2 Scope | Money Flow + Divergenz | Erweitert um PRE-BREAKOUT Phase 2 Kombi-Signal |
| E.2b.4 Scope | AlphaScorer + Post-Crash | Erweitert um Stress-Score-basierte Post-Crash-Erkennung (statt simples VIX>25) |
| Paket E.6 | Push-Indikatoren als separates Paket | In E.2b.3 integriert (Code-Referenz aus Christian jetzt vorhanden) |
| Paket G (neu) | Nicht geplant | Quick-Win Exit-Verbesserungen (Gamma-Zone, RRG-Exit, Time-Stop) |
| Paket F | Optimizer nach 20+ Trades | Erweitert um Filter-Parameter-Optimizer und Shadow-Evaluator |
| Referenz | Christians Doku (Zusammenfassung) | Christians vollständiger Quellcode (22 .py Dateien, Algorithmen verifiziert) |

---

## 1. Motivation (unverändert)

Christians Bull-Put-Scanner nutzt einen Multi-Faktor-Composite-Score
auf zwei Zeitfenstern (125d Classic + 20d Fast). Sein B und F sind
Gesamtscores aus RRG-Quadrant, RSI, Money Flow, Divergenz-Checks,
Earnings Surprise, Seasonality, Breakout-Patterns und Intraday Change.

Unsere bisherige Implementierung (E.1-E.3) nutzt nur RS-Ratio für B
und F. E.2b baut den AlphaScorer zu einem echten Multi-Faktor-Composite
um.

---

## 2. Christians Architektur (verifiziert aus Quellcode)

### 2.1 Scoring-Formel (aus `technical.py:3756`)

```
final_score = bps_score + fast_score × 1.5
```

**Nicht** B + 1.5 × F auf Zeitfenster-Ebene (wie in v1 angenommen),
sondern BPS (Bull Put Spread Tauglichkeit) + Fast Close
(Breakout-Wahrscheinlichkeit) × 1.5.

BPS Score: IV Rank, Trend-Stack, RSI, Momentum, Money Flow, RS, RRG,
Sektor, Earnings, Support, Credit/ROI, Greeks, Seasonality, RVOL, ATR.
Typisch 100-300 Punkte.

Fast Score: Momentum-Profil, RVOL Spike, ROC, ADX, Breakout-Patterns
(Bull Flag, BB Squeeze, VWAP Reclaim, 3-Bar Play, etc.), Wyckoff Phase,
Golden Pocket, RSI Cross, PEAD, Intraday, RRG Fast.
Typisch 30-150 Punkte.

### 2.2 Post-Crash Modus (aus `scanner.py` + `vix.py`)

Trigger: **Stress-Score ≥ 4** (nicht einfach VIX > 25).

Stress-Score Berechnung (max 11 Punkte):

| Signal | Punkte |
|--------|--------|
| VIX > 25 | +3 |
| VIX 20-25 | +1 |
| VIX 10d-Avg > 22 | +2 |
| VIX 10d-Peak > 28 | +2 |
| SPY < SMA50 | +2 |
| Market Breadth < -0.5 | +2 |
| Market Breadth -0.3 bis -0.5 | +1 |

Stress ≥ 4 schaltet Post-Crash-Modus ein. Kein einfacher VIX-Schwellwert.

### 2.3 Breakout-Signal-Hierarchie (aus `scanner.py:SIGNAL_ICONS`)

Christians explizite Rangfolge der Breakout-Qualität, nach
Fast-Score-Punkten:

| Rang | Signal | Punkte | Algorithmus |
|------|--------|--------|-------------|
| 1 | BREAKOUT IMMINENT | +25 | Bull Flag Stufe 2: höhere Tiefs + Vol <70% + OBV↑ |
| 2 | PRE-BREAKOUT Phase 2 | +20 | CMF>0.10↑ + MFI 50-65↑ + OBV>SMA20 + RSI 50-65 |
| 3 | VWAP Reclaim | +15 | Weekly VWAP: war drunter, jetzt drüber + steigend |
| 4 | PEAD | +15 | Post-Earnings Drift 1-10 Tage, positiv |
| 5 | 3-Bar Play | +12 | 3 bullische Kerzen, steigendes Vol, kein Docht |
| 6 | BB Squeeze released | +12 | BB im 20%-Perzentil + heute >5% breiter als gestern |
| 7 | Bull Flag (Stufe 1) | +12 | Fahnenstange ≥5%, Rücksetzer ≤30%, Vol -20% |
| 8 | NR7 + Inside Bar | +10 | Niedrigste 7d-Range + Mutter-Einschluss (nur Kombi) |
| 9 | Golden Pocket+ | +7-10 | Fib 50-65% nur mit ≥2 Confluence (RSI/RRG/Vol) |

Entfernte Signale: Akkumulation Phase 1, BB Squeeze ohne Release,
NR7 allein, Inside Bar allein, >VWAP ohne Reclaim.

### 2.4 K.O.-Kaskade (aus `scanner.py:phase2_score_only`)

Bevor Scores berechnet werden:

1. History < 55 Tage → Datenmangel
2. RSI > 80 → krass überkauft
3. RSI 65-80 fallend nach 10d-Peak ≥ 70 (Drop ≥ 5) → Pullback-Falle
4. Intraday ≤ -4% → aktiver Crash
5. Earnings < 12 Tage → Event-Risiko
6. IV Rank = 0 → keine Daten
7. IV Rank < 35 → kein Credit erreichbar
8. Post-Earnings Cooldown (0-2 Tage nach Earnings)
9. Geschätzter Credit < $0.60

### 2.5 Quality-Gated Korrelation (aus `technical.py:2258`)

Keine harten Sektor-Limits. Stattdessen:

| Situation | Score ≥ 90 | Score ≥ 82 | Score < 82 |
|-----------|------------|------------|------------|
| Sektor 3× vorhanden | 50% Grösse | 35% Grösse | Abgelehnt |
| Portfolio-Korrelation > 0.65 | 50% Grösse | Abgelehnt | Abgelehnt |
| Korrelation < 0.30 | +1.0 Bonus | +1.0 Bonus | +1.0 Bonus |

---

## 3. Revidierter Phasen-Plan

### Phase E.2b.0 — Audit ✅ ABGESCHLOSSEN

Output: `docs/E2b_AUDIT.md` (337 Zeilen, auf main committet)

### Phase E.2b.1 — TechnicalComposite Grundstruktur (1 Session)

Unverändert gegenüber v1:
- CompositeScore Dataclass
- TechnicalComposite Klasse mit Skelett
- Quadrant-Kombinations-Matrix (4x4) in YAML
- RSI-Score-Funktion
- Config-Sektion in trading.yaml
- Unit-Tests

**Kickoff bereit:** `KICKOFF_E2b_1.md` erstellt.

### Phase E.2b.2 — Money Flow + Divergenz + PRE-BREAKOUT (1 Session)

**Erweitert in v2:**

Ursprünglich: OBV/MFI/CMF Score + Divergenz-Penalties.

Zusätzlich (aus Christians Code-Analyse):
- **PRE-BREAKOUT Phase 2 Signal:** Wenn CMF > 0.10 steigend UND MFI 50-65
  steigend UND OBV > SMA20 UND RSI 50-65 gleichzeitig erfüllt sind →
  diskretes Signal "Breakout in Vorbereitung". Score-Bonus +20 im Fast Score.
- **OBV Breakout Signal:** OBV × SMA20 + RSI-Bestätigung → Score-Bonus.

Begründung: Die Einzelindikatoren haben wir bereits. Die kombinierte
Auswertung als Phase-2-Signal ist der eigentliche Mehrwert.

Akzeptanzkriterium erweitert: Neben Money Flow Score und Divergenz-Penalty
muss das System ein PRE-BREAKOUT Signal ausgeben können wenn alle vier
Bedingungen erfüllt sind. Test mit synthetischen Daten.

### Phase E.2b.3 — Tech Score + Breakout-Patterns + Earnings + Seasonality (1-2 Sessions)

**Massiv erweitert in v2.** Ehemals "Paket E.6" (Push-Indikatoren) ist
jetzt hier integriert, weil Christians Quellcode die exakten Algorithmen
liefert.

**a) Tech Score (wie v1):**
- SMA-Alignment (20/50/200 Stack)
- Bollinger Position
- ADX Trend Strength

**b) Breakout-Patterns (NEU in v2, aus Christians Code):**

| Pattern | LOC-Schätzung | Referenz |
|---------|--------------|----------|
| Bull Flag Stufe 1+2 | ~100 | `technical.py:1554-1655` |
| BB Squeeze Release (5% Expansion) | ~20 | `technical.py:3102-3155` |
| VWAP Reclaim (Weekly) | ~40 | `technical.py:3350-3395` |
| 3-Bar Play | ~60 | `technical.py:3214-3275` |
| Golden Pocket + Confluence | ~60 | `technical.py:3281-3340` |
| Inside Bar + NR7 (nur Kombi) | ~30 | `technical.py:3062-3095` |

Geschätzt ~310 LOC neue Pattern-Erkennung. Christians Code dient als
direkte Referenz, nicht 1:1-Kopie (andere Datenstrukturen in OptionPlay).

**c) RSI Peak-Drop K.O. (NEU in v2):**

Aus `scanner.py:phase2_score_only`: RSI aktuell 65-80, war in letzten
10 Tagen ≥ 70, Drop ≥ 5 Punkte → K.O. (kein Trade). Verhindert
Einstieg nach Momentum-Peak. OptionPlay filtert aktuell nur RSI > 80.

**d) Earnings + Seasonality (wie v1):**
- Earnings auf Christians Skala (+12 bis -28)
- Seasonality: Monthly Return Pattern aus daily_prices

Akzeptanzkriterium: Alle 6 Breakout-Patterns erkennen sich in
synthetischen und echten OHLCV-Daten. BREAKOUT IMMINENT feuert bei
bekannten Bull-Flag-Formationen. BB Squeeze Release feuert bei
bekannten Squeeze-Ausbrüchen.

### Phase E.2b.4 — AlphaScorer Umbau + Post-Crash (1 Session)

**Erweitert in v2:**

Wie v1 plus:
- **Stress-Score-basierte Post-Crash-Erkennung** (7 Signale, gewichtet)
  statt simples VIX > 25. Schwelle: Stress ≥ 4.
- **Market Regime Composite** (5 Signale × Gewichte, aus
  `technical.py:2421`): SPY Trend ×3, Breadth ×2, Momentum ×2, VIX ×1,
  OBV ×1.

### Phase E.2b.5 — Verifikation + Kalibrierung (1 Session)

Wie v1 plus:
- Vergleich der Breakout-Signal-Erkennung gegen bekannte historische
  Setups (Bull Flag NVDA Feb 2025, BB Squeeze AAPL Jan 2026, etc.)
- Score-Range-Analyse für BPS und Fast Score getrennt
- Fast Score × 1.5 Multiplikator-Kalibrierung

---

## 4. Was NICHT in E.2b enthalten ist

| Feature | Grund | Wann stattdessen |
|---------|-------|-----------------|
| Self-Optimization Engine | Braucht 20+ geschlossene Trades | Paket F |
| Filter-Parameter-Optimizer | Braucht Scan-Effizienz-Statistik | Paket F |
| Gamma-Zone Stop (DTE<21, -30%) | Exit-Management, nicht Scoring | Paket G |
| RRG-basierter Exit | Exit-Management | Paket G |
| Time-Stop (25d bei -20%) | Exit-Management | Paket G |
| Macro-Kalender-Warnung (FOMC/CPI/NFP) | Notification, nicht Scoring | Paket G |
| Risk-Budget Portfolio (Budget-Pool statt Position-Count) | Portfolio-Management | Paket H |
| Quality-Gated Korrelation | Portfolio-Management | Paket H |
| Position-Sync mit IBKR | Infrastruktur | Paket H |
| Jade Lizard Strategie | Anderer Scope | Nicht geplant |
| Intraday Change Score | Keine Intraday-Daten | Future |
| PCR (Put/Call Ratio) | Nur über IBKR Live | Future |
| Shadow Signal-Impact Analyzer | Braucht 30+ Shadow-Evaluationen | Paket F |

---

## 5. Neue Pakete (aus Christians Code abgeleitet)

### Paket G — Quick-Win Exit-Verbesserungen

Hoher Impact, wenig Aufwand. Kann parallel zu E.2b laufen.

| Phase | Feature | Aufwand | Referenz |
|-------|---------|---------|----------|
| G.1 | Gamma-Zone Stop: DTE<21 + Verlust>30% → sofort Exit | Klein | `config.py:GAMMA_ZONE_*` |
| G.2 | Time-Stop: 25 Tage Haltedauer + Verlust>20% → Exit | Klein | `config.py:TIME_STOP_*` |
| G.3 | RRG-basierter Exit: LEADING→LAGGING = Exit-Empfehlung | Mittel | `intraday_monitor.py:530-590` |
| G.4 | Macro-Kalender: FOMC/CPI/NFP Alerts 1 Tag vorher | Klein | `intraday_monitor.py:215-240` |

### Paket H — Portfolio-Management Upgrade

| Phase | Feature | Aufwand |
|-------|---------|---------|
| H.1 | Risk-Budget-Pool statt festes Position-Count | Mittel |
| H.2 | VIX-basierte Trade-Slots (0-10/Tag nach Regime) | Klein |
| H.3 | Quality-Gated Korrelation (Score bestimmt ob 4. Sektor-Trade ok) | Mittel |
| H.4 | Position-Sync IBKR → DB (manuell geschlossene erkennen) | Mittel |

### Paket F — Optimizer (erweitert)

| Phase | Feature | Voraussetzung |
|-------|---------|---------------|
| F.1 | Shadow-Evaluator: 14d-Returns automatisch berechnen | Shadow-Tracking (Paket C) |
| F.2 | Shadow Signal-Impact: welche Patterns performen? | F.1 + 30 Evaluationen |
| F.3 | Scoring-Gewichte aus Win/Loss-Korrelation lernen | 20+ geschlossene Trades |
| F.4 | Filter-Parameter-Optimizer: Skip-Gründe → Schwellen anpassen | F.3 + Scan-Effizienz-Daten |

---

## 6. Architektur-Entscheidungen (erweitert in v2)

### Entscheidung 1-4: Unverändert aus v1

(Divergenz-Ebenen, Earnings-Skalen, Feature-Flags, YAML-Matrix)

### Entscheidung 5 (NEU): Breakout-Patterns als Fast-Score-Komponenten

Die 6 Breakout-Patterns aus E.2b.3 werden als `_fast_score`-Beiträge
im TechnicalComposite implementiert, nicht als separate Service-Klasse.
Begründung: Christians `score_fast_close()` zeigt dass die Patterns
Punktbeiträge zum Fast Score sind, nicht eigenständige Signale.

Jedes Pattern liefert:
- bool (Pattern erkannt ja/nein)
- float (Score-Beitrag)
- str (Signal-Text für Telegram/Web)

### Entscheidung 6 (NEU): Entfernte Signale bewusst nicht implementieren

Folgende Signale aus Christians Code werden bewusst NICHT übernommen:
- Akkumulation Phase 1 (zu früh, Bull Put Timing passt nicht)
- BB Squeeze ohne Release (kein Trigger)
- NR7 allein / Inside Bar allein (keine Bestätigung)
- >VWAP ohne Reclaim (Dauerzustand)

Das ist keine Lücke, sondern eine bewusste Qualitätsentscheidung die
Christian selbst getroffen hat.

### Entscheidung 7 (NEU): Golden Pocket nur mit Confluence

Golden Pocket standalone bekommt 0 Punkte. Nur mit ≥ 2 von 3
Confluence-Signalen (RSI-Erholung, RRG nicht LAGGING, RVOL ≥ 1.2)
kommen 7-10 Punkte dazu. Christians Research-Konsens bestätigt.

---

## 7. Aufwand-Revision

| Phase | v1 Aufwand | v2 Aufwand | Delta |
|-------|-----------|-----------|-------|
| E.2b.1 | 1 Session, klein | 1 Session, klein | Gleich |
| E.2b.2 | 1 Session, mittel | 1 Session, mittel | +PRE-BREAKOUT Signal, minimal |
| E.2b.3 | 1 Session, mittel-gross | 1-2 Sessions, gross | +310 LOC Breakout-Patterns |
| E.2b.4 | 1 Session, mittel | 1 Session, mittel | +Stress-Score, marginal |
| E.2b.5 | 1 Session, klein | 1 Session, klein-mittel | +Breakout-Verifikation |
| **Gesamt** | **5 Sessions** | **5-6 Sessions** | +1 mögliche Session für E.2b.3 |

Die Erweiterung von E.2b.3 ist der einzige Aufwands-Anstieg. Der
Mehrwert (6 Breakout-Patterns mit verifiziertem Code als Referenz) 
rechtfertigt die zusätzliche Session.

---

## 8. Referenz-Dokumente

| Dokument | Pfad | Inhalt |
|----------|------|--------|
| Audit | `docs/E2b_AUDIT.md` (auf main) | Bestandsaufnahme, Gaps, Architektur-Entscheidungen |
| Breakout-Analyse | `CHRISTIAN_BREAKOUT_ANALYSE.md` | 9 Pattern-Algorithmen im Detail |
| Full Code Analyse | `CHRISTIAN_FULL_CODE_ANALYSE.md` | 10 System-Learnings (Optimizer, Exits, Portfolio) |
| Christians Code | Google Drive `bull_put_scanner/` | 22 .py Dateien, 845KB |
| E.2b.1 Kickoff | `KICKOFF_E2b_1.md` | Code-Chat-Prompt für Phase 1 |

---

## 9. Versionierung

| Datum | Änderung |
|-------|---------|
| 2026-04-20 | v1: Erstversion E.2b Plan mit 5 Phasen |
| 2026-04-20 | v1.1: Erweitert um Offene Punkte, MCP-Cleanup, Restschulden |
| 2026-04-21 | v2: Integration Christians Quellcode-Analyse (Breakout-Patterns, Exit-System, Optimizer, Portfolio-Management). E.6 in E.2b.3 integriert. Neue Pakete G und H. |
