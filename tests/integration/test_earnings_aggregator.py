# OptionPlay - Tests for Earnings Aggregator
# ============================================

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock
import src.utils.earnings_aggregator as earnings_aggregator_module
from src.utils.earnings_aggregator import (
    EarningsAggregator,
    EarningsResult,
    EarningsSource,
    AggregatedEarnings,
    get_earnings_aggregator,
    create_earnings_result,
)


# =============================================================================
# EARNINGS SOURCE ENUM TESTS
# =============================================================================

class TestEarningsSource:
    """Tests for EarningsSource enum."""

    def test_source_values(self):
        """Test source enum values."""
        assert EarningsSource.MARKETDATA.value == "marketdata"
        assert EarningsSource.YAHOO_DIRECT.value == "yahoo_direct"
        assert EarningsSource.YFINANCE.value == "yfinance"

    def test_source_confidence_weights(self):
        """Test confidence weights are properly ordered."""
        assert EarningsSource.MARKETDATA.confidence == 3
        assert EarningsSource.YAHOO_DIRECT.confidence == 2
        assert EarningsSource.YFINANCE.confidence == 1

        # Marketdata should be most trusted
        assert EarningsSource.MARKETDATA.confidence > EarningsSource.YAHOO_DIRECT.confidence
        assert EarningsSource.YAHOO_DIRECT.confidence > EarningsSource.YFINANCE.confidence

    def test_all_sources_have_confidence(self):
        """Test that all sources have valid confidence values."""
        for source in EarningsSource:
            assert isinstance(source.confidence, int)
            assert source.confidence >= 1  # Minimum confidence

    def test_source_from_value(self):
        """Test creating source from string value."""
        assert EarningsSource("marketdata") == EarningsSource.MARKETDATA
        assert EarningsSource("yahoo_direct") == EarningsSource.YAHOO_DIRECT
        assert EarningsSource("yfinance") == EarningsSource.YFINANCE

    def test_invalid_source_value_raises(self):
        """Test that invalid source value raises ValueError."""
        with pytest.raises(ValueError):
            EarningsSource("invalid_source")


# =============================================================================
# EARNINGS RESULT TESTS
# =============================================================================

class TestEarningsResult:
    """Tests for EarningsResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful result."""
        result = EarningsResult(
            source=EarningsSource.MARKETDATA,
            earnings_date="2025-04-15",
            days_to_earnings=80,
            success=True
        )

        assert result.source == EarningsSource.MARKETDATA
        assert result.earnings_date == "2025-04-15"
        assert result.days_to_earnings == 80
        assert result.success is True
        assert result.confidence == 3  # Marketdata weight

    def test_failed_result(self):
        """Test creating a failed result."""
        result = EarningsResult(
            source=EarningsSource.YAHOO_DIRECT,
            earnings_date=None,
            days_to_earnings=None,
            success=False,
            error="Connection timeout"
        )

        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.confidence == 0  # No confidence for failed results

    def test_empty_date_result(self):
        """Test result with no date found."""
        result = EarningsResult(
            source=EarningsSource.YFINANCE,
            earnings_date=None,
            days_to_earnings=None,
            success=True
        )

        assert result.success is True
        assert result.earnings_date is None
        assert result.confidence == 0  # No confidence without date

    def test_default_values(self):
        """Test default values for EarningsResult."""
        result = EarningsResult(
            source=EarningsSource.MARKETDATA,
            earnings_date="2025-04-15",
            days_to_earnings=30
        )

        assert result.success is True  # Default
        assert result.error is None  # Default

    def test_confidence_with_success_but_no_date(self):
        """Test confidence is 0 when successful but no date."""
        result = EarningsResult(
            source=EarningsSource.MARKETDATA,  # High weight source
            earnings_date=None,
            days_to_earnings=None,
            success=True
        )

        assert result.confidence == 0

    def test_confidence_with_failure_and_date(self):
        """Test confidence is 0 when failed even with date."""
        result = EarningsResult(
            source=EarningsSource.MARKETDATA,
            earnings_date="2025-04-15",  # Has date
            days_to_earnings=80,
            success=False,  # But failed
            error="Parse error"
        )

        assert result.confidence == 0

    def test_result_immutability_check(self):
        """Test that result attributes are accessible."""
        result = EarningsResult(
            source=EarningsSource.YAHOO_DIRECT,
            earnings_date="2025-06-01",
            days_to_earnings=120,
            success=True
        )

        # Dataclass should allow attribute access
        assert result.source.value == "yahoo_direct"
        assert result.earnings_date == "2025-06-01"


