# OptionPlay + OptionPlay-Web Alignment Report
Datum: 2026-04-07

## Behobene Probleme OptionPlay Core

- **C1**: Broken Import `EnsembleSelector` aus gelöschtem `src/backtesting/` entfernt (`portfolio/manager.py`)
- **C2**: 3 tote `try/except ImportError` Blöcke für `src/backtesting/` im Scanner entfernt, plus tote Methoden (`_add_reliability_to_signal`, `_add_stability_to_signal`, `_get_adjustment_reason`, `_load_stability_cache`, `get_symbol_stability`, `_create_reliability_scorer`)
- **C2+**: 4 weitere Handler-Dateien bereinigt (`risk.py`, `risk_composed.py`, `analysis.py`, `analysis_composed.py`) — `PriceSimulator`/`EnsembleSelector` Imports durch "removed in v5.0.0" Meldungen ersetzt
- **C3**: Tote Config-Einträge für 3 gelöschte Strategien (ath_breakout, earnings_dip, trend_continuation) aus `trading.yaml`, `scoring.yaml`, `system.yaml` entfernt
- **C4**: Duplizierte Roll-Strategie-Parameter aus `system.yaml` entfernt (trading.yaml ist autoritativ)
- **C5**: VIX Regime v2 Feature-Flag `enable_regime_v2` liest jetzt aus `config/trading.yaml` statt hardcoded `True`
- **C6**: `iv_rank_minimum: 30` in system.yaml geprüft — aktiv genutzt, konsistent mit Code-Default (`ENTRY_IV_RANK_MIN=30`), belassen

## Behobene Probleme OptionPlay-Web

- **W1**: Frontend-Referenzen auf 3 gelöschte Strategien entfernt (`Scanner.jsx`, `Analysis.jsx`, `Portfolio.jsx` — STRATEGIES, Mock-Daten, STRATEGIES_MAP)
- **W2**: Backend-Referenzen auf gelöschte ScanModes (`BREAKOUT_ONLY`, `EARNINGS_DIP`, `TREND_ONLY`) und Strategy-Map entfernt (`json_routes.py`)
- **W3**: 5 fehlgeschlagene Auth-Tests repariert — Ursache: `require_admin_key()` ist async, Tests riefen synchron auf. Fix: `async def` + `await` + `@pytest.mark.asyncio`
- **W4**: Admin-Panel Config-Dateien auf v5.0.0 synchronisiert (6 alte → 4 aktuelle: trading, scoring, system, watchlists)
- **W5**: Python 3.14/3.12 Kompatibilität bestätigt — Cross-Import funktioniert, kein Handlungsbedarf
- **W6**: Shadow Tracker View ergänzt — Backend-Endpoints (`/shadow-review`, `/shadow-stats`) + Frontend-Komponente (`ShadowTracker.jsx`) mit Trades-Tab und Statistics-Tab
- **W7**: Position Detail View ergänzt — `PositionDetail.jsx` mit P&L, Exit Levels, Roll-Signal; clickable rows in `Portfolio.jsx`

## Offene Punkte (nicht im Scope)

- **W8**: Echtzeit-Updates (kein WebSocket/SSE) — zukünftiges Feature
- **W9**: `VITE_ADMIN_KEY` im Build — akzeptabel für lokalen Betrieb

## Dokumentation

- CLAUDE.md: VIX-Ankerpunkte von 4 auf 7 Einträge erweitert (inkl. Earnings Buffer)
- README.md (Web): Version auf v5.0.0 aktualisiert, Features und Config-Dateien synchronisiert
- `vix_strategy.py`: DEPRECATED-Marker korrekt — betrifft nur `MarketRegime` Alias, Modul selbst aktiv genutzt

## TWS-Umstellung (Phase 8)

- Zielport: 7497 (TWS Paper)
- Geänderte Dateien CORE: `config/system.yaml` (port 4001 → 7497)
- Geänderte Dateien WEB: `json_routes.py` (IBKR_PORT default 4001 → 7497), `ibkr_quote.py` (4001 → 7497), `ibkr_news.py` (4001 → 7497)
- VIX-Test via TWS: nicht separat getestet (VIX via Tradier primär)
- Verbindungstest via TWS: OK (`_ensure_connected()` auf 127.0.0.1:7497)
- Fallback-Kette: Tradier primär, TWS sekundär (unverändert)
- readonly-Flag: aktiv (hardcoded `readonly=True` in `connection.py:190`)

## Test-Ergebnis

- OptionPlay Core: 5895 passed, 36 skipped, 0 failed
- OptionPlay-Web: 32 passed, 0 failed
- Vorbestehend: 1 E2E-Test (`test_get_vix`) schlägt fehl (Mock vs. Live-Daten — nicht durch Alignment verursacht)
