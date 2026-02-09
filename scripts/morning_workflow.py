#!/usr/bin/env python3
"""
Morning Workflow — OptionPlay Daily Check
==========================================

Automates the daily morning check:
1. VIX & Regime
2. Sector Status
3. Daily Picks (Top 5)
4. Open Positions Monitor
5. Expiring Positions (14 days)

Run: .venv/bin/python scripts/morning_workflow.py
     .venv/bin/python scripts/morning_workflow.py --save
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def morning_workflow(save: bool = False) -> str:
    from src.mcp_server import OptionPlayServer

    sections = []
    today = datetime.now().strftime("%Y-%m-%d")

    sections.append(f"# Morning Report — {today}")
    sections.append("")

    async with OptionPlayServer() as server:

        # --- 1. VIX & Regime ---
        sections.append("## 1. VIX & Regime")
        sections.append("")
        try:
            vix = await server.get_vix()
            sections.append(f"**Current VIX:** {vix}")
            sections.append("")
        except Exception as e:
            sections.append(f"VIX fetch failed: {e}")
            sections.append("")

        try:
            regime = await server.get_regime_status()
            sections.append(regime)
            sections.append("")
        except Exception as e:
            sections.append(f"Regime fetch failed: {e}")
            sections.append("")

        # --- 2. Sector Status ---
        sections.append("---")
        sections.append("## 2. Sector Status")
        sections.append("")
        try:
            sector = await server.get_sector_status()
            sections.append(sector)
            sections.append("")
        except Exception as e:
            sections.append(f"Sector status failed: {e}")
            sections.append("")

        # --- 3. Daily Picks ---
        sections.append("---")
        sections.append("## 3. Daily Picks (Top 5)")
        sections.append("")
        try:
            picks = await server.daily_picks(max_picks=5, include_strikes=True)
            sections.append(picks)
            sections.append("")
        except Exception as e:
            sections.append(f"Daily picks failed: {e}")
            sections.append("")

        # --- 4. Position Monitor ---
        sections.append("---")
        sections.append("## 4. Open Positions — Monitor")
        sections.append("")
        try:
            monitor = await server.monitor_positions()
            sections.append(monitor)
            sections.append("")
        except Exception as e:
            sections.append(f"Monitor failed: {e}")
            sections.append("")

        # --- 5. Expiring Positions ---
        sections.append("---")
        sections.append("## 5. Expiring Positions (14 days)")
        sections.append("")
        try:
            expiring = server.portfolio_expiring(days=14)
            sections.append(expiring)
            sections.append("")
        except Exception as e:
            sections.append(f"Expiring check failed: {e}")
            sections.append("")

    report = "\n".join(sections)

    # Print to stdout
    print(report)

    # Optionally save
    if save:
        log_dir = Path.home() / ".optionplay" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"morning_{today}.md"
        log_file.write_text(report, encoding="utf-8")
        print(f"\nSaved to {log_file}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OptionPlay Morning Workflow")
    parser.add_argument(
        "--save", action="store_true",
        help="Save report to ~/.optionplay/logs/morning_YYYY-MM-DD.md",
    )
    args = parser.parse_args()
    asyncio.run(morning_workflow(save=args.save))
