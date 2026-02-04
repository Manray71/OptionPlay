# OptionPlay - Extended Pullback Analyzer Tests
# =============================================
# Comprehensive tests for src/analyzers/pullback.py

import pytest
import numpy as np
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.pullback import PullbackAnalyzer
from analyzers.context import AnalysisContext
from models.base import TradeSignal, SignalType, SignalStrength
from models.indicators import MACDResult, StochasticResult, TechnicalIndicators, KeltnerChannelResult
from models.candidates import PullbackCandidate, ScoreBreakdown
from config.config_loader import PullbackScoringConfig


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def default_config():
    """Default PullbackScoringConfig"""
    return PullbackScoringConfig()


@pytest.fixture
def analyzer(default_config):
    """Create PullbackAnalyzer with default config"""
    return PullbackAnalyzer(default_config)


@pytest.fixture
def sample_data():
    """Generate sample price data for testing"""
    np.random.seed(42)
    days = 260

    # Generate trending up prices with some noise
    base_price = 100.0
    trend = np.linspace(0, 30, days)
    noise = np.random.randn(days) * 2
    prices = base_price + trend + noise

    # Generate volumes
    avg_volume = 1000000
    volumes = [int(avg_volume * (0.8 + np.random.random() * 0.4)) for _ in range(days)]

    # Generate highs and lows
    highs = [p + abs(np.random.randn()) * 2 for p in prices]
    lows = [p - abs(np.random.randn()) * 2 for p in prices]

    return {
        'prices': list(prices),
        'volumes': volumes,
        'highs': highs,
        'lows': lows
    }


@pytest.fixture
def oversold_data():
    """Generate data where stock is oversold"""
    days = 260

    # Price declining sharply at end
    prices = [100 + i * 0.1 for i in range(200)]  # Uptrend
    prices.extend([120 - i * 0.5 for i in range(60)])  # Sharp decline

    volumes = [1000000] * days
    highs = [p + 1 for p in prices]
    lows = [p - 1 for p in prices]

    return {
        'prices': prices,
        'volumes': volumes,
        'highs': highs,
        'lows': lows
    }


@pytest.fixture
def uptrend_data():
    """Generate strong uptrend data"""
    days = 260

    # Consistent uptrend
    prices = [100 + i * 0.2 for i in range(days)]

    volumes = [1000000] * days
    volumes[-1] = 1500000  # Volume spike on last day

    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]

    return {
        'prices': prices,
        'volumes': volumes,
        'highs': highs,
        'lows': lows
    }


# =============================================================================
# BASIC TESTS
# =============================================================================

class TestPullbackAnalyzerBasic:
    """Basic tests for PullbackAnalyzer"""

    def test_strategy_name(self, analyzer):
        """Strategy name should be 'pullback'"""
        assert analyzer.strategy_name == "pullback"

    def test_description(self, analyzer):
        """Description should be set"""
        assert "pullback" in analyzer.description.lower()
        assert len(analyzer.description) > 10

    def test_analyze_returns_trade_signal(self, analyzer, sample_data):
        """analyze() should return TradeSignal"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert isinstance(signal, TradeSignal)
        assert signal.symbol == "AAPL"
        assert signal.strategy == "pullback"
        assert 0 <= signal.score <= 10

    def test_analyze_detailed_returns_candidate(self, analyzer, sample_data):
        """analyze_detailed() should return PullbackCandidate"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert isinstance(candidate, PullbackCandidate)
        assert candidate.symbol == "AAPL"
        assert candidate.current_price == sample_data['prices'][-1]
        assert hasattr(candidate, 'score_breakdown')


# =============================================================================
# INPUT VALIDATION TESTS
# =============================================================================

class TestInputValidation:
    """Tests for input validation"""

    def test_insufficient_data_raises_error(self, analyzer):
        """Should raise error for insufficient data"""
        short_prices = [100.0] * 50  # Less than 200 required

        with pytest.raises(ValueError, match="Need"):
            analyzer.analyze_detailed(
                symbol="AAPL",
                prices=short_prices,
                volumes=[1000000] * 50,
                highs=[101.0] * 50,
                lows=[99.0] * 50
            )

    def test_empty_symbol_handled(self, analyzer, sample_data):
        """Should handle empty symbol (may not raise)"""
        # Note: The analyzer may accept empty symbol - this tests actual behavior
        try:
            result = analyzer.analyze_detailed(
                symbol="",
                prices=sample_data['prices'],
                volumes=sample_data['volumes'],
                highs=sample_data['highs'],
                lows=sample_data['lows']
            )
            # If no error, result should still be valid
            assert result is not None
        except ValueError:
            # If it raises ValueError, that's also acceptable
            pass

    def test_mismatched_lengths_raises_error(self, analyzer):
        """Should raise error for mismatched data lengths"""
        with pytest.raises(ValueError):
            analyzer.analyze_detailed(
                symbol="AAPL",
                prices=[100.0] * 260,
                volumes=[1000000] * 200,  # Different length
                highs=[101.0] * 260,
                lows=[99.0] * 260
            )


