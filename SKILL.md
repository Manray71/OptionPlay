---
name: optionplay
description: "MCP-Server für Options-Trading-Analyse mit Bull-Put-Spread Strategien. Verwendet Marketdata.app API und optionale IBKR-Bridge. Trigger: 'Options-Analyse', 'Pullback-Scan', 'Bull-Put-Spread', 'VIX-Strategie', 'Earnings-Check', 'Options-Chain', 'Max Pain', 'IV-Rank', 'Spread-Kandidaten', 'was sagt der Markt', 'Trading-Setup'. Startet den MCP-Server bei ~/OptionPlay und verwendet dessen Tools."
---

# OptionPlay - Options Trading MCP Server v3.4.0

Bull-Put-Spread Analyse-System mit VIX-basierter automatischer Strategie-Auswahl.

## Projektstruktur

```
~/OptionPlay/
├── config/
│   ├── settings.yaml      # Haupt-Konfiguration
│   ├── strategies.yaml    # VIX-basierte Profile
│   └── watchlists.yaml    # 275 Symbole nach GICS-Sektoren
├── src/
│   ├── mcp_server.py      # MCP Server v3.4.0
│   └── strike_recommender.py  # Strike-Empfehlungen
├── .env                   # MARKETDATA_API_KEY
└── docs/ARCHITECTURE.md   # Vollständige Dokumentation
```

## Verfügbare MCP-Tools

### Kern-Funktionen

| Tool | Beschreibung |
|------|-------------|
| `optionplay_earnings_prefilter` | Vorfilter nach Earnings (>45d) - ERSTER Schritt! |
| `optionplay_vix` | Aktueller VIX mit Strategie-Empfehlung |
| `optionplay_scan` | VIX-aware Pullback-Scan |
| `optionplay_scan_multi` | Multi-Strategie-Scan (alle Strategien) |
| `optionplay_quote` | Stock-Quote für Symbol |
| `optionplay_options` | Options-Chain (DTE, Delta, IV) |
| `optionplay_earnings` | Earnings-Check für einzelnes Symbol |
| `optionplay_analyze` | Vollständige Einzelanalyse |
| `optionplay_analyze_multi` | Multi-Strategie-Analyse für Symbol |
| `optionplay_recommend_strikes` | **NEU** Strike-Empfehlungen für Bull-Put-Spreads |

### IBKR Bridge (optional, wenn TWS läuft)

| Tool | Beschreibung |
|------|-------------|
| `optionplay_ibkr_status` | IBKR-Verbindungsstatus |
| `optionplay_ibkr_portfolio` | Portfolio-Positionen |
| `optionplay_ibkr_spreads` | Identifizierte Spread-Positionen |
| `optionplay_ibkr_vix` | Live VIX von IBKR |
| `optionplay_ibkr_quotes` | Batch-Quotes für Watchlist |

---

## ⭐ OPTIMIERTER WORKFLOW (NEU)

### Phase 1: Earnings Pre-Filter (IMMER ZUERST!)
```
> optionplay_earnings_prefilter min_days=45
📅 Earnings Pre-Filter
Summary:
  Total Symbols: 275
  ✅ Safe (>= 45d): 180
  ❌ Excluded (< 45d): 85
  ⚠️ Unknown: 10
Cache: 4 Wochen TTL
```
**Wichtig:** Dieser Schritt verwendet gecachte Earnings-Daten (4 Wochen gültig) und filtert Symbole mit bevorstehenden Earnings aus, BEVOR teure API-Calls für Kursdaten gemacht werden.

### Phase 2: VIX & Strategie-Check
```
> optionplay_vix
VIX: 18.5 → Profil: STANDARD
Delta: -0.30, Spread: $5, Min-Score: 5, Earnings-Buffer: 60d
```

### Phase 3: Multi-Strategie-Scan (mit gefilterter Liste)
```
> optionplay_scan_multi symbols=[gefilterte_symbole] min_score=5
📊 Multi-Strategy Scan
Strategy Summary:
  📊 Bull-Put-Spread: 12 candidates
  🔄 Support Bounce: 8 candidates
  🚀 ATH Breakout: 3 candidates
```

### Phase 4: Detaillierte Analyse der Top-Kandidaten
```
> optionplay_analyze_multi symbol="AAPL"
📊 Multi-Strategy Analysis: AAPL
  📊 Bull-Put-Spread: 8.5/10 ✅ Strong
  🔄 Support Bounce: 6.2/10 🟡 Moderate
```

