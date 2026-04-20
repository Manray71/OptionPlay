# E.0 Audit — Alpha-Engine (20d-RRG, Zwei-Stufen-Modell)
**Stand:** 2026-04-20 | **Status:** Abgeschlossen

---

## 1. SectorRSService — Aktueller Stand

### Datei
`src/services/sector_rs.py` — 794 Zeilen, keine externen Abhängigkeiten außer YAML + Container

### Berechnungslogik (aktuell — ein Zeitfenster)

```
1. _fetch_closes(etf, days=70)          # lookback_days(60) + 10 Buffer
2. compute_rs_ratio(closes, spy_closes, ema_period=30)
   → EMA(sector/spy_ratio, 30) / mean(EMA) × 100
   → Zentriert bei 100; >100 = outperforming
3. compute_rs_momentum(closes, spy_closes, ema_slow=30, momentum_lookback=5)
   → ROC des RS-Ratio-Zeitreihe über 5 Tage
   → Zentriert bei 100; >100 = verbessert sich
4. classify_quadrant(rs_ratio, rs_momentum) → RSQuadrant enum
5. get_quadrant_modifier(quadrant) → float (+0.5 bis -0.5)
```

### Config (`config/trading.yaml → sector_rs`)

```yaml
sector_rs:
  benchmark: "SPY"
  lookback_days: 60
  ema_fast: 10
  ema_slow: 30
  momentum_lookback: 5
  cache_ttl_hours: 8
  score_modifiers:
    leading: 0.5
    improving: 0.3
    weakening: -0.3
    lagging: -0.5
```

### Datenmodell (`SectorRS` dataclass, frozen)

```python
@dataclass(frozen=True)
class SectorRS:
    sector: str
    etf_symbol: str
    rs_ratio: float       # EMA-basiert, 30d-Fenster (aktuell)
    rs_momentum: float    # ROC über 5d
    quadrant: RSQuadrant  # LEADING/WEAKENING/LAGGING/IMPROVING
    score_modifier: float # Additiv: +0.5 bis -0.5
```

### Rückgabewerte

| Methode | Rückgabe | Verwendung |
|---|---|---|
| `get_all_sector_rs()` | `Dict[str, SectorRS]` | Scanner-Cache, Score-Modifier |
| `get_all_sector_rs_with_trail()` | `Dict[str, dict]` (mit trail-Liste) | Web-API `/sectors` |
| `get_stock_rs_with_trail()` | `List[dict]` | Web-API `/stocks/rrg` |
| `get_score_modifier(symbol)` | `float` | Direkte Symbol-Nutzung |
| `get_cached_sector_rs(sector)` | `Optional[SectorRS]` | Scanner (sync) |

---

## 2. Aufrufstellen

### Scanner (`src/scanner/multi_strategy_scanner.py`)

```python
# Initialisierung (Zeile 362-367)
if self.config.enable_sector_rs:
    self._sector_rs_service = SectorRSService()

# Pre-Fetch vor Scan (Zeile 599-608)
await self._sector_rs_service.get_all_sector_rs()

# Score-Anwendung pro Symbol (Zeile 999-1019)
rs = self._sector_rs_service.get_cached_sector_rs(canonical)
if rs.score_modifier != 0.0:
    signal.score = round(max(0.0, min(10.0, signal.score + rs.score_modifier)), 1)
    signal.details["sector_rs_quadrant"] = rs.quadrant.value
```

### Recommendation Engine (`src/services/recommendation_engine.py`, Zeile 447-455)

```python
service = SectorRSService()
statuses = await service.get_all_sector_statuses()
self._sector_factors = {s.sector: (1.0 + s.score_modifier) for s in statuses}
# Wird als Speed-Multiplikator im Ranking genutzt
```

### Web-API (`~/OptionPlay-Web/backend/api/json_routes.py`, Zeile 1181-1257)

```python
# GET /sectors → get_all_sector_rs_with_trail()
# GET /stocks/rrg → get_stock_rs_with_trail()
# Beide geben rs_ratio, rs_momentum, quadrant, trail zurück
```

### Bounce Analyzer (`src/analyzers/bounce.py`, Zeile 494-495)

```python
sector_rs = getattr(sector_status, "sector_rs", None)
if sector_rs is not None and sector_rs < 0:
    # Penalty wenn sektor_rs negativ
```

