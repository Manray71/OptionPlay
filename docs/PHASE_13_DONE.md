# Phase 13 — Stale Artifacts gelöscht

**Datum:** 2026-04-07
**Hinweis:** Dateien in .gitignore (data_inventory/, reports/) — nur lokal gelöscht

## Gelöscht
- `data_inventory/baseline_ath_breakout.json`
- `data_inventory/trained_weights_v3_ath_breakout.json` (+ regime, sector, stability variants)
- `data_inventory/retrain_history/` (komplett)
- `data_inventory/retrain_report_*.json` (14 Dateien)
- `reports/shap/` (komplett)
- `reports/*ath_breakout*` und `*earnings_dip*` (5 PDFs)
- `reports/backtest_results.json`, `bs_comparison.csv`
- `reports/scan_report_*.html/.pdf` (28 Dateien)
- `reports/test_report.html/.pdf`

## Behalten
- `data_inventory/baseline_pullback.json`, `baseline_bounce.json`, `baseline_summary.json`
- `data_inventory/trained_weights_v3_pullback.json` (+ regime, sector, stability variants)
- `data_inventory/trained_weights_v3_bounce.json` (+ regime, sector, stability variants)
- `reports/260*_ScanReport.pdf` (historische Scan-Reports)
- `reports/260*_JPM_bounce.pdf` (Bounce-Reports)