### Phase 5: Earnings-Verifikation (>60 Tage)
```
> optionplay_earnings symbol="AAPL" min_days=60
✅ SAFE: 86 Tage bis Earnings
```

### Phase 6: Options-Chain
```
> optionplay_options symbol="AAPL" dte_min=30 dte_max=60 right="P"
Strikes nahe ATM mit Bid/Ask, IV, Delta, OI
```

### Phase 7: Strike-Empfehlung (NEU!)
```
> optionplay_recommend_strikes symbol="AAPL" dte_min=30 dte_max=60
🎯 Strike Recommendation: AAPL
Current Price: $182.50

📊 Support Levels: $175.00, $170.00, $165.00
📐 Fibonacci: 38.2%: $173.50, 50%: $168.00

⭐ Primary Recommendation:
Short Strike: $170.00
Long Strike: $165.00
Spread Width: $5.00
Reason: Support @ $170.00 + Fib-bestätigt

Expected Metrics:
Est. Credit: $1.25
Max Profit: $125.00
Max Loss: $375.00
P(Profit): 72%

Quality: 🟢 EXCELLENT (78/100)
```

---

## Workflow-Regeln

### Earnings-Filter-Kriterien
1. **Pre-Filter (Phase 1):** min_days=45 (Vorfilter)
2. **Finaler Check (Phase 5):** min_days=60 (hartes Kriterium für Trade)

### Warum zwei Filter?
- **45 Tage Pre-Filter:** Reduziert Watchlist von 275 auf ~180 Symbole
- **60 Tage Final-Check:** Stellt sicher, dass kein Trade mit Earnings < 60 Tagen eingegangen wird
- Symbole zwischen 45-60 Tagen werden gescannt, aber beim finalen Check aussortiert

### Cache-Strategie
| Daten | Cache-Dauer | Grund |
|-------|-------------|-------|
| Earnings | 4 Wochen | Ändern sich selten |
| VIX | 5 Minuten | Volatil |
| Quotes | 5 Minuten | Marktdaten |
| Historical | 5 Minuten | Für technische Analyse |

---

## VIX-Strategie-Profile

| VIX | Profil | Delta | Spread | Min-Score | Earnings |
|-----|--------|-------|--------|-----------|----------|
| <15 | Conservative | -0.20 | $2.50 | 6 | 90d |
| 15-20 | Standard | -0.30 | $5.00 | 5 | 60d |
| 20-30 | Aggressive | -0.35 | $5.00 | 4 | 45d |
| >30 | High Vol | -0.20 | $10.00 | 7 | 90d |

## Pullback-Score (0-10)

| Komponente | Max | Kriterien |
|------------|-----|-----------|
| RSI | 3 | <30=3, <40=2, <50=1 |
| Support-Nähe | 2 | ±3%=2, ±5%=1 |
| Fibonacci | 2 | 61.8%/50%=2, 38.2%=1 |
| MA-Trend | 2 | Preis > SMA200 aber < SMA20 |
| Volumen | 1 | >1.5x Durchschnitt |

## Wichtige Filter

- **Earnings**: Keine Trades innerhalb X Tage vor Earnings (VIX-abhängig)
- **IV-Rank**: 30-80% (konfigurierbar in settings.yaml)
- **Preis**: $20-$500
- **Volumen**: >500k täglich

## Konfiguration anpassen

Alle Parameter in `~/OptionPlay/config/settings.yaml`:
- Scanner: `scanner.min_score`, `scanner.enable_iv_filter`
- Earnings: `filters.earnings.exclude_days_before`
- Options: `options_analysis.short_put.delta_target`

## Datenquellen

| Quelle | Daten | Priorität |
|--------|-------|-----------|
| Marketdata.app | Quotes, Options, Historical | Primär |
| Yahoo Finance | VIX (Fallback), Earnings | Sekundär |
| IBKR (optional) | News, Max Pain, Live VIX | Premium |

## Detaillierte Referenzen

- **Score-Breakdown**: `references/scoring.md`
- **Strategy-Profile**: `references/profiles/`
- **Spread-Typen**: `references/spread-types.md`
- **API-Dokumentation**: `~/OptionPlay/docs/ARCHITECTURE.md`

## Disclaimer

Analyse dient informativen Zwecken. Finale Handelsentscheidung liegt beim Nutzer.
