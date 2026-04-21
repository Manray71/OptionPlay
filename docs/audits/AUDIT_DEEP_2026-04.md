# Tiefen-Audit: services / cache / utils / analyzers

**Datum:** 2026-04-15
**Scope:** `src/services/`, `src/cache/`, `src/utils/`, `src/analyzers/`
**Methodik:** grep-basierte Import-Analyse (`from src.<dir>.<modul>` und Namensreferenzen);
LOC via `wc -l`; Tests = distinct Testdateien die das Modul beim Namen importieren oder
referenzieren; Aufrufer = Dateien *ausserhalb* des eigenen Verzeichnisses die das Modul
direkt importieren. Aufrufer via `src.<dir>.__init__`-Re-exports werden in der Tabelle mit
"(via pkg)" vermerkt, sind aber nicht als direkter Aufrufer aufgelistet.

---

## src/services/ (21 Dateien, 10 447 LOC)

### Datei-fur-Datei-Tabelle

| Datei | LOC | Zweck | Tests | Aufrufer (ausserhalb src/services/) |
|---|---|---|---|---|
| `__init__.py` | 117 | Re-Export aller Service-Klassen | - | - |
| `base.py` | 226 | Basisklasse fur alle Services mit API-Key, Rate Limiting, Circuit Breaker, Caching | 4 | src/analyzers/{base,bounce,pullback,pool,feature_scoring_mixin}.py |
| `enhanced_scoring.py` | 417 | Addiert Bonus-Multiplikatoren auf Signal-Score, re-rankt daily_picks | 1 | src/container.py (1x) |
| `entry_quality_scorer.py` | 491 | Bewertet Einstiegszeitpunkt durch 7 gewichtete Faktoren (IV Rank, IV Pct, Credit Ratio, Theta, Pullback, RSI, Trend) | 1 | 0 — nur intern (recommendation_engine.py) |
| `iv_analyzer.py` | 420 | Berechnet IV Rank und IV Percentile; wrappt iv_cache_impl mit DB-Fallback | 1 | 0 — kein Aufrufer in src/ gefunden |
| `options_chain_validator.py` | 454 | Pruft ob Bull-Put-Spread echte Marktdaten hat (IBKR / Provider-Fallback) | 1 | src/handlers/scan.py (1x) |
| `options_service.py` | 490 | Service fur Options-Chain-Abfragen und Strike-Empfehlungen | 2 | 0 — nur intern (server_core.py) |
| `pick_formatter.py` | 431 | Markdown-Formatierung fur DailyPicks und DailyRecommendationResult | 0 ⚠ | 0 — nur intern (recommendation_engine.py, position_monitor.py) |
| `portfolio_constraints.py` | 546 | Portfolio-Constraints: Positionslimits, Sektor-Diversifikation, Risiko-Budget, Korrelations-Warnungen | 3 | src/handlers/{portfolio,portfolio_composed,validate}.py |
| `position_monitor.py` | 672 | Uberwacht offene Positionen, generiert Exit-Signale per PLAYBOOK §4 | 3 | src/handlers/{monitor,monitor_composed}.py |
| `quote_service.py` | 426 | Service fur Quote-Abfragen (Single/Batch, Caching, Formatierung) | 2 | 0 — nur intern (server_core.py) |
| `recommendation_engine.py` | 701 | Daily Recommendation Engine: Multi-Strategy-Scan, Stability-Filter, VIX-Regime, Sektor-Diversifikation | 2 | src/handlers/{scan,scan_composed}.py |
| `recommendation_ranking.py` | 595 | Ranking-Mixin: Speed-Scoring, Strike-Empfehlung; ausgelagert aus DailyRecommendationEngine | 1 | 0 — nur intern (recommendation_engine.py) |
| `scanner_service.py` | 490 | Service fur Multi-Strategy-Scanning; konsolidiert Duplikat-Methoden aus mcp_server.py | 2 | 0 — nur intern (server_core.py) |
| `sector_rs.py` | 792 | Sektor-Relative-Strength mit RRG-Quadranten; ersetzt SectorCycleService (additiver Score-Modifier) | 2 | src/handlers/{vix,vix_composed}.py, src/scanner/multi_strategy_scanner.py |
| `server_core.py` | 385 | Zentraler Koordinator fur alle Service-Instanzen und ServerState | 1 | 0 — Instanz wird uber src/services/__init__.py exportiert |
| `signal_filter.py` | 185 | Filter-Logik fur Trading-Signale nach PLAYBOOK-Regeln (Blacklist, Stability, Sektor) | 0 ⚠ | 0 — nur intern (recommendation_engine.py, position_monitor.py) |
| `trade_validator.py` | 991 | Validiert Trade-Ideen gegen PLAYBOOK-Regeln; liefert GO/NO_GO/WARNING | 3 | src/handlers/{validate,validate_composed}.py |
| `vix_regime.py` | 478 | VIX Regime v2: Kontinuierliche Interpolation mit 7 Ankerpunkten, Term-Structure- und Trend-Overlay | 1 | src/constants/trading_rules.py, src/handlers/{validate,vix_composed}.py, src/scanner/multi_strategy_scanner.py |
| `vix_service.py` | 291 | VIX-Daten und Strategie-Empfehlungen mit 5-min-Cache (IBKR TWS -> Yahoo Finance Fallback) | 4 | 0 — nur intern (scanner_service.py, server_core.py) |
| `vix_strategy.py` | 849 | VIX Strategy Selector: VIX-Trend-Analyse, automatische Strategie-Auswahl | 6 | src/handlers/{analysis,analysis_composed,base,handler_container,vix}.py |

