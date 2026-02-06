"""
OptionPlay MCP Server v4.0.0 - Claude Desktop Integration
=========================================================

MCP Server für Options Trading Analysis mit Multi-Strategie Support.

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

Verfügbare Tools (52 + Aliases):
- VIX & Strategy: vix, regime, strategy_stock, spread_width, events, health
- Scans: scan, bounce, breakout, dip, multi, prefilter
- Quotes & Data: quote, options, earnings, historical, expirations, validate, max_pain
- Analysis: analyze, analyze_multi, ensemble, ensemble_status, strikes
- Portfolio: portfolio, pf_positions, pf_position, pf_add, pf_close, pf_expire,
             pf_expiring, pf_trades, pf_pnl, pf_monthly, pf_check, pf_constraints
- IBKR: ibkr, ibkr_portfolio, ibkr_spreads, ibkr_vix, ibkr_quotes, news
- Reports: report, scan_report
- Risk: position_size, stop_loss, spread_analysis, monte_carlo
- System: cache_stats, watchlist
"""

import asyncio
import logging
import time
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Prompt, PromptMessage, PromptArgument

# IMPORTANT: Load .env file BEFORE importing other modules that need API keys
# This ensures environment variables are set before SecureConfig is used
from .utils.secure_config import get_secure_config
_config = get_secure_config()  # This triggers .env loading

from .mcp_server import OptionPlayServer
from .container import ServiceContainer
from .utils.metrics import api_requests, api_latency, errors
from .mcp_tool_registry import tool_registry

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MCP Server Instance
app = Server("optionplay")


# =============================================================================
# SERVER INITIALIZATION
# =============================================================================

_server: Optional[OptionPlayServer] = None
_container: Optional[ServiceContainer] = None


def get_server() -> OptionPlayServer:
    """Lazy initialization of OptionPlay server."""
    global _server, _container
    if _server is None:
        _container = ServiceContainer.create_default()
        _server = OptionPlayServer(container=_container)
    return _server


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available OptionPlay tools (52 tools + 52 aliases)."""
    return tool_registry.list_tools()


# =============================================================================
# WORKFLOW PROMPTS
# =============================================================================

WORKFLOW_PROMPTS = {
    "morning_scan": {
        "name": "Morgen-Scan",
        "description": "Vollständiger Morgen-Workflow: VIX prüfen, Earnings filtern, Multi-Strategie-Scan",
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
# TOOL HANDLER
# =============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Handle tool calls using the ToolRegistry.

    Dispatches to the appropriate handler based on tool name or alias.
    """
    server = get_server()
    start_time = time.time()
    status = "success"

    try:
        result = await tool_registry.dispatch(name, server, arguments)

    except ValueError as e:
        result = str(e)
        status = "unknown_tool"
        logger.warning(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        result = f"Error: {str(e)}"
        status = "error"
        errors.inc(labels={"type": type(e).__name__, "operation": name})

    finally:
        elapsed_ms = (time.time() - start_time) * 1000
        resolved_name = tool_registry.resolve_alias(name)
        api_requests.inc(labels={"endpoint": resolved_name, "status": status})
        api_latency.observe(elapsed_ms, labels={"endpoint": resolved_name})

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
