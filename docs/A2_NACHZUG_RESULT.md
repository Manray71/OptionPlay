# A.2 Nachzug — Ergebnis

Branch: `verschlankung/a2-nachzug`
Datum: 2026-04-16

---

## Tests

| Zeitpunkt | Passed | Skipped | Fehler |
|-----------|--------|---------|--------|
| Baseline (vor Commit 1) | 5387 | 35 | 0 |
| Nach Commit 1 | 5387 | 35 | 0 |
| Nach Commit 2 | 5387 | 35 | 0 |
| Nach Commit 3 | 5387 | 35 | 0 |
| Final (nach Commit 4) | 5387 | 35 | 0 |

Delta: ±0. Kein Test neu rot, kein Test neu grün.

Hinweis: `tests/unit/test_hypothesis_pbt.py` kollektioniert nicht
(fehlende `hypothesis`-Abhängigkeit — vorbestehendes Problem,
nicht durch diesen Branch verursacht). In allen Läufen ignoriert.

---

## Commit 1 — OQ-1: Kommentar korrigiert

**Hash:** `b9fd8cf`
**Geänderte Dateien:** `src/constants/trading_rules.py` (1 Datei, 2+/1-)

Vorher:
```python
# Soft filters - WARNING only
ENTRY_IV_RANK_MIN = _entry_cfg.get("iv_rank_min", 30.0)
```

Nachher:
```python
# Hard-reject threshold: symbols below this IV Rank are
# skipped per strategy (see _check_iv_filter in scanner)
ENTRY_IV_RANK_MIN = _entry_cfg.get("iv_rank_min", 30.0)
```

Weitere Stellen mit demselben Mythos: keine gefunden
(`grep -rn "Soft filter|WARNING only" src/ | grep -i "iv_rank|entry"` → leer).

---

## Commit 2 — Regime-Profile Variante C

**Hash:** `ed05bf1`
**Geänderte Dateien:** `config/trading.yaml` (1 Datei, 4+/4-)

| Profil | Alt | Neu |
|--------|-----|-----|
| conservative (VIX < 15) | 50 | 20 |
| standard (VIX 15-20) | 50 | 25 |
| aggressive (VIX 20-30) | 50 | 30 |
| high_volatility (VIX >= 30) | 60 | 40 |

Dieser Commit war ein No-Op: OQ-2 (Bug) maskierte die Werte.
Der Scanner las unabhängig von diesen Werten immer 30 aus `ScannerConfig`.

---

## Commit 3 — OQ-2: Scanner liest filters.iv_rank_minimum

**Hash:** `bed65fe`
**Geänderte Dateien:** `src/config/core.py` (1 Datei, 2+/2-)

**Änderung in `get_scan_config()`:**

Vorher (`core.py:144`):
```python
iv_rank_minimum=(
    override_iv_rank_min
    if override_iv_rank_min is not None
    else scanner_cfg.iv_rank_minimum   # ← stale copy, nie durch Profile aktualisiert
),
iv_rank_maximum=(
    override_iv_rank_max
    if override_iv_rank_max is not None
    else scanner_cfg.iv_rank_maximum
),
```

Nachher:
```python
iv_rank_minimum=(
    override_iv_rank_min
    if override_iv_rank_min is not None
    else filters_cfg.iv_rank_minimum   # ← direkt aus FilterConfig, wird durch Profile aktualisiert
),
iv_rank_maximum=(
    override_iv_rank_max
    if override_iv_rank_max is not None
    else filters_cfg.iv_rank_maximum
),
```

**Warum war es falsch:**
`apply_vix_profile()` in `loader.py:596` aktualisiert `settings.filters.iv_rank_minimum`
wenn ein Profil angewendet wird. `settings.scanner.iv_rank_minimum` ist eine Kopie
die beim Bau von `ScannerConfig` aus `filters` gezogen wird (`loader.py:366`),
danach aber nie mehr aktualisiert wird. `get_scan_config()` las die stale Kopie.

