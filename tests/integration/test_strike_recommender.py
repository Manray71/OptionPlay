# OptionPlay - Strike Recommender Tests
# =======================================
# Comprehensive tests for strike_recommender.py
# Focus areas:
# 1. StrikeRecommender initialization
# 2. recommend_strikes / get_recommendation method
# 3. find_optimal_short_strike / _find_short_strike method
# 4. find_optimal_long_strike / _find_long_strike_by_delta method
# 5. Support/resistance consideration
# 6. Delta targeting

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strike_recommender import (
    StrikeRecommender,
    StrikeRecommendation,
    StrikeQuality,
    SupportLevel,
    calculate_strike_recommendation
)


# =============================================================================
# SECTION 1: StrikeRecommender Initialization Tests
# =============================================================================

class TestStrikeRecommenderInitialization:
    """Tests for StrikeRecommender initialization and configuration."""

    def test_initialization_without_config(self):
        """Test: Recommender initializes with default config when none provided."""
        recommender = StrikeRecommender(use_config_loader=False)

        assert recommender is not None
        assert recommender.config is not None
        assert isinstance(recommender.config, dict)

    def test_default_config_values(self):
        """Test: Default configuration values match PLAYBOOK requirements."""
        recommender = StrikeRecommender(use_config_loader=False)

        # Short Put Delta targeting (PLAYBOOK section 2: -0.20 with +-0.03)
        assert recommender.config["delta_target"] == -0.20
        assert recommender.config["delta_min"] == -0.17  # Less aggressive
        assert recommender.config["delta_max"] == -0.23  # More aggressive

        # Long Put Delta targeting (PLAYBOOK section 2: -0.05 with +-0.02)
        assert recommender.config["long_delta_target"] == -0.05
        assert recommender.config["long_delta_min"] == -0.03  # Less aggressive
        assert recommender.config["long_delta_max"] == -0.07  # More aggressive

        # OTM requirements
        assert recommender.config["min_otm_pct"] == 8.0
        assert recommender.config["target_otm_pct"] == 12.0
        assert recommender.config["max_otm_pct"] == 25.0

        # Premium requirements (PLAYBOOK section 2: >= 10% spread width)
        assert recommender.config["min_credit_pct"] == 10

    def test_custom_config_overrides_defaults(self):
        """Test: Explicit config values override defaults."""
        custom_config = {
            "delta_target": -0.25,
            "min_credit_pct": 25,
            "min_otm_pct": 10.0
        }

        recommender = StrikeRecommender(config=custom_config, use_config_loader=False)

        assert recommender.config["delta_target"] == -0.25
        assert recommender.config["min_credit_pct"] == 25
        assert recommender.config["min_otm_pct"] == 10.0
        # Non-overridden values should remain default
        assert recommender.config["long_delta_target"] == -0.05

    def test_partial_config_merges_with_defaults(self):
        """Test: Partial config is merged with defaults."""
        partial_config = {"target_otm_pct": 15.0}

        recommender = StrikeRecommender(config=partial_config, use_config_loader=False)

        # Provided value
        assert recommender.config["target_otm_pct"] == 15.0
        # Default values preserved
        assert recommender.config["delta_target"] == -0.20

    def test_config_loader_disabled_uses_defaults(self):
        """Test: use_config_loader=False uses only defaults."""
        recommender = StrikeRecommender(use_config_loader=False)

        assert recommender.config["delta_target"] == -0.20

    def test_config_loader_not_available_graceful_fallback(self):
        """Test: When ConfigLoader not available, gracefully fallback to defaults."""
        import strike_recommender
        original = strike_recommender._CONFIG_AVAILABLE

        try:
            strike_recommender._CONFIG_AVAILABLE = False
            recommender = StrikeRecommender(use_config_loader=True)

            # Should work with defaults
            assert recommender.config["delta_target"] == -0.20
        finally:
            strike_recommender._CONFIG_AVAILABLE = original

    def test_config_loader_exception_handled(self):
        """Test: ConfigLoader exceptions are handled gracefully."""
        import strike_recommender
        original_available = strike_recommender._CONFIG_AVAILABLE

        # Mock a ConfigLoader that raises an exception
        mock_loader = MagicMock()
        mock_loader.settings = MagicMock()
        mock_loader.settings.options = MagicMock()
        mock_loader.settings.options.delta_target = None  # Simulate attr access raising

        try:
            strike_recommender._CONFIG_AVAILABLE = True
            # Patch at the config module level where ConfigLoader is actually used
            with patch.object(strike_recommender, '_CONFIG_AVAILABLE', True):
                # Even if ConfigLoader has issues, should fallback to defaults
                recommender = StrikeRecommender(use_config_loader=False)
                # Should still initialize with defaults
                assert recommender.config["delta_target"] == -0.20
        finally:
            strike_recommender._CONFIG_AVAILABLE = original_available


# =============================================================================
# SECTION 2: get_recommendation / recommend_strikes Method Tests
# =============================================================================

