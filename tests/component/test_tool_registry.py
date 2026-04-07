# Tests for MCP Tool Registry
# ============================
"""
Comprehensive tests for the MCP Tool Registry.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from typing import Dict, Any

from src.mcp_tool_registry import (
    ToolDefinition,
    ToolRegistry,
    EMPTY_SCHEMA,
    SYMBOL_SCHEMA,
    SCAN_SCHEMA,
)


# =============================================================================
# TOOL DEFINITION TESTS
# =============================================================================

class TestToolDefinition:
    """Tests for ToolDefinition dataclass."""

    def test_create_tool_definition(self):
        """Test creating a ToolDefinition."""
        async def handler(server, args):
            return "result"

        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            handler=handler,
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.is_async is True
        assert tool.aliases == []

    def test_tool_definition_with_aliases(self):
        """Test ToolDefinition with aliases."""
        async def handler(server, args):
            return "result"

        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            handler=handler,
            aliases=["alias1", "alias2"],
        )

        assert tool.aliases == ["alias1", "alias2"]

    def test_tool_definition_sync(self):
        """Test ToolDefinition with sync handler."""
        def handler(server, args):
            return "result"

        tool = ToolDefinition(
            name="sync_tool",
            description="A sync tool",
            input_schema={"type": "object"},
            handler=handler,
            is_async=False,
        )

        assert tool.is_async is False


# =============================================================================
# TOOL REGISTRY TESTS
# =============================================================================

class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_init_empty(self):
        """Test registry starts empty."""
        registry = ToolRegistry()

        assert registry.tool_count == 0
        assert registry.alias_count == 0

    def test_register_tool(self):
        """Test registering a tool."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_test",
            description="Test tool",
            input_schema={"type": "object"},
        )
        async def handle_test(server, args):
            return "result"

        assert registry.tool_count == 1
        assert registry.has_tool("optionplay_test")

    def test_register_tool_with_aliases(self):
        """Test registering a tool with aliases."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_quote",
            description="Get quote",
            input_schema=SYMBOL_SCHEMA,
            aliases=["quote", "q"],
        )
        async def handle_quote(server, args):
            return "quote"

        assert registry.tool_count == 1
        assert registry.alias_count == 2
        assert registry.has_tool("optionplay_quote")
        assert registry.has_tool("quote")
        assert registry.has_tool("q")

    def test_resolve_alias(self):
        """Test resolving an alias to the main tool name."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_vix",
            description="Get VIX",
            input_schema=EMPTY_SCHEMA,
            aliases=["vix"],
        )
        async def handle_vix(server, args):
            return "vix"

        assert registry.resolve_alias("vix") == "optionplay_vix"
        assert registry.resolve_alias("optionplay_vix") == "optionplay_vix"
        assert registry.resolve_alias("unknown") == "unknown"  # Returns same if not found

    def test_has_tool(self):
        """Test has_tool checks both name and aliases."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_scan",
            description="Scan",
            input_schema=SCAN_SCHEMA,
            aliases=["scan"],
        )
        async def handle_scan(server, args):
            return "scan"

        assert registry.has_tool("optionplay_scan") is True
        assert registry.has_tool("scan") is True
        assert registry.has_tool("unknown") is False

    def test_get_tool(self):
        """Test getting a tool definition."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_analyze",
            description="Analyze stock",
            input_schema=SYMBOL_SCHEMA,
            aliases=["analyze"],
        )
        async def handle_analyze(server, args):
            return "analysis"

        tool = registry.get_tool("optionplay_analyze")
        assert tool is not None
        assert tool.name == "optionplay_analyze"
        assert tool.description == "Analyze stock"

        # Get via alias
        tool_alias = registry.get_tool("analyze")
        assert tool_alias is not None
        assert tool_alias.name == "optionplay_analyze"

    def test_get_tool_unknown_returns_none(self):
        """Test get_tool returns None for unknown tool."""
        registry = ToolRegistry()
        assert registry.get_tool("unknown") is None

    @pytest.mark.asyncio
    async def test_dispatch_async(self):
        """Test dispatching an async tool."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_test",
            description="Test",
            input_schema={"type": "object"},
        )
        async def handle_test(server, arguments):
            return f"Called with {arguments.get('param')}"

        server = MagicMock()
        result = await registry.dispatch("optionplay_test", server, {"param": "value"})

        assert result == "Called with value"

    @pytest.mark.asyncio
    async def test_dispatch_via_alias(self):
        """Test dispatching via alias."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_quote",
            description="Quote",
            input_schema=SYMBOL_SCHEMA,
            aliases=["quote"],
        )
        async def handle_quote(server, arguments):
            return f"Quote for {arguments.get('symbol')}"

        server = MagicMock()
        result = await registry.dispatch("quote", server, {"symbol": "AAPL"})

        assert result == "Quote for AAPL"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_raises(self):
        """Test dispatch raises for unknown tool."""
        registry = ToolRegistry()

        server = MagicMock()
        with pytest.raises(ValueError) as exc:
            await registry.dispatch("unknown_tool", server, {})

        assert "Unknown tool" in str(exc.value)

    @pytest.mark.asyncio
    async def test_dispatch_sync_tool(self):
        """Test dispatching a sync tool."""
        registry = ToolRegistry()

        @registry.register(
            name="sync_tool",
            description="Sync tool",
            input_schema=EMPTY_SCHEMA,
            is_async=False,
        )
        def handle_sync(server, arguments):
            return "sync result"

        server = MagicMock()
        result = await registry.dispatch("sync_tool", server, {})

        assert result == "sync result"

    def test_list_tools(self):
        """Test listing all tools."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_vix",
            description="VIX info",
            input_schema=EMPTY_SCHEMA,
            aliases=["vix"],
        )
        async def handle_vix(server, args):
            return "vix"

        @registry.register(
            name="optionplay_quote",
            description="Quote",
            input_schema=SYMBOL_SCHEMA,
            aliases=["quote"],
        )
        async def handle_quote(server, args):
            return "quote"

        tools = registry.list_tools()

        # 2 main tools + 2 aliases = 4 total
        assert len(tools) == 4

        names = [t.name for t in tools]
        assert "optionplay_vix" in names
        assert "vix" in names
        assert "optionplay_quote" in names
        assert "quote" in names

    def test_list_tools_alias_description(self):
        """Test alias tools have modified description."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_test",
            description="Original description",
            input_schema=EMPTY_SCHEMA,
            aliases=["test"],
        )
        async def handle_test(server, args):
            return "test"

        tools = registry.list_tools()
        alias_tool = [t for t in tools if t.name == "test"][0]

        assert "[Alias for optionplay_test]" in alias_tool.description
        assert "Original description" in alias_tool.description


