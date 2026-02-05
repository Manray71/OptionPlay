# OptionPlay - Earnings Dip Analyzer Tests
# ==========================================
# Comprehensive unit tests for EarningsDipAnalyzer
#
# Test Coverage:
# 1. EarningsDipAnalyzer initialization
# 2. analyze method
# 3. detect_earnings_dip method
# 4. Price drop detection
# 5. Score calculation
# 6. Edge cases

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig, GapInfo
from models.base import SignalType, SignalStrength
from models.indicators import MACDResult, StochasticResult, KeltnerChannelResult
from config.config_loader import EarningsDipScoringConfig


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def analyzer():
    """Default analyzer instance"""
    return EarningsDipAnalyzer()


@pytest.fixture
def custom_config():
    """Custom configuration for testing"""
    return EarningsDipConfig(
        min_dip_pct=7.0,
        max_dip_pct=20.0,
        dip_lookback_days=5,
        require_above_sma200=True,
        min_market_cap=10e9,
        require_stabilization=True,
        stabilization_days=2,
        rsi_oversold_threshold=35.0,
        analyze_gap=True,
        min_gap_pct=2.0,
        gap_fill_threshold=50.0,
        stop_below_dip_low_pct=3.0,
        target_recovery_pct=50.0,
        max_score=10,
        min_score_for_signal=6,
    )


@pytest.fixture
def earnings_dip_data():
    """Generates data with earnings dip and recovery"""
    n = 100
    prices = []

    # Pre-earnings: Stable uptrend
    for i in range(90):
        prices.append(100 + i * 0.1)  # Rises to 109

    # Earnings Dip: -10%
    prices.append(99)    # Gap down Day 1
    prices.append(98.5)  # Continued selling Day 2
    prices.append(98)    # Low reached Day 3

    # Stabilization
    prices.append(98.5)  # Day 4
    prices.append(99)    # Day 5
    prices.append(99.5)  # Day 6 (current)
    prices.append(100)   # Day 7
    prices.append(100.5) # Day 8
    prices.append(101)   # Day 9
    prices.append(101.5) # Day 10

    volumes = [1000000] * n
    volumes[90:93] = [3000000, 2500000, 2000000]  # Volume spike during dip
    volumes[93:] = [1200000] * (n - 93)  # Normalizing

    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]

    # Deeper low on dip day
    lows[92] = 97.0

    return prices, volumes, highs, lows


@pytest.fixture
def ideal_dip_data():
    """Ideal dip scenario (5-10% with recovery signs)"""
    n = 100
    prices = [110.0] * 85  # Above SMA200 pre-dip

    # Clear dip: ~8%
    dip_prices = [101, 99, 97, 96, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105]
    prices.extend(dip_prices)

    volumes = [1000000] * n
    volumes[85:88] = [3000000, 2500000, 2000000]  # Volume spike
    volumes[88:] = [800000] * (n - 88)  # Volume normalizing

    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    lows[89] = 94.0  # Clear dip low

    return prices, volumes, highs, lows


@pytest.fixture
def no_dip_data():
    """Data with no significant dip"""
    n = 100
    prices = [100 + i * 0.1 for i in range(n)]  # Continuous uptrend
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


@pytest.fixture
def large_dip_data():
    """Data with excessive dip (>25%)"""
    n = 100
    prices = [100.0] * 90
    prices += [70, 68, 65, 66, 67, 68, 69, 70, 71, 72]  # ~30% dip
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


@pytest.fixture
def gap_down_data():
    """Data with clear gap down"""
    n = 100
    prices = [100.0] * 93
    highs = [101.0] * 93
    lows = [99.0] * 93

    # Gap Down: High < Previous Low
    prices.append(90.0)
    highs.append(91.0)  # High under Previous Low (99)
    lows.append(89.0)

    # Recovery
    for i in range(6):
        prices.append(90.5 + i * 0.5)
        highs.append(91.5 + i * 0.5)
        lows.append(89.5 + i * 0.5)

    volumes = [1000000] * n
    volumes[93] = 3000000

    return prices, volumes, highs, lows


# =============================================================================
# 1. INITIALIZATION TESTS
# =============================================================================