### Auffalligkeiten src/services/

1. **pick_formatter.py + signal_filter.py: 0 Tests, 0 externe Aufrufer.** Beide werden ausschliesslich von `recommendation_engine.py` und `position_monitor.py` innerhalb von services/ verwendet. Sie wurden laut Docstring als Phase-3.2-Extraktion aus `recommendation_engine.py` ausgelagert, haben aber seitdem keine eigene Testabdeckung erhalten.

2. **iv_analyzer.py: kein Aufrufer in src/.** Das Modul definiert einen IVAnalyzer-Wrapper uber `iv_cache_impl.py`, ist aber weder von anderen Services noch von Handlern noch vom Container importiert. Es existiert 1 Testdatei (`test_iv_analyzer.py`), aber kein Produktionscode ruft es auf.

3. **Mehrere Services ohne externen Direktaufruf, nur uber server_core.py erreichbar:** `options_service.py`, `quote_service.py`, `scanner_service.py`, `vix_service.py`, `entry_quality_scorer.py`, `recommendation_ranking.py`. Alle laufen uber server_core.py als zentralen Koordinator. Das ist das gewollte Composition-Muster, erhoht aber die Zugrifftiefe.

4. **vix_strategy.py (849 LOC) ist das am meisten extern referenzierte Modul** (5 Handler-Dateien). Es ist gleichzeitig das zweitgrosste in services/.

5. **trade_validator.py (991 LOC) ist das grosste Modul** im Verzeichnis und hat 3 Testdateien. Das Modul referenziert intern `signal_filter.py` und `pick_formatter.py`.

6. **server_core.py (385 LOC): 1 Testdatei, kein direkter externer Import.** Wird nur uber `services/__init__.py` exportiert. Funktion als "Koordinator" uberschneidet sich konzeptionell mit `container.py` in src/.

### Konkrete Verschlankungs-Hypothesen src/services/

**H-S1: pick_formatter.py und signal_filter.py in recommendation_engine.py einbetten**
- Beide Module wurden aus `recommendation_engine.py` ausgelagert (Docstring belegt das). Sie haben keine eigenen Tests, keine externen Aufrufer und zusammen 616 LOC.
- Einbettung zuruck in `recommendation_engine.py` ware revertieren der Phase-3.2-Auslagerung.
- Alternativ: Testabdeckung erganzen, dann ist der Status quo vertretbar.
- Geschatzte Einsparung: 2 Dateien, ~50 LOC Overhead (Importe, Datei-Header), keine LOC-Reduktion sonst.
- Risiko: Niedrig (keine externen Abhangigkeiten).
- Zu prufen: Werden pick_formatter oder signal_filter von position_monitor.py unabhangig von recommendation_engine genutzt?

