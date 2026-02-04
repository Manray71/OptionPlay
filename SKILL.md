---
name: optionplay
description: "MCP-Server für Options-Trading mit Bull-Put-Spread Strategien. 3 Jobs: Daily Picks, Trade Validator, Position Manager. Verwendet Tradier + Marketdata.app API + optionale IBKR-Bridge. Trigger: 'Options-Analyse', 'Pullback-Scan', 'Bull-Put-Spread', 'VIX-Strategie', 'Earnings-Check', 'Options-Chain', 'Max Pain', 'IV-Rank', 'Spread-Kandidaten', 'was sagt der Markt', 'Trading-Setup', 'Daily Picks', 'Zeig mir die heutigen Picks', 'Wie stehen meine Positionen', 'Kann ich X traden'."
---

# OptionPlay - Trading Assistant MCP Server

Bull-Put-Spread Trading-Assistent mit 3 klar definierten Jobs.

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
2. prefilter min_days=60         → Earnings-sichere Symbole
3. daily min_stability=70        → Top-Picks mit Strikes
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
| `optionplay_events` | `events` | Anstehende Markt-Events (FOMC, OPEX, CPI) |

### Scanning & Picks

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_daily_picks` | `daily` / `picks` | **Top-Empfehlungen mit Strikes** |
| `optionplay_scan_multi` | `multi` | Multi-Strategie-Scan |
| `optionplay_scan` | `scan` | Pullback-Kandidaten |
| `optionplay_scan_bounce` | `bounce` | Support-Bounce-Kandidaten |
| `optionplay_scan_breakout` | `breakout` | ATH-Breakout-Kandidaten |
| `optionplay_scan_earnings_dip` | `dip` | Earnings-Dip-Kandidaten |
| `optionplay_earnings_prefilter` | `prefilter` | Earnings-Vorfilter (>60 Tage) |

### Einzel-Analyse

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_analyze` | `analyze` | Vollständige Symbol-Analyse |
| `optionplay_analyze_multi` | `analyze_multi` | Multi-Strategie für ein Symbol |
| `optionplay_quote` | `quote` | Aktueller Kurs |
| `optionplay_options` | `options` | Options-Chain mit Greeks |
| `optionplay_earnings` | `earnings` | Earnings-Check |
| `optionplay_expirations` | `expirations` | Verfügbare Verfallstermine |
| `optionplay_historical` | `historical` | Historische Kursdaten |
| `optionplay_validate` | `validate` | Symbol-Validierung (Earnings + Events) |

### Strikes & Risiko

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_recommend_strikes` | `strikes` | Optimale Strike-Empfehlungen |
| `optionplay_spread_analysis` | `spread_analysis` | Spread-P&L-Analyse |
| `optionplay_monte_carlo` | `monte_carlo` | Monte-Carlo-Simulation |
| `optionplay_position_size` | `position_size` | Kelly-Criterion Position Sizing |
| `optionplay_stop_loss` | `stop_loss` | Stop-Loss-Berechnung |
| `optionplay_spread_width` | `spread_width` | Optimale Spread-Breite |
| `optionplay_max_pain` | `max_pain` | Max-Pain-Level |

### Portfolio (internes Tracking)

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_portfolio` | `portfolio` | Portfolio-Zusammenfassung |
| `optionplay_portfolio_positions` | `pf_positions` | Positionen (open/closed/all) |
| `optionplay_portfolio_add` | `pf_add` | Position hinzufügen |
| `optionplay_portfolio_close` | `pf_close` | Position schließen |
| `optionplay_portfolio_expire` | `pf_expire` | Position verfallen lassen |
| `optionplay_portfolio_expiring` | `pf_expiring` | Bald auslaufende Positionen |
| `optionplay_portfolio_check` | `pf_check` | Portfolio-Limit-Check |
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

---

## Datenquellen

| Quelle | Daten | Status |
|--------|-------|--------|
| Tradier | Historical, Options, Quotes | Primär |
| Marketdata.app | Quotes, Options, VIX | Sekundär (Abo läuft, Kündigung prüfen ~März 2026) |
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
│   └── watchlists.yaml        # Watchlist (275 Symbole)
├── docs/
│   ├── PLAYBOOK.md            # DAS Regelwerk (Entry, Exit, VIX, Disziplin)
│   └── ARCHITECTURE.md        # System-Architektur
└── src/                       # Siehe ARCHITECTURE.md für Modul-Details
```

---

## Disclaimer

Analyse dient informativen Zwecken. Finale Handelsentscheidung liegt beim Nutzer.
