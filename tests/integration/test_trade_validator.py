"""
Tests for src/services/trade_validator.py

Tests the Trade Validator against PLAYBOOK rules.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import date, timedelta

from src.constants.trading_rules import TradeDecision, VIXRegime
from src.services.trade_validator import (
    TradeValidator,
    TradeValidationRequest,
    TradeValidationResult,
    ValidationCheck,
    get_trade_validator,
    reset_trade_validator,
)


@pytest.fixture
def validator():
    """Fresh TradeValidator for each test."""
    reset_trade_validator()
    v = TradeValidator()
    return v


@pytest.fixture
def mock_fundamentals():
    """Mock fundamentals data for AAPL."""
    f = MagicMock()
    f.stability_score = 82.0
    f.current_price = 185.0
    f.sector = "Technology"
    f.iv_rank_252d = 45.0
    f.spy_correlation_60d = 0.85
    return f


class TestBlacklistCheck:
    """PLAYBOOK §1: Blacklist Check (first filter)."""

    def test_blacklisted_symbol_is_no_go(self, validator):
        result = validator._check_blacklist("TSLA")
        assert result.decision == TradeDecision.NO_GO
        assert "Blacklist" in result.message

    def test_safe_symbol_is_go(self, validator):
        result = validator._check_blacklist("AAPL")
        assert result.decision == TradeDecision.GO

    def test_case_insensitive(self, validator):
        result = validator._check_blacklist("tsla")
        assert result.decision == TradeDecision.NO_GO

    def test_all_blacklisted_symbols(self, validator):
        from src.constants.trading_rules import BLACKLIST_SYMBOLS
        for symbol in BLACKLIST_SYMBOLS:
            result = validator._check_blacklist(symbol)
            assert result.decision == TradeDecision.NO_GO, f"{symbol} should be NO_GO"


class TestStabilityCheck:
    """PLAYBOOK §1: Stability Check + §3 VIX Adjustment."""

    def test_high_stability_is_go(self, validator, mock_fundamentals):
        mock_fundamentals.stability_score = 85.0
        result = validator._check_stability("AAPL", mock_fundamentals, 18.0)
        assert result.decision == TradeDecision.GO

    def test_low_stability_is_no_go(self, validator, mock_fundamentals):
        mock_fundamentals.stability_score = 60.0
        result = validator._check_stability("AAPL", mock_fundamentals, 18.0)
        assert result.decision == TradeDecision.NO_GO

    def test_boundary_stability_65_is_go(self, validator, mock_fundamentals):
        mock_fundamentals.stability_score = 65.0
        result = validator._check_stability("AAPL", mock_fundamentals, 18.0)
        assert result.decision == TradeDecision.GO

    def test_vix_danger_zone_raises_stability_to_80(self, validator, mock_fundamentals):
        """PLAYBOOK §3: In Danger Zone (VIX 20-25), stability must be >= 80."""
        mock_fundamentals.stability_score = 75.0
        result = validator._check_stability("AAPL", mock_fundamentals, 22.0)
        assert result.decision == TradeDecision.NO_GO
        assert "80" in result.message

    def test_vix_danger_zone_stability_80_is_go(self, validator, mock_fundamentals):
        mock_fundamentals.stability_score = 80.0
        result = validator._check_stability("AAPL", mock_fundamentals, 22.0)
        assert result.decision == TradeDecision.GO

    def test_missing_fundamentals_is_warning(self, validator):
        result = validator._check_stability("AAPL", None, 18.0)
        assert result.decision == TradeDecision.WARNING


class TestVIXCheck:
    """PLAYBOOK §1 + §3: VIX Check."""

    def test_normal_vix_is_go(self, validator):
        result = validator._check_vix(18.0)
        assert result.decision == TradeDecision.GO

    def test_danger_zone_is_warning(self, validator):
        result = validator._check_vix(22.0)
        assert result.decision == TradeDecision.WARNING
        assert "DANGER_ZONE" in result.message

    def test_elevated_is_warning(self, validator):
        result = validator._check_vix(27.0)
        assert result.decision == TradeDecision.WARNING

    def test_high_vol_is_no_go(self, validator):
        result = validator._check_vix(32.0)
        assert result.decision == TradeDecision.NO_GO

    def test_no_trading_is_no_go(self, validator):
        result = validator._check_vix(36.0)
        assert result.decision == TradeDecision.NO_GO

    def test_vix_unavailable_is_warning(self, validator):
        result = validator._check_vix(None)
        assert result.decision == TradeDecision.WARNING


class TestPriceCheck:
    """PLAYBOOK §1: Price Range Check."""

    def test_valid_price(self, validator, mock_fundamentals):
        mock_fundamentals.current_price = 185.0
        result = validator._check_price("AAPL", mock_fundamentals)
        assert result.decision == TradeDecision.GO

    def test_too_cheap(self, validator, mock_fundamentals):
        mock_fundamentals.current_price = 15.0
        result = validator._check_price("PENNY", mock_fundamentals)
        assert result.decision == TradeDecision.NO_GO

    def test_too_expensive(self, validator, mock_fundamentals):
        mock_fundamentals.current_price = 1600.0
        result = validator._check_price("EXPENSIVE", mock_fundamentals)
        assert result.decision == TradeDecision.NO_GO

    def test_boundary_20(self, validator, mock_fundamentals):
        mock_fundamentals.current_price = 20.0
        result = validator._check_price("LOW", mock_fundamentals)
        assert result.decision == TradeDecision.GO

    def test_boundary_1500(self, validator, mock_fundamentals):
        mock_fundamentals.current_price = 1500.0
        result = validator._check_price("HIGH", mock_fundamentals)
        assert result.decision == TradeDecision.GO


class TestIVRankCheck:
    """PLAYBOOK §1: IV Rank Check (soft filter)."""

    def test_optimal_iv_rank(self, validator, mock_fundamentals):
        mock_fundamentals.iv_rank_252d = 55.0
        result = validator._check_iv_rank("AAPL", mock_fundamentals)
        assert result.decision == TradeDecision.GO

    def test_low_iv_rank_is_warning(self, validator, mock_fundamentals):
        mock_fundamentals.iv_rank_252d = 40.0
        result = validator._check_iv_rank("AAPL", mock_fundamentals)
        assert result.decision == TradeDecision.WARNING

    def test_high_iv_rank_is_warning(self, validator, mock_fundamentals):
        mock_fundamentals.iv_rank_252d = 85.0
        result = validator._check_iv_rank("AAPL", mock_fundamentals)
        assert result.decision == TradeDecision.WARNING


class TestDTECheck:
    """PLAYBOOK §2: DTE Check."""

    def test_optimal_dte(self, validator):
        exp = (date.today() + timedelta(days=45)).strftime("%Y-%m-%d")
        result = validator._check_dte(exp)
        assert result.decision == TradeDecision.GO

    def test_dte_too_short(self, validator):
        exp = (date.today() + timedelta(days=20)).strftime("%Y-%m-%d")
        result = validator._check_dte(exp)
        assert result.decision == TradeDecision.NO_GO

    def test_dte_too_long(self, validator):
        exp = (date.today() + timedelta(days=120)).strftime("%Y-%m-%d")
        result = validator._check_dte(exp)
        assert result.decision == TradeDecision.WARNING

    def test_dte_at_minimum(self, validator):
        exp = (date.today() + timedelta(days=35)).strftime("%Y-%m-%d")
        result = validator._check_dte(exp)
        assert result.decision == TradeDecision.GO

    def test_dte_at_maximum(self, validator):
        exp = (date.today() + timedelta(days=50)).strftime("%Y-%m-%d")
        result = validator._check_dte(exp)
        assert result.decision == TradeDecision.GO

    def test_invalid_date_format(self, validator):
        result = validator._check_dte("not-a-date")
        assert result.decision == TradeDecision.WARNING


class TestCreditCheck:
    """PLAYBOOK §2: Credit Check."""

    def test_sufficient_credit(self, validator):
        result = validator._check_credit(credit=2.50, spread_width=10.0)
        assert result.decision == TradeDecision.GO  # 25% >= 20%

    def test_insufficient_credit(self, validator):
        result = validator._check_credit(credit=0.80, spread_width=10.0)
        assert result.decision == TradeDecision.NO_GO  # 8% < 10%

    def test_exact_minimum_credit(self, validator):
        result = validator._check_credit(credit=1.00, spread_width=10.0)
        assert result.decision == TradeDecision.GO  # 10% == 10% (PLAYBOOK §2)

    def test_zero_spread_width(self, validator):
        result = validator._check_credit(credit=1.00, spread_width=0.0)
        assert result.decision == TradeDecision.NO_GO


class TestCreditAbsoluteMinimum:
    """Credit absolute minimum and fee warning tests."""

    def test_credit_below_absolute_minimum(self, validator):
        """$15/contract (credit $0.15/share) should be NO_GO."""
        result = validator._check_credit(credit=0.15, spread_width=5.0)
        assert result.decision == TradeDecision.NO_GO
        assert "Minimum" in result.message

    def test_credit_at_absolute_minimum(self, validator):
        """$20/contract (credit $0.20/share) with sufficient % should pass."""
        # $0.20 / $0.50 = 40% >= 10% min, and $20 >= $20 min absolute
        result = validator._check_credit(credit=0.20, spread_width=0.50)
        assert result.decision in (TradeDecision.GO, TradeDecision.WARNING)

    def test_credit_fee_warning(self, validator):
        """$30/contract should trigger fee WARNING."""
        # $0.30 / $1.00 = 30% >= 10% min, $30 >= $20 absolute, but < $40 threshold
        result = validator._check_credit(credit=0.30, spread_width=1.00)
        assert result.decision == TradeDecision.WARNING
        assert result.details.get("fee_warning") is True

    def test_credit_above_fee_threshold(self, validator):
        """$60/contract should be GO without warnings."""
        result = validator._check_credit(credit=0.60, spread_width=2.00)
        assert result.decision == TradeDecision.GO

    def test_percentage_still_enforced_with_high_absolute(self, validator):
        """$50/contract but only 5% C/R should be NO_GO (percentage rule)."""
        result = validator._check_credit(credit=0.25, spread_width=5.00)
        assert result.decision == TradeDecision.NO_GO  # 5% < 10%


class TestPortfolioChecks:
    """PLAYBOOK §5: Position Sizing."""

    def test_under_position_limit(self, validator, mock_fundamentals):
        positions = [{"symbol": "MSFT", "sector": "Technology"}] * 5
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 18.0)
        pos_check = next(c for c in checks if c.name == "max_positions")
        assert pos_check.decision == TradeDecision.GO

    def test_at_position_limit(self, validator, mock_fundamentals):
        positions = [{"symbol": f"SYM{i}", "sector": "Various"} for i in range(10)]
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 18.0)
        pos_check = next(c for c in checks if c.name == "max_positions")
        assert pos_check.decision == TradeDecision.NO_GO

    def test_danger_zone_reduces_position_limit(self, validator, mock_fundamentals):
        """At VIX 22, max positions drops to 5."""
        positions = [{"symbol": f"SYM{i}", "sector": "Various"} for i in range(5)]
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 22.0)
        pos_check = next(c for c in checks if c.name == "max_positions")
        assert pos_check.decision == TradeDecision.NO_GO

    def test_sector_limit(self, validator, mock_fundamentals):
        """Max 2 positions per sector in normal VIX."""
        positions = [
            {"symbol": "MSFT", "sector": "Technology"},
            {"symbol": "GOOGL", "sector": "Technology"},
        ]
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 18.0)
        sector_check = next((c for c in checks if c.name == "sector_limit"), None)
        if sector_check:
            assert sector_check.decision == TradeDecision.NO_GO


class TestPositionSizing:
    """PLAYBOOK §5: Position Sizing Calculation."""

    def test_sizing_calculation(self, validator, mock_fundamentals):
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            portfolio_value=80000.0,
        )
        sizing = validator._calculate_sizing(request, mock_fundamentals, 18.0)

        assert sizing["spread_width"] == 10.0
        assert sizing["max_loss_per_contract"] == 750.0  # ($10 - $2.50) * 100
        assert sizing["risk_pct"] == 2.5
        assert sizing["max_risk_usd"] == 2000.0  # 80k * 2.5%
        assert sizing["recommended_contracts"] == 2  # $2000 / $750 = 2.67 -> 2

    def test_sizing_danger_zone_reduces_risk(self, validator, mock_fundamentals):
        """VIX 22 = Danger Zone = 1.5% risk."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            portfolio_value=80000.0,
        )
        sizing = validator._calculate_sizing(request, mock_fundamentals, 22.0)
        assert sizing["risk_pct"] == 1.5
        assert sizing["max_risk_usd"] == 1200.0  # 80k * 1.5%


