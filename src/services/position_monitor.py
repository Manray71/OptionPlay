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
  5. Gamma-Zone Stop (DTE < 21 + loss > 30%) → CLOSE  [G.1]
  6. Time-Stop (held > 25d + loss > 20%) → CLOSE       [G.2]
  7. 21 DTE Decision Point → ROLL or CLOSE
  8. High VIX (>30) → CLOSE winners / ALERT losers
  9. Earnings before expiration → CLOSE
  10. RRG Rotation Exit → CLOSE or ALERT              [G.3]
  11. Default → HOLD

Usage:
    from src.services.position_monitor import get_position_monitor

    monitor = get_position_monitor()
    result = await monitor.check_positions(snapshots, current_vix=18.0)

    for signal in result.close_signals:
        print(f"{signal.symbol}: {signal.reason}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from ..constants.trading_rules import (
    EXIT_FORCE_CLOSE_DTE,
    EXIT_GAMMA_ZONE_DTE,
    EXIT_GAMMA_ZONE_LOSS_PCT,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_ROLL_DTE,
    EXIT_STOP_LOSS_MULTIPLIER,
    EXIT_TIME_STOP_DAYS,
    EXIT_TIME_STOP_LOSS_PCT,
    ROLL_NEW_DTE_MAX,
    ROLL_NEW_DTE_MIN,
    SPREAD_DTE_TARGET,
    VIX_ELEVATED_MAX,
    ExitAction,
    VIXRegime,
    get_regime_rules,
    get_vix_regime,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

THETA_ESTIMATE_ORIGINAL_DTE = SPREAD_DTE_TARGET

# G.4 Macro Calendar — FOMC / CPI / NFP Termine 2026
MACRO_EVENTS_2026: Dict[str, List[str]] = {
    "FOMC": [
        "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
        "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
    ],
    "CPI": [
        "2026-01-15", "2026-02-12", "2026-03-12", "2026-04-10",
        "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-12",
        "2026-09-11", "2026-10-14", "2026-11-12", "2026-12-10",
    ],
    "NFP": [
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-08", "2026-06-05", "2026-07-09", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ],
}


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
    net_credit: float  # Per share
    contracts: int
    expiration: str  # YYYY-MM-DD
    dte: int
    max_profit: float  # Total in USD
    max_loss: float  # Total in USD
    breakeven: float
    source: str = "internal"  # "internal" or "ibkr"

    # Live data (optional, from IBKR)
    current_spread_value: Optional[float] = None

    # P&L (optional — set by estimate_pnl or from IBKR)
    unrealized_pnl: Optional[float] = None
    pnl_pct_of_max_profit: Optional[float] = None
    pnl_estimated: bool = False  # True if P&L is theta-estimated

    # Entry metadata (optional — for G.2 Time-Stop and G.3 RRG Exit)
    entry_date: Optional[str] = None          # YYYY-MM-DD, for Time-Stop
    rrg_quadrant_at_entry: Optional[str] = None  # e.g. "leading", for RRG Exit


@dataclass
class PositionSignal:
    """Exit signal for a single position."""

    position_id: str
    symbol: str
    action: ExitAction
    reason: str  # Human-readable
    priority: int  # 1=highest, 11=HOLD
    dte: int
    pnl_pct: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorResult:
    """Result of monitoring all positions."""

    signals: list[PositionSignal]
    vix: Optional[float] = None
    regime: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    positions_count: int = 0
    macro_alerts: List[str] = field(default_factory=list)

    @property
    def close_signals(self) -> list[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.CLOSE]

    @property
    def roll_signals(self) -> list[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.ROLL]

    @property
    def alert_signals(self) -> list[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.ALERT]

    @property
    def hold_signals(self) -> list[PositionSignal]:
        return [s for s in self.signals if s.action == ExitAction.HOLD]


# =============================================================================
# SNAPSHOT BUILDERS
# =============================================================================


def snapshot_from_internal(position: Any) -> PositionSnapshot:
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
        entry_date=getattr(position, "open_date", None),
    )


def snapshot_from_ibkr(spread: dict[str, Any]) -> PositionSnapshot:
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
    original_dte = THETA_ESTIMATE_ORIGINAL_DTE  # Approximation
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

    def __init__(self) -> None:
        self._earnings_manager: Any = None
        self._fundamentals_manager: Any = None

    @property
    def earnings(self) -> Any:
        """Lazy-load Earnings History Manager."""
        if self._earnings_manager is None:
            try:
                from ..cache import get_earnings_history_manager

                self._earnings_manager = get_earnings_history_manager()
            except ImportError:
                logger.warning("Earnings history manager not available")
        return self._earnings_manager

    @property
    def fundamentals(self) -> Any:
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
        snapshots: list[PositionSnapshot],
        current_vix: Optional[float] = None,
        sector_rs_map: Optional[Dict[str, Any]] = None,
    ) -> MonitorResult:
        """
        Check all positions and generate exit signals.

        Args:
            snapshots: Normalized position snapshots
            current_vix: Current VIX level
            sector_rs_map: Optional Dict[symbol, StockRS] for G.3 RRG Exit.
                           If None, RRG exit check is skipped.

        Returns:
            MonitorResult with signals for each position and macro alerts.
        """
        signals: list[PositionSignal] = []

        for snap in snapshots:
            signal = self._evaluate_position(snap, current_vix, sector_rs_map)
            signals.append(signal)

        # Sort by priority (1=urgent, 11=hold)
        signals.sort(key=lambda s: s.priority)

        # Build regime info
        regime = None
        if current_vix is not None:
            vix_regime = get_vix_regime(current_vix)
            regime = f"{vix_regime.value} (VIX {current_vix:.1f})"

        # G.4 Macro Calendar
        macro_alerts = self.check_macro_events(date.today())

        return MonitorResult(
            signals=signals,
            vix=current_vix,
            regime=regime,
            positions_count=len(snapshots),
            macro_alerts=macro_alerts,
        )

    def _evaluate_position(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
        sector_rs_map: Optional[Dict[str, Any]] = None,
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

        # Priority 5: Gamma-Zone Stop (G.1)
        signal = self._check_gamma_zone_stop(snap)
        if signal:
            return signal

        # Priority 6: Time-Stop (G.2)
        signal = self._check_time_stop(snap)
        if signal:
            return signal

        # Priority 7: 21 DTE decision (roll or close)
        signal = self._check_21dte_decision(snap, current_vix)
        if signal:
            return signal

        # Priority 8: High VIX
        signal = self._check_high_vix(snap, current_vix)
        if signal:
            return signal

        # Priority 9: Earnings before expiration
        signal = self._check_earnings_risk(snap)
        if signal:
            return signal

        # Priority 10: RRG Rotation Exit (G.3)
        signal = self._check_rrg_exit(snap, sector_rs_map)
        if signal:
            return signal

        # Priority 11: Default — HOLD
        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.HOLD,
            reason="Keine Aktion nötig",
            priority=11,
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

    def _check_gamma_zone_stop(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 5: G.1 Gamma-Zone Stop — DTE < 21 AND loss > 30%.

        Gamma steigt in den letzten 3 Wochen vor Expiry stark an.
        Ein Spread mit -30% bei DTE < 21 hat hohe Wahrscheinlichkeit auf -100%.
        """
        if snap.pnl_pct_of_max_profit is None:
            return None
        if snap.dte >= EXIT_GAMMA_ZONE_DTE:
            return None
        if snap.pnl_pct_of_max_profit > -EXIT_GAMMA_ZONE_LOSS_PCT:
            return None

        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.CLOSE,
            reason=(
                f"GAMMA-ZONE STOP — DTE {snap.dte} < {EXIT_GAMMA_ZONE_DTE},"
                f" Verlust {snap.pnl_pct_of_max_profit:.0f}% <= -{EXIT_GAMMA_ZONE_LOSS_PCT:.0f}%"
            ),
            priority=5,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
            details={
                "gamma_zone_dte": EXIT_GAMMA_ZONE_DTE,
                "loss_pct": snap.pnl_pct_of_max_profit,
            },
        )

    def _check_time_stop(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 6: G.2 Time-Stop — held > 25 days AND loss > 20%.

        Verhindert Hope-Holding. Eine Position die nach 25 Tagen noch
        im Minus ist, wird wahrscheinlich nicht mehr profitabel.
        """
        if snap.entry_date is None or snap.pnl_pct_of_max_profit is None:
            return None

        try:
            entry = date.fromisoformat(str(snap.entry_date))
        except (ValueError, TypeError):
            return None

        days_held = (date.today() - entry).days

        if days_held <= EXIT_TIME_STOP_DAYS:
            return None
        if snap.pnl_pct_of_max_profit > -EXIT_TIME_STOP_LOSS_PCT:
            return None

        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.CLOSE,
            reason=(
                f"TIME-STOP — {days_held} Tage gehalten,"
                f" Verlust {snap.pnl_pct_of_max_profit:.0f}% <= -{EXIT_TIME_STOP_LOSS_PCT:.0f}%"
            ),
            priority=6,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
            details={
                "days_held": days_held,
                "time_stop_days": EXIT_TIME_STOP_DAYS,
                "loss_pct": snap.pnl_pct_of_max_profit,
            },
        )

    def _check_21dte_decision(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> Optional[PositionSignal]:
        """Priority 7: 21 DTE decision point — roll or close (EXIT_ROLL_DTE)."""
        if snap.dte > EXIT_ROLL_DTE:
            return None

        # At 21 DTE: profitable + rollable → ROLL, otherwise → CLOSE
        is_profitable = snap.pnl_pct_of_max_profit is not None and snap.pnl_pct_of_max_profit > 0

        can_roll = self._can_roll(snap, current_vix)

        if is_profitable and can_roll:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.ROLL,
                reason=f"21-DTE ROLL — DTE {snap.dte}, Profit {snap.pnl_pct_of_max_profit:.0f}%, rollbar",
                priority=7,
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
            priority=7,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
            details={"can_roll": can_roll, "profitable": is_profitable},
        )

    def _check_high_vix(
        self,
        snap: PositionSnapshot,
        current_vix: Optional[float],
    ) -> Optional[PositionSignal]:
        """Priority 8: VIX > 30 — close winners, alert losers."""
        if current_vix is None or current_vix < VIX_ELEVATED_MAX:
            return None

        is_profitable = snap.pnl_pct_of_max_profit is not None and snap.pnl_pct_of_max_profit > 0

        if is_profitable:
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=f"HIGH VIX ({current_vix:.1f}) — Gewinn sichern ({snap.pnl_pct_of_max_profit:.0f}%)",
                priority=8,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"vix": current_vix},
            )

        return PositionSignal(
            position_id=snap.position_id,
            symbol=snap.symbol,
            action=ExitAction.ALERT,
            reason=f"HIGH VIX ({current_vix:.1f}) — Position im Verlust, Beobachtung",
            priority=8,
            dte=snap.dte,
            pnl_pct=snap.pnl_pct_of_max_profit,
            details={"vix": current_vix},
        )

    def _check_earnings_risk(self, snap: PositionSnapshot) -> Optional[PositionSignal]:
        """Priority 9: Earnings fall before expiration."""
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
                priority=9,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={"days_to_earnings": days_to},
            )

        return None

    def _check_rrg_exit(
        self,
        snap: PositionSnapshot,
        sector_rs_map: Optional[Dict[str, Any]],
    ) -> Optional[PositionSignal]:
        """Priority 10: G.3 RRG Rotation Exit.

        Warnung: LEADING → WEAKENING (ALERT)
        Exit: Symbol im LAGGING Quadrant (CLOSE)

        Requires rrg_quadrant_at_entry on the snapshot and sector_rs_map
        with current quadrants. If either is missing, check is skipped.
        """
        if snap.rrg_quadrant_at_entry is None:
            return None
        if sector_rs_map is None:
            return None

        current_rs = sector_rs_map.get(snap.symbol)
        if current_rs is None:
            return None

        try:
            current_quadrant = current_rs.quadrant.value  # e.g. "leading"
        except AttributeError:
            return None

        entry_quadrant = snap.rrg_quadrant_at_entry.lower()

        if current_quadrant == "lagging":
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.CLOSE,
                reason=(
                    f"RRG EXIT — {snap.symbol} → LAGGING"
                    f" (Entry: {entry_quadrant.upper()})"
                    " Aktie verliert Stärke vs. SPY"
                ),
                priority=10,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={
                    "entry_quadrant": entry_quadrant,
                    "current_quadrant": current_quadrant,
                },
            )

        if entry_quadrant == "leading" and current_quadrant == "weakening":
            return PositionSignal(
                position_id=snap.position_id,
                symbol=snap.symbol,
                action=ExitAction.ALERT,
                reason=(
                    f"RRG ROTATION — {snap.symbol} LEADING → WEAKENING"
                    " Kapitalfluss dreht, relative Stärke schwindet"
                ),
                priority=10,
                dte=snap.dte,
                pnl_pct=snap.pnl_pct_of_max_profit,
                details={
                    "entry_quadrant": entry_quadrant,
                    "current_quadrant": current_quadrant,
                },
            )

        return None

    # =========================================================================
    # G.4 MACRO CALENDAR
    # =========================================================================

    @staticmethod
    def check_macro_events(today: date) -> List[str]:
        """
        G.4: Prüft ob morgen ein FOMC / CPI / NFP Termin ist.

        Returns list of event names scheduled for tomorrow, e.g. ["FOMC"].
        Returns empty list when no macro event is upcoming.
        """
        tomorrow = (today + timedelta(days=1)).isoformat()
        return [
            event_type
            for event_type, dates in MACRO_EVENTS_2026.items()
            if tomorrow in dates
        ]

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

        # Condition 2: Stability re-validation via shared utility (Task 2.4)
        from .signal_filter import check_symbol_stability

        passes, stability, required = check_symbol_stability(
            snap.symbol, current_vix, self.fundamentals
        )
        if not passes and stability > 0:
            logger.info(
                f"Roll blocked for {snap.symbol}: stability "
                f"{stability:.0f} < {required:.0f} "
                f"(VIX-adjusted minimum)"
            )
            return False

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
            except (AttributeError, ValueError, RuntimeError) as e:
                logger.debug("Earnings check failed for %s: %s", snap.symbol, e)

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


def reset_position_monitor() -> None:
    """Reset singleton (for tests)."""
    global _monitor
    _monitor = None
