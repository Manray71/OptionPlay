# OptionPlay - Configuration Validation
# =====================================
# Validierungslogik für Konfigurationswerte
#
# Extrahiert aus config_loader.py im Rahmen des Recursive Logic Refactorings (Phase 2.2)

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .models import Settings


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__(f"Configuration validation failed: {'; '.join(errors)}")


def validate_settings(settings: "Settings") -> None:
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
        errors.append(f"RSI oversold ({rsi.oversold}) must be < neutral ({rsi.neutral})")
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
        errors.append(
            f"Long put delta_minimum ({opts.long_delta_minimum}) must be between -1.0 and 0"
        )
    if not (-1.0 <= opts.long_delta_maximum <= 0):
        errors.append(
            f"Long put delta_maximum ({opts.long_delta_maximum}) must be between -1.0 and 0"
        )

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
            errors.append(
                f"Fundamentals min_stability_score ({fund.min_stability_score}) must be 0-100"
            )
        if not (0 <= fund.min_historical_win_rate <= 100):
            errors.append(
                f"Fundamentals min_historical_win_rate ({fund.min_historical_win_rate}) must be 0-100"
            )
        if fund.max_historical_volatility <= 0:
            errors.append(
                f"Fundamentals max_historical_volatility ({fund.max_historical_volatility}) must be > 0"
            )
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