---

## 3. Kritische Erkenntnis: "100d" bedeutet NICHT aktuelles ema_slow=30

**Christians Modell:**
- B = Bounce-Score auf 100-Tage-RRG (langsames Fenster, Kontext)
- F = Fast-Score auf 20-Tage-RRG (schnelles Fenster, aktionables Signal)
- `Gesamtscore = B + 1.5 × F`

**Aktuelles OptionPlay:** Nur ein Fenster (`ema_slow=30`, `lookback_days=60`).

Das ist weder das "100d" noch das "20d" aus Christians Modell — es liegt dazwischen.

**Für Paket E brauchen wir:**
1. **Slow-Fenster** (Kontext, B): `lookback_days=120`, `ema_slow=50` oder echte 100-Tage-Daten
2. **Fast-Fenster** (Signal, F): `lookback_days=30`, `ema_slow=10` oder 20-Tage-Daten
3. Beides parallel berechnen, dann `composite = B + 1.5 × F`

---

## 4. Daten-Check: Reicht `daily_prices` für 100d?

```sql
-- Aus CLAUDE.md: daily_prices = 354 Symbole × ~1280 Bars (2021-2026)
-- Benötigte ETFs: XLK, XLV, XLF, XLY, XLP, XLE, XLI, XLB, XLRE, XLU, XLC + SPY
-- 100d = 100 Handelstage ≈ 5 Monate → sicher vorhanden in daily_prices (seit 2021)
```

**Fazit:** Daten vorhanden. `_fetch_closes(sym, days=115)` reicht für 100d + Buffer.

**Aber:** `lookback_days` muss von 60 auf 115+ erhöht werden. Das erhöht Provider-Anfragen leicht.

---

## 5. Architektur-Empfehlung für E.1

### Minimale API-Erweiterung: Neue Felder in `SectorRS`

```python
@dataclass(frozen=True)
class SectorRS:
    sector: str
    etf_symbol: str
    # Slow (100d, Kontext = B in Christians Modell)
    rs_ratio: float       # Umbenennen oder beibehalten
    rs_momentum: float
    quadrant: RSQuadrant
    score_modifier: float
    # NEU — Fast (20d, Signal = F in Christians Modell)
    rs_ratio_fast: float = 100.0
    rs_momentum_fast: float = 100.0
    quadrant_fast: RSQuadrant = RSQuadrant.LEADING
    # NEU — Alpha composite
    alpha_score: float = 0.0  # B + fast_weight × F
```

### Neue Config-Keys

```yaml
sector_rs:
  # Bestehend (wird zum "slow"-Fenster)
  lookback_days: 120    # Von 60 auf 120 erhöhen (100d + Buffer)
  ema_slow: 50          # Oder beibehalten auf 30 — zu diskutieren
  momentum_lookback: 14 # Oder beibehalten auf 5
  # NEU
  fast_window: 20       # Lookback für schnelles Fenster
  fast_ema: 10          # EMA-Periode für schnelles Fenster
  fast_momentum_lookback: 5
  fast_weight: 1.5      # B + 1.5 × F (Christians Formel)
```

### Berechnung in `calculate_sector_rs()`

```python
# Slow (bestehend, leicht erweitert)
rs_ratio_slow = compute_rs_ratio(sector_closes, benchmark_closes, ema_period=self._ema_slow)
rs_momentum_slow = compute_rs_momentum(sector_closes, benchmark_closes, ...)
quadrant_slow = classify_quadrant(rs_ratio_slow, rs_momentum_slow)

# Fast (NEU — letzten N Bars des gleichen Datensatzes nehmen!)
fast_window = self._config.get("fast_window", 20) + 10  # Buffer
sector_fast = sector_closes[-fast_window:]
bench_fast = benchmark_closes[-fast_window:]
rs_ratio_fast = compute_rs_ratio(sector_fast, bench_fast, ema_period=self._fast_ema)
rs_momentum_fast = compute_rs_momentum(sector_fast, bench_fast, ...)
quadrant_fast = classify_quadrant(rs_ratio_fast, rs_momentum_fast)

# Alpha composite (normalisiert auf 0-Achse für Ranking)
b_score = rs_ratio_slow - 100.0  # Positive = outperforming
f_score = rs_ratio_fast - 100.0
alpha_score = b_score + fast_weight * f_score
```

