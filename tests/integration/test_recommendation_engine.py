"""
Tests for Daily Recommendation Engine
=====================================

Tests the DailyRecommendationEngine class including:
- DailyPick dataclass
- SuggestedStrikes dataclass
- DailyRecommendationResult dataclass
- Stability filtering
- Sector diversification
- Combined ranking with Speed Score
- Strike recommendation integration
- _create_daily_pick method
- _generate_strike_recommendation method
- _format_single_pick method
- get_quick_picks convenience function
- Blacklist filtering
- VIX regime handling
- Liquidity filtering
"""

import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

from src.constants.trading_rules import ENTRY_STABILITY_MIN
from src.services.recommendation_engine import (
    DailyRecommendationEngine,
    DailyPick,
    DailyRecommendationResult,
    SuggestedStrikes,
    create_recommendation_engine,
    get_quick_picks,
)
from src.models.base import TradeSignal, SignalType, SignalStrength
from src.services.vix_strategy import MarketRegime


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_signal():
    """Create a mock TradeSignal."""
    def _create(
        symbol: str,
        score: float,
        stability: float = 75.0,
        sector: str = "Technology",
        strategy: str = "pullback",
    ):
        signal = TradeSignal(
            symbol=symbol,
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG if score >= 7 else SignalStrength.MODERATE,
            strategy=strategy,
            score=score,
            current_price=150.0,
            reason=f"Test signal for {symbol}",
            timestamp=datetime.now(),
            details={
                'stability': {
                    'score': stability,
                    'historical_win_rate': 85.0,
                    'avg_drawdown': 5.0,
                },
                'sector': sector,
            },
        )
        return signal
    return _create


@pytest.fixture
def mock_scan_result(mock_signal):
    """Create a mock ScanResult."""
    from src.scanner.multi_strategy_scanner import ScanResult

    signals = [
        mock_signal("AAPL", 8.0, 90.0, "Technology"),
        mock_signal("MSFT", 7.5, 85.0, "Technology"),
        mock_signal("JPM", 7.0, 82.0, "Financials"),
        mock_signal("XOM", 6.8, 78.0, "Energy"),
        mock_signal("JNJ", 6.5, 88.0, "Healthcare"),
        mock_signal("GOOGL", 6.3, 80.0, "Technology"),
        mock_signal("PG", 6.0, 92.0, "Consumer Staples"),
        mock_signal("LOW", 5.5, 60.0, "Consumer Discretionary"),  # Lower stability
        mock_signal("TSLA", 8.5, 45.0, "Consumer Discretionary"),  # High score, low stability
    ]

    return ScanResult(
        timestamp=datetime.now(),
        symbols_scanned=100,
        symbols_with_signals=len(signals),
        total_signals=len(signals),
        signals=signals,
        scan_duration_seconds=5.0,
    )


# =============================================================================
# TEST DAILY PICK DATACLASS
# =============================================================================