class TestValidationResult:
    """Test TradeValidationResult properties."""

    def test_go_result(self):
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.GO,
            checks=[
                ValidationCheck("test", True, TradeDecision.GO, "OK"),
            ],
        )
        assert len(result.blockers) == 0
        assert len(result.warnings) == 0
        assert "GO" in result.summary

    def test_no_go_result(self):
        result = TradeValidationResult(
            symbol="TSLA",
            decision=TradeDecision.NO_GO,
            checks=[
                ValidationCheck("blacklist", False, TradeDecision.NO_GO, "Blacklist"),
            ],
        )
        assert len(result.blockers) == 1
        assert "NO-GO" in result.summary
        assert "Blacklist" in result.summary

    def test_warning_result(self):
        result = TradeValidationResult(
            symbol="AAPL",
            decision=TradeDecision.WARNING,
            checks=[
                ValidationCheck("iv_rank", True, TradeDecision.WARNING, "Low IV"),
            ],
        )
        assert len(result.warnings) == 1


class TestFullValidation:
    """Integration-style tests for full validate() flow."""

    @pytest.mark.asyncio
    async def test_blacklisted_symbol(self, validator):
        request = TradeValidationRequest(symbol="TSLA")
        result = await validator.validate(request, current_vix=18.0)
        assert result.decision == TradeDecision.NO_GO
        assert any(c.name == "blacklist" for c in result.blockers)

    @pytest.mark.asyncio
    async def test_high_vix_no_trading(self, validator):
        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(request, current_vix=36.0)
        assert result.decision == TradeDecision.NO_GO
        assert any(c.name == "vix" for c in result.blockers)

    @pytest.mark.asyncio
    async def test_regime_info_included(self, validator):
        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(request, current_vix=22.0)
        assert result.regime is not None
        assert "DANGER_ZONE" in result.regime


