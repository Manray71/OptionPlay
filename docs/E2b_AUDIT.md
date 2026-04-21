# E.2b Audit — Multi-Faktor Alpha-Composite
**Stand:** 2026-04-21  
**Phase:** E.2b.0 (Audit, kein Code-Eingriff)  
**Nächste Phase:** E.2b.1 (TechnicalComposite Grundstruktur)

---

## 1. Zweck

Dieses Audit dokumentiert was in OptionPlay bereits vorhanden ist und was
fehlt, um den AlphaScorer vom einfachen RS-Ratio-Modell auf einen
Multi-Faktor-Composite nach Christians Bull-Put-Scanner umzubauen.

Ergebnis: Die Indikator-Infrastruktur ist vollständig. Die fehlenden
Teile sind klar abgrenzbar und betreffen ein neues Service-Modul
plus zwei kleine Erweiterungen in bestehenden Modulen.

---

## 2. Bestandsaufnahme

### 2.1 Indikator-Bibliothek

Alle Indikatoren sind vorhanden und nehmen den Lookback als optionalen
Parameter mit Default-Wert an. Keine hardcodierten Fenster, also direkt
für Dual-Timeframe-Berechnung nutzbar.

| Indikator | Modul | Default-Parameter |
|---|---|---|
| RSI | `src/indicators/momentum.py` | `period=14` |
| OBV | `src/indicators/momentum.py` | parameterlos |
| MFI | `src/indicators/momentum.py` | `period=14` |
| CMF | `src/indicators/momentum.py` | `period=20` |
| MACD | `src/indicators/momentum.py` | `fast=12, slow=26, signal=9` |
| ADX | `src/indicators/trend.py:50` | `period=14` |
| Bollinger Bands | `src/indicators/volatility.py` | `period=20, std=2.0` |
| ATR | `src/indicators/volatility.py` | `period=14` |
| SMA | `src/analyzers/` | parametrisiert |

Zusätzlich: `src/indicators/optimized.py` bietet numpy-Batch-Versionen
für Scanner-Performance.

### 2.2 Divergenz-Checks

Aktiv in `src/indicators/divergence.py` und integriert im
Pullback-Analyzer mit 5 Penalties:

| Check | Penalty |
|---|---|
| Price/RSI Divergenz | -2.0 |
| Price/OBV Divergenz | -1.5 |
| Price/MFI Divergenz | -1.5 |
| CMF + MACD fallend | -1.0 |
| CMF Early Warning | -1.0 |

Christians Doku nennt 7 Checks. Es fehlen:
- Momentum-Divergenz (MFI hoch, aber CMF und RSI fallend)
- Distribution Pattern (3 Indikatoren 3 Bars fallend)

Die Penalties sind weich (-1.0 bis -2.0). Christians Skala ist
aggressiver: -6 (single) / -12 (double) / -20 (severe) auf
Composite-Ebene.

### 2.3 OHLCV-Datenbasis

| Metrik | Wert |
|---|---|
| Symbole | 381 |
| Bars gesamt | 464.000 |
| Zeitraum | 2021-01-04 bis 2026-04-17 |
| Bars pro Symbol | ~1328 (≈5 Jahre) |
| Schema | `open, high, low, close, volume` |

5 Jahre reichen für Seasonality (Monthly Return Pattern). Für
20d-Fast und 125d-Classic RRG-Fenster sind die Daten überdimensioniert.

### 2.4 Alpha-Scorer (aktueller Stand)

`src/services/alpha_scorer.py:91`

```python
raw = rs.b_raw + self._fast_weight * rs.f_raw
# B_raw = rs_ratio_slow - 100  (100d EMA-basiert)
# F_raw = rs_ratio_fast - 100  (20d)
```

- Formel B + 1.5 × F ist bereits implementiert.
- B und F stammen aus dem Dual-Window RS-Ratio (nur Relative Strength).
- Percentile-Rank über alle Symbole liefert die Longlist.
- Pipeline-Helper `get_alpha_filtered_symbols()` mit Feature-Flag
  `alpha_engine_enabled`.

### 2.5 Sector RS Service

`src/services/sector_rs.py` liefert `SectorRS` Dataclass mit:

- `rs_ratio`, `rs_momentum`, `quadrant` (Slow-Window)
- `rs_ratio_fast`, `rs_momentum_fast`, `quadrant_fast`
- Trail-Daten für Web-Visualisierung

Die beiden Quadranten sind damit verfügbar. Was fehlt ist die
Kombinations-Matrix (Classic × Fast → Score-Bonus). Die wird erst
in E.2b.1 als Service-Funktion oder YAML-Lookup angelegt.

### 2.6 Earnings Surprise API

`src/services/earnings_quality.py`

- `get_earnings_surprise_modifier()` liefert `EarningsSurpriseResult`
- Additive Modifier-Skala (externalisiert in `config/scoring.yaml`):