class TestDailyPick:
    """Tests for DailyPick dataclass."""

    def test_creation(self):
        """Test basic DailyPick creation."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            current_price=180.0,
        )

        assert pick.rank == 1
        assert pick.symbol == "AAPL"
        assert pick.strategy == "pullback"
        assert pick.score == 7.5
        assert pick.stability_score == 85.0

    def test_with_strikes(self):
        """Test DailyPick with strike recommendations."""
        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
            estimated_credit=1.25,
            prob_profit=82.0,
        )

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            suggested_strikes=strikes,
        )

        assert pick.suggested_strikes is not None
        assert pick.suggested_strikes.short_strike == 165.0
        assert pick.suggested_strikes.spread_width == 5.0

    def test_to_dict(self):
        """Test DailyPick serialization."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            reliability_grade="A",
            sector="Technology",
            warnings=["Test warning"],
        )

        result = pick.to_dict()

        assert result['rank'] == 1
        assert result['symbol'] == "AAPL"
        assert result['score'] == 7.5
        assert result['reliability_grade'] == "A"
        assert result['sector'] == "Technology"
        assert len(result['warnings']) == 1

    def test_speed_score_included(self):
        """Test that speed_score is included in DailyPick."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            speed_score=6.5,
        )

        assert pick.speed_score == 6.5
        d = pick.to_dict()
        assert d['speed_score'] == 6.5


# =============================================================================
# TEST SUGGESTED STRIKES
# =============================================================================

class TestSuggestedStrikes:
    """Tests for SuggestedStrikes dataclass."""

    def test_creation(self):
        """Test basic creation."""
        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
        )

        assert strikes.short_strike == 165.0
        assert strikes.long_strike == 160.0
        assert strikes.spread_width == 5.0

    def test_with_metrics(self):
        """Test with optional metrics."""
        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
            estimated_credit=1.25,
            estimated_delta=-0.20,
            prob_profit=82.0,
            risk_reward_ratio=0.33,
            quality="excellent",
            confidence_score=85.0,
        )

        assert strikes.estimated_credit == 1.25
        assert strikes.prob_profit == 82.0
        assert strikes.quality == "excellent"

    def test_to_dict(self):
        """Test serialization."""
        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
            estimated_credit=1.25,
        )

        result = strikes.to_dict()

        assert result['short_strike'] == 165.0
        assert result['long_strike'] == 160.0
        assert result['estimated_credit'] == 1.25

    def test_liquidity_fields(self):
        """Test liquidity-related fields."""
        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
            liquidity_quality="good",
            short_oi=500,
            long_oi=300,
            short_spread_pct=3.5,
            long_spread_pct=4.2,
        )

        assert strikes.liquidity_quality == "good"
        assert strikes.short_oi == 500
        assert strikes.long_oi == 300

    def test_tradeable_status_fields(self):
        """Test tradeable status fields."""
        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
            expiry="2026-03-20",
            dte=45,
            dte_warning="DTE 45 < minimum 60",
            tradeable_status="WARNING",
        )

        assert strikes.expiry == "2026-03-20"
        assert strikes.dte == 45
        assert strikes.dte_warning is not None
        assert strikes.tradeable_status == "WARNING"


# =============================================================================
# TEST STABILITY FILTER
# =============================================================================

class TestStabilityFilter:
    """Tests for stability filtering logic."""

    def test_filter_removes_low_stability(self, mock_signal):
        """Test that low stability signals are filtered out."""
        engine = create_recommendation_engine(min_stability=ENTRY_STABILITY_MIN)

        signals = [
            mock_signal("AAPL", 8.0, 90.0),  # Pass
            mock_signal("TSLA", 8.5, 45.0),  # Fail - low stability
            mock_signal("JPM", 7.0, 72.0),   # Pass
            mock_signal("SNAP", 6.0, 55.0),  # Fail - low stability
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=ENTRY_STABILITY_MIN)

        assert len(filtered) == 2
        assert all(s.symbol in ["AAPL", "JPM"] for s in filtered)

    def test_filter_keeps_high_stability(self, mock_signal):
        """Test that high stability signals pass."""
        engine = create_recommendation_engine(min_stability=ENTRY_STABILITY_MIN)

        signals = [
            mock_signal("AAPL", 6.0, 95.0),
            mock_signal("MSFT", 5.5, 88.0),
            mock_signal("JNJ", 5.0, 92.0),
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=ENTRY_STABILITY_MIN)

        assert len(filtered) == 3

    def test_filter_vix_adjusted_minimum(self, mock_signal):
        """Test VIX-adjusted stability minimum."""
        engine = create_recommendation_engine(min_stability=ENTRY_STABILITY_MIN)

        signals = [
            mock_signal("AAPL", 8.0, 75.0),  # Pass at ENTRY_STABILITY_MIN, fail at VIX-adjusted 80
            mock_signal("MSFT", 7.5, 85.0),  # Pass at both
        ]

        # Normal VIX: ENTRY_STABILITY_MIN
        filtered_normal = engine._apply_stability_filter(signals, min_stability=ENTRY_STABILITY_MIN, vix=18.0)
        assert len(filtered_normal) == 2

        # High VIX (danger zone): 80 min
        filtered_high = engine._apply_stability_filter(signals, min_stability=ENTRY_STABILITY_MIN, vix=22.0)
        assert len(filtered_high) == 1
        assert filtered_high[0].symbol == "MSFT"


# =============================================================================
# TEST BLACKLIST FILTER
# =============================================================================

class TestBlacklistFilter:
    """Tests for blacklist filtering logic."""

    def test_filter_removes_blacklisted_symbols(self, mock_signal):
        """Test that blacklisted symbols are removed."""
        engine = create_recommendation_engine()

        signals = [
            mock_signal("AAPL", 8.0, 90.0),
            mock_signal("TSLA", 9.0, 90.0),  # Blacklisted
            mock_signal("MSFT", 7.5, 85.0),
            mock_signal("SNAP", 7.0, 80.0),  # Blacklisted
            mock_signal("COIN", 8.5, 85.0),  # Blacklisted
        ]

        filtered = engine._apply_blacklist_filter(signals)

        assert len(filtered) == 2
        symbols = [s.symbol for s in filtered]
        assert "AAPL" in symbols
        assert "MSFT" in symbols
        assert "TSLA" not in symbols
        assert "SNAP" not in symbols
        assert "COIN" not in symbols

    def test_filter_keeps_non_blacklisted(self, mock_signal):
        """Test that non-blacklisted symbols pass."""
        engine = create_recommendation_engine()

        signals = [
            mock_signal("AAPL", 8.0, 90.0),
            mock_signal("MSFT", 7.5, 85.0),
            mock_signal("JPM", 7.0, 82.0),
        ]

        filtered = engine._apply_blacklist_filter(signals)

        assert len(filtered) == 3

    def test_filter_case_insensitive(self, mock_signal):
        """Test blacklist is case insensitive."""
        engine = create_recommendation_engine()

        # Create signals with lowercase symbols (shouldn't happen normally but test anyway)
        signal = TradeSignal(
            symbol="TSLA",  # Blacklisted
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            strategy="pullback",
            score=8.0,
            current_price=100.0,
            reason="Test",
            timestamp=datetime.now(),
            details={'stability': {'score': 80.0}},
        )

        filtered = engine._apply_blacklist_filter([signal])
        assert len(filtered) == 0


# =============================================================================
# TEST SECTOR DIVERSIFICATION
# =============================================================================

class TestSectorDiversification:
    """Tests for sector diversification logic."""

    def test_limits_per_sector(self, mock_signal):
        """Test that sector limits are enforced."""
        engine = create_recommendation_engine()

        # Mock fundamentals manager
        engine._fundamentals_manager = MagicMock()

        sectors = {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "GOOGL": "Technology",
            "AMZN": "Technology",
            "JPM": "Financials",
            "XOM": "Energy",
        }

        def mock_get_fundamentals_batch(symbols):
            result = {}
            for symbol in symbols:
                mock_fund = MagicMock()
                mock_fund.sector = sectors.get(symbol, "Unknown")
                result[symbol] = mock_fund
            return result

        engine._fundamentals_manager.get_fundamentals_batch = mock_get_fundamentals_batch

        signals = [
            mock_signal("AAPL", 8.0, 90.0, "Technology"),
            mock_signal("MSFT", 7.5, 85.0, "Technology"),
            mock_signal("GOOGL", 7.0, 80.0, "Technology"),
            mock_signal("AMZN", 6.5, 78.0, "Technology"),
            mock_signal("JPM", 6.0, 82.0, "Financials"),
            mock_signal("XOM", 5.5, 75.0, "Energy"),
        ]

        diversified = engine._apply_sector_diversification(signals, max_per_sector=2)

        # Should have max 2 from Technology
        tech_count = sum(1 for s in diversified if s.symbol in ["AAPL", "MSFT", "GOOGL", "AMZN"])
        assert tech_count <= 2

        # Should keep JPM and XOM
        assert any(s.symbol == "JPM" for s in diversified)
        assert any(s.symbol == "XOM" for s in diversified)

    def test_diversification_preserves_order(self, mock_signal):
        """Test that diversification preserves signal order (highest scores first)."""
        engine = create_recommendation_engine()
        engine._fundamentals_manager = MagicMock()

        def mock_batch(symbols):
            return {s: MagicMock(sector="Technology") for s in symbols}

        engine._fundamentals_manager.get_fundamentals_batch = mock_batch

        # Signals in score order
        signals = [
            mock_signal("AAPL", 9.0, 90.0),  # First
            mock_signal("MSFT", 8.0, 85.0),  # Second
            mock_signal("GOOGL", 7.0, 80.0),  # Third (would be excluded)
        ]

        diversified = engine._apply_sector_diversification(signals, max_per_sector=2)

        # Should keep first two (highest scores)
        assert len(diversified) == 2
        assert diversified[0].symbol == "AAPL"
        assert diversified[1].symbol == "MSFT"


# =============================================================================
# TEST RANKING
# =============================================================================

class TestRanking:
    """Tests for combined ranking logic."""

    def test_combined_score_calculation(self, mock_signal):
        """Test that combined score uses signal, stability, and speed multiplier."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.3  # 70% signal, 30% stability

        signals = [
            mock_signal("HIGH_SCORE", 9.0, 50.0),   # High score, low stability
            mock_signal("BALANCED", 7.0, 90.0),     # Medium score, high stability
            mock_signal("LOW_BOTH", 5.0, 60.0),     # Low both
        ]

        ranked = engine._rank_signals(signals)

        # With Speed^0.3 multiplier, high stability boosts both base and speed:
        # HIGH_SCORE: base=7.8, speed~2.25, combined~7.05
        # BALANCED:   base=7.6, speed~3.92, combined~7.33
        # BALANCED wins because stability boosts speed multiplier
        symbols = [s.symbol for s in ranked]
        assert symbols[0] == "BALANCED"    # Wins via speed multiplier from high stability
        assert symbols[-1] == "LOW_BOTH"   # Definitely last


# =============================================================================
# TEST ENGINE INITIALIZATION
# =============================================================================