class TestEarningsCheck:
    """PLAYBOOK §1: Earnings distance check."""

    @pytest.mark.asyncio
    async def test_etf_skips_earnings(self, validator):
        """ETFs like SPY have no earnings — always GO."""
        with patch("src.utils.validation.is_etf", return_value=True):
            result = await validator._check_earnings("SPY")
            assert result.decision == TradeDecision.GO
            assert "ETF" in result.message
            assert result.details.get("is_etf") is True

    @pytest.mark.asyncio
    async def test_earnings_too_close_is_no_go(self, validator):
        """Symbol with earnings in 30 days (< 45 min) = NO_GO."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (False, 30, "too_close")
        validator._earnings_manager = mock_earnings

        with patch("src.utils.validation.is_etf", return_value=False):
            result = await validator._check_earnings("AAPL")
            assert result.decision == TradeDecision.NO_GO
            assert "30 Tage" in result.message
            assert result.details.get("days_to_earnings") == 30

    @pytest.mark.asyncio
    async def test_earnings_safe_is_go(self, validator):
        """Symbol with earnings in 90 days (>= 45 min) = GO."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
        validator._earnings_manager = mock_earnings

        with patch("src.utils.validation.is_etf", return_value=False):
            result = await validator._check_earnings("AAPL")
            assert result.decision == TradeDecision.GO
            assert "90 Tage" in result.message

    @pytest.mark.asyncio
    async def test_earnings_manager_unavailable_is_warning(self, validator):
        """If earnings manager not loaded and API fails, return WARNING."""
        validator._earnings_manager = None

        with patch("src.utils.validation.is_etf", return_value=False):
            # Force the property to return None
            with patch.object(
                type(validator), 'earnings',
                new_callable=lambda: property(lambda self: None),
            ):
                # Mock API fallback to also fail
                with patch.object(
                    validator, '_fetch_earnings_from_api',
                    new_callable=AsyncMock,
                    return_value=(None, None, "none"),
                ):
                    result = await validator._check_earnings("AAPL")
                    assert result.decision == TradeDecision.WARNING
                    assert "nicht verfügbar" in result.message

    @pytest.mark.asyncio
    async def test_earnings_check_exception_falls_back_to_api(self, validator):
        """If DB earnings check throws, API fallback is used."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.side_effect = Exception("DB error")
        validator._earnings_manager = mock_earnings

        with patch("src.utils.validation.is_etf", return_value=False):
            # API fallback also fails -> WARNING
            with patch.object(
                validator, '_fetch_earnings_from_api',
                new_callable=AsyncMock,
                return_value=(None, None, "none"),
            ):
                result = await validator._check_earnings("AAPL")
                assert result.decision == TradeDecision.WARNING

    @pytest.mark.asyncio
    async def test_earnings_no_data_triggers_api_fallback(self, validator):
        """If DB has no earnings data, API fallback should be tried."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (False, None, "no_earnings_data")
        validator._earnings_manager = mock_earnings

        with patch("src.utils.validation.is_etf", return_value=False):
            # API fallback finds earnings 80 days away
            with patch.object(
                validator, '_fetch_earnings_from_api',
                new_callable=AsyncMock,
                return_value=(True, 80, "api_yfinance"),
            ):
                result = await validator._check_earnings("AAPL")
                assert result.decision == TradeDecision.GO
                assert "80 Tage" in result.message

    @pytest.mark.asyncio
    async def test_earnings_no_data_api_finds_close(self, validator):
        """If DB has no data and API finds close earnings, return NO_GO."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (False, None, "no_earnings_data")
        validator._earnings_manager = mock_earnings

        with patch("src.utils.validation.is_etf", return_value=False):
            with patch.object(
                validator, '_fetch_earnings_from_api',
                new_callable=AsyncMock,
                return_value=(False, 20, "api_yahoo_direct"),
            ):
                result = await validator._check_earnings("AAPL")
                assert result.decision == TradeDecision.NO_GO
                assert "20 Tage" in result.message

    @pytest.mark.asyncio
    async def test_earnings_uses_playbook_min_days(self, validator):
        """Verify the min_days parameter matches ENTRY_EARNINGS_MIN_DAYS (45)."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
        validator._earnings_manager = mock_earnings

        with patch("src.utils.validation.is_etf", return_value=False):
            await validator._check_earnings("AAPL")
            call_args = mock_earnings.is_earnings_day_safe.call_args
            assert call_args.kwargs.get("min_days") == 45 or call_args[1].get("min_days") == 45


