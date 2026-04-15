# OptionPlay-Web -- Bestandsaufnahme

Erstellt: 2026-04-07
Projektpfad: `~/OptionPlay-Web/` (macOS case-insensitive: `optionplay-web` = `OptionPlay-web` = `OptionPlay-Web`, gleiche Inode)

---

## 1 -- Projektstatus (Zusammenfassung)

| Eigenschaft | Wert |
|-------------|------|
| Existiert | Ja |
| Laufzeitstatus | Backend laeuft (uvicorn auf Port 8000, Python 3.14), Frontend nicht gestartet |
| node_modules installiert | Ja (329 Pakete) |
| Python venv | Ja (`backend/venv/`) |
| Build vorhanden | Ja (`frontend/dist/`) |
| Implementierungsgrad | ~75% (solides Fundament, einige Inkonsistenzen mit v5.0.0) |
| LOC Frontend | ~5,109 (JSX/JS/CSS) |
| LOC Backend | ~3,466 (Python) |
| Tests | 27 passed, 5 failed (Auth-Tests) |

---

## 2 -- Projektstruktur und Kennzahlen

### Dateiuebersicht

| Kategorie | Dateien | LOC |
|-----------|---------|-----|
| Frontend JSX-Komponenten | 6 | ~4,028 |
| Frontend Utils (PDF Export) | 3 | ~865 |
| Frontend Config (api.js, App, main, CSS) | 4 | ~2,215 |
| Backend API-Module | 5 | ~2,456 |
| Backend Scripts (IBKR) | 3 | ~589 |
| Backend Tests | 4 | ~369 |
| **Gesamt** | **~37 Dateien** | **~10,411** |

### Verzeichnisbaum (Quelldateien)

```
OptionPlay-Web/
├── README.md
├── plan.md                          # Dashboard-Umbau-Plan
├── backend/
│   ├── main.py                      # FastAPI App (46 LOC)
│   ├── rate_limit.py                # slowapi Limiter (6 LOC)
│   ├── .env                         # OPTIONPLAY_ADMIN_KEY
│   ├── .env.example
│   ├── requirements.txt
│   ├── api/
│   │   ├── routes.py                # OptionPlay Server Integration (97 LOC)
│   │   ├── json_routes.py           # JSON API Endpoints (1,825 LOC)
│   │   ├── admin.py                 # Config Management (332 LOC)
│   │   ├── auth.py                  # Auth + Input Validation (49 LOC)
│   │   └── news_sentiment.py        # News Sentiment Enrichment (153 LOC)
│   ├── scripts/
│   │   ├── ibkr_news.py             # IBKR News via Subprocess (79 LOC)
│   │   ├── ibkr_portfolio.py        # IBKR Portfolio via Subprocess (404 LOC)
│   │   └── ibkr_quote.py            # IBKR Quotes via Subprocess (106 LOC)
│   └── tests/
│       ├── conftest.py              # TestClient Setup (60 LOC)
│       ├── test_auth.py             # Admin Auth Tests (73 LOC)
│       ├── test_config_backup.py    # Config Backup Tests (79 LOC)
│       ├── test_health.py           # Health Check Test (11 LOC)
│       └── test_input_validation.py # Input Sanitization (146 LOC)
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    ├── .env                         # VITE_ADMIN_KEY
    └── src/
        ├── main.jsx                 # React Mount (10 LOC)
        ├── App.jsx                  # Routing + State (164 LOC)
        ├── api.js                   # API Client (206 LOC)
        ├── index.css                # Styles (1,835 LOC)
        ├── components/
        │   ├── Dashboard.jsx        # Market Overview (784 LOC)
        │   ├── Scanner.jsx          # Multi-Strategy Scanner (598 LOC)
        │   ├── Analysis.jsx         # Symbol Deep-Dive (1,172 LOC)
        │   ├── Portfolio.jsx        # Position Tracking (533 LOC)
        │   ├── RRGChart.jsx         # Relative Rotation Graph (241 LOC)
        │   └── Admin.jsx            # Config Editor (536 LOC)
        └── utils/
            ├── exportDashboardPdf.js  # PDF Export Dashboard (339 LOC)
            ├── exportScannerPdf.js    # PDF Export Scanner (150 LOC)
            └── exportAnalysisPdf.js   # PDF Export Analysis (376 LOC)
```

---

## 3 -- Tech Stack

### Frontend

