# Tests for Scanner Integration with VIX Regime v2 + Sector RS
# =============================================================

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig


# =============================================================================
# SCAN CONFIG FLAGS
# =============================================================================


class TestScanConfigFlags:
    """Test that new ScanConfig flags have correct defaults."""

    def test_enable_regime_v2_default_false(self):
        cfg = ScanConfig()
        assert cfg.enable_regime_v2 is False

    def test_enable_sector_rs_default_false(self):
        cfg = ScanConfig()
        assert cfg.enable_sector_rs is False

    def test_flags_can_be_enabled(self):
        cfg = ScanConfig(enable_regime_v2=True, enable_sector_rs=True)
        assert cfg.enable_regime_v2 is True
        assert cfg.enable_sector_rs is True


# =============================================================================
# SCANNER INIT WITH V2 FEATURES
# =============================================================================


class TestScannerInit:
    """Test scanner initialization with v2 features."""

    def test_sector_rs_service_none_when_disabled(self):
        """Sector RS service not created when flag is off."""
        cfg = ScanConfig(
            enable_sector_rs=False,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
        )
        scanner = MultiStrategyScanner(config=cfg)
        assert scanner._sector_rs_service is None

    def test_sector_rs_service_created_when_enabled(self):
        """Sector RS service created when flag is on."""
        cfg = ScanConfig(
            enable_sector_rs=True,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
        )
        scanner = MultiStrategyScanner(config=cfg)
        assert scanner._sector_rs_service is not None

    def test_regime_v2_params_initially_none(self):
        """Regime v2 params start as None."""
        cfg = ScanConfig(
            enable_regime_v2=True,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
        )
        scanner = MultiStrategyScanner(config=cfg)
        assert scanner._regime_v2_params is None


# =============================================================================
# VIX REGIME V2 SCORE GATE
# =============================================================================