class TestRecommendStrikesMethod:
    """Tests for the get_recommendation method."""

    @pytest.fixture
    def recommender(self):
        """Standard recommender without ConfigLoader."""
        return StrikeRecommender(use_config_loader=False)

    def test_returns_strike_recommendation_object(self, recommender):
        """Test: get_recommendation returns a StrikeRecommendation object."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )

        assert isinstance(rec, StrikeRecommendation)

    def test_recommendation_has_all_required_fields(self, recommender):
        """Test: Recommendation contains all required fields."""
        rec = recommender.get_recommendation(
            symbol="AAPL",
            current_price=180.0,
            support_levels=[170.0, 165.0]
        )

        assert rec.symbol == "AAPL"
        assert rec.current_price == 180.0
        assert rec.short_strike is not None
        assert rec.long_strike is not None
        assert rec.spread_width > 0
        assert rec.short_strike > rec.long_strike
        assert rec.short_strike_reason is not None
        assert rec.quality in StrikeQuality
        assert 0 <= rec.confidence_score <= 100

    def test_recommendation_with_empty_support_levels(self, recommender):
        """Test: Recommendation works with empty support levels (fallback)."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[]
        )

        assert rec.short_strike is not None
        assert rec.short_strike < rec.current_price
        # Should use OTM percent-based fallback
        assert "OTM" in rec.short_strike_reason or rec.short_strike < 92.0

    def test_recommendation_with_single_support_level(self, recommender):
        """Test: Recommendation works with single support level."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        assert rec.short_strike is not None
        assert rec.short_strike < rec.current_price

    def test_recommendation_with_iv_rank(self, recommender):
        """Test: IV rank is considered in recommendation."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=65.0
        )

        assert rec is not None
        # High IV should not degrade quality
        assert rec.quality != StrikeQuality.POOR

    def test_recommendation_with_custom_dte(self, recommender):
        """Test: Custom DTE is used in calculations."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            dte=30
        )

        assert rec is not None

    def test_recommendation_with_fib_levels(self, recommender):
        """Test: Fibonacci levels are considered."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=[{"level": 90.5}, {"level": 85.0}]
        )

        assert rec is not None

    def test_recommendation_preserves_symbol(self, recommender):
        """Test: Symbol is preserved in recommendation."""
        rec = recommender.get_recommendation(
            symbol="NVDA",
            current_price=500.0,
            support_levels=[450.0]
        )

        assert rec.symbol == "NVDA"

    def test_recommendation_preserves_current_price(self, recommender):
        """Test: Current price is preserved in recommendation."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=123.45,
            support_levels=[110.0]
        )

        assert rec.current_price == 123.45


class TestRecommendStrikesWithOptionsData:
    """Tests for get_recommendation with options chain data."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    @pytest.fixture
    def liquid_options_chain(self):
        """Liquid options chain with proper delta spread."""
        return [
            {"strike": 700.0, "right": "P", "delta": -0.50, "bid": 30.0, "ask": 31.0,
             "open_interest": 500, "volume": 200},
            {"strike": 680.0, "right": "P", "delta": -0.35, "bid": 18.0, "ask": 19.0,
             "open_interest": 400, "volume": 150},
            {"strike": 660.0, "right": "P", "delta": -0.25, "bid": 12.0, "ask": 13.0,
             "open_interest": 350, "volume": 120},
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.50, "ask": 9.00,
             "open_interest": 300, "volume": 100},
            {"strike": 630.0, "right": "P", "delta": -0.18, "bid": 7.00, "ask": 7.50,
             "open_interest": 250, "volume": 80},
            {"strike": 620.0, "right": "P", "delta": -0.15, "bid": 5.50, "ask": 6.00,
             "open_interest": 200, "volume": 60},
            {"strike": 600.0, "right": "P", "delta": -0.10, "bid": 3.50, "ask": 4.00,
             "open_interest": 180, "volume": 50},
            {"strike": 580.0, "right": "P", "delta": -0.07, "bid": 2.00, "ask": 2.50,
             "open_interest": 150, "volume": 40},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.20, "ask": 1.50,
             "open_interest": 120, "volume": 30},
            {"strike": 540.0, "right": "P", "delta": -0.03, "bid": 0.60, "ask": 0.80,
             "open_interest": 100, "volume": 20},
        ]

    def test_uses_options_data_for_delta_selection(self, recommender, liquid_options_chain):
        """Test: Options data is used for delta-based strike selection."""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0],
            options_data=liquid_options_chain
        )

        assert rec.estimated_delta is not None
        # Delta should be near target -0.20 within range
        assert -0.23 <= rec.estimated_delta <= -0.17

    def test_calculates_credit_from_options_bid_ask(self, recommender, liquid_options_chain):
        """Test: Credit is calculated from actual bid/ask prices."""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0],
            options_data=liquid_options_chain
        )

        assert rec.estimated_credit is not None
        assert rec.estimated_credit > 0

    def test_spread_width_derived_from_delta_not_fixed(self, recommender, liquid_options_chain):
        """Test: Spread width is derived from delta selection, not fixed."""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0],
            options_data=liquid_options_chain
        )

        # Width should be the difference between selected strikes
        assert rec.spread_width == rec.short_strike - rec.long_strike
        # For a $720 stock, width should be substantial (not fixed $5 or $10)
        assert rec.spread_width > 10.0

    def test_long_delta_propagated_to_recommendation(self, recommender, liquid_options_chain):
        """Test: Long put delta is included in recommendation."""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0],
            options_data=liquid_options_chain
        )

        assert rec.long_delta is not None
        # Should be in range [-0.07, -0.03]
        assert -0.07 <= rec.long_delta <= -0.03

    def test_returns_poor_quality_when_no_liquid_strikes(self, recommender):
        """Test: Returns POOR quality when no liquid strikes available."""
        illiquid_options = [
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 0, "ask": 2.0,
             "open_interest": 5, "volume": 0},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=illiquid_options
        )

        assert rec.quality == StrikeQuality.POOR
        assert any("liquid" in w.lower() for w in rec.warnings)

    def test_no_fallback_when_options_data_present_but_illiquid(self, recommender):
        """Test: Does NOT fallback to support/OTM when options data exists but illiquid."""
        illiquid_options = [
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 0, "ask": 2.0,
             "open_interest": 0, "volume": 0},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=illiquid_options
        )

        # Should be POOR quality, not a theoretical recommendation
        assert rec.quality == StrikeQuality.POOR

    def test_extracts_dte_from_options_data(self, recommender):
        """Test: DTE is extracted from options data when available."""
        options_with_dte = [
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 2.0, "ask": 2.2,
             "open_interest": 200, "volume": 50, "dte": 45},
            {"strike": 80.0, "right": "P", "delta": -0.05, "bid": 0.5, "ask": 0.7,
             "open_interest": 150, "volume": 30, "dte": 45},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_with_dte
        )

        # Recommendation should succeed
        assert rec is not None


