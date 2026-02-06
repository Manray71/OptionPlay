# OptionPlay Architecture Plan — Continuation Steps
## Remaining Integration Work after Steps 1–6

**Erstellt:** 2026-02-06
**Kontext:** Steps 1–6 aus `ARCHITECTURE_PLAN_FINAL.md` sind implementiert.
Die Infrastruktur steht (YAML, RecursiveConfigResolver, BatchScorer, SectorCycleService),
aber die 4 Analyzer nutzen sie noch nicht. Dieses Dokument beschreibt die verbleibende
Integration.

**Übersicht der erledigten Schritte:**
- [x] Step 1: CIRC-01 Fix + VER-01 Fix
- [x] Step 2: Scoring Inventory → `docs/scoring_extraction.json`
- [x] Step 3: Config Schema → `config/scoring_weights.yaml`
- [x] Step 4: RecursiveConfigResolver → `src/config/scoring_config.py` (26 Tests)
- [x] Step 5B: BatchScorer → `src/analyzers/batch_scorer.py` (7 Tests)
- [x] Step 5A: BaseAnalyzer Infrastructure → `config_resolver` Property + `get_weights()`
- [x] Step 6: SectorCycleService → `src/services/sector_cycle_service.py` (9 Tests)
- [x] Step 6: MCP Tool Registration → `optionplay_sector_status` / `sector_status`

**Gesamter Teststand nach Steps 1–6:** 6705 passed, 36 skipped, 0 errors

---

## Step 7: Regime/Sector-Parameter durch den Call Stack threading

**Ziel:** `regime` und `sector` müssen vom Scanner/Recommendation-Engine bis zu den
Analyzern durchgereicht werden.

### 7A: AnalysisContext erweitern

**Datei:** `src/analyzers/context.py`

Neue Felder zu `AnalysisContext` hinzufügen:

```python
# Neue Felder:
regime: str = "normal"       # VIX regime (low_vol, normal, elevated, high_vol, danger)
sector: Optional[str] = None # Sector name from fundamentals
```

Wenn `AnalysisContext` eine Dataclass ist, Felder hinzufügen.
Wenn es eine Factory-Methode `from_data()` hat, diese um `regime`/`sector` Parameter erweitern.

### 7B: MultiStrategyScanner — Regime und Sector übergeben

**Datei:** `src/scanners/multi_strategy_scanner.py`

1. **VIX Regime beim Context-Setup:**
   - Circa Zeile 862 (`AnalysisContext.from_data(...)`) — `regime=self._get_regime()` übergeben
   - `_get_regime()` soll `self._vix_cache` nutzen (bereits in Zeile 326 gecached)

2. **Sector beim Context-Setup:**
   - Fundamentals-Manager importieren: `from ..cache import get_fundamentals_manager`
   - Sector via `get_fundamentals_manager().get_fundamentals(symbol).sector` abrufen
   - In Context übergeben: `sector=sector`

### 7C: DailyRecommendationEngine — Regime und Sector übergeben

**Datei:** `src/services/recommendation_engine.py`

VIX Regime ist bereits in Zeile 402 als Variable `regime` verfügbar.
Sector ist in Zeile 700/772 über `fundamentals.sector` verfügbar.

1. **Zeile ~401:** `self.set_vix(vix_level)` — zusätzlich Regime am Scanner setzen:
   ```python
   self._scanner.set_regime(regime)  # Neue Methode am Scanner
   ```

2. **`_rank_signals()`** (Zeile 685-734): `regime` Parameter hinzufügen
3. **`_create_daily_pick()`** (Zeile 768-779): `regime` Parameter hinzufügen

---

## Step 8: Analyzer-Refactoring — Scores aus Config statt Hardcoded

**Ziel:** Jeder Analyzer liest seine Scoring-Gewichte aus dem `RecursiveConfigResolver`
statt aus den hardcoded `self.config.*` Dataclass-Werten.

**Strategie:** Schrittweise pro Analyzer. Jeder Analyzer bekommt eine Methode
`_get_resolved_weights()` die via `self.get_weights(regime, sector)` die Gewichte holt.
Die einzelnen Scoring-Methoden lesen dann aus dem `ResolvedWeights`-Objekt statt aus
`self.config`.

### Allgemeines Pattern (für alle 4 Analyzer):

