# Tests for Watchlist Loader
# ==========================
"""
Comprehensive tests for the WatchlistLoader class.
"""

import pytest
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path
import yaml

from src.watchlist_loader import WatchlistLoader, get_watchlist_loader


# =============================================================================
# SAMPLE DATA
# =============================================================================

SAMPLE_YAML = """
watchlists:
  default_275:
    sectors:
      information_technology:
        symbols: [AAPL, MSFT, NVDA]
      health_care:
        symbols: [UNH, JNJ, LLY]
      financials:
        symbols: [JPM, V, MA]
  tech_focus:
    symbols: [AAPL, MSFT, NVDA, AMD, INTC]
"""


# =============================================================================
# INIT TESTS
# =============================================================================

class TestWatchlistLoaderInit:
    """Tests for WatchlistLoader initialization."""

    def test_init_with_valid_config(self, tmp_path):
        """Test initialization with valid config file."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)

        loader = WatchlistLoader(config_path=config_file)

        assert len(loader.get_all_symbols()) > 0
        assert len(loader.get_sector_names()) > 0

    def test_init_with_nonexistent_config(self):
        """Test initialization with nonexistent config uses fallback."""
        loader = WatchlistLoader(config_path=Path("/nonexistent/path/config.yaml"))

        # Should use fallback
        assert len(loader.get_all_symbols()) > 0
        assert "information_technology" in loader.get_sector_names()

    def test_init_default_path_search(self):
        """Test initialization searches default paths."""
        with patch('pathlib.Path.exists', return_value=False):
            loader = WatchlistLoader()

        # Should use fallback since no config found
        assert len(loader.get_all_symbols()) > 0


# =============================================================================
# GET ALL SYMBOLS TESTS
# =============================================================================

class TestGetAllSymbols:
    """Tests for get_all_symbols method."""

    def test_get_all_symbols_returns_list(self, tmp_path):
        """Test get_all_symbols returns a list."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        symbols = loader.get_all_symbols()

        assert isinstance(symbols, list)

    def test_get_all_symbols_no_duplicates(self, tmp_path):
        """Test get_all_symbols returns no duplicates."""
        # Create config with duplicate symbols
        yaml_with_dupes = """
watchlists:
  default_275:
    sectors:
      tech:
        symbols: [AAPL, MSFT, AAPL]
      other:
        symbols: [MSFT, GOOGL]
"""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(yaml_with_dupes)
        loader = WatchlistLoader(config_path=config_file)

        symbols = loader.get_all_symbols()

        assert len(symbols) == len(set(symbols))

    def test_get_all_symbols_returns_copy(self, tmp_path):
        """Test get_all_symbols returns a copy, not reference."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        symbols1 = loader.get_all_symbols()
        symbols2 = loader.get_all_symbols()

        assert symbols1 is not symbols2


# =============================================================================
# GET SECTOR TESTS
# =============================================================================

class TestGetSector:
    """Tests for get_sector method."""

    def test_get_sector_returns_symbols(self, tmp_path):
        """Test get_sector returns sector symbols."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        tech = loader.get_sector("information_technology")

        assert "AAPL" in tech
        assert "MSFT" in tech

    def test_get_sector_unknown_returns_empty(self, tmp_path):
        """Test get_sector returns empty list for unknown sector."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        result = loader.get_sector("unknown_sector")

        assert result == []

    def test_get_sector_returns_copy(self, tmp_path):
        """Test get_sector returns a copy, not reference."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        sector1 = loader.get_sector("information_technology")
        sector2 = loader.get_sector("information_technology")

        assert sector1 is not sector2


# =============================================================================
# GET ALL SECTORS TESTS
# =============================================================================

class TestGetAllSectors:
    """Tests for get_all_sectors method."""

    def test_get_all_sectors_returns_dict(self, tmp_path):
        """Test get_all_sectors returns dictionary."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        sectors = loader.get_all_sectors()

        assert isinstance(sectors, dict)
        assert "information_technology" in sectors

    def test_get_all_sectors_returns_copy(self, tmp_path):
        """Test get_all_sectors returns copies of lists."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        sectors1 = loader.get_all_sectors()
        sectors2 = loader.get_all_sectors()

        assert sectors1 is not sectors2
        assert sectors1["information_technology"] is not sectors2["information_technology"]


# =============================================================================
# GET SECTOR NAMES TESTS
# =============================================================================

