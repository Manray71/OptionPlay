# Tests for VIX Regime v2 Integration
# ====================================
# Tests for get_regime_rules_v2() and VIXStrategySelector.get_recommendation_v2()

import pytest

from src.constants.trading_rules import (
    VIXRegime,
    VIXRegimeRules,
    get_regime_rules,
    get_regime_rules_v2,
    get_vix_regime,
)
from src.services.vix_strategy import (
    MarketRegime,
    StrategyRecommendation,
    VIXStrategySelector,
)


# =============================================================================
# get_regime_rules_v2 TESTS
# =============================================================================


class TestGetRegimeRulesV2:
    """Test the v2 interpolated regime rules function."""

    def test_returns_vix_regime_rules(self):
        """Returns a VIXRegimeRules dataclass."""
        rules = get_regime_rules_v2(20.0)
        assert isinstance(rules, VIXRegimeRules)

    def test_max_positions_interpolated(self):
        """max_positions comes from v2 interpolation, not v1 lookup."""
        rules = get_regime_rules_v2(20.0)
        assert rules.max_positions == 4  # v2 anchor at VIX 20

    def test_max_per_sector_interpolated(self):
        """max_per_sector derived from v2 max_positions."""
        rules = get_regime_rules_v2(10.0)
        assert rules.max_per_sector == 2  # 6 // 3

    def test_stability_min_from_v1(self):
        """stability_min falls back to v1 lookup."""
        rules_v2 = get_regime_rules_v2(20.0)
        rules_v1 = get_regime_rules(20.0)
        assert rules_v2.stability_min == rules_v1.stability_min

    def test_risk_per_trade_from_v1(self):
        """risk_per_trade_pct falls back to v1 lookup."""
        rules_v2 = get_regime_rules_v2(20.0)
        rules_v1 = get_regime_rules(20.0)
        assert rules_v2.risk_per_trade_pct == rules_v1.risk_per_trade_pct

    def test_profit_exit_from_v1(self):
        """profit_exit_pct falls back to v1 lookup."""
        rules_v2 = get_regime_rules_v2(20.0)
        rules_v1 = get_regime_rules(20.0)
        assert rules_v2.profit_exit_pct == rules_v1.profit_exit_pct

    def test_new_trades_allowed_from_v2(self):
        """new_trades_allowed based on v2 max_positions > 0."""
        rules_low = get_regime_rules_v2(15.0)
        assert rules_low.new_trades_allowed is True

        rules_extreme = get_regime_rules_v2(40.0)
        assert rules_extreme.new_trades_allowed is False

    def test_notes_contain_v2_label(self):
        """Notes indicate VIX Regime v2."""
        rules = get_regime_rules_v2(20.0)
        assert "VIX Regime v2" in rules.notes
        assert "NORMAL" in rules.notes

    def test_with_term_structure(self):
        """Term structure adjusts v2 parameters."""
        rules_base = get_regime_rules_v2(28.0)
        rules_contango = get_regime_rules_v2(28.0, vix_futures_front=32.0)
        # Contango gives +1 max_pos
        assert rules_contango.max_positions >= rules_base.max_positions

    def test_regime_from_v1(self):
        """regime label uses v1 VIXRegime enum."""
        rules = get_regime_rules_v2(22.0)
        assert isinstance(rules.regime, VIXRegime)
        assert rules.regime == VIXRegime.DANGER_ZONE

    @pytest.mark.parametrize("vix", [8, 12, 17, 22, 27, 32, 37, 42])
    def test_no_crash_across_range(self, vix):
        """get_regime_rules_v2 works for full VIX range."""
        rules = get_regime_rules_v2(float(vix))
        assert rules.max_positions >= 0
        assert rules.max_per_sector >= 0


# =============================================================================
# VIXStrategySelector.get_recommendation_v2 TESTS
# =============================================================================


class TestGetRecommendationV2:
    """Test the v2 recommendation method."""

    def setup_method(self):
        self.selector = VIXStrategySelector()

    def test_returns_strategy_recommendation(self):
        """Returns a StrategyRecommendation."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert isinstance(rec, StrategyRecommendation)

    def test_delta_from_playbook(self):
        """Delta is always fixed from Playbook."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert rec.delta_target == -0.20

    def test_spread_width_set(self):
        """spread_width populated from v2 (v1 returns None)."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert rec.spread_width is not None
        assert rec.spread_width == 5.00

    def test_min_score_interpolated(self):
        """min_score from interpolation."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert rec.min_score == 4  # int(4.5) = 4

    def test_earnings_buffer_interpolated(self):
        """earnings_buffer_days from interpolation."""
        rec = self.selector.get_recommendation_v2(30.0)
        assert rec.earnings_buffer_days == 75

    def test_profile_name_v2_prefix(self):
        """Profile name starts with v2_."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert rec.profile_name.startswith("v2_")

    def test_regime_mapped(self):
        """regime is a MarketRegime enum."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert isinstance(rec.regime, MarketRegime)

    def test_reasoning_contains_regime(self):
        """Reasoning includes regime label."""
        rec = self.selector.get_recommendation_v2(20.0)
        assert "NORMAL" in rec.reasoning

    def test_none_vix_falls_back_to_v1(self):
        """None VIX falls back to v1 get_recommendation."""
        rec = self.selector.get_recommendation_v2(None)
        assert rec.regime is None

    def test_with_term_structure(self):
        """Term structure info in recommendation."""
        rec = self.selector.get_recommendation_v2(
            28.0, vix_futures_front=25.0
        )
        assert "backwardation" in rec.reasoning.lower()
        assert any("STRESS" in w for w in rec.warnings)

    def test_with_trend(self):
        """Trend info in recommendation."""
        rec = self.selector.get_recommendation_v2(
            24.0, vix_trend="rising_fast"
        )
        assert any("rising_fast" in w for w in rec.warnings)

    def test_extreme_vix_no_trades_warning(self):
        """Extreme VIX shows no-trade warning."""
        rec = self.selector.get_recommendation_v2(42.0)
        assert any("NO NEW TRADES" in w for w in rec.warnings)

    def test_to_dict_works(self):
        """to_dict() works on v2 recommendation."""
        rec = self.selector.get_recommendation_v2(20.0)
        d = rec.to_dict()
        assert "profile" in d
        assert "regime" in d
        assert "recommendations" in d

    @pytest.mark.parametrize("vix", [8, 15, 20, 25, 30, 35, 40])
    def test_no_crash_across_range(self, vix):
        """v2 recommendation works across full VIX range."""
        rec = self.selector.get_recommendation_v2(float(vix))
        assert rec.vix_level == float(vix)
        assert rec.delta_target == -0.20
