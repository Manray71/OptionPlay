# OptionPlay - Configuration Loader
# ===================================
# Lädt und validiert alle Konfigurationsdateien

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging
import os

try:
    from ..constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_STABILITY_MIN,
    )
except ImportError:
    from constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_STABILITY_MIN,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIG PATH RESOLUTION
# =============================================================================

def find_config_dir(config_dir: Optional[str] = None) -> Path:
    """
    Findet das Config-Verzeichnis.
    
    Suchpfade (in Reihenfolge):
    1. Explizit angegebener Pfad
    2. ~/OptionPlay/config/
    3. ../config/ (relativ zum src-Verzeichnis)
    4. ./config/ (aktuelles Arbeitsverzeichnis)
    
    Returns:
        Path zum Config-Verzeichnis oder Fallback auf './config'
    """
    if config_dir:
        path = Path(config_dir)
        if path.exists():
            return path
    
    # Standard-Suchpfade
    possible_paths = [
        Path.home() / "OptionPlay" / "config",
        Path(__file__).parent.parent.parent / "config",
        Path.cwd() / "config"
    ]
    
    for path in possible_paths:
        if path.exists():
            logger.debug(f"Found config directory: {path}")
            return path
    
    logger.warning("Config directory not found in standard locations")
    return Path("config")


# =============================================================================
# DATACLASSES
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

    def __post_init__(self):
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
    min_stability_score: float = ENTRY_STABILITY_MIN  # PLAYBOOK §1: ≥70 (≥80 bei VIX>20)
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
    iv_rank_min: float = 20.0
    iv_rank_max: float = 80.0
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
class FilterConfig:
    """Filter Einstellungen"""
    earnings_exclude_days: int = 60
    price_minimum: float = 20.0
    price_maximum: float = 1500.0
    volume_minimum: int = 500000
    iv_rank_minimum: float = 30.0
    iv_rank_maximum: float = 80.0
    # Fundamentals-Filter
    fundamentals: FundamentalsFilterConfig = field(default_factory=FundamentalsFilterConfig)


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
    exclude_earnings_within_days: int = 60

    # Auto Earnings Pre-Filter (reduziert API-Calls!)
    auto_earnings_prefilter: bool = True  # Automatisch vor Scans filtern
    earnings_prefilter_min_days: int = ENTRY_EARNINGS_MIN_DAYS  # PLAYBOOK §1: >60 Tage

    # BMO/AMC Handling: Earnings vor/nach Markt
    # - AMC am Tag X: Reaktion erst am Tag X+1 → Tag X ist NICHT sicher
    # - BMO am Tag X: Reaktion bereits eingepreist → Tag X kann sicher sein
    earnings_allow_bmo_same_day: bool = False  # Konservativ: BMO-Tag nicht handeln

    # IV-Rank Filter (für Credit-Spreads wichtig!)
    iv_rank_minimum: float = 30.0   # Min IV-Rank für ausreichend Prämie
    iv_rank_maximum: float = 80.0   # Max IV-Rank (zu hohe IV = erhöhtes Risiko)
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
    dte_minimum: int = 60
    dte_maximum: int = 90
    dte_target: int = 75
    # Short Put (verkauft) - Delta ±0.20 (PLAYBOOK §2: ±0.03)
    # Note: delta_minimum = less aggressive (smaller |delta|, closer to 0)
    #       delta_maximum = more aggressive (larger |delta|, further from 0)
    delta_minimum: float = -0.17  # Less aggressive boundary (PLAYBOOK §2)
    delta_maximum: float = -0.23  # More aggressive boundary (PLAYBOOK §2)
    delta_target: float = -0.20
    # Long Put (gekauft) - Delta ±0.05 (PLAYBOOK §2: ±0.02)
    long_delta_minimum: float = -0.03  # Less aggressive boundary (PLAYBOOK §2)
    long_delta_maximum: float = -0.07  # More aggressive boundary (PLAYBOOK §2)
    long_delta_target: float = -0.05
    # Spread-Breite: NICHT konfigurierbar — ergibt sich aus Delta-Differenz (PLAYBOOK §2)
    min_credit_pct: float = 10.0  # PLAYBOOK §2: ≥10% Spread-Breite
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
# CONFIG LOADER
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


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed: {'; '.join(errors)}")


