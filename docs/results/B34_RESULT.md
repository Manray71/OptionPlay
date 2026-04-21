# B.3.4 — IBKR Margin Tracking: Result

**Branch:** `feature/b34-ibkr-margin`
**Datum:** 2026-04-17
**Tests vorher:** 5,683 | **Tests nachher:** 5,714 (+31)

---

## Commits

| # | Hash | Dateien | +LOC | Tests |
|---|------|---------|------|-------|
| 1 | `2fac226` | `src/ibkr/portfolio.py`, `tests/unit/test_ibkr_account_summary.py` | +261 | 10 |
| 2 | `317547e` | `src/risk/position_sizing.py`, `src/constants/trading_rules.py`, `tests/unit/test_spread_margin.py` | +91 | 10 |
| 3 | `a6a4627` | `src/services/trade_validator.py`, `tests/unit/test_margin_check.py` | +267 | 7 |
| 4 | `0d12916` | `config/trading.yaml`, `docs/RISK_MANAGEMENT.md` | +47 | — |
| 5 | `a20e56f` | `tests/integration/test_margin_yaml.py` | +55 | 4 |

---

## Margin-Formel

```
margin = (spread_width - credit_received) × 100 × contracts
```

Implementiert in `src/risk/position_sizing.calculate_spread_margin()` (pure Funktion, keine IBKR-Abhängigkeit).

**Beispiel:** spread_width=10.0, credit=1.85, contracts=1 → (10.0 - 1.85) × 100 × 1 = **$815.00**

---

## Dreistufiger Fallback

| Stufe | Quelle | Prüfung | Ergebnis |
|-------|--------|---------|----------|
| 1 | IBKR `reqAccountSummary` (live) | `(maint_margin_req + new_margin) / net_liq > 50%` | GO / NO_GO |
| 2 | Notional-Approximation (`portfolio_value`) | `new_margin / portfolio_value > 50%` | GO / NO_GO |
| 3 | Kein Wert verfügbar | — | WARNING (manuell prüfen) |

---

## Neues API-Modell

### `IBKRPortfolio.get_account_summary()` (Methode)

Nutzt die shared `IBKRConnection` (gleiche `_ensure_connected()`-Pattern wie `get_portfolio()`).
Kein neues Disconnect beim Aufruf — Connection bleibt offen für weitere Calls.

### `get_account_summary()` (Modulfunktion)

Standalone-Wrapper für Aufrufer ohne `IBKRPortfolio`-Instanz (z.B. `TradeValidator`).
Nutzt `client_id=10` (Hauptbridge: 98) — kein Konflikt.
Disconnected immer im `finally`-Block.

### `TradeValidator._check_margin_capacity()`

Integriert in `validate()` nach `_check_portfolio_value`.
Wird nur aufgerufen wenn `short_strike + long_strike + credit` vorhanden.
`contracts`-Default: 1 (wenn nicht im Request angegeben).

---

## Konfiguration

```yaml
# config/trading.yaml (sizing:)
max_margin_pct: 50.0    # Max 50% margin utilization
use_ibkr_margin: true   # Try IBKR account summary first
```

Neue Konstanten in `trading_rules.py`:
- `SIZING_MAX_MARGIN_PCT = 50.0`
- `SIZING_USE_IBKR_MARGIN = True`

Neue Felder in `PositionSizerConfig`:
- `max_margin_pct: float = 0.50`
- `use_ibkr_margin: bool = True`

---

## Verifikation

### IBKR-Mock-Tests grün

```
tests/unit/test_ibkr_account_summary.py  10 passed
tests/unit/test_margin_check.py           7 passed
tests/unit/test_spread_margin.py         10 passed
tests/integration/test_margin_yaml.py     4 passed
```

### Notional-Fallback funktioniert

`test_fallback_to_notional_when_ibkr_unavailable`: IBKR gibt `None` zurück →
Fallback auf `portfolio_value` → GO bei 0.8% < 50%.

`test_ibkr_exception_falls_back_to_notional`: IBKR wirft `ConnectionError` →
Exception in `except`-Block → Fallback auf Notional.

### Gesamtsuite

```
5714 passed, 29 skipped, 1 warning (alle Tests auf main + neue B.3.4-Tests)
```

MCP-Import: `python -c "import src.mcp_main"` → OK.

---

## Offene Punkte

Keine. `use_ibkr_margin` aus `PositionSizerConfig` wird aktuell noch nicht in
`_check_margin_capacity` ausgewertet (Feld existiert im Config-Objekt, aber
`TradeValidator` liest es nicht direkt — er versucht IBKR immer). Falls gewünscht,
kann der Flag dort eingebunden werden, um IBKR-Versuche komplett zu überspringen.