| Pattern | Modifier |
|---|---|
| All beats (4/4) | +1.2 |
| Mostly beats (3/4) | +0.6 |
| Mixed | 0.0 |
| Mostly misses (≥2 miss) | -1.0 |
| Many misses (3/4 miss) | -1.8 |
| All misses (0/4) | -2.8 |

Fallback: wenn `< min_quarters` Daten → `0.0`.

Christians Skala ist stärker: +12 bis -28. Einfluss-Analyse siehe
Abschnitt 4.

### 2.7 DB-Schema

| Tabelle | Spalten (relevante) |
|---|---|
| `daily_prices` | symbol, quote_date, open, high, low, close, volume |
| `earnings_history` | eps_actual, estimate, surprise, surprise_pct |

Beide Tabellen reichen für alle E.2b-Komponenten (Seasonality aus
daily_prices, Earnings-Pattern aus earnings_history).

---

## 3. Gap-Analyse pro Phase

### E.2b.1 — Grundstruktur (Quadrant-Matrix + RSI)

**Neu:** `src/services/technical_composite.py` mit `CompositeScore`
Dataclass und `TechnicalComposite` Klasse. YAML-Sektion
`alpha_composite` in `config/trading.yaml`. Quadrant-Kombinations-Matrix
(vollständige 4x4) in YAML.

**Nicht neu:** RSI existiert parametrisiert. Dual-Quadrant kommt aus
SectorRS.

**Risiko:** Keines. Skelett-Phase.

### E.2b.2 — Money Flow + Divergenz

**Neu:** 2 fehlende Divergenz-Checks in `src/indicators/divergence.py`
(Momentum-Divergenz, Distribution Pattern). Composite-Penalty-Skala
(-6/-12/-20) in neuem Composite-Kontext. Money Flow Composite als
gewichtete Kombination von OBV/MFI/CMF-Scores.

**Nicht neu:** OBV, MFI, CMF sind alle da. 5 bestehende Divergenz-Checks
bleiben in der Pullback-Logik unverändert.

**Risiko:** Divergenz-Doppelanwendung. Siehe Architektur-Entscheidung 1.

### E.2b.3 — Tech Score + Earnings + Seasonality

**Neu:** Seasonality-Berechnung (Monthly Return Pattern aus
daily_prices, 3-5 Jahre Aggregation). Earnings-Skala-Konfiguration für
Composite-Nutzung (Christians +12/-28). Tech-Score-Funktion
(SMA-Alignment + Bollinger-Position + ADX-Score).

**Nicht neu:** ADX existiert. SMA-Logik teilweise in Analyzern, muss
extrahiert werden. Earnings-API liefert bereits
`EarningsSurpriseResult`.

**Risiko:** Earnings-Skala-Einfluss. Siehe Architektur-Entscheidung 2.

### E.2b.4 — AlphaScorer-Umbau + Post-Crash

**Neu:** AlphaScorer nutzt TechnicalComposite statt RS-Ratio. VIX-Check
für Post-Crash-Modus (70/30 → 30/70 Gewichtsumkehr). Batch-Optimierung
(OHLCV einmal laden, slicen). Neuer Feature-Flag
`alpha_composite.enabled` innerhalb der Alpha-Engine.

**Nicht neu:** Feature-Flag-Infrastruktur (`alpha_engine_enabled`
existiert, zweite Ebene drunter einziehen). Percentile-Rank-Logik.
VIX-Service ist da.

**Risiko:** Regression auf Pipeline (E.3). Siehe
Architektur-Entscheidung 3.

### E.2b.5 — Verifikation + Kalibrierung

**Neu:** 20-Symbol-Smoke-Test. Score-Range-Analyse. Gewichts-Tuning
wenn nötig. `docs/E2b_RESULT.md`.

**Risiko:** Keines, reine Messung.

---

## 4. Architektur-Entscheidungen

### Entscheidung 1: Divergenz-Checks in zwei Ebenen getrennt halten

Die 5 bestehenden Divergenz-Checks bleiben im Pullback-Analyzer mit
ihren weichen Penalties (-1.0 bis -2.0). Der Pullback-Analyzer behält
seine Score-Semantik unverändert.

Der neue TechnicalComposite nutzt alle 7 Checks (5 bestehende + 2 neue)
mit Christians aggressiver Skala (-6/-12/-20). Die Skala wirkt auf
Composite-Ebene, nicht auf Pullback-Score.

Keine Verdopplung, weil der Composite ein paralleler Score ist, der den
Pullback-Score nicht ersetzt.

### Entscheidung 2: Earnings-Skala kontextabhängig

Die aktuelle Skala (+1.2/-2.8) bleibt für den Pullback/Bounce-Analyzer
erhalten. In der Composite-Nutzung kommt Christians Skala (+12/-28) zum
Einsatz. Beide Skalen sind YAML-konfigurierbar.

Einfluss-Rechnung:

- Aktuell: ±2.8 auf Pullback-Score ~0-100 → 1-3% Einfluss
- Christians: ±28 auf Composite-Range ~200-350 → 4-9% Einfluss

Faktor 2-3x stärker im Einfluss, nicht 10x wie der nominale Faktor
suggeriert.

