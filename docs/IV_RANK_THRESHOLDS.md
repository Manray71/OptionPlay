# IV Rank Thresholds in OptionPlay

## Ubersicht

Drei distinkte IV-Rank-Schwellen sind im System aktiv. Sie prüfen unterschiedliche
Datenquellen, werden an verschiedenen Stellen in der Pipeline ausgewertet und haben
unterschiedliche Konsequenzen bei Unterschreitung.

| Wert | Config-Key | Datei | Zweck |
|------|------------|-------|-------|
| 20 | `fundamentals_prefilter.iv_rank_min` | `config/system.yaml:529` | Fundamentals-Vorfilter (historisch) |
| 30 | `filters.implied_volatility.iv_rank_minimum` | `config/system.yaml:150` | Live-IV-Filter im Scan-Loop (Base; Regime-Profil überschreibt: 20/25/30/40) |
| 50 | `entry.iv_rank_min` | `config/trading.yaml:27` | PLAYBOOK-Sollwert (Tastytrade) |

---

## Scan-Pipeline-Reihenfolge

```
Stufe 1 (vor Scan): filter_symbols_by_fundamentals()
  -- prueft symbol_fundamentals.iv_rank_252d (252-Tage-IV-Rank aus DB)
  -- Schwelle: 20  (fundamentals_iv_rank_min)
  -- Ergebnis: Symbol wird aus Symbolliste entfernt (hard reject)

Stufe 2 (im Scan-Loop, pro Strategie): _check_iv_filter()
  -- prueft _iv_cache[symbol] (Live-IV-Rank, gesetzt von IBKR-Daten)
  -- Schwelle: filters_cfg.iv_rank_minimum (get_scan_config() liest FilterConfig,
     nicht ScannerConfig). Wert je nach aktivem VIX-Profil:
       conservative    20  (VIX < 15)
       standard        25  (VIX 15-20)
       aggressive      30  (VIX 20-30)
       high_volatility 40  (VIX >= 30)
     Ohne aktives Profil: 30 (Base aus system.yaml:150)
  -- Ergebnis: Symbol wird fuer diese Strategie uebersprungen (continue)
  -- Ausnahme: Bounce-Strategie wird nicht geprueft (kein Credit-Spread)

Stufe 3 (konzeptionell, Tastytrade-Regel): ENTRY_IV_RANK_MIN = 50
  -- Wert stammt aus trading.yaml, Abschnitt entry
  -- Kein eigener Code-Pfad: dient als Default-Wert fuer
     FilterConfig/ScannerConfig/ScanConfig, wird aber von system.yaml
     auf 30 ueberschrieben (siehe Abschnitt 50 unten)
```

---

## Pro Schwelle

### 20 -- Fundamentals-Vorfilter

- **Definiert in:** `config/system.yaml`, zwei Stellen:
  - `scanner.fundamentals_prefilter.iv_rank_min: 20.0` (Zeile 529)
  - `filters.fundamentals.iv_rank_min: 20.0` (Zeile 183)
- **Geladen von:** `ScannerConfigLoader.get_fundamentals_prefilter()` in
  `src/utils/scanner_config_loader.py:236-247` liefert den Wert fuer
  `ScanConfig.fundamentals_iv_rank_min` (Default 20.0 in
  `multi_strategy_scanner.py:193`). `get_scan_config()` in `src/config/core.py:170`
  ubernimmt den Wert aus `fundamentals_cfg.iv_rank_min`.
- **Datenquelle:** `symbol_fundamentals.iv_rank_252d` -- gespeicherter
  252-Tage-IV-Rank aus der lokalen SQLite-DB, nicht live.
- **Code-Aufruf:** `filter_symbols_by_fundamentals()`, gerufen in
  `scan_async()` vor dem Haupt-Loop
  (`multi_strategy_scanner.py:1304` und `1510`).
- **Vergleich:** `multi_strategy_scanner.py:513`
  ```python
  if f.iv_rank_252d < self.config.fundamentals_iv_rank_min:
  ```
- **Wirkt auf:** gesamte Symbol-Liste vor dem Scan. Das Symbol wird in
  `filtered_reasons` eingetragen und vom weiteren Scan ausgeschlossen.
- **Was passiert unterhalb:** hard reject -- Symbol nimmt an keiner
  Strategie-Analyse teil.