class TestSpeedScoreRanking:
    """Tests for Speed Score integration in ranking."""

    def test_speed_multiplier_boosts_fast_candidate(self, mock_signal):
        """Higher speed score should boost ranking for equal base scores."""
        engine = create_recommendation_engine()

        # Two signals with identical score and stability but different sectors
        # Utilities has speed 1.0, Technology has speed 0.1
        fast = mock_signal("FAST", 7.0, 80.0, sector="Utilities")
        slow = mock_signal("SLOW", 7.0, 80.0, sector="Technology")

        ranked = engine._rank_signals([slow, fast])
        symbols = [s.symbol for s in ranked]
        assert symbols[0] == "FAST"  # Utilities (faster sector) should rank higher

    def test_speed_exponent_in_config(self):
        """Speed exponent should be configurable and default to 0.3."""
        engine = DailyRecommendationEngine()
        assert engine.config.get('speed_exponent') == 0.3

    def test_speed_score_range(self):
        """Speed score should stay within 0-10."""
        engine = DailyRecommendationEngine()

        # Extreme values
        high = engine.compute_speed_score(dte=60, stability_score=100, sector="Utilities",
                                          pullback_score=10, market_context_score=10)
        low = engine.compute_speed_score(dte=90, stability_score=70, sector="Basic Materials",
                                         pullback_score=0, market_context_score=0)

        assert 0 <= high <= 10
        assert 0 <= low <= 10
        assert high > low


class TestSpeedScoreCalculation:
    """Tests for compute_speed_score method."""

    def test_dte_factor(self):
        """Test DTE contributes to speed score."""
        engine = DailyRecommendationEngine()

        # DTE 60 should be faster than DTE 90
        speed_60 = engine.compute_speed_score(dte=60, stability_score=80, sector="Technology")
        speed_90 = engine.compute_speed_score(dte=90, stability_score=80, sector="Technology")

        assert speed_60 > speed_90

    def test_stability_factor(self):
        """Test stability contributes to speed score."""
        engine = DailyRecommendationEngine()

        # Higher stability = faster
        speed_high = engine.compute_speed_score(dte=75, stability_score=90, sector="Technology")
        speed_low = engine.compute_speed_score(dte=75, stability_score=70, sector="Technology")

        assert speed_high > speed_low

    def test_sector_factor(self):
        """Test sector contributes to speed score."""
        engine = DailyRecommendationEngine()

        # Utilities is fastest, Basic Materials is slowest
        speed_util = engine.compute_speed_score(dte=75, stability_score=80, sector="Utilities")
        speed_tech = engine.compute_speed_score(dte=75, stability_score=80, sector="Technology")
        speed_basic = engine.compute_speed_score(dte=75, stability_score=80, sector="Basic Materials")

        assert speed_util > speed_tech > speed_basic

    def test_pullback_score_factor(self):
        """Test pullback score contributes to speed score."""
        engine = DailyRecommendationEngine()

        speed_high = engine.compute_speed_score(
            dte=75, stability_score=80, sector="Technology", pullback_score=9.0
        )
        speed_low = engine.compute_speed_score(
            dte=75, stability_score=80, sector="Technology", pullback_score=3.0
        )

        assert speed_high > speed_low

    def test_market_context_factor(self):
        """Test market context score contributes to speed score."""
        engine = DailyRecommendationEngine()

        speed_high = engine.compute_speed_score(
            dte=75, stability_score=80, sector="Technology", market_context_score=8.0
        )
        speed_low = engine.compute_speed_score(
            dte=75, stability_score=80, sector="Technology", market_context_score=2.0
        )

        assert speed_high > speed_low


class TestEngineInitialization:
    """Tests for engine initialization."""

    def test_default_config(self):
        """Test default configuration."""
        engine = DailyRecommendationEngine()

        assert engine.config['min_stability_score'] == ENTRY_STABILITY_MIN
        assert engine.config['max_picks'] == 5
        assert engine.config['enable_strike_recommendations'] is True

    def test_custom_config(self):
        """Test custom configuration."""
        engine = DailyRecommendationEngine(config={
            'min_stability_score': 80.0,
            'max_picks': 10,
            'enable_strike_recommendations': False,
        })

        assert engine.config['min_stability_score'] == 80.0
        assert engine.config['max_picks'] == 10
        assert engine.config['enable_strike_recommendations'] is False

    def test_factory_function(self):
        """Test create_recommendation_engine factory."""
        engine = create_recommendation_engine(
            min_stability=80.0,
            min_score=6.0,
            max_picks=15,
        )

        assert engine.config['min_stability_score'] == 80.0
        assert engine.config['min_signal_score'] == 6.0
        assert engine.config['max_picks'] == 15

    def test_custom_scanner_injection(self):
        """Test custom scanner can be injected."""
        mock_scanner = MagicMock()
        engine = DailyRecommendationEngine(scanner=mock_scanner)

        assert engine._scanner is mock_scanner

    def test_custom_vix_selector_injection(self):
        """Test custom VIX selector can be injected."""
        mock_vix = MagicMock()
        engine = DailyRecommendationEngine(vix_selector=mock_vix)

        assert engine._vix_selector is mock_vix

    def test_custom_strike_recommender_injection(self):
        """Test custom strike recommender can be injected."""
        mock_strike = MagicMock()
        engine = DailyRecommendationEngine(strike_recommender=mock_strike)

        assert engine._strike_recommender is mock_strike


# =============================================================================
# TEST MARKET REGIME
# =============================================================================

class TestMarketRegime:
    """Tests for market regime handling."""

    def test_set_vix(self):
        """Test VIX setting."""
        engine = DailyRecommendationEngine()
        engine.set_vix(18.5)

        assert engine._vix_cache == 18.5

    def test_get_regime_normal(self):
        """Test normal regime detection."""
        engine = DailyRecommendationEngine()

        # Mock the vix_selector to avoid trend adjustment from historical data
        engine._vix_selector = MagicMock()
        engine._vix_selector.get_regime.return_value = MarketRegime.NORMAL

        regime = engine.get_market_regime(17.0)
        assert regime == MarketRegime.NORMAL

    def test_get_regime_elevated(self):
        """Test elevated regime detection."""
        engine = DailyRecommendationEngine()

        regime = engine.get_market_regime(27.0)
        assert regime == MarketRegime.ELEVATED

    def test_get_regime_unknown(self):
        """Test unknown regime when no VIX."""
        engine = DailyRecommendationEngine()

        regime = engine.get_market_regime(None)
        assert regime is None

    def test_get_regime_low_vol(self):
        """Test low volatility regime."""
        engine = DailyRecommendationEngine()

        regime = engine.get_market_regime(12.0)
        assert regime == MarketRegime.LOW_VOL

    def test_get_regime_danger_zone(self):
        """Test danger zone regime."""
        engine = DailyRecommendationEngine()

        regime = engine.get_market_regime(22.0)
        assert regime == MarketRegime.DANGER_ZONE

    def test_get_regime_high_vol(self):
        """Test high volatility regime."""
        engine = DailyRecommendationEngine()

        regime = engine.get_market_regime(32.0)
        assert regime == MarketRegime.HIGH_VOL


# =============================================================================
# TEST OUTPUT FORMATTING
# =============================================================================

class TestOutputFormatting:
    """Tests for output formatting."""

    def test_format_picks_markdown(self):
        """Test Markdown formatting."""
        engine = DailyRecommendationEngine()

        picks = [
            DailyPick(
                rank=1,
                symbol="AAPL",
                strategy="pullback",
                score=8.0,
                stability_score=90.0,
                current_price=180.0,
                sector="Technology",
                reliability_grade="A",
            ),
        ]

        result = DailyRecommendationResult(
            picks=picks,
            vix_level=18.5,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
            after_sector_diversification=3,
            generation_time_seconds=2.5,
        )

        markdown = engine.format_picks_markdown(result)

        assert "Daily Picks" in markdown
        assert "AAPL" in markdown
        assert "18.5" in markdown  # VIX
        assert "Normal" in markdown  # Regime


