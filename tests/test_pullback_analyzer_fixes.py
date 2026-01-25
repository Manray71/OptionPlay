# OptionPlay - Pullback Analyzer Fixes Tests
# ============================================
# Tests for bug fixes

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.analyzers import PullbackAnalyzer
from src.models import PullbackCandidate, MACDResult, StochasticResult, TradeSignal
from src.config import PullbackScoringConfig


class TestInputValidation:
    """Tests for input validation in analyze()"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_validate_inputs_unequal_lengths(self, analyzer):
        """Unequal array lengths raise ValueError"""
        with pytest.raises(ValueError, match="same length"):
            analyzer.analyze_detailed(
                "TEST",
                prices=[100, 101],
                volumes=[1000],
                highs=[100, 101],
                lows=[99, 100]
            )
    
    def test_validate_inputs_empty_arrays(self, analyzer):
        """Empty arrays raise ValueError"""
        with pytest.raises(ValueError, match="empty"):
            analyzer.analyze_detailed("TEST", [], [], [], [])
    
    def test_validate_inputs_valid_data_passes(self, analyzer):
        """Valid data passes validation and returns PullbackCandidate"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        assert isinstance(result, PullbackCandidate)
    
    def test_analyze_returns_trade_signal(self, analyzer):
        """analyze() returns TradeSignal"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert isinstance(result, TradeSignal)


class TestMACDIndexAlignment:
    """Tests for MACD Index Mismatch Fix"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_macd_none_for_short_list(self, analyzer):
        """MACD returns None for short list"""
        prices = [100] * 30
        result = analyzer._calculate_macd(prices)
        assert result is None
    
    def test_macd_returns_result_for_sufficient_data(self, analyzer):
        """MACD returns result with sufficient data"""
        prices = [100 + i * 0.1 for i in range(50)]
        result = analyzer._calculate_macd(prices)
        assert result is not None
        assert isinstance(result, MACDResult)
    
    def test_macd_histogram_matches_difference(self, analyzer):
        """Histogram = MACD - Signal"""
        prices = [100 + i * 0.1 for i in range(50)]
        result = analyzer._calculate_macd(prices)
        assert result is not None
        expected_histogram = result.macd_line - result.signal_line
        assert abs(result.histogram - expected_histogram) < 0.0001


class TestStochasticValidation:
    """Tests for Stochastic input validation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_stochastic_unequal_lengths_returns_none(self, analyzer):
        """Unequal array lengths return None"""
        highs = [100, 101, 102]
        lows = [99, 100]
        closes = [100, 101, 102]
        result = analyzer._calculate_stochastic(highs, lows, closes)
        assert result is None
    
    def test_stochastic_valid_data_returns_result(self, analyzer):
        """Valid data returns StochasticResult"""
        n = 50
        highs = [100 + i * 0.2 for i in range(n)]
        lows = [99 + i * 0.2 for i in range(n)]
        closes = [99.5 + i * 0.2 for i in range(n)]
        result = analyzer._calculate_stochastic(highs, lows, closes)
        assert result is not None
        assert isinstance(result, StochasticResult)


class TestSupportDetectionEdgeCases:
    """Tests for Support level detection edge cases"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_support_detection_short_list(self, analyzer):
        """Support detection returns empty list with insufficient data"""
        lows = [100.0] * 30
        supports = analyzer._find_support_levels(lows)
        assert supports == []
    
    def test_resistance_detection_short_list(self, analyzer):
        """Resistance detection returns empty list with insufficient data"""
        highs = [100.0] * 30
        resistances = analyzer._find_resistance_levels(highs)
        assert resistances == []


class TestFullAnalysisWithFixes:
    """Integration tests: Full analysis with all fixes"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_full_analysis_with_valid_data(self, analyzer):
        """Full analysis with valid data returns PullbackCandidate"""
        n = 250
        prices = [100 + i * 0.05 + (i % 10) * 0.1 for i in range(n)]
        volumes = [1000000 + (i % 5) * 100000 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert isinstance(result, PullbackCandidate)
        assert result.symbol == "TEST"
        assert 0 <= result.score <= 10
        assert result.technicals is not None
        assert result.score_breakdown is not None
    
    def test_full_analysis_includes_macd(self, analyzer):
        """MACD is included in analysis"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        assert result.technicals.macd is not None
    
    def test_analyze_returns_trade_signal_with_details(self, analyzer):
        """analyze() returns TradeSignal with score_breakdown in details"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert isinstance(result, TradeSignal)
        assert 'score_breakdown' in result.details
        assert result.details['score_breakdown']['total_score'] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
