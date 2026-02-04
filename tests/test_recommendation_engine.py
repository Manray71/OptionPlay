"""
Tests for Daily Recommendation Engine
=====================================

Tests the DailyRecommendationEngine class including:
- DailyPick dataclass
- Stability filtering
- Sector diversification
- Combined ranking
- Strike recommendation integration
- _create_daily_pick method
- _generate_strike_recommendation method
- _format_single_pick method
- get_quick_picks convenience function
"""

import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

from src.services.recommendation_engine import (
    DailyRecommendationEngine,
    DailyPick,
    DailyRecommendationResult,
    SuggestedStrikes,
    create_recommendation_engine,
    get_quick_picks,
)
from src.models.base import TradeSignal, SignalType, SignalStrength
from src.vix_strategy import MarketRegime


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


# =============================================================================
# TEST STABILITY FILTER
# =============================================================================

class TestStabilityFilter:
    """Tests for stability filtering logic."""

    def test_filter_removes_low_stability(self, mock_signal):
        """Test that low stability signals are filtered out."""
        engine = create_recommendation_engine(min_stability=70.0)

        signals = [
            mock_signal("AAPL", 8.0, 90.0),  # Pass
            mock_signal("TSLA", 8.5, 45.0),  # Fail - low stability
            mock_signal("JPM", 7.0, 72.0),   # Pass
            mock_signal("SNAP", 6.0, 55.0),  # Fail - low stability
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=70.0)

        assert len(filtered) == 2
        assert all(s.symbol in ["AAPL", "JPM"] for s in filtered)

    def test_filter_keeps_high_stability(self, mock_signal):
        """Test that high stability signals pass."""
        engine = create_recommendation_engine(min_stability=70.0)

        signals = [
            mock_signal("AAPL", 6.0, 95.0),
            mock_signal("MSFT", 5.5, 88.0),
            mock_signal("JNJ", 5.0, 92.0),
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=70.0)

        assert len(filtered) == 3


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
        # HIGH_SCORE: base=7.8, speed≈2.25, combined≈7.05
        # BALANCED:   base=7.6, speed≈3.92, combined≈7.33
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


class TestEngineInitialization:
    """Tests for engine initialization."""

    def test_default_config(self):
        """Test default configuration."""
        engine = DailyRecommendationEngine()

        assert engine.config['min_stability_score'] == 70.0
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
        assert regime == MarketRegime.UNKNOWN


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
        assert data['market_regime'] == 'normal'
        assert data['statistics']['symbols_scanned'] == 100


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
        assert "🟢" in text  # Grade A gets green badge

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
            strategy="ath_breakout",
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

        assert "Begründung" in text
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
            warnings=["⚠️ Near earnings", "⚠️ Low liquidity"],
        )

        lines = engine._format_single_pick(pick)
        text = "\n".join(lines)

        assert "Near earnings" in text
        assert "Low liquidity" in text

    def test_format_pick_grade_colors(self):
        """Test grade color mapping."""
        engine = DailyRecommendationEngine()

        grades_colors = {
            'A': '🟢',
            'B': '🟢',
            'C': '🟡',
            'D': '🟠',
            'F': '🔴',
        }

        for grade, expected_color in grades_colors.items():
            pick = DailyPick(
                rank=1,
                symbol="TEST",
                strategy="pullback",
                score=7.0,
                stability_score=80.0,
                reliability_grade=grade,
            )

            lines = engine._format_single_pick(pick)
            text = "\n".join(lines)

            assert expected_color in text, f"Grade {grade} should have color {expected_color}"


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
        assert result.market_regime == MarketRegime.UNKNOWN
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
            vix=35.0,  # High volatility
        )

        assert any("VOLATILITY" in w.upper() for w in result.warnings)


# =============================================================================
# TEST STABILITY FILTER EDGE CASES
# =============================================================================