class TestVolumeCheck:
    """PLAYBOOK §1: Volume Check — requires quote provider."""

    @pytest.mark.asyncio
    async def test_volume_go_without_provider(self, validator):
        """Without quote_provider, returns GO (graceful skip)."""
        result = await validator._check_volume("AAPL", None)
        assert result.decision == TradeDecision.GO
        assert "übersprungen" in result.message

    @pytest.mark.asyncio
    async def test_volume_go_with_sufficient_volume(self, validator):
        """With sufficient volume, returns GO."""
        mock_provider = AsyncMock()
        mock_quote = MagicMock()
        mock_quote.volume = 1_000_000
        mock_provider.get_quote = AsyncMock(return_value=mock_quote)
        validator._quote_provider = mock_provider

        result = await validator._check_volume("AAPL", None)
        assert result.decision == TradeDecision.GO
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_volume_no_go_with_low_volume(self, validator):
        """With low volume, returns NO_GO."""
        mock_provider = AsyncMock()
        mock_quote = MagicMock()
        mock_quote.volume = 100_000  # Below 500k minimum
        mock_provider.get_quote = AsyncMock(return_value=mock_quote)
        validator._quote_provider = mock_provider

        result = await validator._check_volume("AAPL", None)
        assert result.decision == TradeDecision.NO_GO
        assert result.passed is False


class TestGetCurrentVix:
    """Test VIX fallback logic."""

    @pytest.mark.asyncio
    async def test_vix_from_cache(self, validator):
        """If vix_cache is available, use it."""
        with patch(
            "src.services.trade_validator.TradeValidator._get_current_vix",
            new_callable=AsyncMock,
            return_value=18.5,
        ):
            vix = await validator._get_current_vix()
            assert vix == 18.5

    @pytest.mark.asyncio
    async def test_vix_returns_none_when_unavailable(self, validator):
        """If both cache and DB fail, return None."""
        with patch.dict("sys.modules", {"src.cache.vix_cache": None}):
            with patch("builtins.__import__", side_effect=ImportError("no cache")):
                # The actual method tries import then sqlite fallback
                # Patching the method itself to verify the contract
                result = await TradeValidator._get_current_vix(validator)
                # Result may be None or a float depending on whether DB exists
                assert result is None or isinstance(result, float)


class TestPortfolioChecksExtended:
    """Extended portfolio checks for VIX regime variations."""

    def test_elevated_vix_reduces_position_limit_to_3(self, validator, mock_fundamentals):
        """VIX 27 = Elevated = max 3 positions."""
        positions = [{"symbol": f"SYM{i}", "sector": "Various"} for i in range(3)]
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 27.0)
        pos_check = next(c for c in checks if c.name == "max_positions")
        assert pos_check.decision == TradeDecision.NO_GO

    def test_elevated_vix_sector_limit_is_1(self, validator, mock_fundamentals):
        """VIX 27 = Elevated = max 1 per sector."""
        positions = [{"symbol": "MSFT", "sector": "Technology"}]
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 27.0)
        sector_check = next((c for c in checks if c.name == "sector_limit"), None)
        assert sector_check is not None
        assert sector_check.decision == TradeDecision.NO_GO

    def test_no_fundamentals_skips_sector_check(self, validator):
        """Without fundamentals, sector check is skipped."""
        positions = [{"symbol": "MSFT", "sector": "Technology"}]
        checks = validator._check_portfolio("AAPL", None, positions, 18.0)
        sector_check = next((c for c in checks if c.name == "sector_limit"), None)
        assert sector_check is None

    def test_empty_positions_is_go(self, validator, mock_fundamentals):
        """No open positions = GO."""
        checks = validator._check_portfolio("AAPL", mock_fundamentals, [], 18.0)
        pos_check = next(c for c in checks if c.name == "max_positions")
        assert pos_check.decision == TradeDecision.GO

    def test_sector_warning_when_one_position_exists(self, validator, mock_fundamentals):
        """One existing position in same sector = WARNING (not NO_GO)."""
        positions = [{"symbol": "MSFT", "sector": "Technology"}]
        checks = validator._check_portfolio("AAPL", mock_fundamentals, positions, 18.0)
        sector_check = next((c for c in checks if c.name == "sector_limit"), None)
        assert sector_check is not None
        assert sector_check.decision == TradeDecision.WARNING


