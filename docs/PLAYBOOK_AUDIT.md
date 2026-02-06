# OptionPlay - PLAYBOOK Compliance Audit

**Erstellt:** 2026-02-04
**Basis:** PLAYBOOK.md (2026-02-03) vs. Codebase v4.0.0
**Status:** Aktiv

---

## Gesamtbewertung: ~75% PLAYBOOK-konform

Die Kern-Logik (Delta, DTE, VIX-Regime-Definitionen, Earnings, Blacklist) ist korrekt implementiert.
Kritische Luecken bestehen bei der Durchsetzung von Regeln, die zwar als Konstanten definiert
sind, aber nie aufgerufen werden.

---

## Uebersicht Abweichungen

| # | Problem | Schwere | Bereich | Status |
|---|---------|---------|---------|--------|
| PB-001 | Volume-Check deaktiviert | KRITISCH | TradeValidator | Offen |
| PB-002 | Preis-Filter fehlt im Scanner | KRITISCH | Scanner | Offen |
| PB-003 | Disziplin-Regeln nicht implementiert | KRITISCH | Fehlend | Offen |
| PB-004 | Portfolio-Constraints ohne VIX-Regime | KRITISCH | PortfolioConstraints | Offen |
| PB-005 | Sector-Limit Fallback falsch (4 statt 2) | HOCH | trading_rules.py | Offen |
| PB-006 | Blacklist in Constraints unvollstaendig | HOCH | portfolio_constraints.py | Offen |
| PB-007 | Support-Break Exit fehlt | HOCH | PositionMonitor | Offen |
| PB-008 | Roll-Validierung unvollstaendig | HOCH | PositionMonitor | Offen |
| PB-009 | Konstanten-Widersprueche | HOCH | Constants | Offen |

---

## KRITISCHE ABWEICHUNGEN

### PB-001: Volume-Check ist komplett deaktiviert

**PLAYBOOK Regel:** §1 — Volume > 500.000 → NO-GO (harter Filter)

**Betroffene Dateien:**
- `src/services/trade_validator.py:555-565` — `_check_volume()` Methode
- `src/constants/trading_rules.py:56` — Konstante definiert: `ENTRY_VOLUME_MIN = 500_000`
- `src/services/trade_validator.py:37` — Konstante importiert aber nie gegen Daten geprueft
- `src/services/trade_validator.py:210` — Volume-Check aufgerufen, gibt aber immer GO

**Exakter Code (`trade_validator.py:555-565`):**

```python
def _check_volume(self, symbol: str, fundamentals: Any) -> ValidationCheck:
    """Check 6: Volume (PLAYBOOK §1)."""
    # Volume data not in fundamentals — skip with info
    # This would need a live quote or historical average
    return ValidationCheck(
        name="volume",
        passed=True,
        decision=TradeDecision.GO,  # IMMER GO!
        message="Volumen-Check (erfordert Live-Daten)",
        details={"note": "Volume check requires live quote data"},
    )
```

**Root Cause:** `symbol_fundamentals` Tabelle hat keine Volume-Spalte.
Historisches Tagesvolumen existiert in den Options-Daten, wird aber nicht herangezogen.

**Auswirkung:** Symbole mit beliebig niedrigem Volumen bestehen die Validierung.
Illiquide Symbole werden nicht ausgefiltert.

**Loesung:** Live-Volume aus Quote-API abrufen und gegen `ENTRY_VOLUME_MIN = 500_000` pruefen.
Alternativ: Durchschnittsvolumen in `symbol_fundamentals` aufnehmen.

---

### PB-002: Preis-Filter fehlt im Scanner / Daily Picks

**PLAYBOOK Regel:** §1 — Preis $20-$1500 → NO-GO (harter Filter)