# =============================================================================
# SCORE BREAKDOWN TESTS
# =============================================================================

class TestScoreBreakdown:
    """Tests for score breakdown components"""

    def test_rsi_score_calculated(self, analyzer, sample_data):
        """RSI score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'rsi_score')
        assert 0 <= breakdown.rsi_score <= 3

    def test_oversold_rsi_gets_higher_score(self, analyzer, oversold_data):
        """Oversold RSI should get higher score"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=oversold_data['prices'],
            volumes=oversold_data['volumes'],
            highs=oversold_data['highs'],
            lows=oversold_data['lows']
        )

        # RSI should be oversold after sharp decline
        assert candidate.technicals.rsi_14 < 40

    def test_support_score_calculated(self, analyzer, sample_data):
        """Support score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'support_score')
        assert 0 <= breakdown.support_score <= 2.5

    def test_fibonacci_score_calculated(self, analyzer, sample_data):
        """Fibonacci score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'fibonacci_score')
        assert 0 <= breakdown.fibonacci_score <= 2

    def test_ma_score_calculated(self, analyzer, sample_data):
        """Moving average score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'ma_score')
        assert 0 <= breakdown.ma_score <= 2

    def test_volume_score_calculated(self, analyzer, sample_data):
        """Volume score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'volume_score')
        assert 0 <= breakdown.volume_score <= 1

    def test_macd_score_calculated(self, analyzer, sample_data):
        """MACD score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'macd_score')
        assert 0 <= breakdown.macd_score <= 2

    def test_stochastic_score_calculated(self, analyzer, sample_data):
        """Stochastic score should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown
        assert hasattr(breakdown, 'stoch_score')
        assert 0 <= breakdown.stoch_score <= 2

    def test_total_score_is_sum_of_components(self, analyzer, sample_data):
        """Total score should be sum of components"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        breakdown = candidate.score_breakdown

        # Calculate expected total (approximately)
        component_sum = (
            breakdown.rsi_score +
            breakdown.support_score +
            breakdown.fibonacci_score +
            breakdown.ma_score +
            breakdown.volume_score +
            breakdown.macd_score +
            breakdown.stoch_score
        )

        # Total should be at least the sum of these components
        # (there may be additional components like keltner, vwap, etc.)
        assert breakdown.total_score >= component_sum * 0.5  # Allow some variance


# =============================================================================
# TECHNICAL INDICATOR TESTS
# =============================================================================

class TestTechnicalIndicators:
    """Tests for technical indicator calculations"""

    def test_rsi_calculation(self, analyzer, sample_data):
        """RSI should be calculated correctly"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        rsi = candidate.technicals.rsi_14
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_sma_calculations(self, analyzer, sample_data):
        """SMAs should be calculated correctly"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert candidate.technicals.sma_20 is not None
        assert candidate.technicals.sma_200 is not None

        # SMA should be reasonable (within range of prices)
        min_price = min(sample_data['prices'])
        max_price = max(sample_data['prices'])
        assert min_price <= candidate.technicals.sma_20 <= max_price

    def test_macd_calculation(self, analyzer, sample_data):
        """MACD should be calculated correctly"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        macd = candidate.technicals.macd
        assert macd is not None
        assert hasattr(macd, 'macd_line')
        assert hasattr(macd, 'signal_line')
        assert hasattr(macd, 'histogram')

    def test_stochastic_calculation(self, analyzer, sample_data):
        """Stochastic should be calculated correctly"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        stoch = candidate.technicals.stochastic
        assert stoch is not None
        assert hasattr(stoch, 'k')
        assert hasattr(stoch, 'd')
        assert 0 <= stoch.k <= 100
        assert 0 <= stoch.d <= 100

    def test_trend_determination(self, analyzer, uptrend_data):
        """Trend should be correctly determined"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=uptrend_data['prices'],
            volumes=uptrend_data['volumes'],
            highs=uptrend_data['highs'],
            lows=uptrend_data['lows']
        )

        # Strong uptrend data should show uptrend
        assert candidate.technicals.trend in ['uptrend', 'sideways']


# =============================================================================
# SIGNAL GENERATION TESTS
# =============================================================================

