# OptionPlay - Position Monitor Service
# ======================================
"""
Monitors open positions and generates exit signals based on PLAYBOOK §4 rules.

All exit rules are sourced from constants/trading_rules.py.
Priority order matches PLAYBOOK (lower number = higher priority):
  1. Expired (DTE <= 0) → CLOSE
  2. Force Close (DTE <= 7) → CLOSE
  3. Profit Target reached → CLOSE
  4. Stop Loss hit → CLOSE
  5. 21 DTE Decision Point → ROLL or CLOSE
  6. High VIX (>30) → CLOSE winners / ALERT losers
  7. Earnings before expiration → CLOSE
  8. Default → HOLD

Usage:
    from src.services.position_monitor import get_position_monitor

    monitor = get_position_monitor()
    result = await monitor.check_positions(snapshots, current_vix=18.0)

    for signal in result.close_signals:
        print(f"{signal.symbol}: {signal.reason}")
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..constants.trading_rules import (
    ExitAction,
    VIXRegime,
    EXIT_FORCE_CLOSE_DTE,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    EXIT_ROLL_DTE,
    ROLL_NEW_DTE_MIN,
    ROLL_NEW_DTE_MAX,
    VIX_ELEVATED_MAX,
    ENTRY_STABILITY_MIN,
    get_vix_regime,
    get_regime_rules,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PositionSnapshot:
    """
    Normalized position data from internal DB or IBKR.

    Provides a common view regardless of data source.
    """
    position_id: str
    symbol: str
    short_strike: float
    long_strike: float
    spread_width: float
    net_credit: float          # Per share
    contracts: int
    expiration: str            # YYYY-MM-DD
    dte: int
    max_profit: float          # Total in USD
    max_loss: float            # Total in USD
    breakeven: float
    source: str = "internal"   # "internal" or "ibkr"

    # Live data (optional, from IBKR)
    current_spread_value: Optional[float] = None

    # P&L (optional — set by estimate_pnl or from IBKR)
    unrealized_pnl: Optional[float] = None
    pnl_pct_of_max_profit: Optional[float] = None
    pnl_estimated: bool = False  # True if P&L is theta-estimated


@dataclass
class PositionSignal:
    """Exit signal for a single position."""
    position_id: str
    symbol: str
    action: ExitAction
    reason: str               # Human-readable
    priority: int             # 1=highest, 8=HOLD
    dte: int
    pnl_pct: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorResult:
    """Result of monitoring all positions."""
    signals: List[PositionSignal]
    vix: Optional[float] = None
    regime: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    positions_count: int = 0

    @property
    def close_signals(self) -> List[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.CLOSE]

    @property
    def roll_signals(self) -> List[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.ROLL]

    @property
    def alert_signals(self) -> List[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.ALERT]

    @property
    def hold_signals(self) -> List[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.HOLD]


# =============================================================================
# SNAPSHOT BUILDERS
# =============================================================================

def snapshot_from_internal(position) -> PositionSnapshot:
    """
    Build PositionSnapshot from internal BullPutSpread.

    Args:
        position: BullPutSpread instance from portfolio manager
    """
    return PositionSnapshot(
        position_id=position.id,
        symbol=position.symbol,
        short_strike=position.short_leg.strike,
        long_strike=position.long_leg.strike,
        spread_width=position.spread_width,
        net_credit=position.net_credit,
        contracts=position.contracts,
        expiration=position.expiration,
        dte=position.days_to_expiration,
        max_profit=position.max_profit,
        max_loss=position.max_loss,
        breakeven=position.breakeven,
        source="internal",
    )


def snapshot_from_ibkr(spread: Dict[str, Any]) -> PositionSnapshot:
    """
    Build PositionSnapshot from IBKR spread dict.

    IBKR expiry format is YYYYMMDD — converted to YYYY-MM-DD.
    """
    # Convert YYYYMMDD to YYYY-MM-DD
    raw_expiry = str(spread["expiry"])
    if len(raw_expiry) == 8 and "-" not in raw_expiry:
        expiration = f"{raw_expiry[:4]}-{raw_expiry[4:6]}-{raw_expiry[6:]}"
    else:
        expiration = raw_expiry

    try:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        dte = (exp_date - date.today()).days
    except ValueError:
        dte = 0

    short_strike = spread["short_strike"]
    long_strike = spread["long_strike"]
    width = spread.get("width", short_strike - long_strike)
    net_credit = spread["net_credit"]  # Per share
    contracts = spread["contracts"]

    max_profit = net_credit * contracts * 100
    max_loss = (width - net_credit) * contracts * 100

    return PositionSnapshot(
        position_id=f"ibkr_{spread['symbol']}_{raw_expiry}_{short_strike:.0f}",
        symbol=spread["symbol"],
        short_strike=short_strike,
        long_strike=long_strike,
        spread_width=width,
        net_credit=net_credit,
        contracts=contracts,
        expiration=expiration,
        dte=dte,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=short_strike - net_credit,
        source="ibkr",
    )


def estimate_pnl_from_theta(snapshot: PositionSnapshot) -> PositionSnapshot:
    """
    Estimate P&L using theta decay approximation (no live data).

    Formula: pnl_pct ≈ sqrt(time_elapsed / total_time) * 100

    This approximation models accelerating theta decay:
    - At 50% time elapsed → ~71% profit
    - At 75% time elapsed → ~87% profit
    - At 90% time elapsed → ~95% profit

    Modifies the snapshot in-place and returns it.
    """
    if snapshot.dte <= 0:
        # Expired — full profit assumed
        snapshot.unrealized_pnl = snapshot.max_profit
        snapshot.pnl_pct_of_max_profit = 100.0
        snapshot.pnl_estimated = True
        return snapshot

    # Estimate original DTE from expiration
    # Typical BPS opened at 60-90 DTE; use spread between now and exp
    # We estimate original entry at ~75 DTE (SPREAD_DTE_TARGET)
    original_dte = 75  # Approximation
    time_elapsed = max(0, original_dte - snapshot.dte)
    total_time = original_dte

    if total_time <= 0:
        snapshot.pnl_estimated = True
        return snapshot

    # sqrt decay model
    elapsed_ratio = min(1.0, time_elapsed / total_time)
    pnl_pct = math.sqrt(elapsed_ratio) * 100.0

    snapshot.pnl_pct_of_max_profit = round(pnl_pct, 1)
    snapshot.unrealized_pnl = round(snapshot.max_profit * pnl_pct / 100.0, 2)
    snapshot.pnl_estimated = True

    return snapshot


# =============================================================================
# POSITION MONITOR
# =============================================================================

class PositionMonitor:
    """
    Monitors positions and generates exit signals per PLAYBOOK §4.

    Does NOT execute trades — only generates signals.
    """

    def __init__(self):
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
        """Lazy-load Fundamentals Manager for stability checks."""
        if self._fundamentals_manager is None:
            try:
                from ..cache import get_fundamentals_manager
                self._fundamentals_manager = get_fundamentals_manager()
            except ImportError:
                logger.debug("Fundamentals manager not available")
        return self._fundamentals_manager

    async def check_positions(
        self,
        snapshots: List[PositionSnapshot],
        current_vix: Optional[float] = None,
    ) -> MonitorResult:
        """
        Check all positions and generate exit signals.

        Args:
            snapshots: Normalized position snapshots
            current_vix: Current VIX level

        Returns:
            MonitorResult with signals for each position
        """
        signals: List[PositionSignal] = []

        for snap in snapshots:
            signal = self._evaluate_position(snap, current_vix)
            signals.append(signal)

        # Sort by priority (1=urgent, 8=hold)
        signals.sort(key=lambda s: s.priority)

        # Build regime info
        regime = None
        if current_vix is not None:
            vix_regime = get_vix_regime(current_vix)
            regime = f"{vix_regime.value} (VIX {current_vix:.1f})"

        return MonitorResult(
            signals=signals,
            vix=current_vix,
            regime=regime,
            positions_count=len(snapshots),
        )

    def _evaluate_position(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> PositionSignal:
        """
        Evaluate a single position through all exit rules in priority order.

        Returns the FIRST matching signal (highest priority).
        """
        # Priority 1: Expired
        signal = self._check_expired(snap)
        if signal:
            return signal

        # Priority 2: Force close (DTE <= 7)
        signal = self._check_force_close(snap)
        if signal:
            return signal

        # Priority 3: Profit target
        signal = self._check_profit_target(snap, current_vix)
        if signal:
            return signal

        # Priority 4: Stop loss
        signal = self._check_stop_loss(snap)
        if signal:
            return signal

        # Priority 5: 21 DTE decision (roll or close)
        signal = self._check_21dte_decision(snap, current_vix)
        if signal:
            return signal

        # Priority 6: High VIX
        signal = self._check_high_vix(snap, current_vix)
        if signal:
            return signal

        # Priority 7: Earnings before expiration
        signal = self._check_earnings_risk(snap)
        if signal:
            return signal

        # Priority 8: Default — HOLD
        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.HOLD,
            reason="Keine Aktion nötig",
            priority=8,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
        )

    # =========================================================================
    # EXIT CHECKS (PLAYBOOK §4, priority order)
    # =========================================================================

    def _check_expired(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 1: Position already expired (DTE <= 0)."""
        if snap.dte <= 0:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"ABGELAUFEN (DTE {snap.dte})",
                priority=1,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
            )
        return None

    def _check_force_close(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 2: Force close at DTE <= 7 (EXIT_FORCE_CLOSE_DTE)."""
        if snap.dte <= EXIT_FORCE_CLOSE_DTE:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"FORCE CLOSE — DTE {snap.dte} <= {EXIT_FORCE_CLOSE_DTE}",
                priority=2,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
            )
        return None

    def _check_profit_target(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> Optional[PositionSignal]:
        """Priority 3: Profit target reached (PLAYBOOK §4 + VIX-adjusted)."""
        if snap.pnl_pct_of_max_profit is None:
            return None

        # Get VIX-adjusted profit target
        target_pct = EXIT_PROFIT_PCT_NORMAL  # Default: 50%
        if current_vix is not None:
            regime_rules = get_regime_rules(current_vix)
            target_pct = regime_rules.profit_exit_pct

        # HIGH_VOL/NO_TRADING: profit_exit_pct=0 means close all winners
        if target_pct == 0.0 and snap.pnl_pct_of_max_profit > 0:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"VIX-Regime: Alle Gewinner sofort schließen (P&L {snap.pnl_pct_of_max_profit:.0f}%)",
                priority=3,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"target_pct": target_pct, "regime": "HIGH_VIX"},
            )

        if target_pct > 0 and snap.pnl_pct_of_max_profit >= target_pct:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"PROFIT TARGET — {snap.pnl_pct_of_max_profit:.0f}% >= {target_pct:.0f}%",
                priority=3,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"target_pct": target_pct},
            )

        return None

    def _check_stop_loss(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 4: Stop loss at 200% of credit (EXIT_STOP_LOSS_MULTIPLIER)."""
        if snap.unrealized_pnl is None:
            return None

        # Stop loss = loss exceeds multiplier * credit
        stop_loss_amount = snap.net_credit * snap.contracts * 100 * EXIT_STOP_LOSS_MULTIPLIER
        current_loss = -snap.unrealized_pnl  # Positive when losing

        if current_loss >= stop_loss_amount:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"STOP LOSS — Verlust ${current_loss:.0f} >= {EXIT_STOP_LOSS_MULTIPLIER:.0f}x Credit (${stop_loss_amount:.0f})",
                priority=4,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={
                    "loss": current_loss,
                    "stop_loss_amount": stop_loss_amount,
                    "multiplier": EXIT_STOP_LOSS_MULTIPLIER,
                },
            )

        return None

    def _check_21dte_decision(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> Optional[PositionSignal]:
        """Priority 5: 21 DTE decision point — roll or close (EXIT_ROLL_DTE)."""
        if snap.dte > EXIT_ROLL_DTE:
            return None

        # At 21 DTE: profitable + rollable → ROLL, otherwise → CLOSE
        is_profitable = (
            snap.pnl_pct_of_max_profit is not None
            and snap.pnl_pct_of_max_profit > 0
        )

        can_roll = self._can_roll(snap, current_vix)

        if is_profitable and can_roll:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.ROLL,
                reason=f"21-DTE ROLL — DTE {snap.dte}, Profit {snap.pnl_pct_of_max_profit:.0f}%, rollbar",
                priority=5,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"can_roll": True, "profitable": True},
            )

        # Not profitable or can't roll → CLOSE
        reason_parts = []
        if not is_profitable:
            reason_parts.append("im Verlust")
        if not can_roll:
            reason_parts.append("nicht rollbar")

        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.CLOSE,
            reason=f"21-DTE CLOSE — DTE {snap.dte}, {', '.join(reason_parts)}",
            priority=5,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
            details={"can_roll": can_roll, "profitable": is_profitable},
        )

    def _check_high_vix(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> Optional[PositionSignal]:
        """Priority 6: VIX > 30 — close winners, alert losers."""
        if current_vix is None or current_vix < VIX_ELEVATED_MAX:
            return None

        is_profitable = (
            snap.pnl_pct_of_max_profit is not None
            and snap.pnl_pct_of_max_profit > 0
        )

        if is_profitable:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"HIGH VIX ({current_vix:.1f}) — Gewinn sichern ({snap.pnl_pct_of_max_profit:.0f}%)",
                priority=6,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"vix": current_vix},
            )

        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.ALERT,
            reason=f"HIGH VIX ({current_vix:.1f}) — Position im Verlust, Beobachtung",
            priority=6,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
            details={"vix": current_vix},
        )

    def _check_earnings_risk(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 7: Earnings fall before expiration."""
        from ..utils.validation import is_etf

        # ETFs have no earnings
        if is_etf(snap.symbol):
            return None

        if self.earnings is None:
            return None

        try:
            is_safe, days_to, reason = self.earnings.is_earnings_day_safe(
                snap.symbol,
                target_date=date.today(),
                min_days=snap.dte,  # Earnings must be AFTER expiration
            )
        except Exception as e:
            logger.debug(f"Earnings check failed for {snap.symbol}: {e}")
            return None

        if not is_safe:
            days_str = f"{days_to} Tagen" if days_to is not None else "unbekannt"
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"EARNINGS-RISIKO — Earnings in {days_str}, vor Expiration (DTE {snap.dte})",
                priority=7,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"days_to_earnings": days_to},
            )

        return None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _can_roll(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> bool:
        """
        Check if a position can be rolled (PLAYBOOK §4 Roll Rules).

        Roll allowed if all conditions met:
        1. VIX < 30 (no rolling in HIGH_VOL/NO_TRADING)
        2. Stability >= VIX-adjusted minimum (re-validation)
        3. Earnings don't fall into new DTE window (60-90 days)
        """
        # Condition 1: VIX must be < 30
        if current_vix is not None and current_vix >= VIX_ELEVATED_MAX:
            return False

        # Condition 2: Stability re-validation (Task 4.3)
        # Symbol must still meet stability requirements for current VIX regime
        if self.fundamentals is not None:
            try:
                f = self.fundamentals.get_fundamentals(snap.symbol)
                if f and f.stability_score is not None:
                    # Get VIX-adjusted stability minimum
                    if current_vix is not None:
                        rules = get_regime_rules(current_vix)
                        stability_min = rules.stability_min
                    else:
                        stability_min = ENTRY_STABILITY_MIN  # Default: 70

                    if f.stability_score < stability_min:
                        logger.info(
                            f"Roll blocked for {snap.symbol}: stability "
                            f"{f.stability_score:.0f} < {stability_min:.0f} "
                            f"(VIX-adjusted minimum)"
                        )
                        return False
            except Exception as e:
                logger.debug(f"Stability check failed for {snap.symbol}: {e}")
                # If we can't check, allow roll (conservative approach)

        # Condition 3: Earnings must not fall into new 60-90 DTE window
        from ..utils.validation import is_etf

        if not is_etf(snap.symbol) and self.earnings is not None:
            try:
                is_safe, days_to, _ = self.earnings.is_earnings_day_safe(
                    snap.symbol,
                    target_date=date.today(),
                    min_days=ROLL_NEW_DTE_MAX,  # Must be safe for 90 days
                )
                if not is_safe:
                    return False
            except Exception:
                pass  # If we can't check, allow roll

        return True


# =============================================================================
# FACTORY / SINGLETON
# =============================================================================

_monitor: Optional[PositionMonitor] = None


def get_position_monitor() -> PositionMonitor:
    """Get singleton PositionMonitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = PositionMonitor()
    return _monitor


def reset_position_monitor():
    """Reset singleton (for tests)."""
    global _monitor
    _monitor = None
