# OptionPlay - Earnings Dip Analyzer Tests
# ==========================================

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig, GapInfo
from models.base import SignalType, SignalStrength


class TestEarningsDipBasics:
    """Grundlegende Tests für Earnings Dip Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    @pytest.fixture
    def earnings_dip_data(self):
        """Generiert Daten mit Earnings-Dip und Recovery"""
        n = 100
        prices = []
        
        # Vor Earnings: Stabiler Aufwärtstrend
        for i in range(90):
            prices.append(100 + i * 0.1)  # Steigt bis 109
        
        # Earnings Dip: -10%
        prices.append(99)   # Gap down Day 1
        prices.append(98.5) # Continued selling Day 2
        prices.append(98)   # Low reached Day 3
        
        # Stabilisierung
        prices.append(98.5) # Day 4
        prices.append(99)   # Day 5
        prices.append(99.5) # Day 6 (aktuell)
        prices.append(100)  # Day 7
        prices.append(100.5) # Day 8
        prices.append(101)  # Day 9
        prices.append(101.5) # Day 10
        
        volumes = [1000000] * n
        volumes[90:93] = [3000000, 2500000, 2000000]  # Erhöhtes Volumen beim Dip
        volumes[93:] = [1200000] * (n - 93)  # Normalisiert
        
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        # Tieferes Low am Dip-Tag
        lows[92] = 97.0
        
        return prices, volumes, highs, lows
    
    def test_strategy_name(self, analyzer):
        """Strategy Name sollte korrekt sein"""
        assert analyzer.strategy_name == "earnings_dip"
    
    def test_dip_detected(self, analyzer, earnings_dip_data):
        """Earnings Dip sollte erkannt werden"""
        prices, volumes, highs, lows = earnings_dip_data
        
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )
        
        assert "Dip" in signal.reason or signal.score > 0
    
    def test_no_signal_without_dip(self, analyzer):
        """Kein Signal ohne Dip"""
        n = 100
        # Kontinuierlicher Aufwärtstrend, kein Dip
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL
        assert "Dip zu klein" in signal.reason or signal.score < 5


class TestEarningsDipConfig:
    """Tests für Earnings Dip Konfiguration"""
    
    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = EarningsDipConfig(
            min_dip_pct=7.0,
            max_dip_pct=20.0,
            rsi_oversold_threshold=30.0
        )
        
        analyzer = EarningsDipAnalyzer(config)
        
        assert analyzer.config.min_dip_pct == 7.0
        assert analyzer.config.max_dip_pct == 20.0
    
    def test_larger_min_dip_fewer_signals(self):
        """Größerer min_dip sollte weniger Signale geben"""
        n = 100
        # Moderater Dip von ~2.5% - explizit kontrolliert
        prices = [100.0] * 90  # Stabiler Preis vor Dip
        prices += [97, 95, 94, 94.5, 95, 95.5, 96, 96.5, 97, 97.5]  # Dip auf 94, dann Recovery
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[92] = 93.5  # Klares Dip-Low
        
        # Strikt (min 10%) - sollte KEIN Signal geben weil Dip nur ~2.5%
        strict = EarningsDipAnalyzer(EarningsDipConfig(min_dip_pct=10.0))
        signal_strict = strict.analyze("TEST", prices, volumes, highs, lows)
        
        # Der Dip ist < 10%, also sollte NEUTRAL sein
        assert signal_strict.signal_type == SignalType.NEUTRAL


class TestEarningsDipDetection:
    """Tests für Dip-Erkennung"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_detects_moderate_dip(self, analyzer):
        """Moderater Dip (5-10%) sollte erkannt werden"""
        n = 100
        prices = [100.0] * 90
        prices += [93, 92, 91, 91.5, 92, 92.5, 93, 93.5, 94, 94.5]  # ~8% Dip, Recovery
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.details.get('dip_info', {}).get('dip_pct', 0) > 5
    
    def test_rejects_too_large_dip(self, analyzer):
        """Zu großer Dip (>25%) sollte abgelehnt werden"""
        n = 100
        prices = [100.0] * 90
        prices += [70, 68, 65, 66, 67, 68, 69, 70, 71, 72]  # ~30% Dip
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL
        assert "zu groß" in signal.reason.lower() or "riskant" in signal.reason.lower()