class TestEarningsDipAnalyzerInitialization:
    """Tests for EarningsDipAnalyzer initialization"""

    def test_default_initialization(self):
        """Default initialization should use default config"""
        analyzer = EarningsDipAnalyzer()

        assert analyzer.config is not None
        assert isinstance(analyzer.config, EarningsDipConfig)
        assert analyzer.scoring_config is not None
        assert isinstance(analyzer.scoring_config, EarningsDipScoringConfig)

    def test_custom_config_initialization(self, custom_config):
        """Custom config should be applied correctly"""
        analyzer = EarningsDipAnalyzer(config=custom_config)

        assert analyzer.config.min_dip_pct == 7.0
        assert analyzer.config.max_dip_pct == 20.0
        assert analyzer.config.rsi_oversold_threshold == 35.0
        assert analyzer.config.min_gap_pct == 2.0

    def test_custom_scoring_config_initialization(self):
        """Custom scoring config should be applied"""
        scoring_config = EarningsDipScoringConfig()
        scoring_config.rsi_extreme_oversold = 20
        scoring_config.rsi_oversold = 30

        analyzer = EarningsDipAnalyzer(scoring_config=scoring_config)

        assert analyzer.scoring_config.rsi_extreme_oversold == 20
        assert analyzer.scoring_config.rsi_oversold == 30

    def test_both_configs_initialization(self, custom_config):
        """Both configs can be provided"""
        scoring_config = EarningsDipScoringConfig()
        analyzer = EarningsDipAnalyzer(config=custom_config, scoring_config=scoring_config)

        assert analyzer.config.min_dip_pct == 7.0
        assert analyzer.scoring_config is not None

    def test_strategy_name_property(self, analyzer):
        """Strategy name should be 'earnings_dip'"""
        assert analyzer.strategy_name == "earnings_dip"

    def test_description_property(self, analyzer):
        """Description should be set"""
        assert "Earnings Dip" in analyzer.description
        assert len(analyzer.description) > 0


# =============================================================================
# 2. ANALYZE METHOD TESTS
# =============================================================================

class TestAnalyzeMethod:
    """Tests for the main analyze method"""

    def test_analyze_returns_trade_signal(self, analyzer, earnings_dip_data):
        """analyze should return a TradeSignal"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        assert signal is not None
        assert signal.symbol == "TEST"
        assert signal.strategy == "earnings_dip"
        assert hasattr(signal, 'signal_type')
        assert hasattr(signal, 'score')

    def test_analyze_with_earnings_date(self, analyzer, earnings_dip_data):
        """analyze should accept earnings_date parameter"""
        prices, volumes, highs, lows = earnings_dip_data
        earnings_date = date.today() - timedelta(days=5)

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            earnings_date=earnings_date,
            pre_earnings_price=109.0
        )

        assert signal is not None
        assert 'earnings_date' in signal.details.get('dip_info', {})

    def test_analyze_with_context(self, analyzer, earnings_dip_data):
        """analyze should accept context parameter"""
        prices, volumes, highs, lows = earnings_dip_data

        # Create mock context
        context = Mock()
        context.spy_prices = [100 + i * 0.1 for i in range(100)]
        context.vix = 15.0

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0,
            context=context
        )

        assert signal is not None

    def test_analyze_detects_dip(self, analyzer, earnings_dip_data):
        """analyze should detect earnings dip"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        assert "Dip" in signal.reason or signal.score > 0

    def test_analyze_no_signal_without_dip(self, analyzer, no_dip_data):
        """analyze should return neutral signal without dip"""
        prices, volumes, highs, lows = no_dip_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.score < 5

    def test_analyze_rejects_large_dip(self, analyzer, large_dip_data):
        """analyze should reject too large dips"""
        prices, volumes, highs, lows = large_dip_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert signal.signal_type == SignalType.NEUTRAL
        assert "too large" in signal.reason.lower() or "too risky" in signal.reason.lower()

    def test_analyze_includes_breakdown(self, analyzer, earnings_dip_data):
        """analyze should include score breakdown in details"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        assert 'score_breakdown' in signal.details
        assert 'components' in signal.details['score_breakdown']

    def test_analyze_sets_stop_loss_and_target(self, analyzer, ideal_dip_data):
        """analyze should set stop_loss and target_price for actionable signals"""
        prices, volumes, highs, lows = ideal_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=110.0
        )

        if signal.signal_type != SignalType.NEUTRAL:
            assert signal.stop_loss is not None
            assert signal.target_price is not None
            assert signal.entry_price is not None

    def test_analyze_validates_inputs(self, analyzer):
        """analyze should validate inputs"""
        short_prices = [100] * 30
        short_volumes = [1000000] * 30
        short_highs = [101] * 30
        short_lows = [99] * 30

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", short_prices, short_volumes, short_highs, short_lows)

    def test_analyze_normalized_score(self, analyzer, earnings_dip_data):
        """analyze should return normalized score (0-10)"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        assert 0 <= signal.score <= 10


# =============================================================================
# 3. DETECT_EARNINGS_DIP METHOD TESTS
# =============================================================================

