# OptionPlay — Daily Picks v2: Implementation Tasks

**Erstellt:** 2026-02-04
**Für:** Claude Code Session
**Basis:** ROADMAP_DAILY_PICKS_V2.md, PLAYBOOK.md, PLAYBOOK_AUDIT.md, TECHNICAL_DEBT.md
**Projekt:** `~/OptionPlay/`

---

## Kontext

OptionPlay ist ein Bull-Put-Spread Trading-System (MCP Server, Python 3.11+).
Die Daily Picks empfehlen täglich 3-5 Trades. Aktuell nutzen sie theoretische
Strike-Berechnung ohne echte Options-Chain-Validierung. ~30% der Picks sind
nicht handelbar (fehlende Liquidität, keine echten Quotes).

**Ziel:** Pipeline umbauen auf Options-Chain-First. Jeder Pick hat echte Bid/Ask,
validierte Liquidität und einen Entry Quality Score.

**Verbindliche Regeln:** `docs/PLAYBOOK.md` — bei Widersprüchen gilt PLAYBOOK.
**DB-Schema:** `CLAUDE.md` — Tabellen, Spalten, Joins.
**Architektur:** `docs/ARCHITECTURE.md`

---

## Allgemeine Regeln für alle Phasen

- `src/constants/trading_rules.py` ist Single Source of Truth für alle Konstanten
- Keine Duplikation von Werten — immer aus `trading_rules` importieren
- Alle neuen Services in `src/services/` anlegen
- Exception-Handling: Spezifische Exceptions aus `src/exceptions.py`, kein bare `except:`
- Logging: `logger = logging.getLogger(__name__)` in jeder Datei
- Type Hints für alle öffentlichen Methoden
- Tests in `tests/` mit `pytest`, Namenskonvention `test_<modul>.py`

---

## PHASE 1: Fundament reparieren

### Task 1.1: Konstanten-Widersprüche auflösen (PB-009)

**Ziel:** Eine einzige Quelle für alle Trading-Konstanten.

**Problem:** Drei Dateien definieren gleiche Werte unterschiedlich:

| Parameter | `trading_rules.py` | `thresholds.py` | `risk_management.py` | PLAYBOOK |
|-----------|-------------------|-----------------|---------------------|----------|
| Min Credit % | 10% | **20%** | — | **10%** |
| Stability Blacklist | 40 | **50** | — | **40** |
| Max/Sektor | **4** | — | — | **2** (normal VIX) |
| DTE_MIN_STRICT | — | — | **45** | **60** |

**Dateien:**

```
src/constants/trading_rules.py    ← Single Source of Truth (behalten + korrigieren)
src/constants/thresholds.py       ← Widersprüche bereinigen, delegieren
src/constants/risk_management.py  ← Widersprüche bereinigen, delegieren
```

**Schritte:**

1. In `src/constants/trading_rules.py`:
   - `SIZING_MAX_PER_SECTOR = 4` ändern auf `2` (PLAYBOOK §5: "Max 2 bei Normal VIX")
   - Prüfen dass `SPREAD_MIN_CREDIT_PCT = 10.0` korrekt ist (PLAYBOOK §2)
   - Prüfen dass `DTE_MIN = 60` korrekt ist (PLAYBOOK §2)
   - Prüfen dass `STABILITY_BLACKLIST_THRESHOLD = 40` korrekt ist (PLAYBOOK §7)

2. In `src/constants/thresholds.py`:
   - `MIN_CREDIT_PCT = 20.0` → durch Import ersetzen:
     ```python
     from .trading_rules import SPREAD_MIN_CREDIT_PCT as MIN_CREDIT_PCT
     ```
   - `STABILITY_BLACKLIST = 50` → durch Import ersetzen:
     ```python
     from .trading_rules import STABILITY_BLACKLIST_THRESHOLD as STABILITY_BLACKLIST
     ```

3. In `src/constants/risk_management.py`:
   - `DTE_MIN_STRICT = 45` → durch Import ersetzen:
     ```python
     from .trading_rules import DTE_MIN as DTE_MIN_STRICT
     ```

4. Grep über gesamtes `src/` nach hardcodierten Werten:
   ```bash
   grep -rn "MIN_CREDIT_PCT\|DTE_MIN\|STABILITY_BLACKLIST\|MAX_PER_SECTOR" src/
   ```
   Alle Stellen die eigene Werte definieren → auf Import umstellen.

**Akzeptanzkriterium:**
```bash
# Nur noch trading_rules.py definiert diese Werte:
grep -rn "= 20.0\|= 50\|= 45\|= 4" src/constants/ | grep -v trading_rules | grep -v "^#"
# → Kein Treffer (außer Comments)
```

---

### Task 1.2: Blacklist vereinheitlichen (PB-006)

**Problem:** `portfolio_constraints.py` hat nur 7 der 14 Blacklist-Symbole.

**Dateien:**

```
src/constants/trading_rules.py         ← Hat alle 14 Symbole ✅
src/services/portfolio_constraints.py  ← Hat nur 7 ❌
```

**Schritte:**

1. In `src/services/portfolio_constraints.py`:
   ```python
   # ALT (löschen):
   symbol_blacklist: List[str] = field(default_factory=lambda: [
       "ROKU", "SNAP", "UPST", "MSTR", "MRNA", "TSLA", "COIN"
   ])

   # NEU:
   from src.constants.trading_rules import BLACKLIST_SYMBOLS
   # ...
   symbol_blacklist: List[str] = field(default_factory=lambda: list(BLACKLIST_SYMBOLS))
   ```

2. Prüfen ob andere Dateien eigene Blacklists haben:
   ```bash
   grep -rn "BLACKLIST\|blacklist" src/ --include="*.py" | grep -v __pycache__
   ```

**Akzeptanzkriterium:**
```python
from src.services.portfolio_constraints import PortfolioConstraints
pc = PortfolioConstraints()
assert len(pc.symbol_blacklist) == 14
assert "DAVE" in pc.symbol_blacklist
assert "IONQ" in pc.symbol_blacklist
```

---

### Task 1.3: Volume-Check aktivieren (PB-001)

**Problem:** `_check_volume()` gibt IMMER GO zurück.

**Datei:** `src/services/trade_validator.py` ca. Zeile 555-565