**H-S2: iv_analyzer.py prufen ob totes Modul**
- Kein Produktionscode importiert `IVAnalyzer`. Das Modul wrappt `iv_cache_impl.py`, welches direkt nutzbar ist.
- Wenn der Wrapper nur fur ein zukunftiges Refactoring vorgesehen war, kann er entfernt werden.
- Geschatzte Einsparung: 420 LOC.
- Risiko: Niedrig (kein Produktionscode betroffen), sofern Verifikation bestatigt.
- Zu prufen: `grep -r "IVAnalyzer" src/` auf 0 Treffer prufen; Testdatei `test_iv_analyzer.py` zeigt ob Klasse nur isoliert getestet wird.

**H-S3: server_core.py mit container.py konsolidieren**
- `server_core.py` koordiniert Service-Instanzen; `container.py` ist der DI-Container mit 11 Singletons. Beide losen das selbe Problem (zentrale Service-Verwaltung) auf unterschiedlichen Ebenen.
- Konsolidierung wurde eine Zugriffs-Ebene eliminieren.
- Geschatzte Einsparung: ~200-385 LOC (Koordinator-Boilerplate).
- Risiko: Hoch — betrifft alle Handler und den gesamten Composition-Stack.
- Zu prufen: Welche Teile von server_core.py nicht in container.py abgedeckt sind (z.B. ServerState, Lifecycle-Management).

**H-S4: recommendation_ranking.py als privates Mixin halten, aber Tests nachliefern**
- recommendation_ranking.py (595 LOC) ist ein internes Mixin fur recommendation_engine.py ohne externen Aufrufer. Es hat 1 Testdatei. Der Status quo (Auslagerung fur Lesbarkeit) ist vertretbar, aber ohne Tests fur die ausgelagerten Methoden bleibt coverage-Lucke.
- Empfehlung: Keine strukturelle Anderung, aber `tests/unit/test_recommendation_ranking.py` ausbauen.
- Geschatzte Einsparung: 0 LOC, aber Coverage-Gewinn.
- Risiko: Niedrig.

---

## src/cache/ (12 Dateien, 6 203 LOC)

### Datei-fur-Datei-Tabelle

| Datei | LOC | Zweck | Tests | Aufrufer (ausserhalb src/cache/) |
|---|---|---|---|---|
| `__init__.py` | 157 | Re-Export aller Cache-Klassen (57 Symbole) | - | - |
| `cache_manager.py` | 765 | Zentralisierte Cache-Verwaltung mit koordinierter Invalidierung | 2 | 0 — via pkg |
| `dividend_history.py` | 456 | Dividenden-Historie (ex_date, amount); AnalysisContext-Integration | 2 | 0 — via pkg |
| `earnings_cache.py` | 43 | Re-Export-Stub fur earnings_cache_impl | 2 | 0 — via pkg |
| `earnings_cache_impl.py` | 771 | Earnings-Cache mit Multi-Source-Abruf und TTL | 0 ⚠ | 0 — nur intern (via earnings_cache.py) |
| `earnings_history.py` | 865 | Earnings History Manager: EPS-Daten, BMO/AMC-Checks, Earnings-Safety | 2 | src/config/watchlist_loader.py (1x) |
| `historical_cache.py` | 464 | Cache fur historische Kursdaten mit TTL; Klassen: HistoricalCache, CacheStatus, CacheLookupResult | 2 | 0 — via pkg (cache/__init__.py exportiert hieraus) |
| `iv_cache.py` | 57 | Re-Export-Stub fur iv_cache_impl | 3 | 0 — via pkg |
| `iv_cache_impl.py` | 994 | Implied Volatility History, IV Rank und IV Percentile; DB-Abfragen | 2 | 0 — via pkg |
| `iv_calculator.py` | 152 | Pure-Math-Funktionen fur IV-Berechnungen (Black-Scholes, Newton-Raphson) | 0 ⚠ | 0 — nur intern (iv_cache_impl.py) |
| `symbol_fundamentals.py` | 1 089 | Symbol Fundamentals Manager: Stability Scores, Win Rates, Sektor, Beta | 1 | src/config/watchlist_loader.py (1x) |
| `vix_cache.py` | 390 | VIX-Tagesdaten mit DB-Fallback (IBKR TWS -> Yahoo Finance) | 1 | 0 — via pkg |

### Auffalligkeiten src/cache/

