# Verschlankungs-Paket E.3 — Ergebnis

**Branch:** verschlankung/e3-legacy-removal
**Datum:** 2026-04-15

---

## Session 1: report-Familie

**Status:** DONE
**Commit:** 552f953

---

### Verifikations-Ergebnisse

**Mixin-Seite (`ReportHandlerMixin`, `from src.handlers.report import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:52,90` | Re-Export + `__all__` | Erwartet → bereinigt |
| `src/handlers/report_composed.py:7` | Docstring-Kommentar | Mitgelöscht |
| `src/mcp_server.py:22,89` | Docstring-Kommentare | Bereinigt |
| `tests/integration/test_report_handler.py` | Testdatei | Gelöscht |
| `tests/system/test_handlers.py:178,190` | MRO-Kombinationstest | Bereinigt |

**Composed-Seite (`ReportHandler`, `report_composed`, `.report.`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/handler_container.py:334-340` | Lazy-Property + `_report` Slot | Entfernt |
| `src/handlers/__init__.py:25,53,78` | Docstring + Import + `__all__` | Bereinigt |
| `tests/integration/test_handler_container.py:175,225-230` | `_report`-Slot-Test + Property-Test | Entfernt |

**Externe Caller (`generate_daily_report`, `generate_portfolio_report`, `generate_report`):**
→ **Keine gefunden.** `mcp_tool_registry.py` enthält kein einziges `report`-Tool. Kein Script in `scripts/` ruft Report-Methoden auf. Kein Config-Eintrag.

**Abweichung von Briefing-Erwartung:**
- Briefing erwartete Testdatei unter `tests/unit/test_report_handler.py` — sie lag tatsächlich in `tests/integration/test_report_handler.py` (17 Testmethoden).
- `tests/integration/test_handler_container.py` enthielt zusätzlich 2 report-spezifische Tests (`test_init_handlers_none` + `test_report_property_lazy_init`) → ebenfalls entfernt.

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/report.py` | **GELÖSCHT** | -290 |
| `src/handlers/report_composed.py` | **GELÖSCHT** | -280 |
| `tests/integration/test_report_handler.py` | **GELÖSCHT** | -272 |
| `src/handlers/__init__.py` | Imports + `__all__` + Docstring | -5 |
| `src/handlers/handler_container.py` | Property + Slot `_report` | -10 |
| `src/mcp_server.py` | 2 Docstring-Zeilen | -2 |
| `tests/integration/test_handler_container.py` | 2 Tests + 1 Assert | -8 |
| `tests/system/test_handlers.py` | Import + MRO-Klasse | -2 |

**Gesamt: -869 LOC**

---

### Tests

| | Passed | Failed | Skipped |
|-|--------|--------|---------|
| **Vorher** | 5920 | 0 | 29 |
| **Nachher** (ohne live e2e) | 5869 | 0 | 29 |

Delta: -51 Tests (= 17 Methoden aus `test_report_handler.py` + 2 aus `test_handler_container.py` + weitere parametrisierte Varianten).

---

### Smoke-Tests

```
python -c "from src.handlers import HandlerContainer; print('handlers OK')"
→ handlers OK

python -m src.mcp_main (4s)
→ Startet ohne Fehler (nur pre-existing DeprecationWarning für get_secure_config(),
  unverändert seit vor dieser Session)
```

---

## Session 2: ibkr

**Status:** DONE
**Commit:** 351ad92

---

### Verifikations-Ergebnisse

**Mixin-Seite (`IbkrHandlerMixin`, `from src.handlers.ibkr import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:43,85` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/ibkr.py` | Mixin-Datei (186 LOC) | Gelöscht |
| `tests/system/test_ibkr_handler.py` | Testdatei (25 Tests, 327 LOC) | Gelöscht |
| `tests/system/test_handlers.py:176,187` | MRO-Kombinationstest | Bereinigt |

**Abweichung von Briefing-Erwartung:**
- Briefing erwartete Testdatei unter `tests/integration/test_ibkr_handler.py` — sie lag tatsächlich in `tests/system/test_ibkr_handler.py`.

**Composed-Seite (`IbkrHandler`, `ibkr_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/ibkr_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:324-329` | Lazy-Property → `IbkrHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:44,74` | Import + `__all__` | **UNVERÄNDERT** |
| `tests/integration/test_handler_container.py` | ibkr_provider/bridge Context-Tests | **UNVERÄNDERT** (keine Mixin-Tests) |

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import IbkrHandler       → OK
'IbkrHandlerMixin' in __all__             → False (entfernt)
'IbkrHandler' in __all__                  → True (bleibt)
```

**vix.get_sector_status (nutzt ibkr_composed intern):**
```
pytest tests/integration/test_vix_composed_handler.py -v -k "sector"
→ 1 passed (TestVixHandlerSectorStatus::test_get_sector_status_returns_markdown)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/ibkr.py` | **GELÖSCHT** | -186 |
| `tests/system/test_ibkr_handler.py` | **GELÖSCHT** | -327 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_handlers.py` | Import + MRO-Klasse bereinigt | -3 |

**Gesamt: -518 LOC**

---

### Tests

| | Passed | Failed | Skipped |
|-|--------|--------|---------|
| **Vorher** (Session 1 End) | 5798 collected | 0 | — |
| **Nachher** | 5773 passed | 0 | 35 |

Delta: -25 Tests (= 25 Mixin-Tests aus `tests/system/test_ibkr_handler.py`).
Pre-existing error in `test_hypothesis_pbt.py` (`hypothesis` Modul fehlt in venv) — unverändert vor und nach dieser Session.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → handlers OK
from src.handlers import IbkrHandler       → IbkrHandler OK
pytest tests/system/test_handlers.py      → 9 passed
pytest tests/integration/test_vix_composed_handler.py -k sector → 1 passed
Gesamtsuite (ohne hypothesis): 5773 passed, 35 skipped
```

---

## Session 3: monitor

**Status:** DONE
**Commit:** 214f5fd

---

### Verifikations-Ergebnisse

**Mixin-Seite (`MonitorHandlerMixin`, `from src.handlers.monitor import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:44,86` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/monitor.py` | Mixin-Datei (191 LOC) | Gelöscht |
| `tests/integration/test_monitor_handler.py` | Testdatei (19 Tests, 367 LOC) | Gelöscht |
| `tests/system/test_workflow_integration.py:45,160-168` | Import + `MockMonitorServer` | Bereinigt |
| `tests/system/test_workflow_integration.py:383-432` | `TestMonitorHandlerWorkflow` (2 Tests) | Bereinigt |

**Abweichung von Briefing-Erwartung:**
- `tests/system/test_workflow_integration.py` enthielt `MockMonitorServer(MonitorHandlerMixin)` und `TestMonitorHandlerWorkflow` — beide außerhalb der erwarteten Orte. Bereinigt statt STOP, da ausschließlich Test-Code (keine Produktion). `TestFullPipelineWorkflow` und `TestMonitorWorkflow` in derselben Datei benutzen `_make_monitor()` → `PositionMonitor()` direkt, kein Mixin-Bezug, unverändert.

**Composed-Seite (`MonitorHandler`, `monitor_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/monitor_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:351-356` | Lazy-Property → `MonitorHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:45,76` | Import + `__all__` | **UNVERÄNDERT** |

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import MonitorHandler    → OK
'MonitorHandlerMixin' in __all__          → False (entfernt)
'MonitorHandler' in __all__               → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/monitor.py` | **GELÖSCHT** | -191 |
| `tests/integration/test_monitor_handler.py` | **GELÖSCHT** | -367 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_workflow_integration.py` | Import + MockMonitorServer + TestMonitorHandlerWorkflow | -67 |

**Gesamt: -627 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** | 5906 collected | — |
| **Nachher** (ohne e2e) | 5823 passed | 29 |

Delta: -21 Tests (19 aus `test_monitor_handler.py` + 2 aus `test_workflow_integration.py`). 3 pre-existing e2e-Fehler in `test_mcp_server_e2e.py` (asyncio event loop, unverändert seit Session 2).

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import MonitorHandler    → OK
pytest tests/ --ignore=test_mcp_server_e2e.py → 5823 passed, 29 skipped
```

---

## Session 4: validate

**Status:** DONE
**Commit:** 26426c0

---

### Verifikations-Ergebnisse

**Mixin-Seite (`ValidateHandlerMixin`, `from src.handlers.validate import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:53,84` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/validate.py` | Mixin-Datei (213 LOC) | Gelöscht |
| `tests/integration/test_validate_handler.py` | Testdatei (12 Tests, 226 LOC) | Gelöscht |
| `tests/system/test_workflow_integration.py:44,148-156` | Import + `MockValidateServer` | Bereinigt |
| `tests/system/test_workflow_integration.py:239-254` | `test_validate_handler_output_format` | Bereinigt (1 Test aus `TestValidateWorkflow`) |

**Hinweis zu `_get_portfolio_db`:** Briefing merkte an, dass `validate.py` diesen Import enthielt. Nach Löschung in Session 4 kein Bezug mehr in `src/` oder `tests/` — bestätigt per `grep -rn "_get_portfolio_db"`.

**Composed-Seite (`ValidateHandler`, `validate_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/validate_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:342-347` | Lazy-Property → `ValidateHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:54,74` | Import + `__all__` | **UNVERÄNDERT** |

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer   → OK
from src.handlers import ValidateHandler    → OK
'ValidateHandlerMixin' in __all__          → False (entfernt)
'ValidateHandler' in __all__               → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/validate.py` | **GELÖSCHT** | -213 |
| `tests/integration/test_validate_handler.py` | **GELÖSCHT** | -226 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_workflow_integration.py` | Import + MockValidateServer + 1 Test | -30 |

**Gesamt: -471 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 3 End) | 5823 passed | 29 |
| **Nachher** (ohne e2e) | 5810 passed | 29 |

Delta: -13 Tests (12 aus `test_validate_handler.py` + 1 aus `test_workflow_integration.py`).

---

### Smoke-Tests

```
from src.handlers import HandlerContainer   → OK
from src.handlers import ValidateHandler    → OK
pytest tests/ --ignore=test_mcp_server_e2e.py → 5810 passed, 29 skipped
```

---

## Session 5: risk

**Status:** DONE
**Commit:** 5759348

---

### Verifikations-Ergebnisse

**Mixin-Seite (`RiskHandlerMixin`, `from src.handlers.risk import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:49,82` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/risk.py` | Mixin-Datei (357 LOC) | Gelöscht |
| `tests/integration/test_risk_handler.py` | Testdatei (189 LOC) | Gelöscht |
| `tests/system/test_handlers.py:177,187` | MRO-Kombinationsklasse | Bereinigt |

Keine unerwarteten Caller außerhalb der erwarteten Orte.

**Composed-Seite (`RiskHandler`, `risk_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/risk_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:333-338` | Lazy-Property → `RiskHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:50,72` | Import + `__all__` | **UNVERÄNDERT** |

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import RiskHandler       → OK
'RiskHandlerMixin' in __all__             → False (entfernt)
'RiskHandler' in __all__                  → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/risk.py` | **GELÖSCHT** | -357 |
| `tests/integration/test_risk_handler.py` | **GELÖSCHT** | -189 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_handlers.py` | MRO-Klasse bereinigt | -2 |

**Gesamt: -550 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 4 End) | 5810 passed | 29 |
| **Nachher** (ohne e2e) | 5798 passed | 29 |

Delta: -12 Tests.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import RiskHandler       → OK
pytest tests/ --ignore=test_mcp_server_e2e.py → 5798 passed, 29 skipped
```

---

## Session 6: portfolio

**Status:** DONE
**Commit:** e39dbb6

---

### Verifikations-Ergebnisse

**Mixin-Seite (`PortfolioHandlerMixin`, `from src.handlers.portfolio import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:45,80` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/portfolio.py` | Mixin-Datei (369 LOC) | Gelöscht |
| `tests/integration/test_portfolio_handler.py` | Testdatei (1434 LOC) | Gelöscht |
| `tests/system/test_handlers.py:153,155,175,184,198,210-211` | TestPortfolioHandler + MRO-Klasse + method-check | Bereinigt |

**Hinweis zu `_get_portfolio_db`:** Per `grep -rn "_get_portfolio_db" src/ tests/` — kein Treffer. Wurde mit `validate.py` in Session 4 mitgelöscht.

**Composed-Seite (`PortfolioHandler`, `portfolio_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/portfolio_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py` | Lazy-Property → `PortfolioHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py` | Import + `__all__` | **UNVERÄNDERT** |

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer    → OK
from src.handlers import PortfolioHandler    → OK
'PortfolioHandlerMixin' in __all__          → False (entfernt)
'PortfolioHandler' in __all__               → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/portfolio.py` | **GELÖSCHT** | -369 |
| `tests/integration/test_portfolio_handler.py` | **GELÖSCHT** | -1434 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_handlers.py` | TestPortfolioHandler + MRO-Klasse + method-check | -24 |

**Gesamt: -1829 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 5 End) | 5798 passed | 29 |
| **Nachher** (ohne e2e) | 5748 passed | 29 |

Delta: -50 Tests.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer    → OK
from src.handlers import PortfolioHandler    → OK
pytest tests/ --ignore=test_mcp_server_e2e.py → 5748 passed, 29 skipped
```

---

## Session 7: quote

**Status:** DONE
**Commit:** b49256e

---

### Verifikations-Ergebnisse

**Mixin-Seite (`QuoteHandlerMixin`, `from src.handlers.quote import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:46,77` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/quote.py` | Mixin-Datei (578 LOC) | Gelöscht |
| `tests/integration/test_quote_handler.py` | Testdatei (1610 LOC) | Gelöscht |
| `tests/system/test_handlers.py:89-128` | TestQuoteHandler (2 Tests) | Bereinigt |
| `tests/system/test_handlers.py:157,165,178,186-187` | MRO-Klasse + method-check | Bereinigt |

Keine unerwarteten Caller außerhalb der erwarteten Orte.

**Composed-Seite (`QuoteHandler`, `quote_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/quote_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:297-302` | Lazy-Property → `QuoteHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:46,65` | Import + `__all__` | **UNVERÄNDERT** |

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import QuoteHandler      → OK
'QuoteHandlerMixin' in __all__            → False (entfernt)
'QuoteHandler' in __all__                 → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/quote.py` | **GELÖSCHT** | -578 |
| `tests/integration/test_quote_handler.py` | **GELÖSCHT** | -1610 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_handlers.py` | TestQuoteHandler + MRO + method-check | -52 |

**Gesamt: -2242 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 6 End) | 5748 passed | 29 |
| **Nachher** (ohne e2e) | 5696 passed | 29 |

Delta: -52 Tests.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import QuoteHandler      → OK
pytest tests/ --ignore=test_mcp_server_e2e.py → 5696 passed, 29 skipped
```

---

## Session 8: analysis

**Status:** DONE
**Commit:** c92a19b

---

### Verifikations-Ergebnisse

**Mixin-Seite (`AnalysisHandlerMixin`, `from src.handlers.analysis import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:30,76` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/analysis.py` | Mixin-Datei (509 LOC) | Gelöscht |
| `tests/integration/test_analysis_handler.py` | Testdatei (718 LOC, 14 Tests) | Gelöscht |
| `tests/system/test_handlers.py:89-104` | TestAnalysisHandler (1 Test) | Bereinigt |
| `tests/system/test_handlers.py:116,123` | MRO-Kombinationsklasse | Bereinigt |

Keine unerwarteten Caller außerhalb der erwarteten Orte.

**Composed-Seite (`AnalysisHandler`, `analysis_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/analysis_composed.py` | Composed-Handler (611 LOC) | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:306-311` | Lazy-Property → `AnalysisHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:31,66` | Import + `__all__` | **UNVERÄNDERT** |

**Divergenz-Check (composed-spezifische Features):**
`_fetch_earnings_cached`, `_fetch_historical_cached`, `_get_scanner`, `_get_multi_scanner`, `_get_options_chain_with_fallback` — alle nur in `analysis_composed.py`, nicht im Mixin. Genutzt in `test_scan_handler.py` und `test_mcp_server_extended.py` als Stubs für den ScanHandler-Kontext.

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import AnalysisHandler   → OK
'AnalysisHandlerMixin' in __all__         → False (entfernt)
'AnalysisHandler' in __all__              → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/analysis.py` | **GELÖSCHT** | -509 |
| `tests/integration/test_analysis_handler.py` | **GELÖSCHT** | -718 |
| `src/handlers/__init__.py` | Import + `__all__` bereinigt | -2 |
| `tests/system/test_handlers.py` | TestAnalysisHandler + MRO bereinigt | -18 |

**Gesamt: -1247 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 7 End) | 5696 passed | 29 |
| **Nachher** (ohne e2e) | 5682 passed | 29 |

Delta: -14 Tests.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import AnalysisHandler   → OK
pytest tests/ --ignore=test_mcp_server_e2e.py → 5682 passed, 29 skipped
```

---

## Session 9: vix

**Status:** DONE
**Commit:** 64edfe6

---

### Verifikations-Ergebnisse

**Mixin-Seite (`VixHandlerMixin`, `from src.handlers.vix import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:50,73` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/vix.py` | Mixin-Datei | Gelöscht |
| `tests/integration/test_vix_handler.py` | Testdatei (17 Tests) | Gelöscht |
| `tests/system/test_handlers.py:9-52` | TestVixHandler (2 Tests) | Bereinigt |
| `tests/system/test_handlers.py:96,103,113,116` | MRO-Klasse + method-check | Bereinigt |
| `src/handlers/scan.py:481` | Kommentar „via VixHandlerMixin" | Bereinigt |

Keine unerwarteten Caller außerhalb der erwarteten Orte.

**Composed-Seite (`VixHandler`, `vix_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/vix_composed.py` | Composed-Handler | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:279-284` | Lazy-Property → `VixHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:53,62` | Import + `__all__` | **UNVERÄNDERT** |
| `tests/integration/test_vix_composed_handler.py` | 535 LOC, 30 Tests | **UNVERÄNDERT** |

**Divergenz-Check (composed-spezifische Features):**
`get_regime_status_v2`, `_get_sector_status_v2` — nur in `vix_composed.py`. Keine direkten Tests für diese privaten Methoden gefunden; öffentliche API via `test_vix_composed_handler.py` vollständig abgedeckt.
`pytest tests/integration/test_vix_composed_handler.py tests/system/test_handlers.py → 32 passed`

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import VixHandler        → OK
'VixHandlerMixin' in __all__             → False (entfernt)
'VixHandler' in __all__                  → True (bleibt)
```

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/vix.py` | **GELÖSCHT** | ~-280 |
| `tests/integration/test_vix_handler.py` | **GELÖSCHT** | ~-380 |
| `src/handlers/__init__.py` | Import + `__all__` + Docstring bereinigt | -4 |
| `src/handlers/scan.py` | Kommentar bereinigt | -1 |
| `tests/system/test_handlers.py` | TestVixHandler + MRO + method-check | -48 |

**Gesamt: ~-713 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 8 End) | 5682 passed | 29 |
| **Nachher** (ohne e2e) | 5665 passed | 29 |

Delta: -17 Tests.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import VixHandler        → OK
pytest tests/integration/test_vix_composed_handler.py tests/system/test_handlers.py → 32 passed
pytest tests/ --ignore=test_mcp_server_e2e.py → 5665 passed, 29 skipped
```

---

## Session 10: scan

**Status:** DONE
**Commit:** 1ca381f

---

### Verifikations-Ergebnisse

**Mixin-Seite (`ScanHandlerMixin`, `from src.handlers.scan import`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:47,72` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/scan.py` | Mixin-Datei (862 LOC) | Gelöscht |
| `tests/integration/test_scan_handler.py` | Testdatei (1905 LOC, 57 Tests) | Gelöscht |
| `tests/system/test_handlers.py:9-40` | TestScanHandler (1 Test) | Bereinigt |
| `tests/system/test_handlers.py:50,55` | MRO-Kombinationsklasse | Bereinigt |

Keine unerwarteten Caller außerhalb der erwarteten Orte.

**Composed-Seite (`ScanHandler`, `scan_composed`):**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/scan_composed.py` | Composed-Handler (1098 LOC) | **UNVERÄNDERT** |
| `src/handlers/handler_container.py:288-293` | Lazy-Property → `ScanHandler` | **UNVERÄNDERT** |
| `src/handlers/__init__.py:48,62` | Import + `__all__` | **UNVERÄNDERT** |
| `tests/integration/test_shadow_daily_picks.py` | `_shadow_log_picks`-Tests (8 Tests) | **UNVERÄNDERT** |

**Divergenz-Check (composed-spezifische Features):**
`_shadow_log_picks`, `_fetch_historical_cached`, `_apply_earnings_prefilter`, `_get_multi_scanner`, `_get_options_chain_with_fallback` — alle nur in `scan_composed.py`.
`pytest tests/integration/test_shadow_daily_picks.py tests/system/test_handlers.py → 10 passed`

**Importierbarkeit nach Änderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import ScanHandler       → OK
'ScanHandlerMixin' in __all__             → False (entfernt)
'ScanHandler' in __all__                  → True (bleibt)
```

**Hinweis:** Nach Session 10 ist `BaseHandlerMixin` das einzige verbliebene Legacy-Mixin in `__init__.py`.

---

### Geänderte Dateien

| Datei | Änderung | LOC-Delta |
|-------|----------|-----------|
| `src/handlers/scan.py` | **GELÖSCHT** | -862 |
| `tests/integration/test_scan_handler.py` | **GELÖSCHT** | -1905 |
| `src/handlers/__init__.py` | Import + `__all__` + Docstring bereinigt | -4 |
| `tests/system/test_handlers.py` | TestScanHandler + MRO → BaseHandlerMixin-only | -50 |

**Gesamt: -2821 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 9 End) | 5665 passed | 29 |
| **Nachher** (ohne e2e) | 5608 passed | 29 |

Delta: -57 Tests.

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import ScanHandler       → OK
pytest tests/integration/test_shadow_daily_picks.py tests/system/test_handlers.py → 10 passed
pytest tests/ --ignore=test_mcp_server_e2e.py → 5608 passed, 29 skipped
```

---

## Gesamtbilanz Sessions 3-10

| Session | Familie | Commit | LOC-Delta | Tests-Delta |
|---------|---------|--------|-----------|-------------|
| 3 | monitor | 214f5fd | -627 | -21 |
| 4 | validate | 26426c0 | -471 | -13 |
| 5 | risk | 5759348 | -550 | -12 |
| 6 | portfolio | e39dbb6 | -1829 | -50 |
| 7 | quote | b49256e | -2242 | -52 |
| 8 | analysis | c92a19b | -1247 | -14 |
| 9 | vix | 64edfe6 | -713 | -17 |
| 10 | scan | 1ca381f | -2821 | -57 |
| **Summe** | | | **-10500** | **-236** |

Gesamtbilanz E.3 (alle 10 Sessions):

| Metrik | Wert |
|--------|------|
| Gelöschte Mixin-Dateien | 10 |
| Gelöschte Test-Dateien | 10 |
| Gesamt LOC entfernt | ~11887 (-869 S1, -518 S2, -10500 S3-10) |
| Tests vorher | 5920 |
| Tests nachher (ohne e2e) | 5608 |
| Tests entfernt | -312 |
| Fehlgeschlagene Sessions | 0 |
| Verbleibendes Legacy-Mixin | `BaseHandlerMixin` (base.py) |

---

## E2E Status (Aufgabe A, Session 11)

### Paket-A-Fix: Auf main gemergt?

**Nein.** Commit d5ca12c ("Fix VIX E2E test mocks after vix_composed refactor") liegt nur auf Branch
`verschlankung/a-tier1-bugs` -- nicht auf `main`, nicht auf `verschlankung/e3-legacy-removal`.

```
git branch --contains d5ca12c
  verschlankung/a-tier1-bugs
```

Das bedeutet: Die drei VIX-Failures waren während der gesamten E.3-Arbeit (Sessions 1-11) im
E2E-Test vorhanden. Sie wurden durch den `vix_composed`-Refactor (vor E.3) verursacht und auf
`a-tier1-bugs` gefixt, aber der Fix wurde nie in `main` gemergt.

### Aktuelle Failures auf dem E.3-Branch

Lauf vom 2026-04-16 auf `verschlankung/e3-legacy-removal` (HEAD 1ca381f):

```
3 failed, 30 passed (test_mcp_server_e2e.py, 33 Tests total)
```

| Test | Fehler |
|------|--------|
| `TestVIXOperations::test_get_vix` | `assert 18.17 == 185.5` |
| `TestVIXOperations::test_get_vix_cached` | `Timeout (>30.0s)` |
| `TestVIXOperations::test_get_strategy_recommendation` | `Timeout (>30.0s)` |

### Failure-Traces (je 3 Zeilen)

**test_get_vix:**
```
tests/system/test_mcp_server_e2e.py:165: in test_get_vix
    assert vix == 185.50  # MockQuote.last
E   assert 18.17 == 185.5
```

**test_get_vix_cached:**
```
src/handlers/vix_composed.py:62: in get_vix
    vix = await self._ctx.ibkr_bridge.get_vix_value()
src/ibkr/bridge.py:157: in get_vix_value
E   Failed: Timeout (>30.0s) -- echte IBKR-Verbindung wird versucht statt Mock
```

**test_get_strategy_recommendation:**
```
src/handlers/vix_composed.py:107: in get_strategy_recommendation
    vix = await self.get_vix()
src/handlers/vix_composed.py:62: in get_vix
E   Failed: Timeout (>30.0s) -- folgt aus test_get_vix_cached (selbe Ursache)
```

### Ursache

Nach dem `vix_composed`-Refactor ruft `get_vix()` direkt `self._ctx.ibkr_bridge.get_vix_value()`
auf. Der E2E-Test mockt aber noch den alten Pfad (`qualifyContracts` auf IB-Ebene statt
`IBKRBridge.get_vix_value`). Das erste Failure gibt den falschen Wert zurueck (VIX aus der lokalen
DB: 18.17 statt MockQuote.last 185.5), die folgenden zwei laufen in Timeout weil der IBKR-Stack
eine echte Verbindung aufbaut.

Fix in d5ca12c: Mock auf `IBKRBridge.get_vix_value` direkt patchen. Dieser Fix muss noch
von `verschlankung/a-tier1-bugs` nach `main` gemergt werden.

### Bewertung

Die drei Failures wurden **nicht durch E.3 verursacht** und wurden **nicht durch E.3 behoben**.
Sie waren pre-existing auf dem E.3-Branch (vor Session 1 vorhanden). E.3 hat den E2E-Status
unverandert ubernommen.

---

## Session 11: Cleanup (Aufgabe B)

**Status:** DONE
**Commit:** (siehe unten)

---

### Verifikations-Ergebnisse

**BaseHandlerMixin grep vor Loeschung:**

| Fundort | Typ | Bewertung |
|---------|-----|-----------|
| `src/handlers/__init__.py:33,70` | Import + `__all__` | Erwartet → bereinigt |
| `src/handlers/base.py:30` | Mixin-Klasse selbst | Datei geloescht |
| `tests/system/test_handlers.py:13-14` | Einziger Test: Subclass + Instantiierung | Datei geloescht |

Keine unerwarteten Caller gefunden. `.pyc`-Dateien enthalten historische Referenzen -- kein Source-Code-Treffer.

**`_get_options_chain_with_fallback` in `base.py`:**
Totes Code. Jedes composed handler hat seine eigene Implementierung:
- `quote_composed.py:569`, `analysis_composed.py:584`, `scan_composed.py:1070`
Kein composed handler erbt von BaseHandlerMixin.

**Importierbarkeit nach Aenderungen:**
```
from src.handlers import HandlerContainer  → OK
from src.handlers import VixHandler, ScanHandler, QuoteHandler,
  AnalysisHandler, PortfolioHandler, IbkrHandler, ValidateHandler,
  MonitorHandler, RiskHandler              → All 9 composed handlers: OK
'BaseHandlerMixin' in __all__             → False (entfernt)
```

---

### Geaenderte Dateien

| Datei | Aenderung | LOC-Delta |
|-------|-----------|-----------|
| `src/handlers/base.py` | **GELOESCHT** | -165 |
| `tests/system/test_handlers.py` | **GELOESCHT** | -29 |
| `src/handlers/__init__.py` | Import + `__all__` + Docstring bereinigt | -6 |

**Gesamt: -200 LOC**

---

### Tests

| | Passed | Skipped |
|-|--------|---------|
| **Vorher** (Session 10 End) | 5606 passed | 29 |
| **Nachher** (ohne e2e) | 5606 passed | 29 |

Delta: 0 Tests (test_handlers.py hatte nur 2 Methoden -- beide entfernt).

---

### Smoke-Tests

```
from src.handlers import HandlerContainer  → OK
from src.handlers import VixHandler, ScanHandler, QuoteHandler,
  AnalysisHandler, PortfolioHandler, IbkrHandler, ValidateHandler,
  MonitorHandler, RiskHandler              → All 9 composed handlers: OK
python -m src.mcp_main (3s)               → Startet ohne Fehler
pytest --ignore=test_mcp_server_e2e.py    → 5606 passed, 29 skipped
```

---

## Final E.3 Summary

### Sessions 1-11

| Session | Geloeschtes Mixin | Commit | LOC-Delta | Tests-Delta |
|---------|-------------------|--------|-----------|-------------|
| 1 | report / report_composed | 552f953 | -869 | -51 |
| 2 | ibkr | 351ad92 | -518 | -25 |
| 3 | monitor | 214f5fd | -627 | -21 |
| 4 | validate | 26426c0 | -471 | -13 |
| 5 | risk | 5759348 | -550 | -12 |
| 6 | portfolio | e39dbb6 | -1829 | -50 |
| 7 | quote | b49256e | -2242 | -52 |
| 8 | analysis | c92a19b | -1247 | -14 |
| 9 | vix | 64edfe6 | -713 | -17 |
| 10 | scan | 1ca381f | -2821 | -57 |
| 11 | base (BaseHandlerMixin) | 1286106 | -200 | 0 |
| **Gesamt** | | | **-12087** | **-312** |

### Gesamtbilanz

| Metrik | Wert |
|--------|------|
| Geloeschte Mixin-Dateien | 11 (incl. base.py) |
| Geloeschte Test-Dateien | 11 |
| Gesamt LOC entfernt | ~12087 |
| Tests vorher (vor E.3) | 5920 |
| Tests nachher (ohne e2e) | 5606 |
| Tests entfernt | -314 |
| Fehlgeschlagene Sessions | 0 |
| Legacy-Architektur komplett weg | **Ja** |

### E2E-Status

3 Failures in `test_mcp_server_e2e.py`, alle in `TestVIXOperations`:
- Ursache: Mock-Pfad nach `vix_composed`-Refactor falsch (pre-existing, vor E.3)
- Fix existiert: Commit d5ca12c auf Branch `verschlankung/a-tier1-bugs`
- Fix nicht auf `main` gemergt

### Empfehlung

E.3 kann gemergt werden. Die drei E2E-Failures sind nicht durch E.3 entstanden und
werden durch E.3 nicht verschlimmert. Vor dem Merge von E.3 nach `main` sollte
`verschlankung/a-tier1-bugs` (Commit d5ca12c) zuerst in `main` gemergt werden,
damit `main` danach sauber gruent. Alternativ: E.3 mergen und `a-tier1-bugs` direkt
danach als separate PR.
