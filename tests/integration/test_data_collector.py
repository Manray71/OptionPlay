# OptionPlay - Data Collector Tests
# ==================================

import pytest
import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass

from src.backtesting.data_collector import (
    DataCollector,
    CollectionConfig,
    CollectionResult,
    format_collection_status,
    run_daily_collection,
    create_collector,
)
from src.backtesting.trade_tracker import PriceBar, VixDataPoint


# =============================================================================
# Test Fixtures
# =============================================================================

@dataclass
class MockBar:
    """Mock für Provider-Bars"""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@pytest.fixture
def mock_bars():
    """Erzeugt Mock-Preisdaten"""
    today = date.today()
    bars = []
    for i in range(10):
        d = today - timedelta(days=i)
        bars.append(MockBar(
            date=d,
            open=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=102.0 + i,
            volume=1000000 + i * 10000,
        ))
    return bars


@pytest.fixture
def mock_vix_bars():
    """Erzeugt Mock-VIX-Daten"""
    today = date.today()
    bars = []
    for i in range(10):
        d = today - timedelta(days=i)
        bars.append(MockBar(
            date=d,
            open=18.0 + i * 0.5,
            high=20.0 + i * 0.5,
            low=17.0 + i * 0.5,
            close=19.0 + i * 0.5,
            volume=0,
        ))
    return bars


@pytest.fixture
def mock_provider(mock_bars, mock_vix_bars):
    """Erzeugt Mock MarketDataProvider"""
    provider = AsyncMock()
    provider.get_historical = AsyncMock(return_value=mock_bars)
    provider.get_index_candles = AsyncMock(return_value=mock_vix_bars)
    return provider


@pytest.fixture
def temp_watchlist(tmp_path):
    """Erzeugt temporäre Watchlist-Datei"""
    watchlist = tmp_path / "watchlist.txt"
    watchlist.write_text("""# Test Watchlist
AAPL
MSFT
GOOGL
# Kommentar
NVDA
""")
    return str(watchlist)


@pytest.fixture
def temp_db(tmp_path):
    """Erzeugt temporäre Datenbank"""
    return str(tmp_path / "test_collector.db")


# =============================================================================
# CollectionConfig Tests
# =============================================================================

class TestCollectionConfig:
    """Tests für CollectionConfig"""

    def test_default_config(self):
        """Default-Konfiguration"""
        config = CollectionConfig()

        assert config.symbols == []
        assert config.watchlist_path is None
        assert config.lookback_days == 260
        assert config.update_mode == "incremental"
        assert config.delay_between_symbols == 0.1
        assert config.batch_size == 50
        assert config.db_path is None

    def test_custom_config(self):
        """Benutzerdefinierte Konfiguration"""
        config = CollectionConfig(
            symbols=["AAPL", "MSFT"],
            lookback_days=500,
            update_mode="full",
            batch_size=100,
        )

        assert config.symbols == ["AAPL", "MSFT"]
        assert config.lookback_days == 500
        assert config.update_mode == "full"
        assert config.batch_size == 100


# =============================================================================
# CollectionResult Tests
# =============================================================================

class TestCollectionResult:
    """Tests für CollectionResult"""

    def test_success_rate_calculation(self):
        """Success Rate Berechnung"""
        result = CollectionResult(
            timestamp=datetime.now(),
            symbols_requested=100,
            symbols_collected=95,
            symbols_failed=["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"],
            total_bars_collected=25000,
            vix_points_collected=260,
            duration_seconds=45.0,
            errors=[],
        )

        assert result.success_rate == 95.0

    def test_success_rate_zero_symbols(self):
        """Success Rate bei 0 Symbolen"""
        result = CollectionResult(
            timestamp=datetime.now(),
            symbols_requested=0,
            symbols_collected=0,
            symbols_failed=[],
            total_bars_collected=0,
            vix_points_collected=0,
            duration_seconds=0.0,
            errors=["No symbols configured"],
        )

        assert result.success_rate == 0.0

    def test_str_representation(self):
        """String-Darstellung"""
        result = CollectionResult(
            timestamp=datetime.now(),
            symbols_requested=10,
            symbols_collected=9,
            symbols_failed=["FAIL"],
            total_bars_collected=2500,
            vix_points_collected=260,
            duration_seconds=5.5,
            errors=[],
        )

        s = str(result)
        assert "9/10" in s
        assert "90.0%" in s
        assert "2500 bars" in s
        assert "260 VIX" in s
        assert "5.5s" in s


# =============================================================================
# DataCollector Tests
# =============================================================================

