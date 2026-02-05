# Tests for Signal Aggregator Module
# ===================================
"""
Tests for SignalAggregator and AggregatedSignal.
"""

import pytest
from unittest.mock import MagicMock

from src.scanner.signal_aggregator import (
    SignalAggregator,
    AggregatedSignal,
)
from src.models.base import TradeSignal, SignalType, SignalStrength


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def create_signal():
    """Factory for creating test signals."""
    def _create(
        symbol: str = "AAPL",
        score: float = 7.0,
        signal_type: SignalType = SignalType.LONG,
        strategy: str = "pullback",
        price: float = 150.0,
    ):
        return TradeSignal(
            symbol=symbol,
            score=score,
            signal_type=signal_type,
            strategy=strategy,
            current_price=price,
            strength=SignalStrength.MODERATE,
        )
    return _create


@pytest.fixture
def sample_signals(create_signal):
    """Create sample signals for testing."""
    return [
        create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
        create_signal("AAPL", 7.5, SignalType.LONG, "bounce"),
        create_signal("MSFT", 6.0, SignalType.LONG, "pullback"),
        create_signal("GOOGL", 5.0, SignalType.NEUTRAL, "pullback"),
    ]


# =============================================================================
# AGGREGATED SIGNAL TESTS
# =============================================================================

class TestAggregatedSignal:
    """Tests for AggregatedSignal dataclass."""

    def test_create_aggregated_signal(self, create_signal):
        """Test AggregatedSignal creation."""
        best = create_signal()
        agg = AggregatedSignal(
            symbol="AAPL",
            current_price=150.0,
            combined_score=7.5,
            signal_count=2,
            strategies=["pullback", "bounce"],
            best_signal=best,
            all_signals=[best],
            consensus_type=SignalType.LONG,
            consensus_strength=SignalStrength.MODERATE,
        )

        assert agg.symbol == "AAPL"
        assert agg.combined_score == 7.5
        assert agg.signal_count == 2

    def test_to_dict(self, create_signal):
        """Test to_dict serialization."""
        best = create_signal()
        agg = AggregatedSignal(
            symbol="AAPL",
            current_price=150.0,
            combined_score=7.55,
            signal_count=2,
            strategies=["pullback", "bounce"],
            best_signal=best,
            all_signals=[best],
            consensus_type=SignalType.LONG,
            consensus_strength=SignalStrength.MODERATE,
        )

        d = agg.to_dict()

        assert d["symbol"] == "AAPL"
        assert d["combined_score"] == 7.55
        assert d["consensus_type"] == SignalType.LONG.value


# =============================================================================
# SIGNAL AGGREGATOR TESTS
# =============================================================================

class TestSignalAggregator:
    """Tests for SignalAggregator class."""

    def test_init_default_weights(self):
        """Test initialization with default weights."""
        agg = SignalAggregator()

        assert agg._default_weight == 1.0
        assert len(agg._weights) == 0

    def test_init_custom_weights(self):
        """Test initialization with custom weights."""
        weights = {"pullback": 1.5, "bounce": 1.0}
        agg = SignalAggregator(strategy_weights=weights)

        assert agg._weights == weights

    def test_set_weight(self):
        """Test set_weight method."""
        agg = SignalAggregator()
        agg.set_weight("pullback", 2.0)

        assert agg._weights["pullback"] == 2.0


# =============================================================================
# AGGREGATE METHOD TESTS
# =============================================================================