- **Rationale (Kommentar in models.py:341):** "Intentionally looser than
  ENTRY_IV_RANK_MIN (pre-filter)" -- der Vorfilter soll nur chronisch
  IV-arme Symbole entfernen; er soll nicht die operationale Schwelle (50)
  durchsetzen, weil historische IV-Ranks schwanken.

---

### 30 -- Live-IV-Scanner-Filter

- **Definiert in:** `config/system.yaml:150`
  ```yaml
  implied_volatility:
    iv_rank_minimum: 30
  ```
- **Geladen von:** `src/config/loader.py:307-308`
  ```python
  iv_rank_minimum=f.get("implied_volatility", {}).get(
      "iv_rank_minimum", ENTRY_IV_RANK_MIN
  )
  ```
  Dieser Wert landet in `FilterConfig.iv_rank_minimum`. `get_scan_config()`
  (`core.py:144`) liest direkt `filters_cfg.iv_rank_minimum` und übernimmt
  ihn in `ScanConfig.iv_rank_minimum`. Wenn ein VIX-Regime-Profil via
  `apply_vix_profile()` aktiv ist, aktualisiert `loader.py:596`
  `FilterConfig.iv_rank_minimum` auf den Profil-Wert (20/25/30/40) --
  dieser Wert erreicht jetzt korrekt den Scanner (OQ-2 behoben).
- **Datenquelle:** `scanner._iv_cache[symbol]` -- live gesetzter IV-Rank,
  befüllt via `set_iv_rank()` / `set_iv_ranks()` (Daten kommen von IBKR).
  Ist kein Eintrag vorhanden, wird der Filter übersprungen
  (`multi_strategy_scanner.py:825`).
- **Code-Aufruf:** `_check_iv_filter()` gerufen in `analyze_symbol()`
  (`multi_strategy_scanner.py:959`) -- einmal pro Symbol pro Strategie,
  nach dem Earnings-Filter und nach dem Tier-Gate, vor dem Analyzer.
- **Vergleich:** `multi_strategy_scanner.py:829`
  ```python
  if iv_rank < self.config.iv_rank_minimum:
      return False, "IV-Rank zu niedrig ..."
  ```
- **Wirkt auf:** jede Strategie einzeln. Bounce ist ausgenommen
  (kein Credit-Spread, `multi_strategy_scanner.py:815`).
- **Was passiert unterhalb:** hard reject fuer diese Strategie (`continue`
  in analyze_symbol).
- **Hinweis zur Benennung in trading_rules.py:**
  `ENTRY_IV_RANK_MIN` trug früher den Kommentar "Soft filters - WARNING only"
  (`trading_rules.py:105`), obwohl der Scanner das Symbol hart verwirft.
  Dieser Widerspruch wurde in OQ-1 behoben: Kommentar lautet jetzt
  "Hard-reject threshold: symbols below this IV Rank are skipped per strategy
  (see _check_iv_filter in scanner)".

---

### 50 -- PLAYBOOK-Sollwert (Tastytrade)

- **Definiert in:** `config/trading.yaml:27`
  ```yaml
  entry:
    iv_rank_min: 50.0  # IV Rank minimum (Tastytrade)
  ```
  VIX-Regime-Profile in derselben Datei (Variante C, gesetzt in A.2-Nachzug;
  bewusste Abweichung vom PLAYBOOK-Wert 50 -- invertierte Staffelung):
  - `conservative.filters.implied_volatility.iv_rank_minimum: 20` (Zeile 279)
  - `standard.filters.implied_volatility.iv_rank_minimum: 25` (Zeile 316)
  - `aggressive.filters.implied_volatility.iv_rank_minimum: 30` (Zeile 353)
  - `high_volatility.filters.implied_volatility.iv_rank_minimum: 40` (Zeile 397)
- **Geladen von:** `src/constants/trading_rules.py:106`
  ```python
  ENTRY_IV_RANK_MIN = _entry_cfg.get("iv_rank_min", 30.0)
  # Laufzeitwert: 50.0 (aus trading.yaml)
  ```
- **Aktive Verwendung:** `ENTRY_IV_RANK_MIN` dient als Default-Wert in
  `FilterConfig.iv_rank_minimum`, `ScannerConfig.iv_rank_minimum` und
  `ScanConfig.iv_rank_minimum`. Diese Defaults werden beim
  Config-Laden durch system.yaml auf 30 uberschrieben.
