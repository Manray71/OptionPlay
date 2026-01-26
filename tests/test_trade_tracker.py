# OptionPlay - Trade Tracker Tests
# =================================

import pytest
import tempfile
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from src.backtesting.trade_tracker import (
    TradeTracker,
    TrackedTrade,
    TradeStats,
    TradeStatus,
    TradeOutcome,
    PriceBar,
    SymbolPriceData,
    VixDataPoint,
    format_trade_stats,
    create_tracker,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_db():
    """Temporäre Datenbank für Tests"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def tracker(temp_db):
    """TradeTracker mit temporärer Datenbank"""
    return TradeTracker(db_path=temp_db)


@pytest.fixture
def sample_trade():
    """Beispiel-Trade"""
    return TrackedTrade(
        symbol="AAPL",
        strategy="pullback",
        signal_date=date(2024, 1, 15),
        signal_score=8.5,
        signal_strength="strong",
        score_breakdown={
            "rsi_score": 2.5,
            "support_score": 3.0,
            "trend_score": 2.0,
            "volume_score": 1.0,
        },
        vix_at_signal=15.5,
        iv_rank_at_signal=45.0,
        entry_price=175.00,
        stop_loss=170.00,
        target_price=185.00,
    )


@pytest.fixture
def multiple_trades():
    """Mehrere Trades für Statistik-Tests"""
    trades = []
    base_date = date(2024, 1, 1)

    # 10 Trades mit verschiedenen Scores und Outcomes
    for i in range(10):
        trade = TrackedTrade(
            symbol="AAPL" if i % 2 == 0 else "MSFT",
            strategy="pullback" if i % 3 != 0 else "breakout",
            signal_date=base_date + timedelta(days=i * 7),
            signal_score=5.0 + (i * 0.5),  # 5.0 bis 9.5
            signal_strength="strong" if i >= 5 else "moderate",
            entry_price=100.0 + i,
            stop_loss=95.0 + i,
            target_price=110.0 + i,
        )
        trades.append(trade)

    return trades


# =============================================================================
# TrackedTrade Tests
# =============================================================================

class TestTrackedTrade:
    """Tests für TrackedTrade Dataclass"""

    def test_create_trade(self, sample_trade):
        """Test Trade-Erstellung"""
        assert sample_trade.symbol == "AAPL"
        assert sample_trade.strategy == "pullback"
        assert sample_trade.signal_score == 8.5
        assert sample_trade.status == TradeStatus.OPEN
        assert sample_trade.outcome == TradeOutcome.PENDING

    def test_trade_to_dict(self, sample_trade):
        """Test Konvertierung zu Dictionary"""
        d = sample_trade.to_dict()

        assert d['symbol'] == "AAPL"
        assert d['strategy'] == "pullback"
        assert d['signal_score'] == 8.5
        assert d['status'] == "open"
        assert d['outcome'] == "pending"
        assert 'rsi_score' in d['score_breakdown']

    def test_trade_from_dict(self):
        """Test Erstellung aus Dictionary"""
        data = {
            'symbol': 'MSFT',
            'strategy': 'breakout',
            'signal_date': '2024-02-01',
            'signal_score': 7.5,
            'signal_strength': 'moderate',
            'score_breakdown': {'trend': 4.0},
            'status': 'closed',
            'outcome': 'win',
            'exit_date': '2024-02-15',
            'exit_price': 420.0,
            'pnl_percent': 5.5,
        }

        trade = TrackedTrade.from_dict(data)

        assert trade.symbol == "MSFT"
        assert trade.strategy == "breakout"
        assert trade.signal_date == date(2024, 2, 1)
        assert trade.status == TradeStatus.CLOSED
        assert trade.outcome == TradeOutcome.WIN

    def test_trade_defaults(self):
        """Test Default-Werte"""
        trade = TrackedTrade()

        assert trade.symbol == ""
        assert trade.status == TradeStatus.OPEN
        assert trade.outcome == TradeOutcome.PENDING
        assert trade.score_breakdown == {}
        assert trade.tags == []


# =============================================================================
# TradeTracker Basic Tests
# =============================================================================

class TestTradeTrackerBasic:
    """Grundlegende TradeTracker-Tests"""

    def test_create_tracker(self, temp_db):
        """Test Tracker-Erstellung"""
        tracker = TradeTracker(db_path=temp_db)

        assert tracker is not None
        assert tracker.db_path == temp_db
        assert os.path.exists(temp_db)

    def test_add_trade(self, tracker, sample_trade):
        """Test Trade hinzufügen"""
        trade_id = tracker.add_trade(sample_trade)

        assert trade_id > 0
        assert tracker.count_trades() == 1

    def test_get_trade(self, tracker, sample_trade):
        """Test Trade abrufen"""
        trade_id = tracker.add_trade(sample_trade)
        retrieved = tracker.get_trade(trade_id)

        assert retrieved is not None
        assert retrieved.id == trade_id
        assert retrieved.symbol == "AAPL"
        assert retrieved.signal_score == 8.5
        assert retrieved.score_breakdown['rsi_score'] == 2.5

    def test_get_nonexistent_trade(self, tracker):
        """Test nicht existenten Trade"""
        trade = tracker.get_trade(99999)
        assert trade is None

    def test_delete_trade(self, tracker, sample_trade):
        """Test Trade löschen"""
        trade_id = tracker.add_trade(sample_trade)
        assert tracker.count_trades() == 1

        result = tracker.delete_trade(trade_id)

        assert result is True
        assert tracker.count_trades() == 0

    def test_delete_nonexistent_trade(self, tracker):
        """Test Löschen nicht existenten Trades"""
        result = tracker.delete_trade(99999)
        assert result is False


# =============================================================================
# Trade Lifecycle Tests
# =============================================================================

class TestTradeLifecycle:
    """Tests für Trade-Lebenszyklus"""

    def test_close_trade_win(self, tracker, sample_trade):
        """Test Trade als Gewinn schließen"""
        trade_id = tracker.add_trade(sample_trade)

        result = tracker.close_trade(
            trade_id=trade_id,
            exit_price=182.50,
            outcome=TradeOutcome.WIN,
            exit_date=date(2024, 1, 25),
            exit_reason="target_reached",
        )

        assert result is True

        closed = tracker.get_trade(trade_id)
        assert closed.status == TradeStatus.CLOSED
        assert closed.outcome == TradeOutcome.WIN
        assert closed.exit_price == 182.50
        assert closed.exit_reason == "target_reached"
        assert closed.pnl_percent > 0
        assert closed.holding_days == 10

    def test_close_trade_loss(self, tracker, sample_trade):
        """Test Trade als Verlust schließen"""
        trade_id = tracker.add_trade(sample_trade)

        result = tracker.close_trade(
            trade_id=trade_id,
            exit_price=170.00,
            outcome=TradeOutcome.LOSS,
            exit_reason="stop_hit",
        )

        assert result is True

        closed = tracker.get_trade(trade_id)
        assert closed.status == TradeStatus.CLOSED
        assert closed.outcome == TradeOutcome.LOSS
        assert closed.pnl_percent < 0

    def test_close_already_closed_trade(self, tracker, sample_trade):
        """Test bereits geschlossenen Trade nochmal schließen"""
        trade_id = tracker.add_trade(sample_trade)

        tracker.close_trade(trade_id, exit_price=180.0, outcome=TradeOutcome.WIN)

        # Zweiter Versuch sollte fehlschlagen
        result = tracker.close_trade(trade_id, exit_price=185.0, outcome=TradeOutcome.WIN)
        assert result is False

    def test_close_nonexistent_trade(self, tracker):
        """Test nicht existenten Trade schließen"""
        result = tracker.close_trade(99999, exit_price=100.0, outcome=TradeOutcome.WIN)
        assert result is False

    def test_update_trade(self, tracker, sample_trade):
        """Test Trade aktualisieren"""
        trade_id = tracker.add_trade(sample_trade)

        result = tracker.update_trade(
            trade_id,
            notes="Adjusted stop after strong move",
            stop_loss=172.50,
            tags=["adjusted", "strong_move"],
        )

        assert result is True

        updated = tracker.get_trade(trade_id)
        assert updated.notes == "Adjusted stop after strong move"
        assert updated.stop_loss == 172.50
        assert "adjusted" in updated.tags


# =============================================================================
# Query Tests
# =============================================================================

class TestTradeQueries:
    """Tests für Trade-Abfragen"""

    def test_query_by_symbol(self, tracker, multiple_trades):
        """Test Abfrage nach Symbol"""
        for trade in multiple_trades:
            tracker.add_trade(trade)

        aapl_trades = tracker.query_trades(symbol="AAPL")
        msft_trades = tracker.query_trades(symbol="MSFT")

        assert len(aapl_trades) == 5
        assert len(msft_trades) == 5
        assert all(t.symbol == "AAPL" for t in aapl_trades)

    def test_query_by_strategy(self, tracker, multiple_trades):
        """Test Abfrage nach Strategie"""
        for trade in multiple_trades:
            tracker.add_trade(trade)

        pullback_trades = tracker.query_trades(strategy="pullback")
        breakout_trades = tracker.query_trades(strategy="breakout")

        assert len(pullback_trades) > 0
        assert len(breakout_trades) > 0
        assert all(t.strategy == "pullback" for t in pullback_trades)

    def test_query_by_status(self, tracker, multiple_trades):
        """Test Abfrage nach Status"""
        # Add trades
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        # Close some
        for i, tid in enumerate(trade_ids[:5]):
            outcome = TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS
            tracker.close_trade(tid, exit_price=105.0, outcome=outcome)

        open_trades = tracker.query_trades(status=TradeStatus.OPEN)
        closed_trades = tracker.query_trades(status=TradeStatus.CLOSED)

        assert len(open_trades) == 5
        assert len(closed_trades) == 5

    def test_query_by_score_range(self, tracker, multiple_trades):
        """Test Abfrage nach Score-Bereich"""
        for trade in multiple_trades:
            tracker.add_trade(trade)

        high_score = tracker.query_trades(min_score=8.0)
        low_score = tracker.query_trades(max_score=6.0)

        assert all(t.signal_score >= 8.0 for t in high_score)
        assert all(t.signal_score <= 6.0 for t in low_score)

    def test_query_by_date_range(self, tracker, multiple_trades):
        """Test Abfrage nach Datumsbereich"""
        for trade in multiple_trades:
            tracker.add_trade(trade)

        jan_trades = tracker.query_trades(
            min_date=date(2024, 1, 1),
            max_date=date(2024, 1, 31),
        )

        assert len(jan_trades) > 0
        for t in jan_trades:
            assert t.signal_date.month == 1

    def test_get_open_trades(self, tracker, multiple_trades):
        """Test Abruf offener Trades"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        # Close half
        for tid in trade_ids[:5]:
            tracker.close_trade(tid, exit_price=100.0, outcome=TradeOutcome.WIN)

        open_trades = tracker.get_open_trades()

        assert len(open_trades) == 5
        assert all(t.status == TradeStatus.OPEN for t in open_trades)

    def test_query_limit(self, tracker, multiple_trades):
        """Test Query Limit"""
        for trade in multiple_trades:
            tracker.add_trade(trade)

        limited = tracker.query_trades(limit=3)

        assert len(limited) == 3


# =============================================================================
# Statistics Tests
# =============================================================================

class TestTradeStatistics:
    """Tests für Statistik-Berechnungen"""

    def test_get_stats_empty(self, tracker):
        """Test Statistiken ohne Trades"""
        stats = tracker.get_stats()

        assert stats.total_trades == 0
        assert stats.win_rate == 0.0

    def test_get_stats_basic(self, tracker, multiple_trades):
        """Test grundlegende Statistiken"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        # Close with mixed outcomes
        for i, tid in enumerate(trade_ids):
            outcome = TradeOutcome.WIN if i % 3 != 0 else TradeOutcome.LOSS
            tracker.close_trade(
                tid,
                exit_price=105.0 if outcome == TradeOutcome.WIN else 95.0,
                outcome=outcome,
            )

        stats = tracker.get_stats()

        assert stats.total_trades == 10
        assert stats.closed_trades == 10
        assert stats.wins + stats.losses == 10
        assert 0 <= stats.win_rate <= 100

    def test_stats_by_strategy(self, tracker, multiple_trades):
        """Test Statistiken pro Strategie"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        for tid in trade_ids:
            tracker.close_trade(tid, exit_price=105.0, outcome=TradeOutcome.WIN)

        stats = tracker.get_stats()

        assert 'pullback' in stats.by_strategy
        assert stats.by_strategy['pullback']['count'] > 0
        assert stats.by_strategy['pullback']['win_rate'] > 0

    def test_stats_by_score_bucket(self, tracker, multiple_trades):
        """Test Statistiken pro Score-Bucket"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        for tid in trade_ids:
            tracker.close_trade(tid, exit_price=105.0, outcome=TradeOutcome.WIN)

        stats = tracker.get_stats()

        # Sollte mehrere Buckets haben
        assert len(stats.by_score_bucket) > 0

        # Jeder Bucket sollte Count und Win Rate haben
        for bucket, data in stats.by_score_bucket.items():
            assert 'count' in data
            assert 'win_rate' in data

    def test_stats_filter_by_strategy(self, tracker, multiple_trades):
        """Test Statistiken gefiltert nach Strategie"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        for tid in trade_ids:
            tracker.close_trade(tid, exit_price=105.0, outcome=TradeOutcome.WIN)

        pullback_stats = tracker.get_stats(strategy="pullback")

        assert pullback_stats.total_trades < 10  # Nicht alle sind Pullbacks


# =============================================================================
# Export Tests
# =============================================================================

class TestTradeExport:
    """Tests für Datenexport"""

    def test_export_for_training(self, tracker, multiple_trades):
        """Test Export für Training"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        # Close all
        for i, tid in enumerate(trade_ids):
            outcome = TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS
            tracker.close_trade(tid, exit_price=105.0, outcome=outcome)

        export = tracker.export_for_training(min_trades=5)

        assert 'version' in export
        assert 'export_date' in export
        assert 'total_trades' in export
        assert 'trades' in export

        assert export['total_trades'] == 10
        assert len(export['trades']) == 10

        # Check trade format
        trade_data = export['trades'][0]
        assert 'symbol' in trade_data
        assert 'score' in trade_data
        assert 'outcome' in trade_data

    def test_export_filter_by_strategy(self, tracker, multiple_trades):
        """Test Export gefiltert nach Strategie"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        for tid in trade_ids:
            tracker.close_trade(tid, exit_price=105.0, outcome=TradeOutcome.WIN)

        export = tracker.export_for_training(
            strategies=["pullback"],
            min_trades=1,
        )

        assert all(t['strategy'] == 'pullback' for t in export['trades'])

    def test_export_filter_by_date(self, tracker, multiple_trades):
        """Test Export gefiltert nach Datum"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        for tid in trade_ids:
            tracker.close_trade(tid, exit_price=105.0, outcome=TradeOutcome.WIN)

        export = tracker.export_for_training(
            min_date=date(2024, 1, 15),
            max_date=date(2024, 2, 15),
            min_trades=1,
        )

        # Sollte weniger Trades haben
        assert export['total_trades'] < 10


# =============================================================================
# Format Tests
# =============================================================================

class TestFormatting:
    """Tests für Formatierung"""

    def test_format_trade_stats(self, tracker, multiple_trades):
        """Test Stats-Formatierung"""
        trade_ids = [tracker.add_trade(t) for t in multiple_trades]

        for i, tid in enumerate(trade_ids):
            outcome = TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS
            tracker.close_trade(tid, exit_price=105.0, outcome=outcome)

        stats = tracker.get_stats()
        output = format_trade_stats(stats)

        assert "TRADE STATISTICS" in output
        assert "Win Rate:" in output
        assert "Total Trades:" in output
        assert "BY SCORE BUCKET:" in output


# =============================================================================
# Factory Tests
# =============================================================================

class TestFactory:
    """Tests für Factory-Funktionen"""

    def test_create_tracker(self, temp_db):
        """Test create_tracker Factory"""
        tracker = create_tracker(db_path=temp_db)

        assert tracker is not None
        assert isinstance(tracker, TradeTracker)


# =============================================================================
# Persistence Tests
# =============================================================================

class TestPersistence:
    """Tests für Datenpersistenz"""

    def test_data_persists(self, temp_db, sample_trade):
        """Test dass Daten persistiert werden"""
        # Create tracker and add trade
        tracker1 = TradeTracker(db_path=temp_db)
        trade_id = tracker1.add_trade(sample_trade)

        # Create new tracker with same DB
        tracker2 = TradeTracker(db_path=temp_db)

        # Trade should still exist
        trade = tracker2.get_trade(trade_id)
        assert trade is not None
        assert trade.symbol == "AAPL"

    def test_score_breakdown_persists(self, temp_db, sample_trade):
        """Test dass Score-Breakdown korrekt persistiert wird"""
        tracker1 = TradeTracker(db_path=temp_db)
        trade_id = tracker1.add_trade(sample_trade)

        tracker2 = TradeTracker(db_path=temp_db)
        trade = tracker2.get_trade(trade_id)

        assert trade.score_breakdown == sample_trade.score_breakdown
        assert trade.score_breakdown['rsi_score'] == 2.5

    def test_tags_persist(self, temp_db, sample_trade):
        """Test dass Tags korrekt persistiert werden"""
        sample_trade.tags = ["momentum", "earnings"]

        tracker1 = TradeTracker(db_path=temp_db)
        trade_id = tracker1.add_trade(sample_trade)

        tracker2 = TradeTracker(db_path=temp_db)
        trade = tracker2.get_trade(trade_id)

        assert trade.tags == ["momentum", "earnings"]


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests für Edge Cases"""

    def test_trade_without_prices(self, tracker):
        """Test Trade ohne Preise"""
        trade = TrackedTrade(
            symbol="TEST",
            strategy="test",
            signal_score=7.0,
        )

        trade_id = tracker.add_trade(trade)
        retrieved = tracker.get_trade(trade_id)

        assert retrieved.entry_price is None
        assert retrieved.stop_loss is None

    def test_close_trade_calculates_pnl(self, tracker):
        """Test P&L Berechnung beim Schließen"""
        trade = TrackedTrade(
            symbol="TEST",
            strategy="test",
            signal_date=date(2024, 1, 1),
            signal_score=8.0,
            entry_price=100.0,
        )

        trade_id = tracker.add_trade(trade)
        tracker.close_trade(
            trade_id,
            exit_price=110.0,
            outcome=TradeOutcome.WIN,
            exit_date=date(2024, 1, 11),
        )

        closed = tracker.get_trade(trade_id)

        assert closed.pnl_amount == 10.0
        assert closed.pnl_percent == 10.0
        assert closed.holding_days == 10

    def test_empty_score_breakdown(self, tracker):
        """Test mit leerem Score-Breakdown"""
        trade = TrackedTrade(
            symbol="TEST",
            strategy="test",
            signal_score=7.0,
            score_breakdown={},
        )

        trade_id = tracker.add_trade(trade)
        retrieved = tracker.get_trade(trade_id)

        assert retrieved.score_breakdown == {}

    def test_special_characters_in_notes(self, tracker):
        """Test Sonderzeichen in Notes"""
        trade = TrackedTrade(
            symbol="TEST",
            strategy="test",
            signal_score=7.0,
            notes="Test with 'quotes' and \"double quotes\" and newline\nhere",
        )

        trade_id = tracker.add_trade(trade)
        retrieved = tracker.get_trade(trade_id)

        assert "quotes" in retrieved.notes
        assert "\n" in retrieved.notes


# =============================================================================
# Price Data Tests
# =============================================================================

@pytest.fixture
def sample_price_bars():
    """Beispiel-Preisdaten"""
    base_date = date(2024, 1, 1)
    bars = []
    for i in range(100):
        bars.append(PriceBar(
            date=base_date + timedelta(days=i),
            open=100.0 + i * 0.1,
            high=102.0 + i * 0.1,
            low=98.0 + i * 0.1,
            close=101.0 + i * 0.1,
            volume=1000000 + i * 10000,
        ))
    return bars


@pytest.fixture
def sample_vix_data():
    """Beispiel-VIX-Daten"""
    base_date = date(2024, 1, 1)
    return [
        VixDataPoint(date=base_date + timedelta(days=i), value=15.0 + (i % 10))
        for i in range(100)
    ]


class TestPriceBar:
    """Tests für PriceBar Dataclass"""

    def test_create_price_bar(self):
        """Test PriceBar-Erstellung"""
        bar = PriceBar(
            date=date(2024, 1, 15),
            open=175.0,
            high=178.0,
            low=174.0,
            close=177.0,
            volume=50000000,
        )

        assert bar.date == date(2024, 1, 15)
        assert bar.close == 177.0

    def test_price_bar_to_dict(self):
        """Test Konvertierung zu Dictionary"""
        bar = PriceBar(
            date=date(2024, 1, 15),
            open=175.0,
            high=178.0,
            low=174.0,
            close=177.0,
            volume=50000000,
        )

        d = bar.to_dict()
        assert d['date'] == '2024-01-15'
        assert d['close'] == 177.0

    def test_price_bar_from_dict(self):
        """Test Erstellung aus Dictionary"""
        data = {
            'date': '2024-01-15',
            'open': 175.0,
            'high': 178.0,
            'low': 174.0,
            'close': 177.0,
            'volume': 50000000,
        }

        bar = PriceBar.from_dict(data)
        assert bar.date == date(2024, 1, 15)
        assert bar.volume == 50000000


class TestPriceDataStorage:
    """Tests für Preisdaten-Speicherung"""

    def test_store_price_data(self, tracker, sample_price_bars):
        """Test Preisdaten speichern"""
        count = tracker.store_price_data("AAPL", sample_price_bars)

        assert count == 100

    def test_get_price_data(self, tracker, sample_price_bars):
        """Test Preisdaten laden"""
        tracker.store_price_data("AAPL", sample_price_bars)

        data = tracker.get_price_data("AAPL")

        assert data is not None
        assert data.symbol == "AAPL"
        assert len(data.bars) == 100
        assert data.first_date == date(2024, 1, 1)

    def test_get_price_data_filtered(self, tracker, sample_price_bars):
        """Test Preisdaten mit Datum-Filter"""
        tracker.store_price_data("AAPL", sample_price_bars)

        data = tracker.get_price_data(
            "AAPL",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 31),
        )

        assert data is not None
        assert len(data.bars) == 17  # 15. bis 31. Jan

    def test_get_price_data_nonexistent(self, tracker):
        """Test nicht existente Preisdaten"""
        data = tracker.get_price_data("UNKNOWN")
        assert data is None

    def test_get_price_data_range(self, tracker, sample_price_bars):
        """Test Datumsbereich-Abfrage"""
        tracker.store_price_data("AAPL", sample_price_bars)

        date_range = tracker.get_price_data_range("AAPL")

        assert date_range is not None
        assert date_range[0] == date(2024, 1, 1)
        assert date_range[1] == date(2024, 4, 9)  # 100 Tage ab 1.1.

    def test_list_symbols_with_price_data(self, tracker, sample_price_bars):
        """Test Symbol-Liste"""
        tracker.store_price_data("AAPL", sample_price_bars)
        tracker.store_price_data("MSFT", sample_price_bars[:50])

        symbols = tracker.list_symbols_with_price_data()

        assert len(symbols) == 2
        assert any(s['symbol'] == 'AAPL' for s in symbols)
        assert any(s['symbol'] == 'MSFT' for s in symbols)

    def test_delete_price_data(self, tracker, sample_price_bars):
        """Test Preisdaten löschen"""
        tracker.store_price_data("AAPL", sample_price_bars)
        assert tracker.get_price_data("AAPL") is not None

        result = tracker.delete_price_data("AAPL")

        assert result is True
        assert tracker.get_price_data("AAPL") is None

    def test_store_price_data_merge(self, tracker):
        """Test Preisdaten-Merge"""
        # Erste Batch
        bars1 = [
            PriceBar(date=date(2024, 1, i), open=100, high=102, low=98, close=101, volume=1000)
            for i in range(1, 11)
        ]
        tracker.store_price_data("AAPL", bars1)

        # Zweite Batch mit Überlappung
        bars2 = [
            PriceBar(date=date(2024, 1, i), open=100, high=102, low=98, close=102, volume=2000)
            for i in range(5, 16)
        ]
        tracker.store_price_data("AAPL", bars2, merge=True)

        data = tracker.get_price_data("AAPL")

        # Sollte 15 Bars haben (1-15 Jan)
        assert len(data.bars) == 15

        # Neuere Daten sollten überschrieben haben
        bar_jan10 = next(b for b in data.bars if b.date == date(2024, 1, 10))
        assert bar_jan10.close == 102  # Von bars2
        assert bar_jan10.volume == 2000

    def test_compression_efficiency(self, tracker):
        """Test dass Kompression funktioniert"""
        # Erzeuge größere Datenmenge
        bars = [
            PriceBar(
                date=date(2024, 1, 1) + timedelta(days=i),
                open=100.0 + i * 0.1,
                high=102.0 + i * 0.1,
                low=98.0 + i * 0.1,
                close=101.0 + i * 0.1,
                volume=1000000,
            )
            for i in range(500)
        ]

        tracker.store_price_data("AAPL", bars)
        stats = tracker.get_storage_stats()

        # Komprimierte Größe sollte deutlich kleiner sein
        # 500 Bars unkomprimiert wären ca. 50-60KB
        assert stats['price_data_compressed_kb'] < 20  # Sollte unter 20KB sein


