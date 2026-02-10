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
from typing import List, Dict, Optional, Callable, Tuple, Any
from datetime import datetime, date
from enum import Enum

from ..analyzers.base import BaseAnalyzer
from ..analyzers.context import AnalysisContext
from ..analyzers.pullback import PullbackAnalyzer
from ..analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from ..analyzers.bounce import BounceAnalyzer, BounceConfig
from ..analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from ..analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
from ..analyzers.pool import AnalyzerPool, PoolConfig, get_analyzer_pool
from ..models.base import TradeSignal, SignalType, SignalStrength
from ..config import PullbackScoringConfig
from ..config.liquidity_blacklist import is_illiquid, filter_liquid_symbols
from ..constants.trading_rules import ENTRY_STABILITY_MIN, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX, ENTRY_EARNINGS_MIN_DAYS

# Optional dependencies — these may not be available in all environments
try:
    from ..backtesting import ReliabilityScorer, ScorerConfig
except ImportError:
    ReliabilityScorer = None
    ScorerConfig = None

try:
    from ..backtesting import (
        calculate_symbol_stability,
        get_symbol_stability_score,
        OUTCOME_DB_PATH,
    )
except ImportError:
    calculate_symbol_stability = None
    get_symbol_stability_score = None
    OUTCOME_DB_PATH = None

try:
    from ..cache.symbol_fundamentals import (
        SymbolFundamentalsManager,
        get_fundamentals_manager,
        SymbolFundamentals,
    )
except ImportError:
    SymbolFundamentalsManager = None
    get_fundamentals_manager = None
    SymbolFundamentals = None

# E.5: Dividend-Gap-Handling
try:
    from ..cache.dividend_history import get_dividend_history_manager
except ImportError:
    get_dividend_history_manager = None

logger = logging.getLogger(__name__)


class ScanMode(Enum):
    """Scan-Modi für verschiedene Anwendungsfälle"""
    ALL = "all"                    # Alle Strategien
    PULLBACK_ONLY = "pullback"    # Nur Pullbacks (für Bull-Put-Spreads)
    BREAKOUT_ONLY = "breakout"    # Nur ATH Breakouts
    BOUNCE_ONLY = "bounce"        # Nur Support Bounces
    EARNINGS_DIP = "earnings_dip" # Nur Earnings Dips
    TREND_ONLY = "trend_continuation"  # Nur Trend Continuation
    BEST_SIGNAL = "best"          # Nur bestes Signal pro Symbol


