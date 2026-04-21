# Data Gap: options_prices 2026-03-28 to 2026-04-17

## Ursache

1. Marketdata.app-Abo ausgelaufen 2026-03-27 — primärer Lieferant für options_prices entfiel.
2. IBKR-basierter `daily_data_fetcher` Options-Snapshot war noch nicht gebaut.
3. Nach dem Bau: zwei Bugs verhinderten erfolgreichen Lauf:
   - **Bug A** (`daily_data_fetcher.py`): Zwei separate `asyncio.run()` Aufrufe crashten auf Python 3.14+ beim zweiten Aufruf. Gefixt: gemeinsamer `_run_ibkr_fetchers()` Wrapper.
   - **Bug B** (`src/ibkr/market_data.py`): Timeout für Preisabfrage war 2s — zu kurz für IBKR delayed data (typisch 3–8s). Gefixt: `range(20)` → `range(80)` (8s).

## Konsequenz

- `options_prices` hat eine Lücke von ~21 Handelstagen (2026-03-28 bis 2026-04-17).
- IV-Rank-Berechnung (`iv_rank_252d` in `symbol_fundamentals`) für diesen Zeitraum unvollständig.
- Walk-Forward-Training sollte diesen Zeitraum ausschließen oder mit Vorbehalt behandeln.

## Status

- Gefixt: 2026-04-18.
- Täglicher Cron sammelt options_prices via IBKR ab nächstem Handelstag.