class TestVixDataStorage:
    """Tests für VIX-Daten-Speicherung"""

    def test_store_vix_data(self, tracker, sample_vix_data):
        """Test VIX-Daten speichern"""
        count = tracker.store_vix_data(sample_vix_data)
        assert count == 100

    def test_get_vix_data(self, tracker, sample_vix_data):
        """Test VIX-Daten laden"""
        tracker.store_vix_data(sample_vix_data)

        data = tracker.get_vix_data()

        assert len(data) == 100
        assert data[0].date == date(2024, 1, 1)

    def test_get_vix_data_filtered(self, tracker, sample_vix_data):
        """Test VIX-Daten mit Datum-Filter"""
        tracker.store_vix_data(sample_vix_data)

        data = tracker.get_vix_data(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 31),
        )

        assert len(data) == 17

    def test_get_vix_at_date(self, tracker, sample_vix_data):
        """Test VIX für bestimmtes Datum"""
        tracker.store_vix_data(sample_vix_data)

        vix = tracker.get_vix_at_date(date(2024, 1, 15))

        assert vix is not None
        assert isinstance(vix, float)

    def test_get_vix_at_date_fallback(self, tracker):
        """Test VIX-Fallback auf vorheriges Datum"""
        # Speichere nur für bestimmte Tage
        vix_data = [
            VixDataPoint(date=date(2024, 1, 1), value=15.0),
            VixDataPoint(date=date(2024, 1, 5), value=18.0),
        ]
        tracker.store_vix_data(vix_data)

        # Frage Datum zwischen den beiden ab
        vix = tracker.get_vix_at_date(date(2024, 1, 3))

        # Sollte den Wert vom 1.1. zurückgeben
        assert vix == 15.0

    def test_get_vix_range(self, tracker, sample_vix_data):
        """Test VIX-Datumsbereich"""
        tracker.store_vix_data(sample_vix_data)

        date_range = tracker.get_vix_range()

        assert date_range is not None
        assert date_range[0] == date(2024, 1, 1)

    def test_count_vix_data(self, tracker, sample_vix_data):
        """Test VIX-Datenpunkte zählen"""
        tracker.store_vix_data(sample_vix_data)

        count = tracker.count_vix_data()
        assert count == 100