**Aktueller Code:**
```python
def _check_volume(self, symbol, fundamentals):
    return ValidationCheck(
        name="volume", passed=True,
        decision=TradeDecision.GO,  # IMMER GO!
        message="Volumen-Check (erfordert Live-Daten)",
    )
```

**Schritte:**

1. Volume aus Quote-API abrufen (Tradier oder IBKR):
   ```python
   async def _check_volume(self, symbol, fundamentals):
       try:
           quote = await self.quote_provider.get_quote(symbol)
           volume = quote.get("volume", 0)
       except Exception as e:
           logger.warning(f"Volume-Check für {symbol} fehlgeschlagen: {e}")
           return ValidationCheck(
               name="volume", passed=True,
               decision=TradeDecision.WARNING,
               message=f"Volume nicht verfügbar — manuell prüfen",
           )

       min_volume = ENTRY_VOLUME_MIN  # 500_000 aus trading_rules.py
       if volume < min_volume:
           return ValidationCheck(
               name="volume", passed=False,
               decision=TradeDecision.NO_GO,
               message=f"Volume {volume:,} < {min_volume:,} Minimum",
           )

       return ValidationCheck(
           name="volume", passed=True,
           decision=TradeDecision.GO,
           message=f"Volume {volume:,} ✅",
       )
   ```

2. `ENTRY_VOLUME_MIN` aus `trading_rules.py` importieren (Wert: 500_000).
   Prüfen ob die Konstante existiert, ggf. anlegen.

3. Quote-Provider als Dependency in TradeValidator injizieren (Constructor).

**Akzeptanzkriterium:**
```python
# Symbol mit < 500k Volume wird abgelehnt
result = await validator.validate_trade("ILLIQUID_SYMBOL")
assert any(c.name == "volume" and c.decision == TradeDecision.NO_GO for c in result.checks)
```

**Hinweis:** Bei API-Fehler → WARNING (nicht NO_GO), damit der Scanner nicht komplett ausfällt.

---

### Task 1.4: Preis-Filter im Scanner (PB-002)

**Problem:** Scanner analysiert alle Symbole, Preis-Check passiert erst im Validator.

**Datei:** `src/scanner/multi_strategy_scanner.py` — Methode `filter_symbols_by_fundamentals()`

**Schritte:**

1. Preis-Check als frühen Filter in `filter_symbols_by_fundamentals()` einbauen:
   ```python
   from src.constants.trading_rules import ENTRY_PRICE_MIN, ENTRY_PRICE_MAX

   def filter_symbols_by_fundamentals(self, symbols):
       filtered = []
       for symbol in symbols:
           fundamentals = self.get_fundamentals(symbol)
           if not fundamentals:
               continue

           # NEU: Preis-Filter (PLAYBOOK §1)
           price = fundamentals.current_price
           if price and (price < ENTRY_PRICE_MIN or price > ENTRY_PRICE_MAX):
               logger.debug(f"{symbol}: Preis ${price:.2f} außerhalb ${ENTRY_PRICE_MIN}-${ENTRY_PRICE_MAX}")
               continue

           # Bestehende Filter (Stability, Market Cap, etc.)
           ...
           filtered.append(symbol)
       return filtered
   ```

2. Prüfen ob `ENTRY_PRICE_MIN` (20) und `ENTRY_PRICE_MAX` (1500) in `trading_rules.py` existieren.

**Akzeptanzkriterium:**
```python
# Symbol mit Preis $8 wird vom Scanner nicht analysiert
scanner = MultiStrategyScanner()
filtered = scanner.filter_symbols_by_fundamentals(["PENNY_STOCK", "AAPL"])
assert "PENNY_STOCK" not in filtered
```

---

### Task 1.5: Bare Exceptions bereinigen (DEBT-002)

**Problem:** 5x bare `except:` und 13x silent `except Exception: pass`

**Dateien:**
```
src/ibkr_bridge.py              ← bare except:
src/options/max_pain.py          ← bare except:
src/indicators/sr_chart.py       ← silent pass
src/handlers/validate.py         ← silent pass
src/services/vix_service.py      ← silent pass
src/services/recommendation_engine.py ← silent pass
src/strike_recommender.py        ← silent pass
src/utils/secure_config.py       ← silent pass
```

**Schritte:**

1. Alle bare `except:` finden und durch `except Exception as e:` ersetzen:
   ```bash
   grep -rn "except:" src/ --include="*.py" | grep -v "except Exception" | grep -v "except \w"
   ```

2. Alle `except Exception: pass` durch Logging ersetzen:
   ```bash
   grep -rn "except.*pass" src/ --include="*.py"
   ```

3. Pattern für Ersetzung:
   ```python
   # ALT:
   except:
       pass

   # NEU:
   except Exception as e:
       logger.debug(f"Non-critical error in {context}: {e}")
   ```

4. Bei kritischen Stellen (trade_validator, position_monitor) statt `debug` → `warning` verwenden.

**Akzeptanzkriterium:**
```bash
# Keine bare except: mehr
grep -rn "except:" src/ --include="*.py" | grep -v "except Exception" | grep -v "except \w" | wc -l
# → 0

# Keine silent pass mehr
grep -rn "except.*pass$" src/ --include="*.py" | wc -l
# → 0
```

---

### Phase 1 — Validierung

Nach Abschluss aller Tasks:

```bash
# 1. Tests laufen
pytest tests/ -x -q

# 2. Konstanten-Check
python -c "
from src.constants.trading_rules import *
from src.constants.thresholds import *
from src.constants.risk_management import *
print(f'Min Credit: {SPREAD_MIN_CREDIT_PCT}%')  # → 10.0
print(f'DTE Min: {DTE_MIN}')                     # → 60
print(f'Stability BL: {STABILITY_BLACKLIST_THRESHOLD}')  # → 40
print(f'Max/Sektor: {SIZING_MAX_PER_SECTOR}')    # → 2
"

# 3. Validator prüft Volume
python -c "
import asyncio
from src.services.trade_validator import TradeValidator
v = TradeValidator()
result = asyncio.run(v.validate_trade('AAPL'))
vol_check = [c for c in result.checks if c.name == 'volume'][0]
print(f'Volume: {vol_check.message}')  # → Volume 54,200,000 ✅ (nicht 'erfordert Live-Daten')
"
```

---

## PHASE 2: Options Chain Integration