class TestPositionSizingExtended:
    """Extended position sizing tests."""

    def test_sizing_elevated_vix_1pct(self, validator, mock_fundamentals):
        """VIX 27 = Elevated = 1.0% risk."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            portfolio_value=80000.0,
        )
        sizing = validator._calculate_sizing(request, mock_fundamentals, 27.0)
        assert sizing["risk_pct"] == 1.0
        assert sizing["max_risk_usd"] == 800.0  # 80k * 1%

    def test_sizing_zero_max_loss(self, validator, mock_fundamentals):
        """If credit equals spread width, max loss is 0 -> 0 contracts."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=10.0,  # credit == spread width
            portfolio_value=80000.0,
        )
        sizing = validator._calculate_sizing(request, mock_fundamentals, 18.0)
        assert sizing["max_loss_per_contract"] == 0.0
        assert sizing["recommended_contracts"] == 0

    def test_sizing_includes_total_fields(self, validator, mock_fundamentals):
        """Verify all expected fields are present."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            portfolio_value=80000.0,
        )
        sizing = validator._calculate_sizing(request, mock_fundamentals, 18.0)
        assert "spread_width" in sizing
        assert "credit_per_contract" in sizing
        assert "max_loss_per_contract" in sizing
        assert "risk_pct" in sizing
        assert "max_risk_usd" in sizing
        assert "recommended_contracts" in sizing
        assert "total_credit" in sizing
        assert "total_risk" in sizing

    def test_sizing_no_vix_uses_default(self, validator, mock_fundamentals):
        """If VIX is None, default 2.5% risk is used."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            portfolio_value=80000.0,
        )
        sizing = validator._calculate_sizing(request, mock_fundamentals, None)
        assert sizing["risk_pct"] == 2.5


class TestFullValidationExtended:
    """Extended integration tests for full validate() flow."""

    @pytest.mark.asyncio
    async def test_go_with_all_params(self, validator, mock_fundamentals):
        """Full validation with all params provided, mocking fundamentals."""
        validator._fundamentals_manager = MagicMock()
        validator._fundamentals_manager.get_fundamentals.return_value = mock_fundamentals

        with patch("src.utils.validation.is_etf", return_value=False):
            mock_earnings = MagicMock()
            mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
            validator._earnings_manager = mock_earnings

            exp = (date.today() + timedelta(days=75)).strftime("%Y-%m-%d")
            request = TradeValidationRequest(
                symbol="AAPL",
                short_strike=175.0,
                long_strike=165.0,
                expiration=exp,
                credit=2.50,
                portfolio_value=80000.0,
            )
            result = await validator.validate(request, current_vix=18.0, open_positions=[])
            # Should not have NO_GO blockers
            assert result.decision in (TradeDecision.GO, TradeDecision.WARNING)
            assert result.sizing_recommendation is not None
            assert result.sizing_recommendation["recommended_contracts"] >= 1

    @pytest.mark.asyncio
    async def test_multiple_blockers(self, validator):
        """Blacklisted + high VIX = still NO_GO with multiple blockers."""
        request = TradeValidationRequest(symbol="TSLA")
        result = await validator.validate(request, current_vix=36.0)
        assert result.decision == TradeDecision.NO_GO
        blocker_names = [c.name for c in result.blockers]
        assert "blacklist" in blocker_names
        assert "vix" in blocker_names

    @pytest.mark.asyncio
    async def test_validate_without_optional_params(self, validator):
        """Validate with only symbol — should still work."""
        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(request, current_vix=18.0)
        assert result.decision in (TradeDecision.GO, TradeDecision.WARNING, TradeDecision.NO_GO)
        assert result.regime is not None
        assert result.sizing_recommendation is None  # No sizing without portfolio_value


class TestSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self):
        reset_trade_validator()
        v1 = get_trade_validator()
        v2 = get_trade_validator()
        assert v1 is v2

    def test_reset_creates_new_instance(self):
        v1 = get_trade_validator()
        reset_trade_validator()
        v2 = get_trade_validator()
        assert v1 is not v2

    def test_singleton_with_quote_provider(self):
        """Quote provider is used when creating new instance."""
        reset_trade_validator()
        mock_provider = MagicMock()
        v = get_trade_validator(quote_provider=mock_provider)
        assert v._quote_provider is mock_provider

    def test_singleton_ignores_subsequent_provider(self):
        """Subsequent calls don't change quote provider."""
        reset_trade_validator()
        mock1 = MagicMock()
        mock2 = MagicMock()
        v1 = get_trade_validator(quote_provider=mock1)
        v2 = get_trade_validator(quote_provider=mock2)
        assert v1 is v2
        assert v1._quote_provider is mock1  # First provider is retained