```python
def analyze(self, symbol, prices, volumes, highs, lows, context=None, **kwargs):
    # Regime und Sector aus Context extrahieren
    regime = getattr(context, 'regime', 'normal') if context else 'normal'
    sector = getattr(context, 'sector', None) if context else None

    # Resolved weights holen (4-Layer Merge: Base → Regime → Sector → Regime×Sector)
    resolved = self.get_weights(regime=regime, sector=sector)

    # ... rest der Analyse, aber mit resolved.weights statt self.config
```

### 8A: PullbackAnalyzer refactoring

**Datei:** `src/analyzers/pullback.py`

**Methode `analyze_detailed()` (Zeile ~233-521):**
Am Anfang der Methode `resolved` Weights holen und als lokale Variable nutzen.

**Zu ändernde Score-Zuweisungen (13 Stellen):**

| Zeile | Alt (hardcoded) | Neu (aus resolved) |
|-------|-----------------|-------------------|
| ~789 | `cfg.weight_extreme` | `resolved.weights.get('rsi', 3.0)` (Maximum) |
| ~790 | `cfg.weight_oversold` | `resolved.weights.get('rsi', 3.0) * 0.67` |
| ~791 | `cfg.weight_neutral` | `resolved.weights.get('rsi', 3.0) * 0.33` |
| ~936 | `cfg.weight_strong_alignment` | `resolved.weights.get('trend_strength', 2.0)` |
| ~938 | `cfg.weight_moderate_alignment` | `resolved.weights.get('trend_strength', 2.0) * 0.5` |
| ~853 | `cfg.weight_decreasing` | `resolved.weights.get('volume', 1.0)` |
| ~873 | `cfg.weight_bullish_cross` | `resolved.weights.get('macd', 2.0)` |
| ~895 | `cfg.weight_oversold_cross` | `resolved.weights.get('stoch', 2.0)` |
| ~1090 | `cfg.weight_below_lower` | `resolved.weights.get('keltner', 2.0)` |
| ~993 | `cfg.weight_close` | `resolved.weights.get('support', 2.5)` |
| ~808-821 | `lvl.points` (Fibonacci) | `resolved.weights.get('fibonacci', 2.0)` als Max |
| ~489-504 | `max_possible = STRATEGY_SCORE_CONFIGS[...]` | `resolved.max_possible` |

**WICHTIG:** Die feingranularen Sub-Weights (z.B. `weight_extreme` vs `weight_oversold` vs `weight_neutral`)
bleiben als Proportionen der YAML-Gewichte erhalten. Die YAML definiert den Maximalwert pro
Komponente, die Analyse-Logik bestimmt den Anteil (z.B. 100%, 67%, 33%).

**Empfohlenes Pattern:**
```python
# RSI Scoring - nur max_weight aus Config, Proportionen bleiben im Code
rsi_max = resolved.weights.get('rsi', 3.0)
if rsi < cfg.extreme_oversold:
    score = rsi_max           # 100% des Maximums
elif rsi < cfg.oversold:
    score = rsi_max * 0.67    # 67%
elif rsi < cfg.neutral:
    score = rsi_max * 0.33    # 33%
```

**Normalisierung:**
```python
# Zeile ~504: max_possible aus Resolver statt aus STRATEGY_SCORE_CONFIGS
breakdown.max_possible = resolved.max_possible
```

### 8B: BounceAnalyzer refactoring

**Datei:** `src/analyzers/bounce.py`

**Methode `analyze()` (Zeile ~155-353):**
Gleiche Strategie wie Pullback.

**Zu ändernde Score-Zuweisungen (12 Stellen):**

| Zeile | Komponente | Alt | Max aus YAML |
|-------|-----------|-----|-------------|
| ~459 | support | hardcoded `3` | `resolved.weights.get('support', 3.0)` |
| ~513 | rsi | hardcoded `2` | `resolved.weights.get('rsi', 2.0)` |
| ~672 | rsi_divergence | hardcoded `3.0` | `resolved.weights.get('rsi_divergence', 3.0)` |
| ~547 | candlestick | hardcoded `2` | `resolved.weights.get('candlestick', 2.0)` |
| ~608 | volume | hardcoded `1` | `resolved.weights.get('volume', 2.0)` |
| ~638 | trend | hardcoded `2` | `resolved.weights.get('trend', 2.0)` |
| ~711 | macd | `cfg.weight_bullish_cross` | `resolved.weights.get('macd', 2.0)` |
| ~750 | stoch | `cfg.weight_oversold_cross` | `resolved.weights.get('stoch', 2.0)` |
| ~787 | keltner | `cfg.weight_below_lower` | `resolved.weights.get('keltner', 2.0)` |
| ~338-353 | max_possible | hardcoded `27` | `resolved.max_possible` |