### Task 2.1: OptionsChainValidator Service erstellen

**Ziel:** Neuer Service der echte Options-Chain-Daten abruft und validiert.

**Neue Datei:** `src/services/options_chain_validator.py`

```python
"""
Options Chain Validator — prüft ob ein Trade echte Marktdaten hat.

Datenquellen-Priorität:
  1. IBKR (wenn TWS verbunden) — Live Bid/Ask
  2. Tradier — Delayed, aber zuverlässig
  3. Marketdata.app — Backup für IV-Daten (wird in Woche 4 geprüft)

Verwendet wird:
  - trading_rules.py für DTE_MIN, DTE_MAX, DELTA_*, SPREAD_MIN_CREDIT_PCT
  - Keine eigenen Konstanten definieren
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import date, timedelta

from src.constants.trading_rules import (
    DTE_MIN, DTE_MAX, DTE_OPTIMAL,
    DELTA_SHORT_TARGET, DELTA_SHORT_TOLERANCE,
    DELTA_LONG_TARGET, DELTA_LONG_TOLERANCE,
    SPREAD_MIN_CREDIT_PCT,
    ENTRY_OPEN_INTEREST_MIN,  # 100
)

logger = logging.getLogger(__name__)


@dataclass
class OptionLeg:
    """Ein Leg eines Spreads mit echten Marktdaten."""
    strike: float
    expiration: str           # YYYY-MM-DD
    dte: int
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float                 # Implied Volatility für diesen Strike
    bid: float
    ask: float
    mid: float
    last: Optional[float]
    open_interest: int
    volume: int


@dataclass
class SpreadValidation:
    """Ergebnis der Options-Chain-Validierung."""
    tradeable: bool
    reason: str = ""
    warning: bool = False

    # Spread-Daten (nur wenn tradeable=True)
    short_leg: Optional[OptionLeg] = None
    long_leg: Optional[OptionLeg] = None
    expiration: Optional[str] = None
    dte: Optional[int] = None

    # Credit-Daten
    credit_bid: Optional[float] = None    # Konservativ: Short Bid - Long Ask
    credit_mid: Optional[float] = None    # Mittel: Short Mid - Long Mid
    spread_width: Optional[float] = None
    credit_pct: Optional[float] = None    # Credit / Spread-Breite in %

    # Spread-Greeks
    spread_theta: Optional[float] = None  # Theta des Spreads pro Tag
    spread_delta: Optional[float] = None  # Netto-Delta
    spread_vega: Optional[float] = None   # Netto-Vega

    # Risiko
    max_loss_per_contract: Optional[float] = None  # (Breite - Credit) × 100

    # IV-Kontext
    short_iv: Optional[float] = None
    long_iv: Optional[float] = None


class OptionsChainValidator:
    """Validiert ob ein Bull-Put-Spread echte Marktdaten hat."""

    def __init__(self, quote_provider, options_provider, ibkr_bridge=None):
        """
        Args:
            quote_provider: Tradier/Yahoo Quote-API
            options_provider: Tradier Options-Chain-API
            ibkr_bridge: Optional IBKR-Bridge für Live-Daten
        """
        self.quote_provider = quote_provider
        self.options_provider = options_provider
        self.ibkr = ibkr_bridge
        self._provider_name = "IBKR" if ibkr_bridge else "Tradier"

    async def validate_spread(self, symbol: str) -> SpreadValidation:
        """
        Hauptmethode: Prüft ob für ein Symbol ein handelbarer
        Bull-Put-Spread existiert.

        Ablauf:
        1. Expirations im DTE-Fenster finden
        2. Beste Expiration wählen (~75 DTE)
        3. Puts-Chain abrufen
        4. Short Strike finden (Delta ≈ -0.20)
        5. Long Strike finden (Delta ≈ -0.05)
        6. Credit berechnen (Short Bid - Long Ask)
        7. Credit >= 10% Spread-Breite?
        8. Liquiditäts-Check (OI, Bid-Ask)
        """
        try:
            # 1. Expirations im DTE-Fenster
            expirations = await self._get_valid_expirations(symbol)
            if not expirations:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Keine Expiration im DTE-Fenster {DTE_MIN}-{DTE_MAX}"
                )

            # 2. Beste Expiration (nächste an DTE_OPTIMAL = 75)
            best_exp, best_dte = self._select_optimal_expiration(expirations)

            # 3. Puts-Chain abrufen
            chain = await self._get_puts_chain(symbol, best_exp)
            if not chain:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Options Chain für {best_exp} nicht verfügbar"
                )

            # 4. Short Strike (Delta ≈ -0.20, Toleranz ±0.03)
            short = self._find_strike_by_delta(
                chain,
                target=DELTA_SHORT_TARGET,    # -0.20
                tolerance=DELTA_SHORT_TOLERANCE  # 0.03
            )
            if not short:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Kein Put mit Delta ≈ {DELTA_SHORT_TARGET} gefunden"
                )

            # 5. Long Strike (Delta ≈ -0.05, Toleranz ±0.02)
            long = self._find_strike_by_delta(
                chain,
                target=DELTA_LONG_TARGET,     # -0.05
                tolerance=DELTA_LONG_TOLERANCE  # 0.02
            )
            if not long:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Kein Put mit Delta ≈ {DELTA_LONG_TARGET} gefunden"
                )

            # Sicherstellen: Short Strike > Long Strike
            if short.strike <= long.strike:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Strike-Reihenfolge ungültig: Short {short.strike} <= Long {long.strike}"
                )

            # 6. Credit berechnen
            credit_bid = short.bid - long.ask    # Konservativ
            credit_mid = short.mid - long.mid    # Mittel
            spread_width = short.strike - long.strike

            if credit_bid <= 0:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Negativer Credit: Short Bid {short.bid} - Long Ask {long.ask} = {credit_bid:.2f}"
                )

            # 7. Credit >= 10% Spread-Breite?
            credit_pct = (credit_bid / spread_width) * 100
            min_pct = SPREAD_MIN_CREDIT_PCT  # 10.0

            if credit_pct < min_pct:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Credit {credit_pct:.1f}% < {min_pct}% Minimum "
                           f"(${credit_bid:.2f} auf ${spread_width:.0f} Spread)"
                )

            # 8. Liquiditäts-Check
            warnings = []
            min_oi = ENTRY_OPEN_INTEREST_MIN  # 100

            if short.open_interest < min_oi:
                warnings.append(f"Short OI {short.open_interest} < {min_oi}")
            if long.open_interest < min_oi:
                warnings.append(f"Long OI {long.open_interest} < {min_oi}")

            bid_ask_spread_short = short.ask - short.bid
            if bid_ask_spread_short > 0.20:
                warnings.append(f"Short Bid-Ask ${bid_ask_spread_short:.2f} > $0.20")

            # Spread-Greeks
            spread_theta = short.theta - long.theta  # Positiv = Geld pro Tag
            spread_delta = short.delta - long.delta
            spread_vega = short.vega - long.vega
            max_loss = (spread_width - credit_bid) * 100

            return SpreadValidation(
                tradeable=True,
                warning=len(warnings) > 0,
                reason="; ".join(warnings) if warnings else "Alle Checks bestanden",
                short_leg=short,
                long_leg=long,
                expiration=best_exp,
                dte=best_dte,
                credit_bid=credit_bid,
                credit_mid=credit_mid,
                spread_width=spread_width,
                credit_pct=credit_pct,
                spread_theta=spread_theta,
                spread_delta=spread_delta,
                spread_vega=spread_vega,
                max_loss_per_contract=max_loss,
                short_iv=short.iv,
                long_iv=long.iv,
            )

        except Exception as e:
            logger.error(f"Chain-Validierung für {symbol} fehlgeschlagen: {e}")
            return SpreadValidation(
                tradeable=False,
                reason=f"Fehler: {e}"
            )

    async def _get_valid_expirations(self, symbol: str) -> List[tuple]:
        """Gibt Liste von (expiration_date_str, dte) im gültigen Fenster zurück."""
        # TODO: Implementierung mit options_provider.get_expirations(symbol)
        # Filtern auf DTE_MIN <= dte <= DTE_MAX
        raise NotImplementedError

    def _select_optimal_expiration(self, expirations: List[tuple]) -> tuple:
        """Wählt Expiration am nächsten an DTE_OPTIMAL (75 Tage)."""
        return min(expirations, key=lambda x: abs(x[1] - DTE_OPTIMAL))

    async def _get_puts_chain(self, symbol: str, expiration: str) -> List[OptionLeg]:
        """Ruft Put-Options für Symbol+Expiration ab."""
        # TODO: Implementierung
        # Provider-Kaskade: IBKR → Tradier → Marketdata.app
        raise NotImplementedError

    def _find_strike_by_delta(self, chain: List[OptionLeg],
                               target: float, tolerance: float) -> Optional[OptionLeg]:
        """Findet den Strike mit Delta am nächsten zum Target."""
        candidates = [
            leg for leg in chain
            if abs(leg.delta - target) <= tolerance
        ]
        if not candidates:
            return None
        # Nächster an Target-Delta
        return min(candidates, key=lambda x: abs(x.delta - target))
```