**Betroffene Dateien:**
- `src/scanner/multi_strategy_scanner.py:404-537` — `filter_symbols_by_fundamentals()`
- `src/handlers/scan.py:510-659` — `daily_picks()` Handler
- `src/services/trade_validator.py:526-553` — `_check_price()` (korrekt, aber wird zu spaet aufgerufen)

**Datenfluss Daily Picks:**

```
daily_picks() [scan.py:510]
  → DailyRecommendationEngine.get_daily_picks() [scan.py:649]
    → MultiStrategyScanner.scan_async()
      → filter_symbols_by_fundamentals() [multi_strategy_scanner.py:404]
          Filtert: stability, win_rate, volatility, beta, IV rank, SPY correlation,
                   sector, market_cap
          Filtert NICHT: price, volume  ← FEHLT
      → analyze_symbol() pro Strategie (aufwaendig, API-Calls)
  → Ergebnis zurueck OHNE TradeValidator-Check  ← FEHLT
```

**Problem 1 — Scanner-Filter (`multi_strategy_scanner.py:404-537`):**

Der Scanner prueft folgende Kriterien vor der Analyse:
- Stability Score (ja)
- Win Rate (ja)
- Volatility (ja)
- Beta (ja)
- IV Rank (ja)
- SPY Correlation (ja)
- Market Cap (ja)
- **Preis: NEIN** ← fehlt
- **Volume: NEIN** ← fehlt

**Problem 2 — Daily Picks ohne Post-Validierung (`scan.py:510-659`):**

Der `daily_picks()` Handler ruft `DailyRecommendationEngine.get_daily_picks()` auf
und gibt Ergebnisse zurueck, OHNE jeden Kandidaten durch den TradeValidator zu schicken.

**Auswirkung:**
- Symbole mit Preis $5 oder $3000 werden analysiert und empfohlen
- Symbole mit 10k Tagesvolumen werden empfohlen
- Aufwaendige Analyse (API-Calls, Options Chain) fuer Symbole die ohnehin scheitern wuerden

**Loesung:**
1. Preis- und Volume-Filter in `filter_symbols_by_fundamentals()` einbauen (frueh, guenstig)
2. `TradeValidator.validate()` als Post-Filter in Daily Picks einbauen

---

### PB-003: Disziplin-Regeln komplett nicht implementiert

**PLAYBOOK Regel:** §6 — Frequenz-Limits und Verlust-Management

| Regel | PLAYBOOK Wert | Konstante definiert | Konstante verwendet |
|-------|--------------|--------------------|--------------------|
| Max Trades/Monat | 25 | `trading_rules.py:273` | Nirgends |
| Max Trades/Woche | 8 | `trading_rules.py:275` | Nirgends |
| Max Trades/Tag | 2 | `trading_rules.py:274` | Nirgends |
| 3 Verluste → 7d Pause | 3 / 7 | `trading_rules.py:278-279` | Nirgends |
| 5 Verluste/Monat → Pause | 5 | `trading_rules.py:280` | Nirgends |
| Portfolio -5% → Pause | 5% | `trading_rules.py:281` | Nirgends |

**Konstanten in `trading_rules.py:272-281`:**

```python
DISCIPLINE_MAX_TRADES_PER_MONTH = 25
DISCIPLINE_MAX_TRADES_PER_DAY = 2
DISCIPLINE_MAX_TRADES_PER_WEEK = 8

DISCIPLINE_CONSECUTIVE_LOSSES_PAUSE = 3
DISCIPLINE_PAUSE_DAYS = 7
DISCIPLINE_MONTHLY_LOSSES_PAUSE = 5
DISCIPLINE_MONTHLY_DRAWDOWN_PAUSE = 5.0
```

**Grep-Ergebnis — DISCIPLINE_* Referenzen im gesamten Codebase:**

| Datei | Art der Referenz |
|-------|-----------------|
| `src/constants/trading_rules.py` | Definition |
| `src/constants/__init__.py` | Re-Export in `__all__` |
| `tests/test_trading_rules.py` | Test-Import (nur Existenz-Check) |

