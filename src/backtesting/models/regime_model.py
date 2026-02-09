#!/usr/bin/env python3
"""
Regime Model - Production-Ready Regime-Based Trading Recommendations

Provides real-time trading parameter recommendations based on trained
regime models and current VIX. Handles regime transitions with hysteresis
to prevent whipsaw behavior.

Usage:
    from src.backtesting.regime_model import RegimeModel

    # Load trained model
    model = RegimeModel.load("~/.optionplay/models/regime_model.json")

    # Get current recommendations
    params = model.get_parameters(vix=18.5)
    print(f"Min Score: {params.min_score}")
    print(f"Strategies: {params.strategies_enabled}")

    # Check if a signal should be traded
    should_trade, reason = model.should_trade(
        score=8.5,
        strategy="pullback",
        vix=18.5
    )
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .regime_config import (
    RegimeConfig,
    RegimeType,
    RegimeState,
    RegimeTransition,
    FIXED_REGIMES,
    get_regime_for_vix,
    load_regimes,
    format_regime_summary,
    get_trained_model_loader,
    load_trained_regimes,
    TrainedModelLoader,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TradingParameters:
    """Current trading parameters based on regime"""
    regime: str
    regime_type: RegimeType
    vix: float
    vix_range: Tuple[float, float]

    # Core Parameters
    min_score: float
    profit_target_pct: float
    stop_loss_pct: float
    position_size_pct: float
    max_concurrent_positions: int

    # Strategy Settings
    strategies_enabled: List[str]
    strategy_weights: Dict[str, float]

    # Metadata
    is_trained: bool
    confidence_level: str
    last_transition: Optional[datetime] = None
    days_in_regime: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "regime_type": self.regime_type.value,
            "vix": round(self.vix, 2),
            "vix_range": (self.vix_range[0], self.vix_range[1]),
            "parameters": {
                "min_score": self.min_score,
                "profit_target_pct": self.profit_target_pct,
                "stop_loss_pct": self.stop_loss_pct,
                "position_size_pct": self.position_size_pct,
                "max_concurrent_positions": self.max_concurrent_positions,
            },
            "strategies": {
                "enabled": self.strategies_enabled,
                "weights": self.strategy_weights,
            },
            "metadata": {
                "is_trained": self.is_trained,
                "confidence_level": self.confidence_level,
                "days_in_regime": self.days_in_regime,
            },
        }


@dataclass
class TradeDecision:
    """Decision result for a potential trade"""
    should_trade: bool
    reason: str
    regime: str
    score_threshold: float
    signal_score: float
    strategy: str
    confidence: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_trade": self.should_trade,
            "reason": self.reason,
            "regime": self.regime,
            "score_threshold": self.score_threshold,
            "signal_score": self.signal_score,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "warnings": self.warnings,
        }


@dataclass
class RegimeStatus:
    """Current regime status with transition info"""
    current_regime: str
    regime_type: RegimeType
    vix: float
    days_in_regime: int
    pending_transition: Optional[str]
    pending_days: int
    transition_history: List[RegimeTransition]
    parameters: TradingParameters

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_regime": self.current_regime,
            "regime_type": self.regime_type.value,
            "vix": round(self.vix, 2),
            "days_in_regime": self.days_in_regime,
            "pending_transition": self.pending_transition,
            "pending_days": self.pending_days,
            "recent_transitions": [
                {
                    "from": t.from_regime,
                    "to": t.to_regime,
                    "date": str(t.transition_date),
                    "vix": round(t.vix_at_transition, 2),
                }
                for t in self.transition_history[-5:]  # Last 5 transitions
            ],
            "parameters": self.parameters.to_dict(),
        }


# =============================================================================
# REGIME MODEL
# =============================================================================

class RegimeModel:
    """
    Production model for regime-based trading recommendations.

    Manages trained regime configurations and provides real-time
    parameter recommendations with hysteresis-aware regime transitions.

    Enhanced to support:
    - Per-strategy min_score thresholds from trained models
    - Symbol-specific optimal strategy recommendations
    - IV-Rank based win rate adjustments
    """

    def __init__(
        self,
        regimes: Optional[Dict[str, RegimeConfig]] = None,
        model_id: Optional[str] = None,
        use_trained_model: bool = True,
    ) -> None:
        """
        Initialize model.

        Args:
            regimes: Dict of trained regime configurations
            model_id: Optional identifier for this model
            use_trained_model: If True, automatically loads trained model
        """
        # Try to load trained model if requested
        self._trained_loader: Optional[TrainedModelLoader] = None
        if use_trained_model and regimes is None:
            self._trained_loader = get_trained_model_loader()
            if self._trained_loader.is_loaded:
                self.regimes = self._trained_loader.create_regime_configs()
                model_id = model_id or "trained"
            else:
                self.regimes = FIXED_REGIMES.copy()
        else:
            self.regimes = regimes or FIXED_REGIMES.copy()

        self.model_id = model_id or "default"
        self._state: Optional[RegimeState] = None
        self._last_vix: Optional[float] = None
        self._last_update: Optional[datetime] = None

    def initialize(self, vix: float, current_date: Optional[date] = None) -> str:
        """
        Initialize regime state with current VIX.

        Call this once at startup to set initial regime state.

        Args:
            vix: Current VIX value
            current_date: Optional date (default: today)

        Returns:
            Initial regime name
        """
        if current_date is None:
            current_date = date.today()

        regime_name, _ = get_regime_for_vix(vix, self.regimes)

        self._state = RegimeState(
            current_regime=regime_name,
            entered_date=current_date,
            days_in_regime=1,
        )

        self._last_vix = vix
        self._last_update = datetime.now()

        logger.info(f"Initialized regime model: {regime_name} (VIX={vix:.2f})")
        return regime_name

    def update(
        self,
        vix: float,
        current_date: Optional[date] = None,
    ) -> Optional[str]:
        """
        Update regime state with new VIX reading.

        Applies hysteresis to prevent whipsaw transitions.

        Args:
            vix: Current VIX value
            current_date: Optional date (default: today)

        Returns:
            New regime name if transition occurred, None otherwise
        """
        if current_date is None:
            current_date = date.today()

        if self._state is None:
            return self.initialize(vix, current_date)

        self._last_vix = vix
        self._last_update = datetime.now()

        # Update state with hysteresis
        new_regime = self._state.update(current_date, vix, self.regimes)

        return new_regime

    def get_parameters(
        self,
        vix: Optional[float] = None,
    ) -> TradingParameters:
        """
        Get current trading parameters.

        Args:
            vix: Optional VIX value (uses last known if not provided)

        Returns:
            TradingParameters for current regime
        """
        if vix is not None:
            self.update(vix)
        elif self._last_vix is None:
            raise ValueError("VIX value required - model not initialized")

        current_vix = vix or self._last_vix
        if self._state is None:
            self.initialize(current_vix)

        regime_name = self._state.current_regime
        config = self.regimes.get(regime_name)

        if config is None:
            logger.warning(f"Unknown regime {regime_name}, using defaults")
            config = FIXED_REGIMES.get("normal", list(FIXED_REGIMES.values())[0])

        return TradingParameters(
            regime=regime_name,
            regime_type=config.regime_type,
            vix=current_vix,
            vix_range=(config.vix_lower, config.vix_upper),
            min_score=config.min_score,
            profit_target_pct=config.profit_target_pct,
            stop_loss_pct=config.stop_loss_pct,
            position_size_pct=config.position_size_pct,
            max_concurrent_positions=config.max_concurrent_positions,
            strategies_enabled=config.strategies_enabled.copy(),
            strategy_weights=config.strategy_weights.copy(),
            is_trained=config.is_trained,
            confidence_level=config.confidence_level,
            days_in_regime=self._state.days_in_regime if self._state else 0,
        )

    def get_min_score_for_strategy(
        self,
        strategy: str,
        regime: Optional[str] = None,
    ) -> float:
        """
        Get the trained min_score threshold for a specific strategy.

        Uses per-strategy thresholds from trained model if available,
        otherwise falls back to regime-level min_score.

        Args:
            strategy: Strategy name (pullback, bounce, etc.)
            regime: Optional regime name (uses current if not provided)

        Returns:
            Min score threshold for the strategy
        """
        if regime is None:
            if self._state:
                regime = self._state.current_regime
            else:
                regime = "normal"

        # Try trained model first
        if self._trained_loader and self._trained_loader.is_loaded:
            return self._trained_loader.get_min_score(regime, strategy)

        # Fallback to regime-level min_score
        config = self.regimes.get(regime)
        if config:
            return config.min_score
        return 5.0

    def get_optimal_strategy_for_symbol(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get the optimal strategy for a symbol in the current regime.

        Uses trained symbol-specific configurations if available.

        Args:
            symbol: Ticker symbol
            regime: Optional regime name (uses current if not provided)

        Returns:
            Optimal strategy name or None
        """
        if regime is None:
            if self._state:
                regime = self._state.current_regime
            else:
                regime = "normal"

        if self._trained_loader and self._trained_loader.is_loaded:
            return self._trained_loader.get_optimal_strategy(symbol, regime)
        return None

    def should_trade(
        self,
        score: float,
        strategy: str,
        vix: Optional[float] = None,
        symbol: Optional[str] = None,
        min_confidence: str = "low",
    ) -> TradeDecision:
        """
        Determine if a signal should be traded.

        Uses per-strategy min_score thresholds from trained model.

        Args:
            score: Signal score
            strategy: Strategy name (pullback, bounce, etc.)
            vix: Optional VIX value
            symbol: Optional symbol for symbol-specific recommendations
            min_confidence: Minimum confidence level ("high", "medium", "low")

        Returns:
            TradeDecision with recommendation
        """
        params = self.get_parameters(vix)
        warnings = []

        # Check strategy enabled
        if strategy not in params.strategies_enabled:
            return TradeDecision(
                should_trade=False,
                reason=f"Strategy '{strategy}' disabled in {params.regime} regime",
                regime=params.regime,
                score_threshold=params.min_score,
                signal_score=score,
                strategy=strategy,
                confidence=params.confidence_level,
            )

        # Get per-strategy min_score (uses trained model if available)
        strategy_min_score = self.get_min_score_for_strategy(strategy, params.regime)

        # Check score threshold
        if score < strategy_min_score:
            return TradeDecision(
                should_trade=False,
                reason=f"Score {score:.1f} below {strategy} threshold {strategy_min_score:.1f}",
                regime=params.regime,
                score_threshold=strategy_min_score,
                signal_score=score,
                strategy=strategy,
                confidence=params.confidence_level,
            )

        # Check confidence level
        confidence_order = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
        if confidence_order.get(params.confidence_level, 0) < confidence_order.get(min_confidence, 0):
            return TradeDecision(
                should_trade=False,
                reason=f"Confidence {params.confidence_level} below required {min_confidence}",
                regime=params.regime,
                score_threshold=strategy_min_score,
                signal_score=score,
                strategy=strategy,
                confidence=params.confidence_level,
            )

        # Check for pending transition
        if self._state and self._state.pending_transition:
            warnings.append(
                f"Potential regime transition to {self._state.pending_transition} "
                f"({self._state.pending_days} days pending)"
            )

        # Check for high volatility
        if params.regime in ("elevated", "high_vol"):
            warnings.append(f"Elevated volatility regime - use caution")

        # Check if regime is new
        if params.days_in_regime < 3:
            warnings.append(f"Recently entered {params.regime} regime ({params.days_in_regime} days)")

        # Check for symbol-specific optimal strategy
        if symbol and self._trained_loader and self._trained_loader.is_loaded:
            optimal = self.get_optimal_strategy_for_symbol(symbol, params.regime)
            if optimal and optimal != strategy:
                warnings.append(f"Note: {optimal} may be better for {symbol} in this regime")

        return TradeDecision(
            should_trade=True,
            reason=f"Signal qualifies in {params.regime} regime (trained threshold)",
            regime=params.regime,
            score_threshold=strategy_min_score,
            signal_score=score,
            strategy=strategy,
            confidence=params.confidence_level,
            warnings=warnings,
        )

    def get_status(self, vix: Optional[float] = None) -> RegimeStatus:
        """
        Get comprehensive regime status.

        Args:
            vix: Optional VIX value

        Returns:
            RegimeStatus with current state
        """
        params = self.get_parameters(vix)
        config = self.regimes.get(params.regime)

        return RegimeStatus(
            current_regime=params.regime,
            regime_type=config.regime_type if config else RegimeType.NORMAL,
            vix=params.vix,
            days_in_regime=self._state.days_in_regime if self._state else 0,
            pending_transition=self._state.pending_transition if self._state else None,
            pending_days=self._state.pending_days if self._state else 0,
            transition_history=self._state.transition_history if self._state else [],
            parameters=params,
        )

    def get_all_regimes(self) -> Dict[str, RegimeConfig]:
        """Get all regime configurations"""
        return self.regimes.copy()

    def format_summary(self) -> str:
        """Format model summary"""
        lines = [
            "",
            "=" * 70,
            f"  REGIME MODEL: {self.model_id}",
            "=" * 70,
        ]

        if self._state:
            lines.extend([
                f"  Current Regime:    {self._state.current_regime}",
                f"  Days in Regime:    {self._state.days_in_regime}",
                f"  Last VIX:          {self._last_vix:.2f}" if self._last_vix else "",
                f"  Last Update:       {self._last_update.strftime('%Y-%m-%d %H:%M')}" if self._last_update else "",
            ])

            if self._state.pending_transition:
                lines.append(
                    f"  Pending Transition: {self._state.pending_transition} "
                    f"({self._state.pending_days} days)"
                )

        lines.append("")
        lines.append(format_regime_summary(self.regimes))

        return "\n".join(lines)

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def save(self, filepath: str) -> str:
        """
        Save model to file.

        Args:
            filepath: Path to save file

        Returns:
            Absolute path of saved file
        """
        filepath = Path(filepath).expanduser()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "1.0.0",
            "model_id": self.model_id,
            "saved_date": datetime.now().isoformat(),
            "regimes": {
                name: config.to_dict()
                for name, config in self.regimes.items()
            },
            "state": {
                "current_regime": self._state.current_regime if self._state else None,
                "days_in_regime": self._state.days_in_regime if self._state else 0,
                "last_vix": self._last_vix,
            } if self._state else None,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Saved regime model to {filepath}")
        return str(filepath)

    @classmethod
    def load(cls, filepath: str) -> "RegimeModel":
        """
        Load model from file.

        Args:
            filepath: Path to saved file

        Returns:
            RegimeModel instance
        """
        filepath = Path(filepath).expanduser()

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        regimes = {}
        for name, config_data in data.get("regimes", {}).items():
            regimes[name] = RegimeConfig.from_dict(config_data)

        model = cls(
            regimes=regimes,
            model_id=data.get("model_id", "loaded"),
        )

        # Restore state if available
        state_data = data.get("state")
        if state_data and state_data.get("current_regime"):
            model._state = RegimeState(
                current_regime=state_data["current_regime"],
                entered_date=date.today(),  # Approximate
                days_in_regime=state_data.get("days_in_regime", 1),
            )
            model._last_vix = state_data.get("last_vix")

        logger.info(f"Loaded regime model from {filepath}")
        return model

    @classmethod
    def load_latest(cls, models_dir: str = "~/.optionplay/models") -> "RegimeModel":
        """
        Load the most recent regime model.

        Prioritizes trained models (GRANULAR_TRAINED_MODEL.json, ENHANCED_FINAL_CONFIG.json)
        over legacy regime_*.json files.

        Args:
            models_dir: Directory containing model files

        Returns:
            RegimeModel instance with trained configurations if available
        """
        models_dir = Path(models_dir).expanduser()

        if not models_dir.exists():
            logger.warning(f"Models directory not found: {models_dir}")
            return cls(use_trained_model=True)  # Will try to load trained model

        # Priority 1: Check for trained models (new format with per-strategy configs)
        trained_model_files = [
            models_dir / "GRANULAR_TRAINED_MODEL.json",
            models_dir / "ENHANCED_FINAL_CONFIG.json",
        ]

        for trained_path in trained_model_files:
            if trained_path.exists():
                logger.info(f"Found trained model: {trained_path}")
                # Create model with trained loader - it will automatically use this
                model = cls(use_trained_model=True)
                if model._trained_loader and model._trained_loader.is_loaded:
                    return model

        # Priority 2: Find legacy regime model files
        model_files = list(models_dir.glob("regime_*.json"))

        if not model_files:
            # Try to find regimes_ files
            model_files = list(models_dir.glob("regimes_*.json"))

        if not model_files:
            logger.warning("No regime model files found, using trained model or defaults")
            return cls(use_trained_model=True)

        # Sort by modification time, newest first
        model_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        return cls.load(str(model_files[0]))


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_regime_recommendation(
    vix: float,
    score: float,
    strategy: str,
    model_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Quick function to get trading recommendation.

    Args:
        vix: Current VIX value
        score: Signal score
        strategy: Strategy name
        model_path: Optional path to model file

    Returns:
        Dict with recommendation details
    """
    if model_path:
        model = RegimeModel.load(model_path)
    else:
        model = RegimeModel.load_latest()

    model.initialize(vix)
    decision = model.should_trade(score, strategy, vix)
    params = model.get_parameters()

    return {
        "decision": decision.to_dict(),
        "parameters": params.to_dict(),
        "regime": params.regime,
        "should_trade": decision.should_trade,
    }


def format_regime_status(vix: float, model_path: Optional[str] = None) -> str:
    """
    Format current regime status as readable string.

    Args:
        vix: Current VIX value
        model_path: Optional path to model file

    Returns:
        Formatted status string
    """
    if model_path:
        model = RegimeModel.load(model_path)
    else:
        model = RegimeModel.load_latest()

    model.initialize(vix)
    status = model.get_status()
    params = status.parameters

    lines = [
        "",
        "=" * 60,
        "  CURRENT REGIME STATUS",
        "=" * 60,
        f"  VIX:              {vix:.2f}",
        f"  Regime:           {status.current_regime.upper()}",
        f"  VIX Range:        {params.vix_range[0]:.0f} - {params.vix_range[1]:.0f}",
        f"  Days in Regime:   {status.days_in_regime}",
        "",
        "-" * 60,
        "  TRADING PARAMETERS",
        "-" * 60,
        f"  Min Score:        {params.min_score:.1f}",
        f"  Profit Target:    {params.profit_target_pct:.0f}%",
        f"  Stop Loss:        {params.stop_loss_pct:.0f}%",
        f"  Position Size:    {params.position_size_pct:.1f}%",
        f"  Max Positions:    {params.max_concurrent_positions}",
        "",
        f"  Strategies:       {', '.join(params.strategies_enabled)}",
        f"  Confidence:       {params.confidence_level.upper()}",
    ]

    if status.pending_transition:
        lines.extend([
            "",
            "-" * 60,
            f"  PENDING TRANSITION: {status.pending_transition}",
            f"  Days Pending: {status.pending_days}",
        ])

    lines.append("=" * 60)
    return "\n".join(lines)