**Hinweis zu Konstanten:** Prüfe ob folgende Konstanten in `trading_rules.py` existieren.
Falls nicht, anlegen mit diesen Werten:

```python
# Delta-Targets (PLAYBOOK §2)
DELTA_SHORT_TARGET = -0.20
DELTA_SHORT_TOLERANCE = 0.03
DELTA_LONG_TARGET = -0.05
DELTA_LONG_TOLERANCE = 0.02

# DTE (PLAYBOOK §2)
DTE_MIN = 60
DTE_MAX = 90
DTE_OPTIMAL = 75

# Credit (PLAYBOOK §2)
SPREAD_MIN_CREDIT_PCT = 10.0

# Liquidität (PLAYBOOK §1)
ENTRY_OPEN_INTEREST_MIN = 100
ENTRY_VOLUME_MIN = 500_000
ENTRY_PRICE_MIN = 20
ENTRY_PRICE_MAX = 1500
```

**Akzeptanzkriterium:**
```python
validator = OptionsChainValidator(quote_provider, options_provider)
result = await validator.validate_spread("AAPL")
assert result.tradeable == True
assert result.credit_bid > 0
assert result.credit_pct >= 10.0
assert result.short_leg.delta >= -0.23  # Innerhalb Toleranz
assert result.short_leg.delta <= -0.17
assert result.long_leg.open_interest >= 100
```

---

### Task 2.2: Provider-Integration für Options Chain

**Ziel:** Tradier und IBKR als Datenquellen für die Chain anbinden.

**Bestehende Provider prüfen:**
```bash
ls src/data_providers/
# Erwartung: tradier.py, ibkr_bridge.py oder ähnlich
```

**Schritte:**

1. Prüfen welche Chain-Methoden bereits existieren:
   ```bash
   grep -rn "get_options\|options_chain\|get_chain\|get_expirations" src/ --include="*.py"
   ```

2. Die `_get_valid_expirations()` und `_get_puts_chain()` Methoden implementieren,
   indem bestehende Provider genutzt werden.

3. Provider-Kaskade:
   ```python
   async def _get_puts_chain(self, symbol, expiration):
       # 1. IBKR (wenn verbunden)
       if self.ibkr and self.ibkr.is_connected():
           try:
               return await self._chain_from_ibkr(symbol, expiration)
           except Exception as e:
               logger.warning(f"IBKR Chain fehlgeschlagen: {e}, Fallback auf Tradier")

       # 2. Tradier
       return await self._chain_from_tradier(symbol, expiration)
   ```

4. Chain-Daten in `OptionLeg` Dataclass konvertieren (Mapping von Provider-Format).

**Akzeptanzkriterium:**
```python
# Chain enthält echte Daten
chain = await validator._get_puts_chain("MSFT", "2026-04-17")
assert len(chain) > 10  # Mehrere Strikes
assert all(leg.bid >= 0 for leg in chain)
assert all(leg.open_interest >= 0 for leg in chain)
assert all(leg.delta < 0 for leg in chain)  # Puts haben negative Deltas
```

---

### Task 2.3: Scanner-Pipeline umbauen (Chain-First)

**Ziel:** Scanner nutzt OptionsChainValidator nach dem Score-Ranking.

**Datei:** `src/scanner/multi_strategy_scanner.py`
**Datei:** `src/handlers/daily_picks.py` (oder wo `optionplay_daily_picks` implementiert ist)

