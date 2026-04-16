# OptionPlay -- Post-Refactoring Snapshot

Erstellt: 2026-04-07
Version: 5.0.0
Branch: `refactor/v2-radical-cleanup`

---

## A -- Projektstruktur und Groessen

### Kennzahlen

| Metrik | Vorher (v4.2.0) | Nachher (v5.0.0) | Delta |
|--------|-----------------|-------------------|-------|
| Module in `src/` | 221 | 156 | -65 (-29%) |
| LOC in `src/` | 96,412 | 67,723 | -28,689 (-30%) |
| YAML-Dateien (aktiv) | 10 | 4 | -6 |
| YAML-Zeilen (aktiv) | ~5,882 | 4,220 | -1,662 (-28%) |
| Scripts | 75 | 8 | -67 (-89%) |
| Testdateien | 160 | 135 | -25 (-16%) |
| Tests bestanden | 7,771 | 5,937 | -1,834 (-24%) |

### Aktive YAML-Konfiguration

| Datei | Zeilen | Inhalt |
|-------|--------|--------|
| `config/trading.yaml` | 688 | Trading Rules + VIX-Profile + Roll-Strategie + Regime v2 + Sector RS |
| `config/scoring.yaml` | 1,499 | Scoring Weights + Analyzer Thresholds + Enhanced Scoring + RSI + Validation |
| `config/system.yaml` | 870 | Settings + Scanner Config + Liquidity Blacklist |
| `config/watchlists.yaml` | 1,163 | Watchlists (default_275, extended_600) nach GICS-Sektoren |

Backup-Dateien (nicht aktiv):

| Datei | Status |
|-------|--------|
| `config/analyzer_thresholds.yaml.backup-20260218` | Backup vor Konsolidierung |
| `config/scanner_config.yaml.backup-20260218` | Backup vor Konsolidierung |
| `config/scoring_weights.yaml.bak` | Alt |
| `config/scoring_weights.yaml.pre-test` | Alt |
| `config/scoring_weights.yaml.pre_wf` | Alt |
| `config/backups/` (3 YAML + JSON) | Training-Backups 2026-01-29 |

### Verzeichnisstruktur `src/`

| Paket | Module | Beschreibung |
|-------|--------|--------------|
| `src/analyzers/` | 10 | PullbackAnalyzer, BounceAnalyzer, Pool, Context, Scoring, FeatureScoringMixin |
| `src/cache/` | 11 | CacheManager, Earnings, IV, VIX, Fundamentals, Dividend History |
| `src/config/` | 9 | Loader, Models, WatchlistLoader, AnalyzerThresholds, ScoringConfig |
| `src/constants/` | 6 | TradingRules, RiskManagement, Performance, TechnicalIndicators |
| `src/data_providers/` | 5 | Tradier, IBKR, LocalDB, Yahoo, Fundamentals |
| `src/formatters/` | 3 | OutputFormatters, PortfolioFormatter |
| `src/handlers/` | 20 | 10 Mixin-Handler + 10 Composed-Handler + HandlerContainer |
| `src/ibkr/` | 5 | Bridge, Connection, MarketData, Portfolio |
| `src/indicators/` | 10 | SR, Trend, Momentum, Volatility, Volume, Gap, Events, Optimized |
| `src/models/` | 9 | Base, Candidates, Indicators, MarketData, Options, Result, Strategy |
| `src/options/` | 7 | SpreadAnalyzer, StrikeRecommender, BlackScholes, Liquidity, MaxPain |
| `src/portfolio/` | 2 | Manager |
| `src/risk/` | 2 | PositionSizing |
| `src/scanner/` | 4 | MultiStrategyScanner, Ranker, SignalAggregator |
| `src/services/` | 18 | VIX, SectorRS, EnhancedScoring, TradeValidator, RecommendationEngine, etc. |
| `src/state/` | 2 | ServerState |
| `src/utils/` | 14 | CircuitBreaker, RateLimiter, SecureConfig, Metrics, etc. |
| Root-Module | 6 | mcp_main, mcp_server, mcp_tool_registry, container, shadow_tracker |

### Scripts (8 verbleibend)

| Script | Zweck |
|--------|-------|
| `populate_fundamentals.py` | Fundamentals + Stability Scores |
| `collect_earnings_eps.py` | EPS-Daten via yfinance |
| `collect_earnings_tradier.py` | Earnings via Tradier API |
| `calculate_derived_metrics.py` | IV Rank, Correlation, HV |
| `daily_data_fetcher.py` | VIX taeglich (Cronjob) |
| `sync_daily_to_price_data.py` | OHLCV: daily_prices -> price_data |
| `classify_liquidity.py` | Liquidity-Tier Klassifizierung |
| `morning_workflow.py` | Taeglicher Morning Report |

---

## B -- Konfigurationsdateien

