# Audit: src/handlers/ — _composed-Pattern
**Datum:** 2026-04-15
**Version:** 5.0.0
**Scope:** Alle 23 Dateien in `src/handlers/`

---

## Zusammenfassung

`src/handlers/` enthält ein **duales Architektur-System** mitten in einer Migration:

- **10 Composed Handler** (aktiv, seit Phase 3.3): `VixHandler`, `ScanHandler`, `QuoteHandler`, `AnalysisHandler`, `PortfolioHandler`, `IbkrHandler`, `ReportHandler`, `RiskHandler`, `ValidateHandler`, `MonitorHandler`
- **10 Legacy Mixins** (deprecated, für Test-Kompatibilität): `VixHandlerMixin`, `ScanHandlerMixin`, etc.
- **3 Infrastruktur-Dateien**: `base.py`, `handler_container.py`, `__init__.py`

**Befund:** Legacy-Dateien sind keine dünnen Stubs — sie enthalten vollständige Implementierungen, die nach der Migration von den `_composed`-Versionen **divergiert** sind. Beide Versionen existieren parallel im Code.

---

## 1. Inventur — Alle 23 Dateien

| Datei | LOC | Typ | Zweck (aus Docstring) | Tests | Aufrufer außerhalb `handlers/` |
|-------|-----|-----|-----------------------|-------|-------------------------------|
| `__init__.py` | 94 | Export | Exports beider Architekturen (Mixin + Composed) | — | — |
| `base.py` | 188 | Interface | `BaseHandlerMixin` — abstrakte Attribute/Methoden für alle Mixin-Handler | — | `src/handlers/*.py` (Mixin-Erben) |
| `handler_container.py` | 407 | Infrastruktur | `ServerContext`, `BaseHandler`, `HandlerContainer`, `create_handler_container_from_server()` | `test_handler_container.py` (26 Tests) | `src/mcp_server.py` (L48, `server.handlers`-Property) |
| `vix.py` | 315 | Legacy Mixin | VIX-Abfrage, Strategie-Empfehlung, Sektoren (deprecated) | `test_vix_handler.py` (15 Tests) | `src/handlers/__init__.py` |
| `vix_composed.py` | 433 | **Composed (aktiv)** | VIX-Abfrage, VIX Regime v2, Sektor RS, Eventkalender | `test_vix_composed_handler.py` (29 Tests) | `mcp_tool_registry.py` (L238, L260, L693) |
| `scan.py` | 862 | Legacy Mixin | Pullback/Bounce-Scan, Daily Picks (deprecated) | `test_scan_handler.py` (56 Tests)* | `src/handlers/__init__.py` |
| `scan_composed.py` | 1098 | **Composed (aktiv)** | Pullback/Bounce/Multi-Scan, Daily Picks mit Chain-Validation | `test_scan_handler.py` (56 Tests)* | `mcp_tool_registry.py` (L288, L302, L339) |
| `quote.py` | 578 | Legacy Mixin | Kursabfrage, Options-Chain, Earnings, historische Daten (deprecated) | `test_quote_handler.py` (50 Tests)* | `src/handlers/__init__.py` |
| `quote_composed.py` | 597 | **Composed (aktiv)** | Kursabfrage mit IBKR, Earnings mit Multi-Source-Fallback | `test_quote_handler.py` (50 Tests)* | `mcp_tool_registry.py` (L360, L379, L401, L415) |
| `analysis.py` | 509 | Legacy Mixin | Symbol-Analyse für Bull-Put-Spread-Eignung (deprecated) | `test_analysis_handler.py` (13 Tests)* | `src/handlers/__init__.py` |
| `analysis_composed.py` | 611 | **Composed (aktiv)** | Symbol-Analyse, Ensemble-Empfehlung, Strike-Empfehlung | `test_analysis_handler.py` (13 Tests)* | `mcp_tool_registry.py` (L476, L487, L510) |
| `portfolio.py` | 369 | Legacy Mixin | Portfolio-Verwaltung (deprecated) | `test_portfolio_handler.py` (49 Tests)* | `src/handlers/__init__.py` |
| `portfolio_composed.py` | 389 | **Composed (aktiv)** | Portfolio-Positionen, Add/Close/Expire, P&L | `test_portfolio_handler.py` (49 Tests)* | `mcp_tool_registry.py` (L531, L547, L571, L598, L617, L639) |
| `ibkr.py` | 186 | Legacy Mixin | IBKR-Bridge: Status, News, MaxPain, Portfolio (deprecated) | `test_ibkr_handler.py` (25 Tests)* | `src/handlers/__init__.py` |
| `ibkr_composed.py` | 198 | **Composed (aktiv)** | IBKR TWS: Status, News, MaxPain, Batch-Quotes | `test_ibkr_handler.py` (25 Tests)* | `mcp_tool_registry.py` (indirekt via `vix.get_sector_status`) |
| `validate.py` | 213 | Legacy Mixin | Trade-Validierung gegen PLAYBOOK-Regeln (deprecated) | `test_validate_handler.py` (12 Tests)* | `src/handlers/__init__.py` |
| `validate_composed.py` | 205 | **Composed (aktiv)** | Trade-Validierung: Spread-Parameter, VIX-Regime, Positionslimit | `test_validate_handler.py` (12 Tests)* | `mcp_tool_registry.py` (L443) |
| `monitor.py` | 191 | Legacy Mixin | Positions-Monitoring: CLOSE/ROLL/ALERT/HOLD (deprecated) | `test_monitor_handler.py` (19 Tests)* | `src/handlers/__init__.py` |
| `monitor_composed.py` | 184 | **Composed (aktiv)** | Positions-Monitoring via IBKR-Spreads + internes Portfolio | `test_monitor_handler.py` (19 Tests)* | `mcp_tool_registry.py` (L461) |
| `report.py` | 290 | Legacy Mixin | Daily-Report, Portfolio-Report, Trade-Log-Export (deprecated) | `test_report_handler.py` (17 Tests)* | `src/handlers/__init__.py` |
| `report_composed.py` | 280 | **Composed (aktiv)** | PDF/HTML-Berichte und CSV-Export | `test_report_handler.py` (17 Tests)* | nicht in `mcp_tool_registry.py` (kein MCP-Tool registriert) |
| `risk.py` | 357 | Legacy Mixin | Spread-Analyse, Kelly-Sizing, Stop-Loss (deprecated) | `test_risk_handler.py` (12 Tests)* | `src/handlers/__init__.py` |
| `risk_composed.py` | 352 | **Composed (aktiv)** | Spread-Analyse, Kelly-Kriterium, VIX-adjustiertes Sizing | `test_risk_handler.py` (12 Tests)* | `mcp_tool_registry.py` (L671) |

