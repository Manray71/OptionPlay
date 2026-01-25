# OptionPlay - Architektur und Logik-Dokumentation

## Übersicht

OptionPlay ist ein Options-Trading-Analyse-System für Bull-Put-Spread Strategien.
Es identifiziert Aktien nach Pullbacks und generiert Trade-Empfehlungen.

---

## 1. Kern-Workflow (3 Stufen)

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  STUFE 1        │    │  STUFE 2        │    │  STUFE 3        │
│  Kandidaten-    │ => │  Filter &       │ => │  Options-       │
│  Screening      │    │  Validierung    │    │  Analyse        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
     │                       │                       │
     ▼                       ▼                       ▼
 Pullback-Score          Earnings-Check         Bid/Ask, IV,
 Technische Ind.         Preis-Filter           Greeks, Strikes
 Support/Resist.         Volumen-Check          Premium-Calc
```

### 1.1 Stufe 1: Kandidaten-Screening (Pullback-Analyse)

**Ziel:** Aktien identifizieren, die nach einem Pullback für Bull-Put-Spreads geeignet sind.

**Input:** Watchlist (275 Symbole, organisiert nach 11 GICS-Sektoren)

**Logik:**

```
Für jedes Symbol:
  1. Lade historische Daten (90 Tage)
  2. Berechne technische Indikatoren
  3. Vergebe Pullback-Score (0-10)
  4. Filtere nach Mindest-Score
```

**Pullback-Score Zusammensetzung:**

| Komponente | Max. Punkte | Beschreibung |
|------------|-------------|--------------|
| RSI-Signal | 3 | RSI < 30 = 3, RSI < 40 = 2, RSI < 50 = 1 |
| Support-Nähe | 2 | Preis nahe an Support-Level |
| Fibonacci-Retracement | 2 | Preis bei 38.2%, 50%, oder 61.8% Level |
| MA-Trend | 2 | Über 200-SMA aber unter 20-SMA (Dip im Aufwärtstrend) |
| Volumen-Anomalie | 1 | Überdurchschnittliches Volumen beim Pullback |

**Formel:**
```python
pullback_score = (
    rsi_score(rsi_14)                     # 0-3 Punkte
    + support_score(price, supports)      # 0-2 Punkte
    + fib_score(price, high, low)         # 0-2 Punkte
    + ma_trend_score(price, sma_20, sma_200)  # 0-2 Punkte
    + volume_score(volume, avg_volume)    # 0-1 Punkt
)
```

### 1.2 Stufe 2: Filter & Validierung

**Ziel:** Ungeeignete Kandidaten aussortieren.

**Filter (alle konfigurierbar in `settings.yaml`):**

| Filter | Standard | Beschreibung |
|--------|----------|--------------|
| Earnings-Ausschluss | 60 Tage | Keine Aktien mit Earnings in den nächsten X Tagen |
| Mindest-Preis | $20 | Penny Stocks ausschließen |
| Maximal-Preis | $500 | Zu teure Underlyings vermeiden |
| Mindest-Volumen | 500k | Liquidität sicherstellen |
| IV-Rang Minimum | 30% | Ausreichende Prämie |

**Earnings-Check (via yfinance):**
```python
def check_earnings(symbol):
    ticker = yf.Ticker(symbol)
    earnings_dates = ticker.earnings_dates
    next_earnings = earnings_dates.index[0]
    days_to_earnings = (next_earnings - today).days
    return days_to_earnings > EARNINGS_THRESHOLD
```

### 1.3 Stufe 3: Options-Analyse

**Ziel:** Konkrete Spread-Empfehlungen mit vollständigen Daten.

**Daten-Anforderungen:**

| Datenpunkt | Quelle | Verwendung |
|------------|--------|------------|
| Options-Chain | Tradier API | Strike-Auswahl |
| Bid/Ask | Tradier API | Premium-Berechnung |
| IV | Tradier/ORATS | IV-Rank Berechnung |
| Greeks | Tradier/ORATS | Delta-Targeting |
| Open Interest | Tradier API | Liquiditäts-Check |

**Strike-Auswahl Logik:**

```
Short Put Strike:
  - Delta zwischen -0.20 und -0.35 (konfigurierbar)
  - Unter Support-Level
  - Ausreichend Open Interest (>100)