1. **earnings_cache_impl.py (771 LOC): 0 direkte Testdateien.** Tests laufen nur indirekt uber `earnings_cache.py`. Da `earnings_cache.py` (43 LOC) ausschliesslich ein Re-Export-Stub ist, testet `test_earnings_cache.py` faktisch die Impl-Datei, aber kein Test-Import referenziert `earnings_cache_impl` direkt. Das erschwert gezielte Unit-Test-Erweiterungen.

2. **iv_calculator.py (152 LOC): 0 Tests, 1 interner Aufrufer.** Reine Math-Funktionen (Black-Scholes, Newton-Raphson). Kein Test pruft die Korrektheit dieser Berechnungen isoliert. Der einzige Caller ist `iv_cache_impl.py`.

3. **Doppelter Re-Export-Stub-Layer:** `earnings_cache.py` (43 LOC) und `iv_cache.py` (57 LOC) sind reine Stubs die zur Impl weiterleiten. `cache/__init__.py` exportiert dieselben Symbole nochmals. Drei Ebenen fur denselben Zugriffsweg.

4. **symbol_fundamentals.py (1 089 LOC) ist das grosste Modul** des Verzeichnisses. Konfiguriert Stability Scores, Fundamentals-Fetching, Liquidity-Tier-Klassifizierung und DB-Persistenz in einer Datei. Nur 1 direkte Testdatei.

5. **Parallel zu src/utils/historical_cache.py:** In `src/utils/` existiert eine WEITERE Datei `historical_cache.py` (386 LOC) mit anderen Klassen (`HistoricalDataCache`, `CacheEntry`) — nicht identisch mit `src/cache/historical_cache.py` (`HistoricalCache`, `CacheLookupResult`, `CacheStatus`). Beide decken "historische Kursdaten mit TTL" ab. `container.py` importiert aus `src.utils.historical_cache`; `cache/__init__.py` aus `src.cache.historical_cache`.

6. **earnings_history.py (865 LOC) und earnings_cache_impl.py (771 LOC)** decken beide Earnings-Daten ab, mit unterschiedlichem Fokus: `earnings_history.py` = EPS + BMO/AMC-Safety-Checks (historisch); `earnings_cache_impl.py` = kurzfristiger Cache mit Multi-Source-Abruf. Architektonisch getrennt, aber thematisch eng verwandt.

### Konkrete Verschlankungs-Hypothesen src/cache/

**H-C1: Re-Export-Stubs earnings_cache.py und iv_cache.py entfernen**
- Beide Stubs delegieren ausschliesslich an die jeweilige _impl-Datei. `cache/__init__.py` re-exportiert dieselben Symbole bereits. Kein Code importiert die Stubs direkt — alle Imports gehen uber `from src.cache import ...`.
- Entfernung der Stubs eliminiert einen uberflussigen Indirektions-Layer.
- Geschatzte Einsparung: 100 LOC, 2 Dateien.
- Risiko: Niedrig — Zu prufen: `grep -r "from src.cache.earnings_cache import\|from src.cache.iv_cache import"` gibt 0 Treffer.
- Nacharbeiten: Inhalte von _impl-Dateien korrekt in __init__.py benennen (was bereits der Fall ist).

**H-C2: iv_calculator.py mit iv_cache_impl.py zusammenfuhren**
- 152 LOC reine Math-Funktionen mit 1 Caller. Kein Test pruft die Implementierung isoliert.
- Einbettung in `iv_cache_impl.py` als private Sektion reduziert Datei-Overhead; alternativ eine separate `tests/unit/test_iv_calculator.py` erstellen.
- Geschatzte Einsparung: 1 Datei, ~20 LOC Overhead.
- Risiko: Niedrig (1 Caller, keine externen Abhangigkeiten).

**H-C3: src/utils/historical_cache.py mit src/cache/historical_cache.py zusammenfuhren**
- Zwei Implementierungen mit identischem Zweck ("historische Kursdaten mit TTL"), unterschiedlichen Klassen-Namen und unterschiedlichen Callern. `container.py` nutzt die utils-Version; `cache/__init__.py` die cache-Version.
- Konsolidierung auf eine Implementierung (die featurereichere cache-Version: 464 LOC) und Migration von `container.py`.
- Geschatzte Einsparung: 386 LOC.
- Risiko: Mittel — API der utils-Version (`HistoricalDataCache`) weicht von der cache-Version (`HistoricalCache`) ab. Migration von `container.py` notwendig.
- Zu prufen: Welche Methoden nutzt `container.py` von `HistoricalDataCache`? Sind diese in `HistoricalCache` vorhanden?

