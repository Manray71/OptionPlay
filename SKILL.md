---
name: optionplay
description: "MCP-Server für Options-Trading mit Bull-Put-Spread Strategien. 3 Jobs: Daily Picks, Trade Validator, Position Manager. Verwendet Tradier + Marketdata.app API + optionale IBKR-Bridge. 80%+ Test-Coverage, 54 Tools + 56 Aliases. Trigger: 'Options-Analyse', 'Pullback-Scan', 'Trend-Scan', 'Bull-Put-Spread', 'VIX-Strategie', 'Earnings-Check', 'Options-Chain', 'Max Pain', 'IV-Rank', 'Spread-Kandidaten', 'was sagt der Markt', 'Trading-Setup', 'Daily Picks', 'Zeig mir die heutigen Picks', 'Wie stehen meine Positionen', 'Kann ich X traden'."
---

# OptionPlay - Trading Assistant MCP Server v4.0.0

Bull-Put-Spread Trading-Assistent mit 3 klar definierten Jobs und 5 ML-trainierten Strategien.

**Version:** 4.0.0 | **Test-Coverage:** 80%+ | **Tests:** 6,917 | **ML-Training:** 2026-02-09 (Walk-Forward)

**Alle Trading-Regeln → `docs/PLAYBOOK.md`**
**DB-Schema & Code → `CLAUDE.md`**

---

## Die 3 Jobs

### Job 1: Daily Picks

**Wann:** Morgens vor Marktöffnung
**Was:** 3-5 fertige Setups mit Strikes, Credit-Ziel, Stop-Loss

```
User: "Zeig mir die heutigen Picks"
      "Morning Scan"
      "Was kann ich heute traden?"

Workflow:
1. vix                           → Regime bestimmen
2. prefilter min_days=45         → Earnings-sichere Symbole
3. daily min_stability=50        → Top-Picks mit Strikes (Tier-System: ≥80→Premium, ≥70→Good, ≥50→OK mit höherer Score-Hürde)
4. Pro Pick: earnings + strikes  → Fertige Setups

Output pro Pick:
  Symbol:     AAPL
  Strategie:  Pullback
  Stability:  82 | Earnings: 85 Tage
  VIX:        17 → NORMAL
  Short Put:  $175 (Delta -0.20)
  Long Put:   $165 (Delta -0.05)
  Credit:     $2.30 (23% der Spread-Breite)
  Max Loss:   $770
  Profit-Ziel: 50% → $1.15
  Stop-Loss:   200% → $4.60
```

### Job 2: Trade Validator

**Wann:** Vor jedem Trade
**Was:** GO / NO-GO / WARNING für eigene Trade-Ideen

```
User: "Kann ich MSFT traden, Short Strike 380?"
      "Check AAPL für Bull-Put-Spread"
      "Ist NVDA safe?"

Workflow:
1. validate symbol              → Blacklist + Earnings + VIX
2. analyze symbol               → Stability + technische Analyse
3. strikes symbol               → Empfohlene Strikes
4. pf_check symbol              → Portfolio-Exposure prüfen

Output:
  ✅ GO:      Alle Regeln erfüllt
  ❌ NO-GO:   "Earnings in 23 Tagen"
  ⚠️ WARNING: "VIX 22 = Danger Zone, nur Stability ≥80"
```

### Job 3: Position Manager

**Wann:** Täglich, bei Marktbewegungen
**Was:** Offene Positionen überwachen, Exit-Signale

```
User: "Wie stehen meine Positionen?"
      "Portfolio Review"
      "Was muss ich heute tun?"

Workflow:
1. ibkr_portfolio               → Live-Positionen von IBKR
2. ibkr_spreads                 → Spread-Erkennung
3. Pro Position prüfen:
   - P&L vs. Exit-Regeln (50% Profit / 200% Stop)
   - DTE vs. Roll-Regeln (21 DTE / 7 DTE)
   - Earnings-Änderungen
4. pf_expiring days=14          → Bald auslaufende Positionen

Output pro Position:
  AAPL 175/165 Mar21:  +42% Profit → HOLD (noch 8% bis Exit)
  MSFT 380/370 Mar28:  -15% → HOLD (Stop bei 200%)
  JPM 195/185 Feb21:   18 DTE → ⚠️ ROLL oder CLOSE Entscheidung
```

---

## Tool-Referenz

### Markt & VIX

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_vix` | `vix` | VIX + Regime-Empfehlung |
| `optionplay_regime_status` | `regime` | Detaillierte Regime-Analyse |
| `optionplay_strategy_for_stock` | `strategy_stock` | Strategie-Empfehlung für ein Symbol basierend auf Kurs + VIX |
| `optionplay_events` | `events` | Anstehende Markt-Events (FOMC, OPEX, CPI) |
| `optionplay_health` | `health` | Server-Status und Konfiguration |
| `optionplay_sector_status` | `sector_status` | Sektor-Momentum mit Relative Strength und Breadth |

### Scanning & Picks

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_daily_picks` | `daily` / `picks` / `recommendations` | **Top-Empfehlungen mit Strikes** |
| `optionplay_scan_multi` | `multi` | Multi-Strategie-Scan |
| `optionplay_scan` | `scan` | Pullback-Kandidaten |
| `optionplay_scan_bounce` | `bounce` | Support-Bounce-Kandidaten |
| `optionplay_scan_breakout` | `breakout` | ATH-Breakout-Kandidaten |
| `optionplay_scan_earnings_dip` | `dip` | Earnings-Dip-Kandidaten |
| `optionplay_scan_trend` | `trend` | Trend-Continuation-Kandidaten (SMA-Alignment) |
| `optionplay_earnings_prefilter` | `prefilter` | Earnings-Vorfilter (>45 Tage) |

