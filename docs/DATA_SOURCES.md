# OptionPlay - Datenquellen

## Übersicht: Benötigte Daten

| Datentyp | Verwendung | Kritikalität | Empfohlene Quelle |
|----------|------------|--------------|-------------------|
| Realtime Quotes | Aktuelle Preise | Mittel | Tradier |
| Options Chains | Strike-Auswahl | Hoch | Tradier |
| Options Greeks | Delta-Targeting | Hoch | Tradier/ORATS |
| Implied Volatility | IV-Rank | Hoch | Tradier/Berechnet |
| Historical OHLCV | Technische Analyse | Mittel | Tradier/yfinance |
| Earnings Dates | Filter | Kritisch | yfinance |
| Open Interest | Liquidität | Mittel | Tradier |
| **Hist. Options** | Backtesting | Optional | Marketdata.app |

---

## Primäre Datenquellen

### 1. Tradier API ⭐ EMPFOHLEN FÜR LIVE-TRADING
**Website**: https://tradier.com

**Warum Tradier?**
- **KOSTENLOS** mit Brokerage-Account (auch Paper Trading!)
- Vollständige Options-Chains mit Greeks (via ORATS Partnership)
- Realtime-Daten für alle Account-Holder
- Sehr stabile API, gut dokumentiert
- Trading-fähig - gleiche API für Daten UND Orders

**Endpunkte:**
```
GET /v1/markets/quotes          # Realtime Quotes
GET /v1/markets/options/chains  # Options mit Greeks
GET /v1/markets/options/expirations
GET /v1/markets/options/strikes
GET /v1/markets/history         # Historische Daten
```

**Kosten:**
| Plan | Preis | Features |
|------|-------|----------|
| Standard | **$0/mo** | Realtime, Options, Greeks |
| Pro | $10/mo | Zusätzliche Features |

**Setup:**
1. Account erstellen: https://tradier.com
2. API-Token: https://dash.tradier.com/settings/api
3. Sandbox für Testing: `https://sandbox.tradier.com/v1`

---

### 2. Marketdata.app ⭐ EMPFOHLEN FÜR BACKTESTING
**Website**: https://www.marketdata.app

**Warum Marketdata.app?**
- **Historische Options-Daten seit 2005** - unschlagbar für Backtesting
- Google Sheets Add-on - sehr praktisch
- 30 Tage Free Trial ohne Kreditkarte
- Keine Brokerage-Account nötig
- Gut dokumentierte REST API

**Endpunkte:**
```
GET /v1/options/quotes/{symbol}     # Options Quote
GET /v1/options/chain/{symbol}      # Options Chain
GET /v1/stocks/candles/{resolution}/{symbol}  # Historical
```

**Kosten:**
| Plan | Preis (annual) | Preis (monthly) | Features |
|------|----------------|-----------------|----------|
| Free | $0 | $0 | 100 req/Tag, 24h delayed |
| Starter | $12/mo | $30/mo | 10k req/Tag, RT Stocks, 15min Options |
| Trader | $30/mo | $75/mo | 100k req/Tag, RT Options |
| Quant | $125/mo | - | 10k req/min |

---

### 3. Yahoo Finance (yfinance) - EARNINGS
**Website**: https://pypi.org/project/yfinance/

**Verwendung:**
- ✅ Earnings Dates (zuverlässig)
- ✅ Historische Preise (Backup)
- ⚠️ Options Chains (nur Fallback)

**Installation:**
```bash
pip install yfinance
```

**Kosten:** Kostenlos (inoffiziell)

---

## Tradier vs. Marketdata.app - Direktvergleich

### Preisvergleich

| Feature | Tradier | Marketdata.app |
|---------|---------|----------------|
| **Kostenlos** | ✅ Unbegrenzt (mit Account) | 100 req/Tag, 24h delayed |
| **Realtime Options** | ✅ $0 | Ab $30/mo (annual) |
| **Trading möglich** | ✅ Ja | ❌ Nein (nur Daten) |
| **Brokerage nötig** | ✅ Ja (Paper OK) | ❌ Nein |
| **Hist. Options** | Begrenzt | ✅ Seit 2005 |
| **Google Sheets** | ❌ Nein | ✅ Add-on |