class TestDetectEarningsDip:
    """Tests for _detect_earnings_dip method"""

    def test_detects_moderate_dip(self, analyzer):
        """Should detect moderate dip (5-10%)"""
        n = 100
        prices = [100.0] * 90
        prices += [93, 92, 91, 91.5, 92, 92.5, 93, 93.5, 94, 94.5]  # ~8% Dip, Recovery

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=100.0
        )

        assert score > 0
        assert info['dip_pct'] > 5

    def test_detects_ideal_dip(self, analyzer):
        """Should give maximum score for ideal dip (5-10%)"""
        n = 100
        # Dip is calculated from CURRENT price to pre_earnings_price
        # For 7% dip: current_price = 93, pre_earnings_price = 100
        # dip_from_current = (1 - 93/100) * 100 = 7%
        prices = [100.0] * 90
        prices += [95, 94, 93, 93, 93, 93, 93, 93, 93, 93]  # current=93, ~7% below pre_earnings

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=100.0
        )

        # Ideal dip (5-10%) should get 3 points
        assert score == 3
        assert 5 <= info['dip_pct'] <= 10

    def test_moderate_dip_scoring(self, analyzer):
        """Should give 2 points for moderate dip (10-15%)"""
        n = 100
        # For 12% dip: current_price = 88, pre_earnings_price = 100
        # dip_from_current = (1 - 88/100) * 100 = 12%
        prices = [100.0] * 90
        prices += [92, 90, 88, 88, 88, 88, 88, 88, 88, 88]  # current=88, ~12% below pre_earnings

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=100.0
        )

        assert score == 2
        assert 10 < info['dip_pct'] <= 15

    def test_large_dip_scoring(self, analyzer):
        """Should give 1 point for large dip (15-25%)"""
        n = 100
        prices = [100.0] * 90
        prices += [82, 80, 78, 79, 80, 81, 82, 83, 84, 85]  # ~18% dip

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=100.0
        )

        assert score == 1
        assert 15 < info['dip_pct'] < 25

    def test_too_small_dip(self, analyzer):
        """Should reject dip smaller than min_dip_pct"""
        n = 100
        prices = [100.0] * 90
        prices += [97, 96, 95, 96, 97, 98, 99, 100, 101, 102]  # ~2% dip

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=100.0
        )

        assert score == 0
        assert "too small" in info.get('reason', '').lower()

    def test_too_large_dip(self, analyzer):
        """Should reject dip larger than max_dip_pct"""
        n = 100
        prices = [100.0] * 90
        prices += [70, 68, 65, 66, 67, 68, 69, 70, 71, 72]  # ~30% dip

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=100.0
        )

        assert score == 0
        assert "too large" in info.get('reason', '').lower() or "too risky" in info.get('reason', '').lower()

    def test_pre_earnings_price_provided(self, analyzer):
        """Should use provided pre_earnings_price"""
        n = 100
        prices = [80.0] * 90 + [75, 73, 72, 73, 74, 75, 76, 77, 78, 79]

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=85.0
        )

        assert info['pre_earnings_price'] == 85.0

    def test_pre_earnings_price_calculated(self, analyzer):
        """Should calculate pre_earnings_price if not provided"""
        n = 100
        prices = [100.0] * 85 + [95, 93, 91, 90, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99]

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=None
        )

        assert 'pre_earnings_price' in info
        assert info['pre_earnings_price'] > 0

    def test_returns_dip_info(self, analyzer, earnings_dip_data):
        """Should return detailed dip info"""
        prices, volumes, highs, lows = earnings_dip_data

        score, info = analyzer._detect_earnings_dip(
            prices, highs, lows,
            earnings_date=None,
            pre_earnings_price=109.0
        )

        assert 'dip_pct' in info
        assert 'dip_low' in info
        assert 'pre_earnings_price' in info
        assert 'current_price' in info


# =============================================================================
# 4. PRICE DROP DETECTION TESTS
# =============================================================================

