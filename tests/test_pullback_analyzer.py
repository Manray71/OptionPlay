# OptionPlay - Pullback Analyzer Tests
# ======================================

import pytest
import sys
from pathlib import Path

# Add project root to path (not src!)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.analyzers import PullbackAnalyzer
from src.models import (
    PullbackCandidate,
    ScoreBreakdown,
    TechnicalIndicators,
    MACDResult,
    StochasticResult,
    TradeSignal
)
from src.config import PullbackScoringConfig, RSIConfig, SupportConfig


class TestRSICalculation:
    """Tests for RSI calculation"""
    
    @pytest.fixture
    def analyzer(self):
        """Standard analyzer with default config"""
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_rsi_oversold(self, analyzer):
        """Falling prices should give low RSI"""
        prices = [100 - i * 0.5 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices, 14)
        assert rsi < 40
        
    def test_rsi_overbought(self, analyzer):
        """Rising prices should give high RSI"""
        prices = [100 + i * 0.5 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices, 14)
        assert rsi > 60
        
    def test_rsi_neutral(self, analyzer):
        """Sideways prices should give RSI around 50"""
        prices = [100 + (i % 2) * 0.5 - 0.25 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices, 14)
        assert 40 < rsi < 60
        
    def test_rsi_range(self, analyzer):
        """RSI should always be between 0 and 100"""
        prices_down = [100 - i * 2 for i in range(50)]
        prices_up = [100 + i * 2 for i in range(50)]
        
        rsi_down = analyzer._calculate_rsi(prices_down, 14)
        rsi_up = analyzer._calculate_rsi(prices_up, 14)
        
        assert 0 <= rsi_down <= 100
        assert 0 <= rsi_up <= 100


class TestMovingAverages:
    """Tests for Moving Average calculations"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_sma_calculation(self, analyzer):
        """SMA should calculate correct average"""
        prices = [10, 20, 30, 40, 50]
        sma = analyzer._calculate_sma(prices, 5)
        assert sma == 30.0
        
    def test_sma_uses_last_n_prices(self, analyzer):
        """SMA should only use last N prices"""
        prices = [100, 10, 20, 30, 40, 50]
        sma = analyzer._calculate_sma(prices, 5)
        assert sma == 30.0
        
    def test_ema_calculation(self, analyzer):
        """EMA should calculate exponential average"""
        prices = [10, 20, 30, 40, 50]
        ema_values = analyzer._calculate_ema(prices, 3)
        assert len(ema_values) > 0
        assert min(prices) <= ema_values[-1] <= max(prices)


class TestMACDCalculation:
    """Tests for MACD calculation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_macd_returns_result(self, analyzer):
        """MACD should return MACDResult with sufficient data"""
        prices = [100 + i * 0.1 for i in range(50)]
        result = analyzer._calculate_macd(prices)
        
        assert result is not None
        assert isinstance(result, MACDResult)
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'signal_line')
        assert hasattr(result, 'histogram')
        
    def test_macd_none_for_insufficient_data(self, analyzer):
        """MACD should return None with insufficient data"""
        prices = [100, 101, 102]
        result = analyzer._calculate_macd(prices)
        assert result is None
        
    def test_macd_crossover_detection(self, analyzer):
        """MACD should detect crossovers"""
        prices = [100 + i * 0.5 for i in range(50)]
        result = analyzer._calculate_macd(prices)
        
        assert result is not None
        assert result.crossover in [None, 'bullish', 'bearish']


class TestStochasticCalculation:
    """Tests for Stochastic calculation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_stochastic_returns_result(self, analyzer):
        """Stochastic should return StochasticResult"""
        n = 50
        highs = [100 + i * 0.2 for i in range(n)]
        lows = [99 + i * 0.2 for i in range(n)]
        closes = [99.5 + i * 0.2 for i in range(n)]
        
        result = analyzer._calculate_stochastic(highs, lows, closes)
        
        assert result is not None
        assert isinstance(result, StochasticResult)
        assert 0 <= result.k <= 100
        assert 0 <= result.d <= 100
        
    def test_stochastic_oversold_zone(self, analyzer):
        """Stochastic should detect oversold zone"""
        n = 50
        highs = [100] * n
        lows = [90] * n
        closes = [91] * n
        
        result = analyzer._calculate_stochastic(highs, lows, closes)
        
        assert result is not None
        assert result.zone == 'oversold'
        
    def test_stochastic_overbought_zone(self, analyzer):
        """Stochastic should detect overbought zone"""
        n = 50
        highs = [100] * n
        lows = [90] * n
        closes = [99] * n
        
        result = analyzer._calculate_stochastic(highs, lows, closes)
        
        assert result is not None
        assert result.zone == 'overbought'


class TestSupportResistance:
    """Tests for Support/Resistance detection"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_find_support_levels(self, analyzer):
        """Should find swing lows as support"""
        lows = [100, 99, 98, 95, 98, 99, 100, 101, 102, 103,
                102, 101, 100, 96, 100, 101, 102, 103, 104, 105] * 5
        supports = analyzer._find_support_levels(lows)
        assert isinstance(supports, list)
        
    def test_find_resistance_levels(self, analyzer):
        """Should find swing highs as resistance"""
        highs = [100, 101, 102, 105, 102, 101, 100, 99, 98, 97,
                 98, 99, 100, 104, 100, 99, 98, 97, 96, 95] * 5
        resistances = analyzer._find_resistance_levels(highs)
        assert isinstance(resistances, list)