class TestRegimeV2ScoreGate:
    """Test VIX Regime v2 min_score gate in analyze_symbol."""

    def _make_scanner(self, enable_v2=True, vix=None):
        cfg = ScanConfig(
            enable_regime_v2=enable_v2,
            enable_sector_rs=False,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
            min_score=0.0,  # Don't filter by default min
        )
        scanner = MultiStrategyScanner(config=cfg)
        if vix is not None:
            scanner._vix_cache = vix
        return scanner

    def test_get_regime_v2_params_with_vix(self):
        """With VIX cached, v2 params are computed."""
        scanner = self._make_scanner(enable_v2=True, vix=20.0)
        params = scanner._get_regime_v2_params()
        assert params is not None
        assert params.min_score == 4.5  # VIX 20 anchor

    def test_get_regime_v2_params_without_vix(self):
        """Without VIX cache, v2 params return None."""
        scanner = self._make_scanner(enable_v2=True, vix=None)
        params = scanner._get_regime_v2_params()
        assert params is None

    def test_get_regime_v2_params_disabled(self):
        """When disabled, v2 params return None."""
        scanner = self._make_scanner(enable_v2=False, vix=20.0)
        params = scanner._get_regime_v2_params()
        assert params is None

    def test_set_regime_resets_v2_cache(self):
        """set_regime() clears v2 params cache."""
        scanner = self._make_scanner(enable_v2=True, vix=20.0)
        # Populate cache
        scanner._get_regime_v2_params()
        assert scanner._regime_v2_params is not None

        # set_regime should reset
        scanner.set_regime("elevated")
        assert scanner._regime_v2_params is None

    def test_v2_gate_blocks_low_score(self):
        """V2 gate should block signals below v2 min_score."""
        scanner = self._make_scanner(enable_v2=True, vix=25.0)
        # VIX 25 => min_score = 5.0

        # Register a mock analyzer that returns a signal with score 4.0
        mock_analyzer = MagicMock()
        mock_signal = MagicMock()
        mock_signal.score = 4.0
        mock_signal.details = {}
        mock_analyzer.analyze.return_value = mock_signal

        scanner._analyzers = {"pullback": mock_analyzer}
        scanner._run_analysis = MagicMock(return_value=mock_signal)
        scanner._should_skip_for_earnings = MagicMock(return_value=False)
        scanner._check_iv_filter = MagicMock(return_value=(True, ""))
        scanner._get_resolved_weights = MagicMock(return_value=None)

        prices = [100.0] * 100
        volumes = [1000000] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100

        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows, strategies=["pullback"]
        )

        # Score 4.0 < min_score 5.0 => blocked
        assert len(signals) == 0

    def test_v2_gate_allows_high_score(self):
        """V2 gate should allow signals above v2 min_score."""
        scanner = self._make_scanner(enable_v2=True, vix=25.0)

        mock_signal = MagicMock()
        mock_signal.score = 6.0
        mock_signal.details = {}

        scanner._analyzers = {"pullback": MagicMock()}
        scanner._run_analysis = MagicMock(return_value=mock_signal)
        scanner._should_skip_for_earnings = MagicMock(return_value=False)
        scanner._check_iv_filter = MagicMock(return_value=(True, ""))
        scanner._get_resolved_weights = MagicMock(return_value=None)

        prices = [100.0] * 100
        volumes = [1000000] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100

        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows, strategies=["pullback"]
        )

        assert len(signals) == 1
        assert signals[0].details.get("regime_v2_label") is not None
        assert signals[0].details.get("regime_v2_min_score") == 5.0

    def test_v2_disabled_no_gate(self):
        """When v2 disabled, no additional score gating."""
        scanner = self._make_scanner(enable_v2=False, vix=25.0)

        mock_signal = MagicMock()
        mock_signal.score = 4.0
        mock_signal.details = {}

        scanner._analyzers = {"pullback": MagicMock()}
        scanner._run_analysis = MagicMock(return_value=mock_signal)
        scanner._should_skip_for_earnings = MagicMock(return_value=False)
        scanner._check_iv_filter = MagicMock(return_value=(True, ""))
        scanner._get_resolved_weights = MagicMock(return_value=None)

        prices = [100.0] * 100
        volumes = [1000000] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100

        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows, strategies=["pullback"]
        )

        # Score 4.0 passes because v2 gate is off (min_score=0 in config)
        assert len(signals) == 1


# =============================================================================
# SECTOR RS MODIFIER IN SCANNER
# =============================================================================


