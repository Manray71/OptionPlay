# OptionPlay - Strategy Rotation Engine
# ======================================
# Extracted from models/ensemble_selector.py (Phase 6d)
#
# Manages automatic strategy rotation based on performance.

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np

from ..models.ensemble_models import (
    STRATEGIES,
    RotationTrigger,
    RotationState,
)

logger = logging.getLogger(__name__)


class StrategyRotationEngine:
    """
    Manages automatic strategy rotation based on performance.

    Tracks recent performance and adjusts strategy preferences
    when underperformance is detected.
    """

    def __init__(
        self,
        rotation_window_days: int = 30,
        performance_threshold: float = 0.40,
        min_trades_for_rotation: int = 10,
        initial_preferences: Optional[Dict[str, float]] = None,
    ):
        self.rotation_window = rotation_window_days
        self.performance_threshold = performance_threshold
        self.min_trades = min_trades_for_rotation

        self._state = RotationState(
            current_preferences=initial_preferences or {s: 1.0 / len(STRATEGIES) for s in STRATEGIES},
            last_rotation_date=date.today(),
            rotation_reason=None,
            recent_win_rates={s: [] for s in STRATEGIES},
            consecutive_losses={s: 0 for s in STRATEGIES},
        )

    def record_trade_result(
        self,
        strategy: str,
        outcome: bool,
        trade_date: date,
    ):
        """Record a trade result for rotation tracking"""
        # Update win rates
        self._state.recent_win_rates[strategy].append(1.0 if outcome else 0.0)

        # Keep only recent window
        max_trades = 50  # Rolling window
        if len(self._state.recent_win_rates[strategy]) > max_trades:
            self._state.recent_win_rates[strategy] = \
                self._state.recent_win_rates[strategy][-max_trades:]

        # Update consecutive losses
        if outcome:
            self._state.consecutive_losses[strategy] = 0
        else:
            self._state.consecutive_losses[strategy] += 1

    def check_rotation(self, current_date: date) -> Optional[Dict[str, Any]]:
        """
        Check if strategy rotation is needed.

        Returns:
            Rotation info dict if rotation triggered, None otherwise
        """
        should_rotate, trigger = self._state.should_rotate(
            current_date,
            self.performance_threshold,
            self.rotation_window,
        )

        if not should_rotate:
            return None

        # Calculate new preferences
        new_prefs = self._calculate_new_preferences()
        old_prefs = self._state.current_preferences.copy()

        # Record rotation
        rotation_info = {
            "date": current_date.isoformat(),
            "trigger": trigger.value,
            "old_preferences": old_prefs,
            "new_preferences": new_prefs,
            "recent_performance": {
                s: np.mean(wrs) if wrs else 0.5
                for s, wrs in self._state.recent_win_rates.items()
            },
        }

        self._state.rotation_history.append(rotation_info)
        self._state.current_preferences = new_prefs
        self._state.last_rotation_date = current_date
        self._state.rotation_reason = trigger

        # Reset consecutive losses
        self._state.consecutive_losses = {s: 0 for s in STRATEGIES}

        logger.info(f"Strategy rotation triggered: {trigger.value}")
        return rotation_info

    def _calculate_new_preferences(self) -> Dict[str, float]:
        """Calculate new strategy preferences based on recent performance"""
        performances = {}

        for strat in STRATEGIES:
            wrs = self._state.recent_win_rates.get(strat, [])
            if len(wrs) >= 5:
                # Recent win rate with recency weighting
                weights = [0.5 ** i for i in range(len(wrs))]
                weights = weights[::-1]  # More weight to recent
                performances[strat] = np.average(wrs, weights=weights[:len(wrs)])
            else:
                # Default to prior
                performances[strat] = self._state.current_preferences.get(strat, 0.25)

        # Normalize
        total = sum(performances.values())
        if total > 0:
            return {k: v / total for k, v in performances.items()}
        else:
            return {s: 1.0 / len(STRATEGIES) for s in STRATEGIES}

    def get_current_preferences(self) -> Dict[str, float]:
        """Get current strategy preferences"""
        return self._state.current_preferences.copy()

    def get_rotation_summary(self) -> Dict[str, Any]:
        """Get summary of rotation state"""
        return {
            "current_preferences": self._state.current_preferences,
            "last_rotation": self._state.last_rotation_date.isoformat(),
            "last_rotation_reason": self._state.rotation_reason.value if self._state.rotation_reason else None,
            "days_since_rotation": (date.today() - self._state.last_rotation_date).days,
            "recent_performance": {
                s: round(np.mean(wrs), 3) if wrs else None
                for s, wrs in self._state.recent_win_rates.items()
            },
            "consecutive_losses": self._state.consecutive_losses,
            "rotation_count": len(self._state.rotation_history),
        }
