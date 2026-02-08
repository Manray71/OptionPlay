# OptionPlay - Analyzer Pool
# ==========================
# Object Pooling für Analyzer-Instanzen zur Performance-Optimierung.
#
# Vorteile:
# - Vermeidet wiederholte Analyzer-Instanziierung bei großen Scans
# - Thread-safe für parallele Verarbeitung
# - Konfigurierbare Pool-Größe pro Analyzer-Typ
# - Automatische Erstellung bei Bedarf
#
# Usage:
#     from src.analyzers.pool import get_analyzer_pool, AnalyzerPool
#
#     pool = get_analyzer_pool()
#
#     # Analyzer ausleihen
#     with pool.acquire("pullback") as analyzer:
#         signal = analyzer.analyze(symbol, prices, volumes, highs, lows)
#
#     # Oder manuell
#     analyzer = pool.checkout("bounce")
#     try:
#         signal = analyzer.analyze(...)
#     finally:
#         pool.checkin("bounce", analyzer)

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Type, TypeVar

from .base import BaseAnalyzer

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseAnalyzer)


@dataclass
class PoolConfig:
    """Konfiguration für den Analyzer Pool"""
    # Pool-Größen pro Analyzer-Typ
    default_pool_size: int = 5
    max_pool_size: int = 20

    # Verhalten bei leerem Pool
    create_on_empty: bool = True  # Erstelle neue Instanz wenn Pool leer
    block_on_empty: bool = False  # Warte auf Rückgabe (nur wenn create_on_empty=False)
    block_timeout: float = 5.0    # Timeout für block_on_empty

    # Pool-Größen pro Strategie (überschreibt default)
    strategy_pool_sizes: Dict[str, int] = field(default_factory=dict)

    def get_pool_size(self, strategy: str) -> int:
        """Gibt Pool-Größe für eine Strategie zurück"""
        return self.strategy_pool_sizes.get(strategy, self.default_pool_size)


@dataclass
class PoolStats:
    """Statistiken für einen Analyzer-Pool"""
    strategy: str
    pool_size: int = 0
    in_use: int = 0
    total_checkouts: int = 0
    total_creates: int = 0
    total_reuses: int = 0

    @property
    def available(self) -> int:
        """Verfügbare Analyzer im Pool"""
        return self.pool_size - self.in_use

    @property
    def reuse_rate(self) -> float:
        """Wiederverwendungsrate (0.0 - 1.0)"""
        if self.total_checkouts == 0:
            return 0.0
        return self.total_reuses / self.total_checkouts

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'strategy': self.strategy,
            'pool_size': self.pool_size,
            'in_use': self.in_use,
            'available': self.available,
            'total_checkouts': self.total_checkouts,
            'total_creates': self.total_creates,
            'total_reuses': self.total_reuses,
            'reuse_rate': round(self.reuse_rate, 3)
        }


