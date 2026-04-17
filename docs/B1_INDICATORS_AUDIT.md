# B.1 Indicators Audit

**Branch:** `verschlankung/b1-audit`
**Datum:** 2026-04-16
**Zweck:** Bestandsaufnahme vor B.1-Implementation (Divergenz-Checks). Kein Code-Eingriff.

---

## 1. Inventur `src/indicators/`

### Dateien und LOC

| Datei | LOC | Inhalt |
|-------|-----|--------|
| `__init__.py` | 81 | Re-export-Facade für alle Indikatoren |
| `momentum.py` | 509 | RSI, MACD, Stochastic, RSI-Divergenz, Swing-Punkte |
| `volatility.py` | 231 | ATR, Bollinger Bands, Keltner Channel |
| `trend.py` | 146 | SMA, EMA, ADX, Trend-Richtung |
| `support_resistance.py` | 83 | Facade → sr_core + sr_advanced |
| `sr_core.py` | 826 | Datenstrukturen, Core-Algorithmen, Hauptfunktionen |
| `sr_advanced.py` | 669 | Volume Profile, Level-Tests, Event-Analyse |
| `optimized.py` | 627 | NumPy-beschleunigte Versionen aller Indikatoren |
| `gap_analysis.py` | 622 | Gap-Erkennung, Gap-Klassifizierung, Score-Faktor |
| `volume_profile.py` | 529 | VWAP, Volume POC, SPY-Trend, Sektor-Faktor |
| `events.py` | 692 | Event-basierte Pivot-Erkennung |
| **Gesamt** | **5.015** | |

### Exportierte API (Haupt-Funktionen)

**momentum.py:**
```python
calculate_rsi(prices: List[float], period: int = 14) -> float
calculate_rsi_series(prices: List[float], period: int = 14) -> List[float]
calculate_macd(prices: List[float], fast_period=12, slow_period=26, signal_period=9) -> Optional[MACDResult]
calculate_stochastic(highs, lows, closes, k_period=14, d_period=3, smooth=3, ...) -> Optional[StochasticResult]
calculate_rsi_divergence(prices, lows, highs, rsi_period=14, lookback=50, swing_window=5,
                         min_divergence_bars=5, max_divergence_bars=30) -> Optional[RSIDivergenceResult]
find_swing_lows(values: List[float], window=5, lookback=50) -> List[Tuple[int, float]]
find_swing_highs(values: List[float], window=5, lookback=50) -> List[Tuple[int, float]]
```

**volatility.py:**
```python
calculate_atr(highs, lows, closes, period=14) -> Optional[ATRResult]
calculate_atr_simple(highs, lows, closes, period=14) -> Optional[float]
calculate_bollinger_bands(prices: List[float], period=20, num_std=2.0) -> Optional[BollingerBands]
calculate_keltner_channel(highs, lows, closes, period=20, multiplier=2.0) -> Optional[KeltnerChannelResult]
```

**trend.py:**
```python
calculate_sma(prices: List[float], period: int) -> float
calculate_ema(prices: List[float], period: int) -> List[float]
calculate_adx(highs, lows, closes, period=14) -> Optional[float]
get_trend_direction(price: float, sma_short: float, sma_long: float) -> str
```

**support_resistance.py (Facade):**
```python
find_support_levels(prices, highs, lows, volumes, lookback=60) -> List[PriceLevel]
find_resistance_levels(prices, highs, lows, volumes, lookback=60) -> List[PriceLevel]
calculate_fibonacci(high: float, low: float) -> Dict[str, float]
analyze_support_resistance(...) -> SupportResistanceResult
# + Enhanced und Event-Aware Varianten aus sr_advanced
```

