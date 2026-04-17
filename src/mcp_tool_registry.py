"""
OptionPlay MCP Tool Registry v4.1.0
===================================

Zentrales Registry für alle MCP Tools mit Handler-Definitionen.

Stats (2026-04-07):
- 25 Tools (reduced from 54)

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

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from mcp.types import Tool

try:
    from .constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        SPREAD_DTE_MAX,
        SPREAD_DTE_MIN,
    )
except ImportError:
    from constants.trading_rules import (
        ENTRY_EARNINGS_MIN_DAYS,
        SPREAD_DTE_MAX,
        SPREAD_DTE_MIN,
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
# VIX & STRATEGY TOOLS (3)
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
    description="Get current VIX regime status. Use version='v2' for continuous interpolation model with term structure and trend overlays. Default shows WF-trained model recommendations.",
    input_schema={
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "description": "Regime model version: 'v1' (default, trained model) or 'v2' (continuous interpolation)",
                "enum": ["v1", "v2"],
                "default": "v1",
            }
        },
    },
    aliases=["regime"],
)
async def handle_regime_status(server: Any, arguments: ToolArguments) -> str:
    version = arguments.get("version", "v1")
    if version == "v2":
        return await server.handlers.vix.get_regime_status_v2()
    return await server.handlers.vix.get_regime_status()


@tool_registry.register(
    name="optionplay_health",
    description="Check server health and configuration status.",
    input_schema=EMPTY_SCHEMA,
    aliases=["health"],
)
async def handle_health(server: Any, arguments: ToolArguments) -> str:
    return await server.health_check()


# =============================================================================
# SCAN TOOLS (3)
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


# =============================================================================
# QUOTE & DATA TOOLS (4)
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
    name="optionplay_expirations",
    description="List available options expiration dates for a symbol.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["expirations"],
)
async def handle_expirations(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.quote.get_expirations(symbol=arguments["symbol"])


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


# =============================================================================
# ANALYSIS TOOLS (3)
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
    name="optionplay_ensemble",
    description="Get ensemble strategy recommendation for a symbol. Uses meta-learner to select best strategy.",
    input_schema=SYMBOL_SCHEMA,
    aliases=["ensemble"],
)
async def handle_ensemble(server: Any, arguments: ToolArguments) -> str:
    return await server.handlers.analysis.get_ensemble_recommendation(arguments["symbol"])


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
# PORTFOLIO TOOLS (6)
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


# =============================================================================
# RISK TOOLS (1)
# =============================================================================


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


# =============================================================================
# SECTOR & SYSTEM TOOLS (2)
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


# =============================================================================
# SUMMARY
# =============================================================================
# Total: 25 Tools
#
# Categories:
# - VIX & Strategy: 3 tools (vix, regime_status, sector_status)
# - Scan: 3 tools (scan, scan_bounce, daily_picks)
# - Quote & Data: 5 tools (quote, options, expirations, earnings, validate_trade)
# - Analysis: 3 tools (analyze, ensemble, recommend_strikes)
# - Portfolio: 7 tools (portfolio, positions, add, close, expire, check, monitor)
# - Risk: 1 tool (spread_analysis)
# - System: 1 tool (health)
# - Shadow Tracker: 2 tools (shadow_review, shadow_stats)