**H-C4: symbol_fundamentals.py aufteilen**
- 1 089 LOC in einer Datei deckt: DB-Fetching, Stability-Score-Berechnung, Liquidity-Tier-Klassifizierung, Market-Cap-Kategorisierung, Singleton-Management. Das sind 4-5 unterscheidbare Verantwortlichkeiten.
- Aufteilung in `symbol_fundamentals_db.py` (Fetching) + `symbol_fundamentals_scoring.py` (Score-Logik) wurde Testbarkeit verbessern.
- Geschatzte Einsparung: 0 LOC, aber erhohte Testbarkeit der Score-Logik.
- Risiko: Mittel — Refactoring erfordert Aktualisierung aller Imports.

---

## src/utils/ (14 Dateien, 6 025 LOC, exkl. __init__.py)

### Datei-fur-Datei-Tabelle

| Datei | LOC | Zweck | Tests | Aufrufer (ausserhalb src/utils/) |
|---|---|---|---|---|
| `__init__.py` | 218 | Re-Export von 79 Symbolen | - | - |
| `circuit_breaker.py` | 562 | Circuit Breaker fur API-Verbindungen mit State Machine (CLOSED/OPEN/HALF_OPEN) | 5 | src/container.py, src/handlers/{base,handler_container}.py, src/mcp_server.py, src/services/base.py |
| `deprecation.py` | 164 | Deprecation-Warnungen fur DI-Migration; dekoriert alte Singleton-Getter | 1 | src/cache/{iv_cache_impl,cache_manager,historical_cache,earnings_cache_impl}.py, src/config/core.py, src/{container,data_providers/local_db}.py u.a. |
| `earnings_aggregator.py` | 370 | Multi-Source Earnings Aggregator mit Majority-Voting (yfinance, alpha_vantage, OpenBB) | 1 | src/container.py, src/handlers/{quote,quote_composed}.py |
| `error_handler.py` | 600 | Unified Error Handling fur MCP-Server-Endpoints; Exception-Hierarchie, Dekoratoren | 1 | src/handlers/{analysis,ibkr,monitor,portfolio,quote}.py u.a. (>10 Aufrufer) |
| `historical_cache.py` | 386 | Cache fur historische Kursdaten mit TTL; Klassen: HistoricalDataCache, CacheEntry | 2 | src/container.py (1x) |
| `markdown_builder.py` | 539 | Fluent Builder fur konsistente Markdown-Formatierung (Tabellen, Sektionen, Badges) | 2 | src/formatters/{output_formatters,portfolio_formatter}.py, src/handlers/{analysis,analysis_composed,ibkr}.py u.a. (>10 Aufrufer) |
| `metrics.py` | 392 | Einfache Metriken-Erfassung (Counter, Gauge, Histogram) fur Observability | 2 | src/mcp_main.py, src/mcp_server.py |
| `provider_orchestrator.py` | 362 | Intelligente Multi-Provider-Strategie mit Rate Limiting (ProviderType, DataType) | 1 | src/handlers/quote.py (1x), src/mcp_server.py (1x) |
| `rate_limiter.py` | 458 | Rate Limiting via Token-Bucket (AdaptiveRateLimiter, retry_with_backoff) | 1 | src/container.py, src/handlers/{base,handler_container}.py, src/mcp_server.py, src/services/base.py |
| `request_dedup.py` | 178 | Dedupliziert gleichzeitige identische Requests zur API-Call-Reduktion | 2 | src/handlers/{base,handler_container}.py, src/mcp_server.py |
| `scanner_config_loader.py` | 321 | Zentrales Laden der Scanner-Konfiguration aus YAML-Dateien | 1 | src/analyzers/pullback_scoring.py, src/container.py, src/scanner/multi_strategy_scanner.py |
| `secure_config.py` | 462 | Sichere Verwaltung von API-Keys und sensiblen Daten; .env-Loading | 2 | src/mcp_main.py, src/mcp_server.py, src/services/base.py |
| `structured_logging.py` | 454 | JSON-basiertes Structured Logging (StructuredFormatter, get_logger, log_context) | 1 | 0 — kein Aufrufer in src/ gefunden (nur __init__.py re-exportiert) |
| `validation.py` | 559 | Zentrale Validierungsfunktionen fur alle Inputs (Symbol, DTE, Delta, Spread-Parameter) | 7 | src/handlers/{analysis,analysis_composed,ibkr,ibkr_composed,portfolio,scan,validate}.py (>15 Aufrufer) |