class ConfigLoader:
    """Lädt und verwaltet Konfiguration."""

    def __init__(self, config_dir: Optional[str] = None, validate: bool = True):
        """
        Initialize config loader.

        Args:
            config_dir: Optional path to config directory.
            validate: If True (default), validates config values after loading.
                      Set to False for testing with intentionally invalid configs.
        """
        self.config_dir = find_config_dir(config_dir)
        self._validate = validate
        self._settings: Optional[Settings] = None
        self._strategies: Dict[str, Any] = {}
        self._watchlists: Dict[str, List[str]] = {}
        self._sectors: Dict[str, List[str]] = {}
        self._trained_weights: Optional[TrainedWeightsConfig] = None

    def load_all(self) -> Settings:
        """Lädt alle Konfigurationsdateien"""
        self._load_settings()
        self._load_strategies()
        self._load_watchlists()
        self._load_trained_weights()
        return self._settings

    def _validate_settings(self, settings: Settings) -> None:
        """
        Validates configuration values for consistency and valid ranges.

        Raises:
            ConfigValidationError: If validation fails with list of errors.
        """
        errors: List[str] = []

        # RSI validation
        rsi = settings.pullback_scoring.rsi
        if rsi.extreme_oversold >= rsi.oversold:
            errors.append(
                f"RSI extreme_oversold ({rsi.extreme_oversold}) must be < oversold ({rsi.oversold})"
            )
        if rsi.oversold >= rsi.neutral:
            errors.append(
                f"RSI oversold ({rsi.oversold}) must be < neutral ({rsi.neutral})"
            )
        if not (0 <= rsi.extreme_oversold <= 100):
            errors.append(f"RSI extreme_oversold ({rsi.extreme_oversold}) must be 0-100")
        if not (0 <= rsi.oversold <= 100):
            errors.append(f"RSI oversold ({rsi.oversold}) must be 0-100")
        if not (0 <= rsi.neutral <= 100):
            errors.append(f"RSI neutral ({rsi.neutral}) must be 0-100")
        if rsi.period <= 0:
            errors.append(f"RSI period ({rsi.period}) must be > 0")

        # Stochastic validation
        stoch = settings.pullback_scoring.stochastic
        if stoch.oversold_threshold >= stoch.overbought_threshold:
            errors.append(
                f"Stochastic oversold ({stoch.oversold_threshold}) must be < overbought ({stoch.overbought_threshold})"
            )

        # Options DTE validation
        opts = settings.options
        if opts.dte_minimum >= opts.dte_maximum:
            errors.append(
                f"Options DTE minimum ({opts.dte_minimum}) must be < maximum ({opts.dte_maximum})"
            )
        if opts.dte_minimum <= 0:
            errors.append(f"Options DTE minimum ({opts.dte_minimum}) must be > 0")
        if not (opts.dte_minimum <= opts.dte_target <= opts.dte_maximum):
            errors.append(
                f"Options DTE target ({opts.dte_target}) must be between min ({opts.dte_minimum}) and max ({opts.dte_maximum})"
            )

        # Delta validation (negative values for puts)
        # Note: For puts, delta ranges from -1.0 to 0. The "minimum" in settings.yaml
        # refers to the less aggressive (closer to 0) boundary, while "maximum" is the
        # more aggressive (further from 0) boundary. So delta_minimum > delta_maximum
        # in terms of raw value (e.g., -0.18 > -0.21). We validate the absolute values.
        if not (-1.0 <= opts.delta_minimum <= 0):
            errors.append(f"Short put delta_minimum ({opts.delta_minimum}) must be between -1.0 and 0")
        if not (-1.0 <= opts.delta_maximum <= 0):
            errors.append(f"Short put delta_maximum ({opts.delta_maximum}) must be between -1.0 and 0")
        if abs(opts.delta_minimum) >= abs(opts.delta_maximum):
            # delta_minimum should be less aggressive (smaller absolute value)
            errors.append(
                f"Short put delta_minimum ({opts.delta_minimum}) should be less aggressive "
                f"(smaller |delta|) than delta_maximum ({opts.delta_maximum})"
            )

        # Long put delta validation
        if not (-1.0 <= opts.long_delta_minimum <= 0):
            errors.append(f"Long put delta_minimum ({opts.long_delta_minimum}) must be between -1.0 and 0")
        if not (-1.0 <= opts.long_delta_maximum <= 0):
            errors.append(f"Long put delta_maximum ({opts.long_delta_maximum}) must be between -1.0 and 0")

        # Filter validation
        filters = settings.filters
        if filters.price_minimum >= filters.price_maximum:
            errors.append(
                f"Price minimum (${filters.price_minimum}) must be < maximum (${filters.price_maximum})"
            )
        if filters.price_minimum <= 0:
            errors.append(f"Price minimum (${filters.price_minimum}) must be > 0")

        # IV Rank validation
        if filters.iv_rank_minimum >= filters.iv_rank_maximum:
            errors.append(
                f"IV rank minimum ({filters.iv_rank_minimum}) must be < maximum ({filters.iv_rank_maximum})"
            )
        if not (0 <= filters.iv_rank_minimum <= 100):
            errors.append(f"IV rank minimum ({filters.iv_rank_minimum}) must be 0-100")
        if not (0 <= filters.iv_rank_maximum <= 100):
            errors.append(f"IV rank maximum ({filters.iv_rank_maximum}) must be 0-100")

        # Scanner validation
        scanner = settings.scanner
        if scanner.min_score >= scanner.min_actionable_score:
            errors.append(
                f"Scanner min_score ({scanner.min_score}) should be < min_actionable_score ({scanner.min_actionable_score})"
            )
        if scanner.max_concurrent <= 0:
            errors.append(f"Scanner max_concurrent ({scanner.max_concurrent}) must be > 0")
        if scanner.min_data_points <= 0:
            errors.append(f"Scanner min_data_points ({scanner.min_data_points}) must be > 0")

        # Fundamentals filter validation
        fund = filters.fundamentals
        if fund.enabled:
            if not (0 <= fund.min_stability_score <= 100):
                errors.append(f"Fundamentals min_stability_score ({fund.min_stability_score}) must be 0-100")
            if not (0 <= fund.min_historical_win_rate <= 100):
                errors.append(f"Fundamentals min_historical_win_rate ({fund.min_historical_win_rate}) must be 0-100")
            if fund.max_historical_volatility <= 0:
                errors.append(f"Fundamentals max_historical_volatility ({fund.max_historical_volatility}) must be > 0")
            if fund.max_beta <= 0:
                errors.append(f"Fundamentals max_beta ({fund.max_beta}) must be > 0")

        # Performance validation
        perf = settings.performance
        if perf.request_timeout <= 0:
            errors.append(f"Performance request_timeout ({perf.request_timeout}) must be > 0")
        if perf.historical_days <= 0:
            errors.append(f"Performance historical_days ({perf.historical_days}) must be > 0")
        if perf.cache_ttl_seconds < 0:
            errors.append(f"Performance cache_ttl_seconds ({perf.cache_ttl_seconds}) must be >= 0")

        # Circuit breaker validation
        cb = settings.circuit_breaker
        if cb.failure_threshold <= 0:
            errors.append(f"Circuit breaker failure_threshold ({cb.failure_threshold}) must be > 0")
        if cb.recovery_timeout <= 0:
            errors.append(f"Circuit breaker recovery_timeout ({cb.recovery_timeout}) must be > 0")

        # Raise error if any validations failed
        if errors:
            raise ConfigValidationError(errors)
    
    def _load_settings(self) -> None:
        """Lädt settings.yaml"""
        settings_path = self.config_dir / "settings.yaml"

        if not settings_path.exists():
            logger.warning(f"Settings not found: {settings_path}, using defaults")
            self._settings = Settings()
            return

        with open(settings_path, 'r') as f:
            raw = yaml.safe_load(f)

        # Handle empty YAML files (yaml.safe_load returns None)
        if raw is None:
            raw = {}

        self._settings = self._parse_settings(raw)

        # Validate configuration values if enabled
        if self._validate:
            try:
                self._validate_settings(self._settings)
            except ConfigValidationError as e:
                for error in e.errors:
                    logger.error(f"Config validation error: {error}")
                raise
            logger.info(f"Loaded and validated settings from {settings_path}")
        else:
            logger.info(f"Loaded settings from {settings_path} (validation disabled)")
        
    def _parse_settings(self, raw: Dict) -> Settings:
        """Parst Raw-YAML in Settings-Objekt"""
        settings = Settings()

        # Data Sources (for historical data)
        if 'data_sources' in raw:
            ds = raw['data_sources']
            local_db = ds.get('local_database', {})
            settings.data_sources = DataSourcesConfig(
                local_database=LocalDatabaseConfig(
                    enabled=local_db.get('enabled', True),
                    db_path=local_db.get('db_path', '~/.optionplay/trades.db'),
                    max_data_age_days=local_db.get('max_data_age_days', 7),
                    min_data_points=local_db.get('min_data_points', 60)
                ),
                provider_priority=ds.get('provider_priority', [
                    "local_db", "tradier", "marketdata", "yahoo"
                ])
            )

        # Connection (IBKR)
        if 'connection' in raw and 'ibkr' in raw['connection']:
            conn = raw['connection']['ibkr']
            settings.connection = ConnectionConfig(
                host=conn.get('host', '127.0.0.1'),
                port=conn.get('port', 7497),
                client_id=conn.get('client_id', 1),
                timeout=conn.get('timeout_seconds', 30),
                max_retries=conn.get('max_retries', 3)
            )
            
        # Tradier (can be under 'connection' or at root level)
        trad = None
        if 'connection' in raw and 'tradier' in raw['connection']:
            trad = raw['connection']['tradier']
        elif 'tradier' in raw:
            trad = raw['tradier']

        if trad:
            settings.tradier = TradierConfig(
                enabled=trad.get('enabled', True),
                environment=trad.get('environment', 'sandbox'),
                api_key=trad.get('api_key', ''),
                timeout_seconds=trad.get('timeout_seconds', 30),
                max_retries=trad.get('max_retries', 3),
                retry_delay_seconds=trad.get('retry_delay_seconds', 1.0),
                rate_limit_per_minute=trad.get('rate_limit_per_minute', 120)
            )
            
        # Pullback Scoring
        if 'pullback_scoring' in raw:
            ps = raw['pullback_scoring']
            
            if 'rsi' in ps:
                rsi = ps['rsi']
                settings.pullback_scoring.rsi = RSIConfig(
                    period=rsi.get('period', 14),
                    extreme_oversold=rsi.get('thresholds', {}).get('extreme_oversold', 30),
                    oversold=rsi.get('thresholds', {}).get('oversold', 40),
                    neutral=rsi.get('thresholds', {}).get('neutral', 50),
                    weight_extreme=rsi.get('weights', {}).get('extreme_oversold', 3),
                    weight_oversold=rsi.get('weights', {}).get('oversold', 2),
                    weight_neutral=rsi.get('weights', {}).get('neutral', 1)
                )
            
            if 'support' in ps:
                sup = ps['support']
                settings.pullback_scoring.support = SupportConfig(
                    lookback_days=sup.get('lookback_days', 60),
                    proximity_percent=sup.get('proximity_percent', 3.0),
                    proximity_percent_wide=sup.get('proximity_percent_wide', 5.0),
                    weight_close=sup.get('weights', {}).get('close_to_support', 2),
                    weight_near=sup.get('weights', {}).get('near_support', 1)
                )
            
            if 'fibonacci' in ps:
                fib = ps['fibonacci']
                levels = []
                for lvl in fib.get('levels', []):
                    levels.append(FibonacciLevel(
                        level=lvl['level'],
                        tolerance=lvl['tolerance'],
                        points=lvl['points']
                    ))
                settings.pullback_scoring.fibonacci = FibonacciConfig(
                    lookback_days=fib.get('lookback_days', 90),
                    levels=levels if levels else settings.pullback_scoring.fibonacci.levels
                )
            
            if 'moving_averages' in ps:
                ma = ps['moving_averages']
                settings.pullback_scoring.moving_averages = MovingAverageConfig(
                    short_period=ma.get('short_period', 20),
                    long_period=ma.get('long_period', 200)
                )
            
            if 'volume' in ps:
                vol = ps['volume']
                settings.pullback_scoring.volume = VolumeConfig(
                    average_period=vol.get('average_period', 20),
                    spike_multiplier=vol.get('spike_multiplier', 1.5)
                )
                
            if 'total' in ps:
                settings.pullback_scoring.max_score = ps['total'].get('max_score', 10)
                settings.pullback_scoring.min_score_for_candidate = ps['total'].get('min_score_for_candidate', 5)
                
        # Filters
        if 'filters' in raw:
            f = raw['filters']

            # Parse Fundamentals Filter
            fundamentals_config = FundamentalsFilterConfig()
            if 'fundamentals' in f:
                fund = f['fundamentals']
                # None-sichere Getter: `or []` für Listen, `or default` für optionale Werte
                # Verhindert Fehler wenn YAML `null` enthält
                fundamentals_config = FundamentalsFilterConfig(
                    enabled=fund.get('enabled', True),
                    min_stability_score=fund.get('min_stability_score') or 50.0,
                    warn_below_stability=fund.get('warn_below_stability') or 60.0,
                    boost_above_stability=fund.get('boost_above_stability') or 70.0,
                    min_historical_win_rate=fund.get('min_historical_win_rate') or 70.0,
                    max_historical_volatility=fund.get('max_historical_volatility') or 70.0,
                    max_beta=fund.get('max_beta') or 2.0,
                    iv_rank_min=fund.get('iv_rank_min') or 20.0,
                    iv_rank_max=fund.get('iv_rank_max') or 80.0,
                    use_iv_percentile=fund.get('use_iv_percentile', False),
                    max_spy_correlation=fund.get('max_spy_correlation'),  # None ist hier erlaubt
                    min_spy_correlation=fund.get('min_spy_correlation'),  # None ist hier erlaubt
                    exclude_sectors=fund.get('exclude_sectors') or [],
                    include_sectors=fund.get('include_sectors') or [],
                    exclude_market_caps=fund.get('exclude_market_caps') or [],
                    include_market_caps=fund.get('include_market_caps') or [],
                    blacklist_symbols=fund.get('blacklist_symbols') or _get_default_blacklist(),
                    whitelist_symbols=fund.get('whitelist_symbols') or [],
                )

            settings.filters = FilterConfig(
                earnings_exclude_days=f.get('earnings', {}).get('exclude_days_before', 60),
                price_minimum=f.get('price', {}).get('minimum', 20.0),
                price_maximum=f.get('price', {}).get('maximum', 500.0),
                volume_minimum=f.get('volume', {}).get('minimum_daily', 500000),
                iv_rank_minimum=f.get('implied_volatility', {}).get('iv_rank_minimum', 30),
                iv_rank_maximum=f.get('implied_volatility', {}).get('iv_rank_maximum', 80),
                fundamentals=fundamentals_config,
            )
            
        # Options Analysis
        if 'options_analysis' in raw:
            oa = raw['options_analysis']
            settings.options = OptionsConfig(
                dte_minimum=oa.get('expiration', {}).get('dte_minimum', 60),
                dte_maximum=oa.get('expiration', {}).get('dte_maximum', 90),
                dte_target=oa.get('expiration', {}).get('dte_target', 75),
                # Short Put Delta ±0.20 (PLAYBOOK §2: ±0.03)
                delta_minimum=oa.get('short_put', {}).get('delta_minimum', -0.17),
                delta_maximum=oa.get('short_put', {}).get('delta_maximum', -0.23),
                delta_target=oa.get('short_put', {}).get('delta_target', -0.20),
                # Long Put Delta ±0.05 (PLAYBOOK §2: ±0.02)
                long_delta_minimum=oa.get('long_put', {}).get('delta_minimum', -0.03),
                long_delta_maximum=oa.get('long_put', {}).get('delta_maximum', -0.07),
                long_delta_target=oa.get('long_put', {}).get('delta_target', -0.05),
                # Spread-Breite: dynamisch aus Delta (PLAYBOOK §2)
                min_credit_pct=oa.get('premium', {}).get('minimum_credit_percent', 10),
                min_open_interest=oa.get('liquidity', {}).get('min_open_interest', 100)
            )
            logger.info(
                f"Delta config loaded — Short: target={settings.options.delta_target}, "
                f"range=[{settings.options.delta_minimum}, {settings.options.delta_maximum}] | "
                f"Long: target={settings.options.long_delta_target}, "
                f"range=[{settings.options.long_delta_minimum}, {settings.options.long_delta_maximum}]"
            )

        if 'logging' in raw:
            settings.log_level = raw['logging'].get('level', 'INFO')
            settings.log_api_calls = raw['logging'].get('log_api_calls', True)
        
        # Scanner Config
        # Kombiniert Werte aus verschiedenen Sections
        scanner_raw = raw.get('scanner', {})
        settings.scanner = ScannerConfig(
            min_score=settings.pullback_scoring.min_score_for_candidate,
            min_actionable_score=settings.pullback_scoring.min_score_for_candidate + 1,
            exclude_earnings_within_days=settings.filters.earnings_exclude_days,
            auto_earnings_prefilter=scanner_raw.get('auto_earnings_prefilter', True),
            earnings_prefilter_min_days=scanner_raw.get('earnings_prefilter_min_days', ENTRY_EARNINGS_MIN_DAYS),
            earnings_allow_bmo_same_day=scanner_raw.get('earnings_allow_bmo_same_day', False),
            iv_rank_minimum=settings.filters.iv_rank_minimum,
            iv_rank_maximum=settings.filters.iv_rank_maximum,
            enable_iv_filter=scanner_raw.get('enable_iv_filter', True),
            max_results_per_symbol=scanner_raw.get('max_results_per_symbol', 3),
            max_total_results=scanner_raw.get('max_total_results', 50),
            max_concurrent=raw.get('performance', {}).get('max_concurrent_requests', 10),
            min_data_points=scanner_raw.get('min_data_points', 60),
            enable_pullback=scanner_raw.get('enable_pullback', True),
            enable_ath_breakout=scanner_raw.get('enable_ath_breakout', True),
            enable_bounce=scanner_raw.get('enable_bounce', True),
            enable_earnings_dip=scanner_raw.get('enable_earnings_dip', True),
            # Stability-First-Filter (Phase 6)
            enable_stability_first=scanner_raw.get('enable_stability_first', True),
            stability_premium_threshold=scanner_raw.get('stability_premium_threshold', 80.0),
            stability_premium_min_score=scanner_raw.get('stability_premium_min_score', 4.0),
            stability_good_threshold=scanner_raw.get('stability_good_threshold', 70.0),
            stability_good_min_score=scanner_raw.get('stability_good_min_score', 5.0),
            stability_ok_threshold=scanner_raw.get('stability_ok_threshold', 50.0),
            stability_ok_min_score=scanner_raw.get('stability_ok_min_score', 6.0),
        )
        
        # Performance Config
        if 'performance' in raw:
            perf = raw['performance']
            settings.performance = PerformanceConfig(
                request_timeout=perf.get('request_timeout', 30),
                batch_delay=perf.get('batch_delay', 1.0),
                max_concurrent_requests=perf.get('max_concurrent_requests', 5),
                cache_ttl_seconds=perf.get('cache_ttl_seconds', 900),  # 15 min default
                cache_ttl_intraday=perf.get('cache_ttl_intraday', 300),  # 5 min
                cache_ttl_vix=perf.get('cache_ttl_vix', 300),  # 5 min
                historical_days=perf.get('historical_days', 260),
                cache_max_entries=perf.get('cache_max_entries', 500),
            )
        
        # API Connection Config
        if 'api_connection' in raw:
            api_conn = raw['api_connection']
            settings.api_connection = ApiConnectionConfig(
                max_retries=api_conn.get('max_retries', 3),
                retry_base_delay=api_conn.get('retry_base_delay', 2),
                vix_cache_seconds=api_conn.get('vix_cache_seconds', 300),
                yahoo_timeout=api_conn.get('yahoo_timeout', 10),
            )
        
        # Circuit Breaker Config
        if 'circuit_breaker' in raw:
            cb = raw['circuit_breaker']
            settings.circuit_breaker = CircuitBreakerConfig(
                failure_threshold=cb.get('failure_threshold', 5),
                recovery_timeout=cb.get('recovery_timeout', 60.0),
                half_open_max_calls=cb.get('half_open_max_calls', 3),
                success_threshold=cb.get('success_threshold', 2),
            )
            
        return settings
    
    def _load_strategies(self) -> None:
        """Lädt strategies.yaml"""
        strategies_path = self.config_dir / "strategies.yaml"
        
        if not strategies_path.exists():
            logger.warning(f"Strategies not found: {strategies_path}")
            return
            
        with open(strategies_path, 'r') as f:
            raw = yaml.safe_load(f)
            
        self._strategies = raw.get('profiles', {})
        logger.info(f"Loaded {len(self._strategies)} strategy profiles")
        
    def _load_watchlists(self) -> None:
        """Lädt watchlists.yaml"""
        watchlists_path = self.config_dir / "watchlists.yaml"
        
        if not watchlists_path.exists():
            logger.warning(f"Watchlists not found: {watchlists_path}")
            return
            
        with open(watchlists_path, 'r') as f:
            raw = yaml.safe_load(f)
            
        for list_name, list_data in raw.get('watchlists', {}).items():
            symbols = []
            
            if 'sectors' in list_data:
                for sector_name, sector_data in list_data['sectors'].items():
                    sector_symbols = sector_data.get('symbols', [])
                    symbols.extend(sector_symbols)
                    self._sectors[sector_name] = sector_symbols
            elif 'symbols' in list_data:
                symbols = list_data['symbols']
                
            self._watchlists[list_name] = symbols
            
        logger.info(f"Loaded {len(self._watchlists)} watchlists, {len(self._sectors)} sectors")

    def _load_trained_weights(self, variant: Optional[str] = None) -> None:
        """
        Lädt trained_weights.yaml mit ML-trainierten Gewichten.

        Args:
            variant: Optional A/B test variant override. If None, uses global setting.
                     "A" = feature-based (trained_weights.yaml)
                     "B" = outcome-based (trained_weights_outcome_based.yaml)
        """
        # Determine which weights file to load
        ab_variant = variant or _ab_test_variant

        if ab_variant == "B":
            weights_path = self.config_dir / "trained_weights_outcome_based.yaml"
            if not weights_path.exists():
                logger.warning("Outcome-based weights not found, falling back to feature-based")
                weights_path = self.config_dir / "trained_weights.yaml"
        else:
            weights_path = self.config_dir / "trained_weights.yaml"

        if not weights_path.exists():
            logger.info("No trained_weights.yaml found, using default weights")
            self._trained_weights = TrainedWeightsConfig()
            return

        with open(weights_path, 'r') as f:
            raw = yaml.safe_load(f)

        if raw is None:
            self._trained_weights = TrainedWeightsConfig()
            return

        # Parse trained weights
        config = TrainedWeightsConfig(
            version=raw.get('version', '1.0.0'),
            training_date=raw.get('training_date', ''),
        )

        # Parse each strategy
        for strategy in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']:
            if strategy in raw:
                strat_data = raw[strategy]
                tw = TrainedWeights(
                    weights=strat_data.get('weights', {}),
                    roll_params=strat_data.get('roll_params', {}),
                    performance=strat_data.get('performance', {}),
                )
                setattr(config, strategy, tw)

        # VIX regime multipliers
        if 'vix_regime_multipliers' in raw:
            config.vix_regime_multipliers = raw['vix_regime_multipliers']

        # Gap Boost configuration
        if 'gap_boost' in raw:
            gb_data = raw['gap_boost']
            thresholds = gb_data.get('thresholds', {})

            # Build strategy_boosts dict from per-strategy configs
            strategy_boosts = {}
            for strategy in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']:
                if strategy in gb_data:
                    strategy_boosts[strategy] = gb_data[strategy]

            config.gap_boost = GapBoostConfig(
                enabled=gb_data.get('enabled', True),
                large_gap_pct=thresholds.get('large_gap_pct', 3.0),
                medium_gap_pct=thresholds.get('medium_gap_pct', 1.0),
                small_gap_pct=thresholds.get('small_gap_pct', 0.5),
                strategy_boosts=strategy_boosts,
            )

        self._trained_weights = config
        logger.info(f"Loaded trained weights v{config.version} from {config.training_date} (A/B variant: {ab_variant})")

    @property
    def trained_weights(self) -> TrainedWeightsConfig:
        """Gibt trainierte Gewichte zurück."""
        if self._trained_weights is None:
            self._load_trained_weights()
        return self._trained_weights

    @property
    def settings(self) -> Settings:
        """Gibt Settings zurück"""
        if not self._settings:
            self.load_all()
        return self._settings
    
    def get_strategy(self, name: str) -> Optional[Dict]:
        """Gibt Strategy-Profile zurück"""
        return self._strategies.get(name)
    
    def get_watchlist(self, name: str = "default_275") -> List[str]:
        """Gibt Watchlist zurück"""
        return self._watchlists.get(name, [])
    
    def get_sector(self, name: str) -> List[str]:
        """Gibt Symbole eines Sektors zurück"""
        normalized = name.lower().replace(' ', '_')
        return self._sectors.get(normalized, [])
    
    def get_all_sectors(self) -> Dict[str, List[str]]:
        """Gibt alle Sektoren zurück"""
        return self._sectors.copy()
    
    def apply_strategy(self, profile_name: str) -> Settings:
        """Wendet Strategy-Profile auf Settings an"""
        if not self._settings:
            self.load_all()
            
        profile = self._strategies.get(profile_name)
        if not profile:
            logger.warning(f"Strategy not found: {profile_name}")
            return self._settings
            
        if 'pullback_scoring' in profile:
            ps = profile['pullback_scoring']
            if 'min_score_for_candidate' in ps:
                self._settings.pullback_scoring.min_score_for_candidate = ps['min_score_for_candidate']
                    
        if 'filters' in profile:
            f = profile['filters']
            if 'earnings' in f:
                self._settings.filters.earnings_exclude_days = f['earnings'].get(
                    'exclude_days_before', 
                    self._settings.filters.earnings_exclude_days
                )
            if 'implied_volatility' in f:
                iv = f['implied_volatility']
                self._settings.filters.iv_rank_minimum = iv.get(
                    'iv_rank_minimum',
                    self._settings.filters.iv_rank_minimum
                )
                    
        if 'options_analysis' in profile:
            oa = profile['options_analysis']
            if 'short_put' in oa:
                sp = oa['short_put']
                self._settings.options.delta_target = sp.get(
                    'delta_target',
                    self._settings.options.delta_target
                )
                self._settings.options.delta_minimum = sp.get(
                    'delta_minimum',
                    self._settings.options.delta_minimum
                )
                self._settings.options.delta_maximum = sp.get(
                    'delta_maximum',
                    self._settings.options.delta_maximum
                )
            if 'long_put' in oa:
                lp = oa['long_put']
                self._settings.options.long_delta_target = lp.get(
                    'delta_target',
                    self._settings.options.long_delta_target
                )
                self._settings.options.long_delta_minimum = lp.get(
                    'delta_minimum',
                    self._settings.options.long_delta_minimum
                )
                self._settings.options.long_delta_maximum = lp.get(
                    'delta_maximum',
                    self._settings.options.long_delta_maximum
                )
        logger.info(f"Applied strategy: {profile_name}")
        return self._settings


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_config: Optional[ConfigLoader] = None