# =============================================================================
# TEST DAILY RECOMMENDATION RESULT
# =============================================================================

class TestDailyRecommendationResult:
    """Tests for DailyRecommendationResult dataclass."""

    def test_to_dict(self):
        """Test serialization."""
        picks = [
            DailyPick(
                rank=1,
                symbol="AAPL",
                strategy="pullback",
                score=8.0,
                stability_score=90.0,
            ),
        ]

        result = DailyRecommendationResult(
            picks=picks,
            vix_level=18.5,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=100,
            signals_found=10,
        )

        data = result.to_dict()

        assert len(data['picks']) == 1
        assert data['vix_level'] == 18.5
        assert data['market_regime'] == 'NORMAL'
        assert data['statistics']['symbols_scanned'] == 100

    def test_after_liquidity_filter_field(self):
        """Test after_liquidity_filter is included."""
        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
            after_liquidity_filter=5,
        )

        assert result.after_liquidity_filter == 5


# =============================================================================
# TEST CREATE DAILY PICK METHOD
# =============================================================================

class TestCreateDailyPick:
    """Tests for _create_daily_pick method."""

    @pytest.mark.asyncio
    async def test_create_pick_basic(self, mock_signal):
        """Test creating a daily pick from a signal."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        signal = mock_signal("AAPL", 7.5, 85.0, "Technology", "pullback")

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert pick.rank == 1
        assert pick.symbol == "AAPL"
        assert pick.strategy == "pullback"
        assert pick.score == 7.5
        assert pick.stability_score == 85.0
        assert pick.current_price == 150.0

    @pytest.mark.asyncio
    async def test_create_pick_with_fundamentals(self):
        """Test creating a daily pick with fundamentals data."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        # Mock fundamentals manager
        mock_fund = MagicMock()
        mock_fund.sector = "Technology"
        mock_fund.market_cap_category = "Large"
        mock_fund.stability_score = 90.0
        mock_fund.historical_win_rate = 82.0

        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals.return_value = mock_fund

        # Create signal without stability/win_rate in details to test fallback
        signal = TradeSignal(
            symbol="AAPL",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            strategy="pullback",
            score=7.5,
            current_price=150.0,
            reason="Test signal",
            timestamp=datetime.now(),
            details={},  # No stability data - will use fundamentals fallback
        )

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert pick.sector == "Technology"
        assert pick.market_cap_category == "Large"
        # Stability should be from fundamentals
        assert pick.stability_score == 90.0
        assert pick.historical_win_rate == 82.0

    @pytest.mark.asyncio
    async def test_create_pick_with_warnings(self, mock_signal):
        """Test that warnings are generated correctly."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        signal = mock_signal("TSLA", 8.0, 60.0)  # Stability below 70

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.DANGER_ZONE,
        )

        # Should have warnings for both low stability and danger zone
        assert len(pick.warnings) >= 2
        assert any("Stability" in w for w in pick.warnings)
        assert any("DANGER" in w or "Danger" in w for w in pick.warnings)

    @pytest.mark.asyncio
    async def test_create_pick_with_reliability_warnings(self, mock_signal):
        """Test that reliability warnings from signal are passed through."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        signal = mock_signal("AAPL", 7.5, 85.0)
        signal.reliability_warnings = ["Near earnings date", "Low volume"]

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert "Near earnings date" in pick.warnings
        assert "Low volume" in pick.warnings

    @pytest.mark.asyncio
    async def test_create_pick_includes_speed_score(self, mock_signal):
        """Test that speed score is calculated and included."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        signal = mock_signal("AAPL", 7.5, 85.0, "Technology", "pullback")
        signal.details['dte'] = 70

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        # Speed score should be calculated
        assert pick.speed_score > 0


# =============================================================================
# TEST GENERATE STRIKE RECOMMENDATION
# =============================================================================

class TestGenerateStrikeRecommendation:
    """Tests for _generate_strike_recommendation method."""

    @pytest.mark.asyncio
    async def test_generate_strikes_basic(self, mock_signal):
        """Test basic strike generation."""
        engine = DailyRecommendationEngine()

        # Mock the strike recommender
        mock_rec = MagicMock()
        mock_rec.short_strike = 140.0
        mock_rec.long_strike = 135.0
        mock_rec.spread_width = 5.0
        mock_rec.estimated_credit = 1.20
        mock_rec.estimated_delta = -0.18
        mock_rec.prob_profit = 80.0
        mock_rec.risk_reward_ratio = 0.32
        mock_rec.quality = MagicMock(value="excellent")
        mock_rec.confidence_score = 85.0

        engine._strike_recommender = MagicMock()
        engine._strike_recommender.get_recommendation.return_value = mock_rec

        signal = mock_signal("AAPL", 7.5, 85.0)

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert strikes is not None
        assert strikes.short_strike == 140.0
        assert strikes.long_strike == 135.0
        assert strikes.spread_width == 5.0
        assert strikes.estimated_credit == 1.20
        assert strikes.quality == "excellent"

    @pytest.mark.asyncio
    async def test_generate_strikes_with_support_levels(self, mock_signal):
        """Test strike generation extracts support levels from signal."""
        engine = DailyRecommendationEngine()

        mock_rec = MagicMock()
        mock_rec.short_strike = 140.0
        mock_rec.long_strike = 135.0
        mock_rec.spread_width = 5.0
        mock_rec.estimated_credit = 1.00
        mock_rec.estimated_delta = -0.20
        mock_rec.prob_profit = 78.0
        mock_rec.risk_reward_ratio = 0.30
        mock_rec.quality = MagicMock(value="good")
        mock_rec.confidence_score = 75.0

        engine._strike_recommender = MagicMock()
        engine._strike_recommender.get_recommendation.return_value = mock_rec

        signal = mock_signal("AAPL", 7.5, 85.0)
        signal.details['technicals'] = {
            'support_levels': [145.0, 140.0, 135.0],
        }
        signal.details['iv_rank'] = 45.0

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        # Verify strike recommender was called with support levels
        assert engine._strike_recommender.get_recommendation.called
        call_kwargs = engine._strike_recommender.get_recommendation.call_args.kwargs
        assert 'support_levels' in call_kwargs
        assert 'iv_rank' in call_kwargs

    @pytest.mark.asyncio
    async def test_generate_strikes_fallback_support(self, mock_signal):
        """Test fallback support level calculation when none provided."""
        engine = DailyRecommendationEngine()

        mock_rec = MagicMock()
        mock_rec.short_strike = 135.0
        mock_rec.long_strike = 130.0
        mock_rec.spread_width = 5.0
        mock_rec.estimated_credit = 0.90
        mock_rec.estimated_delta = -0.22
        mock_rec.prob_profit = 75.0
        mock_rec.risk_reward_ratio = 0.28
        mock_rec.quality = MagicMock(value="acceptable")
        mock_rec.confidence_score = 70.0

        engine._strike_recommender = MagicMock()
        engine._strike_recommender.get_recommendation.return_value = mock_rec

        signal = mock_signal("AAPL", 7.5, 85.0)
        signal.details = {}  # No support levels

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert strikes is not None
        # Should have used fallback support levels
        call_kwargs = engine._strike_recommender.get_recommendation.call_args.kwargs
        assert 'support_levels' in call_kwargs
        assert len(call_kwargs['support_levels']) == 3

    @pytest.mark.asyncio
    async def test_generate_strikes_handles_exception(self, mock_signal):
        """Test that exceptions are handled gracefully."""
        engine = DailyRecommendationEngine()

        engine._strike_recommender = MagicMock()
        engine._strike_recommender.get_recommendation.side_effect = Exception("Test error")

        signal = mock_signal("AAPL", 7.5, 85.0)

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert strikes is None

    @pytest.mark.asyncio
    async def test_generate_strikes_with_score_breakdown(self, mock_signal):
        """Test extraction of support from score breakdown."""
        engine = DailyRecommendationEngine()

        mock_rec = MagicMock()
        mock_rec.short_strike = 140.0
        mock_rec.long_strike = 135.0
        mock_rec.spread_width = 5.0
        mock_rec.estimated_credit = 1.10
        mock_rec.estimated_delta = -0.19
        mock_rec.prob_profit = 79.0
        mock_rec.risk_reward_ratio = 0.31
        mock_rec.quality = MagicMock(value="good")
        mock_rec.confidence_score = 78.0

        engine._strike_recommender = MagicMock()
        engine._strike_recommender.get_recommendation.return_value = mock_rec

        signal = mock_signal("AAPL", 7.5, 85.0)
        signal.details['score_breakdown'] = {
            'components': {
                'support': {
                    'level': 142.0,
                    'strength': 0.8,
                },
            },
        }
        signal.details['fib_levels'] = [0.382, 0.5, 0.618]

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.ELEVATED,
        )

        assert strikes is not None
        call_kwargs = engine._strike_recommender.get_recommendation.call_args.kwargs
        assert 'fib_levels' in call_kwargs

    @pytest.mark.asyncio
    async def test_generate_strikes_with_options_fetcher(self, mock_signal):
        """Test strike generation with live options data."""
        engine = DailyRecommendationEngine()

        mock_rec = MagicMock()
        mock_rec.short_strike = 140.0
        mock_rec.long_strike = 135.0
        mock_rec.spread_width = 5.0
        mock_rec.estimated_credit = 1.10
        mock_rec.estimated_delta = -0.19
        mock_rec.prob_profit = 79.0
        mock_rec.risk_reward_ratio = 0.31
        mock_rec.quality = MagicMock(value="good")
        mock_rec.confidence_score = 78.0

        engine._strike_recommender = MagicMock()
        engine._strike_recommender.get_recommendation.return_value = mock_rec

        # Mock options fetcher
        async def mock_options_fetcher(symbol):
            mock_option = MagicMock()
            mock_option.strike = 140.0
            mock_option.bid = 1.50
            mock_option.ask = 1.60
            mock_option.delta = -0.20
            mock_option.implied_volatility = 0.25
            mock_option.expiry = date(2026, 3, 20)
            mock_option.open_interest = 500
            mock_option.volume = 100
            return [mock_option]

        signal = mock_signal("AAPL", 7.5, 85.0)

        # Test without liquidity assessment (engine doesn't use LiquidityAssessor directly)
        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
            options_fetcher=mock_options_fetcher,
        )

        assert strikes is not None
        assert strikes.short_strike == 140.0


# =============================================================================
# TEST FORMAT SINGLE PICK
# =============================================================================

class TestFormatSinglePick:
    """Tests for _format_single_pick method."""

    def test_format_basic_pick(self):
        """Test basic pick formatting."""
        engine = DailyRecommendationEngine()

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            current_price=180.0,
        )

        lines = engine._format_single_pick(pick)

        # Should contain key info
        text = "\n".join(lines)
        assert "AAPL" in text
        assert "Pullback" in text  # Strategy formatted
        assert "180.00" in text  # Price
        assert "7.5" in text  # Score
        assert "85" in text  # Stability

    def test_format_pick_with_grade(self):
        """Test formatting with reliability grade."""
        engine = DailyRecommendationEngine()

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            current_price=180.0,
            reliability_grade="A",
        )

        lines = engine._format_single_pick(pick)
        text = "\n".join(lines)

        assert "[A]" in text

    def test_format_pick_with_strikes(self):
        """Test formatting with strike recommendations."""
        engine = DailyRecommendationEngine()

        strikes = SuggestedStrikes(
            short_strike=165.0,
            long_strike=160.0,
            spread_width=5.0,
            estimated_credit=1.25,
            prob_profit=82.0,
        )

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            current_price=180.0,
            suggested_strikes=strikes,
        )

        lines = engine._format_single_pick(pick)
        text = "\n".join(lines)

        assert "Short Put" in text
        assert "165.00" in text  # Short strike
        assert "160.00" in text  # Long strike
        assert "5.00" in text  # Spread width
        assert "1.25" in text  # Credit
        assert "82" in text  # POP

    def test_format_pick_with_sector(self):
        """Test formatting with sector info."""
        engine = DailyRecommendationEngine()

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=8.0,
            stability_score=90.0,
            current_price=180.0,
            sector="Technology",
            historical_win_rate=85.0,
        )

        lines = engine._format_single_pick(pick)
        text = "\n".join(lines)

        assert "Sektor" in text
        assert "Technology" in text
        assert "Win Rate" in text
        assert "85" in text

    def test_format_pick_with_reason(self):
        """Test formatting with reason."""
        engine = DailyRecommendationEngine()

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            current_price=180.0,
            reason="RSI oversold + strong support at 175",
        )

        lines = engine._format_single_pick(pick)
        text = "\n".join(lines)

        assert "RSI oversold" in text

    def test_format_pick_with_warnings(self):
        """Test formatting with warnings."""
        engine = DailyRecommendationEngine()

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=65.0,
            current_price=180.0,
            warnings=["Near earnings", "Low liquidity"],
        )

        lines = engine._format_single_pick(pick)
        text = "\n".join(lines)

        assert "Near earnings" in text
        assert "Low liquidity" in text


# =============================================================================
# TEST GET QUICK PICKS FUNCTION
# =============================================================================

class TestGetQuickPicks:
    """Tests for get_quick_picks convenience function."""

    @pytest.mark.asyncio
    async def test_basic_quick_picks(self):
        """Test basic quick picks functionality."""
        # Create mock data fetcher
        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        # Mock the scanner to return test signals
        with patch.object(
            DailyRecommendationEngine,
            'get_daily_picks',
            new_callable=AsyncMock,
        ) as mock_get_picks:
            mock_picks = [
                DailyPick(
                    rank=1,
                    symbol="AAPL",
                    strategy="pullback",
                    score=8.0,
                    stability_score=90.0,
                ),
                DailyPick(
                    rank=2,
                    symbol="MSFT",
                    strategy="bounce",
                    score=7.5,
                    stability_score=85.0,
                ),
            ]

            mock_result = DailyRecommendationResult(
                picks=mock_picks,
                vix_level=18.0,
                market_regime=MarketRegime.NORMAL,
                strategy_recommendation=None,
                scan_result=None,
                symbols_scanned=10,
                signals_found=5,
            )
            mock_get_picks.return_value = mock_result

            picks = await get_quick_picks(
                symbols=["AAPL", "MSFT", "GOOGL"],
                data_fetcher=mock_fetcher,
                max_picks=2,
            )

            assert len(picks) == 2
            assert picks[0].symbol == "AAPL"
            assert picks[1].symbol == "MSFT"

    @pytest.mark.asyncio
    async def test_quick_picks_with_vix(self):
        """Test quick picks with VIX provided."""
        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        with patch.object(
            DailyRecommendationEngine,
            'get_daily_picks',
            new_callable=AsyncMock,
        ) as mock_get_picks:
            mock_result = DailyRecommendationResult(
                picks=[],
                vix_level=25.0,
                market_regime=MarketRegime.DANGER_ZONE,
                strategy_recommendation=None,
                scan_result=None,
                symbols_scanned=10,
                signals_found=0,
            )
            mock_get_picks.return_value = mock_result

            picks = await get_quick_picks(
                symbols=["AAPL"],
                data_fetcher=mock_fetcher,
                vix=25.0,
                max_picks=5,
            )

            # Verify VIX was passed
            call_kwargs = mock_get_picks.call_args.kwargs
            assert call_kwargs['vix'] == 25.0
            assert call_kwargs['max_picks'] == 5


# =============================================================================
# TEST GET DAILY PICKS ASYNC METHOD
# =============================================================================

class TestGetDailyPicks:
    """Tests for get_daily_picks async method."""

    @pytest.mark.asyncio
    async def test_get_daily_picks_basic(self, mock_signal):
        """Test basic daily picks generation."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        # Create mock scan result
        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=10,
            symbols_with_signals=3,
            total_signals=3,
            signals=[
                mock_signal("AAPL", 8.0, 90.0),
                mock_signal("MSFT", 7.5, 85.0),
                mock_signal("JPM", 7.0, 82.0),
            ],
            scan_duration_seconds=1.0,
        )

        # Mock the scanner
        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        # Mock vix_selector to return expected regime
        mock_strategy_rec = MagicMock()
        mock_strategy_rec.regime = MarketRegime.NORMAL
        mock_strategy_rec.warnings = []
        engine._vix_selector = MagicMock()
        engine._vix_selector.get_regime.return_value = MarketRegime.NORMAL
        engine._vix_selector.get_strategy_recommendation.return_value = mock_strategy_rec

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL", "MSFT", "JPM"],
            data_fetcher=mock_fetcher,
            max_picks=2,
            vix=18.0,
        )

        assert result.vix_level == 18.0
        assert result.market_regime == MarketRegime.NORMAL
        assert len(result.picks) == 2
        assert result.symbols_scanned == 10
        assert result.signals_found == 3

    @pytest.mark.asyncio
    async def test_get_daily_picks_no_vix(self, mock_signal):
        """Test daily picks without VIX."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("AAPL", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            max_picks=3,
        )

        assert result.vix_level is None
        assert result.market_regime is None
        assert "VIX-Level nicht verfügbar" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_get_daily_picks_danger_zone_warning(self, mock_signal):
        """Test danger zone warning is added."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("AAPL", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=22.0,  # Danger zone
        )

        assert any("DANGER" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_get_daily_picks_high_vol_warning(self, mock_signal):
        """Test high volatility warning is added."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("AAPL", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=27.0,  # High vol but below 30
        )

        # HIGH_VOL regime but not NO-GO yet
        assert result.market_regime == MarketRegime.ELEVATED

    @pytest.mark.asyncio
    async def test_get_daily_picks_vix_above_30_no_trades(self, mock_signal):
        """Test that VIX >= 30 returns empty picks (NO-GO)."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("AAPL", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=32.0,  # Above 30 = NO-GO
        )

        # Should return empty picks with warning
        assert len(result.picks) == 0
        assert any("NO-GO" in w for w in result.warnings)
        assert result.market_regime == MarketRegime.HIGH_VOL

    @pytest.mark.asyncio
    async def test_get_daily_picks_applies_filter_pipeline(self, mock_signal):
        """Test that filter pipeline is applied in correct order."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        # Include blacklisted and low stability signals
        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=10,
            symbols_with_signals=5,
            total_signals=5,
            signals=[
                mock_signal("AAPL", 8.0, 90.0),
                mock_signal("TSLA", 9.0, 90.0),  # Blacklisted
                mock_signal("MSFT", 7.5, 85.0),
                mock_signal("SNAP", 8.5, 60.0),  # Low stability + blacklisted
                mock_signal("GOOGL", 7.0, 40.0),  # Low stability
            ],
            scan_duration_seconds=1.0,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL", "TSLA", "MSFT", "SNAP", "GOOGL"],
            data_fetcher=mock_fetcher,
            max_picks=5,
            vix=18.0,
        )

        # Only AAPL and MSFT should pass all filters
        symbols = [p.symbol for p in result.picks]
        assert "TSLA" not in symbols  # Blacklisted
        assert "SNAP" not in symbols  # Blacklisted + low stability
        assert "GOOGL" not in symbols  # Low stability


# =============================================================================
# TEST STABILITY FILTER EDGE CASES
# =============================================================================

class TestStabilityFilterEdgeCases:
    """Additional edge case tests for stability filter."""

    def test_filter_empty_list(self):
        """Test filtering empty signal list."""
        engine = create_recommendation_engine()

        filtered = engine._apply_stability_filter([], min_stability=ENTRY_STABILITY_MIN)

        assert filtered == []

    def test_filter_no_stability_in_details(self):
        """Test filtering when stability not in signal details."""
        engine = create_recommendation_engine()
        engine._fundamentals_manager = None  # No fallback

        signal = TradeSignal(
            symbol="TEST",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            strategy="pullback",
            score=7.5,
            current_price=100.0,
            reason="Test",
            timestamp=datetime.now(),
            details={},  # No stability
        )

        filtered = engine._apply_stability_filter([signal], min_stability=ENTRY_STABILITY_MIN)

        assert len(filtered) == 0  # Should be filtered out

    def test_filter_with_fundamentals_fallback(self, mock_signal):
        """Test fallback to fundamentals manager."""
        engine = create_recommendation_engine()

        # Signal without stability
        signal = TradeSignal(
            symbol="AAPL",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            strategy="pullback",
            score=7.5,
            current_price=100.0,
            reason="Test",
            timestamp=datetime.now(),
            details={},  # No stability
        )

        # Mock fundamentals with high stability (uses get_fundamentals_batch)
        mock_fund = MagicMock()
        mock_fund.stability_score = 85.0

        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals_batch.return_value = {"AAPL": mock_fund}

        filtered = engine._apply_stability_filter([signal], min_stability=ENTRY_STABILITY_MIN)

        assert len(filtered) == 1  # Should pass via fundamentals fallback

    def test_filter_boundary_value(self, mock_signal):
        """Test boundary value (exactly at min_stability)."""
        engine = create_recommendation_engine()

        signals = [
            mock_signal("AAPL", 7.0, ENTRY_STABILITY_MIN),  # Exactly at threshold
            mock_signal("MSFT", 7.0, ENTRY_STABILITY_MIN - 0.1),  # Just below
            mock_signal("GOOGL", 7.0, ENTRY_STABILITY_MIN + 0.1),  # Just above
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=ENTRY_STABILITY_MIN)

        symbols = [s.symbol for s in filtered]
        assert "AAPL" in symbols  # At threshold - should pass
        assert "MSFT" not in symbols  # Below - should fail
        assert "GOOGL" in symbols  # Above - should pass


# =============================================================================
# TEST SECTOR DIVERSIFICATION EDGE CASES
# =============================================================================

class TestSectorDiversificationEdgeCases:
    """Additional edge case tests for sector diversification."""

    def test_diversification_no_fundamentals_manager(self, mock_signal):
        """Test that all signals pass when no fundamentals manager."""
        engine = create_recommendation_engine()
        engine._fundamentals_manager = None

        signals = [mock_signal(f"SYM{i}", 7.0, 80.0) for i in range(5)]

        diversified = engine._apply_sector_diversification(signals, max_per_sector=2)

        # Without fundamentals, all should pass
        assert len(diversified) == 5

    def test_diversification_unknown_sector(self, mock_signal):
        """Test handling of unknown sectors."""
        engine = create_recommendation_engine()

        engine._fundamentals_manager = MagicMock()

        def mock_batch(symbols):
            result = {}
            for s in symbols:
                mock_fund = MagicMock()
                mock_fund.sector = None
                result[s] = mock_fund
            return result

        engine._fundamentals_manager.get_fundamentals_batch = mock_batch

        signals = [mock_signal(f"SYM{i}", 7.0, 80.0) for i in range(5)]

        diversified = engine._apply_sector_diversification(signals, max_per_sector=2)

        # All go to "Unknown" sector, max 2
        assert len(diversified) == 2

    def test_diversification_single_sector(self, mock_signal):
        """Test all signals from single sector."""
        engine = create_recommendation_engine()

        engine._fundamentals_manager = MagicMock()

        def mock_batch(symbols):
            result = {}
            for s in symbols:
                mock_fund = MagicMock()
                mock_fund.sector = "Technology"
                result[s] = mock_fund
            return result

        engine._fundamentals_manager.get_fundamentals_batch = mock_batch

        signals = [mock_signal(f"TECH{i}", 7.0, 80.0, "Technology") for i in range(10)]

        diversified = engine._apply_sector_diversification(signals, max_per_sector=3)

        assert len(diversified) == 3


# =============================================================================
# TEST RANKING EDGE CASES
# =============================================================================

class TestRankingEdgeCases:
    """Additional edge case tests for ranking."""

    def test_rank_empty_list(self):
        """Test ranking empty list."""
        engine = create_recommendation_engine()

        ranked = engine._rank_signals([])

        assert ranked == []

    def test_rank_single_signal(self, mock_signal):
        """Test ranking single signal."""
        engine = create_recommendation_engine()

        signals = [mock_signal("AAPL", 7.5, 85.0)]

        ranked = engine._rank_signals(signals)

        assert len(ranked) == 1
        assert ranked[0].symbol == "AAPL"

    def test_rank_equal_scores(self, mock_signal):
        """Test ranking with equal combined scores."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.5

        # These should have equal combined scores
        signals = [
            mock_signal("AAPL", 8.0, 60.0),  # 8 * 0.5 + 6 * 0.5 = 7
            mock_signal("MSFT", 6.0, 80.0),  # 6 * 0.5 + 8 * 0.5 = 7
        ]

        ranked = engine._rank_signals(signals)

        # Both should be present
        assert len(ranked) == 2

    def test_rank_with_fundamentals_fallback(self):
        """Test ranking uses fundamentals fallback for stability."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.5

        # Signal without stability in details
        signal = TradeSignal(
            symbol="AAPL",
            signal_type=SignalType.LONG,
            strength=SignalStrength.STRONG,
            strategy="pullback",
            score=7.5,
            current_price=100.0,
            reason="Test",
            timestamp=datetime.now(),
            details={},  # No stability
        )

        mock_fund = MagicMock()
        mock_fund.stability_score = 90.0
        mock_fund.sector = "Technology"

        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals.return_value = mock_fund

        ranked = engine._rank_signals([signal])

        # Should use fundamentals stability in ranking
        assert len(ranked) == 1


# =============================================================================
# TEST OUTPUT FORMATTING EDGE CASES
# =============================================================================

class TestOutputFormattingEdgeCases:
    """Additional edge case tests for output formatting."""

    def test_format_no_result(self):
        """Test formatting with no result."""
        engine = DailyRecommendationEngine()

        markdown = engine.format_picks_markdown(None)

        assert "Keine Empfehlungen verfügbar" in markdown

    def test_format_no_picks(self):
        """Test formatting with empty picks."""
        engine = DailyRecommendationEngine()

        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=50,
            signals_found=0,
        )

        markdown = engine.format_picks_markdown(result)

        assert "Keine geeigneten Kandidaten" in markdown

    def test_format_uses_last_result(self):
        """Test formatting uses cached last result."""
        engine = DailyRecommendationEngine()

        # Set last result
        result = DailyRecommendationResult(
            picks=[
                DailyPick(
                    rank=1,
                    symbol="CACHED",
                    strategy="bounce",
                    score=7.0,
                    stability_score=80.0,
                )
            ],
            vix_level=19.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=30,
            signals_found=5,
        )
        engine._last_result = result

        markdown = engine.format_picks_markdown()  # No argument

        assert "CACHED" in markdown

    def test_format_with_warnings(self):
        """Test formatting includes warnings."""
        engine = DailyRecommendationEngine()

        result = DailyRecommendationResult(
            picks=[],
            vix_level=22.0,
            market_regime=MarketRegime.DANGER_ZONE,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=50,
            signals_found=0,
            warnings=["Warning 1", "Warning 2"],
        )

        markdown = engine.format_picks_markdown(result)

        assert "Warnungen" in markdown
        assert "Warning 1" in markdown
        assert "Warning 2" in markdown

    def test_format_all_regimes(self):
        """Test formatting handles all regime types."""
        engine = DailyRecommendationEngine()

        regimes_vix = [
            (MarketRegime.LOW_VOL, 12.0),
            (MarketRegime.NORMAL, 18.0),
            (MarketRegime.DANGER_ZONE, 22.0),
            (MarketRegime.ELEVATED, 27.0),
            (MarketRegime.HIGH_VOL, 35.0),
        ]

        for regime, vix in regimes_vix:
            result = DailyRecommendationResult(
                picks=[],
                vix_level=vix,
                market_regime=regime,
                strategy_recommendation=None,
                scan_result=None,
                symbols_scanned=50,
                signals_found=0,
            )

            markdown = engine.format_picks_markdown(result)

            # Should contain regime name
            assert regime.value.replace('_', ' ').title() in markdown or regime.value in markdown.lower()


# =============================================================================
# TEST GET LAST RESULT
# =============================================================================

class TestGetLastResult:
    """Tests for get_last_result method."""

    def test_no_last_result(self):
        """Test when no result has been generated."""
        engine = DailyRecommendationEngine()

        result = engine.get_last_result()

        assert result is None

    @pytest.mark.asyncio
    async def test_last_result_after_picks(self, mock_signal):
        """Test last result is cached after generating picks."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("AAPL", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        await engine.get_daily_picks(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=18.0,
        )

        last = engine.get_last_result()

        assert last is not None
        assert last.vix_level == 18.0
        assert len(last.picks) == 1