**Gesamt:** 23 Dateien | 8.906 LOC
_* Tests testen beide Versionen (Mixin + Composed) via gemeinsame Fixtures_

---

## 2. Das _composed-Pattern

### Infrastruktur: `handler_container.py`

Der Kern des _composed-Patterns besteht aus drei Klassen:

```
ServerContext   — Zentrales Kontext-Objekt (alle geteilten Services + State)
BaseHandler     — Basisklasse aller Composed Handler (hält _ctx: ServerContext)
HandlerContainer — Lazy-initialisierender Container (Properties: .vix, .scan, etc.)
```

**Zugriffspfad** (aus `mcp_server.py:L48+L195`):
```python
# mcp_server.py
@property
def handlers(self) -> HandlerContainer:          # Lazy init
    if self._handler_container is None:
        self._handler_container = create_handler_container_from_server(self)
    return self._handler_container

# mcp_tool_registry.py
return await server.handlers.vix.get_strategy_recommendation()
return await server.handlers.scan.daily_picks(...)
```

**`ServerContext`-Felder** (aus `handler_container.py:L45-95`):

| Kategorie | Felder |
|-----------|--------|
| Config | `config`, `scanner_config` |
| Provider | `provider`, `ibkr_provider`, `ibkr_bridge` |
| Infrastruktur | `rate_limiter`, `circuit_breaker`, `historical_cache`, `deduplicator` |
| Strategy | `vix_selector` |
| State | `connected`, `ibkr_connected`, `current_vix`, `vix_updated` |
| Caches | `quote_cache`, `scan_cache`, `scan_cache_ttl` |
| Stats | `quote_cache_hits/misses`, `scan_cache_hits/misses` |
| Optional | `earnings_fetcher`, `scanner`, `container` (ServiceContainer) |

---

### Paarweise Vergleiche: Legacy vs. Composed

#### `vix.py` (315 LOC) vs. `vix_composed.py` (433 LOC)