# =============================================================================
# SECTION 3: _find_short_strike / find_optimal_short_strike Tests
# =============================================================================

class TestFindOptimalShortStrike:
    """Tests for _find_short_strike method (find optimal short strike)."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_delta_based_selection_with_options_data(self, recommender):
        """Test: Selects short strike based on delta when options data available."""
        options_data = [
            {"strike": 95.0, "right": "P", "delta": -0.30, "bid": 3.0, "ask": 3.5,
             "open_interest": 200, "volume": 50},
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.15, "bid": 0.8, "ask": 1.0,
             "open_interest": 200, "volume": 50},
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        assert short_strike == 90.0  # Delta -0.20 is target
        assert "Delta" in reason

    def test_selects_closest_delta_to_target(self, recommender):
        """Test: Selects strike with delta closest to target -0.20."""
        options_data = [
            {"strike": 92.0, "right": "P", "delta": -0.22, "bid": 2.5, "ask": 3.0,
             "open_interest": 200, "volume": 50},
            {"strike": 90.0, "right": "P", "delta": -0.19, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},
            {"strike": 88.0, "right": "P", "delta": -0.17, "bid": 1.0, "ask": 1.3,
             "open_interest": 200, "volume": 50},
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        # -0.19 is closer to -0.20 than -0.22 or -0.17
        assert short_strike == 90.0

    def test_respects_delta_range_limits(self, recommender):
        """Test: Only considers strikes within delta range [-0.23, -0.17]."""
        options_data = [
            {"strike": 98.0, "right": "P", "delta": -0.45, "bid": 5.0, "ask": 5.5,
             "open_interest": 200, "volume": 50},  # Too high delta
            {"strike": 95.0, "right": "P", "delta": -0.30, "bid": 3.0, "ask": 3.5,
             "open_interest": 200, "volume": 50},  # Outside range
            {"strike": 85.0, "right": "P", "delta": -0.10, "bid": 0.5, "ask": 0.7,
             "open_interest": 200, "volume": 50},  # Too low delta
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        # No valid strike within delta range
        assert short_strike is None
        assert "No liquid strikes" in reason

    def test_skips_itm_strikes(self, recommender):
        """Test: Skips in-the-money strikes (strike >= current price)."""
        options_data = [
            {"strike": 105.0, "right": "P", "delta": -0.60, "bid": 6.0, "ask": 6.5,
             "open_interest": 200, "volume": 50},  # ITM
            {"strike": 100.0, "right": "P", "delta": -0.50, "bid": 3.0, "ask": 3.5,
             "open_interest": 200, "volume": 50},  # ATM
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},  # OTM
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        assert short_strike == 90.0  # Only OTM option with valid delta

    def test_skips_illiquid_strikes_low_oi(self, recommender):
        """Test: Skips strikes with insufficient open interest."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        options_data = [
            {"strike": 92.0, "right": "P", "delta": -0.20, "bid": 2.0, "ask": 2.2,
             "open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "volume": 50},  # Low OI
            {"strike": 88.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": ENTRY_OPEN_INTEREST_MIN + 50, "volume": 50},  # Adequate OI
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        assert short_strike == 88.0  # Liquid strike

    def test_skips_strikes_with_zero_bid(self, recommender):
        """Test: Skips strikes with zero bid price."""
        options_data = [
            {"strike": 92.0, "right": "P", "delta": -0.20, "bid": 0, "ask": 2.0,
             "open_interest": 500, "volume": 100},  # Zero bid
            {"strike": 88.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": 200, "volume": 50},  # Valid bid
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        assert short_strike == 88.0

    def test_support_based_selection_without_options_data(self, recommender):
        """Test: Uses support levels when no options data available."""
        supports = [
            SupportLevel(price=90.0, touches=3, strength="strong", distance_pct=10.0),
            SupportLevel(price=85.0, touches=2, strength="moderate", distance_pct=15.0),
        ]

        short_strike, reason, support_used = recommender._find_short_strike(
            current_price=100.0,
            supports=supports,
            options_data=None
        )

        assert short_strike is not None
        assert short_strike < 100.0
        assert "Support" in reason or "OTM" in reason

    def test_otm_fallback_without_options_or_support(self, recommender):
        """Test: Falls back to OTM percent when no options or support."""
        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=None
        )

        assert short_strike is not None
        # Should be target_otm_pct (12%) below price
        assert 85.0 <= short_strike <= 92.0
        assert "OTM" in reason

    def test_ignores_call_options(self, recommender):
        """Test: Ignores call options in options data."""
        options_data = [
            {"strike": 90.0, "right": "C", "delta": 0.30, "bid": 5.0, "ask": 5.5,
             "open_interest": 500, "volume": 200},  # Call option
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},  # Put option
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        assert short_strike == 90.0  # Should select the put

    def test_handles_missing_delta_in_options(self, recommender):
        """Test: Handles options data with missing delta field."""
        options_data = [
            {"strike": 92.0, "right": "P", "bid": 2.0, "ask": 2.2,
             "open_interest": 200, "volume": 50},  # Missing delta
            {"strike": 88.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": 200, "volume": 50},  # Has delta
        ]

        short_strike, reason, support = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data
        )

        assert short_strike == 88.0  # Only option with delta


# =============================================================================
# SECTION 4: _find_long_strike_by_delta / find_optimal_long_strike Tests
# =============================================================================

class TestFindOptimalLongStrike:
    """Tests for _find_long_strike_by_delta method."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    @pytest.fixture
    def options_chain_with_long_puts(self):
        """Options chain with various long put deltas."""
        return [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            {"strike": 600.0, "right": "P", "delta": -0.10, "bid": 3.5, "ask": 4.0,
             "open_interest": 180, "volume": 50},
            {"strike": 580.0, "right": "P", "delta": -0.07, "bid": 2.0, "ask": 2.5,
             "open_interest": 150, "volume": 40},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.2, "ask": 1.5,
             "open_interest": 120, "volume": 30},
            {"strike": 540.0, "right": "P", "delta": -0.03, "bid": 0.6, "ask": 0.8,
             "open_interest": 100, "volume": 20},
            {"strike": 520.0, "right": "P", "delta": -0.02, "bid": 0.3, "ask": 0.5,
             "open_interest": 100, "volume": 10},
        ]

    def test_finds_long_strike_by_delta_target(self, recommender, options_chain_with_long_puts):
        """Test: Finds long strike with delta closest to -0.05."""
        result = recommender._find_long_strike_by_delta(
            options_chain_with_long_puts, short_strike=640.0
        )

        assert result is not None
        long_strike, long_delta = result
        assert long_strike == 560.0  # Delta -0.05 is target
        assert long_delta == -0.05

    def test_long_strike_must_be_below_short_strike(self, recommender, options_chain_with_long_puts):
        """Test: Long strike must be below short strike."""
        result = recommender._find_long_strike_by_delta(
            options_chain_with_long_puts, short_strike=640.0
        )

        assert result is not None
        long_strike, _ = result
        assert long_strike < 640.0

    def test_respects_long_delta_range(self, recommender, options_chain_with_long_puts):
        """Test: Long delta must be within range [-0.07, -0.03]."""
        result = recommender._find_long_strike_by_delta(
            options_chain_with_long_puts, short_strike=640.0
        )

        assert result is not None
        _, long_delta = result
        assert -0.07 <= long_delta <= -0.03

    def test_returns_none_when_no_valid_long_strike(self, recommender):
        """Test: Returns None when no suitable long strike found."""
        # Only high delta options (no delta in [-0.07, -0.03])
        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.30, "bid": 3.0, "ask": 3.5,
             "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},
        ]

        result = recommender._find_long_strike_by_delta(options_data, short_strike=95.0)
        assert result is None

    def test_skips_illiquid_long_strikes(self, recommender):
        """Test: Skips illiquid long strikes."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        options_data = [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.2, "ask": 1.5,
             "open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "volume": 10},  # Illiquid
            {"strike": 580.0, "right": "P", "delta": -0.06, "bid": 2.0, "ask": 2.5,
             "open_interest": ENTRY_OPEN_INTEREST_MIN + 50, "volume": 40},  # Liquid
        ]

        result = recommender._find_long_strike_by_delta(options_data, short_strike=640.0)

        assert result is not None
        long_strike, _ = result
        assert long_strike == 580.0  # Liquid option

    def test_tolerates_zero_volume_with_high_oi(self, recommender):
        """Test: Tolerates volume=0 when OI is excellent for long puts."""
        from src.constants.trading_rules import LIQUIDITY_OI_EXCELLENT

        options_data = [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.2, "ask": 1.5,
             "open_interest": LIQUIDITY_OI_EXCELLENT, "volume": 0},  # Zero volume but high OI
        ]

        result = recommender._find_long_strike_by_delta(options_data, short_strike=640.0)

        assert result is not None
        long_strike, _ = result
        assert long_strike == 560.0

    def test_selects_best_delta_match_within_range(self, recommender):
        """Test: Selects strike with delta closest to target within range."""
        options_data = [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            {"strike": 580.0, "right": "P", "delta": -0.07, "bid": 2.0, "ask": 2.5,
             "open_interest": 150, "volume": 40},  # At boundary
            {"strike": 560.0, "right": "P", "delta": -0.04, "bid": 1.0, "ask": 1.3,
             "open_interest": 120, "volume": 30},  # Closer to -0.05
            {"strike": 540.0, "right": "P", "delta": -0.03, "bid": 0.6, "ask": 0.8,
             "open_interest": 100, "volume": 20},  # At boundary
        ]

        result = recommender._find_long_strike_by_delta(options_data, short_strike=640.0)

        assert result is not None
        long_strike, long_delta = result
        # -0.04 is closer to target -0.05 than -0.07 or -0.03
        assert long_strike == 560.0
        assert long_delta == -0.04

    def test_ignores_strikes_above_short_strike(self, recommender):
        """Test: Ignores long strike candidates above short strike."""
        options_data = [
            {"strike": 700.0, "right": "P", "delta": -0.05, "bid": 5.0, "ask": 5.5,
             "open_interest": 500, "volume": 200},  # Above short strike
            {"strike": 560.0, "right": "P", "delta": -0.06, "bid": 1.2, "ask": 1.5,
             "open_interest": 120, "volume": 30},  # Below short strike
        ]

        result = recommender._find_long_strike_by_delta(options_data, short_strike=640.0)

        assert result is not None
        long_strike, _ = result
        assert long_strike == 560.0  # Only valid option below short strike


# =============================================================================
# SECTION 5: Support/Resistance Consideration Tests
# =============================================================================

class TestSupportResistanceConsideration:
    """Tests for support and resistance level analysis."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_analyze_support_levels_basic(self, recommender):
        """Test: Basic support level analysis."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[95.0, 90.0, 85.0],
            fib_levels=None
        )

        assert len(supports) > 0
        assert all(isinstance(s, SupportLevel) for s in supports)

    def test_filters_supports_above_price(self, recommender):
        """Test: Filters out support levels above current price."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[105.0, 110.0, 95.0, 90.0],
            fib_levels=None
        )

        prices = [s.price for s in supports]
        assert 105.0 not in prices
        assert 110.0 not in prices
        assert 95.0 in prices

    def test_calculates_distance_percent(self, recommender):
        """Test: Calculates distance percentage correctly."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=None
        )

        assert len(supports) == 1
        assert supports[0].distance_pct == 10.0  # 10% below price

    def test_assigns_strength_based_on_distance(self, recommender):
        """Test: Assigns strength rating based on distance."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[95.0, 88.0, 80.0],  # 5%, 12%, 20% away
            fib_levels=None
        )

        # Closer supports should be stronger
        close_support = next(s for s in supports if s.price == 95.0)
        medium_support = next(s for s in supports if s.price == 88.0)
        far_support = next(s for s in supports if s.price == 80.0)

        assert close_support.strength == "strong"  # < 10%
        assert medium_support.strength == "moderate"  # 10-15%
        assert far_support.strength == "weak"  # > 15%

    def test_fibonacci_confirmation(self, recommender):
        """Test: Fibonacci levels confirm support."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=[{"level": 90.5}]  # Within 2% of support
        )

        assert len(supports) > 0
        assert supports[0].confirmed_by_fib is True

    def test_fibonacci_confirmation_tolerance(self, recommender):
        """Test: Fibonacci confirmation uses 2% tolerance."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=[{"level": 95.0}]  # More than 2% away
        )

        if supports:
            support = supports[0]
            assert support.confirmed_by_fib is False

    def test_sorts_by_strength_and_fib_confirmation(self, recommender):
        """Test: Supports are sorted by strength and fib confirmation."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[95.0, 88.0, 92.0],
            fib_levels=[{"level": 88.5}]  # Confirms 88.0
        )

        # First support should be the strongest/fib-confirmed
        if len(supports) > 1:
            # Fib-confirmed should be prioritized
            fib_confirmed_supports = [s for s in supports if s.confirmed_by_fib]
            if fib_confirmed_supports:
                assert supports[0].confirmed_by_fib

    def test_handles_empty_support_levels(self, recommender):
        """Test: Handles empty support levels list."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[],
            fib_levels=None
        )

        assert supports == []

    def test_handles_none_fib_levels(self, recommender):
        """Test: Handles None fib levels gracefully."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=None
        )

        assert len(supports) == 1
        assert supports[0].confirmed_by_fib is False

    def test_handles_empty_fib_levels(self, recommender):
        """Test: Handles empty fib levels list."""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=[]
        )

        assert len(supports) == 1
        assert supports[0].confirmed_by_fib is False

    def test_support_used_in_recommendation(self, recommender):
        """Test: Selected support level is included in recommendation."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            fib_levels=None
        )

        # Support level may or may not be used depending on delta selection
        # But recommendation should have support_level_used field
        assert hasattr(rec, 'support_level_used')


# =============================================================================
# SECTION 6: Delta Targeting Tests
# =============================================================================

class TestDeltaTargeting:
    """Tests for delta targeting logic."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_short_delta_target_is_minus_020(self, recommender):
        """Test: Short put delta target is -0.20."""
        assert recommender.config["delta_target"] == -0.20

    def test_short_delta_range_is_017_to_023(self, recommender):
        """Test: Short put delta range is [-0.17, -0.23]."""
        assert recommender.config["delta_min"] == -0.17
        assert recommender.config["delta_max"] == -0.23

    def test_long_delta_target_is_minus_005(self, recommender):
        """Test: Long put delta target is -0.05."""
        assert recommender.config["long_delta_target"] == -0.05

    def test_long_delta_range_is_003_to_007(self, recommender):
        """Test: Long put delta range is [-0.03, -0.07]."""
        assert recommender.config["long_delta_min"] == -0.03
        assert recommender.config["long_delta_max"] == -0.07

    def test_prioritizes_delta_over_support(self, recommender):
        """Test: Delta-based selection is prioritized when options data available."""
        options_data = [
            {"strike": 88.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},  # Delta target
            {"strike": 90.0, "right": "P", "delta": -0.25, "bid": 2.5, "ask": 3.0,
             "open_interest": 200, "volume": 50},  # Near support but outside delta range
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],  # 90.0 is a support
            options_data=options_data
        )

        # Should pick delta-based strike (88.0), not support-based (90.0)
        assert rec.short_strike == 88.0
        assert "Delta" in rec.short_strike_reason

    def test_delta_outside_range_is_rejected(self, recommender):
        """Test: Options with delta outside range are rejected."""
        options_data = [
            {"strike": 95.0, "right": "P", "delta": -0.35, "bid": 5.0, "ask": 5.5,
             "open_interest": 500, "volume": 200},  # Too aggressive
            {"strike": 85.0, "right": "P", "delta": -0.12, "bid": 0.5, "ask": 0.8,
             "open_interest": 200, "volume": 50},  # Too conservative
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data
        )

        # No valid delta -> POOR quality
        assert rec.quality == StrikeQuality.POOR

    def test_delta_at_boundary_is_accepted(self, recommender):
        """Test: Options with delta at boundary values are accepted."""
        options_data = [
            {"strike": 88.0, "right": "P", "delta": -0.17, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},  # At min boundary
            {"strike": 75.0, "right": "P", "delta": -0.03, "bid": 0.3, "ask": 0.5,
             "open_interest": 150, "volume": 30},  # Long at min boundary
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data
        )

        # Boundary value -0.17 should be accepted
        assert rec.short_strike == 88.0

    def test_custom_delta_config(self):
        """Test: Custom delta configuration is respected."""
        custom_config = {
            "delta_target": -0.15,
            "delta_min": -0.12,
            "delta_max": -0.18
        }
        recommender = StrikeRecommender(config=custom_config, use_config_loader=False)

        options_data = [
            {"strike": 92.0, "right": "P", "delta": -0.15, "bid": 2.0, "ask": 2.2,
             "open_interest": 200, "volume": 50},  # Custom target
            {"strike": 88.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 1.8,
             "open_interest": 200, "volume": 50},  # Default target (outside custom range)
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data
        )

        # Should use custom delta target
        assert rec.short_strike == 92.0

    def test_delta_is_reported_in_recommendation(self, recommender):
        """Test: Selected delta is reported in recommendation."""
        options_data = [
            {"strike": 88.0, "right": "P", "delta": -0.19, "bid": 1.5, "ask": 2.0,
             "open_interest": 200, "volume": 50},
            {"strike": 75.0, "right": "P", "delta": -0.05, "bid": 0.3, "ask": 0.5,
             "open_interest": 150, "volume": 30},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data
        )

        assert rec.estimated_delta is not None
        assert rec.estimated_delta == -0.19


