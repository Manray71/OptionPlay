# B2 Earnings Audit — Diagnose

**Branch:** verschlankung/b2-audit  
**Datum:** 2026-04-17  
**Zweck:** Reine Diagnose. Kein Code-Eingriff.

---

## 1. Datenqualität `earnings_history`

### 1a. Gesamtüberblick

```
total_rows | symbols | earliest   | latest
-----------+---------+------------+------------
22762      | 363     | 2002-02-05 | 2027-01-20
```

363 Symbole. Zeitraum reicht theoretisch von 2002 bis 2027 (zukünftige Termine werden mitgespeichert).

---

### 1b. Befüllungsgrad pro Spalte

```
total  | has_actual | has_estimate | has_surprise | has_surprise_pct
-------+------------+--------------+--------------+-----------------
22762  | 7989       | 7991         | 7976         | 7976
```

Von 22.762 Zeilen haben nur **7.976–7.991 (~35%)** EPS-Felder befüllt. Die übrigen 14.786 Zeilen (~65%) enthalten nur das Datum.

---

### 1c. Befüllungsgrad nach source

```
source      | total | has_actual | has_estimate | has_surprise
------------+-------+------------+--------------+-------------
ibkr        |   353 |          0 |            0 |           0
marketdata  |   621 |          0 |            0 |           0
tradier     | 13784 |          0 |            0 |           0
yfinance    |  8004 |       7989 |         7991 |        7976
```

**Befund:** Alle 7.976 brauchbaren EPS-Zeilen kommen ausschließlich von `yfinance`. Die drei anderen Quellen (ibkr, marketdata, tradier) liefern nur Datumsstempel ohne EPS-Daten. Tradier ist inzwischen entfernt (2026-04-09), ibkr und marketdata liefern ebenfalls keine EPS-Felder.

---

### 1d. Symbole mit mindestens 4 sauberen Quartalen

```
symbols_with_4_clean_quarters
------------------------------
342
```

342 von 363 Symbolen (94%) haben ≥ 4 Quartale mit `eps_actual IS NOT NULL AND eps_estimate IS NOT NULL AND eps_surprise IS NOT NULL`.

---

### 1e. Verteilung: saubere Quartale pro Symbol

```
clean_q | num_symbols
--------+------------
      2 |           1
      4 |           1
      8 |           2
     10 |           1
     11 |           2
     13 |           1
     16 |           1
     17 |           2
     18 |           7
     19 |           5
     20 |           3
     21 |           6
     22 |           3
     23 |          16
     24 |         284
     25 |           6
     26 |           2
```

Die große Mehrheit (284 Symbole) hat exakt 24 saubere Quartale (= 6 Jahre). Der Long-Tail nach unten (clean_q ≤ 13) umfasst 8 Symbole. 1 Symbol hat nur 2, 1 weiteres nur 4 saubere Quartale. Symbole mit gar keinen EPS-Daten tauchen in dieser Tabelle nicht auf — das betrifft die restlichen 363 − 344 = 21 Symbole (Differenz zur 1d-Abfrage, da 1d `HAVING >= 4` und 1e alle ≥ 1 zeigt; 2 Symbole mit 2 bzw. 4 sauberen Quartalen fallen aus 1d-Bedingung heraus).

Für die Praxis: **≥ 4 saubere Quartale: 342 Symbole. Davon ≥ 8: 339 Symbole.**

---

### 1f. Beat vs. Miss Verteilung

```
beats | meets | misses | total
------+-------+--------+-------
6014  |   293 |  1669  | 7976
```

- Beat-Rate gesamt: **75,4%**
- Miss-Rate: **20,9%**
- Meet-Rate: **3,7%**

Typischer Survivorship-Bias in S&P-nahen Universa: Bekannte Caps schlagen Schätzungen regelmäßig.

---

### 1g. Stichprobe — letzte Quartale ausgewählter Symbole