| Eigenschaft | Wert |
|-------------|------|
| Framework | **Vite 6** (kein Next.js) |
| UI-Bibliothek | **Vanilla CSS** (1,835 LOC custom CSS, kein Tailwind/MUI/shadcn) |
| Komponenten | **React 19** (JSX, nicht TSX) |
| Routing | **react-router-dom 7.1** |
| Icons | **Lucide React** |
| PDF Export | **jsPDF + jspdf-autotable** |
| State Management | **Keines** (React useState/useEffect in App.jsx) |
| TypeScript | **Nein** (rein JSX/JS) |
| Chart-Bibliothek | **Keine** (RRGChart ist Canvas-basiert, manuell gezeichnet) |
| Testing | **Vitest + @testing-library/react** |

### Backend

| Eigenschaft | Wert |
|-------------|------|
| Framework | **FastAPI** |
| Server | **Uvicorn** |
| Python-Version | **3.14** (laut laufendem Prozess) |
| Rate Limiting | **slowapi** |
| Async | **nest_asyncio** (fuer ib_insync Kompatibilitaet) |
| Testing | **pytest + httpx** |
| Linting | **ruff** |

### Wichtige Abhaengigkeiten (backend/requirements.txt)

```
fastapi, uvicorn, python-dotenv, pyyaml, slowapi, pytest, httpx, ruff, nest_asyncio
```

Nicht explizit gelistet aber im Code importiert: `yfinance`, `ib_insync`, `sqlite3`, `zoneinfo`

---

## 4 -- Implementierter Funktionsumfang

### Frontend-Komponenten

| Komponente | LOC | Inhalt | Status |
|-----------|-----|--------|--------|
| **Dashboard.jsx** | 784 | VIX Gauge, Market Indices (10 Symbole), Upcoming Events (FOMC/CPI/NFP/OPEX), Sector Momentum, Earnings Kalender, Market News mit Sentiment | Vollstaendig |
| **Scanner.jsx** | 598 | Multi-Strategy Scan (5 Strategien im UI), Ergebnistabelle mit Score/Stability/Sector/Earnings, Sortierung, Shadow-Trade-Logging, PDF Export | Funktional, aber 3 Strategien verweisen auf geloeschte Analyzer |
| **Analysis.jsx** | 1,172 | Symbol Deep-Dive: Analyst Ratings, IV Percentile, Strategy Scores (5 Strategien), Momentum, SMA Alignment, Support/Resistance, Trade Recommendation, Earnings History, News | Umfangreich, Referenzen auf geloeschte Strategien |
| **Portfolio.jsx** | 533 | IBKR Live-Positionen (via Subprocess), P&L Tracking, Zusammenfassung, Position-Filter | Vollstaendig (abhaengig von IBKR Gateway) |
| **RRGChart.jsx** | 241 | Canvas-basierter Relative Rotation Graph (4 Quadranten), animierte Trails | Vollstaendig |
| **Admin.jsx** | 536 | YAML-Config Editor (4 Dateien), DB-Status, Coverage, Fundamentals-Update, DB-Update (VIX/Options/OHLCV) | Vollstaendig |

### App.jsx -- Routing

| Route | Komponente |
|-------|-----------|
| `/` | Dashboard |
| `/scanner` | Scanner |
| `/analysis` / `/analysis/:symbol` | Analysis |
| `/portfolio` | Portfolio |
| `/admin` | Admin |

---

## 5 -- API-Endpoints

### JSON API (`/api/json/`)

| Methode | Pfad | Datei:Zeile | Beschreibung |
|---------|------|-------------|-------------|
| GET | `/json/vix` | json_routes.py:321 | VIX + Regime + v2 Parameter |
| GET | `/json/regime` | json_routes.py:384 | VIX Regime v2 interpoliert |
| POST | `/json/quotes` | json_routes.py:488 | Batch-Quotes (IBKR -> yfinance -> DB) |
| POST | `/json/scan` | json_routes.py:563 | Multi-Strategy Scan |
| GET | `/json/analyze/{symbol}` | json_routes.py:809 | Symbol-Analyse |
| GET | `/json/news/{symbol}` | json_routes.py:1143 | IBKR News + Sentiment |
| GET | `/json/portfolio/positions` | json_routes.py:1172 | IBKR Portfolio Positionen |
| GET | `/json/portfolio/summary` | json_routes.py:1339 | Portfolio Zusammenfassung |
| GET | `/json/events` | json_routes.py:1404 | Makro-Events Kalender |
| GET | `/json/sectors` | json_routes.py:1431 | Sektor-Momentum Daten |
| GET | `/json/stock-rs` | json_routes.py:1481 | Stock Relative Strength |
| GET | `/json/earnings-calendar` | json_routes.py:1550 | Earnings Kalender |
| POST | `/json/shadow-log` | json_routes.py:1650 | Shadow Trade Logging |
| GET | `/json/market-news` | json_routes.py:1806 | Markt-Nachrichten |