### `config/trading.yaml` (688 Zeilen)

| Sektion | Schluessel | Wert | Zeile |
|---------|------------|------|-------|
| **entry** | stability_min | 65.0 | 19 |
| | earnings_min_days | 45 | 20 |
| | vix_max_new_trades | 30.0 | 22 |
| | vix_no_trading | 35.0 | 23 |
| | price_min / price_max | 20.0 / 1500.0 | 24-25 |
| | volume_min | 500,000 | 26 |
| | iv_rank_min / iv_rank_max | 50.0 / 80.0 | 27-28 |
| **spread** | dte_min / dte_max / dte_target | 35 / 50 / 45 | 35-37 |
| | min_credit_pct | 10.0% | 38 |
| | min_credit_absolute | $20 | 39 |
| **vix_regimes** | 6 Stufen | low_vol bis no_trading | 47-96 |
| | high_vol + no_trading | new_trades_allowed: false | 83-96 |
| **exit** | profit_pct_normal / high_vix | 50% / 30% | 102-103 |
| | stop_loss_multiplier | 2.0 | 104 |
| | roll_dte / force_close_dte | 21 / 7 | 105-106 |
| **roll** | trigger_pct | -50.0% | 119 |
| | new_dte_min / new_dte_max | 35 / 50 | 113-114 |
| **sizing** | max_risk_per_trade_pct | 2.0% | 125 |
| | max_open_positions | 10 | 126 |
| | max_per_sector | 2 | 127 |
| **exit_strategy** (default) | profit_target_pct | 50 | 462 |
| | stop_loss_pct | 200 | 463 |
| | dte_exit | 7 | 464 |
| **vix_regime_v2** | enabled | **true** | 635 |
| | term_structure_overlay | true | 636 |
| **sector_rs** | enabled | **true** | 643 |
| | score_modifiers | leading +0.5, improving +0.3, weakening -0.3, lagging -0.5 | 651-655 |
| **trained_weights** | 4 Strategien x 18 Komponenten | pullback, bounce, ath_breakout, earnings_dip | 484-564 |
| **roll_strategy** | 4 Strategien | trigger_pct: -50.0% (alle) | 571-606 |

**Feature-Flags:**

| Flag | Wert | Zeile |
|------|------|-------|
| `vix_regime_v2.enabled` | true | 635 |
| `sector_rs.enabled` | true | 643 |
| `auto_selection.enabled` | true | 425 |

### `config/scoring.yaml` (1,499 Zeilen)

| Sektion | Inhalt |
|---------|--------|
| `strategies` (5) | pullback, bounce, ath_breakout, earnings_dip, trend_continuation |
| Per Strategie | weights, max_possible, max_tier, regimes (5), sectors (11) |
| `stability_thresholds` | by_regime, by_sector, by_strategy |
| `sector_momentum` | ETF-Mapping, Faktor-Ranges, Gewichte |
| `liquidity` | Entry-Minimums, Quality-Tiers |
| `ranking` | stability_weight: 0.15, speed_exponent: 0.3, min_signal_score: 3.5 |
| `entry_quality` | 7 Faktoren, max 30% Bonus |
| `pullback` (Thresholds) | effective_max: 14.0, signal strong/moderate: 7.0/5.0, min: 3.5 |
| `bounce` (Thresholds) | min: 3.5, max: 10.0, signal strong/moderate: 7.0/5.0 |
| `earnings_dip` (Thresholds) | min: 3.5, max: 9.5, signal strong/moderate: 6.5/5.0 |
| `ath_breakout` (Thresholds) | min: 4.0, max: 9.5, signal strong/moderate: 7.0/5.5 |
| `trend_continuation` (Thresholds) | min: 3.5, max: 10.5 |
| `enhanced_scoring` | mode: multiplicative, max Faktor x1.28 |
| `rsi_thresholds` | 4 Stability-Tiers (85/70/60/0 -> 50/45/40/35) |
| `reliability` | Grade A-F, min_grade: C, min_score: 5.0 |
| `signal_validation` | min_trades_per_bucket: 30 |

**Hinweis:** scoring.yaml enthaelt Thresholds und Weights fuer alle 5 Strategien (inkl. der 3 geloeschten). Diese Werte sind inaktiv, da die Analyzer geloescht wurden, aber die Config-Eintraege verbleiben.

### `config/system.yaml` (870 Zeilen)

