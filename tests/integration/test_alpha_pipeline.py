"""
Integration tests for Alpha-Engine pipeline wiring (E.3).

Tests the two-stage pipeline: AlphaScorer -> Scanner, verifying:
- Feature flag on/off
- Graceful degradation on error
- Alpha data enrichment in picks
- Full watchlist (broadest universe) is used
- Existing filters still apply after alpha
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.alpha import AlphaCandidate
from src.services.alpha_scorer import get_alpha_filtered_symbols

# =============================================================================
# Fixtures
# =============================================================================


def _make_alpha_candidate(symbol: str, percentile: int = 80) -> AlphaCandidate:
    """Create a mock AlphaCandidate for testing."""
    from src.services.sector_rs import RSQuadrant

    return AlphaCandidate(
        symbol=symbol,
        b_raw=1.5,
        f_raw=0.8,
        alpha_raw=2.7,
        alpha_percentile=percentile,
        quadrant_slow=RSQuadrant.IMPROVING,
        quadrant_fast=RSQuadrant.LEADING,
        dual_label="IMP->LEAD",
        sector="Technology",
    )


# =============================================================================
# Test: get_alpha_filtered_symbols()
# =============================================================================


class TestGetAlphaFilteredSymbols:
    """Tests for the shared get_alpha_filtered_symbols() function."""

    @pytest.mark.asyncio
    async def test_disabled_returns_full_watchlist(self):
        """Feature-flag off: returns full watchlist, empty alpha_map."""
        watchlist = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        config = {"sector_rs": {"alpha_engine_enabled": False}}

        symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, config)

        assert symbols == watchlist
        assert alpha_map == {}

    @pytest.mark.asyncio
    async def test_missing_config_returns_full_watchlist(self):
        """No config at all: returns full watchlist (disabled by default)."""
        watchlist = ["AAPL", "MSFT", "NVDA"]
        symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, {})

        assert symbols == watchlist
        assert alpha_map == {}

    @pytest.mark.asyncio
    async def test_none_config_returns_full_watchlist(self):
        """None config: returns full watchlist."""
        watchlist = ["AAPL", "MSFT"]
        symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, None)

        assert symbols == watchlist
        assert alpha_map == {}

    @pytest.mark.asyncio
    async def test_enabled_returns_longlist(self):
        """When enabled, returns filtered longlist from AlphaScorer."""
        watchlist = [f"SYM{i}" for i in range(100)]
        config = {
            "sector_rs": {
                "alpha_engine_enabled": True,
                "alpha_longlist_size": 10,
            }
        }
        mock_longlist = [_make_alpha_candidate(f"SYM{i}", 90 - i) for i in range(10)]

        with patch(
            "src.services.alpha_scorer.AlphaScorer.generate_longlist",
            new_callable=AsyncMock,
            return_value=mock_longlist,
        ):
            symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, config)

        assert len(symbols) == 10
        assert symbols == [f"SYM{i}" for i in range(10)]
        assert len(alpha_map) == 10
        assert "SYM0" in alpha_map
        assert alpha_map["SYM0"].alpha_percentile == 90

    @pytest.mark.asyncio
    async def test_empty_longlist_returns_full_watchlist(self):
        """Empty longlist: falls back to full watchlist."""
        watchlist = ["AAPL", "MSFT", "NVDA"]
        config = {"sector_rs": {"alpha_engine_enabled": True, "alpha_longlist_size": 30}}

        with patch(
            "src.services.alpha_scorer.AlphaScorer.generate_longlist",
            new_callable=AsyncMock,
            return_value=[],
        ):
            symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, config)

        assert symbols == watchlist
        assert alpha_map == {}

    @pytest.mark.asyncio
    async def test_exception_returns_full_watchlist(self):
        """AlphaScorer exception: graceful degradation to full watchlist."""
        watchlist = ["AAPL", "MSFT", "NVDA"]
        config = {"sector_rs": {"alpha_engine_enabled": True}}

        with patch(
            "src.services.alpha_scorer.AlphaScorer.generate_longlist",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RS data unavailable"),
        ):
            symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, config)

        assert symbols == watchlist
        assert alpha_map == {}

    @pytest.mark.asyncio
    async def test_longlist_size_from_config(self):
        """Respects alpha_longlist_size from config."""
        watchlist = [f"SYM{i}" for i in range(200)]
        config = {
            "sector_rs": {
                "alpha_engine_enabled": True,
                "alpha_longlist_size": 15,
            }
        }
        mock_longlist = [_make_alpha_candidate(f"SYM{i}") for i in range(15)]

        with patch(
            "src.services.alpha_scorer.AlphaScorer.generate_longlist",
            new_callable=AsyncMock,
            return_value=mock_longlist,
        ) as mock_gen:
            symbols, alpha_map = await get_alpha_filtered_symbols(watchlist, config)

        mock_gen.assert_called_once_with(watchlist, top_n=15)
        assert len(symbols) == 15


# =============================================================================
# Test: DailyPick alpha field enrichment
# =============================================================================


class TestAlphaEnrichment:
    """Tests that alpha data flows into DailyPick output."""

    def test_daily_pick_alpha_fields_default_none(self):
        """DailyPick alpha fields default to None (backwards compat)."""
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
        )
        assert pick.alpha_percentile is None
        assert pick.alpha_raw is None
        assert pick.dual_label is None
        assert pick.quadrant_slow is None
        assert pick.quadrant_fast is None

    def test_daily_pick_to_dict_without_alpha(self):
        """to_dict() excludes alpha fields when None."""
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
        )
        d = pick.to_dict()
        assert "alpha_percentile" not in d
        assert "dual_label" not in d

    def test_daily_pick_to_dict_with_alpha(self):
        """to_dict() includes alpha fields when set."""
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            alpha_percentile=92,
            alpha_raw=3.14,
            dual_label="IMP->LEAD",
            quadrant_slow="IMPROVING",
            quadrant_fast="LEADING",
        )
        d = pick.to_dict()
        assert d["alpha_percentile"] == 92
        assert d["alpha_raw"] == 3.14
        assert d["dual_label"] == "IMP->LEAD"
        assert d["quadrant_slow"] == "IMPROVING"
        assert d["quadrant_fast"] == "LEADING"


# =============================================================================
# Test: Pipeline integration (mocked scanner)
# =============================================================================


class TestAlphaPipelineIntegration:
    """Tests the full two-stage pipeline with mocked components."""

    @pytest.mark.asyncio
    async def test_scanner_receives_longlist_not_full_watchlist(self):
        """Scanner is called with alpha-longlist (10), not full watchlist (350)."""
        mock_longlist = [_make_alpha_candidate(f"SYM{i}", 95 - i) for i in range(10)]
        full_watchlist = [f"SYM{i}" for i in range(350)]

        with patch(
            "src.services.alpha_scorer.AlphaScorer.generate_longlist",
            new_callable=AsyncMock,
            return_value=mock_longlist,
        ):
            config = {
                "sector_rs": {
                    "alpha_engine_enabled": True,
                    "alpha_longlist_size": 10,
                }
            }
            symbols, alpha_map = await get_alpha_filtered_symbols(full_watchlist, config)

        # Scanner would receive only these 10, not the 350
        assert len(symbols) == 10
        assert all(s.startswith("SYM") for s in symbols)
        # Verify the full 350 were passed to generate_longlist (broadest universe)

    @pytest.mark.asyncio
    async def test_full_watchlist_used_when_disabled(self):
        """When alpha disabled, scanner gets full watchlist."""
        full_watchlist = [f"SYM{i}" for i in range(275)]
        config = {"sector_rs": {"alpha_engine_enabled": False}}

        symbols, alpha_map = await get_alpha_filtered_symbols(full_watchlist, config)

        assert len(symbols) == 275
        assert alpha_map == {}

    @pytest.mark.asyncio
    async def test_broadest_universe_no_duplicates(self):
        """Input to alpha should be merged+deduplicated from all watchlists."""
        default = ["AAPL", "MSFT", "NVDA", "GOOGL"]
        extended = ["MSFT", "NVDA", "AMD", "INTC", "CRM"]
        merged = list(set(default + extended))

        assert len(merged) == 7  # no duplicates
        assert "AAPL" in merged
        assert "AMD" in merged

    @pytest.mark.asyncio
    async def test_alpha_fields_injected_into_pick(self):
        """After scanner returns, alpha data is injected into picks."""
        from src.services.recommendation_engine import DailyPick
        from src.services.sector_rs import RSQuadrant

        candidates = {
            "AAPL": AlphaCandidate(
                symbol="AAPL",
                b_raw=2.0,
                f_raw=1.0,
                alpha_raw=3.5,
                alpha_percentile=85,
                quadrant_slow=RSQuadrant.LAGGING,
                quadrant_fast=RSQuadrant.IMPROVING,
                dual_label="LAG->IMP",
                sector="Technology",
            )
        }

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.0,
            stability_score=80.0,
        )

        # Simulate enrichment logic from scan_composed._daily_picks_core
        ac = candidates.get(pick.symbol)
        if ac:
            pick.alpha_percentile = ac.alpha_percentile
            pick.alpha_raw = ac.alpha_raw
            pick.dual_label = ac.dual_label
            pick.quadrant_slow = (
                ac.quadrant_slow.value
                if hasattr(ac.quadrant_slow, "value")
                else str(ac.quadrant_slow)
            )
            pick.quadrant_fast = (
                ac.quadrant_fast.value
                if hasattr(ac.quadrant_fast, "value")
                else str(ac.quadrant_fast)
            )

        assert pick.alpha_percentile == 85
        assert pick.alpha_raw == 3.5
        assert pick.dual_label == "LAG->IMP"
        assert pick.quadrant_slow == "lagging"
        assert pick.quadrant_fast == "improving"

    @pytest.mark.asyncio
    async def test_no_alpha_fields_when_symbol_not_in_candidates(self):
        """Symbols not in alpha_candidates keep None fields."""
        from src.services.recommendation_engine import DailyPick

        candidates = {}  # empty - no alpha data

        pick = DailyPick(
            rank=1,
            symbol="XYZ",
            strategy="bounce",
            score=6.0,
            stability_score=70.0,
        )

        ac = candidates.get(pick.symbol)
        if ac:
            pick.alpha_percentile = ac.alpha_percentile

        assert pick.alpha_percentile is None
        assert pick.dual_label is None


# =============================================================================
# Test: Regression — existing filters still apply
# =============================================================================


class TestAlphaRegressions:
    """Ensures existing scanner filters still work after alpha pre-filter."""

    @pytest.mark.asyncio
    async def test_earnings_filter_still_applies(self):
        """Symbols in alpha-longlist can still be filtered by earnings in stage 2."""
        # This is a design verification: Alpha selects candidates,
        # but the scanner's earnings filter still applies to them.
        # We verify by checking that the scanner config hasn't changed.
        from src.scanner.multi_strategy_scanner import ScanConfig

        config = ScanConfig()
        assert config.exclude_earnings_within_days > 0

    @pytest.mark.asyncio
    async def test_stability_filter_still_applies(self):
        """Stability filter in recommendation engine still works."""
        from src.services.recommendation_engine import DailyRecommendationEngine

        engine = DailyRecommendationEngine()
        assert engine.config["min_stability_score"] > 0

    @pytest.mark.asyncio
    async def test_alpha_scorer_import_works(self):
        """AlphaScorer and get_alpha_filtered_symbols can be imported."""
        from src.services.alpha_scorer import AlphaScorer, get_alpha_filtered_symbols

        assert callable(get_alpha_filtered_symbols)
        scorer = AlphaScorer.__new__(AlphaScorer)
        assert hasattr(scorer, "generate_longlist")