| Aspekt | `vix.py` (Mixin) | `vix_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **Klasse** | `VixHandlerMixin(BaseHandlerMixin)` | `VixHandler(BaseHandler)` |
| **LOC** | 315 | 433 (+118, +37%) |
| **Methoden** | `get_vix`, `get_strategy_recommendation`, `get_regime_status`, `get_strategy_for_stock`, `get_event_calendar`, `get_sector_status` (6) | `get_vix`, `get_strategy_recommendation`, `get_regime_status`, `get_regime_status_v2`, `get_strategy_for_stock`, `get_event_calendar`, `get_sector_status` (7) |
| **Aufgerufen von** | `__init__.py` (Export), Mixin-Tests | `mcp_tool_registry.py` L238, L260, L693 |
| **Eigene Business-Logik?** | Ja — Yahoo-VIX-Fetch, Strategie-Auswahl, Sektor-RS | Ja — gleich + VIX-Regime-v2 (Interpolation, Term Structure) |
| **Kritischer Unterschied** | `get_regime_status()` gibt Stub zurück: `"Regime status requires composed handler (VIX v2 active)"` (vix.py L146) | `get_regime_status_v2()` vollständig implementiert mit kontinuierlicher Interpolation |
| **Services** | `_config`, `IBKRDataProvider`, Yahoo-API direkt | `_ctx.ibkr_provider`, `get_regime_params()`, `SectorRSService`, `EventCalendar` |

**Befund:** Die Legacy-Version hat einen expliziten Stub für `get_regime_status`, der signalisiert, dass VIX v2 nur im Composed Handler existiert. Die Divergenz ist dokumentiert und beabsichtigt.

---

#### `scan.py` (862 LOC) vs. `scan_composed.py` (1098 LOC)

| Aspekt | `scan.py` (Mixin) | `scan_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **Klasse** | `ScanHandlerMixin(BaseHandlerMixin)` | `ScanHandler(BaseHandler)` |
| **LOC** | 862 | 1098 (+236, +27%) |
| **Öffentliche Methoden** | `scan_with_strategy`, `scan_pullback_candidates`, `scan_bounce`, `scan_multi_strategy`, `daily_picks` (5) | gleich (5) |
| **Private Methoden** | `_execute_scan`, `_make_scan_cache_key`, `_apply_chain_validation`, `_format_daily_picks_output`, `_format_single_pick_v2`, `_format_single_pick_detail` | `_execute_scan`, `_make_scan_cache_key`, `_format_single_pick_v2`, **`_shadow_log_picks`**, **`_apply_earnings_prefilter`**, **`_get_multi_scanner`**, **`_get_options_chain_with_fallback`**, **`_fetch_historical_cached`** |
| **Aufgerufen von** | `__init__.py` (Export), Tests | `mcp_tool_registry.py` L288, L302, L339 |
| **Eigene Business-Logik?** | Hoch — vollständiger Scan-Pipeline inkl. Chain-Validation | Hoch — gleich + Shadow-Logging, explizites Earnings-Prefilter, erweiterte Fallback-Logik |
| **Größtes Alleinstellungsmerkmal composed** | — | `_shadow_log_picks()` (L741): Shadow-Portfolio für Post-Mortem-Analyse |
| **Services (composed)** | `_ctx.scanner`, `_ctx.historical_cache`, `DailyRecommendationEngine`, `OptionsChainValidator` | gleich + `ShadowPortfolioManager` |

**Befund:** Größter Handler (1098 LOC). Der Composed Handler hat zusätzliche Methoden, die nach der Migration eingebaut wurden. Die Legacy-Version ist eine **eingefrorene Kopie** des Stands zur Migrationszeit — nicht aktiv weiterentwickelt.

---

#### `quote.py` (578 LOC) vs. `quote_composed.py` (597 LOC)