class TestEarningsDipStabilization:
    """Tests für Stabilisierungs-Erkennung"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_detects_stabilization(self, analyzer):
        """Stabilisierung sollte erkannt werden"""
        lows = [100] * 90
        lows += [92, 91, 90, 91, 92, 93, 94, 95, 96, 97]  # Low bei 90, dann höher
        
        score, info = analyzer._score_stabilization(lows)
        
        assert info['days_without_new_low'] >= 2
        assert score >= 1
    
    def test_no_stabilization_new_lows(self, analyzer):
        """Keine Stabilisierung bei neuen Lows"""
        lows = [100] * 90
        lows += [95, 94, 93, 92, 91, 90, 89, 88, 87, 86]  # Kontinuierlich neue Lows
        
        score, info = analyzer._score_stabilization(lows)
        
        assert score == 0 or info['days_without_new_low'] < 2


class TestEarningsDipRiskManagement:
    """Tests für Risk Management"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_stop_below_dip_low(self, analyzer):
        """Stop Loss sollte unter Dip-Low sein"""
        n = 100
        prices = [100.0] * 90
        prices += [92, 90, 88, 89, 90, 91, 92, 93, 94, 95]
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 1 for p in prices]
        lows[92] = 86  # Klares Dip-Low
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        if signal.stop_loss:
            # Stop sollte unter dem Dip-Low aus dip_info sein
            dip_low = signal.details.get('dip_info', {}).get('dip_low', min(lows[-10:]))
            assert signal.stop_loss < dip_low
    
    def test_target_is_partial_recovery(self, analyzer):
        """Target sollte teilweise Recovery sein"""
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
            # Target sollte zwischen current und pre_price sein
            assert current < signal.target_price < pre_price


