"""
OptionPlay MCP Tool Registry v4.1.0
===================================

Zentrales Registry für alle MCP Tools mit Handler-Definitionen.

Stats (2026-02-09):
- 54 Tools + 56 Aliases = 110 MCP Endpoints
- 80.19% Test Coverage
- ML-Training: Walk-Forward (2026-02-09) + Stability Thresholds

Pattern:
    @tool_registry.register(
        name="optionplay_xxx",
        description="...",
        input_schema={...},
        aliases=["xxx"],
    )
    async def handle_xxx(server, arguments):
        return await server.method_name(...)

Alle Tools sind hier definiert mit:
- Vollständigem Namen (optionplay_xxx)
- Kurz-Alias (xxx)
- JSON-Schema für Eingabe
- Handler-Funktion
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from mcp.types import Tool

try:
    from .constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        SPREAD_DTE_MAX,
        SPREAD_DTE_MIN,
        SPREAD_DTE_TARGET,
    )
except ImportError:
    from constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        SPREAD_DTE_MAX,
        SPREAD_DTE_MIN,
        SPREAD_DTE_TARGET,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# TYPE ALIASES
# =============================================================================

#: JSON Schema definition for MCP tool input validation.
JsonSchema = Dict[str, Any]

#: MCP tool arguments dict received from JSON-RPC protocol.
ToolArguments = Dict[str, Any]

#: Handler function signature: (server, arguments) -> str (sync or async).
ToolHandlerAsync = Callable[[Any, ToolArguments], Awaitable[str]]
ToolHandlerSync = Callable[[Any, ToolArguments], str]
ToolHandler = Union[ToolHandlerAsync, ToolHandlerSync]


# =============================================================================
# TOOL REGISTRY CLASS
# =============================================================================


@dataclass
class ToolDefinition:
    """Vollständige Tool-Definition mit Handler."""

    name: str
    description: str
    input_schema: JsonSchema
    handler: ToolHandler
    is_async: bool = True
    aliases: List[str] = field(default_factory=list)


class ToolRegistry:
    """
    Registry für MCP Tools.

    Verbindet Tool-Definitionen mit Handlern für sauberen Dispatch.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._aliases: Dict[str, str] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: JsonSchema,
        aliases: Optional[List[str]] = None,
        is_async: bool = True,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator zum Registrieren eines Tool-Handlers."""

        def decorator(func: ToolHandler) -> ToolHandler:
            tool = ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=func,
                is_async=is_async,
                aliases=aliases or [],
            )
            self._tools[name] = tool

            for alias in aliases or []:
                self._aliases[alias] = name

            return func

        return decorator

    def resolve_alias(self, name: str) -> str:
        """Löst einen Alias zum vollen Tool-Namen auf."""
        return self._aliases.get(name, name)

    def has_tool(self, name: str) -> bool:
        """Prüft ob ein Tool (oder Alias) registriert ist."""
        resolved = self.resolve_alias(name)
        return resolved in self._tools

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Holt eine Tool-Definition."""
        resolved = self.resolve_alias(name)
        return self._tools.get(resolved)

    async def dispatch(
        self,
        name: str,
        server: Any,
        arguments: ToolArguments,
    ) -> str:
        """Dispatcht einen Tool-Aufruf zum registrierten Handler."""
        resolved = self.resolve_alias(name)
        tool = self._tools.get(resolved)

        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        if tool.is_async:
            return await tool.handler(server, arguments)
        else:
            return tool.handler(server, arguments)

    def list_tools(self) -> List[Tool]:
        """Gibt alle Tools als MCP Tool-Objekte zurück (inkl. Aliases)."""
        tools = []

        for tool_def in self._tools.values():
            # Haupt-Tool
            tools.append(
                Tool(
                    name=tool_def.name,
                    description=tool_def.description,
                    inputSchema=tool_def.input_schema,
                )
            )

            # Alias-Tools
            for alias in tool_def.aliases:
                tools.append(
                    Tool(
                        name=alias,
                        description=f"[Alias for {tool_def.name}] {tool_def.description}",
                        inputSchema=tool_def.input_schema,
                    )
                )

        return tools

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def alias_count(self) -> int:
        return len(self._aliases)


# =============================================================================
# GLOBAL REGISTRY INSTANCE
# =============================================================================

tool_registry = ToolRegistry()


# =============================================================================
# COMMON SCHEMAS
# =============================================================================

EMPTY_SCHEMA = {"type": "object", "properties": {}}

SYMBOL_SCHEMA = {
    "type": "object",
    "properties": {"symbol": {"type": "string", "description": "Stock ticker symbol"}},
    "required": ["symbol"],
}

SYMBOLS_SCHEMA = {
    "type": "object",
    "properties": {
        "symbols": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of ticker symbols",
        }
    },
}

SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "symbols": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional specific symbols",
        },
        "max_results": {"type": "number", "description": "Maximum candidates (default: 10)"},
        "min_score": {"type": "number", "description": "Minimum score threshold"},
        "list_type": {
            "type": "string",
            "enum": ["stable", "risk", "all"],
            "description": "Which watchlist to scan: 'stable' (default, Stability>=60), 'risk' (Stability<60), or 'all'",
        },
    },
}