**optimized.py** (NumPy, 5–10× schneller, für AnalysisContext):
```python
calc_rsi_numpy(prices, period=14) -> Optional[float]
calc_rsi_batch(prices_list, period=14) -> List[Optional[float]]
calc_sma_numpy(prices, period) -> Optional[float]
calc_sma_series(prices, period) -> np.ndarray
calc_ema_numpy(prices, period) -> Optional[float]
calc_macd_numpy(prices, fast=12, slow=26, signal=9) -> Optional[MACDResult]
calc_stochastic_numpy(highs, lows, closes, k=14, d=3, smooth=3) -> Optional[StochasticResult]
calc_atr_numpy(highs, lows, closes, period=14) -> Optional[float]
calc_fibonacci_levels(high, low) -> Dict[str, float]
find_high_low_numpy(highs, lows, lookback=60) -> Tuple[float, float]
calc_all_indicators(prices, highs, lows, closes, volumes) -> Dict[str, Any]
```

### Caller-Map (wer importiert was)

| Datei | Importiert aus indicators |
|-------|--------------------------|
| `analyzers/context.py` | optimized, support_resistance, momentum, trend, volatility, gap_analysis |
| `analyzers/bounce.py` | momentum (calculate_macd), support_resistance |
| `analyzers/pullback.py` | momentum (calculate_macd, calculate_rsi_divergence, calculate_stochastic), support_resistance, trend, volatility, volume_profile, gap_analysis |
| `analyzers/pullback_scoring.py` | gap_analysis, volatility, volume_profile |
| `analyzers/feature_scoring_mixin.py` | gap_analysis, volume_profile |
| `handlers/analysis_composed.py` | support_resistance |
| `src/__init__.py` | indicators (Re-export) |

---

## 2. Existierende Indikator-Spezies

### Vollständige Übersicht

| Indikator | Vorhanden | Datei | Signatur (Kurzform) | Lookback | Caller |
|-----------|-----------|-------|---------------------|----------|--------|
| **RSI** | Ja | `momentum.py:15` | `calculate_rsi(prices, period=14) -> float` | period+1 min | context.py, pullback.py (inline), bounce.py (inline) |
| **RSI-Serie** | Ja | `momentum.py:107` | `calculate_rsi_series(prices, period=14) -> List[float]` | period+1 min | momentum.py (intern für Divergenz) |
| **RSI-Divergenz** | Ja | `momentum.py:215` | `calculate_rsi_divergence(prices, lows, highs, ...) -> Optional[RSIDivergenceResult]` | rsi_period+lookback+swing_window | pullback.py |
| **Swing Lows/Highs** | Ja | `momentum.py:143,179` | `find_swing_lows/highs(values, window=5, lookback=50) -> List[Tuple[int,float]]` | lookback | momentum.py (intern) |
| **MACD** | Ja | `momentum.py:47` | `calculate_macd(prices, fast=12, slow=26, signal=9) -> Optional[MACDResult]` | slow+signal min | context.py, bounce.py, pullback.py |
| **Stochastic** | Ja | `momentum.py:434` | `calculate_stochastic(highs, lows, closes, k=14, d=3, smooth=3) -> Optional[StochasticResult]` | k+d+smooth min | context.py, pullback.py |
| **Bollinger Bands** | Ja | `volatility.py:56` | `calculate_bollinger_bands(prices, period=20, num_std=2.0) -> Optional[BollingerBands]` | period | bounce.py (inline, nicht via lib) |
| **ATR** | Ja | `volatility.py:15` | `calculate_atr(highs, lows, closes, period=14) -> Optional[ATRResult]` | period+1 | context.py, pullback_scoring.py |
| **Keltner Channel** | Ja | `volatility.py:125` | `calculate_keltner_channel(highs, lows, closes, period=20, multiplier=2.0)` | period | pullback_scoring.py |
| **SMA** | Ja | `trend.py:10` | `calculate_sma(prices, period) -> float` | period | context.py |
| **EMA** | Ja | `trend.py:26` | `calculate_ema(prices, period) -> List[float]` | period | context.py, pullback.py |
| **ADX** | Ja | `trend.py:50` | `calculate_adx(highs, lows, closes, period=14) -> Optional[float]` | period+1 | nicht direkt (via optimized) |
| **Support/Resistance** | Ja | `sr_core.py` / `sr_advanced.py` | `find_support_levels(prices, highs, lows, volumes, lookback=60)` | lookback | context.py, bounce.py, pullback.py |
| **Fibonacci** | Ja | `sr_core.py` | `calculate_fibonacci(high, low) -> Dict[str, float]` | — | context.py, pullback.py, handlers |
| **Gap Analysis** | Ja | `gap_analysis.py` | `analyze_gap(opens, closes, ...) -> Optional[GapResult]` | 20 Bars | context.py, pullback_scoring.py |
| **VWAP** | Ja | `volume_profile.py` | `calculate_vwap(prices, volumes) -> Optional[VWAPResult]` | alle Bars | pullback_scoring.py |
| **Volume Profile POC** | Ja | `volume_profile.py` | `calculate_volume_profile_poc(prices, volumes, bins=20)` | alle Bars | pullback_scoring.py |
| **OBV (On-Balance Volume)** | **Nein** | — | — | — | Nirgendwo in src/ implementiert |
| **MFI (Money Flow Index)** | **Nein** | — | — | — | Nirgendwo in src/ implementiert |
| **CMF (Chaikin Money Flow)** | **Nein** | — | — | — | Nirgendwo in src/ implementiert |

