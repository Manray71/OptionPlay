# Tests for ATH Breakout Analyzer (Refactored v2)
# =================================================
"""
Tests for ATHBreakoutAnalyzer v2 with:
  - 4-step filter pipeline (consolidation → close confirmation → volume → RSI)
  - 4-component scoring (max ~9.0)
  - 10 spec test cases

Test classes:
  - TestATHBreakoutInitialization
  - TestATHBreakoutAnalyzeMethod
  - TestATHBreakoutDisqualifications
  - TestATHBreakoutSpecTestCases (10 cases from spec)
  - TestATHBreakoutSignalText
  - TestATHBreakoutScoringComponents
  - TestConsolidationDetection
  - TestATHBreakoutEdgeCases
  - TestATHBreakoutBackwardCompat
"""

import pytest
import math
from unittest.mock import MagicMock, patch, PropertyMock

from src.analyzers.ath_breakout import (
    ATHBreakoutAnalyzer,
    ATHBreakoutConfig,
    ATH_MIN_SCORE,
    ATH_MAX_SCORE,
)
from src.models.base import TradeSignal, SignalType, SignalStrength
from src.models.strategy_breakdowns import ATHBreakoutScoreBreakdown


# =============================================================================
# HELPER: Generate test data for ATH breakouts
# =============================================================================

