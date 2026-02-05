# OptionPlay — Refactoring-Strategie mit Recursive Logic

**Datum:** 5. Februar 2026  
**Basis:** CODEBASE_ANALYSIS.md v4.0.0 · 335 Dateien · 152 src/ · ~40K LoC  
**Ansatz:** Recursive Decomposition & Self-Similar Pattern Consolidation

---

## Was ist Recursive Logic im Software-Kontext?

Recursive Logic bedeutet: **dasselbe Prinzip auf jeder Ebene anwenden.** Statt ein Problem einmalig von oben zu lösen, zerlegt man es so, dass jede Teilebene die gleiche Struktur aufweist wie das Ganze. Das ergibt:

- **Selbstähnlichkeit:** Ein Modul ist intern genauso aufgebaut wie die Gesamtarchitektur
- **Rekursive Zerlegung:** Jedes Problem wird in gleichartige Teilprobleme aufgeteilt, bis Atome übrig bleiben
- **Fixpunkt-Konvergenz:** Iterative Verbesserungen konvergieren, weil die Struktur stabil ist

Für OptionPlay heißt das konkret: Die Architektur besteht bereits aus rekursiven Mustern (Analyzer → Score → SubScore → Feature). Die Strategie macht diese Rekursion explizit, konsistent und durchgängig.

---

## Rekursive Diagnose: Probleme auf jeder Ebene

### Ebene 0 — Gesamtsystem (335 Dateien)

```
OptionPlay v4.0.0
├── Stärken: Saubere Layer, keine Zyklen, 8/10 Architecture Score
├── Schwäche: 349 Orphans, Duplikation, 87 lose Singletons
└── Kern-Metrik: 40K LoC src/ bei ~2K LoC tatsächlich "heißem" Code
```

**Rekursive Beobachtung:** Das System hat eine klare Top-Level-Struktur (MCP → Handlers → Services → Core), aber innerhalb der Module wiederholt sich dieselbe Unordnung: Große Dateien mit gemischten Verantwortlichkeiten.

### Ebene 1 — Module (14 Packages)

```
Backtesting [500K] → Enthält: Engine, Tracking, Training, ML, Simulation, Validation
Analyzers   [200K] → Enthält: 4 Strategien + Scoring + Normalisierung + Pooling
Services    [200K] → Enthält: Recommendation, Validation, Monitoring, Constraints
Indicators  [145K] → Enthält: 69 Orphan-Funktionen, RSI an 4 Stellen
```

**Rekursive Beobachtung:** Jedes Modul hat intern dasselbe Problem wie das Gesamtsystem — eine klare Kernfunktion umgeben von angeflanschten Hilfsfunktionen ohne klare Grenze.

### Ebene 2 — Dateien (Top-20 Riesen)

```
multi_strategy_scanner.py [67K] → Scanning + Dispatch + Aggregation + Ranking
config_loader.py          [61K] → Core + Strategy + Provider + Validation
trade_tracker.py          [58K] → Schema + Queries + Logic + Statistics + Formatting
```

**Rekursive Beobachtung:** Jede Riesendatei enthält 3–5 verschiedene Verantwortlichkeiten, die jeweils eigenständige Module sein könnten.

### Ebene 3 — Funktionen (600+)

```
analyze()          → Wird 16× aufgerufen, orchestriert _score_*() und _calculate_*()
_score_pullback()  → Ruft 5+ Feature-Scorer auf
_score_momentum()  → Berechnet RSI, MACD, Stochastic intern statt aus indicators/
```

**Rekursive Beobachtung:** Funktionen duplizieren Logik, die eigentlich in tieferen Schichten leben sollte. Der Score-Baum ist bereits rekursiv — aber inkonsistent implementiert.

### Ebene 4 — Patterns (Querschnitt)

```
Singleton Pattern  → 87× get_*()/reset_*() ohne Container
Error Handling     → 2 überlappende Dekoratoren (sync + async)
Caching            → Manuelles Caching statt deklarativem Pattern
DB-Zugriff         → 127× cursor.execute() ohne Abstraktion
```

**Rekursive Beobachtung:** Dieselben Cross-Cutting Concerns werden auf jeder Ebene neu gelöst, statt einmal definiert und rekursiv angewendet.