class TestFibonacciLevels:
    """Tests for Fibonacci calculation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_fibonacci_levels_correct(self, analyzer):
        """Fibonacci levels should be calculated correctly"""
        high = 100
        low = 80
        fib = analyzer._calculate_fibonacci(high, low)
        
        assert fib['0.0%'] == 100
        assert fib['100.0%'] == 80
        assert fib['50.0%'] == 90
        assert abs(fib['38.2%'] - 92.36) < 0.1
        assert abs(fib['61.8%'] - 87.64) < 0.1


class TestPullbackScoring:
    """Tests for pullback scoring"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_rsi_score_extreme_oversold(self, analyzer):
        """RSI < 30 should give 3 points"""
        score, reason = analyzer._score_rsi(25.0)
        assert score == 3
        assert "extreme" in reason.lower() or "25" in reason
        
    def test_rsi_score_oversold(self, analyzer):
        """RSI 30-40 should give 2 points"""
        score, reason = analyzer._score_rsi(35.0)
        assert score == 2
        
    def test_rsi_score_neutral(self, analyzer):
        """RSI 40-50 should give 1 point"""
        score, reason = analyzer._score_rsi(45.0)
        assert score == 1
        
    def test_rsi_score_not_oversold(self, analyzer):
        """RSI >= 50 should give 0 points"""
        score, reason = analyzer._score_rsi(55.0)
        assert score == 0
        
    def test_ma_score_dip_in_uptrend(self, analyzer):
        """Price > SMA200 but < SMA20 should give 2 points"""
        price = 105
        sma_20 = 110
        sma_200 = 100
        
        score, reason = analyzer._score_moving_averages(price, sma_20, sma_200)
        
        assert score == 2
        assert "dip" in reason.lower() or "uptrend" in reason.lower()
        
    def test_ma_score_no_uptrend(self, analyzer):
        """Price < SMA200 should give 0 points"""
        price = 95
        sma_20 = 100
        sma_200 = 100
        
        score, reason = analyzer._score_moving_averages(price, sma_20, sma_200)
        assert score == 0


class TestFullAnalysis:
    """Tests for full analysis using analyze_detailed()"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_analyze_detailed_returns_candidate(self, analyzer):
        """analyze_detailed() should return PullbackCandidate"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert isinstance(result, PullbackCandidate)
        assert result.symbol == "TEST"
        assert 0 <= result.score <= 10
        
    def test_analyze_detailed_includes_breakdown(self, analyzer):
        """Analysis should include score breakdown"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert result.score_breakdown is not None
        assert isinstance(result.score_breakdown, ScoreBreakdown)
        assert result.score_breakdown.total_score == result.score
        
    def test_analyze_detailed_includes_technicals(self, analyzer):
        """Analysis should include technical indicators"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert result.technicals is not None
        assert isinstance(result.technicals, TechnicalIndicators)
        assert result.technicals.rsi_14 is not None
        assert result.technicals.sma_20 is not None
        assert result.technicals.sma_200 is not None
        
    def test_analyze_raises_for_insufficient_data(self, analyzer):
        """Analysis should raise exception with insufficient data"""
        prices = [100, 101, 102]
        volumes = [1000000] * 3
        highs = [101, 102, 103]
        lows = [99, 100, 101]
        
        with pytest.raises(ValueError):
            analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
    
    def test_analyze_returns_trade_signal(self, analyzer):
        """analyze() should return TradeSignal"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert isinstance(result, TradeSignal)
        assert result.symbol == "TEST"
        assert result.strategy == "pullback"


class TestCandidateMethods:
    """Tests for PullbackCandidate methods"""
    
    def test_is_qualified_true(self):
        """is_qualified should be True when score >= min_score"""
        breakdown = ScoreBreakdown(total_score=6)
        technicals = TechnicalIndicators(
            rsi_14=35, sma_20=100, sma_50=98, sma_200=95,
            macd=None, stochastic=None,
            above_sma20=True, above_sma50=True, above_sma200=True,
            trend='uptrend'
        )
        
        candidate = PullbackCandidate(
            symbol="TEST",
            current_price=100,
            score=6,
            score_breakdown=breakdown,
            technicals=technicals,
            support_levels=[95, 90],
            resistance_levels=[105, 110],
            fib_levels={'50%': 97.5},
            avg_volume=1000000,
            current_volume=1200000
        )
        
        assert candidate.is_qualified(min_score=5) == True
        assert candidate.is_qualified(min_score=6) == True
        assert candidate.is_qualified(min_score=7) == False
        
    def test_to_dict(self):
        """to_dict should return complete dict"""
        breakdown = ScoreBreakdown(total_score=5)
        technicals = TechnicalIndicators(
            rsi_14=40, sma_20=100, sma_50=None, sma_200=95,
            macd=None, stochastic=None,
            above_sma20=False, above_sma50=None, above_sma200=True,
            trend='sideways'
        )
        
        candidate = PullbackCandidate(
            symbol="AAPL",
            current_price=175.50,
            score=5,
            score_breakdown=breakdown,
            technicals=technicals,
            support_levels=[170, 165],
            resistance_levels=[180, 185],
            fib_levels={'38.2%': 172, '50%': 170},
            avg_volume=50000000,
            current_volume=55000000
        )
        
        d = candidate.to_dict()
        
        assert d['symbol'] == "AAPL"
        assert d['price'] == 175.50
        assert d['score'] == 5
        assert 'technicals' in d
        assert 'support_levels' in d
        assert 'score_breakdown' in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