class TestPriceDropDetection:
    """Tests for price drop detection components"""

    def test_gap_down_detection(self, analyzer):
        """Should detect clear gap down"""
        # Gap detection checks if highs[idx] < lows[prev_idx] within lookback=5
        # For i=1: checks highs[-1] < lows[-2]
        # Need: current_high < prev_low AND gap_pct >= 2%

        n = 100
        prices = [100.0] * (n - 2)
        highs = [101.0] * (n - 2)
        lows = [99.0] * (n - 2)

        # Day -2 (prev_idx when i=1): normal day - lows[-2] = 99
        # (Already set above)

        # Day -1 (idx when i=1): Gap day - highs[-1] = 90 < lows[-2] = 99
        # Gap = 99 - 90 = 9, gap_pct = 9/100 * 100 = 9%
        prices.append(88.0)  # close
        highs.append(90.0)   # high < prev_low (99) = GAP
        lows.append(87.0)

        # Day 0 (most recent): Recovery day
        prices.append(91.0)  # close
        highs.append(92.0)   # high
        lows.append(90.0)    # low

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        assert gap_info.detected is True
        assert gap_info.gap_size_pct > 0
        assert score > 0

    def test_no_gap_without_price_gap(self, analyzer):
        """Should not detect gap for gradual decline"""
        n = 100
        prices = [100 - i * 0.1 for i in range(n)]  # Slow decline
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        assert gap_info.detected is False
        assert score == 0

    def test_gap_fill_detection(self, analyzer):
        """Should detect gap fill"""
        n = 100
        prices = [100.0] * 96
        highs = [101.0] * 96
        lows = [99.0] * 96

        # Gap Down within 5-day lookback
        prices.append(90.0)
        highs.append(91.0)  # Gap: High (91) < Previous Low (99)
        lows.append(89.0)

        # Recovery
        prices.append(92.0)
        highs.append(93.0)
        lows.append(91.0)

        prices.append(94.0)
        highs.append(95.0)
        lows.append(93.0)

        prices.append(96.0)
        highs.append(98.0)  # Approaching Previous Low
        lows.append(95.0)

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        assert gap_info.detected is True
        assert gap_info.fill_pct > 0

    def test_gap_info_dataclass(self):
        """GapInfo dataclass should work correctly"""
        gap = GapInfo(
            detected=True,
            gap_day_index=2,
            gap_size_pct=5.5,
            gap_open=95.0,
            prev_close=100.0,
            gap_filled=False,
            fill_pct=25.0
        )

        assert gap.detected is True
        assert gap.gap_size_pct == 5.5

        d = gap.to_dict()
        assert d['detected'] is True
        assert d['gap_size_pct'] == 5.5
        assert d['fill_pct'] == 25.0

    def test_gap_minimum_size_config(self):
        """Gap detection should respect minimum size config"""
        config = EarningsDipConfig(min_gap_pct=5.0)
        analyzer = EarningsDipAnalyzer(config)

        n = 100
        prices = [100.0] * 95
        highs = [101.0] * 95
        lows = [99.0] * 95

        # Small gap (~2%)
        prices.append(97.0)
        highs.append(98.0)
        lows.append(96.0)

        for i in range(4):
            prices.append(97.5 + i * 0.5)
            highs.append(98.5 + i * 0.5)
            lows.append(97.0 + i * 0.5)

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        # Gap too small for 5% minimum
        assert gap_info.detected is False or gap_info.gap_size_pct < 5.0


# =============================================================================
# 5. SCORE CALCULATION TESTS
# =============================================================================

class TestScoreCalculation:
    """Tests for score calculation components"""

    def test_rsi_oversold_scoring(self, analyzer):
        """Should score RSI correctly"""
        # Strongly falling prices -> low RSI
        prices = [100 - i * 0.5 for i in range(50)]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert rsi < 40
        assert score >= 1

    def test_rsi_extreme_oversold(self, analyzer):
        """Should give max score for extreme oversold"""
        # Very strongly falling prices
        prices = [100 - i for i in range(50)]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert rsi < 30
        assert score == 2

    def test_rsi_neutral(self, analyzer):
        """Should give 0 for neutral RSI"""
        # Sideways prices
        prices = [100 + (i % 2) * 0.5 for i in range(50)]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert score == 0

    def test_stabilization_scoring(self, analyzer):
        """Should score stabilization correctly"""
        lows = [100] * 90
        lows += [92, 91, 90, 91, 92, 93, 94, 95, 96, 97]  # Low at 90, then higher

        score, info = analyzer._score_stabilization(lows)

        assert info['days_without_new_low'] >= 2
        assert score >= 1

    def test_no_stabilization(self, analyzer):
        """Should give 0 for continued decline"""
        lows = [100] * 90
        lows += [95, 94, 93, 92, 91, 90, 89, 88, 87, 86]  # Continuous new lows

        score, info = analyzer._score_stabilization(lows)

        assert score == 0 or info['days_without_new_low'] < 2

    def test_volume_normalization_scoring(self, analyzer):
        """Should score volume normalization correctly"""
        volumes = [1000000] * 85
        volumes += [3000000, 2500000, 2000000]  # Volume spike
        volumes += [1200000] * 12  # Normalizing

        score, info = analyzer._score_volume_normalization(volumes)

        assert 'trend' in info
        assert 'multiplier' in info

    def test_long_term_trend_scoring(self, analyzer):
        """Should score long-term trend correctly"""
        # Uptrend data
        prices = [100 + i * 0.2 for i in range(200)]

        score, info = analyzer._score_long_term_trend(prices)

        assert 'sma_200' in info
        assert 'was_in_uptrend' in info

    def test_total_score_calculation(self, analyzer, earnings_dip_data):
        """Total score should be sum of all components"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details['score_breakdown']
        components = breakdown['components']

        # Sum all component scores (excluding new features if not present)
        base_components = [
            'dip', 'gap', 'rsi', 'stabilization', 'volume',
            'trend', 'macd', 'stochastic', 'keltner'
        ]
        expected_total = sum(
            components.get(c, {}).get('score', 0)
            for c in base_components
        )

        # Add feature engineering scores
        for feature in ['vwap', 'market_context', 'sector']:
            if feature in components:
                expected_total += components[feature].get('score', 0)

        assert abs(breakdown['total_score'] - expected_total) < 0.01

    def test_max_possible_score(self, analyzer, earnings_dip_data):
        """Max possible should be 24"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details['score_breakdown']
        assert breakdown['max_possible'] == 24

    def test_signal_strength_determination(self, analyzer):
        """Should determine signal strength based on score"""
        # This tests the internal logic
        n = 100
        prices = [110.0] * 85

        # Create optimal dip scenario
        dip_prices = [99, 97, 95, 94, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103]
        prices.extend(dip_prices)

        volumes = [1000000] * n
        volumes[85:88] = [3000000, 2500000, 2000000]
        volumes[88:] = [800000] * (n - 88)

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[89] = 92.0

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=110.0
        )

        # Strength should match score thresholds
        if signal.score >= 7:
            assert signal.strength == SignalStrength.STRONG
        elif signal.score >= 5:
            assert signal.strength == SignalStrength.MODERATE
        elif signal.score >= 3:
            assert signal.strength == SignalStrength.WEAK
        else:
            assert signal.strength == SignalStrength.NONE