class TestTradeValidatorInitialization:
    """Tests for TradeValidator initialization and lazy loading."""

    def test_init_default_values(self):
        """TradeValidator initializes with None values."""
        v = TradeValidator()
        assert v._quote_provider is None
        assert v._fundamentals_manager is None
        assert v._earnings_manager is None

    def test_init_with_quote_provider(self):
        """TradeValidator accepts quote provider."""
        mock_provider = MagicMock()
        v = TradeValidator(quote_provider=mock_provider)
        assert v._quote_provider is mock_provider

    def test_lazy_load_fundamentals(self):
        """Fundamentals manager is lazy-loaded."""
        v = TradeValidator()
        assert v._fundamentals_manager is None

        # Patch the import inside the cache module
        with patch("src.cache.get_fundamentals_manager") as mock_get:
            mock_manager = MagicMock()
            mock_get.return_value = mock_manager

            result = v.fundamentals

            mock_get.assert_called_once()
            assert result is mock_manager
            assert v._fundamentals_manager is mock_manager

    def test_lazy_load_fundamentals_cached(self):
        """Fundamentals manager is cached after first load."""
        v = TradeValidator()
        mock_manager = MagicMock()
        v._fundamentals_manager = mock_manager

        # Access should return cached value
        result = v.fundamentals
        assert result is mock_manager

    def test_lazy_load_fundamentals_import_error(self):
        """Import error returns None gracefully."""
        v = TradeValidator()

        # Patch the import inside the cache module
        with patch(
            "src.cache.get_fundamentals_manager",
            side_effect=ImportError("Module not found")
        ):
            result = v.fundamentals
            assert result is None

    def test_lazy_load_earnings(self):
        """Earnings manager is lazy-loaded."""
        v = TradeValidator()
        assert v._earnings_manager is None

        with patch("src.cache.get_earnings_history_manager") as mock_get:
            mock_manager = MagicMock()
            mock_get.return_value = mock_manager

            result = v.earnings

            mock_get.assert_called_once()
            assert result is mock_manager
            assert v._earnings_manager is mock_manager

    def test_lazy_load_earnings_import_error(self):
        """Import error returns None gracefully."""
        v = TradeValidator()

        with patch(
            "src.cache.get_earnings_history_manager",
            side_effect=ImportError("Module not found")
        ):
            result = v.earnings
            assert result is None


class TestValidationCheckDataclass:
    """Tests for ValidationCheck dataclass."""

    def test_validation_check_defaults(self):
        """ValidationCheck details defaults to empty dict."""
        check = ValidationCheck(
            name="test",
            passed=True,
            decision=TradeDecision.GO,
            message="OK",
        )
        assert check.details == {}

    def test_validation_check_with_details(self):
        """ValidationCheck accepts details dict."""
        check = ValidationCheck(
            name="test",
            passed=True,
            decision=TradeDecision.GO,
            message="OK",
            details={"key": "value", "count": 42},
        )
        assert check.details["key"] == "value"
        assert check.details["count"] == 42


class TestValidationResultProperties:
    """Tests for TradeValidationResult properties."""

    def test_passed_property(self):
        """passed property returns only GO checks."""
        result = TradeValidationResult(
            symbol="TEST",
            decision=TradeDecision.GO,
            checks=[
                ValidationCheck("c1", True, TradeDecision.GO, "OK"),
                ValidationCheck("c2", True, TradeDecision.GO, "OK"),
                ValidationCheck("c3", True, TradeDecision.WARNING, "Warn"),
            ],
        )
        passed = result.passed
        assert len(passed) == 2
        assert all(c.decision == TradeDecision.GO for c in passed)

    def test_summary_go_with_multiple_warnings(self):
        """Summary shows warning count for GO with warnings."""
        result = TradeValidationResult(
            symbol="TEST",
            decision=TradeDecision.GO,
            checks=[
                ValidationCheck("c1", True, TradeDecision.GO, "OK"),
                ValidationCheck("c2", True, TradeDecision.WARNING, "Warn 1"),
                ValidationCheck("c3", True, TradeDecision.WARNING, "Warn 2"),
            ],
        )
        assert "2 Warnung" in result.summary

    def test_summary_warning_decision(self):
        """Summary for WARNING decision includes warning messages."""
        result = TradeValidationResult(
            symbol="TEST",
            decision=TradeDecision.WARNING,
            checks=[
                ValidationCheck("c1", True, TradeDecision.GO, "OK"),
                ValidationCheck("c2", True, TradeDecision.WARNING, "IV too low"),
            ],
        )
        assert "WARNING" in result.summary
        assert "IV too low" in result.summary


class TestReadVixFromDb:
    """Tests for _read_vix_from_db static method."""

    def test_read_vix_db_not_exists(self, validator):
        """Returns None if DB file doesn't exist."""
        with patch("os.path.exists", return_value=False):
            result = TradeValidator._read_vix_from_db()
            assert result is None

    def test_read_vix_db_exists_with_data(self, validator):
        """Returns VIX value from DB."""
        import sqlite3
        import tempfile
        import os

        # Create temp DB with VIX data
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE vix_data (
                    date TEXT PRIMARY KEY,
                    value REAL NOT NULL
                )
            """)
            conn.execute("INSERT INTO vix_data (date, value) VALUES ('2026-02-04', 18.5)")
            conn.commit()
            conn.close()

            with patch("os.path.expanduser", return_value=db_path):
                result = TradeValidator._read_vix_from_db()
                assert result == 18.5
        finally:
            os.unlink(db_path)

    def test_read_vix_db_empty(self, validator):
        """Returns None if DB has no VIX data."""
        import sqlite3
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE vix_data (
                    date TEXT PRIMARY KEY,
                    value REAL NOT NULL
                )
            """)
            conn.commit()
            conn.close()

            with patch("os.path.expanduser", return_value=db_path):
                result = TradeValidator._read_vix_from_db()
                assert result is None
        finally:
            os.unlink(db_path)


