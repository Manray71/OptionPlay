"""
OptionPlay MCP Server - Entry Point

Startet den MCP Server für Options-Trading-Analyse.

Verwendung:
    python -m src.mcp_server
    python -m src.mcp_server --transport http --http-port 8001
"""

from .mcp_server import main

if __name__ == "__main__":
    main()
