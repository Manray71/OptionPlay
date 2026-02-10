# Tests for Market Data Models
# =============================
"""
Tests for src/models/market_data.py including:
- EarningsSource enum
- IVSource enum
- EarningsInfo dataclass
- IVData dataclass
- HistoricalBar dataclass
"""

import pytest
from datetime import datetime

from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
from src.models.market_data import (
    EarningsSource,
    IVSource,
    EarningsInfo,
    IVData,
    HistoricalBar,
)


# =============================================================================
# ENUM TESTS
# =============================================================================

class TestEarningsSource:
    """Tests for EarningsSource enum."""

    def test_all_values(self):
        """Test: All expected values exist."""
        assert EarningsSource.YFINANCE.value == "yfinance"
        assert EarningsSource.YAHOO_SCRAPE.value == "yahoo_scrape"
        assert EarningsSource.TRADIER.value == "tradier"
        assert EarningsSource.MANUAL.value == "manual"
        assert EarningsSource.UNKNOWN.value == "unknown"


class TestIVSource:
    """Tests for IVSource enum."""

    def test_all_values(self):
        """Test: All expected values exist."""
        assert IVSource.TRADIER.value == "tradier"
        assert IVSource.CBOE.value == "cboe"
        assert IVSource.CALCULATED.value == "calculated"
        assert IVSource.UNKNOWN.value == "unknown"


# =============================================================================
# EARNINGS INFO TESTS
# =============================================================================

class TestEarningsInfo:
    """Tests for EarningsInfo dataclass."""

    def test_create_earnings_info(self):
        """Test: Creating EarningsInfo."""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date="2026-02-15",
            days_to_earnings=30,
            source=EarningsSource.YFINANCE,
            updated_at="2026-01-16T10:00:00",
            confirmed=True
        )

        assert info.symbol == "AAPL"
        assert info.earnings_date == "2026-02-15"
        assert info.days_to_earnings == 30
        assert info.source == EarningsSource.YFINANCE
        assert info.confirmed is True

    def test_is_safe_with_enough_days(self):
        """Test: is_safe returns True when enough days."""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date="2026-04-15",
            days_to_earnings=70,
            source=EarningsSource.YFINANCE,
            updated_at="2026-01-16T10:00:00"
        )

        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) is True

    def test_is_safe_with_few_days(self):
        """Test: is_safe returns False when too close."""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date="2026-01-25",
            days_to_earnings=10,
            source=EarningsSource.YFINANCE,
            updated_at="2026-01-16T10:00:00"
        )

        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) is False

    def test_is_safe_with_none_days(self):
        """Test: is_safe returns True when days_to_earnings is None."""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date=None,
            days_to_earnings=None,
            source=EarningsSource.UNKNOWN,
            updated_at="2026-01-16T10:00:00"
        )

        # Unknown = accept (with warning)
        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) is True

    def test_to_dict(self):
        """Test: to_dict serialization."""
        info = EarningsInfo(
            symbol="MSFT",
            earnings_date="2026-02-20",
            days_to_earnings=45,
            source=EarningsSource.TRADIER,
            updated_at="2026-01-06T12:00:00",
            confirmed=False
        )

        d = info.to_dict()

        assert d["symbol"] == "MSFT"
        assert d["earnings_date"] == "2026-02-20"
        assert d["days_to_earnings"] == 45
        assert d["source"] == "tradier"
        assert d["confirmed"] is False
        assert d["is_safe_60d"] is False  # 45 < 60


# =============================================================================
# IV DATA TESTS
# =============================================================================