Long Put Strike:
  - $5 oder $2.50 unter Short Strike (je nach Underlying-Preis)
  - Spread-Breite begrenzt Risiko
```

**Premium-Berechnung:**
```python
net_credit = short_put_bid - long_put_ask
spread_width = short_strike - long_strike
max_loss = (spread_width * 100) - net_credit
return_on_risk = net_credit / max_loss * 100
breakeven = short_strike - net_credit
```

---

## 2. VIX-Basierte Strategie-Auswahl

### 2.1 Übersicht

Das System wählt automatisch das optimale Strategie-Profil basierend auf dem aktuellen VIX.

```
┌─────────────────────────────────────────────────────────────────┐
│                     VIX STRATEGY SELECTOR                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   VIX < 15          VIX 15-20        VIX 20-30        VIX > 30  │
│   ┌──────────┐      ┌──────────┐     ┌──────────┐    ┌────────┐ │
│   │CONSERVAT.│      │ STANDARD │     │AGGRESSIVE│    │HIGH_VOL│ │
│   │          │      │          │     │          │    │        │ │
│   │ Delta    │      │ Delta    │     │ Delta    │    │ Delta  │ │
│   │ -0.20    │      │ -0.30    │     │ -0.35    │    │ -0.20  │ │
│   │          │      │          │     │          │    │        │ │
│   │ Spread   │      │ Spread   │     │ Spread   │    │ Spread │ │
│   │ $2.50    │      │ $5.00    │     │ $5.00    │    │ $10.00 │ │
│   └──────────┘      └──────────┘     └──────────┘    └────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Markt-Regimes

| VIX Range | Regime | Beschreibung |
|-----------|--------|--------------|
| 0 - 15 | `LOW_VOL` | Ruhiger Markt, niedrige Prämien |
| 15 - 20 | `NORMAL` | Normale Bedingungen |
| 20 - 30 | `ELEVATED` | Erhöhte Unsicherheit, attraktive Prämien |
| > 30 | `HIGH_VOL` | Crash-Modus, extreme Vorsicht |

### 2.3 Profil-Details

#### Conservative (VIX < 15)
```yaml
Logik: Niedrige Volatilität = niedrige Prämien
       → Konservativeres Delta für höhere Gewinnwahrscheinlichkeit
       → Engere Spreads da weniger Puffer nötig

Parameter:
  delta_target: -0.20    # ~80% Gewinnwahrscheinlichkeit
  spread_width: $2.50    # Geringeres Risiko
  min_score: 6           # Nur beste Setups
  earnings_buffer: 90d   # Extra vorsichtig
```

#### Standard (VIX 15-20)
```yaml
Logik: Normale Marktbedingungen
       → Standard-Parameter für Bull-Put-Spreads

Parameter:
  delta_target: -0.30    # ~70% Gewinnwahrscheinlichkeit
  spread_width: $5.00    # Ausgewogen
  min_score: 5           # Standard-Schwelle
  earnings_buffer: 60d   # Normal
```

#### Aggressive (VIX 20-30)
```yaml
Logik: Erhöhte Volatilität = attraktive Prämien
       → Aggressiveres Delta für höhere Prämien
       → Gute Zeit für Credit Spreads

Parameter:
  delta_target: -0.35    # ~65% Gewinnwahrscheinlichkeit
  spread_width: $5.00    # Standard Risiko
  min_score: 4           # Mehr Kandidaten
  earnings_buffer: 45d   # Weniger streng
```

#### High Volatility (VIX > 30)
```yaml
Logik: Crash-Modus = sehr hohe Prämien aber Gap-Risiko
       → Konservatives Delta trotz hoher Vol
       → Breite Spreads für mehr Puffer

Parameter:
  delta_target: -0.20    # Sicherheit zuerst
  spread_width: $10.00   # Großer Puffer
  min_score: 7           # Nur Top-Qualität
  earnings_buffer: 90d   # Maximum
```

### 2.4 Code-Beispiel

