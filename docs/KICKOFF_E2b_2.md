# E.2b.2 — Money Flow + Divergenz + PRE-BREAKOUT
**Kontext:** E.2b.1 abgeschlossen auf `feature/e2b-alpha-composite`. 
Docs: `docs/E2b_AUDIT.md`, `docs/PLAN_E2b_MULTI_FAKTOR_COMPOSITE.md` (v2).

---

## Aufgabe

TechnicalComposite um drei Komponenten erweitern:
1. Money Flow Score (OBV + MFI + CMF gewichtet)
2. Divergenz-Penalty auf Christians Skala (-6/-12/-20)
3. PRE-BREAKOUT Phase-2-Signal (diskretes Kombi-Signal)

Alles auf dem bestehenden Branch `feature/e2b-alpha-composite`.

---

## Branch

```bash
cd ~/OptionPlay
git checkout feature/e2b-alpha-composite
git pull origin feature/e2b-alpha-composite
```

---

## Scope E.2b.2

### 1. Money Flow Score

Gewichtete Kombination dreier Indikatoren. Jeder Indikator liefert
einen Teil-Score, die werden kombiniert.

**OBV-Score (Gewicht 40%):**
Bestehende Funktion: `src/indicators/momentum.py:calculate_obv()`

Scoring-Logik:
- OBV > SMA20(OBV): +1.0 (Akkumulation)
- OBV hat SMA20 in letzten 3 Tagen gekreuzt (aufwärts): +0.5 Bonus
- OBV < SMA20(OBV): -0.5 (Distribution)
- OBV divergiert bearish von Preis (Preis steigt, OBV fällt): -1.0

SMA20 des OBV muss berechnet werden (einfacher gleitender Durchschnitt
über die letzten 20 OBV-Werte).

**MFI-Score (Gewicht 35%):**
Bestehende Funktion: `src/indicators/momentum.py:calculate_mfi()`

Scoring-Logik:
- MFI 40-60 und steigend: +1.0 (gesunder Zufluss)
- MFI > 60: +0.5 (stark, aber Vorsicht)
- MFI < 30 und steigend: +1.5 (Reversal-Signal)
- MFI > 80: -0.5 (überkauft)
- MFI < 30 und fallend: -1.0 (Abfluss)

"Steigend" = MFI heute > MFI vor 3 Tagen.

**CMF-Score (Gewicht 25%):**
Bestehende Funktion: `src/indicators/momentum.py:calculate_cmf()`

Scoring-Logik:
- CMF > 0.10 und steigend: +1.5 (starke Akkumulation)
- CMF > 0.05 und steigend: +1.0
- CMF > 0: +0.3
- CMF < -0.10: -1.5 (starke Distribution)
- CMF < -0.05: -0.8
- CMF < 0: -0.3

"Steigend" = CMF heute > CMF vor 3 Tagen.

**Kombination:**
```python
money_flow_score = (
    obv_component * 0.40 +
    mfi_component * 0.35 +
    cmf_component * 0.25
)
```

Score-Range: ca. -1.5 bis +1.5, wird in CompositeScore als
`money_flow_score` gespeichert.

### 2. Divergenz-Penalty

Bestehende Divergenz-Checks in `src/indicators/divergence.py` nutzen.
Die 5 vorhandenen Checks aufrufen und die Anzahl zählen.

**Christians Skala (für den Composite, nicht den Pullback-Analyzer):**

| Divergenz-Checks aktiv | Penalty |
|------------------------|---------|
| 1 | -6 |
| 2-3 | -12 |
| 4+ | -20 |
| 0 | 0 |

Die Schwellen kommen aus YAML (`alpha_composite.divergence_penalties`),
die in E.2b.1 bereits angelegt wurden:

```yaml
divergence_penalties:
    single: -6
    double: -12
    severe: -20
```

**Wichtig:** Der Pullback-Analyzer behält seine eigenen weichen
Penalties (-1.0 bis -2.0) unverändert. Die aggressive Skala hier
wirkt nur auf den Composite-Score.

Implementation: `TechnicalComposite._divergence_penalty(closes, highs,
lows, volumes) -> float`

### 3. PRE-BREAKOUT Phase-2-Signal

Diskretes Kombi-Signal wenn alle vier Bedingungen gleichzeitig erfüllt
sind. Aus Christians `score_technicals()` (technical.py L1914-1934):

```python
pre_breakout = (
    cmf > 0.10 and cmf_rising and
    50 <= mfi <= 65 and mfi_rising and
    obv > sma20_obv and
    50 <= rsi <= 65
)
```

Wenn `pre_breakout == True`:
- `CompositeScore.pre_breakout` = True (neues Feld)
- Score-Bonus von +20 auf den Fast Score (in E.2b.4 eingebaut)
- Für jetzt: als Flag im CompositeScore speichern

Implementation: `TechnicalComposite._pre_breakout_check(closes, highs,
lows, volumes) -> bool`

Nutzt die bereits berechneten MFI, CMF, OBV und RSI Werte aus den
anderen Methoden. Keine doppelte Berechnung.

### 4. CompositeScore erweitern

Das frozen Dataclass aus E.2b.1 um zwei Felder ergänzen:

```python
@dataclass(frozen=True)
class CompositeScore:
    symbol: str
    timeframe: str
    total: float
    rsi_score: float = 0.0
    money_flow_score: float = 0.0      # NEU: berechnet
    tech_score: float = 0.0
    divergence_penalty: float = 0.0    # NEU: berechnet
    earnings_score: float = 0.0
    seasonality_score: float = 0.0
    quadrant_combo_score: float = 0.0
    pre_breakout: bool = False         # NEU: Phase-2-Flag
```

### 5. compute() erweitern

`TechnicalComposite.compute()` berechnet jetzt RSI (E.2b.1) +
Money Flow + Divergenz + PRE-BREAKOUT. Tech, Earnings und
Seasonality bleiben als TODO(E.2b.3).

```python
async def compute(self, ...) -> CompositeScore:
    rsi_sc = self._rsi_score(closes, ...)
    quad_sc = self._quadrant_combo_score(...)
    mf_sc = self._money_flow_score(closes, highs, lows, volumes)
    div_pen = self._divergence_penalty(closes, highs, lows, volumes)
    pre_bo = self._pre_breakout_check(closes, highs, lows, volumes)
    
    total = (
        rsi_sc * weights["rsi"] +
        mf_sc * weights["money_flow"] +
        div_pen * weights["divergence"] +
        quad_sc * weights["quadrant_combo"]
    )
    
    return CompositeScore(
        symbol=symbol, timeframe=timeframe, total=total,
        rsi_score=rsi_sc, money_flow_score=mf_sc,
        divergence_penalty=div_pen,
        quadrant_combo_score=quad_sc,
        pre_breakout=pre_bo,
    )
```

### 6. Tests

`tests/unit/test_technical_composite.py` erweitern mit mindestens:

**Money Flow:**
- OBV über SMA20 → positiver Score
- MFI in Reversal-Zone (< 30, steigend) → hoher Score
- CMF negativ und fallend → negativer Score
- Alle drei zusammen bullish → Score nahe Maximum
- Zu kurze Daten (< 20 Bars) → Score 0.0

**Divergenz:**
- 0 aktive Checks → Penalty 0
- 1 aktiver Check → Penalty -6
- 3 aktive Checks → Penalty -12
- 5 aktive Checks → Penalty -20
- YAML-Werte werden korrekt gelesen

**PRE-BREAKOUT:**
- Alle 4 Bedingungen erfüllt → True
- CMF < 0.10 → False (eine Bedingung fehlt)
- RSI > 65 → False
- Zu kurze Daten → False

**Integration:**
- `compute()` liefert CompositeScore mit allen neuen Feldern != 0
- Money Flow beeinflusst total
- Divergenz-Penalty reduziert total
- pre_breakout Flag wird korrekt gesetzt

Mindestens 15 neue Tests, alle grün.

---

## Was NICHT in E.2b.2

- Tech Score (SMA-Alignment, Bollinger, ADX) → E.2b.3
- Breakout-Patterns (Bull Flag, BB Squeeze etc.) → E.2b.3
- Earnings Score → E.2b.3
- Seasonality → E.2b.3
- Integration in AlphaScorer → E.2b.4
- Die 2 fehlenden Divergenz-Checks (Momentum-Divergenz,
  Distribution Pattern) → PARKEN, existierende 5 Checks reichen
  für den Composite. Nachziehen wenn Shadow-Daten zeigen dass
  sie Impact haben.

---

## Akzeptanzkriterien

1. `money_flow_score` in CompositeScore ist != 0 für typische Daten
2. `divergence_penalty` ist negativ wenn Divergenzen vorliegen
3. `pre_breakout` ist True bei synthetischen Daten die alle 4
   Bedingungen erfüllen
4. `total` reagiert auf Money Flow und Divergenz
5. Mindestens 15 neue Tests grün
6. Gesamtsuite: 5820+ passed, 0 failed
7. `black --check` sauber
8. Kein Import von `alpha_scorer.py` (Regressions-Check)
9. `docs/results/E2b_2_RESULT.md` erstellt

---

## Standing Rules

- Anti-AI-Schreibstil: keine em-dashes, keine parallelen
  Konstruktionen, keine Puffery-Wörter
- Kein Auto-Trading, nur Score-Berechnung
- Keine Secrets in YAML oder Code
- Deutsche Doku, englische Code-Kommentare
- Keine Breaking Changes an bestehenden APIs

---

## Commit-Flow

```bash
git add src/services/technical_composite.py
git add tests/unit/test_technical_composite.py
git commit -m "feat(e2b): add money flow score, divergence penalty, pre-breakout signal"

pytest tests/unit/test_technical_composite.py -v
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
black --check src/ tests/

git push origin feature/e2b-alpha-composite

git add docs/results/E2b_2_RESULT.md
git commit -m "docs(e2b): add E.2b.2 result report"
git push origin feature/e2b-alpha-composite
```

---

## Nächste Phase

E.2b.3 — Breakout-Patterns (Bull Flag, BB Squeeze Release, VWAP
Reclaim, 3-Bar Play, Golden Pocket+, NR7+Inside Bar) + Tech Score
(SMA-Alignment) + Earnings (+12/-28) + Seasonality.
Referenz: `docs/reference/christian_patterns.py`