class TestBulkExport:
    """Tests für Bulk-Export"""

    def test_export_for_backtesting(self, tracker, sample_price_bars, sample_vix_data, sample_trade):
        """Test kompletter Export für Backtesting"""
        # Speichere Daten
        tracker.store_price_data("AAPL", sample_price_bars)
        tracker.store_vix_data(sample_vix_data)
        trade_id = tracker.add_trade(sample_trade)
        tracker.close_trade(trade_id, exit_price=180.0, outcome=TradeOutcome.WIN)

        # Export
        export = tracker.export_for_backtesting()

        assert export['version'] == '2.0.0'
        assert 'AAPL' in export['price_data']
        assert len(export['vix_data']) == 100
        assert len(export['trades']) == 1

        # Summary
        assert export['summary']['symbols_count'] == 1
        assert export['summary']['total_bars'] == 100

    def test_export_filtered(self, tracker, sample_price_bars, sample_vix_data):
        """Test Export mit Filtern"""
        tracker.store_price_data("AAPL", sample_price_bars)
        tracker.store_price_data("MSFT", sample_price_bars[:50])
        tracker.store_vix_data(sample_vix_data)

        export = tracker.export_for_backtesting(
            symbols=["AAPL"],
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 31),
        )

        assert 'AAPL' in export['price_data']
        assert 'MSFT' not in export['price_data']
        assert len(export['price_data']['AAPL']) == 17