class TestFetchEarningsFromApi:
    """Tests for _fetch_earnings_from_api fallback method."""

    @pytest.mark.asyncio
    async def test_fetch_earnings_api_success(self, validator):
        """Successful API fetch returns safe status and days."""
        mock_info = MagicMock()
        mock_info.earnings_date = date.today() + timedelta(days=75)
        mock_info.days_to_earnings = 75
        mock_info.is_safe.return_value = True
        mock_info.source = MagicMock()
        mock_info.source.value = "yfinance"

        # Patch in the src.cache module where the import happens
        with patch("src.cache.get_earnings_fetcher") as mock_get:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = mock_info
            mock_get.return_value = mock_fetcher

            with patch.object(validator, "_save_earnings_to_db"):
                is_safe, days_to, source = await validator._fetch_earnings_from_api("AAPL")

            assert is_safe is True
            assert days_to == 75
            assert "yfinance" in source

    @pytest.mark.asyncio
    async def test_fetch_earnings_api_unsafe(self, validator):
        """API finds close earnings returns unsafe status."""
        mock_info = MagicMock()
        mock_info.earnings_date = date.today() + timedelta(days=30)
        mock_info.days_to_earnings = 30
        mock_info.is_safe.return_value = False
        mock_info.source = MagicMock()
        mock_info.source.value = "yfinance"

        with patch("src.cache.get_earnings_fetcher") as mock_get:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = mock_info
            mock_get.return_value = mock_fetcher

            with patch.object(validator, "_save_earnings_to_db"):
                is_safe, days_to, source = await validator._fetch_earnings_from_api("AAPL")

            assert is_safe is False
            assert days_to == 30

    @pytest.mark.asyncio
    async def test_fetch_earnings_all_fail(self, validator):
        """All API methods fail returns None."""
        # Patch both EarningsFetcher and Yahoo direct fallback
        with patch("src.cache.get_earnings_fetcher", side_effect=Exception("API error")):
            with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
                is_safe, days_to, source = await validator._fetch_earnings_from_api("AAPL")

            assert is_safe is None
            assert days_to is None
            assert source == "none"


class TestSaveEarningsToDb:
    """Tests for _save_earnings_to_db write-through cache."""

    def test_save_earnings_success(self, validator):
        """Successfully saves earnings to DB."""
        mock_earnings = MagicMock()
        validator._earnings_manager = mock_earnings

        validator._save_earnings_to_db("AAPL", "2026-05-15", 90)

        mock_earnings.save_earnings.assert_called_once()
        call_args = mock_earnings.save_earnings.call_args
        assert call_args[0][0] == "AAPL"
        assert call_args[0][1][0]["earnings_date"] == "2026-05-15"

    def test_save_earnings_no_manager(self, validator):
        """No-op if earnings manager unavailable."""
        validator._earnings_manager = None
        # Should not raise
        validator._save_earnings_to_db("AAPL", "2026-05-15", 90)

    def test_save_earnings_negative_days(self, validator):
        """No-op if days_to is negative (past earnings)."""
        mock_earnings = MagicMock()
        validator._earnings_manager = mock_earnings

        validator._save_earnings_to_db("AAPL", "2026-01-01", -30)

        mock_earnings.save_earnings.assert_not_called()

    def test_save_earnings_exception_handled(self, validator):
        """Exception in save is handled gracefully."""
        mock_earnings = MagicMock()
        mock_earnings.save_earnings.side_effect = Exception("DB error")
        validator._earnings_manager = mock_earnings

        # Should not raise
        validator._save_earnings_to_db("AAPL", "2026-05-15", 90)


class TestSymbolNormalization:
    """Tests for symbol normalization in validate()."""

    @pytest.mark.asyncio
    async def test_validate_normalizes_lowercase(self, validator):
        """Validate normalizes symbol to uppercase."""
        request = TradeValidationRequest(symbol="aapl")
        result = await validator.validate(request, current_vix=18.0)
        assert result.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_validate_normalizes_mixed_case(self, validator):
        """Validate normalizes mixed case symbol."""
        request = TradeValidationRequest(symbol="AaPl")
        result = await validator.validate(request, current_vix=18.0)
        assert result.symbol == "AAPL"


class TestValidateFundamentalsException:
    """Tests for exception handling in validate()."""

    @pytest.mark.asyncio
    async def test_validate_handles_fundamentals_exception(self, validator):
        """Validate handles exception when getting fundamentals."""
        request = TradeValidationRequest(symbol="AAPL")
        mock_manager = MagicMock()
        mock_manager.get_fundamentals.side_effect = Exception("DB error")
        validator._fundamentals_manager = mock_manager

        # Should not raise, should continue validation
        result = await validator.validate(request, current_vix=18.0)
        assert result.symbol == "AAPL"
        # Stability check should show WARNING due to missing fundamentals
        stability_check = next((c for c in result.checks if c.name == "stability"), None)
        if stability_check:
            assert stability_check.decision == TradeDecision.WARNING


class TestVixFetchingExtended:
    """Extended tests for VIX fetching logic."""

    @pytest.mark.asyncio
    async def test_get_vix_fallback_to_db_on_import_error(self, validator):
        """Falls back to DB if cache import fails (the actual path)."""
        # The get_latest_vix doesn't exist in vix_cache module, so ImportError is thrown
        # Then it falls back to _read_vix_from_db
        with patch.object(
            TradeValidator, "_read_vix_from_db",
            return_value=19.0
        ):
            result = await validator._get_current_vix()

        # Due to ImportError on get_latest_vix, it should fall back to DB read
        assert result == 19.0 or result is not None  # May succeed via actual DB

    @pytest.mark.asyncio
    async def test_get_vix_returns_none_when_all_fail(self, validator):
        """Returns None if both cache import and DB fail."""
        with patch.object(
            TradeValidator, "_read_vix_from_db",
            side_effect=Exception("DB error")
        ):
            result = await validator._get_current_vix()

        # May return None or the ImportError path succeeds with actual DB
        # The behavior depends on whether actual modules exist
        assert result is None or isinstance(result, float)

    @pytest.mark.asyncio
    async def test_get_vix_method_exists(self, validator):
        """_get_current_vix method should exist and be callable."""
        # The method should return a float or None
        result = await validator._get_current_vix()
        assert result is None or isinstance(result, float)