```
symbol | earnings_date | eps_actual | eps_estimate | eps_surprise | eps_surprise_pct | source
-------+---------------+------------+--------------+--------------+------------------+---------
AAPL   | 2026-01-29    |       2.84 |         2.67 |         0.17 |             6.37 | yfinance
AAPL   | 2025-10-30    |       1.85 |         1.77 |         0.08 |             4.52 | yfinance
AAPL   | 2025-07-31    |       1.57 |         1.43 |         0.14 |             9.79 | yfinance
AAPL   | 2025-05-01    |       1.65 |         1.62 |         0.03 |             1.85 | yfinance
AAPL   | 2025-01-30    |       2.40 |         2.34 |         0.06 |             2.56 | yfinance
AAPL   | 2024-10-31    |       0.97 |         0.95 |         0.02 |             2.11 | yfinance
AAPL   | 2024-08-01    |       1.40 |         1.34 |         0.06 |             4.48 | yfinance
AAPL   | 2024-05-02    |       1.53 |         1.50 |         0.03 |             2.00 | yfinance
AAPL   | 2024-02-01    |       2.18 |         2.11 |         0.07 |             3.32 | yfinance
AAPL   | 2023-11-02    |       1.46 |         1.39 |         0.07 |             5.04 | yfinance
...
AMZN   | 2026-02-05    |       1.95 |         1.95 |         0.00 |             0.00 | yfinance
AMZN   | 2025-10-30    |       1.95 |         1.56 |         0.39 |            25.00 | yfinance
AMZN   | 2025-07-31    |       1.68 |         1.32 |         0.36 |            27.27 | yfinance
AMZN   | 2025-05-01    |       1.59 |         1.36 |         0.23 |            16.91 | yfinance
AMZN   | 2025-02-06    |       1.86 |         1.48 |         0.38 |            25.68 | yfinance
AMZN   | 2024-10-31    |       1.43 |         1.14 |         0.29 |            25.44 | yfinance
AMZN   | 2024-08-01    |       1.26 |         1.02 |         0.24 |            23.53 | yfinance
AMZN   | 2024-04-30    |       0.98 |         0.83 |         0.15 |            18.07 | yfinance
AMZN   | 2024-02-01    |       1.00 |         0.80 |         0.20 |            25.00 | yfinance
AMZN   | 2023-10-26    |       0.94 |         0.59 |         0.35 |            59.32 | yfinance
```

Daten sind konsistent und vollständig. `eps_surprise` = `eps_actual − eps_estimate`. `eps_surprise_pct` = `(eps_actual − eps_estimate) / |eps_estimate| × 100`.

---

## 2. Feature-Design

### Vorgeschlagenes Schema (vom Freund)

| Pattern    | Score (100er) | Score (10er) |
|------------|:-------------:|:------------:|
| 4/4 Beats  | +12           | +1.2         |
| 3/4 Beats  | +6            | +0.6         |
| 2/4 Mix    |  0            |  0.0         |
| 2/4 Misses | −10           | −1.0         |
| 3/4 Misses | −18           | −1.8         |
| 4/4 Misses | −28           | −2.8         |

### Frage 1: Können wir 4/4 für die meisten Symbole umsetzen?

**Ja.** 342 Symbole haben ≥ 4 saubere Quartale; davon 339 mit ≥ 8. Die typische Tiefe ist 24 Quartale, sodass wir für "die letzten 4" immer genug Material haben. Für die 8 Symbole mit < 4 sauberen Quartalen (Tabelle 1e: clean_q ≤ 4) ist das Schema nicht 1:1 anwendbar.

### Frage 2: Symbole mit nur 2–3 sauberen Quartalen (< 4)?

Betrifft 2 Symbole (clean_q = 2 und clean_q = 4 — da `clean_q = 4` gerade noch reicht, also de facto 1 Symbol mit nur 2 sauberen Quartalen). Empfehlung: **pro-rata-Skalierung**. Statt 4/4 = 100% Beats → +1.2, statt 3/3 = 100% Beats → +1.2 (gleiche Schwellenwerte auf verfügbare Quartale anwenden). Alternativ: Default-Wert 0.0 ("neutral"), solange weniger als 4 Quartale vorhanden.

