# OptionPlay - Cache Manager Mixin
# ==================================
"""
Shared lazy-loading properties for earnings and fundamentals managers.

Eliminates duplicate lazy-loading patterns across:
- TradeValidator
- PositionMonitor
- PortfolioConstraintChecker

Usage:
    class MyService(CacheManagerMixin):
        def __init__(self):
            self._init_cache_managers()

        def check(self, symbol):
            if self.earnings:
                safe, days, reason = self.earnings.is_earnings_day_safe(symbol, ...)
"""

import logging

logger = logging.getLogger(__name__)


class CacheManagerMixin:
    """
    Mixin that provides lazy-loaded earnings and fundamentals managers.

    Call _init_cache_managers() in __init__ to initialize backing attributes.
    """

    def _init_cache_managers(self):
        """Initialize backing attributes for lazy properties."""
        self._earnings_manager = None
        self._fundamentals_manager = None

    @property
    def earnings(self):
        """Lazy-load Earnings History Manager."""
        if self._earnings_manager is None:
            try:
                from ..cache import get_earnings_history_manager
                self._earnings_manager = get_earnings_history_manager()
            except ImportError:
                logger.warning("Earnings history manager not available")
        return self._earnings_manager

    @property
    def fundamentals(self):
        """Lazy-load Fundamentals Manager."""
        if self._fundamentals_manager is None:
            try:
                from ..cache import get_fundamentals_manager
                self._fundamentals_manager = get_fundamentals_manager()
            except ImportError:
                logger.warning("Fundamentals manager not available")
        return self._fundamentals_manager
