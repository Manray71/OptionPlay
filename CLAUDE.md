# OptionPlay - Claude Context

Session-Kontext für Claude Code. Enthält DB-Schema, API-Beispiele und Code-Konventionen.
Für alle Trading-Regeln → siehe `docs/PLAYBOOK.md`

**Version:** 4.0.0
**Zuletzt aktualisiert:** 2026-02-03

---

## Datenbank: `~/.optionplay/trades.db`

**Größe**: ~8.6 GB | **Typ**: SQLite

### Tabellen-Übersicht

| Tabelle | Datensätze | Beschreibung |
|---------|------------|--------------|
| `options_prices` | 19.3 Mio | Historische Optionspreise (Bid/Ask/Mid/Last) |
| `options_greeks` | 19.6 Mio | Greeks (Delta, Gamma, Theta, Vega, IV) |
| `earnings_history` | ~8,500 | Earnings-Daten mit EPS (343 Symbole) |
| `symbol_fundamentals` | 357 | Fundamentaldaten + Stability Scores |
| `vix_data` | 1,385 | VIX-Tageswerte |

**Zeiträume:** Options + Greeks: 2021-01 bis 2026-01 | VIX: 2020-07 bis 2026-01

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

stable = manager.get_stable_symbols(min_stability=70.0)
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
WHERE stability_score >= 70
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
```

---

## Dokumentation

| Datei | Inhalt |
|-------|--------|
| `docs/PLAYBOOK.md` | **DAS Regelwerk** — Entry, Exit, Sizing, VIX, Disziplin |
| `docs/ARCHITECTURE.md` | System-Architektur |
| `CLAUDE.md` | Diese Datei — DB, API, Code |

*Alle Trading-Regeln, VIX-Regime, Stability-Schwellen, Watchlist und Blacklist stehen ausschließlich in PLAYBOOK.md.*
