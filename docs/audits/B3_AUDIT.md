# B.3 Risk Management Audit

**Datum:** 2026-04-16
**Branch:** `verschlankung/b3-risk-management`

---

## Befunde

### B.3.0 — Risk per Trade zu niedrig (2.0% vs. Friend-Style 2.5%)

**Schwere:** Mittel
**Beschreibung:** `sizing.max_risk_per_trade_pct` und `vix_regimes.rules.{low_vol,normal}.risk_per_trade_pct`
waren auf 2.0% gesetzt. Der "Friend-Style" (Tastytrade-ähnlich, bewährte Praxis) empfiehlt 2.5%
in ruhigen Marktphasen mit entsprechend reduzierter Größe in höheren VIX-Regimes.

**Fundstellen:**
- `config/trading.yaml` → `sizing.max_risk_per_trade_pct`
- `config/trading.yaml` → `vix_regimes.rules.low_vol.risk_per_trade_pct`
- `config/trading.yaml` → `vix_regimes.rules.normal.risk_per_trade_pct`

---

### B.3.1 — `portfolio_value` bei Risikocheck silently ignoriert

**Schwere:** Hoch (verstecktes Risiko-Loch)
**Beschreibung:** In `TradeValidator.validate()` wurde `portfolio_value = None` stillschweigend
akzeptiert: der Risk-%-Check wurde übersprungen, ohne dass eine Warnung ausgegeben wurde.
Der Aufrufer hatte keine Möglichkeit zu erkennen, dass das Sizing unvollständig war.

**Fundstelle:** `src/services/trade_validator.py` → Zeile ~268 (vor dem Fix)

**Fix:** Neuer `_check_portfolio_value()` Check, der bei `None` → WARNING und bei `<= 0` → NO_GO zurückgibt.
Der Check wird immer ausgeführt wenn Spread-Parameter vorhanden (short_strike, long_strike, credit).

---

### B.3.2 — `max_portfolio_allocation` definiert aber nicht aktiv im Sizing-Pfad

**Schwere:** Mittel
**Beschreibung:** `config/trading.yaml` enthielt bereits `sizing.max_portfolio_allocation: 50.0`
und `PositionSizerConfig` sollte eine analoge Schranke haben, aber `calculate_position_size()`
berücksichtigte kein Notional-basiertes Limit. Die Schranke war toter Code.

**Fundstelle:** `src/risk/position_sizing.py` → `calculate_position_size()`

**Fix (B.3.2-light):** Neuer optionaler Parameter `spread_width` in `calculate_position_size()`.
Wenn gesetzt: Notional-Kapazität = `account_size * max_portfolio_allocation - current_notional`.
Notional pro Contract = `spread_width * 100`. Ergibt `max_by_notional`-Grenze im min()-Ausdruck.

**Einschränkung:** Echte IBKR-Margin (reqAccountSummary) steht erst in B.3.4 zur Verfügung.
50% Notional ist eine konservative Approximation (echte Margin ≈ 70-80% des Notionals).

---

### B.3.3 — `PositionSizerConfig` Dataclass-Defaults driften von YAML

**Schwere:** Mittel (analog OQ-2 für IV Rank)
**Beschreibung:** `PositionSizerConfig` hatte hardkodierte Defaults (`max_risk_per_trade=0.02`,
`max_portfolio_allocation=0.50`). Änderungen in `trading.yaml` griffen nur, wenn der Aufrufer
explizit Constants importierte. Kein Aufrufer tat das — alle nutzten `PositionSizerConfig()` direkt.

**Fundstellen:**
- `src/risk/position_sizing.py` → `PositionSizerConfig` dataclass
- `src/handlers/risk_composed.py` → `PositionSizerConfig(kelly_mode=KellyMode.HALF)`

**Fix:** `PositionSizerConfig.from_yaml()` classmethod, der `SIZING_MAX_RISK_PER_TRADE_PCT` und
`SIZING_MAX_PORTFOLIO_ALLOCATION` aus den Constants liest (welche wiederum aus YAML kommen).
`PositionSizer.__init__` verwendet jetzt `from_yaml()` als Default statt `PositionSizerConfig()`.

---

## Implementation Status (B.3 abgeschlossen)

| Befund | Status | Commit |
|--------|--------|--------|
| Risk per trade 2.5% | ✅ | 64c016e |
| B.3.1 portfolio_value Pflicht | ✅ | 686cff4 |
| B.3.2-light max_portfolio_allocation | ✅ | 47c5c87 |
| B.3.3 PositionSizerConfig.from_yaml() | ✅ | 9bdf656 |

### Neue Defaults (nach B.3)

| Parameter | Vorher | Nachher |
|-----------|--------|---------|
| `sizing.max_risk_per_trade_pct` | 2.0% | 2.5% |
| `vix_regimes.low_vol.risk_per_trade_pct` | 2.0% | 2.5% |
| `vix_regimes.normal.risk_per_trade_pct` | 2.0% | 2.5% |
| `PositionSizerConfig.max_risk_per_trade` | 0.02 (hardcoded) | 0.025 (via from_yaml()) |
| `portfolio_value = None` | silent skip | WARNING check |
| `max_portfolio_allocation` | toter Code | aktiv via current_notional/spread_width |

### Unverändert (bewusst)

| Parameter | Wert | Begründung |
|-----------|------|-----------|
| `danger_zone.risk_per_trade_pct` | 1.5% | VIX 20-25: reduziertes Risiko |
| `elevated.risk_per_trade_pct` | 1.0% | VIX 25-30: stark reduziert |
| `high_vol.risk_per_trade_pct` | 0.0% | VIX > 30: kein Trading |
| `no_trading.risk_per_trade_pct` | 0.0% | VIX > 35: kein Trading |

---

## Offene Restschuld

| ID | Beschreibung | Priorität |
|----|-------------|-----------|
| **B.3.4** | IBKR `reqAccountSummary` für echte Margin-Daten statt Notional-Approximation | Mittel |
| **B.3.5** | `buying_power_pct` Konstante eingeführt (`SIZING_MAX_BUYING_POWER_PCT`), aber noch nicht im Berechnungsweg von `calculate_position_size()` | Niedrig |