| Sektion | Schluessel | Wert |
|---------|------------|------|
| `data_sources.local_database.enabled` | true | |
| `connection.tradier.enabled` | true | |
| `connection.ibkr.port` | 4001 | |
| `filters.earnings.exclude_days_before` | 45 | |
| `filters.fundamentals.min_stability_score` | 50.0 | |
| `options_analysis.expiration.dte_minimum/maximum/target` | 60 / 90 / 75 | |
| `watchlist.default_list` | "extended_600" | |
| `watchlist.stability_split.stable_min_score` | 60.0 | |
| `scanner.auto_earnings_prefilter` | true | |
| `scanner.earnings_prefilter_min_days` | 45 | |
| `scanner.enable_stability_first` | true | |
| `scanner.stability_qualified_threshold` | 60.0 | |
| `shadow_tracker.enabled` | true | |
| `shadow_tracker.auto_log_min_score` | 5.0 | |
| `tradability_gate.min_net_credit` | $2.00 | |
| `liquidity_blacklist.symbols` | 230 Symbole | |

### `config/watchlists.yaml` (1,163 Zeilen)

Organisiert nach GICS-Sektoren (11 Sektoren). Zwei Haupt-Watchlists:
- `default_275`: ~268 Symbole (nach Blacklist-Bereinigung)
- `extended_600`: ~382 Symbole (S&P 500 + Growth/Momentum)

---

## C -- Aktive Analyzer

### PullbackAnalyzer

**Datei:** `src/analyzers/pullback.py` + `src/analyzers/pullback_scoring.py`

**14 Scoring-Komponenten:**

| # | Komponente | Max Punkte | Methode |
|---|-----------|-----------|---------|
| 1 | RSI | 3.0 | `_score_rsi()` |
| 2 | RSI Divergence | 3.0 | `_score_rsi_divergence()` |
| 3 | Support (mit Strength) | 2.0 + 0.5 Bonus | `_score_support_with_strength()` |
| 4 | Fibonacci | 2.5 | `_score_fibonacci()` |
| 5 | Moving Averages | 2.0 | `_score_moving_averages()` |
| 6 | Trend Strength | 2.0 | `_score_trend_strength()` |
| 7 | Volume | 1.0 | `_score_volume()` |
| 8 | MACD | 2.0 | `_score_macd()` |
| 9 | Stochastic | 2.0 | `_score_stochastic()` |
| 10 | Keltner Channel | 2.0 | `_score_keltner()` |
| 11 | VWAP | 1.5 | `_score_vwap()` |
| 12 | Market Context | -1.0 bis +2.0 | `_score_market_context()` |
| 13 | Sector | -1.0 bis +1.0 | `_score_sector()` |
| 14 | Candlestick Reversal | 2.0 | `_score_candlestick_reversal()` |

**effective_max:** 14.0 (P95-Normalisierung)
**Normalisierung:** Raw Score -> 0-10 Skala via `normalize_score()`
**ML-Gewichte:** YAML-Weights / Defaults-Ratio via `_scale()`, plus `sector_factor` multiplikativ

**Gate-Bedingungen (3):**

| Gate | Bedingung | Ergebnis |
|------|-----------|----------|
| 1 | RSI > 70 (overbought) | Skip -- kein Pullback |
| 2 | Preis < SMA200 | Skip -- Abwaertstrend |
| 3 | RSI > 50 AND Preis > SMA20 | Skip -- keine Pullback-Evidenz |

Min. normalisierter Score fuer Signal: 3.5

**Config-Quellen:** `config/scoring.yaml` (Weights, Thresholds), `config/system.yaml` (RSI-Thresholds), `src/constants/` (Perioden, Indikatoren)

**Referenzen auf geloeschte Strategien:** Keine

### BounceAnalyzer

**Datei:** `src/analyzers/bounce.py`

**5 Kern-Komponenten + Modifikatoren:**

| # | Komponente | Range | Methode |
|---|-----------|-------|---------|
| 1 | Support Quality | 0 - 2.5 | `_score_support_quality()` |
| 2 | Proximity | 0 - 2.0 | `_score_proximity()` |
| 3 | Bounce Confirmation | 0 - 2.5 | `_check_bounce_confirmation()` |
| 4 | Volume | -1.0 - 1.5 | `_score_volume()` |
| 5 | Trend Context | -2.0 - 1.5 | `_score_trend_context()` |

**max_score:** 10.0

Bounce Confirmation besteht aus 14 Sub-Signalen (Hammer, Engulfing, Doji, Green Sequence, RSI Turn, MACD Cross, Fib Retracement, SMA Reclaim, RSI Divergence, etc.)

Optionale Modifikatoren (standardmaessig deaktiviert):
- B5 Market Context: bearish x0.8, neutral x0.9 (enabled: false)
- B6 Bollinger Confluence: +0.25 (enabled: false)

**Gate-Bedingungen (5):**

| Gate | Bedingung |
|------|-----------|
| 1 | Kein valider Support (< 2 Beruehrungen in 120 Tagen) |
| 2 | Support gebrochen: Preis < -0.5% unter Support |
| 2b | Zu weit von Support: Preis > 5.0% ueber Support |
| 3 | Kein Bounce bestaetigt: keine Reversal-Signale |
| 4 | Dead Cat Bounce (Volume < 0.7x avg ODER RSI > 70 ODER 2 rote Kerzen) |
| B4 | Extremer Abwaertstrend: > 10% unter fallender SMA200 |

