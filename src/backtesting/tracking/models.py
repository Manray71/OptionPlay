# OptionPlay - Trade Tracking Models
# ===================================
# Dataclasses und Enums für Trade-Tracking
#
# Extrahiert aus trade_tracker.py im Rahmen des Recursive Logic Refactorings (Phase 2.3)

import json
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import List, Dict, Optional, Any


class TradeStatus(Enum):
    """Status eines Trades"""
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TradeOutcome(Enum):
    """Ergebnis eines geschlossenen Trades"""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    PENDING = "pending"


@dataclass
class TrackedTrade:
    """
    Ein getrackter Trade mit allen relevanten Daten für Training.

    Enthält Signal-Informationen, Einstieg, Ausstieg und Outcome.
    """
    # Identifikation
    id: Optional[int] = None
    symbol: str = ""
    strategy: str = ""

    # Signal bei Einstieg
    signal_date: Optional[date] = None
    signal_score: float = 0.0
    signal_strength: str = ""
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    # Marktkontext
    vix_at_signal: Optional[float] = None
    iv_rank_at_signal: Optional[float] = None

    # Preise
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None

    # Trade-Status
    status: TradeStatus = TradeStatus.OPEN
    outcome: TradeOutcome = TradeOutcome.PENDING

    # Exit-Informationen
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""

    # P&L
    pnl_amount: Optional[float] = None
    pnl_percent: Optional[float] = None

    # Holding Period
    holding_days: Optional[int] = None

    # Reliability bei Signal (für Vergleich)
    signal_reliability_grade: Optional[str] = None
    signal_reliability_win_rate: Optional[float] = None

    # Meta
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    notes: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        result = {
            'id': self.id,
            'symbol': self.symbol,
            'strategy': self.strategy,
            'signal_date': self.signal_date.isoformat() if self.signal_date else None,
            'signal_score': self.signal_score,
            'signal_strength': self.signal_strength,
            'score_breakdown': self.score_breakdown,
            'vix_at_signal': self.vix_at_signal,
            'iv_rank_at_signal': self.iv_rank_at_signal,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'target_price': self.target_price,
            'status': self.status.value,
            'outcome': self.outcome.value,
            'exit_date': self.exit_date.isoformat() if self.exit_date else None,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'pnl_amount': self.pnl_amount,
            'pnl_percent': self.pnl_percent,
            'holding_days': self.holding_days,
            'signal_reliability_grade': self.signal_reliability_grade,
            'signal_reliability_win_rate': self.signal_reliability_win_rate,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'notes': self.notes,
            'tags': self.tags,
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackedTrade":
        """Erstellt TrackedTrade aus Dictionary"""
        return cls(
            id=data.get('id'),
            symbol=data.get('symbol', ''),
            strategy=data.get('strategy', ''),
            signal_date=date.fromisoformat(data['signal_date']) if data.get('signal_date') else None,
            signal_score=data.get('signal_score', 0.0),
            signal_strength=data.get('signal_strength', ''),
            score_breakdown=data.get('score_breakdown', {}),
            vix_at_signal=data.get('vix_at_signal'),
            iv_rank_at_signal=data.get('iv_rank_at_signal'),
            entry_price=data.get('entry_price'),
            stop_loss=data.get('stop_loss'),
            target_price=data.get('target_price'),
            status=TradeStatus(data.get('status', 'open')),
            outcome=TradeOutcome(data.get('outcome', 'pending')),
            exit_date=date.fromisoformat(data['exit_date']) if data.get('exit_date') else None,
            exit_price=data.get('exit_price'),
            exit_reason=data.get('exit_reason', ''),
            pnl_amount=data.get('pnl_amount'),
            pnl_percent=data.get('pnl_percent'),
            holding_days=data.get('holding_days'),
            signal_reliability_grade=data.get('signal_reliability_grade'),
            signal_reliability_win_rate=data.get('signal_reliability_win_rate'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.now(),
            notes=data.get('notes', ''),
            tags=data.get('tags', []),
        )


@dataclass
class TradeStats:
    """Aggregierte Trade-Statistiken"""
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0

    wins: int = 0
    losses: int = 0
    breakeven: int = 0

    win_rate: float = 0.0
    avg_pnl_percent: float = 0.0
    total_pnl: float = 0.0

    avg_holding_days: float = 0.0
    avg_score: float = 0.0

    # By Score Bucket
    by_score_bucket: Dict[str, Dict] = field(default_factory=dict)

    # By Strategy
    by_strategy: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class PriceBar:
    """Eine einzelne Preis-Kerze (OHLCV)"""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'date': self.date.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PriceBar":
        return cls(
            date=date.fromisoformat(data['date']),
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume'],
        )


@dataclass
class SymbolPriceData:
    """Historische Preisdaten für ein Symbol"""
    symbol: str
    bars: List[PriceBar]
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    bar_count: int = 0

    def __post_init__(self) -> None:
        if self.bars:
            self.first_date = min(b.date for b in self.bars)
            self.last_date = max(b.date for b in self.bars)
            self.bar_count = len(self.bars)


@dataclass
class VixDataPoint:
    """Ein VIX-Datenpunkt"""
    date: date
    value: float

    def to_dict(self) -> Dict[str, Any]:
        return {'date': self.date.isoformat(), 'value': self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VixDataPoint":
        return cls(
            date=date.fromisoformat(data['date']),
            value=data['value'],
        )


@dataclass
class OptionBar:
    """Historische Options-Preis-Kerze (OHLCV)"""
    occ_symbol: str       # OCC Symbol (z.B. AAPL240119P00150000)
    underlying: str       # Underlying Symbol
    strike: float
    expiry: date
    option_type: str      # 'P' or 'C'
    trade_date: date      # Handelstag
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'occ_symbol': self.occ_symbol,
            'underlying': self.underlying,
            'strike': self.strike,
            'expiry': self.expiry.isoformat(),
            'option_type': self.option_type,
            'trade_date': self.trade_date.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptionBar":
        return cls(
            occ_symbol=data['occ_symbol'],
            underlying=data['underlying'],
            strike=data['strike'],
            expiry=date.fromisoformat(data['expiry']),
            option_type=data['option_type'],
            trade_date=date.fromisoformat(data['trade_date']),
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume'],
        )