### Auffalligkeiten src/utils/

1. **structured_logging.py (454 LOC): 0 Produktions-Aufrufer in src/.** Das Modul ist in `__init__.py` re-exportiert, aber kein Produktionscode in `src/` ruft `get_logger`, `StructuredLogger` oder `configure_logging` auf. Tests konnen das Modul verwenden. Mogliches verwaistes Infrastruktur-Modul.

2. **utils/historical_cache.py parallel zu cache/historical_cache.py** (Details: Befund H-C3 oben). `utils/historical_cache.py` (386 LOC) ist nicht in `utils/__init__.py` re-exportiert, hat aber `container.py` als Aufrufer.

3. **provider_orchestrator.py (362 LOC): nur 2 Aufrufer** (handlers/quote.py, mcp_server.py). Da Tradier als Provider entfernt wurde (2026-04-09), ist zu prufen ob der Orchestrator noch mehrere aktive Provider verwaltet oder nur IBKR TWS und Yahoo Finance.

4. **deprecation.py (164 LOC): aktiv genutzt in >9 Dateien.** Das Modul dekoriert alte Singleton-Getter mit Deprecation-Warnungen fur die DI-Migration. Solange die alten Getter noch existieren, wird das Modul benotigt.

5. **error_handler.py (600 LOC) und validation.py (559 LOC): hoch frequentiert** (>10 bzw. >15 Aufrufer). Beide Module sind stabile, breit eingesetzte Infrastruktur.

6. **Nicht in __init__.py exportiert:** `deprecation`, `earnings_aggregator`, `historical_cache`, `request_dedup`, `scanner_config_loader`. Diese 5 Module sind entweder intern oder in Ubergang.

### Konkrete Verschlankungs-Hypothesen src/utils/

**H-U1: structured_logging.py Status klaren**
- 454 LOC ohne Produktions-Aufrufer in src/. Entweder: (a) das Modul wurde durch Standard-logging ersetzt und kann entfernt werden, oder (b) es ist fur kuenftige Observability vorgesehen und der Status ist klar dokumentiert.
- Aktion: `grep -r "get_logger\|StructuredLogger\|configure_logging" tests/` prufen ob Tests den Logger nutzen. Falls nur Tests darauf zugreifen, entweder entfernen oder in CLAUDE.md als "noch nicht aktiviert" markieren.
- Geschatzte Einsparung: 454 LOC.
- Risiko: Niedrig bis Mittel — Zu prufen ob MCP-Startup-Code oder externe Integrations-Tests darauf setzen.

**H-U2: provider_orchestrator.py auf aktiven Umfang prufen**
- Tradier wurde 2026-04-09 entfernt. `ProviderOrchestrator` unterstutzte ursprunglich Tradier + Marketdata.app + IBKR. Mit IBKR als einzigem Live-Provider konnte der Orchestrator zu einem einfachen Wrapper reduziert werden oder entfallen.
- Geschatzte Einsparung: bis zu 362 LOC.
- Risiko: Mittel — `ProviderConfig`, `ProviderStats`, `ProviderType` werden ggf. von quote.py direkt genutzt.
- Zu prufen: Welche ProviderTypes sind in provider_orchestrator.py noch aktiv konfiguriert?

**H-U3: utils/historical_cache.py eliminieren (Teil von H-C3)**
- Identisch mit H-C3. Migration von `container.py` auf `cache.HistoricalCache` und Loschen von `utils/historical_cache.py`.
- Geschatzte Einsparung: 386 LOC.
- Risiko: Mittel.

---

## src/analyzers/ (9 Dateien + __init__.py, 5 297 LOC)

### Datei-fur-Datei-Tabelle

