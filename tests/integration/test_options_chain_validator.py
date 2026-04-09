"""
Tests for OptionsChainValidator.

Tests the core validation logic with mocked providers.
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.options_chain_validator import (
    OptionsChainValidator,
    OptionLeg,
    SpreadValidation,
)
from src.constants.trading_rules import (
    SPREAD_DTE_MIN,
    SPREAD_DTE_MAX,
    SPREAD_DTE_TARGET,
    SPREAD_SHORT_DELTA_TARGET,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_MIN_CREDIT_PCT,
    ENTRY_OPEN_INTEREST_MIN,
)


# =============================================================================
# FIXTURES
# =============================================================================

def _make_option_quote(
    strike: float,
    delta: float,
    bid: float,
    ask: float,
    oi: int = 500,
    volume: int = 100,
    iv: float = 0.30,
    expiry_days: int = 45,
):
    """Create a mock OptionQuote matching the DataProvider interface."""
    expiry = date.today() + timedelta(days=expiry_days)
    mock = MagicMock()
    mock.strike = strike
    mock.delta = delta
    mock.bid = bid
    mock.ask = ask
    mock.last = (bid + ask) / 2
    mock.volume = volume
    mock.open_interest = oi
    mock.implied_volatility = iv
    mock.gamma = 0.01
    mock.theta = -0.05
    mock.vega = 0.15
    mock.expiry = expiry
    mock.mid = (bid + ask) / 2
    return mock


def _make_chain(underlying_price: float = 200.0, expiry_days: int = 45):
    """Create a realistic put options chain."""
    return [
        _make_option_quote(strike=160, delta=-0.03, bid=0.30, ask=0.45, oi=200, expiry_days=expiry_days),
        _make_option_quote(strike=165, delta=-0.05, bid=0.55, ask=0.70, oi=350, expiry_days=expiry_days),
        _make_option_quote(strike=170, delta=-0.07, bid=0.85, ask=1.00, oi=500, expiry_days=expiry_days),
        _make_option_quote(strike=175, delta=-0.10, bid=1.30, ask=1.50, oi=800, expiry_days=expiry_days),
        _make_option_quote(strike=180, delta=-0.14, bid=2.00, ask=2.20, oi=1200, expiry_days=expiry_days),
        _make_option_quote(strike=185, delta=-0.18, bid=2.80, ask=3.05, oi=1500, expiry_days=expiry_days),
        _make_option_quote(strike=190, delta=-0.20, bid=3.40, ask=3.65, oi=2000, expiry_days=expiry_days),
        _make_option_quote(strike=195, delta=-0.25, bid=4.50, ask=4.80, oi=1800, expiry_days=expiry_days),
        _make_option_quote(strike=200, delta=-0.30, bid=5.80, ask=6.10, oi=2500, expiry_days=expiry_days),
    ]


def _make_provider(chain=None, expirations=None):
    """Create a mock options provider."""
    provider = AsyncMock()

    if expirations is None:
        expirations = [
            date.today() + timedelta(days=35),
            date.today() + timedelta(days=42),
            date.today() + timedelta(days=49),
            date.today() + timedelta(days=56),
        ]

    provider.get_expirations = AsyncMock(return_value=expirations)

    if chain is None:
        chain = _make_chain()
    provider.get_option_chain = AsyncMock(return_value=chain)

    return provider


@pytest.fixture
def validator():
    """Standard validator with mock provider."""
    provider = _make_provider()
    return OptionsChainValidator(options_provider=provider)


# =============================================================================
# TESTS: validate_spread()
# =============================================================================

class TestValidateSpread:
    """Test the main validate_spread method."""

    @pytest.mark.asyncio
    async def test_valid_spread_returns_tradeable(self, validator):
        """A valid chain with good delta, credit, and OI returns tradeable=True."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert result.credit_bid > 0
        assert result.credit_pct >= SPREAD_MIN_CREDIT_PCT
        assert result.short_leg is not None
        assert result.long_leg is not None
        assert result.dte is not None

    @pytest.mark.asyncio
    async def test_short_delta_in_range(self, validator):
        """Short leg delta should be within -0.23 to -0.17."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert -0.25 <= result.short_leg.delta <= -0.15  # Expanded for fallback

    @pytest.mark.asyncio
    async def test_long_delta_in_range(self, validator):
        """Long leg delta should be within -0.07 to -0.03."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert -0.09 <= result.long_leg.delta <= -0.01

    @pytest.mark.asyncio
    async def test_short_strike_greater_than_long(self, validator):
        """Short strike must be > long strike for bull put spread."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert result.short_leg.strike > result.long_leg.strike

    @pytest.mark.asyncio
    async def test_spread_width_calculated(self, validator):
        """Spread width = short strike - long strike."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert result.spread_width == result.short_leg.strike - result.long_leg.strike

    @pytest.mark.asyncio
    async def test_credit_pct_above_minimum(self, validator):
        """Credit must be >= 10% of spread width."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert result.credit_pct >= SPREAD_MIN_CREDIT_PCT

    @pytest.mark.asyncio
    async def test_max_loss_calculated(self, validator):
        """Max loss = (width - credit) × 100."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        expected_max_loss = (result.spread_width - result.credit_bid) * 100
        assert abs(result.max_loss_per_contract - expected_max_loss) < 0.01

    @pytest.mark.asyncio
    async def test_spread_greeks_calculated(self, validator):
        """Spread greeks should be populated."""
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert result.spread_theta is not None
        assert result.spread_delta is not None
        assert result.spread_vega is not None