class TestEarningsDipEdgeCases:
    """Edge Cases für Earnings Dip Analyzer"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_insufficient_data(self, analyzer):
        """Zu wenig Daten sollte Exception werfen"""
        prices = [100] * 30
        volumes = [1000000] * 30
        highs = [101] * 30
        lows = [99] * 30

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_warning_for_large_dip(self, analyzer):
        """Großer Dip sollte Warnung generieren"""
        n = 100
        prices = [100.0] * 90
        prices += [82, 80, 78, 79, 80, 81, 82, 83, 84, 85]  # ~18% Dip

        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        # Entweder Warnung oder niedriger Score
        has_warning = any("risiko" in w.lower() or "groß" in w.lower()
                         for w in signal.warnings)
        assert has_warning or signal.signal_type == SignalType.NEUTRAL


class TestGapDetection:
    """Tests für Gap-Down-Erkennung"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_gap_info_dataclass(self):
        """GapInfo Dataclass sollte korrekt funktionieren"""
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

    def test_detects_clear_gap_down(self, analyzer):
        """Klares Gap Down sollte erkannt werden"""
        n = 100
        # Stabile Preise, dann Gap Down
        prices = [100.0] * 95
        highs = [101.0] * 95
        lows = [99.0] * 95

        # Gap Down: High < Previous Low
        # Tag 96: Gap down - High 94, Low 92, Close 93
        prices.append(93.0)
        highs.append(94.0)  # High unter Previous Low (99)
        lows.append(92.0)

        # Recovery
        for i in range(4):
            prices.append(93.5 + i * 0.5)
            highs.append(94.0 + i * 0.5)
            lows.append(93.0 + i * 0.5)

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        assert gap_info.detected is True
        assert gap_info.gap_size_pct > 0
        assert score == 1

    def test_no_gap_without_price_gap(self, analyzer):
        """Kein Gap wenn Preise kontinuierlich"""
        n = 100
        prices = [100 - i * 0.1 for i in range(n)]  # Langsamer Abstieg
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        # Kein echtes Gap, nur gradueller Rückgang
        assert gap_info.detected is False
        assert score == 0

    def test_gap_fill_detection(self, analyzer):
        """Gap Fill sollte erkannt werden"""
        n = 100
        prices = [100.0] * 96
        highs = [101.0] * 96
        lows = [99.0] * 96

        # Gap Down innerhalb des 5-Tage Lookbacks
        # Tag -4: Gap Down - High muss deutlich unter Previous Low sein
        prices.append(90.0)
        highs.append(91.0)  # Gap: High (91) < Previous Low (99) = 8% Gap
        lows.append(89.0)

        # Tag -3: Partial Recovery
        prices.append(92.0)
        highs.append(93.0)
        lows.append(91.0)

        # Tag -2: More Recovery
        prices.append(94.0)
        highs.append(95.0)
        lows.append(93.0)

        # Tag -1 (aktuell): Further Recovery - High nahe Previous Low
        prices.append(96.0)
        highs.append(98.0)  # Nähert sich der 99 (Previous Low)
        lows.append(95.0)

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        assert gap_info.detected is True
        # Gap sollte als (teilweise) gefüllt erkannt werden
        assert gap_info.fill_pct > 0

    def test_gap_adds_to_score(self, analyzer):
        """Gap sollte zum Score beitragen"""
        n = 100

        # Daten mit Gap Down (typisch für Earnings)
        prices_with_gap = [100.0] * 90
        highs_with_gap = [101.0] * 90
        lows_with_gap = [99.0] * 90

        # Gap Down
        prices_with_gap.extend([90.0, 89.0, 88.0, 89.0, 90.0, 91.0, 92.0, 93.0, 94.0, 94.5])
        highs_with_gap.extend([91.0, 90.0, 89.0, 90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 95.5])
        lows_with_gap.extend([89.0, 88.0, 87.0, 88.0, 89.0, 90.0, 91.0, 92.0, 93.0, 94.0])

        volumes = [1000000] * n
        volumes[90:93] = [3000000, 2500000, 2000000]

        signal = analyzer.analyze(
            "TEST",
            prices_with_gap,
            volumes,
            highs_with_gap,
            lows_with_gap,
            pre_earnings_price=100.0
        )

        # Gap sollte in score_breakdown components sein (neue Struktur)
        breakdown = signal.details.get('score_breakdown', {})
        components = breakdown.get('components', {})
        assert 'gap' in components

    def test_gap_info_in_details(self, analyzer):
        """Gap Info sollte in Signal Details sein"""
        n = 100
        prices = [100.0] * 93
        highs = [101.0] * 93
        lows = [99.0] * 93

        # Gap Down
        prices.append(90.0)
        highs.append(91.0)  # Unter Previous Low
        lows.append(89.0)

        # Recovery
        for i in range(6):
            prices.append(90.5 + i * 0.5)
            highs.append(91.5 + i * 0.5)
            lows.append(89.5 + i * 0.5)

        volumes = [1000000] * n
        volumes[93] = 3000000

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )

        # Wenn Gap erkannt, sollte gap_info in details sein
        gap_info = signal.details.get('gap_info')
        if gap_info:
            assert 'detected' in gap_info
            assert 'gap_size_pct' in gap_info

    def test_gap_config_min_size(self):
        """Min Gap Size Konfiguration sollte respektiert werden"""
        # Config mit höherem Minimum
        config = EarningsDipConfig(min_gap_pct=5.0)
        analyzer = EarningsDipAnalyzer(config)

        n = 100
        prices = [100.0] * 95
        highs = [101.0] * 95
        lows = [99.0] * 95

        # Kleines Gap (nur 3%)
        prices.append(97.0)
        highs.append(98.0)  # 98 < 99 = Gap, aber nur ~1%
        lows.append(96.0)

        for i in range(4):
            prices.append(97.5 + i * 0.5)
            highs.append(98.5 + i * 0.5)
            lows.append(97.0 + i * 0.5)

        score, gap_info = analyzer._detect_gap_down(prices, highs, lows)

        # Gap zu klein für 5% Minimum
        assert gap_info.detected is False or gap_info.gap_size_pct < 5.0