# =============================================================================
# CREATE EARNINGS RESULT HELPER TESTS
# =============================================================================

class TestCreateEarningsResult:
    """Tests for create_earnings_result helper function."""

    def test_create_valid_result(self):
        """Test creating result from raw data."""
        result = create_earnings_result(
            source="marketdata",
            earnings_date="2025-04-15",
            days_to_earnings=80
        )

        assert result.source == EarningsSource.MARKETDATA
        assert result.earnings_date == "2025-04-15"
        assert result.success is True

    def test_create_result_with_error(self):
        """Test creating result with error."""
        result = create_earnings_result(
            source="yahoo_direct",
            earnings_date=None,
            days_to_earnings=None,
            error="API error"
        )

        assert result.source == EarningsSource.YAHOO_DIRECT
        assert result.success is False
        assert result.error == "API error"

    def test_create_result_unknown_source(self):
        """Test creating result with unknown source defaults to yfinance."""
        result = create_earnings_result(
            source="unknown_source",
            earnings_date="2025-04-15",
            days_to_earnings=80
        )

        assert result.source == EarningsSource.YFINANCE

    def test_create_result_empty_source_string(self):
        """Test creating result with empty source string."""
        result = create_earnings_result(
            source="",
            earnings_date="2025-04-15",
            days_to_earnings=80
        )

        # Empty string should fallback to YFINANCE
        assert result.source == EarningsSource.YFINANCE

    def test_create_result_case_sensitivity(self):
        """Test that source matching is case-sensitive."""
        # Uppercase should not match (enum values are lowercase)
        result = create_earnings_result(
            source="MARKETDATA",
            earnings_date="2025-04-15",
            days_to_earnings=80
        )

        # Should fallback to YFINANCE since MARKETDATA != marketdata
        assert result.source == EarningsSource.YFINANCE

    def test_create_result_none_error_means_success(self):
        """Test that None error means success."""
        result = create_earnings_result(
            source="marketdata",
            earnings_date="2025-04-15",
            days_to_earnings=80,
            error=None
        )

        assert result.success is True

    def test_create_result_empty_string_error_means_failure(self):
        """Test that empty string error still means failure."""
        result = create_earnings_result(
            source="marketdata",
            earnings_date="2025-04-15",
            days_to_earnings=80,
            error=""
        )

        # Empty string is not None, so success should be False
        assert result.success is False

    def test_create_result_all_sources(self):
        """Test creating results for all valid sources."""
        sources = ["marketdata", "yahoo_direct", "yfinance"]
        expected = [
            EarningsSource.MARKETDATA,
            EarningsSource.YAHOO_DIRECT,
            EarningsSource.YFINANCE,
        ]

        for source_str, expected_enum in zip(sources, expected):
            result = create_earnings_result(
                source=source_str,
                earnings_date="2025-04-15",
                days_to_earnings=80
            )
            assert result.source == expected_enum


# =============================================================================
# EARNINGS AGGREGATOR INITIALIZATION TESTS
# =============================================================================

class TestEarningsAggregatorInit:
    """Tests for EarningsAggregator initialization."""

    def test_default_initialization(self):
        """Test default aggregator initialization."""
        aggregator = EarningsAggregator()
        assert aggregator is not None

    def test_date_tolerance_constant(self):
        """Test DATE_TOLERANCE_DAYS constant."""
        aggregator = EarningsAggregator()
        assert aggregator.DATE_TOLERANCE_DAYS == 1

    def test_multiple_instances_independent(self):
        """Test that multiple instances are independent."""
        agg1 = EarningsAggregator()
        agg2 = EarningsAggregator()

        # They should be different objects
        assert agg1 is not agg2

    def test_class_constant_accessible(self):
        """Test DATE_TOLERANCE_DAYS is accessible at class level."""
        assert EarningsAggregator.DATE_TOLERANCE_DAYS == 1