**Inline-Implementierungen in Analyzern (nicht via src/indicators):**

| Analyzer | Inline | Beschreibung |
|----------|--------|-------------|
| `bounce.py:1164` | RSI (Liste) | Pure Python, Wilder's Smoothing, gibt `List[float]` zurück |
| `pullback.py:887` | RSI (Skalar) | NumPy, gibt `float` zurück |
| `pullback.py:908` | SMA | NumPy `np.mean` — delegiert aber faktisch an optimized |
| `pullback.py:913` | EMA | Delegiert an `calculate_ema()` aus `indicators.trend` |
| `pullback.py:917` | MACD | Delegiert an `calculate_macd()` aus `indicators.momentum` |
| `pullback.py:925` | Stochastic | Delegiert an `calculate_stochastic()` aus `indicators.momentum` |
| `pullback.py:935` | Fibonacci | Inline-Dict-Berechnung (Duplikat zu `calculate_fibonacci`) |
| `bounce.py:429` | Bollinger Bands | Inline: `bb_middle = sum(prices[-20:])/20`, `bb_std = np.std(...)` |

---

## 3. Konventionen im aktuellen Indikator-Code

### Strukturform

Alle Indikatoren sind **pure Funktionen** (keine Klassen). Kein Zustand, keine Konstruktoren.

```python
# Typisches Muster:
def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0  # Safe default bei unzureichenden Daten
    ...
    return 100 - (100 / (1 + rs))
```

### Eingabeformat

- Immer `List[float]` (oder `List[int]` für volumes)
- Keine pandas DataFrames
- Kein numpy-Array als Interface (NumPy intern in `optimized.py`, aber Eingabe ist `List`)
- Reihenfolge: älteste Werte zuerst (index 0 = ältester Bar)

### Ausgabeformat

| Typ | Verwendung | Beispiel |
|-----|-----------|---------|
| `float` | Einzelwert ohne Metadaten | `calculate_rsi(...)` |
| `List[float]` | Zeitreihe | `calculate_rsi_series(...)`, `calculate_ema(...)` |
| `Optional[NamedTuple/dataclass]` | Strukturiertes Ergebnis | `MACDResult`, `ATRResult`, `BollingerBands`, `StochasticResult`, `RSIDivergenceResult` |
| `List[PriceLevel]` | Level-Listen | `find_support_levels(...)` |
| `Dict[str, float]` | Key-Value Map | `calculate_fibonacci(...)` |

