#!/usr/bin/env python3
"""
Regime-Based Training Configuration Module

Defines VIX regime classifications and their associated trading parameters.
Supports both fixed and percentile-based regime boundaries with hysteresis
for smooth regime transitions.

Usage:
    from src.backtesting.regime_config import (
        RegimeConfig,
        RegimeType,
        FIXED_REGIMES,
        create_percentile_regimes,
    )

    # Get regime for current VIX
    regime = get_regime_for_vix(18.5, FIXED_REGIMES)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class RegimeType(str, Enum):
    """VIX-based market regime classification"""
    LOW_VOL = "low_vol"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH_VOL = "high_vol"


class RegimeBoundaryMethod(str, Enum):
    """Method for determining regime boundaries"""
    FIXED = "fixed"          # Fixed VIX thresholds (15/20/30)
    PERCENTILE = "percentile"  # Based on historical VIX percentiles


# =============================================================================
# CONFIGURATION DATA CLASSES
# =============================================================================

@dataclass
class RegimeConfig:
    """
    Configuration for a single market regime.

    Defines VIX boundaries, trading parameters, and strategy settings
    for a specific volatility environment.
    """
    # Identification
    name: str                               # e.g., "low_vol", "normal"
    regime_type: RegimeType

    # VIX Boundaries
    vix_lower: float                        # VIX >= this to enter
    vix_upper: float                        # VIX < this to enter

    # Hysteresis Settings (for regime transitions)
    entry_buffer: float = 0.0               # Extra VIX points needed to enter
    exit_buffer: float = 1.0                # Buffer before exiting regime
    min_days_in_regime: int = 2             # Minimum days before switching

    # Trading Parameters
    min_score: float = 5.0                  # Minimum signal score
    profit_target_pct: float = 50.0         # Profit target (% of max profit)
    stop_loss_pct: float = 150.0            # Stop loss (% of max profit)
    position_size_pct: float = 5.0          # Max position as % of capital
    max_concurrent_positions: int = 10      # Max open positions

    # Strategy Settings
    strategies_enabled: List[str] = field(
        default_factory=lambda: ["pullback", "bounce", "ath_breakout", "earnings_dip"]
    )
    strategy_weights: Dict[str, float] = field(default_factory=dict)

    # Component Weight Adjustments
    # Allows regime-specific adjustments to score component weights
    component_adjustments: Dict[str, float] = field(default_factory=dict)

    # Metadata
    description: str = ""
    is_trained: bool = False
    training_date: Optional[datetime] = None
    sample_size: int = 0
    confidence_level: str = "unknown"       # "high", "medium", "low"

    def __post_init__(self):
        """Validate configuration after initialization"""
        if self.vix_lower >= self.vix_upper:
            raise ValueError(
                f"vix_lower ({self.vix_lower}) must be less than "
                f"vix_upper ({self.vix_upper})"
            )
        if self.min_score < 0 or self.min_score > 15:
            raise ValueError(f"min_score must be between 0 and 15, got {self.min_score}")

    def contains_vix(self, vix: float, with_hysteresis: bool = False) -> bool:
        """
        Check if a VIX value falls within this regime's boundaries.

        Args:
            vix: Current VIX value
            with_hysteresis: Apply hysteresis buffers for smoother transitions

        Returns:
            True if VIX falls within this regime
        """
        if with_hysteresis:
            lower = self.vix_lower - self.exit_buffer
            upper = self.vix_upper + self.exit_buffer
        else:
            lower = self.vix_lower
            upper = self.vix_upper

        return lower <= vix < upper

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "regime_type": self.regime_type.value,
            "vix_boundaries": {
                "lower": self.vix_lower,
                "upper": self.vix_upper,
            },
            "hysteresis": {
                "entry_buffer": self.entry_buffer,
                "exit_buffer": self.exit_buffer,
                "min_days_in_regime": self.min_days_in_regime,
            },
            "trading_parameters": {
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
            "component_adjustments": self.component_adjustments,
            "metadata": {
                "description": self.description,
                "is_trained": self.is_trained,
                "training_date": self.training_date.isoformat() if self.training_date else None,
                "sample_size": self.sample_size,
                "confidence_level": self.confidence_level,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegimeConfig":
        """Create RegimeConfig from dictionary"""
        boundaries = data.get("vix_boundaries", {})
        hysteresis = data.get("hysteresis", {})
        trading = data.get("trading_parameters", {})
        strategies = data.get("strategies", {})
        metadata = data.get("metadata", {})

        training_date = None
        if metadata.get("training_date"):
            training_date = datetime.fromisoformat(metadata["training_date"])

        return cls(
            name=data["name"],
            regime_type=RegimeType(data["regime_type"]),
            vix_lower=boundaries.get("lower", 0),
            vix_upper=boundaries.get("upper", 100),
            entry_buffer=hysteresis.get("entry_buffer", 0.0),
            exit_buffer=hysteresis.get("exit_buffer", 1.0),
            min_days_in_regime=hysteresis.get("min_days_in_regime", 2),
            min_score=trading.get("min_score", 5.0),
            profit_target_pct=trading.get("profit_target_pct", 50.0),
            stop_loss_pct=trading.get("stop_loss_pct", 150.0),
            position_size_pct=trading.get("position_size_pct", 5.0),
            max_concurrent_positions=trading.get("max_concurrent_positions", 10),
            strategies_enabled=strategies.get("enabled", ["pullback", "bounce", "ath_breakout", "earnings_dip"]),
            strategy_weights=strategies.get("weights", {}),
            component_adjustments=data.get("component_adjustments", {}),
            description=metadata.get("description", ""),
            is_trained=metadata.get("is_trained", False),
            training_date=training_date,
            sample_size=metadata.get("sample_size", 0),
            confidence_level=metadata.get("confidence_level", "unknown"),
        )


@dataclass
class RegimeTransition:
    """Tracks regime transitions with hysteresis"""
    from_regime: Optional[str]
    to_regime: str
    transition_date: date
    vix_at_transition: float
    days_in_previous: int


@dataclass
class RegimeState:
    """
    Current regime state with hysteresis tracking.

    Maintains state for smooth regime transitions, preventing
    whipsaw behavior during volatile VIX periods.
    """
    current_regime: str
    entered_date: date
    days_in_regime: int = 1
    pending_transition: Optional[str] = None
    pending_days: int = 0
    transition_history: List[RegimeTransition] = field(default_factory=list)

    def update(
        self,
        current_date: date,
        vix: float,
        regimes: Dict[str, RegimeConfig],
    ) -> Optional[str]:
        """
        Update regime state based on current VIX.

        Implements hysteresis: regime only changes after VIX has been
        in the new regime for min_days_in_regime consecutive days.

        Args:
            current_date: Current trading date
            vix: Current VIX value
            regimes: Dict of available regime configurations

        Returns:
            New regime name if transition occurred, None otherwise
        """
        current_config = regimes.get(self.current_regime)
        if not current_config:
            return None

        # Check if still in current regime (with exit buffer)
        if current_config.contains_vix(vix, with_hysteresis=True):
            self.days_in_regime += 1
            self.pending_transition = None
            self.pending_days = 0
            return None

        # Find new regime
        new_regime = None
        for name, config in regimes.items():
            if config.contains_vix(vix, with_hysteresis=False):
                new_regime = name
                break

        if not new_regime or new_regime == self.current_regime:
            return None

        # Check if this is a continuation of pending transition
        if self.pending_transition == new_regime:
            self.pending_days += 1
        else:
            self.pending_transition = new_regime
            self.pending_days = 1

        # Check if hysteresis period satisfied
        min_days = regimes[new_regime].min_days_in_regime
        if self.pending_days >= min_days:
            # Execute transition
            transition = RegimeTransition(
                from_regime=self.current_regime,
                to_regime=new_regime,
                transition_date=current_date,
                vix_at_transition=vix,
                days_in_previous=self.days_in_regime,
            )
            self.transition_history.append(transition)

            old_regime = self.current_regime
            self.current_regime = new_regime
            self.entered_date = current_date
            self.days_in_regime = 1
            self.pending_transition = None
            self.pending_days = 0

            logger.info(
                f"Regime transition: {old_regime} -> {new_regime} "
                f"(VIX={vix:.1f}, date={current_date})"
            )
            return new_regime

        return None


# =============================================================================
# DEFAULT REGIME CONFIGURATIONS
# =============================================================================

# Fixed VIX thresholds (traditional approach)
FIXED_REGIMES: Dict[str, RegimeConfig] = {
    RegimeType.LOW_VOL.value: RegimeConfig(
        name="low_vol",
        regime_type=RegimeType.LOW_VOL,
        vix_lower=0,
        vix_upper=15,
        description="Low volatility environment - aggressive positioning allowed",
        min_score=4.0,
        profit_target_pct=40.0,
        stop_loss_pct=200.0,
        position_size_pct=6.0,
        max_concurrent_positions=15,
        strategies_enabled=["pullback", "bounce", "ath_breakout", "earnings_dip"],
    ),
    RegimeType.NORMAL.value: RegimeConfig(
        name="normal",
        regime_type=RegimeType.NORMAL,
        vix_lower=15,
        vix_upper=20,
        description="Normal volatility - standard trading parameters",
        min_score=5.0,
        profit_target_pct=50.0,
        stop_loss_pct=150.0,
        position_size_pct=5.0,
        max_concurrent_positions=10,
        strategies_enabled=["pullback", "bounce", "ath_breakout", "earnings_dip"],
    ),
    RegimeType.ELEVATED.value: RegimeConfig(
        name="elevated",
        regime_type=RegimeType.ELEVATED,
        vix_lower=20,
        vix_upper=30,
        description="Elevated volatility - conservative approach",
        min_score=6.0,
        profit_target_pct=60.0,
        stop_loss_pct=100.0,
        position_size_pct=4.0,
        max_concurrent_positions=7,
        strategies_enabled=["pullback", "bounce"],  # No breakout/dip
    ),
    RegimeType.HIGH_VOL.value: RegimeConfig(
        name="high_vol",
        regime_type=RegimeType.HIGH_VOL,
        vix_lower=30,
        vix_upper=100,
        description="High volatility - defensive or pause trading",
        min_score=8.0,
        profit_target_pct=75.0,
        stop_loss_pct=75.0,
        position_size_pct=2.0,
        max_concurrent_positions=3,
        strategies_enabled=["pullback"],  # Only highest conviction plays
    ),
}


def create_percentile_regimes(
    vix_history: List[float],
    percentiles: Tuple[float, float, float] = (25, 50, 75),
) -> Dict[str, RegimeConfig]:
    """
    Create regime configurations based on historical VIX percentiles.

    This adapts regime boundaries to the actual VIX distribution,
    which can be more robust than fixed thresholds during unusual
    market periods.

    Args:
        vix_history: List of historical VIX values
        percentiles: Tuple of (low, mid, high) percentiles for boundaries

    Returns:
        Dict of RegimeConfig objects with percentile-based boundaries
    """
    import statistics

    if len(vix_history) < 30:
        logger.warning(
            f"Only {len(vix_history)} VIX data points. "
            "Using fixed regimes as fallback."
        )
        return FIXED_REGIMES.copy()

    sorted_vix = sorted(vix_history)
    n = len(sorted_vix)

    def get_percentile(p: float) -> float:
        idx = int(n * p / 100)
        return sorted_vix[min(idx, n - 1)]

    p_low, p_mid, p_high = percentiles
    vix_p25 = get_percentile(p_low)
    vix_p50 = get_percentile(p_mid)
    vix_p75 = get_percentile(p_high)

    logger.info(
        f"Percentile-based regime boundaries: "
        f"P{p_low}={vix_p25:.1f}, P{p_mid}={vix_p50:.1f}, P{p_high}={vix_p75:.1f}"
    )

    # Create configs with percentile boundaries
    # Copy trading parameters from fixed regimes
    regimes = {}

    for regime_type, fixed_config in FIXED_REGIMES.items():
        config = RegimeConfig(
            name=fixed_config.name,
            regime_type=fixed_config.regime_type,
            vix_lower=0,  # Will be set below
            vix_upper=100,  # Will be set below
            entry_buffer=fixed_config.entry_buffer,
            exit_buffer=fixed_config.exit_buffer,
            min_days_in_regime=fixed_config.min_days_in_regime,
            min_score=fixed_config.min_score,
            profit_target_pct=fixed_config.profit_target_pct,
            stop_loss_pct=fixed_config.stop_loss_pct,
            position_size_pct=fixed_config.position_size_pct,
            max_concurrent_positions=fixed_config.max_concurrent_positions,
            strategies_enabled=fixed_config.strategies_enabled.copy(),
            description=f"{fixed_config.description} (percentile-based)",
        )
        regimes[regime_type] = config

    # Set boundaries
    regimes[RegimeType.LOW_VOL.value].vix_lower = 0
    regimes[RegimeType.LOW_VOL.value].vix_upper = vix_p25

    regimes[RegimeType.NORMAL.value].vix_lower = vix_p25
    regimes[RegimeType.NORMAL.value].vix_upper = vix_p50

    regimes[RegimeType.ELEVATED.value].vix_lower = vix_p50
    regimes[RegimeType.ELEVATED.value].vix_upper = vix_p75

    regimes[RegimeType.HIGH_VOL.value].vix_lower = vix_p75
    regimes[RegimeType.HIGH_VOL.value].vix_upper = 100

    return regimes


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_regime_for_vix(
    vix: float,
    regimes: Optional[Dict[str, RegimeConfig]] = None,
) -> Tuple[str, RegimeConfig]:
    """
    Get the regime configuration for a given VIX value.

    Args:
        vix: Current VIX value
        regimes: Optional dict of regime configs (uses FIXED_REGIMES if None)

    Returns:
        Tuple of (regime_name, RegimeConfig)
    """
    if regimes is None:
        regimes = FIXED_REGIMES

    for name, config in regimes.items():
        if config.contains_vix(vix):
            return name, config

    # Fallback to normal if no match (shouldn't happen with proper config)
    logger.warning(f"No regime found for VIX={vix}, defaulting to 'normal'")
    return "normal", regimes.get("normal", FIXED_REGIMES["normal"])


def save_regimes(
    regimes: Dict[str, RegimeConfig],
    filepath: str,
) -> str:
    """
    Save regime configurations to JSON file.

    Args:
        regimes: Dict of regime configurations
        filepath: Path to save file

    Returns:
        Absolute path of saved file
    """
    filepath = Path(filepath).expanduser()
    filepath.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "version": "1.0.0",
        "saved_date": datetime.now().isoformat(),
        "regimes": {
            name: config.to_dict()
            for name, config in regimes.items()
        },
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(regimes)} regime configs to {filepath}")
    return str(filepath)


def load_regimes(filepath: str) -> Dict[str, RegimeConfig]:
    """
    Load regime configurations from JSON file.

    Args:
        filepath: Path to saved file

    Returns:
        Dict of regime configurations
    """
    filepath = Path(filepath).expanduser()

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    regimes = {}
    for name, config_data in data.get("regimes", {}).items():
        regimes[name] = RegimeConfig.from_dict(config_data)

    logger.info(f"Loaded {len(regimes)} regime configs from {filepath}")
    return regimes


def format_regime_summary(regimes: Dict[str, RegimeConfig]) -> str:
    """Format regime configurations as readable summary"""
    lines = [
        "",
        "=" * 80,
        "  REGIME CONFIGURATIONS",
        "=" * 80,
        "",
        f"{'Regime':<12} {'VIX Range':<15} {'Min Score':>10} {'Profit %':>10} {'Stop %':>10} {'Strategies':<20}",
        "-" * 80,
    ]

    for name, config in sorted(regimes.items(), key=lambda x: x[1].vix_lower):
        vix_range = f"{config.vix_lower:.0f} - {config.vix_upper:.0f}"
        strategies = ", ".join(s[:4] for s in config.strategies_enabled)

        lines.append(
            f"{name:<12} {vix_range:<15} {config.min_score:>10.1f} "
            f"{config.profit_target_pct:>10.0f} {config.stop_loss_pct:>10.0f} "
            f"{strategies:<20}"
        )

    lines.append("=" * 80)
    return "\n".join(lines)


# =============================================================================
# TRAINED MODEL LOADER
# =============================================================================

# Mapping from training regime names to system regime names
REGIME_NAME_MAPPING = {
    "low": "low_vol",
    "normal": "normal",
    "elevated": "elevated",
    "high": "high_vol",
}

REGIME_NAME_REVERSE_MAPPING = {v: k for k, v in REGIME_NAME_MAPPING.items()}


@dataclass
class TrainedStrategyConfig:
    """Configuration for a strategy within a regime, loaded from trained model."""
    enabled: bool
    min_score: float
    profit_target_pct: float
    stop_loss_pct: float
    train_wr: float
    test_wr: float
    total_trades: int
    total_pnl: float
    component_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrainedRegimeConfig:
    """Full regime configuration with per-strategy parameters from training."""
    regime_name: str
    strategies: Dict[str, TrainedStrategyConfig]

    def get_min_score_for_strategy(self, strategy: str) -> float:
        """Get trained min_score for a specific strategy."""
        if strategy in self.strategies:
            return self.strategies[strategy].min_score
        return 5.0  # Default fallback

    def get_enabled_strategies(self) -> List[str]:
        """Get list of enabled strategies for this regime."""
        return [
            name for name, cfg in self.strategies.items()
            if cfg.enabled
        ]


class TrainedModelLoader:
    """
    Loads and provides access to trained model configurations.

    Supports both the GRANULAR_TRAINED_MODEL.json format with per-regime×strategy
    configurations and the ENHANCED_FINAL_CONFIG.json with IV-Rank analysis.

    Usage:
        loader = TrainedModelLoader()
        if loader.load():
            config = loader.get_regime_config("normal")
            min_score = config.get_min_score_for_strategy("pullback")
    """

    DEFAULT_MODEL_PATH = "~/.optionplay/models/GRANULAR_TRAINED_MODEL.json"
    ENHANCED_MODEL_PATH = "~/.optionplay/models/ENHANCED_FINAL_CONFIG.json"

    def __init__(self):
        self._loaded = False
        self._model_data: Dict[str, Any] = {}
        self._regime_configs: Dict[str, TrainedRegimeConfig] = {}
        self._symbol_configs: Dict[str, Dict] = {}
        self._iv_rank_analysis: Dict[str, Dict] = {}
        self._summary: Dict[str, Any] = {}
        self._model_path: Optional[str] = None

    def load(self, model_path: Optional[str] = None) -> bool:
        """
        Load trained model from JSON file.

        Args:
            model_path: Optional path to model file. Tries DEFAULT_MODEL_PATH if not provided.

        Returns:
            True if loaded successfully, False otherwise
        """
        # Try paths in order
        paths_to_try = []
        if model_path:
            paths_to_try.append(model_path)
        paths_to_try.extend([self.DEFAULT_MODEL_PATH, self.ENHANCED_MODEL_PATH])

        for path in paths_to_try:
            filepath = Path(path).expanduser()
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        self._model_data = json.load(f)

                    self._parse_model_data()
                    self._loaded = True
                    self._model_path = str(filepath)
                    logger.info(f"Loaded trained model from {filepath}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to load model from {filepath}: {e}")
                    continue

        logger.warning("No trained model found")
        return False

    def _parse_model_data(self) -> None:
        """Parse loaded model data into configuration objects."""
        self._summary = self._model_data.get("summary", {})
        self._symbol_configs = self._model_data.get("symbol_configs", {})
        self._iv_rank_analysis = self._model_data.get("iv_rank_analysis", {})

        # Parse regime×strategy configurations
        regime_strategy_configs = self._model_data.get("regime_strategy_configs", {})

        for train_regime_name, strategies in regime_strategy_configs.items():
            # Map training regime name to system regime name
            system_regime = REGIME_NAME_MAPPING.get(train_regime_name, train_regime_name)

            strategy_configs = {}
            for strategy_name, cfg in strategies.items():
                strategy_configs[strategy_name] = TrainedStrategyConfig(
                    enabled=cfg.get("enabled", True),
                    min_score=cfg.get("min_score", 5.0),
                    profit_target_pct=cfg.get("profit_target_pct", 50.0),
                    stop_loss_pct=cfg.get("stop_loss_pct", 150.0),
                    train_wr=cfg.get("train_wr", 0.0),
                    test_wr=cfg.get("test_wr", 0.0),
                    total_trades=cfg.get("train_trades", 0) + cfg.get("test_trades", 0),
                    total_pnl=cfg.get("total_pnl", 0.0),
                    component_weights=cfg.get("component_weights", {}),
                )

            self._regime_configs[system_regime] = TrainedRegimeConfig(
                regime_name=system_regime,
                strategies=strategy_configs,
            )

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._loaded

    @property
    def model_path(self) -> Optional[str]:
        """Path of loaded model."""
        return self._model_path

    @property
    def summary(self) -> Dict[str, Any]:
        """Model training summary."""
        return self._summary

    def get_regime_config(self, regime: str) -> Optional[TrainedRegimeConfig]:
        """
        Get trained configuration for a regime.

        Args:
            regime: Regime name (e.g., "low_vol", "normal")

        Returns:
            TrainedRegimeConfig or None if not found
        """
        return self._regime_configs.get(regime)

    def get_min_score(self, regime: str, strategy: str) -> float:
        """
        Get trained min_score threshold for regime×strategy.

        Args:
            regime: Regime name
            strategy: Strategy name

        Returns:
            Trained min_score or default (5.0) if not found
        """
        config = self.get_regime_config(regime)
        if config:
            return config.get_min_score_for_strategy(strategy)
        return 5.0

    def get_symbol_config(self, symbol: str) -> Optional[Dict]:
        """
        Get symbol-specific configuration.

        Returns best strategy, optimal regime×strategy mapping, etc.
        """
        return self._symbol_configs.get(symbol)

    def get_optimal_strategy(self, symbol: str, regime: str) -> Optional[str]:
        """
        Get optimal strategy for a symbol in a given regime.

        Args:
            symbol: Ticker symbol
            regime: Current regime name

        Returns:
            Optimal strategy name or None
        """
        sym_cfg = self.get_symbol_config(symbol)
        if not sym_cfg:
            return None

        # Map system regime to training regime name for lookup
        train_regime = REGIME_NAME_REVERSE_MAPPING.get(regime, regime)

        optimal_map = sym_cfg.get("optimal_regime_strategy", {})
        return optimal_map.get(train_regime)

    def get_iv_rank_win_rate(self, strategy: str, iv_rank: float) -> Optional[float]:
        """
        Get expected win rate based on IV rank for a strategy.

        Args:
            strategy: Strategy name
            iv_rank: Current IV rank (0-100+)

        Returns:
            Expected win rate or None
        """
        if strategy not in self._iv_rank_analysis:
            return None

        buckets = self._iv_rank_analysis[strategy]

        # Find matching bucket
        if iv_rank < 25:
            bucket = "0-25"
        elif iv_rank < 50:
            bucket = "25-50"
        elif iv_rank < 75:
            bucket = "50-75"
        elif iv_rank < 100:
            bucket = "75-100"
        else:
            bucket = "100-125"

        bucket_data = buckets.get(bucket, {})
        return bucket_data.get("win_rate")

    def create_regime_configs(self) -> Dict[str, RegimeConfig]:
        """
        Create RegimeConfig objects from trained model.

        Returns RegimeConfigs with trained parameters that can be used
        with the existing regime system.

        Returns:
            Dict of regime name -> RegimeConfig
        """
        if not self._loaded:
            logger.warning("No trained model loaded, using defaults")
            return FIXED_REGIMES.copy()

        regimes = {}

        for regime_name, trained_cfg in self._regime_configs.items():
            # Get base config from FIXED_REGIMES
            base = FIXED_REGIMES.get(regime_name)
            if not base:
                continue

            # Get lowest min_score across all enabled strategies
            enabled_strategies = trained_cfg.get_enabled_strategies()
            if enabled_strategies:
                min_scores = [
                    trained_cfg.strategies[s].min_score
                    for s in enabled_strategies
                ]
                regime_min_score = min(min_scores)
            else:
                regime_min_score = base.min_score

            # Create new RegimeConfig with trained parameters
            regimes[regime_name] = RegimeConfig(
                name=regime_name,
                regime_type=base.regime_type,
                vix_lower=base.vix_lower,
                vix_upper=base.vix_upper,
                entry_buffer=base.entry_buffer,
                exit_buffer=base.exit_buffer,
                min_days_in_regime=base.min_days_in_regime,
                min_score=regime_min_score,
                profit_target_pct=base.profit_target_pct,
                stop_loss_pct=base.stop_loss_pct,
                position_size_pct=base.position_size_pct,
                max_concurrent_positions=base.max_concurrent_positions,
                strategies_enabled=enabled_strategies if enabled_strategies else base.strategies_enabled.copy(),
                strategy_weights={
                    s: cfg.train_wr / 100.0
                    for s, cfg in trained_cfg.strategies.items()
                    if cfg.enabled
                },
                description=f"{base.description} (trained)",
                is_trained=True,
                training_date=datetime.now(),
                sample_size=self._summary.get("total_trades", 0),
                confidence_level="high" if self._summary.get("total_trades", 0) > 10000 else "medium",
            )

        # Add any missing regimes from defaults
        for name, base in FIXED_REGIMES.items():
            if name not in regimes:
                regimes[name] = base

        return regimes


# Global instance for convenience
_trained_model_loader: Optional[TrainedModelLoader] = None


def get_trained_model_loader() -> TrainedModelLoader:
    """
    Get singleton instance of TrainedModelLoader.

    Automatically loads the model on first access.

    Returns:
        TrainedModelLoader instance
    """
    global _trained_model_loader
    if _trained_model_loader is None:
        _trained_model_loader = TrainedModelLoader()
        _trained_model_loader.load()
    return _trained_model_loader


def load_trained_regimes() -> Dict[str, RegimeConfig]:
    """
    Convenience function to load trained regime configurations.

    Falls back to FIXED_REGIMES if no trained model available.

    Returns:
        Dict of regime configurations
    """
    loader = get_trained_model_loader()
    if loader.is_loaded:
        return loader.create_regime_configs()
    return FIXED_REGIMES.copy()