Die finale Kalibrierung passiert in E.2b.5. Wenn der Composite kleinere
Range hat als Christians, Skala reduzieren.

### Entscheidung 3: Zwei-Ebenen Feature-Flag

`alpha_engine_enabled` (bestehend) steuert ob überhaupt Alpha-Engine
läuft.

`alpha_composite.enabled` (neu in E.2b.4) steuert ob der Scorer die
alte RS-only-Formel oder den neuen Composite nutzt. Default: true nach
Verifikation in E.2b.5.

Rollback bei Regression: Flag auf false setzen, alte Berechnung läuft
unverändert. Kein Revert notwendig.

### Entscheidung 4: Quadrant-Kombinations-Matrix in YAML

Die 4x4-Matrix lebt in `config/trading.yaml` unter
`alpha_composite.quadrant_scores`. Lookup via
`f"{classic_quad}_{fast_quad}"` Key. Kein hardcodiertes Dict im Code.

Plan listet 16 von 16 Kombinationen. Die Matrix ist damit vollständig.

---

## 5. Revidierte Aufwands-Schätzung

Alle Phasen bleiben bei "1 Session". Qualitativ angepasst auf Basis der
Audit-Befunde:

| Phase | Aufwand | Warum |
|---|---|---|
| E.2b.1 | Klein | Skelett + RSI, Indikatoren bereits parametrisiert |
| E.2b.2 | Mittel | 2 neue Divergenz-Checks + Skala-Umstellung im Composite |
| E.2b.3 | Mittel-groß | Seasonality ist neue DB-Aggregation, ~50-80 LOC |
| E.2b.4 | Mittel | Feature-Flag-Umbau + Batch-Optimierung + Post-Crash |
| E.2b.5 | Klein | Messung, Vergleich, Result.md |

Gesamt: 5 Code-Chat-Sessions, jeweils mit Branch-Commit und Result.md.

---

## 6. Offene Fragen für E.2b.1

Diese Punkte werden im ersten Code-Chat entschieden oder durch kurze
Recherche geklärt:

**F1:** Bekommt der TechnicalComposite die OHLCV-Daten direkt aus der
DB oder über einen bestehenden Cache-Service? Hintergrund:
Batch-Performance bei 381 Symbolen × 2 Fenster = 762 Indikator-Läufe
pro Scan.

**F2:** Sollen die 2 fehlenden Divergenz-Checks in E.2b.2 als neue
Funktionen in `divergence.py` oder als separates Modul
(`divergence_extended.py`)? Empfehlung: in `divergence.py`, mit Flag
ob sie im Pullback oder nur im Composite genutzt werden.

**F3:** Seasonality-Fenster. Christians Doku ist dazu dünn. Vorschlag:
durchschnittliche Monatsrendite der letzten 5 Jahre, aktuellen Monat
herausrechnen, Score ∈ [-5, +5] je nach historischer Monatsperformance.
In E.2b.3 final festlegen.

**F4:** Post-Crash-Erkennung. Nutzt der bestehende VIX-Service das
5-Tage-Peak-Kriterium (VIX > 25 in letzten 5 Tagen)? Kurz prüfen in
E.2b.4.

---

## 7. Branch-Strategie

```
main
 └─ feature/e2b-alpha-composite  (Feature-Branch für alle E.2b-Phasen)
      ├─ E.2b.1 Commit
      ├─ E.2b.2 Commit
      ├─ E.2b.3 Commit
      ├─ E.2b.4 Commit
      └─ E.2b.5 Commit + PR-Merge nach main
```

Jeder Phase-Commit läuft durch CI vor Start der nächsten Phase.
Merge auf main erst nach E.2b.5 mit grünen Tests und E2b_RESULT.md.

---

## 8. Zusammenfassung

| Kategorie | Status |
|---|---|
| Indikatoren | Vollständig, parametrisiert, numpy-optimiert |
| Daten (OHLCV, Earnings) | Vollständig, Schema deckt alles ab |
| Dual-Window RS | Vorhanden (aus E.1) |
| Alpha-Scorer Skelett | B + 1.5×F Formel bereits da |
| Feature-Flag | `alpha_engine_enabled` bestehend, zweite Ebene neu |
| Divergenz-Checks | 5 von 7 vorhanden, 2 neue in E.2b.2 |
| Earnings-API | Vorhanden, Skala kontextabhängig anzupassen |
| Seasonality | Neu in E.2b.3 |
| TechnicalComposite | Komplett neu, Hauptarbeit von E.2b |
| Quadrant-Kombi-Matrix | YAML-Konfiguration in E.2b.1 |

Die Arbeit konzentriert sich auf ein neues Service-Modul plus
Kalibrierung. Bestehende Pipeline (E.3), Pullback-Analyzer und
Risk-Stufe bleiben unberührt.

---

*Ende Audit. Nächster Schritt: Code-Chat für E.2b.1 mit diesem
Dokument, BRIEFING_PAKET_E.md und PLAN_E2b_MULTI_FAKTOR_COMPOSITE.md
als Kontext.*