```python
from src.vix_strategy import get_strategy_for_vix, format_recommendation

# VIX abrufen (z.B. von Tradier)
current_vix = 22.5

# Strategie-Empfehlung holen
rec = get_strategy_for_vix(current_vix)

print(f"Profil: {rec.profile_name}")       # aggressive
print(f"Regime: {rec.regime.value}")        # elevated
print(f"Delta: {rec.delta_target}")         # -0.35
print(f"Spread: ${rec.spread_width}")       # $5.00

# Formatierte Ausgabe
print(format_recommendation(rec))
```

**Output:**
```
═══════════════════════════════════════════════════════════
  STRATEGIE-EMPFEHLUNG
═══════════════════════════════════════════════════════════
  VIX:          22.5
  Regime:       elevated
  Profil:       AGGRESSIVE
───────────────────────────────────────────────────────────
  Delta-Target: -0.35
  Spread-Breite: $5.00
  Min-Score:    4
  Earnings:     >45 Tage
───────────────────────────────────────────────────────────
  VIX bei 22.5 zeigt erhöhte Volatilität. Optionsprämien 
  sind attraktiv - aggressiveres Delta möglich.
───────────────────────────────────────────────────────────
  ⚠️ Erhöhte Vorsicht bei Positionsgrößen empfohlen
═══════════════════════════════════════════════════════════
```

### 2.5 Integration in Workflow

```
┌─────────────────┐
│  Start Scan     │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Hole VIX       │◄─── Tradier API oder Yahoo Finance
└────────┬────────┘
         ▼
┌─────────────────┐
│  VIX Strategy   │
│  Selector       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Lade Profil    │◄─── strategies.yaml
│  Parameter      │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Stufe 1-3      │
│  mit angepassten│
│  Parametern     │
└─────────────────┘
```

---

## 3. Datenfluss-Diagramm

```
                    ┌──────────────────┐
                    │   Watchlist      │
                    │   (275 Symbole)  │
                    └────────┬─────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────┐
│                    STUFE 1: SCREENING                   │
├────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌────────────┐  │
│  │ Tradier/    │    │ Technische  │    │ Pullback   │  │
│  │ Historische │ => │ Indikatoren │ => │ Score      │  │
│  │ Daten       │    │ berechnen   │    │ (0-10)     │  │
│  └─────────────┘    └─────────────┘    └────────────┘  │
└────────────────────────────┬───────────────────────────┘
                             │ Score >= Minimum (VIX-abhängig)
                             ▼
┌────────────────────────────────────────────────────────┐
│                    STUFE 2: FILTER                      │
├────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌────────────┐  │
│  │ yfinance    │    │ Preis &     │    │ Validierte │  │
│  │ Earnings    │ => │ Volumen     │ => │ Kandidaten │  │
│  │ Dates       │    │ Filter      │    │            │  │
│  └─────────────┘    └─────────────┘    └────────────┘  │
└────────────────────────────┬───────────────────────────┘
                             │ Alle Filter bestanden
                             ▼
┌────────────────────────────────────────────────────────┐
│                    STUFE 3: ANALYSE                     │
├────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌────────────┐  │
│  │ Tradier     │    │ Greeks &    │    │ Trade      │  │
│  │ Options     │ => │ Premium     │ => │ Empfehlung │  │
│  │ Chain       │    │ Berechnung  │    │            │  │
│  └─────────────┘    └─────────────┘    └────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## 4. Technische Indikatoren - Berechnungen

### 4.1 RSI (Relative Strength Index)
```python
def calculate_rsi(prices, period=14):
    # Wilder's Smoothing Method
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    # Wilder's Smoothing für Rest
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi
```

### 4.2 MACD (Moving Average Convergence Divergence)
```python
def calculate_macd(prices, fast=12, slow=26, signal=9):
    # EMA berechnen
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    
    # MACD Line
    macd_line = ema_fast - ema_slow
    
    # Signal Line
    signal_line = calculate_ema(macd_line, signal)
    
    # Histogram
    histogram = macd_line - signal_line
    
    # Crossover Detection
    crossover = detect_crossover(macd_line, signal_line)
    
    return macd_line[-1], signal_line[-1], histogram[-1], crossover
