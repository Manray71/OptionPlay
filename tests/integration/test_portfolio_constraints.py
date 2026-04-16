# OptionPlay - Tests für Portfolio Constraints
# =============================================
"""
Tests für Portfolio-Constraint-System.

Testet:
- Blacklist-Prüfung
- Positions-Limit
- Sektor-Limits
- Daily/Weekly Risk Budget
- Korrelations-Warnungen
- Integration mit Portfolio Handler
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from src.services.portfolio_constraints import (
    PortfolioConstraints,
    PortfolioConstraintChecker,
    ConstraintResult,
    get_constraint_checker,
    reset_constraint_checker,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    reset_constraint_checker()
    yield
    reset_constraint_checker()


@pytest.fixture
def default_constraints():
    """Default constraints for testing."""
    return PortfolioConstraints()


@pytest.fixture
def strict_constraints():
    """Strict constraints for testing edge cases."""
    return PortfolioConstraints(
        max_positions=3,
        max_per_sector=1,
        max_daily_risk_usd=1000.0,
        max_weekly_risk_usd=3000.0,
        max_position_size_usd=500.0,
        max_correlation=0.50,
        symbol_blacklist=["ROKU", "SNAP", "TSLA"],
    )


@pytest.fixture
def checker(default_constraints):
    """Create constraint checker with default constraints."""
    return PortfolioConstraintChecker(default_constraints)


@pytest.fixture
def strict_checker(strict_constraints):
    """Create constraint checker with strict constraints."""
    return PortfolioConstraintChecker(strict_constraints)


@pytest.fixture
def mock_fundamentals():
    """Mock fundamentals manager."""
    @dataclass
    class MockFundamentals:
        symbol: str
        sector: str = "Technology"
        spy_correlation_60d: float = 0.65

    manager = Mock()
    manager.get_fundamentals = Mock(side_effect=lambda s: MockFundamentals(
        symbol=s,
        sector="Technology" if s in ["AAPL", "MSFT", "GOOGL", "META"] else
               "Financial Services" if s in ["JPM", "BAC", "GS"] else
               "Energy" if s in ["XOM", "CVX"] else
               "Healthcare" if s in ["JNJ", "PFE"] else "Unknown",
        spy_correlation_60d=0.75 if s in ["AAPL", "MSFT", "SPY"] else 0.50
    ))
    return manager


# =============================================================================
# Test: PortfolioConstraints Dataclass
# =============================================================================

class TestPortfolioConstraints:
    """Tests für PortfolioConstraints Dataclass."""

    def test_default_values(self):
        """Test default constraint values."""
        c = PortfolioConstraints()

        assert c.max_positions == 5
        assert c.max_per_sector == 2
        assert c.max_daily_risk_usd == 1500.0
        assert c.max_weekly_risk_usd == 5000.0
        assert c.max_position_size_usd == 2000.0
        assert c.max_correlation == 0.70
        assert c.min_cash_reserve_pct == 0.20

    def test_blacklist_default(self):
        """Test default blacklist contains high-risk symbols."""
        c = PortfolioConstraints()

        assert "ROKU" in c.symbol_blacklist
        assert "SNAP" in c.symbol_blacklist
        assert "TSLA" in c.symbol_blacklist
        assert "COIN" in c.symbol_blacklist

    def test_custom_values(self):
        """Test custom constraint values."""
        c = PortfolioConstraints(
            max_positions=10,
            max_per_sector=3,
            max_daily_risk_usd=2000.0,
        )

        assert c.max_positions == 10
        assert c.max_per_sector == 3
        assert c.max_daily_risk_usd == 2000.0

    def test_sector_specific_limits(self):
        """Test sector-specific limits."""
        c = PortfolioConstraints(
            sector_limits={"Technology": 3, "Energy": 1}
        )

        assert c.sector_limits["Technology"] == 3
        assert c.sector_limits["Energy"] == 1


# =============================================================================
# Test: ConstraintResult
# =============================================================================

class TestConstraintResult:
    """Tests für ConstraintResult Dataclass."""

    def test_allowed_result(self):
        """Test allowed result."""
        result = ConstraintResult(
            allowed=True,
            blockers=[],
            warnings=["warning1"],
            details={"test": True}
        )

        assert result.allowed is True
        assert len(result.blockers) == 0
        assert len(result.warnings) == 1
        assert result.messages == ["warning1"]

    def test_blocked_result(self):
        """Test blocked result."""
        result = ConstraintResult(
            allowed=False,
            blockers=["blocker1", "blocker2"],
            warnings=["warning1"],
            details={}
        )

        assert result.allowed is False
        assert len(result.blockers) == 2
        assert len(result.messages) == 3

    def test_messages_combines_blockers_and_warnings(self):
        """Test messages property combines both."""
        result = ConstraintResult(
            allowed=False,
            blockers=["B1", "B2"],
            warnings=["W1"],
            details={}
        )

        assert result.messages == ["B1", "B2", "W1"]


# =============================================================================
# Test: Blacklist Check
# =============================================================================

class TestBlacklistCheck:
    """Tests für Blacklist-Prüfung."""

    def test_blacklisted_symbol_blocked(self, checker):
        """Test that blacklisted symbols are blocked."""
        result = checker.check_all_constraints(
            symbol="ROKU",
            max_risk=500.0,
            open_positions=[]
        )

        assert result.allowed is False
        assert any("Blacklist" in b for b in result.blockers)
        assert result.details.get('blacklisted') is True

    def test_blacklist_case_insensitive(self, checker):
        """Test blacklist is case insensitive."""
        result = checker.check_all_constraints(
            symbol="roku",
            max_risk=500.0,
            open_positions=[]
        )

        assert result.allowed is False
        assert any("Blacklist" in b for b in result.blockers)

    def test_non_blacklisted_symbol_allowed(self, checker):
        """Test non-blacklisted symbols are allowed."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        # May be blocked for other reasons, but not blacklist
        assert not any("Blacklist" in b for b in result.blockers)

    def test_custom_blacklist(self):
        """Test custom blacklist."""
        constraints = PortfolioConstraints(
            symbol_blacklist=["CUSTOM1", "CUSTOM2"]
        )
        checker = PortfolioConstraintChecker(constraints)

        # ROKU not in custom blacklist
        result = checker.check_all_constraints(
            symbol="ROKU",
            max_risk=500.0,
            open_positions=[]
        )
        assert not any("Blacklist" in b for b in result.blockers)

        # CUSTOM1 is blocked
        result = checker.check_all_constraints(
            symbol="CUSTOM1",
            max_risk=500.0,
            open_positions=[]
        )
        assert any("Blacklist" in b for b in result.blockers)