**Config-Quellen:** `config/scoring.yaml` (Thresholds), `src/constants/` (Perioden)

**Referenzen auf geloeschte Strategien:** Keine

---

## D -- VIX Regime v2 und Sector RS

### VIX Regime v2

**Feature-Flag Status:**
- `config/trading.yaml` Zeile 635: `enabled: true` -- wird aber von keinem Python-Code gelesen
- `ScanConfig.enable_regime_v2` in `multi_strategy_scanner.py` Zeile 223: hardcoded `True`
- Fazit: v2 ist aktiv im Scanner und im MCP-Tool `regime_status`, aber der YAML-Flag ist reine Dokumentation

**7 Ankerpunkte** (vix_regime.py Zeilen 59-68):

| VIX | Spread Width | Min Score | Earnings Buffer | Max Positions |
|-----|-------------|-----------|-----------------|---------------|
| 10 | $2.50 | 3.5 | 60d | 6 |
| 15 | $5.00 | 4.0 | 60d | 5 |
| 20 | $5.00 | 4.5 | 60d | 4 |
| 25 | $5.00 | 5.0 | 60d | 3 |
| 30 | $7.50 | 5.5 | 75d | 2 |
| 35 | $10.00 | 6.0 | 90d | 1 |
| 40 | $10.00 | 7.0 | 90d | 0 (Pause) |

**Diskrepanz zu CLAUDE.md:** Dort sind nur 4 Ankerpunkte dokumentiert (10, 20, 30, 40). Im Code sind es 7 (zusaetzlich 15, 25, 35).

Delta bleibt fix ("Delta ist heilig") -- nicht in Ankerpunkten enthalten.

**Fallback auf v1:** Ja, v1 (`VIXStrategySelector` mit 5 diskreten Profilen) bleibt aktiv in:
- Report-Handler (`report.py`, `report_composed.py`): nutzen `get_recommendation()` (v1)
- `get_strategy_for_vix()` / `get_strategy_for_stock()`: immer v1
- `get_recommendation_v2()`: Fallback auf v1 wenn VIX=None

### Sector RS (RRG-Quadranten)

**Datei:** `src/services/sector_rs.py`

**Quadranten-Klassifikation:**

| Quadrant | Bedingung | Score-Modifier |
|----------|-----------|----------------|
| LEADING | RS Ratio > 100 AND RS Momentum > 100 | **+0.5** |
| IMPROVING | RS Ratio <= 100 AND RS Momentum > 100 | **+0.3** |
| WEAKENING | RS Ratio > 100 AND RS Momentum <= 100 | **-0.3** |
| LAGGING | RS Ratio <= 100 AND RS Momentum <= 100 | **-0.5** |

**Integration in Scanner:** Additiv auf `signal.score` (multi_strategy_scanner.py Zeile 1083-1084), clamped auf [0.0, 10.0]. Wird nach VIX-Score-Multiplier angewendet.

**Sektor-Mapping:** 11 GICS-Sektoren, Alias-Normalisierung fuer DB-Sektornamen (z.B. "Consumer Cyclical" -> "Consumer Discretionary").

---

## E -- MCP Tools

**25 Tools + 28 Aliases = 53 registrierte Eintraege**

| # | Tool | Aliases |
|---|------|---------|
| 1 | optionplay_vix | vix |
| 2 | optionplay_regime_status | regime |
| 3 | optionplay_health | health |
| 4 | optionplay_scan | scan |
| 5 | optionplay_scan_bounce | bounce |
| 6 | optionplay_daily_picks | daily, picks, recommendations |
| 7 | optionplay_quote | quote |
| 8 | optionplay_options | options |
| 9 | optionplay_earnings | earnings |
| 10 | optionplay_expirations | expirations |
| 11 | optionplay_validate_trade | check |
| 12 | optionplay_monitor_positions | monitor |
| 13 | optionplay_analyze | analyze |
| 14 | optionplay_ensemble | ensemble |
| 15 | optionplay_recommend_strikes | strikes |
| 16 | optionplay_portfolio | portfolio |
| 17 | optionplay_portfolio_positions | pf_positions |
| 18 | optionplay_portfolio_add | pf_add |
| 19 | optionplay_portfolio_close | pf_close |
| 20 | optionplay_portfolio_expire | pf_expire |
| 21 | optionplay_portfolio_check | pf_check |
| 22 | optionplay_spread_analysis | spread_analysis |
| 23 | optionplay_sector_status | sector_status |
| 24 | optionplay_shadow_review | shadow_review, shadow |
| 25 | optionplay_shadow_stats | shadow_stats |