### General API (`/api/`)

| Methode | Pfad | Datei:Zeile | Beschreibung |
|---------|------|-------------|-------------|
| GET | `/vix` | routes.py:51 | VIX (Markdown-Format) |
| GET | `/quote/{symbol}` | routes.py:60 | Quote (Markdown) |
| GET | `/analyze/{symbol}` | routes.py:68 | Analyse (Markdown) |
| POST | `/scan` | routes.py:76 | Scan (Markdown) |

### Admin API (`/api/admin/`)

| Methode | Pfad | Datei:Zeile | Beschreibung |
|---------|------|-------------|-------------|
| POST | `/db-update` | admin.py:46 | DB-Update (VIX/Options/OHLCV) |
| GET | `/db-status` | admin.py:94 | DB Groesse + Tabellen |
| GET | `/db-coverage` | admin.py:114 | Symbol-Abdeckung |
| POST | `/fundamentals-update` | admin.py:225 | Fundamentals aktualisieren |
| GET | `/files` | admin.py:274 | Config-Dateiliste |
| GET | `/{file_key}` | admin.py:279 | Config lesen |
| POST | `/{file_key}` | admin.py:298 | Config speichern |

### Health

| Methode | Pfad | Datei:Zeile |
|---------|------|-------------|
| GET | `/health` | main.py:44 |

**Gesamt: 22 Endpoints** (14 JSON + 4 General + 7 Admin + 1 Health)

---

## 6 -- Verbindung zu OptionPlay-Core

### Integrationsmuster

1. **Direktimport** (routes.py Zeile 34): `from src.mcp_server import OptionPlayServer`
   - Setzt `sys.path` auf `../../../OptionPlay` (Geschwister-Verzeichnis)
   - Singleton `OptionPlayServer` Instanz
   - Zugriff via `server.handlers.X.method()`

2. **Subprocess** (json_routes.py): IBKR-Daten via Subprocess-Aufrufe
   - `scripts/ibkr_news.py`, `ibkr_portfolio.py`, `ibkr_quote.py`
   - Nutzt OptionPlay's `.venv/bin/python`
   - Port-Check auf IBKR Gateway (default 4001) vor Aufruf

3. **Direkte DB-Abfrage** (json_routes.py Zeile 118): `~/.optionplay/trades.db`
   - VIX-Daten, Kurse, Fundamentals, Earnings
   - SQLite direkt, kein ORM

4. **OptionPlay-Module direkt** (json_routes.py): Importiert `src.services.vix_regime`, `src.scanner.multi_strategy_scanner`, `src.config.watchlist_loader`, etc.

### Environment-Variablen

| Datei | Schluessel | Zweck |
|-------|-----------|-------|
| `backend/.env` | `OPTIONPLAY_ADMIN_KEY` | Admin-API Authentifizierung |
| `frontend/.env` | `VITE_ADMIN_KEY` | Admin-Key im Frontend |
| (runtime) | `OPTIONPLAY_NO_IBKR` | Deaktiviert direkte IBKR-Verbindungen |
| (runtime) | `IBKR_PORT` | IBKR Gateway Port (default 4001) |

---

## 7 -- Laufzeitstatus

| Check | Status |
|-------|--------|
| Backend (uvicorn) | **Laeuft** auf Port 8000, Python 3.14 |
| Frontend (vite dev) | **Nicht gestartet** |
| Frontend Build | Vorhanden (`frontend/dist/`) |
| node_modules | Installiert (329 Pakete) |
| Python venv | Vorhanden (`backend/venv/`) |
| IBKR Gateway | Nicht geprueft (kein API-Call ausgefuehrt) |

### Tests

```
27 passed, 5 failed, 18 warnings in 0.05s
```

5 fehlgeschlagene Tests in `test_auth.py`:
- `test_missing_key_returns_401`
- `test_empty_key_returns_401`
- `test_wrong_key_returns_401`
- `test_correct_key_returns_key`
- `test_server_key_not_configured_returns_500`

Ursache: Wahrscheinlich Auth-Middleware-Aenderung, die nicht in Tests nachgezogen wurde.

### Port-Konfiguration

| Dienst | Port |
|--------|------|
| Backend (uvicorn) | 8000 |
| Frontend (Vite dev) | 5173 |
| IBKR Gateway | 4001 (konfigurierbar via `IBKR_PORT`) |

---

## 8 -- Implementierungsluecken