class AnalyzerPool:
    """
    Object Pool für Analyzer-Instanzen.

    Verwaltet einen Pool von Analyzer-Instanzen pro Strategie-Typ.
    Thread-safe für parallele Verwendung in async Scans.

    Features:
    - Automatische Instanz-Erstellung bei Bedarf
    - Konfigurierbare Pool-Größen pro Strategie
    - Context Manager für sicheres Checkout/Checkin
    - Statistiken für Monitoring

    Verwendung:
        pool = AnalyzerPool()

        # Registriere Factory-Funktionen
        pool.register_factory("pullback", lambda: PullbackAnalyzer(config))
        pool.register_factory("bounce", BounceAnalyzer)

        # Verwende mit Context Manager (empfohlen)
        with pool.acquire("pullback") as analyzer:
            signal = analyzer.analyze(symbol, prices, volumes, highs, lows)

        # Oder manuell
        analyzer = pool.checkout("pullback")
        try:
            signal = analyzer.analyze(...)
        finally:
            pool.checkin("pullback", analyzer)
    """

    def __init__(self, config: Optional[PoolConfig] = None):
        """
        Initialisiert den Analyzer Pool.

        Args:
            config: Pool-Konfiguration (optional)
        """
        self.config = config or PoolConfig()

        # Pools pro Strategie: Liste von verfügbaren Analyzern
        self._pools: Dict[str, List[BaseAnalyzer]] = defaultdict(list)

        # Factory-Funktionen pro Strategie
        self._factories: Dict[str, Callable[[], BaseAnalyzer]] = {}

        # Locks für Thread-Safety
        self._pool_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._global_lock = threading.Lock()

        # Statistiken
        self._stats: Dict[str, PoolStats] = {}

        # Tracking für ausgecheckte Analyzer (für Debugging)
        self._checked_out: Dict[str, int] = defaultdict(int)

        logger.debug("AnalyzerPool initialized")

    def register_factory(
        self,
        strategy: str,
        factory: Callable[[], BaseAnalyzer]
    ) -> None:
        """
        Registriert eine Factory-Funktion für einen Strategie-Typ.

        Die Factory wird aufgerufen, wenn ein neuer Analyzer erstellt werden muss.

        Args:
            strategy: Name der Strategie (z.B. "pullback", "bounce")
            factory: Funktion die einen neuen Analyzer erstellt
        """
        with self._global_lock:
            self._factories[strategy] = factory
            if strategy not in self._stats:
                self._stats[strategy] = PoolStats(strategy=strategy)
            logger.debug(f"Registered factory for '{strategy}'")

    def register_analyzer_class(
        self,
        strategy: str,
        analyzer_class: Type[BaseAnalyzer],
        *args,
        **kwargs
    ) -> None:
        """
        Registriert eine Analyzer-Klasse mit Konstruktor-Argumenten.

        Convenience-Methode für einfache Registrierung.

        Args:
            strategy: Name der Strategie
            analyzer_class: Analyzer-Klasse
            *args, **kwargs: Konstruktor-Argumente
        """
        def factory() -> BaseAnalyzer:
            return analyzer_class(*args, **kwargs)

        self.register_factory(strategy, factory)

    def _get_lock(self, strategy: str) -> threading.Lock:
        """Gibt Lock für eine Strategie zurück (thread-safe)"""
        with self._global_lock:
            return self._pool_locks[strategy]

    def _create_analyzer(self, strategy: str) -> BaseAnalyzer:
        """
        Erstellt einen neuen Analyzer.

        Args:
            strategy: Name der Strategie

        Returns:
            Neue Analyzer-Instanz

        Raises:
            KeyError: Wenn keine Factory registriert ist
        """
        if strategy not in self._factories:
            raise KeyError(
                f"No factory registered for strategy '{strategy}'. "
                f"Available: {list(self._factories.keys())}"
            )

        analyzer = self._factories[strategy]()
        self._stats[strategy].total_creates += 1

        logger.debug(f"Created new '{strategy}' analyzer (total: {self._stats[strategy].total_creates})")

        return analyzer

    def checkout(self, strategy: str) -> BaseAnalyzer:
        """
        Checkt einen Analyzer aus dem Pool aus.

        Wenn der Pool leer ist und create_on_empty=True, wird ein neuer
        Analyzer erstellt. Andernfalls wird je nach Konfiguration gewartet
        oder ein Fehler geworfen.

        Args:
            strategy: Name der Strategie

        Returns:
            Analyzer-Instanz (ausgeliehen, muss zurückgegeben werden!)

        Raises:
            KeyError: Wenn keine Factory registriert und Pool leer
            TimeoutError: Wenn block_on_empty und Timeout erreicht
        """
        lock = self._get_lock(strategy)

        with lock:
            pool = self._pools[strategy]
            stats = self._stats.get(strategy)

            if not stats:
                self._stats[strategy] = PoolStats(strategy=strategy)
                stats = self._stats[strategy]

            stats.total_checkouts += 1

            if pool:
                # Analyzer aus Pool nehmen
                analyzer = pool.pop()
                stats.total_reuses += 1
                self._checked_out[strategy] += 1
                stats.in_use = self._checked_out[strategy]
                stats.pool_size = len(pool) + stats.in_use

                logger.debug(
                    f"Checked out '{strategy}' analyzer from pool "
                    f"(available: {len(pool)}, in_use: {stats.in_use})"
                )
                return analyzer

            # Pool ist leer
            if self.config.create_on_empty:
                analyzer = self._create_analyzer(strategy)
                self._checked_out[strategy] += 1
                stats.in_use = self._checked_out[strategy]
                stats.pool_size = stats.in_use
                return analyzer

            # TODO: Implementiere block_on_empty mit Condition Variable
            raise RuntimeError(
                f"Pool for '{strategy}' is empty and create_on_empty=False"
            )

    def checkin(self, strategy: str, analyzer: BaseAnalyzer) -> None:
        """
        Gibt einen Analyzer zurück in den Pool.

        Der Analyzer kann danach von anderen Threads wiederverwendet werden.

        Args:
            strategy: Name der Strategie
            analyzer: Zurückzugebender Analyzer
        """
        lock = self._get_lock(strategy)

        with lock:
            pool = self._pools[strategy]
            stats = self._stats.get(strategy)

            if stats:
                self._checked_out[strategy] = max(0, self._checked_out[strategy] - 1)
                stats.in_use = self._checked_out[strategy]

            max_size = self.config.get_pool_size(strategy)

            if len(pool) < max_size:
                pool.append(analyzer)
                logger.debug(
                    f"Checked in '{strategy}' analyzer to pool "
                    f"(available: {len(pool)})"
                )
            else:
                # Pool ist voll, Analyzer wird verworfen
                logger.debug(
                    f"Pool for '{strategy}' is full, discarding analyzer"
                )

            # Update pool_size AFTER potentially discarding
            if stats:
                stats.pool_size = len(pool) + stats.in_use

    @contextmanager
    def acquire(self, strategy: str) -> Generator[BaseAnalyzer, None, None]:
        """
        Context Manager für sicheres Checkout/Checkin.

        Garantiert dass der Analyzer zurückgegeben wird, auch bei Exceptions.

        Args:
            strategy: Name der Strategie

        Yields:
            Analyzer-Instanz

        Usage:
            with pool.acquire("pullback") as analyzer:
                signal = analyzer.analyze(...)
        """
        analyzer = self.checkout(strategy)
        try:
            yield analyzer
        finally:
            self.checkin(strategy, analyzer)

    def prefill(self, strategy: str, count: Optional[int] = None) -> int:
        """
        Füllt den Pool mit Analyzer-Instanzen vor.

        Nützlich für Warmup vor großen Scans.

        Args:
            strategy: Name der Strategie
            count: Anzahl zu erstellender Analyzer (default: pool_size)

        Returns:
            Anzahl erstellter Analyzer
        """
        if count is None:
            count = self.config.get_pool_size(strategy)

        lock = self._get_lock(strategy)
        created = 0

        with lock:
            pool = self._pools[strategy]
            max_size = self.config.get_pool_size(strategy)

            while len(pool) < min(count, max_size):
                analyzer = self._create_analyzer(strategy)
                pool.append(analyzer)
                created += 1

            if strategy not in self._stats:
                self._stats[strategy] = PoolStats(strategy=strategy)
            self._stats[strategy].pool_size = len(pool)

        logger.info(f"Prefilled '{strategy}' pool with {created} analyzers")
        return created

    def prefill_all(self) -> Dict[str, int]:
        """
        Füllt alle registrierten Pools vor.

        Returns:
            Dict mit Strategie -> Anzahl erstellter Analyzer
        """
        result = {}
        for strategy in self._factories:
            result[strategy] = self.prefill(strategy)
        return result

    def clear(self, strategy: Optional[str] = None) -> int:
        """
        Leert den Pool (oder alle Pools).

        Args:
            strategy: Strategie-Name (None = alle)

        Returns:
            Anzahl entfernter Analyzer
        """
        with self._global_lock:
            if strategy:
                pool = self._pools.get(strategy, [])
                count = len(pool)
                self._pools[strategy] = []
                if strategy in self._stats:
                    self._stats[strategy].pool_size = 0
                return count

            total = sum(len(p) for p in self._pools.values())
            self._pools.clear()
            for stats in self._stats.values():
                stats.pool_size = 0
            return total

    def stats(self, strategy: Optional[str] = None) -> Dict[str, Any]:
        """
        Gibt Pool-Statistiken zurück.

        Args:
            strategy: Strategie-Name (None = alle)

        Returns:
            Dict mit Statistiken
        """
        with self._global_lock:
            if strategy:
                if strategy in self._stats:
                    return self._stats[strategy].to_dict()
                return {}

            return {
                'pools': {
                    name: stats.to_dict()
                    for name, stats in self._stats.items()
                },
                'total_analyzers': sum(
                    stats.pool_size for stats in self._stats.values()
                ),
                'total_in_use': sum(
                    stats.in_use for stats in self._stats.values()
                ),
                'registered_strategies': list(self._factories.keys())
            }

    @property
    def registered_strategies(self) -> List[str]:
        """Liste aller registrierten Strategien"""
        return list(self._factories.keys())


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_pool_instance: Optional[AnalyzerPool] = None
_pool_lock = threading.Lock()