### 8C: ATHBreakoutAnalyzer refactoring

**Datei:** `src/analyzers/ath_breakout.py`

**Zu ändernde Score-Zuweisungen (12 Stellen):**

| Zeile | Komponente | Alt | Max aus YAML |
|-------|-----------|-----|-------------|
| ~477 | ath | hardcoded `3` | `resolved.weights.get('ath', 3.0)` |
| ~554 | volume | hardcoded `2` | `resolved.weights.get('volume', 2.0)` |
| ~581 | trend | hardcoded `2` | `resolved.weights.get('trend', 2.0)` |
| ~617 | rsi | hardcoded `1` | `resolved.weights.get('rsi', 1.0)` |
| ~641 | rs | hardcoded `2` | `resolved.weights.get('rs', 2.0)` |
| ~659 | momentum | `cfg.weight_strong_momentum` | `resolved.weights.get('momentum', 2.0)` |
| ~690 | macd | `cfg.weight_bullish_cross` | `resolved.weights.get('macd', 2.0)` |
| ~730 | keltner | `cfg.weight_above_upper` | `resolved.weights.get('keltner', 2.0)` |
| ~295-309 | max_possible | hardcoded `23` | `resolved.max_possible` |

### 8D: EarningsDipAnalyzer refactoring

**Datei:** `src/analyzers/earnings_dip.py`

**Zu ändernde Score-Zuweisungen (10 Stellen):**

| Zeile | Komponente | Alt | Max aus YAML |
|-------|-----------|-----|-------------|
| ~442 | dip | `cfg.weight_ideal` | `resolved.weights.get('dip', 3.0)` |
| ~497 | gap | `cfg.weight_gap_detected` | `resolved.weights.get('gap', 2.0)` |
| ~547 | rsi | hardcoded `2` | `resolved.weights.get('rsi', 2.0)` |
| ~572 | stabilization | `cfg.weight_stable` | `resolved.weights.get('stabilization', 2.0)` |
| ~614 | volume | hardcoded `1` | `resolved.weights.get('volume', 2.0)` |
| ~647 | trend | hardcoded `2` | `resolved.weights.get('trend', 2.0)` |
| ~692 | macd | `cfg.weight_bullish_cross` | `resolved.weights.get('macd', 2.0)` |
| ~731 | stoch | `cfg.weight_oversold_cross` | `resolved.weights.get('stoch', 2.0)` |
| ~768 | keltner | `cfg.weight_below_lower` | `resolved.weights.get('keltner', 2.0)` |
| ~327-341 | max_possible | hardcoded `24` | `resolved.max_possible` |

### Validierung nach Step 8:

```bash
# Pro Analyzer einzeln testen:
python3 -m pytest tests/unit/test_pullback_analyzer.py -x -q
python3 -m pytest tests/unit/test_bounce_analyzer.py -x -q
python3 -m pytest tests/unit/test_ath_breakout_analyzer.py -x -q
python3 -m pytest tests/unit/test_earnings_dip_analyzer.py -x -q

# Component-Tests:
python3 -m pytest tests/component/ -x -q

# Scoring-Config-Tests müssen weiterhin grün sein:
python3 -m pytest tests/unit/test_scoring_config.py -x -q

# Komplett:
python3 -m pytest tests/ -x -q --timeout=120
```

---

## Step 9: score_normalization.py Update

**Ziel:** `normalize_score()` soll optional `ResolvedWeights.max_possible` nutzen statt
des hardcoded `STRATEGY_SCORE_CONFIGS`.

**Datei:** `src/analyzers/score_normalization.py`

### Änderung:

```python
# VORHER (Zeile 76-99):
def normalize_score(raw_score: float, strategy: str) -> float:
    config = STRATEGY_SCORE_CONFIGS.get(strategy)
    ...
    return (raw_score / config.max_possible) * 10.0

# NACHHER:
def normalize_score(
    raw_score: float,
    strategy: str,
    max_possible: Optional[float] = None,  # NEU
) -> float:
    if max_possible is None:
        config = STRATEGY_SCORE_CONFIGS.get(strategy)
        if config is None:
            return raw_score
        max_possible = config.max_possible

    if max_possible <= 0:
        return raw_score
    return max(0.0, min(10.0, (raw_score / max_possible) * 10.0))
```

**Damit bleibt die Funktion rückwärtskompatibel**, aber Analyzer können jetzt den
dynamischen `resolved.max_possible` Wert übergeben.

### Validierung:

```bash
python3 -m pytest tests/unit/test_score_normalization.py -x -q
```

---

