# OptionPlay - Central Constants
# ===============================
# All magic numbers and configuration values in one place.
#
# Usage:
#   from src.constants import TechnicalIndicators, Thresholds, RiskManagement
#
# Or individual values:
#   from src.constants import RSI_PERIOD, MACD_FAST, SUPPORT_LOOKBACK_DAYS

from .technical_indicators import (
    # Moving Averages
    SMA_SHORT,
    SMA_MEDIUM,
    SMA_LONG,
    EMA_MULTIPLIER,

    # ATR
    ATR_PERIOD,

    # RSI
    RSI_PERIOD,
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    RSI_NEUTRAL_LOW,
    RSI_NEUTRAL_HIGH,

    # MACD
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,

    # Stochastic
    STOCH_K_PERIOD,
    STOCH_D_PERIOD,
    STOCH_SMOOTH,
    STOCH_OVERSOLD,
    STOCH_OVERBOUGHT,

    # Keltner Channels
    KELTNER_ATR_MULTIPLIER,
    KELTNER_LOWER_THRESHOLD,
    KELTNER_UPPER_THRESHOLD,
    KELTNER_NEUTRAL_LOW,

    # Fibonacci
    FIB_LEVELS,
    FIB_LOOKBACK_DAYS,

    # Volume
    VOLUME_AVG_PERIOD,
    VOLUME_RECENT_WINDOW,
    VOLUME_TREND_LOW,
    VOLUME_TREND_HIGH,
    VOLUME_SPIKE_MULTIPLIER,

    # VWAP
    VWAP_PERIOD,
    VWAP_STRONG_ABOVE,
    VWAP_ABOVE,
    VWAP_BELOW,
    VWAP_STRONG_BELOW,

    # Support/Resistance
    SUPPORT_LOOKBACK_DAYS,
    SUPPORT_WINDOW,
    SUPPORT_MAX_LEVELS,
    SUPPORT_TOLERANCE_PCT,
    SR_LOOKBACK_DAYS_EXTENDED,

    # RSI Divergence
    DIVERGENCE_SWING_WINDOW,
    DIVERGENCE_MIN_BARS,
    DIVERGENCE_MAX_BARS,
    DIVERGENCE_STRENGTH_STRONG,
    DIVERGENCE_STRENGTH_MODERATE,

    # Gap Analysis
    GAP_LOOKBACK_DAYS,
    GAP_WINDOW,
    GAP_MIN_PCT,
    GAP_FILL_THRESHOLD,
    GAP_SIZE_LARGE,
    GAP_SIZE_MEDIUM,
    GAP_SIZE_SMALL_NEG,
    GAP_SIZE_LARGE_NEG,

    # Class exports
    TechnicalIndicators,
)

from .thresholds import (
    # Score Thresholds
    SCORE_STRONG_THRESHOLD,
    SCORE_MODERATE_THRESHOLD,
    SCORE_WEAK_THRESHOLD,
    MIN_SCORE_DEFAULT,
    MIN_ACTIONABLE_SCORE,

    # Credit Requirements
    MIN_CREDIT_PCT,
    TARGET_CREDIT_PCT,
    OTM_IDEAL_PCT,
    OTM_MAX_PCT,

    # VIX Z-Score Thresholds
    VIX_ZSCORE_RISING_FAST,
    VIX_ZSCORE_RISING,
    VIX_ZSCORE_FALLING,
    VIX_ZSCORE_FALLING_FAST,

    # Position Sizing Modifiers
    POSITION_SIZE_DANGER_ZONE,

    # Stability Thresholds
    STABILITY_PREMIUM,
    STABILITY_GOOD,
    STABILITY_OK,
    STABILITY_BLACKLIST,
    STABILITY_PREMIUM_MIN_SCORE,
    STABILITY_GOOD_MIN_SCORE,
    STABILITY_OK_MIN_SCORE,

    # Win Rate Thresholds (from training)
    WIN_RATE_PREMIUM,
    WIN_RATE_GOOD,
    WIN_RATE_OK,
    WIN_RATE_BLACKLIST,

    # VIX Regime Thresholds
    VIX_LOW,
    VIX_NORMAL,
    VIX_ELEVATED,
    VIX_HIGH,
    VIX_EXTREME,

    # IV Rank Thresholds
    IV_RANK_MIN,
    IV_RANK_MAX,
    IV_RANK_OPTIMAL_LOW,
    IV_RANK_OPTIMAL_HIGH,

    # Reliability Grades
    RELIABILITY_MIN_GRADE,
    RELIABILITY_GRADE_A_MIN_WR,
    RELIABILITY_GRADE_B_MIN_WR,
    RELIABILITY_GRADE_C_MIN_WR,
    RELIABILITY_GRADE_D_MIN_WR,

    # Market Context
    MARKET_UPTREND_SMA_RATIO,
    MARKET_DOWNTREND_SMA_RATIO,
    SECTOR_CORRELATION_HIGH,
    SECTOR_CORRELATION_LOW,

    # Class exports
    Thresholds,
)