---

## Die Recursive-Logic-Strategie: 4 Rekursionsstufen

Die Idee: **Ein einziges Refactoring-Pattern, das sich selbst auf jeder Ebene anwendet.**

```
PATTERN: Identify → Extract → Unify → Reconnect

Auf System-Ebene:    Module identifizieren → Klare Grenzen extrahieren → Interfaces vereinheitlichen
Auf Modul-Ebene:     Verantwortlichkeiten identifizieren → Dateien extrahieren → Contracts vereinheitlichen
Auf Datei-Ebene:     Funktionsgruppen identifizieren → Klassen extrahieren → APIs vereinheitlichen
Auf Funktions-Ebene: Duplizierung identifizieren → Gemeinsame Logik extrahieren → Aufruf vereinheitlichen
```

---

## Stufe 1: Rekursive Kern-Extraktion — "Was ist das Atom?"

### Prinzip

Jede Ebene wird auf ihren **Kern** reduziert. Was ist die kleinstmögliche, in sich geschlossene Einheit, die das Gleiche tut wie das Ganze?

### Anwendung auf die 7 Hub-Module

Die 7 Hub-Module (6+ Importe) bilden das "Skelett" des Systems:

```
handlers/base.py       [11 Importer] → ATOM: Request → Validate → Dispatch → Format
utils/error_handler.py  [9 Importer] → ATOM: Try → Execute → Catch → Log → Return
utils/markdown_builder.py [8 Importer] → ATOM: Data → Template → Markdown
analyzers/base.py       [6 Importer] → ATOM: Symbol → Features → Scores → Signal
utils/validation.py     [6 Importer] → ATOM: Input → Rules → Valid/Invalid
models/result.py        [5 Importer] → ATOM: Operation → Success/Failure + Data
analyzers/context.py    [5 Importer] → ATOM: Symbol + Market State → Analysis Context
```

**Aktion:** Jedes Atom bekommt exakt ein Interface, einen Vertrag, einen Test:

```python
# Das universelle Atom-Interface für OptionPlay
class Atom(Protocol):
    """Jede Komponente auf jeder Ebene implementiert dieses Pattern."""
    
    def validate(self, input: Any) -> ValidationResult:
        """Rekursionsbasis: Ist der Input gültig?"""
        ...
    
    def process(self, input: Any) -> ProcessResult:
        """Rekursionsschritt: Input → Output"""
        ...
    
    def format(self, result: ProcessResult) -> str:
        """Rekursionsabschluss: Result → Darstellung"""
        ...
```

Das ist kein theoretisches Konstrukt — es beschreibt exakt, was jeder Handler, jeder Analyzer, jeder Service bereits tut. Der Unterschied: Aktuell macht es jeder anders.

---

## Stufe 2: Rekursive Baum-Normalisierung — "Gleiche Tiefe, gleiche Breite"

### Prinzip

Der Dependency-Graph ist ein Baum. Rekursive Logik verlangt: **Jeder Knoten hat die gleiche Struktur.** Aktuell ist der Baum asymmetrisch:

```
AKTUELL (asymmetrisch):
Backtesting/  → 16 Dateien, 500K, 100+ Funktionen
Pricing/      →  2 Dateien,  43K,  23 Funktionen
Portfolio/    →  1 Datei            
Risk/         →  1 Datei            
```

### Ziel-Struktur: Rekursiv balanciert

```
ZIEL (balanciert, jedes Modul = 3–8 Dateien, 50–150K):
backtesting/
├── core/           # engine.py, runner.py
├── tracking/       # trade_tracker_schema.py, trade_tracker_logic.py, trade_tracker_stats.py
├── training/       # regime_trainer.py, walk_forward.py, ml_weight_optimizer.py
├── models/         # ensemble_selector.py, regime_model.py, regime_config.py
├── simulation/     # options_simulator.py, real_options_backtester.py
└── validation/     # signal_validation.py, reliability.py, metrics.py
```

### Konkrete Zerlegungen

#### 2a. `multi_strategy_scanner.py` (67K → 3 Dateien)

```
scanner/
├── engine.py           # scan_async(), Orchestrierung         (~25K)
├── strategy_dispatch.py # Strategy-Routing, Analyzer-Pool      (~20K)  
└── result_aggregator.py # SignalAggregator, Ranking, Formatting (~22K)
```

