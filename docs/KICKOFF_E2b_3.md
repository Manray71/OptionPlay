# E.2b.3 — Breakout-Patterns + Tech Score + Earnings + Seasonality
**Kontext:** E.2b.2 abgeschlossen auf `feature/e2b-alpha-composite`.
Referenz-Code: `docs/reference/christian_patterns.py` (10 Funktionen, getestet)
Plan: `docs/PLAN_E2b_MULTI_FAKTOR_COMPOSITE.md` (v2, Sektion 3 Phase E.2b.3)

---

## Aufgabe

TechnicalComposite um vier Blöcke erweitern:
1. **Tech Score** (SMA-Alignment + ADX)
2. **6 Breakout-Patterns** (Bull Flag, BB Squeeze Release, VWAP Reclaim,
   3-Bar Play, Golden Pocket+, NR7+Inside Bar)
3. **Earnings Score** auf Christians Skala (+12/-28)
4. **Seasonality Score** aus historischen Monatsdaten

Die Breakout-Patterns werden als `breakout_score` zusammengefasst,
nicht als Einzelfelder. Christians `docs/reference/christian_patterns.py`
enthält die exakten Algorithmen als Referenz.

---

## Branch

```bash
cd ~/OptionPlay
git checkout feature/e2b-alpha-composite
git pull origin feature/e2b-alpha-composite
```

---

## Scope E.2b.3

### 1. Tech Score

Bewertet die technische Trendstruktur. Drei Komponenten:

**a) SMA-Alignment (max +3.0):**

```python
score = 0.0
if close > sma20:  score += 0.5
if close > sma50:  score += 0.8
if close > sma200: score += 1.0
if sma20 > sma50:  score += 0.4  # bullisches Alignment
if sma50 > sma200: score += 0.3  # Golden Cross Umfeld
# Negativer Fall:
if close < sma50 and close < sma200:
    score -= 1.5  # klarer Downtrend
```

SMA-Berechnung: `src/indicators/trend.py` oder einfacher Durchschnitt.
Braucht mindestens 200 Bars für SMA200, Fallback auf SMA50 wenn < 200.

**b) ADX Trend-Stärke (max +1.0):**

Bestehend: `src/indicators/trend.py:calculate_adx()`

```python
if adx >= 30: score += 1.0   # starker Trend
elif adx >= 20: score += 0.5  # moderater Trend
elif adx < 15: score -= 0.3   # kein Trend (Range-Markt)
```

**c) RSI Peak-Drop K.O. (Penalty):**

Aus Christians K.O.-Kaskade (scanner.py L350-380). Nicht als
harter K.O. sondern als Score-Penalty im Composite:

```python
# RSI der letzten 10 Tage
rsi_now = rsi_series[-1]
rsi_peak_10d = max(rsi_series[-10:])
rsi_drop = rsi_peak_10d - rsi_now

if rsi_now >= 65 and rsi_peak_10d >= 70 and rsi_drop >= 5:
    score -= 2.0  # Momentum-Peak vorbei, gefährlich
```

**Gesamt Tech Score:** `_tech_score()` → float, Range ca. -3.5 bis +4.0

Implementation: `TechnicalComposite._tech_score(closes, highs, lows,
volumes) -> float`

### 2. Breakout-Patterns (6 Pattern-Detektoren)

Jedes Pattern liefert ein Tuple `(detected: bool, score: float,
signal: str)`. Die Patterns werden in einer `_breakout_score()` Methode
zusammengefasst.

**Referenz-Code:** `docs/reference/christian_patterns.py` enthält alle
Algorithmen. Die Logik und Schwellwerte übernehmen, an OptionPlays
Datenstrukturen anpassen (Listen statt numpy, sync statt async).

| Pattern | Funktion | Score wenn erkannt | Referenz |
|---------|----------|-------------------|----------|
| Bull Flag Stufe 2 (BREAKOUT IMMINENT) | `_detect_bull_flag()` | +5.0 | christian_patterns.py:bull_flag_analysis |
| Bull Flag Stufe 1 | (gleiche Funktion) | +2.5 | |
| BB Squeeze Release | `_detect_bb_squeeze_release()` | +2.5 | christian_patterns.py:bollinger_squeeze |
| VWAP Reclaim | `_detect_vwap_reclaim()` | +3.0 | christian_patterns.py:weekly_vwap_reclaim |
| 3-Bar Play | `_detect_three_bar_play()` | +2.5 | christian_patterns.py:three_bar_play |
| Golden Pocket+ (≥2 Confluence) | `_detect_golden_pocket()` | +2.0 | christian_patterns.py:golden_pocket |
| NR7 + Inside Bar (nur Kombi) | `_detect_nr7_inside_bar()` | +2.0 | christian_patterns.py:inside_bar_nr7 |

**Wichtige Design-Entscheidungen:**

- Golden Pocket bekommt nur Score wenn ≥ 2 Confluence-Signale
  vorliegen (RSI erholt, RRG nicht LAGGING, RVOL ≥ 1.2).
  Da wir in `compute()` keinen RRG-Quadranten haben, nutzen wir
  stattdessen: RSI-Erholung + RVOL als Confluence. RRG kommt
  in E.2b.4 als externer Parameter dazu.