@dataclass
class ScanConfig:
    """Konfiguration für den Scanner"""
    # Score-Filter (normalized 0-10 scale)
    min_score: float = 3.5  # Minimum score for signal (normalized)
    min_actionable_score: float = 5.0  # Strong actionable signal

    # Earnings-Filter
    exclude_earnings_within_days: int = ENTRY_EARNINGS_MIN_DAYS

    # IV-Rank Filter (für Credit-Spreads wichtig!)
    iv_rank_minimum: float = 30.0   # Min IV-Rank für ausreichend Prämie
    iv_rank_maximum: float = 80.0   # Max IV-Rank (zu hohe IV = erhöhtes Risiko)
    enable_iv_filter: bool = True   # IV-Filter aktivieren/deaktivieren

    # Liquidity Filter (basiert auf historischen Options-Daten)
    enable_liquidity_filter: bool = True  # Illiquide Symbole ausschließen

    # Output-Limits
    max_results_per_symbol: int = 3
    max_total_results: int = 50

    # Portfolio Concentration (verhindert zu viel Exposure auf ein Symbol)
    max_symbol_appearances: int = 2  # Max Anzahl ein Symbol in Multi-Strategy Results
    warn_on_concentration: bool = True  # Warnung bei hoher Symbol-Konzentration

    # Parallel Processing
    max_concurrent: int = 10

    # Data Requirements
    min_data_points: int = 60

    # Strategies to enable
    enable_pullback: bool = True
    enable_ath_breakout: bool = True
    enable_bounce: bool = True
    enable_earnings_dip: bool = True
    enable_trend_continuation: bool = True

    # Analyzer Pool Settings
    use_analyzer_pool: bool = True   # Object Pooling für Performance
    pool_size_per_strategy: int = 5  # Analyzer pro Strategie im Pool

    # Reliability Scoring (Phase 3 - Hochverlässlichkeits-Framework)
    enable_reliability_scoring: bool = True  # Reliability-Grades berechnen
    reliability_model_path: Optional[str] = None  # Pfad zum trainierten Modell
    reliability_min_grade: str = "D"  # Mindest-Grade für Signale (A-F)

    # Symbol Stability Filtering (Phase 4 - Outcome-basierte Filterung)
    enable_stability_scoring: bool = True  # Stability Scores aus Backtest-DB
    stability_min_score: float = ENTRY_STABILITY_MIN  # PLAYBOOK §1: ≥70
    stability_boost_threshold: float = 70.0  # Ab diesem Score wird Score erhöht
    stability_boost_amount: float = 1.0  # Score-Boost für stabile Symbole (LEGACY)
    warn_on_volatile_symbols: bool = True  # Warnung bei volatilen Symbolen

    # =========================================================================
    # STABILITY-FIRST FILTERING (Phase 6 - Stability > Score)
    # =========================================================================
    # Basierend auf Training-Ergebnissen:
    # - Stability ≥80: 94.5% Win Rate (Premium-Symbole)
    # - Stability 70-80: 86.1% Win Rate (Gute Symbole)
    # - Stability 50-70: 75% Win Rate (Akzeptabel)
    # - Stability <50: 66.0% Win Rate (Blacklist)
    enable_stability_first: bool = True  # Stability-First-Filterung aktivieren

    # Tiered Thresholds: Je höher Stability, desto niedriger min_score erlaubt
    stability_premium_threshold: float = 80.0  # Premium-Symbole (94.5% WR)
    stability_premium_min_score: float = 4.0   # Niedrigerer Score OK für Premium
    stability_good_threshold: float = 70.0     # Gute Symbole (86.1% WR)
    stability_good_min_score: float = 5.0      # Standard Score für gute Symbole
    stability_acceptable_threshold: float = 65.0  # Akzeptable Symbole (65-70, WARNING)
    stability_acceptable_min_score: float = 5.5   # Leicht höherer Score für 65-70 Range
    stability_ok_threshold: float = 50.0       # Grenzwertige Symbole
    stability_ok_min_score: float = 6.0        # Höherer Score für grenzwertige Symbole
    # Symbole unter stability_ok_threshold werden komplett gefiltert (Blacklist)

    # Win Rate Integration (Phase 5 - Proportionale Integration)
    # Formel: adjusted_score = base_score * (base_multiplier + win_rate/win_rate_divisor)
    # Beispiel: base=0.7, divisor=300, WR=90% => Multiplier = 0.7 + 0.30 = 1.0
    # Beispiel: base=0.7, divisor=300, WR=70% => Multiplier = 0.7 + 0.23 = 0.93
    enable_win_rate_integration: bool = True
    win_rate_base_multiplier: float = 0.7  # Basis-Multiplikator
    win_rate_divisor: float = 300.0  # Divisor für Win Rate (WR/Divisor = Bonus)

    # Drawdown Risk Adjustment (Phase 5 - Risk-basierte Filterung)
    enable_drawdown_adjustment: bool = True
    drawdown_penalty_threshold: float = 10.0  # Ab diesem Avg-Drawdown: Penalty
    drawdown_penalty_per_pct: float = 0.02  # Score-Reduktion pro % über Threshold

    # =========================================================================
    # FUNDAMENTALS PRE-FILTER (Phase 6 - symbol_fundamentals Integration)
    # =========================================================================
    # Filtert Symbole VOR dem Scan basierend auf Fundamentaldaten
    enable_fundamentals_filter: bool = True  # Master-Schalter

    # Stability-basierte Filterung (aus outcomes.db)
    # Note: Lowered from ENTRY_STABILITY_MIN (70) to align with stability_ok_threshold (50).
    # The Stability-First post-filter (enable_stability_first) handles tiered filtering:
    # - Premium (≥80): min_score 4.0
    # - Good (≥70): min_score 5.0
    # - OK (≥50): min_score 6.0 (requires stronger signals)
    # - <50: blacklisted
    # This prevents double-filtering where the pre-filter kills symbols that
    # the tiered system would handle appropriately with higher score requirements.
    fundamentals_min_stability: float = 50.0  # Aligned with stability_ok_threshold
    fundamentals_min_win_rate: float = 65.0   # Lowered: tiered system handles quality control

    # Volatility-basierte Filterung
    fundamentals_max_volatility: float = 70.0  # Max HV (annualisiert %)
    fundamentals_max_beta: float = 2.0         # Max Beta zu SPY

    # IV Rank aus Fundamentals (symbol_fundamentals.iv_rank_252d)
    fundamentals_iv_rank_min: float = 20.0
    fundamentals_iv_rank_max: float = 80.0

    # SPY Correlation Filter
    fundamentals_max_spy_correlation: Optional[float] = None  # z.B. 0.7
    fundamentals_min_spy_correlation: Optional[float] = None  # z.B. 0.3

    # Sector/Market Cap Filter
    fundamentals_exclude_sectors: List[str] = field(default_factory=list)
    fundamentals_include_sectors: List[str] = field(default_factory=list)
    fundamentals_exclude_market_caps: List[str] = field(default_factory=list)
    fundamentals_include_market_caps: List[str] = field(default_factory=list)

    # Blacklist/Whitelist
    # Blacklist ist zentral in fundamentals_constants.py definiert
    fundamentals_blacklist: List[str] = field(default_factory=lambda: _get_default_blacklist_scanner())
    fundamentals_whitelist: List[str] = field(default_factory=list)  # Überschreibt alle Filter


