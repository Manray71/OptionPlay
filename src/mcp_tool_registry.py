# OptionPlay - Tool Registry Pattern
# ===================================
# Eliminiert die 340-Zeilen elif-Kette in mcp_main.py
#
# Usage:
#     from .mcp_tool_registry import ToolRegistry, tool_registry
#
#     @tool_registry.register("optionplay_vix")
#     async def handle_vix(server, arguments):
#         return await server.get_strategy_recommendation()
#
#     # In call_tool:
#     result = await tool_registry.dispatch(name, server, arguments)

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable, Union
from mcp.types import Tool

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Vollständige Tool-Definition mit Handler."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Awaitable[str]]
    is_async: bool = True
    aliases: List[str] = field(default_factory=list)


class ToolRegistry:
    """
    Registry für MCP Tools.

    Verbindet Tool-Definitionen mit Handlern für sauberen Dispatch.

    Example:
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_vix",
            description="Get VIX and strategy",
            input_schema={"type": "object", "properties": {}}
        )
        async def handle_vix(server, arguments):
            return await server.get_strategy_recommendation()

        # Later in call_tool:
        result = await registry.dispatch("optionplay_vix", server, {})
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._aliases: Dict[str, str] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        aliases: Optional[List[str]] = None,
        is_async: bool = True,
    ):
        """
        Decorator zum Registrieren eines Tool-Handlers.

        Args:
            name: Voller Tool-Name (z.B. "optionplay_vix")
            description: Tool-Beschreibung für Claude
            input_schema: JSON-Schema für die Eingabe
            aliases: Optionale kurze Aliase (z.B. ["vix"])
            is_async: True wenn der Handler async ist

        Returns:
            Decorator-Funktion
        """
        def decorator(func: Callable[..., Awaitable[str]]) -> Callable:
            tool = ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=func,
                is_async=is_async,
                aliases=aliases or [],
            )
            self._tools[name] = tool

            # Register aliases
            for alias in (aliases or []):
                self._aliases[alias] = name

            logger.debug(f"Tool registered: {name} (aliases: {aliases})")
            return func

        return decorator

    def register_handler(
        self,
        name: str,
        handler: Callable[..., Awaitable[str]],
        description: str = "",
        input_schema: Optional[Dict[str, Any]] = None,
        aliases: Optional[List[str]] = None,
        is_async: bool = True,
    ) -> None:
        """
        Registriert einen Handler direkt (ohne Decorator).

        Nützlich für dynamische Registrierung.
        """
        tool = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            handler=handler,
            is_async=is_async,
            aliases=aliases or [],
        )
        self._tools[name] = tool

        for alias in (aliases or []):
            self._aliases[alias] = name

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
        arguments: Dict[str, Any],
    ) -> str:
        """
        Dispatcht einen Tool-Aufruf zum registrierten Handler.

        Args:
            name: Tool-Name oder Alias
            server: OptionPlayServer Instanz
            arguments: Tool-Argumente

        Returns:
            Handler-Ergebnis als String

        Raises:
            ValueError: Wenn Tool nicht gefunden
        """
        resolved = self.resolve_alias(name)
        tool = self._tools.get(resolved)

        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        if tool.is_async:
            return await tool.handler(server, arguments)
        else:
            return tool.handler(server, arguments)

    def list_tools(self) -> List[Tool]:
        """
        Gibt alle Tools als MCP Tool-Objekte zurück.

        Inkl. Alias-Tools mit "[Alias for ...]" Prefix.
        """
        tools = []

        for tool_def in self._tools.values():
            # Haupt-Tool
            tools.append(Tool(
                name=tool_def.name,
                description=tool_def.description,
                inputSchema=tool_def.input_schema,
            ))

            # Alias-Tools
            for alias in tool_def.aliases:
                tools.append(Tool(
                    name=alias,
                    description=f"[Alias for {tool_def.name}] {tool_def.description}",
                    inputSchema=tool_def.input_schema,
                ))

        return tools

    @property
    def tool_count(self) -> int:
        """Anzahl registrierter Tools (ohne Aliase)."""
        return len(self._tools)

    @property
    def alias_count(self) -> int:
        """Anzahl registrierter Aliase."""
        return len(self._aliases)


# =============================================================================
# GLOBAL REGISTRY INSTANCE
# =============================================================================

tool_registry = ToolRegistry()


# =============================================================================
# TOOL HANDLERS
# =============================================================================
# Diese Funktionen werden vom Registry aufgerufen.
# Jeder Handler bekommt (server, arguments) und gibt einen String zurück.

# -----------------------------------------------------------------------------
# CORE TOOLS
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_vix",
    description="Get current VIX level and strategy recommendation based on market volatility.",
    input_schema={"type": "object", "properties": {}, "required": []},
    aliases=["vix"],
)
async def handle_vix(server, arguments):
    return await server.get_strategy_recommendation()


@tool_registry.register(
    name="optionplay_scan",
    description="Scan watchlist for pullback candidates suitable for Bull-Put-Spreads. Uses VIX-based strategy selection.",
    input_schema={
        "type": "object",
        "properties": {
            "max_results": {"type": "number", "description": "Maximum candidates (default: 10)"},
            "symbols": {"type": "array", "items": {"type": "string"}, "description": "Optional specific symbols"},
        },
    },
    aliases=["scan"],
)
async def handle_scan(server, arguments):
    return await server.scan_with_strategy(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
    )


@tool_registry.register(
    name="optionplay_quote",
    description="Get current stock quote with bid/ask/volume.",
    input_schema={
        "type": "object",
        "properties": {"symbol": {"type": "string", "description": "Stock ticker symbol"}},
        "required": ["symbol"],
    },
    aliases=["quote"],
)
async def handle_quote(server, arguments):
    return await server.get_quote(arguments["symbol"])


@tool_registry.register(
    name="optionplay_options",
    description="Get options chain for a symbol with Greeks and IV.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "dte_min": {"type": "number", "description": "Min DTE (default: 30)"},
            "dte_max": {"type": "number", "description": "Max DTE (default: 60)"},
            "right": {"type": "string", "description": "P for puts, C for calls (default: P)"},
        },
        "required": ["symbol"],
    },
    aliases=["options"],
)
async def handle_options(server, arguments):
    return await server.get_options_chain(
        symbol=arguments["symbol"],
        dte_min=arguments.get("dte_min", 30),
        dte_max=arguments.get("dte_max", 60),
        right=arguments.get("right", "P"),
    )


@tool_registry.register(
    name="optionplay_earnings",
    description="Check earnings date for a symbol. Returns safety status for trading.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "min_days": {"type": "number", "description": "Min days buffer (default: 60)"},
        },
        "required": ["symbol"],
    },
    aliases=["earnings"],
)
async def handle_earnings(server, arguments):
    return await server.get_earnings_aggregated(
        arguments["symbol"],
        arguments.get("min_days", 60),
    )


@tool_registry.register(
    name="optionplay_analyze",
    description="Complete analysis of a symbol for Bull-Put-Spread suitability.",
    input_schema={
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
    aliases=["analyze"],
)
async def handle_analyze(server, arguments):
    return await server.analyze_symbol(arguments["symbol"])


@tool_registry.register(
    name="optionplay_portfolio",
    description="Show INTERNAL tracking portfolio (manually tracked trades). NOTE: For LIVE positions from Interactive Brokers/TWS, use optionplay_ibkr_portfolio instead!",
    input_schema={"type": "object", "properties": {}},
    aliases=["portfolio"],
    is_async=False,
)
def handle_portfolio(server, arguments):
    return server.portfolio_summary()


@tool_registry.register(
    name="optionplay_health",
    description="Check server health and configuration status.",
    input_schema={"type": "object", "properties": {}},
    aliases=["health"],
)
async def handle_health(server, arguments):
    return await server.health_check()


# -----------------------------------------------------------------------------
# REGIME & ENSEMBLE
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_regime_status",
    description="Get current VIX regime status with trained model recommendations. Shows regime, trading parameters, enabled strategies based on trained model.",
    input_schema={"type": "object", "properties": {}},
    aliases=["regime"],
)
async def handle_regime_status(server, arguments):
    return await server.get_regime_status()


@tool_registry.register(
    name="optionplay_ensemble",
    description="Get ensemble strategy recommendation for a symbol. Uses meta-learner to select best strategy based on symbol history, regime, and confidence-weighted scoring.",
    input_schema={
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
    aliases=["ensemble"],
)
async def handle_ensemble(server, arguments):
    return await server.get_ensemble_recommendation(arguments["symbol"])


@tool_registry.register(
    name="optionplay_ensemble_status",
    description="Get ensemble selector and strategy rotation status. Shows current strategy preferences, rotation triggers, and meta-learner insights.",
    input_schema={"type": "object", "properties": {}},
    aliases=["ensemble_status"],
)
async def handle_ensemble_status(server, arguments):
    return await server.get_ensemble_status()


# -----------------------------------------------------------------------------
# MULTI-STRATEGY SCANNERS
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_scan_bounce",
    description="Scan for Support Bounce candidates - stocks bouncing off established support levels. Good for long entries (stock or calls).",
    input_schema={
        "type": "object",
        "properties": {
            "max_results": {"type": "number"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number"},
        },
    },
    aliases=["bounce"],
)
async def handle_scan_bounce(server, arguments):
    return await server.scan_bounce(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 5.0),
    )


@tool_registry.register(
    name="optionplay_scan_breakout",
    description="Scan for ATH Breakout candidates - stocks breaking out to new all-time highs with volume confirmation. Good for momentum trades.",
    input_schema={
        "type": "object",
        "properties": {
            "max_results": {"type": "number"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number"},
        },
    },
    aliases=["breakout"],
)
async def handle_scan_breakout(server, arguments):
    return await server.scan_ath_breakout(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 6.0),
    )


@tool_registry.register(
    name="optionplay_scan_earnings_dip",
    description="Scan for Earnings Dip Buy candidates - quality stocks that dropped 5-15% after earnings (potential overreaction). Contrarian play.",
    input_schema={
        "type": "object",
        "properties": {
            "max_results": {"type": "number"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number"},
        },
    },
    aliases=["dip"],
)
async def handle_scan_earnings_dip(server, arguments):
    return await server.scan_earnings_dip(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 10),
        min_score=arguments.get("min_score", 5.0),
    )


@tool_registry.register(
    name="optionplay_scan_multi",
    description="Multi-Strategy Scan - runs all strategies (Pullback, Bounce, ATH Breakout, Earnings Dip) and returns the best signal per symbol. Shows which strategy is optimal for each candidate.",
    input_schema={
        "type": "object",
        "properties": {
            "max_results": {"type": "number"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number"},
        },
    },
    aliases=["multi"],
)
async def handle_scan_multi(server, arguments):
    return await server.scan_multi_strategy(
        symbols=arguments.get("symbols"),
        max_results=arguments.get("max_results", 20),
        min_score=arguments.get("min_score", 5.0),
    )


@tool_registry.register(
    name="optionplay_analyze_multi",
    description="Multi-Strategy Analysis for a single symbol - analyzes which strategies are suitable and returns scores for each.",
    input_schema={
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
    aliases=["analyze_multi"],
)
async def handle_analyze_multi(server, arguments):
    return await server.analyze_multi_strategy(arguments["symbol"])


# -----------------------------------------------------------------------------
# EARNINGS PREFILTER
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_earnings_prefilter",
    description="Pre-filter watchlist by earnings dates. Returns only symbols with earnings > X days away. Uses 4-week cache. This should be the FIRST step before any scan to avoid wasting API calls on symbols with upcoming earnings.",
    input_schema={
        "type": "object",
        "properties": {
            "min_days": {"type": "number", "description": "Minimum days to earnings (default: 45)"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "show_excluded": {"type": "boolean", "description": "Show excluded symbols (default: false)"},
        },
    },
    aliases=["prefilter"],
)
async def handle_earnings_prefilter(server, arguments):
    return await server.earnings_prefilter(
        min_days=arguments.get("min_days", 45),
        symbols=arguments.get("symbols"),
        show_excluded=arguments.get("show_excluded", False),
    )


# -----------------------------------------------------------------------------
# STRIKE RECOMMENDER
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_recommend_strikes",
    description="Generate optimal strike recommendations for Bull-Put-Spreads. Analyzes support levels, Fibonacci retracements, and options chain to recommend short/long strike combinations with quality scores.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "dte_min": {"type": "number"},
            "dte_max": {"type": "number"},
            "num_alternatives": {"type": "number"},
        },
        "required": ["symbol"],
    },
    aliases=["strikes"],
)
async def handle_recommend_strikes(server, arguments):
    return await server.recommend_strikes(
        symbol=arguments["symbol"],
        dte_min=arguments.get("dte_min", 30),
        dte_max=arguments.get("dte_max", 60),
        num_alternatives=arguments.get("num_alternatives", 3),
    )


# -----------------------------------------------------------------------------
# REPORTS
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_report",
    description="Generate a detailed PDF report for a trading candidate. Includes summary, score breakdown, technical levels, options setup, and news. The PDF is saved to the reports/ directory.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "strategy": {"type": "string"},
            "include_options": {"type": "boolean"},
            "include_news": {"type": "boolean"},
        },
        "required": ["symbol"],
    },
    aliases=["report"],
)
async def handle_report(server, arguments):
    return await server.generate_report(
        symbol=arguments["symbol"],
        strategy=arguments.get("strategy"),
        include_options=arguments.get("include_options", True),
        include_news=arguments.get("include_news", True),
    )


@tool_registry.register(
    name="optionplay_scan_report",
    description="Generate a comprehensive multi-symbol PDF scan report. Creates a 13-page professional report with: Cover page, market environment analysis, scan results, earnings filter, support analysis, qualified candidates, fundamental analysis (top 2), trade setups with Volume Profile (top 2), comparison, and risk management. PDF is saved to reports/ directory.",
    input_schema={
        "type": "object",
        "properties": {
            "strategy": {"type": "string"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number"},
            "max_candidates": {"type": "number"},
        },
    },
    aliases=["scan_report"],
)
async def handle_scan_report(server, arguments):
    return await server.generate_scan_report(
        strategy=arguments.get("strategy", "multi"),
        symbols=arguments.get("symbols"),
        min_score=arguments.get("min_score", 5.0),
        max_candidates=arguments.get("max_candidates", 20),
    )


# -----------------------------------------------------------------------------
# IBKR BRIDGE TOOLS
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_ibkr_status",
    description="Check IBKR/TWS connection status.",
    input_schema={"type": "object", "properties": {}},
    aliases=["ibkr"],
)
async def handle_ibkr_status(server, arguments):
    return await server.get_ibkr_status()


@tool_registry.register(
    name="optionplay_ibkr_portfolio",
    description="Get LIVE portfolio positions from Interactive Brokers TWS. This is the PRIMARY portfolio tool - use this to see actual open positions, spreads, and P&L. Requires TWS connection.",
    input_schema={"type": "object", "properties": {}},
    aliases=["ibkr_portfolio"],
)
async def handle_ibkr_portfolio(server, arguments):
    return await server.get_ibkr_portfolio()


@tool_registry.register(
    name="optionplay_ibkr_spreads",
    description="Get identified spread positions from IBKR/TWS.",
    input_schema={"type": "object", "properties": {}},
    aliases=["ibkr_spreads"],
)
async def handle_ibkr_spreads(server, arguments):
    return await server.get_ibkr_spreads()


@tool_registry.register(
    name="optionplay_ibkr_vix",
    description="Get live VIX from IBKR with source indicator.",
    input_schema={"type": "object", "properties": {}},
    aliases=["ibkr_vix"],
)
async def handle_ibkr_vix(server, arguments):
    return await server.get_ibkr_vix()


@tool_registry.register(
    name="optionplay_ibkr_quotes",
    description="Get batch quotes for watchlist from IBKR.",
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "batch_size": {"type": "number"},
        },
    },
    aliases=["ibkr_quotes"],
)
async def handle_ibkr_quotes(server, arguments):
    return await server.get_ibkr_quotes(
        symbols=arguments.get("symbols"),
        batch_size=arguments.get("batch_size", 50),
    )


# -----------------------------------------------------------------------------
# PORTFOLIO MANAGEMENT
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_portfolio_positions",
    description="List portfolio positions with optional status filter. Shows all tracked Bull-Put-Spread positions.",
    input_schema={
        "type": "object",
        "properties": {"status": {"type": "string", "description": "Filter: open, closed, all"}},
    },
    aliases=["pf_positions"],
    is_async=False,
)
def handle_portfolio_positions(server, arguments):
    return server.portfolio_positions(status=arguments.get("status", "all"))


@tool_registry.register(
    name="optionplay_portfolio_add",
    description="Add a new Bull-Put-Spread position to tracking. Records entry for P&L tracking.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "short_strike": {"type": "number"},
            "long_strike": {"type": "number"},
            "expiration": {"type": "string"},
            "credit": {"type": "number"},
            "contracts": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["symbol", "short_strike", "long_strike", "expiration", "credit"],
    },
    aliases=["pf_add"],
    is_async=False,
)
def handle_portfolio_add(server, arguments):
    return server.portfolio_add(
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
    description="Close a position by buying back the spread. Records the closing premium and calculates P&L.",
    input_schema={
        "type": "object",
        "properties": {
            "position_id": {"type": "string"},
            "close_premium": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["position_id", "close_premium"],
    },
    aliases=["pf_close"],
    is_async=False,
)
def handle_portfolio_close(server, arguments):
    return server.portfolio_close(
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
def handle_portfolio_expire(server, arguments):
    return server.portfolio_expire(position_id=arguments["position_id"])


@tool_registry.register(
    name="optionplay_portfolio_expiring",
    description="List positions expiring within specified days. Helps manage upcoming expirations.",
    input_schema={
        "type": "object",
        "properties": {"days": {"type": "number"}},
    },
    aliases=["pf_expiring"],
    is_async=False,
)
def handle_portfolio_expiring(server, arguments):
    return server.portfolio_expiring(days=arguments.get("days", 7))


@tool_registry.register(
    name="optionplay_portfolio_trades",
    description="Show trade history with recent entries and exits.",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "number"}},
    },
    aliases=["pf_trades"],
    is_async=False,
)
def handle_portfolio_trades(server, arguments):
    return server.portfolio_trades(limit=arguments.get("limit", 20))


@tool_registry.register(
    name="optionplay_portfolio_pnl",
    description="Show realized P&L grouped by symbol. See which symbols are most profitable.",
    input_schema={"type": "object", "properties": {}},
    aliases=["pf_pnl"],
    is_async=False,
)
def handle_portfolio_pnl(server, arguments):
    return server.portfolio_pnl_symbols()


@tool_registry.register(
    name="optionplay_portfolio_monthly",
    description="Show monthly P&L report. Track performance over time.",
    input_schema={"type": "object", "properties": {}},
    aliases=["pf_monthly"],
    is_async=False,
)
def handle_portfolio_monthly(server, arguments):
    return server.portfolio_pnl_monthly()


# -----------------------------------------------------------------------------
# ADVANCED ANALYSIS
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_position_size",
    description="Calculate optimal position size using Kelly Criterion. Adjusts for VIX, signal quality, and portfolio exposure.",
    input_schema={
        "type": "object",
        "properties": {
            "account_size": {"type": "number"},
            "max_loss_per_contract": {"type": "number"},
            "win_rate": {"type": "number"},
            "avg_win": {"type": "number"},
            "avg_loss": {"type": "number"},
            "signal_score": {"type": "number"},
            "reliability_grade": {"type": "string"},
            "current_exposure": {"type": "number"},
        },
        "required": ["account_size", "max_loss_per_contract"],
    },
    aliases=["position_size"],
)
async def handle_position_size(server, arguments):
    return await server.calculate_position_size(
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
            "net_credit": {"type": "number"},
            "spread_width": {"type": "number"},
        },
        "required": ["net_credit", "spread_width"],
    },
    aliases=["stop_loss"],
)
async def handle_stop_loss(server, arguments):
    return await server.recommend_stop_loss(
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
            "dte": {"type": "number"},
            "contracts": {"type": "number"},
        },
        "required": ["symbol", "short_strike", "long_strike", "net_credit", "dte"],
    },
    aliases=["spread_analysis"],
)
async def handle_spread_analysis(server, arguments):
    return await server.analyze_spread(
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
            "dte": {"type": "number"},
            "num_simulations": {"type": "number"},
            "volatility": {"type": "number"},
        },
        "required": ["symbol", "short_strike", "long_strike", "net_credit"],
    },
    aliases=["monte_carlo"],
)
async def handle_monte_carlo(server, arguments):
    return await server.run_monte_carlo(
        symbol=arguments["symbol"],
        short_strike=arguments["short_strike"],
        long_strike=arguments["long_strike"],
        net_credit=arguments["net_credit"],
        dte=arguments.get("dte", 45),
        num_simulations=arguments.get("num_simulations", 500),
        volatility=arguments.get("volatility"),
    )


# -----------------------------------------------------------------------------
# DATA & MARKET TOOLS
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_historical",
    description="Get historical price data for a symbol. Shows recent price action.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "days": {"type": "number"},
        },
        "required": ["symbol"],
    },
    aliases=["historical"],
)
async def handle_historical(server, arguments):
    return await server.get_historical_data(
        symbol=arguments["symbol"],
        days=arguments.get("days", 30),
    )


@tool_registry.register(
    name="optionplay_expirations",
    description="List available options expiration dates for a symbol.",
    input_schema={
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
    aliases=["expirations"],
)
async def handle_expirations(server, arguments):
    return await server.get_expirations(symbol=arguments["symbol"])


@tool_registry.register(
    name="optionplay_events",
    description="Get upcoming market events (FOMC, OPEX, CPI, NFP). Helps plan around macro events.",
    input_schema={
        "type": "object",
        "properties": {"days": {"type": "number"}},
    },
    aliases=["events"],
)
async def handle_events(server, arguments):
    return await server.get_event_calendar(days=arguments.get("days", 30))


@tool_registry.register(
    name="optionplay_validate",
    description="Validate if a symbol is safe for trading based on earnings and events.",
    input_schema={
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
    aliases=["validate"],
)
async def handle_validate(server, arguments):
    return await server.validate_for_trading(symbol=arguments["symbol"])


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
async def handle_max_pain(server, arguments):
    return await server.get_max_pain(symbols=arguments["symbols"])


@tool_registry.register(
    name="optionplay_news",
    description="Get recent news headlines for symbols via IBKR. Requires TWS connection.",
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "days": {"type": "number"},
        },
        "required": ["symbols"],
    },
    aliases=["news"],
)
async def handle_news(server, arguments):
    return await server.get_news(
        symbols=arguments["symbols"],
        days=arguments.get("days", 5),
    )


# -----------------------------------------------------------------------------
# SYSTEM & MONITORING
# -----------------------------------------------------------------------------

@tool_registry.register(
    name="optionplay_cache_stats",
    description="Show cache statistics for historical data, quotes, and scan results. Monitor cache performance.",
    input_schema={"type": "object", "properties": {}},
    aliases=["cache_stats"],
    is_async=False,
)
def handle_cache_stats(server, arguments):
    return server.get_cache_stats()


@tool_registry.register(
    name="optionplay_watchlist_info",
    description="Show information about the current watchlist including total symbols and sectors.",
    input_schema={"type": "object", "properties": {}},
    aliases=["watchlist"],
    is_async=False,
)
def handle_watchlist_info(server, arguments):
    return server.get_watchlist_info()