def get_analyzer_pool(config: Optional[PoolConfig] = None) -> AnalyzerPool:
    """
    Gibt die globale AnalyzerPool-Instanz zurück.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.

    Erstellt bei Bedarf eine neue Instanz.

    Args:
        config: Pool-Konfiguration (nur bei erster Erstellung verwendet)

    Returns:
        AnalyzerPool Instanz
    """
    try:
        from ..utils.deprecation import warn_singleton_usage
        warn_singleton_usage("get_analyzer_pool", "ServiceContainer.analyzer_pool")
    except ImportError:
        pass

    global _pool_instance

    with _pool_lock:
        if _pool_instance is None:
            _pool_instance = AnalyzerPool(config)
            logger.info("Global AnalyzerPool initialized")
        return _pool_instance


def reset_analyzer_pool() -> None:
    """
    Setzt den globalen Pool zurück (für Tests).
    """
    global _pool_instance

    with _pool_lock:
        if _pool_instance:
            _pool_instance.clear()
        _pool_instance = None


def configure_default_pool() -> AnalyzerPool:
    """
    Konfiguriert den globalen Pool mit Standard-Analyzern.

    Registriert alle verfügbaren Analyzer-Typen mit ihren
    Standard-Konfigurationen.

    Returns:
        Konfigurierter AnalyzerPool
    """
    from .pullback import PullbackAnalyzer
    from .bounce import BounceAnalyzer, BounceConfig
    from .ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from .earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
    from .trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig

    try:
        from ..config import PullbackScoringConfig
    except ImportError:
        from config import PullbackScoringConfig

    pool = get_analyzer_pool()

    # Registriere Standard-Analyzer
    pool.register_factory(
        "pullback",
        lambda: PullbackAnalyzer(PullbackScoringConfig())
    )

    pool.register_factory(
        "bounce",
        lambda: BounceAnalyzer(BounceConfig())
    )

    pool.register_factory(
        "ath_breakout",
        lambda: ATHBreakoutAnalyzer(ATHBreakoutConfig())
    )

    pool.register_factory(
        "earnings_dip",
        lambda: EarningsDipAnalyzer(EarningsDipConfig())
    )

    pool.register_factory(
        "trend_continuation",
        lambda: TrendContinuationAnalyzer(TrendContinuationConfig())
    )

    logger.info(f"Configured default pool with strategies: {pool.registered_strategies}")

    return pool


__all__ = [
    'AnalyzerPool',
    'PoolConfig',
    'PoolStats',
    'get_analyzer_pool',
    'reset_analyzer_pool',
    'configure_default_pool',
]