### Einzel-Analyse

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_analyze` | `analyze` | Vollständige Symbol-Analyse |
| `optionplay_analyze_multi` | `analyze_multi` | Multi-Strategie für ein Symbol |
| `optionplay_ensemble` | `ensemble` | Ensemble-Strategie-Empfehlung (Meta-Learner) |
| `optionplay_ensemble_status` | `ensemble_status` | Ensemble-Selektor und Rotations-Status |
| `optionplay_quote` | `quote` | Aktueller Kurs |
| `optionplay_options` | `options` | Options-Chain mit Greeks |
| `optionplay_earnings` | `earnings` | Earnings-Check |
| `optionplay_expirations` | `expirations` | Verfügbare Verfallstermine |
| `optionplay_historical` | `historical` | Historische Kursdaten |
| `optionplay_validate` | `validate` | Symbol-Validierung (Earnings + Events) |
| `optionplay_validate_trade` | `check` | Trade-Validierung gegen PLAYBOOK-Regeln (GO / NO-GO / WARNING) |
| `optionplay_monitor_positions` | `monitor` | Offene Positionen auf Exit-Signale prüfen |

### Strikes & Risiko

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_recommend_strikes` | `strikes` | Optimale Strike-Empfehlungen |
| `optionplay_spread_analysis` | `spread_analysis` | Spread-P&L-Analyse |
| `optionplay_monte_carlo` | `monte_carlo` | Monte-Carlo-Simulation |
| `optionplay_position_size` | `position_size` | Kelly-Criterion Position Sizing |
| `optionplay_stop_loss` | `stop_loss` | Stop-Loss-Berechnung |
| `optionplay_max_pain` | `max_pain` | Max-Pain-Level |

### Portfolio (internes Tracking)

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_portfolio` | `portfolio` | Portfolio-Zusammenfassung |
| `optionplay_portfolio_positions` | `pf_positions` | Positionen (open/closed/all) |
| `optionplay_portfolio_position` | `pf_position` | Detail-Ansicht einer Position |
| `optionplay_portfolio_add` | `pf_add` | Position hinzufügen |
| `optionplay_portfolio_close` | `pf_close` | Position schließen |
| `optionplay_portfolio_expire` | `pf_expire` | Position verfallen lassen |
| `optionplay_portfolio_expiring` | `pf_expiring` | Bald auslaufende Positionen |
| `optionplay_portfolio_trades` | `pf_trades` | Handelshistorie |
| `optionplay_portfolio_check` | `pf_check` | Portfolio-Limit-Check |
| `optionplay_portfolio_constraints` | `pf_constraints` | Constraint-Konfiguration und Status |
| `optionplay_portfolio_pnl` | `pf_pnl` | P&L nach Symbol |
| `optionplay_portfolio_monthly` | `pf_monthly` | Monats-Report |

### IBKR Bridge (wenn TWS läuft)

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_ibkr_status` | `ibkr` | Verbindungsstatus |
| `optionplay_ibkr_portfolio` | `ibkr_portfolio` | **Live-Positionen** |
| `optionplay_ibkr_spreads` | `ibkr_spreads` | Spread-Erkennung |
| `optionplay_ibkr_vix` | `ibkr_vix` | Live VIX |
| `optionplay_ibkr_quotes` | `ibkr_quotes` | Batch-Quotes |
| `optionplay_news` | `news` | News Headlines |

### Reports

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_report` | `report` | PDF-Report für ein Symbol |
| `optionplay_scan_report` | `scan_report` | PDF Multi-Symbol Scan-Report |

### System

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_cache_stats` | `cache_stats` | Cache-Statistiken (Historical, Quotes, Scans) |
| `optionplay_watchlist_info` | `watchlist` | Watchlist-Übersicht mit Sektoren |

---

## Datenquellen

| Quelle | Daten | Status |
|--------|-------|--------|
| Tradier | Historical, Options, Quotes, OHLCV | Primaer |
| Marketdata.app | Quotes, Options, VIX | Sekundaer |
| Local SQLite DB | Options (19.3M), Greeks (19.6M), OHLCV (442k), VIX | Offline-Cache (~8.6 GB) |
| Yahoo Finance | VIX, Earnings | Fallback |
| IBKR (optional) | Live Data, Portfolio, News | Premium |

---

## Projektstruktur