| Datei | LOC | Zweck | Tests | Aufrufer (ausserhalb src/analyzers/) |
|---|---|---|---|---|
| `__init__.py` | 61 | Re-Export: BaseAnalyzer, BounceAnalyzer, PullbackAnalyzer, AnalysisContext, AnalyzerPool, BatchScorer, score_normalization | - | - |
| `base.py` | 153 | Abstraktes Interface fur alle Strategie-Analyzer | 2 | src/scanner/multi_strategy_scanner.py (1x) |
| `batch_scorer.py` | 129 | Ersetzt Per-Symbol-Loop durch NumPy-Matrixmultiplikation | 1 | src/scanner/multi_strategy_scanner.py (1x) |
| `bounce.py` | 1 259 | Analysiert Bounces von etablierten Support-Levels | 3 | src/scanner/multi_strategy_scanner.py (1x) |
| `context.py` | 658 | Vorberechnete Shared-Values fur Analyzer zur Vermeidung redundanter Berechnungen | 11 | src/scanner/multi_strategy_scanner.py (1x) |
| `feature_scoring_mixin.py` | 360 | Shared Scoring-Methoden aus Feature-Engineering fur alle Analyzer | 2 | src/scanner/multi_strategy_scanner.py (1x) |
| `pool.py` | 538 | Object-Pooling fur Analyzer-Instanzen zur Performance-Optimierung | 1 | src/scanner/multi_strategy_scanner.py, src/container.py |
| `pullback.py` | 954 | Technische Analyse fur Pullback-Kandidaten | 3 | src/scanner/multi_strategy_scanner.py (1x) |
| `pullback_scoring.py` | 882 | Scoring-Methoden ausgelagert aus PullbackAnalyzer zur Modulgrosse-Reduktion | 2 | 0 — nur intern (pullback.py, bounce.py, feature_scoring_mixin.py) |
| `score_normalization.py` | 242 | Zentrale Normalisierung aller Strategie-Scores auf 0-10-Skala | 3 | src/scanner/multi_strategy_ranker.py (1x) |

### Auffalligkeiten src/analyzers/

1. **Einziger externer Aufrufer: src/scanner/multi_strategy_scanner.py.** Alle Analyzer-Module werden ausschliesslich vom Scanner konsumiert (+ container.py fur pool.py). Das Verzeichnis ist ein geschlossenes Subsystem des Scanners.

2. **pullback_scoring.py (882 LOC) ohne externen Aufrufer.** Es wurde aus `pullback.py` ausgelagert, wird intern von `pullback.py`, `bounce.py` und `feature_scoring_mixin.py` genutzt. Der Docstring bestatigt die Auslagerung war motiviert durch Modulgrosse.

3. **bounce.py ist das grosste Modul (1 259 LOC).** Enthalt Analyse-Logik + Scoring-Methoden. pullback.py hat seine Scoring-Logik in pullback_scoring.py ausgelagert, bounce.py hingegen nicht.

4. **context.py (658 LOC): am starksten getestet (11 Testdateien).** AnalysisContext ist die zentrale Datenstruktur, uber die alle Analyzer kommunizieren.

5. **batch_scorer.py (129 LOC): 1 Testdatei, 1 externer Aufrufer.** Kleines Modul mit klarer Funktion (NumPy-Optimierung). Verwendung als optionaler Import (`try/except ImportError`) in `__init__.py` deutet auf optionale numpy-Abhangigkeit hin.

6. **score_normalization.py (242 LOC): nur 1 externer Aufrufer** (`multi_strategy_ranker.py`). Wird intern von bounce.py und pullback.py genutzt. Ist in `__init__.py` re-exportiert.

### Konkrete Verschlankungs-Hypothesen src/analyzers/

**H-A1: bounce.py Scoring-Logik analog zu pullback.py auslagern**
- bounce.py (1 259 LOC) ist das grosste Modul; pullback.py (954 LOC) hat seine Scoring-Logik bereits in `pullback_scoring.py` ausgelagert. Die gleiche Logik fur bounce.py ware konsistent.
- Geschatzte Einsparung: 0 LOC (Auslagerung, keine Loschung), aber bounce.py wurde auf ca. 600-700 LOC sinken.
- Risiko: Niedrig — Refactoring innerhalb von analyzers/, kein externer Caller benotigt Anderung.
- Zu prufen: Gibt es uberlappende Scoring-Logik zwischen pullback_scoring.py und bounce-Scoring, die konsolidiert werden konnte?