# =============================================================================
# 6. EDGE CASES TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_insufficient_data(self, analyzer):
        """Should raise ValueError for insufficient data"""
        prices = [100] * 30
        volumes = [1000000] * 30
        highs = [101] * 30
        lows = [99] * 30

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_mismatched_array_lengths(self, analyzer):
        """Should raise ValueError for mismatched array lengths"""
        prices = [100] * 100
        volumes = [1000000] * 99  # Wrong length
        highs = [101] * 100
        lows = [99] * 100

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_negative_prices(self, analyzer):
        """Should raise ValueError for negative prices"""
        prices = [100] * 50 + [-5] + [100] * 49
        volumes = [1000000] * 100
        highs = [101] * 100
        lows = [99] * 100

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_high_less_than_low(self, analyzer):
        """Should raise ValueError when high < low"""
        prices = [100] * 100
        volumes = [1000000] * 100
        highs = [99] * 100  # Wrong - lower than lows
        lows = [101] * 100

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_empty_arrays(self, analyzer):
        """Should raise ValueError for empty arrays"""
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", [], [], [], [])

    def test_warning_for_large_dip(self, analyzer):
        """Large dip should generate warning"""
        n = 100
        prices = [100.0] * 90
        prices += [82, 80, 78, 79, 80, 81, 82, 83, 84, 85]  # ~18% Dip

        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        # Either warning or neutral signal
        has_warning = any("risk" in w.lower() or "large" in w.lower() or "groß" in w.lower()
                         for w in signal.warnings)
        assert has_warning or signal.signal_type == SignalType.NEUTRAL

    def test_symbol_length_limit(self, analyzer, earnings_dip_data):
        """Should handle various symbol lengths"""
        prices, volumes, highs, lows = earnings_dip_data

        # Short symbol
        signal = analyzer.analyze("A", prices, volumes, highs, lows)
        assert signal.symbol == "A"

        # Long symbol (max is typically 10)
        signal = analyzer.analyze("GOOGL", prices, volumes, highs, lows)
        assert signal.symbol == "GOOGL"

    def test_very_small_prices(self, analyzer):
        """Should handle very small stock prices"""
        n = 100
        prices = [1.0] * 90 + [0.92, 0.90, 0.88, 0.89, 0.90, 0.91, 0.92, 0.93, 0.94, 0.95]
        volumes = [10000000] * n  # Penny stocks have high volume
        highs = [p + 0.01 for p in prices]
        lows = [p - 0.01 for p in prices]

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal is not None

    def test_very_large_prices(self, analyzer):
        """Should handle very large stock prices"""
        n = 100
        prices = [5000.0] * 90 + [4600, 4500, 4400, 4450, 4500, 4550, 4600, 4650, 4700, 4750]
        volumes = [100000] * n
        highs = [p + 50 for p in prices]
        lows = [p - 50 for p in prices]

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal is not None


# =============================================================================
# MACD RECOVERY SCORING TESTS
# =============================================================================