**Konvention bei unzureichenden Daten:**
- Skalare: `return 50.0` (RSI-Neutralwert) oder `return None`
- Strukturierte Ergebnisse: `return None`
- Zeitreihen: `return [50.0] * len(prices)`
- Pandas-NaN wird nicht verwendet

### Parameter-Handling

- **Defaults hartcodiert** als Funktionsparameter (kein Config-Lookup im Indikator selbst)
- Config-Werte werden vom Caller (Analyzer) geladen und als Parameter übergeben
- Beispiel: `PULLBACK_DIVERGENCE_LOOKBACK = _cfg.get("pullback.divergence.lookback", 60)` in pullback.py, dann `calculate_rsi_divergence(..., lookback=PULLBACK_DIVERGENCE_LOOKBACK)`

### Fehlerhandling

- Längen-Check am Anfang jeder Funktion
- Kein `try/except` (Ausnahme: optionale Imports in context.py)
- Array-Grenzen werden mit `max(0, len-lookback)` abgesichert
- Division-by-Zero bei RSI: expliziter `if avg_loss == 0: return 100.0`

### Tests

6 Testdateien für Indikatoren:

| Datei | LOC | Tests | Inhalt |
|-------|-----|-------|--------|
| `tests/unit/test_indicators_momentum.py` | 1.215 | 95 | RSI, MACD, Stochastic, RSI-Divergenz, Swing-Punkte |
| `tests/unit/test_indicators_trend.py` | 848 | 70 | SMA, EMA, ADX |
| `tests/unit/test_indicators_volatility.py` | 934 | 70 | ATR, Bollinger Bands, Keltner Channel |
| `tests/unit/test_momentum_indicators.py` | 317 | 29 | Ältere Tests (RSI, MACD) |
| `tests/unit/test_trend_indicators.py` | 272 | 20 | Ältere Tests (SMA, EMA) |
| `tests/unit/test_volatility_indicators.py` | 258 | 18 | Ältere Tests (ATR, BB) |

Muster: **eine Datei pro Indikator-Kategorie** (Momentum, Trend, Volatility) — nicht eine pro Einzelindikator.

---

## 4. AnalysisContext-Schnittstelle

### Alle relevanten Felder

```python
# src/analyzers/context.py — AnalysisContext (dataclass, slots=True)

# Skalare Indikatoren (NUR aktueller Wert, KEINE Zeitreihe)
rsi_14: Optional[float] = None          # RSI Periode 14
macd_line: Optional[float] = None       # MACD-Linie (aktueller Wert)
macd_signal: Optional[float] = None     # Signal-Linie (aktueller Wert)
macd_histogram: Optional[float] = None  # Histogramm (aktueller Wert)
stoch_k: Optional[float] = None
stoch_d: Optional[float] = None
sma_20: Optional[float] = None
sma_50: Optional[float] = None
sma_200: Optional[float] = None
ema_12: Optional[list[float]] = None    # Achtung: List mit einem Element [last_ema_12]
ema_26: Optional[list[float]] = None    # Achtung: List mit einem Element [last_ema_26]
atr_14: Optional[float] = None

# Kein Rohdaten-Zugriff via Context
# prices, highs, lows, volumes sind NICHT als Felder gespeichert
# Raw-Daten werden nur intern bei _calculate_indicators() verwendet
```

### Lücken für Divergenz-Analyse

| Benötigt | Vorhanden in Context? | Verfügbar wo? |
|----------|----------------------|---------------|
| Close-Preise (letzte 30–50 Bars) | **Nein** | Analyzer-Argument `prices: List[float]` |
| RSI-Zeitreihe (30–50 Werte) | **Nein** | `calculate_rsi_series()` muss aufgerufen werden |
| OBV-Zeitreihe | **Nein** | Nicht implementiert |
| MFI-Zeitreihe | **Nein** | Nicht implementiert |
| CMF-Zeitreihe | **Nein** | Nicht implementiert |
| MACD-Zeitreihe | **Nein** | Nur Skalare im Context |
| Volumes (letzte N Bars) | **Nein** | Analyzer-Argument `volumes: List[int]` |