**H-A2: pullback_scoring.py als privates Modul kennzeichnen**
- pullback_scoring.py hat 0 externe Aufrufer und ist nicht in `__init__.py` re-exportiert. Der Modulstatus ("ausgelagert fur Lesbarkeit") ist korrekt dokumentiert.
- Keine strukturelle Anderung notwendig; `_pullback_scoring.py` (underscore-Prafix) wurde den privaten Status explizit machen.
- Geschatzte Einsparung: 0 LOC.
- Risiko: Niedrig — Erfordert Umbenennung + Import-Aktualisierung in 3 Dateien.

**H-A3: batch_scorer.py prufens ob numpy-Abhangigkeit aktiv genutzt wird**
- `batch_scorer.py` wird uber `try/except ImportError` importiert; `BatchScorer` wird in `__init__.py` als `None` exportiert wenn numpy fehlt. Zu prufen ob `multi_strategy_scanner.py` den `None`-Fall tatschlich handhabt oder ob numpy immer vorhanden ist.
- Falls numpy immer in der Umgebung, kann der optionale Import und der `None`-Guard entfernt werden.
- Geschatzte Einsparung: ~20 LOC Guard-Logik.
- Risiko: Niedrig.

---

## Querschnitts-Beobachtungen

### Module im "falschen" Verzeichnis

| Modul | Aktuelles Verzeichnis | Vorschlag | Begruendung |
|---|---|---|---|
| `src/utils/historical_cache.py` | utils/ | cache/ | Ist ein Cache-Modul. Parallele Implementierung in cache/ vorhanden. |
| `src/services/iv_analyzer.py` | services/ | cache/ oder loschen | Wrappt `cache/iv_cache_impl.py`, keine Service-Logik. Hat keinen externen Aufrufer. |
| `src/services/pick_formatter.py` | services/ | formatters/ | Laut Docstring pure Presentation-Logik. `src/formatters/` existiert bereits. |
| `src/services/signal_filter.py` | services/ | scanner/ oder in recommendation_engine | Filter-Logik die spezifisch fur Scan-Ergebnisse ist; kein Handler- oder Service-Level. |

### Top-5-Verschlankungs-Empfehlungen (sortiert nach LOC-Einsparung x inversem Risiko)

**1. H-U1: structured_logging.py entfernen (454 LOC, Risiko Niedrig)**
Kein einziger Produktionscode-Aufrufer in src/. Das Modul ist re-exportiert aber inaktiv.
Verifikation dauert 2 Minuten (grep). Bei Bestatigung: direktes Loschen + Bereinigung von
`__init__.py`. Hohes LOC/Risiko-Verhaltnis.

**2. H-C3 + H-U3: utils/historical_cache.py eliminieren (386 LOC, Risiko Mittel)**
Zwei Implementierungen gleichen Zwecks in verschiedenen Verzeichnissen. `container.py` als
einziger Caller der utils-Version kann auf die featurereichere cache-Version migriert werden.
Loscht 1 Datei komplett.

**3. H-S2: iv_analyzer.py (services/) auf totes Modul prufen und ggf. loschen (420 LOC, Risiko Niedrig)**
Kein Produktionscode ruft `IVAnalyzer` auf. Falls Verifikation bestatigt (grep auf 0 Treffer),
420 LOC mit 1 Testdatei entfernbar. Wrapper-Funktionalitat steckt bereits in iv_cache_impl.py.

**4. H-C1: Re-Export-Stubs earnings_cache.py + iv_cache.py entfernen (100 LOC, Risiko Niedrig)**
Zwei uberflussige Indirektions-Layer. `cache/__init__.py` re-exportiert dieselben Symbole
bereits direkt. Keine Produktionscode-Importe uber die Stubs (zu verifizieren). Kleine aber
klare Bereinigung.

**5. H-U2: provider_orchestrator.py auf Post-Tradier-Umfang prufen (bis 362 LOC, Risiko Mittel)**
Tradier wurde 2026-04-09 entfernt. Der Orchestrator fur Multi-Provider-Strategie verliert
seinen primaren Anwendungsfall wenn nur noch IBKR TWS + Yahoo Finance aktiv sind.
Kann zu einfachem Wrapper oder direktem IBKR-Aufruf degenerieren.

---

*Ende des Audits. Alle Aussagen basieren auf Code/Import-Analyse via grep und wc -l. Keine Verhaltens-Spekulation.*
