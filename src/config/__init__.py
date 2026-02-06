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
    get_config,
    get_scan_config,
    reset_config,
    set_ab_test_variant,
    get_ab_test_variant,
)

# Loader
from .loader import (
    ConfigLoader,
    find_config_dir,
)

# Validation
from .validation import ConfigValidationError

# Models - Main configs
from .models import (
    Settings,
    PullbackScoringConfig,
    FilterConfig,
    FundamentalsFilterConfig,
    OptionsConfig,
    ScannerConfig,
    PerformanceConfig,
    ApiConnectionConfig,
    CircuitBreakerConfig,
    # Indicator configs
    RSIConfig,
    SupportConfig,
    FibonacciConfig,
    FibonacciLevel,
    MovingAverageConfig,
    VolumeConfig,
    MACDScoringConfig,
    StochasticScoringConfig,
    TrendStrengthConfig,
    KeltnerChannelConfig,
    # Strategy-specific configs
    BounceScoringConfig,
    BounceSupportConfig,
    BounceCandlestickConfig,
    ATHBreakoutScoringConfig,
    ATHDetectionConfig,
    MomentumConfig,
    RelativeStrengthConfig,
    EarningsDipScoringConfig,
    DipDetectionConfig,
    GapAnalysisConfig,
    StabilizationConfig,
    # Infrastructure configs
    ConnectionConfig,
    TradierConfig,
    DataSourcesConfig,
    LocalDatabaseConfig,
    # Trained weights
    TrainedWeightsConfig,
    TrainedWeights,
    GapBoostConfig,
)

# Scoring Config (RecursiveConfigResolver)
from .scoring_config import (
    RecursiveConfigResolver,
    ResolvedWeights,
    get_scoring_resolver,
)

# Fundamentals constants
from .fundamentals_constants import (
    DEFAULT_BLACKLIST,
    BLACKLIST_LOW_STABILITY,
    BLACKLIST_EXTREME_VOL,
    get_stability_tier,
    STABILITY_TIERS,
    VOLATILITY_CLUSTERS,
)

# Watchlist loader
from .watchlist_loader import WatchlistLoader, get_watchlist_loader

__all__ = [
    # Core
    'ConfigLoader',
    'ConfigValidationError',
    'get_config',
    'get_scan_config',
    'reset_config',
    'find_config_dir',
    # A/B Test Support
    'set_ab_test_variant',
    'get_ab_test_variant',
    # Main Settings
    'Settings',
    'PullbackScoringConfig',
    'FilterConfig',
    'FundamentalsFilterConfig',
    'OptionsConfig',
    'ScannerConfig',
    'PerformanceConfig',
    'ApiConnectionConfig',
    'CircuitBreakerConfig',
    # Indicator Configs
    'RSIConfig',
    'SupportConfig',
    'FibonacciConfig',
    'FibonacciLevel',
    'MovingAverageConfig',
    'VolumeConfig',
    'MACDScoringConfig',
    'StochasticScoringConfig',
    'TrendStrengthConfig',
    'KeltnerChannelConfig',
    # Strategy-specific Configs
    'BounceScoringConfig',
    'BounceSupportConfig',
    'BounceCandlestickConfig',
    'ATHBreakoutScoringConfig',
    'ATHDetectionConfig',
    'MomentumConfig',
    'RelativeStrengthConfig',
    'EarningsDipScoringConfig',
    'DipDetectionConfig',
    'GapAnalysisConfig',
    'StabilizationConfig',
    # Infrastructure Configs
    'ConnectionConfig',
    'TradierConfig',
    'DataSourcesConfig',
    'LocalDatabaseConfig',
    # Trained Weights
    'TrainedWeightsConfig',
    'TrainedWeights',
    'GapBoostConfig',
    # Scoring Config
    'RecursiveConfigResolver',
    'ResolvedWeights',
    'get_scoring_resolver',
    # Watchlist
    'WatchlistLoader',
    'get_watchlist_loader',
    # Fundamentals Constants
    'DEFAULT_BLACKLIST',
    'BLACKLIST_LOW_STABILITY',
    'BLACKLIST_EXTREME_VOL',
    'get_stability_tier',
    'STABILITY_TIERS',
    'VOLATILITY_CLUSTERS',
]