class TestStabilityFilterEdgeCases:
    """Additional edge case tests for stability filter."""

    def test_filter_empty_list(self):
        """Test filtering empty signal list."""
        engine = create_recommendation_engine()

        filtered = engine._apply_stability_filter([], min_stability=70.0)

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

        filtered = engine._apply_stability_filter([signal], min_stability=70.0)

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

        filtered = engine._apply_stability_filter([signal], min_stability=70.0)

        assert len(filtered) == 1  # Should pass via fundamentals fallback

    def test_filter_boundary_value(self, mock_signal):
        """Test boundary value (exactly at min_stability)."""
        engine = create_recommendation_engine()

        signals = [
            mock_signal("AAPL", 7.0, 70.0),  # Exactly at threshold
            mock_signal("MSFT", 7.0, 69.9),  # Just below
            mock_signal("GOOGL", 7.0, 70.1),  # Just above
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=70.0)

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
            vix=12.0,  # Low volatility
        )

        # Should NOT have DANGER or HIGH VOLATILITY warnings
        assert not any("DANGER" in w for w in result.warnings)
        assert not any("VOLATILITY" in w.upper() for w in result.warnings)
        assert result.market_regime == MarketRegime.LOW_VOL


# =============================================================================
# TEST SCORE BREAKDOWN SUPPORT EXTRACTION
# =============================================================================

class TestScoreBreakdownExtraction:
    """Tests for support level extraction from score_breakdown."""

    @pytest.mark.asyncio
    async def test_extract_support_from_score_breakdown(self, mock_signal):
        """Test extraction of support level from score_breakdown."""
        engine = DailyRecommendationEngine()

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
        # Add score_breakdown with support component
        signal.details['score_breakdown'] = {
            'components': {
                'support': {
                    'level': 145.50,
                    'strength': 0.85,
                    'distance_pct': 3.0,
                },
            },
        }

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        # Verify support level was extracted
        call_kwargs = engine._strike_recommender.get_recommendation.call_args.kwargs
        assert 145.50 in call_kwargs['support_levels']

    @pytest.mark.asyncio
    async def test_extract_support_from_both_sources(self, mock_signal):
        """Test extraction combines score_breakdown and technicals."""
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
        signal.details['score_breakdown'] = {
            'components': {
                'support': {
                    'level': 148.0,
                },
            },
        }
        signal.details['technicals'] = {
            'support_levels': [145.0, 140.0],
        }

        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        call_kwargs = engine._strike_recommender.get_recommendation.call_args.kwargs
        # Both support levels should be included
        assert 148.0 in call_kwargs['support_levels']
        assert 145.0 in call_kwargs['support_levels']
        assert 140.0 in call_kwargs['support_levels']

    @pytest.mark.asyncio
    async def test_score_breakdown_dict_not_dict(self, mock_signal):
        """Test handling when score_breakdown.components is not a dict."""
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
        signal.details['score_breakdown'] = "not a dict"  # Invalid format

        # Should not raise, should use fallback
        strikes = await engine._generate_strike_recommendation(
            symbol="AAPL",
            current_price=150.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        assert strikes is not None


# =============================================================================
# TEST CONFIG MERGE BEHAVIOR
# =============================================================================

class TestConfigMerge:
    """Tests for configuration merge behavior."""

    def test_partial_config_merge(self):
        """Test that partial config merges with defaults."""
        engine = DailyRecommendationEngine(config={
            'min_stability_score': 80.0,
            # max_picks not specified - should use default
        })

        assert engine.config['min_stability_score'] == 80.0
        assert engine.config['max_picks'] == 5  # Default preserved
        assert engine.config['enable_strike_recommendations'] is True  # Default preserved

    def test_empty_config_uses_defaults(self):
        """Test that empty config uses all defaults."""
        engine = DailyRecommendationEngine(config={})

        assert engine.config['min_stability_score'] == 70.0
        assert engine.config['max_picks'] == 5
        assert engine.config['stability_weight'] == 0.3

    def test_config_none_uses_defaults(self):
        """Test that None config uses all defaults."""
        engine = DailyRecommendationEngine(config=None)

        assert engine.config['min_stability_score'] == 70.0
        assert engine.config['enable_sector_diversification'] is True


# =============================================================================
# TEST SCANNER INJECTION
# =============================================================================

class TestScannerInjection:
    """Tests for injected scanner usage."""

    @pytest.mark.asyncio
    async def test_uses_injected_scanner(self, mock_signal):
        """Test that injected scanner is used."""
        mock_scanner = MagicMock()
        mock_scanner.set_vix = MagicMock()

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=5,
            symbols_with_signals=1,
            total_signals=1,
            signals=[mock_signal("INJECTED", 8.0, 90.0)],
            scan_duration_seconds=0.5,
        )
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan)

        engine = DailyRecommendationEngine(scanner=mock_scanner)
        engine.config['enable_strike_recommendations'] = False

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["TEST"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=18.0,
        )

        # Verify our injected scanner was used
        mock_scanner.scan_async.assert_called_once()
        assert len(result.picks) == 1
        assert result.picks[0].symbol == "INJECTED"

    def test_creates_scanner_when_none_injected(self):
        """Test that scanner is created when none injected."""
        engine = DailyRecommendationEngine()

        assert engine._scanner is not None