### Frage 3: Symbole mit 0 sauberen Quartalen?

Betrifft die 21 Symbole ohne EPS-Daten (ausschließlich Datumsstempel aus ibkr/tradier/marketdata). Empfehlung: **Default 0.0** — kein Bonus, keine Strafe. Das Fehlen von Daten ist kein Qualitätssignal.

---

## 3. Bestehende Earnings-Nutzung im Code

### grep-Ergebnisse

```
src/mcp_server.py:476:        from .cache import get_earnings_history_manager
src/mcp_server.py:481:        earnings_history = get_earnings_history_manager()
src/mcp_server.py:503:        batch_results = await earnings_history.is_earnings_day_safe_batch_async(...)
src/container.py:89:    earnings_cache: Optional["EarningsCache"] = None
src/container.py:98:    earnings_history_manager: Optional["EarningsHistoryManager"] = None
src/data_providers/local_db.py:247:  FROM earnings_history
src/scanner/multi_strategy_scanner.py:336:  self._earnings_cache: Dict[str, Optional[date]] = {}
src/data_providers/fundamentals.py:342:  surprise = earnings.get("surprise_pct", 0)
src/data_providers/fundamentals.py:343:  factors.append(f"Letzter Earnings Beat ({surprise:+.1f}% Überraschung)")
src/cache/symbol_fundamentals.py:815:  def update_earnings_beat_rate(self, symbol: str) -> bool:
```

### Gibt es bereits einen Earnings-Surprise-Score?

**Nein** — nicht im Analyzer-/Scoring-Flow.

Was existiert:

1. **`earnings_beat_rate` in `symbol_fundamentals`** (`src/cache/symbol_fundamentals.py:815`): Berechnet als `beats / total * 100` über *alle* historischen Quartale mit Daten. Wird per `update_earnings_beat_rate()` in die DB geschrieben (340 von 381 Symbolen befüllt). Wird aber nirgends in `bounce.py`, `pullback.py` oder `multi_strategy_scanner.py` gelesen — ausschließlich in der Fundamentals-Tabelle abgelegt.

2. **`generate_positive_factors()` in `data_providers/fundamentals.py:339–343`**: Liest den letzten Earnings-Beat über yfinance live und ergänzt einen Textbaustein (`"Letzter Earnings Beat (+X.X% Überraschung)"`). Das ist reine Display-Logik für den MCP-Analysetext, kein numerischer Score-Modifier.

3. **`is_earnings_day_safe()` / `is_earnings_day_safe_batch_async()`** in `EarningsHistoryManager`: Einzige produktive Earnings-Nutzung im Scanner — prüft ob ein Symbol zu nahe an einem Earnings-Termin liegt (Entry-Filter, nicht Scoring).

**Fazit:** EPS-Surprise-Daten sind vorhanden und vollständig, werden aber nicht als Score-Faktor verwendet. Es gibt kein Modul, das "4 letzte Quartale Beat/Miss" in einen numerischen Modifier übersetzt.

---

## 4. Integration-Architektur

### Drei Optionen

**Option A: Pure Funktion in `src/cache/earnings_history.py`**

Pro: Daten-Nähe (Datenbankzugriff sitzt bereits dort), kein neues Modul.  
Con: `earnings_history.py` ist eine Cache-/Storage-Schicht, keine Scoring-Schicht. Mixing concerns.

**Option B: Neues Modul `src/services/earnings_quality.py`**

Pro: Klare Separation. Analogie zu `sector_rs.py` — ein Service, der aus rohen Daten einen Score-Modifier berechnet. Leicht testbar, leicht konfigurierbar.  
Con: Ein weiteres Modul.

**Option C: Direkt in `bounce.py` / `pullback.py`**

Pro: Keine neuen Dateien.  
Con: Divergenz-Penalties wurden ebenfalls aus den Analyzern ausgelagert (eigene Indikatoren-Module). Konsistenz spricht gegen C.

### Empfehlung