```

### 4.3 Stochastik Oszillator
```python
def calculate_stochastic(highs, lows, closes, k=14, d=3, smooth=3):
    # Raw %K
    raw_k = []
    for i in range(k-1, len(closes)):
        period_high = max(highs[i-k+1:i+1])
        period_low = min(lows[i-k+1:i+1])
        
        k_value = 100 * (closes[i] - period_low) / (period_high - period_low)
        raw_k.append(k_value)
    
    # Smoothed %K
    smooth_k = sma(raw_k, smooth)
    
    # %D (SMA of %K)
    d_values = sma(smooth_k, d)
    
    return smooth_k[-1], d_values[-1]
```

### 4.4 Support/Resistance Detection
```python
def find_support_levels(lows, window=20):
    supports = []
    for i in range(window, len(lows) - window):
        # Swing Low: Tiefster Punkt in Fenster
        if lows[i] == min(lows[i-window:i+window]):
            supports.append(lows[i])
    return sorted(set(supports))[-3:]  # Top 3 nearest
```

### 4.5 Fibonacci Retracement
```python
def calculate_fib_levels(high, low):
    diff = high - low
    return {
        '23.6%': high - (diff * 0.236),
        '38.2%': high - (diff * 0.382),
        '50.0%': high - (diff * 0.500),
        '61.8%': high - (diff * 0.618),
        '78.6%': high - (diff * 0.786)
    }
```

### 4.6 Moving Averages
```python
def calculate_sma(prices, period):
    return np.mean(prices[-period:])

def calculate_ema(prices, period):
    multiplier = 2 / (period + 1)
    ema = [np.mean(prices[:period])]  # Start mit SMA
    
    for price in prices[period:]:
        ema.append((price * multiplier) + (ema[-1] * (1 - multiplier)))
    
    return ema
```

---

## 5. Module-Übersicht

```
src/
├── __init__.py           # Exports
├── config_loader.py      # YAML → Python Dataclasses
├── pullback_analyzer.py  # Technische Analyse & Scoring
├── vix_strategy.py       # VIX-basierte Profil-Auswahl
└── data_providers/
    ├── __init__.py
    └── interface.py      # Abstrakte Provider-Schnittstelle
```

### 5.1 pullback_analyzer.py

**Klassen:**
- `PullbackAnalyzer` - Hauptanalyse-Klasse
- `PullbackCandidate` - Ergebnis-Container
- `ScoreBreakdown` - Detaillierte Score-Aufschlüsselung
- `TechnicalIndicators` - Alle Indikatoren zusammen
- `MACDResult` - MACD-Daten
- `StochasticResult` - Stochastik-Daten

### 5.2 vix_strategy.py

**Klassen:**
- `VIXStrategySelector` - Profil-Auswahl basierend auf VIX
- `MarketRegime` - Enum für Markt-Regimes
- `StrategyRecommendation` - Empfehlung mit Begründung

**Funktionen:**
- `get_strategy_for_vix(vix)` - Schnelle Profil-Auswahl
- `format_recommendation(rec)` - Formatierte Ausgabe

### 5.3 earnings_cache.py

**Klassen:**
- `EarningsCache` - Persistenter JSON-Cache für Earnings-Daten
- `EarningsFetcher` - Holt Earnings mit automatischem Caching
- `EarningsInfo` - Container für Earnings-Daten
- `EarningsSource` - Enum für Datenquellen

**Funktionen:**
- `get_earnings(symbol)` - Schnelle Earnings-Abfrage
- `is_earnings_safe(symbol, min_days)` - Prüft Earnings-Abstand
- `get_earnings_cache()` - Globale Cache-Instanz
- `get_earnings_fetcher()` - Globale Fetcher-Instanz

---

## 6. Earnings-Cache System

### 6.1 Übersicht

Der Earnings-Cache minimiert API-Calls und beschleunigt wiederholte Scans.

```
┌─────────────────────────────────────────────────────────────────┐
│                     EARNINGS CACHE FLOW                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Anfrage für "AAPL"                                            │
│          │                                                       │
│          ▼                                                       │
│   ┌──────────────┐                                              │
│   │ Cache prüfen │                                              │
│   └──────┬───────┘                                              │
│          │                                                       │
│          ├── Fresh? ──► Ja ──► Return cached EarningsInfo       │
│          │                                                       │
│          └── Nein/Missing                                        │
│                 │                                                │
│                 ▼                                                │
│          ┌──────────────┐                                       │
│          │   yfinance   │◄─── Primäre Quelle                    │
│          └──────┬───────┘                                       │
│                 │                                                │
│                 ├── Gefunden? ──► Ja ──► Cache & Return         │
│                 │                                                │
│                 └── Nein                                         │
│                        │                                         │
│                        ▼                                         │
│                 ┌──────────────┐                                │
│                 │ Yahoo Scrape │◄─── Fallback                   │
│                 └──────┬───────┘                                │
│                        │                                         │
│                        ▼                                         │
│                 Cache & Return (auch wenn None)                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Cache-Datei