# =============================================================================
# TEST STABILITY WEIGHT EDGE CASES
# =============================================================================

class TestStabilityWeightEdgeCases:
    """Tests for stability_weight edge cases."""

    def test_stability_weight_zero(self, mock_signal):
        """Test with stability_weight = 0 (100% signal score)."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.0

        signals = [
            mock_signal("HIGH_SCORE", 9.0, 50.0),  # High score, low stability
            mock_signal("LOW_SCORE", 5.0, 100.0),  # Low score, high stability
        ]

        ranked = engine._rank_signals(signals)

        # With weight=0, only signal score matters
        assert ranked[0].symbol == "HIGH_SCORE"
        assert ranked[1].symbol == "LOW_SCORE"

    def test_stability_weight_one(self, mock_signal):
        """Test with stability_weight = 1.0 (100% stability)."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 1.0

        signals = [
            mock_signal("HIGH_SCORE", 9.0, 50.0),  # High score, low stability
            mock_signal("HIGH_STAB", 5.0, 100.0),   # Low score, high stability
        ]

        ranked = engine._rank_signals(signals)

        # With weight=1, only stability matters
        assert ranked[0].symbol == "HIGH_STAB"
        assert ranked[1].symbol == "HIGH_SCORE"

    def test_stability_weight_half(self, mock_signal):
        """Test with stability_weight = 0.5 (equal weight)."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.5

        # These have equal combined scores with weight=0.5:
        # AAPL: 8.0 * 0.5 + 6.0 * 0.5 = 7.0
        # MSFT: 6.0 * 0.5 + 8.0 * 0.5 = 7.0
        signals = [
            mock_signal("AAPL", 8.0, 60.0),
            mock_signal("MSFT", 6.0, 80.0),
        ]

        ranked = engine._rank_signals(signals)

        # Both should be present with equal scores
        assert len(ranked) == 2


# =============================================================================
# TEST HIGH_VOL REGIME IN CREATE DAILY PICK
# =============================================================================

class TestCreateDailyPickHighVol:
    """Tests for HIGH_VOL regime handling in _create_daily_pick."""

    @pytest.mark.asyncio
    async def test_create_pick_high_vol_no_extra_warning(self, mock_signal):
        """Test that HIGH_VOL doesn't add separate pick-level warning."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        signal = mock_signal("AAPL", 8.0, 90.0)  # High stability

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.HIGH_VOL,
        )

        # HIGH_VOL should not add a specific warning at pick level
        # (it's handled at result level)
        # Only stability-related warnings should appear if stability < 70
        assert not any("HIGH" in w and "VOL" in w for w in pick.warnings)

    @pytest.mark.asyncio
    async def test_create_pick_danger_zone_adds_warning(self, mock_signal):
        """Test that DANGER_ZONE adds warning to pick."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        signal = mock_signal("AAPL", 8.0, 90.0)

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.DANGER_ZONE,
        )

        # DANGER_ZONE should add a warning
        assert any("Danger" in w or "DANGER" in w for w in pick.warnings)


# =============================================================================
# TEST SET_VIX PROPAGATION
# =============================================================================

class TestSetVixPropagation:
    """Tests for VIX setting propagation."""

    def test_set_vix_updates_cache(self):
        """Test that set_vix updates internal cache."""
        engine = DailyRecommendationEngine()

        engine.set_vix(25.5)

        assert engine._vix_cache == 25.5

    def test_set_vix_propagates_to_scanner(self):
        """Test that set_vix propagates to scanner."""
        mock_scanner = MagicMock()
        mock_scanner.set_vix = MagicMock()

        engine = DailyRecommendationEngine(scanner=mock_scanner)
        engine.set_vix(22.0)

        mock_scanner.set_vix.assert_called_once_with(22.0)

    def test_get_regime_uses_cache(self):
        """Test that get_market_regime uses cached VIX."""
        engine = DailyRecommendationEngine()
        engine._vix_cache = 27.0

        regime = engine.get_market_regime()  # No argument

        assert regime == MarketRegime.ELEVATED


# =============================================================================
# TEST SUGGESTED STRIKES DEFAULTS
# =============================================================================

class TestSuggestedStrikesDefaults:
    """Tests for SuggestedStrikes default values."""

    def test_default_quality(self):
        """Test default quality value."""
        strikes = SuggestedStrikes(
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
        )

        assert strikes.quality == "good"

    def test_default_confidence_score(self):
        """Test default confidence_score value."""
        strikes = SuggestedStrikes(
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
        )

        assert strikes.confidence_score == 0.0

    def test_all_optional_fields_none(self):
        """Test all optional fields can be None."""
        strikes = SuggestedStrikes(
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
        )

        assert strikes.estimated_credit is None
        assert strikes.estimated_delta is None
        assert strikes.prob_profit is None
        assert strikes.risk_reward_ratio is None


# =============================================================================
# TEST VIX SELECTOR INJECTION
# =============================================================================

class TestVixSelectorInjection:
    """Tests for VIX selector injection."""

    def test_uses_injected_vix_selector(self):
        """Test that injected VIX selector is used."""
        mock_selector = MagicMock()
        mock_selector.get_regime.return_value = MarketRegime.ELEVATED

        engine = DailyRecommendationEngine(vix_selector=mock_selector)
        regime = engine.get_market_regime(25.0)

        mock_selector.get_regime.assert_called_once_with(25.0)
        assert regime == MarketRegime.ELEVATED

    def test_creates_vix_selector_when_none_injected(self):
        """Test that VIX selector is created when none injected."""
        engine = DailyRecommendationEngine()

        assert engine._vix_selector is not None


# =============================================================================
# TEST STRIKE RECOMMENDER INJECTION
# =============================================================================

class TestStrikeRecommenderInjection:
    """Tests for strike recommender injection."""

    @pytest.mark.asyncio
    async def test_uses_injected_strike_recommender(self, mock_signal):
        """Test that injected strike recommender is used."""
        mock_recommender = MagicMock()
        mock_rec = MagicMock()
        mock_rec.short_strike = 999.0
        mock_rec.long_strike = 990.0
        mock_rec.spread_width = 9.0
        mock_rec.estimated_credit = 9.99
        mock_rec.estimated_delta = -0.99
        mock_rec.prob_profit = 99.0
        mock_rec.risk_reward_ratio = 0.99
        mock_rec.quality = MagicMock(value="test_quality")
        mock_rec.confidence_score = 99.0
        mock_recommender.get_recommendation.return_value = mock_rec

        engine = DailyRecommendationEngine(strike_recommender=mock_recommender)

        signal = mock_signal("TEST", 7.5, 85.0)

        strikes = await engine._generate_strike_recommendation(
            symbol="TEST",
            current_price=1000.0,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        mock_recommender.get_recommendation.assert_called_once()
        assert strikes.short_strike == 999.0
        assert strikes.quality == "test_quality"


# =============================================================================
# TEST FUNDAMENTALS MANAGER UNAVAILABLE
# =============================================================================

class TestFundamentalsManagerUnavailable:
    """Tests for handling unavailable fundamentals manager."""

    def test_stability_filter_without_fundamentals(self, mock_signal):
        """Test stability filter works without fundamentals manager."""
        engine = create_recommendation_engine()
        engine._fundamentals_manager = None

        signals = [
            mock_signal("AAPL", 8.0, 90.0),  # Has stability in details
            mock_signal("MSFT", 7.5, 85.0),
        ]

        filtered = engine._apply_stability_filter(signals, min_stability=70.0)

        # Should still filter based on signal details
        assert len(filtered) == 2

    def test_ranking_without_fundamentals(self, mock_signal):
        """Test ranking works without fundamentals manager."""
        engine = create_recommendation_engine()
        engine._fundamentals_manager = None

        signals = [
            mock_signal("AAPL", 8.0, 90.0),
            mock_signal("MSFT", 7.5, 85.0),
        ]

        ranked = engine._rank_signals(signals)

        # Should rank based on signal details only
        assert len(ranked) == 2

    @pytest.mark.asyncio
    async def test_create_pick_without_fundamentals(self, mock_signal):
        """Test pick creation without fundamentals manager."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False
        engine._fundamentals_manager = None

        signal = mock_signal("AAPL", 8.0, 85.0)

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        # Should create pick with None for sector/market_cap
        assert pick.sector is None
        assert pick.market_cap_category is None


