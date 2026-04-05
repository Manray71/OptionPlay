"""
Extended tests for the IV Cache Implementation module.

Tests cover:
- IVSource enum
- IVData dataclass
- IVCacheEntry dataclass
- IV calculation functions (calculate_iv_rank, calculate_iv_percentile)
- IVCache class
- IVFetcher class
- HistoricalIVFetcher class
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cache.iv_cache_impl import (
    IVSource,
    IVData,
    IVCacheEntry,
    IVCache,
    IVFetcher,
    HistoricalIVFetcher,
    calculate_iv_rank,
    calculate_iv_percentile,
    get_iv_cache,
    get_iv_fetcher,
    get_iv_rank,
    is_iv_elevated,
    reset_iv_cache,
    DEFAULT_CACHE_MAX_AGE_DAYS,
    IV_HISTORY_DAYS,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_iv_history():
    """Create sample IV history data with at least 20 points."""
    import numpy as np
    np.random.seed(42)
    # Generate 252 trading days of IV data
    base_iv = 0.25
    iv_history = []
    for _ in range(252):
        iv = base_iv + np.random.uniform(-0.10, 0.15)
        iv = max(0.10, min(0.60, iv))
        iv_history.append(iv)
    return iv_history


@pytest.fixture
def small_iv_history():
    """Create sample IV history with 30 data points (minimum for rank calc)."""
    return [0.20 + i * 0.01 for i in range(30)]  # 0.20 to 0.49


@pytest.fixture
def sample_iv_data():
    """Create sample IVData."""
    return IVData(
        symbol="AAPL",
        current_iv=0.25,
        iv_rank=45.0,
        iv_percentile=42.0,
        iv_high_52w=0.40,
        iv_low_52w=0.15,
        data_points=252,
        source=IVSource.IBKR,
        updated_at=datetime.now().isoformat(),
    )


@pytest.fixture
def sample_cache_entry():
    """Create sample IVCacheEntry."""
    return IVCacheEntry(
        iv_history=[0.20, 0.22, 0.25, 0.30, 0.28, 0.25],
        iv_high=0.30,
        iv_low=0.20,
        data_points=6,
        source="ibkr",
        updated=datetime.now().isoformat(),
    )


@pytest.fixture
def temp_cache_dir():
    """Create a temporary directory for cache files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# IV SOURCE ENUM TESTS
# =============================================================================