**KEINE Referenzen in:**
- `src/handlers/portfolio.py` — kein Import
- `src/handlers/monitor.py` — kein Import
- `src/services/portfolio_constraints.py` — kein Import
- `src/services/position_monitor.py` — kein Import
- `src/services/trade_validator.py` — kein Import

**Fehlende Komponenten:**
- Kein `DisciplineMonitor` oder `PauseManager` Service
- Kein Loss-Tracking pro Position (Konsekutiv-Zaehler)
- Keine monatliche P&L-Aggregation fuer Pause-Trigger
- Keine Pre-Entry-Pruefung ("Ist eine Pause aktiv?")
- Kein Trade-Counter (wieviele Trades diese Woche/Monat)

**Auswirkung:** Trader kann unbegrenzt Verluste akkumulieren und weiter handeln.
Alle PLAYBOOK §6 Schutzregeln sind wirkungslos.

**Loesung:** `DisciplineMonitor`-Service erstellen:
1. Trade-Counter: Trades pro Tag/Woche/Monat zaehlen (aus Portfolio-DB)
2. Loss-Tracker: Konsekutive Verluste zaehlen
3. Pause-State: Aktive Pause mit Ablaufdatum
4. Pre-Entry-Check: Vor jedem `portfolio_add()` pruefen

---

### PB-004: Portfolio-Constraints ignorieren VIX-Regime

**PLAYBOOK Regel:** §5 — VIX-adjustierte Positions-Limits

| VIX | Regime | Max Positionen | Max/Sektor | Risiko/Trade |
|-----|--------|---------------|-----------|-------------|
| < 15 | LOW_VOL | 10 | 2 | 2% |
| 15-20 | NORMAL | 10 | 2 | 2% |
| 20-25 | DANGER_ZONE | 5 | 1 | 1.5% |
| 25-30 | ELEVATED | 3 | 1 | 1% |
| > 30 | HIGH_VOL | 0 | 0 | 0% |
| > 35 | NO_TRADING | 0 | 0 | 0% |

**Betroffene Dateien:**
- `src/services/portfolio_constraints.py:44-69` — `PortfolioConstraints` Dataclass
- `src/services/portfolio_constraints.py:117-146` — `can_open_position()` Signatur
- `src/services/portfolio_constraints.py:181` — Positions-Limit-Check (fest)
- `src/services/portfolio_constraints.py:253-281` — Sector-Limit-Check (fest)
- `src/handlers/portfolio.py:123` — Aufruf ohne VIX-Parameter
- `src/handlers/portfolio.py:310` — Aufruf ohne VIX-Parameter

**Hardcoded Defaults (`portfolio_constraints.py:44-69`):**

```python
@dataclass
class PortfolioConstraints:
    max_positions: int = 5              # Fest! PLAYBOOK: VIX-abhaengig
    max_per_sector: int = 2             # Fest! PLAYBOOK: VIX-abhaengig
    max_daily_risk_usd: float = 1500.0  # Fest! PLAYBOOK: VIX-abhaengig
    max_weekly_risk_usd: float = 5000.0
    max_position_size_usd: float = 2000.0
    max_correlation: float = 0.70
    min_cash_reserve_pct: float = 0.20
    symbol_blacklist: List[str] = field(default_factory=lambda: [
        "ROKU", "SNAP", "UPST", "MSTR", "MRNA", "TSLA", "COIN"  # Nur 7 von 14!
    ])
```

**`can_open_position()` Signatur (`portfolio_constraints.py:117-146`):**

```python
def can_open_position(
    self,
    symbol: str,
    max_risk: float,
    open_positions: List[Dict[str, Any]],
    account_value: Optional[float] = None,
) -> Tuple[bool, List[str]]:
```

Kein `vix: Optional[float]` Parameter. Kein Aufruf von `get_regime_rules()`.

**Kontrast — TradeValidator NUTZT VIX korrekt (`trade_validator.py:735-740`):**

