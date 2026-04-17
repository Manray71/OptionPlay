# OptionPlay - Configuration Loader
# ==================================
# ConfigLoader Klasse für YAML-Parsing
#
# Extrahiert aus config_loader.py im Rahmen des Recursive Logic Refactorings (Phase 2.2)

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import (
    ApiConnectionConfig,
    CircuitBreakerConfig,
    ConnectionConfig,
    DataSourcesConfig,
    FibonacciConfig,
    FibonacciLevel,
    FilterConfig,
    FundamentalsFilterConfig,
    GapBoostConfig,
    LocalDatabaseConfig,
    MovingAverageConfig,
    OptionsConfig,
    PerformanceConfig,
    RSIConfig,
    ScannerConfig,
    Settings,
    SupportConfig,
    TrainedWeights,
    TrainedWeightsConfig,
    VolumeConfig,
    _get_default_blacklist,
)
from .validation import ConfigValidationError, validate_settings

try:
    from ..constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_IV_RANK_MAX,
        ENTRY_IV_RANK_MIN,
        ENTRY_PRICE_MAX,
        ENTRY_PRICE_MIN,
        ENTRY_VOLUME_MIN,
        SPREAD_DTE_MAX,
        SPREAD_DTE_MIN,
        SPREAD_DTE_TARGET,
        SPREAD_LONG_DELTA_MAX,
        SPREAD_LONG_DELTA_MIN,
        SPREAD_LONG_DELTA_TARGET,
        SPREAD_MIN_CREDIT_PCT,
        SPREAD_SHORT_DELTA_MAX,
        SPREAD_SHORT_DELTA_MIN,
        SPREAD_SHORT_DELTA_TARGET,
    )
except ImportError:
    from constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_IV_RANK_MAX,
        ENTRY_IV_RANK_MIN,
        ENTRY_PRICE_MAX,
        ENTRY_PRICE_MIN,
        ENTRY_VOLUME_MIN,
        SPREAD_DTE_MAX,
        SPREAD_DTE_MIN,
        SPREAD_DTE_TARGET,
        SPREAD_LONG_DELTA_MAX,
        SPREAD_LONG_DELTA_MIN,
        SPREAD_LONG_DELTA_TARGET,
        SPREAD_MIN_CREDIT_PCT,
        SPREAD_SHORT_DELTA_MAX,
        SPREAD_SHORT_DELTA_MIN,
        SPREAD_SHORT_DELTA_TARGET,
    )

logger = logging.getLogger(__name__)


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
        Path.cwd() / "config",
    ]

    for path in possible_paths:
        if path.exists():
            logger.debug(f"Found config directory: {path}")
            return path

    logger.warning("Config directory not found in standard locations")
    return Path("config")