**Option B** — analog zu `sector_rs.py` und den Divergenz-Checks aus B.1b/c. Das bestehende Muster lautet:

- Service in `src/services/` berechnet den Modifier aus rohen Daten.
- Analyzer ruft den Service-Modifier ab und addiert/subtrahiert ihn nach den Divergenz-Checks.
- Konfigurationswerte stehen in `config/scoring.yaml`.

`earnings_history.py` bekommt eine schlanke Query-Hilfsfunktion (`get_recent_eps_results(symbol, n=4)`), die der neue Service aufruft. So bleibt die DB-Zugriffslogik dort, die Scoring-Logik wandert in den Service.

---

## 5. Empfehlung — konkreter Implementation-Vorschlag

### Funktions-Signatur

```python
# src/services/earnings_quality.py

def get_earnings_surprise_modifier(
    symbol: str,
    n_quarters: int = 4,
    db_path: Optional[Path] = None,
) -> float:
    """
    Berechnet einen additiven Score-Modifier auf Basis der letzten n Quartale.

    Returns:
        float — Modifier (z.B. +1.2, 0.0, -2.8).
        0.0 bei fehlenden/unvollständigen Daten.
    """
```

### Input

Symbol-String. Die Funktion liest direkt aus `earnings_history` (via bestehenden `EarningsHistoryManager` oder eigenem lightweight SQL). Keine vorberechnete Liste als Input — das würde das API unnötig verkomplizieren.

### Output

`float` — additiver Score-Modifier, YAML-konfigurierbar. Wertebereich entspricht dem vorgeschlagenen Schema (−2.8 bis +1.2 auf 10er-Skala).

### Default-Wert bei fehlenden/unvollständigen Daten

`0.0`. Neutral. Keine Strafe für fehlende Daten (Datenverfügbarkeit ist ein technisches, kein qualitatives Signal).

Bei < 4 sauberen Quartalen: **pro-rata** oder ebenfalls `0.0` — zu entscheiden beim Implementieren; Default `0.0` ist die konservativere Wahl.

### Wo im Scoring-Flow

Nach den Divergenz-Penalties, vor `clamp_score()`. Die Reihenfolge in `bounce.py` ist derzeit:

```python
total_score = self._apply_divergence_penalties(...)   # B.1b/c
total_score = clamp_score(total_score, BOUNCE_MAX_SCORE)
```

Einfügen als:

```python
total_score = self._apply_divergence_penalties(...)
total_score += get_earnings_surprise_modifier(context.symbol)  # B.2 — neu
total_score = clamp_score(total_score, BOUNCE_MAX_SCORE)
```

Analog in `pullback.py` an der entsprechenden Stelle (`_apply_divergence_penalties` → clamp).

### YAML-Konfiguration (analog Divergenz-Penalties)

```yaml
# config/scoring.yaml
earnings_surprise:
  n_quarters: 4
  thresholds:
    all_beats:    1.2    # 4/4 beats
    mostly_beats: 0.6    # 3/4 beats
    mixed:        0.0    # 2/4 (either direction)
    mostly_misses: -1.0  # 2/4 misses (d.h. nur 0-1 beats bei 4 Quartalen)
    many_misses:  -1.8   # 3/4 misses
    all_misses:   -2.8   # 4/4 misses
  min_quarters: 4        # default 0.0 wenn weniger Quartale vorhanden
```

### Geschätzter Umfang

| Artefakt | LOC (ca.) |
|---|---|
| `src/services/earnings_quality.py` — Service + Logik | 80–100 |
| Änderungen in `src/analyzers/bounce.py` | 5–10 |
| Änderungen in `src/analyzers/pullback.py` | 5–10 |
| Ergänzung `config/scoring.yaml` | 10 |
| Tests (`tests/unit/test_earnings_quality.py`) | 50–70 |
| **Gesamt** | **~150–200** |

Dateien: 3 geändert (bounce, pullback, scoring.yaml), 2 neu (earnings_quality.py, test_earnings_quality.py).

---

*Ende des Audits. Kein Code wurde verändert.*