**Vorteil dieser Implementierung:**
- Nur ein Provider-Call pro Symbol (lange Datenserie, daraus kurze Serie durch Slicing)
- Keine API-Änderungen an `_fetch_closes()` nötig
- Rückwärtskompatibel: bestehende `score_modifier` bleibt auf dem Slow-Fenster

---

## 6. Impact-Analyse

### Dateien die geändert werden (E.1)

| Datei | Was ändert sich |
|---|---|
| `src/services/sector_rs.py` | `SectorRS` + neue Felder, `calculate_sector_rs()` + fast-Berechnung, Config-Properties |
| `config/trading.yaml` | Neue Keys: `fast_window`, `fast_ema`, `fast_momentum_lookback`, `fast_weight`, `lookback_days: 120` |
| `src/services/sector_rs.py` (Trail-Methoden) | `get_all_sector_rs_with_trail()` braucht fast-Trail für Web |

### Dateien die geändert werden (E.2)

| Datei | Was ändert sich |
|---|---|
| `src/services/alpha_scorer.py` (NEU) | `AlphaScorer`: Watchlist → Alpha-Score → Top-N Longlist |
| `src/models/daily_pick.py` o.ä. | Neues Feld `alpha_score`, `quadrant_slow`, `quadrant_fast` |

### Dateien die NICHT geändert werden (rückwärtskompatibel)

| Datei | Warum stabil |
|---|---|
| `src/scanner/multi_strategy_scanner.py` | `score_modifier` bleibt unverändert (slow-Quadrant) |
| `src/services/recommendation_engine.py` | `sector_factors` bleibt unverändert |
| `src/analyzers/*.py` | Kein Zugriff auf neue Felder nötig |
| Web-API `/sectors` | Bekommt neue Felder, aber bestehende bleiben |

---

## 7. Offene Fragen vor E.1

1. **Slow-Fenster EMA**: Aktuell `ema_slow=30`, `momentum_lookback=5`. Für echtes 100d-Pendant empfiehlt sich `ema_slow=50`, `momentum_lookback=14`. Oder bestehende Werte beibehalten und nur `lookback_days` erhöhen?

2. **Alpha-Score Normalisierung**: `B + 1.5*F` kann sehr unterschiedliche Ranges haben. Wird für Ranking normalisiert (z.B. 0-10 Skala) oder roh als Sortierschlüssel verwendet?

3. **Score-Modifier für Risk-Stufe**: Bleibt der bestehende `score_modifier` auf dem Slow-Quadrant (Kontext) oder wechselt er zum Fast-Quadrant (Signal)? Empfehlung: Slow bleibt für Risk-Filter (konservativ), Fast geht in Alpha-Longlist.

4. **`lookback_days` Erhöhung**: Von 60 auf 120. Erhöht Datenvolumen pro Fetch (alle 12 ETFs + SPY). Bei warmem Cache (8h TTL) kein Problem.

---

## 8. Phasen-Plan Bestätigt

```
E.1.1  SectorRS dataclass: rs_ratio_fast, rs_momentum_fast, quadrant_fast, alpha_score
E.1.2  calculate_sector_rs(): Fast-Berechnung via Slicing (kein extra Fetch)
E.1.3  Config: fast_window=20, fast_ema=10, fast_weight=1.5, lookback_days=120
E.1.4  get_all_sector_rs_with_trail(): Fast-Trail für Web (trail_fast Liste)
E.1.5  Tests: compute_rs_ratio fast vs slow, classify_quadrant dual, trail format

E.2.1  AlphaScorer (neu): composite = B + weight * F, Top-N Longlist
E.2.2  Dual-Quadrant-Label (z.B. "LAG→IMP"): slow_quadrant/fast_quadrant
E.2.3  Tests: AlphaScorer Ranking, Grenzfälle

E.3.1  DailyRecommendationEngine: Alpha-Longlist als Eingang für Risk-Stufe
E.3.2  /scan: Stufe1→Stufe2 Pipeline verdrahten
```

**Nächster Schritt:** E.1.1 — `SectorRS` erweitern und `calculate_sector_rs()` mit Fast-Berechnung.