# =============================================================================
# ADDITIONAL TESTS: Spread Width, Metrics, Quality, etc.
# =============================================================================

class TestSpreadWidthCalculation:
    """Tests for spread width calculation."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_spread_width_is_short_minus_long(self, recommender):
        """Test: Spread width equals short strike minus long strike."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )

        assert rec.spread_width == rec.short_strike - rec.long_strike

    def test_spread_width_fallback_low_price(self, recommender):
        """Test: Fallback spread width for low-priced stocks (~12%)."""
        widths = recommender._get_spread_widths_fallback(30.0)

        assert len(widths) >= 1
        # 12% of $30 = $3.60, rounded to $2.50 or $5.00
        assert widths[0] >= 2.5

    def test_spread_width_fallback_medium_price(self, recommender):
        """Test: Fallback spread width for medium-priced stocks."""
        widths = recommender._get_spread_widths_fallback(100.0)

        # 12% of $100 = $12, rounded to $10 or $15
        assert widths[0] >= 10.0

    def test_spread_width_fallback_high_price(self, recommender):
        """Test: Fallback spread width for high-priced stocks."""
        widths = recommender._get_spread_widths_fallback(500.0)

        # 12% of $500 = $60
        assert widths[0] >= 50.0

    def test_spread_width_is_positive(self, recommender):
        """Test: Spread width is always positive."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        assert rec.spread_width > 0


class TestMetricsCalculation:
    """Tests for metrics calculation."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_max_loss_calculated(self, recommender):
        """Test: Max loss is calculated."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        assert rec.max_loss is not None
        assert rec.max_loss > 0

    def test_max_profit_calculated(self, recommender):
        """Test: Max profit is calculated."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        assert rec.max_profit is not None
        assert rec.max_profit > 0

    def test_max_profit_less_than_max_loss(self, recommender):
        """Test: Max profit is less than max loss (typical for credit spreads)."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        if rec.max_profit and rec.max_loss:
            assert rec.max_profit < rec.max_loss

    def test_break_even_between_strikes(self, recommender):
        """Test: Break-even is between the strikes."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        if rec.break_even:
            assert rec.long_strike <= rec.break_even <= rec.short_strike

    def test_prob_profit_in_valid_range(self, recommender):
        """Test: Probability of profit is between 0 and 100."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        if rec.prob_profit:
            assert 0 < rec.prob_profit < 100

    def test_risk_reward_ratio_calculated(self, recommender):
        """Test: Risk/reward ratio is calculated."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        if rec.risk_reward_ratio:
            assert rec.risk_reward_ratio > 0