class TestStorageStats:
    """Tests für Speicher-Statistiken"""

    def test_get_storage_stats(self, tracker, sample_price_bars, sample_vix_data, sample_trade):
        """Test Speicher-Statistiken"""
        tracker.store_price_data("AAPL", sample_price_bars)
        tracker.store_vix_data(sample_vix_data)
        tracker.add_trade(sample_trade)

        stats = tracker.get_storage_stats()

        assert stats['trades_count'] == 1
        assert stats['symbols_with_price_data'] == 1
        assert stats['total_price_bars'] == 100
        assert stats['vix_data_points'] == 100
        assert stats['database_size_mb'] > 0

    def test_storage_stats_empty(self, tracker):
        """Test Statistiken bei leerer DB"""
        stats = tracker.get_storage_stats()

        assert stats['trades_count'] == 0
        assert stats['symbols_with_price_data'] == 0


class TestPriceDataPersistence:
    """Tests für Preisdaten-Persistenz"""

    def test_price_data_persists(self, temp_db, sample_price_bars):
        """Test dass Preisdaten persistiert werden"""
        tracker1 = TradeTracker(db_path=temp_db)
        tracker1.store_price_data("AAPL", sample_price_bars)

        tracker2 = TradeTracker(db_path=temp_db)
        data = tracker2.get_price_data("AAPL")

        assert data is not None
        assert len(data.bars) == 100

    def test_vix_data_persists(self, temp_db, sample_vix_data):
        """Test dass VIX-Daten persistiert werden"""
        tracker1 = TradeTracker(db_path=temp_db)
        tracker1.store_vix_data(sample_vix_data)

        tracker2 = TradeTracker(db_path=temp_db)
        data = tracker2.get_vix_data()

        assert len(data) == 100
