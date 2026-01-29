"""
OptionPlay MCP Server - Claude Desktop Integration
==================================================

Echter MCP Server der das JSON-RPC Protokoll über stdio spricht.
Wird von Claude Desktop als MCP Tool genutzt.

v3.5.0 - Complete Tool Exposure:
- Portfolio Management: positions, add, close, expire, expiring, trades, pnl, monthly
- Advanced Analysis: position_size, stop_loss, spread_analysis, monte_carlo
- Data & Market: historical, expirations, events, validate, max_pain, news

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
import time
from typing import Optional, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Prompt, PromptMessage, PromptArgument

from .mcp_server import OptionPlayServer
from .container import ServiceContainer
from .utils.metrics import api_requests, api_latency, errors

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MCP Server Instance
app = Server("optionplay")

# =============================================================================
# TOOL ALIASES - Kürzere Namen für schnelleres Tippen
# =============================================================================
TOOL_ALIASES = {
    # Kurze Aliase -> volle Namen
    "vix": "optionplay_vix",
    "scan": "optionplay_scan",
    "quote": "optionplay_quote",
    "options": "optionplay_options",
    "earnings": "optionplay_earnings",
    "analyze": "optionplay_analyze",
    "portfolio": "optionplay_ibkr_portfolio",
    "health": "optionplay_health",
    "bounce": "optionplay_scan_bounce",
    "breakout": "optionplay_scan_breakout",
    "dip": "optionplay_scan_earnings_dip",
    "multi": "optionplay_scan_multi",
    "analyze_multi": "optionplay_analyze_multi",
    "prefilter": "optionplay_earnings_prefilter",
    "strikes": "optionplay_recommend_strikes",
    "report": "optionplay_report",
    "scan_report": "optionplay_scan_report",
    "regime": "optionplay_regime_status",
    "ensemble": "optionplay_ensemble",
    "ensemble_status": "optionplay_ensemble_status",
    "ibkr": "optionplay_ibkr_status",
    "ibkr_portfolio": "optionplay_ibkr_portfolio",
    "ibkr_spreads": "optionplay_ibkr_spreads",
    "ibkr_vix": "optionplay_ibkr_vix",
    "ibkr_quotes": "optionplay_ibkr_quotes",
    # NEW: Portfolio Management
    "pf_positions": "optionplay_portfolio_positions",
    "pf_add": "optionplay_portfolio_add",
    "pf_close": "optionplay_portfolio_close",
    "pf_expire": "optionplay_portfolio_expire",
    "pf_expiring": "optionplay_portfolio_expiring",
    "pf_trades": "optionplay_portfolio_trades",
    "pf_pnl": "optionplay_portfolio_pnl",
    "pf_monthly": "optionplay_portfolio_monthly",
    # NEW: Advanced Analysis
    "position_size": "optionplay_position_size",
    "stop_loss": "optionplay_stop_loss",
    "spread_analysis": "optionplay_spread_analysis",
    "monte_carlo": "optionplay_monte_carlo",
    # NEW: Data & Market
    "historical": "optionplay_historical",
    "expirations": "optionplay_expirations",
    "events": "optionplay_events",
    "validate": "optionplay_validate",
    "max_pain": "optionplay_max_pain",
    "news": "optionplay_news",
    # NEW: System & Monitoring
    "cache_stats": "optionplay_cache_stats",
    "watchlist": "optionplay_watchlist_info",
}

def resolve_alias(name: str) -> str:
    """Löse Tool-Alias auf den vollen Namen auf."""
    return TOOL_ALIASES.get(name, name)

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

def _create_alias_tool(alias: str, full_name: str, base_tool: Tool) -> Tool:
    """Create an alias tool that references the original."""
    return Tool(
        name=alias,
        description=f"[Alias for {full_name}] {base_tool.description}",
        inputSchema=base_tool.inputSchema
    )

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available OptionPlay tools including short aliases."""

    # Define base tools
    base_tools = [
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
            description="Show INTERNAL tracking portfolio (manually tracked trades). NOTE: For LIVE positions from Interactive Brokers/TWS, use optionplay_ibkr_portfolio instead!",
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
        Tool(
            name="optionplay_regime_status",
            description="Get current VIX regime status with trained model recommendations. Shows regime, trading parameters, enabled strategies based on trained model.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_ensemble",
            description="Get ensemble strategy recommendation for a symbol. Uses meta-learner to select best strategy based on symbol history, regime, and confidence-weighted scoring.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol to analyze (e.g., 'AAPL')"
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="optionplay_ensemble_status",
            description="Get ensemble selector and strategy rotation status. Shows current strategy preferences, rotation triggers, and meta-learner insights.",
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
        # DETAILED REPORT
        # =====================================================================
        Tool(
            name="optionplay_report",
            description="Generate a detailed PDF report for a trading candidate. Includes summary, score breakdown, technical levels, options setup, and news. The PDF is saved to the reports/ directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "strategy": {
                        "type": "string",
                        "description": "Specific strategy (pullback, bounce, breakout, earnings_dip). If not specified, uses best matching.",
                        "enum": ["pullback", "bounce", "breakout", "earnings_dip"]
                    },
                    "include_options": {
                        "type": "boolean",
                        "description": "Include options strike recommendations (default: true)",
                        "default": True
                    },
                    "include_news": {
                        "type": "boolean",
                        "description": "Include recent news from Yahoo Finance (default: true)",
                        "default": True
                    }
                },
                "required": ["symbol"]
            }
        ),

        # =====================================================================
        # SCAN REPORT
        # =====================================================================
        Tool(
            name="optionplay_scan_report",
            description="Generate a comprehensive multi-symbol PDF scan report. Creates a 13-page professional report with: Cover page, market environment analysis, scan results, earnings filter, support analysis, qualified candidates, fundamental analysis (top 2), trade setups with Volume Profile (top 2), comparison, and risk management. PDF is saved to reports/ directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "string",
                        "description": "Scan strategy (default: multi)",
                        "enum": ["multi", "pullback", "bounce", "breakout", "earnings_dip"],
                        "default": "multi"
                    },
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of symbols to scan (uses default watchlist if not provided)"
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum score for qualification (default: 5.0)",
                        "default": 5.0
                    },
                    "max_candidates": {
                        "type": "integer",
                        "description": "Maximum candidates to include in report (default: 20)",
                        "default": 20
                    }
                },
                "required": []
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
            description="Get LIVE portfolio positions from Interactive Brokers TWS. This is the PRIMARY portfolio tool - use this to see actual open positions, spreads, and P&L. Requires TWS connection.",
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

        # =====================================================================
        # PORTFOLIO MANAGEMENT (NEW)
        # =====================================================================
        Tool(
            name="optionplay_portfolio_positions",
            description="List portfolio positions with optional status filter. Shows all tracked Bull-Put-Spread positions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: 'open', 'closed', or 'all' (default: 'all')",
                        "enum": ["open", "closed", "all"],
                        "default": "all"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_portfolio_add",
            description="Add a new Bull-Put-Spread position to tracking. Records entry for P&L tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "short_strike": {
                        "type": "number",
                        "description": "Strike price of the short put"
                    },
                    "long_strike": {
                        "type": "number",
                        "description": "Strike price of the long put (must be lower than short)"
                    },
                    "expiration": {
                        "type": "string",
                        "description": "Expiration date (YYYY-MM-DD format)"
                    },
                    "credit": {
                        "type": "number",
                        "description": "Net credit received per share"
                    },
                    "contracts": {
                        "type": "integer",
                        "description": "Number of contracts (default: 1)",
                        "default": 1
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes for the position",
                        "default": ""
                    }
                },
                "required": ["symbol", "short_strike", "long_strike", "expiration", "credit"]
            }
        ),
        Tool(
            name="optionplay_portfolio_close",
            description="Close a position by buying back the spread. Records the closing premium and calculates P&L.",
            inputSchema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "Position ID to close"
                    },
                    "close_premium": {
                        "type": "number",
                        "description": "Premium paid to close (cost to buy back)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional closing notes",
                        "default": ""
                    }
                },
                "required": ["position_id", "close_premium"]
            }
        ),
        Tool(
            name="optionplay_portfolio_expire",
            description="Mark a position as expired worthless. Records full credit as profit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "Position ID to mark as expired"
                    }
                },
                "required": ["position_id"]
            }
        ),
        Tool(
            name="optionplay_portfolio_expiring",
            description="List positions expiring within specified days. Helps manage upcoming expirations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to look ahead (default: 7)",
                        "default": 7
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_portfolio_trades",
            description="Show trade history with recent entries and exits.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of trades to show (default: 20)",
                        "default": 20
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_portfolio_pnl",
            description="Show realized P&L grouped by symbol. See which symbols are most profitable.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_portfolio_monthly",
            description="Show monthly P&L report. Track performance over time.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),

        # =====================================================================
        # ADVANCED ANALYSIS (NEW)
        # =====================================================================
        Tool(
            name="optionplay_position_size",
            description="Calculate optimal position size using Kelly Criterion. Adjusts for VIX, signal quality, and portfolio exposure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_size": {
                        "type": "number",
                        "description": "Total account value in USD"
                    },
                    "max_loss_per_contract": {
                        "type": "number",
                        "description": "Maximum loss per contract in USD"
                    },
                    "win_rate": {
                        "type": "number",
                        "description": "Historical win rate (0.0-1.0, default: 0.65)",
                        "default": 0.65
                    },
                    "avg_win": {
                        "type": "number",
                        "description": "Average winning trade in USD (default: 100)",
                        "default": 100
                    },
                    "avg_loss": {
                        "type": "number",
                        "description": "Average losing trade in USD (default: 350)",
                        "default": 350
                    },
                    "signal_score": {
                        "type": "number",
                        "description": "Signal quality score 0-10 (default: 7.0)",
                        "default": 7.0
                    },
                    "reliability_grade": {
                        "type": "string",
                        "description": "Optional reliability grade (A, B, C, D, F)",
                        "enum": ["A", "B", "C", "D", "F"]
                    },
                    "current_exposure": {
                        "type": "number",
                        "description": "Current portfolio exposure in USD (default: 0)",
                        "default": 0
                    }
                },
                "required": ["account_size", "max_loss_per_contract"]
            }
        ),
        Tool(
            name="optionplay_stop_loss",
            description="Get recommended stop loss level for a credit spread. Adjusts based on VIX regime.",
            inputSchema={
                "type": "object",
                "properties": {
                    "net_credit": {
                        "type": "number",
                        "description": "Net credit received per share"
                    },
                    "spread_width": {
                        "type": "number",
                        "description": "Width of the spread in dollars"
                    }
                },
                "required": ["net_credit", "spread_width"]
            }
        ),
        Tool(
            name="optionplay_spread_analysis",
            description="Analyze a Bull-Put-Spread with comprehensive risk/reward metrics, probabilities, and P&L scenarios.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "short_strike": {
                        "type": "number",
                        "description": "Strike price of short put"
                    },
                    "long_strike": {
                        "type": "number",
                        "description": "Strike price of long put"
                    },
                    "net_credit": {
                        "type": "number",
                        "description": "Net credit received per share"
                    },
                    "dte": {
                        "type": "integer",
                        "description": "Days to expiration"
                    },
                    "contracts": {
                        "type": "integer",
                        "description": "Number of contracts (default: 1)",
                        "default": 1
                    }
                },
                "required": ["symbol", "short_strike", "long_strike", "net_credit", "dte"]
            }
        ),
        Tool(
            name="optionplay_monte_carlo",
            description="Run Monte Carlo simulation for a Bull-Put-Spread. Simulates price paths to estimate outcome probabilities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "short_strike": {
                        "type": "number",
                        "description": "Strike price of short put"
                    },
                    "long_strike": {
                        "type": "number",
                        "description": "Strike price of long put"
                    },
                    "net_credit": {
                        "type": "number",
                        "description": "Net credit received per share"
                    },
                    "dte": {
                        "type": "integer",
                        "description": "Days to expiration (default: 45)",
                        "default": 45
                    },
                    "num_simulations": {
                        "type": "integer",
                        "description": "Number of simulations (default: 500, max: 2000)",
                        "default": 500
                    },
                    "volatility": {
                        "type": "number",
                        "description": "Optional volatility override (e.g., 0.30 = 30%)"
                    }
                },
                "required": ["symbol", "short_strike", "long_strike", "net_credit"]
            }
        ),

        # =====================================================================
        # DATA & MARKET TOOLS (NEW)
        # =====================================================================
        Tool(
            name="optionplay_historical",
            description="Get historical price data for a symbol. Shows recent price action.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days of history (default: 30)",
                        "default": 30
                    }
                },
                "required": ["symbol"]
            }
        ),
        Tool(
            name="optionplay_expirations",
            description="List available options expiration dates for a symbol.",
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
            name="optionplay_events",
            description="Get upcoming market events (FOMC, OPEX, CPI, NFP). Helps plan around macro events.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to look ahead (default: 30)",
                        "default": 30
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="optionplay_validate",
            description="Validate if a symbol is safe for trading based on earnings and events.",
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
            name="optionplay_max_pain",
            description="Calculate Max Pain level for symbols. Shows where maximum options pain occurs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of symbols to calculate max pain for"
                    }
                },
                "required": ["symbols"]
            }
        ),
        Tool(
            name="optionplay_news",
            description="Get recent news headlines for symbols via IBKR. Requires TWS connection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of symbols to get news for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days of news (default: 5)",
                        "default": 5
                    }
                },
                "required": ["symbols"]
            }
        ),

        # =====================================================================
        # SYSTEM & MONITORING (NEW)
        # =====================================================================
        Tool(
            name="optionplay_cache_stats",
            description="Show cache statistics for historical data, quotes, and scan results. Monitor cache performance.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="optionplay_watchlist_info",
            description="Show information about the current watchlist including total symbols and sectors.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
    ]

    # Create alias tools for shorter names
    alias_tools = []
    tool_by_name = {t.name: t for t in base_tools}

    for alias, full_name in TOOL_ALIASES.items():
        if full_name in tool_by_name:
            alias_tools.append(_create_alias_tool(alias, full_name, tool_by_name[full_name]))

    return base_tools + alias_tools