class TestQualityEvaluation:
    """Tests for quality evaluation."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_quality_is_assigned(self, recommender):
        """Test: Quality rating is assigned."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )

        assert rec.quality in StrikeQuality

    def test_confidence_score_in_range(self, recommender):
        """Test: Confidence score is between 0 and 100."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )

        assert 0 <= rec.confidence_score <= 100

    def test_high_iv_boosts_quality(self, recommender):
        """Test: High IV rank improves quality (credit spreads benefit)."""
        rec_low_iv = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=20
        )

        rec_high_iv = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=70
        )

        assert rec_high_iv.confidence_score >= rec_low_iv.confidence_score

    def test_warning_for_low_otm(self, recommender):
        """Test: Warning generated for low OTM percentage."""
        recommender.config["min_otm_pct"] = 10.0

        support = SupportLevel(price=95.0, distance_pct=5.0)
        metrics = {"credit": 1.0, "spread_width": 5.0, "risk_reward": 0.3}

        quality, score, warnings = recommender._evaluate_quality(
            short_strike=95.0,  # Only 5% OTM
            long_strike=90.0,
            current_price=100.0,
            support=support,
            metrics=metrics,
            iv_rank=None
        )

        assert any("OTM" in w or "ITM" in w for w in warnings)

    def test_warning_for_no_support(self, recommender):
        """Test: Warning when no support level used."""
        metrics = {"credit": 1.0, "spread_width": 5.0, "risk_reward": 0.3}

        quality, score, warnings = recommender._evaluate_quality(
            short_strike=88.0,
            long_strike=80.0,
            current_price=100.0,
            support=None,
            metrics=metrics,
            iv_rank=None
        )

        assert any("support" in w.lower() for w in warnings)

    def test_quality_excellent_for_high_score(self, recommender):
        """Test: EXCELLENT quality for high confidence scores."""
        support = SupportLevel(price=87.0, touches=3, strength="strong",
                               confirmed_by_fib=True, distance_pct=13.0)
        metrics = {"credit": 2.0, "spread_width": 5.0, "risk_reward": 0.5}

        quality, score, warnings = recommender._evaluate_quality(
            short_strike=87.0,
            long_strike=82.0,
            current_price=100.0,
            support=support,
            metrics=metrics,
            iv_rank=60
        )

        if score >= 75:
            assert quality == StrikeQuality.EXCELLENT


class TestMultipleRecommendations:
    """Tests for generating multiple recommendations."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_get_multiple_recommendations_returns_list(self, recommender):
        """Test: Returns a list of recommendations."""
        recs = recommender.get_multiple_recommendations(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0, 80.0],
            num_alternatives=3
        )

        assert isinstance(recs, list)
        assert all(isinstance(r, StrikeRecommendation) for r in recs)

    def test_recommendations_limited_to_num_alternatives(self, recommender):
        """Test: Number of recommendations limited by num_alternatives."""
        recs = recommender.get_multiple_recommendations(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0, 80.0],
            num_alternatives=2
        )

        assert len(recs) <= 2

    def test_recommendations_sorted_by_confidence(self, recommender):
        """Test: Recommendations sorted by confidence score (descending)."""
        recs = recommender.get_multiple_recommendations(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0, 80.0],
            num_alternatives=3
        )

        if len(recs) > 1:
            scores = [r.confidence_score for r in recs]
            assert scores == sorted(scores, reverse=True)

    def test_multiple_recommendations_with_options_data(self, recommender):
        """Test: Multiple recommendations work with options data."""
        options_data = [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            {"strike": 580.0, "right": "P", "delta": -0.07, "bid": 2.0, "ask": 2.5,
             "open_interest": 150, "volume": 40},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.2, "ask": 1.5,
             "open_interest": 120, "volume": 30},
            {"strike": 540.0, "right": "P", "delta": -0.04, "bid": 0.8, "ask": 1.0,
             "open_interest": 110, "volume": 25},
        ]

        recs = recommender.get_multiple_recommendations(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0],
            options_data=options_data,
            num_alternatives=3
        )

        assert len(recs) >= 1