**Aktuelle Pipeline:**
```
filter_symbols → analyze_all → score → recommend_strikes → output
```

**Neue Pipeline:**
```
filter_symbols → analyze_top_30 → score → sort_top_15
→ validate_chain (NEU) → nur tradeable weiter → output mit echten Daten
```

**Schritte:**

1. In der Daily-Picks-Logik nach dem Scoring:
   ```python
   # Nach Score-Ranking: Top 15 Kandidaten
   top_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)[:15]

   # NEU: Chain-Validierung für Top 15
   chain_validator = OptionsChainValidator(quote_provider, options_provider, ibkr)

   validated = []
   for candidate in top_candidates:
       spread = await chain_validator.validate_spread(candidate.symbol)
       if spread.tradeable:
           candidate.spread = spread  # Echte Daten anhängen
           validated.append(candidate)
       else:
           logger.info(f"{candidate.symbol}: Nicht handelbar — {spread.reason}")

   # Nur validierte Picks ausgeben
   return validated[:max_picks]
   ```

2. Output-Format erweitern um echte Spread-Daten (siehe Task 4.1).

**Akzeptanzkriterium:**
```
# Daily Picks gibt nur noch Symbole mit echtem Spread aus
# Jeder Pick hat: credit_bid, credit_mid, spread_width, OI, Bid-Ask
```

---

## PHASE 3: Entry Quality Score

### Task 3.1: IV Rank + IV Percentile berechnen

**Ziel:** Beide IV-Metriken verfügbar machen — sie messen verschiedene Dinge.

**Erklärung:**
- **IV Rank:** Wo steht die aktuelle IV im 52-Wochen-Range? `(IV - 52w_Low) / (52w_High - 52w_Low)`
  → Sagt: "Die IV ist bei 60% ihres Jahres-Ranges" — aber nicht wie oft sie dort war.
- **IV Percentile:** An wieviel % der Handelstage war die IV NIEDRIGER als heute?
  → Sagt: "Die IV war an 75% aller Tage im letzten Jahr niedriger als heute"

**Warum beides:** Ein Symbol kann IV Rank 50% haben (Mitte des Ranges), aber IV Percentile 90%
(die IV war fast nie so hoch). Das passiert wenn es einen einzelnen Spike gab der den Range
aufgeblasen hat. Percentile ist robuster gegen Ausreißer.

**Berechnung aus lokaler DB:**

```python
"""
IV Rank + IV Percentile aus historischen Daten.
Quelle: options_greeks Tabelle, 252 Handelstage.
"""

async def calculate_iv_metrics(self, symbol: str) -> dict:
    """
    Berechnet IV Rank und IV Percentile für ein Symbol.

    Nutzt ATM-Optionen (Delta ≈ -0.50 für Puts) der letzten 252 Tage.
    """
    query = """
        SELECT g.iv_calculated, p.quote_date
        FROM options_greeks g
        JOIN options_prices p ON g.options_price_id = p.id
        WHERE p.underlying = ?
          AND p.option_type = 'put'
          AND g.delta BETWEEN -0.55 AND -0.45  -- ATM-Puts
          AND p.dte BETWEEN 25 AND 35           -- ~30 DTE für Vergleichbarkeit
          AND p.quote_date >= date('now', '-365 days')
        ORDER BY p.quote_date
    """
    # Tages-Durchschnitt berechnen (mehrere Strikes pro Tag)
    # → daily_iv: Liste von (date, avg_iv)

    if len(daily_iv) < 30:
        return {"iv_rank": None, "iv_percentile": None, "reason": "Zu wenig Daten"}

    current_iv = daily_iv[-1]  # Letzte verfügbare IV
    iv_values = [iv for _, iv in daily_iv]

    # IV Rank
    iv_52w_high = max(iv_values)
    iv_52w_low = min(iv_values)
    if iv_52w_high == iv_52w_low:
        iv_rank = 50.0
    else:
        iv_rank = ((current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low)) * 100

    # IV Percentile
    days_below = sum(1 for iv in iv_values if iv < current_iv)
    iv_percentile = (days_below / len(iv_values)) * 100

    return {
        "iv_rank": round(iv_rank, 1),
        "iv_percentile": round(iv_percentile, 1),
        "current_iv": round(current_iv * 100, 1),  # In Prozent
        "iv_52w_high": round(iv_52w_high * 100, 1),
        "iv_52w_low": round(iv_52w_low * 100, 1),
        "data_points": len(iv_values),
    }
```

**Datenquelle-Fallback:**
1. Lokale DB (options_greeks) — 252 Tage historisch verfügbar
2. Marketdata.app API — liefert IV Rank direkt (solange Abo aktiv)
3. Tradier — liefert aktuelle IV, historisch begrenzt

**Prüfen:** Existiert bereits eine IV-Rank-Berechnung?
```bash
grep -rn "iv_rank\|iv_percentile\|IVRank\|iv_calculated" src/ --include="*.py"
```

Wenn `symbol_fundamentals.iv_rank_252d` existiert, nutzen und um Percentile ergänzen.

**Neue Datei:** `src/services/iv_analyzer.py` (oder in bestehenden Service integrieren)

**Akzeptanzkriterium:**
```python
metrics = await iv_analyzer.calculate_iv_metrics("AAPL")
assert 0 <= metrics["iv_rank"] <= 100
assert 0 <= metrics["iv_percentile"] <= 100
# IV Rank und Percentile können deutlich voneinander abweichen
```

---

### Task 3.2: Entry Quality Score (EQS) implementieren

**Ziel:** Numerischer Score der Entry-Timing-Qualität bewertet.

**Neue Datei:** `src/services/entry_quality_scorer.py`