# =============================================================================
# WORKFLOW PROMPTS - Vordefinierte Workflows für häufige Aufgaben
# =============================================================================

WORKFLOW_PROMPTS = {
    "morning_scan": {
        "name": "Morgen-Scan",
        "description": "Vollständiger Morgen-Workflow: VIX prüfen, Earnings filtern, Multi-Strategie-Scan durchführen",
        "prompt": """Führe den vollständigen Morgen-Scan durch:

1. Prüfe den aktuellen VIX und die empfohlene Strategie
2. Führe einen Earnings Pre-Filter durch (min 45 Tage)
3. Scanne mit Multi-Strategie die gefilterten Symbole
4. Zeige die Top 5 Kandidaten mit ihrer besten Strategie

Fasse die Ergebnisse übersichtlich zusammen."""
    },
    "analyze_symbol": {
        "name": "Symbol-Analyse",
        "description": "Vollständige Analyse eines Symbols mit Strike-Empfehlungen",
        "arguments": [
            PromptArgument(name="symbol", description="Aktien-Symbol (z.B. AAPL)", required=True)
        ],
        "prompt": """Analysiere {symbol} vollständig für einen Bull-Put-Spread:

1. Hole den aktuellen Kurs
2. Prüfe Earnings (min 60 Tage)
3. Führe Multi-Strategie-Analyse durch
4. Hole Strike-Empfehlungen
5. Zeige Options-Chain für die empfohlenen Strikes

Gib eine klare Handelsempfehlung."""
    },
    "quick_scan": {
        "name": "Schnell-Scan",
        "description": "Schneller Scan nach den besten aktuellen Kandidaten",
        "prompt": """Führe einen schnellen Scan durch:

1. Prüfe VIX
2. Scanne nach Pullback-Kandidaten (Top 5)

Zeige die Ergebnisse kompakt an."""
    },
    "earnings_check": {
        "name": "Earnings-Check",
        "description": "Prüfe welche Symbole sichere Earnings-Abstände haben",
        "prompt": """Prüfe die Earnings-Situation:

1. Führe Earnings Pre-Filter durch (45 Tage)
2. Zeige wie viele Symbole sicher sind
3. Liste die nächsten 10 Earnings-Termine

Dies hilft bei der Planung der nächsten Trades."""
    },
    "portfolio_review": {
        "name": "Portfolio-Review",
        "description": "Überprüfe aktuelle Positionen und deren Status",
        "prompt": """Führe ein Portfolio-Review durch:

1. Zeige Portfolio-Übersicht
2. Prüfe IBKR-Status (falls verfügbar)
3. Zeige offene Spreads
4. Gib einen Gesamt-P&L-Überblick"""
    },
    "setup_trade": {
        "name": "Trade-Setup",
        "description": "Vollständiges Setup für einen neuen Trade",
        "arguments": [
            PromptArgument(name="symbol", description="Aktien-Symbol", required=True),
            PromptArgument(name="dte", description="Tage bis Verfall (z.B. 45)", required=False)
        ],
        "prompt": """Bereite einen Trade für {symbol} vor:

1. Aktueller Kurs und VIX-Strategie
2. Earnings-Check (muss >60 Tage sein)
3. Technische Analyse (Support, Fibonacci)
4. Strike-Empfehlungen mit {dte} DTE (falls angegeben, sonst 30-60)
5. Options-Chain mit Bid/Ask
6. Zusammenfassung: Empfohlener Spread, Credit, Max Risk, P(Profit)"""
    }
}


