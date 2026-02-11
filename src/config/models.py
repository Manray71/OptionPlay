# OptionPlay - Configuration Models
# ==================================
# Dataclasses für alle Konfigurationstypen
#
# Extrahiert aus config_loader.py im Rahmen des Recursive Logic Refactorings (Phase 2.2)

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import os

try:
    from ..constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_STABILITY_MIN,
        ENTRY_PRICE_MIN, ENTRY_PRICE_MAX,
        ENTRY_VOLUME_MIN,
        ENTRY_IV_RANK_MIN, ENTRY_IV_RANK_MAX,
        SPREAD_SHORT_DELTA_TARGET, SPREAD_SHORT_DELTA_MIN, SPREAD_SHORT_DELTA_MAX,
        SPREAD_LONG_DELTA_TARGET, SPREAD_LONG_DELTA_MIN, SPREAD_LONG_DELTA_MAX,
        SPREAD_DTE_MIN, SPREAD_DTE_MAX, SPREAD_DTE_TARGET,
        SPREAD_MIN_CREDIT_PCT,
    )
except ImportError:
    from constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_STABILITY_MIN,
        ENTRY_PRICE_MIN, ENTRY_PRICE_MAX,
        ENTRY_VOLUME_MIN,
        ENTRY_IV_RANK_MIN, ENTRY_IV_RANK_MAX,
        SPREAD_SHORT_DELTA_TARGET, SPREAD_SHORT_DELTA_MIN, SPREAD_SHORT_DELTA_MAX,
        SPREAD_LONG_DELTA_TARGET, SPREAD_LONG_DELTA_MIN, SPREAD_LONG_DELTA_MAX,
        SPREAD_DTE_MIN, SPREAD_DTE_MAX, SPREAD_DTE_TARGET,
        SPREAD_MIN_CREDIT_PCT,
    )


# =============================================================================
# CONNECTION & PROVIDER CONFIGS
# =============================================================================

@dataclass
class ConnectionConfig:
    """Verbindungseinstellungen"""
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    timeout: int = 30
    max_retries: int = 3


@dataclass
class TradierConfig:
    """Tradier API Konfiguration"""
    enabled: bool = True
    environment: str = "sandbox"  # "sandbox" oder "production"
    api_key: str = ""
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    rate_limit_per_minute: int = 120

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("TRADIER_API_KEY", "")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def base_url(self) -> str:
        if self.is_production:
            return "https://api.tradier.com"
        return "https://sandbox.tradier.com"


# =============================================================================
# INDICATOR SCORING CONFIGS
# =============================================================================

@dataclass
class RSIConfig:
    """RSI Scoring Parameter"""
    period: int = 14
    extreme_oversold: int = 30
    oversold: int = 40
    neutral: int = 50
    weight_extreme: int = 3
    weight_oversold: int = 2
    weight_neutral: int = 1


@dataclass
class SupportConfig:
    """Support Level Scoring"""
    lookback_days: int = 60
    proximity_percent: float = 3.0
    proximity_percent_wide: float = 5.0
    min_touches: int = 2
    touch_tolerance_pct: float = 2.0  # Toleranz für Touch-Erkennung
    weight_close: int = 2
    weight_near: int = 1


@dataclass
class FibonacciLevel:
    """Einzelnes Fibonacci Level"""
    level: float
    tolerance: float
    points: int


@dataclass
class FibonacciConfig:
    """Fibonacci Retracement Config"""
    lookback_days: int = 90
    levels: List[FibonacciLevel] = field(default_factory=lambda: [
        FibonacciLevel(0.618, 0.02, 2),
        FibonacciLevel(0.500, 0.02, 2),
        FibonacciLevel(0.382, 0.02, 1)
    ])


@dataclass
class MovingAverageConfig:
    """Moving Average Parameter"""
    short_period: int = 20
    long_period: int = 200


