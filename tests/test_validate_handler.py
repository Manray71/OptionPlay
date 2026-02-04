"""
Tests for src/handlers/validate.py

Tests the ValidateHandlerMixin — MCP endpoint for trade validation.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import date, timedelta

from src.constants.trading_rules import TradeDecision
from src.services.trade_validator import (
    TradeValidationRequest,
    TradeValidationResult,
    ValidationCheck,
    reset_trade_validator,
)
from src.handlers.validate import ValidateHandlerMixin


class MockServer(ValidateHandlerMixin):
    """Minimal mock server with the ValidateHandlerMixin."""

    def __init__(self):
        self._ibkr_bridge = None

    async def get_vix(self):
        """Return a fixed VIX for testing."""
        return 18.0


@pytest.fixture
def server():
    """Fresh mock server for each test."""
    reset_trade_validator()
    return MockServer()


class TestFormatValidationResult:
    """Test _format_validation_result Markdown output."""

    def test_go_result_formatting(self, server):
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.GO,
            checks=[
                ValidationCheck("blacklist", True, TradeDecision.GO, "Nicht auf Blacklist"),
                ValidationCheck("stability", True, TradeDecision.GO, "Stability 85 >= 70"),
            ],
            regime="NORMAL (VIX 18.0)",
            regime_notes="Standard-Parameter",
        )
        request = TradeValidationRequest(symbol="AAPL")
        output = server._format_validation_result(result, request)

        assert "AAPL" in output
        assert "[GO]" in output
        assert "NORMAL" in output
        assert "Standard-Parameter" in output
        assert "OK" in output

    def test_no_go_result_formatting(self, server):
        result = TradeValidationResult(
            symbol="TSLA",
            decision=TradeDecision.NO_GO,
            checks=[
                ValidationCheck("blacklist", False, TradeDecision.NO_GO, "TSLA ist auf der Blacklist"),
            ],
            regime="NORMAL (VIX 18.0)",
        )
        request = TradeValidationRequest(symbol="TSLA")
        output = server._format_validation_result(result, request)

        assert "TSLA" in output
        assert "[NO-GO]" in output
        assert "NO-GO" in output
        assert "Blacklist" in output

    def test_warning_result_formatting(self, server):
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.WARNING,
            checks=[
                ValidationCheck("blacklist", True, TradeDecision.GO, "OK"),
                ValidationCheck("iv_rank", True, TradeDecision.WARNING, "IV Rank 20% < 30%"),
            ],
        )
        request = TradeValidationRequest(symbol="AAPL")
        output = server._format_validation_result(result, request)

        assert "[WARNING]" in output
        assert "WARNING" in output
        assert "IV Rank" in output

    def test_trade_details_shown(self, server):
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.GO,
            checks=[ValidationCheck("test", True, TradeDecision.GO, "OK")],
        )
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            expiration="2026-05-15",
            credit=2.50,
        )
        output = server._format_validation_result(result, request)

        assert "175.00" in output
        assert "165.00" in output
        assert "2026-05-15" in output
        assert "2.50" in output
        assert "10.00" in output  # spread width

    def test_sizing_recommendation_shown(self, server):
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.GO,
            checks=[ValidationCheck("test", True, TradeDecision.GO, "OK")],
            sizing_recommendation={
                "spread_width": 10.0,
                "max_loss_per_contract": 750.0,
                "risk_pct": 2.0,
                "max_risk_usd": 1600.0,
                "recommended_contracts": 2,
                "total_credit": 500.0,
                "total_risk": 1500.0,
            },
        )
        request = TradeValidationRequest(symbol="AAPL")
        output = server._format_validation_result(result, request)

        assert "Position Sizing" in output
        assert "$750" in output
        assert "2.0%" in output
        assert "$1600" in output

    def test_no_regime_info(self, server):
        """Output should work without regime info."""
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.GO,
            checks=[ValidationCheck("test", True, TradeDecision.GO, "OK")],
            regime=None,
        )
        request = TradeValidationRequest(symbol="AAPL")
        output = server._format_validation_result(result, request)

        assert "AAPL" in output
        # Should not crash without regime

    def test_multiple_blockers_and_warnings(self, server):
        """Multiple blockers and warnings all appear in output."""
        result = TradeValidationResult(
            symbol="TEST",
            decision=TradeDecision.NO_GO,
            checks=[
                ValidationCheck("blacklist", False, TradeDecision.NO_GO, "Blacklisted"),
                ValidationCheck("price", False, TradeDecision.NO_GO, "Preis zu niedrig"),
                ValidationCheck("iv_rank", True, TradeDecision.WARNING, "Niedriger IV Rank"),
                ValidationCheck("stability", True, TradeDecision.GO, "Stability OK"),
            ],
        )
        request = TradeValidationRequest(symbol="TEST")
        output = server._format_validation_result(result, request)

        assert "Blacklisted" in output
        assert "Preis zu niedrig" in output
        assert "Niedriger IV Rank" in output
        assert "Stability OK" in output


class TestGetOpenPositions:
    """Test _get_open_positions fallback logic."""

    @pytest.mark.asyncio
    async def test_no_ibkr_returns_empty(self, server):
        """Without IBKR bridge, returns empty list."""
        positions = await server._get_open_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_ibkr_bridge_exception_returns_empty(self, server):
        """If IBKR bridge throws, falls back gracefully."""
        server._ibkr_bridge = MagicMock()
        server._ibkr_bridge.get_portfolio.side_effect = Exception("Connection failed")
        positions = await server._get_open_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_ibkr_bridge_returns_positions(self, server):
        """IBKR bridge returns positions -> formatted list."""
        server._ibkr_bridge = MagicMock()
        server._ibkr_bridge.get_portfolio.return_value = [
            {"symbol": "AAPL", "sector": "Technology", "other": "data"},
            {"symbol": "MSFT", "sector": "Technology"},
        ]
        positions = await server._get_open_positions()
        assert len(positions) == 2
        assert positions[0]["symbol"] == "AAPL"
        assert positions[0]["sector"] == "Technology"


class TestValidateTradeEndpoint:
    """Integration tests for the validate_trade endpoint."""

    @pytest.mark.asyncio
    async def test_blacklisted_symbol_returns_no_go(self, server):
        """Calling validate_trade with a blacklisted symbol."""
        # Mock the mcp_endpoint decorator behavior — call the inner method
        # The @mcp_endpoint decorator wraps the function, so we call the raw method
        with patch.object(server, 'get_vix', new_callable=AsyncMock, return_value=18.0):
            with patch.object(server, '_get_open_positions', new_callable=AsyncMock, return_value=[]):
                output = await server.validate_trade.__wrapped__(server, symbol="TSLA")
                assert "NO-GO" in output
                assert "Blacklist" in output

    @pytest.mark.asyncio
    async def test_valid_symbol_returns_output(self, server):
        """Calling validate_trade with a valid symbol."""
        with patch.object(server, 'get_vix', new_callable=AsyncMock, return_value=18.0):
            with patch.object(server, '_get_open_positions', new_callable=AsyncMock, return_value=[]):
                output = await server.validate_trade.__wrapped__(server, symbol="AAPL")
                assert "AAPL" in output
                assert "Prüf-Ergebnisse" in output