class TestIVSource:
    """Tests for IVSource enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert IVSource.IBKR.value == "ibkr"
        assert IVSource.YAHOO.value == "yahoo"
        assert IVSource.IBKR.value == "ibkr"
        assert IVSource.IBKR.value == "ibkr"
        assert IVSource.MANUAL.value == "manual"
        assert IVSource.UNKNOWN.value == "unknown"


# =============================================================================
# IV DATA TESTS
# =============================================================================


class TestIVData:
    """Tests for IVData dataclass."""

    def test_creation(self, sample_iv_data):
        """Test IVData creation."""
        data = sample_iv_data
        assert data.symbol == "AAPL"
        assert data.current_iv == 0.25
        assert data.iv_rank == 45.0
        assert data.iv_percentile == 42.0

    def test_is_elevated_true(self):
        """Test is_elevated returns True for elevated IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.35,
            iv_rank=60.0,
            iv_percentile=55.0,
            iv_high_52w=0.40,
            iv_low_52w=0.20,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.is_elevated(threshold=50.0) is True

    def test_is_elevated_false(self):
        """Test is_elevated returns False for normal IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.20,
            iv_rank=30.0,
            iv_percentile=25.0,
            iv_high_52w=0.40,
            iv_low_52w=0.15,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.is_elevated(threshold=50.0) is False

    def test_is_elevated_with_none_iv_rank(self):
        """Test is_elevated returns False when iv_rank is None."""
        data = IVData(
            symbol="TEST",
            current_iv=0.25,
            iv_rank=None,
            iv_percentile=None,
            iv_high_52w=None,
            iv_low_52w=None,
            data_points=0,
            source=IVSource.UNKNOWN,
            updated_at="2026-01-15",
        )
        assert data.is_elevated() is False

    def test_is_low_true(self):
        """Test is_low returns True for low IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.15,
            iv_rank=20.0,
            iv_percentile=18.0,
            iv_high_52w=0.40,
            iv_low_52w=0.12,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.is_low(threshold=30.0) is True

    def test_is_low_false(self):
        """Test is_low returns False for normal IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.25,
            iv_rank=45.0,
            iv_percentile=42.0,
            iv_high_52w=0.40,
            iv_low_52w=0.15,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.is_low(threshold=30.0) is False

    def test_iv_status_very_high(self):
        """Test iv_status returns 'very_high' for high IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.45,
            iv_rank=75.0,
            iv_percentile=70.0,
            iv_high_52w=0.50,
            iv_low_52w=0.15,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.iv_status() == "very_high"

    def test_iv_status_elevated(self):
        """Test iv_status returns 'elevated' for elevated IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.30,
            iv_rank=55.0,
            iv_percentile=50.0,
            iv_high_52w=0.40,
            iv_low_52w=0.15,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.iv_status() == "elevated"

    def test_iv_status_normal(self):
        """Test iv_status returns 'normal' for normal IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.25,
            iv_rank=40.0,
            iv_percentile=35.0,
            iv_high_52w=0.40,
            iv_low_52w=0.15,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.iv_status() == "normal"

    def test_iv_status_low(self):
        """Test iv_status returns 'low' for low IV."""
        data = IVData(
            symbol="TEST",
            current_iv=0.15,
            iv_rank=20.0,
            iv_percentile=15.0,
            iv_high_52w=0.40,
            iv_low_52w=0.12,
            data_points=100,
            source=IVSource.IBKR,
            updated_at="2026-01-15",
        )
        assert data.iv_status() == "low"

    def test_iv_status_unknown(self):
        """Test iv_status returns 'unknown' when iv_rank is None."""
        data = IVData(
            symbol="TEST",
            current_iv=0.25,
            iv_rank=None,
            iv_percentile=None,
            iv_high_52w=None,
            iv_low_52w=None,
            data_points=0,
            source=IVSource.UNKNOWN,
            updated_at="2026-01-15",
        )
        assert data.iv_status() == "unknown"

    def test_to_dict(self, sample_iv_data):
        """Test to_dict serialization."""
        d = sample_iv_data.to_dict()

        assert d["symbol"] == "AAPL"
        assert d["current_iv"] == 25.0  # Percent
        assert d["current_iv_decimal"] == 0.25
        assert d["iv_rank"] == 45.0
        assert d["iv_percentile"] == 42.0
        assert d["iv_high_52w"] == 40.0  # Percent
        assert d["iv_low_52w"] == 15.0  # Percent
        assert d["source"] == "ibkr"

    def test_to_dict_with_none_values(self):
        """Test to_dict with None values."""
        data = IVData(
            symbol="TEST",
            current_iv=None,
            iv_rank=None,
            iv_percentile=None,
            iv_high_52w=None,
            iv_low_52w=None,
            data_points=0,
            source=IVSource.UNKNOWN,
            updated_at="2026-01-15",
        )
        d = data.to_dict()

        assert d["current_iv"] is None
        assert d["iv_rank"] is None


# =============================================================================
# IV CACHE ENTRY TESTS
# =============================================================================


class TestIVCacheEntry:
    """Tests for IVCacheEntry dataclass."""

    def test_creation(self, sample_cache_entry):
        """Test IVCacheEntry creation."""
        entry = sample_cache_entry
        assert entry.iv_high == 0.30
        assert entry.iv_low == 0.20
        assert entry.data_points == 6
        assert entry.source == "ibkr"
        assert len(entry.iv_history) == 6


# =============================================================================
# IV CALCULATION TESTS
# =============================================================================