@dataclass
class VolumeConfig:
    """Volumen Scoring"""
    average_period: int = 20
    spike_multiplier: float = 1.5
    # NEW: Volume-Trend Scoring
    weight_decreasing: float = 1.0  # Sinkendes Volumen = gesunder Pullback
    decrease_threshold: float = 0.7  # Vol < 70% des Durchschnitts = "decreasing"
    # E.3: Very low volume penalty
    very_low_threshold: float = 0.5  # Vol < 50% = very low (weak conviction)
    weight_very_low: float = -0.5   # Penalty for very low volume


@dataclass
class MACDScoringConfig:
    """MACD Scoring Konfiguration"""
    weight_bullish_cross: float = 2.0  # Bullish Cross = starkes Signal
    weight_bullish: float = 1.0  # Histogram positiv
    weight_neutral: float = 0.0


@dataclass
class StochasticScoringConfig:
    """Stochastik Scoring Konfiguration"""
    oversold_threshold: int = 20
    overbought_threshold: int = 80
    weight_oversold_cross: float = 2.0  # Oversold + Bullish Cross
    weight_oversold: float = 1.0  # Nur oversold


@dataclass
class TrendStrengthConfig:
    """Trend-Stärke Konfiguration"""
    # SMA-Alignment Scoring
    weight_strong_alignment: float = 2.0  # SMA20 > SMA50 > SMA200
    weight_moderate_alignment: float = 1.0  # Preis > SMA200, aber nicht perfektes Alignment
    # Slope-Berechnung
    slope_lookback: int = 5  # Tage für Slope-Berechnung
    min_positive_slope: float = 0.001  # Mindest-Steigung für Aufwärtstrend


@dataclass
class KeltnerChannelConfig:
    """Keltner Channel Konfiguration"""
    # Channel-Parameter
    ema_period: int = 20  # EMA für Mittellinie
    atr_period: int = 10  # ATR-Periode
    atr_multiplier: float = 2.0  # Multiplikator für Bandbreite

    # Scoring - Lower Band (für Pullback/Bounce Strategien)
    weight_below_lower: float = 2.0  # Preis unter unterem Band = stark oversold
    weight_near_lower: float = 1.0  # Preis nahe unterem Band
    weight_mean_reversion: float = 1.0  # Preis bewegt sich zurück zur Mitte

    # Scoring - Upper Band (für ATH Breakout Strategien)
    weight_above_upper: float = 2.0  # Preis über oberem Band = starker Breakout
    weight_near_upper: float = 1.0  # Preis nahe oberem Band = potenzieller Breakout

    # Thresholds
    near_band_threshold: float = 0.1  # Innerhalb 10% der Bandbreite zum Band


# =============================================================================
# STRATEGY SCORING CONFIGS
# =============================================================================

