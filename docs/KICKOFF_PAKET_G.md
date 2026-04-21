# Paket G — Quick-Win Exit-Verbesserungen
**Kontext:** E.2b abgeschlossen, PR #3 auf main gemergt. 5914 Tests.
Referenz: `docs/christian/CHRISTIAN_FULL_CODE_ANALYSE.md` (Sektion 2)

---

## Motivation

OptionPlays Exit-Logik ist rudimentär: +50% Profit, -50% Stop. Christians
System hat drei zeitlich gestaffelte Exit-Schichten plus Signal-basierte
Exits. Der Gamma-Zone-Stop allein verhindert geschätzt 30% der grossen
Verluste, weil Gamma in den letzten 3 Wochen vor Expiry explodiert.

---

## Scope

4 Phasen, jeweils klein. Kann in 1-2 Code-Chat-Sessions implementiert
werden.

### G.1 — Gamma-Zone Stop

**Regel:** DTE < 21 UND Verlust > 30% → Exit-Empfehlung.

Hintergrund: Bei DTE < 21 steigt Gamma stark an. Ein Spread der bei
DTE 18 bereits -30% im Minus ist, wird mit hoher Wahrscheinlichkeit
-100%. Der normale -50% Stop greift zu spät.

Christians Config:
```python
GAMMA_ZONE_DTE      = 21
GAMMA_ZONE_LOSS_PCT = 30
```

**Implementation:**

Prüfen wo die bestehende Exit-Logik lebt (vermutlich in einem Monitor-
oder Validator-Service). Dort eine zusätzliche Bedingung einfügen:

```python
# Bestehendes Stop-Loss (bleibt):
if pnl_pct <= -50:
    recommend_exit("STOP_LOSS")

# NEU: Gamma-Zone Stop
dte_remaining = (expiry_date - today).days
if dte_remaining < 21 and pnl_pct <= -30:
    recommend_exit("GAMMA_ZONE_STOP")
```

Die Schwellen (21 Tage, 30%) in `config/trading.yaml`:

```yaml
exit_rules:
  gamma_zone:
    dte_threshold: 21
    loss_pct_threshold: 30
```

### G.2 — Time-Stop

**Regel:** Haltedauer > 25 Tage UND Verlust > 20% → Exit-Empfehlung.

Verhindert "Hope-Holding". Eine Position die nach 25 Tagen noch im
Minus ist, wird wahrscheinlich nicht mehr profitabel.

Christians Config:
```python
TIME_STOP_DAYS     = 25
TIME_STOP_LOSS_PCT = 20
```

**Implementation:**

```python
days_held = (today - entry_date).days
if days_held > 25 and pnl_pct <= -20:
    recommend_exit("TIME_STOP")
```

Config:
```yaml
exit_rules:
  time_stop:
    days_threshold: 25
    loss_pct_threshold: 20
```

### G.3 — RRG-basierter Exit

Nutzt die Dual-RRG-Infrastruktur aus E.1 für Exit-Empfehlungen.
Zwei Stufen:

**Warnung:** Stock wandert von LEADING → WEAKENING
```
⚠️ RRG ROTATION: {TICKER} LEADING → WEAKENING
Kapitalfluss dreht — relative Stärke schwindet
Position beobachten
```

**Exit-Empfehlung:** Stock in LAGGING
```
🔴 EXIT: {TICKER} → LAGGING
Aktie verliert Stärke vs. SPY
Schliessen empfohlen
```

**Implementation:**

Braucht den Entry-Quadranten (bei Trade-Eröffnung speichern) und den
aktuellen Quadranten (aus SectorRS-Service).

```python
entry_quadrant = trade.get("rrg_quadrant_at_entry", "UNKNOWN")
current = sector_rs.get_stock_rs(symbol).quadrant

if entry_quadrant == "LEADING" and current == "WEAKENING":
    warn("RRG_ROTATION_WARNING")
elif current == "LAGGING":
    recommend_exit("RRG_LAGGING_EXIT")
```

Prüfen ob der Entry-Quadrant aktuell gespeichert wird. Falls nicht,
Feld zum Trade-Record hinzufügen.

