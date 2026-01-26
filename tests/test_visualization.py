# Tests for Visualization Module
# ==============================

import pytest
from typing import List, Tuple
import tempfile
import os

# Test imports
try:
    from src.visualization.sr_chart import (
        SRChartConfig,
        plot_support_resistance,
        plot_volume_profile,
        plot_sr_with_volume_profile,
        save_chart,
        create_sr_report_chart,
        _get_level_alpha,
        _get_level_linewidth,
    )
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False

# Check matplotlib availability
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for tests
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_price_data() -> Tuple[List[float], List[float], List[float], List[int]]:
    """Generate sample OHLCV data for testing."""
    # 60 days of simulated price data with trend and volatility
    prices = []
    highs = []
    lows = []
    volumes = []

    base_price = 100.0
    for i in range(60):
        # Add trend and noise
        trend = i * 0.2
        noise = (i % 7 - 3) * 0.5

        close = base_price + trend + noise
        high = close + abs(noise) + 1.0
        low = close - abs(noise) - 0.5
        vol = 1000000 + (i % 5) * 200000

        prices.append(close)
        highs.append(high)
        lows.append(low)
        volumes.append(vol)

    return prices, highs, lows, volumes


@pytest.fixture
def sample_sr_levels() -> Tuple[List[float], List[float], List[float], List[float]]:
    """Generate sample S/R levels with strengths."""
    support_levels = [98.50, 95.00, 92.00]
    support_strengths = [0.85, 0.65, 0.45]

    resistance_levels = [115.00, 118.50, 122.00]
    resistance_strengths = [0.75, 0.55, 0.40]

    return support_levels, support_strengths, resistance_levels, resistance_strengths


@pytest.fixture
def sample_touches() -> Tuple[List[int], List[int]]:
    """Generate sample touch counts."""
    support_touches = [4, 3, 2]
    resistance_touches = [3, 2, 1]
    return support_touches, resistance_touches


# =============================================================================
# CONFIG TESTS
# =============================================================================

@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestSRChartConfig:
    """Tests for SRChartConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SRChartConfig()

        assert config.figsize == (14, 8)
        assert config.dpi == 150
        assert config.support_color == '#00C853'
        assert config.resistance_color == '#FF1744'
        assert config.show_level_labels is True
        assert config.vp_width_pct == 15.0

    def test_custom_config(self):
        """Test custom configuration."""
        config = SRChartConfig(
            figsize=(20, 10),
            dpi=300,
            support_color='#00FF00',
            show_strength=False
        )

        assert config.figsize == (20, 10)
        assert config.dpi == 300
        assert config.support_color == '#00FF00'
        assert config.show_strength is False

    def test_to_dict(self):
        """Test config serialization."""
        config = SRChartConfig()
        d = config.to_dict()

        assert 'figsize' in d
        assert 'dpi' in d
        assert 'support_color' in d
        assert 'resistance_color' in d


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_level_alpha_min(self):
        """Test alpha for minimum strength."""
        alpha = _get_level_alpha(0.0)
        assert alpha == pytest.approx(0.3, abs=0.01)

    def test_get_level_alpha_max(self):
        """Test alpha for maximum strength."""
        alpha = _get_level_alpha(1.0)
        assert alpha == pytest.approx(1.0, abs=0.01)

    def test_get_level_alpha_mid(self):
        """Test alpha for mid strength."""
        alpha = _get_level_alpha(0.5)
        assert 0.3 < alpha < 1.0

    def test_get_level_linewidth_min(self):
        """Test linewidth for minimum strength."""
        width = _get_level_linewidth(0.0, base_width=1.5)
        assert width == pytest.approx(1.5, abs=0.01)

    def test_get_level_linewidth_max(self):
        """Test linewidth for maximum strength."""
        width = _get_level_linewidth(1.0, base_width=1.5)
        assert width == pytest.approx(3.0, abs=0.01)


# =============================================================================
# PLOTTING TESTS
# =============================================================================

@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestPlotSupportResistance:
    """Tests for plot_support_resistance function."""

    def test_basic_plot(self, sample_price_data):
        """Test basic S/R plot creation."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol="TEST"
        )

        assert fig is not None
        assert ax is not None
        plt.close(fig)

    def test_plot_with_support_levels(self, sample_price_data, sample_sr_levels):
        """Test plot with support levels."""
        prices, highs, lows, volumes = sample_price_data
        support_levels, support_strengths, _, _ = sample_sr_levels

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            support_levels=support_levels,
            support_strengths=support_strengths,
            symbol="TEST"
        )

        assert fig is not None
        # Should have horizontal lines for support
        lines = [line for line in ax.get_lines()]
        assert len(lines) >= 1
        plt.close(fig)

    def test_plot_with_resistance_levels(self, sample_price_data, sample_sr_levels):
        """Test plot with resistance levels."""
        prices, highs, lows, volumes = sample_price_data
        _, _, resistance_levels, resistance_strengths = sample_sr_levels

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            resistance_levels=resistance_levels,
            resistance_strengths=resistance_strengths,
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)

    def test_plot_with_all_levels(
        self, sample_price_data, sample_sr_levels, sample_touches
    ):
        """Test plot with all S/R levels and touches."""
        prices, highs, lows, volumes = sample_price_data
        support_levels, support_strengths, resistance_levels, resistance_strengths = sample_sr_levels
        support_touches, resistance_touches = sample_touches

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            support_strengths=support_strengths,
            resistance_strengths=resistance_strengths,
            support_touches=support_touches,
            resistance_touches=resistance_touches,
            symbol="TEST"
        )

        assert fig is not None
        assert ax is not None
        plt.close(fig)

    def test_plot_with_custom_config(self, sample_price_data):
        """Test plot with custom configuration."""
        prices, highs, lows, volumes = sample_price_data

        config = SRChartConfig(
            figsize=(10, 6),
            show_level_labels=False,
            show_grid=False
        )

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            config=config,
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestPlotVolumeProfile:
    """Tests for plot_volume_profile function."""

    def test_basic_volume_profile(self, sample_price_data):
        """Test basic volume profile creation."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            symbol="TEST"
        )

        assert fig is not None
        assert ax is not None
        plt.close(fig)

    def test_volume_profile_zones(self, sample_price_data):
        """Test volume profile with custom zone count."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            num_zones=50,
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestPlotSRWithVolumeProfile:
    """Tests for combined S/R + Volume Profile plot."""

    def test_combined_plot(self, sample_price_data, sample_sr_levels):
        """Test combined chart creation."""
        prices, highs, lows, volumes = sample_price_data
        support_levels, support_strengths, resistance_levels, resistance_strengths = sample_sr_levels

        fig, axes = plot_sr_with_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            symbol="TEST"
        )

        assert fig is not None
        assert axes is not None
        assert len(axes) == 2  # price ax + volume ax
        plt.close(fig)

    def test_combined_plot_without_levels(self, sample_price_data):
        """Test combined chart without S/R levels."""
        prices, highs, lows, volumes = sample_price_data

        fig, axes = plot_sr_with_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)


