# OptionPlay Formatters Package
# ===============================
"""
Output formatters for MCP server responses.

Usage:
    from src.formatters import formatters
    
    output = formatters.scan_result.format(result, recommendation, vix)
"""

from .output_formatters import (
    # Main registry
    formatters,
    FormatterRegistry,

    # Individual formatters
    BaseFormatter,
    ScanResultFormatter,
    QuoteFormatter,
    OptionsChainFormatter,
    EarningsFormatter,
    StrategyRecommendationFormatter,
    HealthCheckFormatter,
    HealthCheckData,
    HistoricalDataFormatter,
    SymbolAnalysisFormatter,
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
]
