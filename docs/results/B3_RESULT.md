# B.3 Risk Management — Implementation Verification

**Branch:** `verschlankung/b3-risk-management`
**Datum:** 2026-04-16

---

## 1. Baseline

Vor dem ersten Commit:

```
5492 passed, 29 skipped, 8 warnings in 248.40s (0:04:08)
```

---

## 2. Commits im Detail

### Commit 1 — Risk per Trade 2.0% → 2.5%

**Hash:** `64c016e`
**Dateien:** 4 geändert, 13 Insertions, 13 Deletions (reine Wertänderungen)

| Datei | Änderung |
|-------|----------|
| `config/trading.yaml` | `max_risk_per_trade_pct`, `low_vol/normal.risk_per_trade_pct`: 2.0 → 2.5 |
| `tests/unit/test_trading_rules.py` | 3 Assertions: 2.0 → 2.5 |
| `tests/integration/test_portfolio_constraints.py` | 1 Assertion: 2.0 → 2.5 (LOW_VOL) |
| `tests/integration/test_trade_validator.py` | 2 Assertions + `max_risk_usd` Folgewert korrigiert |

**Tests nach Commit 1:** 5492 passed (gleich — nur Wertanpassungen, keine neuen Tests)

### Commit 2 — B.3.1: portfolio_value Pflicht

**Hash:** `686cff4`
**Dateien:** 2 geändert, 102 Insertions

| Datei | Änderung |
|-------|----------|
| `src/services/trade_validator.py` | `_check_portfolio_value()` Methode (38 LOC) + Aufruf in `validate()` |
| `tests/integration/test_trade_validator.py` | `TestPortfolioValueCheck` Klasse mit 5 Tests |

**Neue Tests:** +5 (auf 5497 gesamt)

### Commit 3 — B.3.2-light: max_portfolio_allocation aktiv

**Hash:** `47c5c87`
**Dateien:** 3 geändert, 126 Insertions, 2 Deletions

| Datei | Änderung |
|-------|----------|
| `src/constants/trading_rules.py` | `SIZING_MAX_PORTFOLIO_ALLOCATION`, `SIZING_MAX_BUYING_POWER_PCT` |
| `src/risk/position_sizing.py` | `max_portfolio_allocation` Feld in Config + `current_notional`/`spread_width` Parameter + Notional-Logik in `calculate_position_size()` |
| `tests/unit/test_position_sizing.py` | `TestMaxPortfolioAllocation` mit 4 Tests |

**Neue Tests:** +4 (auf 5501 gesamt)

### Commit 4 — B.3.3: PositionSizerConfig.from_yaml()

**Hash:** `9bdf656`
**Dateien:** 3 geändert, 67 Insertions, 2 Deletions

| Datei | Änderung |
|-------|----------|
| `src/risk/position_sizing.py` | `from_yaml()` classmethod (24 LOC) + `PositionSizer.__init__` nutzt `from_yaml()` als Default |
| `src/handlers/risk_composed.py` | `PositionSizerConfig(kelly_mode=...)` → `from_yaml()` + explizite kelly_mode-Zuweisung |
| `tests/unit/test_position_sizing.py` | `TestPositionSizerConfigFromYaml` mit 4 Tests |

**Neue Tests:** +4 (auf 5505 gesamt)

### Commit 5 — Dokumentation

**Hash:** `c2cae98`
**Dateien:** 2 neue Docs

| Datei | Inhalt |
|-------|--------|
| `docs/B3_AUDIT.md` | Befunde, Implementation Status, Restschuld |
| `docs/RISK_MANAGEMENT.md` | Aktive Risk-Management-Logik (Referenz) |

---

## 3. Verifikation Commit 1: Welche Tests mussten angepasst werden?

Ja, 6 Tests hatten den Wert 2.0 hardkodiert und mussten auf 2.5 gehoben werden:

1. `test_trading_rules.py::TestPlaybookPositionSizing::test_max_risk_per_trade` — `SIZING_MAX_RISK_PER_TRADE_PCT == 2.0`
2. `test_trading_rules.py::TestTradingRulesConstants::...` — `tr.MAX_RISK_PCT == 2.0`
3. `test_trading_rules.py::TestVIXRegimeRiskParameters::test_low_vol_risk`
4. `test_trading_rules.py::TestVIXRegimeRiskParameters::test_normal_risk`
5. `test_portfolio_constraints.py::TestGetPositionLimits::test_get_position_limits_low_vix` — `risk_per_trade_pct == 2.0`
6. `test_trade_validator.py::TestPositionSizing::test_sizing_calculation` — `risk_pct == 2.0` + `max_risk_usd == 1600.0`
7. `test_trade_validator.py::TestPositionSizingExtended::test_sizing_no_vix_uses_default`

Zusätzlich: `max_risk_usd` in test_sizing_calculation von 1600.0 → 2000.0 (80k × 2.5% = 2000).

---

## 4. Verifikation Commit 3: Greift max_portfolio_allocation?

Ja. Beweistest: `TestMaxPortfolioAllocation::test_position_size_zero_when_allocation_full`

```python
config = PositionSizerConfig(max_portfolio_allocation=0.50)
sizer = PositionSizer(account_size=100_000, config=config)
result = sizer.calculate_position_size(
    max_loss_per_contract=500,
    ...,
    current_notional=50_000.0,  # 100% der erlaubten Allokation bereits belegt
    spread_width=10.0,
)
assert result.contracts == 0
assert result.limiting_factor == "max_portfolio_allocation"
```

Und `test_position_size_capped_by_max_portfolio_allocation`:
- Account 100k, Allokation 50% = 50k Notional
- current_notional 48k → 2k Kapazität
- spread_width=10 → 1000 Notional/Contract → max 2 by notional
- Kelly würde 4 erlauben → Notional ist bindender Faktor
- `result.contracts <= 2`, `result.limiting_factor == "max_portfolio_allocation"` ✅

---

## 5. Verifikation Commit 4: Greift PositionSizerConfig.from_yaml() in risk_composed.py?

Ja. Die Kette ist:
1. `risk_composed.py` ruft `PositionSizerConfig.from_yaml()` auf
2. `from_yaml()` liest `SIZING_MAX_RISK_PER_TRADE_PCT` aus `trading_rules.py`
3. `trading_rules.py` liest `_sizing_cfg.get("max_risk_per_trade_pct", 2.0)` aus `trading.yaml`
4. `trading.yaml` hat `max_risk_per_trade_pct: 2.5`

Beweistest: `TestPositionSizerConfigFromYaml::test_position_sizer_uses_yaml_value_when_constructed_via_from_yaml`

```python
sizer = PositionSizer(account_size=100_000)  # kein config-Argument
expected_fraction = SIZING_MAX_RISK_PER_TRADE_PCT / 100.0  # = 0.025
assert sizer.config.max_risk_per_trade == pytest.approx(expected_fraction)  # ✅
```

Vor dem Fix: `sizer.config.max_risk_per_trade == 0.02` (Dataclass-Default, YAML ignoriert).
Nach dem Fix: `0.025` (aus YAML).

---

## 6. Tests nach Abschluss

```
5505 passed, 29 skipped, 8 warnings
```

Netto neue Tests: **+13** (5 + 4 + 4)

---

## 7. Offene Restschuld

| ID | Beschreibung | Priorität |
|----|-------------|-----------|
| **B.3.4** | IBKR `reqAccountSummary` für echte Margin-Daten statt Notional-Approximation | Mittel |
| **B.3.5** | `SIZING_MAX_BUYING_POWER_PCT` (5%) Konstante eingeführt, aber noch nicht im Berechnungsweg | Niedrig |
