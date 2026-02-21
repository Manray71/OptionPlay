# OptionPlay - Claude Context

Session-Kontext für Claude Code. Enthält DB-Schema, API-Beispiele und Code-Konventionen.
Für alle Trading-Regeln → siehe `docs/PLAYBOOK.md`

**Version:** 4.0.0
**Zuletzt aktualisiert:** 2026-02-21
**Test-Coverage:** 80%+ (7,635 Tests)
**Codebase:** 220 Module | 94,080 LOC (src/) | 151 Testdateien

---

## Datenbank: `~/.optionplay/trades.db`

**Größe**: ~8.6 GB | **Typ**: SQLite

### Tabellen-Übersicht

| Tabelle | Datensätze | Beschreibung |
|---------|------------|--------------|
| `options_prices` | 19.3 Mio | Historische Optionspreise (Bid/Ask/Mid/Last) |
| `options_greeks` | 19.6 Mio | Greeks (Delta, Gamma, Theta, Vega, IV) |
| `daily_prices` | 442k | Echte OHLCV-Bars via Tradier (354 Symbole × ~1280 Bars) |
| `price_data` | 630 | Komprimierte Preisdaten pro Symbol (via PriceStorage) |
| `earnings_history` | ~8,500 | Earnings-Daten mit EPS (343 Symbole) |
| `symbol_fundamentals` | 357 | Fundamentaldaten + Stability Scores |
| `vix_data` | 1,385 | VIX-Tageswerte |

**Zeiträume:** Options + Greeks: 2021-01 bis 2026-01 | VIX: 2020-07 bis 2026-01 | OHLCV: 2021-01 bis 2026-01

### Zweite DB: `~/.optionplay/outcomes.db`

`trade_outcomes` (17,438 Trades) — Backtestete Bull-Put-Spreads mit Entry-Daten, Outcome, Drawdown, VIX und Scores.

---

## Schema Details

### `symbol_fundamentals`

```sql
CREATE TABLE symbol_fundamentals (
    symbol TEXT PRIMARY KEY,
    sector TEXT,                      -- z.B. "Technology"
    industry TEXT,
    market_cap REAL,
    market_cap_category TEXT,         -- "Micro", "Small", "Mid", "Large", "Mega"
    beta REAL,
    week_52_high REAL,
    week_52_low REAL,
    current_price REAL,
    spy_correlation_60d REAL,         -- -1.0 bis 1.0
    iv_rank_252d REAL,                -- 0-100
    historical_volatility_30d REAL,   -- Annualisiert in %
    stability_score REAL,             -- 0-100 (höher = stabiler)
    historical_win_rate REAL,         -- Win Rate in %
    avg_drawdown REAL,                -- Durchschn. Max Drawdown in %
    earnings_beat_rate REAL,
    updated_at TEXT
);
```

### `vix_data`

```sql
CREATE TABLE vix_data (
    date TEXT PRIMARY KEY,
    value REAL NOT NULL,     -- ⚠️ Spalte heißt "value", NICHT "close"!
    created_at TEXT
);
```

### `earnings_history`

```sql
CREATE TABLE earnings_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    earnings_date DATE NOT NULL,
    fiscal_year INTEGER,
    fiscal_quarter TEXT,
    eps_actual REAL,
    eps_estimate REAL,
    eps_surprise REAL,
    eps_surprise_pct REAL,
    time_of_day TEXT,             -- "bmo" / "amc"
    source TEXT DEFAULT 'yfinance',
    UNIQUE(symbol, earnings_date)
);
```

### Joins & Gotchas

- **VIX**: Spalte heißt `value`, NICHT `close`
- **Underlying-Preise**: Nutze `underlying_price` aus `options_prices`, NICHT `price_data`
- **Greeks-Join**: `options_greeks.options_price_id = options_prices.id`
- **Earnings BMO/AMC**: Bei AMC am Tag X ist der Tag NICHT sicher (Reaktion erst X+1)

---

## Python API

### Symbol Fundamentals

```python
from src.cache import get_fundamentals_manager

manager = get_fundamentals_manager()
f = manager.get_fundamentals("AAPL")
# f.stability_score, f.historical_win_rate, f.avg_drawdown

stable = manager.get_stable_symbols()  # Default: ENTRY_STABILITY_MIN
```

### Earnings

```python
from src.cache import get_earnings_history_manager

manager = get_earnings_history_manager()
is_safe = manager.is_earnings_day_safe("PLTR", target_date)
# Bei AMC: Tag selbst ist NICHT sicher
```

---

## Beispiel-Queries