# =============================================================================
# Test: Position Limit Check
# =============================================================================

class TestPositionLimitCheck:
    """Tests für Positions-Limit."""

    def test_under_limit_allowed(self, checker):
        """Test positions under limit are allowed."""
        positions = [
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
        ]

        result = checker.check_all_constraints(
            symbol="GOOGL",
            max_risk=500.0,
            open_positions=positions
        )

        assert not any("Positions-Limit" in b for b in result.blockers)

    def test_at_limit_blocked(self, checker):
        """Test positions at limit are blocked."""
        positions = [
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
            {"symbol": "GOOGL"},
            {"symbol": "META"},
            {"symbol": "AMZN"},
        ]

        result = checker.check_all_constraints(
            symbol="NVDA",
            max_risk=500.0,
            open_positions=positions
        )

        assert result.allowed is False
        assert any("Positions-Limit" in b for b in result.blockers)

    def test_custom_position_limit(self):
        """Test custom position limit."""
        constraints = PortfolioConstraints(max_positions=2)
        checker = PortfolioConstraintChecker(constraints)

        positions = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]

        result = checker.check_all_constraints(
            symbol="GOOGL",
            max_risk=500.0,
            open_positions=positions
        )

        assert result.allowed is False
        assert any("2/2" in b for b in result.blockers)


# =============================================================================
# Test: Sector Limit Check
# =============================================================================