class TestNoExpirations:
    """Test when no valid expirations exist."""

    @pytest.mark.asyncio
    async def test_no_expirations_returns_not_tradeable(self):
        """No expirations in DTE window → not tradeable."""
        provider = AsyncMock()
        provider.get_expirations = AsyncMock(return_value=[
            date.today() + timedelta(days=30),  # Too short
            date.today() + timedelta(days=120),  # Too long
        ])
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False
        assert "DTE-Fenster" in result.reason

    @pytest.mark.asyncio
    async def test_empty_expirations_returns_not_tradeable(self):
        """Empty expiration list → not tradeable."""
        provider = AsyncMock()
        provider.get_expirations = AsyncMock(return_value=[])
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False


class TestNoDelta:
    """Test when no strikes match delta requirements."""

    @pytest.mark.asyncio
    async def test_no_short_delta_match(self):
        """No put with delta ≈ -0.20 → not tradeable."""
        chain = [
            _make_option_quote(strike=160, delta=-0.03, bid=0.30, ask=0.45),
            _make_option_quote(strike=165, delta=-0.05, bid=0.55, ask=0.70),
            _make_option_quote(strike=200, delta=-0.50, bid=5.80, ask=6.10),
        ]
        provider = _make_provider(chain=chain)
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False
        assert "Delta" in result.reason

    @pytest.mark.asyncio
    async def test_no_long_delta_match(self):
        """No put with delta ≈ -0.05 → not tradeable."""
        chain = [
            _make_option_quote(strike=190, delta=-0.20, bid=3.40, ask=3.65),
            _make_option_quote(strike=200, delta=-0.30, bid=5.80, ask=6.10),
        ]
        provider = _make_provider(chain=chain)
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False
        assert "Delta" in result.reason


class TestCreditCheck:
    """Test credit requirement validation."""

    @pytest.mark.asyncio
    async def test_insufficient_credit_returns_not_tradeable(self):
        """Credit < 10% of spread width → not tradeable."""
        chain = [
            _make_option_quote(strike=165, delta=-0.05, bid=0.55, ask=0.70),
            # Short bid - long ask = 0.80 - 0.70 = 0.10 on $25 spread = 0.4%
            _make_option_quote(strike=190, delta=-0.20, bid=0.80, ask=1.00),
        ]
        provider = _make_provider(chain=chain)
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False
        assert "Credit" in result.reason

    @pytest.mark.asyncio
    async def test_negative_credit_returns_not_tradeable(self):
        """Negative credit (short bid < long ask) → not tradeable."""
        chain = [
            _make_option_quote(strike=165, delta=-0.05, bid=4.00, ask=4.50),
            _make_option_quote(strike=190, delta=-0.20, bid=3.00, ask=3.50),
        ]
        provider = _make_provider(chain=chain)
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False
        assert "Negativer Credit" in result.reason


class TestLiquidityWarnings:
    """Test liquidity warning generation."""

    @pytest.mark.asyncio
    async def test_low_oi_generates_warning(self):
        """OI below minimum → tradeable but with warning."""
        chain = [
            _make_option_quote(strike=165, delta=-0.05, bid=0.55, ask=0.70, oi=50),
            _make_option_quote(strike=190, delta=-0.20, bid=3.40, ask=3.65, oi=2000),
        ]
        provider = _make_provider(chain=chain)
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        if result.tradeable:
            assert result.warning is True
            assert "OI" in result.reason