# A/B Test Weight Selection
# Set via environment variable or config
_ab_test_variant: str = os.environ.get("OPTIONPLAY_AB_VARIANT", "A")  # "A" = feature-based, "B" = outcome-based


def set_ab_test_variant(variant: str) -> None:
    """
    Set the A/B test variant for weight selection.

    Args:
        variant: "A" for feature-based v3.7, "B" for outcome-based v3.8
    """
    global _ab_test_variant
    if variant not in ("A", "B"):
        raise ValueError(f"Invalid variant '{variant}'. Must be 'A' or 'B'.")
    _ab_test_variant = variant
    logger.info(f"A/B Test variant set to: {variant}")


def get_ab_test_variant() -> str:
    """Get current A/B test variant."""
    return _ab_test_variant


def get_config(config_dir: Optional[str] = None) -> ConfigLoader:
    """
    Globaler Config-Zugriff (Singleton).

    .. deprecated:: 3.5.0
        Use ``ServiceContainer.config`` or pass config explicitly.
        Will be removed in v4.0.
    """
    from ..utils.deprecation import warn_singleton_usage
    warn_singleton_usage("get_config", "container.config")

    global _config
    if _config is None:
        _config = ConfigLoader(config_dir)
        _config.load_all()
    return _config


def reset_config() -> None:
    """Setzt den Singleton zurück."""
    global _config
    _config = None


