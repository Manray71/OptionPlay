#!/usr/bin/env python3
"""
Smoke Test — OptionPlay MCP Server
===================================

Tests all 10 core MCP tools via direct Python imports.
Run: .venv/bin/python scripts/smoke_test.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def run_smoke_test():
    from src.mcp_server import OptionPlayServer

    results = []
    total = 10

    def record(name: str, ok: bool, detail: str, elapsed: float):
        status = "OK" if ok else "FAIL"
        results.append((name, ok, detail, elapsed))
        icon = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        print(f"  {icon} {name:<25} {status}  ({elapsed:.1f}s)  {detail}")

    print("=" * 60)
    print("OptionPlay Smoke Test")
    print("=" * 60)
    print()

    async with OptionPlayServer() as server:

        # 1. Health Check
        t0 = time.time()
        try:
            result = await server.health_check()
            ok = isinstance(result, str) and len(result) > 50
            record("health", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("health", False, str(e)[:80], time.time() - t0)

        # 2. VIX
        t0 = time.time()
        try:
            vix = await server.get_vix()
            ok = vix is not None and 5 < vix < 100
            record("vix", ok, f"VIX={vix}", time.time() - t0)
        except Exception as e:
            record("vix", False, str(e)[:80], time.time() - t0)

        # 3. Regime
        t0 = time.time()
        try:
            result = await server.get_regime_status()
            ok = isinstance(result, str) and len(result) > 20
            record("regime", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("regime", False, str(e)[:80], time.time() - t0)

        # 4. Sector Status
        t0 = time.time()
        try:
            result = await server.get_sector_status()
            ok = isinstance(result, str) and len(result) > 20
            record("sector_status", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("sector_status", False, str(e)[:80], time.time() - t0)

        # 5. Ensemble Status
        t0 = time.time()
        try:
            result = await server.get_ensemble_status()
            ok = isinstance(result, str) and len(result) > 20
            record("ensemble_status", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("ensemble_status", False, str(e)[:80], time.time() - t0)

        # 6. Daily Picks (max_picks=3)
        t0 = time.time()
        try:
            result = await server.daily_picks(max_picks=3)
            ok = isinstance(result, str) and len(result) > 20
            record("daily (picks=3)", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("daily (picks=3)", False, str(e)[:80], time.time() - t0)

        # 7. Multi-Strategy Scanner (max_results=5)
        t0 = time.time()
        try:
            result = await server.scan_multi_strategy(max_results=5)
            ok = isinstance(result, str) and len(result) > 20
            record("multi (results=5)", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("multi (results=5)", False, str(e)[:80], time.time() - t0)

        # 8. Trend Continuation Scanner
        t0 = time.time()
        try:
            result = await server.scan_trend_continuation(max_results=5)
            ok = isinstance(result, str) and len(result) > 20
            record("trend", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("trend", False, str(e)[:80], time.time() - t0)

        # 9. Portfolio Summary
        t0 = time.time()
        try:
            result = server.portfolio_summary()
            ok = isinstance(result, str) and len(result) > 10
            record("portfolio", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("portfolio", False, str(e)[:80], time.time() - t0)

        # 10. Position Monitor
        t0 = time.time()
        try:
            result = await server.monitor_positions()
            ok = isinstance(result, str) and len(result) > 10
            record("monitor", ok, f"{len(result)} chars", time.time() - t0)
        except Exception as e:
            record("monitor", False, str(e)[:80], time.time() - t0)

    # Summary
    passed = sum(1 for _, ok, _, _ in results if ok)
    print()
    print("=" * 60)
    if passed == total:
        print(f"\033[32m  RESULT: {passed}/{total} OK — All systems operational\033[0m")
    else:
        failed = [name for name, ok, _, _ in results if not ok]
        print(f"\033[31m  RESULT: {passed}/{total} OK — Failed: {', '.join(failed)}\033[0m")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_smoke_test())
    sys.exit(0 if success else 1)