# =============================================================================
# TEST DAILY PICK TIMESTAMP PRECISION
# =============================================================================

class TestDailyPickTimestamp:
    """Tests for DailyPick timestamp handling."""

    def test_timestamp_is_recent(self):
        """Test that auto-generated timestamp is recent."""
        before = datetime.now()
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )
        after = datetime.now()

        assert before <= pick.timestamp <= after

    def test_to_dict_timestamp_format(self):
        """Test that timestamp is ISO formatted in to_dict."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )

        d = pick.to_dict()

        # Should be ISO format string
        assert isinstance(d['timestamp'], str)
        # Should be parseable
        parsed = datetime.fromisoformat(d['timestamp'])
        assert parsed is not None


# =============================================================================
# TEST DAILY RECOMMENDATION RESULT TIMESTAMP
# =============================================================================

class TestDailyRecommendationResultTimestamp:
    """Tests for DailyRecommendationResult timestamp handling."""

    def test_timestamp_is_recent(self):
        """Test that auto-generated timestamp is recent."""
        before = datetime.now()
        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
        )
        after = datetime.now()

        assert before <= result.timestamp <= after

    def test_to_dict_timestamp_format(self):
        """Test that timestamp is ISO formatted in to_dict."""
        result = DailyRecommendationResult(
            picks=[],
            vix_level=18.0,
            market_regime=MarketRegime.NORMAL,
            strategy_recommendation=None,
            scan_result=None,
        )

        d = result.to_dict()

        assert isinstance(d['timestamp'], str)
        parsed = datetime.fromisoformat(d['timestamp'])
        assert parsed is not None


# =============================================================================
# TEST REGIME EMOJI MAPPING
# =============================================================================

class TestRegimeEmojiMapping:
    """Tests for regime emoji mapping in formatting."""

    def test_format_low_vol_emoji(self):
        """Test LOW_VOL gets green emoji."""
        engine = DailyRecommendationEngine()

        result = DailyRecommendationResult(
            picks=[],
            vix_level=12.0,
            market_regime=MarketRegime.LOW_VOL,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=50,
            signals_found=0,
        )

        markdown = engine.format_picks_markdown(result)

        assert "🟢" in markdown

    def test_format_danger_zone_emoji(self):
        """Test DANGER_ZONE gets yellow emoji."""
        engine = DailyRecommendationEngine()

        result = DailyRecommendationResult(
            picks=[],
            vix_level=22.0,
            market_regime=MarketRegime.DANGER_ZONE,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=50,
            signals_found=0,
        )

        markdown = engine.format_picks_markdown(result)

        assert "🟡" in markdown

    def test_format_high_vol_emoji(self):
        """Test HIGH_VOL gets red emoji."""
        engine = DailyRecommendationEngine()

        result = DailyRecommendationResult(
            picks=[],
            vix_level=35.0,
            market_regime=MarketRegime.HIGH_VOL,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=50,
            signals_found=0,
        )

        markdown = engine.format_picks_markdown(result)

        assert "🔴" in markdown


# =============================================================================
# TEST FORMAT WITHOUT VIX
# =============================================================================

class TestFormatWithoutVix:
    """Tests for formatting without VIX data."""

    def test_format_no_vix_level(self):
        """Test formatting when VIX level is None."""
        engine = DailyRecommendationEngine()

        result = DailyRecommendationResult(
            picks=[],
            vix_level=None,
            market_regime=MarketRegime.UNKNOWN,
            strategy_recommendation=None,
            scan_result=None,
            symbols_scanned=50,
            signals_found=0,
        )

        markdown = engine.format_picks_markdown(result)

        # Should not crash, should contain basic structure
        assert "Daily Picks" in markdown
        # Should not contain VIX formatting
        assert "VIX:" not in markdown


# =============================================================================
# TEST MULTIPLE PICKS RANKING ORDER
# =============================================================================

class TestMultiplePicksRankingOrder:
    """Tests for multiple picks ranking order."""

    @pytest.mark.asyncio
    async def test_picks_are_ranked_correctly(self, mock_signal):
        """Test that picks maintain correct ranking order."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False
        engine.config['stability_weight'] = 0.0  # Pure signal score ranking
        engine.config['enable_sector_diversification'] = False  # Focus on ranking only

        from src.scanner.multi_strategy_scanner import ScanResult

        # Create signals with different scores and different sectors
        signals = [
            mock_signal("THIRD", 6.0, 90.0, "Energy"),
            mock_signal("FIRST", 9.0, 90.0, "Technology"),
            mock_signal("SECOND", 7.5, 90.0, "Financials"),
        ]

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=3,
            symbols_with_signals=3,
            total_signals=3,
            signals=signals,
            scan_duration_seconds=0.5,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["TEST"],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=18.0,
        )

        # Verify ranking order
        assert result.picks[0].symbol == "FIRST"
        assert result.picks[0].rank == 1
        assert result.picks[1].symbol == "SECOND"
        assert result.picks[1].rank == 2
        assert result.picks[2].symbol == "THIRD"
        assert result.picks[2].rank == 3