```python
max_positions = SIZING_MAX_OPEN_POSITIONS  # 10
if current_vix is not None:
    regime_rules = get_regime_rules(current_vix)
    max_positions = regime_rules.max_positions
```

Die richtige Datenstruktur existiert in `trading_rules.py:140-201` (`VIXRegimeRules`),
wird aber von `PortfolioConstraints` nicht verwendet.

**Auswirkung:**
- Bei VIX 22 (DANGER_ZONE): Erlaubt 5 Positionen statt PLAYBOOK-Maximum 5 → zufaellig OK
- Bei VIX 28 (ELEVATED): Erlaubt 5 Positionen statt Maximum 3 → VERSTOSS
- Bei VIX 32 (HIGH_VOL): Erlaubt 5 neue Positionen statt 0 → SCHWERER VERSTOSS

**Loesung:** `vix: Optional[float]` Parameter zu `can_open_position()` und
`check_all_constraints()` hinzufuegen. `get_regime_rules(vix)` aufrufen und
Limits dynamisch anpassen.

---

## HOHE ABWEICHUNGEN

### PB-005: Sector-Limit Fallback falsch

**PLAYBOOK:** §5 — Max 2 Positionen/Sektor (bei VIX < 20)

**Betroffene Dateien:**
- `src/constants/trading_rules.py:265` — `SIZING_MAX_PER_SECTOR = 4` (FALSCH)
- `src/services/portfolio_constraints.py:52` — `max_per_sector: int = 2`
- `src/services/portfolio_constraints.py:253-281` — `_check_sector_limit()` Methode
- `src/services/portfolio_constraints.py:268-271` — Fallback-Logik
- `src/services/trade_validator.py:761` — Baseline-Wert

**`_check_sector_limit()` (`portfolio_constraints.py:253-281`):**

```python
def _check_sector_limit(self, symbol, open_positions):
    # ...
    sector = fundamentals.sector
    sector_count = sum(1 for p in open_positions if p.get('sector') == sector)
    limit = self.constraints.sector_limits.get(
        sector, self.constraints.max_per_sector  # Fallback auf 2 (Dataclass-Default)
    )
    if sector_count >= limit:
        return blocker
```

**Problem:**
- `PortfolioConstraints.max_per_sector` Default = 2 (OK fuer Normal-VIX)
- `SIZING_MAX_PER_SECTOR` in `trading_rules.py:265` = 4 (ZU HOCH)
- Der TradeValidator nutzt `SIZING_MAX_PER_SECTOR = 4` als Baseline (`trade_validator.py:761`)
- PLAYBOOK sagt bei normalem VIX: Max 2, bei Low Vol: Max 2
- VIXRegimeRules definiert korrekt: LOW_VOL=2, NORMAL=2, DANGER=1, ELEVATED=1

**Auswirkung:** TradeValidator erlaubt 4 Positionen pro Sektor als Fallback.

**Loesung:** `SIZING_MAX_PER_SECTOR` auf 2 setzen. VIX-Regime-spezifische Limits
aus `VIXRegimeRules` verwenden.

---

### PB-006: Blacklist in portfolio_constraints.py unvollstaendig

**PLAYBOOK:** §7 — 14 Symbole auf Blacklist

**Vergleich:**

| Symbol | `trading_rules.py:80-83` | `portfolio_constraints.py:67-69` |
|--------|:------------------------:|:--------------------------------:|
| ROKU   | ✅ | ✅ |
| SNAP   | ✅ | ✅ |
| UPST   | ✅ | ✅ |
| AFRM   | ✅ | ❌ FEHLT |
| MRNA   | ✅ | ✅ |
| RUN    | ✅ | ❌ FEHLT |
| MSTR   | ✅ | ✅ |
| TSLA   | ✅ | ✅ |
| COIN   | ✅ | ✅ |
| SQ     | ✅ | ❌ FEHLT |
| IONQ   | ✅ | ❌ FEHLT |
| QBTS   | ✅ | ❌ FEHLT |
| RGTI   | ✅ | ❌ FEHLT |
| DAVE   | ✅ | ❌ FEHLT |

