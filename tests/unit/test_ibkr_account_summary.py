# Tests for IBKRPortfolio.get_account_summary() and module-level get_account_summary()
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ibkr.portfolio import IBKRPortfolio


def _make_account_item(tag: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(tag=tag, value=value)


def _make_connection(ensure_ok: bool = True, summary_items=None) -> MagicMock:
    conn = MagicMock()
    conn._ensure_connected = AsyncMock(return_value=ensure_ok)
    ib = MagicMock()
    ib.accountSummary.return_value = summary_items if summary_items is not None else []
    ib.reqAccountSummary = MagicMock()
    conn.ib = ib
    return conn


class TestGetAccountSummaryMethod:
    """Tests for IBKRPortfolio.get_account_summary()."""

    @pytest.mark.asyncio
    async def test_returns_dict_with_all_fields(self):
        items = [
            _make_account_item("NetLiquidation", "100000.00"),
            _make_account_item("MaintMarginReq", "15000.00"),
            _make_account_item("AvailableFunds", "85000.00"),
            _make_account_item("BuyingPower", "170000.00"),
        ]
        conn = _make_connection(ensure_ok=True, summary_items=items)
        portfolio = IBKRPortfolio(conn)

        result = await portfolio.get_account_summary()

        assert result is not None
        assert result["net_liquidation"] == pytest.approx(100000.0)
        assert result["maint_margin_req"] == pytest.approx(15000.0)
        assert result["available_funds"] == pytest.approx(85000.0)
        assert result["buying_power"] == pytest.approx(170000.0)

    @pytest.mark.asyncio
    async def test_not_connected_returns_none(self):
        conn = _make_connection(ensure_ok=False)
        portfolio = IBKRPortfolio(conn)

        result = await portfolio.get_account_summary()

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_summary_requests_and_retries(self):
        # First call returns empty; after reqAccountSummary, returns data
        items = [_make_account_item("NetLiquidation", "50000.00")]
        conn = _make_connection(ensure_ok=True, summary_items=[])
        # After req, return items
        conn.ib.accountSummary.side_effect = [[], items]

        portfolio = IBKRPortfolio(conn)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await portfolio.get_account_summary()

        conn.ib.reqAccountSummary.assert_called_once()
        assert result is not None
        assert result["net_liquidation"] == pytest.approx(50000.0)

    @pytest.mark.asyncio
    async def test_empty_summary_after_retry_returns_none(self):
        conn = _make_connection(ensure_ok=True, summary_items=[])
        conn.ib.accountSummary.return_value = []

        portfolio = IBKRPortfolio(conn)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await portfolio.get_account_summary()

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        conn = _make_connection(ensure_ok=True)
        conn.ib.accountSummary.side_effect = RuntimeError("connection dropped")

        portfolio = IBKRPortfolio(conn)
        result = await portfolio.get_account_summary()

        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_tags_ignored(self):
        items = [
            _make_account_item("NetLiquidation", "75000.00"),
            _make_account_item("SomeOtherTag", "999.00"),
        ]
        conn = _make_connection(ensure_ok=True, summary_items=items)
        portfolio = IBKRPortfolio(conn)

        result = await portfolio.get_account_summary()

        assert result is not None
        assert "net_liquidation" in result
        assert "some_other_tag" not in result

    @pytest.mark.asyncio
    async def test_invalid_float_value_skipped(self):
        items = [
            _make_account_item("NetLiquidation", "not_a_number"),
            _make_account_item("MaintMarginReq", "5000.00"),
        ]
        conn = _make_connection(ensure_ok=True, summary_items=items)
        portfolio = IBKRPortfolio(conn)

        result = await portfolio.get_account_summary()

        # maint_margin_req parsed, net_liquidation skipped → result still returned
        assert result is not None
        assert "maint_margin_req" in result
        assert "net_liquidation" not in result

    @pytest.mark.asyncio
    async def test_all_invalid_values_returns_none(self):
        items = [_make_account_item("NetLiquidation", "N/A")]
        conn = _make_connection(ensure_ok=True, summary_items=items)
        portfolio = IBKRPortfolio(conn)

        result = await portfolio.get_account_summary()

        assert result is None


class TestModuleLevelGetAccountSummary:
    """Tests for the module-level get_account_summary() convenience function."""

    @pytest.mark.asyncio
    async def test_module_function_returns_dict(self):
        items = [_make_account_item("NetLiquidation", "200000.00")]

        with (
            patch("src.ibkr.portfolio.IBKRConnection") as MockConn,
            patch("src.ibkr.portfolio.IBKRPortfolio") as MockPortfolio,
        ):
            mock_conn_instance = MagicMock()
            mock_conn_instance.disconnect = AsyncMock()
            MockConn.return_value = mock_conn_instance

            mock_portfolio_instance = MagicMock()
            mock_portfolio_instance.get_account_summary = AsyncMock(
                return_value={"net_liquidation": 200000.0}
            )
            MockPortfolio.return_value = mock_portfolio_instance

            from src.ibkr.portfolio import get_account_summary

            result = await get_account_summary()

        assert result == {"net_liquidation": 200000.0}
        mock_conn_instance.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_module_function_disconnects_on_exception(self):
        with (
            patch("src.ibkr.portfolio.IBKRConnection") as MockConn,
            patch("src.ibkr.portfolio.IBKRPortfolio") as MockPortfolio,
        ):
            mock_conn_instance = MagicMock()
            mock_conn_instance.disconnect = AsyncMock()
            MockConn.return_value = mock_conn_instance

            mock_portfolio_instance = MagicMock()
            mock_portfolio_instance.get_account_summary = AsyncMock(
                side_effect=RuntimeError("boom")
            )
            MockPortfolio.return_value = mock_portfolio_instance

            from src.ibkr.portfolio import get_account_summary

            with pytest.raises(RuntimeError):
                await get_account_summary()

        mock_conn_instance.disconnect.assert_awaited_once()