@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available workflow prompts."""
    prompts = []
    for key, workflow in WORKFLOW_PROMPTS.items():
        prompts.append(Prompt(
            name=key,
            description=workflow["description"],
            arguments=workflow.get("arguments", [])
        ))
    return prompts


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> list[PromptMessage]:
    """Get a specific workflow prompt."""
    if name not in WORKFLOW_PROMPTS:
        raise ValueError(f"Unknown prompt: {name}")

    workflow = WORKFLOW_PROMPTS[name]
    prompt_text = workflow["prompt"]

    # Replace placeholders with arguments
    if arguments:
        for key, value in arguments.items():
            prompt_text = prompt_text.replace(f"{{{key}}}", str(value))

    return [
        PromptMessage(
            role="user",
            content=TextContent(type="text", text=prompt_text)
        )
    ]


# =============================================================================
# TOOL HANDLERS
# =============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls with alias support."""
    server = get_server()
    start_time = time.time()
    status = "success"

    # Resolve alias to full tool name
    name = resolve_alias(name)

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

        elif name == "optionplay_regime_status":
            result = await server.get_regime_status()

        elif name == "optionplay_ensemble":
            symbol = arguments["symbol"]
            result = await server.get_ensemble_recommendation(symbol)

        elif name == "optionplay_ensemble_status":
            result = await server.get_ensemble_status()

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
        # DETAILED REPORT
        # =================================================================
        elif name == "optionplay_report":
            symbol = arguments["symbol"]
            strategy = arguments.get("strategy")
            include_options = arguments.get("include_options", True)
            include_news = arguments.get("include_news", True)
            result = await server.generate_report(
                symbol=symbol,
                strategy=strategy,
                include_options=include_options,
                include_news=include_news
            )

        # =================================================================
        # SCAN REPORT
        # =================================================================
        elif name == "optionplay_scan_report":
            strategy = arguments.get("strategy", "multi")
            symbols = arguments.get("symbols")
            min_score = arguments.get("min_score", 5.0)
            max_candidates = arguments.get("max_candidates", 20)
            result = await server.generate_scan_report(
                strategy=strategy,
                symbols=symbols,
                min_score=min_score,
                max_candidates=max_candidates
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

        # =================================================================
        # PORTFOLIO MANAGEMENT (NEW)
        # =================================================================
        elif name == "optionplay_portfolio_positions":
            status_filter = arguments.get("status", "all")
            result = server.portfolio_positions(status=status_filter)

        elif name == "optionplay_portfolio_add":
            result = server.portfolio_add(
                symbol=arguments["symbol"],
                short_strike=arguments["short_strike"],
                long_strike=arguments["long_strike"],
                expiration=arguments["expiration"],
                credit=arguments["credit"],
                contracts=arguments.get("contracts", 1),
                notes=arguments.get("notes", ""),
            )

        elif name == "optionplay_portfolio_close":
            result = server.portfolio_close(
                position_id=arguments["position_id"],
                close_premium=arguments["close_premium"],
                notes=arguments.get("notes", ""),
            )

        elif name == "optionplay_portfolio_expire":
            result = server.portfolio_expire(
                position_id=arguments["position_id"]
            )

        elif name == "optionplay_portfolio_expiring":
            days = arguments.get("days", 7)
            result = server.portfolio_expiring(days=days)

        elif name == "optionplay_portfolio_trades":
            limit = arguments.get("limit", 20)
            result = server.portfolio_trades(limit=limit)

        elif name == "optionplay_portfolio_pnl":
            result = server.portfolio_pnl_symbols()

        elif name == "optionplay_portfolio_monthly":
            result = server.portfolio_pnl_monthly()

        # =================================================================
        # ADVANCED ANALYSIS (NEW)
        # =================================================================
        elif name == "optionplay_position_size":
            result = await server.calculate_position_size(
                account_size=arguments["account_size"],
                max_loss_per_contract=arguments["max_loss_per_contract"],
                win_rate=arguments.get("win_rate", 0.65),
                avg_win=arguments.get("avg_win", 100),
                avg_loss=arguments.get("avg_loss", 350),
                signal_score=arguments.get("signal_score", 7.0),
                reliability_grade=arguments.get("reliability_grade"),
                current_exposure=arguments.get("current_exposure", 0),
            )

        elif name == "optionplay_stop_loss":
            result = await server.recommend_stop_loss(
                net_credit=arguments["net_credit"],
                spread_width=arguments["spread_width"],
            )

        elif name == "optionplay_spread_analysis":
            result = await server.analyze_spread(
                symbol=arguments["symbol"],
                short_strike=arguments["short_strike"],
                long_strike=arguments["long_strike"],
                net_credit=arguments["net_credit"],
                dte=arguments["dte"],
                contracts=arguments.get("contracts", 1),
            )

        elif name == "optionplay_monte_carlo":
            result = await server.run_monte_carlo(
                symbol=arguments["symbol"],
                short_strike=arguments["short_strike"],
                long_strike=arguments["long_strike"],
                net_credit=arguments["net_credit"],
                dte=arguments.get("dte", 45),
                num_simulations=arguments.get("num_simulations", 500),
                volatility=arguments.get("volatility"),
            )

        # =================================================================
        # DATA & MARKET TOOLS (NEW)
        # =================================================================
        elif name == "optionplay_historical":
            result = await server.get_historical_data(
                symbol=arguments["symbol"],
                days=arguments.get("days", 30),
            )

        elif name == "optionplay_expirations":
            result = await server.get_expirations(
                symbol=arguments["symbol"]
            )

        elif name == "optionplay_events":
            result = await server.get_event_calendar(
                days=arguments.get("days", 30)
            )

        elif name == "optionplay_validate":
            result = await server.validate_for_trading(
                symbol=arguments["symbol"]
            )

        elif name == "optionplay_max_pain":
            result = await server.get_max_pain(
                symbols=arguments["symbols"]
            )

        elif name == "optionplay_news":
            result = await server.get_news(
                symbols=arguments["symbols"],
                days=arguments.get("days", 5),
            )

        # =================================================================
        # SYSTEM & MONITORING (NEW)
        # =================================================================
        elif name == "optionplay_cache_stats":
            result = server.get_cache_stats()

        elif name == "optionplay_watchlist_info":
            result = server.get_watchlist_info()

        else:
            result = f"Unknown tool: {name}"
            status = "unknown_tool"

    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        result = f"❌ Error: {str(e)}"
        status = "error"
        errors.inc(labels={"type": type(e).__name__, "operation": name})

    finally:
        # Record metrics
        elapsed_ms = (time.time() - start_time) * 1000
        api_requests.inc(labels={"endpoint": name, "status": status})
        api_latency.observe(elapsed_ms, labels={"endpoint": name})

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