**Auswirkung:** Wenn `PortfolioConstraintChecker` seinen Default-Blacklist verwendet,
koennen 7 geblockte Symbole durch den Constraint-Check kommen.
Der TradeValidator faengt sie zwar ab, aber die Pruefung ist redundant und inkonsistent.

**Loesung:** In `portfolio_constraints.py` die Blacklist aus `trading_rules.BLACKLIST_SYMBOLS`
importieren statt eine eigene, verkuerzte Liste zu definieren:

```python
from src.constants.trading_rules import BLACKLIST_SYMBOLS
symbol_blacklist: List[str] = field(default_factory=lambda: list(BLACKLIST_SYMBOLS))
```

---

### PB-007: Support-Break Exit nicht implementiert

**PLAYBOOK Regel:** §4 — "Support gebrochen → SCHLIESSEN innerhalb der Sitzung"

**Betroffene Dateien:**
- `src/services/position_monitor.py:310-354` — Exit-Prioritaets-Kette (8 Checks)
- `src/visualization/sr_chart.py` — 1,141 LOC, Support/Resistance Berechnung + Visualisierung

**Exit-Checks in `position_monitor.py:310-354` (aktuell implementiert):**

1. `_check_expired()` — DTE <= 0
2. `_check_force_close()` — DTE <= 7
3. `_check_profit_target()` — 50%/30% Profit
4. `_check_stop_loss()` — 200% Loss
5. `_check_21dte_decision()` — Roll oder Close
6. `_check_high_vix()` — VIX > 30 Management
7. `_check_earnings_risk()` — Earnings vor Expiration
8. Default: HOLD

**FEHLEND:** `_check_support_break()` — kein Check ob Support-Level gebrochen wurde.

**S/R-Berechnung existiert aber:** `src/visualization/sr_chart.py` berechnet
Support/Resistance-Levels fuer Visualisierung. Diese Logik wird aber NUR fuer
PDF-Reports und Charts verwendet, nicht fuer Exit-Entscheidungen.

**Grep-Ergebnis in `position_monitor.py`:**
- "support": 0 Treffer
- "resistance": 0 Treffer
- "sr_chart": 0 Treffer

**Auswirkung:** Wenn ein Symbol seinen Support bricht, erhaelt der Trader kein CLOSE-Signal.
Die Position laeuft weiter bis Stop Loss (200%) oder DTE-Exit greift.

**Loesung (mehrstufig):**
1. Support-Level-Berechnung aus `sr_chart.py` in eigenen Service extrahieren
2. `_check_support_break()` in `position_monitor.py` hinzufuegen
3. Check: Ist der aktuelle Preis unter dem naechsten Support-Level unter dem Short-Strike?
4. Bei Bruch: CLOSE-Signal mit Prioritaet zwischen Stop-Loss und 21-DTE

---

### PB-008: Roll-Validierung unvollstaendig

**PLAYBOOK Regel:** §4 — Roll-Regeln

**Datei:** `src/services/position_monitor.py:581-617` — `_can_roll()`

**PLAYBOOK Anforderungen vs. Implementation:**

| Bedingung | PLAYBOOK | Implementiert | Zeile |
|-----------|----------|:------------:|-------|
| Position profitabel/Break-Even | Ja | ✅ | :467-470 |
| Symbol besteht alle Entry-Filter | Ja | ❌ | :598-600 (Kommentar: "can't check") |
| Neues Expiration 60-90 DTE | Ja | ✅ | `ROLL_NEW_DTE_MIN/MAX` definiert |
| Neuer Credit >= 10% Spread | Ja | ❌ | Nicht geprueft |
| Nicht im Verlust | Ja | ✅ | :467-470 |
| Keine Earnings im neuen Fenster | Ja | ✅ | :602-614 |

