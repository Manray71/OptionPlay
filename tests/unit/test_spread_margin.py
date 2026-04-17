# Tests for calculate_spread_margin() and PositionSizerConfig margin fields
from __future__ import annotations

import pytest

from src.risk.position_sizing import PositionSizerConfig, calculate_spread_margin


class TestCalculateSpreadMargin:
    def test_basic_case(self):
        # (10.0 - 1.85) × 100 × 1 = 815.0
        result = calculate_spread_margin(spread_width=10.0, credit_received=1.85, contracts=1)
        assert result == pytest.approx(815.0)

    def test_multiple_contracts(self):
        # (5.0 - 1.00) × 100 × 3 = 1200.0
        result = calculate_spread_margin(spread_width=5.0, credit_received=1.00, contracts=3)
        assert result == pytest.approx(1200.0)

    def test_zero_credit(self):
        # (10.0 - 0.0) × 100 × 2 = 2000.0
        result = calculate_spread_margin(spread_width=10.0, credit_received=0.0, contracts=2)
        assert result == pytest.approx(2000.0)

    def test_full_credit_edge_case(self):
        # credit == spread_width → margin = 0
        result = calculate_spread_margin(spread_width=5.0, credit_received=5.0, contracts=1)
        assert result == pytest.approx(0.0)

    def test_zero_contracts(self):
        result = calculate_spread_margin(spread_width=10.0, credit_received=2.0, contracts=0)
        assert result == pytest.approx(0.0)

    def test_fractional_values(self):
        # (7.50 - 1.25) × 100 × 4 = 2500.0
        result = calculate_spread_margin(spread_width=7.50, credit_received=1.25, contracts=4)
        assert result == pytest.approx(2500.0)


class TestPositionSizerConfigMarginFields:
    def test_default_use_ibkr_margin_true(self):
        config = PositionSizerConfig()
        assert config.use_ibkr_margin is True

    def test_default_max_margin_pct(self):
        config = PositionSizerConfig()
        assert config.max_margin_pct == pytest.approx(0.50)

    def test_from_yaml_loads_margin_fields(self):
        config = PositionSizerConfig.from_yaml()
        # Should parse from trading.yaml (or fall back to defaults)
        # max_margin_pct: 50.0 → fraction 0.50
        assert 0.0 < config.max_margin_pct <= 1.0
        assert isinstance(config.use_ibkr_margin, bool)

    def test_custom_values_respected(self):
        config = PositionSizerConfig(use_ibkr_margin=False, max_margin_pct=0.30)
        assert config.use_ibkr_margin is False
        assert config.max_margin_pct == pytest.approx(0.30)