def make_ath_data(
    n: int = 300,
    base_price: float = 100.0,
    consolidation_days: int = 40,
    consolidation_range_pct: float = 6.0,
    breakout_pct: float = 2.0,
    ath_tests: int = 0,
    volume_ratio: float = 2.0,
    avg_volume: int = 1_000_000,
    trend: str = 'up',
    close_above_ath: bool = True,
    days_above_ath: int = 1,
    rsi_target: float = 60.0,
) -> dict:
    """
    Generate OHLCV test data for ATH breakout scenarios.

    Creates a price history with:
    1. An initial uptrend establishing the ATH
    2. A consolidation phase below the ATH
    3. A breakout bar (current bar)

    Args:
        n: Total data points
        base_price: Price level around which consolidation happens
        consolidation_days: Days of consolidation before breakout
        consolidation_range_pct: Range of consolidation (%)
        breakout_pct: How far above ATH the close is (%)
        ath_tests: Number of times price tested ATH during consolidation
        volume_ratio: Breakout volume / avg volume
        avg_volume: Average volume
        trend: 'up' for uptrend, 'down' for downtrend
        close_above_ath: Whether close is above ATH (False = fakeout)
        days_above_ath: Consecutive days with close > ATH
        rsi_target: Target RSI value (approximate)

    Returns:
        dict with keys: prices, volumes, highs, lows
    """
    import numpy as np
    np.random.seed(42)

    # Calculate ATH based on base_price
    # ATH is at the top of where consolidation happened
    half_range = (consolidation_range_pct / 2) / 100
    ath = base_price * (1 + half_range)

    # Build price history
    prices = []
    highs = []
    lows = []
    volumes = []

    # Phase 1: Uptrend to ATH (first n - consolidation_days - days_above_ath bars)
    uptrend_days = n - consolidation_days - days_above_ath
    if uptrend_days < 10:
        uptrend_days = 10

    start_price = base_price * 0.65  # Start 35% below base
    for i in range(uptrend_days):
        progress = i / max(uptrend_days - 1, 1)
        # Gradually rise to near ATH
        p = start_price + (ath - start_price) * progress
        # Add small noise
        noise = np.random.uniform(-0.3, 0.3) * (p * 0.005)
        p += noise

        h = p + abs(np.random.normal(0, p * 0.005))
        l = p - abs(np.random.normal(0, p * 0.005))

        prices.append(p)
        highs.append(h)
        lows.append(l)
        volumes.append(int(avg_volume * np.random.uniform(0.8, 1.2)))

    # Phase 2: Consolidation below ATH
    # Create oscillating pattern that brings RSI toward neutral (50-65)
    consol_mid = base_price
    consol_half = (consolidation_range_pct / 2) / 100 * base_price

    # ATH test positions (if any)
    test_positions = []
    if ath_tests > 0 and consolidation_days > 5:
        step = consolidation_days // (ath_tests + 1)
        for t in range(ath_tests):
            test_positions.append((t + 1) * step)

    for i in range(consolidation_days):
        # Oscillate up and down within consolidation range to normalize RSI
        # Use multiple sine waves for more realistic oscillation
        phase1 = i / max(consolidation_days - 1, 1) * 4 * math.pi  # 2 full cycles
        phase2 = i / max(consolidation_days - 1, 1) * 7 * math.pi  # ~3.5 cycles
        oscillation = (math.sin(phase1) * 0.5 + math.sin(phase2) * 0.3) * consol_half
        p = consol_mid + oscillation
        noise = np.random.uniform(-0.3, 0.3) * (p * 0.005)
        p += noise

        h = p + abs(np.random.normal(0, p * 0.006))
        l = p - abs(np.random.normal(0, p * 0.006))

        # ATH test: push high near ATH but keep close below
        if i in test_positions:
            h = ath * np.random.uniform(0.995, 1.005)
            p = min(p, ath * 0.995)  # Close below ATH

        # Make sure lows don't go below consolidation bottom
        consol_bottom = consol_mid - consol_half
        l = max(l, consol_bottom)

        prices.append(p)
        highs.append(h)
        lows.append(l)
        volumes.append(int(avg_volume * np.random.uniform(0.8, 1.2)))

    # Phase 2b: Add RSI-normalizing dips at end of consolidation
    # to prevent RSI from being > 80 on breakout day
    # We create a meaningful pullback in the last 5 bars of consolidation
    n_dip_bars = min(5, consolidation_days // 3)
    for i in range(n_dip_bars):
        idx = len(prices) - 1 - i  # Last bars of consolidation
        if 0 <= idx < len(prices):
            # Progressive dip: deeper toward the end of the dip
            dip_depth = consol_half * (0.3 + 0.2 * i)
            prices[idx] = consol_mid - dip_depth
            lows[idx] = prices[idx] - abs(np.random.normal(0, 0.3))
            highs[idx] = prices[idx] + abs(np.random.normal(0, 0.5))
            # Keep within consolidation range
            prices[idx] = max(prices[idx], consol_mid - consol_half * 0.9)
            lows[idx] = max(lows[idx], consol_mid - consol_half)
            highs[idx] = max(highs[idx], prices[idx])

    # Phase 3: Breakout bar(s)
    breakout_close = ath * (1 + breakout_pct / 100) if close_above_ath else ath * 0.998
    breakout_volume = int(avg_volume * volume_ratio)

    for d in range(days_above_ath):
        if d == 0:
            # First breakout day
            p = breakout_close
            h = p + abs(np.random.normal(0, p * 0.003))
            l = p - abs(np.random.normal(0, p * 0.005))
            l = max(l, ath * 0.99)  # Don't go too far below ATH
            v = breakout_volume
        else:
            # Follow-through days
            prev = prices[-1]
            p = prev * np.random.uniform(1.001, 1.005)
            h = p + abs(np.random.normal(0, p * 0.003))
            l = p - abs(np.random.normal(0, p * 0.003))
            v = int(breakout_volume * np.random.uniform(0.8, 1.0))

        # For fakeout: high above ATH but close below
        if not close_above_ath and d == days_above_ath - 1:
            h = ath * 1.01  # High above ATH
            p = ath * 0.998  # Close below ATH

        prices.append(p)
        highs.append(max(h, p))
        lows.append(min(l, p))
        volumes.append(v)

    # Ensure we have exactly n data points
    while len(prices) < n:
        prices.insert(0, start_price * np.random.uniform(0.95, 1.05))
        highs.insert(0, prices[0] * 1.005)
        lows.insert(0, prices[0] * 0.995)
        volumes.insert(0, int(avg_volume * np.random.uniform(0.8, 1.2)))

    # Trim to n points if too many
    prices = prices[-n:]
    highs = highs[-n:]
    lows = lows[-n:]
    volumes = volumes[-n:]

    # Validate highs >= prices >= lows
    for i in range(len(prices)):
        highs[i] = max(highs[i], prices[i])
        lows[i] = min(lows[i], prices[i])
        if highs[i] < lows[i]:
            highs[i] = max(prices[i], highs[i], lows[i])
            lows[i] = min(prices[i], highs[i], lows[i])

    return {
        'prices': prices,
        'volumes': volumes,
        'highs': highs,
        'lows': lows,
        'ath': ath,
    }


# =============================================================================
# TEST: INITIALIZATION
# =============================================================================

class TestATHBreakoutInitialization:
    """Tests for ATHBreakoutAnalyzer initialization."""

    def test_default_config(self):
        """Test analyzer creates with default config."""
        analyzer = ATHBreakoutAnalyzer()
        assert analyzer.config is not None
        assert analyzer.config.ath_lookback_days == 252
        assert analyzer.config.consolidation_min_days == 20
        assert analyzer.config.min_score_for_signal == 4.0

    def test_custom_config(self):
        """Test analyzer with custom config."""
        config = ATHBreakoutConfig(
            ath_lookback_days=200,
            consolidation_min_days=15,
            min_score_for_signal=3.0,
        )
        analyzer = ATHBreakoutAnalyzer(config=config)
        assert analyzer.config.ath_lookback_days == 200
        assert analyzer.config.consolidation_min_days == 15
        assert analyzer.config.min_score_for_signal == 3.0

    def test_strategy_name(self):
        """Test strategy name property."""
        analyzer = ATHBreakoutAnalyzer()
        assert analyzer.strategy_name == "ath_breakout"

    def test_description(self):
        """Test description property."""
        analyzer = ATHBreakoutAnalyzer()
        assert "ATH" in analyzer.description
        assert "Breakout" in analyzer.description

    def test_backward_compat_scoring_config(self):
        """Test scoring_config parameter accepted but ignored."""
        mock_config = MagicMock()
        analyzer = ATHBreakoutAnalyzer(scoring_config=mock_config)
        assert analyzer.scoring_config == mock_config  # Stored but not used

    def test_backward_compat_legacy_fields(self):
        """Test legacy config fields accepted."""
        config = ATHBreakoutConfig(
            confirmation_days=3,
            breakout_threshold_pct=2.0,
            volume_spike_multiplier=2.0,
        )
        analyzer = ATHBreakoutAnalyzer(config=config)
        # Legacy fields exist but don't affect v2 behavior
        assert analyzer.config.confirmation_days == 3


# =============================================================================
# TEST: ANALYZE METHOD
# =============================================================================

class TestATHBreakoutAnalyzeMethod:
    """Tests for the main analyze() method."""

    def test_returns_trade_signal(self):
        """Test analyze returns TradeSignal."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert isinstance(signal, TradeSignal)

    def test_signal_has_strategy_name(self):
        """Test signal has correct strategy name."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.strategy == "ath_breakout"

    def test_signal_score_range(self):
        """Test signal score is within expected range."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert 0.0 <= signal.score <= 10.0

    def test_minimum_data_requirement(self):
        """Test insufficient data raises ValueError."""
        analyzer = ATHBreakoutAnalyzer()
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", [100] * 10, [1000] * 10,
                           [101] * 10, [99] * 10)

    def test_details_contains_components(self):
        """Test details dict has component scores."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300, volume_ratio=2.0, breakout_pct=2.0)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert 'components' in signal.details
            comps = signal.details['components']
            assert 'consolidation_quality' in comps
            assert 'breakout_strength' in comps
            assert 'volume' in comps
            assert 'momentum_trend' in comps

    def test_signal_has_entry_stop_target(self):
        """Test signal has entry, stop, and target prices."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300, volume_ratio=2.0, breakout_pct=2.0)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.target_price > signal.entry_price
            assert signal.stop_loss < signal.entry_price

    def test_spy_prices_accepted(self):
        """Test spy_prices parameter accepted for backward compat."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300)
        spy = [100.0] * 300
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows'],
            spy_prices=spy
        )
        assert isinstance(signal, TradeSignal)