@dataclass
class PullbackScoringConfig:
    """Gesamte Pullback Scoring Konfiguration"""
    rsi: RSIConfig = field(default_factory=RSIConfig)
    support: SupportConfig = field(default_factory=SupportConfig)
    fibonacci: FibonacciConfig = field(default_factory=FibonacciConfig)
    moving_averages: MovingAverageConfig = field(default_factory=MovingAverageConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    # Zusätzliche Scoring-Komponenten
    macd: MACDScoringConfig = field(default_factory=MACDScoringConfig)
    stochastic: StochasticScoringConfig = field(default_factory=StochasticScoringConfig)
    trend_strength: TrendStrengthConfig = field(default_factory=TrendStrengthConfig)
    keltner: KeltnerChannelConfig = field(default_factory=KeltnerChannelConfig)
    max_score: int = 16  # Erhöht von 14 auf 16 (Keltner = 0-2)
    min_score_for_candidate: int = 6


# =============================================================================
# BOUNCE ANALYZER CONFIG
# =============================================================================

@dataclass
class BounceSupportConfig:
    """Support Detection für Bounce"""
    lookback_days: int = 60
    touches_min: int = 2
    tolerance_pct: float = 1.5  # Support-Zone Toleranz
    weight_strong: float = 3.0  # Starker Support mit Touches
    weight_moderate: float = 2.0
    weight_weak: float = 1.0


@dataclass
class BounceCandlestickConfig:
    """Candlestick Pattern Scoring für Bounce"""
    weight_hammer: float = 2.0
    weight_engulfing: float = 2.0
    weight_doji: float = 1.0
    weight_bullish_candle: float = 1.0


@dataclass
class BounceScoringConfig:
    """Gesamte Bounce Scoring Konfiguration"""
    support: BounceSupportConfig = field(default_factory=BounceSupportConfig)
    candlestick: BounceCandlestickConfig = field(default_factory=BounceCandlestickConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    macd: MACDScoringConfig = field(default_factory=MACDScoringConfig)
    stochastic: StochasticScoringConfig = field(default_factory=StochasticScoringConfig)
    keltner: KeltnerChannelConfig = field(default_factory=KeltnerChannelConfig)
    # RSI-Thresholds für Bounce (oversold)
    rsi_extreme_oversold: int = 30
    rsi_oversold: int = 40
    # Bounce Confirmation
    bounce_min_pct: float = 1.0
    volume_spike_multiplier: float = 1.3
    # Risk Management
    stop_below_support_pct: float = 2.0
    target_risk_reward: float = 2.0
    # Scoring
    max_score: int = 17
    min_score_for_signal: int = 6


# =============================================================================
# ATH BREAKOUT ANALYZER CONFIG
# =============================================================================

@dataclass
class ATHDetectionConfig:
    """ATH Detection Konfiguration"""
    lookback_days: int = 252  # 1 Jahr
    consolidation_days: int = 20
    breakout_threshold_pct: float = 1.0  # Min % über altem ATH
    weight_with_consolidation: float = 3.0
    weight_without_consolidation: float = 2.0


@dataclass
class MomentumConfig:
    """Momentum/ROC Konfiguration"""
    roc_period: int = 10  # Rate of Change Periode
    weight_strong_momentum: float = 2.0  # ROC > 5%
    weight_moderate_momentum: float = 1.0  # ROC > 2%
    strong_threshold: float = 5.0
    moderate_threshold: float = 2.0


@dataclass
class RelativeStrengthConfig:
    """Relative Strength vs SPY"""
    lookback_days: int = 20
    weight_strong_outperformance: float = 2.0  # > 5% Outperformance
    weight_moderate_outperformance: float = 1.0  # > 2%
    strong_threshold: float = 5.0
    moderate_threshold: float = 2.0


@dataclass
class ATHBreakoutScoringConfig:
    """Gesamte ATH Breakout Scoring Konfiguration"""
    ath_detection: ATHDetectionConfig = field(default_factory=ATHDetectionConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    momentum: MomentumConfig = field(default_factory=MomentumConfig)
    relative_strength: RelativeStrengthConfig = field(default_factory=RelativeStrengthConfig)
    macd: MACDScoringConfig = field(default_factory=MACDScoringConfig)
    keltner: KeltnerChannelConfig = field(default_factory=KeltnerChannelConfig)
    # Volume für Breakout (höher als normal)
    volume_spike_multiplier: float = 1.5
    volume_strong_multiplier: float = 2.25
    # RSI nicht überkauft
    rsi_max: float = 80.0
    rsi_ideal_max: float = 70.0
    # Scoring
    max_score: int = 16
    min_score_for_signal: int = 6


# =============================================================================
# EARNINGS DIP ANALYZER CONFIG
# =============================================================================

@dataclass
class DipDetectionConfig:
    """Earnings Dip Detection Konfiguration"""
    min_dip_pct: float = 5.0
    max_dip_pct: float = 25.0
    ideal_max_dip_pct: float = 10.0
    lookback_days: int = 5
    weight_ideal: float = 3.0  # 5-10% Dip
    weight_moderate: float = 2.0  # 10-15% Dip
    weight_large: float = 1.0  # 15-25% Dip


@dataclass
class GapAnalysisConfig:
    """Gap Analysis Konfiguration"""
    min_gap_pct: float = 2.0
    gap_fill_threshold: float = 50.0  # Ab 50% gilt als "filling"
    weight_gap_detected: float = 1.0


@dataclass
class StabilizationConfig:
    """Stabilization Scoring"""
    min_days_for_full_score: int = 2
    weight_stable: float = 2.0
    weight_beginning: float = 1.0


@dataclass
class EarningsDipScoringConfig:
    """Gesamte Earnings Dip Scoring Konfiguration"""
    dip_detection: DipDetectionConfig = field(default_factory=DipDetectionConfig)
    gap_analysis: GapAnalysisConfig = field(default_factory=GapAnalysisConfig)
    stabilization: StabilizationConfig = field(default_factory=StabilizationConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    macd: MACDScoringConfig = field(default_factory=MACDScoringConfig)
    stochastic: StochasticScoringConfig = field(default_factory=StochasticScoringConfig)
    keltner: KeltnerChannelConfig = field(default_factory=KeltnerChannelConfig)
    # RSI für Oversold nach Dip
    rsi_extreme_oversold: int = 25
    rsi_oversold: int = 35
    # Quality Filter
    require_above_sma200: bool = True
    # Risk Management
    stop_below_dip_low_pct: float = 3.0
    target_recovery_pct: float = 50.0
    # Scoring
    max_score: int = 18
    min_score_for_signal: int = 6


# =============================================================================
# FILTER CONFIGS
# =============================================================================

def _get_default_blacklist() -> List[str]:
    """Lädt die Default-Blacklist aus fundamentals_constants."""
    try:
        from .fundamentals_constants import DEFAULT_BLACKLIST
        return DEFAULT_BLACKLIST.copy()
    except ImportError:
        # Fallback wenn Import fehlschlägt
        return [
            "ROKU", "SNAP", "UPST", "AFRM", "MRNA",
            "RUN", "MSTR", "TSLA", "COIN", "SQ",
            "DAVE", "IONQ", "QBTS", "QMCO", "QUBT", "RDW", "RGTI"
        ]


@dataclass
class FundamentalsFilterConfig:
    """
    Fundamentals-basierte Filter für Symbol-Selektion.

    Nutzt Daten aus der symbol_fundamentals Tabelle:
    - Stability Score aus historischen Backtests
    - IV Rank/Percentile
    - SPY Correlation für Diversifikation
    - Historical Volatility
    - Sector/Market Cap Filtering

    Konstanten sind zentral definiert in: src/config/fundamentals_constants.py
    """
    # Aktivierung
    enabled: bool = True

    # Stability Filter (aus outcomes.db)
    # Stability Score >= 70 → 94.5% Win Rate (vs. 66% bei <50)
    min_stability_score: float = ENTRY_STABILITY_MIN  # PLAYBOOK §1: ≥65 (65-70=WARNING, ≥80 bei VIX>20)
    warn_below_stability: float = 60.0  # Warnung wenn unter diesem Wert
    boost_above_stability: float = 70.0  # Score-Boost ab diesem Wert

    # Historical Win Rate Filter
    min_historical_win_rate: float = 70.0  # Mindest historische Win Rate (%)

    # Volatility Filter
    # HV > 70% hat nur 27-31% Win Rate → ausschließen
    max_historical_volatility: float = 70.0  # Max annualisierte HV (%)
    max_beta: float = 2.0  # Max Beta zu SPY

    # IV Rank Filter (ergänzt bestehenden IV-Filter)
    # Optimal: IV Rank 20-80 (nicht zu niedrig, nicht zu hoch)
    iv_rank_min: float = 20.0  # Intentionally looser than ENTRY_IV_RANK_MIN (pre-filter)
    iv_rank_max: float = ENTRY_IV_RANK_MAX
    use_iv_percentile: bool = False  # True = iv_percentile statt iv_rank

    # SPY Correlation Filter (für Diversifikation)
    # Niedrige Korrelation = bessere Diversifikation
    max_spy_correlation: Optional[float] = None  # None = kein Filter
    min_spy_correlation: Optional[float] = None  # None = kein Filter

    # Sector Filter
    exclude_sectors: List[str] = field(default_factory=list)
    include_sectors: List[str] = field(default_factory=list)  # Leer = alle

    # Market Cap Filter
    # Kategorien: "Micro", "Small", "Mid", "Large", "Mega"
    # Default: Micro Caps ausschließen (synchron mit settings.yaml)
    exclude_market_caps: List[str] = field(default_factory=lambda: ["Micro"])
    include_market_caps: List[str] = field(default_factory=list)  # Leer = alle

    # Blacklist (Symbole die nie gehandelt werden)
    # Importiert aus fundamentals_constants.py für zentrale Verwaltung
    blacklist_symbols: List[str] = field(default_factory=lambda: _get_default_blacklist())

    # Whitelist (überschreibt alle anderen Filter)
    whitelist_symbols: List[str] = field(default_factory=list)


@dataclass
class FilterConfig:
    """Filter Einstellungen"""
    earnings_exclude_days: int = ENTRY_EARNINGS_MIN_DAYS
    price_minimum: float = ENTRY_PRICE_MIN
    price_maximum: float = ENTRY_PRICE_MAX
    volume_minimum: int = ENTRY_VOLUME_MIN
    iv_rank_minimum: float = ENTRY_IV_RANK_MIN
    iv_rank_maximum: float = ENTRY_IV_RANK_MAX
    # Fundamentals-Filter
    fundamentals: FundamentalsFilterConfig = field(default_factory=FundamentalsFilterConfig)


# =============================================================================
# SCANNER & OPTIONS CONFIGS
# =============================================================================

@dataclass
class ScannerConfig:
    """
    Scanner-Konfiguration aus settings.yaml.

    Wird verwendet, um ScanConfig im MultiStrategyScanner zu initialisieren.
    """
    # Score-Filter
    min_score: float = 5.0
    min_actionable_score: float = 6.0

    # Earnings-Filter
    exclude_earnings_within_days: int = ENTRY_EARNINGS_MIN_DAYS

    # Auto Earnings Pre-Filter (reduziert API-Calls!)
    auto_earnings_prefilter: bool = True  # Automatisch vor Scans filtern
    earnings_prefilter_min_days: int = ENTRY_EARNINGS_MIN_DAYS  # PLAYBOOK §1: >45 Tage

    # BMO/AMC Handling: Earnings vor/nach Markt
    # - AMC am Tag X: Reaktion erst am Tag X+1 → Tag X ist NICHT sicher
    # - BMO am Tag X: Reaktion bereits eingepreist → Tag X kann sicher sein
    earnings_allow_bmo_same_day: bool = False  # Konservativ: BMO-Tag nicht handeln

    # IV-Rank Filter (für Credit-Spreads wichtig!)
    iv_rank_minimum: float = ENTRY_IV_RANK_MIN   # Min IV-Rank für ausreichend Prämie
    iv_rank_maximum: float = ENTRY_IV_RANK_MAX   # Max IV-Rank (zu hohe IV = erhöhtes Risiko)
    enable_iv_filter: bool = True   # IV-Filter aktivieren/deaktivieren

    # Output-Limits
    max_results_per_symbol: int = 3
    max_total_results: int = 50

    # Parallel Processing
    max_concurrent: int = 10

    # Data Requirements
    min_data_points: int = 60

    # Strategies to enable
    enable_pullback: bool = True
    enable_ath_breakout: bool = True
    enable_bounce: bool = True
    enable_earnings_dip: bool = True

    # Stability-First-Filter (Phase 6)
    # Stability ist der stärkste Prädiktor für Win Rate!
    enable_stability_first: bool = True  # Stability-First-Filterung aktivieren
    stability_premium_threshold: float = 80.0  # Premium-Symbole (94.5% WR)
    stability_premium_min_score: float = 4.0   # Niedrigerer Score OK für Premium
    stability_good_threshold: float = 70.0     # Gute Symbole (86.1% WR)
    stability_good_min_score: float = 5.0      # Standard Score für gute Symbole
    stability_ok_threshold: float = 50.0       # Akzeptable Symbole
    stability_ok_min_score: float = 6.0        # Höherer Score für grenzwertige Symbole


@dataclass
class OptionsConfig:
    """Options Analyse Parameter"""
    dte_minimum: int = SPREAD_DTE_MIN
    dte_maximum: int = SPREAD_DTE_MAX
    dte_target: int = SPREAD_DTE_TARGET
    # Short Put (verkauft) - Delta ±0.20 (PLAYBOOK §2: ±0.03)
    # Note: delta_minimum = less aggressive (smaller |delta|, closer to 0)
    #       delta_maximum = more aggressive (larger |delta|, further from 0)
    delta_minimum: float = SPREAD_SHORT_DELTA_MIN   # Less aggressive boundary (PLAYBOOK §2)
    delta_maximum: float = SPREAD_SHORT_DELTA_MAX   # More aggressive boundary (PLAYBOOK §2)
    delta_target: float = SPREAD_SHORT_DELTA_TARGET
    # Long Put (gekauft) - Delta (PLAYBOOK §2: ±0.02)
    long_delta_minimum: float = SPREAD_LONG_DELTA_MIN   # Less aggressive boundary (PLAYBOOK §2)
    long_delta_maximum: float = SPREAD_LONG_DELTA_MAX   # More aggressive boundary (PLAYBOOK §2)
    long_delta_target: float = SPREAD_LONG_DELTA_TARGET
    # Spread-Breite: NICHT konfigurierbar — ergibt sich aus Delta-Differenz (PLAYBOOK §2)
    min_credit_pct: float = SPREAD_MIN_CREDIT_PCT  # PLAYBOOK §2: ≥10% Spread-Breite
    min_open_interest: int = 100

    @property
    def delta_min(self) -> float:
        return self.delta_minimum

    @property
    def delta_max(self) -> float:
        return self.delta_maximum

    # Short put aliases
    @property
    def short_delta_target(self) -> float:
        return self.delta_target

    @property
    def short_delta_min(self) -> float:
        return self.delta_minimum

    @property
    def short_delta_max(self) -> float:
        return self.delta_maximum


# =============================================================================
# PERFORMANCE & INFRASTRUCTURE CONFIGS
# =============================================================================

@dataclass
class PerformanceConfig:
    """Performance und Cache Parameter"""
    request_timeout: int = 30
    batch_delay: float = 1.0
    max_concurrent_requests: int = 5
    # Cache TTLs (in Sekunden)
    cache_ttl_seconds: int = 900  # 15 Minuten (historische Daten ändern sich selten)
    cache_ttl_intraday: int = 300  # 5 Minuten für Intraday-Quotes
    cache_ttl_vix: int = 300  # 5 Minuten für VIX
    historical_days: int = 260
    cache_max_entries: int = 500


@dataclass
class ApiConnectionConfig:
    """API Verbindungs-Parameter"""
    max_retries: int = 3
    retry_base_delay: int = 2
    vix_cache_seconds: int = 300
    yahoo_timeout: int = 10


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker Parameter"""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    success_threshold: int = 2


@dataclass
class LocalDatabaseConfig:
    """Local database configuration for historical data."""
    enabled: bool = True
    db_path: str = "~/.optionplay/trades.db"
    max_data_age_days: int = 7
    min_data_points: int = 60


@dataclass
class DataSourcesConfig:
    """Data sources configuration for historical data priority."""
    local_database: LocalDatabaseConfig = field(default_factory=LocalDatabaseConfig)
    provider_priority: List[str] = field(default_factory=lambda: [
        "local_db", "tradier", "marketdata", "yahoo"
    ])


# =============================================================================
# MAIN SETTINGS
# =============================================================================

@dataclass
class Settings:
    """Haupt-Konfigurationsklasse"""
    data_sources: DataSourcesConfig = field(default_factory=DataSourcesConfig)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    tradier: TradierConfig = field(default_factory=TradierConfig)
    pullback_scoring: PullbackScoringConfig = field(default_factory=PullbackScoringConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    api_connection: ApiConnectionConfig = field(default_factory=ApiConnectionConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    log_level: str = "INFO"
    log_api_calls: bool = True
    cache_ttl: int = 300


# =============================================================================
# TRAINED WEIGHTS (ML)
# =============================================================================

@dataclass
class TrainedWeights:
    """Trained component weights for a strategy."""
    weights: Dict[str, float] = field(default_factory=dict)
    roll_params: Dict[str, float] = field(default_factory=dict)
    performance: Dict[str, float] = field(default_factory=dict)


@dataclass
class GapBoostConfig:
    """Gap Boost configuration for score enhancement based on gap signals."""
    enabled: bool = True
    # Default thresholds (in %)
    large_gap_pct: float = 3.0
    medium_gap_pct: float = 1.0
    small_gap_pct: float = 0.5
    # Per-strategy boost multipliers
    strategy_boosts: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def get_boost_multiplier(self, strategy: str, gap_size_pct: float, gap_type: str) -> float:
        """
        Calculate the gap boost multiplier for a given gap.

        Args:
            strategy: Strategy name ('pullback', 'bounce', etc.)
            gap_size_pct: Gap size in percent (negative for down-gaps)
            gap_type: Gap type ('up', 'down', 'partial_up', 'partial_down', 'none')

        Returns:
            Multiplier to apply to final score (1.0 = no change)
        """
        if not self.enabled or gap_type == 'none':
            return 1.0

        boosts = self.strategy_boosts.get(strategy, {})
        if not boosts:
            return 1.0

        abs_size = abs(gap_size_pct)
        is_down = gap_type in ('down', 'partial_down')
        is_up = gap_type in ('up', 'partial_up')

        if is_down:
            if abs_size >= self.large_gap_pct:
                return boosts.get('large_down_gap', 1.0)
            elif abs_size >= self.medium_gap_pct:
                return boosts.get('medium_down_gap', 1.0)
            elif abs_size >= self.small_gap_pct:
                return boosts.get('small_down_gap', 1.0)
        elif is_up:
            if abs_size >= self.large_gap_pct:
                return boosts.get('large_up_gap', 1.0)
            # Medium/small up-gaps get no boost by default

        return 1.0


@dataclass
class TrainedWeightsConfig:
    """All trained weights from ML training."""
    version: str = "1.0.0"
    training_date: str = ""
    pullback: TrainedWeights = field(default_factory=TrainedWeights)
    bounce: TrainedWeights = field(default_factory=TrainedWeights)
    ath_breakout: TrainedWeights = field(default_factory=TrainedWeights)
    earnings_dip: TrainedWeights = field(default_factory=TrainedWeights)
    vix_regime_multipliers: Dict[str, Dict[str, float]] = field(default_factory=dict)
    gap_boost: GapBoostConfig = field(default_factory=GapBoostConfig)

    def get_strategy_weights(self, strategy: str) -> Dict[str, float]:
        """Get weights for a specific strategy."""
        strategy_map = {
            'pullback': self.pullback,
            'bounce': self.bounce,
            'ath_breakout': self.ath_breakout,
            'earnings_dip': self.earnings_dip,
        }
        tw = strategy_map.get(strategy)
        return tw.weights if tw else {}

    def get_roll_params(self, strategy: str) -> Dict[str, float]:
        """Get roll parameters for a specific strategy."""
        strategy_map = {
            'pullback': self.pullback,
            'bounce': self.bounce,
            'ath_breakout': self.ath_breakout,
            'earnings_dip': self.earnings_dip,
        }
        tw = strategy_map.get(strategy)
        return tw.roll_params if tw else {}

    def get_gap_boost(self, strategy: str, gap_size_pct: float, gap_type: str) -> float:
        """Get gap boost multiplier for a strategy and gap."""
        return self.gap_boost.get_boost_multiplier(strategy, gap_size_pct, gap_type)