**Tools fuer geloeschte Strategien:** Keine. `scan` und `daily_picks` dispatchen nur noch an PullbackAnalyzer und BounceAnalyzer.

**Bewertung:** OK -- Tool-Anzahl stimmt mit CLAUDE.md (25 Tools) ueberein.

---

## F -- Filter-Logik

### Vollstaendige Filter-Reihenfolge (multi_strategy_scanner.py)

**Phase 1: VOR dem Scan (Symbol-Level)**

| # | Filter | Schwelle | Quelle |
|---|--------|----------|--------|
| 1 | Liquidity Blacklist | 230 Symbole | `config/system.yaml` |
| 2 | Fundamentals Pre-Filter | stability >= 50, win_rate >= 65%, HV <= 70%, beta <= 2.0, IV >= 20 | `config/system.yaml` |

**Phase 2: Pro Symbol, pro Strategie**

| # | Filter | Schwelle |
|---|--------|----------|
| 3 | Regime-enabled | `resolved.enabled` aus scoring.yaml (false bei HIGH) |
| 4 | Liquidity Tier Gate | Symbol-Tier <= Strategie `max_tier` |
| 5 | Earnings Filter | Earnings innerhalb `earnings_min_days` (45d) -> Skip |
| 6 | IV Rank Filter | min/max aus Config (uebersprungen fuer Bounce) |
| 7 | VIX Score Multiplier | `resolved.vix_score_multiplier` (0.70-1.05) |
| 8 | Sector RS Modifier | +0.5 bis -0.5 additiv |
| 9 | VIX Regime v2 Min-Score | Interpolierter `min_score` Gate |
| 10 | Reliability Scoring | Grade + Win Rate |
| 11 | Stability Scoring | Win Rate Integration, Drawdown Penalty, Boost |
| 12 | Min Score Gate | signal.score >= 3.5 |

**Phase 3: NACH dem Scan**

| # | Filter | Schwelle |
|---|--------|----------|
| 13 | Batch Re-Scoring | Optional, via BatchScorer |
| 14 | Stability-First | Qualified (>= 60): min 3.5 / Blacklist (< 60): rejected |
| 15 | Top-N | max_total_results: 50 |
| 16 | Best-per-Symbol | Bestes Signal pro Symbol |
| 17 | Concentration | max_symbol_appearances: 2 |

**Aktive Strategien im Scanner:** Nur `pullback` und `bounce` (enable_pullback/enable_bounce: true)

**Referenzen auf geloeschte Strategien:** Keine in aktivem Code. Drei `try/except ImportError`-Bloecke fuer `src/backtesting` (Zeilen 41-55) schlagen still fehl.

**YAML-Ladung:** Korrekt -- `config/scoring.yaml` via `get_scoring_resolver()`, `config/system.yaml` via `_get_scanner_cfg()`, `config/trading.yaml` via `constants/trading_rules.py`.

---

## G -- Shadow Tracker

**Datei:** `src/shadow_tracker.py`

| Parameter | Wert | Quelle |
|-----------|------|--------|
| auto_log_min_score | 5.0 | `config/system.yaml` Zeile 512 |
| DB-Pfad | `data/shadow_trades.db` | `config/system.yaml` Zeile 513 |
| Abhaengigkeit auf `src/backtesting/` | **Keine** | -- |
| VALID_STRATEGIES | `["pullback", "bounce"]` | Zeile 26-29 |

### Schema `shadow_trades.db`

**Tabelle `shadow_trades`** (36 Spalten):
`id` (TEXT PK), `logged_at`, `source`, `symbol`, `strategy`, `score`, `enhanced_score`, `liquidity_tier`, `short_strike`, `long_strike`, `spread_width`, `est_credit`, `expiration`, `dte`, `short_bid/ask`, `short_oi`, `long_bid/ask`, `long_oi`, `price_at_log`, `vix_at_log`, `regime_at_log`, `stability_at_log`, `trade_context` (JSON), `status` (open/max_profit/stop_loss/...), `resolved_at`, `price_at_expiry`, `price_min`, `price_at_50pct`, `days_to_50pct`, `theoretical_pnl`, `spread_value_at_resolve`, `outcome_notes`

**Tabelle `shadow_rejections`** (12 Spalten):
`id`, `logged_at`, `source`, `symbol`, `strategy`, `score`, `liquidity_tier`, `short_strike`, `long_strike`, `rejection_reason` (low_credit/low_oi/no_bid/wide_spread/no_chain), `actual_credit`, `short_oi`, `details`

7 Indizes auf `shadow_trades`, 2 auf `shadow_rejections`.

**Tradability Gate** (Zeilen 158-178):

| Parameter | Wert |
|-----------|------|
| min_net_credit | $2.00 |
| min_open_interest | 100 |
| min_bid | $0.10 |
| max_bid_ask_spread_pct | 30% |