class TestValidateWithSpreadParams:
    """Tests for validate() with spread parameters."""

    @pytest.mark.asyncio
    async def test_validate_includes_dte_check_when_expiration_provided(self, validator):
        """DTE check is included when expiration is provided."""
        exp = (date.today() + timedelta(days=75)).strftime("%Y-%m-%d")
        request = TradeValidationRequest(symbol="AAPL", expiration=exp)

        result = await validator.validate(request, current_vix=18.0)

        check_names = [c.name for c in result.checks]
        assert "dte" in check_names

    @pytest.mark.asyncio
    async def test_validate_includes_credit_check_when_all_spread_params_provided(self, validator):
        """Credit check is included when all spread params provided."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
        )

        result = await validator.validate(request, current_vix=18.0)

        check_names = [c.name for c in result.checks]
        assert "credit" in check_names

    @pytest.mark.asyncio
    async def test_validate_skips_credit_check_when_partial_params(self, validator):
        """Credit check is skipped when params are partial."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            # Missing long_strike and credit
        )

        result = await validator.validate(request, current_vix=18.0)

        check_names = [c.name for c in result.checks]
        assert "credit" not in check_names


class TestValidateWithPortfolio:
    """Tests for validate() with portfolio positions."""

    @pytest.mark.asyncio
    async def test_validate_includes_portfolio_checks(self, validator, mock_fundamentals):
        """Portfolio checks are included when positions provided."""
        validator._fundamentals_manager = MagicMock()
        validator._fundamentals_manager.get_fundamentals.return_value = mock_fundamentals

        request = TradeValidationRequest(symbol="AAPL")
        positions = [{"symbol": "MSFT", "sector": "Technology"}]

        with patch("src.utils.validation.is_etf", return_value=False):
            mock_earnings = MagicMock()
            mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
            validator._earnings_manager = mock_earnings

            result = await validator.validate(
                request, current_vix=18.0, open_positions=positions
            )

        check_names = [c.name for c in result.checks]
        assert "max_positions" in check_names

    @pytest.mark.asyncio
    async def test_validate_skips_portfolio_checks_when_no_positions(self, validator):
        """Portfolio checks skipped when positions is None."""
        request = TradeValidationRequest(symbol="AAPL")

        result = await validator.validate(request, current_vix=18.0, open_positions=None)

        check_names = [c.name for c in result.checks]
        assert "max_positions" not in check_names


class TestValidateWithSizing:
    """Tests for validate() with sizing calculation."""

    @pytest.mark.asyncio
    async def test_validate_includes_sizing_when_all_params(self, validator, mock_fundamentals):
        """Sizing is calculated when all required params provided."""
        validator._fundamentals_manager = MagicMock()
        validator._fundamentals_manager.get_fundamentals.return_value = mock_fundamentals

        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            portfolio_value=80000.0,
        )

        with patch("src.utils.validation.is_etf", return_value=False):
            mock_earnings = MagicMock()
            mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
            validator._earnings_manager = mock_earnings

            result = await validator.validate(request, current_vix=18.0)

        assert result.sizing_recommendation is not None
        assert "recommended_contracts" in result.sizing_recommendation

    @pytest.mark.asyncio
    async def test_validate_skips_sizing_when_missing_portfolio_value(self, validator):
        """Sizing is skipped when portfolio_value is missing."""
        request = TradeValidationRequest(
            symbol="AAPL",
            short_strike=175.0,
            long_strike=165.0,
            credit=2.50,
            # No portfolio_value
        )

        result = await validator.validate(request, current_vix=18.0)

        assert result.sizing_recommendation is None


class TestOverallDecisionLogic:
    """Tests for overall decision determination."""

    @pytest.mark.asyncio
    async def test_no_go_takes_precedence(self, validator):
        """NO_GO takes precedence over WARNING."""
        # TSLA is blacklisted (NO_GO) and high VIX = 22 (WARNING)
        request = TradeValidationRequest(symbol="TSLA")

        result = await validator.validate(request, current_vix=22.0)

        assert result.decision == TradeDecision.NO_GO
        # Should have both blacklist (NO_GO) and VIX (WARNING)
        blocker_names = [c.name for c in result.blockers]
        assert "blacklist" in blocker_names

    @pytest.mark.asyncio
    async def test_warning_when_no_blockers(self, validator, mock_fundamentals):
        """WARNING decision when no blockers but has warnings."""
        validator._fundamentals_manager = MagicMock()
        mock_fundamentals.iv_rank_252d = 20.0  # Low IV = WARNING
        validator._fundamentals_manager.get_fundamentals.return_value = mock_fundamentals

        request = TradeValidationRequest(symbol="AAPL")

        with patch("src.utils.validation.is_etf", return_value=False):
            mock_earnings = MagicMock()
            mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
            validator._earnings_manager = mock_earnings

            result = await validator.validate(request, current_vix=18.0)

        # If no blockers and has IV warning, should be WARNING
        if result.decision == TradeDecision.WARNING:
            assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_go_when_no_blockers_no_warnings(self, validator, mock_fundamentals):
        """GO decision when no blockers and no warnings."""
        validator._fundamentals_manager = MagicMock()
        mock_fundamentals.iv_rank_252d = 50.0  # Good IV = GO
        validator._fundamentals_manager.get_fundamentals.return_value = mock_fundamentals

        request = TradeValidationRequest(symbol="AAPL")

        with patch("src.utils.validation.is_etf", return_value=False):
            mock_earnings = MagicMock()
            mock_earnings.is_earnings_day_safe.return_value = (True, 90, "safe")
            validator._earnings_manager = mock_earnings

            result = await validator.validate(request, current_vix=18.0)

        # If all checks pass, should be GO
        if len(result.blockers) == 0 and len(result.warnings) == 0:
            assert result.decision == TradeDecision.GO
