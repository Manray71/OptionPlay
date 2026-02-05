# OptionPlay - Scanner Package
# =============================
# Multi-Strategie Scanner und Signal-Aggregation

from .market_scanner import MarketScanner
from .signal_aggregator import SignalAggregator
from .scan_config import ScanMode, ScanConfig
from .scan_result import ScanResult, DataFetcher, AsyncDataFetcher
from .multi_strategy_scanner import (
    MultiStrategyScanner,
    create_scanner,
    quick_scan
)

__all__ = [
    # Legacy
    'MarketScanner',
    'SignalAggregator',
    
    # New Multi-Strategy Scanner
    'MultiStrategyScanner',
    'ScanConfig',
    'ScanResult',
    'ScanMode',
    
    # Convenience Functions
    'create_scanner',
    'quick_scan',
]
