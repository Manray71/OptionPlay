# OptionPlay - Multi-Strategy Scanner
# =====================================
# Kombiniert alle Analyzer für umfassendes Market Scanning
#
# Features:
# - Parallel-Scanning mit allen registrierten Analyzern
# - Ranking und Aggregation von Signalen
# - Filter nach Strategie, Score, Signal-Typ
# - Earnings-Filter Integration
# - Export-Funktionen

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Tuple, Any
from datetime import datetime, date
from enum import Enum

try:
    from ..analyzers.base import BaseAnalyzer
    from ..analyzers.pullback import PullbackAnalyzer
    from ..analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from ..analyzers.bounce import BounceAnalyzer, BounceConfig
    from ..analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..config.config_loader import PullbackScoringConfig
except ImportError:
    from analyzers.base import BaseAnalyzer
    from analyzers.pullback import PullbackAnalyzer
    from analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from analyzers.bounce import BounceAnalyzer, BounceConfig
    from analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
    from models.base import TradeSignal, SignalType, SignalStrength
    from config.config_loader import PullbackScoringConfig

logger = logging.getLogger(__name__)


class ScanMode(Enum):
    """Scan-Modi für verschiedene Anwendungsfälle"""
    ALL = "all"                    # Alle Strategien
    PULLBACK_ONLY = "pullback"    # Nur Pullbacks (für Bull-Put-Spreads)
    BREAKOUT_ONLY = "breakout"    # Nur ATH Breakouts
    BOUNCE_ONLY = "bounce"        # Nur Support Bounces
    EARNINGS_DIP = "earnings_dip" # Nur Earnings Dips
    BEST_SIGNAL = "best"          # Nur bestes Signal pro Symbol


@dataclass
class ScanConfig:
    """Konfiguration für den Scanner"""
    # Score-Filter
    min_score: float = 5.0
    min_actionable_score: float = 6.0
    
    # Earnings-Filter
    exclude_earnings_within_days: int = 60
    
    # IV-Rank Filter (für Credit-Spreads wichtig!)
    iv_rank_minimum: float = 30.0   # Min IV-Rank für ausreichend Prämie
    iv_rank_maximum: float = 80.0   # Max IV-Rank (zu hohe IV = erhöhtes Risiko)
    enable_iv_filter: bool = True   # IV-Filter aktivieren/deaktivieren
    
    # Output-Limits
    max_results_per_symbol: int = 3
    max_total_results: int = 50
    
    # Parallel Processing
    max_concurrent: int = 10
    
    # Data Requirements
    min_data_points: int = 60
    
    # Strategies to enable
    enable_pullback: bool = True
    enable_ath_breakout: bool = True
    enable_bounce: bool = True
    enable_earnings_dip: bool = True


@dataclass
class ScanResult:
    """Ergebnis eines Scans"""
    timestamp: datetime
    symbols_scanned: int
    symbols_with_signals: int
    total_signals: int
    signals: List[TradeSignal]
    errors: List[str] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    
    def get_by_strategy(self, strategy: str) -> List[TradeSignal]:
        """Filtert Signale nach Strategie"""
        return [s for s in self.signals if s.strategy == strategy]
    
    def get_by_symbol(self, symbol: str) -> List[TradeSignal]:
        """Filtert Signale nach Symbol"""
        return [s for s in self.signals if s.symbol == symbol]
    
    def get_actionable(self) -> List[TradeSignal]:
        """Gibt nur actionable Signale zurück"""
        return [s for s in self.signals if s.is_actionable]
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbols_scanned': self.symbols_scanned,
            'symbols_with_signals': self.symbols_with_signals,
            'total_signals': self.total_signals,
            'scan_duration_seconds': self.scan_duration_seconds,
            'signals': [s.to_dict() for s in self.signals],
            'errors': self.errors
        }


# Type alias für Data Fetcher
DataFetcher = Callable[[str], Tuple[List[float], List[int], List[float], List[float]]]
AsyncDataFetcher = Callable[[str], 'asyncio.Future[Tuple[List[float], List[int], List[float], List[float]]]']