class TestSectorLimitCheck:
    """Tests für Sektor-Limit."""

    def test_sector_limit_with_mock_fundamentals(self, strict_checker, mock_fundamentals):
        """Test sector limit with mocked fundamentals."""
        # Patch the fundamentals manager
        strict_checker._fundamentals_manager = mock_fundamentals

        # Already have AAPL (Technology)
        positions = [{"symbol": "AAPL"}]

        # Try to add MSFT (also Technology) - should be blocked with max_per_sector=1
        result = strict_checker.check_all_constraints(
            symbol="MSFT",
            max_risk=400.0,
            open_positions=positions
        )

        assert any("Sektor-Limit" in b for b in result.blockers)
        assert result.details.get('sector') == "Technology"

    def test_different_sector_allowed(self, strict_checker, mock_fundamentals):
        """Test different sector is allowed."""
        strict_checker._fundamentals_manager = mock_fundamentals

        # Have AAPL (Technology)
        positions = [{"symbol": "AAPL"}]

        # Add JPM (Financial Services) - should be allowed
        result = strict_checker.check_all_constraints(
            symbol="JPM",
            max_risk=400.0,
            open_positions=positions
        )

        assert not any("Sektor-Limit" in b for b in result.blockers)

    def test_sector_specific_limits(self, mock_fundamentals):
        """Test sector-specific limits override default."""
        constraints = PortfolioConstraints(
            max_per_sector=2,
            sector_limits={"Technology": 1}  # Stricter for Tech
        )
        checker = PortfolioConstraintChecker(constraints)
        checker._fundamentals_manager = mock_fundamentals

        positions = [{"symbol": "AAPL"}]

        # Tech has limit 1, should be blocked
        result = checker.check_all_constraints(
            symbol="MSFT",
            max_risk=500.0,
            open_positions=positions
        )

        assert any("Sektor-Limit" in b for b in result.blockers)


# =============================================================================
# Test: Daily Risk Check
# =============================================================================

