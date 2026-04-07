# OptionPlay - Recursive Config Resolver for Scoring Weights
# ==========================================================
# Central architecture element: resolves hierarchical overrides
#
# Resolution order:
#   Base → Regime-Override → Sektor-Override → Regime×Sektor-Override
#
# Singleton with RLock (thread-safe), hot-reloadable via reload()

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger(__name__)

# Default YAML path
_DEFAULT_YAML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "scoring.yaml",
)


@dataclass(frozen=True)
class ResolvedWeights:
    """Immutable resolved weights for a strategy+regime+sector combination."""

    strategy: str
    regime: str
    sector: Optional[str]
    weights: Dict[str, float]
    max_possible: float
    min_stability: float
    sector_factor: float = 1.0  # Multiplicative sector adjustment (0.5-1.3)
    enabled: bool = True  # Whether strategy is enabled for this regime
    vix_score_multiplier: float = 1.0  # VIX regime score multiplier (0.0-1.5)
    max_tier: int = 3  # Max liquidity tier allowed (1=T1 only, 2=T1+T2, 3=all)

    def as_numpy_array(self, component_order: List[str]) -> "np.ndarray":
        """Convert weights to numpy array in specified component order."""
        if not HAS_NUMPY:
            raise ImportError("numpy is required for as_numpy_array()")
        return np.array(
            [self.weights.get(c, 0.0) for c in component_order],
            dtype=np.float64,
        )


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins on conflicts)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class RecursiveConfigResolver:
    """
    Singleton resolver for hierarchical scoring configuration.

    Loads scoring_weights.yaml and resolves weights for any
    (strategy, regime, sector) combination with 4-layer merging:

        Base → Regime → Sector → Regime×Sector
    """

    _instance: Optional["RecursiveConfigResolver"] = None
    _lock = threading.RLock()

    def __new__(cls, yaml_path: Optional[str] = None) -> "RecursiveConfigResolver":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    def __init__(self, yaml_path: Optional[str] = None) -> None:
        with self._lock:
            if self._initialized:
                return
            self._yaml_path = yaml_path or _DEFAULT_YAML
            self._raw: Dict[str, Any] = {}
            self._cache: Dict[Tuple, ResolvedWeights] = {}
            self._load()
            self._initialized = True

    def _load(self) -> None:
        """Load YAML config from disk."""
        path = Path(self._yaml_path)
        if path.exists():
            try:
                with open(path, "r") as f:
                    self._raw = yaml.safe_load(f) or {}
                logger.info(f"Loaded scoring config from {path}")
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}. Using defaults.")
                self._raw = {}
        else:
            logger.info(f"No scoring config at {path}. Using defaults.")
            self._raw = {}

    # ------------------------------------------------------------------
    # Fallback defaults (used when YAML is missing or incomplete)
    # ------------------------------------------------------------------

    _FALLBACK_STRATEGIES: Dict[str, Dict[str, Any]] = {
        "pullback": {
            "weights": {
                "rsi": 3.0,
                "rsi_divergence": 3.0,
                "support": 2.5,
                "fibonacci": 2.0,
                "ma": 2.0,
                "trend_strength": 2.0,
                "volume": 1.0,
                "macd": 2.0,
                "stoch": 2.0,
                "keltner": 2.0,
                "vwap": 3.0,
                "market_context": 2.0,
                "sector": 1.0,
                "gap": 1.0,
            },
            "max_possible": 14.0,
        },
        "bounce": {
            "weights": {
                "support": 3.0,
                "rsi": 2.0,
                "rsi_divergence": 3.0,
                "candlestick": 2.0,
                "volume": 2.0,
                "trend": 2.0,
                "macd": 2.0,
                "stoch": 2.0,
                "keltner": 2.0,
                "vwap": 3.0,
                "market_context": 2.0,
                "sector": 1.0,
                "gap": 1.0,
            },
            "max_possible": 10.0,
        },
    }

    _FALLBACK_STABILITY: Dict[str, float] = {
        "low": 70,
        "normal": 70,
        "elevated": 80,
        "danger": 80,
        "high": 999,
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        strategy: str,
        regime: str = "normal",
        sector: Optional[str] = None,
    ) -> ResolvedWeights:
        """
        Resolve weights for a (strategy, regime, sector) combination.

        Uses 4-layer merge:
            strategy base → regime override → sector override → regime×sector override

        Results are cached for repeated lookups.
        """
        cache_key = (strategy, regime, sector)

        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        resolved = self._resolve_uncached(strategy, regime, sector)

        with self._lock:
            self._cache[cache_key] = resolved

        return resolved

    def _resolve_uncached(
        self, strategy: str, regime: str, sector: Optional[str]
    ) -> ResolvedWeights:
        """Perform the actual 4-layer resolution."""
        strategies = self._raw.get("strategies", {})
        strat_cfg = strategies.get(strategy, {})

        # Layer 1: Base (from YAML or fallback)
        fallback = self._FALLBACK_STRATEGIES.get(strategy, {})
        base_weights = strat_cfg.get("weights", fallback.get("weights", {})).copy()
        base_max = strat_cfg.get("max_possible", fallback.get("max_possible", 10.0))

        defaults = self._raw.get("defaults", {})
        base_stability = defaults.get("min_stability", 70)

        merged = {
            "weights": base_weights,
            "max_possible": base_max,
            "min_stability": base_stability,
            "max_tier": strat_cfg.get("max_tier", 3),
        }

        # Layer 2: Regime override
        regimes = strat_cfg.get("regimes", {})
        regime_override = regimes.get(regime, {})
        if regime_override:
            merged = _deep_merge(merged, regime_override)

        # Layer 3: Sector override
        sectors = strat_cfg.get("sectors", {})
        if sector:
            sector_override = sectors.get(sector, {})
            if sector_override:
                merged = _deep_merge(merged, sector_override)

            # Layer 4: Regime×Sector override
            regime_sector_key = f"{regime}:{sector}"
            regime_sector_override = sectors.get(regime_sector_key, {})
            if regime_sector_override:
                merged = _deep_merge(merged, regime_sector_override)

        # Extract sector_factor (Iter 4 trained multiplicative adjustment)
        sector_factor = float(merged.get("sector_factor", 1.0))
        sector_factor = max(0.5, min(1.3, sector_factor))  # Safety clamp

        # Extract enabled flag (Schritt 7: VIX regime harmonization)
        enabled = bool(merged.get("enabled", True))

        # Extract VIX score multiplier (Schritt 7: centralized VIX regime handling)
        vix_mult = float(merged.get("vix_score_multiplier", 1.0))
        vix_mult = max(0.0, min(1.5, vix_mult))  # Safety clamp

        # Extract max liquidity tier (Schritt 5: liquidity tier gate)
        max_tier = int(merged.get("max_tier", 3))
        max_tier = max(1, min(3, max_tier))  # Safety clamp

        return ResolvedWeights(
            strategy=strategy,
            regime=regime,
            sector=sector,
            weights=merged.get("weights", base_weights),
            max_possible=float(merged.get("max_possible", base_max)),
            min_stability=float(merged.get("min_stability", base_stability)),
            sector_factor=sector_factor,
            enabled=enabled,
            vix_score_multiplier=vix_mult,
            max_tier=max_tier,
        )

    def get_stability_threshold(
        self,
        regime: str,
        sector: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> float:
        """
        Get stability threshold, optionally strategy-specific (v3).

        Resolution order (v3):
            1. by_strategy[strategy].by_regime[regime] + by_strategy[strategy].by_sector[sector]
            2. by_regime[regime] + by_sector[sector]  (global fallback)

        Returns: base regime threshold + sector adjustment (if any)
        """
        thresholds = self._raw.get("stability_thresholds", {})

        # v3: Try strategy-specific thresholds first
        if strategy:
            by_strategy = thresholds.get("by_strategy", {})
            strat_cfg = by_strategy.get(strategy)
            if strat_cfg:
                strat_by_regime = strat_cfg.get("by_regime", {})
                base = strat_by_regime.get(regime)
                if base is not None:
                    if sector:
                        strat_by_sector = strat_cfg.get("by_sector", {})
                        adjustment = strat_by_sector.get(sector, 0)
                        return float(base + adjustment)
                    return float(base)

        # Fallback: global thresholds
        by_regime = thresholds.get("by_regime", self._FALLBACK_STABILITY)
        base = by_regime.get(regime, 70)

        if sector:
            by_sector = thresholds.get("by_sector", {})
            adjustment = by_sector.get(sector, 0)
            return float(base + adjustment)

        return float(base)

    def get_sector_factor_config(
        self, strategy: Optional[str] = None
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        Get strategy-specific sector momentum factor_range and component_weights (v3).

        Resolution:
            1. sector_momentum.strategy_overrides[strategy]
            2. sector_momentum (global defaults)

        Returns:
            (factor_range dict, component_weights dict)
        """
        sm = self._raw.get("sector_momentum", {})
        global_range = sm.get("factor_range", {"min": 0.6, "max": 1.2})
        global_weights = sm.get(
            "component_weights",
            {
                "relative_strength_30d": 0.40,
                "relative_strength_60d": 0.30,
                "breadth": 0.20,
                "vol_premium": 0.10,
            },
        )

        if strategy:
            overrides = sm.get("strategy_overrides", {})
            strat_override = overrides.get(strategy)
            if strat_override:
                factor_range = strat_override.get("factor_range", global_range)
                comp_weights = strat_override.get("component_weights", global_weights)
                return factor_range, comp_weights

        return global_range, global_weights

    def get_training_config(self, strategy: str) -> dict:
        """Get training configuration for a specific strategy (v3)."""
        training = self._raw.get("training", {})
        configs = training.get("strategy_configs", {})
        return configs.get(strategy, {})

    def get_sector_momentum_config(self) -> dict:
        """Get sector momentum configuration."""
        return self._raw.get(
            "sector_momentum",
            {
                "enabled": False,
                "cache_ttl_hours": 4,
            },
        )

    def get_parallelization_config(self) -> dict:
        """Get parallelization configuration."""
        return self._raw.get(
            "parallelization",
            {
                "sector_batch_size": 11,
                "scan_concurrency": 50,
                "training_workers": None,
            },
        )

    def get_liquidity_config(self) -> dict:
        """Get liquidity threshold configuration."""
        return self._raw.get(
            "liquidity",
            {
                "entry": {
                    "open_interest_min": 100,
                    "bid_ask_spread_max": 0.20,
                },
                "quality": {
                    "open_interest": {"excellent": 500, "good": 100, "fair": 50},
                    "spread_pct": {"excellent": 5.0, "good": 10.0, "fair": 15.0},
                    "volume": {"excellent": 200, "good": 50, "fair": 10},
                },
                "min_quality_daily_picks": "good",
            },
        )

    def get_ranking_config(self) -> dict:
        """Get ranking & speed scoring configuration."""
        return self._raw.get(
            "ranking",
            {
                "stability_weight": 0.3,
                "speed_exponent": 0.3,
                "min_signal_score": 3.5,
                "stability_warning": 70,
                "speed": {
                    "dte_optimal": 60,
                    "dte_range": 30,
                    "dte_weight": 3.0,
                    "stability_baseline": 70,
                    "stability_range": 30,
                    "stability_weight": 2.5,
                    "sector_weight": 1.5,
                    "pullback_weight": 1.5,
                    "market_context_weight": 1.5,
                    "score_max": 10.0,
                    "multiplier_min": 0.5,
                },
                "strike_support": {"pct_1": 0.90, "pct_2": 0.85, "pct_3": 0.80},
                "sector_speed": {},
            },
        )

    def get_entry_quality_config(self) -> dict:
        """Get entry quality scorer (EQS) configuration."""
        return self._raw.get("entry_quality", {})

    def get_feature_engineering_config(self) -> dict:
        """Get feature-engineering thresholds (VWAP, Market Context, Gap)."""
        return self._raw.get(
            "feature_engineering",
            {
                "vwap": {
                    "period": 20,
                    "strong_above": 3.0,
                    "above": 1.0,
                    "below": -1.0,
                    "strong_below": -3.0,
                },
                "market_context": {
                    "sma_short": 20,
                    "sma_medium": 50,
                },
                "gap": {
                    "size_large": 3.0,
                    "size_medium": 1.0,
                },
            },
        )

    def list_strategies(self) -> List[str]:
        """List all configured strategy names."""
        yaml_strats = set(self._raw.get("strategies", {}).keys())
        fallback_strats = set(self._FALLBACK_STRATEGIES.keys())
        return sorted(yaml_strats | fallback_strats)

    def reload(self) -> None:
        """Reload config from disk and clear cache."""
        with self._lock:
            self._cache.clear()
            self._load()
            logger.info("Scoring config reloaded")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for tests)."""
        with cls._lock:
            cls._instance = None


# ------------------------------------------------------------------
# Module-level convenience functions
# ------------------------------------------------------------------


def get_scoring_resolver(yaml_path: Optional[str] = None) -> RecursiveConfigResolver:
    """Get (or create) the singleton RecursiveConfigResolver."""
    return RecursiveConfigResolver(yaml_path)
