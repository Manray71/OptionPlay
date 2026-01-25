"""
OptionPlay MCP Server - Claude Desktop Integration
==================================================

Echter MCP Server der das JSON-RPC Protokoll über stdio spricht.
Wird von Claude Desktop als MCP Tool genutzt.

v3.4.0 - Strike Recommender:
- optionplay_recommend_strikes: Optimale Strike-Empfehlungen für Bull-Put-Spreads

v3.3.0 - Workflow Optimization:
- optionplay_earnings_prefilter: Earnings Pre-Filter mit 4-Wochen-Cache

v3.2.0 - Multi-Strategy Support:
- optionplay_scan_bounce: Support Bounce Scanner
- optionplay_scan_breakout: ATH Breakout Scanner
- optionplay_scan_earnings_dip: Earnings Dip Scanner
- optionplay_scan_multi: Multi-Strategy Scanner (alle Strategien)

Verwendung in claude_desktop_config.json:
{
  "mcpServers": {
    "optionplay": {
      "command": "python3",
      "args": ["-m", "src.mcp_main"],
      "cwd": "/Users/larschristiansen/OptionPlay"
    }
  }
}
"""

import asyncio
import logging
from typing import Optional, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .mcp_server import OptionPlayServer
from .container import ServiceContainer

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MCP Server Instance
app = Server("optionplay")

# OptionPlay Server (lazy init)
_server: Optional[OptionPlayServer] = None
_container: Optional[ServiceContainer] = None