Die Rekursion: `engine.py` ruft `strategy_dispatch.py` auf, das ruft Analyzer auf, die jeweils `_score_*()` aufrufen — jede Ebene hat Input → Process → Output.

#### 2b. `config_loader.py` (61K → 4 Dateien)

```
config/
├── core.py              # get_config(), Basislogik             (~15K)
├── strategy_config.py   # Strategie-spezifische Parameter      (~15K)
├── provider_config.py   # Data-Provider-Konfiguration          (~15K)
└── validation.py        # Config-Validierung und Defaults      (~16K)
```

#### 2c. `trade_tracker.py` (58K → 3 Dateien)

```
backtesting/tracking/
├── schema.py       # DB-Schema, Prepared Statements, Migrations (~18K)
├── operations.py   # CRUD, Batch-Ops mit executemany()          (~20K)
└── analytics.py    # Statistics, P&L, format_trade_stats()      (~20K)
```

Die 50 `execute()`-Aufrufe werden in `schema.py` als Prepared Statements zentralisiert, `operations.py` nutzt nur noch Referenzen.

#### 2d. `black_scholes.py` (41K → 2 Dateien)

```
pricing/
├── models.py       # BS-Formeln, Greeks, IV (pure math)        (~25K)
└── spreads.py      # Spread-Pricing, Batch-PnL (angewandt)    (~16K)
```

---

## Stufe 3: Rekursive Duplikat-Eliminierung — "Single Source of Truth durch Rekursion"

### Prinzip

Wenn dieselbe Berechnung an mehreren Stellen auftaucht, ist das ein Zeichen für fehlende Rekursionstiefe. Die Lösung: Eine kanonische Funktion auf der tiefsten Ebene, die alle höheren Ebenen rekursiv nutzen.

### 3a. Der RSI-Fall (4 Stellen → 1)

Aktuell:
```
indicators/momentum.py:14   → calculate_rsi()         # Standard
indicators/momentum.py:112  → calculate_rsi_series()   # Mit Zeitreihe
indicators/optimized.py:71  → calc_rsi_numpy()         # NumPy-optimiert
analyzers/pullback.py:~???  → inline RSI-Berechnung    # Duplikat
```

Rekursive Lösung:
```python
# indicators/momentum.py — Die EINZIGE RSI-Quelle
def calculate_rsi(
    prices: np.ndarray, 
    period: int = 14,
    engine: Literal["standard", "numpy"] = "numpy"
) -> np.ndarray:
    """Rekursionsbasis: Ein RSI, ein Ort, ein Interface."""
    if engine == "numpy" and len(prices) > 100:
        return _rsi_numpy(prices, period)
    return _rsi_standard(prices, period)

def calculate_rsi_series(prices: np.ndarray, period: int = 14) -> pd.Series:
    """Rekursionsschritt: Wraps calculate_rsi mit Pandas-Output."""
    return pd.Series(calculate_rsi(prices, period))
```

Alle Analyzer importieren aus `indicators/momentum.py`. Kein Analyzer berechnet RSI selbst.

### 3b. Das Singleton-Factory-Problem (87 Paare → 1 Container)

Aktuell — jeder Service hat sein eigenes get/reset Paar:
```python
_instance = None
def get_trade_validator():
    global _instance
    if _instance is None:
        _instance = TradeValidator(get_config())
    return _instance

def reset_trade_validator():
    global _instance
    _instance = None
```

