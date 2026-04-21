# E.2b.5 — Verifikation + Kalibrierung + Merge
**Kontext:** E.2b.4 abgeschlossen auf `feature/e2b-alpha-composite`.
AlphaScorer nutzt TechnicalComposite hinter Feature-Flag (aktuell `false`).
5914 Tests grün.

---

## Aufgabe

Feature-Flag auf `true` setzen, Composite gegen echte Daten testen,
Score-Range kalibrieren, Breakout-Patterns verifizieren, PR nach main.

---

## Branch

```bash
cd ~/OptionPlay
git checkout feature/e2b-alpha-composite
git pull origin feature/e2b-alpha-composite
```

---

## Scope E.2b.5

### 1. Feature-Flag aktivieren

```yaml
# config/trading.yaml
alpha_composite:
  enabled: true    # war false
```

Alle bestehenden Tests müssen weiterhin grün sein.

```bash
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
```

Falls Tests brechen: Flag zurück auf `false`, Problem fixen, dann
erneut aktivieren.

### 2. Smoke-Test: 20-Symbol-Longlist

Echte Daten aus der DB nutzen. Script das die Longlist generiert
und die Ergebnisse formatiert:

```python
"""
Smoke-Test: Composite-Ranking für 20 bekannte Symbole.
Ausführen: python3 scripts/e2b_smoke_test.py
"""
import asyncio
from src.services.alpha_scorer import AlphaScorer
# ... config laden, DB verbinden ...

SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "TSLA", "JPM", "XOM", "COP",
    "UNH", "V", "MA", "HD", "PG",
    "COST", "ABBV", "LLY", "MRK", "AVGO",
]

async def main():
    scorer = AlphaScorer(config)
    results = await scorer.generate_longlist(SYMBOLS, top_n=20)
    
    print(f"{'Rank':>4} {'Symbol':<8} {'Total':>8} {'B':>8} {'F':>8} "
          f"{'Breakout':>10} {'Signals'}")
    print("-" * 80)
    for i, r in enumerate(results, 1):
        print(f"{i:4} {r.symbol:<8} {r.alpha_raw:8.1f} "
              f"{r.b_composite:8.1f} {r.f_composite:8.1f} "
              f"{r.breakout_score:10.1f} {r.breakout_signals}")

asyncio.run(main())
```

Das Script muss nicht perfekt sein. Ziel: sehen ob die Rankings
plausibel sind und die Score-Range stimmt.

Speichern als `scripts/e2b_smoke_test.py` (temporär, kann nach
Verifikation gelöscht werden).

### 3. Score-Range-Analyse

Erwartete Ranges (basierend auf Christians System):

| Komponente | Erwartete Range | Prüfen |
|------------|----------------|--------|
| B (Classic Composite) | 10-80 | Nicht 0 oder >200 |
| F (Fast Composite) | 5-50 | Nicht 0 oder >100 |
| final (B + 1.5×F) | 20-150 | Nicht negativ oder >300 |
| breakout_score | 0-10 | Meist 0, gelegentlich 2-5 |

Falls die Ranges stark abweichen:
- Zu eng (alles zwischen 30-40): Gewichte in YAML erhöhen
- Zu breit (0-500): Gewichte reduzieren
- Alle gleich: ein Indikator dominiert, dessen Gewicht senken

Dokumentieren welche Anpassungen nötig waren.

### 4. Breakout-Pattern-Verifikation

Gegen bekannte historische Patterns testen. Nicht automatisiert,
sondern manuell prüfen:

```python
# Beispiel: NVDA hatte Bull Flag im Feb 2025
# Prüfen ob bull_flag für NVDA in dem Zeitraum feuert
bars = await db.get_daily_prices("NVDA", limit=260)
# Slice auf Feb 2025 Zeitraum
composite = TechnicalComposite(config)
result = await composite.compute(
    symbol="NVDA", closes=..., timeframe="fast", ...
)
print(f"breakout_signals: {result.breakout_signals}")
print(f"breakout_score: {result.breakout_score}")
print(f"pre_breakout: {result.pre_breakout}")
```

Falls keine historischen Breakout-Beispiele sofort auffindbar:
Das PRE-BREAKOUT Signal mit aktuellen Daten testen. Prüfen ob
Symbole mit hohem Money Flow + RSI 50-65 + CMF > 0.10 das Flag
bekommen.

