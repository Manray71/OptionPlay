---
name: optionplay
description: "MCP-Server für Options-Trading-Analyse mit Bull-Put-Spread Strategien. Verwendet Marketdata.app API und optionale IBKR-Bridge. Trigger: 'Options-Analyse', 'Pullback-Scan', 'Bull-Put-Spread', 'VIX-Strategie', 'Earnings-Check', 'Options-Chain', 'Max Pain', 'IV-Rank', 'Spread-Kandidaten', 'was sagt der Markt', 'Trading-Setup'. Startet den MCP-Server bei ~/OptionPlay und verwendet dessen Tools."
---

# OptionPlay - Options Trading MCP Server v3.5.0

Bull-Put-Spread Analyse-System mit VIX-basierter automatischer Strategie-Auswahl.

## 🚀 Schnellstart

### Installation
```bash
cd ~/OptionPlay
python3 scripts/setup_claude.py
```
Das Setup-Skript:
- Prüft Python und Abhängigkeiten
- Konfiguriert Claude Desktop automatisch
- Validiert die Installation

### Claude Desktop neu starten
Nach dem Setup Claude Desktop neu starten.

---

## 📝 Workflow-Prompts (NEU!)

Vordefinierte Workflows für häufige Aufgaben:

| Prompt | Beschreibung |
|--------|-------------|
| `morning_scan` | Vollständiger Morgen-Workflow |
| `quick_scan` | Schneller Scan nach Kandidaten |
| `analyze_symbol` | Vollständige Symbol-Analyse |
| `earnings_check` | Earnings-Situation prüfen |
| `portfolio_review` | Portfolio-Übersicht |
| `setup_trade` | Vollständiges Trade-Setup |

### Verwendung in Claude Desktop
```
Führe den morning_scan Workflow aus
```
oder
```
Analysiere AAPL mit dem analyze_symbol Workflow
```

---

## 🔧 Tool-Aliase (NEU!)

Kürzere Namen für schnelleres Tippen:

| Alias | Voller Name |
|-------|-------------|
| `vix` | optionplay_vix |
| `scan` | optionplay_scan |
| `quote` | optionplay_quote |
| `options` | optionplay_options |
| `earnings` | optionplay_earnings |
| `analyze` | optionplay_analyze |
| `multi` | optionplay_scan_multi |
| `bounce` | optionplay_scan_bounce |
| `breakout` | optionplay_scan_breakout |
| `dip` | optionplay_scan_earnings_dip |
| `prefilter` | optionplay_earnings_prefilter |
| `strikes` | optionplay_recommend_strikes |
| `report` | optionplay_report |
| `portfolio` | optionplay_portfolio |
| `health` | optionplay_health |

---

## Projektstruktur

```
~/OptionPlay/
├── config/
│   ├── settings.yaml      # Haupt-Konfiguration
│   ├── strategies.yaml    # VIX-basierte Profile
│   └── watchlists.yaml    # 275 Symbole nach GICS-Sektoren
├── scripts/
│   └── setup_claude.py    # Automatisches Setup
├── src/
│   ├── mcp_main.py        # MCP Server mit Prompts & Aliases
│   └── mcp_server.py      # Tool-Implementierungen
├── .env                   # MARKETDATA_API_KEY
└── docs/ARCHITECTURE.md   # Vollständige Dokumentation
```

## Verfügbare MCP-Tools

### Kern-Funktionen

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_earnings_prefilter` | `prefilter` | Vorfilter nach Earnings (>45d) |
| `optionplay_vix` | `vix` | VIX mit Strategie-Empfehlung |
| `optionplay_scan` | `scan` | VIX-aware Pullback-Scan |
| `optionplay_scan_multi` | `multi` | Multi-Strategie-Scan |
| `optionplay_quote` | `quote` | Stock-Quote |
| `optionplay_options` | `options` | Options-Chain |
| `optionplay_earnings` | `earnings` | Earnings-Check |
| `optionplay_analyze` | `analyze` | Einzelanalyse |
| `optionplay_analyze_multi` | `analyze_multi` | Multi-Strategie-Analyse |
| `optionplay_recommend_strikes` | `strikes` | Strike-Empfehlungen |
| `optionplay_report` | `report` | PDF-Report mit Score-Breakdown, Options, News |

### IBKR Bridge (optional)

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_ibkr_status` | `ibkr` | Verbindungsstatus |
| `optionplay_ibkr_portfolio` | `ibkr_portfolio` | Positionen |
| `optionplay_ibkr_spreads` | `ibkr_spreads` | Spread-Positionen |
| `optionplay_ibkr_vix` | `ibkr_vix` | Live VIX |
| `optionplay_ibkr_quotes` | `ibkr_quotes` | Batch-Quotes |

---

## ⭐ OPTIMIERTER WORKFLOW

### Phase 1: Earnings Pre-Filter (IMMER ZUERST!)
```
> prefilter min_days=45
📅 Earnings Pre-Filter
  ✅ Safe: 180  |  ❌ Excluded: 85
```

### Phase 2: VIX & Strategie
```
> vix
VIX: 18.5 → STANDARD Profile
```

### Phase 3: Multi-Strategie-Scan
```
> multi symbols=[gefilterte] min_score=5
📊 Bull-Put-Spread: 12  |  🔄 Bounce: 8  |  🚀 Breakout: 3
```

### Phase 4: Detailanalyse
```
> analyze_multi symbol="AAPL"
📊 Bull-Put-Spread: 8.5/10 ✅
```

### Phase 5: Strike-Empfehlung
```
> strikes symbol="AAPL"
⭐ Short: $170 / Long: $165
   Credit: $1.25 | P(Profit): 72%
```

---

## VIX-Strategie-Profile

| VIX | Profil | Delta | Spread | Min-Score |
|-----|--------|-------|--------|-----------|
| <15 | Conservative | -0.20 | $2.50 | 6 |
| 15-20 | Standard | -0.30 | $5.00 | 5 |
| 20-30 | Aggressive | -0.35 | $5.00 | 4 |
| >30 | High Vol | -0.20 | $10.00 | 7 |

## Datenquellen

| Quelle | Daten | Priorität |
|--------|-------|-----------|
| Tradier | Historical, Options, Quotes | Primär |
| Marketdata.app | Fallback, VIX | Sekundär |
| Yahoo Finance | VIX, Earnings | Fallback |
| IBKR (optional) | Live Data, Portfolio | Premium |

---

## ⏰ ERINNERUNG: Marketdata.app entfernen

**Datum: 16. Februar 2026**

Nach 3 Wochen (ab 26. Januar 2026) kann Marketdata.app entfernt werden:
- [ ] Tradier als alleiniger Daten-Provider für Quotes, Options, Historical
- [ ] VIX nur über Yahoo Finance + IBKR
- [ ] Marketdata.app API-Key und Code entfernen
- [ ] `_ensure_connected()` auf Tradier umstellen
- [ ] Rate Limiter auf Tradier anpassen (120/min statt 100/min)

---

## Disclaimer

Analyse dient informativen Zwecken. Finale Handelsentscheidung liegt beim Nutzer.