### Options-Daten Vergleich

| Feature | Tradier | Marketdata.app |
|---------|---------|----------------|
| Greeks | ✅ Via ORATS | ✅ Vollständig |
| IV | ✅ | ✅ |
| Open Interest | ✅ | ✅ |
| Chains | ✅ Vollständig | ✅ OPRA Feed |
| Historie | Begrenzt | **Seit 2005** |

### Empfehlung nach Use Case

| Use Case | Empfehlung |
|----------|------------|
| **Live-Trading Analyse** | **Tradier** (kostenlos + Trading) |
| **Backtesting** | **Marketdata.app** (Historie seit 2005) |
| **Budget-Lösung** | **Tradier** ($0) |
| **Google Sheets User** | **Marketdata.app** |
| **Beides** | Tradier (live) + Marketdata Starter ($12/mo) |

---

## Alternative Datenquellen

### 4. Massive.com (ehem. Polygon.io)
**Website**: https://massive.com

| Plan | Preis | Features |
|------|-------|----------|
| Basic | $0/mo | EOD, 2 Jahre, 5 API/min |
| Starter | $29/mo | 15min delayed, Greeks/IV |
| Developer | $79/mo | 4 Jahre Historie |
| Advanced | $199/mo | Realtime, 5+ Jahre |

---

### 5. ORATS ⭐ PREMIUM QUALITY
**Website**: https://orats.com

**Spezialisiert auf Options-Daten mit proprietären Indikatoren!**

| Plan | Preis | Features |
|------|-------|----------|
| Delayed | $99/mo | 20k req/mo, EOD, IV Rank |
| Live | $199/mo | 100k req/mo, Realtime |
| Intraday | $399/mo | 1M req/mo, 1-min Daten |

**Einzigartige Features:**
- Smoothed Market Values (SMV) - bereinigte Greeks
- IV Rank und IV Percentile vorberechnet
- Ex-Earnings IV (IV ohne Earnings-Effekt)
- 15+ Jahre historische Daten (seit 2007)

---

## Empfohlene Kombinationen für OptionPlay

### Option A: Kostenlos ($0/mo)
| Datentyp | Quelle |
|----------|--------|
| Live Quotes | Tradier |
| Options Chains | Tradier |
| Greeks | Tradier/ORATS |
| Historical Stocks | yfinance |
| Earnings | yfinance |
| IV Rank | Berechnet |

**Voraussetzung:** Tradier Paper Trading Account

---

### Option B: Mit Backtesting ($12/mo)
| Datentyp | Quelle |
|----------|--------|
| Live Quotes | Tradier |
| Options Chains | Tradier |
| Greeks | Tradier |
| **Hist. Options** | **Marketdata.app Starter** |
| Earnings | yfinance |

---

### Option C: Premium ($200/mo)
| Datentyp | Quelle |
|----------|--------|
| Alles | ORATS Live |

---

## Setup-Anleitungen

### Tradier Setup

```bash
# .env
TRADIER_API_KEY=your_sandbox_token
TRADIER_BASE_URL=https://sandbox.tradier.com/v1
```

```python
import requests

response = requests.get(
    "https://sandbox.tradier.com/v1/markets/quotes",
    params={"symbols": "AAPL"},
    headers={
        "Authorization": "Bearer YOUR_TOKEN",
        "Accept": "application/json"
    }
)
```

### Marketdata.app Setup

```bash
# .env
MARKETDATA_API_KEY=your_token
```

```python
import requests

response = requests.get(
    "https://api.marketdata.app/v1/options/chain/AAPL/",
    headers={"Authorization": "Token YOUR_TOKEN"}
)
```

---

## Fazit

**Für OptionPlay Bull-Put-Spread Screening:**

1. **Primär**: Tradier (kostenlos) + yfinance für Earnings
2. **Optional**: Marketdata.app Starter ($12/mo) für Backtesting
3. **Premium**: ORATS Live ($199) für beste Datenqualität

Die Kombination Tradier + yfinance löst die IBKR-Probleme:
- ✅ Keine Null-Bid/Ask mehr
- ✅ Stabile API ohne Timeouts
- ✅ Greeks direkt verfügbar