Rekursive Lösung — Ein Container, der das Pattern rekursiv auf alle Services anwendet:
```python
class ServiceContainer:
    """Rekursiver DI-Container: Dasselbe Pattern für jeden Service."""
    
    _registry: dict[str, type] = {}
    _instances: dict[str, Any] = {}
    _dependencies: dict[str, list[str]] = {}
    
    @classmethod
    def register(cls, name: str, factory: type, depends_on: list[str] = None):
        cls._registry[name] = factory
        cls._dependencies[name] = depends_on or []
    
    @classmethod
    def get(cls, name: str) -> Any:
        """Rekursive Auflösung: Jede Dependency wird genauso aufgelöst."""
        if name not in cls._instances:
            deps = {d: cls.get(d) for d in cls._dependencies.get(name, [])}
            cls._instances[name] = cls._registry[name](**deps)
        return cls._instances[name]
    
    @classmethod
    def reset(cls, name: str = None):
        if name:
            cls._instances.pop(name, None)
            # Rekursiv: Alles resetten, was von name abhängt
            for svc, deps in cls._dependencies.items():
                if name in deps:
                    cls.reset(svc)
        else:
            cls._instances.clear()

# Registration (einmalig beim Startup)
ServiceContainer.register("config", ConfigLoader)
ServiceContainer.register("cache", CacheManager, depends_on=["config"])
ServiceContainer.register("fundamentals", FundamentalsManager, depends_on=["config", "cache"])
ServiceContainer.register("trade_validator", TradeValidator, depends_on=["config", "fundamentals"])
```

Der Container löst Dependencies rekursiv auf. `reset("config")` kaskadiert automatisch.

### 3c. Das Error-Handling-Problem (2 Dekoratoren → 1)

```python
def endpoint(func):
    """Rekursiver Endpoint-Dekorator: Erkennt async/sync automatisch."""
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                return _handle_error(func.__name__, e)
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return _handle_error(func.__name__, e)
        return sync_wrapper
```

---

## Stufe 4: Rekursive Qualitätssicherung — "Jede Ebene testet sich selbst"

### Prinzip

Tests folgen derselben Rekursion wie der Code. Jede Ebene hat Tests, die exakt die Atome dieser Ebene prüfen.

### Aktuelle Test-Struktur vs. Rekursive Ziel-Struktur

```
AKTUELL: 140+ Test-Dateien, 80K LoC — aber Verteilung unklar

ZIEL (spiegelt src/ rekursiv):
tests/
├── unit/                    # Ebene 4: Funktions-Tests
│   ├── indicators/          # Jede Funktion isoliert
│   ├── pricing/             # BS-Formeln mathematisch verifiziert
│   └── models/              # Datenklassen-Contracts
├── component/               # Ebene 3: Datei/Klassen-Tests
│   ├── analyzers/           # Analyzer mit Mock-Daten
│   ├── cache/               # Cache-Verhalten
│   └── services/            # Service-Logik
├── integration/             # Ebene 2: Modul-Tests
│   ├── scan_pipeline/       # Scanner → Analyzer → Scorer
│   ├── data_pipeline/       # Provider → Cache → Service
│   └── trade_pipeline/      # Validate → Execute → Track
└── system/                  # Ebene 1: End-to-End
    ├── mcp_tools/           # MCP-Call → Result
    └── daily_picks/         # Vollständiger Picks-Durchlauf
```

### Rekursives Test-Atom

```python
class RecursiveTestPattern:
    """Jeder Test auf jeder Ebene folgt diesem Pattern."""
    
    def test_valid_input_produces_valid_output(self):
        """Rekursionsbasis: Happy Path"""
        ...
    
    def test_invalid_input_returns_error(self):
        """Rekursionsbasis: Error Path"""
        ...
    
    def test_edge_cases_are_handled(self):
        """Rekursionsschritt: Grenzen"""
        ...
    
    def test_performance_within_bounds(self):
        """Rekursionsabschluss: Nicht-funktionale Anforderung"""
        ...
```

---

## Umsetzungsplan: Rekursive Wellen

Die Umsetzung folgt selbst einem rekursiven Muster: Jede Welle wendet dasselbe Refactoring auf einer tieferen Ebene an.

### Welle 1 — Foundation (Woche 1–2): Atome definieren

| # | Aktion | Dateien | Risiko |
|---|--------|---------|--------|
| 1.1 | ServiceContainer implementieren | 1 neue Datei | Niedrig |
| 1.2 | `endpoint()` Dekorator vereinheitlichen | utils/error_handler.py | Niedrig |
| 1.3 | 5 kritische Docstrings schreiben | 5 Dateien | Keins |
| 1.4 | ~50 True Orphans entfernen | ~15 Dateien | Niedrig (Tests) |

**Rekursions-Check:** Nach Welle 1 hat das System einen einzigen DI-Mechanismus, einen einzigen Error-Handler, und ist um ~50 tote Funktionen leichter.