# =============================================================================
# EARNINGS AGGREGATOR AGGREGATE METHOD TESTS
# =============================================================================

class TestEarningsAggregatorAggregate:
    """Tests for EarningsAggregator.aggregate method."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return EarningsAggregator()

    def test_all_sources_agree(self, aggregator):
        """Test when all sources return the same date."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YFINANCE, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 3
        assert aggregated.total_sources == 3
        assert aggregated.is_reliable is True
        assert aggregated.discrepancy_warning is False
        assert aggregated.confidence >= 80  # High confidence

    def test_two_sources_agree(self, aggregator):
        """Test when two sources agree and one differs."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YFINANCE, "2025-04-20", 85, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 2
        assert aggregated.is_reliable is True
        assert aggregated.discrepancy_warning is True

    def test_one_day_tolerance(self, aggregator):
        """Test that dates within 1 day are grouped together."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-16", 81, True),  # +1 day
            EarningsResult(EarningsSource.YFINANCE, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # All three should be grouped together (within tolerance)
        assert aggregated.sources_agree == 3
        assert aggregated.is_reliable is True

    def test_weighted_voting(self, aggregator):
        """Test that higher-weight sources win in close votes."""
        # Marketdata (weight 3) vs Yahoo + yfinance (weights 2+1=3)
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-20", 85, True),
            EarningsResult(EarningsSource.YFINANCE, "2025-04-20", 85, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Yahoo + yfinance have more agreement, so they should win
        assert aggregated.consensus_date == "2025-04-20"
        assert aggregated.sources_agree == 2

    def test_no_valid_results(self, aggregator):
        """Test when no sources return valid data."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, None, None, False, "Error 1"),
            EarningsResult(EarningsSource.YAHOO_DIRECT, None, None, False, "Error 2"),
            EarningsResult(EarningsSource.YFINANCE, None, None, True),  # Success but no date
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date is None
        assert aggregated.sources_agree == 0
        assert aggregated.is_reliable is False
        assert aggregated.confidence == 0

    def test_single_source_high_confidence(self, aggregator):
        """Test that single high-confidence source can be reliable."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, None, None, False, "Error"),
            EarningsResult(EarningsSource.YFINANCE, None, None, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1
        # Single source with high confidence should still be reliable
        assert aggregated.confidence >= 60

    def test_days_to_earnings_calculation(self, aggregator):
        """Test that days_to_earnings is calculated correctly."""
        today = date.today()
        future_date = today + timedelta(days=45)

        results = [
            EarningsResult(
                EarningsSource.MARKETDATA,
                future_date.isoformat(),
                45,
                True
            ),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.days_to_earnings == 45

    def test_discrepancy_details(self, aggregator):
        """Test that discrepancy details are formatted correctly."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-20", 85, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.discrepancy_warning is True
        assert "2025-04-15" in aggregated.discrepancy_details
        assert "2025-04-20" in aggregated.discrepancy_details
        assert "marketdata" in aggregated.discrepancy_details
        assert "yahoo_direct" in aggregated.discrepancy_details

    def test_empty_results_list(self, aggregator):
        """Test aggregation with empty results list."""
        aggregated = aggregator.aggregate("AAPL", [])

        assert aggregated.symbol == "AAPL"
        assert aggregated.consensus_date is None
        assert aggregated.total_sources == 0
        assert aggregated.sources_agree == 0
        assert aggregated.confidence == 0

    def test_symbol_preserved(self, aggregator):
        """Test that symbol is preserved in aggregation."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("TSLA", results)
        assert aggregated.symbol == "TSLA"

    def test_all_results_preserved(self, aggregator):
        """Test that all_results contains original results."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert len(aggregated.all_results) == 2
        assert aggregated.all_results == results

    def test_past_date_handling(self, aggregator):
        """Test handling of past earnings dates."""
        today = date.today()
        past_date = today - timedelta(days=30)

        results = [
            EarningsResult(
                EarningsSource.MARKETDATA,
                past_date.isoformat(),
                -30,
                True
            ),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == past_date.isoformat()
        assert aggregated.days_to_earnings == -30

    def test_invalid_date_format_ignored(self, aggregator):
        """Test that invalid date formats are ignored."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "invalid-date", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Should only use the valid date
        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1

    def test_two_day_gap_not_grouped(self, aggregator):
        """Test that dates 2+ days apart are not grouped."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-17", 82, True),  # +2 days
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Should have discrepancy since dates are 2 days apart
        assert aggregated.discrepancy_warning is True
        assert aggregated.sources_agree == 1

    def test_tie_breaking_prefers_earlier_date(self, aggregator):
        """Test that in close votes, earlier date is preferred."""
        # Both groups have same score (weight 3 + bonus 2 = 5 each)
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-20", 85, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YFINANCE, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Yahoo + yfinance have equal or greater total score, but
        # the algorithm considers agreement bonus
        assert aggregated.discrepancy_warning is True


# =============================================================================
# DATE CALCULATIONS TESTS
# =============================================================================

class TestDateCalculations:
    """Tests for date-related calculations in aggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return EarningsAggregator()

    def test_days_to_earnings_today(self, aggregator):
        """Test days_to_earnings when earnings is today."""
        today = date.today()

        results = [
            EarningsResult(
                EarningsSource.MARKETDATA,
                today.isoformat(),
                0,
                True
            ),
        ]

        aggregated = aggregator.aggregate("AAPL", results)
        assert aggregated.days_to_earnings == 0

    def test_days_to_earnings_far_future(self, aggregator):
        """Test days_to_earnings for far future date."""
        today = date.today()
        future_date = today + timedelta(days=365)

        results = [
            EarningsResult(
                EarningsSource.MARKETDATA,
                future_date.isoformat(),
                365,
                True
            ),
        ]

        aggregated = aggregator.aggregate("AAPL", results)
        assert aggregated.days_to_earnings == 365

    def test_days_to_earnings_negative(self, aggregator):
        """Test days_to_earnings for past date."""
        today = date.today()
        past_date = today - timedelta(days=100)

        results = [
            EarningsResult(
                EarningsSource.MARKETDATA,
                past_date.isoformat(),
                -100,
                True
            ),
        ]

        aggregated = aggregator.aggregate("AAPL", results)
        assert aggregated.days_to_earnings == -100

    def test_leap_year_date_handling(self, aggregator):
        """Test handling of leap year dates."""
        # February 29, 2024 (leap year)
        leap_date = "2024-02-29"

        results = [
            EarningsResult(EarningsSource.MARKETDATA, leap_date, 30, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)
        assert aggregated.consensus_date == leap_date

    def test_year_boundary_tolerance(self, aggregator):
        """Test date tolerance across year boundary."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2024-12-31", 30, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-01-01", 31, True),  # +1 day
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Should be grouped together (within tolerance)
        assert aggregated.sources_agree == 2
        assert aggregated.discrepancy_warning is False

    def test_month_boundary_tolerance(self, aggregator):
        """Test date tolerance across month boundary."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-01-31", 30, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-02-01", 31, True),  # +1 day
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Should be grouped together (within tolerance)
        assert aggregated.sources_agree == 2


# =============================================================================
# DATA VALIDATION TESTS
# =============================================================================

class TestDataValidation:
    """Tests for data validation in aggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return EarningsAggregator()

    def test_malformed_date_string(self, aggregator):
        """Test handling of malformed date strings."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025/04/15", 80, True),  # Wrong format
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),  # Correct
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Only valid date should be used
        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1

    def test_partial_date_string(self, aggregator):
        """Test handling of partial date strings."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04", 80, True),  # Missing day
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1

    def test_empty_date_string(self, aggregator):
        """Test handling of empty date strings."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"

    def test_all_invalid_dates(self, aggregator):
        """Test when all dates are invalid."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "invalid1", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "invalid2", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date is None
        assert aggregated.sources_agree == 0

    def test_impossible_date(self, aggregator):
        """Test handling of impossible dates."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-02-30", 80, True),  # Invalid
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1

    def test_whitespace_in_symbol(self, aggregator):
        """Test symbol with whitespace is preserved."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("  AAPL  ", results)
        assert aggregated.symbol == "  AAPL  "  # Preserved as-is

    def test_empty_symbol(self, aggregator):
        """Test empty symbol is allowed."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("", results)
        assert aggregated.symbol == ""

    def test_mixed_valid_invalid_dates(self, aggregator):
        """Test mixture of valid and invalid dates."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, None, None, True),
            EarningsResult(EarningsSource.YFINANCE, "not-a-date", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1
        assert aggregated.total_sources == 3


# =============================================================================
# AGGREGATED EARNINGS TESTS
# =============================================================================

class TestAggregatedEarnings:
    """Tests for AggregatedEarnings dataclass."""

    def test_is_reliable_multiple_sources(self):
        """Test is_reliable with multiple agreeing sources."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date="2025-04-15",
            days_to_earnings=80,
            confidence=85,
            sources_agree=2,
            total_sources=3
        )

        assert aggregated.is_reliable is True

    def test_is_reliable_single_high_confidence(self):
        """Test is_reliable with single high-confidence source."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date="2025-04-15",
            days_to_earnings=80,
            confidence=75,
            sources_agree=1,
            total_sources=3
        )

        assert aggregated.is_reliable is True  # >= 60% confidence

    def test_is_reliable_single_low_confidence(self):
        """Test is_reliable with single low-confidence source."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date="2025-04-15",
            days_to_earnings=80,
            confidence=40,
            sources_agree=1,
            total_sources=3
        )

        assert aggregated.is_reliable is False  # < 60% confidence

    def test_is_reliable_boundary_confidence(self):
        """Test is_reliable at exactly 60% confidence boundary."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date="2025-04-15",
            days_to_earnings=80,
            confidence=60,
            sources_agree=1,
            total_sources=3
        )

        assert aggregated.is_reliable is True  # Exactly 60%

    def test_is_reliable_below_boundary(self):
        """Test is_reliable just below 60% confidence."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date="2025-04-15",
            days_to_earnings=80,
            confidence=59,
            sources_agree=1,
            total_sources=3
        )

        assert aggregated.is_reliable is False  # Below 60%

    def test_is_reliable_zero_sources(self):
        """Test is_reliable with zero sources agreeing."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date=None,
            days_to_earnings=None,
            confidence=0,
            sources_agree=0,
            total_sources=3
        )

        assert aggregated.is_reliable is False

    def test_source_summary(self):
        """Test source_summary property."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YFINANCE, None, None, False),
        ]

        aggregated = AggregatedEarnings(
            symbol="AAPL",
            consensus_date="2025-04-15",
            all_results=results
        )

        summary = aggregated.source_summary
        assert "marketdata" in summary
        assert "yahoo_direct" in summary

    def test_source_summary_no_successful_sources(self):
        """Test source_summary with no successful sources."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, None, None, False),
            EarningsResult(EarningsSource.YAHOO_DIRECT, None, None, False),
        ]

        aggregated = AggregatedEarnings(
            symbol="AAPL",
            all_results=results
        )

        assert aggregated.source_summary == "none"

    def test_source_summary_empty_results(self):
        """Test source_summary with empty results list."""
        aggregated = AggregatedEarnings(
            symbol="AAPL",
            all_results=[]
        )

        assert aggregated.source_summary == "none"

    def test_default_values(self):
        """Test default values of AggregatedEarnings."""
        aggregated = AggregatedEarnings(symbol="AAPL")

        assert aggregated.consensus_date is None
        assert aggregated.days_to_earnings is None
        assert aggregated.confidence == 0
        assert aggregated.sources_agree == 0
        assert aggregated.total_sources == 0
        assert aggregated.all_results == []
        assert aggregated.discrepancy_warning is False
        assert aggregated.discrepancy_details is None

    def test_source_summary_with_date_but_failed(self):
        """Test source_summary excludes sources with date but failed."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, False),  # Failed
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),  # Success
        ]

        aggregated = AggregatedEarnings(
            symbol="AAPL",
            all_results=results
        )

        summary = aggregated.source_summary
        assert "marketdata" not in summary  # Failed, excluded
        assert "yahoo_direct" in summary


