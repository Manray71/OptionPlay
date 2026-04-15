# OptionPlay Formatters Package
# ===============================
"""
Output formatters for MCP server responses.

Usage:
    from src.formatters import formatters

    output = formatters.scan_result.format(result, recommendation, vix)
"""

from .output_formatters import (  # Main registry; Individual formatters
    BaseFormatter,
    EarningsFormatter,
    FormatterRegistry,
    HealthCheckData,
    HealthCheckFormatter,
    HistoricalDataFormatter,
    LegacyScanResultFormatter,
    OptionsChainFormatter,
    QuoteFormatter,
    ScanResultFormatter,
    StrategyRecommendationFormatter,
    SymbolAnalysisFormatter,
    formatters,
)
from .pick_formatter import (
    format_picks_markdown,
    format_picks_v2,
    format_single_pick,
    format_single_pick_v2,
)
from .portfolio_formatter import (
    PortfolioFormatter,
    portfolio_formatter,
)

__all__ = [
    "formatters",
    "FormatterRegistry",
    "BaseFormatter",
    "ScanResultFormatter",
    "LegacyScanResultFormatter",
    "QuoteFormatter",
    "OptionsChainFormatter",
    "EarningsFormatter",
    "StrategyRecommendationFormatter",
    "HealthCheckFormatter",
    "HealthCheckData",
    "HistoricalDataFormatter",
    "SymbolAnalysisFormatter",
    "PortfolioFormatter",
    "portfolio_formatter",
    # Pick Formatter
    "format_picks_markdown",
    "format_picks_v2",
    "format_single_pick",
    "format_single_pick_v2",
]