**Fazit:** AnalysisContext ist ausschließlich ein Cache für **Skalare** (aktueller Indikatorwert). Für Divergenz-Checks (brauchen 20–50 Bar-Zeitreihen) müssen die Analyzer die Raw-Daten (`prices`, `highs`, `lows`, `volumes`) direkt nutzen, die ihnen als Parameter übergeben werden.

Die Raw-Daten sind bei Analyzer-Aufruf verfügbar (252 Bars, siehe Abschnitt 7). Zeitreihen müssen zur Laufzeit berechnet werden — entweder im Analyzer-Aufruf oder in einem neuen `src/indicators/divergence.py`.

---

## 5. Wo würden Divergenz-Checks integriert?

### Option A: `src/indicators/divergence.py`

Pure Funktionen, identisches Muster zu `momentum.py`:

```python
# divergence.py
def check_price_rsi_divergence(prices, rsi_series, lookback=30) -> Optional[DivergenceSignal]: ...
def check_price_obv_divergence(prices, obv_series, lookback=30) -> Optional[DivergenceSignal]: ...
def check_cmf_macd_falling(cmf_series, macd_series, lookback=3) -> bool: ...
# ...
```

**Pro:** Testbar isoliert, wiederverwendbar, folgt Konventionen exakt.
**Contra:** Braucht neue Indikator-Zeitreihen (OBV, MFI, CMF) als Input.

### Option B: Methode im Analyzer (`bounce.py`, `pullback.py`)

Inline wie die existierenden `_score_rsi_divergence()`-Methoden.

**Pro:** Einfacher Einstieg, kein neues Modul.
**Contra:** Duplikation, kein Reuse zwischen Analyzern, schwerer testbar.

### Option C: `src/services/divergence_scoring.py`

Score-Service analog zu `EnhancedScoringService`.

**Pro:** Zentraler Penalty-Mechanismus für alle Strategies.
**Contra:** Overkill für 7 Checks; fügt Schicht hinzu die heute nicht existiert.

### Empfehlung: **Option A** mit Vorbedingung

Die existierenden Konventionen zeigen klar: Indikatoren als pure Funktionen in `src/indicators/`. Die RSI-Divergenz in `momentum.py` ist das exakte Vorbild.

**Reihenfolge:**
1. OBV, MFI, CMF als Funktionen in `momentum.py` ergänzen (oder neues `volume_indicators.py`)
2. Divergenz-Checks in `divergence.py` — reine Kombinationslogik die auf bestehende Zeitreihen operiert
3. Calls aus `bounce.py`/`pullback.py` heraus, mit Score-Anpassung via `score += PENALTY_CONSTANT`

Die Indikatoren kennen keine Scores. Die Penalty-Werte gehören in den Analyzer (wie `BOUNCE_CONFIRM_PENALTY_MOMENTUM = -0.5`), konfigurierbar via `config/scoring.yaml`.

---

## 6. Scoring-Integration

### Etabliertes Muster

Alle Score-Modifikationen in den Analyzern arbeiten **additiv** mit benannten Konstanten:

```python
# bounce.py — typisches Muster
BOUNCE_CONFIRM_PENALTY_MOMENTUM = _cfg.get("bounce.confirmation.penalty_momentum", -0.5)
BOUNCE_CONFIRM_PENALTY_MACD = _cfg.get("bounce.confirmation.penalty_macd", -0.5)
BOUNCE_FIB_WEAK_PENALTY = _cfg.get("bounce.fibonacci.weak_penalty", -0.5)
BOUNCE_DOWNTREND_SEVERE_PENALTY = _cfg.get("bounce.downtrend_filter.severe_penalty", -2.5)

# Im Scoring-Flow:
score += BOUNCE_CONFIRM_PENALTY_MOMENTUM   # negativ = Abzug
score += BOUNCE_FIB_WEAK_PENALTY           # negativ = Abzug
score += BOUNCE_SMA_RECLAIM_20_BONUS       # positiv = Bonus
```

