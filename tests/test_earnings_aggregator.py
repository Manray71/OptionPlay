# OptionPlay - Tests for Earnings Aggregator
# ============================================

import pytest
from datetime import date, timedelta
from src.utils.earnings_aggregator import (
    EarningsAggregator,
    EarningsResult,
    EarningsSource,
    AggregatedEarnings,
    get_earnings_aggregator,
    create_earnings_result,
)


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


class TestEarningsAggregator:
    """Tests for EarningsAggregator class."""
    
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


class TestGlobalAggregator:
    """Tests for global aggregator instance."""
    
    def test_get_aggregator_singleton(self):
        """Test that get_earnings_aggregator returns same instance."""
        aggregator1 = get_earnings_aggregator()
        aggregator2 = get_earnings_aggregator()
        
        assert aggregator1 is aggregator2
    
    def test_aggregator_instance_type(self):
        """Test that global aggregator is correct type."""
        aggregator = get_earnings_aggregator()
        assert isinstance(aggregator, EarningsAggregator)
