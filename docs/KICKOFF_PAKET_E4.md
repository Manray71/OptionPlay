# Paket E.4 — Frontend: Composite-Visualisierung
**Kontext:** E.2b (Composite), G (Exits), E.5 (Telegram) abgeschlossen.
AlphaScorer liefert `AlphaCandidate` mit `b_composite`, `f_composite`,
`breakout_signals`, `pre_breakout`. Telegram zeigt die Daten bereits.

---

## Motivation

Die Web-UI zeigt noch das alte RS-only-Modell. Die neuen Composite-Scores,
Breakout-Signals und Dual-RRG-Quadranten sind im Backend berechnet, aber
im Frontend unsichtbar. E.4 macht sie sichtbar.

---

## Branch

```bash
cd ~/OptionPlay-Web  # oder wo das Frontend-Repo liegt
git checkout main && git pull
git checkout -b feature/e4-composite-frontend
```

**Prüfen:** Liegt das Frontend im gleichen Repo (`~/OptionPlay`) oder
separat (`~/OptionPlay-Web`)? Entsprechend anpassen.

---

## Vorarbeit: Bestehende Frontend-Architektur verstehen

```bash
# Repo-Struktur
ls -la ~/OptionPlay-Web/ 2>/dev/null || ls -la ~/OptionPlay/frontend/ 2>/dev/null

# Tech-Stack erkennen (React? Vue? Vanilla?)
cat ~/OptionPlay-Web/package.json 2>/dev/null | head -20
find ~/OptionPlay-Web/src -name "*.tsx" -o -name "*.vue" -o -name "*.jsx" 2>/dev/null | head -10

# Bestehende RRG-Komponente
find ~/OptionPlay-Web -name "*rrg*" -o -name "*RRG*" -o -name "*rgg*" 2>/dev/null
find ~/OptionPlay-Web -name "*scanner*" -o -name "*scan*" 2>/dev/null | head -10
find ~/OptionPlay-Web -name "*sector*" -o -name "*alpha*" 2>/dev/null | head -10

# API-Endpunkte die das Frontend aufruft
grep -rn "api\|fetch\|axios\|endpoint" ~/OptionPlay-Web/src --include="*.ts" --include="*.tsx" --include="*.vue" --include="*.js" 2>/dev/null | head -20

# Backend-API für Frontend
grep -rn "def.*route\|@app\.\|@router\." ~/OptionPlay/src/web/ ~/OptionPlay/src/api/ 2>/dev/null | head -20
grep -rn "alpha\|composite\|breakout\|longlist" ~/OptionPlay/src/web/ ~/OptionPlay/src/api/ 2>/dev/null | head -20
```

Basierend auf dem Output die vier Phasen an die tatsächliche Architektur
anpassen.

---

## Scope E.4

### E.4.1 — RRG-Chart: Dual-Trails

Das RRG-Chart (Relative Rotation Graph) zeigt Symbole in einem
4-Quadranten-Diagramm. Aktuell vermutlich nur Slow-Window.

**Neu:**
- Slow-Trail (125d): gestrichelte Linie, gedämpfte Farbe
- Fast-Trail (20d): durchgezogene Linie, kräftige Farbe
- Aktueller Punkt: grösser, mit Symbol-Label
- Quadranten-Hintergrund: LEADING (grün), IMPROVING (blau),
  WEAKENING (gelb), LAGGING (rot), jeweils leicht eingefärbt

Falls kein RRG-Chart existiert: eines bauen. SVG oder Canvas,
X-Achse = RS-Ratio, Y-Achse = RS-Momentum. Punkt pro Symbol mit
Trail der letzten N Tage.

**Daten vom Backend:**
Das SectorRS-Service liefert Trail-Daten (`rs_ratio`, `rs_momentum`
für Slow und Fast). Prüfen welcher API-Endpunkt diese Daten
ausliefert.

### E.4.2 — Tooltip: Composite-Breakdown

Hover über ein Symbol im RRG-Chart oder in der Scanner-Tabelle
zeigt ein Tooltip mit:

```
NVDA — Alpha: 187
━━━━━━━━━━━━━━━━
B (Classic): 72
  RSI:        8.2
  Money Flow: 1.3
  Tech:       3.1
  Quadrant:   +25
  Earnings:   +12
  Season.:    +1.5
  Divergenz:  0
  Breakout:   +5.0

F (Fast):    77
  (gleiche Aufschlüsselung)

Signals: 🚩⚡ BREAKOUT IMMINENT
         📊 VWAP Reclaim
```