class TestSectorRSModifierInScanner:
    """Test Sector RS additive modifier in analyze_symbol."""

    def _make_scanner_with_rs(self, sector_cache=None):
        cfg = ScanConfig(
            enable_regime_v2=False,
            enable_sector_rs=True,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
            min_score=0.0,
        )
        scanner = MultiStrategyScanner(config=cfg)

        # Pre-populate sector RS cache
        if sector_cache and scanner._sector_rs_service is not None:
            scanner._sector_rs_service._cache = sector_cache
            import time
            scanner._sector_rs_service._cache_time = time.time()

        return scanner

    def test_sector_rs_modifier_applied(self):
        """Sector RS modifier adds to signal score."""
        from src.services.sector_rs import RSQuadrant, SectorRS

        sector_cache = {
            "Technology": SectorRS(
                sector="Technology",
                etf_symbol="XLK",
                rs_ratio=103.0,
                rs_momentum=101.5,
                quadrant=RSQuadrant.LEADING,
                score_modifier=0.5,
            ),
        }
        scanner = self._make_scanner_with_rs(sector_cache)

        mock_signal = MagicMock()
        mock_signal.score = 6.0
        mock_signal.details = {}

        # Create a context with sector
        from src.analyzers.context import AnalysisContext

        context = AnalysisContext(symbol="AAPL", sector="Technology")

        scanner._analyzers = {"pullback": MagicMock()}
        scanner._run_analysis = MagicMock(return_value=mock_signal)
        scanner._should_skip_for_earnings = MagicMock(return_value=False)
        scanner._check_iv_filter = MagicMock(return_value=(True, ""))
        scanner._get_resolved_weights = MagicMock(return_value=None)

        prices = [100.0] * 100
        volumes = [1000000] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100

        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows,
            strategies=["pullback"], context=context,
        )

        assert len(signals) == 1
        assert signals[0].score == 6.5  # 6.0 + 0.5
        assert signals[0].details["sector_rs_modifier"] == 0.5
        assert signals[0].details["sector_rs_quadrant"] == "leading"
        assert signals[0].details["pre_sector_rs_score"] == 6.0

    def test_sector_rs_negative_modifier(self):
        """Lagging sector applies negative modifier."""
        from src.services.sector_rs import RSQuadrant, SectorRS

        sector_cache = {
            "Real Estate": SectorRS(
                sector="Real Estate",
                etf_symbol="XLRE",
                rs_ratio=96.0,
                rs_momentum=97.0,
                quadrant=RSQuadrant.LAGGING,
                score_modifier=-0.5,
            ),
        }
        scanner = self._make_scanner_with_rs(sector_cache)

        mock_signal = MagicMock()
        mock_signal.score = 6.0
        mock_signal.details = {}

        from src.analyzers.context import AnalysisContext

        context = AnalysisContext(symbol="O", sector="Real Estate")

        scanner._analyzers = {"pullback": MagicMock()}
        scanner._run_analysis = MagicMock(return_value=mock_signal)
        scanner._should_skip_for_earnings = MagicMock(return_value=False)
        scanner._check_iv_filter = MagicMock(return_value=(True, ""))
        scanner._get_resolved_weights = MagicMock(return_value=None)

        prices = [100.0] * 100
        volumes = [1000000] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100

        signals = scanner.analyze_symbol(
            "O", prices, volumes, highs, lows,
            strategies=["pullback"], context=context,
        )

        assert len(signals) == 1
        assert signals[0].score == 5.5  # 6.0 - 0.5

    def test_no_sector_no_modifier(self):
        """Without sector in context, no modifier applied."""
        scanner = self._make_scanner_with_rs({})

        mock_signal = MagicMock()
        mock_signal.score = 6.0
        mock_signal.details = {}

        from src.analyzers.context import AnalysisContext

        context = AnalysisContext(symbol="AAPL", sector=None)

        scanner._analyzers = {"pullback": MagicMock()}
        scanner._run_analysis = MagicMock(return_value=mock_signal)
        scanner._should_skip_for_earnings = MagicMock(return_value=False)
        scanner._check_iv_filter = MagicMock(return_value=(True, ""))
        scanner._get_resolved_weights = MagicMock(return_value=None)

        prices = [100.0] * 100
        volumes = [1000000] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100

        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows,
            strategies=["pullback"], context=context,
        )

        assert len(signals) == 1
        assert signals[0].score == 6.0  # unchanged
        assert "sector_rs_modifier" not in signals[0].details


# =============================================================================
# PREFETCH SECTOR RS
# =============================================================================


class TestPrefetchSectorRS:
    """Test prefetch_sector_rs async method."""

    @pytest.mark.asyncio
    async def test_prefetch_calls_service(self):
        """prefetch_sector_rs calls get_all_sector_rs on service."""
        cfg = ScanConfig(
            enable_sector_rs=True,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
        )
        scanner = MultiStrategyScanner(config=cfg)
        scanner._sector_rs_service.get_all_sector_rs = AsyncMock(return_value={})

        await scanner.prefetch_sector_rs()
        scanner._sector_rs_service.get_all_sector_rs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prefetch_no_error_when_disabled(self):
        """prefetch_sector_rs does nothing when service is None."""
        cfg = ScanConfig(
            enable_sector_rs=False,
            use_analyzer_pool=False,
            enable_reliability_scoring=False,
            enable_stability_scoring=False,
            enable_fundamentals_filter=False,
        )
        scanner = MultiStrategyScanner(config=cfg)

        # Should not raise
        await scanner.prefetch_sector_rs()