**Bewertung:** OK -- sauber vom Backtesting-Modul entkoppelt.

---

## H -- Portfolio und Validator

### PortfolioManager (`src/portfolio/manager.py`)

**Exit-Regeln:** Der PortfolioManager implementiert **keine** automatischen Exit-Regeln. Er ist eine reine CRUD-Persistenzschicht mit manuellen Methoden:
- `close_position(position_id, close_premium)` -- manuell
- `expire_position(position_id)` -- manuell (voller Credit als Profit)
- `assign_position(position_id)` -- manuell (max Loss)

Die 50% TP, 2x SL, 21 DTE Roll-Regeln muessen ueber den Monitor-Handler (`optionplay_monitor_positions`) implementiert sein.

**Config-Werte aus trading.yaml:** Keine -- der Manager liest keine YAML-Config.

**Persistenz:** JSON-Datei `~/.optionplay/portfolio.json` (kein SQLite).

**Problem:** Broken Import in `_notify_ensemble()` (Zeile 415):
```python
from ..backtesting.ensemble.selector import EnsembleSelector
```
Da `src/backtesting/` geloescht ist, schlaegt dieser Import immer fehl. Wird per `except Exception` still behandelt. Totes Code-Fragment.

### TradeValidator (`src/services/trade_validator.py`)

**10 Checks in PLAYBOOK-Reihenfolge:**

| # | Check | NO_GO Bedingung | WARNING Bedingung |
|---|-------|----------------|-------------------|
| 1 | Blacklist | Symbol auf Blacklist | -- |
| 2 | Stability | Score < VIX-adjustiertes Minimum | Fundamentals nicht verfuegbar |
| 3 | Earnings | Earnings < 45 Tage | Daten nicht verfuegbar |
| 4 | VIX | new_trades_allowed = false | DANGER_ZONE / ELEVATED |
| 5 | Price | < $20 oder > $1,500 | Preis nicht verfuegbar |
| 6 | Volume | < 500,000 | Daten nicht verfuegbar |
| 7 | IV Rank | -- (nur soft) | < 50 oder > 80 |
| 8 | DTE | < 35 | > 50 |
| 9 | Credit | < $20 oder < 20% Spread | < $40 (Fee-Warnung) |
| 10 | Portfolio | >= VIX-max_positions, >= max_per_sector | Sektor-Konzentration |

**Entscheidungslogik:**
- **NO_GO** wenn mindestens 1 Check NO_GO
- **WARNING** wenn mindestens 1 Check WARNING (aber kein NO_GO)
- **GO** sonst

**Config-Ladung:** Ueber `constants/trading_rules.py`, das aus `config/trading.yaml` laedt. Kein direkter YAML-Zugriff.

---

## I -- Geloeschte Artefakte

| Pfad | Status |
|------|--------|
| `src/analyzers/ath_breakout.py` | GELOESCHT |
| `src/analyzers/earnings_dip.py` | GELOESCHT |
| `src/analyzers/trend_continuation.py` | GELOESCHT |
| `src/backtesting/` | GELOESCHT |
| `src/pricing/` | GELOESCHT |
| `src/scanner/market_scanner.py` | GELOESCHT |
| `src/visualization/` | GELOESCHT |
| `config/settings.yaml` | GELOESCHT |
| `config/strategies.yaml` | GELOESCHT |
| `config/scoring_weights.yaml` | GELOESCHT |
| `config/trading_rules.yaml` | GELOESCHT |
| `config/analyzer_thresholds.yaml` | GELOESCHT |
| `data_inventory/baseline_ath_breakout.json` | GELOESCHT |
| `data_inventory/baseline_earnings_dip.json` | GELOESCHT |
| `data_inventory/retrain_history/` | GELOESCHT |

**Bewertung:** Alle 15 erwarteten Artefakte korrekt entfernt.

---

## J -- Zombie-Referenzen

### Suche in `src/**/*.py`

| Suchbegriff | Treffer |
|-------------|---------|
| `ath_breakout` / `ATHBreakout` / `AthBreakout` | 0 |
| `earnings_dip` / `EarningsDip` | 0 |
| `trend_continuation` / `TrendContinuation` | 0 |
| `from src.backtesting` / `import backtesting` | 0 |
| `market_scanner` / `MarketScanner` | 0 |

**Bewertung:** Keine Zombie-Referenzen im aktiven Quellcode.

**Hinweis:** `multi_strategy_scanner.py` Zeilen 41-55 haben drei `try/except ImportError`-Bloecke fuer Backtesting-Imports. Diese sind keine Zombie-Referenzen, da sie sauber mit Fallback behandelt werden, aber sie sind toter Code.

### Zombie-Referenzen in Config

