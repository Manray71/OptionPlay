# OptionPlay - Multi-Strategy Scanner
# =====================================
# Kombiniert alle Analyzer für umfassendes Market Scanning
#
# Features:
# - Parallel-Scanning mit allen registrierten Analyzern
# - Object Pooling für Analyzer-Wiederverwendung
# - Ranking und Aggregation von Signalen
# - Filter nach Strategie, Score, Signal-Typ
# - Earnings-Filter Integration
# - Export-Funktionen

import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from functools import cached_property
from typing import List, Dict, Optional, Callable, Tuple, Any
from datetime import datetime, date
from enum import Enum

try:
    from ..analyzers.base import BaseAnalyzer
    from ..analyzers.context import AnalysisContext
    from ..analyzers.pullback import PullbackAnalyzer
    from ..analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from ..analyzers.bounce import BounceAnalyzer, BounceConfig
    from ..analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
    from ..analyzers.pool import AnalyzerPool, PoolConfig, get_analyzer_pool
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..config.config_loader import PullbackScoringConfig
    from ..config.liquidity_blacklist import is_illiquid, filter_liquid_symbols
    from ..backtesting.reliability import ReliabilityScorer, ScorerConfig
    from ..backtesting.real_options_backtester import (
        calculate_symbol_stability,
        get_symbol_stability_score,
        OUTCOME_DB_PATH,
    )
    from ..cache.symbol_fundamentals import (
        SymbolFundamentalsManager,
        get_fundamentals_manager,
        SymbolFundamentals,
    )
    from ..constants.trading_rules import ENTRY_STABILITY_MIN, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX
except ImportError:
    from analyzers.base import BaseAnalyzer
    from analyzers.context import AnalysisContext
    from analyzers.pullback import PullbackAnalyzer
    from analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from analyzers.bounce import BounceAnalyzer, BounceConfig
    from analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
    from analyzers.pool import AnalyzerPool, PoolConfig, get_analyzer_pool
    from models.base import TradeSignal, SignalType, SignalStrength
    from config.config_loader import PullbackScoringConfig
    try:
        from config.liquidity_blacklist import is_illiquid, filter_liquid_symbols
    except ImportError:
        # Fallback wenn Blacklist nicht verfügbar
        def is_illiquid(symbol: str) -> bool:
            return False
        def filter_liquid_symbols(symbols: list) -> list:
            return symbols
    try:
        from backtesting.reliability import ReliabilityScorer, ScorerConfig
    except ImportError:
        ReliabilityScorer = None
        ScorerConfig = None
    try:
        from backtesting.real_options_backtester import (
            calculate_symbol_stability,
            get_symbol_stability_score,
            OUTCOME_DB_PATH,
        )
    except ImportError:
        calculate_symbol_stability = None
        get_symbol_stability_score = None
        OUTCOME_DB_PATH = None
    try:
        from cache.symbol_fundamentals import (
            SymbolFundamentalsManager,
            get_fundamentals_manager,
            SymbolFundamentals,
        )
    except ImportError:
        SymbolFundamentalsManager = None
        get_fundamentals_manager = None
        SymbolFundamentals = None
    try:
        from constants.trading_rules import ENTRY_STABILITY_MIN, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX
    except ImportError:
        ENTRY_STABILITY_MIN = 70.0
        ENTRY_PRICE_MIN = 20.0
        ENTRY_PRICE_MAX = 1500.0

# Extracted in Phase 5: Config and Result dataclasses
from .scan_config import ScanMode, ScanConfig, _get_default_blacklist_scanner
from .scan_result import ScanResult, DataFetcher, AsyncDataFetcher

logger = logging.getLogger(__name__)


# ScanMode and ScanConfig are now in scan_config.py
# ScanResult and DataFetcher/AsyncDataFetcher are now in scan_result.py
# They are re-imported above for backwards compatibility.