```python
"""
Entry Quality Score (EQS) — bewertet wie günstig der Einstiegszeitpunkt ist.

Der EQS ersetzt den Signal Score NICHT. Er gibt einen Bonus von bis zu 30%:
  Ranking Score = Signal Score × (1 + EQS_normalized × 0.3)

Optimiert auf Capital Efficiency, NICHT auf Speed-to-50%.
(Speed Score wurde getestet und verworfen — arbeitet gegen Profit.)
"""

@dataclass
class EntryQuality:
    """Bewertung der Entry-Qualität."""
    eqs_total: float          # 0-100
    eqs_normalized: float     # 0.0-1.0

    # Einzelfaktoren (0-100 jeweils)
    iv_rank_score: float
    iv_percentile_score: float
    credit_ratio_score: float
    theta_efficiency_score: float
    pullback_score: float
    rsi_score: float
    trend_score: float

    # Rohdaten
    iv_rank: Optional[float]
    iv_percentile: Optional[float]
    credit_pct: Optional[float]
    theta_per_day: Optional[float]
    pullback_pct: Optional[float]
    rsi: Optional[float]


class EntryQualityScorer:
    """Bewertet Entry-Timing-Qualität basierend auf IV, Momentum, Technicals."""

    # Gewichtung der Faktoren
    WEIGHTS = {
        "iv_rank":          0.20,  # IV Range-Position
        "iv_percentile":    0.15,  # IV Häufigkeitsverteilung
        "credit_ratio":     0.20,  # Credit / Spread-Breite
        "theta_efficiency": 0.15,  # Theta / Credit Verhältnis
        "pullback":         0.15,  # Pullback-Tiefe
        "rsi":              0.10,  # RSI(14) Niveau
        "trend":            0.05,  # Trend-Alignment
    }

    def score(self, iv_rank, iv_percentile, credit_pct,
              spread_theta, credit_bid, pullback_pct, rsi, trend_bullish) -> EntryQuality:
        """
        Berechnet den Entry Quality Score.

        Args:
            iv_rank: IV Rank 0-100 (None wenn nicht verfügbar)
            iv_percentile: IV Percentile 0-100 (None wenn nicht verfügbar)
            credit_pct: Credit als % der Spread-Breite
            spread_theta: Täglicher Theta des Spreads in $
            credit_bid: Absolute Credit in $ (Bid)
            pullback_pct: Abstand zum 52w-High in % (negativ, z.B. -4.2)
            rsi: RSI(14) Wert (0-100)
            trend_bullish: True wenn SMA20 > SMA50 > SMA200
        """
        scores = {}

        # --- IV Rank Score ---
        # Sweet Spot: 40-65% → höchstes IV-Crush-Potenzial
        # Unter 20%: Zu wenig Premium
        # Über 80%: Warnung (Event-Risiko?)
        if iv_rank is not None:
            if iv_rank < 20:
                scores["iv_rank"] = iv_rank * 2.5     # 0-50
            elif 20 <= iv_rank < 40:
                scores["iv_rank"] = 50 + (iv_rank - 20) * 1.5  # 50-80
            elif 40 <= iv_rank <= 65:
                scores["iv_rank"] = 80 + (iv_rank - 40) * 0.8  # 80-100 ← Sweet Spot
            elif 65 < iv_rank <= 80:
                scores["iv_rank"] = 100 - (iv_rank - 65) * 1.3  # 100→80
            else:
                scores["iv_rank"] = max(30, 80 - (iv_rank - 80))  # 80→30
        else:
            scores["iv_rank"] = 50  # Neutral wenn nicht verfügbar

        # --- IV Percentile Score ---
        # Hohes Percentile (>50%) = IV ist häufiger niedriger = guter Entry
        # Percentile 60-80% ist ideal
        if iv_percentile is not None:
            if iv_percentile < 30:
                scores["iv_percentile"] = iv_percentile * 1.0  # 0-30
            elif 30 <= iv_percentile < 50:
                scores["iv_percentile"] = 30 + (iv_percentile - 30) * 2.0  # 30-70
            elif 50 <= iv_percentile <= 80:
                scores["iv_percentile"] = 70 + (iv_percentile - 50) * 1.0  # 70-100 ← Sweet Spot
            else:
                scores["iv_percentile"] = max(50, 100 - (iv_percentile - 80) * 1.5)
        else:
            scores["iv_percentile"] = 50

        # --- Credit Ratio Score ---
        # Minimum 10% (PLAYBOOK). Mehr ist besser, aber mit abnehmendem Grenznutzen
        if credit_pct is not None:
            if credit_pct < 10:
                scores["credit_ratio"] = 0  # Unter Minimum
            elif credit_pct < 15:
                scores["credit_ratio"] = (credit_pct - 10) * 12  # 0-60
            elif credit_pct < 25:
                scores["credit_ratio"] = 60 + (credit_pct - 15) * 4  # 60-100
            else:
                scores["credit_ratio"] = 100  # Cap
        else:
            scores["credit_ratio"] = 0

        # --- Theta Efficiency Score ---
        # Theta pro Tag / Credit → wie schnell decayed der Spread relativ zum Credit?
        # Höher = schnellerer relativer Decay
        if spread_theta and credit_bid and credit_bid > 0:
            theta_ratio = abs(spread_theta) / credit_bid * 100  # In %
            # ~2-5% pro Tag ist typisch
            scores["theta_efficiency"] = min(100, theta_ratio * 25)
        else:
            scores["theta_efficiency"] = 50

        # --- Pullback Score ---
        # Tiefer Dip = besserer Entry (Mean Reversion)
        # -2% bis -8% ist Sweet Spot, tiefer als -10% ist Warnung
        if pullback_pct is not None:
            depth = abs(pullback_pct)
            if depth < 1:
                scores["pullback"] = 20      # Kaum Pullback
            elif 1 <= depth < 3:
                scores["pullback"] = 20 + (depth - 1) * 20  # 20-60
            elif 3 <= depth <= 8:
                scores["pullback"] = 60 + (depth - 3) * 8   # 60-100 ← Sweet Spot
            elif 8 < depth <= 12:
                scores["pullback"] = 100 - (depth - 8) * 10  # 100-60
            else:
                scores["pullback"] = 30      # Zu tief, Warnung
        else:
            scores["pullback"] = 50

        # --- RSI Score ---
        # Überverkauft (<35) ist gut für Bull-Put (Bounce wahrscheinlich)
        if rsi is not None:
            if rsi < 25:
                scores["rsi"] = 100    # Stark überverkauft
            elif rsi < 35:
                scores["rsi"] = 70 + (35 - rsi) * 3  # 70-100
            elif rsi < 50:
                scores["rsi"] = 40 + (50 - rsi) * 2  # 40-70
            elif rsi < 70:
                scores["rsi"] = 40     # Neutral
            else:
                scores["rsi"] = 20     # Überkauft — weniger ideal
        else:
            scores["rsi"] = 50

        # --- Trend Score ---
        scores["trend"] = 100 if trend_bullish else 30

        # --- Gewichteter Gesamtscore ---
        eqs_total = sum(
            scores[factor] * weight
            for factor, weight in self.WEIGHTS.items()
        )
        eqs_normalized = eqs_total / 100.0  # 0.0-1.0

        return EntryQuality(
            eqs_total=round(eqs_total, 1),
            eqs_normalized=round(eqs_normalized, 3),
            iv_rank_score=round(scores["iv_rank"], 1),
            iv_percentile_score=round(scores["iv_percentile"], 1),
            credit_ratio_score=round(scores["credit_ratio"], 1),
            theta_efficiency_score=round(scores["theta_efficiency"], 1),
            pullback_score=round(scores["pullback"], 1),
            rsi_score=round(scores["rsi"], 1),
            trend_score=round(scores["trend"], 1),
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            credit_pct=credit_pct,
            theta_per_day=spread_theta,
            pullback_pct=pullback_pct,
            rsi=rsi,
        )
```

