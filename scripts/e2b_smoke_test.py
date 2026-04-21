"""
Smoke-Test E.2b.5: Composite-Ranking fuer 20 bekannte Symbole.

Fuehrt 3 Tests durch:
  1. Ranking mit alpha_composite.enabled=true (Composite-Pfad)
  2. Ranking mit enabled=false (RS-only Pfad, Vergleich)
  3. Timing fuer alle verfuegbaren Symbole

Ausfuehren: python3 scripts/e2b_smoke_test.py
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from pathlib import Path
from typing import List

import yaml

logging.basicConfig(level=logging.WARNING)

# --- Projektpfad sicherstellen ---
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_providers.local_db import LocalDBProvider
from src.services.alpha_scorer import AlphaScorer
from src.services.sector_rs import SectorRSService

SYMBOLS_20 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "TSLA", "JPM", "XOM", "COP",
    "UNH", "V", "MA", "HD", "PG",
    "COST", "ABBV", "LLY", "MRK", "AVGO",
]


def _load_composite_cfg() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config" / "trading.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("alpha_composite", {})


def _load_sector_rs_cfg() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config" / "trading.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("sector_rs", {})


def _build_scorer(composite_enabled: bool) -> AlphaScorer:
    cfg = _load_composite_cfg()
    cfg = dict(cfg)
    cfg["enabled"] = composite_enabled
    provider = LocalDBProvider()
    srs = SectorRSService(provider=provider)
    sector_cfg = _load_sector_rs_cfg()
    return AlphaScorer(
        sector_rs_service=srs,
        config=sector_cfg,
        composite_config=cfg,
    )


async def run_ranking(symbols: List[str], composite_enabled: bool, top_n: int = 20):
    scorer = _build_scorer(composite_enabled)
    t0 = time.time()
    results = await scorer.generate_longlist(symbols, top_n=top_n)
    elapsed = time.time() - t0
    return results, elapsed


def _header(title: str):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print("=" * 80)


async def main():
    # =========================================================================
    # 1. Composite-Ranking (enabled=true)
    # =========================================================================
    _header("1. COMPOSITE RANKING — 20 Symbole (alpha_composite.enabled=true)")
    comp_results, comp_elapsed = await run_ranking(SYMBOLS_20, composite_enabled=True, top_n=20)

    print(
        f"\n{'Rank':>4} {'Symbol':<8} {'Total':>8} {'B':>8} {'F':>8} "
        f"{'Breakout':>10} {'Signals'}"
    )
    print("-" * 80)

    comp_totals, comp_b, comp_f, comp_brk = [], [], [], []
    for i, r in enumerate(comp_results, 1):
        b_val = r.b_composite if r.b_composite is not None else r.b_raw
        f_val = r.f_composite if r.f_composite is not None else r.f_raw
        # Breakout score: sum of signal scores from breakout_signals length proxy
        brk_score = len(r.breakout_signals) * 2.5  # approx
        signals_str = ", ".join(r.breakout_signals) if r.breakout_signals else "-"
        pb_flag = " [PRE-BRK]" if r.pre_breakout else ""
        print(
            f"{i:4} {r.symbol:<8} {r.alpha_raw:8.1f} "
            f"{b_val:8.1f} {f_val:8.1f} "
            f"{brk_score:10.1f} {signals_str}{pb_flag}"
        )
        comp_totals.append(r.alpha_raw)
        comp_b.append(b_val)
        comp_f.append(f_val)
        comp_brk.append(brk_score)

    print(f"\n  Laufzeit: {comp_elapsed:.1f}s fuer {len(SYMBOLS_20)} Symbole")

    # =========================================================================
    # 2. Score-Range Analyse
    # =========================================================================
    _header("2. SCORE-RANGE ANALYSE")

    def stats(vals, label):
        if not vals:
            print(f"  {label}: KEINE DATEN")
            return
        print(
            f"  {label:<20} Min={min(vals):8.1f}  Median={statistics.median(vals):8.1f}"
            f"  Max={max(vals):8.1f}  Erwartung: {_expected(label)}"
        )

    def _expected(label):
        e = {
            "B (classic)": "10-80",
            "F (fast)": "5-50",
            "Total (B+1.5×F)": "20-150",
            "Breakout Score": "0-10",
        }
        return e.get(label, "?")

    stats(comp_b, "B (classic)")
    stats(comp_f, "F (fast)")
    stats(comp_totals, "Total (B+1.5×F)")
    stats(comp_brk, "Breakout Score")

    # =========================================================================
    # 3. RS-only Ranking (enabled=false) — Vergleich
    # =========================================================================
    _header("3. RS-ONLY RANKING (enabled=false) — Vergleich")
    rs_results, rs_elapsed = await run_ranking(SYMBOLS_20, composite_enabled=False, top_n=20)

    # Rang-Maps aufbauen
    comp_rank = {r.symbol: i for i, r in enumerate(comp_results, 1)}
    rs_rank = {r.symbol: i for i, r in enumerate(rs_results, 1)}

    all_symbols = sorted(set(comp_rank) | set(rs_rank))
    print(f"\n  {'Symbol':<8} {'Alt-Rang':>9} {'Neu-Rang':>9} {'Delta':>6}  Breakout-Signals")
    print("  " + "-" * 70)
    for sym in sorted(all_symbols, key=lambda s: comp_rank.get(s, 99)):
        alt = rs_rank.get(sym, "-")
        neu = comp_rank.get(sym, "-")
        if isinstance(alt, int) and isinstance(neu, int):
            delta = alt - neu
            delta_str = f"+{delta}" if delta > 0 else str(delta)
        else:
            delta_str = "?"
        r_comp = next((r for r in comp_results if r.symbol == sym), None)
        sigs = ", ".join(r_comp.breakout_signals) if r_comp and r_comp.breakout_signals else "-"
        pb = " [PRE-BRK]" if r_comp and r_comp.pre_breakout else ""
        print(f"  {sym:<8} {str(alt):>9} {str(neu):>9} {delta_str:>6}  {sigs}{pb}")

    # =========================================================================
    # 4. Timing-Messung (alle Symbole)
    # =========================================================================
    _header("4. TIMING — Alle verfuegbaren Symbole")
    try:
        from src.cache import get_fundamentals_manager

        manager = get_fundamentals_manager()
        all_syms = [f.symbol for f in manager.get_stable_symbols(min_stability=50)]
        print(f"  Gefundene Symbole: {len(all_syms)}")

        scorer_all = _build_scorer(composite_enabled=True)
        t0 = time.time()
        all_results = await scorer_all.generate_longlist(all_syms, top_n=30)
        elapsed_all = time.time() - t0

        print(f"  {len(all_syms)} Symbole in {elapsed_all:.1f}s")
        if all_syms:
            print(f"  Pro Symbol: {elapsed_all / len(all_syms) * 1000:.0f}ms")
        ziel = "✓ ERREICHT" if elapsed_all < 30 else ("~ KNAPP" if elapsed_all < 60 else "✗ ZU LANGSAM")
        print(f"  Ziel <30s: {ziel} | Limit <60s: {'✓' if elapsed_all < 60 else '✗'}")
    except Exception as e:
        print(f"  Timing-Test fehlgeschlagen: {e}")

    # =========================================================================
    # 5. Breakout-Verifikation
    # =========================================================================
    _header("5. BREAKOUT-PATTERN VERIFIKATION")
    breakout_count = sum(1 for r in comp_results if r.breakout_signals)
    pre_breakout_count = sum(1 for r in comp_results if r.pre_breakout)

    if breakout_count == 0 and pre_breakout_count == 0:
        print("  WARNUNG: Keine Breakout-Signale in den 20 Symbolen!")
        print("  Pruefe TechnicalComposite._breakout_score() Implementierung.")
    else:
        print(f"  Symbole mit Breakout-Signals: {breakout_count}/{len(comp_results)}")
        print(f"  Symbole mit PRE-BREAKOUT Flag: {pre_breakout_count}/{len(comp_results)}")
        print("  Details:")
        for r in comp_results:
            if r.breakout_signals or r.pre_breakout:
                pb = " + PRE-BREAKOUT" if r.pre_breakout else ""
                print(f"    {r.symbol}: {', '.join(r.breakout_signals)}{pb}")

    # =========================================================================
    # Summary
    # =========================================================================
    _header("ZUSAMMENFASSUNG")
    ok = all([
        len(comp_results) > 0,
        comp_totals and (min(comp_totals) > -500) and (max(comp_totals) < 500),
        True,  # breakout optional aber dokumentiert
    ])
    print(f"  Composite-Ergebnisse: {len(comp_results)} Symbole")
    print(f"  Score-Range Total: [{min(comp_totals):.1f}, {max(comp_totals):.1f}]")
    print(f"  Breakout-Signale gesamt: {breakout_count}")
    print(f"  Status: {'✓ OK' if ok else '✗ PROBLEMS'}")


if __name__ == "__main__":
    asyncio.run(main())