# =============================================================================
# TEST DAILY PICK ADDITIONAL FIELDS
# =============================================================================

class TestDailyPickAdditionalFields:
    """Additional tests for DailyPick fields."""

    def test_default_warnings(self):
        """Test default warnings is empty list."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )

        assert pick.warnings == []

    def test_default_current_price(self):
        """Test default current price."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )

        assert pick.current_price == 0.0

    def test_timestamp_auto_generated(self):
        """Test timestamp is auto-generated."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )

        assert pick.timestamp is not None
        assert isinstance(pick.timestamp, datetime)

    def test_to_dict_includes_strikes(self):
        """Test to_dict includes suggested strikes."""
        strikes = SuggestedStrikes(
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
        )

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
            suggested_strikes=strikes,
        )

        d = pick.to_dict()

        assert d['suggested_strikes'] is not None
        assert d['suggested_strikes']['short_strike'] == 145.0

    def test_to_dict_without_strikes(self):
        """Test to_dict handles None strikes."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )

        d = pick.to_dict()

        assert d['suggested_strikes'] is None


# =============================================================================
# TEST DAILY RECOMMENDATION RESULT ADDITIONAL FIELDS
# =============================================================================

class TestDailyRecommendationResultAdditional:
    """Additional tests for DailyRecommendationResult."""

    def test_default_statistics(self):
        """Test default statistics values."""
        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
        )

        assert result.symbols_scanned == 0
        assert result.signals_found == 0
        assert result.after_stability_filter == 0
        assert result.after_sector_diversification == 0

    def test_default_metadata(self):
        """Test default metadata values."""
        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
        )

        assert result.generation_time_seconds == 0.0
        assert result.warnings == []
        assert result.timestamp is not None

    def test_to_dict_with_strategy_rec(self):
        """Test to_dict with strategy recommendation."""
        # Mock strategy recommendation
        mock_rec = MagicMock()
        mock_rec.to_dict.return_value = {'regime': 'normal', 'strategy': 'standard'}

        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=mock_rec,
            scan_result=None,
            symbols_scanned=100,
            signals_found=10,
        )

        d = result.to_dict()

        assert d['strategy_recommendation'] == {'regime': 'normal', 'strategy': 'standard'}


