# Tests for Candidates Models
# ===========================
"""
Tests for models/candidates.py including:
- SupportLevel
- ScoreBreakdown
- PullbackCandidate
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock
from src.models.candidates import SupportLevel, ScoreBreakdown, PullbackCandidate


class TestSupportLevel:
    """Tests for SupportLevel dataclass."""

    def test_create_support_level(self):
        """Test creating a SupportLevel."""
        sl = SupportLevel(price=150.0, strength=3, touches=5)
        assert sl.price == 150.0
        assert sl.strength == 3
        assert sl.touches == 5


class TestScoreBreakdown:
    """Tests for ScoreBreakdown dataclass."""

    def test_create_score_breakdown(self):
        """Test creating a ScoreBreakdown."""
        sb = ScoreBreakdown(
            rsi_score=2.0,
            rsi_value=45.0,
            rsi_reason="RSI in oversold zone",
            support_score=1.5,
        )
        assert sb.rsi_score == 2.0
        assert sb.rsi_value == 45.0

    def test_score_breakdown_defaults(self):
        """Test ScoreBreakdown has sensible defaults."""
        sb = ScoreBreakdown()
        assert sb.rsi_score == 0
        assert sb.support_score == 0


class TestPullbackCandidateBackwardCompat:
    """Tests for PullbackCandidate backward compatibility properties."""

    def _create_sample_candidate(self):
        """Create a sample PullbackCandidate for testing with mocks."""
        # Create mock technicals that returns expected values
        mock_technicals = MagicMock()
        mock_technicals.rsi_14 = 45.0
        mock_technicals.sma_20 = 150.0
        mock_technicals.sma_200 = 140.0
        mock_technicals.to_dict.return_value = {}

        # Create mock score_breakdown
        mock_breakdown = MagicMock()
        mock_breakdown.to_dict.return_value = {}

        return PullbackCandidate(
            symbol="AAPL",
            score=8,
            score_breakdown=mock_breakdown,
            current_price=155.0,
            support_levels=[140.0, 135.0],
            resistance_levels=[160.0, 165.0],
            fib_levels={"0.382": 148.0, "0.618": 145.0},
            technicals=mock_technicals,
            avg_volume=2000000,
            current_volume=1000000,
        )

    def test_rsi_14_property(self):
        """Test backward compatible rsi_14 property."""
        candidate = self._create_sample_candidate()
        assert candidate.rsi_14 == 45.0

    def test_sma_20_property(self):
        """Test backward compatible sma_20 property."""
        candidate = self._create_sample_candidate()
        assert candidate.sma_20 == 150.0

    def test_sma_200_property(self):
        """Test backward compatible sma_200 property."""
        candidate = self._create_sample_candidate()
        assert candidate.sma_200 == 140.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