class TestMACDRecoveryScoring:
    """Tests for MACD Recovery scoring"""

    def test_macd_score_bullish_cross(self, analyzer):
        """Bullish crossover should give 2 points"""
        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover='bullish'
        )

        prices = [100] * 50

        score, reason, signal, turning = analyzer._score_macd_recovery(macd, prices)

        assert score == 2
        assert signal == "bullish_cross"
        assert "bullish" in reason.lower() or "recovery" in reason.lower()

    def test_macd_score_histogram_positive(self, analyzer):
        """Positive histogram should give 1 point"""
        macd = MACDResult(
            macd_line=0.2,
            signal_line=0.1,
            histogram=0.1,
            crossover=None
        )

        prices = [100] * 50

        score, reason, signal, turning = analyzer._score_macd_recovery(macd, prices)

        assert score == 1
        assert signal == "bullish"

    def test_macd_score_bearish(self, analyzer):
        """Negative histogram should give 0 points"""
        macd = MACDResult(
            macd_line=-0.5,
            signal_line=-0.3,
            histogram=-0.2,
            crossover=None
        )

        prices = [100] * 50

        score, reason, signal, turning = analyzer._score_macd_recovery(macd, prices)

        assert score == 0
        assert signal == "bearish"

    def test_macd_score_none(self, analyzer):
        """No MACD data should give 0 points"""
        prices = [100] * 50

        score, reason, signal, turning = analyzer._score_macd_recovery(None, prices)

        assert score == 0
        assert signal == "neutral"
        assert turning is False

    def test_macd_calculation(self, analyzer):
        """MACD should be calculated correctly"""
        n = 50
        prices = [100 + i * 0.5 for i in range(n)]

        result = analyzer._calculate_macd(prices)

        assert result is not None
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'histogram')

    def test_macd_turning_up_detection(self, analyzer):
        """Should detect MACD histogram turning up"""
        macd = MACDResult(
            macd_line=-0.1,
            signal_line=-0.2,
            histogram=-0.1,  # Less negative than before
            crossover=None
        )

        # Create prices where previous MACD histogram would be more negative
        prices = [100 - i * 0.5 for i in range(30)] + [80 + i * 0.2 for i in range(20)]

        score, reason, signal, turning = analyzer._score_macd_recovery(macd, prices)

        # Should detect recovery signal if histogram is turning up
        assert score >= 0


# =============================================================================
# STOCHASTIC SCORING TESTS
# =============================================================================