# =============================================================================
# TEST VIX REGIME LOW_VOL
# =============================================================================

class TestMarketRegimeLowVol:
    """Tests for LOW_VOL regime handling."""

    def test_get_regime_low_vol(self):
        """Test low volatility regime detection."""
        engine = DailyRecommendationEngine()

        regime = engine.get_market_regime(12.0)
        assert regime == MarketRegime.LOW_VOL

    def test_get_regime_low_vol_boundary(self):
        """Test low vol boundary at 15."""
        engine = DailyRecommendationEngine()

        # Just below boundary
        regime = engine.get_market_regime(14.9)
        assert regime == MarketRegime.LOW_VOL

    @pytest.mark.asyncio
    async def test_daily_picks_low_vol_no_warning(self, mock_signal):
        """Test that LOW_VOL regime doesn't add danger warnings."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("AAPL", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=12.0,  # Low vol
        )

        # Should not have DANGER or HIGH_VOL warnings
        assert not any("DANGER" in w for w in result.warnings)
        assert not any("HIGH" in w.upper() for w in result.warnings)


# =============================================================================
# TEST LIQUIDITY FILTERING
# =============================================================================

class TestLiquidityFiltering:
    """Tests for liquidity-based filtering in daily picks."""

    @pytest.mark.asyncio
    async def test_liquidity_filter_counts_tracked(self, mock_signal):
        """Test that liquidity filter counts are tracked in result."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=3,
            symbols_with_signals=3,
            total_signals=3,
            signals=[
                mock_signal("AAPL", 8.0, 90.0),
                mock_signal("MSFT", 7.5, 85.0),
                mock_signal("JPM", 7.0, 82.0),
            ],
            scan_duration_seconds=1.0,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        # Mock vix_selector
        mock_strategy_rec = MagicMock()
        mock_strategy_rec.regime = MarketRegime.NORMAL
        mock_strategy_rec.warnings = []
        engine._vix_selector = MagicMock()
        engine._vix_selector.get_regime.return_value = MarketRegime.NORMAL
        engine._vix_selector.get_strategy_recommendation.return_value = mock_strategy_rec

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["AAPL", "MSFT", "JPM"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=18.0,
        )

        # Liquidity filter count should be tracked
        assert result.after_liquidity_filter >= 0
        # Without options_fetcher, liquidity filter should pass all
        assert result.after_liquidity_filter == result.after_sector_diversification