- NR7 allein und Inside Bar allein bekommen 0 Punkte. Nur die
  Kombination zählt (Christians bewusste Entscheidung).

- BB Squeeze ohne Release bekommt 0 Punkte. Nur Release zählt.

**Breakout Score Zusammenfassung:**

```python
def _breakout_score(self, closes, highs, lows, volumes, opens=None):
    total = 0.0
    signals = []
    
    bf = self._detect_bull_flag(closes, volumes, highs, lows)
    if bf["breakout_imminent"]:
        total += 5.0; signals.append("BREAKOUT IMMINENT")
    elif bf["bull_flag"]:
        total += 2.5; signals.append("Bull Flag")
    
    # ... weitere Patterns ...
    
    return total, signals
```

Die `signals` Liste wird im CompositeScore gespeichert (neues Feld).

### 3. Earnings Score

Bestehende API: `src/services/earnings_quality.py` mit
`get_earnings_surprise_modifier()`.

Christians Skala (aus YAML, bereits in E.2b.1 angelegt):

```yaml
earnings_scores:
    beats_4: 12
    beats_3: 6
    mixed: 0
    misses_2: -10
    misses_3: -18
    misses_4: -28
```

Implementation: `TechnicalComposite._earnings_score(symbol) -> float`

Nutzt den bestehenden `EarningsSurpriseResult` und mappt auf Christians
Skala. Falls das Earnings-Modul async ist, den Score als Parameter
an `compute()` übergeben statt intern abzurufen.

Alternativer Ansatz (falls einfacher): Den bestehenden Modifier
(+1.2 bis -2.8) mit Faktor 10 multiplizieren. Ergibt +12 bis -28.
Das ist mathematisch identisch mit Christians Skala.

### 4. Seasonality Score

Berechnet durchschnittliche Monatsrendite des aktuellen Monats
aus historischen Daten.

**Datenquelle:** `daily_prices` Tabelle (381 Symbole, 5 Jahre Daten).

**Algorithmus:**
```python
def _seasonality_score(self, symbol: str, month: int) -> float:
    # Aus DB: alle Monats-Returns für dieses Symbol im gegebenen Monat
    # Return pro Monat = (close_last_day / close_first_day - 1) * 100
    # Durchschnitt über alle Jahre
    # Score-Mapping:
    #   avg_return >= 3.0%:  +3.0
    #   avg_return >= 1.5%:  +1.5
    #   avg_return >= 0.5%:  +0.5
    #   avg_return >= -0.5%:  0.0
    #   avg_return >= -1.5%: -1.0
    #   avg_return < -1.5%:  -2.0
```

Christians Ansatz: statische Lookup-Matrix pro Sektor und Monat.
Unser Ansatz: symbolspezifisch aus echten Daten, weil wir 5 Jahre
OHLCV haben. Flexibler und genauer.

**DB-Query Option:**
```sql
SELECT
    strftime('%Y', quote_date) as year,
    strftime('%m', quote_date) as month,
    MIN(quote_date) as first_day,
    MAX(quote_date) as last_day
FROM daily_prices
WHERE symbol = ? AND strftime('%m', quote_date) = ?
GROUP BY year, month
```

Dann Close am first_day und last_day pro Jahr holen und Return
berechnen.

**Performance-Hinweis:** Bei 381 Symbolen pro Scan wäre ein
DB-Call pro Symbol teuer. Option A: Batch-Query für alle Symbole
auf einmal. Option B: Caching (Seasonality ändert sich nur einmal
pro Monat). Option C: Statische Matrix wie Christian. Empfehlung:
Option C für jetzt (Sektor × Monat), symbolspezifisch in E.2b.5
wenn Shadow-Daten zeigen dass es Impact hat.

Falls Option C gewählt wird, Christians statische Matrix aus
`technical.py` (SECTOR_SEASONALITY) als YAML übernehmen.

### 5. CompositeScore erweitern

```python
@dataclass(frozen=True)
class CompositeScore:
    symbol: str
    timeframe: str
    total: float
    rsi_score: float = 0.0
    money_flow_score: float = 0.0
    tech_score: float = 0.0            # NEU: berechnet
    divergence_penalty: float = 0.0
    earnings_score: float = 0.0        # NEU: berechnet
    seasonality_score: float = 0.0     # NEU: berechnet
    quadrant_combo_score: float = 0.0
    breakout_score: float = 0.0        # NEU: Summe aller Patterns
    pre_breakout: bool = False
    breakout_signals: tuple = ()       # NEU: aktive Pattern-Namen
```

`breakout_signals` als Tuple (frozen dataclass braucht immutable).

### 6. compute() vervollständigen

Nach E.2b.3 berechnet `compute()` alle Komponenten. Nur die
Integration in AlphaScorer (E.2b.4) fehlt dann noch.

