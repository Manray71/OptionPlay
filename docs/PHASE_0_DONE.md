# Phase 0 — Vorbereitung

**Datum:** 2026-04-06
**Branch:** refactor/v2-radical-cleanup
**Backup:** ~/OptionPlay_BACKUP_20260406_2047

## Baseline

### Tests
- 7771 passed, 11 skipped, 0 failed
- Laufzeit: 342.96s

### Größen
- Module src/: 221
- LOC src/: 96,412
- YAML config/: 5,882 Zeilen
- Scripts: 75
- Test-Dateien: 160

## Shadow Tracker Check
- `grep -n "backtesting" src/shadow_tracker.py` → **Output leer**
- shadow_tracker.py hat keine backtesting-Abhängigkeit
- Komplettes Löschen von src/backtesting/ ist sicher

## Untracked Files
- docs/SYSTEM_SNAPSHOT.md (war bereits vor Branch-Erstellung vorhanden, unverändert)