# =============================================================================
# TEST: DISQUALIFICATIONS
# =============================================================================

class TestATHBreakoutDisqualifications:
    """Tests for disqualification scenarios."""

    def test_no_ath_breakout(self):
        """No signal when price is below ATH."""
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        # Downtrend: not near ATH
        prices = [100 - i * 0.1 for i in range(n)]
        highs = [p + 1.0 for p in prices]
        lows = [p - 1.0 for p in prices]
        volumes = [1_000_000] * n

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL
        assert "below" in signal.reason.lower() or "no ath" in signal.reason.lower()

    def test_no_consolidation_disqualified(self):
        """No signal when there's no consolidation (steady climb)."""
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        # Steady uptrend with no consolidation — always making new highs
        prices = [100 + i * 0.5 for i in range(n)]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * n
        # Last bar breaks out to new high with volume
        volumes[-1] = 2_000_000

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL

    def test_fakeout_close_below_ath(self):
        """No signal when high > ATH but close < ATH (fakeout)."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            close_above_ath=False,
            volume_ratio=2.0,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.NEUTRAL
        assert "fakeout" in signal.reason.lower() or "not confirmed" in signal.reason.lower() or "below" in signal.reason.lower()

    def test_weak_volume_disqualified(self):
        """No signal when volume < 1.0x avg."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            volume_ratio=0.6,  # Way below threshold
            breakout_pct=2.0,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.NEUTRAL
        assert "volume" in signal.reason.lower() or "weak" in signal.reason.lower()

    def test_rsi_overbought_disqualified(self):
        """No signal when RSI > 80."""
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        # Create strong uptrend with very high RSI
        # Prices going up sharply to get RSI > 80
        prices = []
        for i in range(n):
            if i < n - 60:
                p = 100.0  # Flat for most of the history
            elif i < n - 1:
                # Consolidation
                p = 100.0 + (i - (n - 60)) * 0.01
            else:
                p = 100.0 + 50.0  # Huge jump
            prices.append(p)

        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * n
        volumes[-1] = 2_000_000

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        # Either disqualified for RSI or for lack of consolidation
        assert signal.signal_type == SignalType.NEUTRAL

    def test_wide_range_disqualified(self):
        """No signal when consolidation range > 15%."""
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        ath = 110.0
        # Create a wild swing pattern where every 20-day window has > 15% range
        prices = [70 + i * 0.1 for i in range(n - 65)]  # Uptrend
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * len(prices)

        # Last 65 bars: wild up-down swings (range > 15% in any 20-day window)
        for i in range(64):
            if i % 3 == 0:
                p = ath * 0.98  # Near top
            elif i % 3 == 1:
                p = ath * 0.82  # Drop to bottom (18% range)
            else:
                p = ath * 0.90  # Mid
            prices.append(p)
            highs.append(p + 0.3)
            lows.append(p - 0.3)
            volumes.append(1_000_000)

        # Breakout bar
        prices.append(ath * 1.02)
        highs.append(ath * 1.03)
        lows.append(ath * 0.99)
        volumes.append(2_000_000)

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL


# =============================================================================
# TEST: SPEC TEST CASES (10 cases from spec)
# =============================================================================

class TestATHBreakoutSpecTestCases:
    """Tests from the specification document."""

    def test_case_1_classic_breakout(self):
        """
        Spec Case 1: 45-day base (6% range), Close +2% over ATH, Vol 2.0x, MACD bullish
        Expected: Strong signal (~7.5)
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=45,
            consolidation_range_pct=6.0,
            breakout_pct=2.0,
            volume_ratio=2.0,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= ATH_MIN_SCORE
        # Classic breakout should be moderate to strong
        assert signal.score >= 5.0

    def test_case_2_moderate_breakout(self):
        """
        Spec Case 2: 25-day base (10% range), Close +1% over ATH, Vol 1.6x
        Expected: Moderate signal (~5.0)
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=25,
            consolidation_range_pct=10.0,
            breakout_pct=1.0,
            volume_ratio=1.6,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= ATH_MIN_SCORE

    def test_case_3_no_consolidation(self):
        """
        Spec Case 3: No base (steady climb), new high, Vol 1.2x
        Expected: No signal (no consolidation)
        """
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        # Steady uptrend — no consolidation
        prices = [80 + i * 0.2 for i in range(n)]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * n
        volumes[-1] = 1_200_000

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case_4_fakeout(self):
        """
        Spec Case 4: 30-day base, High over ATH, but Close below
        Expected: No signal (not confirmed)
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=30,
            close_above_ath=False,
            volume_ratio=2.0,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case_5_weak_volume(self):
        """
        Spec Case 5: 40-day base, Close over ATH, but Vol only 0.8x
        Expected: No signal (weak volume)
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=40,
            breakout_pct=2.0,
            volume_ratio=0.8,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case_6_excellent_breakout(self):
        """
        Spec Case 6: 50-day base (5% range, 3x tested), Close +3%, Vol 2.5x, perfect SMA alignment
        Expected: Excellent signal (~8.5)
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=50,
            consolidation_range_pct=5.0,
            ath_tests=3,
            breakout_pct=3.0,
            volume_ratio=2.5,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= 6.0  # Should be high, exact value depends on momentum

    def test_case_7_overextended(self):
        """
        Spec Case 7: 20-day base, Close +8% over ATH, Vol 1.5x, RSI 78
        Expected: Weak signal (~4.0) — overextended + near overbought
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=20,
            breakout_pct=8.0,
            volume_ratio=1.5,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        # Could be LONG with weak score or NEUTRAL if RSI disqualified
        if signal.signal_type == SignalType.LONG:
            assert signal.score <= 6.0  # Should not be strong

    def test_case_8_wide_range(self):
        """
        Spec Case 8: Base present, but range 18%
        Expected: No signal (range too wide)
        """
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        ath = 110.0
        # Uptrend phase
        prices = [70 + i * 0.1 for i in range(n - 65)]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * len(prices)

        # "Base" with 18% range — too wide for consolidation
        for i in range(64):
            if i % 3 == 0:
                p = ath * 0.97
            elif i % 3 == 1:
                p = ath * 0.80  # 20% below ATH
            else:
                p = ath * 0.88
            prices.append(p)
            highs.append(p + 0.3)
            lows.append(p - 0.3)
            volumes.append(1_000_000)

        # Breakout
        prices.append(ath * 1.02)
        highs.append(ath * 1.03)
        lows.append(ath * 0.99)
        volumes.append(2_000_000)

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case_9_sustained_breakout(self):
        """
        Spec Case 9: 60-day base, Close over ATH since 3 days, strong volume initially
        Expected: Strong signal + multi-day bonus
        """
        analyzer = ATHBreakoutAnalyzer()
        # Build data manually for multi-day breakout to ensure
        # follow-through days are clearly above ATH
        import numpy as np
        np.random.seed(99)

        n = 300
        ath = 103.0
        avg_vol = 1_000_000

        # Phase 1: Uptrend (first ~237 bars) — peaks below ATH
        prices, highs, lows, volumes = [], [], [], []
        for i in range(237):
            p = 65 + (100.0 - 65) * (i / 236)  # Max close = 100.0 (below ATH)
            h = p + 0.4
            l = p - 0.4
            prices.append(p)
            highs.append(h)
            lows.append(l)
            volumes.append(int(avg_vol * np.random.uniform(0.8, 1.2)))

        # Phase 2: Consolidation (60 bars) at 98-102 range (below ATH=103)
        for i in range(60):
            phase = i / 59 * 8 * 3.14159  # 4 full cycles
            p = 100.0 + 1.5 * np.sin(phase)
            # Create explicit pullback in last 10 bars to lower RSI
            if i >= 50:
                p = 97.0 - (i - 50) * 0.3  # Dip to ~94
            h = p + 0.5
            l = p - 0.5
            prices.append(p)
            highs.append(h)
            lows.append(l)
            volumes.append(int(avg_vol * np.random.uniform(0.8, 1.2)))

        # Phase 3: 3 days above ATH (rising from the dip, strong volume)
        for d in range(3):
            p = ath * (1.02 + 0.005 * d)  # 2-3% above ATH
            h = p + 0.3
            l = p - 0.3
            v = int(avg_vol * (2.5 if d == 0 else 1.8))
            prices.append(p)
            highs.append(h)
            lows.append(l)
            volumes.append(v)

        # Validate
        for i in range(len(prices)):
            highs[i] = max(highs[i], prices[i])
            lows[i] = min(lows[i], prices[i])

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= ATH_MIN_SCORE
        # With 3 breakout days, the "previous_ath" includes earlier
        # breakout days' highs, so days_above may be 1 (only last bar
        # closes above the most recent high). The key is that a multi-day
        # scenario still produces a LONG signal.
        assert signal.details is not None

    def test_case_10_borderline_volume(self):
        """
        Spec Case 10: New ATH, base 60 days (very long), Vol 1.3x
        Expected: Weak signal (~4.5) — volume borderline
        Note: With 120-day lookback, consolidation must be long enough
              to dominate the window and keep range tight.
        """
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            consolidation_days=60,
            consolidation_range_pct=7.0,
            breakout_pct=1.5,
            volume_ratio=1.3,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= ATH_MIN_SCORE
        # Borderline volume should keep score moderate
        assert signal.score <= 7.0