**Kein Multiplikator-Mechanismus im Analyzer-Core** (Multiplikatoren existieren nur in `EnhancedScoringService` für daily_picks-Re-Ranking).

### Einpassung von Divergenz-Penalties

Das Muster ist identisch mit bestehenden Penalties. Für Divergenz-Checks würde es so aussehen:

```python
# In config/scoring.yaml (neu unter "bounce.divergence" oder "pullback.divergence"):
DIVERGENZ_PENALTY_PRICE_RSI   = _cfg.get("bounce.divergence.price_rsi", -0.5)
DIVERGENZ_PENALTY_PRICE_OBV   = _cfg.get("bounce.divergence.price_obv", -0.3)
DIVERGENZ_PENALTY_CMF_MACD    = _cfg.get("bounce.divergence.cmf_macd_falling", -0.4)
DIVERGENZ_PENALTY_DISTRIBUTION = _cfg.get("bounce.divergence.distribution_pattern", -0.8)

# Im Analyzer:
if divergence_result.has_bearish_rsi_divergence:
    score += DIVERGENZ_PENALTY_PRICE_RSI
```

Die Penalties des Freundes (-6/-12/-20 Punkte auf 100er-Skala) müssen auf die 0–10 Skala von OptionPlay skaliert werden — grob: Friend-Penalty / 10 → OptionPlay-Penalty.

---

## 7. Verfügbare Daten für Indikatoren

### Bars pro Symbol beim Analyzer-Aufruf

| Quelle | Wert | Fundstelle |
|--------|------|-----------|
| Minimum für AnalysisContext | 20 Bars | `context.py:233` |
| Minimum für Bounce-Analyzer | 120 Bars (`support_lookback_days`) | `bounce.py:285` |
| Minimum für Pullback-Analyzer | 50 Bars (base.py default) | `base.py:85` |
| Support/Resistance-Lookback | 60–120 Bars | `bounce.py:61`, `pullback.py:111` |
| Fibonacci-Lookback | 10–60 Bars | `bounce.py:130,131`, `pullback.py:386` |
| RSI-Divergenz-Lookback | 20 (Bounce), 60 (Pullback) Bars | `bounce.py:141`, `pullback.py:102` |
| Typisch geladene Historie | ~252 Bars | Scanner lädt 1 Jahr tägliche Bars |

**Fazit:** Divergenz-Checks brauchen 20–50 Bars — das ist für beide Analyzer unkritisch. Der begrenzende Faktor sind neue Indikatoren (OBV, MFI, CMF), die `volumes` + `highs` + `lows` brauchen, allesamt verfügbar.

---

## 8. Empfehlung pro Divergenz-Check

### Check 1: Price/RSI-Divergenz (Higher High, RSI Lower)

**Benötigte Daten:** Close-Preise (letzte 50 Bars), RSI-Zeitreihe (via `calculate_rsi_series`)

**Status:** `calculate_rsi_divergence()` in `momentum.py` **existiert bereits** und tut genau das (bullisch und bärisch). `pullback.py` nutzt sie bereits.

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Ja — `calculate_rsi_divergence()` + `calculate_rsi_series()` |
| Aufwand | **Klein** — nur Caller-Code in bounce.py ergänzen |
| Risiko | **Niedrig** — Implementierung bewährt, Tests vorhanden (95 Tests) |
| Aktion | `bounce.py` um `_score_rsi_divergence()` erweitern (Pullback hat das bereits) |

---

### Check 2: Price/OBV-Divergenz

