# Risk Management — Aktive Logik

**Stand:** 2026-04-17 (nach B.3.4-Implementation)

Dieses Dokument beschreibt die aktiven Risk-Management-Mechanismen.
Trading-Regeln (Playbook) → `docs/PLAYBOOK.md`.

---

## 1. Risk per Trade

**Quelle:** `config/trading.yaml → sizing.max_risk_per_trade_pct`
**Konstante:** `SIZING_MAX_RISK_PER_TRADE_PCT` in `src/constants/trading_rules.py`

| VIX-Regime | Risk per Trade |
|------------|---------------|
| LOW_VOL (< 15) | 2.5% |
| NORMAL (15-20) | 2.5% |
| DANGER_ZONE (20-25) | 1.5% |
| ELEVATED (25-30) | 1.0% |
| HIGH_VOL / NO_TRADING | 0.0% |

Der VIX-Regime-spezifische Wert stammt aus `vix_regimes.rules.<regime>.risk_per_trade_pct`
und wird in `TradeValidator._calculate_sizing()` angewendet.

---

## 2. Position Sizing (Kelly Criterion)

**Modul:** `src/risk/position_sizing.py`
**Klasse:** `PositionSizer` + `PositionSizerConfig`

### Berechnungsreihenfolge

1. Kelly-Fraktion berechnen (win_rate, avg_win, avg_loss)
2. VIX-Adjustment anwenden (1.0× bei low, 0.25× bei extreme)
3. Reliability-Grade-Adjustment (A=1.0, F=0.0)
4. Score-Adjustment (linear ab `min_score_for_trade=5.0`)
5. Verfügbares Risiko-Budget: `account_size * max_portfolio_risk - current_exposure`
6. Trade-Risiko: `min(kelly, max_risk_per_trade, available_risk)`
7. Contracts aus Trade-Risiko / max_loss_per_contract
8. Cap durch `max_by_capital` (5% des Accounts)
9. **Cap durch `max_by_notional`** (B.3.2-light, wenn `spread_width` übergeben)

### PositionSizerConfig.from_yaml()

```python
config = PositionSizerConfig.from_yaml()
```

Liest `max_risk_per_trade` und `max_portfolio_allocation` aus YAML-Konstanten.
Eliminiert Drift zwischen YAML und Dataclass-Defaults (analog OQ-2 fix).

---

## 3. Notional-basierte Portfolio-Allokation (B.3.2-light)

**Quelle:** `config/trading.yaml → sizing.max_portfolio_allocation: 50.0`
**Feld:** `PositionSizerConfig.max_portfolio_allocation = 0.50`

Wenn `spread_width` an `calculate_position_size()` übergeben wird:

```
notional_capacity = account_size * 0.50 - current_notional
max_new_notional   = spread_width * 100
max_by_notional    = int(notional_capacity / max_new_notional)
```

**Einschränkung:** Dies ist eine Näherung. Echte IBKR-Margin bindet ca. 70-80% des Notionals.
Die 50%-Notional-Grenze ist bewusst konservativ. Seit B.3.4 wird die echte IBKR-Margin bevorzugt
(siehe §5 unten); die Notional-Approximation bleibt als Fallback aktiv.

---

## 4. portfolio_value Pflicht (B.3.1)

**Modul:** `src/services/trade_validator.py`
**Methode:** `_check_portfolio_value()`

Wenn Spread-Parameter vorhanden (short_strike, long_strike, credit) aber kein portfolio_value:

| portfolio_value | Decision | Begründung |
|-----------------|----------|-----------|
| `None` | WARNING | Risk-Check übersprungen, manuelle Prüfung nötig |
| `<= 0` | NO_GO | Ungültig, Berechnung nicht möglich |
| `> 0` | GO | Normal |

---

## 5. Margin-Capacity-Check (B.3.4)

**Modul:** `src/services/trade_validator.py`
**Methode:** `_check_margin_capacity()`
**Quelle:** `config/trading.yaml → sizing.max_margin_pct: 50.0`
**Konstante:** `SIZING_MAX_MARGIN_PCT` in `src/constants/trading_rules.py`

### Formel

```
margin = (spread_width - credit_received) × 100 × contracts
```

Implementiert in `src/risk/position_sizing.calculate_spread_margin()` (pure Funktion).

### Dreistufiger Fallback

| Stufe | Quelle | Entscheidung |
|-------|--------|-------------|
| 1 | IBKR `reqAccountSummary` (live) | `(maint_margin_req + new_margin) / net_liq > 50%` → NO_GO |
| 2 | Notional-Approximation (`portfolio_value`) | `new_margin / portfolio_value > 50%` → NO_GO |
| 3 | Kein Wert verfügbar | WARNING — manuell prüfen |

### Konfiguration

```yaml
# config/trading.yaml
sizing:
  max_margin_pct: 50.0    # Max 50% margin utilization
  use_ibkr_margin: true   # Try IBKR first; fallback to notional
```

### Einbindung in validate()

Läuft nach `_check_portfolio_value`, nur wenn short_strike + long_strike + credit vorhanden.
Wenn `contracts` nicht angegeben: Prüfung mit 1 Contract.

---

## 6. Offene Restschuld

| ID | Beschreibung |
|----|-------------|
| B.3.5 | `SIZING_MAX_BUYING_POWER_PCT` (5%) im Berechnungsweg ✅ (seit B.3.5) |