# =============================================================================
# SCHEMA TESTS
# =============================================================================

class TestSchemas:
    """Tests for common schema definitions."""

    def test_empty_schema(self):
        """Test EMPTY_SCHEMA structure."""
        assert EMPTY_SCHEMA["type"] == "object"
        assert "properties" in EMPTY_SCHEMA

    def test_symbol_schema(self):
        """Test SYMBOL_SCHEMA structure."""
        assert SYMBOL_SCHEMA["type"] == "object"
        assert "symbol" in SYMBOL_SCHEMA["properties"]
        assert "required" in SYMBOL_SCHEMA
        assert "symbol" in SYMBOL_SCHEMA["required"]

    def test_scan_schema(self):
        """Test SCAN_SCHEMA structure."""
        assert SCAN_SCHEMA["type"] == "object"
        props = SCAN_SCHEMA["properties"]
        assert "symbols" in props
        assert "max_results" in props
        assert "min_score" in props
        assert "list_type" in props


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestRegistryIntegration:
    """Integration tests for the tool registry."""

    def test_multiple_tools_with_shared_alias_pattern(self):
        """Test multiple tools don't conflict."""
        registry = ToolRegistry()

        @registry.register(
            name="optionplay_scan",
            description="Scan",
            input_schema=SCAN_SCHEMA,
            aliases=["scan"],
        )
        async def handle_scan(server, args):
            return "scan"

        @registry.register(
            name="optionplay_scan_bounce",
            description="Bounce scan",
            input_schema=SCAN_SCHEMA,
            aliases=["bounce"],
        )
        async def handle_bounce(server, args):
            return "bounce"

        assert registry.tool_count == 2
        assert registry.alias_count == 2
        assert registry.has_tool("scan")
        assert registry.has_tool("bounce")

    def test_tool_count_property(self):
        """Test tool_count property."""
        registry = ToolRegistry()

        for i in range(5):
            @registry.register(
                name=f"tool_{i}",
                description=f"Tool {i}",
                input_schema=EMPTY_SCHEMA,
            )
            async def handler(server, args, idx=i):
                return f"tool_{idx}"

        assert registry.tool_count == 5

    def test_alias_count_property(self):
        """Test alias_count property."""
        registry = ToolRegistry()

        @registry.register(
            name="multi_alias_tool",
            description="Tool with many aliases",
            input_schema=EMPTY_SCHEMA,
            aliases=["a1", "a2", "a3", "a4"],
        )
        async def handler(server, args):
            return "result"

        assert registry.alias_count == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