class MultiStrategyScanner:
    """
    Multi-Strategie Scanner für umfassendes Market Scanning.

    Kombiniert alle verfügbaren Analyzer und bietet:
    - Einheitliches Interface für alle Strategien
    - Object Pooling für Analyzer-Wiederverwendung (Performance)
    - Ranking und Aggregation
    - Earnings-Filter
    - Async-Support für paralleles Scanning

    Verwendung:
        scanner = MultiStrategyScanner()

        # Mit async Data Fetcher (mit Opens für Gap-Analyse)
        async def fetch_data(symbol):
            return prices, volumes, highs, lows, opens

        result = await scanner.scan_async(
            symbols=["AAPL", "MSFT", "GOOGL"],
            data_fetcher=fetch_data
        )

        # Top 10 Signale
        for signal in result.signals[:10]:
            print(f"{signal.symbol}: {signal.strategy} - Score {signal.score}")

        # Pool-Statistiken
        print(scanner.pool_stats())
    """

    def __init__(
        self,
        config: Optional[ScanConfig] = None,
        analyzer_pool: Optional[AnalyzerPool] = None,
        reliability_scorer: Optional['ReliabilityScorer'] = None
    ):
        self.config = config or ScanConfig()
        self._analyzers: Dict[str, BaseAnalyzer] = {}
        self._earnings_cache: Dict[str, Optional[date]] = {}
        self._iv_cache: Dict[str, Optional[float]] = {}  # Symbol -> IV-Rank
        self._vix_cache: Optional[float] = None  # Aktueller VIX für Reliability
        self._last_scan: Optional[ScanResult] = None

        # Analyzer Pool für Object Pooling
        self._pool: Optional[AnalyzerPool] = None
        self._use_pool = self.config.use_analyzer_pool

        if self._use_pool:
            self._pool = analyzer_pool or self._create_pool()

        # Registriere Standard-Analyzer (Fallback wenn Pool nicht verwendet)
        if not self._use_pool:
            self._register_default_analyzers()

        # Reliability Scorer (Phase 3)
        self._reliability_scorer: Optional['ReliabilityScorer'] = None
        if self.config.enable_reliability_scoring and ReliabilityScorer is not None:
            self._reliability_scorer = reliability_scorer or self._create_reliability_scorer()

        # Fundamentals Manager (lazy-loaded via _fundamentals_cache)
        self._fundamentals_manager: Optional['SymbolFundamentalsManager'] = None

    @cached_property
    def _stability_cache(self) -> Dict[str, Dict]:
        """Lädt Symbol-Stabilitätsdaten aus der Outcome-Datenbank (lazy, einmalig)."""
        if not self.config.enable_stability_scoring or calculate_symbol_stability is None:
            return {}

        try:
            if OUTCOME_DB_PATH and OUTCOME_DB_PATH.exists():
                cache = calculate_symbol_stability(OUTCOME_DB_PATH)
                if cache:
                    stable_count = sum(1 for d in cache.values() if d.get('recommended'))
                    volatile_count = sum(1 for d in cache.values() if d.get('blacklisted'))
                    logger.info(
                        f"Loaded stability data for {len(cache)} symbols "
                        f"({stable_count} stable, {volatile_count} volatile)"
                    )
                    return cache
        except Exception as e:
            logger.warning(f"Could not load stability cache: {e}")
        return {}

    @cached_property
    def _fundamentals_cache(self) -> Dict[str, 'SymbolFundamentals']:
        """Lädt Fundamentaldaten aus der symbol_fundamentals Tabelle (lazy, einmalig)."""
        if not self.config.enable_fundamentals_filter or get_fundamentals_manager is None:
            return {}

        try:
            self._fundamentals_manager = get_fundamentals_manager()
            all_fundamentals = self._fundamentals_manager.get_all_fundamentals()

            cache = {f.symbol: f for f in all_fundamentals}

            with_stability = sum(1 for f in all_fundamentals if f.stability_score is not None)
            with_iv_rank = sum(1 for f in all_fundamentals if f.iv_rank_252d is not None)

            logger.info(
                f"Loaded fundamentals for {len(cache)} symbols "
                f"({with_stability} with stability, {with_iv_rank} with IV rank)"
            )
            return cache
        except Exception as e:
            logger.warning(f"Could not load fundamentals cache: {e}")
        return {}

    def get_symbol_fundamentals(self, symbol: str) -> Optional['SymbolFundamentals']:
        """
        Gibt Fundamentaldaten für ein Symbol zurück.

        Returns:
            SymbolFundamentals oder None
        """
        return self._fundamentals_cache.get(symbol.upper())

    def filter_symbols_by_fundamentals(
        self,
        symbols: List[str],
        log_filtered: bool = True
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        Filtert Symbole basierend auf Fundamentaldaten aus symbol_fundamentals.

        Diese Methode wird VOR dem Scan aufgerufen, um Symbole auszuschließen,
        die die Fundamentals-Kriterien nicht erfüllen.

        Args:
            symbols: Liste der zu filternden Symbole
            log_filtered: Ob gefilterte Symbole geloggt werden sollen

        Returns:
            Tuple: (gefilterte_symbole, filter_grund_dict)
        """
        if not self.config.enable_fundamentals_filter:
            return symbols, {}

        if not self._fundamentals_cache:
            logger.debug("Fundamentals cache is empty - skipping fundamentals filter")
            return symbols, {}

        passed: List[str] = []
        filtered: Dict[str, str] = {}

        # Defensive None-Checks für Listen
        whitelist = self.config.fundamentals_whitelist or []
        blacklist = self.config.fundamentals_blacklist or []

        for symbol in symbols:
            symbol_upper = symbol.upper()

            # Whitelist überschreibt alles
            if whitelist and symbol_upper in whitelist:
                passed.append(symbol)
                continue

            # Blacklist
            if blacklist and symbol_upper in blacklist:
                filtered[symbol] = "Blacklisted (historisch schlechte Performance)"
                continue

            # Fundamentals abrufen
            f = self._fundamentals_cache.get(symbol_upper)

            # Kein Eintrag → durchlassen (konservativ)
            if f is None:
                passed.append(symbol)
                continue

            # Stability Score Filter
            if f.stability_score is not None:
                if f.stability_score < self.config.fundamentals_min_stability:
                    filtered[symbol] = f"Stability zu niedrig ({f.stability_score:.0f} < {self.config.fundamentals_min_stability:.0f})"
                    continue

            # Price Filter (PLAYBOOK §1: $20-$1500)
            if f.current_price is not None:
                if f.current_price < ENTRY_PRICE_MIN or f.current_price > ENTRY_PRICE_MAX:
                    filtered[symbol] = f"Preis ${f.current_price:.2f} außerhalb ${ENTRY_PRICE_MIN:.0f}-${ENTRY_PRICE_MAX:.0f}"
                    continue

            # Historical Win Rate Filter
            if f.historical_win_rate is not None:
                if f.historical_win_rate < self.config.fundamentals_min_win_rate:
                    filtered[symbol] = f"Win Rate zu niedrig ({f.historical_win_rate:.0f}% < {self.config.fundamentals_min_win_rate:.0f}%)"
                    continue

            # Historical Volatility Filter
            if f.historical_volatility_30d is not None:
                if f.historical_volatility_30d > self.config.fundamentals_max_volatility:
                    filtered[symbol] = f"HV zu hoch ({f.historical_volatility_30d:.0f}% > {self.config.fundamentals_max_volatility:.0f}%)"
                    continue

            # Beta Filter
            if f.beta is not None:
                if f.beta > self.config.fundamentals_max_beta:
                    filtered[symbol] = f"Beta zu hoch ({f.beta:.1f} > {self.config.fundamentals_max_beta:.1f})"
                    continue

            # IV Rank Filter (aus symbol_fundamentals)
            if f.iv_rank_252d is not None:
                if f.iv_rank_252d < self.config.fundamentals_iv_rank_min:
                    filtered[symbol] = f"IV Rank zu niedrig ({f.iv_rank_252d:.0f} < {self.config.fundamentals_iv_rank_min:.0f})"
                    continue
                if f.iv_rank_252d > self.config.fundamentals_iv_rank_max:
                    filtered[symbol] = f"IV Rank zu hoch ({f.iv_rank_252d:.0f} > {self.config.fundamentals_iv_rank_max:.0f})"
                    continue

            # SPY Correlation Filter
            if f.spy_correlation_60d is not None:
                if self.config.fundamentals_max_spy_correlation is not None:
                    if f.spy_correlation_60d > self.config.fundamentals_max_spy_correlation:
                        filtered[symbol] = f"SPY Korrelation zu hoch ({f.spy_correlation_60d:.2f})"
                        continue
                if self.config.fundamentals_min_spy_correlation is not None:
                    if f.spy_correlation_60d < self.config.fundamentals_min_spy_correlation:
                        filtered[symbol] = f"SPY Korrelation zu niedrig ({f.spy_correlation_60d:.2f})"
                        continue

            # Sector Filter
            if f.sector:
                if self.config.fundamentals_exclude_sectors:
                    if f.sector in self.config.fundamentals_exclude_sectors:
                        filtered[symbol] = f"Sektor ausgeschlossen ({f.sector})"
                        continue
                if self.config.fundamentals_include_sectors:
                    if f.sector not in self.config.fundamentals_include_sectors:
                        filtered[symbol] = f"Sektor nicht in Whitelist ({f.sector})"
                        continue

            # Market Cap Filter
            if f.market_cap_category:
                if self.config.fundamentals_exclude_market_caps:
                    if f.market_cap_category in self.config.fundamentals_exclude_market_caps:
                        filtered[symbol] = f"Market Cap ausgeschlossen ({f.market_cap_category})"
                        continue
                if self.config.fundamentals_include_market_caps:
                    if f.market_cap_category not in self.config.fundamentals_include_market_caps:
                        filtered[symbol] = f"Market Cap nicht in Whitelist ({f.market_cap_category})"
                        continue

            # Alle Filter bestanden
            passed.append(symbol)

        if log_filtered and filtered:
            logger.info(
                f"Fundamentals filter: {len(filtered)} symbols removed, "
                f"{len(passed)} remaining"
            )
            # Detail-Log für erste 5 gefilterte
            for i, (sym, reason) in enumerate(list(filtered.items())[:5]):
                logger.debug(f"  Filtered {sym}: {reason}")
            if len(filtered) > 5:
                logger.debug(f"  ... and {len(filtered) - 5} more")

        return passed, filtered

    def get_symbol_stability(self, symbol: str) -> Optional[Dict]:
        """
        Gibt Stabilitätsdaten für ein Symbol zurück.

        Returns:
            Dict mit stability_score, win_rate, avg_drawdown etc. oder None
        """
        return self._stability_cache.get(symbol)

    def _create_reliability_scorer(self) -> Optional['ReliabilityScorer']:
        """Erstellt den Reliability Scorer"""
        if ReliabilityScorer is None:
            logger.warning("ReliabilityScorer not available - reliability scoring disabled")
            return None

        try:
            if self.config.reliability_model_path:
                # Lade trainiertes Modell
                scorer = ReliabilityScorer.from_trained_model(
                    self.config.reliability_model_path
                )
                logger.info(f"Loaded reliability model from {self.config.reliability_model_path}")
            else:
                # Default Scorer ohne Trainingsdaten
                scorer = ReliabilityScorer()
                logger.info("Using default reliability scorer (no trained model)")

            return scorer
        except Exception as e:
            logger.warning(f"Could not create reliability scorer: {e}")
            return None

    def set_vix(self, vix: float) -> None:
        """
        Setzt den aktuellen VIX für Regime-basierte Reliability-Anpassungen.

        Args:
            vix: Aktueller VIX-Wert
        """
        self._vix_cache = vix

    def _create_pool(self) -> AnalyzerPool:
        """Erstellt und konfiguriert den Analyzer Pool"""
        pool_config = PoolConfig(
            default_pool_size=self.config.pool_size_per_strategy,
            max_pool_size=self.config.pool_size_per_strategy * 2,
            create_on_empty=True
        )

        pool = AnalyzerPool(pool_config)

        # Registriere Analyzer-Factories basierend auf Config
        if self.config.enable_pullback:
            try:
                pullback_config = PullbackScoringConfig()
                pool.register_factory(
                    "pullback",
                    lambda cfg=pullback_config: PullbackAnalyzer(cfg)
                )
            except Exception as e:
                logger.warning(f"Could not register PullbackAnalyzer: {e}")

        if self.config.enable_ath_breakout:
            pool.register_factory(
                "ath_breakout",
                lambda: ATHBreakoutAnalyzer(ATHBreakoutConfig())
            )

        if self.config.enable_bounce:
            pool.register_factory(
                "bounce",
                lambda: BounceAnalyzer(BounceConfig())
            )

        if self.config.enable_earnings_dip:
            pool.register_factory(
                "earnings_dip",
                lambda: EarningsDipAnalyzer(EarningsDipConfig())
            )

        logger.info(
            f"Created analyzer pool with strategies: {pool.registered_strategies}"
        )

        return pool

    def _register_default_analyzers(self) -> None:
        """Registriert die Standard-Analyzer basierend auf Config (ohne Pool)"""
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
        if self._use_pool and self._pool:
            # Registriere Factory für den Analyzer
            self._pool.register_factory(
                analyzer.strategy_name,
                lambda a=analyzer: a  # Gibt immer dieselbe Instanz zurück
            )
        else:
            self._analyzers[analyzer.strategy_name] = analyzer
        logger.info(f"Registered custom analyzer: {analyzer.strategy_name}")

    def get_analyzer(self, name: str) -> Optional[BaseAnalyzer]:
        """Gibt einen Analyzer nach Namen zurück"""
        if self._use_pool and self._pool:
            # Checkout ohne Checkin (für direkte Verwendung)
            try:
                return self._pool.checkout(name)
            except KeyError:
                return None
        return self._analyzers.get(name)

    @property
    def available_strategies(self) -> List[str]:
        """Liste aller verfügbaren Strategien"""
        if self._use_pool and self._pool:
            return self._pool.registered_strategies
        return list(self._analyzers.keys())

    def pool_stats(self) -> Dict[str, Any]:
        """Gibt Pool-Statistiken zurück (nur wenn Pool aktiviert)"""
        if self._pool:
            return self._pool.stats()
        return {"pool_enabled": False}

    def prefill_pool(self) -> Dict[str, int]:
        """
        Füllt den Analyzer Pool mit Instanzen vor.

        Nützlich für Warmup vor großen Scans um Latenz zu reduzieren.

        Returns:
            Dict mit Strategie -> Anzahl erstellter Analyzer
        """
        if self._pool:
            return self._pool.prefill_all()
        return {}
    
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
        # IV-Filter nur für Credit-Spread-Strategien (pullback)
        # Andere Strategien (bounce, ath_breakout, earnings_dip) sind keine Credit-Spreads
        if strategy in ['earnings_dip', 'ath_breakout', 'bounce']:
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

        Logik:
        - earnings_dip: Nur wenn Earnings KÜRZLICH stattgefunden haben
          (innerhalb der letzten 10 Tage). Bevorstehende Earnings = skip.
        - andere Strategien: Skip wenn Earnings bevorstehen (in den nächsten X Tagen)

        HINWEIS: Die primäre Filterung erfolgt im MCP-Server via
        _apply_earnings_prefilter(). Diese Methode ist eine zusätzliche
        Sicherheitsschicht für direkte Scanner-Aufrufe.
        """
        earnings_date = self._earnings_cache.get(symbol)

        if strategy == 'earnings_dip':
            # Earnings Dip braucht KÜRZLICH VERGANGENE Earnings
            if not earnings_date:
                # Kein Datum bekannt -> überspringen
                logger.debug(f"Skipping {symbol} for earnings_dip: no earnings date known")
                return True

            days_to_earnings = (earnings_date - date.today()).days

            # Earnings müssen in der Vergangenheit liegen (negativ)
            # und nicht zu weit zurück (max 10 Tage)
            if days_to_earnings > 0:
                # Earnings stehen noch bevor -> kein Dip möglich
                logger.debug(f"Skipping {symbol} for earnings_dip: earnings in {days_to_earnings} days (not yet occurred)")
                return True

            if days_to_earnings < -10:
                # Earnings zu lange her (>10 Tage) -> kein frischer Dip
                logger.debug(f"Skipping {symbol} for earnings_dip: earnings {abs(days_to_earnings)} days ago (too old)")
                return True

            # Earnings innerhalb der letzten 10 Tage -> analysieren
            return False

        # Für andere Strategien: Skip wenn Earnings bevorstehen
        if self.config.exclude_earnings_within_days <= 0:
            return False

        if not earnings_date:
            # Kein Datum im Scanner-Cache bekannt.
            # Statt konservativ zu überspringen, erlauben wir die Analyse.
            # Der Benutzer wird in der Ausgabe über fehlende Earnings-Daten informiert.
            logger.debug(f"No earnings date for {symbol}, allowing analysis (earnings unknown)")
            return False

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
        opens: Optional[List[float]] = None,
        strategies: Optional[List[str]] = None,
        context: Optional[AnalysisContext] = None,
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
            opens: Eröffnungskurse (optional, für Gap-Analyse)
            strategies: Optional: Nur diese Strategien verwenden
            context: Optional: Pre-calculated AnalysisContext for performance
            **kwargs: Zusätzliche Parameter für Analyzer

        Returns:
            Liste von TradeSignals
        """
        signals = []

        # Welche Strategien verwenden?
        if self._use_pool and self._pool:
            strategies_to_use = strategies or self._pool.registered_strategies
        else:
            strategies_to_use = strategies or list(self._analyzers.keys())

        # Pre-calculate context once if not provided (shared across all analyzers)
        if context is None and len(strategies_to_use) > 1:
            context = AnalysisContext.from_data(symbol, prices, volumes, highs, lows, opens=opens)

        for strategy_name in strategies_to_use:
            try:
                # Earnings-Filter
                if self._should_skip_for_earnings(symbol, strategy_name):
                    continue

                # IV-Rank-Filter
                passes_iv, iv_reason = self._check_iv_filter(symbol, strategy_name)
                if not passes_iv:
                    logger.debug(f"Skipping {symbol} for {strategy_name}: {iv_reason}")
                    continue

                # Analyzer holen (aus Pool oder direkt)
                if self._use_pool and self._pool:
                    # Mit Pool: acquire/release Context Manager
                    with self._pool.acquire(strategy_name) as analyzer:
                        signal = self._run_analysis(
                            analyzer, symbol, prices, volumes, highs, lows,
                            context, **kwargs
                        )
                else:
                    # Ohne Pool: direkte Verwendung
                    analyzer = self._analyzers.get(strategy_name)
                    if not analyzer:
                        continue
                    signal = self._run_analysis(
                        analyzer, symbol, prices, volumes, highs, lows,
                        context, **kwargs
                    )

                if signal is None:
                    continue

                # IV-Rank zum Signal hinzufügen wenn verfügbar
                iv_rank = self._iv_cache.get(symbol.upper())
                if iv_rank is not None and signal.details is not None:
                    signal.details['iv_rank'] = iv_rank

                # Reliability Scoring (Phase 3)
                if self._reliability_scorer and signal.score >= self.config.min_score:
                    self._add_reliability_to_signal(signal)

                # Stability Scoring (Phase 4 - Outcome-basiert)
                if self.config.enable_stability_scoring:
                    self._add_stability_to_signal(signal)

                # Nur Signale über min_score
                if signal.score >= self.config.min_score:
                    signals.append(signal)

            except KeyError as e:
                # Strategy not registered in pool
                logger.debug(f"Strategy {strategy_name} not available: {e}")
            except ValueError as e:
                # Insufficient data or validation errors - log at debug level
                logger.debug(f"Skipping {symbol} for {strategy_name}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error in {strategy_name} for {symbol}: {e}", exc_info=True)

        # Sortiere nach Score
        signals.sort(key=lambda x: x.score, reverse=True)

        # Limit pro Symbol
        return signals[:self.config.max_results_per_symbol]

    def _add_reliability_to_signal(self, signal: TradeSignal) -> None:
        """
        Fügt Reliability-Informationen zu einem Signal hinzu.

        Args:
            signal: TradeSignal das erweitert werden soll
        """
        if not self._reliability_scorer:
            return

        try:
            # Score Breakdown aus Details extrahieren wenn verfügbar
            score_breakdown = None
            if signal.details and 'score_breakdown' in signal.details:
                score_breakdown = signal.details['score_breakdown']

            # Reliability berechnen
            result = self._reliability_scorer.score(
                pullback_score=signal.score,
                score_breakdown=score_breakdown,
                vix=self._vix_cache,
            )

            # Zum Signal hinzufügen
            signal.reliability_grade = result.grade
            signal.reliability_win_rate = result.historical_win_rate
            signal.reliability_ci = result.confidence_interval
            signal.reliability_warnings = result.warnings.copy()

            # Auch in Details speichern für JSON-Export
            if signal.details is not None:
                signal.details['reliability'] = {
                    'grade': result.grade,
                    'win_rate': result.historical_win_rate,
                    'confidence_interval': result.confidence_interval,
                    'regime': result.regime,
                    'should_trade': result.should_trade,
                }

        except Exception as e:
            logger.debug(f"Could not add reliability to signal: {e}")

    def _add_stability_to_signal(self, signal: TradeSignal) -> None:
        """
        Fügt Symbol-Stabilitätsinformationen zu einem Signal hinzu und
        passt den Score basierend auf historischen Backtest-Ergebnissen an.

        Anpassungen:
        1. Win Rate Integration: Score wird proportional zur historischen Win Rate skaliert
        2. Drawdown Penalty: Hohe Drawdowns reduzieren den Score
        3. Stability Boost: Stabile Symbole erhalten zusätzlichen Bonus

        Formel: adjusted_score = base_score * win_rate_multiplier * drawdown_factor

        Args:
            signal: TradeSignal das erweitert werden soll
        """
        stability_data = self._stability_cache.get(signal.symbol)
        original_score = signal.score

        if stability_data:
            stability_score = stability_data.get('stability_score', 0)
            historical_wr = stability_data.get('win_rate', 0)  # 0-100
            avg_drawdown = stability_data.get('avg_drawdown', 0)

            # 1. Win Rate Integration (proportional)
            # Formel: multiplier = base + (win_rate / divisor)
            # Bei WR=90%: 0.7 + 0.30 = 1.0 (kein Boost, volle Stärke)
            # Bei WR=70%: 0.7 + 0.23 = 0.93 (leichte Reduktion)
            # Bei WR=50%: 0.7 + 0.17 = 0.87 (stärkere Reduktion)
            if self.config.enable_win_rate_integration and historical_wr > 0:
                win_rate_multiplier = (
                    self.config.win_rate_base_multiplier +
                    historical_wr / self.config.win_rate_divisor
                )
                signal.score = signal.score * win_rate_multiplier

            # 2. Drawdown Penalty
            # Hoher Drawdown = höheres Risiko = Score-Reduktion
            if self.config.enable_drawdown_adjustment and avg_drawdown > self.config.drawdown_penalty_threshold:
                excess_drawdown = avg_drawdown - self.config.drawdown_penalty_threshold
                drawdown_penalty = excess_drawdown * self.config.drawdown_penalty_per_pct
                signal.score = signal.score * (1.0 - min(drawdown_penalty, 0.3))  # Max 30% Reduktion

            # 3. Legacy Stability Boost (für rückwärts Kompatibilität)
            # Jetzt: Nur zusätzlich für SEHR stabile Symbole (Score >= 80)
            if stability_score >= 80:
                signal.score = signal.score + (self.config.stability_boost_amount * 0.5)
            elif stability_score >= self.config.stability_boost_threshold:
                signal.score = signal.score + (self.config.stability_boost_amount * 0.25)

            # Round to 1 decimal
            signal.score = round(signal.score, 1)

            # Warnung für volatile Symbole
            if self.config.warn_on_volatile_symbols and stability_data.get('blacklisted'):
                if not hasattr(signal, 'reliability_warnings') or signal.reliability_warnings is None:
                    signal.reliability_warnings = []
                signal.reliability_warnings.append(
                    f"⚠️ Volatile Symbol: Historische WR nur {historical_wr:.0f}%, "
                    f"Avg Drawdown {avg_drawdown:.1f}%"
                )

            # Stability-Info in Details speichern (erweitert)
            if signal.details is not None:
                signal.details['stability'] = {
                    'score': stability_score,
                    'historical_win_rate': historical_wr,
                    'avg_drawdown': avg_drawdown,
                    'avg_days_below_short': stability_data.get('avg_days_below', 0),
                    'total_backtest_trades': stability_data.get('total_trades', 0),
                    'recommended': stability_data.get('recommended', False),
                    'blacklisted': stability_data.get('blacklisted', False),
                    # Neue Felder für Transparenz
                    'original_score': original_score,
                    'score_adjustment': round(signal.score - original_score, 2),
                    'adjustment_reason': self._get_adjustment_reason(
                        historical_wr, avg_drawdown, stability_score
                    ),
                }

    def _get_adjustment_reason(
        self,
        win_rate: float,
        avg_drawdown: float,
        stability_score: float
    ) -> str:
        """Erklärt die Score-Anpassung für Transparenz."""
        reasons = []

        if win_rate >= 90:
            reasons.append(f"Exzellente WR ({win_rate:.0f}%)")
        elif win_rate >= 85:
            reasons.append(f"Sehr gute WR ({win_rate:.0f}%)")
        elif win_rate < 75:
            reasons.append(f"Niedrige WR ({win_rate:.0f}%) → Score reduziert")

        if avg_drawdown > 15:
            reasons.append(f"Hoher Drawdown ({avg_drawdown:.1f}%) → Penalty")
        elif avg_drawdown < 5:
            reasons.append(f"Niedriger Drawdown ({avg_drawdown:.1f}%)")

        if stability_score >= 80:
            reasons.append(f"Sehr stabil (Score {stability_score:.0f})")

        return " | ".join(reasons) if reasons else "Standard"

    def _filter_by_stability(
        self,
        signals: List[TradeSignal]
    ) -> Tuple[List[TradeSignal], Dict[str, int]]:
        """
        Stability-First-Filterung: Filtert Signale basierend auf Symbol-Stability.

        Konzept: Stability ist der stärkste Prädiktor für Win Rate!
        - Stability ≥80 (Premium): 94.5% WR → niedriger min_score OK
        - Stability ≥70 (Gut): 86.1% WR → normaler min_score
        - Stability ≥50 (OK): 75% WR → höherer min_score erforderlich
        - Stability <50 (Blacklist): 66% WR → komplett gefiltert

        Args:
            signals: Liste von TradeSignals (müssen bereits stability data haben)

        Returns:
            Tuple von (gefilterte_signale, statistiken)
        """
        if not self.config.enable_stability_first:
            return signals, {'filtered': 0, 'reason': 'disabled'}

        filtered = []
        stats = {
            'total': len(signals),
            'premium_kept': 0,
            'good_kept': 0,
            'ok_kept': 0,
            'blacklisted': 0,
            'no_stability_data': 0,
            'score_too_low': 0,
        }

        for signal in signals:
            # Stability-Score aus Signal-Details extrahieren
            stability_score = 0.0
            if signal.details and 'stability' in signal.details:
                stability_score = signal.details['stability'].get('score', 0.0)

            # Kein Stability-Score vorhanden → konservativ behandeln (wie OK-Tier)
            if stability_score == 0.0:
                stats['no_stability_data'] += 1
                # Ohne Stability-Daten: Standard min_score verwenden
                if signal.score >= self.config.min_score:
                    filtered.append(signal)
                else:
                    stats['score_too_low'] += 1
                continue

            # Tier-basierte Filterung
            if stability_score >= self.config.stability_premium_threshold:
                # Premium-Symbol (94.5% WR): Niedrigerer Score OK
                if signal.score >= self.config.stability_premium_min_score:
                    filtered.append(signal)
                    stats['premium_kept'] += 1
                else:
                    stats['score_too_low'] += 1

            elif stability_score >= self.config.stability_good_threshold:
                # Gutes Symbol (86.1% WR): Standard Score
                if signal.score >= self.config.stability_good_min_score:
                    filtered.append(signal)
                    stats['good_kept'] += 1
                else:
                    stats['score_too_low'] += 1

            elif stability_score >= self.config.stability_ok_threshold:
                # OK Symbol (75% WR): Höherer Score erforderlich
                if signal.score >= self.config.stability_ok_min_score:
                    filtered.append(signal)
                    stats['ok_kept'] += 1
                else:
                    stats['score_too_low'] += 1

            else:
                # Blacklist: Stability < 50 → komplett gefiltert
                stats['blacklisted'] += 1

        stats['filtered'] = stats['total'] - len(filtered)

        if stats['filtered'] > 0:
            logger.info(
                f"Stability-First-Filter: {stats['filtered']}/{stats['total']} Signale gefiltert "
                f"(Premium: {stats['premium_kept']}, Good: {stats['good_kept']}, "
                f"OK: {stats['ok_kept']}, Blacklisted: {stats['blacklisted']})"
            )

        return filtered, stats

    def _run_analysis(
        self,
        analyzer: BaseAnalyzer,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        context: Optional[AnalysisContext],
        **kwargs
    ) -> Optional[TradeSignal]:
        """
        Führt die Analyse mit einem Analyzer durch.

        Extrahiert die Analyse-Logik für Wiederverwendung mit/ohne Pool.

        Args:
            analyzer: Zu verwendender Analyzer
            symbol: Ticker-Symbol
            prices, volumes, highs, lows: Preisdaten
            context: Pre-calculated AnalysisContext
            **kwargs: Zusätzliche Parameter

        Returns:
            TradeSignal oder None bei Fehler
        """
        try:
            return analyzer.analyze(
                symbol=symbol,
                prices=prices,
                volumes=volumes,
                highs=highs,
                lows=lows,
                context=context,
                **kwargs
            )
        except ValueError:
            # Insufficient data - expected, don't log
            raise
        except Exception as e:
            logger.debug(f"Analysis error for {symbol}: {e}")
            return None
    
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

        # Liquidity Filter: Entferne illiquide Symbole VOR dem Scan
        original_count = len(symbols)
        if self.config.enable_liquidity_filter:
            symbols = filter_liquid_symbols(symbols)
            filtered_count = original_count - len(symbols)
            if filtered_count > 0:
                logger.info(f"Liquidity filter: removed {filtered_count} illiquid symbols")

        # Fundamentals Filter: Entferne Symbole basierend auf Fundamentaldaten
        if self.config.enable_fundamentals_filter:
            pre_filter_count = len(symbols)
            symbols, filtered_reasons = self.filter_symbols_by_fundamentals(symbols)
            if len(filtered_reasons) > 0:
                logger.info(
                    f"Fundamentals filter: {len(filtered_reasons)} removed, "
                    f"{len(symbols)} remaining (from {pre_filter_count})"
                )

        # Strategien basierend auf Mode
        strategies = self._get_strategies_for_mode(mode)

        # PERFORMANCE: Prefill analyzer pool before scan to reduce first-checkout latency
        if self._use_pool and self._pool:
            self._pool.prefill_all()

        # PERFORMANCE: Create semaphore once, but defer acquisition until after data fetch
        # This allows data fetching to proceed in parallel while only limiting analysis
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        # PERFORMANCE: Context cache to avoid re-calculating for same data
        context_cache: Dict[str, AnalysisContext] = {}

        async def scan_one(idx: int, symbol: str) -> List[TradeSignal]:
            try:
                if progress_callback:
                    progress_callback(idx + 1, len(symbols), symbol)

                # PERFORMANCE: Fetch data OUTSIDE semaphore (I/O bound, not CPU bound)
                data = await data_fetcher(symbol)
                if not data or len(data[0]) < self.config.min_data_points:
                    return []

                # Support both 4-tuple (legacy) and 5-tuple (with opens)
                if len(data) == 5:
                    prices, volumes, highs, lows, opens = data
                else:
                    prices, volumes, highs, lows = data
                    opens = None

                # PERFORMANCE: Only acquire semaphore for CPU-intensive analysis
                async with semaphore:
                    # PERFORMANCE: Create context once and cache it
                    context = context_cache.get(symbol)
                    if context is None:
                        context = AnalysisContext.from_data(symbol, prices, volumes, highs, lows, opens=opens)
                        context_cache[symbol] = context

                    # Analysieren mit gecachtem Context
                    return self.analyze_symbol(
                        symbol=symbol,
                        prices=prices,
                        volumes=volumes,
                        highs=highs,
                        lows=lows,
                        opens=opens,
                        strategies=strategies,
                        context=context
                    )
            except Exception as e:
                errors.append(f"{symbol}: {str(e)}")
                return []

        # Parallel ausführen
        tasks = [scan_one(i, sym) for i, sym in enumerate(symbols)]
        results = await asyncio.gather(*tasks)

        # PERFORMANCE: Clear context cache after scan to free memory
        context_cache.clear()

        # PERFORMANCE: Use heapq.nlargest instead of sort + slice for top-N
        # This is O(n log k) instead of O(n log n) where k = max_total_results
        # Ergebnisse aggregieren
        for symbol_signals in results:
            if symbol_signals:
                symbols_with_signals += 1
                all_signals.extend(symbol_signals)

        # =====================================================================
        # STABILITY-FIRST-FILTER (Phase 6)
        # Filtert Signale basierend auf Symbol-Stability NACH der Analyse
        # =====================================================================
        if self.config.enable_stability_first:
            pre_stability_count = len(all_signals)
            all_signals, stability_stats = self._filter_by_stability(all_signals)
            if stability_stats.get('filtered', 0) > 0:
                logger.info(
                    f"Stability-First: {pre_stability_count} → {len(all_signals)} signals "
                    f"(Premium: {stability_stats.get('premium_kept', 0)}, "
                    f"Good: {stability_stats.get('good_kept', 0)}, "
                    f"OK: {stability_stats.get('ok_kept', 0)})"
                )

        # PERFORMANCE: nlargest is faster than full sort when k << n
        max_results = self.config.max_total_results
        if len(all_signals) > max_results * 2:
            # Use heapq for large result sets
            all_signals = heapq.nlargest(max_results, all_signals, key=lambda x: x.score)
        else:
            # Regular sort for small result sets (heapq overhead not worth it)
            all_signals.sort(key=lambda x: x.score, reverse=True)
            all_signals = all_signals[:max_results]
        
        # Best Signal Mode: Nur bestes pro Symbol
        if mode == ScanMode.BEST_SIGNAL:
            all_signals = self._keep_best_per_symbol(all_signals)

        # Apply concentration filter to limit symbol appearances
        if mode != ScanMode.BEST_SIGNAL and self.config.max_symbol_appearances > 0:
            all_signals, concentration_stats = self._limit_symbol_concentration(
                all_signals,
                max_appearances=self.config.max_symbol_appearances
            )

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

        # Liquidity Filter: Entferne illiquide Symbole VOR dem Scan
        original_count = len(symbols)
        if self.config.enable_liquidity_filter:
            symbols = filter_liquid_symbols(symbols)
            filtered_count = original_count - len(symbols)
            if filtered_count > 0:
                logger.info(f"Liquidity filter: removed {filtered_count} illiquid symbols")

        # Fundamentals Filter: Entferne Symbole basierend auf Fundamentaldaten
        if self.config.enable_fundamentals_filter:
            pre_filter_count = len(symbols)
            symbols, filtered_reasons = self.filter_symbols_by_fundamentals(symbols)
            if len(filtered_reasons) > 0:
                logger.info(
                    f"Fundamentals filter: {len(filtered_reasons)} removed, "
                    f"{len(symbols)} remaining (from {pre_filter_count})"
                )

        strategies = self._get_strategies_for_mode(mode)

        for idx, symbol in enumerate(symbols):
            try:
                if progress_callback:
                    progress_callback(idx + 1, len(symbols), symbol)
                
                # Daten abrufen
                data = data_fetcher(symbol)
                if not data or len(data[0]) < self.config.min_data_points:
                    continue
                
                prices, volumes, highs, lows, *_ = data

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

        # =====================================================================
        # STABILITY-FIRST-FILTER (Phase 6)
        # Filtert Signale basierend auf Symbol-Stability NACH der Analyse
        # =====================================================================
        if self.config.enable_stability_first:
            pre_stability_count = len(all_signals)
            all_signals, stability_stats = self._filter_by_stability(all_signals)
            if stability_stats.get('filtered', 0) > 0:
                logger.info(
                    f"Stability-First: {pre_stability_count} → {len(all_signals)} signals "
                    f"(Premium: {stability_stats.get('premium_kept', 0)}, "
                    f"Good: {stability_stats.get('good_kept', 0)}, "
                    f"OK: {stability_stats.get('ok_kept', 0)})"
                )

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
        # Fallback for future modes
        return None  # pragma: no cover
    
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

    def _limit_symbol_concentration(
        self,
        signals: List[TradeSignal],
        max_appearances: int = 2
    ) -> Tuple[List[TradeSignal], Dict[str, int]]:
        """
        Begrenzt die Anzahl der Signale pro Symbol für Portfolio-Diversifikation.

        Verhindert zu hohe Konzentration auf einzelne Symbole in Multi-Strategy Scans.
        Behält die besten N Signale pro Symbol basierend auf Score.

        Args:
            signals: Liste aller Signale (bereits nach Score sortiert)
            max_appearances: Max Anzahl Signale pro Symbol (default: 2)

        Returns:
            Tuple of (filtered_signals, concentration_stats)
        """
        if max_appearances <= 0:
            return signals, {}

        symbol_counts: Dict[str, int] = {}
        filtered: List[TradeSignal] = []
        removed_count = 0

        # Signals sollten bereits nach Score sortiert sein
        for signal in signals:
            symbol = signal.symbol
            current_count = symbol_counts.get(symbol, 0)

            if current_count < max_appearances:
                filtered.append(signal)
                symbol_counts[symbol] = current_count + 1
            else:
                removed_count += 1

        # Log wenn viele Signale entfernt wurden
        if removed_count > 0 and self.config.warn_on_concentration:
            logger.info(
                f"Concentration filter: Removed {removed_count} signals "
                f"(max {max_appearances} per symbol)"
            )

        return filtered, symbol_counts
    
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
            # Reliability Badge wenn verfügbar
            rel_badge = ""
            if signal.reliability_grade:
                wr = signal.reliability_win_rate or 0
                rel_badge = f" [{signal.reliability_grade}] {wr:.0f}%"

            lines.append(
                f"{i:2}. {signal.symbol:6} | {signal.strategy:15} | "
                f"Score: {signal.score:4.1f} | {signal.strength.value:8}{rel_badge}"
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
    min_score: float = 3.5,  # Normalized 0-10 scale
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
    min_score: float = 3.5  # Normalized 0-10 scale
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
