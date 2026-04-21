# Verschlankungs-Paket A -- Ergebnis

**Branch:** verschlankung/a-tier1-bugs
**Datum:** 2026-04-15

## Baseline
- Tests vorher: 5919 passed, 1 failed (from background run); second run 5920 passed, 0 failed
- Failures vorher: 1 (test_get_strategy_recommendation -- intermittent VIX cache issue)

## Schritt A.1: Roll-Parameter deduplizieren
**Status:** DONE
**Commit:** af76030
**Befund:** system.yaml roll block was already comment-only (6 lines, no YAML keys) pointing to trading.yaml. No actual parameter duplication existed. The conflicting values mentioned (bounce.dte_extension 52 vs 76) were in the old history, not in current files. Removed the empty comment block.

## Schritt A.2: iv_rank_minimum entfernen
**Status:** BLOCKED
**Commit:** none
**Befund:** `iv_rank_minimum` is actively read at src/config/loader.py:307-308 from system.yaml `filters.implied_volatility.iv_rank_minimum`. Also used in src/config/models.py (field default), src/config/validation.py (bounds check), and src/formatters/output_formatters.py (display). The value 30 is the active scanner pre-filter default. Do NOT delete.

## Schritt A.3: VIX E2E Failures fixen
**Status:** DONE
**Commit:** d5ca12c
**Befund:** Root cause: server fixture did not clear `server._current_vix` before tests. The VixHandler.get_vix() checks cache first (line 53-57 in vix_composed.py); if `_ctx.current_vix` was already populated from the shared singleton state (17.96 from Yahoo/DB), it returned that instead of reaching `mock_provider.get_quote("VIX")`. Also, `server._ibkr_bridge` was set to the real IBKRBridge singleton (if IBKR_AVAILABLE), causing potential hangs in the bridge.get_vix_value() path. Fix: added `server._ibkr_bridge = None`, `server._current_vix = None`, `server._vix_updated = None` to the server fixture.

## Schritt A.4: vix_regime_v2.enabled entfernen
**Status:** DONE
**Commit:** 72fe038
**Befund:** `_load_vix_regime_v2_enabled()` in multi_strategy_scanner.py only reads `vix_regime_v2.enabled` and defaults to True when the key is absent. `term_structure_overlay` was not read from YAML anywhere in src/. Entire `vix_regime_v2:` block (9 lines including header comment) removed from trading.yaml. Scanner behavior unchanged.

## Schritt A.5: CLAUDE.md aktualisieren
**Status:** DONE
**Commit:** 4ea0d65
**Befund:** VIX anchor table was already correct (7 anchors). Two corrections made: (1) earnings_history source DEFAULT: 'yfinance' -> 'marketdata' (actual value in src/cache/earnings_history.py:133); (2) removed stale Feature-Flag note about vix_regime_v2.enabled since the config key was deleted in A.4.

## Schritt A.6: DTE-Dualitat dokumentieren
**Status:** DONE
**Commit:** 2027e95
**Befund:** DTE ranges found: spread.dte_min=35 / dte_max=50 in trading.yaml serve BOTH entry signal selection AND options chain query defaults (via SPREAD_DTE_MIN/MAX in trading_rules.py). Hardcoded fallback in trading_rules.py is 60-90 but runtime values are 35-50. Added DTE Conventions section to CLAUDE.md and clarifying comments to trading.yaml spread block.

## Schritt A.7: mcp_main.py Docstring
**Status:** DONE
**Commit:** 6e2828b
**Befund:** Docstring showed "53 + 55 Aliases = 108 Endpoints" -- completely outdated. Actual registry count (excluding example placeholder): 25 tools + 28 aliases = 53 endpoints (matches SKILL.md). Replaced stale inline tool list with single-line pointer to mcp_tool_registry.py.

## Ergebnis
- Tests nachher: 5920 passed, 0 failed, 29 skipped
- Failures nachher: 0
- Coverage: 76.18%