```sql
-- Stabile Symbole für Trading
SELECT symbol, sector, stability_score, historical_win_rate
FROM symbol_fundamentals
WHERE stability_score >= 65  -- ENTRY_STABILITY_MIN
ORDER BY stability_score DESC;

-- Options mit Greeks
SELECT p.underlying, p.quote_date, p.strike, p.option_type,
       p.bid, p.ask, p.underlying_price, p.dte,
       g.delta, g.gamma, g.theta, g.vega, g.iv_calculated
FROM options_prices p
JOIN options_greeks g ON g.options_price_id = p.id
WHERE p.underlying = 'AAPL'
  AND p.option_type = 'put'
  AND p.dte BETWEEN 60 AND 90
  AND g.delta BETWEEN -0.25 AND -0.15
ORDER BY p.quote_date, p.strike;

-- Earnings-Check
SELECT symbol, earnings_date, time_of_day,
       julianday(earnings_date) - julianday('now') as days_to
FROM earnings_history
WHERE symbol = 'AAPL' AND earnings_date >= date('now')
ORDER BY earnings_date ASC LIMIT 1;
```

---

## Code-Konventionen

### Sicherheitsregel: API-Keys

**NIEMALS** API-Keys in `claude_desktop_config.json` oder andere Config-Dateien eintragen.
Alle Keys gehören ausschließlich in `.env` und werden über `SecureConfig._load_env_file()` geladen.

### Import-Patterns

```python
# Innerhalb von src/: Relative Imports
from .config import get_config
from ..utils.markdown_builder import MarkdownBuilder

# Optionale Abhängigkeiten
try:
    from .ibkr_bridge import IBKRBridge
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
```

### Handler-Pattern (Mixin-basiert)

```python
class OptionPlayServer(
    VixHandlerMixin,
    ScanHandlerMixin,
    QuoteHandlerMixin,
    BaseHandlerMixin,
):
    pass
```

### Exception-Hierarchie

```
MCPError (Basis)
├── DataFetchError
│   ├── RateLimitError
│   ├── ApiTimeoutError
│   └── ApiConnectionError
├── ConfigurationError
├── ProviderError
├── SymbolNotFoundError
├── NoDataError
└── InsufficientDataError
```

---

## Scripts für Daten-Updates

```bash
python scripts/populate_fundamentals.py      # Fundamentals + Stability
python scripts/collect_earnings_eps.py       # EPS-Daten
python scripts/calculate_derived_metrics.py  # IV Rank, Correlation, HV
python scripts/daily_data_fetcher.py         # VIX täglich (Cronjob)
python scripts/sync_daily_to_price_data.py   # OHLCV: daily_prices → price_data
```

### ML-Training Scripts

```bash
python scripts/full_walkforward_train.py     # Full Walk-Forward (280 Jobs, ~45 Min)
python scripts/fast_weight_train.py          # Schnelles Component-Weight-Training
python scripts/fast_strategy_train.py        # Schnelles Strategy-Training
python scripts/train_stability_thresholds.py # Stability-Cutoffs per Strategy × Regime (~2 Min)
```

**Trainings-Output:** `~/.optionplay/models/`
- `component_weights.json` — ML-Gewichte pro Scoring-Komponente
- `trained_models.json` — Score-Schwellen + Regime-Adjustments
- `SECTOR_CLUSTER_WEIGHTS.json` — Sektor-Faktoren (12 × 5)
- `wf_training_results_detailed.json` — Detaillierte Walk-Forward-Ergebnisse
- `stability_threshold_analysis.json` — Stability-Cutoff-Analyse (2,978 Trades)

---

## Dokumentation

| Datei | Inhalt |
|-------|--------|
| `docs/PLAYBOOK.md` | **DAS Regelwerk** — Entry, Exit, Sizing, VIX, Disziplin |
| `docs/ARCHITECTURE.md` | System-Architektur |
| `docs/ROADMAP.md` | Stabilisierungs-Roadmap (Phase 1-6 ✅, S1-S6 ✅) |
| `docs/PROJECT_REVIEW.md` | Vollständige Projektdokumentation mit Code-Review |
| `CLAUDE.md` | Diese Datei — DB, API, Code |
| `SKILL.md` | MCP-Tool-Referenz (53 Tools + 55 Aliases) |

---

## Architektur-Hinweise für Weiterentwicklung

### Trading-Strategien (5 Analyzer)

| Strategie | Datei | Max Score | Min Score | WF Threshold | OOS WR |
|-----------|-------|-----------|-----------|-------------|--------|
| **Pullback** | `analyzers/pullback.py` | 14.0 (P95) | 3.5 | 4.5 | 88.3% |
| **Bounce** | `analyzers/bounce.py` | 10.0 | 3.5 | 6.0 | 91.6% |
| **ATH Breakout** | `analyzers/ath_breakout.py` | 10.0 | 4.0 | 6.0 | 88.9% |
| **Earnings Dip** | `analyzers/earnings_dip.py` | 9.5 | 3.5 | 5.0 | 86.7% |
| **Trend Continuation** | `analyzers/trend_continuation.py` | 10.5 | 3.5 | 5.5 | 87.7% |