class TestStochasticScoring:
    """Tests for Stochastic scoring"""

    def test_stoch_score_oversold_bullish_cross(self, analyzer):
        """Oversold + bullish cross should give 2 points"""
        stoch = StochasticResult(
            k=15.0,
            d=18.0,
            crossover='bullish',
            zone='oversold'
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 2
        assert signal == "oversold_bullish_cross"

    def test_stoch_score_oversold_only(self, analyzer):
        """Oversold without cross should give 1 point"""
        stoch = StochasticResult(
            k=15.0,
            d=12.0,
            crossover=None,
            zone='oversold'
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 1
        assert signal == "oversold"

    def test_stoch_score_overbought(self, analyzer):
        """Overbought should give 0 points"""
        stoch = StochasticResult(
            k=85.0,
            d=82.0,
            crossover=None,
            zone='overbought'
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "overbought"

    def test_stoch_score_neutral(self, analyzer):
        """Neutral zone should give 0 points"""
        stoch = StochasticResult(
            k=50.0,
            d=48.0,
            crossover=None,
            zone='neutral'
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "neutral"

    def test_stoch_score_none(self, analyzer):
        """No stochastic data should give 0 points"""
        score, reason, signal = analyzer._score_stochastic(None)

        assert score == 0
        assert signal == "neutral"

    def test_stoch_calculation(self, analyzer):
        """Stochastic should be calculated correctly"""
        n = 30
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_stochastic(prices, highs, lows)

        assert result is not None
        assert hasattr(result, 'k')
        assert hasattr(result, 'd')
        assert hasattr(result, 'zone')
        assert 0 <= result.k <= 100
        assert 0 <= result.d <= 100


# =============================================================================
# KELTNER CHANNEL SCORING TESTS
# =============================================================================

class TestKeltnerChannelScoring:
    """Tests for Keltner Channel scoring"""

    def test_keltner_score_below_lower(self, analyzer):
        """Price below lower band should give 2 points"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='below_lower',
            percent_position=-1.5,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 85.0)

        assert score == 2
        assert "below" in reason.lower() or "unter" in reason.lower()

    def test_keltner_score_near_lower(self, analyzer):
        """Price near lower band should give 1 point"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='near_lower',
            percent_position=-0.7,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 93.0)

        assert score == 1
        assert "near" in reason.lower() or "nahe" in reason.lower()

    def test_keltner_score_above_upper(self, analyzer):
        """Price above upper band should give 0 points"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='above_upper',
            percent_position=1.5,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 115.0)

        assert score == 0
        assert "above" in reason.lower() or "über" in reason.lower()

    def test_keltner_score_in_channel(self, analyzer):
        """Price in channel should give 0 points (neutral)"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='in_channel',
            percent_position=0.1,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 101.0)

        assert score == 0

    def test_keltner_calculation(self, analyzer):
        """Keltner Channel should be calculated correctly"""
        n = 50
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is not None
        assert result.upper > result.middle > result.lower
        assert result.atr > 0


# =============================================================================
# SCORE BREAKDOWN TESTS
# =============================================================================

class TestScoreBreakdown:
    """Tests for EarningsDipScoreBreakdown"""

    def test_breakdown_contains_all_fields(self, analyzer, earnings_dip_data):
        """Breakdown should contain all scoring fields"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details.get('score_breakdown', {})
        components = breakdown.get('components', {})

        # Core components
        assert 'dip' in components
        assert 'gap' in components
        assert 'rsi' in components
        assert 'stabilization' in components
        assert 'volume' in components
        assert 'trend' in components
        assert 'macd' in components
        assert 'stochastic' in components
        assert 'keltner' in components

    def test_breakdown_macd_fields(self, analyzer, earnings_dip_data):
        """MACD component should have correct fields"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        macd_info = signal.details['score_breakdown']['components']['macd']

        assert 'score' in macd_info
        assert 'signal' in macd_info
        assert 'histogram' in macd_info
        assert 'turning_up' in macd_info
        assert 'reason' in macd_info

    def test_breakdown_stochastic_fields(self, analyzer, earnings_dip_data):
        """Stochastic component should have correct fields"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        stoch_info = signal.details['score_breakdown']['components']['stochastic']

        assert 'score' in stoch_info
        assert 'signal' in stoch_info
        assert 'k' in stoch_info
        assert 'd' in stoch_info
        assert 'reason' in stoch_info

    def test_breakdown_keltner_fields(self, analyzer, earnings_dip_data):
        """Keltner component should have correct fields"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        keltner_info = signal.details['score_breakdown']['components']['keltner']

        assert 'score' in keltner_info
        assert 'position' in keltner_info
        assert 'percent' in keltner_info
        assert 'reason' in keltner_info


# =============================================================================
# HELPER METHODS TESTS
# =============================================================================

class TestHelperMethods:
    """Tests for helper methods"""

    def test_calculate_ema(self, analyzer):
        """EMA should be calculated correctly"""
        values = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]

        ema = analyzer._calculate_ema(values, 5)

        assert ema is not None
        assert len(ema) > 0
        assert 105 < ema[-1] < 111

    def test_calculate_ema_insufficient_data(self, analyzer):
        """EMA should return None with insufficient data"""
        values = [100, 101, 102]

        ema = analyzer._calculate_ema(values, 10)
        assert ema is None

    def test_calculate_atr(self, analyzer):
        """ATR should be calculated correctly"""
        n = 30
        highs = [102] * n
        lows = [98] * n
        closes = [100.0] * n

        atr = analyzer._calculate_atr(highs, lows, closes, 14)

        assert atr is not None
        assert 3.5 < atr < 4.5

    def test_calculate_atr_insufficient_data(self, analyzer):
        """ATR should return None with insufficient data"""
        atr = analyzer._calculate_atr([100, 101], [98, 99], [99, 100], 14)
        assert atr is None


# =============================================================================
# RISK MANAGEMENT TESTS
# =============================================================================

class TestRiskManagement:
    """Tests for risk management features"""

    def test_stop_below_dip_low(self, analyzer):
        """Stop loss should be below dip low"""
        n = 100
        prices = [100.0] * 90
        prices += [92, 90, 88, 89, 90, 91, 92, 93, 94, 95]

        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 1 for p in prices]
        lows[92] = 86  # Clear dip low

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.stop_loss:
            dip_low = signal.details.get('dip_info', {}).get('dip_low', min(lows[-10:]))
            assert signal.stop_loss < dip_low

    def test_target_is_partial_recovery(self, analyzer):
        """Target should be partial recovery"""
        n = 100
        pre_price = 100.0
        current = 92.0

        prices = [pre_price] * 90
        prices += [93, 91, 90, 91, 92, 92, 92, 92, 92, current]

        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=pre_price
        )

        if signal.target_price:
            assert current < signal.target_price < pre_price


# =============================================================================
# FEATURE ENGINEERING INTEGRATION TESTS
# =============================================================================

class TestFeatureEngineeringIntegration:
    """Tests for feature engineering mixin integration"""

    def test_applies_feature_scores(self, analyzer, earnings_dip_data):
        """Should apply feature engineering scores"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details['score_breakdown']
        components = breakdown.get('components', {})

        # Feature engineering components should be present
        assert 'vwap' in components
        assert 'market_context' in components
        assert 'sector' in components

    def test_vwap_score_fields(self, analyzer, earnings_dip_data):
        """VWAP component should have correct fields"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        components = signal.details['score_breakdown']['components']
        vwap_info = components.get('vwap', {})

        if vwap_info:
            assert 'score' in vwap_info
            assert 'value' in vwap_info
            assert 'distance_pct' in vwap_info
            assert 'position' in vwap_info

    @patch('analyzers.feature_scoring_mixin.get_sector')
    def test_sector_score_applied(self, mock_get_sector, analyzer, earnings_dip_data):
        """Should apply sector score"""
        mock_get_sector.return_value = "Technology"

        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "AAPL", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        components = signal.details['score_breakdown']['components']
        sector_info = components.get('sector', {})

        if sector_info:
            assert 'score' in sector_info
            assert 'name' in sector_info