**Speicherort:** `~/.optionplay/earnings_cache.json`

**Format:**
```json
{
  "AAPL": {
    "earnings_date": "2025-04-25",
    "days_to_earnings": 90,
    "source": "yfinance",
    "updated": "2025-01-24T10:30:00",
    "confirmed": false
  },
  "MSFT": {
    "earnings_date": null,
    "days_to_earnings": null,
    "source": "yahoo_scrape",
    "updated": "2025-01-24T10:31:00",
    "confirmed": false
  }
}
```

### 6.3 TTL (Time to Live)

- **Default:** 24 Stunden
- **Konfigurierbar:** `EarningsCache(max_age_hours=48)`
- **Stale Entries:** Werden bei nächster Anfrage automatisch aktualisiert

### 6.4 Code-Beispiele

```python
from src.earnings_cache import (
    get_earnings, 
    is_earnings_safe, 
    EarningsFetcher,
    EarningsCache
)

# Einfache Abfrage
info = get_earnings("AAPL")
print(f"AAPL Earnings: {info.earnings_date}")
print(f"Tage bis Earnings: {info.days_to_earnings}")
print(f"Sicher für 60d Trade: {info.is_safe(60)}")

# Quick-Check
if is_earnings_safe("AAPL", min_days=60):
    print("OK für Bull-Put-Spread")

# Bulk-Abfrage mit Fortschritt
fetcher = EarningsFetcher()

def progress(current, total, symbol):
    print(f"  {current}/{total}: {symbol}")

results = fetcher.fetch_many(
    ["AAPL", "MSFT", "GOOGL", "AMZN"],
    progress_callback=progress
)

# Filtern nach Earnings
safe, excluded = fetcher.filter_by_earnings(
    ["AAPL", "MSFT", "GOOGL"],
    min_days=60
)
print(f"Safe: {safe}")
print(f"Excluded: {excluded}")

# Cache-Statistiken
cache = EarningsCache()
stats = cache.stats()
print(f"Cache: {stats['fresh_entries']}/{stats['total_entries']} fresh")
```

### 6.5 Datenquellen

| Quelle | Priorität | Zuverlässigkeit | Geschwindigkeit |
|--------|-----------|-----------------|------------------|
| yfinance | 1 (primär) | Hoch | ~0.5s pro Symbol |
| Yahoo Scrape | 2 (fallback) | Mittel | ~1s pro Symbol |
| Tradier | 3 (geplant) | Hoch | ~0.2s pro Symbol |

---

## 7. IV-Cache System (Implied Volatility)

### 7.1 Übersicht

Der IV-Cache speichert 52-Wochen IV-History für schnelle IV-Rank Berechnungen.

**Warum nötig?**
- Tradier liefert nur aktuelle IV pro Option
- IV-Rank benötigt 52-Wochen-History
- Tägliches Sammeln der ATM-IV

### 7.2 IV-Rank vs IV-Perzentil