class TestCalculateIVRank:
    """Tests for calculate_iv_rank function."""

    def test_basic_calculation(self, sample_iv_history):
        """Test basic IV rank calculation."""
        current_iv = 0.30
        rank = calculate_iv_rank(current_iv, sample_iv_history)

        assert rank is not None
        assert 0 <= rank <= 100

    def test_iv_at_low(self, small_iv_history):
        """Test IV rank at historical low."""
        # small_iv_history is [0.20, 0.21, ..., 0.49] - 30 points
        current_iv = 0.20  # At the low
        rank = calculate_iv_rank(current_iv, small_iv_history)

        assert rank == 0.0

    def test_iv_at_high(self, small_iv_history):
        """Test IV rank at historical high."""
        current_iv = 0.49  # At the high
        rank = calculate_iv_rank(current_iv, small_iv_history)

        assert rank == 100.0

    def test_iv_in_middle(self, small_iv_history):
        """Test IV rank in middle."""
        # Range is 0.20 to 0.49 (0.29 spread), middle is 0.345
        current_iv = 0.345
        rank = calculate_iv_rank(current_iv, small_iv_history)

        assert abs(rank - 50.0) < 0.01  # Allow for floating-point precision

    def test_insufficient_data(self):
        """Test with insufficient data."""
        iv_history = [0.25, 0.30]  # Less than 20 data points
        current_iv = 0.27
        rank = calculate_iv_rank(current_iv, iv_history)

        assert rank is None

    def test_empty_history(self):
        """Test with empty history."""
        rank = calculate_iv_rank(0.25, [])
        assert rank is None

    def test_zero_current_iv(self, small_iv_history):
        """Test with zero current IV."""
        rank = calculate_iv_rank(0.0, small_iv_history)
        assert rank is None

    def test_none_current_iv(self, small_iv_history):
        """Test with None current IV."""
        rank = calculate_iv_rank(None, small_iv_history)
        assert rank is None

    def test_no_variation_in_history(self):
        """Test when all historical values are the same."""
        iv_history = [0.25] * 30
        current_iv = 0.25
        rank = calculate_iv_rank(current_iv, iv_history)

        assert rank == 50.0  # Returns 50 when no variation

    def test_iv_below_historical_low(self, small_iv_history):
        """Test when current IV is below historical low."""
        current_iv = 0.10  # Below the low of 0.20
        rank = calculate_iv_rank(current_iv, small_iv_history)

        assert rank == 0.0  # Clamped to 0

    def test_iv_above_historical_high(self, small_iv_history):
        """Test when current IV is above historical high."""
        current_iv = 0.60  # Above the high of 0.49
        rank = calculate_iv_rank(current_iv, small_iv_history)

        assert rank == 100.0  # Clamped to 100


class TestCalculateIVPercentile:
    """Tests for calculate_iv_percentile function."""

    def test_basic_calculation(self, sample_iv_history):
        """Test basic IV percentile calculation."""
        current_iv = 0.25
        percentile = calculate_iv_percentile(current_iv, sample_iv_history)

        assert percentile is not None
        assert 0 <= percentile <= 100

    def test_lowest_iv(self, small_iv_history):
        """Test percentile when current IV is the lowest."""
        current_iv = 0.10  # Below all values
        percentile = calculate_iv_percentile(current_iv, small_iv_history)

        assert percentile == 0.0

    def test_highest_iv(self, small_iv_history):
        """Test percentile when current IV is the highest."""
        current_iv = 0.60  # Above all values
        percentile = calculate_iv_percentile(current_iv, small_iv_history)

        assert percentile == 100.0

    def test_insufficient_data(self):
        """Test with insufficient data."""
        iv_history = [0.25, 0.30]
        percentile = calculate_iv_percentile(0.27, iv_history)
        assert percentile is None

    def test_empty_history(self):
        """Test with empty history."""
        percentile = calculate_iv_percentile(0.25, [])
        assert percentile is None


# =============================================================================
# IV CACHE TESTS
# =============================================================================