| Aspekt | `quote.py` (Mixin) | `quote_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **Klasse** | `QuoteHandlerMixin(BaseHandlerMixin)` | `QuoteHandler(BaseHandler)` |
| **LOC** | 578 | 597 (+19, +3%) |
| **Methoden** | `get_quote`, `get_options_chain`, `get_earnings`, `get_earnings_aggregated`, `earnings_prefilter`, `get_historical_data`, `get_expirations`, `validate_for_trading` (8) | gleich + `_fetch_yahoo_earnings` (9) |
| **Aufgerufen von** | `__init__.py`, Tests | `mcp_tool_registry.py` L360, L379, L401, L415 |
| **Eigene Business-Logik?** | Mittel — Multi-Source Earnings-Fallback (DB → Yahoo → yfinance) | Mittel — gleich, expliziter private `_fetch_yahoo_earnings()` extrahiert |
| **Services** | IBKR Provider, `EarningsHistoryManager`, `EarningsFetcher` | gleich via `_ctx` |

**Befund:** Nahezu identisch. Die 19 LOC Differenz kommt vom extrahierten `_fetch_yahoo_earnings()`. Geringste Divergenz aller Paare.

---

#### `analysis.py` (509 LOC) vs. `analysis_composed.py` (611 LOC)

| Aspekt | `analysis.py` (Mixin) | `analysis_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **Klasse** | `AnalysisHandlerMixin(BaseHandlerMixin)` | `AnalysisHandler(BaseHandler)` |
| **LOC** | 509 | 611 (+102, +20%) |
| **Methoden** | `analyze_symbol`, `analyze_multi_strategy`, `get_ensemble_recommendation`, `get_ensemble_status`, `recommend_strikes` (5) | gleich (5) |
| **Private Helpers** | `_fetch_earnings_cached`, `_fetch_historical_cached`, `_get_scanner` | gleich + `_get_multi_scanner`, `_get_options_chain_with_fallback` |
| **Aufgerufen von** | `__init__.py`, Tests | `mcp_tool_registry.py` L476, L487, L510 |
| **Eigene Business-Logik?** | Mittel — Multi-Strategy Scoring, Ensemble-Integration | Mittel — gleich + expliziter IBKR-Fallback für Options-Chain |
| **Services** | `FundamentalsManager`, `MultiStrategyScanner`, `EnsembleStrategySelector`, `OptionsChainValidator` | gleich via `_ctx` |

**Befund:** +102 LOC durch expliziten `_get_multi_scanner()` und `_get_options_chain_with_fallback()` — diese wurden nach der Migration ergänzt.

---

#### `portfolio.py` (369 LOC) vs. `portfolio_composed.py` (389 LOC)

| Aspekt | `portfolio.py` (Mixin) | `portfolio_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **LOC** | 369 | 389 (+20, +5%) |
| **Methoden** | 11 (alle Portfolio-Operationen) | 11 (identisch) |
| **Eigene Business-Logik?** | Keine — delegiert an `PortfolioManager` | Keine — delegiert an `PortfolioManager` |
| **Services** | `get_portfolio_manager()`, `get_constraint_checker()` | gleich |

**Befund:** Funktional identisch. Rein mechanischer Austausch `self` → `BaseHandler`. Kein Risiko.

---

#### `ibkr.py` (186 LOC) vs. `ibkr_composed.py` (198 LOC)

| Aspekt | `ibkr.py` (Mixin) | `ibkr_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **LOC** | 186 | 198 (+12, +6%) |
| **Methoden** | `get_ibkr_status`, `get_news`, `get_max_pain`, `get_ibkr_portfolio`, `get_ibkr_spreads`, `get_ibkr_vix`, `get_ibkr_quotes` (7) | gleich (7) |
| **Eigene Business-Logik?** | Keine — delegiert an `IBKRBridge` | Keine — delegiert an `IBKRBridge` |
| **MCP-Tool registriert?** | Nein | Nein (kein eigenes Tool; Sektor-Status via `vix.get_sector_status`) |

**Befund:** Funktional identisch. `ibkr_composed.py` hat kein eigenes MCP-Tool — IBKR-Funktionen werden entweder über `VixHandler.get_sector_status()` oder direkt via `IBKRBridge` aufgerufen.

---

#### `validate.py` (213 LOC) vs. `validate_composed.py` (205 LOC)

| Aspekt | `validate.py` (Mixin) | `validate_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **LOC** | 213 | 205 (−8, −4%) |
| **Methoden** | `validate_trade` (1 öffentlich) | gleich |
| **Eigene Business-Logik?** | Keine — delegiert an `TradeValidator` | Keine |
| **Besonderheit** | Enthält `from ..handlers.portfolio import _get_portfolio_db` (L195) — interner Handler-zu-Handler-Import | Nutzt `_ctx.ibkr_bridge` und `get_portfolio_manager()` |

**Befund:** Legacy-Datei hat einen direkten Import aus `portfolio.py` (`_get_portfolio_db`) — Handler-zu-Handler-Coupling, das im Composed-Ansatz durch `_ctx` aufgelöst ist.

---

#### `monitor.py` (191 LOC) vs. `monitor_composed.py` (184 LOC)

| Aspekt | `monitor.py` (Mixin) | `monitor_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **LOC** | 191 | 184 (−7, −4%) |
| **Methoden** | `monitor_positions` (1 öffentlich) | gleich + `_collect_position_snapshots`, `_format_monitor_result`, `_signal_icon`, `_format_pnl` |
| **Eigene Business-Logik?** | Keine — delegiert an `PositionMonitor` | Keine — delegiert an `PositionMonitor` |
| **Services** | `get_position_monitor()`, `IBKRBridge.get_spreads()` | gleich via `_ctx` |

