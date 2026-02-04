# OptionPlay - Market Scanner
# =============================
# Scannt Watchlist mit allen verfügbaren Analyzern

import asyncio
import logging
from typing import List, Dict, Optional, Type
from datetime import datetime

try:
    from ..analyzers.base import BaseAnalyzer
    from ..models.base import TradeSignal, SignalType
except ImportError:
    from analyzers.base import BaseAnalyzer
    from models.base import TradeSignal, SignalType

logger = logging.getLogger(__name__)


class MarketScanner:
    """
    Scannt eine Watchlist mit mehreren Strategien parallel.
    
    Verwendung:
        scanner = MarketScanner()
        scanner.register_analyzer(PullbackAnalyzer(config))
        scanner.register_analyzer(BreakoutAnalyzer(config))
        
        results = await scanner.scan(symbols, data_provider)
    """
    
    def __init__(self):
        self._analyzers: List[BaseAnalyzer] = []
        self._last_scan: Optional[datetime] = None
    
    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """
        Registriert einen Analyzer für den Scan.
        
        Args:
            analyzer: Instanz eines BaseAnalyzer
        """
        self._analyzers.append(analyzer)
        logger.info(f"Registered analyzer: {analyzer.strategy_name}")
    
    def get_analyzers(self) -> List[str]:
        """Gibt Namen aller registrierten Analyzer zurück"""
        return [a.strategy_name for a in self._analyzers]
    
    async def scan_symbol(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        **kwargs
    ) -> List[TradeSignal]:
        """
        Scannt ein Symbol mit allen registrierten Analyzern.
        
        Returns:
            Liste von TradeSignals (eins pro Analyzer)
        """
        signals = []
        
        for analyzer in self._analyzers:
            try:
                signal = analyzer.analyze(
                    symbol=symbol,
                    prices=prices,
                    volumes=volumes,
                    highs=highs,
                    lows=lows,
                    **kwargs
                )
                signals.append(signal)
            except Exception as e:
                logger.warning(f"Error in {analyzer.strategy_name} for {symbol}: {e}")
                # Neutrales Signal bei Fehler
                signals.append(analyzer.create_neutral_signal(
                    symbol, prices[-1] if prices else 0, f"Error: {e}"
                ))
        
        return signals
    
    async def scan(
        self,
        symbols: List[str],
        data_fetcher,  # Callable[[str], Tuple[prices, volumes, highs, lows]]
        min_score: float = 5.0,
        strategies: Optional[List[str]] = None,
        max_concurrent: int = 10
    ) -> Dict[str, List[TradeSignal]]:
        """
        Scannt alle Symbole mit allen Analyzern (parallelisiert).

        Args:
            symbols: Liste der zu scannenden Symbole
            data_fetcher: Async function to fetch price data
            min_score: Minimaler Score für Ergebnisse
            strategies: Optional: Nur diese Strategien verwenden
            max_concurrent: Maximum concurrent data fetches (default: 10)

        Returns:
            Dict mit Symbol -> Liste von Signals
        """
        self._last_scan = datetime.now()
        results: Dict[str, List[TradeSignal]] = {}

        # Filter Analyzer wenn strategies angegeben
        analyzers = self._analyzers
        if strategies:
            analyzers = [a for a in self._analyzers if a.strategy_name in strategies]

        if not analyzers:
            logger.warning("No analyzers registered or selected")
            return results

        logger.info(f"Scanning {len(symbols)} symbols with {len(analyzers)} analyzers")

        # Phase 1: Fetch all data in parallel
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_data(symbol: str):
            async with semaphore:
                try:
                    return (symbol, await data_fetcher(symbol))
                except Exception as e:
                    logger.error(f"Failed to fetch data for {symbol}: {e}")
                    return (symbol, None)

        fetch_tasks = [fetch_data(symbol) for symbol in symbols]
        fetched_data = await asyncio.gather(*fetch_tasks)

        # Phase 2: Analyze all fetched data (CPU-bound, but fast)
        for symbol, data in fetched_data:
            if not data:
                continue

            try:
                prices, volumes, highs, lows, *_ = data

                # Alle Analyzer anwenden
                symbol_signals = []
                for analyzer in analyzers:
                    try:
                        signal = analyzer.analyze(symbol, prices, volumes, highs, lows)
                        if signal.score >= min_score:
                            symbol_signals.append(signal)
                    except Exception as e:
                        logger.debug(f"{analyzer.strategy_name} failed for {symbol}: {e}")

                if symbol_signals:
                    results[symbol] = symbol_signals

            except Exception as e:
                logger.error(f"Failed to analyze {symbol}: {e}")

        logger.info(f"Scan complete: {len(results)} symbols with signals")
        return results
    
    def get_top_signals(
        self,
        scan_results: Dict[str, List[TradeSignal]],
        top_n: int = 10,
        signal_type: Optional[SignalType] = None
    ) -> List[TradeSignal]:
        """
        Extrahiert die Top-N Signale aus Scan-Ergebnissen.
        
        Args:
            scan_results: Ergebnis von scan()
            top_n: Anzahl der Top-Signale
            signal_type: Optional: Nur dieser Signal-Typ
            
        Returns:
            Liste der besten Signale, sortiert nach Score
        """
        all_signals = []
        
        for symbol, signals in scan_results.items():
            for signal in signals:
                if signal_type and signal.signal_type != signal_type:
                    continue
                all_signals.append(signal)
        
        # Nach Score sortieren
        all_signals.sort(key=lambda x: x.score, reverse=True)
        
        return all_signals[:top_n]
