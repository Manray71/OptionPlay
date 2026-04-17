# Integration tests: margin config values read correctly from trading.yaml
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.constants.trading_rules import SIZING_MAX_MARGIN_PCT, SIZING_USE_IBKR_MARGIN
from src.risk.position_sizing import PositionSizerConfig
from src.services.trade_validator import TradeValidator


class TestMarginYamlIntegration:
    def test_max_margin_pct_from_yaml(self):
        """trading.yaml sizing.max_margin_pct: 50.0 must be loaded."""
        assert SIZING_MAX_MARGIN_PCT == pytest.approx(50.0)

    def test_use_ibkr_margin_from_yaml(self):
        """trading.yaml sizing.use_ibkr_margin: true must be loaded."""
        assert SIZING_USE_IBKR_MARGIN is True

    def test_position_sizer_config_from_yaml_loads_margin_fields(self):
        config = PositionSizerConfig.from_yaml()
        # 50.0 pct → 0.50 fraction
        assert config.max_margin_pct == pytest.approx(0.50)
        assert config.use_ibkr_margin is True

    @pytest.mark.asyncio
    async def test_margin_check_respects_yaml_threshold(self):
        """When IBKR returns data, the check enforces the YAML threshold (50%)."""
        # At 49% we expect GO; at 51% we expect NO_GO
        validator = TradeValidator()

        # 49% scenario: net_liq=100k, current=40k, new_margin=9k → 49% < 50% → GO
        summary_pass = {"net_liquidation": 100_000.0, "maint_margin_req": 40_000.0}
        with patch("src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock) as mock_a:
            mock_a.return_value = summary_pass
            # spread=10, credit=1, contracts=1 → margin=(10-1)*100*1=900
            check = await validator._check_margin_capacity(10.0, 1.0, 1)

        from src.constants.trading_rules import TradeDecision

        assert check.decision == TradeDecision.GO
        assert check.details["projected_margin_pct"] < 0.50

        # 51% scenario: net_liq=10k, current=4k, new_margin=1100 → 51% > 50% → NO_GO
        summary_fail = {"net_liquidation": 10_000.0, "maint_margin_req": 4_000.0}
        with patch("src.ibkr.portfolio.get_account_summary", new_callable=AsyncMock) as mock_b:
            mock_b.return_value = summary_fail
            # (10-0)*100*1=1000; 4000+1000=5000; 5000/10000=50% exactly — borderline
            # Use 1100 margin: spread=11, credit=0, contracts=1
            check2 = await validator._check_margin_capacity(11.0, 0.0, 1)

        assert check2.decision == TradeDecision.NO_GO
        assert check2.details["projected_margin_pct"] > 0.50