```
IV-Rank = (Current IV - 52w Low) / (52w High - 52w Low) × 100

  Zeigt: Wo liegt aktuelle IV im Range?
  Beispiel: IV-Rank 80% = IV nahe am 52-Wochen-Hoch

IV-Perzentil = % der Tage mit niedrigerer IV

  Zeigt: An wieviel % der Tage war IV niedriger?
  Beispiel: Perzentil 90% = Nur 10% der Tage hatten höhere IV
```

### 7.3 Cache-Datei

**Speicherort:** `~/.optionplay/iv_cache.json`

**Format:**
```json
{
  "AAPL": {
    "iv_history": [0.22, 0.24, 0.23, 0.28, ...],
    "iv_high": 0.45,
    "iv_low": 0.18,
    "data_points": 252,
    "source": "tradier",
    "updated": "2025-01-24T10:30:00"
  }
}
```

### 7.4 Code-Beispiele

```python
from src.iv_cache import (
    get_iv_rank,
    is_iv_elevated,
    IVCache,
    IVFetcher
)

# Quick IV-Rank Berechnung
iv_data = get_iv_rank("AAPL", current_iv=0.28)
print(f"IV-Rank: {iv_data.iv_rank}%")
print(f"IV-Perzentil: {iv_data.iv_percentile}%")
print(f"Status: {iv_data.iv_status()}")  # 'elevated', 'normal', 'low'

# Check für Credit-Spreads
if is_iv_elevated("AAPL", 0.35, threshold=50):
    print("Gute Zeit für Bull-Put-Spread")

# IV-History aus Options-Chain extrahieren
fetcher = IVFetcher()
atm_iv = fetcher.extract_atm_iv_from_chain(options_chain, underlying_price)
fetcher.cache.add_iv_point("AAPL", atm_iv)

# Cache-Statistiken
cache = IVCache()
stats = cache.stats()
print(f"Symbols: {stats['total_symbols']}")
print(f"With sufficient data: {stats['with_sufficient_data']}")
```

### 7.5 IV-Status Interpretation

| IV-Rank | Status | Bedeutung für Bull-Put-Spreads |
|---------|--------|--------------------------------|
| 70-100% | `very_high` | ⭐ Beste Prämien, aber Vorsicht |
| 50-70% | `elevated` | ✅ Gute Prämien |
| 30-50% | `normal` | ⚠️ Standard-Prämien |
| 0-30% | `low` | ❌ Niedrige Prämien, besser warten |

### 7.6 Integration in Workflow

```
┌─────────────────┐
│  Options-Chain  │
│  von Tradier    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ATM-IV         │
│  extrahieren    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  IV-Cache       │◄─── ~/.optionplay/iv_cache.json
│  aktualisieren  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  IV-Rank        │
│  berechnen      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Filter:        │
│  IV-Rank 30-80% │
└─────────────────┘
```

---

## 8. Max Pain Calculator

### 8.1 Was ist Max Pain?

Max Pain = Strike-Preis, bei dem Options-Käufer den maximalen Gesamtverlust erleiden.

**Theorie:** Der Preis tendiert zum Verfall hin zu diesem Level ("Pinning"), da Market Makers dort am meisten profitieren.

### 8.2 Berechnung

```
Für jeden möglichen Settlement-Preis:
  1. Berechne Verlust aller Call-Käufer (OTM Calls = wertlos)
  2. Berechne Verlust aller Put-Käufer (OTM Puts = wertlos)
  3. Summiere zu Total Pain

Max Pain = Strike mit höchstem Total Pain
```

### 8.3 Zusätzliche Metriken

| Metrik | Beschreibung | Verwendung |
|--------|--------------|------------|
| **Put Wall** | Strike mit höchstem Put OI | Support-Level |
| **Call Wall** | Strike mit höchstem Call OI | Resistance-Level |
| **PCR** | Put/Call Ratio (Total OI) | Sentiment-Indikator |

### 8.4 PCR Interpretation

| PCR | Sentiment | Bedeutung |
|-----|-----------|----------|
| > 1.2 | Bearish | Mehr Puts = Angst/Absicherung |
| 0.8 - 1.2 | Neutral | Ausgeglichen |
| < 0.8 | Bullish | Mehr Calls = Optimismus |

### 8.5 Code-Beispiele

