# OptionPlay - Multi-Provider Strategie

**Version:** 2.0.0  
**Datum:** 2026-01-24

---

## Provider-Übersicht

| Provider | Stärken | Schwächen | Rate Limits | Exklusiv-Features |
|----------|---------|-----------|-------------|-------------------|
| **Marketdata.app** | Schnell, günstig, Bulk-Daten | Keine Live-Execution, VIX-Probleme | 100/min | Bulk-Scans |
| **IBKR/TWS** | Präzise Live-Daten, Trade-Ready, News | Langsam, rate-limitiert | ~30/min | News, Max Pain, OI-Daten |
| **Yahoo Finance** | Kostenlos, zuverlässig für VIX | Verzögerte Daten | ~120/min | - |

---

## IBKR MCP Server Tools

Der IBKR MCP Server (`~/ib-mcp/ibkr_mcp_server.py`) bietet folgende exklusive Tools:

| Tool | Beschreibung | Rate Impact |
|------|--------------|-------------|
| `export_positions_and_prices` | Portfolio & Watchlist-Preise | Hoch (viele Abfragen) |
| `fetch_options_data` | Options-Chain mit Greeks | Mittel |
| `get_iv_rank` | IV-Rang & IV-Perzentil | Mittel |
| `fetch_pullback_candidates` | Pullback-Scan mit Support/Fib | Hoch |
| `filter_candidates` | VIX/RSI/MACD/Stoch Filter | Hoch |
| `fetch_max_pain` | Max Pain & Put/Call Walls | Hoch |
| **`fetch_news`** | **IBKR News Headlines** | Niedrig |
| `scan_all_sectors` | Alle 275 Symbole scannen | Sehr hoch |
| `recommend_strikes` | VIX-integrierte Strike-Empfehlung | Mittel |

### ⚠️ Rate Limit Hinweise

- **IBKR max ~30 Requests/Minute** - TWS kann bei zu vielen Anfragen instabil werden
- **Nie `scan_all_sectors` und andere Tools gleichzeitig**
- **News-Abruf ist günstig** - Kann für einzelne Symbole problemlos genutzt werden
- **Max Pain ist teuer** - Viele OI-Abfragen pro Symbol

---

## Routing-Strategie

### 1. Scans & Historische Daten → Marketdata.app
```
Bulk-Scans (275 Symbole): Marketdata.app
Historische Candles: Marketdata.app
IV-Rank Berechnung: Marketdata.app + Cache
```

### 2. VIX → IBKR (primär) → Yahoo Finance (Fallback)
```
VIX-Abruf: IBKR (wenn TWS läuft) → Yahoo Finance → Marketdata.app
Grund: IBKR liefert Live-VIX, Marketdata.app oft 404
```

### 3. News → NUR IBKR
```
News Headlines: Nur über IBKR verfügbar
Nutze: fetch_news Tool mit Symbol-Liste
```

### 4. Earnings → Multi-Source mit Cache
```
1. Cache prüfen (24h TTL)
2. Yahoo Finance direkt
3. Marketdata.app
4. yfinance Library
```

### 5. Max Pain & OI-Daten → NUR IBKR
```
Open Interest Daten: Nur über IBKR
Max Pain Berechnung: Nur über IBKR
Put/Call Walls: Nur über IBKR
```

### 6. Strike-Empfehlung → IBKR (bevorzugt)
```
VIX-integrierte Empfehlung: IBKR recommend_strikes Tool
Enthält: VIX-Regime, OTM%, Spread-Width, Credit-Ziele
```

### 7. Finale Trade-Validierung → IBKR
```
Nur für:
- Finale Preis-Validierung vor Trade-Eintrag
- Options-Chain mit präzisen Greeks
- Live-Daten während Market Hours
```

---

## Empfohlener Workflow

### A) Morgen-Scan (TWS optional)

**Ohne TWS:**
```
1. VIX von Yahoo           → Strategie bestimmen
2. Watchlist via Marketdata → Pullback-Kandidaten
3. Earnings filtern         → Sichere Kandidaten
```

