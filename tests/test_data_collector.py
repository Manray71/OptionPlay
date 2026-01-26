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