```python
from src.max_pain import calculate_max_pain, format_max_pain_report

# Aus Tradier Options-Chain
result = calculate_max_pain(
    symbol="AAPL",
    options_chain=chain_data,  # Liste von Options-Dicts
    current_price=175.50
)

print(f"Max Pain: ${result.max_pain}")
print(f"Abstand: {result.distance_pct:+.1f}%")
print(f"Put Wall: ${result.put_wall}")
print(f"Call Wall: ${result.call_wall}")
print(f"PCR: {result.pcr} ({result.sentiment()})")

# Formatierter Report
print(format_max_pain_report(result))
```

**Output:**
```
═══════════════════════════════════════════════════════════
  MAX PAIN ANALYSE: AAPL
  Expiry: 20250321
═══════════════════════════════════════════════════════════

  Aktueller Preis:  $175.50
  Max Pain:         $172.50  (-1.7%) ↓

───────────────────────────────────────────────────────────
  WALLS (Höchstes Open Interest)
───────────────────────────────────────────────────────────
  Put Wall:   $170.00  (45,230 OI)
  Call Wall:  $180.00  (38,150 OI)
═══════════════════════════════════════════════════════════
```

### 8.6 Verwendung für Bull-Put-Spreads

| Situation | Empfehlung |
|-----------|------------|
| Preis > Max Pain | Vorsicht, könnte fallen |
| Preis < Max Pain | Bullish bias, könnte steigen |
| Short Put < Put Wall | Zusätzlicher Support |
| Short Put > Call Wall | Zu aggressiv |

---

## 9. API-Endpunkte (geplant)

### 9.1 scan_pullback_candidates
```
Input: symbols (optional), min_score (0-10), filter_earnings (bool)
Output: [{
  symbol, price, pullback_score, score_breakdown,
  technicals (rsi, macd, stoch, sma),
  support_levels, fib_levels,
  days_to_earnings, recommendation
}]
```

### 9.2 get_strategy_recommendation
```
Input: vix (optional, wird automatisch geholt wenn None)
Output: {
  profile_name, regime, vix_level,
  recommendations (delta, spread, min_score, earnings_buffer),
  reasoning, warnings
}
```

### 9.3 filter_candidates
```
Input: symbols, profile (auto/conservative/standard/aggressive/high_volatility), 
       min_price, max_price, exclude_earnings_days, top_n
Output: [{
  symbol, price, strategy_fit, indicators,
  earnings_safe, volume_ok
}]
```

### 9.4 get_options_chain
```
Input: symbols, dte_min, dte_max, right (P/C)
Output: [{
  symbol, expiry, strike, bid, ask, last,
  iv, delta, gamma, theta, vega, open_interest
}]
```

### 9.5 calculate_iv_rank
```
Input: symbols
Output: [{
  symbol, current_iv, iv_rank, iv_percentile,
  iv_high_52w, iv_low_52w
}]
```

---

## 10. Glossar

| Begriff | Definition |
|---------|------------|
| Bull-Put-Spread | Bullische Options-Strategie: Verkauf Put (höherer Strike) + Kauf Put (niedrigerer Strike) |
| DTE | Days to Expiration - Tage bis Verfall |
| EMA | Exponential Moving Average - Gewichteter gleitender Durchschnitt |
| IV | Implied Volatility - Erwartete Schwankungsbreite |
| IV-Rank | Position der aktuellen IV im 52-Wochen-Range (0-100%) |
| MACD | Moving Average Convergence Divergence - Trendfolge-Indikator |
| Max Pain | Strike-Preis, bei dem Options-Käufer den größten Verlust erleiden |
| Pullback | Temporärer Kursrückgang in einem übergeordneten Aufwärtstrend |
| RSI | Relative Strength Index - Momentum-Oszillator (0-100) |
| SMA | Simple Moving Average - Einfacher gleitender Durchschnitt |
| Stochastik | Momentum-Indikator der Überkauft/Überverkauft-Zonen zeigt |
| Support | Preislevel mit historischer Kaufnachfrage |
| VIX | CBOE Volatility Index - "Angstbarometer" des Marktes |
| GICS | Global Industry Classification Standard - Sektor-Klassifizierung |