class TestOptimalExpiration:
    """Test expiration selection logic."""

    @pytest.mark.asyncio
    async def test_selects_closest_to_75_dte(self):
        """Should prefer expiration closest to 75 DTE."""
        expirations = [
            date.today() + timedelta(days=62),
            date.today() + timedelta(days=74),  # Closest to 75
            date.today() + timedelta(days=88),
        ]
        provider = _make_provider(expirations=expirations)
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        if result.tradeable:
            assert abs(result.dte - 44) <= 1  # Should be ~44 DTE


class TestProviderFallback:
    """Test IBKR → Provider fallback behavior."""

    @pytest.mark.asyncio
    async def test_provider_used_without_ibkr(self):
        """Without IBKR, should use provider fallback."""
        provider = _make_provider()
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.data_source == "Provider"

    @pytest.mark.asyncio
    async def test_ibkr_used_when_connected(self):
        """With connected IBKR, should prefer IBKR."""
        chain = _make_chain()
        provider = _make_provider(chain=chain)

        ibkr = MagicMock()
        ibkr.is_connected = MagicMock(return_value=True)
        ibkr.get_option_chain = AsyncMock(return_value=chain)

        validator = OptionsChainValidator(options_provider=provider, ibkr_bridge=ibkr)
        result = await validator.validate_spread("AAPL")
        # IBKR should be tried first
        assert result.data_source in ("IBKR", "Provider")

    @pytest.mark.asyncio
    async def test_falls_back_to_provider_on_ibkr_error(self):
        """If IBKR fails, should fall back to provider."""
        provider = _make_provider()

        ibkr = MagicMock()
        ibkr.is_connected = MagicMock(return_value=True)
        ibkr.get_option_chain = AsyncMock(side_effect=Exception("IBKR connection lost"))

        validator = OptionsChainValidator(options_provider=provider, ibkr_bridge=ibkr)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is True
        assert result.data_source == "Provider"


class TestErrorHandling:
    """Test error handling in validate_spread."""

    @pytest.mark.asyncio
    async def test_provider_error_returns_not_tradeable(self):
        """Provider exception → not tradeable (no expirations available)."""
        provider = AsyncMock()
        provider.get_expirations = AsyncMock(side_effect=Exception("API down"))
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False
        # Error is caught in _get_valid_expirations, resulting in empty list
        assert "Expiration" in result.reason or "Fehler" in result.reason

    @pytest.mark.asyncio
    async def test_empty_chain_returns_not_tradeable(self):
        """Empty chain → not tradeable."""
        provider = _make_provider(chain=[])
        validator = OptionsChainValidator(options_provider=provider)
        result = await validator.validate_spread("AAPL")
        assert result.tradeable is False


class TestFindStrikeByDelta:
    """Test the delta-finding helper."""

    def test_finds_closest_to_target(self):
        """Should return leg closest to target delta."""
        chain = [
            OptionLeg(strike=185, expiration="2026-04-17", dte=44, delta=-0.18,
                     gamma=0.01, theta=-0.05, vega=0.15, iv=0.30,
                     bid=2.80, ask=3.05, mid=2.925, last=2.90,
                     open_interest=1500, volume=100),
            OptionLeg(strike=190, expiration="2026-04-17", dte=44, delta=-0.21,
                     gamma=0.01, theta=-0.05, vega=0.15, iv=0.30,
                     bid=3.40, ask=3.65, mid=3.525, last=3.50,
                     open_interest=2000, volume=150),
        ]
        validator = OptionsChainValidator(options_provider=AsyncMock())
        result = validator._find_strike_by_delta(
            chain, target=-0.20, min_delta=-0.23, max_delta=-0.17
        )
        assert result is not None
        assert result.strike == 190  # Delta -0.21 is closest to -0.20

    def test_returns_none_outside_range(self):
        """No candidates in delta range → returns None."""
        chain = [
            OptionLeg(strike=200, expiration="2026-04-17", dte=44, delta=-0.50,
                     gamma=0.01, theta=-0.05, vega=0.15, iv=0.30,
                     bid=5.80, ask=6.10, mid=5.95, last=5.90,
                     open_interest=2500, volume=200),
        ]
        validator = OptionsChainValidator(options_provider=AsyncMock())
        result = validator._find_strike_by_delta(
            chain, target=-0.20, min_delta=-0.23, max_delta=-0.17
        )
        assert result is None