def get_scan_config(
    config_dir: Optional[str] = None,
    override_min_score: Optional[float] = None,
    override_earnings_days: Optional[int] = None,
    override_iv_rank_min: Optional[float] = None,
    override_iv_rank_max: Optional[float] = None,
    enable_iv_filter: Optional[bool] = None,
    enable_fundamentals_filter: Optional[bool] = None,
) -> 'ScanConfig':
    """
    Erstellt ScanConfig aus YAML-Konfiguration.

    Importiert ScanConfig aus multi_strategy_scanner, um circular imports zu vermeiden.

    Args:
        config_dir: Optionaler Pfad zum Config-Verzeichnis
        override_min_score: Überschreibt min_score aus Config
        override_earnings_days: Überschreibt exclude_earnings_within_days aus Config
        override_iv_rank_min: Überschreibt iv_rank_minimum aus Config
        override_iv_rank_max: Überschreibt iv_rank_maximum aus Config
        enable_iv_filter: Überschreibt enable_iv_filter aus Config
        enable_fundamentals_filter: Überschreibt enable_fundamentals_filter aus Config

    Returns:
        ScanConfig Instanz für MultiStrategyScanner

    Usage:
        from src.config import get_scan_config
        from src.scanner import MultiStrategyScanner

        scan_config = get_scan_config()
        scanner = MultiStrategyScanner(scan_config)
    """
    # Import hier, um circular imports zu vermeiden
    from ..scanner.multi_strategy_scanner import ScanConfig

    cfg = get_config(config_dir)
    scanner_cfg = cfg.settings.scanner
    filters_cfg = cfg.settings.filters
    fundamentals_cfg = filters_cfg.fundamentals

    return ScanConfig(
        min_score=override_min_score if override_min_score is not None else scanner_cfg.min_score,
        min_actionable_score=scanner_cfg.min_actionable_score,
        exclude_earnings_within_days=(
            override_earnings_days if override_earnings_days is not None
            else scanner_cfg.exclude_earnings_within_days
        ),
        iv_rank_minimum=(
            override_iv_rank_min if override_iv_rank_min is not None
            else scanner_cfg.iv_rank_minimum
        ),
        iv_rank_maximum=(
            override_iv_rank_max if override_iv_rank_max is not None
            else scanner_cfg.iv_rank_maximum
        ),
        enable_iv_filter=(
            enable_iv_filter if enable_iv_filter is not None
            else scanner_cfg.enable_iv_filter
        ),
        max_results_per_symbol=scanner_cfg.max_results_per_symbol,
        max_total_results=scanner_cfg.max_total_results,
        max_concurrent=scanner_cfg.max_concurrent,
        min_data_points=scanner_cfg.min_data_points,
        enable_pullback=scanner_cfg.enable_pullback,
        enable_ath_breakout=scanner_cfg.enable_ath_breakout,
        enable_bounce=scanner_cfg.enable_bounce,
        enable_earnings_dip=scanner_cfg.enable_earnings_dip,

        # Fundamentals Filter (aus filters.fundamentals)
        enable_fundamentals_filter=(
            enable_fundamentals_filter if enable_fundamentals_filter is not None
            else fundamentals_cfg.enabled
        ),
        fundamentals_min_stability=fundamentals_cfg.min_stability_score,
        fundamentals_min_win_rate=fundamentals_cfg.min_historical_win_rate,
        fundamentals_max_volatility=fundamentals_cfg.max_historical_volatility,
        fundamentals_max_beta=fundamentals_cfg.max_beta,
        fundamentals_iv_rank_min=fundamentals_cfg.iv_rank_min,
        fundamentals_iv_rank_max=fundamentals_cfg.iv_rank_max,
        fundamentals_max_spy_correlation=fundamentals_cfg.max_spy_correlation,
        fundamentals_min_spy_correlation=fundamentals_cfg.min_spy_correlation,
        fundamentals_exclude_sectors=fundamentals_cfg.exclude_sectors,
        fundamentals_include_sectors=fundamentals_cfg.include_sectors,
        fundamentals_exclude_market_caps=fundamentals_cfg.exclude_market_caps,
        fundamentals_include_market_caps=fundamentals_cfg.include_market_caps,
        fundamentals_blacklist=fundamentals_cfg.blacklist_symbols,
        fundamentals_whitelist=fundamentals_cfg.whitelist_symbols,

        # Stability-First-Filter (Phase 6)
        enable_stability_first=scanner_cfg.enable_stability_first,
        stability_premium_threshold=scanner_cfg.stability_premium_threshold,
        stability_premium_min_score=scanner_cfg.stability_premium_min_score,
        stability_good_threshold=scanner_cfg.stability_good_threshold,
        stability_good_min_score=scanner_cfg.stability_good_min_score,
        stability_ok_threshold=scanner_cfg.stability_ok_threshold,
        stability_ok_min_score=scanner_cfg.stability_ok_min_score,
    )
