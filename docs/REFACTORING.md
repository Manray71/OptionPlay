# OptionPlay Code Refactoring v3.1.0

## Übersicht

Dieses Refactoring adressiert die folgenden Punkte aus dem Code Review:

1. **scan_with_strategy() zu lang** (~100 Zeilen) → Aufgeteilt in Logik + Formatierung
2. **Markdown-Duplizierung** → Neuer MarkdownBuilder + Formatters
3. **Inkonsistente Formatierung** → Zentrale Formatter-Klassen

## Neue Dateien

```
src/
├── utils/
│   └── markdown_builder.py    # NEU: Fluent Markdown Builder
├── formatters/
│   ├── __init__.py            # NEU: Package
│   └── output_formatters.py   # NEU: Alle Output-Formatter

tests/
└── test_markdown_builder.py   # NEU: Comprehensive Tests
```

## Änderungen im Detail

### 1. MarkdownBuilder (`src/utils/markdown_builder.py`)

Fluent Builder für konsistente Markdown-Generierung:

```python
from src.utils.markdown_builder import MarkdownBuilder, md

# Fluent Interface
output = (
    MarkdownBuilder()
    .h1("Scan Results")
    .kv("VIX", 18.5, fmt=".2f")
    .kv("Strategy", "STANDARD")
    .blank()
    .table(["Symbol", "Score"], rows)
    .build()
)

# Oder mit Shortcuts
text = md.h1("Title") + md.kv("Key", "Value")
```

**Features:**
- Headings: `h1()`, `h2()`, `h3()`, `h4()`
- Key-Value: `kv()`, `kv_line()`, `kv_inline()`
- Listen: `bullet()`, `bullets()`, `numbered_list()`
- Tabellen: `table()` mit Alignment-Support
- Status: `status_ok()`, `status_warning()`, `status_error()`
- Bedingt: `if_true()`, `if_value()`
- Spezial: `hint()`, `note()`, `warning_box()`, `code_block()`

**Format-Strings:**
```python
.kv("Price", 175.5, fmt="$.2f")      # → **Price:** $175.50
.kv("Change", 2.5, fmt="+.1f%")      # → **Change:** +2.5%
.kv("Volume", 1500000, fmt=",.0f")   # → **Volume:** 1,500,000
```

### 2. Output Formatters (`src/formatters/output_formatters.py`)

Spezialisierte Formatter-Klassen:

| Formatter | Verwendung |
|-----------|------------|
| `ScanResultFormatter` | scan_with_strategy() |
| `LegacyScanResultFormatter` | scan_pullback_candidates() |
| `QuoteFormatter` | get_quote() |
| `OptionsChainFormatter` | get_options_chain() |
| `EarningsFormatter` | get_earnings() |
| `StrategyRecommendationFormatter` | get_strategy_recommendation() |
| `HealthCheckFormatter` | health_check() |
| `HistoricalDataFormatter` | get_historical_data() |
| `SymbolAnalysisFormatter` | analyze_symbol() |

**Verwendung:**
```python
from src.formatters import formatters

# Im MCP Server
result = await self._execute_scan(symbols, max_results)
return formatters.scan_result.format(result, recommendation, vix)
```

### 3. Migration zum refaktorierten MCP Server

**Vorher:** `scan_with_strategy()` hatte ~100 Zeilen mit vermischter Logik und Formatierung

**Nachher:** Getrennt in:
```python
async def _execute_scan(self, symbols, max_results, min_score, earnings_days):
    """Reine Scan-Logik (keine Formatierung)."""
    # ... 30 Zeilen
    return result

async def scan_with_strategy(self, symbols, max_results, use_vix_strategy):
    """API-Endpunkt mit Formatierung."""
    vix = await self.get_vix() if use_vix_strategy else None
    recommendation = get_strategy_for_vix(vix)
    result = await self._execute_scan(...)
    return formatters.scan_result.format(result, recommendation, vix)  # ← Delegiert
```

## Vorteile

### Separation of Concerns
- **Logik** in `_execute_scan()` → Testbar ohne Markdown
- **Formatierung** in Formatters → Wiederverwendbar, konsistent

### DRY (Don't Repeat Yourself)
- Alle `"\n".join(lines)` Patterns eliminiert
- Einheitliche Key-Value-Formatierung
- Tabellen-Code zentralisiert

### Testbarkeit
- MarkdownBuilder hat 60+ Unit Tests
- Formatter können isoliert getestet werden
- Scan-Logik testbar ohne Output-Parsing

### Erweiterbarkeit
- Neuer Output-Typ? → Neuer Formatter
- Neues Format (JSON, HTML)? → Builder austauschen
- Styling ändern? → Nur Formatter anpassen

## Migration

### Schrittweise Migration (empfohlen)

Du kannst die bestehenden Methoden schrittweise auf Formatter umstellen. Hier ein Beispiel für `get_quote()`:

```python
# Alt (in mcp_server.py)
lines = [f"# Quote: {symbol}", "", ...]
return "\n".join(lines)

# Neu
from src.formatters import formatters
return formatters.quote.format(symbol, quote)
```

### Imports in mcp_server.py anpassen
```python
# NEU hinzufügen
from .formatters import formatters, HealthCheckData
from .utils.markdown_builder import MarkdownBuilder
```

## Metriken

| Metrik | Vorher | Nachher |
|--------|--------|---------|
| scan_with_strategy() Zeilen | ~100 | ~15 |
| Markdown-Code dupliziert | 8x | 1x (Builder) |
| Testbare Formatierung | ❌ | ✅ |
| Neue Dateien | - | 4 |
| LOC hinzugefügt | - | ~1200 |

## Offene Punkte

1. **IBKR Bridge:** Verwendet noch inline-Formatierung → Auch auf Formatters migrieren
2. **Error Messages:** `format_error_response()` in error_handler.py → Könnte auch MarkdownBuilder nutzen
3. **Weitere Tests:** Output-Formatter Integration Tests hinzufügen

## Beispiel-Output

```python
# Mit dem neuen System
result = (
    MarkdownBuilder()
    .h1("Pullback Scan Results")
    .blank()
    .kv("VIX", 18.50, fmt=".2f")
    .kv("Strategy", "STANDARD")
    .blank()
    .h2("Top Candidates")
    .table(
        ["Symbol", "Score", "Price", "Reason"],
        [
            ["AAPL", "7.5", "$175.50", "RSI oversold"],
            ["MSFT", "6.8", "$380.20", "Support bounce"],
        ]
    )
    .blank()
    .h2("Next Steps")
    .numbered_list([
        "Check earnings: `get_earnings AAPL`",
        "Options chain: `get_options_chain AAPL`",
    ])
    .build()
)
```

Ausgabe:
```markdown
# Pullback Scan Results

**VIX:** 18.50
**Strategy:** STANDARD

## Top Candidates

| Symbol | Score | Price | Reason |
| --- | --- | --- | --- |
| AAPL | 7.5 | $175.50 | RSI oversold |
| MSFT | 6.8 | $380.20 | Support bounce |

## Next Steps

1. Check earnings: `get_earnings AAPL`
2. Options chain: `get_options_chain AAPL`
```

## Tests ausführen

```bash
cd ~/OptionPlay
pytest tests/test_markdown_builder.py -v
```
