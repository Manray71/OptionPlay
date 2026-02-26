#!/usr/bin/env python3
"""
AMD Debug Trace — Verfolgt AMD durch JEDEN Filter und Analyzer.

Zeigt exakt:
1. Earnings Pre-Filter Ergebnis
2. Stability/Fundamentals Pre-Filter Ergebnis
3. Volume-Daten (was kommt rein?)
4. Jeder Analyzer einzeln + Score
5. Wo genau AMD rausfliegt

Usage:
    cd OptionPlay && python scripts/debug_amd_trace.py
"""

import asyncio
import sys
import os
from datetime import date, timedelta
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SYMBOL = "AMD"
DIVIDER = "=" * 70


def header(text: str):
    print(f"\n{DIVIDER}")
    print(f"  {text}")
    print(DIVIDER)


async def main():
    print(f"AMD DEBUG TRACE — {date.today()}")
    print(f"{'=' * 70}")

    # =========================================================================
    # 1. EARNINGS PRE-FILTER
    # =========================================================================
    header("1. EARNINGS PRE-FILTER")

    try:
        from src.cache import get_earnings_history_manager

        em = get_earnings_history_manager()

        # Direkte Safety-Prüfung
        is_safe, days_to, reason = em.is_earnings_day_safe(SYMBOL, date.today())
        print(f"  is_earnings_day_safe('{SYMBOL}', {date.today()}):")
        print(f"    is_safe    = {is_safe}")
        print(f"    days_to    = {days_to}")
        print(f"    reason     = {reason}")

        # Alle Earnings-Daten
        all_earnings = em.get_all_earnings(SYMBOL)
        if all_earnings:
            print(f"\n  Alle Earnings für {SYMBOL} ({len(all_earnings)} Einträge):")
            for e in all_earnings[:10]:
                days_diff = (e.earnings_date - date.today()).days
                print(
                    f"    {e.earnings_date} ({e.time_of_day or '?'}) — "
                    f"EPS: {e.eps_actual} vs {e.eps_estimate} — "
                    f"{'ZUKUNFT' if days_diff > 0 else f'vor {abs(days_diff)} Tagen'}"
                )
        else:
            print(f"  KEINE Earnings-Daten für {SYMBOL} in der DB!")

        # Next future earnings
        next_e = em.get_next_future_earnings(SYMBOL, date.today())
        if next_e:
            days_to_next = (next_e.earnings_date - date.today()).days
            print(
                f"\n  Nächste Future Earnings: {next_e.earnings_date} "
                f"({next_e.time_of_day or '?'}) — in {days_to_next} Tagen"
            )
        else:
            print(f"\n  Keine zukünftigen Earnings gefunden")

        # Simulate what the MCP pre-filter would do
        print(f"\n  MCP Pre-Filter Simulation:")
        print(f"    Normal strategies (min_days=60): ", end="")
        if is_safe:
            print("PASS")
        else:
            print(f"BLOCKED — {reason}")

        # Earnings Dip check: needs -10 <= days_to <= 0
        print(f"    Earnings Dip (need -10..0 days): ", end="")
        if days_to is not None and -10 <= days_to <= 0:
            print(f"PASS (days_to={days_to})")
        else:
            print(f"BLOCKED (days_to={days_to})")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback

        traceback.print_exc()

    # =========================================================================
    # 2. FUNDAMENTALS / STABILITY PRE-FILTER
    # =========================================================================
    header("2. FUNDAMENTALS / STABILITY PRE-FILTER")

    try:
        from src.cache import get_fundamentals_manager

        fm = get_fundamentals_manager()

        f = fm.get_fundamentals(SYMBOL)
        if f:
            print(f"  Symbol:            {f.symbol}")
            print(f"  Sector:            {f.sector}")
            print(f"  Stability Score:   {f.stability_score}")
            print(f"  Win Rate:          {f.historical_win_rate}")
            print(f"  Avg Drawdown:      {f.avg_drawdown}")
            print(f"  Market Cap:        {f.market_cap_category}")
            print(f"  Beta:              {f.beta}")
            print(f"  Current Price:     {f.current_price}")
            print(f"  Earnings Beat:     {f.earnings_beat_rate}")

            # Simulate pre-filter
            min_stability = 50.0  # From config
            min_win_rate = 0.0  # Default
            print(f"\n  Pre-Filter Check:")
            print(f"    Stability >= {min_stability}: ", end="")
            if f.stability_score is not None and f.stability_score >= min_stability:
                print(f"PASS ({f.stability_score:.1f})")
            elif f.stability_score is None:
                print(f"PASS (no score = durchlassen)")
            else:
                print(f"BLOCKED ({f.stability_score:.1f} < {min_stability})")

            print(f"    Price $20-$1500: ", end="")
            if f.current_price and 20 <= f.current_price <= 1500:
                print(f"PASS (${f.current_price:.2f})")
            else:
                print(f"BLOCKED (${f.current_price})")
        else:
            print(f"  KEINE Fundamentals für {SYMBOL} — wird durchgelassen")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback

        traceback.print_exc()

    # =========================================================================
    # 3. HISTORICAL DATA / VOLUME CHECK
    # =========================================================================
    header("3. HISTORICAL DATA & VOLUME")

    prices = volumes = highs = lows = opens = None
    data_source = "none"

    # Try local DB first (like the real scanner)
    try:
        from src.data_providers.local_db import LocalDBProvider

        local_db = LocalDBProvider()

        if local_db.is_available():
            data = await local_db.get_historical_for_scanner(SYMBOL, days=260)
            if data:
                prices, volumes, highs, lows, opens = data
                data_source = "local_db"
                print(f"  Quelle: Lokale DB (~/.optionplay/trades.db)")
                print(f"  Datenpunkte: {len(prices)}")
                print(f"  Zeitraum: ~{len(prices)} Trading-Tage")
                print(f"  Letzter Preis: ${prices[-1]:.2f}")
                print(f"\n  VOLUME-ANALYSE:")
                non_zero = [v for v in volumes if v > 0]
                print(f"    Volumes total:    {len(volumes)}")
                print(f"    Volumes non-zero: {len(non_zero)}")
                print(f"    Volumes == 0:     {len(volumes) - len(non_zero)}")
                print(f"    Letzte 5 Volumes: {volumes[-5:]}")
                all_zero = all(v == 0 for v in volumes)
                if all_zero:
                    print(f"    >>> ALLE VOLUMES SIND 0! <<<")
                    print(f"    >>> LocalDB hat keine Volume-Daten <<<")
                    print(f"    >>> Volume-Fallback findet KEINEN non-zero Wert <<<")

                print(f"\n  OHLC-ANALYSE:")
                prices_eq_highs = prices == highs
                prices_eq_lows = prices == lows
                print(f"    Prices == Highs: {prices_eq_highs}")
                print(f"    Prices == Lows:  {prices_eq_lows}")
                if prices_eq_highs and prices_eq_lows:
                    print(f"    >>> HIGHS = LOWS = CLOSE! <<<")
                    print(f"    >>> Support/Resistance-Erkennung unmöglich <<<")
                    print(f"    >>> Bounce-Analyse bekommt falsche Daten <<<")
            else:
                print(f"  Lokale DB: Keine Daten für {SYMBOL}")
        else:
            print(f"  Lokale DB nicht verfügbar")
    except Exception as e:
        print(f"  LocalDB Error: {e}")

    # Try API if no local data or to compare
    api_data = None
    try:
        tradier_key = os.environ.get("TRADIER_API_KEY", "")
        if tradier_key:
            from src.data_providers import TradierProvider

            async with TradierProvider(api_key=tradier_key, environment="production") as tradier:
                api_data = await tradier.get_historical_for_scanner(SYMBOL, days=260)
                if api_data:
                    ap, av, ah, al, ao = api_data
                    print(f"\n  Vergleich: Tradier API")
                    print(f"    Datenpunkte: {len(ap)}")
                    print(f"    Letzter Preis: ${ap[-1]:.2f}")
                    non_zero_api = [v for v in av if v > 0]
                    print(f"    Volumes non-zero: {len(non_zero_api)}/{len(av)}")
                    print(f"    Letzte 5 Volumes: {av[-5:]}")
                    print(f"    Letzte 5 Highs:   {[f'{h:.2f}' for h in ah[-5:]]}")
                    print(f"    Letzte 5 Lows:    {[f'{l:.2f}' for l in al[-5:]]}")
                    print(f"    Letzte 5 Closes:  {[f'{p:.2f}' for p in ap[-5:]]}")

                    if data_source == "local_db":
                        # Use API data for analyzer testing since it has real OHLCV
                        print(f"\n    >>> Verwende API-Daten für Analyzer-Tests <<<")
                        prices, volumes, highs, lows, opens = api_data
                        data_source = "tradier_api"
        else:
            print(f"\n  Kein TRADIER_API_KEY gesetzt — kein API-Vergleich")

        if not tradier_key or not api_data:
            mdata_key = os.environ.get("MARKETDATA_API_KEY", "")
            if mdata_key:
                from src.data_providers import MarketDataProvider

                async with MarketDataProvider(api_key=mdata_key) as mdp:
                    api_data = await mdp.get_historical_for_scanner(SYMBOL, days=260)
                    if api_data:
                        ap, av, ah, al, ao = api_data
                        print(f"\n  Vergleich: Marketdata.app API")
                        print(f"    Datenpunkte: {len(ap)}")
                        non_zero_api = [v for v in av if v > 0]
                        print(f"    Volumes non-zero: {len(non_zero_api)}/{len(av)}")
                        print(f"    Letzte 5 Volumes: {av[-5:]}")

                        if data_source == "local_db":
                            prices, volumes, highs, lows, opens = api_data
                            data_source = "marketdata_api"
    except Exception as e:
        print(f"  API Error: {e}")

    if prices is None:
        print(f"\n  KEINE DATEN — Kann Analyzer nicht testen!")
        return

    # =========================================================================
    # 4. CONTEXT-BERECHNUNG
    # =========================================================================
    header("4. ANALYSIS CONTEXT")

    try:
        from src.analyzers.context import AnalysisContext

        ctx = AnalysisContext.from_data(
            symbol=SYMBOL,
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows,
            opens=opens,
            calculate_all=True,
            regime="normal",
            sector="Technology",
        )
        print(f"  Current Price:   ${ctx.current_price:.2f}")
        print(f"  Current Volume:  {ctx.current_volume:,}")
        print(
            f"  Volume Ratio:    {ctx.volume_ratio:.2f}x"
            if ctx.volume_ratio
            else "  Volume Ratio:    N/A"
        )
        print(
            f"  Avg Volume 20d:  {ctx.avg_volume_20:,.0f}"
            if ctx.avg_volume_20
            else "  Avg Volume 20d:  N/A"
        )
        print(f"  RSI 14:          {ctx.rsi_14:.1f}" if ctx.rsi_14 else "  RSI 14:          N/A")
        print(f"  SMA 20:          ${ctx.sma_20:.2f}" if ctx.sma_20 else "  SMA 20:          N/A")
        print(f"  SMA 50:          ${ctx.sma_50:.2f}" if ctx.sma_50 else "  SMA 50:          N/A")
        print(f"  SMA 200:         ${ctx.sma_200:.2f}" if ctx.sma_200 else "  SMA 200:         N/A")
        print(f"  Trend:           {ctx.trend}" if ctx.trend else "  Trend:           N/A")
        print(
            f"  ATH:             ${ctx.all_time_high:.2f}"
            if ctx.all_time_high
            else "  ATH:             N/A"
        )
        print(
            f"  % from ATH:      {ctx.pct_from_ath:.1f}%"
            if ctx.pct_from_ath is not None
            else "  % from ATH:      N/A"
        )

        if ctx.current_volume == 0:
            print(f"\n  >>> current_volume ist 0 — Volume-Fallback hat NICHT gegriffen <<<")
            print(f"  >>> URSACHE: Alle Volumes in der Liste sind 0 <<<")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback

        traceback.print_exc()

    # =========================================================================
    # 5. JEDER ANALYZER EINZELN
    # =========================================================================
    header("5. ANALYZER-ERGEBNISSE")

    analyzers_to_test = []

    # 5a. Pullback
    try:
        from src.analyzers import PullbackAnalyzer

        analyzers_to_test.append(("Pullback", PullbackAnalyzer(), {}))
    except Exception as e:
        print(f"  PullbackAnalyzer Import Error: {e}")

    # 5b. Bounce
    try:
        from src.analyzers import BounceAnalyzer, BounceConfig

        analyzers_to_test.append(("Bounce", BounceAnalyzer(), {}))
    except Exception as e:
        print(f"  BounceAnalyzer Import Error: {e}")

    # 5c. ATH Breakout
    try:
        from src.analyzers import ATHBreakoutAnalyzer, ATHBreakoutConfig

        analyzers_to_test.append(("ATH Breakout", ATHBreakoutAnalyzer(), {}))
    except Exception as e:
        print(f"  ATHBreakoutAnalyzer Import Error: {e}")

    # 5d. Earnings Dip
    try:
        from src.analyzers import EarningsDipAnalyzer, EarningsDipConfig

        # Earnings Dip braucht extra Params
        em = get_earnings_history_manager()
        all_earnings = em.get_all_earnings(SYMBOL)
        earnings_kwargs = {}

        if all_earnings:
            # Find most recent past earnings
            past = [e for e in all_earnings if (e.earnings_date - date.today()).days <= 0]
            if past:
                last_e = past[0]
                days_since = (date.today() - last_e.earnings_date).days
                earnings_kwargs["earnings_date"] = last_e.earnings_date
                earnings_kwargs["next_earnings_days"] = None

                # Pre-earnings price (10 days before)
                if days_since <= 10 and len(prices) > days_since + 1:
                    earnings_kwargs["pre_earnings_price"] = prices[-(days_since + 1)]

        fm = get_fundamentals_manager()
        f = fm.get_fundamentals(SYMBOL)
        if f and f.stability_score:
            earnings_kwargs["stability_score"] = f.stability_score

        analyzers_to_test.append(("Earnings Dip", EarningsDipAnalyzer(), earnings_kwargs))
    except Exception as e:
        print(f"  EarningsDipAnalyzer Import Error: {e}")

    # 5e. Trend Continuation
    try:
        from src.analyzers import TrendContinuationAnalyzer, TrendContinuationConfig

        analyzers_to_test.append(("Trend Continuation", TrendContinuationAnalyzer(), {}))
    except Exception as e:
        print(f"  TrendContinuationAnalyzer Import Error: {e}")

    for name, analyzer, extra_kwargs in analyzers_to_test:
        print(f"\n  --- {name} ---")
        try:
            signal = analyzer.analyze(
                SYMBOL, prices, volumes, highs, lows, context=ctx, **extra_kwargs
            )

            print(f"    Signal Type:  {signal.signal_type}")
            print(f"    Strength:     {signal.strength}")
            print(f"    Score:        {signal.score}")
            print(f"    Reason:       {signal.reason}")

            if signal.entry_price:
                print(f"    Entry:        ${signal.entry_price:.2f}")
            if signal.stop_loss:
                print(f"    Stop Loss:    ${signal.stop_loss:.2f}")
            if signal.target_price:
                print(f"    Target:       ${signal.target_price:.2f}")

            if signal.warnings:
                print(f"    Warnings:     {signal.warnings}")

            # Details
            if signal.details:
                vol_ratio = signal.details.get("volume_ratio")
                if vol_ratio is not None:
                    print(f"    Volume Ratio: {vol_ratio:.2f}x")

                components = signal.details.get("components", {})
                if components:
                    print(f"    Components:")
                    for k, v in components.items():
                        print(f"      {k}: {v}")

                score_bd = signal.details.get("score_breakdown")
                if score_bd and isinstance(score_bd, dict):
                    print(f"    Score Breakdown:")
                    for k, v in score_bd.items():
                        if isinstance(v, (int, float)) and not k.startswith("_"):
                            print(f"      {k}: {v}")

            # Actionable?
            from src.models.base import SignalType

            is_actionable = signal.signal_type in (SignalType.LONG, SignalType.SHORT)
            min_score = 3.5
            print(f"    Actionable:   {is_actionable}")
            print(f"    Score >= {min_score}: {signal.score >= min_score}")
            if not is_actionable:
                print(f"    >>> DISQUALIFIED: {signal.reason}")

        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback

            traceback.print_exc()

    # =========================================================================
    # 6. ZUSAMMENFASSUNG
    # =========================================================================
    header("6. ZUSAMMENFASSUNG")

    print(f"  Symbol:      {SYMBOL}")
    print(f"  Datenquelle: {data_source}")
    print(f"  Datenpunkte: {len(prices)}")

    if data_source == "local_db":
        print(f"\n  ROOT CAUSE:")
        print(f"  Die lokale DB liefert:")
        print(f"    - volumes = [0, 0, 0, ...] (ALLE NULL)")
        print(f"    - highs = lows = prices (IDENTISCH)")
        print(f"  Das bedeutet:")
        print(f"    1. Volume-Fallback findet keinen non-zero Wert")
        print(f"    2. Volume-Ratio = 0 → Dead Cat Bounce Filter killt Bounce-Signals")
        print(f"    3. Identische High/Low → Support-Erkennung kaputt")
        print(f"    4. Keine echte Candle-Analyse möglich")
        print(f"\n  FIX BENÖTIGT:")
        print(f"    LocalDBProvider._get_historical_for_scanner_sync()")
        print(f"    muss echte OHLCV-Daten liefern, NICHT:")
        print(f"      volumes = [0] * len(prices)")
        print(f"      highs = prices.copy()")
        print(f"      lows = prices.copy()")

    all_zero = all(v == 0 for v in volumes) if volumes else True
    if all_zero and data_source != "local_db":
        print(f"\n  WARNUNG: Auch API-Daten haben Volume=0!")


if __name__ == "__main__":
    asyncio.run(main())