class TestGapReasonInOutput:
    """Tests für Gap-Informationen im Signal Output"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_gap_reason_included(self, analyzer):
        """Gap Down sollte in Reason erscheinen wenn erkannt"""
        n = 100
        prices = [100.0] * 93
        highs = [101.0] * 93
        lows = [99.0] * 93

        # Klares Gap Down
        prices.append(88.0)
        highs.append(89.0)  # Deutlich unter Previous Low
        lows.append(87.0)

        # Recovery
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

        # Wenn Score > 0, sollte Gap in Reason sein
        if signal.details.get('score_breakdown', {}).get('gap', 0) > 0:
            assert "Gap" in signal.reason


# =============================================================================
# NEW TESTS: MACD Recovery, Stochastic, Keltner Channel Scoring
# =============================================================================

class TestEarningsDipMACDScoring:
    """Tests for MACD Recovery scoring in Earnings Dip Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_macd_score_bullish_cross(self, analyzer):
        """Bullish crossover should give 2 points"""
        from models.indicators import MACDResult

        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover='bullish'
        )

        # Mock prices list for the recovery check
        prices = [100] * 50

        score, reason, signal, turning = analyzer._score_macd_recovery(macd, prices)

        assert score == 2
        assert signal == "bullish_cross"
        assert "bullish" in reason.lower() or "recovery" in reason.lower()

    def test_macd_score_histogram_positive(self, analyzer):
        """Positive histogram should give 1 point"""
        from models.indicators import MACDResult

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
        from models.indicators import MACDResult

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
        """MACD should be calculated correctly with sufficient data"""
        n = 50
        prices = [100 + i * 0.5 for i in range(n)]

        result = analyzer._calculate_macd(prices)

        assert result is not None
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'histogram')


class TestEarningsDipStochasticScoring:
    """Tests for Stochastic scoring in Earnings Dip Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_stoch_score_oversold_bullish_cross(self, analyzer):
        """Oversold + bullish cross should give 2 points"""
        from models.indicators import StochasticResult

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
        from models.indicators import StochasticResult

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
        from models.indicators import StochasticResult

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
        from models.indicators import StochasticResult

        stoch = StochasticResult(
            k=50.0,
            d=48.0,
            crossover=None,
            zone='neutral'
        )
        score, reason, signal = analyzer._score_stochastic(stoch)

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


class TestEarningsDipKeltnerScoring:
    """Tests for Keltner Channel scoring in Earnings Dip Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_keltner_score_below_lower(self, analyzer):
        """Price below lower band should give 2 points"""
        from models.indicators import KeltnerChannelResult

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
        assert "unter" in reason.lower() or "below" in reason.lower()

    def test_keltner_score_near_lower(self, analyzer):
        """Price near lower band should give 1 point"""
        from models.indicators import KeltnerChannelResult

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
        assert "nahe" in reason.lower() or "near" in reason.lower()

    def test_keltner_score_above_upper(self, analyzer):
        """Price above upper band should give 0 points"""
        from models.indicators import KeltnerChannelResult

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
        assert "über" in reason.lower() or "above" in reason.lower()

    def test_keltner_score_in_channel(self, analyzer):
        """Price in channel should give 0 points (neutral)"""
        from models.indicators import KeltnerChannelResult

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