class TestIVCache:
    """Tests for IVCache class."""

    def test_initialization(self, temp_cache_dir):
        """Test basic initialization."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        assert cache is not None
        assert cache.cache_file == cache_file

    def test_initialization_with_custom_path(self, temp_cache_dir):
        """Test initialization with custom cache file path."""
        cache_file = temp_cache_dir / "custom_iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        assert cache.cache_file == cache_file

    def test_get_history_nonexistent_symbol(self, temp_cache_dir):
        """Test getting history for nonexistent symbol."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        result = cache.get_history("NONEXISTENT")
        assert result == []  # Returns empty list

    def test_update_and_get_history(self, temp_cache_dir, small_iv_history):
        """Test updating and getting IV history."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        result = cache.get_history("AAPL")

        assert result is not None
        assert len(result) == len(small_iv_history)

    def test_get_iv_data(self, temp_cache_dir, small_iv_history):
        """Test getting full IV data."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        result = cache.get_iv_data("AAPL", current_iv=0.30)

        assert result is not None
        assert result.symbol == "AAPL"
        assert result.current_iv == 0.30
        assert result.iv_rank is not None

    def test_add_iv_point(self, temp_cache_dir):
        """Test adding a single IV point."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.add_iv_point("AAPL", 0.25, IVSource.IBKR)
        cache.add_iv_point("AAPL", 0.30, IVSource.IBKR)

        history = cache.get_history("AAPL")
        # May return empty if cache considers it stale or not enough data
        # But shouldn't crash

    def test_add_iv_point_invalid_value(self, temp_cache_dir):
        """Test adding invalid IV values."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        # Should not crash with invalid values
        cache.add_iv_point("AAPL", 0.0, IVSource.IBKR)
        cache.add_iv_point("AAPL", -0.1, IVSource.IBKR)
        cache.add_iv_point("AAPL", None, IVSource.IBKR)

    def test_add_iv_points_batch(self, temp_cache_dir):
        """Test batch adding IV points."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        entries = [
            ("AAPL", 0.25, IVSource.IBKR),
            ("MSFT", 0.22, IVSource.IBKR),
            ("GOOGL", 0.28, IVSource.IBKR),
        ]

        added = cache.add_iv_points_batch(entries)
        assert added == 3

    def test_is_fresh(self, temp_cache_dir, small_iv_history):
        """Test is_fresh method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file, max_age_days=14)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        assert cache.is_fresh("AAPL") is True
        assert cache.is_fresh("NONEXISTENT") is False

    def test_get_cache_age(self, temp_cache_dir, small_iv_history):
        """Test get_cache_age method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        age = cache.get_cache_age("AAPL")

        assert age is not None
        assert age == 0  # Just created

    def test_get_stale_symbols(self, temp_cache_dir, small_iv_history):
        """Test get_stale_symbols method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)

        stale = cache.get_stale_symbols(["AAPL", "MSFT", "GOOGL"])
        assert "AAPL" not in stale  # Fresh
        assert "MSFT" in stale  # Not in cache
        assert "GOOGL" in stale  # Not in cache

    def test_invalidate(self, temp_cache_dir, small_iv_history):
        """Test invalidate method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        cache.invalidate("AAPL")

        assert "AAPL" not in cache

    def test_stats(self, temp_cache_dir, small_iv_history):
        """Test stats method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        stats = cache.stats()

        assert "total_symbols" in stats
        assert stats["total_symbols"] == 1
        assert "fresh_entries" in stats

    def test_len(self, temp_cache_dir, small_iv_history):
        """Test __len__ method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        cache.update_history("MSFT", small_iv_history, IVSource.IBKR)

        assert len(cache) == 2

    def test_contains(self, temp_cache_dir, small_iv_history):
        """Test __contains__ method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)

        assert "AAPL" in cache
        assert "aapl" in cache  # Case insensitive
        assert "MSFT" not in cache