**Mit TWS:**
```
1. VIX von IBKR (Live)      → Strategie bestimmen
2. Watchlist via Marketdata → Pullback-Kandidaten (schneller)
3. Earnings filtern         → Sichere Kandidaten
4. News-Check via IBKR      → Event-Risiken prüfen
5. Top 5 via IBKR validieren → Finale Liste mit Greeks
```

### B) Trade-Vorbereitung (TWS empfohlen)

```
1. Symbol analysieren (Marketdata) → Score, Technicals
2. Earnings prüfen (Cache)         → Safety Check
3. News prüfen (IBKR)              → Event-Risiken
4. Max Pain (IBKR)                 → Price Magnet
5. Options-Chain (IBKR)            → Präzise Greeks
6. Strike-Empfehlung (IBKR)        → VIX-optimiertes Setup
```

### C) Intraday-Monitoring

```
- Watchlist-Preise: Marketdata.app (alle 5 min)
- Aktive Positionen: IBKR (bei Bedarf)
- VIX-Updates: IBKR oder Yahoo (alle 5 min)
- Breaking News: IBKR fetch_news (bei Verdacht)
```

---

## Implementation

### ProviderOrchestrator (`src/utils/provider_orchestrator.py`)

```python
from src.utils import get_orchestrator, ProviderType, DataType

orchestrator = get_orchestrator()

# IBKR aktivieren wenn TWS verbunden
orchestrator.enable_ibkr(connected=True)

# Automatisches Routing
best_provider = orchestrator.get_best_provider(DataType.QUOTE)

# Für Scans immer Marketdata
scan_provider = orchestrator.get_scan_provider()  # → MARKETDATA

# Für News nur IBKR
news_provider = orchestrator.get_best_provider(DataType.NEWS)  # → IBKR oder None

# Status abrufen
status = orchestrator.get_provider_status()
```

---

## Rate Limit Empfehlungen

### Marketdata.app (100/min)
- Bulk-Scan mit 20 Symbolen: ~1 min
- Voller Scan (275 Symbole): ~3-4 min
- Mit Rate Limiter: Automatische Drosselung

### IBKR/TWS (~30/min, KRITISCH)
- **Schone TWS!** Zu viele Anfragen = Instabilität
- Nur für finale Validierung nutzen
- Max 5-10 Symbole pro Detail-Durchlauf
- Pausen zwischen Anfragen: 2-3 Sekunden
- **News-Abruf ist OK** - Günstige Operation
- **Max Pain ist TEUER** - Viele OI-Abfragen

### Yahoo Finance (120/min)
- VIX: 1 Anfrage alle 5 Minuten (gecacht)
- Earnings: Mit 24h Cache, selten direkt

---

## Best Practices

1. **IBKR schonen**
   - Nie für Bulk-Scans
   - Scans via Marketdata, dann Top 5 via IBKR validieren
   - News nur bei Bedarf (vor Trade, bei Verdacht)
   - Max ~500 Requests/Tag für IBKR

2. **Cache nutzen**
   - Earnings: 24h Cache
   - IV-History: 1h Cache (IBKR) / 14 Tage (Marketdata)
   - VIX: 5 Minuten Cache

3. **Fallbacks einplanen**
   - Immer mehrere Provider pro Datentyp
   - Graceful Degradation bei Fehlern
   - TWS nicht verfügbar? → Scan trotzdem möglich

4. **Monitoring**
   - `health_check()` für OptionPlay Server-Status
   - `format_provider_status()` für Provider-Details

---

## Zusammenfassung: Wann welchen Provider?

| Use Case | Provider | Begründung |
|----------|----------|------------|
| **Bulk-Scans** | Marketdata.app | Schnell, hohe Rate Limits |
| **Historische Daten** | Marketdata.app | Kosteneffizient |
| **VIX** | IBKR → Yahoo | Live-Daten, zuverlässig |
| **Earnings** | Cache → Yahoo | Multi-Source |
| **News** | **IBKR only** | Exklusiv-Feature |
| **Max Pain / OI** | **IBKR only** | Exklusiv-Feature |
| **Strike-Empfehlung** | IBKR | VIX-integriert |
| **Finale Validierung** | IBKR | Präzise Live-Daten |
| **Live Options-Chain** | IBKR | Exakte Greeks |