class TestIVData:
    """Tests for IVData dataclass."""

    def test_create_iv_data(self):
        """Test: Creating IVData."""
        iv = IVData(
            symbol="AAPL",
            current_iv=0.25,
            iv_rank=55.0,
            iv_percentile=60.0,
            hv_20=0.20,
            hv_50=0.22,
            iv_hv_ratio=1.25,
            source=IVSource.TRADIER,
            updated_at="2026-01-16T10:00:00"
        )

        assert iv.symbol == "AAPL"
        assert iv.current_iv == 0.25
        assert iv.iv_rank == 55.0

    def test_is_elevated_true(self):
        """Test: is_elevated returns True when IV rank high."""
        iv = IVData(
            symbol="AAPL",
            current_iv=0.35,
            iv_rank=65.0,
            iv_percentile=70.0
        )

        assert iv.is_elevated(threshold=50.0) is True

    def test_is_elevated_false(self):
        """Test: is_elevated returns False when IV rank low."""
        iv = IVData(
            symbol="AAPL",
            current_iv=0.20,
            iv_rank=30.0,
            iv_percentile=35.0
        )

        assert iv.is_elevated(threshold=50.0) is False

    def test_iv_regime_very_high(self):
        """Test: iv_regime returns 'very_high' for rank >= 80."""
        iv = IVData(symbol="AAPL", current_iv=0.5, iv_rank=85.0, iv_percentile=90.0)
        assert iv.iv_regime() == "very_high"

    def test_iv_regime_elevated(self):
        """Test: iv_regime returns 'elevated' for rank 50-79."""
        iv = IVData(symbol="AAPL", current_iv=0.35, iv_rank=60.0, iv_percentile=65.0)
        assert iv.iv_regime() == "elevated"

    def test_iv_regime_normal(self):
        """Test: iv_regime returns 'normal' for rank 20-49."""
        iv = IVData(symbol="AAPL", current_iv=0.25, iv_rank=35.0, iv_percentile=40.0)
        assert iv.iv_regime() == "normal"

    def test_iv_regime_low(self):
        """Test: iv_regime returns 'low' for rank < 20."""
        iv = IVData(symbol="AAPL", current_iv=0.15, iv_rank=10.0, iv_percentile=12.0)
        assert iv.iv_regime() == "low"

    def test_to_dict(self):
        """Test: to_dict serialization."""
        iv = IVData(
            symbol="MSFT",
            current_iv=0.28,
            iv_rank=55.0,
            iv_percentile=58.0,
            hv_20=0.22,
            hv_50=0.24,
            iv_hv_ratio=1.27,
            source=IVSource.CALCULATED,
            updated_at="2026-01-06T12:00:00"
        )

        d = iv.to_dict()

        assert d["symbol"] == "MSFT"
        assert d["current_iv"] == 28.0  # As percent
        assert d["iv_rank"] == 55.0
        assert d["hv_20"] == 22.0  # As percent
        assert d["regime"] == "elevated"
        assert d["is_elevated"] is True
        assert d["source"] == "calculated"

    def test_to_dict_with_none_values(self):
        """Test: to_dict handles None HV values."""
        iv = IVData(
            symbol="XYZ",
            current_iv=0.30,
            iv_rank=45.0,
            iv_percentile=48.0,
            hv_20=None,
            hv_50=None,
            iv_hv_ratio=None
        )

        d = iv.to_dict()

        assert d["hv_20"] is None
        assert d["hv_50"] is None
        assert d["iv_hv_ratio"] is None


# =============================================================================
# HISTORICAL BAR TESTS
# =============================================================================

class TestHistoricalBar:
    """Tests for HistoricalBar dataclass."""

    def test_create_historical_bar(self):
        """Test: Creating HistoricalBar."""
        bar = HistoricalBar(
            timestamp=datetime(2026, 1, 15, 16, 0, 0),
            open=150.0,
            high=152.0,
            low=149.0,
            close=151.5,
            volume=1000000
        )

        assert bar.open == 150.0
        assert bar.high == 152.0
        assert bar.low == 149.0
        assert bar.close == 151.5
        assert bar.volume == 1000000

    def test_to_dict(self):
        """Test: to_dict serialization."""
        bar = HistoricalBar(
            timestamp=datetime(2026, 1, 15, 16, 0, 0),
            open=150.0,
            high=152.0,
            low=149.0,
            close=151.5,
            volume=1000000
        )

        d = bar.to_dict()

        assert d["open"] == 150.0
        assert d["high"] == 152.0
        assert d["low"] == 149.0
        assert d["close"] == 151.5
        assert d["volume"] == 1000000
        assert "2026-01-15" in d["timestamp"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