Die Daten kommen aus `CompositeScore` (via `AlphaCandidate`).
Prüfen ob der API-Endpunkt diese Detail-Daten mitliefert oder
ob ein neuer Endpunkt nötig ist.

### E.4.3 — Sektor-Tabelle: Quadrant-Kombi

Die Sektor-Übersichtstabelle (falls vorhanden) erweitern um:

| Sektor | Classic | Fast | Kombi | Score |
|--------|---------|------|-------|-------|
| Tech | LEADING | IMPROVING | LEA→IMP | +10 |
| Energy | WEAKENING | LAGGING | WEA→LAG | -20 |
| Health | IMPROVING | LEADING | IMP→LEA | +25 |

Farbcodierung nach Quadrant. Sortierung nach Kombi-Score.

### E.4.4 — Scanner-Seite: Longlist mit Alpha

Die Scanner-Seite (Kandidaten-Übersicht) erweitern:

- Sortierung nach `alpha_raw` (Composite) statt altem Score
- Breakout-Signal-Icons neben jedem Symbol
- PRE-BREAKOUT Badge (🎯) wenn aktiv
- Ampel-Farbe basierend auf Composite-Tier:
  - Grün: Top 20% (Alpha > 80. Perzentil)
  - Gelb: Mitte (40.-80. Perzentil)
  - Rot: Unten (< 40. Perzentil)

---

## API-Erweiterungen (falls nötig)

Falls das Backend die Composite-Details noch nicht per API ausliefert,
müssen ein oder zwei Endpunkte erweitert werden:

```python
# Beispiel: Longlist-Endpunkt erweitern
@router.get("/api/alpha/longlist")
async def get_longlist():
    candidates = await alpha_scorer.generate_longlist(symbols, top_n=30)
    return [{
        "symbol": c.symbol,
        "alpha_raw": c.alpha_raw,
        "b_composite": c.b_composite,
        "f_composite": c.f_composite,
        "breakout_signals": list(c.breakout_signals),
        "pre_breakout": c.pre_breakout,
        # ... weitere Felder
    } for c in candidates]
```

Prüfen was der aktuelle API-Layer liefert und was ergänzt werden muss.

---

## Tests

**Frontend-Tests (je nach Framework):**
- RRG-Chart rendert ohne Crash
- Tooltip zeigt alle Composite-Felder
- Breakout-Icons werden korrekt gemappt
- Sektor-Tabelle sortiert nach Kombi-Score
- Scanner-Seite zeigt Alpha-Ranking

**Backend-API-Tests (falls API erweitert):**
- Longlist-Endpunkt liefert Composite-Felder
- Breakout-Signals als Liste serialisiert
- Leere Signals → leere Liste (kein null)

---

## Akzeptanzkriterien

1. RRG-Chart zeigt Dual-Trails (Slow + Fast)
2. Tooltip zeigt Composite-Breakdown (B + F Einzelkomponenten)
3. Breakout-Signal-Icons sichtbar in Scanner-Tabelle
4. Sektor-Tabelle mit Quadrant-Kombi
5. Scanner sortiert nach Alpha-Composite
6. Bestehende Frontend-Funktionen unverändert
7. `docs/results/E4_RESULT.md` erstellt

---

## Standing Rules

- Anti-AI-Schreibstil
- Keine Breaking Changes
- Responsive Design (Desktop + Tablet)
- Keine externen Dependencies ohne Begründung

---

## Commit-Flow

```bash
# Frontend-Repo
git add .
git commit -m "feat(e4): composite visualization, dual RRG trails, breakout icons"
git push origin feature/e4-composite-frontend

# Backend (falls API erweitert, im OptionPlay-Repo)
cd ~/OptionPlay
git checkout -b feature/e4-api-composite
# ... Änderungen ...
git commit -m "feat(e4): extend alpha API with composite details"
git push origin feature/e4-api-composite

# Merges nach Review
```

---

## Nach E.4

Alle geplanten Pakete E.2b, G, E.5, E.4 sind dann abgeschlossen.
Verbleibend:
- **F (Optimizer):** Shadow-Evaluator + Auto-Gewichte (nach 20+ Trades)
- **H (Portfolio-Management):** Risk-Budget, VIX-Slots, Korrelation
- **D (Retraining):** Delta 0.16, DTE 30-45