class TestGetSectorNames:
    """Tests for get_sector_names method."""

    def test_get_sector_names_returns_list(self, tmp_path):
        """Test get_sector_names returns list of sector names."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        names = loader.get_sector_names()

        assert isinstance(names, list)
        assert "information_technology" in names
        assert "health_care" in names


# =============================================================================
# GET WATCHLIST TESTS
# =============================================================================

class TestGetWatchlist:
    """Tests for get_watchlist method."""

    def test_get_watchlist_returns_dict(self, tmp_path):
        """Test get_watchlist returns watchlist dictionary."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        watchlist = loader.get_watchlist("default_275")

        assert watchlist is not None
        assert "sectors" in watchlist

    def test_get_watchlist_unknown_returns_none(self, tmp_path):
        """Test get_watchlist returns None for unknown watchlist."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        result = loader.get_watchlist("unknown_watchlist")

        assert result is None


# =============================================================================
# GET SYMBOLS FROM WATCHLIST TESTS
# =============================================================================

class TestGetSymbolsFromWatchlist:
    """Tests for get_symbols_from_watchlist method."""

    def test_get_symbols_from_watchlist_sectors(self, tmp_path):
        """Test get_symbols_from_watchlist with sectored watchlist."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        symbols = loader.get_symbols_from_watchlist("default_275")

        assert "AAPL" in symbols
        assert "JPM" in symbols

    def test_get_symbols_from_watchlist_direct(self, tmp_path):
        """Test get_symbols_from_watchlist with direct symbol list."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        symbols = loader.get_symbols_from_watchlist("tech_focus")

        assert "AAPL" in symbols
        assert "AMD" in symbols

    def test_get_symbols_from_watchlist_unknown_returns_empty(self, tmp_path):
        """Test get_symbols_from_watchlist returns empty for unknown."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        symbols = loader.get_symbols_from_watchlist("unknown")

        assert symbols == []


# =============================================================================
# SYMBOL IN SECTOR TESTS
# =============================================================================

class TestSymbolInSector:
    """Tests for symbol_in_sector method."""

    def test_symbol_in_sector_finds_sector(self, tmp_path):
        """Test symbol_in_sector finds the correct sector."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        sector = loader.symbol_in_sector("AAPL")

        assert sector == "information_technology"

    def test_symbol_in_sector_unknown_returns_none(self, tmp_path):
        """Test symbol_in_sector returns None for unknown symbol."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        sector = loader.symbol_in_sector("UNKNOWN")

        assert sector is None


# =============================================================================
# GET SECTOR DISPLAY NAME TESTS
# =============================================================================

class TestGetSectorDisplayName:
    """Tests for get_sector_display_name method."""

    def test_get_sector_display_name_known(self, tmp_path):
        """Test get_sector_display_name for known sectors."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        assert loader.get_sector_display_name("information_technology") == "Technology"
        assert loader.get_sector_display_name("health_care") == "Healthcare"
        assert loader.get_sector_display_name("financials") == "Financials"

    def test_get_sector_display_name_unknown(self, tmp_path):
        """Test get_sector_display_name for unknown sector falls back to title case."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text(SAMPLE_YAML)
        loader = WatchlistLoader(config_path=config_file)

        result = loader.get_sector_display_name("some_new_sector")

        assert result == "Some New Sector"


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests for get_watchlist_loader singleton."""

    def test_get_watchlist_loader_returns_instance(self):
        """Test get_watchlist_loader returns a WatchlistLoader instance."""
        # Reset singleton
        import src.watchlist_loader as module
        module._loader_instance = None

        loader = get_watchlist_loader()

        assert isinstance(loader, WatchlistLoader)

    def test_get_watchlist_loader_returns_same_instance(self):
        """Test get_watchlist_loader returns the same instance."""
        # Reset singleton
        import src.watchlist_loader as module
        module._loader_instance = None

        loader1 = get_watchlist_loader()
        loader2 = get_watchlist_loader()

        assert loader1 is loader2


# =============================================================================
# FALLBACK TESTS
# =============================================================================

class TestFallback:
    """Tests for fallback watchlist."""

    def test_fallback_has_all_sectors(self):
        """Test fallback has all expected sectors."""
        loader = WatchlistLoader(config_path=Path("/nonexistent"))

        sector_names = loader.get_sector_names()

        expected_sectors = [
            "information_technology", "health_care", "financials",
            "consumer_discretionary", "communication_services",
            "industrials", "consumer_staples", "energy",
            "utilities", "real_estate", "materials"
        ]
        for sector in expected_sectors:
            assert sector in sector_names

    def test_fallback_has_symbols(self):
        """Test fallback has symbols in each sector."""
        loader = WatchlistLoader(config_path=Path("/nonexistent"))

        for sector in loader.get_sector_names():
            symbols = loader.get_sector(sector)
            assert len(symbols) > 0


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_yaml_uses_fallback(self, tmp_path):
        """Test invalid YAML uses fallback."""
        config_file = tmp_path / "watchlists.yaml"
        config_file.write_text("invalid: yaml: content: [[[")

        loader = WatchlistLoader(config_path=config_file)

        # Should fall back to hardcoded list
        assert len(loader.get_all_symbols()) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
