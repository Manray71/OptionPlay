# OptionPlay - Portfolio Manager
# ==============================
# Tracks open positions, P&L, and trade history for Bull-Put-Spreads.
#
# Features:
# - Position tracking (open/closed)
# - P&L calculation (realized/unrealized)
# - Trade history with notes
# - JSON persistence
# - Optional IBKR integration for live prices

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    """Position status."""

    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    ASSIGNED = "assigned"


class TradeAction(Enum):
    """Trade action type."""

    OPEN = "open"
    CLOSE = "close"
    ADJUST = "adjust"
    ROLL = "roll"
    EXPIRE = "expire"
    ASSIGN = "assign"


@dataclass
class SpreadLeg:
    """Single leg of an options spread."""

    strike: float
    expiration: str  # YYYY-MM-DD
    right: str  # 'P' or 'C'
    quantity: int  # Positive = long, negative = short
    premium: float  # Per contract (positive = credit, negative = debit)

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpreadLeg":
        return cls(**data)


@dataclass
class BullPutSpread:
    """
    Bull Put Spread position.

    Structure:
    - Short put at higher strike (collect premium)
    - Long put at lower strike (protection)

    Max Profit: Net credit received
    Max Loss: (Spread width - Net credit) * 100 * contracts
    """

    id: str
    symbol: str
    short_leg: SpreadLeg
    long_leg: SpreadLeg
    contracts: int
    open_date: str  # YYYY-MM-DD
    status: PositionStatus = PositionStatus.OPEN
    close_date: Optional[str] = None
    close_premium: Optional[float] = None  # Premium paid to close
    notes: str = ""
    tags: List[str] = field(default_factory=list)

    @property
    def spread_width(self) -> float:
        """Width between strikes."""
        return abs(self.short_leg.strike - self.long_leg.strike)

    @property
    def net_credit(self) -> float:
        """Net credit received per contract."""
        # Short leg premium is positive (received), long leg is negative (paid)
        return self.short_leg.premium + self.long_leg.premium

    @property
    def total_credit(self) -> float:
        """Total credit received (all contracts)."""
        return self.net_credit * self.contracts * 100

    @property
    def max_profit(self) -> float:
        """Maximum profit if expires OTM."""
        return self.total_credit

    @property
    def max_loss(self) -> float:
        """Maximum loss if assigned."""
        return (self.spread_width - self.net_credit) * self.contracts * 100

    @property
    def breakeven(self) -> float:
        """Breakeven price at expiration."""
        return self.short_leg.strike - self.net_credit

    @property
    def expiration(self) -> str:
        """Expiration date (same for both legs)."""
        return self.short_leg.expiration

    @property
    def days_to_expiration(self) -> int:
        """Days until expiration."""
        try:
            exp_date = datetime.strptime(self.expiration, "%Y-%m-%d").date()
            return (exp_date - date.today()).days
        except ValueError:
            return 0

    @property
    def is_expired(self) -> bool:
        """Check if position is expired."""
        return self.days_to_expiration <= 0

    def realized_pnl(self) -> Optional[float]:
        """
        Calculate realized P&L for closed positions.

        Returns:
            P&L in dollars or None if still open
        """
        if self.status == PositionStatus.OPEN:
            return None

        if self.status == PositionStatus.EXPIRED:
            # Expired worthless = keep full credit
            return self.total_credit

        if self.status == PositionStatus.CLOSED and self.close_premium is not None:
            # Closed position: credit received - cost to close
            cost_to_close = self.close_premium * self.contracts * 100
            return self.total_credit - cost_to_close

        if self.status == PositionStatus.ASSIGNED:
            # Assigned = max loss
            return -self.max_loss

        return None

    def unrealized_pnl(self, current_spread_value: float) -> float:
        """
        Calculate unrealized P&L for open positions.

        Args:
            current_spread_value: Current market value of spread (per contract)

        Returns:
            Unrealized P&L in dollars
        """
        if self.status != PositionStatus.OPEN:
            return 0.0

        # P&L = credit received - current cost to close
        current_cost = current_spread_value * self.contracts * 100
        return self.total_credit - current_cost

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "short_leg": self.short_leg.to_dict(),
            "long_leg": self.long_leg.to_dict(),
            "contracts": self.contracts,
            "open_date": self.open_date,
            "status": self.status.value,
            "close_date": self.close_date,
            "close_premium": self.close_premium,
            "notes": self.notes,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BullPutSpread":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            symbol=data["symbol"],
            short_leg=SpreadLeg.from_dict(data["short_leg"]),
            long_leg=SpreadLeg.from_dict(data["long_leg"]),
            contracts=data["contracts"],
            open_date=data["open_date"],
            status=PositionStatus(data["status"]),
            close_date=data.get("close_date"),
            close_premium=data.get("close_premium"),
            notes=data.get("notes", ""),
            tags=data.get("tags", []),
        )