class TestAggregate:
    """Tests for aggregate method."""

    def test_returns_list(self, sample_signals):
        """Test aggregate returns list."""
        agg = SignalAggregator()
        result = agg.aggregate(sample_signals)

        assert isinstance(result, list)

    def test_returns_aggregated_signals(self, sample_signals):
        """Test aggregate returns AggregatedSignal objects."""
        agg = SignalAggregator()
        result = agg.aggregate(sample_signals)

        for item in result:
            assert isinstance(item, AggregatedSignal)

    def test_groups_by_symbol(self, create_signal):
        """Test signals are grouped by symbol."""
        signals = [
            create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
            create_signal("AAPL", 7.0, SignalType.LONG, "bounce"),
            create_signal("MSFT", 6.0, SignalType.LONG, "pullback"),
        ]
        agg = SignalAggregator()
        result = agg.aggregate(signals)

        symbols = [r.symbol for r in result]
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_min_agreement_filter(self, create_signal):
        """Test min_agreement filters results."""
        signals = [
            create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
            create_signal("AAPL", 7.0, SignalType.LONG, "bounce"),
            create_signal("MSFT", 6.0, SignalType.LONG, "pullback"),
        ]
        agg = SignalAggregator()
        result = agg.aggregate(signals, min_agreement=2)

        symbols = [r.symbol for r in result]
        assert "AAPL" in symbols
        assert "MSFT" not in symbols  # Only 1 signal

    def test_excludes_neutral_signals(self, create_signal):
        """Test neutral signals are excluded from consensus."""
        signals = [
            create_signal("AAPL", 8.0, SignalType.NEUTRAL, "pullback"),
            create_signal("AAPL", 7.0, SignalType.NEUTRAL, "bounce"),
        ]
        agg = SignalAggregator()
        result = agg.aggregate(signals)

        # Should be empty since all signals are neutral
        assert len(result) == 0

    def test_sorted_by_score(self, create_signal):
        """Test results are sorted by combined_score descending."""
        signals = [
            create_signal("MSFT", 6.0, SignalType.LONG, "pullback"),
            create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
            create_signal("GOOGL", 9.0, SignalType.LONG, "pullback"),
        ]
        agg = SignalAggregator()
        result = agg.aggregate(signals)

        scores = [r.combined_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_applies_strategy_weights(self, create_signal):
        """Test strategy weights are applied."""
        signals = [
            create_signal("AAPL", 10.0, SignalType.LONG, "pullback"),
            create_signal("AAPL", 5.0, SignalType.LONG, "bounce"),
        ]

        # Without weights: (10 + 5) / 2 = 7.5
        agg = SignalAggregator()
        result = agg.aggregate(signals)
        assert result[0].combined_score == 7.5

        # With weights: (10*2 + 5*1) / 3 = 8.33...
        agg_weighted = SignalAggregator(strategy_weights={"pullback": 2.0, "bounce": 1.0})
        result_weighted = agg_weighted.aggregate(signals)
        assert abs(result_weighted[0].combined_score - 8.33) < 0.1


# =============================================================================
# FILTER BY STRATEGY TESTS
# =============================================================================

class TestFilterByStrategy:
    """Tests for filter_by_strategy method."""

    def test_filters_correctly(self, create_signal):
        """Test filter_by_strategy filters correctly."""
        signals = [
            create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
            create_signal("MSFT", 7.0, SignalType.LONG, "bounce"),
            create_signal("GOOGL", 6.0, SignalType.LONG, "pullback"),
        ]
        agg = SignalAggregator()
        result = agg.filter_by_strategy(signals, "pullback")

        assert len(result) == 2
        for signal in result:
            assert signal.strategy == "pullback"


# =============================================================================
# MULTI STRATEGY HITS TESTS
# =============================================================================

class TestGetMultiStrategyHits:
    """Tests for get_multi_strategy_hits method."""

    def test_returns_multi_strategy_symbols(self, create_signal):
        """Test get_multi_strategy_hits returns correct symbols."""
        signals = [
            create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
            create_signal("AAPL", 7.0, SignalType.LONG, "bounce"),
            create_signal("MSFT", 6.0, SignalType.LONG, "pullback"),
        ]
        agg = SignalAggregator()
        result = agg.get_multi_strategy_hits(signals, min_strategies=2)

        symbols = [r.symbol for r in result]
        assert "AAPL" in symbols
        assert "MSFT" not in symbols

    def test_empty_when_no_multi_strategy(self, create_signal):
        """Test empty result when no multi-strategy hits."""
        signals = [
            create_signal("AAPL", 8.0, SignalType.LONG, "pullback"),
            create_signal("MSFT", 6.0, SignalType.LONG, "pullback"),
        ]
        agg = SignalAggregator()
        result = agg.get_multi_strategy_hits(signals, min_strategies=2)

        assert len(result) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