- **Min Score**: Analyzer-Schwelle fuer Signal-Generierung
- **WF Threshold**: Walk-Forward-trainierte optimale Schwelle (2026-02-09)
- **OOS WR**: Out-of-Sample Win Rate ueber 7 Epochen (4,112 Trades)

Alle Scores werden via `score_normalization.py` auf 0-10 Skala normalisiert.

### Scoring-System (3 Stufen)

1. **Komponenten-Scoring**: Jeder Analyzer vergibt Punkte pro Indikator (`config/scoring_weights.yaml`)
2. **ML-Weights**: `FeatureScoringMixin` wendet trainierte Gewichte an (`~/.optionplay/models/component_weights.json`)
   - Walk-Forward-trainiert (18/6/6 Monate, 7 Epochen, 2020-2025)
   - Sector-Factors pro Strategie × Sektor (12 Sektoren)
   - VIX-Regime-Adjustments (normal, elevated, high, extreme)
3. **Ranking**: `recommendation_engine.py` kombiniert Signal (70%) + Stability (30%) × Speed-Multiplier

### Bekannte kritische Issues

| Issue | Beschreibung | Priorität |
|-------|-------------|-----------|
| **CIRC-01** | ~~Zirkulärer Import~~ — Lazy Import in `reliability.py` | ✅ GELÖST |
| **VER-01** | ~~Versionskonflikt~~ — Vereinheitlicht auf 4.0.0 | ✅ GELÖST |
| **WEIGHT-01** | ~~Scoring-Gewichte hardcoded~~ — `config/scoring_weights.yaml` + RecursiveConfigResolver | ✅ GELÖST |
| **VOL-01** | ~~Volume=0 am Wochenende~~ — Fallback auf letzten non-zero Volume-Wert in Context + allen Analyzern | ✅ GELÖST |
| **EARN-01** | ~~Earnings Pre-Filter blockiert Dip-Strategie~~ — `include_dip_candidates` in ALL/BEST_SIGNAL Mode | ✅ GELÖST |
| **STAB-01** | ~~Fundamentals Pre-Filter zu aggressiv~~ — Von 70 auf 50 gesenkt, Tier-System (Stability-First) übernimmt Qualitätskontrolle | ✅ GELÖST |

### Stability-Filterung (3-Stufen-System)

1. **Fundamentals Pre-Filter** (VOR Scan): `min_stability ≥ 50` — entfernt nur Blacklist-Symbole
2. **Stability-First Post-Filter** (NACH Scan): Tiered Score-Anforderungen:
   - Premium (≥80 Stability): min_score 4.0
   - Good (70-80): min_score 5.0
   - OK (50-70): min_score 6.0 (hoehere Huerde!)
   - Blacklist (<50): komplett gefiltert
3. **WF-Trained Stability Thresholds** (per Strategy × Regime):
   - `by_strategy` Werte in `scoring_weights.yaml` OVERRIDEN globale Defaults (nicht additiv)
   - Meiste Cutoffs = 0 (WF-Score-Thresholds filtern bereits effektiv genug)
   - Ausnahmen: `earnings_dip` (high VIX → 70, Tech/Healthcare/Industrials → 65-70), `trend_continuation` (elevated → 60)
   - Trainiert auf 2,978 OOS-Trades mit echten Stability-Scores

### Volume-Fallback (Wochenende/Feiertage)

Wenn `volumes[-1] == 0`, wird der letzte non-zero Volume-Wert verwendet.
Betrifft: `AnalysisContext`, `PullbackAnalyzer`, `BounceAnalyzer`, `ATHBreakoutAnalyzer`.

### Backtesting Sub-Packages (nach Phase 6)

```
src/backtesting/                    44 Module | 17,611 LOC
├── core/                           Engine, Metrics, Simulator, DB
├── simulation/                     Options-Simulator, Real-Backtester
├── training/                       Walk-Forward, Regime, ML-Optimizer
├── validation/                     Signal-Validation, Reliability
├── ensemble/                       Meta-Learner, Rotation, Selector (5 Strategien)
├── tracking/                       Trade-CRUD, Storage (Price/VIX/Options)
├── models/                         25 Dataclasses (reine Datenmodelle)
└── data_collector.py               Daten-Pipeline
```

### Strategy-Refactor Sessions (2026-02)

| Session | Strategie | Tests | Status |
|---------|-----------|-------|--------|
| 1 | Support Bounce (Refactor) | 65 | ✅ |
| 2 | ATH Breakout (Refactor) | 79 | ✅ |
| 3 | Earnings Dip (Refactor) | 77 | ✅ |
| 4 | Trend Continuation (NEU) | 98 | ✅ |
| 5 | Integration & Backtesting | — | ✅ |
| 6 | Retraining (ML-Weights, Sector Rotation, Stability) | — | ✅ (Walk-Forward, 4112 OOS-Trades, 89.1% WR) |

*Alle Trading-Regeln, VIX-Regime, Stability-Schwellen, Watchlist und Blacklist stehen ausschließlich in PLAYBOOK.md.*