# =============================================================================
# SIGNAL OUTPUT TESTS
# =============================================================================

class TestSignalOutput:
    """Tests for signal output formatting"""

    def test_gap_reason_included(self, analyzer, gap_down_data):
        """Gap should appear in reason if detected"""
        prices, volumes, highs, lows = gap_down_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )

        # If gap scored, should be in reason
        gap_score = signal.details.get('score_breakdown', {}).get('components', {}).get('gap', {}).get('score', 0)
        if gap_score > 0:
            assert "Gap" in signal.reason

    def test_gap_info_in_details(self, analyzer, gap_down_data):
        """Gap info should be in signal details"""
        prices, volumes, highs, lows = gap_down_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )

        gap_info = signal.details.get('gap_info')
        if gap_info:
            assert 'detected' in gap_info
            assert 'gap_size_pct' in gap_info

    def test_dip_info_in_details(self, analyzer, earnings_dip_data):
        """Dip info should be in signal details"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        assert 'dip_info' in signal.details
        dip_info = signal.details['dip_info']
        assert 'dip_pct' in dip_info
        assert 'dip_low' in dip_info

    def test_raw_score_in_details(self, analyzer, earnings_dip_data):
        """Raw score should be in details"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        assert 'raw_score' in signal.details
        assert 'max_possible' in signal.details


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestConfigurationBehavior:
    """Tests for configuration behavior"""

    def test_larger_min_dip_fewer_signals(self):
        """Larger min_dip should give fewer signals"""
        n = 100
        # Moderate dip of ~2.5%
        prices = [100.0] * 90
        prices += [97, 95, 94, 94.5, 95, 95.5, 96, 96.5, 97, 97.5]

        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[92] = 93.5

        # Strict config (min 10%)
        strict = EarningsDipAnalyzer(EarningsDipConfig(min_dip_pct=10.0))
        signal_strict = strict.analyze("TEST", prices, volumes, highs, lows)

        # Dip is < 10%, should be NEUTRAL
        assert signal_strict.signal_type == SignalType.NEUTRAL

    def test_smaller_max_dip_rejects_large_dips(self):
        """Smaller max_dip should reject large dips"""
        n = 100
        # Large dip of ~18%
        prices = [100.0] * 90
        prices += [82, 80, 78, 79, 80, 81, 82, 83, 84, 85]

        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        # Strict config (max 15%)
        strict = EarningsDipAnalyzer(EarningsDipConfig(max_dip_pct=15.0))
        signal_strict = strict.analyze("TEST", prices, volumes, highs, lows)

        # Dip is > 15%, should be NEUTRAL
        assert signal_strict.signal_type == SignalType.NEUTRAL

    def test_gap_analysis_disabled(self):
        """Gap analysis can be disabled"""
        config = EarningsDipConfig(analyze_gap=False)
        analyzer = EarningsDipAnalyzer(config)

        n = 100
        prices = [100.0] * 93
        highs = [101.0] * 93
        lows = [99.0] * 93

        # Add gap
        prices.append(88.0)
        highs.append(89.0)
        lows.append(87.0)

        for i in range(6):
            prices.append(88.5 + i * 0.5)
            highs.append(89.5 + i * 0.5)
            lows.append(87.5 + i * 0.5)

        volumes = [1000000] * n
        volumes[93] = 4000000

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )

        # Gap should not add a warning when disabled
        gap_warnings = [w for w in signal.warnings if "gap" in w.lower()]
        # With analyze_gap=False, we should not get "no gap" warnings
        assert all("no gap" not in w.lower() for w in gap_warnings) or len(gap_warnings) == 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for the analyzer"""

    def test_full_analysis_workflow(self, analyzer, ideal_dip_data):
        """Test complete analysis workflow"""
        prices, volumes, highs, lows = ideal_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=110.0
        )

        # Should have all required attributes
        assert signal.symbol == "TEST"
        assert signal.strategy == "earnings_dip"
        assert signal.signal_type in [SignalType.LONG, SignalType.NEUTRAL]
        assert signal.strength in [SignalStrength.STRONG, SignalStrength.MODERATE, SignalStrength.WEAK, SignalStrength.NONE]
        assert 0 <= signal.score <= 10
        assert signal.current_price > 0
        assert signal.details is not None

    def test_to_dict_output(self, analyzer, earnings_dip_data):
        """Signal to_dict should produce valid output"""
        prices, volumes, highs, lows = earnings_dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        signal_dict = signal.to_dict()

        assert 'symbol' in signal_dict
        assert 'strategy' in signal_dict
        assert 'score' in signal_dict
        assert 'signal_type' in signal_dict
        assert 'details' in signal_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