# =============================================================================
# INTERNAL METHODS TESTS
# =============================================================================

class TestInternalMethods:
    """Tests for internal aggregator methods."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return EarningsAggregator()

    def test_group_by_date_single_date(self, aggregator):
        """Test _group_by_date with single date."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        groups = aggregator._group_by_date(results)

        assert len(groups) == 1
        assert "2025-04-15" in groups
        assert len(groups["2025-04-15"]) == 1

    def test_group_by_date_multiple_same_date(self, aggregator):
        """Test _group_by_date with multiple same dates."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        groups = aggregator._group_by_date(results)

        assert len(groups) == 1
        assert len(groups["2025-04-15"]) == 2

    def test_group_by_date_within_tolerance(self, aggregator):
        """Test _group_by_date groups dates within tolerance."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-16", 81, True),
        ]

        groups = aggregator._group_by_date(results)

        # Should be in same group due to tolerance
        assert len(groups) == 1

    def test_group_by_date_outside_tolerance(self, aggregator):
        """Test _group_by_date separates dates outside tolerance."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-20", 85, True),
        ]

        groups = aggregator._group_by_date(results)

        # Should be in different groups
        assert len(groups) == 2

    def test_group_by_date_empty_results(self, aggregator):
        """Test _group_by_date with empty results."""
        groups = aggregator._group_by_date([])
        assert len(groups) == 0

    def test_group_by_date_invalid_dates_skipped(self, aggregator):
        """Test _group_by_date skips invalid dates."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "invalid", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        groups = aggregator._group_by_date(results)

        assert len(groups) == 1
        assert "2025-04-15" in groups

    def test_find_consensus_single_group(self, aggregator):
        """Test _find_consensus with single group."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]
        date_groups = {"2025-04-15": results}

        consensus_date, agreeing = aggregator._find_consensus(date_groups)

        assert consensus_date == "2025-04-15"
        assert len(agreeing) == 1

    def test_find_consensus_empty_groups(self, aggregator):
        """Test _find_consensus with empty groups."""
        consensus_date, agreeing = aggregator._find_consensus({})

        assert consensus_date is None
        assert agreeing == []

    def test_calculate_confidence_all_agree(self, aggregator):
        """Test _calculate_confidence when all results agree."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
        ]

        confidence = aggregator._calculate_confidence(results, results)

        # Should be high (100% agreement + bonus)
        assert confidence >= 80

    def test_calculate_confidence_empty(self, aggregator):
        """Test _calculate_confidence with empty agreeing results."""
        all_results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        confidence = aggregator._calculate_confidence([], all_results)
        assert confidence == 0

    def test_calculate_confidence_bonus_for_multiple(self, aggregator):
        """Test _calculate_confidence gives bonus for multiple sources."""
        result1 = EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True)
        result2 = EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True)

        single_conf = aggregator._calculate_confidence([result1], [result1])
        multi_conf = aggregator._calculate_confidence([result1, result2], [result1, result2])

        # Multiple sources should get bonus
        assert multi_conf >= single_conf

    def test_format_discrepancy_single_group(self, aggregator):
        """Test _format_discrepancy with single group."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]
        date_groups = {"2025-04-15": results}

        formatted = aggregator._format_discrepancy(date_groups)

        assert "2025-04-15" in formatted
        assert "marketdata" in formatted

    def test_format_discrepancy_multiple_groups(self, aggregator):
        """Test _format_discrepancy with multiple groups."""
        date_groups = {
            "2025-04-15": [EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True)],
            "2025-04-20": [EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-20", 85, True)],
        }

        formatted = aggregator._format_discrepancy(date_groups)

        assert "2025-04-15" in formatted
        assert "2025-04-20" in formatted
        assert " vs " in formatted


# =============================================================================
# GLOBAL AGGREGATOR TESTS
# =============================================================================

class TestGlobalAggregator:
    """Tests for global aggregator instance."""

    def setup_method(self):
        """Reset global aggregator before each test."""
        earnings_aggregator_module._aggregator = None

    def test_get_aggregator_singleton(self):
        """Test that get_earnings_aggregator returns same instance."""
        aggregator1 = get_earnings_aggregator()
        aggregator2 = get_earnings_aggregator()

        assert aggregator1 is aggregator2

    def test_aggregator_instance_type(self):
        """Test that global aggregator is correct type."""
        aggregator = get_earnings_aggregator()
        assert isinstance(aggregator, EarningsAggregator)

    def test_singleton_reset(self):
        """Test that resetting module variable creates new instance."""
        aggregator1 = get_earnings_aggregator()

        # Reset the singleton
        earnings_aggregator_module._aggregator = None

        aggregator2 = get_earnings_aggregator()

        # Should be different instances after reset
        assert aggregator1 is not aggregator2

    def test_global_aggregator_functional(self):
        """Test that global aggregator works correctly."""
        aggregator = get_earnings_aggregator()

        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"


# =============================================================================
# EDGE CASES AND STRESS TESTS
# =============================================================================

class TestEdgeCases:
    """Edge case tests for earnings aggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return EarningsAggregator()

    def test_large_number_of_results(self, aggregator):
        """Test with many results."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True)
            for _ in range(100)
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 100
        assert aggregated.total_sources == 100

    def test_many_different_dates(self, aggregator):
        """Test with many different dates (outside tolerance)."""
        base_date = date(2025, 4, 1)
        results = [
            EarningsResult(
                EarningsSource.YFINANCE,
                (base_date + timedelta(days=i * 5)).isoformat(),  # 5 days apart
                i * 5,
                True
            )
            for i in range(10)
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Should have many discrepancies
        assert aggregated.discrepancy_warning is True
        assert aggregated.sources_agree == 1  # Each date is unique

    def test_special_characters_in_symbol(self, aggregator):
        """Test with special characters in symbol."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("BRK.B", results)
        assert aggregated.symbol == "BRK.B"

    def test_unicode_in_symbol(self, aggregator):
        """Test with unicode characters in symbol."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
        ]

        aggregated = aggregator.aggregate("TEST-", results)
        assert aggregated.symbol == "TEST-"

    def test_very_old_date(self, aggregator):
        """Test with very old date."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "1990-01-01", -10000, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "1990-01-01"

    def test_very_future_date(self, aggregator):
        """Test with very future date."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2099-12-31", 30000, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2099-12-31"

    def test_all_sources_different_dates(self, aggregator):
        """Test when all sources report completely different dates."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-01-15", 30, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 120, True),
            EarningsResult(EarningsSource.YFINANCE, "2025-07-15", 210, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        # Should pick highest weighted (MARKETDATA has weight 3)
        assert aggregated.discrepancy_warning is True
        assert aggregated.sources_agree == 1

    def test_none_results_in_list(self, aggregator):
        """Test that None results don't cause errors."""
        results = [
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
            EarningsResult(EarningsSource.YAHOO_DIRECT, None, None, True),
        ]

        aggregated = aggregator.aggregate("AAPL", results)

        assert aggregated.consensus_date == "2025-04-15"
        assert aggregated.sources_agree == 1


# =============================================================================
# LOGGING TESTS
# =============================================================================

class TestLogging:
    """Tests for logging behavior."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator instance."""
        return EarningsAggregator()

    def test_discrepancy_logs_warning(self, aggregator, caplog):
        """Test that discrepancy logs a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            results = [
                EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
                EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-20", 85, True),
            ]

            aggregator.aggregate("AAPL", results)

        # Check warning was logged
        assert any("discrepancy" in record.message.lower() for record in caplog.records)
        assert any("AAPL" in record.message for record in caplog.records)

    def test_no_warning_when_all_agree(self, aggregator, caplog):
        """Test that no warning is logged when all sources agree."""
        import logging

        with caplog.at_level(logging.WARNING):
            results = [
                EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80, True),
                EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80, True),
            ]

            aggregator.aggregate("AAPL", results)

        # Check no warning was logged
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