def get_server() -> OptionPlayServer:
    """Lazy initialization of OptionPlay server with container."""
    global _server, _container
    if _server is None:
        # Create container with default services
        _container = ServiceContainer.create_default()
        _server = OptionPlayServer(container=_container)
    return _server


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available OptionPlay tools."""
    return [
        # =====================================================================
        # CORE TOOLS
        # =====================================================================
        Tool(
            name="optionplay_vix",
            description="Get current VIX level and strategy recommendation based on market volatility.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_scan",
            description="Scan watchlist for pullback candidates suitable for Bull-Put-Spreads. Uses VIX-based strategy selection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of candidates to return (default: 10)",
                        "default": 10
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols to scan (default: full watchlist)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_quote",
            description="Get current stock quote with bid/ask/volume.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL)"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="optionplay_options",
            description="Get options chain for a symbol with Greeks and IV.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "dte_min": {
                        "type": "integer",
                        "description": "Minimum days to expiration (default: 30)",
                        "default": 30
                    },
                    "dte_max": {
                        "type": "integer",
                        "description": "Maximum days to expiration (default: 60)",
                        "default": 60
                    },
                    "right": {
                        "type": "string",
                        "description": "Option type: P for puts, C for calls (default: P)",
                        "default": "P"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="optionplay_earnings",
            description="Check earnings date for a symbol. Returns safety status for trading.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "min_days": {
                        "type": "integer",
                        "description": "Minimum days buffer before earnings (default: 60)",
                        "default": 60
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="optionplay_analyze",
            description="Complete analysis of a symbol for Bull-Put-Spread suitability.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="optionplay_portfolio",
            description="Show portfolio summary with P&L, open positions, and statistics.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_health",
            description="Check server health and configuration status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        
        # =====================================================================
        # MULTI-STRATEGY SCANNERS (NEW)
        # =====================================================================
        Tool(
            name="optionplay_scan_bounce",
            description="Scan for Support Bounce candidates - stocks bouncing off established support levels. Good for long entries (stock or calls).",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of candidates to return (default: 10)",
                        "default": 10
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols to scan (default: full watchlist)"
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum bounce score (default: 5.0)",
                        "default": 5.0
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_scan_breakout",
            description="Scan for ATH Breakout candidates - stocks breaking out to new all-time highs with volume confirmation. Good for momentum trades.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of candidates to return (default: 10)",
                        "default": 10
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols to scan (default: full watchlist)"
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum breakout score (default: 6.0)",
                        "default": 6.0
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_scan_earnings_dip",
            description="Scan for Earnings Dip Buy candidates - quality stocks that dropped 5-15% after earnings (potential overreaction). Contrarian play.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of candidates to return (default: 10)",
                        "default": 10
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols to scan (default: full watchlist)"
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum earnings dip score (default: 5.0)",
                        "default": 5.0
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_scan_multi",
            description="Multi-Strategy Scan - runs all strategies (Pullback, Bounce, ATH Breakout, Earnings Dip) and returns the best signal per symbol. Shows which strategy is optimal for each candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of candidates to return (default: 20)",
                        "default": 20
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols to scan (default: full watchlist)"
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum score across any strategy (default: 5.0)",
                        "default": 5.0
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_analyze_multi",
            description="Multi-Strategy Analysis for a single symbol - analyzes which strategies are suitable and returns scores for each.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    }
                },
                "required": ["symbol"]
            }
        ),
        
        # =====================================================================
        # EARNINGS PREFILTER (NEW - WORKFLOW OPTIMIZATION)
        # =====================================================================
        Tool(
            name="optionplay_earnings_prefilter",
            description="Pre-filter watchlist by earnings dates. Returns only symbols with earnings > X days away. Uses 4-week cache. This should be the FIRST step before any scan to avoid wasting API calls on symbols with upcoming earnings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_days": {
                        "type": "integer",
                        "description": "Minimum days until earnings (default: 45)",
                        "default": 45
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols to check (default: full watchlist)"
                    },
                    "show_excluded": {
                        "type": "boolean",
                        "description": "Show excluded symbols with their earnings dates (default: false)",
                        "default": False
                    }
                },
                "required": []
            }
        ),
        
        # =====================================================================
        # STRIKE RECOMMENDER (NEW)
        # =====================================================================
        Tool(
            name="optionplay_recommend_strikes",
            description="Generate optimal strike recommendations for Bull-Put-Spreads. Analyzes support levels, Fibonacci retracements, and options chain to recommend short/long strike combinations with quality scores.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "dte_min": {
                        "type": "integer",
                        "description": "Minimum days to expiration (default: 30)",
                        "default": 30
                    },
                    "dte_max": {
                        "type": "integer",
                        "description": "Maximum days to expiration (default: 60)",
                        "default": 60
                    },
                    "num_alternatives": {
                        "type": "integer",
                        "description": "Number of alternative recommendations (default: 3)",
                        "default": 3
                    }
                },
                "required": ["symbol"]
            }
        ),
        
        # =====================================================================
        # IBKR BRIDGE TOOLS
        # =====================================================================
        Tool(
            name="optionplay_ibkr_status",
            description="Check IBKR/TWS connection status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_ibkr_portfolio",
            description="Get portfolio positions from IBKR/TWS.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_ibkr_spreads",
            description="Get identified spread positions from IBKR/TWS.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_ibkr_vix",
            description="Get live VIX from IBKR with source indicator.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_ibkr_quotes",
            description="Get batch quotes for watchlist from IBKR.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: specific symbols (default: full watchlist)"
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Symbols per batch (default: 50)",
                        "default": 50
                    }
                },
                "required": []
            }
        ),
    ]


# =============================================================================
# TOOL HANDLERS
# =============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    server = get_server()
    
    try:
        # =================================================================
        # CORE TOOLS
        # =================================================================
        if name == "optionplay_vix":
            result = await server.get_strategy_recommendation()
            
        elif name == "optionplay_scan":
            max_results = arguments.get("max_results", 10)
            symbols = arguments.get("symbols")
            result = await server.scan_with_strategy(
                symbols=symbols,
                max_results=max_results
            )
            
        elif name == "optionplay_quote":
            symbol = arguments["symbol"]
            result = await server.get_quote(symbol)
            
        elif name == "optionplay_options":
            symbol = arguments["symbol"]
            dte_min = arguments.get("dte_min", 30)
            dte_max = arguments.get("dte_max", 60)
            right = arguments.get("right", "P")
            result = await server.get_options_chain(
                symbol=symbol,
                dte_min=dte_min,
                dte_max=dte_max,
                right=right
            )
            
        elif name == "optionplay_earnings":
            symbol = arguments["symbol"]
            min_days = arguments.get("min_days", 60)
            result = await server.get_earnings_aggregated(symbol, min_days)
            
        elif name == "optionplay_analyze":
            symbol = arguments["symbol"]
            result = await server.analyze_symbol(symbol)
            
        elif name == "optionplay_portfolio":
            result = server.portfolio_summary()
            
        elif name == "optionplay_health":
            result = await server.health_check()
        
        # =================================================================
        # MULTI-STRATEGY SCANNERS (NEW)
        # =================================================================
        elif name == "optionplay_scan_bounce":
            max_results = arguments.get("max_results", 10)
            symbols = arguments.get("symbols")
            min_score = arguments.get("min_score", 5.0)
            result = await server.scan_bounce(
                symbols=symbols,
                max_results=max_results,
                min_score=min_score
            )
            
        elif name == "optionplay_scan_breakout":
            max_results = arguments.get("max_results", 10)
            symbols = arguments.get("symbols")
            min_score = arguments.get("min_score", 6.0)
            result = await server.scan_ath_breakout(
                symbols=symbols,
                max_results=max_results,
                min_score=min_score
            )
            
        elif name == "optionplay_scan_earnings_dip":
            max_results = arguments.get("max_results", 10)
            symbols = arguments.get("symbols")
            min_score = arguments.get("min_score", 5.0)
            result = await server.scan_earnings_dip(
                symbols=symbols,
                max_results=max_results,
                min_score=min_score
            )
            
        elif name == "optionplay_scan_multi":
            max_results = arguments.get("max_results", 20)
            symbols = arguments.get("symbols")
            min_score = arguments.get("min_score", 5.0)
            result = await server.scan_multi_strategy(
                symbols=symbols,
                max_results=max_results,
                min_score=min_score
            )
            
        elif name == "optionplay_analyze_multi":
            symbol = arguments["symbol"]
            result = await server.analyze_multi_strategy(symbol)
        
        # =================================================================
        # EARNINGS PREFILTER (NEW)
        # =================================================================
        elif name == "optionplay_earnings_prefilter":
            min_days = arguments.get("min_days", 45)
            symbols = arguments.get("symbols")
            show_excluded = arguments.get("show_excluded", False)
            result = await server.earnings_prefilter(
                min_days=min_days,
                symbols=symbols,
                show_excluded=show_excluded
            )
        
        # =================================================================
        # STRIKE RECOMMENDER (NEW)
        # =================================================================
        elif name == "optionplay_recommend_strikes":
            symbol = arguments["symbol"]
            dte_min = arguments.get("dte_min", 30)
            dte_max = arguments.get("dte_max", 60)
            num_alternatives = arguments.get("num_alternatives", 3)
            result = await server.recommend_strikes(
                symbol=symbol,
                dte_min=dte_min,
                dte_max=dte_max,
                num_alternatives=num_alternatives
            )
            
        # =================================================================
        # IBKR BRIDGE TOOLS
        # =================================================================
        elif name == "optionplay_ibkr_status":
            result = await server.get_ibkr_status()
            
        elif name == "optionplay_ibkr_portfolio":
            result = await server.get_ibkr_portfolio()
            
        elif name == "optionplay_ibkr_spreads":
            result = await server.get_ibkr_spreads()
            
        elif name == "optionplay_ibkr_vix":
            result = await server.get_ibkr_vix()
            
        elif name == "optionplay_ibkr_quotes":
            symbols = arguments.get("symbols")
            batch_size = arguments.get("batch_size", 50)
            result = await server.get_ibkr_quotes(
                symbols=symbols,
                batch_size=batch_size
            )
            
        else:
            result = f"Unknown tool: {name}"
            
    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        result = f"❌ Error: {str(e)}"
    
    return [TextContent(type="text", text=result)]


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