**Benötigte Daten:** Close-Preise + Volumes (letzte 30–50 Bars), OBV-Zeitreihe

**Status:** OBV nicht implementiert.

OBV-Formel ist trivial:
```python
obv[i] = obv[i-1] + volume[i]  if close[i] > close[i-1]
obv[i] = obv[i-1] - volume[i]  if close[i] < close[i-1]
obv[i] = obv[i-1]              if close[i] == close[i-1]
```

Divergenz-Logik: Swing-Hochs im Preis vs. Swing-Hochs in OBV — dasselbe Muster wie RSI-Divergenz.

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Nein — OBV muss neu implementiert werden |
| Aufwand | **Klein** — `calculate_obv_series(closes, volumes) -> List[float]` in `momentum.py`, dann Divergenz-Check-Funktion |
| Risiko | **Niedrig** — OBV ist einer der einfachsten Indikatoren |
| Aktion | OBV in `momentum.py`, Divergenz-Funktion in `divergence.py` (neu) |

---

### Check 3: Price/MFI-Divergenz

**Benötigte Daten:** Close, High, Low, Volume (letzte 30–50 Bars), MFI-Zeitreihe

**Status:** MFI nicht implementiert.

MFI (14-Perioden-Standard):
- Typical Price = (H + L + C) / 3
- Raw Money Flow = TP × Volume
- Positive/Negative Money Flow über Periode
- MFI = 100 × PMF / (PMF + NMF)

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Nein — MFI muss neu implementiert werden |
| Aufwand | **Mittel** — komplexer als OBV, braucht High/Low/Volume-Arrays |
| Risiko | **Niedrig bis Mittel** — Formel klar, aber 4 Arrays als Input |
| Aktion | `calculate_mfi_series(highs, lows, closes, volumes, period=14) -> List[float]` in `momentum.py` |

---

### Check 4: CMF + MACD fallend gleichzeitig

**Benötigte Daten:** CMF-Zeitreihe (letzte 3 Bars), MACD-Zeitreihe (letzte 3 Bars)

**Status:** CMF nicht implementiert. MACD existiert, aber nur als Skalar im Context — für den Check brauchen wir MACD der letzten 3 Bars → Zeitreihe nötig.

CMF (20-Perioden-Standard):
- MFV (Money Flow Volume) = ((C - L) - (H - C)) / (H - L) × Volume
- CMF = Sum(MFV, period) / Sum(Volume, period)

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Nein — CMF fehlt; MACD-Serie fehlt im Context |
| Aufwand | **Mittel** — CMF implementieren + MACD-Serie aus Raw-Daten berechnen |
| Risiko | **Mittel** — zwei neue Indikatoren, Division-by-Zero wenn H==L |
| Aktion | `calculate_cmf_series()` + `calculate_macd_series()` (MACD existiert, aber nur als Skalar); oder MACD-Zeitreihe direkt im `calculate_macd()` als optionales Return ergänzen |

---

### Check 5: Momentum-Divergenz (MFI up, CMF down + RSI down)

**Benötigte Daten:** MFI-Serie, CMF-Serie, RSI-Serie (letzte 3–5 Bars)

**Status:** MFI und CMF fehlen (gleiche Voraussetzung wie Checks 3 und 4).

Der Check selbst ist reine Kombinationslogik auf bestehenden Zeitreihen — sobald MFI und CMF implementiert sind, ist dieser Check trivial.

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Nein — setzt MFI (Check 3) + CMF (Check 4) voraus |
| Aufwand | **Klein** (nach MFI/CMF) |
| Risiko | **Niedrig** |
| Abhängigkeit | Checks 3 + 4 müssen zuerst fertig sein |

---

### Check 6: Distribution Pattern (3 Indikatoren, 3 Bars fallend)

**Benötigte Daten:** MFI-Serie, CMF-Serie, OBV-Serie (letzte 3 Bars)