# =============================================================================
# VIX & STRATEGY TOOLS (6)
# =============================================================================


@tool_registry.register(
    name="optionplay_vix",
    description="Get current VIX level and strategy recommendation based on market volatility.",
    input_schema=EMPTY_SCHEMA,
    aliases=["vix"],
)
async def handle_vix(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.vix.get_strategy_recommendation()


@tool_registry.register(
    name="optionplay_regime_status",
    description="Get current VIX regime status with WF-trained model recommendations. Shows regime, trading parameters, enabled strategies, and stability thresholds.",
    input_schema=EMPTY_SCHEMA,
    aliases=["regime"],
)
async def handle_regime_status(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.vix.get_regime_status()


@tool_registry.register(
    name="optionplay_strategy_for_stock",
    description="Get strategy recommendation based on stock price and VIX.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["strategy_stock"],
)
async def handle_strategy_for_stock(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.vix.get_strategy_for_stock(arguments["symbol"])


@tool_registry.register(
    name="optionplay_events",
    description="Get upcoming market events (FOMC, OPEX, CPI, NFP). Helps plan around macro events.",
    input_schema={
        "type": "object",
        "properties": {
            "days": {"type": "number", "description": "Days to look ahead (default: 30)"}
        },
    },
    aliases=["events"],
)
async def handle_events(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.vix.get_event_calendar(days=arguments.get("days", 30))


@tool_registry.register(
    name="optionplay_health",
    description="Check server health and configuration status.",
    input_schema=EMPTY_SCHEMA,
    aliases=["health"],
)
async def handle_health(server: Any, arguments: ToolArguments) -> str:
    return await server.health_check()


# =============================================================================
# SCAN TOOLS (7)
# =============================================================================


@tool_registry.register(
    name="optionplay_scan",
    description="Scan watchlist for pullback candidates suitable for Bull-Put-Spreads. Uses VIX-based strategy selection.",
    input_schema=SCAN_SCHEMA,
    aliases=["scan"],
)
async def handle_scan(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.scan_with_strategy(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 3.5),
    )


@tool_registry.register(
    name="optionplay_scan_bounce",
    description="Scan for Support Bounce candidates - stocks bouncing off established support levels.",
    input_schema=SCAN_SCHEMA,
    aliases=["bounce"],
)
async def handle_scan_bounce(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.scan_bounce(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 5.0),
    )


@tool_registry.register(
    name="optionplay_scan_breakout",
    description="Scan for ATH Breakout candidates - stocks breaking out to new all-time highs with volume confirmation.",
    input_schema=SCAN_SCHEMA,
    aliases=["breakout"],
)
async def handle_scan_breakout(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.scan_ath_breakout(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 6.0),
    )


@tool_registry.register(
    name="optionplay_scan_earnings_dip",
    description="Scan for Earnings Dip Buy candidates - quality stocks that dropped 5-15% after earnings (potential overreaction).",
    input_schema=SCAN_SCHEMA,
    aliases=["dip"],
)
async def handle_scan_earnings_dip(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.scan_earnings_dip(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 5.0),
    )


@tool_registry.register(
    name="optionplay_scan_trend",
    description="Scan for Trend Continuation candidates - stocks in stable uptrends with perfect SMA alignment, ideal for Bull-Put-Spreads.",
    input_schema=SCAN_SCHEMA,
    aliases=["trend"],
)
async def handle_scan_trend(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.scan_trend_continuation(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 5.0),
    )


@tool_registry.register(
    name="optionplay_scan_multi",
    description="Multi-Strategy Scan - runs all strategies and returns the best signal per symbol.",
    input_schema=SCAN_SCHEMA,
    aliases=["multi"],
)
async def handle_scan_multi(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.scan_multi_strategy(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 20),
        min_score=arguments.get("min_score", 3.5),
        list_type=arguments.get("list_type", "stable"),
    )


@tool_registry.register(
    name="optionplay_daily_picks",
    description="Generate Top 5 daily trading recommendations. Applies PLAYBOOK filter order: Blacklist, Stability, Earnings, VIX regime, then scoring. Returns ranked picks with strikes, credit targets, and stop-loss levels. IMPORTANT: The output is pre-formatted Markdown with tables. Display it EXACTLY as returned - do not reformat or summarize. Always preserve the Markdown table including the Speed column.",
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional specific symbols (default: watchlist)",
            },
            "max_picks": {"type": "number", "description": "Maximum recommendations (default: 5)"},
            "min_score": {
                "type": "number",
                "description": "Minimum signal score for ranking (default: 3.5)",
            },
            "min_stability": {
                "type": "number",
                "description": "Minimum stability score 0-100 (default: 70)",
            },
            "include_strikes": {
                "type": "boolean",
                "description": "Include strike recommendations (default: true)",
            },
        },
    },
    aliases=["daily", "picks", "recommendations"],
)
async def handle_daily_picks(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.daily_picks(
        symbols=arguments.get("symbols"),
        max_picks=arguments.get("max_picks", 5),
        min_score=arguments.get("min_score", 3.5),
        min_stability=arguments.get("min_stability", 70.0),
        include_strikes=arguments.get("include_strikes", True),
    )


@tool_registry.register(
    name="optionplay_earnings_prefilter",
    description="Pre-filter watchlist by earnings dates. Returns only symbols with earnings > X days away. Should be FIRST step before any scan.",
    input_schema={
        "type": "object",
        "properties": {
            "min_days": {"type": "number", "description": "Minimum days to earnings (default: 45)"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "show_excluded": {
                "type": "boolean",
                "description": "Show excluded symbols (default: false)",
            },
        },
    },
    aliases=["prefilter"],
)
async def handle_earnings_prefilter(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.scan.earnings_prefilter(
        min_days=arguments.get("min_days", ENTRY_EARNINGS_MIN_DAYS),
        symbols=arguments.get("symbols"),
        show_excluded=arguments.get("show_excluded", False),
    )


# =============================================================================
# QUOTE & DATA TOOLS (7)
# =============================================================================


@tool_registry.register(
    name="optionplay_quote",
    description="Get current stock quote with bid/ask/volume.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["quote"],
)
async def handle_quote(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.get_quote(arguments["symbol"])


@tool_registry.register(
    name="optionplay_options",
    description="Get options chain for a symbol with Greeks and IV.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "dte_min": {"type": "number", "description": "Min DTE (default: 60)"},
            "dte_max": {"type": "number", "description": "Max DTE (default: 90)"},
            "right": {"type": "string", "description": "P for puts, C for calls (default: P)"},
        },
        "required": ["symbol"],
    },
    aliases=["options"],
)
async def handle_options(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.get_options_chain(
        symbol=arguments["symbol"],
        dte_min=arguments.get("dte_min", SPREAD_DTE_MIN),
        dte_max=arguments.get("dte_max", SPREAD_DTE_MAX),
        right=arguments.get("right", "P"),
    )


@tool_registry.register(
    name="optionplay_earnings",
    description="Check earnings date for a symbol. Returns safety status for trading.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "min_days": {"type": "number", "description": "Min days buffer (default: 45)"},
        },
        "required": ["symbol"],
    },
    aliases=["earnings"],
)
async def handle_earnings(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.get_earnings_aggregated(
        arguments["symbol"],
        arguments.get("min_days", ENTRY_EARNINGS_MIN_DAYS),
    )


@tool_registry.register(
    name="optionplay_historical",
    description="Get historical price data for a symbol. Shows recent price action.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "days": {"type": "number", "description": "Days of history (default: 30)"},
        },
        "required": ["symbol"],
    },
    aliases=["historical"],
)
async def handle_historical(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.get_historical_data(
        symbol=arguments["symbol"],
        days=arguments.get("days", 30),
    )


@tool_registry.register(
    name="optionplay_expirations",
    description="List available options expiration dates for a symbol.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["expirations"],
)
async def handle_expirations(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.get_expirations(symbol=arguments["symbol"])


@tool_registry.register(
    name="optionplay_validate",
    description="Validate if a symbol is safe for trading based on earnings and events.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["validate"],
)
async def handle_validate(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.validate_for_trading(symbol=arguments["symbol"])


@tool_registry.register(
    name="optionplay_validate_trade",
    description=(
        "Full trade validation against PLAYBOOK rules. "
        "Returns GO / NO-GO / WARNING with detailed checks for "
        "stability, earnings, VIX regime, price, volume, IV rank, "
        "DTE, credit, and portfolio constraints."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ticker symbol"},
            "short_strike": {"type": "number", "description": "Short put strike price"},
            "expiration": {"type": "string", "description": "Expiration date (YYYY-MM-DD)"},
            "long_strike": {"type": "number", "description": "Long put strike price"},
            "credit": {"type": "number", "description": "Net credit per share"},
            "contracts": {"type": "number", "description": "Number of contracts"},
            "portfolio_value": {"type": "number", "description": "Portfolio value in USD"},
        },
        "required": ["symbol"],
    },
    aliases=["check"],
)
async def handle_validate_trade(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.validate.validate_trade(
        symbol=arguments["symbol"],
        short_strike=arguments.get("short_strike"),
        expiration=arguments.get("expiration"),
        long_strike=arguments.get("long_strike"),
        credit=arguments.get("credit"),
        contracts=arguments.get("contracts"),
        portfolio_value=arguments.get("portfolio_value"),
    )


@tool_registry.register(
    name="optionplay_monitor_positions",
    description="Monitor all open positions for exit signals. Checks PLAYBOOK rules and returns CLOSE / ROLL / ALERT / HOLD for each position.",
    input_schema=EMPTY_SCHEMA,
    aliases=["monitor"],
)
async def handle_monitor_positions(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.monitor.monitor_positions()


@tool_registry.register(
    name="optionplay_max_pain",
    description="Calculate Max Pain level for symbols. Shows where maximum options pain occurs.",
    input_schema={
        "type": "object",
        "properties": {"symbols": {"type": "array", "items": {"type": "string"}}},
        "required": ["symbols"],
    },
    aliases=["max_pain"],
)
async def handle_max_pain(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_max_pain(symbols=arguments["symbols"])


# =============================================================================
# ANALYSIS TOOLS (5)
# =============================================================================


@tool_registry.register(
    name="optionplay_analyze",
    description="Complete analysis of a symbol for Bull-Put-Spread suitability.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["analyze"],
)
async def handle_analyze(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.analysis.analyze_symbol(arguments["symbol"])


@tool_registry.register(
    name="optionplay_analyze_multi",
    description="Multi-Strategy Analysis for a single symbol - analyzes which strategies are suitable.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["analyze_multi"],
)
async def handle_analyze_multi(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.analysis.analyze_multi_strategy(arguments["symbol"])


@tool_registry.register(
    name="optionplay_ensemble",
    description="Get ensemble strategy recommendation for a symbol. Uses meta-learner to select best strategy.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["ensemble"],
)
async def handle_ensemble(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.analysis.get_ensemble_recommendation(arguments["symbol"])


@tool_registry.register(
    name="optionplay_ensemble_status",
    description="Get ensemble selector and strategy rotation status. Shows current strategy preferences and meta-learner insights.",
    input_schema=EMPTY_SCHEMA,
    aliases=["ensemble_status"],
)
async def handle_ensemble_status(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.analysis.get_ensemble_status()


@tool_registry.register(
    name="optionplay_recommend_strikes",
    description="Generate optimal strike recommendations for Bull-Put-Spreads. Analyzes support levels, Fibonacci, and options chain.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "dte_min": {"type": "number", "description": "Min DTE (default: 60)"},
            "dte_max": {"type": "number", "description": "Max DTE (default: 90)"},
            "num_alternatives": {
                "type": "number",
                "description": "Number of alternatives (default: 3)",
            },
        },
        "required": ["symbol"],
    },
    aliases=["strikes"],
)
async def handle_recommend_strikes(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.analysis.recommend_strikes(
        symbol=arguments["symbol"],
        dte_min=arguments.get("dte_min", SPREAD_DTE_MIN),
        dte_max=arguments.get("dte_max", SPREAD_DTE_MAX),
        num_alternatives=arguments.get("num_alternatives", 3),
    )


# =============================================================================
# PORTFOLIO TOOLS (13)
# =============================================================================


@tool_registry.register(
    name="optionplay_portfolio",
    description="Show INTERNAL tracking portfolio summary. NOTE: For LIVE IBKR positions, use optionplay_ibkr_portfolio!",
    input_schema=EMPTY_SCHEMA,
    aliases=["portfolio"],
    is_async=False,
)
def handle_portfolio(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_summary()


@tool_registry.register(
    name="optionplay_portfolio_positions",
    description="List portfolio positions with optional status filter (open, closed, all).",
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter: open, closed, all (default: all)"}
        },
    },
    aliases=["pf_positions"],
    is_async=False,
)
def handle_portfolio_positions(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_positions(status=arguments.get("status", "all"))


@tool_registry.register(
    name="optionplay_portfolio_position",
    description="Get detailed view of a single position including current status and P&L.",
    input_schema={
        "type": "object",
        "properties": {"position_id": {"type": "string", "description": "Position ID to view"}},
        "required": ["position_id"],
    },
    aliases=["pf_position"],
    is_async=False,
)
def handle_portfolio_position(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_position(position_id=arguments["position_id"])


@tool_registry.register(
    name="optionplay_portfolio_add",
    description="Add a new Bull-Put-Spread position to tracking.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "short_strike": {"type": "number"},
            "long_strike": {"type": "number"},
            "expiration": {"type": "string", "description": "YYYY-MM-DD"},
            "credit": {"type": "number", "description": "Net credit per share"},
            "contracts": {"type": "number", "description": "Number of contracts (default: 1)"},
            "notes": {"type": "string"},
        },
        "required": ["symbol", "short_strike", "long_strike", "expiration", "credit"],
    },
    aliases=["pf_add"],
    is_async=False,
)
def handle_portfolio_add(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_add(
        symbol=arguments["symbol"],
        short_strike=arguments["short_strike"],
        long_strike=arguments["long_strike"],
        expiration=arguments["expiration"],
        credit=arguments["credit"],
        contracts=arguments.get("contracts", 1),
        notes=arguments.get("notes", ""),
    )


@tool_registry.register(
    name="optionplay_portfolio_close",
    description="Close a position by buying back the spread. Records closing premium and calculates P&L.",
    input_schema={
        "type": "object",
        "properties": {
            "position_id": {"type": "string"},
            "close_premium": {"type": "number", "description": "Premium paid to close (per share)"},
            "notes": {"type": "string"},
        },
        "required": ["position_id", "close_premium"],
    },
    aliases=["pf_close"],
    is_async=False,
)
def handle_portfolio_close(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_close(
        position_id=arguments["position_id"],
        close_premium=arguments["close_premium"],
        notes=arguments.get("notes", ""),
    )


@tool_registry.register(
    name="optionplay_portfolio_expire",
    description="Mark a position as expired worthless. Records full credit as profit.",
    input_schema={
        "type": "object",
        "properties": {"position_id": {"type": "string"}},
        "required": ["position_id"],
    },
    aliases=["pf_expire"],
    is_async=False,
)
def handle_portfolio_expire(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_expire(position_id=arguments["position_id"])


@tool_registry.register(
    name="optionplay_portfolio_expiring",
    description="List positions expiring within specified days.",
    input_schema={
        "type": "object",
        "properties": {
            "days": {"type": "number", "description": "Days to look ahead (default: 7)"}
        },
    },
    aliases=["pf_expiring"],
    is_async=False,
)
def handle_portfolio_expiring(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_expiring(days=arguments.get("days", 7))


@tool_registry.register(
    name="optionplay_portfolio_trades",
    description="Show trade history with recent entries and exits.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "number", "description": "Max trades to show (default: 20)"}
        },
    },
    aliases=["pf_trades"],
    is_async=False,
)
def handle_portfolio_trades(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_trades(limit=arguments.get("limit", 20))


@tool_registry.register(
    name="optionplay_portfolio_pnl",
    description="Show realized P&L grouped by symbol.",
    input_schema=EMPTY_SCHEMA,
    aliases=["pf_pnl"],
    is_async=False,
)
def handle_portfolio_pnl(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_pnl_symbols()


@tool_registry.register(
    name="optionplay_portfolio_monthly",
    description="Show monthly P&L report. Track performance over time.",
    input_schema=EMPTY_SCHEMA,
    aliases=["pf_monthly"],
    is_async=False,
)
def handle_portfolio_monthly(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_pnl_monthly()


@tool_registry.register(
    name="optionplay_portfolio_check",
    description="Check if a new position can be opened. Validates against max positions, sector limits, and daily risk limits.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "max_risk": {"type": "number", "description": "Maximum risk in USD (default: 500)"},
        },
        "required": ["symbol"],
    },
    aliases=["pf_check"],
    is_async=False,
)
def handle_portfolio_check(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_check(
        symbol=arguments["symbol"],
        max_risk=arguments.get("max_risk", 500.0),
    )


@tool_registry.register(
    name="optionplay_portfolio_constraints",
    description="Show current constraint configuration and status (max positions, sector limits, daily/weekly risk limits).",
    input_schema=EMPTY_SCHEMA,
    aliases=["pf_constraints"],
    is_async=False,
)
def handle_portfolio_constraints(server: Any, arguments: ToolArguments) -> str:
    return server.handlers.portfolio.portfolio_constraints()


# =============================================================================
# IBKR TOOLS (7)
# =============================================================================


@tool_registry.register(
    name="optionplay_ibkr_status",
    description="Check IBKR/TWS connection status.",
    input_schema=EMPTY_SCHEMA,
    aliases=["ibkr"],
)
async def handle_ibkr_status(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_ibkr_status()


@tool_registry.register(
    name="optionplay_ibkr_portfolio",
    description="Get LIVE portfolio positions from Interactive Brokers TWS. This is the PRIMARY portfolio tool for actual positions.",
    input_schema=EMPTY_SCHEMA,
    aliases=["ibkr_portfolio"],
)
async def handle_ibkr_portfolio(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_ibkr_portfolio()


@tool_registry.register(
    name="optionplay_ibkr_spreads",
    description="Get identified spread positions from IBKR/TWS.",
    input_schema=EMPTY_SCHEMA,
    aliases=["ibkr_spreads"],
)
async def handle_ibkr_spreads(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_ibkr_spreads()


@tool_registry.register(
    name="optionplay_ibkr_vix",
    description="Get live VIX from IBKR with source indicator.",
    input_schema=EMPTY_SCHEMA,
    aliases=["ibkr_vix"],
)
async def handle_ibkr_vix(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_ibkr_vix()


@tool_registry.register(
    name="optionplay_ibkr_quotes",
    description="Get batch quotes for watchlist from IBKR.",
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "batch_size": {"type": "number", "description": "Symbols per batch (default: 50)"},
        },
    },
    aliases=["ibkr_quotes"],
)
async def handle_ibkr_quotes(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_ibkr_quotes(
        symbols=arguments.get("symbols"),
        batch_size=arguments.get("batch_size", 50),
    )


@tool_registry.register(
    name="optionplay_news",
    description="Get recent news headlines for symbols via IBKR. Requires TWS connection.",
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "days": {"type": "number", "description": "Days to look back (default: 5)"},
        },
        "required": ["symbols"],
    },
    aliases=["news"],
)
async def handle_news(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.ibkr.get_news(
        symbols=arguments["symbols"],
        days=arguments.get("days", 5),
    )


# =============================================================================
# REPORT TOOLS (2)
# =============================================================================


@tool_registry.register(
    name="optionplay_report",
    description="Generate a detailed PDF report for a trading candidate. Saved to reports/ directory.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "strategy": {"type": "string", "description": "Strategy type (default: pullback)"},
            "include_options": {
                "type": "boolean",
                "description": "Include options chain (default: true)",
            },
            "include_news": {"type": "boolean", "description": "Include news (default: true)"},
        },
        "required": ["symbol"],
    },
    aliases=["report"],
)
async def handle_report(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.report.generate_report(
        symbol=arguments["symbol"],
        strategy=arguments.get("strategy"),
        include_options=arguments.get("include_options", True),
        include_news=arguments.get("include_news", True),
    )


@tool_registry.register(
    name="optionplay_scan_report",
    description="Generate comprehensive multi-symbol PDF scan report with 13 pages. Saved to reports/ directory.",
    input_schema={
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "description": "Strategy: pullback, bounce, breakout, dip, multi (default: multi)",
            },
            "symbols": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number", "description": "Minimum score (default: 5.0)"},
            "max_candidates": {"type": "number", "description": "Max candidates (default: 20)"},
        },
    },
    aliases=["scan_report"],
)
async def handle_scan_report(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.report.generate_scan_report(
        strategy=arguments.get("strategy", "multi"),
        symbols=arguments.get("symbols"),
        min_score=arguments.get("min_score", 5.0),
        max_candidates=arguments.get("max_candidates", 20),
    )


# =============================================================================
# RISK TOOLS (4)
# =============================================================================


@tool_registry.register(
    name="optionplay_position_size",
    description="Calculate optimal position size using Kelly Criterion. Adjusts for VIX, signal quality, and portfolio exposure.",
    input_schema={
        "type": "object",
        "properties": {
            "account_size": {"type": "number", "description": "Total account size in USD"},
            "max_loss_per_contract": {
                "type": "number",
                "description": "Maximum loss per contract in USD",
            },
            "win_rate": {"type": "number", "description": "Historical win rate (default: 0.65)"},
            "avg_win": {"type": "number", "description": "Average win in USD (default: 100)"},
            "avg_loss": {"type": "number", "description": "Average loss in USD (default: 350)"},
            "signal_score": {
                "type": "number",
                "description": "Signal quality score (default: 7.0)",
            },
            "reliability_grade": {"type": "string", "description": "A, B, or C grade"},
            "current_exposure": {
                "type": "number",
                "description": "Current portfolio exposure (default: 0)",
            },
        },
        "required": ["account_size", "max_loss_per_contract"],
    },
    aliases=["position_size"],
)
async def handle_position_size(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.risk.calculate_position_size(
        account_size=arguments["account_size"],
        max_loss_per_contract=arguments["max_loss_per_contract"],
        win_rate=arguments.get("win_rate", 0.65),
        avg_win=arguments.get("avg_win", 100),
        avg_loss=arguments.get("avg_loss", 350),
        signal_score=arguments.get("signal_score", 7.0),
        reliability_grade=arguments.get("reliability_grade"),
        current_exposure=arguments.get("current_exposure", 0),
    )


@tool_registry.register(
    name="optionplay_stop_loss",
    description="Get recommended stop loss level for a credit spread. Adjusts based on VIX regime.",
    input_schema={
        "type": "object",
        "properties": {
            "net_credit": {"type": "number", "description": "Net credit received"},
            "spread_width": {"type": "number", "description": "Spread width in USD"},
        },
        "required": ["net_credit", "spread_width"],
    },
    aliases=["stop_loss"],
)
async def handle_stop_loss(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.risk.recommend_stop_loss(
        net_credit=arguments["net_credit"],
        spread_width=arguments["spread_width"],
    )


@tool_registry.register(
    name="optionplay_spread_analysis",
    description="Analyze a Bull-Put-Spread with comprehensive risk/reward metrics, probabilities, and P&L scenarios.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "short_strike": {"type": "number"},
            "long_strike": {"type": "number"},
            "net_credit": {"type": "number"},
            "dte": {"type": "number", "description": "Days to expiration"},
            "contracts": {"type": "number", "description": "Number of contracts (default: 1)"},
        },
        "required": ["symbol", "short_strike", "long_strike", "net_credit", "dte"],
    },
    aliases=["spread_analysis"],
)
async def handle_spread_analysis(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.risk.analyze_spread(
        symbol=arguments["symbol"],
        short_strike=arguments["short_strike"],
        long_strike=arguments["long_strike"],
        net_credit=arguments["net_credit"],
        dte=arguments["dte"],
        contracts=arguments.get("contracts", 1),
    )


@tool_registry.register(
    name="optionplay_monte_carlo",
    description="Run Monte Carlo simulation for a Bull-Put-Spread. Simulates price paths to estimate outcome probabilities.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "short_strike": {"type": "number"},
            "long_strike": {"type": "number"},
            "net_credit": {"type": "number"},
            "dte": {"type": "number", "description": "Days to expiration (default: 75)"},
            "num_simulations": {
                "type": "number",
                "description": "Number of simulations (default: 500)",
            },
            "volatility": {"type": "number", "description": "Override volatility (optional)"},
        },
        "required": ["symbol", "short_strike", "long_strike", "net_credit"],
    },
    aliases=["monte_carlo"],
)
async def handle_monte_carlo(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.risk.run_monte_carlo(
        symbol=arguments["symbol"],
        short_strike=arguments["short_strike"],
        long_strike=arguments["long_strike"],
        net_credit=arguments["net_credit"],
        dte=arguments.get("dte", SPREAD_DTE_TARGET),
        num_simulations=arguments.get("num_simulations", 500),
        volatility=arguments.get("volatility"),
    )


# =============================================================================
# SYSTEM TOOLS (2)
# =============================================================================


@tool_registry.register(
    name="optionplay_cache_stats",
    description="Show cache statistics for historical data, quotes, and scan results.",
    input_schema=EMPTY_SCHEMA,
    aliases=["cache_stats"],
)
async def handle_cache_stats(server: Any, arguments: ToolArguments) -> str:
    return await server.get_cache_stats()


@tool_registry.register(
    name="optionplay_watchlist_info",
    description="Show information about the current watchlist including total symbols and sectors.",
    input_schema=EMPTY_SCHEMA,
    aliases=["watchlist"],
    is_async=False,
)
def handle_watchlist_info(server: Any, arguments: ToolArguments) -> str:
    return server.get_watchlist_info()


# =============================================================================
# SECTOR CYCLE TOOLS (1)
# =============================================================================


@tool_registry.register(
    name="optionplay_sector_status",
    description="Get current sector momentum analysis with relative strength, breadth, and momentum factors for all sectors.",
    input_schema=EMPTY_SCHEMA,
    aliases=["sector_status"],
)
async def handle_sector_status(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.vix.get_sector_status()


# =============================================================================
# SHADOW TRADE TRACKER (2)
# =============================================================================


@tool_registry.register(
    name="optionplay_shadow_review",
    description=(
        "Review shadow trades: resolve open trades against current market data, "
        "show open/closed trades with P&L. Resolves using live options chain prices."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "resolve": {
                "type": "boolean",
                "description": "Resolve open trades against current prices (default: true)",
            },
            "status_filter": {
                "type": "string",
                "enum": ["all", "open", "closed"],
                "description": "Filter by status (default: all)",
            },
            "strategy_filter": {
                "type": "string",
                "description": "Filter by strategy name",
            },
            "days_back": {
                "type": "number",
                "description": "Time period in days (default: 90)",
            },
        },
    },
    aliases=["shadow_review", "shadow"],
)
async def handle_shadow_review(server: Any, arguments: ToolArguments) -> str:
    from .shadow_tracker import (
        ShadowTracker,
        format_review_output,
        resolve_open_trades,
    )

    do_resolve = arguments.get("resolve", True)
    status_filter = arguments.get("status_filter", "all")
    strategy_filter = arguments.get("strategy_filter")
    days_back = int(arguments.get("days_back", 90))

    tracker = ShadowTracker()
    try:
        # Resolve open trades if requested
        resolutions = []
        if do_resolve:
            provider = None
            if hasattr(server, "handlers"):
                ctx = server.handlers._context
                if ctx.ibkr_connected and ctx.ibkr_provider:
                    provider = ctx.ibkr_provider
            resolutions = await resolve_open_trades(tracker, provider=provider)

        # Fetch trades and rejections
        trades = tracker.get_trades(
            status_filter=status_filter,
            strategy_filter=strategy_filter,
            days_back=days_back,
        )
        rejections = tracker.get_rejections(days_back=days_back)

        return format_review_output(trades, resolutions, rejections)
    finally:
        tracker.close()


@tool_registry.register(
    name="optionplay_shadow_stats",
    description=(
        "Aggregated shadow trade statistics. Group by strategy, score bucket, "
        "regime, month, symbol, liquidity tier, or rejection reason."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "enum": [
                    "strategy",
                    "score_bucket",
                    "regime",
                    "month",
                    "symbol",
                    "tier",
                    "rejection_reason",
                ],
                "description": "Grouping dimension (default: strategy)",
            },
            "min_trades": {
                "type": "number",
                "description": "Minimum trades per group for relevance (default: 5)",
            },
        },
    },
    aliases=["shadow_stats"],
)
async def handle_shadow_stats(server: Any, arguments: ToolArguments) -> str:
    from .shadow_tracker import ShadowTracker, format_stats_output, get_stats

    group_by = arguments.get("group_by", "strategy")
    min_trades = int(arguments.get("min_trades", 5))

    tracker = ShadowTracker()
    try:
        stats = get_stats(tracker, group_by=group_by, min_trades=min_trades)
        return format_stats_output(stats)
    finally:
        tracker.close()


@tool_registry.register(
    name="optionplay_shadow_log",
    description=(
        "Manually log a shadow trade. Runs tradability check against the live "
        "options chain before logging. Use this when you want to track a specific "
        "trade idea outside of daily_picks."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ticker symbol (e.g. AAPL)"},
            "strategy": {
                "type": "string",
                "enum": [
                    "pullback",
                    "bounce",
                    "ath_breakout",
                    "earnings_dip",
                    "trend_continuation",
                ],
                "description": "Trading strategy",
            },
            "score": {"type": "number", "description": "Signal score (0-10)"},
            "short_strike": {"type": "number", "description": "Short put strike price"},
            "long_strike": {"type": "number", "description": "Long put strike price"},
            "expiration": {"type": "string", "description": "Expiration date (YYYY-MM-DD)"},
            "price_at_log": {"type": "number", "description": "Current underlying price"},
        },
        "required": [
            "symbol",
            "strategy",
            "score",
            "short_strike",
            "long_strike",
            "expiration",
            "price_at_log",
        ],
    },
    aliases=["shadow_log"],
)
async def handle_shadow_log(server: Any, arguments: ToolArguments) -> str:
    from .shadow_tracker import ShadowTracker, check_tradability

    symbol = arguments["symbol"].upper()
    strategy = arguments["strategy"]
    score = float(arguments["score"])
    short_strike = float(arguments["short_strike"])
    long_strike = float(arguments["long_strike"])
    expiration = arguments["expiration"]
    price_at_log = float(arguments["price_at_log"])
    spread_width = short_strike - long_strike

    if spread_width <= 0:
        return "**Error:** short_strike must be greater than long_strike."

    # Get Tradier provider
    provider = None
    if hasattr(server, "handlers"):
        ctx = server.handlers._context
        if ctx.ibkr_connected and ctx.ibkr_provider:
            provider = ctx.ibkr_provider

    if not provider:
        return "**Error:** Tradier provider not available. Cannot run tradability check."

    # Run tradability check
    tradeable, reason, details = await check_tradability(
        provider, symbol, expiration, short_strike, long_strike
    )

    tracker = ShadowTracker()
    try:
        if not tradeable:
            # Log rejection
            rej_id = tracker.log_rejection(
                source="manual",
                symbol=symbol,
                strategy=strategy,
                score=score,
                rejection_reason=reason,
                short_strike=short_strike,
                long_strike=long_strike,
                actual_credit=details.get("net_credit"),
                short_oi=details.get("short_oi"),
                details=json.dumps(details),
            )
            return (
                f"**NOT TRADEABLE** — {reason}\n\n"
                f"Rejection logged (ID: `{rej_id}`)\n\n"
                f"Details: {json.dumps(details, indent=2)}"
            )

        # Calculate DTE
        from datetime import date as _date

        dte = (_date.fromisoformat(expiration) - _date.today()).days
        est_credit = details.get("net_credit", 0.0)

        trade_id = tracker.log_trade(
            source="manual",
            symbol=symbol,
            strategy=strategy,
            score=score,
            short_strike=short_strike,
            long_strike=long_strike,
            spread_width=spread_width,
            est_credit=est_credit,
            expiration=expiration,
            dte=dte,
            price_at_log=price_at_log,
            short_bid=details.get("short_bid"),
            short_ask=details.get("short_ask"),
            short_oi=details.get("short_oi"),
            long_bid=details.get("long_bid"),
            long_ask=details.get("long_ask"),
            long_oi=details.get("long_oi"),
        )

        if trade_id is None:
            return f"**Duplicate:** A trade for {symbol} {short_strike}/{long_strike} already exists today."

        return (
            f"**TRADEABLE** — Shadow trade logged\n\n"
            f"- **Trade ID:** `{trade_id}`\n"
            f"- **Symbol:** {symbol}\n"
            f"- **Strategy:** {strategy}\n"
            f"- **Score:** {score:.1f}\n"
            f"- **Strikes:** {short_strike:.0f}/{long_strike:.0f}\n"
            f"- **Est. Credit:** ${est_credit:.2f}\n"
            f"- **Expiration:** {expiration} (DTE: {dte})\n"
            f"- **Short Bid/Ask:** ${details.get('short_bid', 0):.2f}/${details.get('short_ask', 0):.2f}\n"
            f"- **Long Bid/Ask:** ${details.get('long_bid', 0):.2f}/${details.get('long_ask', 0):.2f}"
        )
    finally:
        tracker.close()


@tool_registry.register(
    name="optionplay_shadow_detail",
    description=(
        "Show full details of a single shadow trade by ID. "
        "Displays all fields including options market data at logging, "
        "current status, and resolution details."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trade_id": {
                "type": "string",
                "description": "Trade UUID (from shadow_review or shadow_log output)",
            },
        },
        "required": ["trade_id"],
    },
    aliases=["shadow_detail"],
)
async def handle_shadow_detail(server: Any, arguments: ToolArguments) -> str:
    from .shadow_tracker import ShadowTracker, format_detail_output

    trade_id = arguments["trade_id"]

    tracker = ShadowTracker()
    try:
        trade = tracker.get_trade(trade_id)
        return format_detail_output(trade)
    finally:
        tracker.close()


# =============================================================================
# SUMMARY
# =============================================================================
# Total: 58 Tools + 61 Aliases = 119 MCP endpoints
#
# Categories:
# - VIX & Strategy: 6 tools (inkl. sector_status)
# - Scan: 7 tools (inkl. daily_picks)
# - Quote & Data: 7 tools
# - Analysis: 5 tools
# - Portfolio: 13 tools
# - IBKR: 7 tools (inkl. news, max_pain)
# - Reports: 2 tools
# - Risk: 4 tools
# - System: 2 tools
# - Shadow Tracker: 4 tools
