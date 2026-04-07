---
name: optionplay
description: "MCP-Server fuer Options-Trading mit Bull-Put-Spread Strategien. 25 Tools, 2 aktive Strategien (Pullback + Bounce). Tastytrade-basierte Parameter. Trigger: 'Options-Analyse', 'Pullback-Scan', 'Bounce-Scan', 'Bull-Put-Spread', 'VIX-Strategie', 'Earnings-Check', 'Options-Chain', 'Daily Picks', 'Portfolio', 'Shadow Review'."
---

# OptionPlay MCP Tool Reference v5.0.0

Bull-Put-Spread Trading-Assistent mit 2 aktiven Strategien (Pullback + Bounce) und Tastytrade-basierten Parametern.

**Version:** 5.0.0 | **Strategien:** Pullback, Bounce | **Tools:** 25

---

## Tool-Liste (25 Tools)

### Scan

| Tool | Beschreibung |
|------|-------------|
| `optionplay_scan` | Pullback-Kandidaten scannen |
| `optionplay_scan_bounce` | Support-Bounce-Kandidaten scannen |

### Daily Picks

| Tool | Beschreibung |
|------|-------------|
| `optionplay_daily_picks` | Top-Empfehlungen mit Strikes und Credit-Zielen |

### Analyse

| Tool | Beschreibung |
|------|-------------|
| `optionplay_analyze` | Vollstaendige technische Analyse fuer ein Symbol |
| `optionplay_ensemble` | Ensemble-Strategie-Empfehlung via Meta-Learner |
| `optionplay_recommend_strikes` | Optimale Strike-Empfehlungen fuer Bull-Put-Spread |
| `optionplay_spread_analysis` | Spread-P&L-Analyse mit Szenarien |

### VIX & Regime

| Tool | Beschreibung |
|------|-------------|
| `optionplay_vix` | Aktueller VIX-Wert und Regime-Empfehlung |
| `optionplay_regime_status` | Detaillierte VIX-Regime-Analyse mit Term Structure |
| `optionplay_sector_status` | Sektor-Relative-Strength (RRG-Quadranten) |

### Options & Quotes

| Tool | Beschreibung |
|------|-------------|
| `optionplay_quote` | Aktueller Kurs eines Symbols |
| `optionplay_options` | Options-Chain mit Greeks |
| `optionplay_expirations` | Verfuegbare Verfallstermine |
| `optionplay_earnings` | Earnings-Termine und Sicherheits-Check |

### Portfolio

| Tool | Beschreibung |
|------|-------------|
| `optionplay_portfolio` | Portfolio-Zusammenfassung |
| `optionplay_portfolio_positions` | Positionen auflisten (open/closed/all) |
| `optionplay_portfolio_add` | Neue Position hinzufuegen |
| `optionplay_portfolio_close` | Position schliessen |
| `optionplay_portfolio_expire` | Position verfallen lassen |
| `optionplay_portfolio_check` | Portfolio-Limit und Exposure pruefen |

### Monitor & Validation

| Tool | Beschreibung |
|------|-------------|
| `optionplay_monitor_positions` | Offene Positionen auf Exit-Signale pruefen |
| `optionplay_validate_trade` | Trade gegen PLAYBOOK-Regeln validieren (GO/NO-GO/WARNING) |

### Shadow Tracker

| Tool | Beschreibung |
|------|-------------|
| `optionplay_shadow_review` | Shadow-Trades reviewen und bewerten |
| `optionplay_shadow_stats` | Shadow-Tracker Statistiken und Performance |

### System

| Tool | Beschreibung |
|------|-------------|
| `optionplay_health` | Server-Status und Konfiguration |

---

## VIX-Profil-Tabelle (Tastytrade)

| Profil | VIX | Delta | DTE | IV Rank | Besonderheit |
|--------|-----|-------|-----|---------|-------------|
| Conservative | < 15 | -0.16 | 35-50 | >= 50% | Engerer Delta fuer Sicherheit |
| Standard | 15-20 | -0.20 | 35-50 | >= 50% | Normales Setup |
| Aggressive | 20-30 | -0.20 | 35-50 | >= 50% | Hoehere Praemien, gleiches Delta |
| High Vol | 30+ | -0.16 | 35-50 | >= 60% | Engerer Delta, hoehere IV-Anforderung |

**Feste Regeln:**
- Take-Profit: 50% des Credits
- Stop-Loss: 2x Premium
- Rolling: bei 21 DTE

---

## Standard-Workflow

```
1. VIX pruefen        ->  optionplay_vix
2. Scannen             ->  optionplay_daily_picks  oder  optionplay_scan
3. Analysieren         ->  optionplay_analyze SYMBOL
4. Strikes bestimmen   ->  optionplay_recommend_strikes SYMBOL
5. Validieren          ->  optionplay_validate_trade SYMBOL
```

---

## Config-Uebersicht

| Datei | Inhalt |
|-------|--------|
| `config/trading.yaml` | Entry, Exit, VIX-Regime, Spread, Sizing, Disziplin |
| `config/scoring.yaml` | Scoring-Gewichte, Sector-Factors, Stability-Thresholds |
| `config/system.yaml` | Technische Parameter, Cache, Provider |
| `config/watchlists.yaml` | Watchlist, Blacklist, Symbole nach Tier |

---

## Aktive Strategien

| Strategie | Beschreibung |
|-----------|-------------|
| **Pullback** | RSI-Divergenz + Support-Level nach Ruecksetzer im Aufwaertstrend |
| **Bounce** | Support-Bounce mit Candlestick-Bestaetigung und Volume |

---

## Disclaimer

Analyse dient informativen Zwecken. Finale Handelsentscheidung liegt beim Nutzer.