from .strategy_parameters import (
    # Pullback Strategy
    PULLBACK_MIN_UPTREND_DAYS,
    PULLBACK_MAX_PULLBACK_PCT,
    PULLBACK_MIN_PULLBACK_PCT,

    # ATH Breakout Strategy
    ATH_LOOKBACK_DAYS,
    ATH_CONSOLIDATION_DAYS,
    ATH_BREAKOUT_THRESHOLD_PCT,
    ATH_CONFIRMATION_DAYS,
    ATH_CONFIRMATION_THRESHOLD,
    ATH_VOLUME_SPIKE_MULTIPLIER,
    ATH_RSI_MAX,
    ATH_MIN_UPTREND_DAYS,

    # Bounce Strategy
    BOUNCE_PROXIMITY_PCT,
    BOUNCE_MIN_TOUCHES,
    BOUNCE_LOOKBACK_DAYS,

    # Earnings Dip Strategy
    EARNINGS_DIP_MIN_PCT,
    EARNINGS_DIP_MAX_PCT,
    EARNINGS_DIP_LOOKBACK_DAYS,
    EARNINGS_RSI_OVERSOLD,
    EARNINGS_STOP_BELOW_LOW_PCT,
    EARNINGS_TARGET_RECOVERY_PCT,

    # Class exports
    StrategyParameters,
)

from .risk_management import (
    # DTE (Days to Expiration)
    DTE_MIN,
    DTE_MAX,
    DTE_TARGET,
    DTE_MIN_STRICT,

    # Delta Targets (Short Put)
    DELTA_TARGET,
    DELTA_MIN,
    DELTA_MAX,
    DELTA_AGGRESSIVE,
    DELTA_CONSERVATIVE,

    # Delta Targets (Long Put)
    DELTA_LONG_TARGET,
    DELTA_LONG_MIN,
    DELTA_LONG_MAX,

    # Spread Width: dynamisch aus Delta (PLAYBOOK §2), keine Konstanten

    # Risk/Reward
    RISK_REWARD_MIN,
    RISK_REWARD_TARGET,
    STOP_LOSS_MULTIPLIER,
    TARGET_MULTIPLIER,

    # Earnings Safety
    EARNINGS_MIN_DAYS,
    EARNINGS_MIN_DAYS_STRICT,
    EARNINGS_SAFE_DAYS,

    # Position Sizing
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_EXPOSURE_PCT,
    MAX_DAILY_TRADES,

    # Class exports
    RiskManagement,
)