`config/scoring.yaml` enthaelt weiterhin vollstaendige Konfigurationen fuer:
- `ath_breakout` (Weights, Regimes, Sectors, Thresholds) -- Zeilen 160-222, 1092-1218
- `earnings_dip` (Weights, Regimes, Sectors, Thresholds) -- Zeilen 224-276, 965-1088
- `trend_continuation` (Weights, Regimes, Sectors, Thresholds) -- Zeilen 277-331, 1222-1321

`config/trading.yaml` enthaelt:
- `trained_weights.ath_breakout` -- Zeilen 525-543
- `trained_weights.earnings_dip` -- Zeilen 545-563
- `roll_strategy.ath_breakout` / `roll_strategy.earnings_dip` -- Zeilen 591-606

`config/system.yaml` enthaelt:
- `scanner.enable_ath_breakout: true` -- Zeile 433
- `scanner.enable_earnings_dip: true` -- Zeile 435
- `roll_strategy.ath_breakout` / `roll_strategy.earnings_dip` -- Zeilen 487-501

Diese Config-Eintraege sind inaktiv (keine Analyzer vorhanden), aber stellen potenzielle Verwirrung dar.

---

## K -- Test-Zustand

### Aktueller Testlauf (2026-04-07)

```
5937 passed, 36 skipped, 1 warning in 63.05s
```

| Metrik | Baseline (v4.2.0) | Aktuell (v5.0.0) | Delta |
|--------|-------------------|-------------------|-------|
| Bestanden | 7,771 | 5,937 | -1,834 |
| Uebersprungen | 11 | 36 | +25 |
| Fehlgeschlagen | 0 | 0 | 0 |
| Warnungen | 9 | 1 | -8 |
| Dauer | 342.96s | 63.05s | -280s (-82%) |

**Fehlgeschlagen/Errors:** 0

**1 Warnung:**
```
tests/unit/test_indicators_momentum.py::TestEdgeCases::test_rsi_with_inf_values
  RuntimeWarning: invalid value encountered in scalar divide (rs = avg_gain / avg_loss)
```

**Bewertung:** OK -- keine Fehler. Der Rueckgang von 7,771 auf 5,937 Tests entspricht der Loeschung von Tests fuer entfernte Module (backtesting, ath_breakout, earnings_dip, trend_continuation, visualization, pricing). Die Testdauer sank um 82% (von 5:43 auf 1:03).

---

## L -- Konfigurationskonsistenz

### earnings_min_days (Soll: 45)

| Datei | Wert | Status |
|-------|------|--------|
| `config/trading.yaml:20` | 45 | OK |
| `config/system.yaml:414` | 45 | OK |
| `src/constants/trading_rules.py:97` | Fallback 30, aber laedt 45 aus YAML | OK |
| `src/config/models.py:432` | Default `ENTRY_EARNINGS_MIN_DAYS` | OK |

**Bewertung:** Konsistent (45 ueberall)

### Stability-Schwelle (Soll: 60)

| Datei | Wert | Kontext |
|-------|------|---------|
| `config/system.yaml:352` | 60.0 | stable_min_score |
| `config/system.yaml:446` | 60.0 | stability_qualified_threshold |
| `config/system.yaml:602` | 50.0 | Pre-Filter (absichtlich lockerer) |
| `config/scoring.yaml:973` | 60.0 | earnings_dip min_stability |

**Bewertung:** Konsistent (60 fuer Qualifikation, 50 fuer Pre-Filter ist beabsichtigt)

### Roll-Trigger (Soll: -50%)

| Datei | Wert | Status |
|-------|------|--------|
| `config/trading.yaml:119` | -50.0 | OK |
| `config/trading.yaml:573-600` | -50.0 (alle 4) | OK |
| `config/system.yaml:469-496` | -50.0 (alle 4) | OK |

**Bewertung:** Konsistent

### DTE (zwei verschiedene Bereiche)

| Kontext | Min | Max | Target | Datei |
|---------|-----|-----|--------|-------|
| Entry + Roll (Tastytrade) | 35 | 50 | 45 | `trading.yaml:35-37` |
| Options Chain Query | 60 | 90 | 75 | `system.yaml:265-267` |

**Bewertung:** Beabsichtigte Dualitaet -- Tastytrade DTE fuer Entry, breiterer Range fuer Chain-Suche. OK.

### IV Rank Min (mehrere Werte)

| Kontext | Wert | Datei |
|---------|------|-------|
| Entry Rule | 50.0 | `trading.yaml:27` |
| Pre-Filter | 20.0 | `system.yaml:216, 606` |
| Filter (allgemein) | 30 | `system.yaml:183` |

**Bewertung:** Beabsichtigte Abstufung (Pre-Filter lockerer als Entry). OK, aber `system.yaml:183` (iv_rank_minimum: 30) ist ein dritter Wert der unklar ist -- wird er ueberhaupt genutzt? Potenzielle Verwirrung.