@dataclass
class TradeRecord:
    """Record of a trade action."""

    id: str
    position_id: str
    action: TradeAction
    timestamp: str  # ISO format
    symbol: str
    details: Dict[str, Any]
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "position_id": self.position_id,
            "action": self.action.value,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "details": self.details,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeRecord":
        return cls(
            id=data["id"],
            position_id=data["position_id"],
            action=TradeAction(data["action"]),
            timestamp=data["timestamp"],
            symbol=data["symbol"],
            details=data["details"],
            notes=data.get("notes", ""),
        )


@dataclass
class PortfolioSummary:
    """Summary of portfolio statistics."""

    total_positions: int
    open_positions: int
    closed_positions: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    win_rate: float  # Percentage of profitable closed trades
    avg_profit: float  # Average P&L per closed trade
    total_capital_at_risk: float  # Sum of max loss for open positions
    positions_expiring_soon: int  # Within 7 days


class PortfolioManager:
    """
    Manages options portfolio with persistence.

    Features:
    - Add/close/adjust positions
    - Track P&L (realized/unrealized)
    - Trade history
    - JSON file persistence
    - Portfolio statistics

    Usage:
        portfolio = PortfolioManager()

        # Add a position
        position = portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2025-03-21",
            net_credit=1.50,
            contracts=2
        )

        # Close position
        portfolio.close_position(position.id, close_premium=0.30)

        # Get summary
        summary = portfolio.get_summary()
    """

    DEFAULT_FILE = Path.home() / ".optionplay" / "portfolio.json"

    def __init__(self, filepath: Optional[Path] = None) -> None:
        """
        Initialize portfolio manager.

        Args:
            filepath: Path to portfolio JSON file (optional)
        """
        self.filepath = filepath or self.DEFAULT_FILE
        self._positions: Dict[str, BullPutSpread] = {}
        self._trades: List[TradeRecord] = []
        self._load()

    def _load(self):
        """Load portfolio from file."""
        if not self.filepath.exists():
            logger.debug(f"Portfolio file not found: {self.filepath}")
            return

        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)

            # Load positions
            for pos_data in data.get("positions", []):
                pos = BullPutSpread.from_dict(pos_data)
                self._positions[pos.id] = pos

            # Load trades
            for trade_data in data.get("trades", []):
                self._trades.append(TradeRecord.from_dict(trade_data))

            logger.info(
                f"Loaded portfolio: {len(self._positions)} positions, {len(self._trades)} trades"
            )

        except Exception as e:
            logger.error(f"Error loading portfolio: {e}")

    def _save(self):
        """Save portfolio to file."""
        try:
            # Ensure directory exists
            self.filepath.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": "1.0",
                "updated": datetime.now().isoformat(),
                "positions": [pos.to_dict() for pos in self._positions.values()],
                "trades": [trade.to_dict() for trade in self._trades],
            }

            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Portfolio saved: {self.filepath}")

        except Exception as e:
            logger.error(f"Error saving portfolio: {e}")
            raise

    def _generate_id(self) -> str:
        """Generate unique ID."""
        return str(uuid.uuid4())[:8]

    def _record_trade(
        self, position: BullPutSpread, action: TradeAction, details: Dict[str, Any], notes: str = ""
    ):
        """Record a trade action."""
        trade = TradeRecord(
            id=self._generate_id(),
            position_id=position.id,
            action=action,
            timestamp=datetime.now().isoformat(),
            symbol=position.symbol,
            details=details,
            notes=notes,
        )
        self._trades.append(trade)

    def _notify_ensemble(
        self,
        position: BullPutSpread,
        outcome: bool,
        pnl: float,
        strategy: Optional[str] = None,
    ):
        """
        Notify ensemble meta-learner of trade outcome.

        Extracts strategy from position tags (e.g. "strategy:pullback")
        or uses the provided strategy parameter.
        """
        # Determine strategy from tags or parameter
        if strategy is None:
            for tag in position.tags:
                if tag.startswith("strategy:"):
                    strategy = tag.split(":", 1)[1]
                    break

        if strategy is None:
            logger.debug(
                f"No strategy tag for {position.symbol} ({position.id}), "
                f"skipping ensemble notification"
            )
            return

        try:
            from ..backtesting.ensemble.selector import EnsembleSelector

            selector = EnsembleSelector.load_trained_model()
            credit = position.total_credit
            pnl_percent = (pnl / credit * 100) if credit > 0 else 0.0

            selector.update_with_result(
                symbol=position.symbol,
                strategy=strategy,
                outcome=outcome,
                pnl_percent=pnl_percent,
                signal_date=date.today(),
            )
            logger.info(
                f"Ensemble notified: {position.symbol} {strategy} "
                f"{'WIN' if outcome else 'LOSS'} ({pnl_percent:+.1f}%)"
            )
        except Exception as e:
            logger.warning(f"Could not notify ensemble: {e}")

    # =========================================================================
    # POSITION MANAGEMENT
    # =========================================================================

    def add_bull_put_spread(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        net_credit: float,
        contracts: int = 1,
        short_premium: Optional[float] = None,
        long_premium: Optional[float] = None,
        notes: str = "",
        tags: Optional[List[str]] = None,
    ) -> BullPutSpread:
        """
        Add a new Bull Put Spread position.

        Args:
            symbol: Underlying symbol
            short_strike: Short put strike (higher)
            long_strike: Long put strike (lower)
            expiration: Expiration date (YYYY-MM-DD)
            net_credit: Net credit per contract
            contracts: Number of spreads
            short_premium: Premium received for short put (optional)
            long_premium: Premium paid for long put (optional)
            notes: Trade notes
            tags: Tags for categorization

        Returns:
            Created BullPutSpread position
        """
        # Validate
        if short_strike <= long_strike:
            raise ValueError("Short strike must be higher than long strike for Bull Put Spread")

        if net_credit <= 0:
            raise ValueError("Net credit must be positive for Bull Put Spread")

        if contracts < 1:
            raise ValueError("Contracts must be at least 1")

        # Calculate individual premiums if not provided
        if short_premium is None or long_premium is None:
            # Estimate: short gets 70% of spread width as premium
            spread_width = short_strike - long_strike
            short_premium = net_credit * 0.7 + spread_width * 0.1
            long_premium = -(short_premium - net_credit)

        position = BullPutSpread(
            id=self._generate_id(),
            symbol=symbol.upper(),
            short_leg=SpreadLeg(
                strike=short_strike,
                expiration=expiration,
                right="P",
                quantity=-contracts,
                premium=short_premium,
            ),
            long_leg=SpreadLeg(
                strike=long_strike,
                expiration=expiration,
                right="P",
                quantity=contracts,
                premium=long_premium,
            ),
            contracts=contracts,
            open_date=date.today().isoformat(),
            notes=notes,
            tags=tags or [],
        )

        self._positions[position.id] = position

        self._record_trade(
            position,
            TradeAction.OPEN,
            {
                "short_strike": short_strike,
                "long_strike": long_strike,
                "expiration": expiration,
                "net_credit": net_credit,
                "contracts": contracts,
            },
            notes,
        )

        self._save()

        logger.info(
            f"Added Bull Put Spread: {symbol} "
            f"${long_strike}/{short_strike} exp {expiration} "
            f"x{contracts} @ ${net_credit:.2f} credit"
        )

        return position

    def close_position(
        self,
        position_id: str,
        close_premium: float,
        notes: str = "",
        strategy: Optional[str] = None,
    ) -> BullPutSpread:
        """
        Close a position by buying back the spread.

        Args:
            position_id: Position ID
            close_premium: Premium paid to close (per contract)
            notes: Close notes
            strategy: Strategy name for ensemble feedback (optional)

        Returns:
            Updated position
        """
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")

        position = self._positions[position_id]

        if position.status != PositionStatus.OPEN:
            raise ValueError(f"Position is not open: {position.status.value}")

        position.status = PositionStatus.CLOSED
        position.close_date = date.today().isoformat()
        position.close_premium = close_premium

        pnl = position.realized_pnl()

        self._record_trade(
            position,
            TradeAction.CLOSE,
            {
                "close_premium": close_premium,
                "realized_pnl": pnl,
            },
            notes,
        )

        self._save()

        logger.info(f"Closed position {position_id}: {position.symbol} " f"P&L: ${pnl:.2f}")

        # Notify ensemble of trade outcome
        if pnl is not None:
            self._notify_ensemble(position, outcome=pnl > 0, pnl=pnl, strategy=strategy)

        return position

    def expire_position(
        self,
        position_id: str,
        notes: str = "",
        strategy: Optional[str] = None,
    ) -> BullPutSpread:
        """
        Mark position as expired worthless (full profit).

        Args:
            position_id: Position ID
            notes: Notes
            strategy: Strategy name for ensemble feedback (optional)

        Returns:
            Updated position
        """
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")

        position = self._positions[position_id]

        if position.status != PositionStatus.OPEN:
            raise ValueError(f"Position is not open: {position.status.value}")

        position.status = PositionStatus.EXPIRED
        position.close_date = date.today().isoformat()
        position.close_premium = 0.0

        pnl = position.total_credit

        self._record_trade(
            position,
            TradeAction.EXPIRE,
            {
                "realized_pnl": pnl,
            },
            notes or "Expired worthless",
        )

        self._save()

        logger.info(
            f"Position expired: {position_id} - {position.symbol} " f"Full profit: ${pnl:.2f}"
        )

        # Notify ensemble - expired worthless is always a win
        self._notify_ensemble(position, outcome=True, pnl=pnl, strategy=strategy)

        return position

    def assign_position(
        self,
        position_id: str,
        notes: str = "",
        strategy: Optional[str] = None,
    ) -> BullPutSpread:
        """
        Mark position as assigned (max loss).

        Args:
            position_id: Position ID
            notes: Notes
            strategy: Strategy name for ensemble feedback (optional)

        Returns:
            Updated position
        """
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")

        position = self._positions[position_id]

        if position.status != PositionStatus.OPEN:
            raise ValueError(f"Position is not open: {position.status.value}")

        position.status = PositionStatus.ASSIGNED
        position.close_date = date.today().isoformat()

        pnl = -position.max_loss

        self._record_trade(
            position,
            TradeAction.ASSIGN,
            {
                "realized_pnl": pnl,
            },
            notes or "Assigned",
        )

        self._save()

        logger.info(
            f"Position assigned: {position_id} - {position.symbol} "
            f"Loss: ${position.max_loss:.2f}"
        )

        # Notify ensemble - assignment is always a loss
        self._notify_ensemble(position, outcome=False, pnl=pnl, strategy=strategy)

        return position

    def delete_position(self, position_id: str) -> None:
        """
        Delete a position (use with caution).

        Args:
            position_id: Position ID
        """
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")

        position = self._positions.pop(position_id)

        # Remove associated trades
        self._trades = [t for t in self._trades if t.position_id != position_id]

        self._save()

        logger.info(f"Deleted position: {position_id} - {position.symbol}")

    def update_notes(self, position_id: str, notes: str) -> None:
        """Update position notes."""
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")

        self._positions[position_id].notes = notes
        self._save()

    def add_tag(self, position_id: str, tag: str) -> None:
        """Add tag to position."""
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")

        position = self._positions[position_id]
        if tag not in position.tags:
            position.tags.append(tag)
            self._save()

    # =========================================================================
    # QUERIES
    # =========================================================================

    def get_position(self, position_id: str) -> Optional[BullPutSpread]:
        """Get position by ID."""
        return self._positions.get(position_id)

    def get_all_positions(self) -> List[BullPutSpread]:
        """Get all positions."""
        return list(self._positions.values())

    def get_open_positions(self) -> List[BullPutSpread]:
        """Get all open positions."""
        return [p for p in self._positions.values() if p.status == PositionStatus.OPEN]

    def get_closed_positions(self) -> List[BullPutSpread]:
        """Get all closed positions."""
        return [p for p in self._positions.values() if p.status != PositionStatus.OPEN]

    def get_positions_by_symbol(self, symbol: str) -> List[BullPutSpread]:
        """Get positions for a symbol."""
        symbol = symbol.upper()
        return [p for p in self._positions.values() if p.symbol == symbol]

    def get_expiring_soon(self, days: int = 7) -> List[BullPutSpread]:
        """Get positions expiring within N days."""
        return [p for p in self.get_open_positions() if 0 < p.days_to_expiration <= days]

    def get_trades(self, position_id: Optional[str] = None) -> List[TradeRecord]:
        """Get trade history."""
        if position_id:
            return [t for t in self._trades if t.position_id == position_id]
        return self._trades

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_summary(self, unrealized_values: Optional[Dict[str, float]] = None) -> PortfolioSummary:
        """
        Calculate portfolio summary statistics.

        Args:
            unrealized_values: Dict of position_id -> current spread value
                               (for unrealized P&L calculation)

        Returns:
            PortfolioSummary with statistics
        """
        all_positions = list(self._positions.values())
        open_positions = [p for p in all_positions if p.status == PositionStatus.OPEN]
        closed_positions = [p for p in all_positions if p.status != PositionStatus.OPEN]

        # Realized P&L
        realized_pnls = [p.realized_pnl() for p in closed_positions]
        realized_pnls = [pnl for pnl in realized_pnls if pnl is not None]
        total_realized = sum(realized_pnls)

        # Win rate
        if realized_pnls:
            wins = sum(1 for pnl in realized_pnls if pnl > 0)
            win_rate = (wins / len(realized_pnls)) * 100
            avg_profit = total_realized / len(realized_pnls)
        else:
            win_rate = 0.0
            avg_profit = 0.0

        # Unrealized P&L
        total_unrealized = 0.0
        if unrealized_values:
            for pos in open_positions:
                if pos.id in unrealized_values:
                    total_unrealized += pos.unrealized_pnl(unrealized_values[pos.id])

        # Capital at risk
        total_risk = sum(p.max_loss for p in open_positions)

        # Expiring soon
        expiring_soon = len(self.get_expiring_soon(7))

        return PortfolioSummary(
            total_positions=len(all_positions),
            open_positions=len(open_positions),
            closed_positions=len(closed_positions),
            total_realized_pnl=total_realized,
            total_unrealized_pnl=total_unrealized,
            win_rate=win_rate,
            avg_profit=avg_profit,
            total_capital_at_risk=total_risk,
            positions_expiring_soon=expiring_soon,
        )

    def get_pnl_by_symbol(self) -> Dict[str, float]:
        """Get realized P&L grouped by symbol."""
        pnl_by_symbol: Dict[str, float] = {}

        for position in self.get_closed_positions():
            pnl = position.realized_pnl()
            if pnl is not None:
                symbol = position.symbol
                pnl_by_symbol[symbol] = pnl_by_symbol.get(symbol, 0.0) + pnl

        return pnl_by_symbol

    def get_monthly_pnl(self) -> Dict[str, float]:
        """Get realized P&L grouped by month."""
        pnl_by_month: Dict[str, float] = {}

        for position in self.get_closed_positions():
            if position.close_date:
                month = position.close_date[:7]  # YYYY-MM
                pnl = position.realized_pnl()
                if pnl is not None:
                    pnl_by_month[month] = pnl_by_month.get(month, 0.0) + pnl

        return dict(sorted(pnl_by_month.items()))


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_portfolio: Optional[PortfolioManager] = None


def get_portfolio_manager() -> PortfolioManager:
    """
    Get global portfolio manager instance.

    Prefers the global ServiceContainer if available, otherwise
    falls back to the module-level singleton.
    """
    # Prefer container if available
    try:
        from ..container import _default_container

        if _default_container is not None and _default_container.portfolio_manager is not None:
            return _default_container.portfolio_manager
    except ImportError:
        pass

    global _default_portfolio
    if _default_portfolio is None:
        _default_portfolio = PortfolioManager()
    return _default_portfolio


def reset_portfolio_manager() -> None:
    """Reset global portfolio manager (for testing)."""
    global _default_portfolio
    _default_portfolio = None
    try:
        from ..container import _default_container

        if _default_container is not None:
            _default_container.portfolio_manager = None
    except ImportError:
        pass