# =============================================================================
# SAVE CHART TESTS
# =============================================================================

@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestSaveChart:
    """Tests for save_chart function."""

    def test_save_png(self, sample_price_data):
        """Test saving chart as PNG."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol="TEST"
        )

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            filepath = f.name

        try:
            result = save_chart(fig, filepath)
            assert result is True
            assert os.path.exists(filepath)
            assert os.path.getsize(filepath) > 0
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
            plt.close(fig)

    def test_save_pdf(self, sample_price_data):
        """Test saving chart as PDF."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol="TEST"
        )

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            filepath = f.name

        try:
            result = save_chart(fig, filepath)
            assert result is True
            assert os.path.exists(filepath)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
            plt.close(fig)

    def test_save_with_dpi(self, sample_price_data):
        """Test saving chart with custom DPI."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol="TEST"
        )

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            filepath = f.name

        try:
            result = save_chart(fig, filepath, dpi=300)
            assert result is True
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
            plt.close(fig)

    def test_save_creates_directory(self, sample_price_data):
        """Test that save_chart creates parent directories."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol="TEST"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "subdir", "chart.png")

            result = save_chart(fig, filepath)
            assert result is True
            assert os.path.exists(filepath)

        plt.close(fig)

    def test_save_none_figure(self):
        """Test saving None figure returns False."""
        result = save_chart(None, "/tmp/test.png")
        assert result is False


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestCreateSRReportChart:
    """Tests for create_sr_report_chart convenience function."""

    def test_create_report_chart(self, sample_price_data):
        """Test creating full report chart."""
        prices, highs, lows, volumes = sample_price_data

        fig, saved_path = create_sr_report_chart(
            symbol="TEST",
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes
        )

        assert fig is not None
        assert saved_path == ""  # No path provided
        plt.close(fig)

    def test_create_report_chart_with_save(self, sample_price_data):
        """Test creating and saving report chart."""
        prices, highs, lows, volumes = sample_price_data

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            filepath = f.name

        try:
            fig, saved_path = create_sr_report_chart(
                symbol="TEST",
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                output_path=filepath
            )

            assert fig is not None
            assert saved_path == filepath
            assert os.path.exists(filepath)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
            if fig:
                plt.close(fig)

    def test_create_report_chart_with_custom_config(self, sample_price_data):
        """Test report chart with custom configuration."""
        prices, highs, lows, volumes = sample_price_data

        config = SRChartConfig(
            figsize=(16, 9),
            dpi=200,
            vp_width_pct=20.0
        )

        fig, saved_path = create_sr_report_chart(
            symbol="AAPL",
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            config=config
        )

        assert fig is not None
        plt.close(fig)


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.skipif(not VISUALIZATION_AVAILABLE, reason="Visualization module not available")
class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_levels(self, sample_price_data):
        """Test plot with empty level lists."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            support_levels=[],
            resistance_levels=[],
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)

    def test_single_data_point(self):
        """Test with minimal data."""
        prices = [100.0]
        highs = [101.0]
        lows = [99.0]
        volumes = [1000000]

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)

    def test_flat_price_range(self):
        """Test with constant prices (edge case for volume profile)."""
        prices = [100.0] * 30
        highs = [100.0] * 30
        lows = [100.0] * 30
        volumes = [1000000] * 30

        fig, ax = plot_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            symbol="TEST"
        )

        assert fig is not None
        plt.close(fig)

    def test_no_symbol(self, sample_price_data):
        """Test plot without symbol (empty title)."""
        prices, highs, lows, volumes = sample_price_data

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            symbol=""
        )

        assert fig is not None
        plt.close(fig)