### profit_target_pct (Soll: 50)

Alle aktiven Werte: 50. Backup-Werte (100) nur in `config/backups/`. OK.

### stop_loss_multiplier (Soll: 2.0)

Einziger Wert: 2.0 in `trading.yaml:104`. OK.

---

## M -- Watchlist-Status

| Watchlist | Symbole |
|-----------|---------|
| `default_275` | 268 |
| `extended_600` | 382 |
| `get_all_symbols()` | 381 |
| `get_stable_symbols()` | 347 |
| `get_risk_symbols()` | 24 |

**Aktive Default-Watchlist:** `extended_600` (laut `config/system.yaml:332`)

**Stability Split:** Aktiv (347 stable + 24 risk = 371; 10 Symbole ohne Score -> stable)

**Bewertung:** OK -- `get_all_symbols()` (381) weicht um 1 von `extended_600` (382) ab, vermutlich durch Blacklist-Filterung.

---

## N -- Offene Fragen / Auffaelligkeiten

### 1. Tote Config-Eintraege fuer geloeschte Strategien (Mittel)

`config/scoring.yaml`, `config/trading.yaml` und `config/system.yaml` enthalten umfangreiche Konfigurationen fuer ath_breakout, earnings_dip und trend_continuation (Weights, Thresholds, Roll-Parameter, Scanner-Flags). Diese sind inaktiv aber potenzielle Verwirrungsquelle. `system.yaml` hat sogar `enable_ath_breakout: true` und `enable_earnings_dip: true`.

**Empfehlung:** Config-Eintraege fuer geloeschte Strategien entfernen oder unter `# ARCHIVED` kommentieren.

### 2. Broken Import in PortfolioManager (Niedrig)

`src/portfolio/manager.py` Zeile 415 importiert `EnsembleSelector` aus `src/backtesting/`, das geloescht ist. Wird per `except Exception` gefangen -- kein Laufzeitfehler, aber toter Code.

**Empfehlung:** `_notify_ensemble()` Methode entfernen.

### 3. Backtesting-Imports im Scanner (Niedrig)

`multi_strategy_scanner.py` Zeilen 41-55: drei `try/except ImportError` fuer `ReliabilityScorer`, `calculate_symbol_stability`, etc. aus `src/backtesting/`. Alle schlagen fehl -> Features deaktiviert.

**Empfehlung:** Imports und zugehoerige Code-Pfade entfernen.

### 4. VIX Regime v2 Feature-Flag ohne Effekt (Info)

`config/trading.yaml` Zeile 635: `vix_regime_v2.enabled: true` wird von keinem Python-Code gelesen. Die Aktivierung erfolgt ueber `ScanConfig.enable_regime_v2` (hardcoded True).

**Empfehlung:** Flag entfernen oder Code anpassen, damit er den YAML-Wert liest.

### 5. CLAUDE.md Ankerpunkt-Diskrepanz (Info)

CLAUDE.md dokumentiert 4 VIX-Ankerpunkte (10, 20, 30, 40). Der Code hat 7 (10, 15, 20, 25, 30, 35, 40).

**Empfehlung:** CLAUDE.md aktualisieren.

### 6. Duplizierte Roll-Strategie-Parameter (Mittel)

Roll-Strategien sind sowohl in `config/trading.yaml` (Zeilen 571-606) als auch in `config/system.yaml` (Zeilen 466-501) mit leicht unterschiedlichen Werten definiert. Beispiel `bounce.dte_extension`: 52 (trading.yaml) vs 76 (system.yaml).

**Empfehlung:** Klaeren welche Quelle autoritativ ist, die andere entfernen.

### 7. TODO/DEPRECATED Kommentare (Niedrig)

| Datei | Zeile | Kommentar |
|-------|-------|-----------|
| `src/analyzers/pool.py` | 280 | TODO: Implementiere block_on_empty mit Condition Variable |
| `src/services/vix_strategy.py` | 74 | DEPRECATED -- use VIXRegime from constants.trading_rules directly |

### 8. DTE-Dualitaet nicht dokumentiert (Info)

Zwei DTE-Bereiche existieren (35-50 Tastytrade vs 60-90 Chain-Query), aber die Unterscheidung ist nirgends explizit dokumentiert. Koennte bei kuenftigen Aenderungen zu Verwirrung fuehren.

### 9. IV Rank Dreifach-Wert (Niedrig)

`system.yaml` definiert `iv_rank_minimum: 30` (Zeile 183) zusaetzlich zu `iv_rank_min: 20` (Zeile 216, Pre-Filter) und `iv_rank_min: 50` (trading.yaml, Entry). Unklar ob die 30 aktiv genutzt wird.

---

*Ende des Snapshots*
