# E.2b.4 — AlphaScorer-Umbau + Post-Crash + Batch-Loading
**Kontext:** E.2b.3 abgeschlossen auf `feature/e2b-alpha-composite`.
TechnicalComposite berechnet alle 8 Komponenten + 6 Breakout-Patterns.
99 Unit-Tests grün, 5900 Gesamtsuite.

---

## Aufgabe

AlphaScorer umbauen: TechnicalComposite statt nur RS-Ratio.
Post-Crash-Modus mit Stress-Score. Feature-Flag für Rollback.
Batch-OHLCV-Loading für 381 Symbole.

---

## Branch

```bash
cd ~/OptionPlay
git checkout feature/e2b-alpha-composite
git pull origin feature/e2b-alpha-composite
```

---

## Scope E.2b.4

### 1. AlphaScorer-Umbau

Aktuell in `src/services/alpha_scorer.py`:

```python
raw = rs.b_raw + self._fast_weight * rs.f_raw
# B_raw und F_raw sind reine RS-Ratio-Werte
```

Neu: Wenn `alpha_composite.enabled == true`, nutzt der Scorer
TechnicalComposite statt RS-Ratio.

```python
if self._composite_enabled:
    composite = TechnicalComposite(self._composite_config)
    
    # Classic-Fenster (125d)
    b_score = await composite.compute(
        symbol=sym,
        closes=closes[-135:],  # 125d + 10d Buffer
        highs=highs[-135:],
        lows=lows[-135:],
        volumes=volumes[-135:],
        timeframe="classic",
        classic_quadrant=quad_classic,
        fast_quadrant=quad_fast,
    )
    
    # Fast-Fenster (20d)
    f_score = await composite.compute(
        symbol=sym,
        closes=closes[-30:],  # 20d + 10d Buffer
        highs=highs[-30:],
        lows=lows[-30:],
        volumes=volumes[-30:],
        timeframe="fast",
        classic_quadrant=quad_classic,
        fast_quadrant=quad_fast,
    )
    
    alpha_raw = b_score.total + 1.5 * f_score.total
else:
    # Fallback: alte RS-only Berechnung
    alpha_raw = rs.b_raw + self._fast_weight * rs.f_raw
```

**Wichtig:** Die bestehende RS-Berechnung bleibt komplett erhalten.
Nur ein if/else um den neuen Pfad. Kein Löschen von altem Code.

### 2. Batch-OHLCV-Loading

381 Symbole × 2 Fenster = 762 Composite-Berechnungen pro Scan.
OHLCV-Daten einmal laden, dann slicen.

```python
# In generate_longlist() oder score_symbols():

# 1. Alle OHLCV auf einmal laden (ein DB-Call)
from src.data_providers.local_db_provider import LocalDBProvider
db = LocalDBProvider(...)
all_ohlcv = {}
for sym in symbols:
    bars = await db.get_daily_prices(sym, limit=260)  # 1 Jahr
    all_ohlcv[sym] = bars

# 2. Pro Symbol slicen
for sym in symbols:
    bars = all_ohlcv[sym]
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    # ... etc
    # Classic: closes[-135:]
    # Fast: closes[-30:]
```

Prüfen wie `LocalDBProvider.get_daily_prices()` funktioniert.
Falls es schon Batch-Support hat, nutzen. Falls nicht, sequentiell
aber mit einem einzigen DB-Connection-Open.

Ziel: Gesamtzeit für 381 Symbole < 30 Sekunden (Indikator-Berechnung
ist CPU-bound, nicht IO-bound).

### 3. Post-Crash-Modus

Trigger: Stress-Score ≥ 4 (aus Christians vix.py).

Wenn Post-Crash aktiv:
- Classic-Gewicht: 0.3 (statt implizit 1.0)
- Fast-Gewicht: 0.7 × 1.5 = 1.05 (statt 1.5)

```python
if is_post_crash:
    alpha_raw = b_score.total * 0.3 + f_score.total * 0.7 * 1.5
else:
    alpha_raw = b_score.total + f_score.total * 1.5
```

Alternativ die Gewichte aus YAML nehmen (bereits angelegt in E.2b.1):

```yaml
post_crash:
    classic_weight: 0.3
    fast_weight_adj: 0.7
    score_adjustment: -8
```

Stress-Score Berechnung: Braucht VIX-Wert, SPY vs SMA50, und
optional Market Breadth. Prüfen ob ein VIX-Service existiert.
Falls nicht, als Parameter an `generate_longlist()` übergeben
(der Scan-Orchestrator kennt den VIX).

Minimale Implementierung für E.2b.4:

```python
def _is_post_crash(self, vix: float = None) -> bool:
    """Simplified stress check. Full stress score in future."""
    if vix and vix >= 25:
        return True
    return False
```

Falls ein VIX-Service existiert, den nutzen. Falls nicht, VIX als
optionalen Parameter akzeptieren. Kein neuer API-Call in dieser Phase.

### 4. Feature-Flag

Zwei Ebenen (aus E.2b.1 Architektur-Entscheidung 3):

```yaml
# config/trading.yaml
alpha_engine:
  enabled: true           # bestehend — steuert ob Alpha-Engine läuft

alpha_composite:
  enabled: false          # NEU — steuert ob Composite statt RS-Ratio
```

