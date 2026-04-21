# E.2b.1 — TechnicalComposite Grundstruktur
**Kontext:** docs/E2b_AUDIT.md auf main. Plan: PLAN_E2b_MULTI_FAKTOR_COMPOSITE.md.

---

## Aufgabe

Neues Service-Modul `src/services/technical_composite.py` anlegen mit
Skelett-Klasse, CompositeScore Dataclass, Quadrant-Kombinations-Matrix
als YAML-Lookup und RSI-Score-Funktion. Config-Sektion in
`config/trading.yaml`. Unit-Tests.

Keine Integration in AlphaScorer (das kommt in E.2b.4). Keine
Regression auf bestehende Logik.

---

## Branch

```bash
cd ~/OptionPlay
git checkout main && git pull
git checkout -b feature/e2b-alpha-composite
```

Alle E.2b-Phasen laufen auf diesem Branch bis E.2b.5 Merge.

---

## Scope E.2b.1

### 1. Dataclass `CompositeScore`

Immutable, alle Score-Komponenten plus Summe. Frozen dataclass.

```python
@dataclass(frozen=True)
class CompositeScore:
    symbol: str
    timeframe: str  # "classic" oder "fast"
    total: float
    # Komponenten (für Debugging/Transparenz)
    rsi_score: float = 0.0
    money_flow_score: float = 0.0
    tech_score: float = 0.0
    divergence_penalty: float = 0.0
    earnings_score: float = 0.0
    seasonality_score: float = 0.0
    quadrant_combo_score: float = 0.0
```

In E.2b.1 wird nur `rsi_score` und `quadrant_combo_score` berechnet.
Die anderen bleiben 0.0 bis E.2b.2/E.2b.3.

### 2. Klasse `TechnicalComposite`

Skelett mit `compute()` Methode. In E.2b.1 nur RSI + Quadrant-Combo.
Andere Komponenten als `# TODO(E.2b.2)`, `# TODO(E.2b.3)` markieren.

```python
class TechnicalComposite:
    def __init__(self, config: dict): ...

    async def compute(
        self,
        symbol: str,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
        timeframe: str,
        classic_quadrant: str,
        fast_quadrant: str,
    ) -> CompositeScore: ...

    def _rsi_score(self, closes: list[float], period: int) -> float: ...

    def _quadrant_combo_score(self, classic: str, fast: str) -> float: ...
```

`_quadrant_combo_score` ist reiner Dict-Lookup aus YAML. Key-Format:
`f"{classic}_{fast}"` (z.B. "LAGGING_IMPROVING"). Fallback auf 0.0
bei unbekannter Kombi.

`_rsi_score` nutzt den bestehenden `src/indicators/momentum.py:rsi()`
mit variablem `period`. Score-Mapping: RSI < 30 → +5 (oversold bullish),
30-50 → linear +5 → 0, 50-70 → linear 0 → +3 (neutral-bullish),
> 70 → -3 (overbought). Exakte Schwellen in YAML.

### 3. Quadrant-Matrix in YAML

`config/trading.yaml` neue Sektion `alpha_composite`:

```yaml
alpha_composite:
  # Vollständige 4x4 Matrix (Classic × Fast)
  quadrant_scores:
    LEADING_LEADING: 30
    LEADING_IMPROVING: 10
    LEADING_WEAKENING: -5
    LEADING_LAGGING: -10
    IMPROVING_LEADING: 25
    IMPROVING_IMPROVING: 10
    IMPROVING_WEAKENING: -10
    IMPROVING_LAGGING: -15
    WEAKENING_LEADING: 5
    WEAKENING_IMPROVING: 0
    WEAKENING_WEAKENING: -15
    WEAKENING_LAGGING: -20
    LAGGING_LEADING: 20
    LAGGING_IMPROVING: 15
    LAGGING_WEAKENING: -20
    LAGGING_LAGGING: -25
  # RSI Score-Mapping (parametrisierbar)
  rsi_scoring:
    oversold_threshold: 30      # < 30 → max bullish
    oversold_score: 5.0
    neutral_upper: 70           # > 70 → overbought
    overbought_score: -3.0
    neutral_bullish_score: 3.0
  # Skelett für spätere Phasen (E.2b.2-E.2b.5)
  weights:
    rsi: 1.0
    money_flow: 1.0       # E.2b.2
    tech: 1.0             # E.2b.3
    divergence: 1.0       # E.2b.2
    earnings: 1.0         # E.2b.3
    seasonality: 0.5      # E.2b.3
    quadrant_combo: 1.0
  # Feature-Flag (E.2b.4)
  enabled: false
```

Die Sektion komplett jetzt anlegen, auch wenn E.2b.1 nur die RSI- und
Quadrant-Teile nutzt. Spart Migration-Arbeit in späteren Phasen.

### 4. YAML-Loading

