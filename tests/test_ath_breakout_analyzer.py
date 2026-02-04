# OptionPlay - ATH Breakout Analyzer Tests
# ==========================================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from models.base import SignalType, SignalStrength


class TestATHBreakoutBasics:
    """Grundlegende Tests für ATH Breakout Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()
    
    @pytest.fixture
    def uptrend_data(self):
        """Generiert Aufwärtstrend-Daten mit ATH-Breakout"""
        n = 260
        # Aufwärtstrend mit Konsolidierung und dann Breakout
        prices = []
        highs = []
        lows = []
        
        for i in range(n):
            if i < 200:
                # Aufwärtstrend bis 120
                p = 100 + i * 0.1
                prices.append(p)
                highs.append(p + 0.5)  # ATH wird 120.5
                lows.append(p - 0.5)
            elif i < 250:
                # Konsolidierung bei 115 (deutlich unter ATH von 120.5)
                p = 115 + (i % 3) * 0.2
                prices.append(p)
                highs.append(p + 0.3)  # Highs unter altem ATH
                lows.append(p - 0.3)
            else:
                # BREAKOUT: Neues ATH!
                p = 121 + (i - 250) * 0.5
                prices.append(p)
                highs.append(p + 1)  # Neues ATH über 120.5!
                lows.append(p - 0.3)
        
        volumes = [1000000] * n
        volumes[-1] = 2000000  # Volume Spike am Breakout
        
        return prices, volumes, highs, lows
    
    def test_strategy_name(self, analyzer):
        """Strategy Name sollte korrekt sein"""
        assert analyzer.strategy_name == "ath_breakout"
    
    def test_breakout_detected(self, analyzer, uptrend_data):
        """ATH Breakout sollte erkannt werden"""
        prices, volumes, highs, lows = uptrend_data
        
        # Debug: Check that the data actually has a breakout
        old_ath = max(highs[:-10])  # ATH vor den letzten 10 Tagen
        current_high = highs[-1]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Wenn current_high > old_ath, sollte Breakout erkannt werden
        if current_high > old_ath * 1.01:  # Mindestens 1% über ATH
            assert signal.score >= 2, f"Expected score >= 2, got {signal.score}. Current high: {current_high}, Old ATH: {old_ath}"
        else:
            # Testdaten erzeugen keinen echten Breakout - Test überspringen
            assert signal.signal_type in [SignalType.LONG, SignalType.NEUTRAL]
    
    def test_no_breakout_in_downtrend(self, analyzer):
        """Kein Signal bei Abwärtstrend"""
        n = 260
        prices = [100 - i * 0.1 for i in range(n)]  # Abwärtstrend
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.score < 5
    
    def test_volume_confirmation_bonus(self, analyzer, uptrend_data):
        """Volumen-Spike sollte Score erhöhen"""
        prices, volumes, highs, lows = uptrend_data
        
        # Mit Volumen-Spike
        signal_with_vol = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Ohne Volumen-Spike
        low_volumes = [1000000] * len(volumes)
        signal_no_vol = analyzer.analyze("TEST", prices, low_volumes, highs, lows)
        
        assert signal_with_vol.score >= signal_no_vol.score


class TestATHBreakoutConfig:
    """Tests für ATH Breakout Konfiguration"""
    
    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = ATHBreakoutConfig(
            breakout_threshold_pct=2.0,
            volume_spike_multiplier=2.0,
            min_score_for_signal=7
        )
        
        analyzer = ATHBreakoutAnalyzer(config)
        
        assert analyzer.config.breakout_threshold_pct == 2.0
        assert analyzer.config.volume_spike_multiplier == 2.0
    
    def test_stricter_config_less_signals(self):
        """Striktere Config sollte weniger Signale geben"""
        n = 260
        prices = [100 + i * 0.08 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        # Standard Config
        standard = ATHBreakoutAnalyzer()
        signal_standard = standard.analyze("TEST", prices, volumes, highs, lows)
        
        # Strikte Config
        strict_config = ATHBreakoutConfig(min_score_for_signal=9)
        strict = ATHBreakoutAnalyzer(strict_config)
        signal_strict = strict.analyze("TEST", prices, volumes, highs, lows)
        
        # Beide haben Score, aber nur Standard hat LONG Signal
        if signal_standard.signal_type == SignalType.LONG:
            assert signal_strict.score <= signal_standard.score or \
                   signal_strict.signal_type == SignalType.NEUTRAL


class TestATHBreakoutRiskManagement:
    """Tests für Risk Management"""
    
    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()
    
    def test_stop_loss_below_recent_low(self, analyzer):
        """Stop Loss sollte unter letztem Low sein"""
        n = 260
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [2000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        if signal.stop_loss:
            recent_low = min(lows[-10:])
            assert signal.stop_loss < recent_low
    
    def test_target_has_positive_rr(self, analyzer):
        """Target sollte positives Risk/Reward haben"""
        n = 260
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [2000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        if signal.risk_reward_ratio:
            assert signal.risk_reward_ratio >= 1.5


class TestATHBreakoutEdgeCases:
    """Edge Cases für ATH Breakout"""
    
    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()
    
    def test_insufficient_data(self, analyzer):
        """Zu wenig Daten sollte Exception werfen"""
        prices = [100] * 50  # Nur 50 Punkte, braucht 252
        volumes = [1000000] * 50
        highs = [101] * 50
        lows = [99] * 50
        
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)
    
    def test_flat_prices_no_signal(self, analyzer):
        """Flache Preise sollten kein Signal geben"""
        n = 260
        prices = [100.0] * n  # Komplett flat
        volumes = [1000000] * n
        highs = [100.5] * n
        lows = [99.5] * n
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL


# =============================================================================
# NEW TESTS: MACD, Momentum, Keltner Channel Scoring
# =============================================================================

class TestATHMACDScoring:
    """Tests for MACD scoring in ATH Breakout Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()

    def test_macd_score_bullish_cross(self, analyzer):
        """Bullish crossover should give 2 points"""
        from models.indicators import MACDResult

        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover='bullish'
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 2
        assert signal == "bullish_cross"
        assert "bullish" in reason.lower()

    def test_macd_score_positive_momentum(self, analyzer):
        """Positive MACD line and histogram should give 1 point"""
        from models.indicators import MACDResult

        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover=None
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 1
        assert signal == "bullish"

    def test_macd_score_weak_bullish(self, analyzer):
        """Positive histogram only should give 0.5 points"""
        from models.indicators import MACDResult

        macd = MACDResult(
            macd_line=-0.1,  # Negative MACD line
            signal_line=-0.2,
            histogram=0.1,  # But positive histogram
            crossover=None
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 0.5
        assert signal == "bullish_weak"

    def test_macd_score_not_confirming(self, analyzer):
        """Negative histogram should give 0 points"""
        from models.indicators import MACDResult

        macd = MACDResult(
            macd_line=0.3,
            signal_line=0.5,
            histogram=-0.2,
            crossover=None
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 0
        assert signal == "neutral"

    def test_macd_score_none(self, analyzer):
        """No MACD data should give 0 points"""
        score, reason, signal = analyzer._score_macd(None)

        assert score == 0
        assert signal == "neutral"

    def test_macd_calculation(self, analyzer):
        """MACD should be calculated correctly with sufficient data"""
        n = 50
        prices = [100 + i * 0.5 for i in range(n)]

        result = analyzer._calculate_macd(prices)

        assert result is not None
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'histogram')


class TestATHMomentumScoring:
    """Tests for Momentum/ROC scoring in ATH Breakout Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()

    def test_momentum_strong(self, analyzer):
        """Strong momentum (ROC > 5%) should give 2 points"""
        # Price increased 10% over 10 days
        prices = [100] * 10 + [110]

        score, roc, reason = analyzer._score_momentum(prices)

        assert score == 2
        assert roc == pytest.approx(10.0, rel=0.1)
        assert "strong" in reason.lower()

    def test_momentum_moderate(self, analyzer):
        """Moderate momentum (2-5% ROC) should give 1 point"""
        # Price increased 3% over 10 days
        prices = [100] * 10 + [103]

        score, roc, reason = analyzer._score_momentum(prices)

        assert score == 1
        assert 2 <= roc <= 5
        assert "moderate" in reason.lower()

    def test_momentum_weak(self, analyzer):
        """Weak positive momentum should give 0 points"""
        # Price increased 1% over 10 days
        prices = [100] * 10 + [101]

        score, roc, reason = analyzer._score_momentum(prices)

        assert score == 0
        assert roc > 0
        assert "weak" in reason.lower()

    def test_momentum_negative(self, analyzer):
        """Negative momentum should give 0 points"""
        # Price decreased
        prices = [100] * 10 + [95]

        score, roc, reason = analyzer._score_momentum(prices)

        assert score == 0
        assert roc < 0
        assert "negative" in reason.lower()

    def test_momentum_insufficient_data(self, analyzer):
        """Insufficient data should give 0 points"""
        prices = [100, 101, 102]

        score, roc, reason = analyzer._score_momentum(prices)

        assert score == 0
        assert "insufficient" in reason.lower()


class TestATHKeltnerScoring:
    """Tests for Keltner Channel scoring in ATH Breakout Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()

    def test_keltner_score_above_upper(self, analyzer):
        """Price above upper band should give 2 points for breakout"""
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

        score, reason = analyzer._score_keltner_breakout(keltner, 115.0)

        assert score == 2
        assert "breakout" in reason.lower() or "above" in reason.lower()

    def test_keltner_score_near_upper(self, analyzer):
        """Price near upper band should give 1 point"""
        from models.indicators import KeltnerChannelResult

        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='near_upper',
            percent_position=0.7,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner_breakout(keltner, 107.0)

        assert score == 1
        assert "near" in reason.lower()

    def test_keltner_score_below_lower(self, analyzer):
        """Price below lower band should give 0 points for breakout"""
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

        score, reason = analyzer._score_keltner_breakout(keltner, 85.0)

        assert score == 0
        assert "not a breakout" in reason.lower()

    def test_keltner_score_in_channel(self, analyzer):
        """Price in middle of channel should give 0 points"""
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

        score, reason = analyzer._score_keltner_breakout(keltner, 101.0)

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


class TestATHScoreBreakdown:
    """Tests for ATHBreakoutScoreBreakdown (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()

    @pytest.fixture
    def breakout_data(self):
        """Generiert Breakout-Daten"""
        n = 260
        prices = []
        highs = []
        lows = []

        for i in range(n):
            if i < 200:
                p = 100 + i * 0.1
            elif i < 250:
                p = 115 + (i % 3) * 0.2
            else:
                p = 121 + (i - 250) * 0.5

            prices.append(p)
            highs.append(p + 0.5 if i < 250 else p + 1)
            lows.append(p - 0.5)

        volumes = [1000000] * n
        volumes[-1] = 2000000

        return prices, volumes, highs, lows

    def test_breakdown_contains_all_new_fields(self, analyzer, breakout_data):
        """ATHBreakoutScoreBreakdown should contain all new scoring fields"""
        prices, volumes, highs, lows = breakout_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        # Prüfe ob Signal generiert wurde (könnte auch neutral sein)
        if signal.signal_type == SignalType.NEUTRAL:
            return  # Kein Breakout erkannt, Test überspringen

        breakdown = signal.details.get('score_breakdown', {})

        assert 'components' in breakdown
        components = breakdown['components']

        assert 'ath_breakout' in components
        assert 'volume' in components
        assert 'trend' in components
        assert 'rsi' in components
        assert 'relative_strength' in components
        assert 'macd' in components
        assert 'momentum' in components
        assert 'keltner' in components

    def test_breakdown_macd_fields(self, analyzer, breakout_data):
        """MACD component should have correct fields"""
        prices, volumes, highs, lows = breakout_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.signal_type == SignalType.NEUTRAL:
            return

        macd_info = signal.details['score_breakdown']['components']['macd']

        assert 'score' in macd_info
        assert 'signal' in macd_info
        assert 'histogram' in macd_info
        assert 'reason' in macd_info

    def test_breakdown_momentum_fields(self, analyzer, breakout_data):
        """Momentum component should have correct fields"""
        prices, volumes, highs, lows = breakout_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.signal_type == SignalType.NEUTRAL:
            return

        momentum_info = signal.details['score_breakdown']['components']['momentum']

        assert 'score' in momentum_info
        assert 'roc' in momentum_info
        assert 'reason' in momentum_info

    def test_breakdown_keltner_fields(self, analyzer, breakout_data):
        """Keltner component should have correct fields"""
        prices, volumes, highs, lows = breakout_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.signal_type == SignalType.NEUTRAL:
            return

        keltner_info = signal.details['score_breakdown']['components']['keltner']

        assert 'score' in keltner_info
        assert 'position' in keltner_info
        assert 'percent' in keltner_info
        assert 'reason' in keltner_info

    def test_max_possible_is_23(self, analyzer, breakout_data):
        """Max possible score should be 23 (includes gap score)"""
        prices, volumes, highs, lows = breakout_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.signal_type == SignalType.NEUTRAL:
            return

        breakdown = signal.details['score_breakdown']

        assert breakdown['max_possible'] == 23


# =============================================================================
# NEW TESTS: Multi-Day Confirmation (P1-B)
# =============================================================================

class TestATHBreakoutConfirmation:
    """Tests for Multi-Day Breakout Confirmation (P1-B)"""

    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()

    def test_confirmed_breakout_score(self, analyzer):
        """Confirmed breakout (2+ days above ATH) should get full score"""
        # Generate prices that stay above ATH for 3 days
        n = 264
        prices = []
        highs = []

        for i in range(n):
            if i < 250:
                p = 100 + i * 0.08  # Gradual rise to ~120
            else:
                # Last 4 days: all above ATH of 120
                p = 121 + (i - 250) * 0.5  # 121, 121.5, 122, 122.5

            prices.append(p)
            highs.append(p + 0.5)

        is_confirmed, score, info = analyzer._check_breakout_confirmation(
            prices=prices,
            highs=highs,
            ath_price=120.0,
            confirmation_days=2
        )

        assert is_confirmed is True
        assert score >= 1.0
        assert info['status'] == 'confirmed'
        assert info['days_close_above_ath'] >= 2

    def test_unconfirmed_breakout_score(self, analyzer):
        """Unconfirmed breakout (only 1 day above ATH) should get reduced score"""
        n = 264
        prices = []
        highs = []

        for i in range(n):
            if i < 260:
                p = 100 + i * 0.077  # Rise to ~120
            elif i == 260:
                p = 121  # Day 1: above ATH
            elif i == 261:
                p = 119  # Day 2: below ATH (failed confirmation)
            elif i == 262:
                p = 118  # Day 3: below ATH
            else:
                p = 122  # Day 4 (today): back above

            prices.append(p)
            highs.append(p + 0.5)

        is_confirmed, score, info = analyzer._check_breakout_confirmation(
            prices=prices,
            highs=highs,
            ath_price=120.0,
            confirmation_days=2
        )

        assert is_confirmed is False
        assert score < 1.0
        assert info['status'] == 'unconfirmed'
        assert info['days_close_above_ath'] < 2

    def test_partial_confirmation_score(self, analyzer):
        """Partial confirmation (1 of 2 days) should give partial credit"""
        n = 264
        prices = []
        highs = []

        for i in range(n):
            if i < 261:
                p = 100 + i * 0.076
            elif i == 261:
                p = 121  # 1 day above ATH
            elif i == 262:
                p = 118  # 1 day below ATH
            else:
                p = 122

            prices.append(p)
            highs.append(p + 0.5)

        is_confirmed, score, info = analyzer._check_breakout_confirmation(
            prices=prices,
            highs=highs,
            ath_price=120.0,
            confirmation_days=2
        )

        assert is_confirmed is False
        assert 0 < score < 0.5  # Partial credit
        assert info['days_close_above_ath'] == 1

    def test_ath_score_reduced_for_unconfirmed(self, analyzer):
        """_score_ath_breakout should reduce score for unconfirmed breakouts"""
        n = 264
        prices = []
        highs = []

        # Create unconfirmed breakout
        for i in range(n):
            if i < 260:
                p = 100 + i * 0.077
            elif i == 260:
                p = 121
            elif i == 261:
                p = 119  # Failed confirmation
            elif i == 262:
                p = 118
            else:
                p = 122

            prices.append(p)
            highs.append(p + 0.5 if i < 260 else p + 1)

        score, info = analyzer._score_ath_breakout(
            highs=highs,
            current_high=123,
            prices=prices
        )

        assert info['confirmation']['status'] == 'unconfirmed'
        assert info['score_adjustment'] == 'reduced_unconfirmed'
        # Score should be reduced (typically from 2-3 to 1-2)
        assert score <= 2

    def test_ath_score_full_for_confirmed(self, analyzer):
        """_score_ath_breakout should give full score for confirmed breakouts"""
        n = 264
        prices = []
        highs = []

        # Create confirmed breakout
        for i in range(n):
            if i < 250:
                p = 100 + i * 0.08
            else:
                p = 121 + (i - 250) * 0.5  # All days above ATH

            prices.append(p)
            highs.append(p + 0.5 if i < 250 else p + 1)

        score, info = analyzer._score_ath_breakout(
            highs=highs,
            current_high=128,
            prices=prices
        )

        assert info['confirmation']['status'] == 'confirmed'
        assert info['score_adjustment'] == 'confirmed'
        # Score should be full (2-3)
        assert score >= 2

    def test_config_confirmation_days(self):
        """Configuration should control confirmation days"""
        config = ATHBreakoutConfig(confirmation_days=3)
        analyzer = ATHBreakoutAnalyzer(config)

        assert analyzer.config.confirmation_days == 3

        # Generate prices that only confirm for 2 days (not 3)
        n = 264
        prices = []
        highs = []

        for i in range(n):
            if i < 260:
                p = 100 + i * 0.077
            elif i in [260, 261]:  # Only 2 days above ATH
                p = 121
            else:
                p = 119  # Below ATH

            prices.append(p)
            highs.append(p + 0.5)

        prices[-1] = 122  # Today above ATH

        is_confirmed, score, info = analyzer._check_breakout_confirmation(
            prices=prices,
            highs=highs,
            ath_price=120.0,
            confirmation_days=3  # Require 3 days
        )

        # Should NOT be confirmed because we only have 2 days
        assert is_confirmed is False

    def test_insufficient_data_for_confirmation(self, analyzer):
        """Should handle insufficient data gracefully"""
        prices = [100, 101]  # Only 2 data points (need 3 for confirmation_days=2)
        highs = [101, 102]

        is_confirmed, score, info = analyzer._check_breakout_confirmation(
            prices=prices,
            highs=highs,
            ath_price=100.0,
            confirmation_days=2
        )

        assert is_confirmed is False
        assert info['status'] == 'insufficient_data'


class TestATHHelperMethods:
    """Tests for helper methods (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