`alpha_composite.enabled` startet als `false`. Wird erst nach
E.2b.5 Verifikation auf `true` gesetzt.

Im AlphaScorer:

```python
def __init__(self, config):
    self._composite_enabled = config.get(
        "alpha_composite", {}
    ).get("enabled", False)
    if self._composite_enabled:
        self._composite = TechnicalComposite(
            config["alpha_composite"]
        )
```

### 5. Quadranten-Übergabe

TechnicalComposite.compute() braucht `classic_quadrant` und
`fast_quadrant` als Parameter. Die kommen aus dem SectorRS-Service
(E.1).

Im AlphaScorer existiert bereits der Zugriff auf SectorRS-Daten
(rs.quadrant, rs.quadrant_fast o.ä.). Diese Werte an compute()
durchreichen.

Prüfen:
```bash
grep -n "quadrant" src/services/alpha_scorer.py
grep -n "quadrant_fast\|fast_quadrant" src/services/sector_rs.py
```

### 6. Ranking und Longlist

Nach Composite-Berechnung: Percentile-Rank über alle Symbole,
Top-N zurückgeben. Die bestehende Ranking-Logik bleibt.

Optional (wenn einfach): Im Longlist-Output die Composite-Details
mitgeben (B-Score, F-Score, aktive Breakout-Signals) für spätere
Telegram/Web-Darstellung. Als Dict oder erweiterte Dataclass.

### 7. Regressions-Check

Die Pipeline (E.3) konsumiert `get_alpha_filtered_symbols()`.
Diese Funktion muss weiterhin eine Liste von Symbolen + Scores
liefern, unabhängig ob Composite oder RS-only.

```bash
# Nach Umbau: Prüfen dass Pipeline-Tests grün bleiben
pytest tests/ -k "pipeline or alpha or scanner" -v
```

---

## Tests

**AlphaScorer-Tests (mindestens 8):**
- `alpha_composite.enabled = false` → alte RS-Berechnung läuft
- `alpha_composite.enabled = true` → Composite-Berechnung läuft
- Composite-Score ist signifikant anders als RS-Score
- Longlist enthält Symbole mit breakout_signals
- Post-Crash: Fast-Gewicht erhöht, Classic reduziert
- Post-Crash: VIX < 25 → normaler Modus
- Regressions: `get_alpha_filtered_symbols()` liefert Liste
- Regressions: Pipeline-Integration unverändert

**Batch-Loading (mindestens 3):**
- OHLCV für 5 Test-Symbole in einem Batch
- Slicing 135d und 30d liefert korrekte Längen
- Symbol mit < 30 Bars wird übersprungen (kein Crash)

**Integration (mindestens 3):**
- Smoke: 10 echte Symbole aus DB, Composite-Ranking plausibel
- Feature-Flag Toggle: gleiche Symbole, unterschiedliche Rankings
- Kein Import-Zirkel (technical_composite ↔ alpha_scorer)

Mindestens 14 neue Tests.

---

## Was NICHT in E.2b.4

- Kalibrierung der Score-Range → E.2b.5
- Vergleich mit Christians Output → E.2b.5
- Frontend-Darstellung → E.4
- Telegram-Format → E.5
- Gewichts-Tuning → E.2b.5 oder Paket F
- Vollständiger Stress-Score (7 Signale) → vereinfachte Version reicht

---

## Akzeptanzkriterien

1. `alpha_composite.enabled = true` → AlphaScorer nutzt
   TechnicalComposite
2. `alpha_composite.enabled = false` → alte Berechnung unverändert
3. Post-Crash-Modus schaltbar (VIX-basiert)
4. Batch-OHLCV: ein DB-Open für alle Symbole
5. `get_alpha_filtered_symbols()` liefert weiterhin korrekte Ausgabe
6. Pipeline-Tests grün (Regression)
7. Mindestens 14 neue Tests
8. Gesamtsuite: 5900+ passed, 0 failed
9. `black --check` sauber
10. `docs/results/E2b_4_RESULT.md` mit:
    - Vergleich: Top-10 alte vs. neue Berechnung (gleiche Symbole)
    - Timing: wie lange dauert ein Composite-Scan für N Symbole
    - Feature-Flag-Status dokumentiert

---

## Standing Rules

- Anti-AI-Schreibstil
- Kein Auto-Trading
- Deutsche Doku, englische Code-Kommentare
- Keine Breaking Changes an bestehenden APIs
- `alpha_composite.enabled` bleibt `false` bis E.2b.5

---

## Commit-Flow

```bash
git add src/services/alpha_scorer.py
git add src/services/technical_composite.py
git add config/trading.yaml
git add tests/
git commit -m "feat(e2b): integrate TechnicalComposite into AlphaScorer with feature flag"

pytest tests/ -k "alpha or composite or pipeline" -v
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
black --check src/ tests/

git push origin feature/e2b-alpha-composite

git add docs/results/E2b_4_RESULT.md
git commit -m "docs(e2b): add E.2b.4 result report"
git push origin feature/e2b-alpha-composite
```

---

## Nächste Phase

E.2b.5 — Verifikation + Kalibrierung: `alpha_composite.enabled = true`
setzen, 20-Symbol-Smoke-Test, Score-Range-Analyse, Breakout-Pattern-
Verifikation gegen bekannte historische Setups, Gewichts-Tuning wenn
nötig, E2b_RESULT.md, PR-Merge nach main.