### G.4 — Macro-Kalender Warnung

FOMC, CPI und NFP Termine für 2026. Einen Tag vorher Alert:

```
📅 MACRO MORGEN: FOMC
Erhöhtes Gap-Risiko für alle offenen Positionen.
```

**Implementation:**

Statische Liste in Config oder als Python-Dict:

```python
MACRO_EVENTS_2026 = {
    "FOMC": ["2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
             "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17"],
    "CPI":  ["2026-01-15", "2026-02-12", "2026-03-12", "2026-04-10",
             "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-12",
             "2026-09-11", "2026-10-14", "2026-11-12", "2026-12-10"],
    "NFP":  ["2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
             "2026-05-08", "2026-06-05", "2026-07-09", "2026-08-07",
             "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"],
}
```

Einmal pro Tag prüfen ob morgen ein Event ist. In den Telegram-
Notifier integrieren.

---

## Vorarbeit: Bestehende Exit-Logik finden

Vor dem Implementieren muss der Code-Chat die bestehende Exit-Architektur
verstehen:

```bash
cd ~/OptionPlay
# Wo lebt die Exit-Logik?
grep -rn "exit\|stop_loss\|profit_target\|close_position" \
  src/services/ src/scanner/ --include="*.py" | head -30

# Wo werden offene Trades geprüft?
grep -rn "open_trades\|check_positions\|monitor" \
  src/services/ src/scanner/ --include="*.py" | head -20

# Telegram-Notifier
grep -rn "class.*Notifier\|def send\|def notify" \
  src/ --include="*.py" | head -15

# Trade-Record-Felder
grep -rn "class.*Trade\|entry_date\|expiry\|dte\|pnl" \
  src/models/ src/services/ --include="*.py" | head -20
```

Basierend auf dem Output entscheiden wo G.1-G.4 eingebaut werden.

---

## Tests

**G.1 Gamma-Zone (4 Tests):**
- DTE 18, Verlust -35% → Exit empfohlen
- DTE 18, Verlust -25% → kein Exit (unter Schwelle)
- DTE 25, Verlust -35% → kein Exit (über DTE-Schwelle)
- DTE 5, Verlust -10% → kein Exit (kein Verlust)

**G.2 Time-Stop (4 Tests):**
- 30 Tage gehalten, -25% → Exit empfohlen
- 30 Tage gehalten, -15% → kein Exit
- 20 Tage gehalten, -25% → kein Exit (zu früh)
- 30 Tage gehalten, +10% → kein Exit (im Gewinn)

**G.3 RRG-Exit (4 Tests):**
- Entry LEADING, jetzt WEAKENING → Warnung
- Entry LEADING, jetzt LAGGING → Exit
- Entry IMPROVING, jetzt LAGGING → Exit
- Entry IMPROVING, jetzt LEADING → kein Exit (verbessert)

**G.4 Macro-Kalender (3 Tests):**
- Morgen ist FOMC → Alert
- Heute ist FOMC → kein Alert (zu spät)
- Morgen ist normaler Tag → kein Alert

Mindestens 15 Tests.

---

## Branch-Strategie

```bash
git checkout main
git pull origin main
git checkout -b feature/g-exit-improvements
```

Alle 4 Phasen auf einem Branch, ein Merge nach main.

---

## Akzeptanzkriterien

1. Gamma-Zone-Stop feuert bei DTE < 21 + Verlust > 30%
2. Time-Stop feuert bei 25+ Tage + Verlust > 20%
3. RRG-Exit unterscheidet Warnung (WEAKENING) von Exit (LAGGING)
4. Macro-Kalender erkennt Events einen Tag vorher
5. Alle Schwellen in YAML konfigurierbar
6. Bestehende Exit-Logik (+50%/-50%) unverändert
7. Mindestens 15 neue Tests
8. Gesamtsuite grün
9. `docs/results/G_RESULT.md` erstellt

---

## Standing Rules

- Kein Auto-Trading, nur Empfehlungen
- Deutsche Doku, englische Code-Kommentare
- Keine Breaking Changes
- Anti-AI-Schreibstil