## Step 10: SectorCycleService → Recommendation Engine Integration

**Ziel:** Sector-Momentum-Faktor in die Daily-Picks-Berechnung integrieren.

**Datei:** `src/services/recommendation_engine.py`

### 10A: SectorCycleService instanziieren

In `DailyRecommendationEngine.__init__()` oder `get_daily_picks()`:

```python
from ..services.sector_cycle_service import SectorCycleService

# In __init__() oder lazy:
self._sector_cycle_service = SectorCycleService()
```

### 10B: Sector-Faktoren prefetchen

In `get_daily_picks()` (nach VIX-Check, ca. Zeile 407):

```python
# Sector Momentum prefetch (einmalig für alle Symbole)
sector_factors: Dict[str, float] = {}
try:
    from ..config.scoring_config import get_scoring_resolver
    resolver = get_scoring_resolver()
    sm_config = resolver.get_sector_momentum_config()
    if sm_config.get('enabled', False):
        statuses = await self._sector_cycle_service.get_all_sector_statuses()
        sector_factors = {s.sector: s.momentum_factor for s in statuses}
except Exception as e:
    logger.warning(f"Sector momentum fetch failed: {e}")
```

### 10C: Integration in compute_speed_score()

**Zeile ~649** (Sector Factor im Speed Score):

```python
# VORHER:
sector_factor = self.SECTOR_SPEED.get(sector, 0.5) * 1.5

# NACHHER:
base_sector_speed = self.SECTOR_SPEED.get(sector, 0.5) * 1.5
# Cycle-Faktor anwenden (0.6 - 1.2, Default 1.0)
cycle_factor = self._sector_factors.get(sector, 1.0) if hasattr(self, '_sector_factors') else 1.0
sector_factor = base_sector_speed * cycle_factor
```

### 10D: Alternativ — Cycle-Faktor direkt auf Signal Score

Statt im Speed Score kann der Cycle-Faktor auch direkt auf den Signal Score
angewendet werden (in `_rank_signals()`):

```python
# In _rank_signals(), ca. Zeile 717:
base = (1 - weight) * signal_score + weight * (stability / 10)

# Cycle-Faktor als Multiplikator:
cycle_factor = sector_factors.get(sector, 1.0)
adjusted_base = base * cycle_factor
```

**Empfehlung:** Option 10C (Speed Score) ist die sicherere Integration, da der
Speed Score nur die Reihenfolge beeinflusst, nicht die Go/No-Go-Entscheidung.

### Validierung:

```bash
python3 -m pytest tests/unit/test_sector_cycle_service.py -x -q
python3 -m pytest tests/unit/test_recommendation_engine.py -x -q
# Ggf. neuen Test schreiben:
# test_sector_cycle_integration.py — Verify factor applied in speed score
```

---

## Step 11: BatchScorer Integration in Scanner

**Ziel:** BatchScorer im Scanner nutzbar machen für bulk-scoring.

**HINWEIS:** Dieser Schritt ist optional und nur nützlich wenn >100 Symbole gleichzeitig
gescannt werden. Die bestehende Einzelsymbol-Analyse funktioniert weiterhin.

### 11A: BatchScorer im Scanner registrieren

**Datei:** `src/scanners/multi_strategy_scanner.py`

```python
# In __init__():
from ..analyzers.batch_scorer import BatchScorer
self._batch_scorer = BatchScorer()
```

### 11B: Batch-Scoring nach Einzelanalyse

Der BatchScorer kann NICHT die Einzelanalyse ersetzen (die Analyzer berechnen
die Komponenten), aber er kann die Normalisierung/Re-Scoring beschleunigen wenn
viele Symbole vorliegen.

**Integration nach Zeile ~913** (nach `_run_analysis()`):

```python
# Sammle alle (symbol, strategy, components) Tupel
# Am Ende des Scan-Loops: batch_scorer.score_batch() für Re-Normalisierung
```

**Realistischer Nutzen:**
- Bei 275+ Symbolen spart BatchScorer ~50ms durch Vektorisierung
- Bei <50 Symbolen kein messbarer Unterschied
- Hauptnutzen: konsistente Normalisierung über alle Symbole

### 11C: Parallelization Config

Die `config/scoring_weights.yaml` hat bereits den Abschnitt:

```yaml
parallelization:
  scan_concurrency: 8
  batch_size: 50
  enable_batch_scoring: false
```

BatchScorer nur aktivieren wenn `enable_batch_scoring: true`.

### Validierung:

```bash
python3 -m pytest tests/unit/test_batch_scorer.py -x -q
# Integration test mit echtem Scanner:
python3 -m pytest tests/component/test_multi_scanner.py -x -q
```

---

## Step 12: Feature-Engineering Weights in YAML vervollständigen

**Ziel:** Die VWAP, Market Context, Sector und Gap Scores aus dem
`FeatureScoringMixin` (Datei: `src/analyzers/feature_scoring_mixin.py`) haben
eigene Gewichte die noch nicht vollständig in der YAML stehen.

### Aktuelle Situation:

Die YAML hat bereits `vwap`, `market_context`, `sector`, `gap` als Komponenten
pro Strategie. Aber die Schwellenwerte im Mixin sind hardcoded:

**Datei:** `src/analyzers/feature_scoring_mixin.py`

- VWAP Thresholds: `0.02`, `0.005` (Zeilen ~1138-1144 in pullback.py)
- Market Context: `spy_change > 0.03`, `> 0.01` etc.
- Gap Scoring: Various hardcoded thresholds

### Empfehlung:

Diese Thresholds sind strategieübergreifend gleich und ändern sich selten.
**Niedrige Priorität** — erst refactoren wenn ein konkreter Anlass besteht
(z.B. unterschiedliche Thresholds pro Regime).

---

## Zusammenfassung — Reihenfolge und Abhängigkeiten

```
Step 7: Context erweitern + Threading     ← Voraussetzung für Step 8
   ↓
Step 8: Analyzer Refactoring (4 Dateien)  ← Kernarbeit, grösster Aufwand
   ↓
Step 9: score_normalization Update         ← Kleine Änderung, kann parallel zu 8
   ↓
Step 10: SectorCycle → RecommendationEngine ← Unabhängig von 8, braucht nur 7
   ↓
Step 11: BatchScorer → Scanner             ← Optional, niedrige Priorität
   ↓
Step 12: Feature Mixin YAML               ← Optional, niedrigste Priorität
```

**Geschätzter Aufwand:**
- Step 7: ~30 Min (3 Dateien, kleine Änderungen)
- Step 8: ~2-3 Stunden (4 Analyzer, viele Stellen, Tests nötig)
- Step 9: ~15 Min (1 Funktion, rückwärtskompatibel)
- Step 10: ~45 Min (1 Datei, 2-3 Integrationspunkte)
- Step 11: ~30 Min (optional)
- Step 12: ~30 Min (optional)

---

## Validierung — Abschließender Gesamttest

Nach allen Schritten:

```bash
# Alle Tests:
python3 -m pytest tests/ -x -q --timeout=120

# Erwartung: 6705+ passed (neue Tests kommen hinzu), 0 errors

# Sanity-Check der MCP-Tools:
python3 -c "from src.config.scoring_config import get_scoring_resolver; r = get_scoring_resolver(); print(r.resolve('pullback', 'danger', 'Technology'))"

# Prüfen ob Sector-Momentum funktioniert:
python3 -c "
import asyncio
from src.services.sector_cycle_service import SectorCycleService
async def test():
    s = SectorCycleService()
    statuses = await s.get_all_sector_statuses()
    for st in statuses:
        print(f'{st.sector}: {st.momentum_factor:.3f} ({st.regime.value})')
asyncio.run(test())
"
```

---

## Referenzdateien

| Datei | Relevanz |
|-------|---------|
| `config/scoring_weights.yaml` | Single Source of Truth für alle Gewichte |
| `src/config/scoring_config.py` | RecursiveConfigResolver (Step 4) |
| `src/analyzers/base.py` | `get_weights()` Methode (Step 5A) |
| `src/analyzers/batch_scorer.py` | BatchScorer (Step 5B) |
| `src/services/sector_cycle_service.py` | SectorCycleService (Step 6) |
| `src/analyzers/pullback.py` | Analyzer mit 13 Score-Stellen |
| `src/analyzers/bounce.py` | Analyzer mit 12 Score-Stellen |
| `src/analyzers/ath_breakout.py` | Analyzer mit 12 Score-Stellen |
| `src/analyzers/earnings_dip.py` | Analyzer mit 10 Score-Stellen |
| `src/analyzers/score_normalization.py` | Normalisierung (Step 9) |
| `src/services/recommendation_engine.py` | Daily Picks + Speed Score (Step 10) |
| `src/scanners/multi_strategy_scanner.py` | Scanner Pipeline (Step 7+11) |
| `src/analyzers/context.py` | AnalysisContext (Step 7) |
| `docs/scoring_extraction.json` | Scoring Inventory (Step 2) |
