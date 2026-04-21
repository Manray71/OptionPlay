# Technische Schulden — Cleanup Sprint
**Kontext:** E.2b, G, E.5, E.4 abgeschlossen. Jetzt die Restposten aus
Plan Sektion 11, Stand 2026-04-20. Einige Punkte sind möglicherweise
durch die 8 Pakete heute bereits gelöst.

---

## Aufgabe

Alle bekannten technischen Schulden in einem Durchgang abarbeiten.
Drei Kategorien: Code-Fixes, manuelle Checks, Watchlist-Bereinigung.

---

## Branch

```bash
cd ~/OptionPlay
git checkout main && git pull
git checkout -b fix/tech-debt-cleanup
```

---

## Kategorie 1: Code-Fixes

### 1.1 MCP-Server: get_secure_config() Deprecation

`mcp_main.py:35` hat eine Deprecation-Warning. Fix:

```bash
grep -n "get_secure_config" src/mcp_main.py src/mcp/*.py
```

Migration: `get_secure_config()` → `ServiceContainer.secure_config`.

### 1.2 MCP-Server: IBKR clientId-Konflikt

Telegram-Bot (LaunchAgent) hält clientId 1. MCP bekommt Timeout bei
Reconnect. Fix: clientId im MCP auf 2 setzen.

```bash
grep -rn "client_id\|clientId\|client.*=.*1" src/mcp*.py src/ibkr/ config/
```

### 1.3 Watchlist: Tote Symbole entfernen

IBKR kennt diese Symbole nicht (Error 200):

- **CFLT** — aus Watchlist entfernen oder Alias prüfen
- **EXAS** — aus Watchlist entfernen oder Alias prüfen
- **SQ** — Block Inc., Ticker geändert. Prüfen ob `XYZ` der neue ist

```bash
grep -n "CFLT\|EXAS\|\bSQ\b" config/watchlists.yaml
```

Falls die Symbole in der Watchlist stehen: entfernen oder durch
korrekten Ticker ersetzen. Falls nicht: nur in Logs, kein Fix nötig.

### 1.4 Options-Collector Branch mergen oder löschen

Branch `fix/daily-options-collector` existiert seit Wochen.

```bash
git branch -a | grep daily-options
```

Optionen:
- Falls der Fix noch relevant ist: mergen
- Falls durch E.2b-Änderungen obsolet: Branch löschen
- Falls unklar: Status prüfen mit `git log main..fix/daily-options-collector --oneline`

### 1.5 Skipped Tests klären

Aktuell ~46 skipped Tests. 8 davon "pre-existing".

```bash
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | grep -i "skip\|SKIP"
pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
```

Prüfen welche skips berechtigt sind (z.B. DB-Benchmarks, IBKR-Verbindung)
und welche auf tote Funktionalität zeigen. Tote Skips: Tests löschen
oder fixen.

---

## Kategorie 2: Manuelle Checks (kein Code)

Diese Punkte erfordern manuelle Prüfung. Das Ergebnis dokumentieren,
dann als erledigt markieren.

### 2.1 Earnings-Script: Fehlende Symbole

Prüfen ob JNJ, BAC, JPM, KMI, WFC jetzt in earnings_history stehen:

```bash
cd ~/OptionPlay
python3 -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.optionplay' / 'trades.db'
conn = sqlite3.connect(str(db))
for sym in ('JNJ', 'BAC', 'JPM', 'KMI', 'WFC'):
    row = conn.execute(
        'SELECT COUNT(*) FROM earnings_history WHERE symbol = ?', (sym,)
    ).fetchone()
    print(f'{sym}: {row[0]} Einträge')
conn.close()
"
```

Falls 0 Einträge: `scripts/collect_earnings_eps.py` nochmal laufen lassen.
Falls > 0: erledigt.

### 2.2 Telegram-Token prüfen

```bash
source .env
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool
```

Falls Error → neuen Token erstellen über @BotFather.
Falls OK → erledigt.

### 2.3 Web Shadow-Button testen

Im Browser: OptionPlay-Web öffnen, DevTools (F12), Shadow-Button klicken.
Prüfen ob Console-Errors auftreten. Falls Fehler: dokumentieren.

### 2.4 MCP-Server Neustart testen

```bash
# Claude Desktop beenden und neu starten
# Dann in neuem Chat testen:
# tool_search query="optionplay"
# Sollte OptionPlay-Tools finden
```

### 2.5 IBKR Options Data Subscription

Error 10091 in Logs: Options-Marktdaten-Abo fehlt für NYSE.

Prüfen in TWS: Edit → Global Configuration → Market Data →
Market Data Subscriptions. Falls NYSE Options fehlt: Subscription
hinzufügen (kostet ~$1.50/Monat).

### 2.6 JNJ Options Chain: Halbe Strikes

JNJ hat $2.50-Inkremente statt $5.00. Strike-Selection-Logik prüfen:

```bash
grep -rn "strike.*increment\|strike.*step\|round.*strike" src/services/ src/scanner/
```

Falls die Logik auf $5-Inkremente hardcodiert ist: parametrisieren.
Falls sie bereits dynamisch ist: Testfall für JNJ hinzufügen.

---

## Kategorie 3: Akzeptiert / Kein Fix nötig

Zur Dokumentation: diese Punkte sind bewusst offen und brauchen keine Aktion.

| Punkt | Status | Begründung |
|-------|--------|------------|
| diskcache CVE | Akzeptiert | Kein upstream Fix, Dependabot dismissed |
| Options-Daten-Lücke 03/28-04/17 | Akzeptiert | Dokumentiert in DATA_GAP.md, nicht backfillbar |
| Div-Retro (30d Penalty-Check) | Warten | Braucht 30 Tage Shadow-Daten, Kalender-Reminder |
| use_ibkr_margin Flag | Optional | Nice-to-have, kein Impact auf Trading |
| Strategy.ATH_BREAKOUT Import | Vermutlich gefixt | Legacy-Cleanup (E.3) hat das behoben, verifizieren bei MCP-Neustart |

---

## Tests

Für die Code-Fixes (1.1-1.5):
- MCP startet ohne Deprecation-Warning
- ClientId-Konflikt nicht mehr reproduzierbar (braucht IBKR)
- Watchlist hat keine toten Symbole
- Skipped Tests sind dokumentiert oder gefixt
- Gesamtsuite grün

---

## Akzeptanzkriterien

1. `get_secure_config()` Deprecation gefixt
2. MCP clientId auf 2 (oder dokumentiert warum nicht)
3. CFLT, EXAS, SQ aus Watchlist entfernt oder korrekt
4. Options-Collector Branch entschieden (merge oder delete)
5. Skipped Tests reduziert oder dokumentiert
6. Earnings für JNJ/BAC/JPM/KMI/WFC verifiziert
7. Telegram-Token funktioniert
8. `docs/results/TECH_DEBT_RESULT.md` mit allen Ergebnissen

---

## Commit-Flow

```bash
# Code-Fixes committen
git add .
git commit -m "fix: tech debt cleanup — MCP deprecation, clientId, watchlist, skips"

pytest --tb=short --ignore=tests/system/test_mcp_server_e2e.py -q 2>&1 | tail -5
black --check src/ tests/
git push origin fix/tech-debt-cleanup

# Result-Doc
git add docs/results/TECH_DEBT_RESULT.md
git commit -m "docs: tech debt cleanup results"
git push origin fix/tech-debt-cleanup

# Merge
git checkout main && git pull
git merge --no-ff fix/tech-debt-cleanup -m "fix: tech debt cleanup sprint"
git push origin main
git branch -d fix/tech-debt-cleanup
```