### 5. Timing-Messung

Wie lange dauert ein Composite-Scan?

```python
import time
t0 = time.time()
results = await scorer.generate_longlist(all_symbols, top_n=30)
elapsed = time.time() - t0
print(f"{len(all_symbols)} symbols in {elapsed:.1f}s")
print(f"Per symbol: {elapsed/len(all_symbols)*1000:.0f}ms")
```

Ziel: < 30s für 381 Symbole. Falls langsamer: Engpass identifizieren
(DB? Indikator-Berechnung? Divergenz-Checks?).

### 6. Vergleich: Alte vs. Neue Rankings

Denselben Smoke-Test mit `alpha_composite.enabled = false` laufen
lassen und die Rankings nebeneinander stellen:

```
Symbol   Alt-Rank  Neu-Rank  Δ    Breakout-Signals
NVDA     3         1         +2   Bull Flag, VWAP Reclaim
XOM      1         7         -6   (keine)
AMZN     12        4         +8   PRE-BREAKOUT, BB Squeeze
...
```

Das zeigt ob Turnaround-Kandidaten (LAG→IMP, LAG→LEAD) jetzt
höher ranken als im RS-only-Modell.

### 7. Gewichts-Tuning (falls nötig)

Falls die Score-Range zu schmal oder ein Indikator dominiert:

```yaml
alpha_composite:
  weights:
    rsi: 1.0          # ggf. anpassen
    money_flow: 1.0
    tech: 1.0
    divergence: 1.0
    earnings: 1.0
    seasonality: 0.5
    quadrant_combo: 1.0
```

Maximal 2-3 Gewichte in dieser Phase anpassen. Grosses Tuning
kommt in Paket F (Optimizer).

### 8. Result-Dokumentation

`docs/results/E2b_5_RESULT.md` mit:

- Smoke-Test-Ergebnis: Top-20 Ranking (Tabelle)
- Score-Range: Min/Max/Median für B, F, Total
- Breakout-Verifikation: welche Patterns feuerten
- Timing: Dauer für N Symbole
- Vergleich Alt vs. Neu: Ranking-Shifts
- Gewichtsanpassungen (falls gemacht)
- Gesamtergebnis E.2b: LOC, Tests, Phasen-Zusammenfassung

### 9. PR-Merge nach main

```bash
# Finaler Test-Lauf
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q

# Merge
git checkout main
git pull origin main
git merge --no-ff feature/e2b-alpha-composite \
    -m "feat: E.2b Multi-Faktor Alpha-Composite

- TechnicalComposite: 8 Score-Komponenten + 6 Breakout-Patterns
- AlphaScorer: Composite statt RS-only (feature flag)
- Post-Crash-Modus: VIX >= 25 dreht Gewichtung
- Batch-OHLCV: ein DB-Call für alle Symbole
- 99+ neue Unit-Tests, Gesamtsuite 5900+ passed"

git push origin main

# Branch aufräumen
git branch -d feature/e2b-alpha-composite
git push origin --delete feature/e2b-alpha-composite
```

---

## Akzeptanzkriterien

1. `alpha_composite.enabled = true` → alle Tests grün
2. Smoke-Test: 20 Symbole ranken plausibel
3. Score-Range: B, F, Total in erwarteten Bereichen
4. Mindestens 1 Breakout-Pattern feuert in echten Daten
5. Timing: < 60s für alle Symbole (< 30s ideal)
6. Alt vs. Neu Vergleich dokumentiert
7. Gesamtsuite: 5914+ passed, 0 failed
8. PR-Merge auf main sauber
9. `docs/results/E2b_5_RESULT.md` vollständig
10. Feature-Branch gelöscht

---

## Nach E.2b.5

Paket E.2b ist abgeschlossen. Nächste Optionen:

- **Paket G** (Quick-Win Exits): Gamma-Zone-Stop, Time-Stop, RRG-Exit
- **Paket E.4** (Frontend): Composite-Details in Web-UI
- **Paket E.5** (Telegram): B+F im Scan-Output
- **Paket F** (Optimizer): Shadow-Evaluator + Auto-Gewichte