### Welle 2 — Module (Woche 3–5): Bäume balancieren

| # | Aktion | Von → Nach | Impact |
|---|--------|------------|--------|
| 2.1 | `multi_strategy_scanner.py` aufteilen | 1 → 3 Dateien | Hoch |
| 2.2 | `config_loader.py` aufteilen | 1 → 4 Dateien | Hoch |
| 2.3 | `trade_tracker.py` aufteilen | 1 → 3 Dateien | Hoch |
| 2.4 | `backtesting/` Unterstruktur einführen | flach → 6 Sub-Packages | Mittel |
| 2.5 | 87 Singleton-Factories → Container migrieren | 87 Funktionen | Mittel |

**Rekursions-Check:** Nach Welle 2 hat kein File mehr als 25K. Jedes Modul hat 3–8 Dateien mit je einer Verantwortlichkeit.

### Welle 3 — Funktionen (Woche 6–8): Duplikate eliminieren

| # | Aktion | Scope | Einsparung |
|---|--------|-------|-----------|
| 3.1 | RSI/MACD/ATR-Konsolidierung | indicators/ + analyzers/ | ~2K LoC |
| 3.2 | DB-Zugriff abstrahieren (Prepared Statements) | backtesting/ | Performance |
| 3.3 | Cache-Aufrufe konsolidieren (`@cached_property`) | handlers/ | ~200 Aufrufe |
| 3.4 | Score-Baum normalisieren | analyzers/ | Konsistenz |
| 3.5 | `format_*()` Pipeline vereinheitlichen | formatters/ + handlers/ | ~3K LoC |

**Rekursions-Check:** Nach Welle 3 gilt Single Source of Truth für jeden Indikator, jedes Scoring-Pattern, jede Formatierung.

### Welle 4 — Härtung (Woche 9–12): Rekursive Tests + Types

| # | Aktion | Scope | Benefit |
|---|--------|-------|---------|
| 4.1 | Test-Struktur rekursiv umbauen | tests/ | Klarheit |
| 4.2 | Type Hints für Hub-Module | 7 Dateien | IDE + Docs |
| 4.3 | Type Hints für Models | 9 Dateien | API-Contracts |
| 4.4 | Type Hints für Services | 16 Dateien | Refactoring-Sicherheit |
| 4.5 | Performance-Benchmarks für DB-Hotspots | backtesting/ | Messbarkeit |

---

## Metriken: Vorher → Nachher

| Metrik | Aktuell | Nach Welle 4 | Verbesserung |
|--------|---------|-------------|-------------|
| Größte Datei | 67K | ≤25K | -63% |
| Orphan-Funktionen | 349 | ~200 | -43% |
| True Dead Code | ~50 | 0 | -100% |
| Singleton-Factories | 87 lose Paare | 1 Container | Strukturell |
| RSI-Berechnungen | 4 Stellen | 1 Stelle | Single Source |
| Error-Dekoratoren | 2 überlappend | 1 vereinheitlicht | Konsistenz |
| DB `execute()` Aufrufe | 127 roh | ~30 prepared | -76% |
| Module ohne Unterstruktur | backtesting/ (16 flach) | 6 Sub-Packages | Navigierbarkeit |
| Architecture Quality Score | 8/10 | 9/10 | +1 |

---

## Das rekursive Prinzip als Dauerhafte Regel

Nach dem Refactoring gelten diese Invarianten für jeden zukünftigen Commit:

```
INVARIANTE 1: Kein File > 25K / ~800 Zeilen
              → Wenn es wächst: Extract (Rekursion anwenden)

INVARIANTE 2: Kein Pattern an >1 Stelle implementiert
              → Wenn dupliziert: Consolidate (tiefere Ebene)

INVARIANTE 3: Jede Ebene folgt Validate → Process → Format
              → Wenn abweichend: Normalize (Atom-Interface)

INVARIANTE 4: Dependencies nur nach unten
              → Wenn zirkulär: Extract shared interface (neue Ebene)

INVARIANTE 5: Jeder Service über Container
              → Wenn get_*() Funktion: Migrieren
```

Diese 5 Regeln sind selbst rekursiv — sie gelten auf System-, Modul-, Datei- und Funktionsebene gleichermaßen.