`TechnicalComposite.__init__(config: dict)` nimmt die
`alpha_composite`-Sektion. Der Loader (`from_yaml()` Pattern) kommt
in E.2b.4 mit dem AlphaScorer-Umbau. In E.2b.1 reicht es, wenn
Tests den Config direkt als Dict übergeben.

### 5. Tests

`tests/services/test_technical_composite.py` mit mindestens:

**Quadrant-Matrix:**
- Alle 16 Kombinationen liefern den richtigen Wert aus YAML
- Unbekannte Kombi liefert 0.0
- Edge Case: leerer oder ungültiger Quadrant-String

**RSI-Score:**
- RSI < 30 liefert oversold_score
- RSI > 70 liefert overbought_score
- RSI zwischen den Schwellen liefert plausible Werte (monoton)
- Zu kurze Close-Liste (< period) liefert 0.0

**CompositeScore Dataclass:**
- Frozen (TypeError bei Mutation)
- Defaults funktionieren

**Integration Smoke:**
- `compute()` für ein Testsymbol mit 30 Closes + Quadrant-Paar liefert
  `CompositeScore` mit `rsi_score != 0` und `quadrant_combo_score != 0`,
  Rest 0.0

Mindestens 10 Tests, alle grün.

---

## Was NICHT in E.2b.1

- Integration in AlphaScorer (E.2b.4)
- Money Flow, Divergenz, Tech Score, Earnings, Seasonality
  (E.2b.2, E.2b.3)
- Batch-Berechnung über 381 Symbole (E.2b.4)
- Post-Crash-Modus (E.2b.4)
- Feature-Flag-Switching (E.2b.4)

---

## Offene Frage F1 aus dem Audit

**OHLCV-Lade-Architektur:** Wie bekommt `TechnicalComposite.compute()`
die OHLCV-Daten in Produktion? Drei Optionen:

1. Direkt aus DB (SQLite Query pro Symbol)
2. Über bestehenden Cache-Service (vermutlich in `src/cache/`)
3. Vom AlphaScorer als Parameter übergeben (Batch-Loading)

In E.2b.1 reicht Option 3 für die Test-Signatur. Die produktive
Entscheidung fällt in E.2b.4 bei der Batch-Optimierung.

Vor Start bitte prüfen welche Cache-Services für OHLCV existieren:

```bash
grep -rn "class.*Cache\|class.*Provider" src/cache/ src/data_providers/ | head -10
grep -rn "daily_prices\|get_closes\|get_bars" src/cache/ src/services/ | head -10
```

Ergebnis in einer Zeile im Commit-Message dokumentieren, keine
Architektur-Änderung in E.2b.1.

---

## Akzeptanzkriterien

1. `src/services/technical_composite.py` existiert mit
   `CompositeScore` + `TechnicalComposite`
2. `config/trading.yaml` hat `alpha_composite` Sektion vollständig
3. Mindestens 10 Unit-Tests grün
4. Gesamtsuite grün: 5784+ passed, 0 failed
   (pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py)
5. `black --check src/services/technical_composite.py tests/services/`
   sauber
6. Integration in AlphaScorer NICHT erfolgt (Regressions-Check:
   `git diff main -- src/services/alpha_scorer.py` ist leer)
7. CI grün nach Push
8. `docs/E2b_1_RESULT.md` erstellt mit:
   - Test-Count vorher/nachher
   - LOC-Statistik (neue vs. geänderte Dateien)
   - Antwort auf F1 (welche Cache-Services gefunden)
   - Screenshots/Auszüge der neuen Tests

---

## Standing Rules

- Anti-AI-Schreibstil: keine em-dashes, keine parallelen Konstruktionen,
  keine Puffery-Wörter
- Kein Auto-Trading, nur Score-Berechnung
- Keine Secrets in YAML oder Code
- Deutsche Doku für Result.md, englische Code-Kommentare
- Keine Breaking Changes an bestehenden APIs

---

## Commit-Flow

```bash
# Entwicklung
git add src/services/technical_composite.py
git add config/trading.yaml
git add tests/services/test_technical_composite.py
git commit -m "feat(e2b): add TechnicalComposite skeleton with RSI + quadrant matrix"

# Tests lokal
pytest tests/services/test_technical_composite.py -v
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
black --check src/ tests/

# Push
git push origin feature/e2b-alpha-composite

# CI warten, Ergebnis in Result.md eintragen
# Result.md committen und pushen
git add docs/E2b_1_RESULT.md
git commit -m "docs(e2b): add E.2b.1 result report"
git push origin feature/e2b-alpha-composite
```

---

## Nächste Phase

E.2b.2 — Money Flow (OBV/MFI/CMF Score) + Divergenz-Integration mit
Christians Skala (-6/-12/-20) + 2 neue Divergenz-Checks
(Momentum-Divergenz, Distribution Pattern).