**Status:** Alle drei fehlen. Sobald OBV (Check 2), MFI (Check 3), CMF (Check 4) implementiert sind, ist der Check trivial:
```python
obv_falling_3 = all(obv[-3-i] > obv[-2-i] ... )  # vereinfacht
```

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Nein — setzt OBV + MFI + CMF voraus |
| Aufwand | **Klein** (nach OBV/MFI/CMF) |
| Risiko | **Niedrig** |
| Abhängigkeit | Checks 2, 3, 4 müssen zuerst fertig sein |

---

### Check 7: CMF Early Warning (CMF 3 Bars fallend, noch positiv)

**Benötigte Daten:** CMF-Zeitreihe (letzte 3–5 Bars)

**Status:** CMF fehlt (gleiche Voraussetzung wie Check 4).

Der Check ist eine einzige Bedingung auf der CMF-Serie:
```python
def check_cmf_early_warning(cmf_series: List[float], lookback: int = 3) -> bool:
    recent = cmf_series[-lookback:]
    return recent[-1] > 0 and all(recent[i] > recent[i+1] for i in range(len(recent)-1))
```

| Aspekt | Bewertung |
|--------|-----------|
| Indikatoren vorhanden? | Nein — setzt CMF voraus |
| Aufwand | **Klein** (nach CMF) |
| Risiko | **Niedrig** |
| Abhängigkeit | Check 4 (CMF) muss zuerst fertig sein |

---

### Zusammenfassung der Abhängigkeiten

```
Check 1 (Price/RSI)          → Sofort umsetzbar (RSI-Divergenz existiert)
Check 2 (Price/OBV)          → OBV implementieren → Check umsetzbar
Check 3 (Price/MFI)          → MFI implementieren → Check umsetzbar
Check 4 (CMF+MACD fallend)   → CMF implementieren, MACD-Serie ergänzen
Check 5 (Momentum-Divergenz) → Depends on: Check 3 + Check 4
Check 6 (Distribution)       → Depends on: Check 2 + Check 3 + Check 4
Check 7 (CMF Early Warning)  → Depends on: Check 4 (CMF)
```

**Empfohlene Reihenfolge:**
1. `calculate_obv_series()` — 30 LOC, risikoarm
2. `calculate_mfi_series()` — 40 LOC, risikoarm
3. `calculate_cmf_series()` — 30 LOC, Division-by-Zero beachten
4. MACD-Zeitreihe: entweder `calculate_macd_series()` oder optionaler Return in bestehendem `calculate_macd()`
5. `divergence.py` (neu): Checks 1–7 als pure Funktionen, alle unter 20 LOC pro Check
6. Integration in `bounce.py` und `pullback.py` mit konfigurierbaren Penalty-Konstanten

**Gesamt-Aufwand:** ~4–6 Implementierungsstunden für alle 7 Checks (inkl. Tests).

---

## Offene Punkte / Design Debt

| # | Issue | Priorität |
|---|-------|-----------|
| IND-01 | RSI inline in `bounce.py` und `pullback.py` dupliziert (3 RSI-Implementierungen gesamt) | Niedrig — funktioniert, kein unmittelbarer Schaden |
| IND-02 | Fibonacci inline in `pullback.py` dupliziert (zusätzlich zu `calculate_fibonacci()`) | Niedrig |
| IND-03 | Bollinger Bands inline in `bounce.py` — nutzt nicht `calculate_bollinger_bands()` | Niedrig |
| IND-04 | `ema_12`/`ema_26` im Context als `List[float]` statt `float` — API-Inkonsistenz | Niedrig |
| IND-05 | OBV, MFI, CMF nicht vorhanden — Voraussetzung für 6 der 7 Divergenz-Checks | **Hoch** (Blocker für B.1) |
| IND-06 | MACD nur als Skalar im Context, keine Zeitreihe verfügbar | Mittel — nötig für Check 4 |