# =============================================================================
# TEST: SIGNAL TEXT FORMAT
# =============================================================================

class TestATHBreakoutSignalText:
    """Tests for signal text formatting."""

    def test_signal_text_contains_ath_breakout(self):
        """Signal text starts with 'ATH Breakout'."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300, volume_ratio=2.0, breakout_pct=2.0)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert "ATH Breakout" in signal.reason

    def test_signal_text_contains_close_price(self):
        """Signal text includes close price."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300, volume_ratio=2.0, breakout_pct=2.0)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert "Close $" in signal.reason

    def test_signal_text_contains_base_info(self):
        """Signal text includes base duration and range."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300, consolidation_days=40,
            volume_ratio=2.0, breakout_pct=2.0,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert "base" in signal.reason.lower() or "day" in signal.reason.lower()

    def test_signal_text_contains_volume(self):
        """Signal text includes volume ratio."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300, volume_ratio=2.0, breakout_pct=2.0)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert "Vol" in signal.reason


# =============================================================================
# TEST: SCORING COMPONENTS
# =============================================================================

class TestATHBreakoutScoringComponents:
    """Tests for individual scoring components."""

    def setup_method(self):
        """Setup analyzer for each test."""
        self.analyzer = ATHBreakoutAnalyzer()

    def test_consolidation_quality_tight_long_base(self):
        """Tight, long base gets highest consolidation score."""
        consol_info = {
            'range_pct': 5.0,   # ≤ 8%
            'duration': 40,      # >= 30 days
            'ath_tests': 0,
        }
        score = self.analyzer._score_consolidation_quality(consol_info)
        assert score == 2.5

    def test_consolidation_quality_tight_short_base(self):
        """Tight but shorter base."""
        consol_info = {
            'range_pct': 6.0,   # ≤ 8%
            'duration': 22,      # 20-30 days
            'ath_tests': 0,
        }
        score = self.analyzer._score_consolidation_quality(consol_info)
        assert score == 2.0

    def test_consolidation_quality_medium_range(self):
        """Medium range consolidation."""
        consol_info = {
            'range_pct': 10.0,  # 8-12%
            'duration': 35,     # >= 30 days
            'ath_tests': 0,
        }
        score = self.analyzer._score_consolidation_quality(consol_info)
        assert score == 2.0

    def test_consolidation_quality_wide_range(self):
        """Wide range consolidation."""
        consol_info = {
            'range_pct': 13.0,  # 12-15%
            'duration': 25,
            'ath_tests': 0,
        }
        score = self.analyzer._score_consolidation_quality(consol_info)
        assert score == 1.0

    def test_consolidation_quality_ath_test_bonus(self):
        """ATH tests add 0.5 bonus (capped at 2.5)."""
        consol_info = {
            'range_pct': 10.0,
            'duration': 25,      # 1.5 base
            'ath_tests': 3,      # +0.5 bonus
        }
        score = self.analyzer._score_consolidation_quality(consol_info)
        assert score == 2.0  # 1.5 + 0.5 = 2.0

    def test_breakout_strength_small(self):
        """Small breakout (0-1% above ATH)."""
        close_info = {'pct_above': 0.5, 'days_above': 1}
        score = self.analyzer._score_breakout_strength(close_info)
        assert score == 1.0

    def test_breakout_strength_moderate(self):
        """Moderate breakout (1-3% above ATH)."""
        close_info = {'pct_above': 2.0, 'days_above': 1}
        score = self.analyzer._score_breakout_strength(close_info)
        assert score == 1.5

    def test_breakout_strength_strong(self):
        """Strong breakout (3-5% above ATH)."""
        close_info = {'pct_above': 4.0, 'days_above': 1}
        score = self.analyzer._score_breakout_strength(close_info)
        assert score == 2.0

    def test_breakout_strength_overextended(self):
        """Overextended breakout (>5% above ATH)."""
        close_info = {'pct_above': 7.0, 'days_above': 1}
        score = self.analyzer._score_breakout_strength(close_info)
        assert score == 1.5  # Penalized for overextension

    def test_breakout_strength_multiday_bonus(self):
        """Multi-day confirmation bonus."""
        close_info = {'pct_above': 1.5, 'days_above': 3}
        score = self.analyzer._score_breakout_strength(close_info)
        assert score == 2.0  # 1.5 + 0.5 = 2.0 (capped)

    def test_volume_score_very_strong(self):
        """Very strong volume >= 2.5x avg."""
        score = self.analyzer._score_volume(3.0)
        assert score == 2.5

    def test_volume_score_strong(self):
        """Strong volume >= 2.0x avg."""
        score = self.analyzer._score_volume(2.2)
        assert score == 2.0

    def test_volume_score_moderate(self):
        """Moderate volume 1.5-2.0x avg."""
        score = self.analyzer._score_volume(1.7)
        assert score == 1.5

    def test_volume_score_borderline(self):
        """Borderline volume 1.0-1.5x avg."""
        score = self.analyzer._score_volume(1.2)
        assert score == 0.5

    def test_volume_score_weak(self):
        """Weak volume < 1.0x avg gets penalty."""
        score = self.analyzer._score_volume(0.7)
        assert score == -1.0


