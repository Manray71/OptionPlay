# Paket E.5 — Telegram: Composite-Scores + Breakout-Signals
**Kontext:** E.2b (Multi-Faktor Composite) und Paket G (Exits) abgeschlossen.
AlphaScorer liefert `AlphaCandidate` mit `b_composite`, `f_composite`,
`breakout_signals`, `pre_breakout`. Exit-Regeln mit Gamma-Zone, Time-Stop,
RRG-Exit und Macro-Kalender aktiv.

---

## Motivation

Die neuen Composite-Scores und Breakout-Signale werden berechnet, sind
aber im Telegram-Output nicht sichtbar. Der tägliche Scan zeigt noch
das alte Format. Ohne Telegram-Integration siehst du die Daten nicht
im Alltag.

---

## Branch

```bash
cd ~/OptionPlay
git checkout main && git pull
git checkout -b feature/e5-telegram-composite
```

---

## Vorarbeit: Bestehende Telegram-Architektur verstehen

```bash
cd ~/OptionPlay

# Wo lebt der Telegram-Bot / Notifier?
grep -rn "class.*Bot\|class.*Notifier\|def send\|telegram" \
  src/ --include="*.py" | head -20

# Wie wird der Scan-Output formatiert?
grep -rn "format_scan\|format_pick\|format_top\|def format" \
  src/ --include="*.py" | head -20

# Welche Felder werden aktuell angezeigt?
grep -rn "ticker\|score\|strike\|credit\|dte\|quadrant" \
  src/formatters/ --include="*.py" | head -30

# MCP-Handler für /scan und /top15
grep -rn "scan\|top15\|daily_picks" \
  src/mcp/ --include="*.py" | head -15
```

Basierend auf dem Output entscheiden wo die neuen Felder eingebaut werden.

---

## Scope E.5

### E.5.1 — Scan-Output: Composite-Details im Pick-Format

Aktuell zeigt ein Pick vermutlich sowas wie:
```
🟢 NVDA | Score 87 | $125/$115P | $1.85 | 32 DTE
IV 45 | RSI 52 | RRG IMPROVING
```

Neu: B+F Aufschlüsselung + aktive Breakout-Signals:
```
🟢 NVDA | 187 (B:72 + F:77×1.5) | $125/$115P | $1.85 | 32 DTE
IV 45 | RSI 52 | RRG IMP→LEAD
🚩⚡ BREAKOUT IMMINENT | 📊 VWAP Reclaim
```

**Felder die dazukommen:**
- `B:XX + F:XX×1.5` (Composite-Aufschlüsselung)
- Dual-RRG Kurzformat: `IMP→LEAD` (Classic→Fast)
- Breakout-Signal-Icons (aus `breakout_signals` Tuple)
- PRE-BREAKOUT Flag wenn aktiv

**Signal-Icons (aus Christians SIGNAL_ICONS):**
```
🚩⚡  BREAKOUT IMMINENT
🎯    PRE-BREAKOUT
📊    VWAP Reclaim
📈    3-Bar Play
⚙️↑   BB Squeeze released
🚩    Bull Flag
🕯️    NR7+Inside Bar
✧     Golden Pocket+
```

Nur aktive Signals anzeigen. Keine Signals = keine Zeile.

### E.5.2 — Top-15: Alpha-Longlist mit Composite

Der /top15 oder /longlist Befehl (falls vorhanden) zeigt die
technische Longlist. Neues Format:

```
📊 Top 15 Alpha-Composite

 #  Symbol  Total   B    F   Signals
 1  NVDA    187    72   77  🚩⚡📊
 2  MSFT    165    68   65  🎯
 3  AMZN    158    55   69  📈⚙️↑
 4  META    142    62   53
 5  AVGO    138    58   53  📊
...
```

Kompakt, eine Zeile pro Symbol. Signal-Icons ohne Text.

### E.5.3 — Exit-Alerts: G.1-G.4 im Telegram

Die neuen Exit-Regeln aus Paket G brauchen Telegram-Nachrichten.
Prüfen ob `position_monitor.py` bereits Telegram-Alerts sendet
oder ob die Alerts nur als Return-Werte vorliegen.

Falls Alerts noch nicht als Telegram-Nachrichten formatiert sind:

**Gamma-Zone Stop:**
```
🔴 GAMMA-ZONE EXIT — AAPL
$125/$115P exp 2026-05-15 | DTE 14
Verlust: -32% | Gamma-Risiko steigt stark
→ Jetzt schliessen
```

**Time-Stop:**
```
🟡 TIME-STOP — XOM
$95/$85P exp 2026-06-20 | 28 Tage gehalten
Verlust: -22% | Position erholt sich nicht
→ Schliessen erwägen
```

**RRG-Exit:**
```
🔴 RRG LAGGING — COP
$115/$105P exp 2026-05-30
RRG: LEADING → LAGGING | Kapitalfluss dreht
→ Schliessen empfohlen
```

**Macro-Warnung:**
```
📅 MACRO MORGEN: FOMC
Erhöhtes Gap-Risiko für alle offenen Positionen.
Offene Spreads prüfen.
```

### E.5.4 — Scan-Summary: Breakout-Statistik

Am Ende jedes Scans eine kurze Zusammenfassung:

```
📊 Scan-Summary: 361 Symbole | 5.3s
Composite aktiv | Post-Crash: Nein
Breakout-Signals: 8 aktiv (3× VWAP, 2× 3-Bar, 2× BB, 1× GP+)
Top B: NVDA 72 | Top F: AMZN 77
```

---

## Tests

**Formatter-Tests (mindestens 10):**
- Pick mit Breakout-Signals formatiert korrekt
- Pick ohne Breakout-Signals hat keine Signal-Zeile
- B+F Aufschlüsselung zeigt beide Werte
- Dual-RRG Kurzformat: "IMP→LEAD"
- PRE-BREAKOUT Flag erscheint als 🎯
- Top-15 Tabelle hat korrekte Spalten
- Alle 8 Signal-Icons werden korrekt gemappt
- Exit-Alerts (Gamma, Time, RRG) formatieren korrekt
- Macro-Alert formatiert korrekt
- Scan-Summary zeigt Breakout-Zählung

Mindestens 10 neue Tests.

---

## Akzeptanzkriterien

1. Scan-Pick zeigt B+F Aufschlüsselung
2. Aktive Breakout-Signals als Icons sichtbar
3. Top-15 zeigt Composite-Ranking kompakt
4. Exit-Alerts (G.1-G.4) als Telegram-Nachrichten formatiert
5. Scan-Summary mit Breakout-Statistik
6. Bestehende Telegram-Funktionen unverändert
7. Mindestens 10 neue Tests
8. Gesamtsuite grün
9. `docs/results/E5_RESULT.md` erstellt

---

## Standing Rules

- Anti-AI-Schreibstil
- Kein Auto-Trading
- Deutsche Telegram-Texte
- Keine Breaking Changes
- Keine Secrets in Code

---

## Commit-Flow

```bash
git add src/formatters/ src/mcp/ src/services/
git add tests/
git commit -m "feat(e5): telegram composite scores, breakout signals, exit alerts"

pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
black --check src/ tests/
git push origin feature/e5-telegram-composite

# Result-Doc
git add docs/results/E5_RESULT.md
git commit -m "docs(e5): add result report"
git push origin feature/e5-telegram-composite

# Nach Review: Merge
git checkout main && git pull
git merge --no-ff feature/e5-telegram-composite \
    -m "feat: E.5 Telegram composite scores + breakout signals + exit alerts"
git push origin main
git branch -d feature/e5-telegram-composite
git push origin --delete feature/e5-telegram-composite
```