**Befund:** Funktional identisch, Composed-Version hat private Helper explizit extrahiert.

---

#### `report.py` (290 LOC) vs. `report_composed.py` (280 LOC)

| Aspekt | `report.py` (Mixin) | `report_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **LOC** | 290 | 280 (−10, −3%) |
| **Methoden** | `generate_daily_report`, `generate_portfolio_report`, `generate_trade_log` (3) | gleich (3) |
| **Eigene Business-Logik?** | Keine — delegiert an `ReportGenerator` | Keine |
| **MCP-Tool registriert?** | Nein | **Nein** — kein Tool in `mcp_tool_registry.py` |

**Befund:** `ReportHandler` ist aktiv (in `HandlerContainer` registriert), aber kein MCP-Tool gibt ihn preis. Nur intern nutzbar.

---

#### `risk.py` (357 LOC) vs. `risk_composed.py` (352 LOC)

| Aspekt | `risk.py` (Mixin) | `risk_composed.py` (aktiv) |
|--------|-----------------|--------------------------|
| **LOC** | 357 | 352 (−5, −1%) |
| **Methoden** | `analyze_spread`, `calculate_position_size`, `calculate_stop_loss` (3) | gleich (3) |
| **Eigene Business-Logik?** | Mittel — orchestriert `SpreadAnalyzer` + `PositionSizer` + VIX-Adjustment | Mittel — gleich |
| **Services** | `SpreadAnalyzer`, `PositionSizer`, `_current_vix` | `_ctx` → `SpreadAnalyzer`, `PositionSizer`, `_get_vix()` |

**Befund:** Nahezu identisch. Composed nutzt `_get_vix()` aus `BaseHandler` statt direktem `_current_vix`.

---

## 3. MCP-Tool-Registry

Alle Tools in `mcp_tool_registry.py` routen ausschließlich über das Composed-Pattern:

| Handler | MCP-Tools | Registry-Zeilen |
|---------|-----------|----------------|
| `vix` | `optionplay_vix`, `optionplay_regime_status`, `optionplay_sector_status` | L238, L260, L693 |
| `scan` | `optionplay_scan`, `optionplay_scan_bounce`, `optionplay_daily_picks` | L288, L302, L339 |
| `quote` | `optionplay_quote`, `optionplay_options`, `optionplay_earnings`, `optionplay_expirations` | L360, L379, L401, L415 |
| `analysis` | `optionplay_analyze`, `optionplay_ensemble`, `optionplay_strikes` | L476, L487, L510 |
| `portfolio` | `optionplay_portfolio`, `optionplay_portfolio_positions`, `optionplay_portfolio_add`, `optionplay_portfolio_close`, `optionplay_portfolio_expire`, `optionplay_portfolio_check` | L531–L639 |
| `validate` | `optionplay_validate_trade` | L443 |
| `monitor` | `optionplay_monitor_positions` | L461 |
| `risk` | `optionplay_spread_analysis` | L671 |
| `report` | — | (kein Tool) |
| `ibkr` | — | (kein direktes Tool) |

**Gesamte MCP-Tools: 20** (nicht 25 — `ibkr` und `report` sind ohne eigenes Tool)

---

## 4. Befunde und Empfehlungen

### Befund 1 — Legacy-Dateien sind keine Stubs

Die 10 Legacy-Mixin-Dateien sind **vollständige, funktionierende Implementierungen**, nicht leere Hüllen. Sie exportiert `__init__.py` explizit, und Tests importieren sie via gemeinsame Fixtures.

- Beispiel: `vix.py` hat 315 LOC mit vollem Yahoo-Fetch, Sektor-RS, Eventkalender.
- Ausnahme: `vix.py:get_regime_status()` gibt bewusst einen Stub zurück (`"Regime status requires composed handler"`) — das ist die einzige dokumentierte intentionale Divergenz.

**Risiko:** Wer aus Tests oder anderen Modulen `VixHandlerMixin` importiert, bekommt eine veraltete Version ohne Regime v2. Dies passiert in `test_vix_handler.py` (15 Tests).

### Befund 2 — Divergenz ist real, nicht nur mechanisch

Die Composed-Versionen wurden nach der Migration weiterentwickelt. Neue Methoden existieren nur in den Composed Dateien:

| Methode | Composed-Datei | Legacy-Datei |
|---------|---------------|-------------|
| `get_regime_status_v2()` | `vix_composed.py` | ✗ (Stub) |
| `_shadow_log_picks()` | `scan_composed.py` | ✗ |
| `_apply_earnings_prefilter()` | `scan_composed.py` | ✗ |
| `_get_options_chain_with_fallback()` | `scan_composed.py`, `analysis_composed.py` | ✗ |

### Befund 3 — Handler-zu-Handler-Coupling im Legacy-Code

`validate.py:L195` importiert direkt `_get_portfolio_db` aus `portfolio.py`:
```python
from ..handlers.portfolio import _get_portfolio_db
```
Im Composed-Pendant wird dies über `_ctx.ibkr_bridge` und `get_portfolio_manager()` gelöst. Das Legacy-Coupling ist ein konkretes Argument, die Migration abzuschließen.

### Befund 4 — `ReportHandler` ohne MCP-Tool

`report_composed.py` ist in `HandlerContainer` registriert (`handler_container.py:L334`), aber kein Tool in `mcp_tool_registry.py` exponiert ihn. Entweder ist das Feature unvollständig oder die Tools wurden entfernt ohne den Handler zu löschen.

### Befund 5 — `ScanHandler` ist zu groß

Mit 1098 LOC enthält `ScanHandler` mehrere orthogonale Verantwortlichkeiten:
- Scan-Execution-Pipeline
- 30-Minuten-Cache-Logik
- Earnings-Prefilter
- Chain-Validation (Phase 2)
- Shadow-Logging
- Markdown-Formatierung (mehrere Format-Methoden)

Das macht `scan_composed.py` schwer isoliert zu testen und zu warten.

---

## 5. Empfehlungen (priorisiert)

| Prio | Empfehlung | Aufwand | Grund |
|------|-----------|---------|-------|
| 1 | **Legacy-Mixin-Dateien löschen** | Mittel | 10 Dateien (3.476 LOC) die aktiv Verwirrung stiften. Voraussetzung: Tests auf Composed-Klassen umstellen. Blocker: `test_vix_handler.py`, `test_scan_handler.py` etc. testen noch Mixins direkt. | 
| 2 | **`report_composed.py` aufräumen** | Klein | Entweder MCP-Tool ergänzen oder `ReportHandler` aus `HandlerContainer` entfernen. Aktuell toter Code-Pfad. |
| 3 | **`validate.py:L195` Handler-Import entfernen** | Klein | `from ..handlers.portfolio import _get_portfolio_db` ist Coupling zwischen Legacy-Modulen — sollte nach Mixin-Löschung nicht mehr existieren. |
| 4 | **`ScanHandler` aufteilen** | Groß | Split in `ScanCore` (Pipeline), `ScanCacheManager` (TTL-Logik), `ScanFormatter` (Markdown). Verbessert Testbarkeit. |
| 5 | **`base.py` deprecieren** | Klein | `BaseHandlerMixin` wird nur noch von den Legacy-Mixins gebraucht. Fällt mit Empfehlung 1 weg. |

---

## Anhang: `ServerContext`-Felder nach Quelle

```python
# handler_container.py:L45 — Pflichtfelder
config: Config                         # src/config.py
provider: Optional[Any]               # Legacy-Provider (nicht mehr aktiv)
ibkr_provider: Optional[IBKRDataProvider]  # IBKR TWS (primary)
rate_limiter: AdaptiveRateLimiter
circuit_breaker: CircuitBreaker
historical_cache: HistoricalCache
vix_selector: VIXStrategySelector
deduplicator: RequestDeduplicator
container: Optional[ServiceContainer] # DI-Container (11 Singletons)
server_state: Optional[ServerState]

# Mutable shared state
connected: bool
ibkr_connected: bool
current_vix: Optional[float]
vix_updated: Optional[datetime]
quote_cache: Dict[str, tuple]
scan_cache: Dict[str, tuple]
scan_cache_ttl: int = 1800             # 30 Minuten

# Optionale Services
earnings_fetcher: Optional[EarningsFetcher]
scanner: Optional[MultiStrategyScanner]
ibkr_bridge: Optional[IBKRBridge]
```
