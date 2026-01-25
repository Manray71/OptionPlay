#!/usr/bin/env python3
"""
OptionPlay - MarketData.app Live Test
=====================================

Testet die Verbindung zu MarketData.app und führt einen Mini-Scan durch.

Verwendung:
    # Mit .env Datei:
    python scripts/test_marketdata_live.py
    
    # Oder mit Environment Variable:
    MARKETDATA_API_KEY=your_key python scripts/test_marketdata_live.py
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# Projekt-Root zum Path hinzufügen
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# .env laden falls vorhanden
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


async def test_connection(provider):
    """Testet die API-Verbindung"""
    print("\n" + "="*60)
    print("1. VERBINDUNGSTEST")
    print("="*60)
    
    connected = await provider.connect()
    
    if connected:
        print("✅ Verbindung erfolgreich!")
        return True
    else:
        print("❌ Verbindung fehlgeschlagen!")
        return False


async def test_quote(provider, symbol="AAPL"):
    """Testet Quote-Abruf"""
    print("\n" + "="*60)
    print(f"2. QUOTE TEST - {symbol}")
    print("="*60)
    
    quote = await provider.get_quote(symbol)
    
    if quote:
        print(f"✅ {symbol} Quote erhalten:")
        print(f"   Last:   ${quote.last:.2f}")
        print(f"   Bid:    ${quote.bid:.2f}" if quote.bid else "   Bid:    N/A")
        print(f"   Ask:    ${quote.ask:.2f}" if quote.ask else "   Ask:    N/A")
        print(f"   Volume: {quote.volume:,}" if quote.volume else "   Volume: N/A")
        return quote
    else:
        print(f"❌ Kein Quote für {symbol}")
        return None


async def test_historical(provider, symbol="AAPL", days=30):
    """Testet historische Daten"""
    print("\n" + "="*60)
    print(f"3. HISTORICAL TEST - {symbol} ({days} Tage)")
    print("="*60)
    
    bars = await provider.get_historical(symbol, days=days)
    
    if bars:
        print(f"✅ {len(bars)} Bars erhalten")
        print(f"   Zeitraum: {bars[0].date} bis {bars[-1].date}")
        print(f"   Letzter Close: ${bars[-1].close:.2f}")
        
        # Performance berechnen
        if len(bars) >= 2:
            perf = ((bars[-1].close / bars[0].close) - 1) * 100
            print(f"   Performance: {perf:+.1f}%")
        
        return bars
    else:
        print(f"❌ Keine historischen Daten für {symbol}")
        return None


async def test_options_chain(provider, symbol="AAPL"):
    """Testet Options-Chain"""
    print("\n" + "="*60)
    print(f"4. OPTIONS CHAIN TEST - {symbol}")
    print("="*60)
    
    chain = await provider.get_option_chain(symbol, dte_min=30, dte_max=60, right="P")
    
    if chain:
        print(f"✅ {len(chain)} Put-Optionen erhalten")
        
        # Gruppiere nach Expiration
        expirations = {}
        for opt in chain:
            exp = opt.expiry
            if exp not in expirations:
                expirations[exp] = []
            expirations[exp].append(opt)
        
        print(f"   Verfallstermine: {len(expirations)}")
        
        for exp, opts in sorted(expirations.items())[:2]:
            print(f"\n   {exp}:")
            # Zeige 3 Optionen nahe ATM
            sorted_opts = sorted(opts, key=lambda x: x.strike)
            for opt in sorted_opts[:3]:
                iv_str = f"{opt.implied_volatility*100:.1f}%" if opt.implied_volatility else "N/A"
                delta_str = f"{opt.delta:.2f}" if opt.delta else "N/A"
                print(f"      ${opt.strike:.0f} P | Bid: ${opt.bid:.2f} | Ask: ${opt.ask:.2f} | IV: {iv_str} | Δ: {delta_str}")
        
        return chain
    else:
        print(f"❌ Keine Options-Chain für {symbol}")
        return None


async def test_earnings(provider, symbol="AAPL"):
    """Testet Earnings-Daten"""
    print("\n" + "="*60)
    print(f"5. EARNINGS TEST - {symbol}")
    print("="*60)
    
    earnings = await provider.get_earnings_date(symbol)
    
    if earnings and earnings.earnings_date:
        print(f"✅ Earnings-Datum gefunden:")
        print(f"   Datum: {earnings.earnings_date}")
        print(f"   Tage bis Earnings: {earnings.days_to_earnings}")
        print(f"   Quelle: {earnings.source.value}")
        return earnings
    else:
        print(f"⚠️  Kein Earnings-Datum für {symbol} gefunden")
        return None


async def test_vix(provider):
    """Testet VIX-Abruf"""
    print("\n" + "="*60)
    print("6. VIX TEST")
    print("="*60)
    
    vix = await provider.get_vix()
    
    if vix:
        print(f"✅ VIX: {vix:.2f}")
        
        if vix < 15:
            print("   → Niedriges Volatilitätsumfeld")
        elif vix < 20:
            print("   → Normales Volatilitätsumfeld")
        elif vix < 30:
            print("   → Erhöhte Volatilität")
        else:
            print("   → Hohe Volatilität / Panik")
        
        return vix
    else:
        print("❌ Kein VIX-Wert erhalten")
        return None


async def test_scanner_integration(provider, symbols):
    """Testet Scanner-Integration"""
    print("\n" + "="*60)
    print(f"7. SCANNER INTEGRATION TEST ({len(symbols)} Symbole)")
    print("="*60)
    
    from scanner import MultiStrategyScanner, ScanMode, ScanConfig
    
    # Scanner konfigurieren
    config = ScanConfig(
        min_score=4.0,
        max_total_results=10,
        enable_pullback=True,
        enable_ath_breakout=True,
        enable_bounce=True,
        enable_earnings_dip=False  # Braucht spezielle Daten
    )
    
    scanner = MultiStrategyScanner(config)
    
    # Data Fetcher erstellen
    async def data_fetcher(symbol):
        return await provider.get_historical_for_scanner(symbol, days=260)
    
    # Scan durchführen
    print(f"   Scanne {symbols}...")
    
    result = await scanner.scan_async(
        symbols=symbols,
        data_fetcher=data_fetcher,
        mode=ScanMode.ALL
    )
    
    print(f"\n✅ Scan abgeschlossen!")
    print(f"   Symbole gescannt: {result.symbols_scanned}")
    print(f"   Symbole mit Signalen: {result.symbols_with_signals}")
    print(f"   Gesamte Signale: {result.total_signals}")
    print(f"   Dauer: {result.scan_duration_seconds:.2f}s")
    
    if result.signals:
        print("\n   TOP SIGNALE:")
        for i, signal in enumerate(result.signals[:5], 1):
            print(f"   {i}. {signal.symbol:6} | {signal.strategy:15} | Score: {signal.score:.1f}")
    
    return result


async def main():
    """Hauptfunktion"""
    print("\n" + "="*60)
    print("  OPTIONPLAY - MARKETDATA.APP LIVE TEST")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # API Key prüfen
    api_key = os.environ.get("MARKETDATA_API_KEY")
    
    if not api_key or api_key == "your_api_key_here":
        print("\n❌ FEHLER: Kein API Key gefunden!")
        print("\nBitte setze den API Key:")
        print("  1. Erstelle .env Datei mit: MARKETDATA_API_KEY=dein_key")
        print("  2. Oder: export MARKETDATA_API_KEY=dein_key")
        return
    
    print(f"\n🔑 API Key: {api_key[:8]}...{api_key[-4:]}")
    
    # Provider erstellen
    from data_providers import MarketDataProvider
    
    async with MarketDataProvider(api_key) as provider:
        # Tests durchführen
        if not await test_connection(provider):
            return
        
        await test_quote(provider, "AAPL")
        await test_historical(provider, "AAPL", days=30)
        await test_options_chain(provider, "AAPL")
        await test_earnings(provider, "AAPL")
        await test_vix(provider)
        
        # Scanner-Test mit einigen Symbolen
        test_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        await test_scanner_integration(provider, test_symbols)
    
    print("\n" + "="*60)
    print("  ALLE TESTS ABGESCHLOSSEN")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
