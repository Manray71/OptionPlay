# Tests for Support/Resistance Chart Visualization
# ================================================
"""
Comprehensive tests for visualization/sr_chart.py functions.
"""

import pytest
from unittest.mock import MagicMock, patch, Mock
import tempfile
import os
from pathlib import Path

from src.visualization.sr_chart import (
    SRChartConfig,
    _check_matplotlib,
    _get_level_alpha,
    _get_level_linewidth,
    plot_support_resistance,
    plot_volume_profile,
    plot_sr_with_volume_profile,
    save_chart,
)


# =============================================================================
# TEST DATA FIXTURES
# =============================================================================

@pytest.fixture
def sample_prices():
    """Generate sample price data."""
    return [100.0 + i * 0.5 + (i % 5) * 0.2 for i in range(60)]


@pytest.fixture
def sample_highs(sample_prices):
    """Generate sample high prices."""
    return [p + 2.0 for p in sample_prices]


@pytest.fixture
def sample_lows(sample_prices):
    """Generate sample low prices."""
    return [p - 2.0 for p in sample_prices]


@pytest.fixture
def sample_volumes():
    """Generate sample volume data."""
    return [1000000 + i * 10000 for i in range(60)]


@pytest.fixture
def sample_support_levels():
    """Generate sample support levels."""
    return [98.0, 95.0, 92.0]


@pytest.fixture
def sample_resistance_levels():
    """Generate sample resistance levels."""
    return [115.0, 118.0, 122.0]


# =============================================================================
# SR CHART CONFIG TESTS
# =============================================================================

