# Tests for TradeValidator._check_margin_capacity()
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.constants.trading_rules import TradeDecision
from src.services.trade_validator import TradeValidator


class TestCheckMarginCapacity:
    def _make_validator(self) -> TradeValidator:
        return TradeValidator()

    @pytest.mark.asyncio
    async def test_passes_when_below_50pct_ibkr(self):
        # net_liq=100k, current_margin=10k, new=5k → 15% < 50%
        summary = {
            "net_liquidation": 100_000.0,
            "maint_margin_req": 10_000.0,
            "available_funds": 85_000.0,
        }
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.return_value = summary
            check = await validator._check_margin_capacity(
                spread_width=10.0, credit_received=2.0, contracts=1, portfolio_value=100_000.0
            )

        assert check.passed is True
        assert check.decision == TradeDecision.GO
        assert "IBKR live" in check.message
        assert check.details["source"] == "ibkr_live"

    @pytest.mark.asyncio
    async def test_nogo_when_above_50pct_ibkr(self):
        # net_liq=100k, current_margin=45k, new=800 → ~45.8% is fine...
        # Let's make current_margin=48k, new=800 → 48.8% < 50% still passes.
        # Use net_liq=10k, current=4k, new=2k → 60% > 50%
        summary = {
            "net_liquidation": 10_000.0,
            "maint_margin_req": 4_000.0,
        }
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.return_value = summary
            # spread=10, credit=0, contracts=2 → margin=2000
            check = await validator._check_margin_capacity(
                spread_width=10.0, credit_received=0.0, contracts=2, portfolio_value=None
            )

        assert check.passed is False
        assert check.decision == TradeDecision.NO_GO
        assert "ibkr_live" in check.details["source"]

    @pytest.mark.asyncio
    async def test_fallback_to_notional_when_ibkr_unavailable(self):
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.return_value = None  # IBKR unavailable
            check = await validator._check_margin_capacity(
                spread_width=10.0,
                credit_received=2.0,
                contracts=1,
                portfolio_value=100_000.0,
            )

        # new_trade_margin = (10-2)*100*1 = 800 → 800/100k = 0.8% < 50%
        assert check.passed is True
        assert check.decision == TradeDecision.GO
        assert check.details["source"] == "notional"

    @pytest.mark.asyncio
    async def test_manual_review_when_no_data(self):
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.return_value = None
            check = await validator._check_margin_capacity(
                spread_width=10.0,
                credit_received=2.0,
                contracts=1,
                portfolio_value=None,  # no portfolio value either
            )

        assert check.passed is False
        assert check.decision == TradeDecision.WARNING
        assert check.details["source"] == "none"

    @pytest.mark.asyncio
    async def test_uses_ibkr_over_notional(self):
        # When IBKR returns data, it should be used (not notional)
        summary = {"net_liquidation": 200_000.0, "maint_margin_req": 5_000.0}
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.return_value = summary
            check = await validator._check_margin_capacity(
                spread_width=5.0,
                credit_received=1.0,
                contracts=2,
                portfolio_value=200_000.0,
            )

        assert check.details["source"] == "ibkr_live"

    @pytest.mark.asyncio
    async def test_ibkr_exception_falls_back_to_notional(self):
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.side_effect = ConnectionError("IBKR unreachable")
            check = await validator._check_margin_capacity(
                spread_width=10.0,
                credit_received=2.0,
                contracts=1,
                portfolio_value=50_000.0,
            )

        assert check.details["source"] == "notional"

    @pytest.mark.asyncio
    async def test_notional_nogo_when_above_50pct(self):
        # new_trade_margin = (10-0)*100*10 = 10000; portfolio=15000 → 66.7% > 50%
        validator = self._make_validator()
        with patch(
            "src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock
        ) as mock_acct:
            mock_acct.return_value = None
            check = await validator._check_margin_capacity(
                spread_width=10.0,
                credit_received=0.0,
                contracts=10,
                portfolio_value=15_000.0,
            )

        assert check.passed is False
        assert check.decision == TradeDecision.NO_GO
        assert check.details["source"] == "notional"