| Feature | Vorhanden | Vollstaendig | Hinweis |
|---------|-----------|-------------|---------|
| Dashboard / Market Overview | Ja | Ja | VIX, Indices, Events, Sectors, Earnings, News |
| Scanner-Ergebnisse | Ja | Teilweise | UI zeigt 5 Strategien, nur 2 existieren in v5.0.0 |
| Portfolio-Uebersicht | Ja | Ja | IBKR Live-Positionen + P&L |
| Position Detail | Nein | -- | Keine Detail-Ansicht einzelner Positionen |
| VIX-Regime-Anzeige | Ja | Ja | v2 Interpolation integriert |
| Sector RS / RRG-View | Ja | Ja | Canvas-basierter RRG-Chart |
| Shadow Tracker View | Teilweise | Nein | Logging via Scanner vorhanden, kein Review/Stats View |
| API-Authentifizierung | Ja | Teilweise | Nur Admin-Endpoints (X-Admin-Key), kein User-Auth |
| Echtzeit-Updates | Nein | -- | Kein WebSocket/SSE, nur manueller Refresh |
| Mobile-Responsive | Unklar | -- | CSS vorhanden (1,835 LOC), nicht getestet |
| PDF Export | Ja | Ja | Dashboard, Scanner, Analysis |

---

## 9 -- Offene Fragen und Auffaelligkeiten

### 1. Referenzen auf geloeschte Strategien (HOCH)

Frontend und Backend verweisen auf 3 in v5.0.0 geloeschte Strategien:

**Frontend:**

| Datei | Zeile | Referenz |
|-------|-------|----------|
| Scanner.jsx | 20-22 | `ATH Breakout`, `Earnings Dip`, `Trend Continuation` in Strategy-Liste |
| Scanner.jsx | 37 | Strategy-Mapping: `Breakout`, `Earnings Dip`, `Trend` |
| Portfolio.jsx | 39 | `STRATEGIES_MAP`: `Breakout`, `Trend`, `Earnings Dip` |
| Analysis.jsx | 119 | `case 'ath_breakout'` Handler |
| Analysis.jsx | 170-184 | `trend_continuation` Referenzen (SMA alignment, momentum health) |

**Backend:**

| Datei | Zeile | Referenz |
|-------|-------|----------|
| json_routes.py | 578-580 | `ScanMode.BREAKOUT_ONLY`, `ScanMode.EARNINGS_DIP`, `ScanMode.TREND_ONLY` |
| json_routes.py | 1683-1687 | Strategy-Mapping: `ath_breakout`, `earnings_dip`, `trend_continuation` |

Diese Referenzen fuehren zu Laufzeitfehlern wenn ein User die entsprechende Strategie im Scanner auswaehlt, da `ScanMode.BREAKOUT_ONLY` etc. in v5.0.0 nicht mehr existieren.

### 2. Dreifache Verzeichnis-Kopie (NIEDRIG)

`~/optionplay-web`, `~/OptionPlay-web`, `~/OptionPlay-Web` sind dasselbe Verzeichnis (gleiche Inode 310078427). macOS APFS ist case-insensitive. Kein echtes Problem, aber verwirrend.

### 3. Test-Failures in Auth (MITTEL)

5 von 32 Tests schlagen fehl (alle in `test_auth.py`). Die Auth-Middleware wurde moeglicherweise geaendert ohne Test-Update.

### 4. Kein TODO/FIXME/HACK gefunden (POSITIV)

Keine offenen TODO-Kommentare im Quellcode.

### 5. Config-Dateien Referenz (INFO)

Admin.jsx verwaltet Config-Dateien. Die `admin.py` Zeile 274 (`/files`) listet die verfuegbaren Config-Dateien. Muessen mit den in v5.0.0 konsolidierten 4 YAML-Dateien abgeglichen werden.

### 6. Python 3.14 (INFO)

Backend laeuft mit Python 3.14.2. OptionPlay-Core nutzt Python 3.12 (`.venv/bin/python`). Koennte zu Import-Inkompatibilitaeten fuehren.

### 7. Frontend nutzt kein TypeScript (INFO)

Gesamtes Frontend in JSX/JS geschrieben. Kein TypeScript trotz `@types/react` in devDependencies.

### 8. Fehlende Echtzeit-Updates (INFO)

Kein WebSocket oder Server-Sent Events implementiert. Dashboard und Scanner zeigen nur Daten zum Zeitpunkt des Ladens. Fuer ein Trading-Dashboard waeren Live-Updates wuenschenswert.

### 9. VITE_ADMIN_KEY im Frontend (SICHERHEIT)

`frontend/.env` enthaelt den Admin-Key im Klartext. Da Vite `VITE_`-Variablen in den Build einbettet, ist der Key im Frontend-Bundle sichtbar. Kein echtes Sicherheitsproblem fuer lokale Nutzung, aber nicht fuer Produktion geeignet.

---

*Ende des Snapshots*