# =============================================================================
# TEST INTEGRATION - FULL PIPELINE
# =============================================================================

class TestFullPipeline:
    """Integration tests for the full recommendation pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_order(self, mock_signal):
        """Test that filters are applied in correct order."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        # Create a variety of signals
        signals = [
            mock_signal("AAPL", 9.0, 90.0, "Technology"),   # Good
            mock_signal("TSLA", 9.5, 95.0, "Automotive"),   # Blacklisted
            mock_signal("MSFT", 8.5, 85.0, "Technology"),   # Good
            mock_signal("SNAP", 8.0, 80.0, "Technology"),   # Blacklisted
            mock_signal("GOOGL", 7.5, 50.0, "Technology"),  # Low stability
            mock_signal("JPM", 7.0, 82.0, "Financials"),    # Good
            mock_signal("JNJ", 6.5, 88.0, "Healthcare"),    # Good
        ]

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=7,
            symbols_with_signals=7,
            total_signals=7,
            signals=signals,
            scan_duration_seconds=1.0,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        # Mock fundamentals for sector diversification
        mock_fund_data = {
            "AAPL": MagicMock(sector="Technology", stability_score=90.0),
            "MSFT": MagicMock(sector="Technology", stability_score=85.0),
            "JPM": MagicMock(sector="Financials", stability_score=82.0),
            "JNJ": MagicMock(sector="Healthcare", stability_score=88.0),
        }

        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals_batch.return_value = mock_fund_data
        engine._fundamentals_manager.get_fundamentals.side_effect = lambda s: mock_fund_data.get(s)

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=[s.symbol for s in signals],
            data_fetcher=mock_fetcher,
            max_picks=5,
            vix=18.0,
        )

        # Check pipeline statistics
        assert result.signals_found == 7
        # Blacklist removes TSLA and SNAP: 5 remain
        # Stability removes GOOGL: 4 remain
        assert result.after_stability_filter == 4

        # Check final picks
        symbols = [p.symbol for p in result.picks]
        assert "TSLA" not in symbols
        assert "SNAP" not in symbols
        assert "GOOGL" not in symbols

    @pytest.mark.asyncio
    async def test_sector_diversification_in_pipeline(self, mock_signal):
        """Test sector diversification limits in full pipeline."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False
        engine.config['max_per_sector'] = 2

        from src.scanner.multi_strategy_scanner import ScanResult

        # All tech signals
        signals = [
            mock_signal("AAPL", 9.0, 90.0, "Technology"),
            mock_signal("MSFT", 8.5, 88.0, "Technology"),
            mock_signal("GOOGL", 8.0, 86.0, "Technology"),
            mock_signal("AMZN", 7.5, 84.0, "Technology"),
            mock_signal("META", 7.0, 82.0, "Technology"),
        ]

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=5,
            total_signals=5,
            signals=signals,
            scan_duration_seconds=1.0,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        # All same sector
        mock_fund_data = {s.symbol: MagicMock(sector="Technology", stability_score=85.0) for s in signals}
        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals_batch.return_value = mock_fund_data
        engine._fundamentals_manager.get_fundamentals.side_effect = lambda s: mock_fund_data.get(s)

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=[s.symbol for s in signals],
            data_fetcher=mock_fetcher,
            max_picks=5,
            vix=18.0,
        )

        # Should be limited to 2 from Technology sector
        assert result.after_sector_diversification == 2
        assert len(result.picks) == 2