**Integration ins Ranking:**

```python
# In Daily Picks, nach Chain-Validierung:
for candidate in validated_candidates:
    eq = entry_scorer.score(
        iv_rank=candidate.iv_metrics["iv_rank"],
        iv_percentile=candidate.iv_metrics["iv_percentile"],
        credit_pct=candidate.spread.credit_pct,
        spread_theta=candidate.spread.spread_theta,
        credit_bid=candidate.spread.credit_bid,
        pullback_pct=candidate.technicals.pullback_pct,
        rsi=candidate.technicals.rsi,
        trend_bullish=candidate.technicals.trend_bullish,
    )
    candidate.entry_quality = eq

    # Combined Ranking: Signal Score + EQS Bonus (max 30%)
    candidate.ranking_score = candidate.signal_score * (1 + eq.eqs_normalized * 0.3)
```

**Akzeptanzkriterium:**
```python
scorer = EntryQualityScorer()
eq = scorer.score(
    iv_rank=55, iv_percentile=68,
    credit_pct=18.5, spread_theta=0.042, credit_bid=1.85,
    pullback_pct=-4.2, rsi=32, trend_bullish=True
)
assert 0 <= eq.eqs_total <= 100
assert eq.iv_percentile_score > 50   # Percentile 68% ist gut
assert eq.rsi_score > 70            # RSI 32 ist überverkauft → gut
assert eq.credit_ratio_score > 60   # 18.5% ist deutlich über 10%
```

---

### Task 3.3: Walk-Forward-Backtest für EQS-Kalibrierung

**Ziel:** Validieren dass EQS die Capital Efficiency tatsächlich verbessert.

**Datenquelle:** `~/.optionplay/outcomes.db` — 17.438 Trades

**Wichtig:** Diese Tabelle hat (nach dem früheren Feature) eine `days_to_50pct` Spalte.
Falls nicht vorhanden, muss sie zuerst berechnet werden (siehe früheres Gespräch).

```bash
# Prüfen ob Spalte existiert:
sqlite3 ~/.optionplay/outcomes.db ".schema trade_outcomes" | grep days_to_50
```

**Backtest-Logik:**

```python
"""
Walk-Forward-Backtest: EQS Ranking vs. Signal-Score-Only Ranking

Split:
  Train: 2021-01 bis 2023-12
  Test:  2024-01 bis 2026-01

Vergleich:
  A) Ranking nur nach Signal Score (Baseline)
  B) Ranking nach Signal Score × (1 + EQS × 0.3)

Metriken:
  - Win Rate (%)
  - Avg Capital Efficiency (Profit / Max_Risk / Haltezeit)
  - Avg P&L pro Trade ($)
  - Max Drawdown Serie
"""
```

**Akzeptanzkriterium:**
- EQS-Ranking hat mindestens gleiche Win Rate wie Baseline
- Capital Efficiency ist messbar besser (>5% Verbesserung)
- Kein Overfitting: Test-Periode zeigt ähnliche Verbesserung wie Train

---

## PHASE 4: Ausgabe & Compliance

### Task 4.1: Daily Picks Output-Format

**Ziel:** Jeder Pick zeigt alle Informationen die ein Trader für die Entscheidung braucht.

**Datei:** Wo immer `optionplay_daily_picks` das Markdown generiert.
Wahrscheinlich `src/handlers/daily_picks.py` oder `src/formatters/`.

```bash
grep -rn "daily_picks\|Daily Picks\|optionplay_daily_picks" src/ --include="*.py"
```

**Neues Output-Format pro Pick:**

```markdown
## #1 — MSFT · Pullback · Score 8.2 · EQS 74

| | Short Put | Long Put |
|---|----------|---------|
| Strike | $390 | $380 |
| Delta | -0.19 | -0.06 |
| IV | 28.3% | 24.1% |
| OI | 2,847 | 1,203 |
| Bid/Ask | $3.40/$3.65 | $1.55/$1.70 |

**Spread:** $10.00 breit | **Expiry:** 2026-04-17 (72 DTE)
**Credit:** $1.85 (Bid) — $2.10 (Mid) | **Credit/Breite:** 18.5% ✅
**Max Loss:** $815/Kontrakt | **50% Target:** $0.93 | **200% Stop:** $3.70

**Entry-Qualität:**
IV Rank 62% · IV Pctl 75% · RSI 32 (überverkauft) · Pullback -4.2%
Theta $0.042/d · Trend bullish · Earnings 82d ✅ · Vol 34.2M ✅

**Checkliste:** ✅ BL ✅ Stab(83) ✅ Earn(82d) ✅ VIX(<30)
✅ Preis($392) ✅ Vol(34M) ✅ DTE(72) ✅ Delta ✅ Credit(18.5%)
```

**Header des Reports:**

```markdown
# Daily Picks — 2026-02-04

**Regime:** Normal (VIX 16.36) | **Slots frei:** 7/10 | **Heute:** 0/2 Trades

---
```

**Datenquellen für die einzelnen Felder:**

