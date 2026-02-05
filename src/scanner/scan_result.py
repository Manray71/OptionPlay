# OptionPlay - Scan Result
# =========================
"""
Data structures for scan results.

Extracted from multi_strategy_scanner.py (Phase 5 - Monolith Aufbrechen).
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Callable, Tuple

try:
    from ..models.base import TradeSignal
except ImportError:
    from models.base import TradeSignal


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