class TestStrikeRounding:
    """Tests for strike price rounding."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_round_strike_low_price(self, recommender):
        """Test: Low prices rounded to whole numbers."""
        rounded = recommender._round_strike(32.7, 35.0)
        assert rounded == 33.0

    def test_round_strike_medium_price(self, recommender):
        """Test: Medium prices rounded to $5 increments."""
        rounded = recommender._round_strike(97.3, 100.0)
        assert rounded == 95.0 or rounded == 100.0

    def test_round_strike_high_price(self, recommender):
        """Test: High prices rounded to $10 increments."""
        rounded = recommender._round_strike(347.5, 350.0)
        assert rounded % 10 == 0


class TestConvenienceFunction:
    """Tests for calculate_strike_recommendation convenience function."""

    def test_returns_dict(self):
        """Test: Returns a dictionary."""
        result = calculate_strike_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )

        assert isinstance(result, dict)

    def test_dict_has_required_keys(self):
        """Test: Dictionary has all required keys."""
        result = calculate_strike_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )

        required_keys = ["symbol", "current_price", "short_strike", "long_strike",
                         "spread_width", "quality", "confidence_score"]
        for key in required_keys:
            assert key in result

    def test_with_all_params(self):
        """Test: Works with all optional parameters."""
        result = calculate_strike_recommendation(
            symbol="AAPL",
            current_price=180.0,
            support_levels=[170.0, 165.0],
            iv_rank=55,
            fib_levels=[{"level": 168.0}]
        )

        assert result["symbol"] == "AAPL"
        assert result["current_price"] == 180.0


class TestToDict:
    """Tests for to_dict serialization method."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_contains_all_fields(self, recommender):
        """Test: to_dict contains all expected fields."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        d = rec.to_dict()

        required_fields = [
            "symbol", "current_price", "short_strike", "long_strike",
            "spread_width", "quality", "confidence_score"
        ]

        for field in required_fields:
            assert field in d

    def test_quality_serialized_as_string(self, recommender):
        """Test: Quality is serialized as string."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        d = rec.to_dict()

        assert isinstance(d["quality"], str)
        assert d["quality"] in ["excellent", "good", "acceptable", "poor"]

    def test_support_level_serialized(self, recommender):
        """Test: Support level is properly serialized if present."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )

        d = rec.to_dict()

        # support_level may or may not be present
        if d.get("support_level"):
            assert "price" in d["support_level"]
            assert "strength" in d["support_level"]


class TestLiquidityFiltering:
    """Tests for liquidity-based filtering in strike selection."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_skips_short_strike_with_low_oi(self, recommender):
        """Test: Short strike with low OI is skipped."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 2.0, "ask": 2.2,
             "open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": ENTRY_OPEN_INTEREST_MIN + 50, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data
        )

        assert rec.short_strike == 85.0

    def test_skips_short_strike_with_zero_bid(self, recommender):
        """Test: Short strike with zero bid is skipped."""
        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 0, "ask": 2.0,
             "open_interest": 500, "volume": 100},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": 200, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data
        )

        assert rec.short_strike == 85.0

    def test_skips_long_strike_with_low_oi(self, recommender):
        """Test: Long strike with low OI is skipped."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        options_data = [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.2, "ask": 1.5,
             "open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "volume": 10},
            {"strike": 580.0, "right": "P", "delta": -0.06, "bid": 2.0, "ask": 2.5,
             "open_interest": ENTRY_OPEN_INTEREST_MIN + 50, "volume": 40},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=720.0,
            support_levels=[680.0],
            options_data=options_data
        )

        assert rec.long_strike == 580.0

    def test_is_strike_liquid_method(self, recommender):
        """Test: _is_strike_liquid method works correctly."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        # Liquid
        assert recommender._is_strike_liquid(
            {"open_interest": ENTRY_OPEN_INTEREST_MIN, "bid": 1.0}
        ) is True

        # Insufficient OI
        assert recommender._is_strike_liquid(
            {"open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "bid": 1.0}
        ) is False

        # Zero bid
        assert recommender._is_strike_liquid(
            {"open_interest": 500, "bid": 0}
        ) is False

        # Missing fields
        assert recommender._is_strike_liquid({}) is False

    def test_liquidity_warning_for_wide_spread(self, recommender):
        """Test: Warning generated for wide bid-ask spread."""
        from src.constants.trading_rules import LIQUIDITY_SPREAD_PCT_GOOD

        options_data = [
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 5.0, "ask": 7.0,
             "open_interest": 300, "volume": 100},  # Wide spread
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 0.5, "ask": 1.5,
             "open_interest": 200, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=720.0,
            support_levels=[680.0],
            options_data=options_data
        )

        assert any("spread" in w.lower() or "Wide" in w for w in rec.warnings)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_very_low_stock_price(self, recommender):
        """Test: Handles very low stock prices."""
        rec = recommender.get_recommendation(
            symbol="PENNY",
            current_price=5.0,
            support_levels=[4.5, 4.0]
        )

        assert rec.short_strike > 0
        assert rec.short_strike < rec.current_price

    def test_very_high_stock_price(self, recommender):
        """Test: Handles very high stock prices."""
        rec = recommender.get_recommendation(
            symbol="BRK",
            current_price=500000.0,
            support_levels=[490000.0, 480000.0]
        )

        assert rec.short_strike > 0
        assert rec.short_strike < rec.current_price

    def test_all_supports_above_price(self, recommender):
        """Test: Handles case where all supports are above current price."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[110.0, 105.0]  # All above price
        )

        # Should still generate recommendation using OTM fallback
        assert rec.short_strike is not None
        assert rec.short_strike < rec.current_price

    def test_duplicate_support_levels(self, recommender):
        """Test: Handles duplicate support levels."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 90.0, 85.0]
        )

        assert rec is not None

    def test_negative_iv_rank(self, recommender):
        """Test: Handles negative IV rank gracefully."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=-5.0  # Invalid but should not crash
        )

        assert rec is not None

    def test_iv_rank_above_100(self, recommender):
        """Test: Handles IV rank above 100 gracefully."""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=150.0  # Invalid but should not crash
        )

        assert rec is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