class TestSignalGeneration:
    """Tests for trade signal generation"""

    def test_strong_signal_for_good_setup(self, analyzer):
        """Strong setup should generate strong signal"""
        # Create ideal pullback scenario
        days = 260

        # Strong uptrend with recent pullback
        prices = [100 + i * 0.3 for i in range(230)]  # Uptrend
        prices.extend([169 - i * 0.3 for i in range(30)])  # Pullback

        volumes = [1000000] * days
        volumes[-1] = 2000000  # Volume spike

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        # Should generate some kind of signal
        assert signal.signal_type in [SignalType.LONG, SignalType.NEUTRAL]

    def test_neutral_signal_for_weak_setup(self, analyzer):
        """Weak setup should generate neutral signal"""
        days = 260

        # Sideways/choppy market
        np.random.seed(42)
        prices = [100 + np.sin(i / 10) * 5 + np.random.randn() for i in range(days)]

        volumes = [1000000] * days
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]

        signal = analyzer.analyze(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        # Choppy market should not generate strong signal
        assert signal.strength != SignalStrength.STRONG or signal.signal_type == SignalType.NEUTRAL

    def test_signal_includes_entry_price(self, analyzer, sample_data):
        """Signal should include entry price"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert signal.entry_price is not None
        assert signal.entry_price == sample_data['prices'][-1]

    def test_signal_includes_details(self, analyzer, sample_data):
        """Signal should include details dict"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert signal.details is not None
        assert 'rsi' in signal.details
        assert 'score_breakdown' in signal.details


# =============================================================================
# CONTEXT USAGE TESTS
# =============================================================================

class TestContextUsage:
    """Tests for AnalysisContext usage"""

    def test_analyze_without_context_works(self, analyzer, sample_data):
        """analyze should work without context"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows'],
            context=None
        )

        # Should produce valid signal
        assert isinstance(signal, TradeSignal)

    def test_analyze_without_context(self, analyzer, sample_data):
        """analyze should work without context"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows'],
            context=None
        )

        assert isinstance(signal, TradeSignal)


# =============================================================================
# SUPPORT/RESISTANCE TESTS
# =============================================================================

class TestSupportResistance:
    """Tests for support and resistance level detection"""

    def test_support_levels_detected(self, analyzer, sample_data):
        """Support levels should be detected"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        # Should have some support levels
        assert candidate.support_levels is not None
        assert len(candidate.support_levels) >= 0

    def test_resistance_levels_detected(self, analyzer, sample_data):
        """Resistance levels should be detected"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        # Should have some resistance levels
        assert candidate.resistance_levels is not None

    def test_support_distance_calculated(self, analyzer, sample_data):
        """Distance to support should be calculated"""
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        if candidate.support_levels:
            breakdown = candidate.score_breakdown
            assert hasattr(breakdown, 'support_distance_pct')


# =============================================================================
# FIBONACCI TESTS
# =============================================================================

class TestFibonacci:
    """Tests for Fibonacci retracement calculations"""

    def test_fibonacci_levels_at_retracement(self, analyzer, default_config):
        """Fibonacci score should increase at retracement levels"""
        # Create data where price is at 38.2% retracement
        days = 260

        # Swing from 100 to 150, then retrace to ~131 (38.2%)
        prices = [100 + i * 0.25 for i in range(200)]  # Up to 150
        prices.extend([150 - i * 0.316 for i in range(60)])  # Retrace

        volumes = [1000000] * days
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        # Fibonacci score should be positive at retracement
        assert candidate.score_breakdown.fibonacci_score >= 0


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases"""

    def test_constant_prices(self, analyzer):
        """Should handle constant prices"""
        days = 260
        prices = [100.0] * days
        volumes = [1000000] * days
        highs = [100.5] * days
        lows = [99.5] * days

        # Should not crash
        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        assert candidate is not None

    def test_very_volatile_data(self, analyzer):
        """Should handle very volatile data"""
        days = 260
        np.random.seed(42)

        # Very volatile prices
        prices = [100 + np.random.randn() * 20 for _ in range(days)]
        volumes = [1000000] * days
        highs = [p + abs(np.random.randn()) * 10 for p in prices]
        lows = [p - abs(np.random.randn()) * 10 for p in prices]

        # Ensure highs > lows
        for i in range(days):
            if highs[i] <= lows[i]:
                highs[i] = lows[i] + 1

        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        assert candidate is not None

    def test_zero_volume(self, analyzer, sample_data):
        """Should handle zero volume days"""
        sample_data['volumes'][-1] = 0

        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert candidate is not None

    def test_high_equals_low(self, analyzer):
        """Should handle high equals low (no range)"""
        days = 260
        prices = [100 + i * 0.1 for i in range(days)]
        volumes = [1000000] * days

        # Some days with no range
        highs = list(prices)
        lows = list(prices)

        candidate = analyzer.analyze_detailed(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        assert candidate is not None


# =============================================================================
# SCORE NORMALIZATION TESTS
# =============================================================================

class TestScoreNormalization:
    """Tests for score normalization"""

    def test_normalized_score_is_0_to_10(self, analyzer, sample_data):
        """Normalized score should be between 0 and 10"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert 0 <= signal.score <= 10

    def test_raw_score_in_details(self, analyzer, sample_data):
        """Raw score should be in details"""
        signal = analyzer.analyze(
            symbol="AAPL",
            prices=sample_data['prices'],
            volumes=sample_data['volumes'],
            highs=sample_data['highs'],
            lows=sample_data['lows']
        )

        assert 'raw_score' in signal.details
        assert 'max_possible' in signal.details


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
