# Paket E.4 — Frontend: Composite-Visualisierung — RESULT

**Datum:** 2026-04-21
**Branch:** feature/g-exit-improvements
**Status:** ✅ Abgeschlossen

---

## Umgesetzte Änderungen

### E.4.1 — RRGChart: Dual-Trails

**Datei:** `~/OptionPlay-Web/frontend/src/components/RRGChart.jsx`

- **Slow-Trail (125d)**: gestrichelte Linie (`strokeDasharray="5,4"`), gedämpfte Farben via `MUTED_COLORS`-Map, Opacity 0.3–0.5
- **Fast-Trail (20d)**: durchgezogene Linie, kräftige Quadrant-Farben, Opacity 0.6–0.9
- **Aktueller Punkt**: Fast-Position als Haupt-Dot (gross), Slow-Position als Ghost-Dot (klein, transparent)
- **Legenden-Zeile**: "--- Slow (125d) — Fast (20d)" am unteren Rand, nur sichtbar wenn Fast-Trail-Daten vorhanden
- **Fallback**: Kein Breaking Change — wenn kein `trailFast`, wird der alte Trail-Pfad verwendet

**Neue Props je Datenpunkt** (alle optional):
- `trailFast`: Array `[{rs_ratio, rs_momentum}]`
- `rsRatioFast`, `rsMomentumFast`: aktuelle Fast-Position
- `quadrantFast`: Quadrant der Fast-Position (bestimmt Dot-Farbe)
- `dualLabel`: z.B. "LEAD→LAG" (im Tooltip)

### E.4.2 — Tooltip: Composite-Breakdown

**Datei:** `~/OptionPlay-Web/frontend/src/components/RRGChart.jsx`

Tooltip beim Hover zeigt jetzt:
- Sector-Name + ETF-Symbol
- **Slow RS**: `Ratio: X.XX  Mom: X.XX` (gedimmt)
- **Fast RS**: `Ratio: X.XX  Mom: X.XX` (heller, separte Zeile)
- **Dual-Label**: farbiger Badge, z.B. "LEAD→LAG"
- Earnings-Tage (wie bisher)

### E.4.3 — Sektor-Tabelle: Quadrant-Kombi

**Datei:** `~/OptionPlay-Web/frontend/src/components/Dashboard.jsx`

Sector-Tabelle erweitert von 6 auf 8 Spalten:

| Vorher | Nachher |
|--------|---------|
| Sector, ETF, Quadrant, RS Ratio, RS Mom, Mod | Sector, ETF, **Classic**, **Fast**, **Kombi**, RS Ratio, RS Mom, Mod |

- **Classic**: Slow-Quadrant Badge (wie bisher)
- **Fast**: Fast-Quadrant Badge (20d, neue Spalte)
- **Kombi**: Dual-Label Badge (z.B. "LEAD→LAG"), farbkodiert nach Quadrant-Konstellation

Beispieldaten (live, 2026-04-21):
```
Energy  | XLE | Leading  | Lagging  | LEAD→LAG  | 118.82 | 101.84 | +0.5
Tech    | XLK | Improving| Lagging  | IMP→LAG   |  97.3  |  98.4  | +0.3
```

### E.4.4 — Scanner: Alpha-Daten

**Backend:** `~/OptionPlay-Web/backend/api/json_routes.py`

Scan-Endpoint (`POST /api/json/scan`) liefert jetzt zusätzlich pro Signal:
- `alpha_raw`: Composite-Score (B + 1.5×F)
- `alpha_percentile`: Percentile-Rank 0–100 innerhalb der gescannten Symbole
- `breakout_signals`: Liste aktiver Breakout-Signale (leer wenn Feature inaktiv)
- `pre_breakout`: Boolean
- `dual_label`: Quadrant-Kombination
- `quadrant_fast`: Fast-Quadrant des Symbols

**Frontend:** `~/OptionPlay-Web/frontend/src/components/Scanner.jsx`

- **Neue Spalte "Alpha%"**: sortierbar, zeigt Percentile-Badge mit Ampelfarbe
  - Grün: ≥ 80. Perzentil
  - Amber: 40.–79. Perzentil
  - Rot: < 40. Perzentil
- **Breakout-Icons** neben Symbol:
  - 🎯 `pre_breakout`
  - ⚡ `BREAKOUT_IMMINENT`
  - 📊 `VWAP_RECLAIM`
  - 🔥 `VOLUME_SURGE`
- **Dual-Label** als Sub-Text unter Alpha-Badge (z.B. "LEAD→IMP")

---

## Geänderte Dateien

| Datei | Art | Beschreibung |
|-------|-----|-------------|
| `OptionPlay-Web/frontend/src/components/RRGChart.jsx` | Frontend | Dual-Trail, Enhanced Tooltip |
| `OptionPlay-Web/frontend/src/components/Dashboard.jsx` | Frontend | Fast-Trail Props, Kombi-Spalte |
| `OptionPlay-Web/frontend/src/components/Scanner.jsx` | Frontend | Alpha%, Breakout-Icons |
| `OptionPlay-Web/backend/api/json_routes.py` | Backend | sectors + scan Endpunkt erweitert |

---

## Akzeptanzkriterien — Check

| Kriterium | Status |
|-----------|--------|
| 1. RRG-Chart zeigt Dual-Trails (Slow + Fast) | ✅ |
| 2. Tooltip zeigt Fast RS + Dual-Label | ✅ |
| 3. Breakout-Signal-Icons in Scanner-Tabelle | ✅ (Icons vorhanden; Signale leer bis Feature aktiv) |
| 4. Sektor-Tabelle mit Quadrant-Kombi | ✅ |
| 5. Scanner zeigt Alpha-Percentile-Badge | ✅ |
| 6. Bestehende Frontend-Funktionen unverändert | ✅ |
| 7. `docs/results/E4_RESULT.md` erstellt | ✅ |

---

## Technische Anmerkungen

- **Breakout-Signale**: Backend-Infrastruktur vorhanden (`AlphaCandidate.breakout_signals`), aber noch nicht befüllt — erfordert separate Pattern-Detection-Implementierung (E.2b-Erweiterung).
- **Alpha-Enrichment**: Läuft als separater AlphaScorer-Call nach dem Scan. Maximal 50 Symbole, parallel per `get_all_stock_rs`. Failure-safe (kein Break bei Exception).
- **RRG Achsbereich**: Automatisch angepasst an Slow- UND Fast-Werte, keine manuelle Skalierung nötig.

---

## Nächste Pakete

- **F (Optimizer):** Shadow-Evaluator + Auto-Gewichte (nach 20+ Trades)
- **H (Portfolio-Management):** Risk-Budget, VIX-Slots, Korrelation
- **D (Retraining):** Delta 0.16, DTE 30-45