class TestIVCachePersistence:
    """Tests for IV cache persistence."""

    def test_save_and_load(self, temp_cache_dir, small_iv_history):
        """Test saving and loading cache."""
        cache_file = temp_cache_dir / "iv_cache.json"

        # Create and populate cache
        cache1 = IVCache(cache_file=cache_file)
        cache1.update_history("AAPL", small_iv_history, IVSource.IBKR)

        # Create new cache instance (should load from file)
        cache2 = IVCache(cache_file=cache_file)
        history = cache2.get_history("AAPL")

        assert len(history) == len(small_iv_history)

    def test_load_corrupted_file(self, temp_cache_dir):
        """Test loading corrupted cache file."""
        cache_file = temp_cache_dir / "iv_cache.json"

        # Write invalid JSON
        with open(cache_file, "w") as f:
            f.write("invalid json content {{{")

        # Should handle gracefully
        cache = IVCache(cache_file=cache_file)
        # Should not crash, just start with empty cache
        assert cache.get_history("AAPL") == []

    def test_load_missing_file(self, temp_cache_dir):
        """Test loading when cache file doesn't exist."""
        cache_file = temp_cache_dir / "nonexistent.json"

        # Should handle gracefully
        cache = IVCache(cache_file=cache_file)
        assert cache.get_history("AAPL") == []


# =============================================================================
# IV FETCHER TESTS
# =============================================================================