# =============================================================================
# TEST EMPTY SYMBOL LIST
# =============================================================================

class TestEmptySymbolList:
    """Tests for handling empty symbol list."""

    @pytest.mark.asyncio
    async def test_empty_symbols_returns_empty_picks(self):
        """Test that empty symbol list returns empty picks."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False

        from src.scanner.multi_strategy_scanner import ScanResult

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=0,
            symbols_with_signals=0,
            total_signals=0,
            signals=[],
            scan_duration_seconds=0.1,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return []

        result = await engine.get_daily_picks(
            symbols=[],
            data_fetcher=mock_fetcher,
            max_picks=3,
            vix=18.0,
        )

        assert len(result.picks) == 0
        assert result.symbols_scanned == 0
        assert result.signals_found == 0


# =============================================================================
# TEST MAX PICKS LIMIT
# =============================================================================

class TestMaxPicksLimit:
    """Tests for max_picks limit enforcement."""

    @pytest.mark.asyncio
    async def test_max_picks_limits_output(self, mock_signal):
        """Test that max_picks limits the output."""
        engine = DailyRecommendationEngine()
        engine.config['enable_strike_recommendations'] = False
        engine.config['max_per_sector'] = 10  # Disable sector limit for this test

        from src.scanner.multi_strategy_scanner import ScanResult

        # Create 10 signals
        signals = [mock_signal(f"SYM{i}", 8.0 - i*0.1, 90.0) for i in range(10)]

        mock_scan = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=10,
            symbols_with_signals=10,
            total_signals=10,
            signals=signals,
            scan_duration_seconds=1.0,
        )

        engine._scanner = MagicMock()
        engine._scanner.scan_async = AsyncMock(return_value=mock_scan)
        engine._scanner.set_vix = MagicMock()

        async def mock_fetcher(symbol):
            return [100.0 + i for i in range(60)]

        result = await engine.get_daily_picks(
            symbols=["TEST"],
            data_fetcher=mock_fetcher,
            max_picks=3,  # Limit to 3
            vix=18.0,
        )

        assert len(result.picks) == 3
        assert result.signals_found == 10  # All were found


# =============================================================================
# TEST SPEED SCORE
# =============================================================================

class TestSpeedScore:
    """Tests for Speed Score computation and tiebreaker integration."""

    def test_compute_speed_score_basic(self):
        """Test basic Speed Score computation."""
        engine = create_recommendation_engine()

        score = engine.compute_speed_score(
            dte=60,
            stability_score=90.0,
            sector="Utilities",
        )

        # DTE=60 → dte_factor=1.0 → 3.0
        # Stab=90 → stab_factor=(90-70)/30=0.667 → 1.667
        # Utilities → 1.0 * 1.5 = 1.5
        # Total = 3.0 + 1.667 + 1.5 = 6.167
        assert 6.0 <= score <= 6.5

    def test_compute_speed_score_worst_case(self):
        """Test Speed Score for slow-exit profile."""
        engine = create_recommendation_engine()

        score = engine.compute_speed_score(
            dte=90,
            stability_score=70.0,
            sector="Basic Materials",
        )

        # DTE=90 → dte_factor=0.0 → 0.0
        # Stab=70 → stab_factor=0.0 → 0.0
        # Basic Materials → 0.0 * 1.5 = 0.0
        # Total = 0.0
        assert score == 0.0

    def test_compute_speed_score_cap_at_10(self):
        """Test that Speed Score is capped at 10."""
        engine = create_recommendation_engine()

        score = engine.compute_speed_score(
            dte=60,
            stability_score=100.0,
            sector="Utilities",
            pullback_score=10.0,
            market_context_score=10.0,
        )

        # Would be 3.0 + 2.5 + 1.5 + 1.5 + 1.5 = 10.0
        assert score <= 10.0

    def test_compute_speed_score_dte_factor(self):
        """Test DTE factor: closer to 60 = higher speed."""
        engine = create_recommendation_engine()

        score_60 = engine.compute_speed_score(dte=60, stability_score=80.0, sector="Technology")
        score_75 = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Technology")
        score_90 = engine.compute_speed_score(dte=90, stability_score=80.0, sector="Technology")

        assert score_60 > score_75 > score_90

    def test_compute_speed_score_stability_factor(self):
        """Test stability factor: higher = faster exit."""
        engine = create_recommendation_engine()

        score_high = engine.compute_speed_score(dte=75, stability_score=95.0, sector="Technology")
        score_mid = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Technology")
        score_low = engine.compute_speed_score(dte=75, stability_score=70.0, sector="Technology")

        assert score_high > score_mid > score_low

    def test_compute_speed_score_sector_factor(self):
        """Test sector factor: defensive = faster exit."""
        engine = create_recommendation_engine()

        score_util = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Utilities")
        score_tech = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Technology")
        score_basic = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Basic Materials")

        assert score_util > score_tech > score_basic

    def test_compute_speed_score_unknown_sector(self):
        """Test Speed Score with unknown sector uses default 0.5."""
        engine = create_recommendation_engine()

        score_unknown = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Unknown")
        score_none = engine.compute_speed_score(dte=75, stability_score=80.0, sector=None)

        # Both should use 0.5 default
        assert score_unknown == score_none

    def test_compute_speed_score_with_optional_scores(self):
        """Test that pullback and market_context scores add to speed."""
        engine = create_recommendation_engine()

        base = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Technology")
        with_pb = engine.compute_speed_score(
            dte=75, stability_score=80.0, sector="Technology",
            pullback_score=5.0,
        )
        with_both = engine.compute_speed_score(
            dte=75, stability_score=80.0, sector="Technology",
            pullback_score=5.0, market_context_score=5.0,
        )

        assert with_pb > base
        assert with_both > with_pb

    def test_compute_speed_score_negative_market_context(self):
        """Test that negative market_context_score is clamped to 0."""
        engine = create_recommendation_engine()

        base = engine.compute_speed_score(dte=75, stability_score=80.0, sector="Technology")
        with_neg = engine.compute_speed_score(
            dte=75, stability_score=80.0, sector="Technology",
            market_context_score=-1.0,
        )

        # Negative market context should not reduce score (clamped to 0)
        assert with_neg == base


class TestSpeedScoreTiebreaker:
    """Tests for Speed Score as tiebreaker in ranking."""

    def test_tiebreaker_breaks_close_scores(self, mock_signal):
        """Test that Speed Score breaks ties for similar combined scores."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.3

        # Set up fundamentals mock to provide sector info for speed calculation
        mock_fund_util = MagicMock()
        mock_fund_util.stability_score = 80.0
        mock_fund_util.sector = "Utilities"

        mock_fund_tech = MagicMock()
        mock_fund_tech.stability_score = 80.0
        mock_fund_tech.sector = "Technology"

        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals.side_effect = lambda sym: {
            "UTIL_SYM": mock_fund_util,
            "TECH_SYM": mock_fund_tech,
        }.get(sym)

        # Same signal score, same stability, different sectors
        # Combined scores are identical → Speed Score decides
        signals = [
            mock_signal("TECH_SYM", 7.0, 80.0, "Technology"),      # Slow sector
            mock_signal("UTIL_SYM", 7.0, 80.0, "Utilities"),       # Fast sector
        ]

        ranked = engine._rank_signals(signals)
        symbols = [s.symbol for s in ranked]

        # Utilities has higher Speed Score → should rank first
        assert symbols[0] == "UTIL_SYM"
        assert symbols[1] == "TECH_SYM"

    def test_primary_score_still_dominates(self, mock_signal):
        """Test that large score differences are NOT affected by tiebreaker."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.3

        signals = [
            mock_signal("LOW_SCORE", 5.0, 80.0, "Utilities"),     # Low score, fast sector
            mock_signal("HIGH_SCORE", 9.0, 80.0, "Technology"),   # High score, slow sector
        ]

        ranked = engine._rank_signals(signals)
        symbols = [s.symbol for s in ranked]

        # HIGH_SCORE should still win despite slow sector
        assert symbols[0] == "HIGH_SCORE"

    def test_tiebreaker_with_equal_combined_but_different_stability(self, mock_signal):
        """Test tiebreaker when combined scores match but stability differs."""
        engine = create_recommendation_engine()
        engine.config['stability_weight'] = 0.5

        # 8.0*0.5 + 6.0*0.5 = 7.0
        # 6.0*0.5 + 8.0*0.5 = 7.0
        # Combined scores equal → Speed Score via stability difference
        signals = [
            mock_signal("LOW_STAB", 8.0, 60.0, "Technology"),   # Lower stability → lower speed
            mock_signal("HIGH_STAB", 6.0, 80.0, "Technology"),  # Higher stability → higher speed
        ]

        ranked = engine._rank_signals(signals)

        # Both have combined=7.0, but HIGH_STAB has better speed (higher stability)
        assert ranked[0].symbol == "HIGH_STAB"


class TestDailyPickSpeedScore:
    """Tests for Speed Score in DailyPick dataclass."""

    def test_daily_pick_has_speed_score_field(self):
        """Test that DailyPick includes speed_score."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            speed_score=5.2,
        )

        assert pick.speed_score == 5.2

    def test_daily_pick_speed_score_default(self):
        """Test that speed_score defaults to 0.0."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
        )

        assert pick.speed_score == 0.0

    def test_daily_pick_to_dict_includes_speed(self):
        """Test that to_dict includes speed_score."""
        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            speed_score=4.8,
        )

        d = pick.to_dict()
        assert 'speed_score' in d
        assert d['speed_score'] == 4.8

    @pytest.mark.asyncio
    async def test_create_daily_pick_computes_speed(self, mock_signal):
        """Test that _create_daily_pick computes speed_score."""
        engine = create_recommendation_engine()

        signal = mock_signal("AAPL", 8.0, 90.0, "Utilities")

        pick = await engine._create_daily_pick(
            rank=1,
            signal=signal,
            regime=MarketRegime.NORMAL,
        )

        # Should have non-zero speed score (Utilities + high stability)
        assert pick.speed_score > 0.0

    @pytest.mark.asyncio
    async def test_create_daily_pick_speed_varies_by_sector(self, mock_signal):
        """Test that speed_score differs by sector."""
        engine = create_recommendation_engine()

        # Set up fundamentals mock so _create_daily_pick gets sector info
        mock_fund_util = MagicMock()
        mock_fund_util.stability_score = 80.0
        mock_fund_util.sector = "Utilities"
        mock_fund_util.market_cap_category = "Large"
        mock_fund_util.historical_win_rate = None

        mock_fund_tech = MagicMock()
        mock_fund_tech.stability_score = 80.0
        mock_fund_tech.sector = "Technology"
        mock_fund_tech.market_cap_category = "Large"
        mock_fund_tech.historical_win_rate = None

        engine._fundamentals_manager = MagicMock()
        engine._fundamentals_manager.get_fundamentals.side_effect = lambda sym: {
            "UTIL": mock_fund_util,
            "TECH": mock_fund_tech,
        }.get(sym)

        signal_util = mock_signal("UTIL", 7.0, 80.0, "Utilities")
        signal_tech = mock_signal("TECH", 7.0, 80.0, "Technology")

        pick_util = await engine._create_daily_pick(1, signal_util, MarketRegime.NORMAL)
        pick_tech = await engine._create_daily_pick(1, signal_tech, MarketRegime.NORMAL)

        assert pick_util.speed_score > pick_tech.speed_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