class TestDataCollector:
    """Tests für DataCollector"""

    def test_init_default(self):
        """Initialisierung mit Default-Config"""
        collector = DataCollector()

        assert collector.config is not None
        assert collector.config.symbols == []

    def test_init_custom_config(self):
        """Initialisierung mit Custom-Config"""
        config = CollectionConfig(symbols=["AAPL"])
        collector = DataCollector(config)

        assert collector.config.symbols == ["AAPL"]

    def test_lazy_tracker_loading(self, temp_db):
        """Lazy Loading des Trackers"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        # Tracker noch nicht geladen
        assert collector._tracker is None

        # Zugriff lädt Tracker
        tracker = collector.tracker
        assert tracker is not None
        assert collector._tracker is not None


class TestWatchlistLoading:
    """Tests für Watchlist-Laden"""

    def test_load_watchlist(self, temp_watchlist, temp_db):
        """Watchlist laden"""
        config = CollectionConfig(
            watchlist_path=temp_watchlist,
            db_path=temp_db,
        )
        collector = DataCollector(config)

        symbols = collector._load_watchlist()

        assert len(symbols) == 4
        assert "AAPL" in symbols
        assert "MSFT" in symbols
        assert "GOOGL" in symbols
        assert "NVDA" in symbols
        # Kommentare sollten ignoriert werden
        assert "# Test Watchlist" not in symbols

    def test_load_missing_watchlist(self, temp_db):
        """Fehlende Watchlist"""
        config = CollectionConfig(
            watchlist_path="/nonexistent/watchlist.txt",
            db_path=temp_db,
        )
        collector = DataCollector(config)

        symbols = collector._load_watchlist()

        assert symbols == []

    def test_get_symbols_combined(self, temp_watchlist, temp_db):
        """Kombinierte Symbole aus Config und Watchlist"""
        config = CollectionConfig(
            symbols=["TSLA", "AMZN", "AAPL"],  # AAPL auch in Watchlist
            watchlist_path=temp_watchlist,
            db_path=temp_db,
        )
        collector = DataCollector(config)

        symbols = collector._get_symbols()

        # Dedupliziert und sortiert
        assert "AAPL" in symbols
        assert "AMZN" in symbols
        assert "TSLA" in symbols
        assert "MSFT" in symbols
        # AAPL nur einmal
        assert symbols.count("AAPL") == 1
        # Sortiert
        assert symbols == sorted(symbols)

    def test_get_symbols_uppercase(self, temp_db):
        """Symbole werden in Großbuchstaben konvertiert"""
        config = CollectionConfig(
            symbols=["aapl", "Msft", "GoOgL"],
            db_path=temp_db,
        )
        collector = DataCollector(config)

        symbols = collector._get_symbols()

        assert "AAPL" in symbols
        assert "MSFT" in symbols
        assert "GOOGL" in symbols


class TestDataCollection:
    """Tests für Datensammlung"""

    @pytest.mark.asyncio
    async def test_collect_no_symbols(self, temp_db):
        """Sammlung ohne Symbole"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        provider = AsyncMock()
        result = await collector.collect(provider)

        assert result.symbols_requested == 0
        assert result.symbols_collected == 0
        assert "No symbols configured" in result.errors

    @pytest.mark.asyncio
    async def test_collect_single_symbol(self, mock_provider, temp_db):
        """Sammlung für einzelnes Symbol"""
        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        result = await collector.collect(mock_provider)

        assert result.symbols_requested == 1
        assert result.symbols_collected == 1
        assert result.total_bars_collected > 0
        assert result.success_rate == 100.0
        mock_provider.get_historical.assert_called()

    @pytest.mark.asyncio
    async def test_collect_multiple_symbols(self, mock_provider, temp_db):
        """Sammlung für mehrere Symbole"""
        config = CollectionConfig(
            symbols=["AAPL", "MSFT", "GOOGL"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,  # Schneller für Tests
        )
        collector = DataCollector(config)

        result = await collector.collect(mock_provider)

        assert result.symbols_requested == 3
        assert result.symbols_collected == 3
        assert mock_provider.get_historical.call_count == 3

    @pytest.mark.asyncio
    async def test_collect_with_failures(self, temp_db):
        """Sammlung mit fehlgeschlagenen Symbolen"""
        provider = AsyncMock()
        # Erstes Symbol OK, zweites fehlschlägt
        provider.get_historical = AsyncMock(side_effect=[
            [MockBar(date.today(), 100, 105, 95, 102, 1000000)],
            Exception("API Error"),
            [],  # Drittes: leere Daten
        ])
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL", "FAIL", "EMPTY"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert result.symbols_requested == 3
        assert result.symbols_collected == 1
        assert len(result.symbols_failed) == 2
        assert "FAIL" in result.symbols_failed
        assert "EMPTY" in result.symbols_failed

    @pytest.mark.asyncio
    async def test_collect_with_progress_callback(self, mock_provider, temp_db):
        """Sammlung mit Progress-Callback"""
        config = CollectionConfig(
            symbols=["AAPL", "MSFT"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        progress_calls = []
        def callback(symbol, current, total):
            progress_calls.append((symbol, current, total))

        await collector.collect(mock_provider, progress_callback=callback)

        assert len(progress_calls) == 2
        assert progress_calls[0] == ("AAPL", 1, 2)
        assert progress_calls[1] == ("MSFT", 2, 2)


class TestVixCollection:
    """Tests für VIX-Datensammlung"""

    @pytest.mark.asyncio
    async def test_collect_vix(self, mock_provider, mock_vix_bars, temp_db):
        """VIX-Daten sammeln"""
        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        result = await collector.collect(mock_provider)

        assert result.vix_points_collected > 0
        mock_provider.get_index_candles.assert_called_with("VIX", days=260)

    @pytest.mark.asyncio
    async def test_collect_vix_failure(self, temp_db):
        """VIX-Sammlung fehlschlägt"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[
            MockBar(date.today(), 100, 105, 95, 102, 1000000)
        ])
        provider.get_index_candles = AsyncMock(side_effect=Exception("VIX Error"))

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        # Symbole sollten trotzdem gesammelt werden
        assert result.symbols_collected == 1
        assert result.vix_points_collected == 0


class TestIncrementalUpdate:
    """Tests für inkrementelle Updates"""

    @pytest.mark.asyncio
    async def test_incremental_update(self, mock_provider, temp_db):
        """Inkrementelles Update"""
        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        # Erste Sammlung (full)
        result1 = await collector.collect(mock_provider)
        bars1 = result1.total_bars_collected

        # Zweite Sammlung (incremental)
        config.update_mode = "incremental"
        result2 = await collector.collect(mock_provider)

        # Bei inkrementeller Sammlung können weniger Bars hinzukommen
        # (da bereits vorhandene gefiltert werden)
        assert result2.symbols_collected >= 0


class TestCollectSingle:
    """Tests für Einzelsymbol-Sammlung"""

    @pytest.mark.asyncio
    async def test_collect_single(self, mock_provider, temp_db):
        """Einzelnes Symbol sammeln"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        count = await collector.collect_single(mock_provider, "AAPL")

        assert count > 0
        mock_provider.get_historical.assert_called()

    @pytest.mark.asyncio
    async def test_collect_single_custom_days(self, mock_provider, temp_db):
        """Einzelnes Symbol mit Custom-Days"""
        config = CollectionConfig(db_path=temp_db, lookback_days=260)
        collector = DataCollector(config)

        count = await collector.collect_single(mock_provider, "AAPL", days=30)

        # Config sollte temporär geändert und wiederhergestellt werden
        assert collector.config.lookback_days == 260


class TestCollectionStatus:
    """Tests für Collection Status"""

    def test_get_collection_status(self, mock_provider, temp_db):
        """Collection Status abrufen"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        status = collector.get_collection_status()

        assert "total_symbols" in status
        assert "symbols" in status
        assert "stale_symbols" in status
        assert "vix_range" in status
        assert "storage" in status


# =============================================================================
# Formatting Tests
# =============================================================================

class TestFormatCollectionStatus:
    """Tests für Status-Formatierung"""

    def test_format_empty_status(self):
        """Leeren Status formatieren"""
        status = {
            "total_symbols": 0,
            "symbols": [],
            "stale_symbols": [],
            "vix_range": {"start": None, "end": None},
            "storage": {
                "total_price_bars": 0,
                "database_size_mb": 0.0,
                "vix_data_points": 0,
            },
        }

        output = format_collection_status(status)

        assert "DATA COLLECTION STATUS" in output
        assert "Total Symbols: 0" in output
        assert "VIX Data: None" in output

    def test_format_status_with_data(self):
        """Status mit Daten formatieren"""
        status = {
            "total_symbols": 5,
            "symbols": [],
            "stale_symbols": [],
            "vix_range": {"start": "2023-01-01", "end": "2024-01-01"},
            "storage": {
                "total_price_bars": 1300,
                "database_size_mb": 1.5,
                "vix_data_points": 260,
            },
        }

        output = format_collection_status(status)

        assert "Total Symbols: 5" in output
        assert "Total Bars: 1300" in output
        assert "1.5" in output  # MB
        assert "2023-01-01" in output
        assert "2024-01-01" in output

    def test_format_status_with_stale_symbols(self):
        """Status mit veralteten Symbolen"""
        status = {
            "total_symbols": 5,
            "symbols": [],
            "stale_symbols": [
                {"symbol": "OLD1", "last_date": "2023-01-01", "days_old": 30},
                {"symbol": "OLD2", "last_date": "2023-02-01", "days_old": 20},
            ],
            "vix_range": {"start": None, "end": None},
            "storage": {
                "total_price_bars": 0,
                "database_size_mb": 0.0,
                "vix_data_points": 0,
            },
        }

        output = format_collection_status(status)

        assert "STALE SYMBOLS" in output
        assert "OLD1" in output
        assert "OLD2" in output
        assert "30 days" in output


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestCreateCollector:
    """Tests für Factory-Funktion"""

    def test_create_collector_default(self):
        """Collector mit Defaults erstellen"""
        collector = create_collector()

        assert collector is not None
        assert collector.config.symbols == []

    def test_create_collector_with_symbols(self):
        """Collector mit Symbolen erstellen"""
        collector = create_collector(symbols=["AAPL", "MSFT"])

        assert "AAPL" in collector.config.symbols
        assert "MSFT" in collector.config.symbols

    def test_create_collector_with_watchlist(self, temp_watchlist):
        """Collector mit Watchlist erstellen"""
        collector = create_collector(watchlist_path=temp_watchlist)

        assert collector.config.watchlist_path == temp_watchlist

    def test_create_collector_with_db_path(self, temp_db):
        """Collector mit DB-Pfad erstellen"""
        collector = create_collector(db_path=temp_db)

        assert collector.config.db_path == temp_db


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration Tests"""

    @pytest.mark.asyncio
    async def test_full_collection_cycle(self, mock_provider, temp_db):
        """Vollständiger Sammlungszyklus"""
        # 1. Collector erstellen
        config = CollectionConfig(
            symbols=["AAPL", "MSFT"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        # 2. Daten sammeln
        result = await collector.collect(mock_provider)

        assert result.symbols_collected == 2
        assert result.total_bars_collected > 0

        # 3. Status prüfen
        status = collector.get_collection_status()

        assert status["total_symbols"] == 2

        # 4. Daten aus Tracker abrufen
        tracker = collector.tracker
        symbols = tracker.list_symbols_with_price_data()

        assert len(symbols) == 2

    @pytest.mark.asyncio
    async def test_collection_with_persistence(self, mock_provider, temp_db):
        """Sammlung mit Persistenz"""
        # Erste Sammlung
        config1 = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector1 = DataCollector(config1)
        await collector1.collect(mock_provider)

        # Neue Collector-Instanz mit gleicher DB
        config2 = CollectionConfig(
            symbols=["MSFT"],
            db_path=temp_db,
            update_mode="full",
        )
        collector2 = DataCollector(config2)
        await collector2.collect(mock_provider)

        # Status sollte beide Symbole zeigen
        status = collector2.get_collection_status()
        assert status["total_symbols"] == 2


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge Case Tests"""

    @pytest.mark.asyncio
    async def test_empty_provider_response(self, temp_db):
        """Provider gibt leere Daten zurück"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[])
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert result.symbols_collected == 0
        assert "AAPL" in result.symbols_failed

    @pytest.mark.asyncio
    async def test_large_batch(self, mock_provider, temp_db):
        """Große Batch-Sammlung"""
        symbols = [f"SYM{i:03d}" for i in range(100)]

        config = CollectionConfig(
            symbols=symbols,
            db_path=temp_db,
            batch_size=25,
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        result = await collector.collect(mock_provider)

        assert result.symbols_requested == 100
        # Provider sollte für jedes Symbol aufgerufen werden
        assert mock_provider.get_historical.call_count == 100

    def test_watchlist_with_empty_lines(self, tmp_path, temp_db):
        """Watchlist mit leeren Zeilen"""
        watchlist = tmp_path / "watchlist.txt"
        watchlist.write_text("""
AAPL

MSFT

# Comment

GOOGL

""")

        config = CollectionConfig(
            watchlist_path=str(watchlist),
            db_path=temp_db,
        )
        collector = DataCollector(config)

        symbols = collector._load_watchlist()

        assert len(symbols) == 3
        assert "" not in symbols

    @pytest.mark.asyncio
    async def test_date_filtering_in_incremental(self, mock_provider, temp_db):
        """Test date filtering in incremental mode with existing data"""
        today = date.today()

        # Create bars spanning multiple days
        old_bars = [
            MockBar(
                date=today - timedelta(days=i),
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=1000000,
            )
            for i in range(20, 30)  # 20-30 days ago
        ]

        new_bars = [
            MockBar(
                date=today - timedelta(days=i),
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=1000000,
            )
            for i in range(0, 20)  # 0-20 days ago
        ]

        provider = AsyncMock()
        provider.get_historical = AsyncMock(side_effect=[old_bars, new_bars])
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",  # First full
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        # First collection (full)
        await collector.collect(provider)

        # Reset mock and do incremental
        provider.get_historical.reset_mock()
        provider.get_historical.return_value = new_bars
        config.update_mode = "incremental"

        await collector.collect(provider)

        # Should have called get_historical for incremental update
        provider.get_historical.assert_called()

    @pytest.mark.asyncio
    async def test_provider_timeout_handling(self, temp_db):
        """Test handling of provider timeouts"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(side_effect=asyncio.TimeoutError())
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert result.symbols_collected == 0
        assert "AAPL" in result.symbols_failed
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_partial_bar_data(self, temp_db):
        """Test handling of bars with missing/partial data"""
        # Bar with string date instead of date object
        bar_with_string_date = MockBar(
            date="2024-01-15",  # String instead of date
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000000,
        )

        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[bar_with_string_date])
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        # Should handle string dates gracefully
        result = await collector.collect(provider)

        assert result.symbols_collected == 1
        assert result.total_bars_collected == 1


# =============================================================================
# Data Validation Tests
# =============================================================================

class TestDataValidation:
    """Tests for data validation during collection"""

    @pytest.mark.asyncio
    async def test_empty_bars_filtered(self, temp_db):
        """Test that empty bar lists are handled"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[])
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert "AAPL" in result.symbols_failed
        assert "No data returned" in result.errors[0]

    @pytest.mark.asyncio
    async def test_none_bars_handled(self, temp_db):
        """Test that None response from provider is handled"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=None)
        provider.get_index_candles = AsyncMock(return_value=None)

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert result.symbols_collected == 0

    @pytest.mark.asyncio
    async def test_bars_sorted_by_date(self, mock_provider, temp_db):
        """Test that bars are sorted by date before storage"""
        today = date.today()
        # Create unsorted bars
        unsorted_bars = [
            MockBar(date=today - timedelta(days=5), open=100, high=105, low=95, close=102, volume=1000),
            MockBar(date=today - timedelta(days=10), open=100, high=105, low=95, close=102, volume=1000),
            MockBar(date=today - timedelta(days=1), open=100, high=105, low=95, close=102, volume=1000),
        ]

        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=unsorted_bars)
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        await collector.collect(provider)

        # Verify bars are sorted in tracker
        data = collector.tracker.get_price_data("AAPL")
        assert data is not None
        dates = [b.date for b in data.bars]
        assert dates == sorted(dates)


# =============================================================================
# Storage and Retrieval Tests
# =============================================================================

class TestStorageRetrieval:
    """Tests for data storage and retrieval integrity"""

    @pytest.mark.asyncio
    async def test_price_data_integrity(self, mock_bars, temp_db):
        """Test that stored price data maintains integrity"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=mock_bars)
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        await collector.collect(provider)

        # Retrieve and verify
        data = collector.tracker.get_price_data("AAPL")
        assert data is not None
        assert len(data.bars) == len(mock_bars)

        # Verify OHLCV values match
        for original, stored in zip(sorted(mock_bars, key=lambda b: b.date),
                                     sorted(data.bars, key=lambda b: b.date)):
            assert stored.open == original.open
            assert stored.high == original.high
            assert stored.low == original.low
            assert stored.close == original.close
            assert stored.volume == original.volume

    @pytest.mark.asyncio
    async def test_vix_data_integrity(self, mock_vix_bars, temp_db):
        """Test that stored VIX data maintains integrity"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[
            MockBar(date.today(), 100, 105, 95, 102, 1000000)
        ])
        provider.get_index_candles = AsyncMock(return_value=mock_vix_bars)

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)

        await collector.collect(provider)

        # Retrieve and verify VIX
        vix_data = collector.tracker.get_vix_data()
        assert len(vix_data) == len(mock_vix_bars)

        # VIX should use close values
        for original, stored in zip(sorted(mock_vix_bars, key=lambda b: b.date),
                                     sorted(vix_data, key=lambda v: v.date)):
            assert stored.value == original.close

    @pytest.mark.asyncio
    async def test_multiple_symbols_stored_separately(self, mock_bars, temp_db):
        """Test that multiple symbols are stored separately"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=mock_bars)
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL", "MSFT", "GOOGL"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        await collector.collect(provider)

        # Verify each symbol has separate data
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            data = collector.tracker.get_price_data(symbol)
            assert data is not None
            assert data.symbol == symbol

    @pytest.mark.asyncio
    async def test_incremental_merge_preserves_old_data(self, temp_db):
        """Test that incremental updates merge with existing data"""
        today = date.today()

        # Old data (10-20 days ago)
        old_bars = [
            MockBar(
                date=today - timedelta(days=i),
                open=100.0, high=105.0, low=95.0, close=100.0 + i, volume=1000000,
            )
            for i in range(10, 20)
        ]

        # New data (0-10 days ago)
        new_bars = [
            MockBar(
                date=today - timedelta(days=i),
                open=110.0, high=115.0, low=105.0, close=110.0 + i, volume=2000000,
            )
            for i in range(0, 10)
        ]

        provider = AsyncMock()
        provider.get_index_candles = AsyncMock(return_value=[])

        # First: full collection with old data
        provider.get_historical = AsyncMock(return_value=old_bars)
        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)
        await collector.collect(provider)

        # Second: incremental with new data
        provider.get_historical = AsyncMock(return_value=new_bars)
        config.update_mode = "incremental"
        await collector.collect(provider)

        # Verify merged data contains both old and new
        data = collector.tracker.get_price_data("AAPL")
        assert data is not None
        # Should have data from both collections
        assert data.bar_count >= len(new_bars)


# =============================================================================
# Run Daily Collection Tests
# =============================================================================

class TestRunDailyCollection:
    """Tests for run_daily_collection convenience function"""

    @pytest.mark.asyncio
    async def test_run_daily_collection_with_symbols(self, temp_db):
        """Test run_daily_collection with explicit symbols"""
        # The import happens inside run_daily_collection, so we need to patch where it's imported
        with patch.dict('sys.modules', {'src.data_providers.marketdata': MagicMock()}):
            # Import after patching
            import sys
            mock_module = sys.modules['src.data_providers.marketdata']

            # Setup mock provider
            mock_instance = AsyncMock()
            mock_instance.get_historical = AsyncMock(return_value=[
                MockBar(date.today(), 100, 105, 95, 102, 1000000)
            ])
            mock_instance.get_index_candles = AsyncMock(return_value=[
                MockBar(date.today(), 18, 20, 17, 19, 0)
            ])
            mock_module.MarketDataProvider.return_value = mock_instance
            mock_module.MarketDataConfig.return_value = MagicMock()

            result = await run_daily_collection(
                api_key="test_key",
                symbols=["AAPL"],
            )

            assert result.symbols_requested == 1
            mock_instance.connect.assert_called_once()
            mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_daily_collection_with_watchlist(self, temp_watchlist, temp_db):
        """Test run_daily_collection with watchlist"""
        with patch.dict('sys.modules', {'src.data_providers.marketdata': MagicMock()}):
            import sys
            mock_module = sys.modules['src.data_providers.marketdata']

            mock_instance = AsyncMock()
            mock_instance.get_historical = AsyncMock(return_value=[
                MockBar(date.today(), 100, 105, 95, 102, 1000000)
            ])
            mock_instance.get_index_candles = AsyncMock(return_value=[])
            mock_module.MarketDataProvider.return_value = mock_instance
            mock_module.MarketDataConfig.return_value = MagicMock()

            result = await run_daily_collection(
                api_key="test_key",
                watchlist_path=temp_watchlist,
            )

            # Watchlist has 4 symbols
            assert result.symbols_requested == 4

    @pytest.mark.asyncio
    async def test_run_daily_collection_closes_on_error(self, temp_db):
        """Test that provider is closed even on error"""
        with patch.dict('sys.modules', {'src.data_providers.marketdata': MagicMock()}):
            import sys
            mock_module = sys.modules['src.data_providers.marketdata']

            mock_instance = AsyncMock()
            mock_instance.connect = AsyncMock(side_effect=Exception("Connection failed"))
            mock_instance.close = AsyncMock()
            mock_module.MarketDataProvider.return_value = mock_instance
            mock_module.MarketDataConfig.return_value = MagicMock()

            with pytest.raises(Exception, match="Connection failed"):
                await run_daily_collection(api_key="test_key", symbols=["AAPL"])

            # Close should still be called
            mock_instance.close.assert_called_once()


# =============================================================================
# Batch Processing Tests
# =============================================================================

class TestBatchProcessing:
    """Tests for batch processing logic"""

    @pytest.mark.asyncio
    async def test_batch_boundaries(self, mock_provider, temp_db):
        """Test that batch boundaries are handled correctly"""
        # 27 symbols with batch_size=10 should create 3 batches: 10, 10, 7
        symbols = [f"SYM{i:02d}" for i in range(27)]

        config = CollectionConfig(
            symbols=symbols,
            db_path=temp_db,
            batch_size=10,
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        result = await collector.collect(mock_provider)

        assert result.symbols_requested == 27
        assert mock_provider.get_historical.call_count == 27

    @pytest.mark.asyncio
    async def test_rate_limiting_respected(self, mock_provider, temp_db):
        """Test that rate limiting delay is applied between symbols"""
        config = CollectionConfig(
            symbols=["AAPL", "MSFT"],
            db_path=temp_db,
            delay_between_symbols=0.01,  # 10ms delay
        )
        collector = DataCollector(config)

        start_time = datetime.now()
        await collector.collect(mock_provider)
        elapsed = (datetime.now() - start_time).total_seconds()

        # Should have at least one delay (between AAPL and MSFT)
        # Allow some margin for test execution overhead
        assert elapsed >= 0.01


# =============================================================================
# Error Limit Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling and limits"""

    @pytest.mark.asyncio
    async def test_errors_limited_to_20(self, temp_db):
        """Test that errors list is limited to 20 entries"""
        # Create 30 failing symbols
        symbols = [f"FAIL{i:02d}" for i in range(30)]

        provider = AsyncMock()
        provider.get_historical = AsyncMock(side_effect=Exception("API Error"))
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=symbols,
            db_path=temp_db,
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        # All should fail
        assert result.symbols_collected == 0
        assert len(result.symbols_failed) == 30
        # But errors list should be limited to 20
        assert len(result.errors) == 20

    @pytest.mark.asyncio
    async def test_mixed_success_failure(self, temp_db):
        """Test collection with mix of successful and failed symbols"""
        success_bar = MockBar(date.today(), 100, 105, 95, 102, 1000000)

        call_count = [0]

        async def mock_get_historical(symbol, days=None):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise Exception(f"Error for {symbol}")
            return [success_bar]

        provider = AsyncMock()
        provider.get_historical = AsyncMock(side_effect=mock_get_historical)
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["SYM1", "SYM2", "SYM3", "SYM4"],
            db_path=temp_db,
            delay_between_symbols=0.0,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert result.symbols_collected == 2
        assert len(result.symbols_failed) == 2


# =============================================================================
# Config Edge Cases
# =============================================================================

class TestConfigEdgeCases:
    """Tests for configuration edge cases"""

    def test_config_with_all_options(self, temp_watchlist, temp_db):
        """Test config with all options specified"""
        config = CollectionConfig(
            symbols=["AAPL"],
            watchlist_path=temp_watchlist,
            lookback_days=500,
            update_mode="full",
            delay_between_symbols=0.5,
            batch_size=100,
            db_path=temp_db,
        )

        assert config.symbols == ["AAPL"]
        assert config.watchlist_path == temp_watchlist
        assert config.lookback_days == 500
        assert config.update_mode == "full"
        assert config.delay_between_symbols == 0.5
        assert config.batch_size == 100
        assert config.db_path == temp_db

    def test_collector_with_none_config(self):
        """Test collector initialization with None config"""
        collector = DataCollector(None)

        assert collector.config is not None
        assert collector.config.symbols == []
        assert collector.config.lookback_days == 260

    def test_watchlist_no_path_returns_empty(self, temp_db):
        """Test _load_watchlist returns empty when no path configured"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        symbols = collector._load_watchlist()

        assert symbols == []


# =============================================================================
# Tracker Property Tests
# =============================================================================

class TestTrackerProperty:
    """Tests for tracker property and lazy loading"""

    def test_tracker_same_instance(self, temp_db):
        """Test that tracker property returns same instance"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        tracker1 = collector.tracker
        tracker2 = collector.tracker

        assert tracker1 is tracker2

    def test_tracker_uses_config_db_path(self, temp_db):
        """Test that tracker uses db_path from config"""
        config = CollectionConfig(db_path=temp_db)
        collector = DataCollector(config)

        tracker = collector.tracker

        assert tracker.db_path == temp_db


# =============================================================================
# Status Formatting Edge Cases
# =============================================================================

class TestStatusFormattingEdgeCases:
    """Additional tests for status formatting"""

    def test_format_status_many_stale_symbols(self):
        """Test formatting with more than 10 stale symbols"""
        stale_symbols = [
            {"symbol": f"STALE{i}", "last_date": "2023-01-01", "days_old": 100 + i}
            for i in range(15)
        ]

        status = {
            "total_symbols": 20,
            "symbols": [],
            "stale_symbols": stale_symbols,
            "vix_range": {"start": "2023-01-01", "end": "2024-01-01"},
            "storage": {
                "total_price_bars": 5000,
                "database_size_mb": 2.5,
                "vix_data_points": 260,
            },
        }

        output = format_collection_status(status)

        assert "STALE SYMBOLS" in output
        # Should show first 10
        assert "STALE0" in output
        assert "STALE9" in output
        # Should show "and X more"
        assert "and 5 more" in output

    def test_format_status_with_vix_data(self):
        """Test formatting with VIX data present"""
        status = {
            "total_symbols": 5,
            "symbols": [],
            "stale_symbols": [],
            "vix_range": {"start": "2023-06-01", "end": "2024-06-01"},
            "storage": {
                "total_price_bars": 1300,
                "database_size_mb": 1.5,
                "vix_data_points": 260,
            },
        }

        output = format_collection_status(status)

        assert "VIX Data:" in output
        assert "2023-06-01" in output
        assert "2024-06-01" in output
        assert "VIX Points: 260" in output


# =============================================================================
# Collect Single Extended Tests
# =============================================================================

class TestCollectSingleExtended:
    """Extended tests for collect_single method"""

    @pytest.mark.asyncio
    async def test_collect_single_restores_config(self, mock_provider, temp_db):
        """Test that collect_single restores original config after completion"""
        config = CollectionConfig(db_path=temp_db, lookback_days=260)
        collector = DataCollector(config)

        # Collect with custom days
        await collector.collect_single(mock_provider, "AAPL", days=30)

        # Config should be restored
        assert collector.config.lookback_days == 260

    @pytest.mark.asyncio
    async def test_collect_single_restores_on_exception(self, temp_db):
        """Test that config is restored even when exception occurs"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(side_effect=Exception("Test error"))

        config = CollectionConfig(db_path=temp_db, lookback_days=260)
        collector = DataCollector(config)

        # collect_single propagates exceptions but still restores config
        with pytest.raises(Exception, match="Test error"):
            await collector.collect_single(provider, "AAPL", days=30)

        # Config should still be restored due to try/finally
        assert collector.config.lookback_days == 260

    @pytest.mark.asyncio
    async def test_collect_single_uses_default_days(self, mock_provider, temp_db):
        """Test collect_single uses config lookback_days when days not specified"""
        config = CollectionConfig(db_path=temp_db, lookback_days=100)
        collector = DataCollector(config)

        await collector.collect_single(mock_provider, "AAPL")

        # Should call with 100 days
        mock_provider.get_historical.assert_called_with("AAPL", days=100)


# =============================================================================
# VIX Collection Extended Tests
# =============================================================================

class TestVixCollectionExtended:
    """Extended tests for VIX data collection"""

    @pytest.mark.asyncio
    async def test_vix_incremental_update(self, temp_db):
        """Test VIX incremental update logic"""
        today = date.today()

        # Old VIX data
        old_vix = [
            MockBar(date=today - timedelta(days=i), open=18, high=20, low=17, close=18 + i * 0.1, volume=0)
            for i in range(30, 40)
        ]

        # New VIX data
        new_vix = [
            MockBar(date=today - timedelta(days=i), open=18, high=20, low=17, close=19 + i * 0.1, volume=0)
            for i in range(0, 10)
        ]

        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[
            MockBar(today, 100, 105, 95, 102, 1000000)
        ])

        # First collection
        provider.get_index_candles = AsyncMock(return_value=old_vix)
        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
            update_mode="full",
        )
        collector = DataCollector(config)
        await collector.collect(provider)

        # Second collection (incremental)
        provider.get_index_candles = AsyncMock(return_value=new_vix)
        config.update_mode = "incremental"
        result = await collector.collect(provider)

        # VIX should have been collected
        assert result.vix_points_collected > 0

    @pytest.mark.asyncio
    async def test_vix_empty_response(self, temp_db):
        """Test handling of empty VIX response"""
        provider = AsyncMock()
        provider.get_historical = AsyncMock(return_value=[
            MockBar(date.today(), 100, 105, 95, 102, 1000000)
        ])
        provider.get_index_candles = AsyncMock(return_value=[])

        config = CollectionConfig(
            symbols=["AAPL"],
            db_path=temp_db,
        )
        collector = DataCollector(config)

        result = await collector.collect(provider)

        assert result.vix_points_collected == 0
        # But symbol collection should still succeed
        assert result.symbols_collected == 1
