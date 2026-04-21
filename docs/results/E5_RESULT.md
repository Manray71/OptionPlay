# E.5 — Telegram: Composite-Scores + Breakout-Signals

**Branch:** feature/g-exit-improvements  
**Datum:** 2026-04-21  
**Status:** ✅ Abgeschlossen

---

## Umgesetzt

### E.5.1 — Scan-Output: Composite-Details im Pick-Format

`src/telegram/notifier.py → format_pick_message()`  
`src/formatters/pick_formatter.py → format_single_pick_v2()`

- B+F Aufschlüsselung: `📡 Alpha: 187 (B:72 + F:77×1.5) | IMP→LEAD`
- Dual-RRG Kurzformat aus `dual_label` (z.B. `IMP→LEAD`, `LEADING`)
- Breakout-Signal-Icons: 8 Signal-Typen mit eigenen Icons (🚩⚡ 🎯 📊 📈 ⚙️↑ 🚩 🕯️ ✧)
- PRE-BREAKOUT Flag via `pre_breakout=True` → Icon 🎯 automatisch gesetzt
- Nur aktive Signals angezeigt — keine Signals = keine Zeile

### E.5.2 — Top-15: Alpha-Longlist mit Composite

`src/telegram/notifier.py → format_top15_alpha(candidates)`

Neue Funktion für kompakte HTML-Tabelle:
```
📊 Top 15 Alpha-Composite

 #   Symbol   Total    B    F   Signals
 1   NVDA      187    72   77   🚩⚡📊
 2   MSFT      165    68   65   🎯
```

### E.5.3 — Exit-Alerts: G.1-G.4 im Telegram

`src/telegram/notifier.py → format_exit_signal(), format_macro_alert()`

- `format_exit_signal(signal, snap=None)` — erkennt Typ anhand `priority + action`:
  - Priority 5 / CLOSE → 🔴 GAMMA-ZONE EXIT
  - Priority 6 / CLOSE → 🟡 TIME-STOP
  - Priority 10 / CLOSE → 🔴 RRG LAGGING
  - Priority 10 / ALERT → 🟡 RRG ROTATION
- `format_macro_alert(events)` — G.4 FOMC/CPI/NFP Warnung
  - Leere Liste → leerer String (kein Output)

### E.5.4 — Scan-Summary: Breakout-Statistik

`src/telegram/notifier.py → format_scan_summary()` (optionaler `scan_stats` Parameter)

```
📊 Scan: 361 Symbole | 5.3s
🚩 Breakout-Signals: 8 aktiv (3× VWAP Reclaim | 2× 3-Bar Play)
NVDA 72 | Top F: AMZN 77
```

Vollständig rückwärtskompatibel — bestehende Aufrufe ohne `scan_stats` unverändert.

---

## Neue Felder

### `AlphaCandidate` (`src/models/alpha.py`)
- `breakout_signals: tuple[str, ...] = ()` — Pattern-Signals (z.B. `"VWAP_RECLAIM"`)
- `pre_breakout: bool = False` — Vorläufer-Breakout-Flag

### `DailyPick` (`src/services/recommendation_engine.py`)
- `b_raw: Optional[float] = None` — Slow RS-Komponente
- `f_raw: Optional[float] = None` — Fast RS-Komponente
- `breakout_signals: tuple[str, ...] = ()` — weitergeleitet von AlphaCandidate
- `pre_breakout: bool = False` — weitergeleitet von AlphaCandidate

Propagation in `src/handlers/scan_composed.py` (Alpha-Enrichment-Block).

---

## Tests

**Neue Testdatei:** `tests/unit/test_e5_telegram_composite.py`  
**19 Tests** — alle grün:

| Klasse | Tests |
|--------|-------|
| `TestPickMessageComposite` | 6 |
| `TestTop15Alpha` | 3 |
| `TestExitSignal` | 4 |
| `TestMacroAlert` | 3 |
| `TestScanSummaryBreakout` | 3 |

**Gesamtsuite:** 5.857 passed, 29 skipped, 0 failures (320s)

---

## Akzeptanzkriterien

| # | Kriterium | Status |
|---|-----------|--------|
| 1 | Scan-Pick zeigt B+F Aufschlüsselung | ✅ |
| 2 | Aktive Breakout-Signals als Icons sichtbar | ✅ |
| 3 | Top-15 zeigt Composite-Ranking kompakt | ✅ |
| 4 | Exit-Alerts (G.1-G.4) als Telegram-Nachrichten formatiert | ✅ |
| 5 | Scan-Summary mit Breakout-Statistik | ✅ |
| 6 | Bestehende Telegram-Funktionen unverändert | ✅ |
| 7 | Mindestens 10 neue Tests | ✅ (19) |
| 8 | Gesamtsuite grün | ✅ |
| 9 | `docs/results/E5_RESULT.md` erstellt | ✅ |

---

## Hinweis: Breakout-Signal-Berechnung

Die Signal-Typen (`BREAKOUT_IMMINENT`, `VWAP_RECLAIM`, etc.) sind in `AlphaCandidate` und `DailyPick` als Optional-Felder definiert. Die tatsächliche Pattern-Erkennung (aus Christians SIGNAL_ICONS Referenz) ist für E.2b vorgesehen. Alle Formatter sind so implementiert, dass sie Signals zeigen wenn vorhanden und die Zeile weglassen wenn keine Signals gesetzt sind — keine Breaking Changes.