```
~/OptionPlay/
├── CLAUDE.md                  # Session-Kontext (DB, API, Code)
├── SKILL.md                   # Diese Datei (MCP-Tool-Referenz)
├── config/
│   ├── settings.yaml          # Technische Parameter
│   ├── strategies.yaml        # VIX-basierte Profile
│   ├── scoring_weights.yaml   # Scoring-Gewichte + Sector-Factors (WF-trained)
│   └── watchlists.yaml        # Watchlist (275 Symbole)
├── docs/
│   ├── PLAYBOOK.md            # DAS Regelwerk (Entry, Exit, VIX, Disziplin)
│   ├── ARCHITECTURE.md        # System-Architektur
│   └── ROADMAP.md             # Stabilisierungs-Roadmap
├── tests/                     # 138 Testdateien, 6,917 Tests
└── src/                       # 223 Module, 89,574 LOC — Details in ARCHITECTURE.md
```

---

## Qualitätssicherung

| Metrik | Wert |
|--------|------|
| Test-Coverage | 80%+ |
| Tests | 6,917 (138 Testdateien) |
| Module (src/) | 223 Python-Dateien, 89,574 LOC |
| Tools | 54 + 56 Aliases = 110 Endpoints |
| Thread-Safety | ✅ (10+ Module mit Locks) |
| Async-SQLite | ✅ (asyncio.to_thread) |

---

## Scoring & Weighting-Architektur

Trade-Auswahl erfolgt in 3 Stufen:

### Stufe 1: Komponenten-Scoring (pro Strategie)

Jede der 5 Strategien vergibt Punkte pro technischem Indikator:

| Strategie | Max Punkte | Kern-Komponenten |
|-----------|-----------|-----------------|
| Pullback | 26.0 | RSI, RSI-Div, Support, Fib, MA, Trend, Volume, MACD, Stoch, Keltner, VWAP, Market, Sector, Gap |
| Bounce | 27.0 | Support, RSI, RSI-Div, Candlestick, Volume, Trend, MACD, Stoch, Keltner, VWAP, Market, Sector, Gap |
| ATH Breakout | 23.0 | ATH, Volume, Trend, RSI, RS, Momentum, MACD, Keltner, VWAP, Market, Sector, Gap |
| Earnings Dip | 21.0 | Dip, Gap, RSI, Stabilization, Volume, Trend, MACD, Stoch, Keltner, VWAP, Market, Sector |
| Trend Continuation | 10.5 | SMA-Alignment, Stability, Buffer, Momentum, Volatility |

Normalisierung auf 0-10 Skala via `score_normalization.py`.

### Stufe 2: ML-Trained Weights (Walk-Forward, 2026-02-09)

`FeatureScoringMixin` wendet trainierte Gewichte an (`~/.optionplay/models/`):

| Strategie | WF Threshold | OOS WR | OOS Trades | Degradation |
|-----------|-------------|--------|------------|-------------|
| Pullback | 4.5 | 88.3% | 896 | -2.9% |
| Bounce | 6.0 | 91.6% | 1,072 | -2.9% |
| ATH Breakout | 6.0 | 88.9% | 502 | -3.0% |
| Earnings Dip | 5.0 | 86.7% | 583 | -1.6% |
| Trend Cont. | 5.5 | 87.7% | 1,059 | -1.7% |

**Training:** 18/6/6 Monate Rolling, 7 Epochen (2020-2025), 630 Symbole, echte Options-Chains
**Sector-Rotation:** 12 Sektoren mit trainierten sector_factors (0.647-1.154)
**VIX-Regime:** 4 Regimes (normal 92-95% WR, elevated 82-90%, high 70-85%, extreme unprofitabel)
**Stability-Thresholds:** WF-trainierte Cutoffs per Strategy × Regime (2,978 Trades). Meiste = 0, Ausnahmen: earnings_dip (high→70), trend_continuation (elevated→60)

### Stufe 3: Ranking (Daily Picks)

```
base = 0.7 * signal_score + 0.3 * (stability_score / 10)
speed_multiplier = (0.5 + speed/10) ^ 0.3
final = base * speed_multiplier
```

`stability_weight` und `speed_exponent` sind Config-Parameter.

### Tuning-Hebel

| Was | Wo | Aufwand |
|-----|----|---------|
| ML-Weights anpassen | `~/.optionplay/models/component_weights.json` | Gering |
| Sector-Factors | `config/scoring_weights.yaml` (sectors) | Gering |
| Score-Schwellen | `~/.optionplay/models/trained_models.json` | Gering |
| Stability-Cutoffs | `config/scoring_weights.yaml` (stability_thresholds.by_strategy) | Gering |
| Stability/Speed-Gewichtung | Config-Dict in recommendation_engine | Gering |
| RSI/MACD-Schwellen | `constants/strategy_parameters.py` | Gering |
| Komponenten-Punktzahlen | `config/scoring_weights.yaml` (weights) | Mittel |
| Stability-Threshold Training | `scripts/train_stability_thresholds.py` (~2 Min) | Mittel |
| Full WF Retraining | `scripts/full_walkforward_train.py` (~45 Min) | Hoch |

---

## Disclaimer

Analyse dient informativen Zwecken. Finale Handelsentscheidung liegt beim Nutzer.