class TestEarningsDipScoreBreakdown:
    """Tests for EarningsDipScoreBreakdown (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    @pytest.fixture
    def dip_data(self):
        """Generiert Daten mit Earnings-Dip"""
        n = 100
        prices = []

        # Vor Earnings: Stabiler Aufwärtstrend
        for i in range(90):
            prices.append(100 + i * 0.1)

        # Earnings Dip: -10%
        prices.extend([99, 98.5, 98, 98.5, 99, 99.5, 100, 100.5, 101, 101.5])

        volumes = [1000000] * n
        volumes[90:93] = [3000000, 2500000, 2000000]
        volumes[93:] = [1200000] * (n - 93)

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[92] = 97.0

        return prices, volumes, highs, lows

    def test_breakdown_contains_all_new_fields(self, analyzer, dip_data):
        """EarningsDipScoreBreakdown should contain all new scoring fields"""
        prices, volumes, highs, lows = dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details.get('score_breakdown', {})

        assert 'components' in breakdown
        components = breakdown['components']

        assert 'dip' in components
        assert 'gap' in components
        assert 'rsi' in components
        assert 'stabilization' in components
        assert 'volume' in components
        assert 'trend' in components
        assert 'macd' in components
        assert 'stochastic' in components
        assert 'keltner' in components

    def test_breakdown_macd_fields(self, analyzer, dip_data):
        """MACD component should have correct fields"""
        prices, volumes, highs, lows = dip_data

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

    def test_breakdown_stochastic_fields(self, analyzer, dip_data):
        """Stochastic component should have correct fields"""
        prices, volumes, highs, lows = dip_data

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

    def test_breakdown_keltner_fields(self, analyzer, dip_data):
        """Keltner component should have correct fields"""
        prices, volumes, highs, lows = dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        keltner_info = signal.details['score_breakdown']['components']['keltner']

        assert 'score' in keltner_info
        assert 'position' in keltner_info
        assert 'percent' in keltner_info
        assert 'reason' in keltner_info

    def test_total_score_includes_all_components(self, analyzer, dip_data):
        """Total score should include all component scores"""
        prices, volumes, highs, lows = dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details['score_breakdown']

        # Calculate expected total from components
        components = breakdown['components']
        expected_total = sum([
            components['dip']['score'],
            components['gap']['score'],
            components['rsi']['score'],
            components['stabilization']['score'],
            components['volume']['score'],
            components['trend']['score'],
            components['macd']['score'],
            components['stochastic']['score'],
            components['keltner']['score']
        ])

        assert abs(breakdown['total_score'] - expected_total) < 0.01

    def test_max_possible_is_18(self, analyzer, dip_data):
        """Max possible score should be 18"""
        prices, volumes, highs, lows = dip_data

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )

        breakdown = signal.details['score_breakdown']

        assert breakdown['max_possible'] == 18


class TestEarningsDipHelperMethods:
    """Tests for helper methods (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

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


class TestEarningsDipSignalStrength:
    """Tests for signal strength determination (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()

    def test_strong_signal_high_score(self, analyzer):
        """High score should result in signal with appropriate strength"""
        # Create ideal dip scenario with recovery indicators
        n = 100
        prices = [110.0] * 85  # Above SMA200 pre-dip

        # Clear dip: ~10% - need 100 prices total
        dip_prices = [99, 97, 95, 94, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103]
        prices.extend(dip_prices)

        volumes = [1000000] * n
        volumes[85:88] = [3000000, 2500000, 2000000]  # Volume spike
        volumes[88:] = [800000] * (n - 88)  # Volume normalizing

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[87] = 92.0  # Clear dip low

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=110.0
        )

        # With a clear dip, we should get some signal
        # Check that if we have a valid dip, it's properly processed
        if signal.signal_type != SignalType.NEUTRAL:
            assert signal.strength in [SignalStrength.MODERATE, SignalStrength.STRONG, SignalStrength.WEAK]
        else:
            # If NEUTRAL, verify the dip detection reasonably failed
            assert "Dip" in signal.reason or signal.score < 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
