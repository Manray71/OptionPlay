# OptionPlay - Config Package
# ============================
# Konfiguration und Watchlist-Verwaltung
#
# Refactored in Phase 2.2 (Recursive Logic):
# - models.py: Alle Dataclasses
# - validation.py: Validierungslogik
# - loader.py: ConfigLoader Klasse
# - core.py: Singleton, get_config(), get_scan_config()
#
# Abwärtskompatibilität: Alle bisherigen Imports funktionieren weiterhin.

# Core functionality
from .core import (
    get_ab_test_variant,
    get_config,
    get_scan_config,
    reset_config,
    set_ab_test_variant,
)

# Fundamentals constants
from .fundamentals_constants import (
    BLACKLIST_EXTREME_VOL,
    BLACKLIST_LOW_STABILITY,
    DEFAULT_BLACKLIST,
    STABILITY_TIERS,
    VOLATILITY_CLUSTERS,
    get_stability_tier,
)

# Loader
from .loader import (
    ConfigLoader,
    find_config_dir,
)

# Models - Main configs
from .models import (  # Indicator configs; Strategy-specific configs; Infrastructure configs; Trained weights
    ApiConnectionConfig,
    ATHBreakoutScoringConfig,
    ATHDetectionConfig,
    BounceCandlestickConfig,
    BounceScoringConfig,
    BounceSupportConfig,
    CircuitBreakerConfig,
    ConnectionConfig,
    DataSourcesConfig,
    DipDetectionConfig,
    EarningsDipScoringConfig,
    FibonacciConfig,
    FibonacciLevel,
    FilterConfig,
    FundamentalsFilterConfig,
    GapAnalysisConfig,
    GapBoostConfig,
    KeltnerChannelConfig,
    LocalDatabaseConfig,
    MACDScoringConfig,
    MomentumConfig,
    MovingAverageConfig,
    OptionsConfig,
    PerformanceConfig,
    PullbackScoringConfig,
    RelativeStrengthConfig,
    RSIConfig,
    ScannerConfig,
    Settings,
    StabilizationConfig,
    StochasticScoringConfig,
    SupportConfig,
    TradierConfig,
    TrainedWeights,
    TrainedWeightsConfig,
    TrendStrengthConfig,
    VolumeConfig,
)

# Scoring Config (RecursiveConfigResolver)
from .scoring_config import (
    RecursiveConfigResolver,
    ResolvedWeights,
    get_scoring_resolver,
)

# Validation
from .validation import ConfigValidationError

# Watchlist loader
from .watchlist_loader import WatchlistLoader, get_watchlist_loader

__all__ = [
    # Core
    "ConfigLoader",
    "ConfigValidationError",
    "get_config",
    "get_scan_config",
    "reset_config",
    "find_config_dir",
    # A/B Test Support
    "set_ab_test_variant",
    "get_ab_test_variant",
    # Main Settings
    "Settings",
    "PullbackScoringConfig",
    "FilterConfig",
    "FundamentalsFilterConfig",
    "OptionsConfig",
    "ScannerConfig",
    "PerformanceConfig",
    "ApiConnectionConfig",
    "CircuitBreakerConfig",
    # Indicator Configs
    "RSIConfig",
    "SupportConfig",
    "FibonacciConfig",
    "FibonacciLevel",
    "MovingAverageConfig",
    "VolumeConfig",
    "MACDScoringConfig",
    "StochasticScoringConfig",
    "TrendStrengthConfig",
    "KeltnerChannelConfig",
    # Strategy-specific Configs
    "BounceScoringConfig",
    "BounceSupportConfig",
    "BounceCandlestickConfig",
    "ATHBreakoutScoringConfig",
    "ATHDetectionConfig",
    "MomentumConfig",
    "RelativeStrengthConfig",
    "EarningsDipScoringConfig",
    "DipDetectionConfig",
    "GapAnalysisConfig",
    "StabilizationConfig",
    # Infrastructure Configs
    "ConnectionConfig",
    "TradierConfig",
    "DataSourcesConfig",
    "LocalDatabaseConfig",
    # Trained Weights
    "TrainedWeightsConfig",
    "TrainedWeights",
    "GapBoostConfig",
    # Scoring Config
    "RecursiveConfigResolver",
    "ResolvedWeights",
    "get_scoring_resolver",
    # Watchlist
    "WatchlistLoader",
    "get_watchlist_loader",
    # Fundamentals Constants
    "DEFAULT_BLACKLIST",
    "BLACKLIST_LOW_STABILITY",
    "BLACKLIST_EXTREME_VOL",
    "get_stability_tier",
    "STABILITY_TIERS",
    "VOLATILITY_CLUSTERS",
]