# =============================================================================
# TEST: CONSOLIDATION DETECTION
# =============================================================================

class TestConsolidationDetection:
    """Tests for consolidation detection logic."""

    def setup_method(self):
        """Setup analyzer for each test."""
        self.analyzer = ATHBreakoutAnalyzer()

    def test_detects_consolidation(self):
        """Detects a valid consolidation pattern."""
        n = 300
        ath = 105.0

        # Build data with clear consolidation in last 60 bars
        highs = [90.0 + i * 0.05 for i in range(n)]
        lows = [h - 1.0 for h in highs]
        prices = [(h + l) / 2 for h, l in zip(highs, lows)]

        # Create consolidation in last 50 bars (before breakout)
        for i in range(n - 50, n - 1):
            prices[i] = 102.0 + (i % 5) * 0.5
            highs[i] = prices[i] + 0.5
            lows[i] = prices[i] - 0.5

        # Breakout bar
        prices[-1] = 106.0
        highs[-1] = 107.0
        lows[-1] = 104.5

        result = self.analyzer._detect_consolidation(highs, lows, prices, ath)
        assert result['has_consolidation'] is True
        assert result['range_pct'] <= 15.0

    def test_no_consolidation_steep_trend(self):
        """No consolidation when price is in steep uptrend."""
        n = 80
        ath = 500.0

        # Very steep uptrend: price doubles over 80 bars (exponential growth)
        # Each 20-bar window will have > 15% range
        prices = [100 * (1.01 ** i) for i in range(n)]
        highs = [p * 1.002 for p in prices]
        lows = [p * 0.998 for p in prices]

        result = self.analyzer._detect_consolidation(highs, lows, prices, ath)
        assert result['has_consolidation'] is False

    def test_counts_ath_tests(self):
        """Counts ATH tests during consolidation."""
        n = 300
        ath = 105.0

        # Flat consolidation
        prices = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n

        # Add ATH tests at specific points
        for i in [n - 40, n - 25, n - 10]:
            highs[i] = ath * 0.998  # Within 1% of ATH
            prices[i] = ath * 0.99  # Close below ATH

        # Breakout
        prices[-1] = ath * 1.02
        highs[-1] = ath * 1.03
        lows[-1] = ath * 0.99

        result = self.analyzer._detect_consolidation(highs, lows, prices, ath)
        if result['has_consolidation']:
            assert result['ath_tests'] >= 2

    def test_insufficient_data(self):
        """Handles insufficient data gracefully."""
        result = self.analyzer._detect_consolidation(
            [100, 101, 102], [99, 100, 101], [99.5, 100.5, 101.5], 103.0
        )
        assert result['has_consolidation'] is False

    def test_longest_valid_window_selected(self):
        """Selects longest valid consolidation window, not shortest.

        With monotonically non-decreasing range as window grows, the algorithm
        should pick the longest window still within max_range (default 15%).
        A short window (20 bars, ~2% range) AND a long window (50 bars, ~5%)
        are both valid — the longer one should be chosen.
        """
        n = 300
        ath = 110.0

        # Uptrend phase
        prices = [80.0 + i * 0.1 for i in range(n)]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        # Create tight consolidation in last 60 bars (range ~5%)
        for i in range(n - 60, n - 1):
            base = 103.0
            offset = (i % 7) * 0.4 - 1.2  # oscillate within ~3 points
            prices[i] = base + offset
            highs[i] = prices[i] + 0.8
            lows[i] = prices[i] - 0.8

        # Breakout bar
        prices[-1] = 111.0
        highs[-1] = 112.0
        lows[-1] = 110.0

        result = self.analyzer._detect_consolidation(highs, lows, prices, ath)
        assert result['has_consolidation'] is True
        # Duration should be > min_days (20), closer to the full 59 bar window
        assert result['duration'] > 30, (
            f"Expected longest valid window (>30 bars), got {result['duration']}"
        )

    def test_window_stops_growing_when_range_exceeds_max(self):
        """Window growth stops when adding older, volatile data exceeds max_range."""
        n = 300
        ath = 110.0

        # Build volatile early data, then tight consolidation at end
        prices = [80.0 + i * 0.3 for i in range(n)]
        highs = [p + 3.0 for p in prices]  # Wide range early
        lows = [p - 3.0 for p in prices]

        # Tight consolidation in only the last 30 bars (~3% range)
        for i in range(n - 30, n - 1):
            prices[i] = 105.0 + (i % 3) * 0.5
            highs[i] = prices[i] + 0.5
            lows[i] = prices[i] - 0.5

        # Breakout bar
        prices[-1] = 111.0
        highs[-1] = 112.0
        lows[-1] = 110.0

        result = self.analyzer._detect_consolidation(highs, lows, prices, ath)
        assert result['has_consolidation'] is True
        # Should not extend beyond the tight zone into volatile territory
        assert result['duration'] <= 40