| Feld | Quelle |
|------|--------|
| Strike, Delta, IV, OI, Bid/Ask | `SpreadValidation` (Task 2.1) |
| Credit Bid/Mid, Spread-Breite | `SpreadValidation` (Task 2.1) |
| Max Loss, Profit Target, Stop | Berechnung aus Credit + Spread |
| IV Rank, IV Percentile | `IVAnalyzer` (Task 3.1) |
| RSI, Pullback, Trend | Bestehende technische Analyse |
| Earnings-Abstand | Bestehender Earnings-Check |
| Volume | Quote-API (Task 1.3) |
| VIX, Regime, Slots | Bestehende VIX/Portfolio-Logik |
| Score, EQS | Signal Score + Entry Quality (Task 3.2) |
| Checkliste | PLAYBOOK-Regeln gegen echte Daten |

---

### Task 4.2: Portfolio-Constraints mit VIX-Regime verbinden (PB-004)

**Problem:** Feste Limits, keine VIX-Abhängigkeit.

**Datei:** `src/services/portfolio_constraints.py`
**Daten:** `src/constants/trading_rules.py` — `VIXRegimeRules` (existiert bereits, Zeile 140-201)

**Schritte:**

1. Aktuelle hardcodierte Werte durch dynamische VIX-Abfrage ersetzen:
   ```python
   # ALT:
   max_positions: int = 5
   max_per_sector: int = 2

   # NEU:
   def get_position_limits(self) -> dict:
       """Gibt VIX-abhängige Limits zurück."""
       from src.constants.trading_rules import get_regime_rules
       vix = self._get_current_vix()
       rules = get_regime_rules(vix)
       return {
           "max_positions": rules.max_positions,     # 10/5/3/0
           "max_per_sector": rules.max_per_sector,   # 2/1/1/0
           "max_risk_per_trade": rules.max_risk_pct, # 2%/1.5%/1%/0%
       }
   ```

2. Prüfen ob `get_regime_rules()` in `trading_rules.py` existiert:
   ```bash
   grep -rn "get_regime_rules\|VIXRegimeRules" src/constants/trading_rules.py
   ```

3. Falls nicht: Funktion erstellen die basierend auf VIX-Level die Regime-Parameter zurückgibt.

**PLAYBOOK §5 — VIX-Adjustierung:**

| VIX | Max Positionen | Max/Sektor | Risiko/Trade |
|-----|---------------|-----------|-------------|
| < 20 | 10 | 2 | 2% |
| 20-25 | 5 | 1 | 1.5% |
| 25-30 | 3 | 1 | 1% |
| > 30 | 0 | 0 | 0% |

**Akzeptanzkriterium:**
```python
# Bei VIX 22 → Danger Zone Limits
constraints = PortfolioConstraints()
limits = constraints.get_position_limits()  # VIX = 22
assert limits["max_positions"] == 5
assert limits["max_per_sector"] == 1
```

---

### Task 4.3: Roll-Validierung vervollständigen (PB-008)

**Datei:** `src/services/position_monitor.py` — `_can_roll()` ca. Zeile 581-617

**Aktuell implementiert:**
- ✅ VIX < 30
- ✅ Earnings im neuen Fenster
- ✅ Position profitabel/Break-Even

**Fehlt:**
- ❌ Symbol besteht alle Entry-Filter (Re-Validierung)
- ❌ Neuer Credit >= 10% Spread-Breite

**Schritte:**

1. TradeValidator für Re-Validierung aufrufen:
   ```python
   async def _can_roll(self, position):
       # Bestehende Checks...

       # NEU: Entry-Filter Re-Validierung
       validation = await self.trade_validator.validate_trade(position.symbol)
       if validation.decision == TradeDecision.NO_GO:
           return False, f"Symbol besteht Entry-Filter nicht mehr: {validation.reason}"

       # NEU: Credit-Check für neues Expiration
       new_spread = await self.chain_validator.validate_spread(position.symbol)
       if not new_spread.tradeable:
           return False, f"Kein handelbarer Spread: {new_spread.reason}"
       if new_spread.credit_pct < SPREAD_MIN_CREDIT_PCT:
           return False, f"Neuer Credit {new_spread.credit_pct:.1f}% < {SPREAD_MIN_CREDIT_PCT}%"

       return True, "Roll möglich"
   ```

**Akzeptanzkriterium:**
- Roll wird abgelehnt wenn Symbol Stability < 70 hat
- Roll wird abgelehnt wenn neuer Credit < 10% Spread-Breite

---

## Anhang: Marketdata.app Ablösung prüfen

**Wann:** Ende Phase 2 (Woche 2)
**Frage:** Welche Daten kommen exklusiv von Marketdata.app?

**Prüfung:**
```bash
grep -rn "marketdata\|Marketdata\|MARKETDATA" src/ --include="*.py"
```

**Erwartung:**
- IV Rank → Kann aus lokaler DB berechnet werden (Task 3.1)
- IV Percentile → Kann aus lokaler DB berechnet werden (Task 3.1)
- Options Chain → Tradier ist primär
- Greeks → Tradier liefert Greeks in der Chain

**Entscheidung:** Wenn Tradier + lokale Berechnung alle benötigten Daten liefern,
kann Marketdata.app gekündigt werden. Sonst: prüfen welche spezifischen Daten
fehlen und ob sie anders beschafft werden können.

---

## Zusammenfassung: Reihenfolge

```
Phase 1 (Woche 1):
  1.1 Konstanten-Widersprüche          ← ZUERST (Basis für alles)
  1.2 Blacklist vereinheitlichen        ← Schneller Fix
  1.3 Volume-Check aktivieren           ← API-Integration nötig
  1.4 Preis-Filter im Scanner           ← Einfacher Filter
  1.5 Bare Exceptions                   ← Hygiene

Phase 2 (Woche 2):
  2.1 OptionsChainValidator Service     ← Kern-Feature
  2.2 Provider-Integration              ← Tradier + IBKR anbinden
  2.3 Scanner-Pipeline umbauen          ← Chain-First

  → Marketdata.app Ablösung prüfen

Phase 3 (Woche 3):
  3.1 IV Rank + IV Percentile           ← Beide Metriken
  3.2 Entry Quality Score               ← EQS implementieren
  3.3 Walk-Forward-Backtest             ← Kalibrierung + Validierung

Phase 4 (Woche 4):
  4.1 Output-Format redesignen          ← Alle Daten darstellen
  4.2 Portfolio-Constraints + VIX       ← PLAYBOOK-Compliance
  4.3 Roll-Validierung                  ← Vervollständigen
```