```python
total = (
    rsi_sc * w["rsi"] +
    mf_sc * w["money_flow"] +
    tech_sc * w["tech"] +
    div_pen * w["divergence"] +
    earn_sc * w["earnings"] +
    seas_sc * w["seasonality"] +
    quad_sc * w["quadrant_combo"] +
    brk_sc  # Breakout-Score ungewichtet (Bonus)
)
```

Breakout-Score wird ungewichtet addiert (ist bereits kalibriert).
Alle anderen Komponenten nutzen YAML-Gewichte.

---

## Tests

`tests/unit/test_technical_composite.py` erweitern:

**Tech Score (mindestens 6 Tests):**
- Vollständiges bullisches Alignment → Score nahe Maximum
- Klarer Downtrend (unter SMA50+200) → negativer Score
- ADX > 30 → Bonus
- RSI Peak-Drop (70 → 64) → Penalty -2.0
- Zu wenig Daten für SMA200 → Fallback ohne Crash

**Breakout-Patterns (mindestens 12 Tests):**
- Bull Flag Stufe 1: Fahnenstange + Rücksetzer → detected
- Bull Flag Stufe 2: + höhere Tiefs + Vol kontrahiert → imminent
- BB Squeeze Release: Bandbreite expandiert > 5% → detected
- BB Squeeze ohne Release → nicht detected
- VWAP Reclaim: war drunter, jetzt drüber → detected
- 3-Bar Play: 3 bullische Kerzen + steigendes Vol → detected
- Golden Pocket ohne Confluence → nicht detected (Score 0)
- Golden Pocket mit RSI + RVOL Confluence → detected
- NR7 allein → nicht detected (Score 0)
- Inside Bar allein → nicht detected (Score 0)
- NR7 + Inside Bar Kombi → detected
- Keine Patterns aktiv → breakout_score == 0

**Earnings (mindestens 3 Tests):**
- 4/4 Beats → Score +12
- 4/4 Misses → Score -28
- Mixed → Score 0

**Seasonality (mindestens 3 Tests):**
- Historisch starker Monat → positiver Score
- Historisch schwacher Monat → negativer Score
- Fehlende Daten → Score 0

**Integration (mindestens 3 Tests):**
- `compute()` liefert alle Felder befüllt
- `breakout_signals` enthält aktive Pattern-Namen
- `total` reagiert auf alle Komponenten

Mindestens 27 neue Tests.

---

## Was NICHT in E.2b.3

- Integration in AlphaScorer → E.2b.4
- Post-Crash-Modus → E.2b.4
- Batch-Optimierung (381 Symbole) → E.2b.4
- Die 2 fehlenden Divergenz-Checks → geparkt
- PEAD (Post-Earnings Drift) → geparkt (braucht Earnings-Datum)
- Intraday Change → kein Intraday-Daten

---

## Akzeptanzkriterien

1. Alle 6 Breakout-Patterns erkennen sich in Testdaten
2. `tech_score` != 0 für typische OHLCV-Daten
3. `earnings_score` auf Christians Skala (+12 bis -28)
4. `seasonality_score` liefert Werte für bekannte Monate
5. `breakout_signals` Tuple enthält aktive Pattern-Namen
6. `total` reagiert auf alle 8 Komponenten (RSI, MF, Tech,
   Divergenz, Earnings, Seasonality, Quadrant, Breakout)
7. Mindestens 27 neue Tests grün
8. Gesamtsuite: 5859+ passed, 0 failed
9. `black --check` sauber
10. Kein Import von `alpha_scorer.py`
11. `docs/results/E2b_3_RESULT.md` erstellt mit LOC-Statistik

---

## Referenz-Dateien

| Datei | Zweck |
|-------|-------|
| `docs/reference/christian_patterns.py` | Algorithmen für alle 6 Patterns |
| `docs/christian/CHRISTIAN_BREAKOUT_ANALYSE.md` | Pattern-Dokumentation |
| `src/services/technical_composite.py` | Zieldatei (erweitern) |
| `src/indicators/divergence.py` | Bestehende Divergenz-Checks |
| `src/services/earnings_quality.py` | Bestehende Earnings-API |

---

## Standing Rules

- Anti-AI-Schreibstil
- Kein Auto-Trading
- Deutsche Doku, englische Code-Kommentare
- Keine Breaking Changes

---

## Commit-Flow

```bash
# Möglicherweise 2 Commits (Patterns + Earnings/Seasonality)
git add src/services/technical_composite.py
git add tests/unit/test_technical_composite.py
git commit -m "feat(e2b): add breakout patterns, tech score, earnings, seasonality"

pytest tests/unit/test_technical_composite.py -v
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
black --check src/ tests/

git push origin feature/e2b-alpha-composite

git add docs/results/E2b_3_RESULT.md
git commit -m "docs(e2b): add E.2b.3 result report"
git push origin feature/e2b-alpha-composite
```

---

## Nächste Phase

E.2b.4 — AlphaScorer-Umbau: TechnicalComposite statt RS-Ratio,
B + 1.5×F Formel mit Composite, Post-Crash-Modus (Stress-Score ≥ 4),
Batch-OHLCV-Loading, Feature-Flag `alpha_composite.enabled`.