class ConfigLoader:
    """Lädt und verwaltet Konfiguration."""

    def __init__(self, config_dir: Optional[str] = None, validate: bool = True) -> None:
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
        self._ab_test_variant: str = "A"  # Default variant

    def set_ab_test_variant(self, variant: str) -> None:
        """Set the A/B test variant for this loader instance."""
        if variant not in ("A", "B"):
            raise ValueError(f"Invalid variant '{variant}'. Must be 'A' or 'B'.")
        self._ab_test_variant = variant

    def load_all(self) -> Settings:
        """Lädt alle Konfigurationsdateien"""
        self._load_settings()
        self._load_strategies()
        self._load_watchlists()
        self._load_trained_weights()
        return self._settings

    def _load_settings(self) -> None:
        """Lädt settings.yaml"""
        settings_path = self.config_dir / "system.yaml"

        if not settings_path.exists():
            logger.warning(f"Settings not found: {settings_path}, using defaults")
            self._settings = Settings()
            return

        with open(settings_path, "r") as f:
            raw = yaml.safe_load(f)

        # Handle empty YAML files (yaml.safe_load returns None)
        if raw is None:
            raw = {}

        self._settings = self._parse_settings(raw)

        # Validate configuration values if enabled
        if self._validate:
            try:
                validate_settings(self._settings)
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
        if "data_sources" in raw:
            ds = raw["data_sources"]
            local_db = ds.get("local_database", {})
            settings.data_sources = DataSourcesConfig(
                local_database=LocalDatabaseConfig(
                    enabled=local_db.get("enabled", True),
                    db_path=local_db.get("db_path", "~/.optionplay/trades.db"),
                    max_data_age_days=local_db.get("max_data_age_days", 7),
                    min_data_points=local_db.get("min_data_points", 60),
                ),
                provider_priority=ds.get("provider_priority", ["local_db", "ibkr", "yahoo"]),
            )

        # Connection (IBKR)
        if "connection" in raw and "ibkr" in raw["connection"]:
            conn = raw["connection"]["ibkr"]
            settings.connection = ConnectionConfig(
                host=conn.get("host", "127.0.0.1"),
                port=conn.get("port", 7497),
                client_id=conn.get("client_id", 1),
                timeout=conn.get("timeout_seconds", 30),
                max_retries=conn.get("max_retries", 3),
            )

        # Pullback Scoring
        if "pullback_scoring" in raw:
            ps = raw["pullback_scoring"]

            if "rsi" in ps:
                rsi = ps["rsi"]
                settings.pullback_scoring.rsi = RSIConfig(
                    period=rsi.get("period", 14),
                    extreme_oversold=rsi.get("thresholds", {}).get("extreme_oversold", 30),
                    oversold=rsi.get("thresholds", {}).get("oversold", 40),
                    neutral=rsi.get("thresholds", {}).get("neutral", 50),
                    weight_extreme=rsi.get("weights", {}).get("extreme_oversold", 3),
                    weight_oversold=rsi.get("weights", {}).get("oversold", 2),
                    weight_neutral=rsi.get("weights", {}).get("neutral", 1),
                )

            if "support" in ps:
                sup = ps["support"]
                settings.pullback_scoring.support = SupportConfig(
                    lookback_days=sup.get("lookback_days", 60),
                    proximity_percent=sup.get("proximity_percent", 3.0),
                    proximity_percent_wide=sup.get("proximity_percent_wide", 5.0),
                    weight_close=sup.get("weights", {}).get("close_to_support", 2),
                    weight_near=sup.get("weights", {}).get("near_support", 1),
                )

            if "fibonacci" in ps:
                fib = ps["fibonacci"]
                levels = []
                for lvl in fib.get("levels", []):
                    levels.append(
                        FibonacciLevel(
                            level=lvl["level"], tolerance=lvl["tolerance"], points=lvl["points"]
                        )
                    )
                settings.pullback_scoring.fibonacci = FibonacciConfig(
                    lookback_days=fib.get("lookback_days", 90),
                    levels=levels if levels else settings.pullback_scoring.fibonacci.levels,
                )

            if "moving_averages" in ps:
                ma = ps["moving_averages"]
                settings.pullback_scoring.moving_averages = MovingAverageConfig(
                    short_period=ma.get("short_period", 20), long_period=ma.get("long_period", 200)
                )

            if "volume" in ps:
                vol = ps["volume"]
                settings.pullback_scoring.volume = VolumeConfig(
                    average_period=vol.get("average_period", 20),
                    spike_multiplier=vol.get("spike_multiplier", 1.5),
                )

            if "total" in ps:
                settings.pullback_scoring.max_score = ps["total"].get("max_score", 10)
                settings.pullback_scoring.min_score_for_candidate = ps["total"].get(
                    "min_score_for_candidate", 5
                )

        # Filters
        if "filters" in raw:
            f = raw["filters"]

            # Parse Fundamentals Filter
            fundamentals_config = FundamentalsFilterConfig()
            if "fundamentals" in f:
                fund = f["fundamentals"]
                # None-sichere Getter: `or []` für Listen, `or default` für optionale Werte
                # Verhindert Fehler wenn YAML `null` enthält
                fundamentals_config = FundamentalsFilterConfig(
                    enabled=fund.get("enabled", True),
                    min_stability_score=fund.get("min_stability_score") or 50.0,
                    warn_below_stability=fund.get("warn_below_stability") or 60.0,
                    boost_above_stability=fund.get("boost_above_stability") or 70.0,
                    min_historical_win_rate=fund.get("min_historical_win_rate") or 70.0,
                    max_historical_volatility=fund.get("max_historical_volatility") or 70.0,
                    max_beta=fund.get("max_beta") or 2.0,
                    iv_rank_min=fund.get("iv_rank_min") or 20.0,
                    iv_rank_max=fund.get("iv_rank_max") or ENTRY_IV_RANK_MAX,
                    use_iv_percentile=fund.get("use_iv_percentile", False),
                    max_spy_correlation=fund.get("max_spy_correlation"),  # None ist hier erlaubt
                    min_spy_correlation=fund.get("min_spy_correlation"),  # None ist hier erlaubt
                    exclude_sectors=fund.get("exclude_sectors") or [],
                    include_sectors=fund.get("include_sectors") or [],
                    exclude_market_caps=fund.get("exclude_market_caps") or [],
                    include_market_caps=fund.get("include_market_caps") or [],
                    blacklist_symbols=fund.get("blacklist_symbols") or _get_default_blacklist(),
                    whitelist_symbols=fund.get("whitelist_symbols") or [],
                )

            settings.filters = FilterConfig(
                earnings_exclude_days=f.get("earnings", {}).get(
                    "exclude_days_before", ENTRY_EARNINGS_MIN_DAYS
                ),
                price_minimum=f.get("price", {}).get("minimum", ENTRY_PRICE_MIN),
                price_maximum=f.get("price", {}).get("maximum", ENTRY_PRICE_MAX),
                volume_minimum=f.get("volume", {}).get("minimum_daily", ENTRY_VOLUME_MIN),
                iv_rank_minimum=f.get("implied_volatility", {}).get(
                    "iv_rank_minimum", ENTRY_IV_RANK_MIN
                ),
                iv_rank_maximum=f.get("implied_volatility", {}).get(
                    "iv_rank_maximum", ENTRY_IV_RANK_MAX
                ),
                fundamentals=fundamentals_config,
            )

        # Options Analysis
        if "options_analysis" in raw:
            oa = raw["options_analysis"]
            settings.options = OptionsConfig(
                dte_minimum=oa.get("expiration", {}).get("dte_minimum", SPREAD_DTE_MIN),
                dte_maximum=oa.get("expiration", {}).get("dte_maximum", SPREAD_DTE_MAX),
                dte_target=oa.get("expiration", {}).get("dte_target", SPREAD_DTE_TARGET),
                # Short Put Delta ±0.20 (PLAYBOOK §2: ±0.03)
                delta_minimum=oa.get("short_put", {}).get("delta_minimum", SPREAD_SHORT_DELTA_MIN),
                delta_maximum=oa.get("short_put", {}).get("delta_maximum", SPREAD_SHORT_DELTA_MAX),
                delta_target=oa.get("short_put", {}).get("delta_target", SPREAD_SHORT_DELTA_TARGET),
                # Long Put Delta (PLAYBOOK §2: ±0.02)
                long_delta_minimum=oa.get("long_put", {}).get(
                    "delta_minimum", SPREAD_LONG_DELTA_MIN
                ),
                long_delta_maximum=oa.get("long_put", {}).get(
                    "delta_maximum", SPREAD_LONG_DELTA_MAX
                ),
                long_delta_target=oa.get("long_put", {}).get(
                    "delta_target", SPREAD_LONG_DELTA_TARGET
                ),
                # Spread-Breite: dynamisch aus Delta (PLAYBOOK §2)
                min_credit_pct=oa.get("premium", {}).get(
                    "minimum_credit_percent", SPREAD_MIN_CREDIT_PCT
                ),
                min_open_interest=oa.get("liquidity", {}).get("min_open_interest", 100),
            )
            logger.info(
                f"Delta config loaded — Short: target={settings.options.delta_target}, "
                f"range=[{settings.options.delta_minimum}, {settings.options.delta_maximum}] | "
                f"Long: target={settings.options.long_delta_target}, "
                f"range=[{settings.options.long_delta_minimum}, {settings.options.long_delta_maximum}]"
            )

        if "logging" in raw:
            settings.log_level = raw["logging"].get("level", "INFO")
            settings.log_api_calls = raw["logging"].get("log_api_calls", True)

        # Scanner Config
        # Kombiniert Werte aus verschiedenen Sections
        scanner_raw = raw.get("scanner", {})
        settings.scanner = ScannerConfig(
            min_score=settings.pullback_scoring.min_score_for_candidate,
            min_actionable_score=settings.pullback_scoring.min_score_for_candidate + 1,
            exclude_earnings_within_days=settings.filters.earnings_exclude_days,
            auto_earnings_prefilter=scanner_raw.get("auto_earnings_prefilter", True),
            earnings_prefilter_min_days=scanner_raw.get(
                "earnings_prefilter_min_days", ENTRY_EARNINGS_MIN_DAYS
            ),
            earnings_allow_bmo_same_day=scanner_raw.get("earnings_allow_bmo_same_day", False),
            iv_rank_minimum=settings.filters.iv_rank_minimum,
            iv_rank_maximum=settings.filters.iv_rank_maximum,
            enable_iv_filter=scanner_raw.get("enable_iv_filter", True),
            max_results_per_symbol=scanner_raw.get("max_results_per_symbol", 3),
            max_total_results=scanner_raw.get("max_total_results", 50),
            max_concurrent=raw.get("performance", {}).get("max_concurrent_requests", 10),
            min_data_points=scanner_raw.get("min_data_points", 60),
            enable_pullback=scanner_raw.get("enable_pullback", True),
            enable_bounce=scanner_raw.get("enable_bounce", True),
            # Stability-First-Filter (simplified 2-tier)
            enable_stability_first=scanner_raw.get("enable_stability_first", True),
            stability_qualified_threshold=scanner_raw.get("stability_qualified_threshold", 60.0),
            stability_qualified_min_score=scanner_raw.get("stability_qualified_min_score", 3.5),
        )

        # Performance Config
        if "performance" in raw:
            perf = raw["performance"]
            settings.performance = PerformanceConfig(
                request_timeout=perf.get("request_timeout", 30),
                batch_delay=perf.get("batch_delay", 1.0),
                max_concurrent_requests=perf.get("max_concurrent_requests", 5),
                cache_ttl_seconds=perf.get("cache_ttl_seconds", 900),  # 15 min default
                cache_ttl_intraday=perf.get("cache_ttl_intraday", 300),  # 5 min
                cache_ttl_vix=perf.get("cache_ttl_vix", 300),  # 5 min
                historical_days=perf.get("historical_days", 260),
                cache_max_entries=perf.get("cache_max_entries", 500),
            )

        # API Connection Config
        if "api_connection" in raw:
            api_conn = raw["api_connection"]
            settings.api_connection = ApiConnectionConfig(
                max_retries=api_conn.get("max_retries", 3),
                retry_base_delay=api_conn.get("retry_base_delay", 2),
                vix_cache_seconds=api_conn.get("vix_cache_seconds", 300),
                yahoo_timeout=api_conn.get("yahoo_timeout", 10),
            )

        # Circuit Breaker Config
        if "circuit_breaker" in raw:
            cb = raw["circuit_breaker"]
            settings.circuit_breaker = CircuitBreakerConfig(
                failure_threshold=cb.get("failure_threshold", 5),
                recovery_timeout=cb.get("recovery_timeout", 60.0),
                half_open_max_calls=cb.get("half_open_max_calls", 3),
                success_threshold=cb.get("success_threshold", 2),
            )

        return settings

    def _load_strategies(self) -> None:
        """Lädt strategies.yaml"""
        strategies_path = self.config_dir / "trading.yaml"

        if not strategies_path.exists():
            logger.warning(f"Strategies not found: {strategies_path}")
            return

        with open(strategies_path, "r") as f:
            raw = yaml.safe_load(f)

        self._strategies = raw.get("profiles", {})
        logger.info(f"Loaded {len(self._strategies)} strategy profiles")

    def _load_watchlists(self) -> None:
        """Lädt watchlists.yaml"""
        watchlists_path = self.config_dir / "watchlists.yaml"

        if not watchlists_path.exists():
            logger.warning(f"Watchlists not found: {watchlists_path}")
            return

        with open(watchlists_path, "r") as f:
            raw = yaml.safe_load(f)

        for list_name, list_data in raw.get("watchlists", {}).items():
            symbols = []

            if "sectors" in list_data:
                for sector_name, sector_data in list_data["sectors"].items():
                    sector_symbols = sector_data.get("symbols", [])
                    symbols.extend(sector_symbols)
                    self._sectors[sector_name] = sector_symbols
            elif "symbols" in list_data:
                symbols = list_data["symbols"]

            self._watchlists[list_name] = symbols

        logger.info(f"Loaded {len(self._watchlists)} watchlists, {len(self._sectors)} sectors")

    def _load_trained_weights(self, variant: Optional[str] = None) -> None:
        """
        Lädt trained_weights.yaml mit ML-trainierten Gewichten.

        Args:
            variant: Optional A/B test variant override. If None, uses instance setting.
                     "A" = feature-based (trained_weights.yaml)
                     "B" = outcome-based (trained_weights_outcome_based.yaml)
        """
        # Determine which weights file to load
        ab_variant = variant or self._ab_test_variant

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

        with open(weights_path, "r") as f:
            raw = yaml.safe_load(f)

        if raw is None:
            self._trained_weights = TrainedWeightsConfig()
            return

        # Parse trained weights
        config = TrainedWeightsConfig(
            version=raw.get("version", "1.0.0"),
            training_date=raw.get("training_date", ""),
        )

        # Parse each strategy
        for strategy in [
            "pullback",
            "bounce",
        ]:
            if strategy in raw:
                strat_data = raw[strategy]
                tw = TrainedWeights(
                    weights=strat_data.get("weights", {}),
                    roll_params=strat_data.get("roll_params", {}),
                    performance=strat_data.get("performance", {}),
                )
                setattr(config, strategy, tw)

        # VIX regime multipliers
        if "vix_regime_multipliers" in raw:
            config.vix_regime_multipliers = raw["vix_regime_multipliers"]

        # Gap Boost configuration
        if "gap_boost" in raw:
            gb_data = raw["gap_boost"]
            thresholds = gb_data.get("thresholds", {})

            # Build strategy_boosts dict from per-strategy configs
            strategy_boosts = {}
            for strategy in [
                "pullback",
                "bounce",
            ]:
                if strategy in gb_data:
                    strategy_boosts[strategy] = gb_data[strategy]

            config.gap_boost = GapBoostConfig(
                enabled=gb_data.get("enabled", True),
                large_gap_pct=thresholds.get("large_gap_pct", 3.0),
                medium_gap_pct=thresholds.get("medium_gap_pct", 1.0),
                small_gap_pct=thresholds.get("small_gap_pct", 0.5),
                strategy_boosts=strategy_boosts,
            )

        self._trained_weights = config
        logger.info(
            f"Loaded trained weights v{config.version} from {config.training_date} (A/B variant: {ab_variant})"
        )

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
        normalized = name.lower().replace(" ", "_")
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

        if "pullback_scoring" in profile:
            ps = profile["pullback_scoring"]
            if "min_score_for_candidate" in ps:
                self._settings.pullback_scoring.min_score_for_candidate = ps[
                    "min_score_for_candidate"
                ]

        if "filters" in profile:
            f = profile["filters"]
            if "earnings" in f:
                self._settings.filters.earnings_exclude_days = f["earnings"].get(
                    "exclude_days_before", self._settings.filters.earnings_exclude_days
                )
            if "implied_volatility" in f:
                iv = f["implied_volatility"]
                self._settings.filters.iv_rank_minimum = iv.get(
                    "iv_rank_minimum", self._settings.filters.iv_rank_minimum
                )

        if "options_analysis" in profile:
            oa = profile["options_analysis"]
            if "short_put" in oa:
                sp = oa["short_put"]
                self._settings.options.delta_target = sp.get(
                    "delta_target", self._settings.options.delta_target
                )
                self._settings.options.delta_minimum = sp.get(
                    "delta_minimum", self._settings.options.delta_minimum
                )
                self._settings.options.delta_maximum = sp.get(
                    "delta_maximum", self._settings.options.delta_maximum
                )
            if "long_put" in oa:
                lp = oa["long_put"]
                self._settings.options.long_delta_target = lp.get(
                    "delta_target", self._settings.options.long_delta_target
                )
                self._settings.options.long_delta_minimum = lp.get(
                    "delta_minimum", self._settings.options.long_delta_minimum
                )
                self._settings.options.long_delta_maximum = lp.get(
                    "delta_maximum", self._settings.options.long_delta_maximum
                )
        logger.info(f"Applied strategy: {profile_name}")
        return self._settings