- **Regime-Profile (nach OQ-2-Fix aktiv):** Wenn ein VIX-Profil angewendet
  wird (via `apply_vix_profile()`), setzt `loader.py:596`
  `settings.filters.iv_rank_minimum` auf den Profil-Wert (20/25/30/40).
  `get_scan_config()` liest jetzt `filters_cfg.iv_rank_minimum`
  (`core.py:141-145`) -- der Profil-Wert wirkt sich damit korrekt auf den
  Scanner aus.
- **Was passiert unterhalb:** Profil-Wert wird von `_check_iv_filter()`
  als Hard-Reject-Schwelle verwendet (kein eigener Code-Pfad für den
  PLAYBOOK-Wert 50 -- dieser dient nur als class-level Default).
- **Abweichung vom PLAYBOOK:** Das PLAYBOOK fordert IV Rank >= 50.
  Die Regime-Profile sind bewusst niedriger gesetzt (Variante C), um bei
  ruhigem Markt (VIX < 15) mehr Setups zuzulassen. Das PLAYBOOK gilt als
  konservative Referenz; die Profile erlauben kontrollierte Abweichung.

---

## Naming-Diskrepanz

Zwei verschiedene Config-Keys mit unterschiedlichen Werten existieren
nebeneinander:

| Key | Wert | Ort |
|-----|------|-----|
| `iv_rank_minimum` | 30 | `config/system.yaml → filters.implied_volatility` |
| `iv_rank_min` | 20 | `config/system.yaml → scanner.fundamentals_prefilter` |
| `iv_rank_min` | 20 | `config/system.yaml → filters.fundamentals` |
| `iv_rank_min` | 50 | `config/trading.yaml → entry` |

Die unterschiedlichen Suffixe (`_minimum` vs. `_min`) referenzieren
verschiedene Schwellen mit verschiedenen Zwecken. Das ist historisch
gewachsen und nicht konsistent, aber momentan eindeutig, weil jeder
Key in einem anderen YAML-Abschnitt sitzt.

---

## Empfehlung (nicht umzusetzen)

Die drei Werte haben klar trennbare Rollen. Eine Umbenennung nach diesem
Muster ware klarer:

| Neuer Key | Wert | Bedeutung |
|-----------|------|-----------|
| `iv_rank_prefilter_min` | 20 | Historischer Vorfilter (DB-Daten) |
| `iv_rank_scanner_min` | 30 | Live-Scanner-Filter (IBKR-Daten) |
| `iv_rank_entry_min` | 50 | PLAYBOOK-Sollwert (Tastytrade) |

Vorteil: Aus dem Namen ist sofort ersichtlich, in welcher Pipeline-Stufe
der Wert wirkt. Der heutige Mix aus `_min` / `_minimum` in verschiedenen
Abschnitten verbirgt diesen Unterschied.

Gegenargument: Der Status quo ist durch Kommentare im Code hinreichend
dokumentiert (`models.py:341`: "Intentionally looser than
ENTRY_IV_RANK_MIN (pre-filter)"). Eine Umbenennung erfordert Anpassungen
in mind. 8 Dateien (YAML, loader, models, scanner, core) und den
zugehorigen Tests.

---

## Offene Fragen

**OQ-1: "Soft filters -- WARNING only" Kommentar widerspricht Verhalten — RESOLVED**

Behoben in Branch `verschlankung/a2-nachzug`, Commit `b9fd8cf`.
`src/constants/trading_rules.py:105` kommentiert `ENTRY_IV_RANK_MIN` jetzt als:
"Hard-reject threshold: symbols below this IV Rank are skipped per strategy
(see _check_iv_filter in scanner)".

**OQ-2: Regime-Profil-Update erreicht den Scanner nicht — RESOLVED**

Behoben in Branch `verschlankung/a2-nachzug`, Commit `bed65fe`.
`src/config/core.py:141-145` liest jetzt `filters_cfg.iv_rank_minimum` statt
`scanner_cfg.iv_rank_minimum`. Da `apply_vix_profile()` (`loader.py:596`)
`FilterConfig.iv_rank_minimum` aktualisiert, wirkt das Profil jetzt korrekt
auf den Scanner. Gleichzeitig wurden die Profil-Werte auf Variante C gesetzt
(20/25/30/40, invertierte Staffelung).
