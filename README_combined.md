# OptionPlay — Kombinierte Projektdokumentation

[![CI OptionPlay](https://github.com/Manray71/OptionPlay/actions/workflows/ci.yml/badge.svg)](https://github.com/Manray71/OptionPlay/actions/workflows/ci.yml)
[![CI OptionPlay-Web](https://github.com/Manray71/OptionPlay-Web/actions/workflows/ci.yml/badge.svg)](https://github.com/Manray71/OptionPlay-Web/actions/workflows/ci.yml)

---

## Inhaltsverzeichnis

1. [Projektübersicht](#projektübersicht)
2. [Gesamtarchitektur](#gesamtarchitektur)
3. [OptionPlay — MCP Backend](#optionplay--mcp-backend)
   - [Features](#features-backend)
   - [Tech-Stack Backend](#tech-stack-backend)
   - [Projektstruktur Backend](#projektstruktur-backend)
   - [Installation Backend](#installation-backend)
   - [Konfiguration Backend](#konfiguration-backend)
   - [Verwendung Backend](#verwendung-backend)
4. [OptionPlay-Web — React + FastAPI Frontend](#optionplay-web--react--fastapi-frontend)
   - [Features Frontend](#features-frontend)
   - [Tech-Stack Frontend](#tech-stack-frontend)
   - [Projektstruktur Frontend](#projektstruktur-frontend)
   - [Installation Frontend](#installation-frontend)
   - [Konfiguration Frontend](#konfiguration-frontend)
   - [Verwendung Frontend](#verwendung-frontend)
5. [Datenbank](#datenbank)
6. [Trading-Strategien & Backtesting](#trading-strategien--backtesting)
7. [Datenprovider](#datenprovider)
8. [Sicherheit](#sicherheit)
9. [Lizenz](#lizenz)

---

## Projektübersicht

**OptionPlay** ist ein quantitatives Optionshandels-Analyse-System, spezialisiert auf **Bull-Put-Credit-Spreads**. Es besteht aus zwei eng verzahnten Projekten:

| Projekt | Beschreibung | Repo |
|---------|-------------|------|
| **OptionPlay** v5.0.0 | Python-Backend: Multi-Strategie-Scanner, ML-Scoring, VIX-Regime-Logik, MCP-Server für Claude Desktop | [Manray71/OptionPlay](https://github.com/Manray71/OptionPlay) |
| **OptionPlay-Web** v1.0.0 | React-Frontend + FastAPI-Backend: Dashboard, Scanner-UI, Analyse, Portfolio, Shadow-Tracker, Admin | [Manray71/OptionPlay-Web](https://github.com/Manray71/OptionPlay-Web) |

### Walk-Forward Backtesting-Ergebnisse (Out-of-Sample, 2020–2025)

| Strategie | Win Rate | OOS-Trades | WF-Schwelle |
|-----------|----------|-----------|-------------|
| Pullback | 88,3 % | — | 4,5 |
| Support Bounce | 91,6 % | — | 6,0 |
| **Gesamt** | **89,1 %** | **4.112** | — |

*Walk-Forward-Training: 18/6/6-Monate-Fenster, 7 Epochen, 2020–2025*

---

## Gesamtarchitektur

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BENUTZER-SCHNITTSTELLEN                            │
│                                                                              │
│   ┌─────────────────────────────┐     ┌──────────────────────────────────┐  │
│   │     Claude Desktop (MCP)    │     │   Browser (React SPA)            │  │
│   │   53 Tools via MCP Protocol │     │   http://localhost:5173          │  │
│   └──────────────┬──────────────┘     └────────────────┬─────────────────┘  │
│                  │                                      │                    │
└──────────────────┼──────────────────────────────────────┼────────────────────┘
                   │                                      │
                   ▼                                      ▼
┌──────────────────────────────┐     ┌──────────────────────────────────────┐
│     OptionPlay (MCP Server)  │     │   OptionPlay-Web                     │
│     python -m src.mcp_main   │     │                                      │
│     (Port: stdio / MCP)      │     │   FastAPI Backend (Port 8000)        │
│                              │     │   ├── /api/vix                       │
│  OptionPlayServer            │◄────┤   ├── /api/quote/{symbol}           │
│  ├── HandlerContainer        │     │   ├── /api/analyze/{symbol}          │
│  │   ├── vix                 │     │   ├── /api/scan                      │
│  │   ├── scan                │     │   ├── /api/json/stream (SSE)         │
│  │   ├── quote               │     │   ├── /api/json/dashboard            │
│  │   ├── analysis            │     │   ├── /api/json/portfolio            │
│  │   ├── portfolio           │     │   └── /api/admin/*                   │
│  │   ├── validate            │     │                                      │
│  │   ├── monitor             │     │   Vite/React Frontend (Port 5173)    │
│  │   └── ibkr                │     │   ├── Dashboard (Market Overview)    │
│  │                           │     │   ├── Scanner                        │
│  ├── ServiceContainer (DI)   │     │   ├── Analysis                       │
│  │   ├── vix_manager         │     │   ├── Portfolio                      │
│  │   ├── fundamentals_mgr    │     │   ├── Shadow Tracker                 │
│  │   └── scanner_config      │     │   └── Admin                         │
│  │                           │     └──────────────────────────────────────┘
│  ├── Analyzers (2 Strategien)│
│  │   ├── PullbackAnalyzer    │
│  │   └── BounceAnalyzer      │
│  │                           │
│  └── Services                │
│      ├── VIX Regime v2       │
│      ├── Sector RS (RRG)     │
│      └── Enhanced Scoring    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│                       DATENSCHICHT                            │
│                                                              │
│  ~/.optionplay/trades.db (8,6 GB — SQLite)                   │
│  ├── options_prices:      19,3 Mio. Datensätze              │
│  ├── options_greeks:      19,6 Mio. Datensätze              │
│  ├── daily_prices:        442k OHLCV-Bars (354 Symbole)     │
│  ├── symbol_fundamentals: 357 Symbole                       │
│  ├── earnings_history:    ~8.500 Einträge                   │
│  └── vix_data:            1.385 Tageswerte                  │
│                                                              │
│  ~/.optionplay/outcomes.db  (ML-Training)                    │
│  └── trade_outcomes: 17.438 Backtested Trades               │
│                                                              │
│  IBKR TWS (live)           │  Yahoo Finance (VIX, Earnings) │
│  localhost:7497             │  yfinance                      │
└──────────────────────────────────────────────────────────────┘
```

---

## OptionPlay — MCP Backend

**Repository:** [Manray71/OptionPlay](https://github.com/Manray71/OptionPlay)
**Version:** 5.0.0 | **Codebase:** 156 Module, ~67.700 LOC | **Tests:** 5.937 (80 %+ Coverage)

### Features Backend

#### Trading-Core
- **2 Aktive Strategien** — Pullback (88,3 % WR) und Support Bounce (91,6 % WR)
- **VIX-Regime v2** — Kontinuierliche Interpolation über 7 Ankerpunkte (VIX 10–40); ersetzt das alte 5-Stufen-System
- **ML-Optimiertes Scoring** — Walk-Forward-Training (18/6/6 Monate, 7 Epochen) mit Sektor-Faktoren und VIX-Regime-Adjustments
- **Sector RS (RRG-Quadranten)** — Leading/Weakening/Lagging/Improving für 11 GICS-Sektoren; Score-Modifier ±0,3–0,5
- **Enhanced Scoring** — Multiplikative Bonus-Gewichtung (max ×1,28): Liquidität, Credit, Pullback, Stabilität
- **3-stufige Stabilitätsfilterung** — Pre-Filter (min 50), Stability-First Post-Filter (Tier-System), WF-trainierte Schwellen
- **Liquidity-Tier-System** — T1 (OI > 500): 136 Symbole, T2 (100–500): 143, T3 (< 100): 80

#### MCP-Server (Claude Desktop)
- **53 MCP-Tools** für direkte Claude-Desktop-Integration
- **Composition-basierte Handler** via `HandlerContainer` (10 Handler-Gruppen)
- **Trade Validator** — GO/NO-GO/WARNING gegen PLAYBOOK-Regeln
- **Position Monitor** — HOLD/CLOSE/ROLL/ALERT Exit-Signale
- **Daily Picks** — 3–5 fertige Setups mit Strike-Empfehlung, Credit-Ziel, Stop-Loss
- **Strike-Empfehlungssystem** — Delta-basiert (Short −0,20 ±0,03) → Support-basiert → OTM%-basiert (12 %)

#### Infrastruktur
- **ServiceContainer (DI)** — 11 Singletons (VixCacheManager, SymbolFundamentalsManager, etc.)
- **Caching-Layer** — Earnings, VIX, Fundamentals, Historical Prices
- **Circuit Breaker + Rate Limiter** — Adaptive Fehlertoleranz für externe APIs
- **Exception-Hierarchie** — 9 typisierte Exceptions (`MCPError`, `DataFetchError`, `NoDataError`, ...)

### Tech-Stack Backend

| Komponente | Technologie |
|-----------|-------------|
| Sprache | Python 3.11+ |
| Web-Framework | — (MCP via stdio) |
| Datenbank | SQLite (~8,6 GB, `trades.db` + `outcomes.db`) |
| Numerik | NumPy, pandas |
| HTTP | aiohttp |
| Konfiguration | PyYAML (5 YAML-Dateien) |
| Validierung | Pydantic 2.0 |
| MCP | `mcp`, `fastmcp` |
| Live-Daten | IBKR TWS (ib_insync, Port 7497) |
| Marktdaten | yfinance (VIX, Fundamentals, EPS) |
| Testing | pytest, pytest-cov, pytest-asyncio |
| Linting | black, isort, flake8, mypy |
| CI/CD | GitHub Actions |

### Projektstruktur Backend

```
OptionPlay/
├── src/
│   ├── mcp_server.py              # OptionPlayServer (Komposition)
│   ├── mcp_tool_registry.py       # 53 Tool-Registrierungen
│   ├── mcp_main.py                # Entry Point
│   ├── container.py               # ServiceContainer (DI, 11 Singletons)
│   ├── ibkr_bridge.py             # Interactive Brokers TWS Bridge
│   ├── spread_analyzer.py         # Spread-Bewertung
│   ├── strike_recommender.py      # Strike-Empfehlungen
│   ├── handlers/                  # 14 MCP-Handler (vix, scan, quote, ...)
│   ├── services/                  # Business Logic (VIX Regime, Sector RS, ...)
│   ├── analyzers/                 # 2 Strategie-Analyzer + FeatureScoringMixin
│   ├── scanner/                   # MultiStrategyScanner + Ranker
│   ├── cache/                     # Caching (Earnings, VIX, Fundamentals, ...)
│   ├── data_providers/            # DataProvider ABC, IBKR, Local DB
│   ├── constants/                 # Trading-Regeln, Schwellen, Risiko-Parameter
│   ├── models/                    # Domain-Modelle (TradeSignal, DailyPick, ...)
│   ├── indicators/                # RSI, Bollinger, MACD, Support/Resistance
│   ├── options/                   # Greeks, Black-Scholes
│   └── utils/                     # Rate Limiter, Circuit Breaker, Logging
├── config/
│   ├── trading.yaml               # Trading-Regeln, VIX-Profile, Roll-Strategie
│   ├── scoring.yaml               # Scoring-Gewichte, Analyzer-Schwellen
│   ├── system.yaml                # Scanner-Config, Liquidity-Blacklist
│   └── watchlists.yaml            # Symbol-Listen (default_275, extended_600)
├── scripts/
│   ├── daily_data_fetcher.py      # VIX + Options-Snapshot täglich (Cronjob)
│   ├── populate_fundamentals.py   # Fundamentals + Stability-Scores
│   ├── collect_earnings_eps.py    # EPS-Daten via yfinance
│   ├── calculate_derived_metrics.py  # IV Rank, Korrelation, HV
│   ├── sync_daily_to_price_data.py   # OHLCV: daily_prices → price_data
│   ├── classify_liquidity.py      # Liquidity-Tier-Klassifizierung
│   └── morning_workflow.py        # Täglicher Morning Report
├── docs/
│   ├── PLAYBOOK.md                # Regelwerk (Entry, Exit, Sizing, Disziplin)
│   └── ARCHITECTURE.md            # System-Architektur
├── tests/                         # 135 Testdateien, 5.937 Tests
├── CLAUDE.md                      # DB-Schema, API-Beispiele, Code-Konventionen
└── requirements.txt
```

### Installation Backend

#### Voraussetzungen

- Python 3.11+
- Interactive Brokers TWS (für Live-Daten, optional)
- SQLite-Datenbank `~/.optionplay/trades.db` (Initiales Setup via Scripts)

#### Setup

```bash
# Repository klonen
git clone https://github.com/Manray71/OptionPlay.git
cd OptionPlay

# Virtuelle Umgebung erstellen
python3 -m venv .venv
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt

# Environment-Datei konfigurieren
cp .env.example .env
# .env bearbeiten — alle Keys nur hier eintragen, niemals in config/

# Daten-Pipeline (einmalig)
python scripts/populate_fundamentals.py       # Fundamentals + Stability
python scripts/collect_earnings_eps.py        # EPS-Daten
python scripts/calculate_derived_metrics.py   # IV Rank, HV, Korrelation
python scripts/classify_liquidity.py          # Liquidity-Tier
```

#### Cronjob (täglich)

```bash
# crontab -e
# Täglich um 18:30 Uhr (nach US-Marktschluss)
30 18 * * 1-5 /path/to/.venv/bin/python /path/to/OptionPlay/scripts/daily_data_fetcher.py
```

### Konfiguration Backend

Alle Parameter sind in YAML externalisiert — keine Hardcodierung:

| Datei | Inhalt | Wichtige Parameter |
|-------|--------|--------------------|
| `config/trading.yaml` | Trading-Regeln, VIX-Profile, Roll-Strategie, Regime v2 | VIX-Ankerpunkte, Delta-Ziele, Earnings-Buffer |
| `config/scoring.yaml` | Scoring-Gewichte, Analyzer-Schwellen, Enhanced Scoring | ML-Gewichte, Sektor-Faktoren, VIX-Multiplier |
| `config/system.yaml` | Scanner-Config, Liquidity-Blacklist | Scan-Limits, API-Timeouts |
| `config/watchlists.yaml` | Symbol-Listen | default_275, extended_600 |

**Delta ist heilig:** Die Delta-Ziele (Short −0,20 ±0,03, Long −0,05 ±0,02) sind im Code verankert und werden **nicht** externalisiert.

#### VIX-Regime v2 — Ankerpunkte

| VIX | Spread-Breite | Min Score | Earnings-Buffer | Max Positionen |
|-----|--------------|-----------|-----------------|----------------|
| 10 | $ 2,50 | 3,5 | 60 Tage | 6 |
| 15 | $ 5,00 | 4,0 | 60 Tage | 5 |
| 20 | $ 5,00 | 4,5 | 60 Tage | 4 |
| 25 | $ 5,00 | 5,0 | 60 Tage | 3 |
| 30 | $ 7,50 | 5,5 | 75 Tage | 2 |
| 35 | $10,00 | 6,0 | 90 Tage | 1 |
| 40 | $10,00 | 7,0 | 90 Tage | 0 (Pause) |

### Verwendung Backend

#### Als MCP-Server (Claude Desktop)

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "optionplay": {
      "command": "/path/to/OptionPlay/.venv/bin/python",
      "args": ["-m", "src.mcp_main"],
      "cwd": "/path/to/OptionPlay"
    }
  }
}
```

#### Direkter Python-Aufruf

```bash
# MCP-Server starten
python -m src.mcp_main

# Scanner direkt ausführen
python -m src.scanner.multi_strategy_scanner

# Morning Report
python scripts/morning_workflow.py

# Tests
pytest --cov=src --cov-fail-under=80
```

#### Wichtige MCP-Tools (Auswahl)

| Tool | Beschreibung |
|------|-------------|
| `optionplay_daily_picks` | 3–5 fertige Trade-Setups |
| `optionplay_scan` | Multi-Strategie-Scan |
| `optionplay_validate_trade` | GO/NO-GO/WARNING für eigene Ideen |
| `optionplay_monitor_position` | Exit-Signale für offene Positionen |
| `optionplay_vix_strategy` | Aktuelle VIX-Regime-Einschätzung |
| `optionplay_analyze_symbol` | Tiefenanalyse eines Symbols |
| `optionplay_sector_status` | RRG-Tabelle (Leading/Weakening/...) |
| `optionplay_get_quote` | Live-Quote via IBKR |

---

## OptionPlay-Web — React + FastAPI Frontend

**Repository:** [Manray71/OptionPlay-Web](https://github.com/Manray71/OptionPlay-Web)
**Version:** 1.0.0 | **Abhängigkeit:** OptionPlay v5.0.0

### Features Frontend

#### Dashboard (Market Overview)
- VIX-Gauge mit Regime-Ampel und Strategie-Empfehlung
- Markt-Indizes (SPY, QQQ, IWM) mit Intraday-Trend
- Sektor-Momentum (RRG-Quadranten: Leading / Weakening / Lagging / Improving)
- Upcoming Events & Earnings-Kalender
- Nachrichten mit automatischer Sentiment-Analyse

#### Scanner
- Multi-Strategie-Optionen-Scanner (Pullback, Support Bounce)
- VIX-Regime-v2-Filterung
- Sortierung nach Score, Liquidität, Stabilität
- Prefetch: Analyse aller Scan-Ergebnisse im Hintergrund
- PDF-Export (einseitig, A4)

#### Analysis
- Tiefenanalyse je Symbol: IV-Perzentil, Strategie-Scores, Momentum
- Support/Resistance-Levels
- Strike-Empfehlungen mit Credit-Schätzung und Risk/Reward
- Analyst-Konsens, Earnings-Daten, Nachrichten
- Direkt aus dem Scanner per Klick erreichbar
- PDF-Export

#### Portfolio
- Positionsverfolgung mit P&L-Monitoring
- Detailansicht je Position mit Exit-Levels
- IBKR-Portfolio-Sync via Subprocess

#### Shadow Tracker
- Logging von Paper Trades (ohne echte Ausführung)
- Performance-Statistiken: Win Rate, P&L, Drawdown
- Filter nach Strategie, VIX-Regime, Score-Bucket
- Persistenz in lokaler DB

#### Admin
- Live-Konfigurationseditor für alle YAML-Configs
- Vier Config-Bereiche: Trading, Scoring, System, Watchlists
- Keine Server-Neustarterforderlich (Hot Reload)

#### Technische Features
- **Server-Sent Events (SSE)** — Echtzeit-Streaming von Marktdaten
- **Rate Limiting** (slowapi) — Schutz der Backend-Endpunkte
- **Input-Validierung** — Symbol-Regex-Prüfung, max. 50 Symbole pro Batch
- **MarketDataContext** — Globaler State via React Context (kein Redux)
- **URL-Parameter** — Deep-Links auf bestimmte Seiten und Symbole (`?page=analysis&symbol=AAPL`)

### Tech-Stack Frontend

| Schicht | Technologie | Version |
|---------|------------|---------|
| **Frontend** | React | 19 |
| Build-Tool | Vite | 6 |
| Routing | react-router-dom | 7 |
| Icons | lucide-react | 0.475 |
| PDF-Export | jsPDF + jspdf-autotable | 4.1 / 5.0 |
| Tests | Vitest + Testing Library | 3.0 |
| Linting | ESLint | 9 |
| **Backend** | FastAPI | aktuell |
| ASGI-Server | Uvicorn | aktuell |
| SSE | sse-starlette | aktuell |
| Rate Limiting | slowapi | aktuell |
| Event-Loop | nest_asyncio | aktuell |
| Tests | pytest + httpx | aktuell |
| Linting | ruff | 0.15 |

### Projektstruktur Frontend

```
OptionPlay-Web/
├── frontend/
│   ├── src/
│   │   ├── App.jsx                    # Routing, globaler State, Nav
│   │   ├── api.js                     # API-Client (alle Backend-Aufrufe)
│   │   ├── components/
│   │   │   ├── Dashboard.jsx          # Market Overview (VIX, Sektoren, Events)
│   │   │   ├── Scanner.jsx            # Scan-UI + Ergebnistabelle
│   │   │   ├── Analysis.jsx           # Symbol-Tiefenanalyse
│   │   │   ├── Portfolio.jsx          # Positionsübersicht
│   │   │   ├── PositionDetail.jsx     # Einzelposition mit Exit-Levels
│   │   │   ├── ShadowTracker.jsx      # Paper-Trade-Tracking
│   │   │   ├── Admin.jsx              # Config-Editor
│   │   │   └── RRGChart.jsx           # Relative Rotation Graph
│   │   ├── contexts/
│   │   │   └── MarketDataContext.jsx  # Globaler Marktdaten-State
│   │   └── utils/
│   │       ├── exportDashboardPdf.js  # PDF-Export Dashboard
│   │       ├── exportScannerPdf.js    # PDF-Export Scanner
│   │       └── exportAnalysisPdf.js   # PDF-Export Analysis
│   ├── package.json
│   └── vite.config.js
│
├── backend/
│   ├── main.py                        # FastAPI App (Lifespan, CORS, Router)
│   ├── rate_limit.py                  # slowapi Limiter
│   ├── api/
│   │   ├── routes.py                  # OptionPlayServer-Integration (/api/*)
│   │   ├── json_routes.py             # Strukturierte JSON-API (/api/json/*)
│   │   ├── sse_routes.py              # SSE-Streaming (/api/json/stream)
│   │   ├── admin.py                   # Config-Management (/api/admin/*)
│   │   ├── auth.py                    # Symbol-Validierung
│   │   └── news_sentiment.py          # Sentiment-Anreicherung
│   ├── services/
│   │   ├── ibkr_helpers.py            # IBKR-Hilfsfunktionen (Portfolio, Quotes)
│   │   ├── market_data_cache.py       # In-Memory Cache für Marktdaten
│   │   └── polling_loop.py            # Background-Polling (Marktdaten)
│   ├── scripts/
│   │   ├── ibkr_portfolio.py          # IBKR-Portfolio per Subprocess
│   │   ├── ibkr_quote.py              # IBKR-Quotes per Subprocess
│   │   └── ibkr_news.py               # IBKR-Nachrichten per Subprocess
│   ├── tests/                         # pytest-Tests (auth, health, cache, SSE)
│   └── requirements.txt
│
└── plan.md                            # Entwicklungsplan
```

### Installation Frontend

#### Voraussetzungen

- Node.js 18+
- Python 3.11+
- OptionPlay v5.0.0 installiert und konfiguriert (Schwester-Verzeichnis)
- Interactive Brokers TWS (für Portfolio-Daten, optional)

#### Setup

```bash
# Repository klonen (als Schwester von OptionPlay)
git clone https://github.com/Manray71/OptionPlay-Web.git
cd OptionPlay-Web

# ── Frontend ──────────────────────────────
cd frontend
npm install
cd ..

# ── Backend ───────────────────────────────
# Virtuelle Umgebung (oder in bestehende installieren)
pip install -r backend/requirements.txt

# Environment-Datei konfigurieren
cp backend/.env.example backend/.env
# backend/.env bearbeiten
```

#### `backend/.env` — Wichtige Variablen

```env
# Pfad zum OptionPlay-Verzeichnis (automatisch per sys.path gesetzt)
# OPTIONPLAY_DIR=/pfad/zu/OptionPlay   # optional, Standard: ../OptionPlay

# IBKR TWS (für Portfolio-Daten)
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=10

# Kein API-Key nötig — OptionPlay lädt Keys aus eigenem .env
```

### Konfiguration Frontend

Die Web-Configs spiegeln die OptionPlay-Configs:

| Datei | Inhalt |
|-------|--------|
| `config/trading.yaml` | Trading-Regeln, VIX-Regime, Exit/Roll-Strategie |
| `config/scoring.yaml` | Scoring-Gewichte, Schwellen, Sektor-Faktoren |
| `config/system.yaml` | Scanner-Config, Datenprovider, Infrastruktur |
| `config/watchlists.yaml` | Symbol-Listen (default, extended) |

Änderungen können direkt im **Admin**-Tab der Web-UI vorgenommen werden.

### Verwendung Frontend

#### Starten

```bash
# Terminal 1 — FastAPI Backend (Port 8000)
cd OptionPlay-Web
python3 -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Vite Frontend (Port 5173)
cd OptionPlay-Web/frontend
npm run dev
```

Browser öffnen: **http://localhost:5173**

#### API-Endpunkte (Backend)

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/health` | GET | Health Check |
| `/api/vix` | GET | VIX + Regime-Empfehlung |
| `/api/quote/{symbol}` | GET | Live-Quote |
| `/api/analyze/{symbol}` | GET | Symbol-Tiefenanalyse |
| `/api/scan` | POST | Multi-Strategie-Scan |
| `/api/json/dashboard` | GET | Dashboard-Daten (strukturiert) |
| `/api/json/portfolio` | GET | Portfolio-Positionen |
| `/api/json/stream` | GET | SSE-Echtzeit-Stream |
| `/api/admin/config/{file}` | GET/PUT | Config lesen/schreiben |

#### Tests ausführen

```bash
# Backend-Tests
cd OptionPlay-Web
pytest backend/tests/ -v

# Frontend-Tests
cd frontend
npm run test

# Linting
ruff check backend/        # Python
npm run lint               # JavaScript/React
```

---

## Datenbank

### trades.db — `~/.optionplay/trades.db` (~8,6 GB)

| Tabelle | Datensätze | Beschreibung |
|---------|------------|--------------|
| `options_prices` | 19,3 Mio. | Historische Optionspreise (Bid/Ask/Mid/Last) |
| `options_greeks` | 19,6 Mio. | Greeks (Delta, Gamma, Theta, Vega, IV) |
| `daily_prices` | 442k | OHLCV-Bars (354 Symbole × ~1.280 Bars) |
| `price_data` | 630 | Komprimierte Preisdaten (via PriceStorage) |
| `earnings_history` | ~8.500 | Earnings mit EPS (343 Symbole) |
| `symbol_fundamentals` | 357 | Fundamentaldaten + Stability Scores |
| `vix_data` | 1.385 | VIX-Tageswerte |

**Zeitraum:** Optionen + Greeks: 2021-01 bis 2026-01 | OHLCV: 2021-01 bis 2026-01 | VIX: 2020-07 bis 2026-01

### outcomes.db — `~/.optionplay/outcomes.db`

| Tabelle | Datensätze | Beschreibung |
|---------|------------|--------------|
| `trade_outcomes` | 17.438 | Backtestete Bull-Put-Spreads (ML-Training) |

### Wichtige Schema-Hinweise

```sql
-- VIX: Spalte heißt "value", NICHT "close"
SELECT date, value FROM vix_data WHERE date >= date('now', '-30 days');

-- Greeks-Join
SELECT p.underlying, p.strike, g.delta, g.iv_calculated
FROM options_prices p
JOIN options_greeks g ON g.options_price_id = p.id
WHERE p.underlying = 'AAPL' AND p.option_type = 'put'
  AND p.dte BETWEEN 60 AND 90
  AND g.delta BETWEEN -0.25 AND -0.15;

-- Stabile Symbole
SELECT symbol, stability_score, historical_win_rate
FROM symbol_fundamentals
WHERE stability_score >= 65
ORDER BY stability_score DESC;
```

---

## Trading-Strategien & Backtesting

### Aktive Strategien (v5.0.0)

#### Pullback
- **Konzept:** Kursrücksetzer im intakten Aufwärtstrend
- **WF-Schwelle:** 4,5 | **OOS Win Rate:** 88,3 %
- **Max Score (P95):** 14,0 | **Min Score:** 3,5
- **Datei:** `src/analyzers/pullback.py`

#### Support Bounce
- **Konzept:** Abpraller an historischer Unterstützungszone
- **WF-Schwelle:** 6,0 | **OOS Win Rate:** 91,6 %
- **Max Score (P95):** 10,0 | **Min Score:** 3,5
- **Datei:** `src/analyzers/bounce.py`

### Dreistufiges Scoring-System

```
Stufe 1: Komponenten-Scoring (pro Strategie)
  └── Analyzer vergibt Punkte pro Indikator (RSI, MACD, Support, Volume, ...)
  └── Normalisierung auf 0–10 via score_normalization.py

Stufe 2: ML-Trained Weights (FeatureScoringMixin)
  └── Gewichte aus ~/.optionplay/models/component_weights.json
  └── Per Strategie × VIX-Regime × Sektor
  └── Walk-Forward-Training (7 Epochen, 2020–2025)

Stufe 3: Ranking (DailyRecommendationEngine)
  └── base = 0,70 × signal_score + 0,30 × stability_score
  └── final = base × speed_multiplier
  └── Enhanced Scoring: final × (1 + Σ multipliers) — max ×1,28
```

### Trainierte Modell-Dateien

```
~/.optionplay/models/
├── component_weights.json           # ML-Gewichte pro Scoring-Komponente
├── trained_models.json              # Score-Schwellen + Regime-Adjustments
├── SECTOR_CLUSTER_WEIGHTS.json      # Sektor-Faktoren (12 × 5)
├── wf_training_results_detailed.json
└── stability_threshold_analysis.json
```

---

## Datenprovider

| Provider | Zweck | Status |
|----------|-------|--------|
| **IBKR TWS** (Port 7497) | Live-Quotes, Options-Chains, Greeks, Portfolio, Nachrichten | Primär (aktiv) |
| **Yahoo Finance** (yfinance) | VIX-Daten, Fundamentals, EPS-Daten | Aktiv |
| **SQLite (trades.db)** | Historische Options- und Preisdaten | Aktiv |
| Tradier | Live-Daten | **Entfernt** (seit 2026-04-09) |
| Marketdata.app | Live-Daten | **Entfernt** |

**Provider-Fallback:** IBKR TWS → Local DB (kein weiterer Fallback)

---

## Sicherheit

- **API-Keys:** Ausschließlich in `.env`-Dateien — **niemals** in YAML-Configs, `claude_desktop_config.json` o.ä.
- **Symbol-Validierung:** Regex-Prüfung (`^[A-Z0-9]{1,6}([.\-][A-Z]{1,2})?!?$`) an allen Eingabepunkten
- **Rate Limiting:** slowapi auf allen `/api/*`-Endpunkten (HTTP 429 bei Überschreitung)
- **Input Sanitization:** SQL-Injection-Schutz via parametrisierte Queries; max. 50 Symbole pro Batch-Request
- **CORS:** Explizit nur `http://localhost:5173` erlaubt
- **IBKR:** Direktverbindungen aus dem Web-Backend deaktiviert (`OPTIONPLAY_NO_IBKR=1`); Portfolio-Abruf ausschließlich per isoliertem Subprocess

---

## Lizenz

[MIT](LICENSE) — Beide Projekte (OptionPlay + OptionPlay-Web)