from .trading_rules import (
    # Enums
    TradeDecision,
    VIXRegime,
    ExitAction,

    # Entry Rules (PLAYBOOK §1)
    ENTRY_STABILITY_MIN,
    ENTRY_EARNINGS_MIN_DAYS,
    ENTRY_VIX_MAX_NEW_TRADES,
    ENTRY_VIX_NO_TRADING,
    ENTRY_PRICE_MIN,
    ENTRY_PRICE_MAX,
    ENTRY_VOLUME_MIN,
    ENTRY_IV_RANK_MIN,
    ENTRY_IV_RANK_MAX,
    ENTRY_OPEN_INTEREST_MIN,
    ENTRY_BID_ASK_SPREAD_MAX,
    LIQUIDITY_OI_EXCELLENT,
    LIQUIDITY_OI_GOOD,
    LIQUIDITY_OI_FAIR,
    LIQUIDITY_SPREAD_PCT_EXCELLENT,
    LIQUIDITY_SPREAD_PCT_GOOD,
    LIQUIDITY_SPREAD_PCT_FAIR,
    LIQUIDITY_VOLUME_EXCELLENT,
    LIQUIDITY_VOLUME_GOOD,
    LIQUIDITY_VOLUME_FAIR,
    LIQUIDITY_MIN_QUALITY_DAILY_PICKS,
    BLACKLIST_SYMBOLS,

    # Spread Parameters (PLAYBOOK §2)
    SPREAD_DTE_MIN,
    SPREAD_DTE_MAX,
    SPREAD_DTE_TARGET,
    SPREAD_SHORT_DELTA_TARGET,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_LONG_DELTA_MIN,
    SPREAD_LONG_DELTA_MAX,
    SPREAD_MIN_CREDIT_PCT,

    # VIX Regime (PLAYBOOK §3)
    VIX_REGIME_RULES,
    VIXRegimeRules,
    get_vix_regime,
    get_regime_rules,

    # Helper Functions
    is_blacklisted,
    get_adjusted_stability_min,

    # Exit Rules (PLAYBOOK §4)
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_PROFIT_PCT_HIGH_VIX,
    EXIT_STOP_LOSS_MULTIPLIER,
    EXIT_ROLL_DTE,
    EXIT_FORCE_CLOSE_DTE,

    # Position Sizing (PLAYBOOK §5)
    SIZING_MAX_RISK_PER_TRADE_PCT,
    SIZING_MAX_OPEN_POSITIONS,
    SIZING_MAX_PER_SECTOR,
    SIZING_MAX_NEW_TRADES_PER_DAY,

    # Discipline (PLAYBOOK §6)
    DISCIPLINE_MAX_TRADES_PER_MONTH,
    DISCIPLINE_MAX_TRADES_PER_DAY,
    DISCIPLINE_MAX_TRADES_PER_WEEK,
    DISCIPLINE_CONSECUTIVE_LOSSES_PAUSE,
    DISCIPLINE_PAUSE_DAYS,

    # Watchlist (PLAYBOOK §7)
    PRIMARY_WATCHLIST,

    # Convenience
    TradingRules,
)

from .performance import (
    # Cache Settings
    CACHE_TTL_SECONDS,
    CACHE_TTL_INTRADAY,
    CACHE_TTL_VIX,
    CACHE_MAX_ENTRIES,

    # Request Settings
    REQUEST_TIMEOUT,
    MAX_CONCURRENT_REQUESTS,
    BATCH_DELAY,
    MAX_RETRIES,
    RETRY_BASE_DELAY,

    # Data Requirements
    MIN_DATA_POINTS,
    HISTORICAL_DAYS,

    # Numerical Precision
    PRICE_TOLERANCE,
    SCORE_DECIMAL_PLACES,

    # Class exports
    Performance,
)

__all__ = [
    # Classes
    'TechnicalIndicators',
    'Thresholds',
    'StrategyParameters',
    'RiskManagement',
    'Performance',
    'TradingRules',

    # Enums
    'TradeDecision',
    'VIXRegime',
    'ExitAction',

    # Trading Rules (PLAYBOOK)
    'VIXRegimeRules',
    'VIX_REGIME_RULES',
    'get_vix_regime',
    'get_regime_rules',
    'is_blacklisted',
    'get_adjusted_stability_min',
    'BLACKLIST_SYMBOLS',
    'PRIMARY_WATCHLIST',

    # Individual constants are also exported (see imports above)
]