def _get_default_blacklist_scanner() -> List[str]:
    """Lädt die Default-Blacklist aus fundamentals_constants."""
    try:
        from ..config.fundamentals_constants import DEFAULT_BLACKLIST
        return DEFAULT_BLACKLIST.copy()
    except ImportError:
        try:
            from config.fundamentals_constants import DEFAULT_BLACKLIST
            return DEFAULT_BLACKLIST.copy()
        except ImportError:
            # Fallback wenn Import fehlschlägt
            return [
                "ROKU", "SNAP", "UPST", "AFRM", "MRNA", "RUN", "MSTR", "TSLA", "COIN", "SQ",
                "DAVE", "IONQ", "QBTS", "QMCO", "QUBT", "RDW", "RGTI"
            ]


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
    ) -> None:
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

        # Symbol Stability Cache (Phase 4 - Outcome-basiert)
        self._stability_cache: Dict[str, Dict] = {}
        if self.config.enable_stability_scoring and calculate_symbol_stability is not None:
            self._load_stability_cache()

        # Fundamentals Cache (Phase 6 - symbol_fundamentals Integration)
        self._fundamentals_cache: Dict[str, 'SymbolFundamentals'] = {}
        self._fundamentals_manager: Optional['SymbolFundamentalsManager'] = None
        if self.config.enable_fundamentals_filter and get_fundamentals_manager is not None:
            self._load_fundamentals_cache()

        # BatchScorer (Step 11 - vectorized re-scoring)
        self._batch_scorer = None
        self._batch_scoring_enabled = False
        try:
            from ..config.scoring_config import get_scoring_resolver
            par_config = get_scoring_resolver().get_parallelization_config()
            if par_config.get('enable_batch_scoring', False):
                from ..analyzers.batch_scorer import BatchScorer
                self._batch_scorer = BatchScorer()
                self._batch_scoring_enabled = True
                logger.info("BatchScorer enabled for vectorized re-scoring")
        except Exception as e:
            logger.debug(f"BatchScorer not available: {e}")

    def _load_stability_cache(self) -> None:
        """Lädt Symbol-Stabilitätsdaten aus der Outcome-Datenbank"""
        if calculate_symbol_stability is None:
            return

        try:
            if OUTCOME_DB_PATH and OUTCOME_DB_PATH.exists():
                self._stability_cache = calculate_symbol_stability(OUTCOME_DB_PATH)
                if self._stability_cache:
                    stable_count = sum(1 for d in self._stability_cache.values() if d.get('recommended'))
                    volatile_count = sum(1 for d in self._stability_cache.values() if d.get('blacklisted'))
                    logger.info(
                        f"Loaded stability data for {len(self._stability_cache)} symbols "
                        f"({stable_count} stable, {volatile_count} volatile)"
                    )
        except Exception as e:
            logger.warning(f"Could not load stability cache: {e}")

    def _load_fundamentals_cache(self) -> None:
        """Lädt Fundamentaldaten aus der symbol_fundamentals Tabelle"""
        if get_fundamentals_manager is None:
            return

        try:
            self._fundamentals_manager = get_fundamentals_manager()
            all_fundamentals = self._fundamentals_manager.get_all_fundamentals()

            for f in all_fundamentals:
                self._fundamentals_cache[f.symbol] = f

            # Statistiken loggen
            with_stability = sum(1 for f in all_fundamentals if f.stability_score is not None)
            with_iv_rank = sum(1 for f in all_fundamentals if f.iv_rank_252d is not None)

            logger.info(
                f"Loaded fundamentals for {len(self._fundamentals_cache)} symbols "
                f"({with_stability} with stability, {with_iv_rank} with IV rank)"
            )
        except Exception as e:
            logger.warning(f"Could not load fundamentals cache: {e}")

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

    def set_regime(self, regime: str) -> None:
        """
        Setzt das aktuelle VIX-Regime für Config-basierte Scoring-Gewichte.

        Args:
            regime: Regime-Name (low_vol, normal, elevated, high_vol, danger)
        """
        self._regime_cache = regime

    def _get_regime(self) -> str:
        """Returns cached regime or 'normal' as default."""
        return getattr(self, '_regime_cache', 'normal')

    def _get_sector(self, symbol: str) -> Optional[str]:
        """Looks up sector for a symbol from fundamentals."""
        if get_fundamentals_manager is None:
            return None
        try:
            manager = get_fundamentals_manager()
            fundamentals = manager.get_fundamentals(symbol)
            if fundamentals:
                return fundamentals.sector
        except (AttributeError, ValueError) as e:
            logger.debug("Sector lookup failed for %s: %s", symbol, e)
        return None

    def _set_dividend_context(self, context: AnalysisContext, symbol: str) -> None:
        """E.5: Sets dividend context fields for gap-filtering."""
        if get_dividend_history_manager is None:
            return
        try:
            manager = get_dividend_history_manager()
            today = date.today()
            context.is_near_ex_dividend = manager.is_near_ex_dividend(symbol, today)
            if context.is_near_ex_dividend:
                context.ex_dividend_amount = manager.get_ex_dividend_amount(symbol, today)
        except Exception as e:
            logger.debug("Dividend lookup failed for %s: %s", symbol, e)

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

        if self.config.enable_trend_continuation:
            pool.register_factory(
                "trend_continuation",
                lambda: TrendContinuationAnalyzer(TrendContinuationConfig())
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

        if self.config.enable_trend_continuation:
            self._analyzers['trend_continuation'] = TrendContinuationAnalyzer()

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
            context = AnalysisContext.from_data(
                symbol, prices, volumes, highs, lows, opens=opens,
                regime=self._get_regime(),
                sector=self._get_sector(symbol),
            )

        # E.5: Set dividend context for gap-filtering
        if context is not None:
            self._set_dividend_context(context, symbol)

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

    def _batch_rescore_signals(self, signals: List[TradeSignal]) -> List[TradeSignal]:
        """
        Re-score signals using BatchScorer for consistent cross-strategy normalization.

        Extracts component scores from signal details, groups by strategy,
        and applies vectorized re-scoring with YAML-configured weights.

        Args:
            signals: List of TradeSignals with score_breakdown in details

        Returns:
            Signals with updated normalized scores
        """
        if not self._batch_scorer or not signals:
            return signals

        try:
            import numpy as np

            # Group signals by strategy
            strategy_groups: Dict[str, List[int]] = {}
            for i, sig in enumerate(signals):
                strategy_groups.setdefault(sig.strategy, []).append(i)

            regime = self._get_regime()

            for strategy, indices in strategy_groups.items():
                # Extract component scores from details
                component_names: Optional[List[str]] = None
                rows = []
                sectors = []
                valid_indices = []

                for idx in indices:
                    sig = signals[idx]
                    breakdown = (sig.details or {}).get('score_breakdown', {})
                    components = breakdown.get('components', {})

                    if not components:
                        continue

                    # Use first signal's component names as reference
                    if component_names is None:
                        component_names = sorted(components.keys())

                    # Extract scores in consistent order
                    row = [
                        components.get(name, {}).get('score', 0.0)
                        for name in component_names
                    ]
                    rows.append(row)
                    sectors.append(
                        sig.details.get('sector')
                        or (sig.details.get('score_breakdown', {}).get('sector', {}).get('name'))
                        or self._get_sector(sig.symbol)
                    )
                    valid_indices.append(idx)

                if not rows or component_names is None:
                    continue

                # Build matrix and score
                matrix = np.array(rows, dtype=np.float64)
                new_scores = self._batch_scorer.score_batch(
                    strategy=strategy,
                    regime=regime,
                    sectors=sectors,
                    component_matrix=matrix,
                    component_names=component_names,
                )

                # Update signal scores
                for i, idx in enumerate(valid_indices):
                    old_score = signals[idx].score
                    signals[idx].score = float(new_scores[i])
                    if signals[idx].details is not None:
                        signals[idx].details['batch_rescored'] = True
                        signals[idx].details['pre_batch_score'] = old_score

            logger.debug(f"BatchScorer re-scored {len(signals)} signals")

        except Exception as e:
            logger.warning(f"BatchScorer re-scoring failed, keeping original scores: {e}")

        return signals

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

        # Get strategy-aware stability thresholds from trained config (Iter 5)
        try:
            from ..config.scoring_config import get_scoring_resolver
            resolver = get_scoring_resolver()
        except (ImportError, AttributeError):
            resolver = None

        regime = self._get_regime()

        filtered = []
        stats = {
            'total': len(signals),
            'premium_kept': 0,
            'good_kept': 0,
            'ok_kept': 0,
            'blacklisted': 0,
            'no_stability_data': 0,
            'score_too_low': 0,
            'below_strategy_threshold': 0,
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

            # Strategy-aware minimum stability check (Iter 5 trained thresholds)
            if resolver and signal.strategy:
                sector = None
                f = self._fundamentals_cache.get(signal.symbol.upper())
                if f:
                    sector = f.sector
                min_stability = resolver.get_stability_threshold(
                    regime, sector, strategy=signal.strategy
                )
                if stability_score < min_stability:
                    stats['below_strategy_threshold'] += 1
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

            elif stability_score >= self.config.stability_acceptable_threshold:
                # Akzeptables Symbol (65-70, WARNING): Leicht höherer Score
                if signal.score >= self.config.stability_acceptable_min_score:
                    filtered.append(signal)
                    stats['ok_kept'] += 1
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
                f"OK: {stats['ok_kept']}, Blacklisted: {stats['blacklisted']}, "
                f"BelowStratThresh: {stats['below_strategy_threshold']})"
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

        # G.1: Pre-compute market context once for ALL symbols (SPY trend is global)
        precomputed_market_score: Optional[float] = None
        precomputed_market_trend: Optional[str] = None
        try:
            spy_data = await data_fetcher("SPY")
            if spy_data and len(spy_data[0]) >= 50:
                spy_prices = spy_data[0]
                from ..analyzers.feature_scoring_mixin import FeatureScoringMixin
                _scorer = FeatureScoringMixin()
                mc_result = _scorer._score_market_context(spy_prices)
                precomputed_market_score = mc_result[0]
                precomputed_market_trend = mc_result[1]
                logger.debug(
                    f"G.1: Pre-computed market context: {precomputed_market_trend} "
                    f"(score={precomputed_market_score})"
                )
        except Exception as e:
            logger.debug(f"G.1: Could not pre-compute market context: {e}")

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
                        context = AnalysisContext.from_data(
                            symbol, prices, volumes, highs, lows, opens=opens,
                            regime=self._get_regime(),
                            sector=self._get_sector(symbol),
                        )
                        # G.1: Inject pre-computed market context
                        if precomputed_market_score is not None:
                            context.market_context_score = precomputed_market_score
                            context.market_context_trend = precomputed_market_trend
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
        # BATCH RE-SCORING (Step 11 - vectorized normalization)
        # Re-scores signals using BatchScorer for consistent YAML-based weights
        # =====================================================================
        if self._batch_scoring_enabled and all_signals:
            all_signals = self._batch_rescore_signals(all_signals)

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

        # G.1: Pre-compute market context once (sync path)
        sync_market_score: Optional[float] = None
        sync_market_trend: Optional[str] = None
        try:
            spy_data = data_fetcher("SPY")
            if spy_data and len(spy_data[0]) >= 50:
                spy_prices = spy_data[0]
                from ..analyzers.feature_scoring_mixin import FeatureScoringMixin
                _scorer = FeatureScoringMixin()
                mc_result = _scorer._score_market_context(spy_prices)
                sync_market_score = mc_result[0]
                sync_market_trend = mc_result[1]
        except Exception as e:
            logger.debug(f"G.1: Could not pre-compute market context (sync): {e}")

        for idx, symbol in enumerate(symbols):
            try:
                if progress_callback:
                    progress_callback(idx + 1, len(symbols), symbol)

                # Daten abrufen
                data = data_fetcher(symbol)
                if not data or len(data[0]) < self.config.min_data_points:
                    continue

                prices, volumes, highs, lows, *_ = data

                # G.1: Create context with pre-computed market data
                ctx = AnalysisContext.from_data(
                    symbol, prices, volumes, highs, lows,
                    regime=self._get_regime(),
                    sector=self._get_sector(symbol),
                )
                if sync_market_score is not None:
                    ctx.market_context_score = sync_market_score
                    ctx.market_context_trend = sync_market_trend

                # Analysieren
                signals = self.analyze_symbol(
                    symbol=symbol,
                    prices=prices,
                    volumes=volumes,
                    highs=highs,
                    lows=lows,
                    strategies=strategies,
                    context=ctx,
                )
                
                if signals:
                    symbols_with_signals += 1
                    all_signals.extend(signals)
                    
            except Exception as e:
                errors.append(f"{symbol}: {str(e)}")

        # =====================================================================
        # BATCH RE-SCORING (Step 11 - vectorized normalization)
        # =====================================================================
        if self._batch_scoring_enabled and all_signals:
            all_signals = self._batch_rescore_signals(all_signals)

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
        elif mode == ScanMode.TREND_ONLY:
            return ['trend_continuation']
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
    enable_trend_continuation: bool = True,
    min_score: float = 3.5,  # Normalized 0-10 scale
    exclude_earnings_days: int = ENTRY_EARNINGS_MIN_DAYS
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
        enable_earnings_dip=enable_earnings_dip,
        enable_trend_continuation=enable_trend_continuation,
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
