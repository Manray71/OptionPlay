# OptionPlay - Configuration Loader
# ===================================
# Lädt und validiert alle Konfigurationsdateien

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging
import os

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
    sandbox: bool = True
    base_url: str = "https://sandbox.tradier.com/v1"
    api_key: str = ""
    
    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.environ.get("TRADIER_API_KEY", "")


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


@dataclass
class PullbackScoringConfig:
    """Gesamte Pullback Scoring Konfiguration"""
    rsi: RSIConfig = field(default_factory=RSIConfig)
    support: SupportConfig = field(default_factory=SupportConfig)
    fibonacci: FibonacciConfig = field(default_factory=FibonacciConfig)
    moving_averages: MovingAverageConfig = field(default_factory=MovingAverageConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    max_score: int = 10
    min_score_for_candidate: int = 5


@dataclass
class FilterConfig:
    """Filter Einstellungen"""
    earnings_exclude_days: int = 60
    price_minimum: float = 20.0
    price_maximum: float = 500.0
    volume_minimum: int = 500000
    iv_rank_minimum: float = 30.0
    iv_rank_maximum: float = 80.0


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


@dataclass
class OptionsConfig:
    """Options Analyse Parameter"""
    dte_minimum: int = 30
    dte_maximum: int = 60
    dte_target: int = 45
    delta_minimum: float = -0.35
    delta_maximum: float = -0.20
    delta_target: float = -0.30
    default_spread_width: float = 5.0
    min_credit_pct: float = 20.0
    min_open_interest: int = 100
    
    # Aliases for compatibility
    @property
    def spread_width(self) -> float:
        return self.default_spread_width
    
    @property
    def delta_min(self) -> float:
        return self.delta_minimum
    
    @property
    def delta_max(self) -> float:
        return self.delta_maximum


@dataclass
class PerformanceConfig:
    """Performance und Cache Parameter"""
    request_timeout: int = 30
    batch_delay: float = 1.0
    max_concurrent_requests: int = 5
    cache_ttl_seconds: int = 300
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
class Settings:
    """Haupt-Konfigurationsklasse"""
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

class ConfigLoader:
    """Lädt und verwaltet Konfiguration."""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = find_config_dir(config_dir)
        self._settings: Optional[Settings] = None
        self._strategies: Dict[str, Any] = {}
        self._watchlists: Dict[str, List[str]] = {}
        self._sectors: Dict[str, List[str]] = {}
        
    def load_all(self) -> Settings:
        """Lädt alle Konfigurationsdateien"""
        self._load_settings()
        self._load_strategies()
        self._load_watchlists()
        return self._settings
    
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
        logger.info(f"Loaded settings from {settings_path}")
        
    def _parse_settings(self, raw: Dict) -> Settings:
        """Parst Raw-YAML in Settings-Objekt"""
        settings = Settings()
        
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
            
        # Tradier
        if 'connection' in raw and 'tradier' in raw['connection']:
            trad = raw['connection']['tradier']
            settings.tradier = TradierConfig(
                enabled=trad.get('enabled', True),
                sandbox=trad.get('sandbox', True),
                base_url=trad.get('base_url', 'https://sandbox.tradier.com/v1'),
                api_key=trad.get('api_key', '')
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
            settings.filters = FilterConfig(
                earnings_exclude_days=f.get('earnings', {}).get('exclude_days_before', 60),
                price_minimum=f.get('price', {}).get('minimum', 20.0),
                price_maximum=f.get('price', {}).get('maximum', 500.0),
                volume_minimum=f.get('volume', {}).get('minimum_daily', 500000),
                iv_rank_minimum=f.get('implied_volatility', {}).get('iv_rank_minimum', 30),
                iv_rank_maximum=f.get('implied_volatility', {}).get('iv_rank_maximum', 80)
            )
            
        # Options Analysis
        if 'options_analysis' in raw:
            oa = raw['options_analysis']
            settings.options = OptionsConfig(
                dte_minimum=oa.get('expiration', {}).get('dte_minimum', 30),
                dte_maximum=oa.get('expiration', {}).get('dte_maximum', 60),
                dte_target=oa.get('expiration', {}).get('dte_target', 45),
                delta_minimum=oa.get('short_put', {}).get('delta_minimum', -0.35),
                delta_maximum=oa.get('short_put', {}).get('delta_maximum', -0.20),
                delta_target=oa.get('short_put', {}).get('delta_target', -0.30),
                default_spread_width=oa.get('spread', {}).get('preferred_width', 5.0),
                min_credit_pct=oa.get('premium', {}).get('minimum_credit_percent', 20),
                min_open_interest=oa.get('liquidity', {}).get('min_open_interest', 100)
            )
            
        if 'logging' in raw:
            settings.log_level = raw['logging'].get('level', 'INFO')
            settings.log_api_calls = raw['logging'].get('log_api_calls', True)
        
        # Scanner Config
        # Kombiniert Werte aus verschiedenen Sections
        settings.scanner = ScannerConfig(
            min_score=settings.pullback_scoring.min_score_for_candidate,
            min_actionable_score=settings.pullback_scoring.min_score_for_candidate + 1,
            exclude_earnings_within_days=settings.filters.earnings_exclude_days,
            iv_rank_minimum=settings.filters.iv_rank_minimum,
            iv_rank_maximum=settings.filters.iv_rank_maximum,
            enable_iv_filter=raw.get('scanner', {}).get('enable_iv_filter', True),
            max_results_per_symbol=raw.get('scanner', {}).get('max_results_per_symbol', 3),
            max_total_results=raw.get('scanner', {}).get('max_total_results', 50),
            max_concurrent=raw.get('performance', {}).get('max_concurrent_requests', 10),
            min_data_points=raw.get('scanner', {}).get('min_data_points', 60),
            enable_pullback=raw.get('scanner', {}).get('enable_pullback', True),
            enable_ath_breakout=raw.get('scanner', {}).get('enable_ath_breakout', True),
            enable_bounce=raw.get('scanner', {}).get('enable_bounce', True),
            enable_earnings_dip=raw.get('scanner', {}).get('enable_earnings_dip', True),
        )
        
        # Performance Config
        if 'performance' in raw:
            perf = raw['performance']
            settings.performance = PerformanceConfig(
                request_timeout=perf.get('request_timeout', 30),
                batch_delay=perf.get('batch_delay', 1.0),
                max_concurrent_requests=perf.get('max_concurrent_requests', 5),
                cache_ttl_seconds=perf.get('cache_ttl_seconds', 300),
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
            if 'spread' in oa:
                self._settings.options.default_spread_width = oa['spread'].get(
                    'preferred_width',
                    self._settings.options.default_spread_width
                )
                
        logger.info(f"Applied strategy: {profile_name}")
        return self._settings


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_config: Optional[ConfigLoader] = None


def get_config(config_dir: Optional[str] = None) -> ConfigLoader:
    """Globaler Config-Zugriff (Singleton)."""
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
    )