class TestIVFetcher:
    """Tests for IVFetcher class."""

    def test_initialization(self, temp_cache_dir):
        """Test IVFetcher initialization."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = IVFetcher(cache=cache)
        assert fetcher is not None

    def test_get_iv_rank_with_cache(self, temp_cache_dir, small_iv_history):
        """Test get_iv_rank with cached data."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)

        fetcher = IVFetcher(cache=cache)
        iv_data = fetcher.get_iv_rank("AAPL", current_iv=0.30)

        assert iv_data is not None
        assert iv_data.symbol == "AAPL"
        assert iv_data.current_iv == 0.30

    def test_get_iv_rank_no_cache(self, temp_cache_dir):
        """Test get_iv_rank without cached data."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)

        fetcher = IVFetcher(cache=cache)
        iv_data = fetcher.get_iv_rank("UNKNOWN", current_iv=0.30)

        # Should return IVData with None for rank/percentile
        assert iv_data is not None
        assert iv_data.symbol == "UNKNOWN"
        assert iv_data.current_iv == 0.30
        assert iv_data.iv_rank is None
        assert iv_data.data_points == 0

    def test_get_iv_rank_many(self, temp_cache_dir, small_iv_history):
        """Test get_iv_rank_many method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)
        cache.update_history("MSFT", small_iv_history, IVSource.IBKR)

        fetcher = IVFetcher(cache=cache)
        symbols_with_iv = [("AAPL", 0.30), ("MSFT", 0.25)]
        results = fetcher.get_iv_rank_many(symbols_with_iv)

        assert "AAPL" in results
        assert "MSFT" in results

    def test_extract_atm_iv_from_chain(self, temp_cache_dir):
        """Test extract_atm_iv_from_chain method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = IVFetcher(cache=cache)

        options_chain = [
            {"strike": 145, "greeks": {"mid_iv": 0.25}},
            {"strike": 150, "greeks": {"mid_iv": 0.28}},
            {"strike": 155, "greeks": {"mid_iv": 0.30}},
        ]
        underlying_price = 149.0

        atm_iv = fetcher.extract_atm_iv_from_chain(options_chain, underlying_price)
        assert atm_iv == 0.28  # Closest to 149 is 150

    def test_extract_atm_iv_with_smv_vol(self, temp_cache_dir):
        """Test extract_atm_iv_from_chain with smv_vol."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = IVFetcher(cache=cache)

        options_chain = [
            {"strike": 150, "greeks": {"smv_vol": 0.32, "mid_iv": 0.28}},
        ]

        atm_iv = fetcher.extract_atm_iv_from_chain(options_chain, 150.0)
        assert atm_iv == 0.32  # Prefers smv_vol

    def test_extract_atm_iv_empty_chain(self, temp_cache_dir):
        """Test extract_atm_iv_from_chain with empty chain."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = IVFetcher(cache=cache)

        atm_iv = fetcher.extract_atm_iv_from_chain([], 150.0)
        assert atm_iv is None


# =============================================================================
# HISTORICAL IV FETCHER TESTS
# =============================================================================


class TestHistoricalIVFetcher:
    """Tests for HistoricalIVFetcher class."""

    def test_initialization(self, temp_cache_dir):
        """Test HistoricalIVFetcher initialization."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = HistoricalIVFetcher(cache=cache)
        assert fetcher is not None

    def test_calculate_historical_volatility(self, temp_cache_dir):
        """Test calculate_historical_volatility method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = HistoricalIVFetcher(cache=cache)

        # Generate some price data
        prices = [100 + i * 0.5 for i in range(50)]

        hv_values = fetcher.calculate_historical_volatility(prices, window=20)

        assert len(hv_values) > 0
        for hv in hv_values:
            assert hv >= 0

    def test_calculate_historical_volatility_insufficient_data(self, temp_cache_dir):
        """Test calculate_historical_volatility with insufficient data."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = HistoricalIVFetcher(cache=cache)

        prices = [100, 101, 102]  # Too few data points
        hv_values = fetcher.calculate_historical_volatility(prices, window=20)

        assert hv_values == []

    def test_estimate_iv_from_hv(self, temp_cache_dir):
        """Test estimate_iv_from_hv method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = HistoricalIVFetcher(cache=cache)

        hv_values = [0.20, 0.22, 0.25]
        estimated_iv = fetcher.estimate_iv_from_hv(hv_values, iv_premium=1.15)

        assert len(estimated_iv) == 3
        # IV should be higher than HV (with premium)
        for iv, hv in zip(estimated_iv, hv_values):
            assert iv >= hv

    def test_estimate_iv_from_hv_empty(self, temp_cache_dir):
        """Test estimate_iv_from_hv with empty data."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        fetcher = HistoricalIVFetcher(cache=cache)

        estimated_iv = fetcher.estimate_iv_from_hv([])
        assert estimated_iv == []

    def test_get_stale_symbols(self, temp_cache_dir, small_iv_history):
        """Test get_stale_symbols method."""
        cache_file = temp_cache_dir / "iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        cache.update_history("AAPL", small_iv_history, IVSource.IBKR)

        fetcher = HistoricalIVFetcher(cache=cache)
        stale = fetcher.get_stale_symbols(["AAPL", "MSFT"])

        assert "AAPL" not in stale
        assert "MSFT" in stale


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_reset_iv_cache(self):
        """Test reset_iv_cache function."""
        reset_iv_cache()

        # Should create new instances
        cache1 = get_iv_cache()
        reset_iv_cache()
        cache2 = get_iv_cache()

        # They should be different instances
        assert cache1 is not cache2

    def test_get_iv_cache(self):
        """Test get_iv_cache returns singleton."""
        reset_iv_cache()
        cache1 = get_iv_cache()
        cache2 = get_iv_cache()

        assert cache1 is cache2

    def test_get_iv_fetcher(self):
        """Test get_iv_fetcher returns singleton."""
        reset_iv_cache()
        fetcher1 = get_iv_fetcher()
        fetcher2 = get_iv_fetcher()

        assert fetcher1 is fetcher2

    def test_get_iv_rank_function(self):
        """Test get_iv_rank convenience function."""
        reset_iv_cache()
        iv_data = get_iv_rank("AAPL", 0.30)

        assert iv_data is not None
        assert iv_data.symbol == "AAPL"
        assert iv_data.current_iv == 0.30

    def test_is_iv_elevated_function(self):
        """Test is_iv_elevated convenience function."""
        reset_iv_cache()
        # Without history, should return False
        result = is_iv_elevated("AAPL", 0.30, threshold=50.0)
        assert result is False