class TestDailyRiskCheck:
    """Tests für tägliches Risk-Budget."""

    def test_under_daily_limit_allowed(self, checker):
        """Test risk under daily limit is allowed."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        assert not any("Tages-Budget" in b for b in result.blockers)

    def test_over_daily_limit_blocked(self, checker):
        """Test risk over daily limit is blocked."""
        # Use up most of daily budget
        checker.update_risk_used(daily_risk=1400.0)

        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,  # Would exceed 1500 limit
            open_positions=[]
        )

        assert result.allowed is False
        assert any("Tages-Budget" in b for b in result.blockers)

    def test_reset_daily_risk(self, checker):
        """Test resetting daily risk."""
        checker.update_risk_used(daily_risk=1400.0)
        checker.reset_daily_risk()

        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        assert not any("Tages-Budget" in b for b in result.blockers)


# =============================================================================
# Test: Position Size Check
# =============================================================================

class TestPositionSizeCheck:
    """Tests für maximale Positions-Größe."""

    def test_under_max_size_allowed(self, checker):
        """Test position under max size is allowed."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=1500.0,  # Under 2000 limit
            open_positions=[]
        )

        assert not any("Position zu groß" in b for b in result.blockers)

    def test_over_max_size_blocked(self, checker):
        """Test position over max size is blocked."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=2500.0,  # Over 2000 limit
            open_positions=[]
        )

        assert result.allowed is False
        assert any("Position zu groß" in b for b in result.blockers)


# =============================================================================
# Test: Weekly Risk Warning
# =============================================================================

class TestWeeklyRiskWarning:
    """Tests für wöchentliches Risk-Budget (Warnung, kein Blocker)."""

    def test_weekly_warning_at_80_percent(self, checker):
        """Test warning when approaching 80% of weekly limit."""
        # Use 3600 of 5000 = 72%
        # Adding 500 would be 82% (> 80%) - should warn
        checker.update_risk_used(weekly_risk=3600.0)

        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        assert any("Wochen-Budget" in w for w in result.warnings)

    def test_no_weekly_warning_under_80_percent(self, checker):
        """Test no warning when well under 80%."""
        checker.update_risk_used(weekly_risk=2000.0)

        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        assert not any("Wochen-Budget" in w for w in result.warnings)


# =============================================================================
# Test: Correlation Check
# =============================================================================

class TestCorrelationCheck:
    """Tests für Korrelations-Warnungen."""

    def test_high_correlation_warning(self, checker, mock_fundamentals):
        """Test warning for high correlation positions."""
        checker._fundamentals_manager = mock_fundamentals
        checker.constraints.max_correlation = 0.50

        # AAPL and MSFT are both Technology = 0.75 correlation
        positions = [{"symbol": "AAPL"}]

        result = checker.check_all_constraints(
            symbol="MSFT",
            max_risk=500.0,
            open_positions=positions
        )

        assert any("Korrelation" in w for w in result.warnings)

    def test_low_correlation_no_warning(self, checker, mock_fundamentals):
        """Test no warning for low correlation."""
        checker._fundamentals_manager = mock_fundamentals

        # AAPL (Tech) and XOM (Energy) - different sectors
        positions = [{"symbol": "AAPL"}]

        result = checker.check_all_constraints(
            symbol="XOM",
            max_risk=500.0,
            open_positions=positions
        )

        # No high correlation warning (different sectors = no automatic 0.75)
        # SPY correlation based warning depends on product of correlations
        # With max_correlation=0.70 and products being lower, likely no warning
        # This test verifies no sector-based correlation warning
        high_corr_warnings = [w for w in result.warnings if "Korrelation" in w and "0.75" in w]
        assert len(high_corr_warnings) == 0


# =============================================================================
# Test: Same Sector Warning
# =============================================================================

class TestSameSectorWarning:
    """Tests für Sektor-Warnungen (nicht Blocker)."""

    def test_same_sector_warning(self, checker, mock_fundamentals):
        """Test warning when adding to same sector (under limit)."""
        checker._fundamentals_manager = mock_fundamentals

        positions = [{"symbol": "AAPL"}]

        result = checker.check_all_constraints(
            symbol="MSFT",
            max_risk=500.0,
            open_positions=positions
        )

        assert any("Position(en) im Sektor" in w for w in result.warnings)


# =============================================================================
# Test: can_open_position Helper
# =============================================================================

class TestCanOpenPosition:
    """Tests für can_open_position Helper."""

    def test_returns_tuple(self, checker):
        """Test can_open_position returns (bool, list)."""
        allowed, messages = checker.can_open_position(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        assert isinstance(allowed, bool)
        assert isinstance(messages, list)

    def test_blocked_returns_false(self, checker):
        """Test blocked position returns False."""
        allowed, messages = checker.can_open_position(
            symbol="ROKU",  # Blacklisted
            max_risk=500.0,
            open_positions=[]
        )

        assert allowed is False
        assert len(messages) > 0


# =============================================================================
# Test: get_status
# =============================================================================

class TestGetStatus:
    """Tests für get_status Methode."""

    def test_status_contains_constraints(self, checker):
        """Test status contains constraint config."""
        status = checker.get_status()

        assert 'constraints' in status
        assert status['constraints']['max_positions'] == 5
        assert status['constraints']['max_daily_risk_usd'] == 1500.0

    def test_status_contains_current(self, checker):
        """Test status contains current values."""
        checker.update_risk_used(daily_risk=500.0, weekly_risk=1000.0)
        status = checker.get_status()

        assert 'current' in status
        assert status['current']['daily_risk_used'] == 500.0
        assert status['current']['weekly_risk_used'] == 1000.0
        assert status['current']['daily_remaining'] == 1000.0


# =============================================================================
# Test: Singleton Pattern
# =============================================================================

class TestSingleton:
    """Tests für Singleton-Pattern."""

    def test_get_constraint_checker_returns_same_instance(self):
        """Test singleton returns same instance."""
        checker1 = get_constraint_checker()
        checker2 = get_constraint_checker()

        assert checker1 is checker2

    def test_reset_creates_new_instance(self):
        """Test reset creates new instance."""
        checker1 = get_constraint_checker()
        reset_constraint_checker()
        checker2 = get_constraint_checker()

        assert checker1 is not checker2

    def test_custom_constraints_on_first_call(self):
        """Test custom constraints only work on first call."""
        custom = PortfolioConstraints(max_positions=10)
        checker = get_constraint_checker(custom)

        assert checker.constraints.max_positions == 10


# =============================================================================
# Test: Multiple Constraints Combined
# =============================================================================

class TestMultipleConstraints:
    """Tests für kombinierte Constraints."""

    def test_multiple_blockers(self, strict_checker):
        """Test multiple blockers at once."""
        # Blacklisted + too large + at limit
        positions = [
            {"symbol": "A"},
            {"symbol": "B"},
            {"symbol": "C"},
        ]

        result = strict_checker.check_all_constraints(
            symbol="ROKU",  # Blacklisted
            max_risk=1000.0,  # Over 500 limit AND over daily budget
            open_positions=positions  # At 3/3 limit
        )

        assert result.allowed is False
        assert len(result.blockers) >= 2  # Multiple reasons

    def test_blockers_and_warnings(self, strict_checker, mock_fundamentals):
        """Test having both blockers and warnings."""
        strict_checker._fundamentals_manager = mock_fundamentals
        strict_checker.update_risk_used(weekly_risk=2600.0)  # Near 80% of 3000

        positions = [{"symbol": "AAPL"}]  # 1 position

        result = strict_checker.check_all_constraints(
            symbol="MSFT",  # Same sector as AAPL
            max_risk=400.0,
            open_positions=positions
        )

        # Should have sector limit blocker (max_per_sector=1)
        assert any("Sektor-Limit" in b for b in result.blockers)
        # Should have weekly warning
        assert any("Wochen-Budget" in w for w in result.warnings)


# =============================================================================
# Test: VIX-Dynamic Limits (Task 4.2)
# =============================================================================

class TestVIXDynamicLimits:
    """Tests für VIX-abhängige Portfolio-Limits."""

    def test_get_position_limits_low_vix(self, checker):
        """VIX < 15 → LOW_VOL limits."""
        limits = checker.get_position_limits(vix=12.0)
        assert limits["max_positions"] == 10
        assert limits["max_per_sector"] == 2
        assert limits["risk_per_trade_pct"] == 2.5
        assert limits["new_trades_allowed"] is True
        assert limits["regime"] == "LOW_VOL"

    def test_get_position_limits_normal_vix(self, checker):
        """VIX 15-20 → NORMAL limits."""
        limits = checker.get_position_limits(vix=18.0)
        assert limits["max_positions"] == 10
        assert limits["max_per_sector"] == 2
        assert limits["new_trades_allowed"] is True
        assert limits["regime"] == "NORMAL"

    def test_get_position_limits_danger_zone(self, checker):
        """VIX 20-25 → DANGER_ZONE limits."""
        limits = checker.get_position_limits(vix=22.0)
        assert limits["max_positions"] == 5
        assert limits["max_per_sector"] == 1
        assert limits["risk_per_trade_pct"] == 1.5
        assert limits["new_trades_allowed"] is True
        assert limits["regime"] == "DANGER_ZONE"

    def test_get_position_limits_elevated(self, checker):
        """VIX 25-30 → ELEVATED limits."""
        limits = checker.get_position_limits(vix=27.0)
        assert limits["max_positions"] == 3
        assert limits["max_per_sector"] == 1
        assert limits["risk_per_trade_pct"] == 1.0
        assert limits["new_trades_allowed"] is True
        assert limits["regime"] == "ELEVATED"

    def test_get_position_limits_high_vol(self, checker):
        """VIX > 30 → HIGH_VOL: no new trades."""
        limits = checker.get_position_limits(vix=32.0)
        assert limits["max_positions"] == 0
        assert limits["new_trades_allowed"] is False
        assert limits["regime"] == "HIGH_VOL"

    def test_get_position_limits_no_trading(self, checker):
        """VIX > 35 → NO_TRADING: all stop."""
        limits = checker.get_position_limits(vix=38.0)
        assert limits["max_positions"] == 0
        assert limits["new_trades_allowed"] is False
        assert limits["regime"] == "NO_TRADING"

    def test_get_position_limits_no_vix_fallback(self, checker):
        """No VIX → static defaults."""
        limits = checker.get_position_limits(vix=None)
        assert limits["max_positions"] == checker.constraints.max_positions
        assert limits["max_per_sector"] == checker.constraints.max_per_sector
        assert limits["regime"] == "UNKNOWN"

    def test_vix_provider_used(self, checker):
        """VIX provider is used when vix not passed."""
        checker.set_vix_provider(lambda: 22.0)
        limits = checker.get_position_limits()
        assert limits["regime"] == "DANGER_ZONE"
        assert limits["max_positions"] == 5

    def test_vix_provider_exception_fallback(self, checker):
        """VIX provider exception → fallback to static defaults."""
        checker.set_vix_provider(lambda: (_ for _ in ()).throw(RuntimeError("VIX error")))
        limits = checker.get_position_limits()
        assert limits["regime"] == "UNKNOWN"

    def test_check_all_constraints_danger_zone_limits(self, checker):
        """VIX 22 → Danger Zone limits applied to check."""
        positions = [
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
            {"symbol": "GOOGL"},
            {"symbol": "META"},
            {"symbol": "AMZN"},
        ]
        result = checker.check_all_constraints(
            symbol="NVDA",
            max_risk=500.0,
            open_positions=positions,
            current_vix=22.0,  # DANGER_ZONE: max 5 positions
        )
        assert result.allowed is False
        assert any("Positions-Limit" in b for b in result.blockers)
        assert result.details['vix_regime'] == "DANGER_ZONE"
        assert result.details['max_positions'] == 5

    def test_check_all_constraints_high_vol_blocks_all(self, checker):
        """VIX > 30 → blocks all new trades."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[],
            current_vix=32.0,
        )
        assert result.allowed is False
        assert any("Keine neuen Trades" in b for b in result.blockers)

    def test_check_all_constraints_no_vix_uses_static(self, checker):
        """Without VIX, uses static defaults."""
        positions = [
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
        ]
        result = checker.check_all_constraints(
            symbol="GOOGL",
            max_risk=500.0,
            open_positions=positions,
        )
        # Static default is 5 positions, 2 used → allowed
        assert not any("Positions-Limit" in b for b in result.blockers)

    def test_acceptance_vix_22_limits(self):
        """TASKS acceptance: VIX 22 → max_positions=5, max_per_sector=1."""
        checker = PortfolioConstraintChecker()
        limits = checker.get_position_limits(vix=22.0)
        assert limits["max_positions"] == 5
        assert limits["max_per_sector"] == 1


# =============================================================================
# Test: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests für Edge Cases."""

    def test_empty_positions_list(self, checker):
        """Test with empty positions list."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[]
        )

        assert result.details['current_positions'] == 0

    def test_position_without_symbol(self, checker):
        """Test handling position without symbol key."""
        positions = [
            {"symbol": "AAPL"},
            {},  # Missing symbol
            {"other": "data"},
        ]

        # Should not crash
        result = checker.check_all_constraints(
            symbol="MSFT",
            max_risk=500.0,
            open_positions=positions
        )

        assert isinstance(result, ConstraintResult)

    def test_zero_max_risk(self, checker):
        """Test with zero max risk."""
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=0.0,
            open_positions=[]
        )

        assert not any("Position zu groß" in b for b in result.blockers)

    def test_fundamentals_unavailable(self, checker):
        """Test when fundamentals manager unavailable."""
        # Don't set fundamentals manager
        checker._fundamentals_manager = None

        # Should not crash, just skip sector checks
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500.0,
            open_positions=[{"symbol": "MSFT"}]
        )

        assert isinstance(result, ConstraintResult)
        # Sector should be Unknown
        assert result.details.get('sector', 'Unknown') == 'Unknown' or \
               'sector' not in result.details


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