class TestSRChartConfig:
    """Tests for SRChartConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SRChartConfig()

        assert config.figsize == (14, 8)
        assert config.dpi == 150
        assert config.title_fontsize == 14
        assert config.label_fontsize == 10

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SRChartConfig(
            figsize=(16, 10),
            dpi=200,
            support_color='#00FF00',
            resistance_color='#FF0000',
        )

        assert config.figsize == (16, 10)
        assert config.dpi == 200
        assert config.support_color == '#00FF00'
        assert config.resistance_color == '#FF0000'

    def test_color_defaults(self):
        """Test default color values."""
        config = SRChartConfig()

        assert config.support_color == '#00C853'
        assert config.resistance_color == '#FF1744'
        assert config.price_color == '#1976D2'
        assert config.volume_color == '#78909C'
        assert config.hvn_color == '#7B1FA2'
        assert config.poc_color == '#FF6F00'

    def test_line_style_defaults(self):
        """Test default line style values."""
        config = SRChartConfig()

        assert config.support_linestyle == '--'
        assert config.resistance_linestyle == '--'
        assert config.support_linewidth == 1.5
        assert config.resistance_linewidth == 1.5

    def test_label_options(self):
        """Test label display options."""
        config = SRChartConfig()

        assert config.show_level_labels is True
        assert config.show_strength is True
        assert config.show_touches is True
        assert config.show_hold_rate is True

    def test_volume_profile_settings(self):
        """Test volume profile settings."""
        config = SRChartConfig()

        assert config.vp_width_pct == 15.0
        assert config.vp_num_zones == 30

    def test_to_dict(self):
        """Test to_dict method."""
        config = SRChartConfig()

        result = config.to_dict()

        assert isinstance(result, dict)
        assert 'figsize' in result
        assert 'dpi' in result
        assert 'support_color' in result
        assert 'resistance_color' in result

    def test_grid_settings(self):
        """Test grid settings."""
        config = SRChartConfig()

        assert config.show_grid is True
        assert config.grid_alpha == 0.3


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestCheckMatplotlib:
    """Tests for _check_matplotlib function."""

    def test_returns_bool(self):
        """Test returns boolean."""
        result = _check_matplotlib()
        assert isinstance(result, bool)

    @patch.dict('sys.modules', {'matplotlib': None})
    def test_handles_import_error(self):
        """Test handles ImportError gracefully."""
        # This test verifies the function doesn't raise exceptions
        # The actual return value depends on whether matplotlib is installed
        try:
            result = _check_matplotlib()
            assert isinstance(result, bool)
        except ImportError:
            pass


class TestGetLevelAlpha:
    """Tests for _get_level_alpha function."""

    def test_zero_strength(self):
        """Test alpha for zero strength."""
        result = _get_level_alpha(0.0)
        assert result == 0.3

    def test_full_strength(self):
        """Test alpha for full strength."""
        result = _get_level_alpha(1.0)
        assert result == 1.0

    def test_half_strength(self):
        """Test alpha for half strength."""
        result = _get_level_alpha(0.5)
        assert 0.3 < result < 1.0
        assert result == pytest.approx(0.65, rel=0.01)

    def test_interpolation(self):
        """Test alpha interpolates linearly."""
        alpha_low = _get_level_alpha(0.25)
        alpha_mid = _get_level_alpha(0.5)
        alpha_high = _get_level_alpha(0.75)

        assert alpha_low < alpha_mid < alpha_high


class TestGetLevelLinewidth:
    """Tests for _get_level_linewidth function."""

    def test_zero_strength(self):
        """Test linewidth for zero strength."""
        result = _get_level_linewidth(0.0)
        assert result == 1.5  # base_width * 1.0

    def test_full_strength(self):
        """Test linewidth for full strength."""
        result = _get_level_linewidth(1.0)
        assert result == 3.0  # base_width * 2.0

    def test_custom_base_width(self):
        """Test with custom base width."""
        result = _get_level_linewidth(0.5, base_width=2.0)
        assert result == 3.0  # 2.0 * 1.5

    def test_linewidth_increases_with_strength(self):
        """Test linewidth increases with strength."""
        low = _get_level_linewidth(0.2)
        mid = _get_level_linewidth(0.5)
        high = _get_level_linewidth(0.8)

        assert low < mid < high


# =============================================================================
# PLOT SUPPORT RESISTANCE TESTS
# =============================================================================

class TestPlotSupportResistance:
    """Tests for plot_support_resistance function."""

    def test_returns_tuple(self, sample_prices, sample_highs, sample_lows):
        """Test returns tuple of (fig, ax)."""
        result = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_with_support_levels(
        self, sample_prices, sample_highs, sample_lows, sample_support_levels
    ):
        """Test with support levels."""
        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            support_levels=sample_support_levels,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_resistance_levels(
        self, sample_prices, sample_highs, sample_lows, sample_resistance_levels
    ):
        """Test with resistance levels."""
        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            resistance_levels=sample_resistance_levels,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_both_levels(
        self, sample_prices, sample_highs, sample_lows,
        sample_support_levels, sample_resistance_levels
    ):
        """Test with both support and resistance levels."""
        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            support_levels=sample_support_levels,
            resistance_levels=sample_resistance_levels,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_strengths(
        self, sample_prices, sample_highs, sample_lows, sample_support_levels
    ):
        """Test with strength values."""
        strengths = [0.8, 0.6, 0.4]

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            support_levels=sample_support_levels,
            support_strengths=strengths,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_touches(
        self, sample_prices, sample_highs, sample_lows, sample_support_levels
    ):
        """Test with touch counts."""
        touches = [5, 3, 2]

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            support_levels=sample_support_levels,
            support_touches=touches,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_symbol(
        self, sample_prices, sample_highs, sample_lows
    ):
        """Test with symbol name."""
        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            symbol="AAPL",
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_custom_config(
        self, sample_prices, sample_highs, sample_lows
    ):
        """Test with custom config."""
        config = SRChartConfig(
            figsize=(10, 6),
            dpi=100,
            show_level_labels=False,
        )

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            config=config,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_existing_ax(
        self, sample_prices, sample_highs, sample_lows
    ):
        """Test with existing axes."""
        if not _check_matplotlib():
            pytest.skip("matplotlib not available")

        import matplotlib.pyplot as plt

        fig, existing_ax = plt.subplots()

        fig_result, ax_result = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            ax=existing_ax,
        )

        assert ax_result is existing_ax
        plt.close(fig)


# =============================================================================
# PLOT VOLUME PROFILE TESTS
# =============================================================================

class TestPlotVolumeProfile:
    """Tests for plot_volume_profile function."""

    def test_returns_tuple(
        self, sample_prices, sample_highs, sample_lows, sample_volumes
    ):
        """Test returns tuple of (fig, ax)."""
        result = plot_volume_profile(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            volumes=sample_volumes,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_with_custom_zones(
        self, sample_prices, sample_highs, sample_lows, sample_volumes
    ):
        """Test with custom number of zones."""
        fig, ax = plot_volume_profile(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            volumes=sample_volumes,
            num_zones=20,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_with_symbol(
        self, sample_prices, sample_highs, sample_lows, sample_volumes
    ):
        """Test with symbol name."""
        fig, ax = plot_volume_profile(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            volumes=sample_volumes,
            symbol="AAPL",
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_handles_equal_high_low(self):
        """Test handles equal high and low prices."""
        prices = [100.0] * 10
        highs = [100.0] * 10
        lows = [100.0] * 10
        volumes = [1000] * 10

        fig, ax = plot_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)


# =============================================================================
# PLOT SR WITH VOLUME PROFILE TESTS
# =============================================================================

class TestPlotSRWithVolumeProfile:
    """Tests for plot_sr_with_volume_profile function."""

    def test_returns_tuple(
        self, sample_prices, sample_highs, sample_lows, sample_volumes
    ):
        """Test returns tuple of (fig, (ax1, ax2))."""
        result = plot_sr_with_volume_profile(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            volumes=sample_volumes,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_with_all_parameters(
        self, sample_prices, sample_highs, sample_lows, sample_volumes,
        sample_support_levels, sample_resistance_levels
    ):
        """Test with all parameters."""
        fig, axes = plot_sr_with_volume_profile(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            volumes=sample_volumes,
            support_levels=sample_support_levels,
            resistance_levels=sample_resistance_levels,
            support_strengths=[0.8, 0.6, 0.4],
            resistance_strengths=[0.7, 0.5, 0.3],
            support_touches=[5, 3, 2],
            resistance_touches=[4, 3, 1],
            symbol="AAPL",
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)


# =============================================================================
# SAVE CHART TESTS
# =============================================================================

class TestSaveChart:
    """Tests for save_chart function."""

    def test_returns_false_for_none_figure(self):
        """Test returns False when figure is None."""
        result = save_chart(None, "/tmp/test.png")
        assert result is False

    def test_saves_png_file(self, sample_prices, sample_highs, sample_lows):
        """Test saves PNG file successfully."""
        if not _check_matplotlib():
            pytest.skip("matplotlib not available")

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
        )

        if fig is None:
            pytest.skip("Figure creation failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_chart.png")

            result = save_chart(fig, filepath)

            assert result is True
            assert os.path.exists(filepath)

        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_saves_pdf_file(self, sample_prices, sample_highs, sample_lows):
        """Test saves PDF file successfully."""
        if not _check_matplotlib():
            pytest.skip("matplotlib not available")

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
        )

        if fig is None:
            pytest.skip("Figure creation failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_chart.pdf")

            result = save_chart(fig, filepath, format='pdf')

            assert result is True
            assert os.path.exists(filepath)

        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_creates_parent_directory(self, sample_prices, sample_highs, sample_lows):
        """Test creates parent directory if not exists."""
        if not _check_matplotlib():
            pytest.skip("matplotlib not available")

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
        )

        if fig is None:
            pytest.skip("Figure creation failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "subdir", "nested", "test_chart.png")

            result = save_chart(fig, filepath)

            assert result is True
            assert os.path.exists(filepath)

        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_with_custom_dpi(self, sample_prices, sample_highs, sample_lows):
        """Test saves with custom DPI."""
        if not _check_matplotlib():
            pytest.skip("matplotlib not available")

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
        )

        if fig is None:
            pytest.skip("Figure creation failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_chart.png")

            result = save_chart(fig, filepath, dpi=300)

            assert result is True

        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_with_transparent_background(self, sample_prices, sample_highs, sample_lows):
        """Test saves with transparent background."""
        if not _check_matplotlib():
            pytest.skip("matplotlib not available")

        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
        )

        if fig is None:
            pytest.skip("Figure creation failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_chart.png")

            result = save_chart(fig, filepath, transparent=True)

            assert result is True

        import matplotlib.pyplot as plt
        plt.close(fig)


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_support_levels(self, sample_prices, sample_highs, sample_lows):
        """Test with empty support levels list."""
        fig, ax = plot_support_resistance(
            prices=sample_prices,
            highs=sample_highs,
            lows=sample_lows,
            support_levels=[],
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_single_price_point(self):
        """Test with single price point."""
        fig, ax = plot_support_resistance(
            prices=[100.0],
            highs=[102.0],
            lows=[98.0],
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_very_long_data(self):
        """Test with very long price data."""
        n = 500
        prices = [100.0 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        fig, ax = plot_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
        )

        if fig is not None:
            import matplotlib.pyplot as plt
            plt.close(fig)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