**Kommentar im Code (`position_monitor.py:598-600`):**

```python
# Condition 2: Stability check — we can't check without fundamentals
# in this service, so we allow it (the Trade Validator will catch it
# if the user actually tries to enter the roll)
```

**`ROLL_MIN_CREDIT_PCT` Verwendung:**
- Definiert: `trading_rules.py:256` = 10.0
- Verwendet: **Nirgends** ausser `tests/test_trading_rules.py:363` (Existenz-Test)
- **Nicht aufgerufen** in `_can_roll()`

**Auswirkung:** System empfiehlt Rolls ohne zu pruefen ob:
- Das Symbol noch alle Entry-Filter besteht (Stability koennte gefallen sein)
- Der neue Credit ausreichend ist (koennte unter 10% Spread-Breite liegen)

**Loesung:**
1. `TradeValidator` in `PositionMonitor` injizieren (DI)
2. Bei Roll-Entscheidung: `await validator.validate(symbol)` aufrufen
3. Credit-Check: `new_credit >= spread_width * ROLL_MIN_CREDIT_PCT / 100`

---

### PB-009: Konstanten-Widersprueche zwischen Dateien

Drei Dateien definieren teilweise dieselben Parameter mit unterschiedlichen Werten:

**Betroffene Dateien:**
- `src/constants/trading_rules.py` — PLAYBOOK-konforme Werte
- `src/constants/thresholds.py` — Abweichende Werte
- `src/constants/risk_management.py` — Abweichende Werte
- `src/constants/__init__.py` — Re-Exports (leitet falsche Werte weiter)

#### PB-009a: MIN_CREDIT_PCT — 10% vs. 20%

| Datei | Konstante | Wert | PLAYBOOK |
|-------|-----------|------|----------|
| `trading_rules.py:110` | `SPREAD_MIN_CREDIT_PCT` | 10.0 | **10%** ✅ |
| `thresholds.py:31` | `MIN_CREDIT_PCT` | **20.0** | 10% ❌ |

**Wer importiert den falschen Wert?**
- `src/constants/__init__.py:101` — exportiert `thresholds.MIN_CREDIT_PCT = 20.0`
- Module die `from src.constants import MIN_CREDIT_PCT` nutzen, bekommen 20% statt 10%

**Auswirkung:** Abhaengig davon welche Konstante importiert wird, werden Trades mit
10-19% Credit entweder akzeptiert (korrekt) oder abgelehnt (falsch).

#### PB-009b: DTE_MIN_STRICT — 45 vs. 60

| Datei | Konstante | Wert | PLAYBOOK |
|-------|-----------|------|----------|
| `trading_rules.py:96` | `SPREAD_DTE_MIN` | 60 | **60** ✅ |
| `risk_management.py:21` | `DTE_MIN_STRICT` | **45** | 60 ❌ |

**Auswirkung:** `DTE_MIN_STRICT = 45` suggeriert dass Trades mit 45 DTE "strikt" erlaubt sind.
PLAYBOOK verlangt Minimum 60 DTE. In der Praxis nutzt der TradeValidator `SPREAD_DTE_MIN = 60`
(korrekt), aber das falsche Strict-Limit koennte bei zukuenftiger Verwendung Probleme machen.

#### PB-009c: STABILITY_BLACKLIST — 50 vs. 40

| Datei | Konstante | Wert | PLAYBOOK |
|-------|-----------|------|----------|
| `trading_rules.py:86` | `BLACKLIST_STABILITY_THRESHOLD` | 40.0 | **40** ✅ |
| `thresholds.py:64` | `STABILITY_BLACKLIST` | **50.0** | 40 ❌ |

**Auswirkung:** Symbole mit Stability 41-49 werden von `thresholds.py` als Blacklist-Kandidaten
eingestuft, obwohl PLAYBOOK nur < 40 blacklisted. Zu konservativ, aber falsche Grenze.