**Feld `ScannerConfig.iv_rank_minimum` entfernt: NEIN**

Das Feld bleibt im Modell. Entfernen würde zwei Tests brechen, die den Dataclass-Default
prüfen:
- `tests/component/test_config_loader.py:455`: `assert config.iv_rank_minimum == 50.0`
  (testet `ScannerConfig()` Default)
- `tests/integration/test_multi_strategy_scanner.py:144`: `assert config.iv_rank_minimum == 50.0`
  (testet `ScanConfig()` Default -- anderer Typ, nicht betroffen)

Diese Tests prüfen keine falsche Verhaltens-Erwartung, sondern Dataclass-Defaults.
Das Feld in `ScannerConfig` wird noch gesetzt (`loader.py:366`), nur nicht mehr von
`core.py` gelesen. Die Doppelspurigkeit bleibt als technische Schuld bestehen.

**BESONDERER BEFUND — Keine Regime-Tests vorher rot, jetzt grün:**

Die gezielte Suche `pytest tests/ -k "regime or profile or iv_rank"` ergab
304 passed / 6 skipped. Kein einziger Test wurde durch Commit 3 neu grün oder neu rot.

Erklärung: Die vorhandenen Tests für Regime/Profile testen die Laufzeit-Logik
(VIX-Regime-Berechnung, Score-Multiplikatoren, etc.), aber keiner testet explizit
ob `get_scan_config()` den `filters_cfg`-Wert übernimmt. Die Verhaltensänderung
ist real, aber nicht durch bestehende Tests abgedeckt. Ein Test der Form
"nach apply_vix_profile(conservative) liefert get_scan_config().iv_rank_minimum == 20"
fehlt.

**BESONDERER BEFUND — Keine Tests rot geworden:**

Kein Test prüfte das alte "immer 30"-Verhalten explizit. Die Tests für
`ScannerConfig.iv_rank_minimum` testen nur Dataclass-Defaults, nicht den
Rückgabewert von `get_scan_config()`.

---

## Commit 4 — Dokumentation

**Hash:** `597b3aa`
**Geänderte Dateien:** `docs/IV_RANK_THRESHOLDS.md` (neu aus b0-Branch übernommen und aktualisiert)

Änderungen am Dokument:
- Übersichtstabelle: Beschreibung Stufe 2 ergänzt ("Regime-Profil überschreibt: 20/25/30/40")
- Pipeline-Beschreibung: Stufe 2 zeigt jetzt alle vier Profil-Werte statt statisch "30"
- Abschnitt "30 -- Live-IV-Scanner-Filter": core.py-Ladeweg korrigiert (liest jetzt `filters_cfg`)
- Abschnitt "30": Hinweis auf OQ-1-Behebung (Kommentar-Fix)
- Abschnitt "50": Profil-Werte auf Variante C aktualisiert (20/25/30/40)
  Abweichung vom PLAYBOOK (50) explizit dokumentiert
- Abschnitt "Offene Fragen": OQ-1 und OQ-2 als RESOLVED markiert mit Commit-Hashes

---

## Zusammenfassung

| Commit | Hash | Verhalten geändert |
|--------|------|--------------------|
| OQ-1 Kommentar | b9fd8cf | Nein (nur Kommentar) |
| Profil-Werte (Variante C) | ed05bf1 | Nein (Bug maskierte Werte) |
| OQ-2 Scanner-Read | bed65fe | Ja — Profile wirken jetzt |
| Dokumentation | 597b3aa | Nein |

Die Verhaltensänderung liegt ausschließlich in Commit 3: Wenn ein VIX-Regime-Profil
aktiv ist, liest der Scanner jetzt den Profil-Wert statt immer 30. Commit 2 liefert
die korrekten Zielwerte (20/25/30/40); Commit 3 schaltet sie ein.