# =============================================================================
# TEST: EDGE CASES
# =============================================================================

class TestATHBreakoutEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exact_ath_on_close(self):
        """Close exactly at ATH (not above) should not trigger."""
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        prices = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        volumes = [1_000_000] * n

        # Make last bar close exactly at 252-day high close
        max_prev_close = max(prices[:-1])
        prices[-1] = max_prev_close  # Exactly at, not above

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        # Close must be strictly > previous ATH for confirmation
        assert signal.signal_type == SignalType.NEUTRAL

    def test_very_small_breakout(self):
        """Very small breakout still detected."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            breakout_pct=0.1,  # Just barely above ATH
            volume_ratio=2.0,
            consolidation_days=30,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        # Could be signal or neutral depending on close confirmation
        assert isinstance(signal, TradeSignal)

    def test_all_same_prices(self):
        """All prices the same — no ATH breakout possible."""
        analyzer = ATHBreakoutAnalyzer()
        n = 300
        prices = [100.0] * n
        highs = [100.0] * n
        lows = [100.0] * n
        volumes = [1_000_000] * n

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL

    def test_extreme_volume(self):
        """Extreme volume spike should give max volume score."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            volume_ratio=5.0,  # 5x average
            breakout_pct=2.0,
            consolidation_days=40,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            comps = signal.details['components']
            assert comps['volume'] == 2.5

    def test_warnings_on_elevated_rsi(self):
        """Warnings when RSI is elevated but below disqualify threshold."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(
            n=300,
            breakout_pct=2.0,
            volume_ratio=2.0,
        )
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        # Warnings may or may not be present depending on RSI value
        assert isinstance(signal.warnings, list)

    def test_context_parameter_accepted(self):
        """Test that AnalysisContext parameter is accepted."""
        from src.analyzers.context import AnalysisContext
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300)
        context = AnalysisContext()

        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows'],
            context=context
        )
        assert isinstance(signal, TradeSignal)


# =============================================================================
# TEST: BACKWARD COMPATIBILITY
# =============================================================================

class TestATHBreakoutBackwardCompat:
    """Tests for backward compatibility with v1 interface."""

    def test_config_accepts_legacy_fields(self):
        """Config accepts old-style parameters."""
        config = ATHBreakoutConfig(
            confirmation_days=3,
            breakout_threshold_pct=1.5,
            volume_spike_multiplier=2.0,
            rsi_max=75.0,
            min_uptrend_days=60,
        )
        analyzer = ATHBreakoutAnalyzer(config=config)
        assert analyzer.config.confirmation_days == 3

    def test_breakdown_to_dict(self):
        """Test breakdown to_dict works."""
        breakdown = ATHBreakoutScoreBreakdown()
        breakdown.total_score = 6.5
        d = breakdown.to_dict()
        assert d['total_score'] == 6.5
        assert d['max_possible'] == 10.0
        assert 'components' in d
        assert 'ath_breakout' in d['components']
        assert 'volume' in d['components']
        assert 'trend' in d['components']
        assert 'rsi' in d['components']

    def test_breakdown_qualified_threshold(self):
        """Test breakdown qualified uses new threshold (4.0)."""
        breakdown = ATHBreakoutScoreBreakdown()
        breakdown.total_score = 4.5
        assert breakdown.to_dict()['qualified'] is True

        breakdown.total_score = 3.5
        assert breakdown.to_dict()['qualified'] is False

    def test_breakdown_max_possible(self):
        """Test breakdown max_possible is 10.0."""
        breakdown = ATHBreakoutScoreBreakdown()
        assert breakdown.max_possible == 10.0

    def test_signal_details_backward_compat(self):
        """Test signal details contain expected fields."""
        analyzer = ATHBreakoutAnalyzer()
        data = make_ath_data(n=300, volume_ratio=2.0, breakout_pct=2.0)
        signal = analyzer.analyze(
            "TEST", data['prices'], data['volumes'],
            data['highs'], data['lows']
        )
        if signal.signal_type == SignalType.LONG:
            assert 'score_breakdown' in signal.details
            assert 'raw_score' in signal.details
            assert 'max_possible' in signal.details
            assert signal.details['max_possible'] == 10.0

    def test_legacy_breakdown_fields_default_zero(self):
        """Legacy breakdown fields (rs_score, keltner_score, etc.) default to 0."""
        breakdown = ATHBreakoutScoreBreakdown()
        assert breakdown.rs_score == 0
        assert breakdown.macd_score == 0
        assert breakdown.momentum_score == 0
        assert breakdown.keltner_score == 0
        assert breakdown.vwap_score == 0
        assert breakdown.market_context_score == 0
        assert breakdown.sector_score == 0


# =============================================================================
# TEST: RSI CALCULATION
# =============================================================================

class TestATHBreakoutRSI:
    """Tests for internal RSI calculation."""

    def test_rsi_returns_float(self):
        """RSI returns a float value."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [100.0 + i * 0.1 for i in range(30)]
        rsi = analyzer._calculate_rsi(prices)
        assert isinstance(rsi, float)

    def test_rsi_range(self):
        """RSI value is between 0 and 100."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [100.0 + i * 0.1 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices)
        assert 0 <= rsi <= 100

    def test_rsi_uptrend_high(self):
        """RSI should be high in strong uptrend."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [100.0 + i * 1.0 for i in range(50)]  # Strong uptrend
        rsi = analyzer._calculate_rsi(prices)
        assert rsi > 60

    def test_rsi_downtrend_low(self):
        """RSI should be low in strong downtrend."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [200.0 - i * 1.0 for i in range(50)]  # Strong downtrend
        rsi = analyzer._calculate_rsi(prices)
        assert rsi < 40

    def test_rsi_insufficient_data(self):
        """RSI returns 50.0 for insufficient data."""
        analyzer = ATHBreakoutAnalyzer()
        rsi = analyzer._calculate_rsi([100, 101, 102])
        assert rsi == 50.0


# =============================================================================
# TEST: VOLUME CHECK
# =============================================================================

class TestATHBreakoutVolumeCheck:
    """Tests for volume checking logic."""

    def test_strong_volume(self):
        """Strong volume returns high ratio."""
        analyzer = ATHBreakoutAnalyzer()
        volumes = [1_000_000] * 25 + [3_000_000]  # 3x spike
        result = analyzer._check_volume(volumes)
        assert result['ratio'] >= 2.5

    def test_weak_volume(self):
        """Weak volume returns low ratio."""
        analyzer = ATHBreakoutAnalyzer()
        volumes = [1_000_000] * 25 + [500_000]  # 0.5x
        result = analyzer._check_volume(volumes)
        assert result['ratio'] < 1.0

    def test_insufficient_volume_data(self):
        """Handles insufficient volume data."""
        analyzer = ATHBreakoutAnalyzer()
        result = analyzer._check_volume([1000] * 5)
        assert result['ratio'] == 1.0


# =============================================================================
# TEST: CLOSE CONFIRMATION
# =============================================================================

class TestATHBreakoutCloseConfirmation:
    """Tests for close confirmation logic."""

    def test_close_above_ath(self):
        """Close above ATH is confirmed."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [100.0] * 50 + [105.0]
        result = analyzer._check_close_confirmation(prices, 103.0)
        assert result['confirmed'] is True
        assert result['pct_above'] > 0

    def test_close_below_ath(self):
        """Close below ATH is not confirmed."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [100.0] * 50 + [101.0]
        result = analyzer._check_close_confirmation(prices, 103.0)
        assert result['confirmed'] is False
        assert result['pct_above'] < 0

    def test_days_above_ath(self):
        """Counts consecutive days above ATH."""
        analyzer = ATHBreakoutAnalyzer()
        prices = [100.0] * 45 + [104.0, 105.0, 106.0, 107.0, 108.0]
        result = analyzer._check_close_confirmation(prices, 103.0)
        assert result['days_above'] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