**Loesung (fuer alle PB-009):**
1. `trading_rules.py` als alleinige Source of Truth festlegen
2. In `thresholds.py`: Falsche Werte loeschen, stattdessen aus `trading_rules` importieren
3. In `risk_management.py`: `DTE_MIN_STRICT` auf 60 korrigieren oder entfernen
4. In `__init__.py`: Nur noch `trading_rules.*` re-exportieren fuer ueberlappende Werte

---

## KORREKT IMPLEMENTIERT

| Bereich | Datei:Zeile | Details |
|---------|-------------|---------|
| VIX-Regime-Definitionen | `trading_rules.py:140-201` | Alle 6 Tiers korrekt |
| VIX-Boundaries | `trading_rules.py:121-125` | 15, 20, 25, 30, 35 |
| VIX-abhaengige Stability | `trading_rules.py:143,163` | 70 (normal), 80 (Danger/Elevated) |
| VIX-Regime in Validator | `trade_validator.py:735-740` | `get_regime_rules()` korrekt |
| Delta-Targets Short | `trading_rules.py:101-103` | -0.20 ±0.03 |
| Delta-Targets Long | `trading_rules.py:105-107` | -0.05 ±0.02 |
| "Delta ist heilig" | Strike-Recommender | Kein Backdoor |
| Spread-Breite dynamisch | Strike-Recommender | Aus Delta abgeleitet, nicht fest |
| DTE 60-90 | `trading_rules.py:96-98` | 60/90/75 korrekt |
| Earnings > 60 Tage | `trade_validator.py:207` | Mit DB + API Fallback |
| Blacklist (TradeValidator) | `trading_rules.py:80-83` | Alle 14 Symbole |
| Preis-Check (Validator) | `trade_validator.py:526-553` | $20-$1500 korrekt |
| Exit 50% Profit (VIX < 20) | `position_monitor.py:388-428` | Korrekt |
| Exit 30% Profit (VIX >= 20) | `position_monitor.py:398-426` | Korrekt VIX-abhaengig |
| Exit 200% Stop Loss | `position_monitor.py:430-455` | Korrekt |
| Exit 7 DTE Force Close | `position_monitor.py:374-386` | Korrekt |
| Exit 21 DTE Decision | `position_monitor.py:457-502` | Korrekt |
| Exit High VIX Management | `position_monitor.py:504-539` | Korrekt |
| Exit Earnings Risk | `position_monitor.py:541-575` | Korrekt |
| Exit-Prioritaets-Reihenfolge | `position_monitor.py:310-354` | 8 Checks, richtige Reihenfolge |
| Pruef-Reihenfolge (Validator) | `trade_validator.py` | Exakt wie PLAYBOOK §1 |
| Liquidity OI > 100 | `strike_recommender.py:673-693` | Korrekt |
| Blacklist-Kriterien | `trading_rules.py:86-88` | Stability<40, WR<70%, Vol>100% |

---

## Empfohlene Reihenfolge

1. **PB-009** — Konstanten-Widersprueche bereinigen (Basis fuer alles andere)
2. **PB-006** — Blacklist aus trading_rules importieren (schneller Fix, 1 Zeile)
3. **PB-001** — Volume-Check aktivieren (API-Integration noetig)
4. **PB-002** — Preis+Volume in Scanner als fruehen Filter + Post-Validierung
5. **PB-004** — Portfolio-Constraints mit VIX-Regime verbinden
6. **PB-005** — Sector-Limit Default auf 2 korrigieren
7. **PB-008** — Roll-Validierung vervollstaendigen (Credit + Entry-Filter)
8. **PB-003** — Disziplin-System (DisciplineMonitor/PauseManager) implementieren
9. **PB-007** — Support-Break Detection (groesstes Feature, S/R-Service extrahieren)