class MultiStrategyScanner:
    """
    Multi-Strategie Scanner für umfassendes Market Scanning.
    
    Kombiniert alle verfügbaren Analyzer und bietet:
    - Einheitliches Interface für alle Strategien
    - Ranking und Aggregation
    - Earnings-Filter
    - Async-Support für paralleles Scanning
    
    Verwendung:
        scanner = MultiStrategyScanner()
        
        # Mit async Data Fetcher
        async def fetch_data(symbol):
            return prices, volumes, highs, lows
        
        result = await scanner.scan_async(
            symbols=["AAPL", "MSFT", "GOOGL"],
            data_fetcher=fetch_data
        )
        
        # Top 10 Signale
        for signal in result.signals[:10]:
            print(f"{signal.symbol}: {signal.strategy} - Score {signal.score}")
    """
    
    def __init__(self, config: Optional[ScanConfig] = None):
        self.config = config or ScanConfig()
        self._analyzers: Dict[str, BaseAnalyzer] = {}
        self._earnings_cache: Dict[str, Optional[date]] = {}
        self._iv_cache: Dict[str, Optional[float]] = {}  # Symbol -> IV-Rank
        self._last_scan: Optional[ScanResult] = None
        
        # Registriere Standard-Analyzer
        self._register_default_analyzers()
    
    def _register_default_analyzers(self) -> None:
        """Registriert die Standard-Analyzer basierend auf Config"""
        if self.config.enable_pullback:
            try:
                # PullbackAnalyzer benötigt PullbackScoringConfig
                pullback_config = PullbackScoringConfig()
                self._analyzers['pullback'] = PullbackAnalyzer(pullback_config)
            except Exception as e:
                logger.warning(f"Could not register PullbackAnalyzer: {e}")
        
        if self.config.enable_ath_breakout:
            self._analyzers['ath_breakout'] = ATHBreakoutAnalyzer()
        
        if self.config.enable_bounce:
            self._analyzers['bounce'] = BounceAnalyzer()
        
        if self.config.enable_earnings_dip:
            self._analyzers['earnings_dip'] = EarningsDipAnalyzer()
        
        logger.info(f"Registered {len(self._analyzers)} analyzers: {list(self._analyzers.keys())}")
    
    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """Registriert einen zusätzlichen Analyzer"""
        self._analyzers[analyzer.strategy_name] = analyzer
        logger.info(f"Registered custom analyzer: {analyzer.strategy_name}")
    
    def get_analyzer(self, name: str) -> Optional[BaseAnalyzer]:
        """Gibt einen Analyzer nach Namen zurück"""
        return self._analyzers.get(name)
    
    @property
    def available_strategies(self) -> List[str]:
        """Liste aller verfügbaren Strategien"""
        return list(self._analyzers.keys())
    
    def set_earnings_date(self, symbol: str, earnings_date: Optional[date]) -> None:
        """Setzt das Earnings-Datum für ein Symbol"""
        self._earnings_cache[symbol] = earnings_date
    
    def set_iv_rank(self, symbol: str, iv_rank: Optional[float]) -> None:
        """
        Setzt den IV-Rank für ein Symbol.
        
        Args:
            symbol: Ticker-Symbol
            iv_rank: IV-Rank (0-100) oder None
        """
        self._iv_cache[symbol.upper()] = iv_rank
    
    def set_iv_ranks(self, iv_data: Dict[str, float]) -> None:
        """
        Setzt IV-Ranks für mehrere Symbole.
        
        Args:
            iv_data: Dict mit Symbol -> IV-Rank
        """
        for symbol, iv_rank in iv_data.items():
            self._iv_cache[symbol.upper()] = iv_rank
    
    def _check_iv_filter(self, symbol: str, strategy: str) -> Tuple[bool, Optional[str]]:
        """
        Prüft ob ein Symbol den IV-Filter besteht.
        
        Für Credit-Spreads (Bull-Put-Spreads) wollen wir:
        - Mindest-IV-Rank (für ausreichend Prämie)
        - Maximum-IV-Rank (zu hohe IV = erhöhtes Risiko)
        
        Args:
            symbol: Ticker-Symbol
            strategy: Strategie-Name
            
        Returns:
            Tuple (passes_filter, reason_if_failed)
        """
        # IV-Filter nur für Credit-Spread-Strategien
        if strategy in ['earnings_dip', 'ath_breakout']:
            return True, None
        
        # Filter deaktiviert?
        if not self.config.enable_iv_filter:
            return True, None
        
        iv_rank = self._iv_cache.get(symbol.upper())
        
        # Kein IV-Rank bekannt -> durchlassen (nicht filtern)
        if iv_rank is None:
            return True, None
        
        # Zu niedrige IV -> nicht genug Prämie
        if iv_rank < self.config.iv_rank_minimum:
            return False, f"IV-Rank zu niedrig ({iv_rank:.0f}% < {self.config.iv_rank_minimum:.0f}%)"
        
        # Zu hohe IV -> erhöhtes Risiko
        if iv_rank > self.config.iv_rank_maximum:
            return False, f"IV-Rank zu hoch ({iv_rank:.0f}% > {self.config.iv_rank_maximum:.0f}%)"
        
        return True, None
    
    def _should_skip_for_earnings(self, symbol: str, strategy: str) -> bool:
        """
        Prüft ob ein Symbol wegen Earnings übersprungen werden soll.
        
        Für Bull-Put-Spreads (pullback, bounce) wollen wir keine
        Aktien mit nahen Earnings.
        """
        if strategy == 'earnings_dip':
            # Earnings Dip braucht gerade Earnings
            return False
        
        if self.config.exclude_earnings_within_days <= 0:
            return False
        
        earnings_date = self._earnings_cache.get(symbol)
        if not earnings_date:
            return False  # Kein Datum bekannt -> nicht filtern
        
        days_to_earnings = (earnings_date - date.today()).days
        
        if 0 < days_to_earnings <= self.config.exclude_earnings_within_days:
            logger.debug(f"Skipping {symbol} for {strategy}: earnings in {days_to_earnings} days")
            return True
        
        return False
    
    def analyze_symbol(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        strategies: Optional[List[str]] = None,
        **kwargs
    ) -> List[TradeSignal]:
        """
        Analysiert ein Symbol mit allen (oder ausgewählten) Strategien.
        
        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse
            volumes: Volumen
            highs: Tageshochs
            lows: Tagestiefs
            strategies: Optional: Nur diese Strategien verwenden
            **kwargs: Zusätzliche Parameter für Analyzer
            
        Returns:
            Liste von TradeSignals
        """
        signals = []
        
        # Welche Analyzer verwenden?
        analyzers_to_use = self._analyzers
        if strategies:
            analyzers_to_use = {k: v for k, v in self._analyzers.items() if k in strategies}
        
        for name, analyzer in analyzers_to_use.items():
            try:
                # Earnings-Filter
                if self._should_skip_for_earnings(symbol, name):
                    continue
                
                # IV-Rank-Filter
                passes_iv, iv_reason = self._check_iv_filter(symbol, name)
                if not passes_iv:
                    logger.debug(f"Skipping {symbol} for {name}: {iv_reason}")
                    continue
                
                # Analyse durchführen
                signal = analyzer.analyze(
                    symbol=symbol,
                    prices=prices,
                    volumes=volumes,
                    highs=highs,
                    lows=lows,
                    **kwargs
                )
                
                # IV-Rank zum Signal hinzufügen wenn verfügbar
                iv_rank = self._iv_cache.get(symbol.upper())
                if iv_rank is not None and signal.details is not None:
                    signal.details['iv_rank'] = iv_rank
                
                # Nur Signale über min_score
                if signal.score >= self.config.min_score:
                    signals.append(signal)
                    
            except ValueError as e:
                # Insufficient data or validation errors - log at debug level
                logger.debug(f"Skipping {symbol} for {name}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error in {name} for {symbol}: {e}", exc_info=True)
        
        # Sortiere nach Score
        signals.sort(key=lambda x: x.score, reverse=True)
        
        # Limit pro Symbol
        return signals[:self.config.max_results_per_symbol]
    
    async def scan_async(
        self,
        symbols: List[str],
        data_fetcher: AsyncDataFetcher,
        mode: ScanMode = ScanMode.ALL,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> ScanResult:
        """
        Scannt Symbole asynchron.
        
        Args:
            symbols: Liste der Symbole
            data_fetcher: Async-Funktion zum Abrufen der Daten
            mode: Scan-Modus
            progress_callback: Optional: Callback für Fortschritt (current, total, symbol)
            
        Returns:
            ScanResult mit allen Signalen
        """
        start_time = datetime.now()
        all_signals: List[TradeSignal] = []
        errors: List[str] = []
        symbols_with_signals = 0
        
        # Strategien basierend auf Mode
        strategies = self._get_strategies_for_mode(mode)
        
        # Semaphore für Parallelität
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        
        async def scan_one(idx: int, symbol: str) -> List[TradeSignal]:
            async with semaphore:
                try:
                    if progress_callback:
                        progress_callback(idx + 1, len(symbols), symbol)
                    
                    # Daten abrufen
                    data = await data_fetcher(symbol)
                    if not data or len(data[0]) < self.config.min_data_points:
                        return []
                    
                    prices, volumes, highs, lows = data
                    
                    # Analysieren
                    return self.analyze_symbol(
                        symbol=symbol,
                        prices=prices,
                        volumes=volumes,
                        highs=highs,
                        lows=lows,
                        strategies=strategies
                    )
                except Exception as e:
                    errors.append(f"{symbol}: {str(e)}")
                    return []
        
        # Parallel ausführen
        tasks = [scan_one(i, sym) for i, sym in enumerate(symbols)]
        results = await asyncio.gather(*tasks)
        
        # Ergebnisse aggregieren
        for symbol_signals in results:
            if symbol_signals:
                symbols_with_signals += 1
                all_signals.extend(symbol_signals)
        
        # Nach Score sortieren und limitieren
        all_signals.sort(key=lambda x: x.score, reverse=True)
        all_signals = all_signals[:self.config.max_total_results]
        
        # Best Signal Mode: Nur bestes pro Symbol
        if mode == ScanMode.BEST_SIGNAL:
            all_signals = self._keep_best_per_symbol(all_signals)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        result = ScanResult(
            timestamp=start_time,
            symbols_scanned=len(symbols),
            symbols_with_signals=symbols_with_signals,
            total_signals=len(all_signals),
            signals=all_signals,
            errors=errors,
            scan_duration_seconds=duration
        )
        
        self._last_scan = result
        logger.info(
            f"Scan complete: {len(symbols)} symbols, "
            f"{len(all_signals)} signals, {duration:.1f}s"
        )
        
        return result
    
    def scan_sync(
        self,
        symbols: List[str],
        data_fetcher: DataFetcher,
        mode: ScanMode = ScanMode.ALL,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> ScanResult:
        """
        Scannt Symbole synchron.
        
        Args:
            symbols: Liste der Symbole
            data_fetcher: Sync-Funktion zum Abrufen der Daten
            mode: Scan-Modus
            progress_callback: Optional: Callback für Fortschritt
            
        Returns:
            ScanResult mit allen Signalen
        """
        start_time = datetime.now()
        all_signals: List[TradeSignal] = []
        errors: List[str] = []
        symbols_with_signals = 0
        
        strategies = self._get_strategies_for_mode(mode)
        
        for idx, symbol in enumerate(symbols):
            try:
                if progress_callback:
                    progress_callback(idx + 1, len(symbols), symbol)
                
                # Daten abrufen
                data = data_fetcher(symbol)
                if not data or len(data[0]) < self.config.min_data_points:
                    continue
                
                prices, volumes, highs, lows = data
                
                # Analysieren
                signals = self.analyze_symbol(
                    symbol=symbol,
                    prices=prices,
                    volumes=volumes,
                    highs=highs,
                    lows=lows,
                    strategies=strategies
                )
                
                if signals:
                    symbols_with_signals += 1
                    all_signals.extend(signals)
                    
            except Exception as e:
                errors.append(f"{symbol}: {str(e)}")
        
        # Nach Score sortieren und limitieren
        all_signals.sort(key=lambda x: x.score, reverse=True)
        all_signals = all_signals[:self.config.max_total_results]
        
        if mode == ScanMode.BEST_SIGNAL:
            all_signals = self._keep_best_per_symbol(all_signals)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        result = ScanResult(
            timestamp=start_time,
            symbols_scanned=len(symbols),
            symbols_with_signals=symbols_with_signals,
            total_signals=len(all_signals),
            signals=all_signals,
            errors=errors,
            scan_duration_seconds=duration
        )
        
        self._last_scan = result
        return result
    
    def _get_strategies_for_mode(self, mode: ScanMode) -> Optional[List[str]]:
        """Gibt die Strategien für einen Mode zurück"""
        if mode == ScanMode.ALL or mode == ScanMode.BEST_SIGNAL:
            return None  # Alle
        elif mode == ScanMode.PULLBACK_ONLY:
            return ['pullback']
        elif mode == ScanMode.BREAKOUT_ONLY:
            return ['ath_breakout']
        elif mode == ScanMode.BOUNCE_ONLY:
            return ['bounce']
        elif mode == ScanMode.EARNINGS_DIP:
            return ['earnings_dip']
        return None
    
    def _keep_best_per_symbol(self, signals: List[TradeSignal]) -> List[TradeSignal]:
        """Behält nur das beste Signal pro Symbol"""
        best_by_symbol: Dict[str, TradeSignal] = {}
        
        for signal in signals:
            if signal.symbol not in best_by_symbol or \
               signal.score > best_by_symbol[signal.symbol].score:
                best_by_symbol[signal.symbol] = signal
        
        result = list(best_by_symbol.values())
        result.sort(key=lambda x: x.score, reverse=True)
        return result
    
    def get_summary(self, result: Optional[ScanResult] = None) -> str:
        """
        Erstellt eine Text-Zusammenfassung des Scans.
        """
        result = result or self._last_scan
        if not result:
            return "No scan results available"
        
        lines = [
            "=" * 60,
            f"SCAN SUMMARY - {result.timestamp.strftime('%Y-%m-%d %H:%M')}",
            "=" * 60,
            f"Symbols scanned: {result.symbols_scanned}",
            f"Symbols with signals: {result.symbols_with_signals}",
            f"Total signals: {result.total_signals}",
            f"Scan duration: {result.scan_duration_seconds:.1f}s",
            "",
            "TOP SIGNALS:",
            "-" * 40,
        ]
        
        for i, signal in enumerate(result.signals[:10], 1):
            lines.append(
                f"{i:2}. {signal.symbol:6} | {signal.strategy:15} | "
                f"Score: {signal.score:4.1f} | {signal.strength.value:8}"
            )
            if signal.reason:
                lines.append(f"    └─ {signal.reason[:60]}")
        
        # Signale pro Strategie
        lines.extend(["", "SIGNALS BY STRATEGY:", "-" * 40])
        for strategy in self.available_strategies:
            count = len(result.get_by_strategy(strategy))
            if count > 0:
                lines.append(f"  {strategy}: {count}")
        
        if result.errors:
            lines.extend(["", f"Errors: {len(result.errors)}"])
        
        return "\n".join(lines)
    
    def export_signals(
        self,
        result: Optional[ScanResult] = None,
        format: str = 'dict'
    ) -> Any:
        """
        Exportiert Signale in verschiedenen Formaten.
        
        Args:
            result: ScanResult (oder letzter Scan)
            format: 'dict', 'csv', 'json'
        """
        result = result or self._last_scan
        if not result:
            return None
        
        if format == 'dict':
            return result.to_dict()
        
        elif format == 'csv':
            lines = [
                "symbol,strategy,signal_type,strength,score,current_price,"
                "entry_price,stop_loss,target_price,risk_reward,reason"
            ]
            for s in result.signals:
                lines.append(
                    f"{s.symbol},{s.strategy},{s.signal_type.value},"
                    f"{s.strength.value},{s.score},{s.current_price},"
                    f"{s.entry_price or ''},{s.stop_loss or ''},{s.target_price or ''},"
                    f"{s.risk_reward_ratio or ''},{s.reason}"
                )
            return "\n".join(lines)
        
        elif format == 'json':
            import json
            return json.dumps(result.to_dict(), indent=2)
        
        return None


# Convenience-Funktionen

def create_scanner(
    enable_pullback: bool = True,
    enable_breakout: bool = True,
    enable_bounce: bool = True,
    enable_earnings_dip: bool = True,
    min_score: float = 5.0,
    exclude_earnings_days: int = 60
) -> MultiStrategyScanner:
    """
    Factory-Funktion für einfache Scanner-Erstellung.
    
    Beispiel:
        scanner = create_scanner(enable_earnings_dip=False)
        result = scanner.scan_sync(symbols, data_fetcher)
    """
    config = ScanConfig(
        min_score=min_score,
        exclude_earnings_within_days=exclude_earnings_days,
        enable_pullback=enable_pullback,
        enable_ath_breakout=enable_breakout,
        enable_bounce=enable_bounce,
        enable_earnings_dip=enable_earnings_dip
    )
    return MultiStrategyScanner(config)


def quick_scan(
    symbols: List[str],
    data_fetcher: DataFetcher,
    mode: ScanMode = ScanMode.ALL,
    min_score: float = 5.0
) -> List[TradeSignal]:
    """
    Schneller Scan ohne Scanner-Instanz.
    
    Beispiel:
        signals = quick_scan(
            ["AAPL", "MSFT"],
            lambda s: get_price_data(s),
            mode=ScanMode.PULLBACK_ONLY
        )
    """
    scanner = create_scanner(min_score=min_score)
    result = scanner.scan_sync(symbols, data_fetcher, mode)
    return result.signals
