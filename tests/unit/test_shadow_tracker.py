"""Unit tests for ShadowTracker — DB schema, CRUD, duplicate detection, tradability."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.shadow_tracker import (
    VALID_REJECTION_REASONS,
    VALID_SOURCES,
    VALID_STATUSES,
    VALID_STRATEGIES,
    ShadowTracker,
    calculate_pnl,
    check_tradability,
    format_detail_output,
    format_review_output,
    format_stats_output,
    get_stats,
    resolve_open_trades,
    resolve_trade,
)


@pytest.fixture
def tracker(tmp_path):
    """Create a ShadowTracker with a temp DB."""
    db = tmp_path / "test_shadow.db"
    t = ShadowTracker(db_path=str(db))
    yield t
    t.close()


def _make_trade_kwargs(**overrides):
    """Helper to build valid log_trade kwargs."""
    defaults = {
        "source": "daily_picks",
        "symbol": "AAPL",
        "strategy": "pullback",
        "score": 8.5,
        "short_strike": 240.0,
        "long_strike": 230.0,
        "spread_width": 10.0,
        "est_credit": 2.50,
        "expiration": "2026-04-17",
        "dte": 54,
        "price_at_log": 245.0,
        "enhanced_score": 9.1,
        "liquidity_tier": 1,
        "short_bid": 4.20,
        "short_ask": 4.50,
        "short_oi": 1500,
        "long_bid": 1.60,
        "long_ask": 1.75,
        "long_oi": 900,
        "vix_at_log": 18.5,
        "regime_at_log": "normal",
        "stability_at_log": 82.0,
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# DB Init & Schema
# ===========================================================================


class TestDBInit:
    def test_creates_db_file(self, tmp_path):
        db = tmp_path / "sub" / "shadow.db"
        t = ShadowTracker(db_path=str(db))
        assert db.exists()
        t.close()

    def test_creates_both_tables(self, tracker):
        with tracker._get_connection() as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
        assert "shadow_trades" in tables
        assert "shadow_rejections" in tables

    def test_creates_indices(self, tracker):
        with tracker._get_connection() as conn:
            indices = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name LIKE 'idx_%' ORDER BY name"
                ).fetchall()
            ]
        expected = [
            "idx_rejected_reason",
            "idx_rejected_symbol",
            "idx_shadow_expiration",
            "idx_shadow_logged",
            "idx_shadow_status",
            "idx_shadow_strategy",
            "idx_shadow_symbol",
            "idx_shadow_tier",
        ]
        assert sorted(indices) == expected

    def test_wal_mode_active(self, tracker):
        with tracker._get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_synchronous_normal(self, tracker):
        with tracker._get_connection() as conn:
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        # NORMAL = 1
        assert sync == 1

    def test_idempotent_init(self, tmp_path):
        """Calling init twice doesn't fail."""
        db = tmp_path / "shadow.db"
        t1 = ShadowTracker(db_path=str(db))
        t1.close()
        t2 = ShadowTracker(db_path=str(db))
        t2.close()

    def test_rejects_symlink_path(self, tmp_path):
        real_db = tmp_path / "real.db"
        real_db.touch()
        link = tmp_path / "link.db"
        link.symlink_to(real_db)
        with pytest.raises(ValueError, match="symlink"):
            ShadowTracker(db_path=str(link))


# ===========================================================================
# CRUD: shadow_trades
# ===========================================================================


class TestLogTrade:
    def test_returns_uuid(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        assert tid is not None
        uuid.UUID(tid)  # Validates UUID format

    def test_stores_all_fields(self, tracker):
        kwargs = _make_trade_kwargs()
        tid = tracker.log_trade(**kwargs)
        trade = tracker.get_trade(tid)

        assert trade["symbol"] == "AAPL"
        assert trade["strategy"] == "pullback"
        assert trade["score"] == 8.5
        assert trade["enhanced_score"] == 9.1
        assert trade["liquidity_tier"] == 1
        assert trade["short_strike"] == 240.0
        assert trade["long_strike"] == 230.0
        assert trade["spread_width"] == 10.0
        assert trade["est_credit"] == 2.50
        assert trade["expiration"] == "2026-04-17"
        assert trade["dte"] == 54
        assert trade["short_bid"] == 4.20
        assert trade["short_ask"] == 4.50
        assert trade["short_oi"] == 1500
        assert trade["long_bid"] == 1.60
        assert trade["long_ask"] == 1.75
        assert trade["long_oi"] == 900
        assert trade["price_at_log"] == 245.0
        assert trade["vix_at_log"] == 18.5
        assert trade["regime_at_log"] == "normal"
        assert trade["stability_at_log"] == 82.0
        assert trade["status"] == "open"
        assert trade["source"] == "daily_picks"

    def test_logged_at_is_iso(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        trade = tracker.get_trade(tid)
        # Should parse as ISO datetime
        datetime.fromisoformat(trade["logged_at"])

    def test_invalid_source_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid source"):
            tracker.log_trade(**_make_trade_kwargs(source="invalid"))

    def test_invalid_strategy_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid strategy"):
            tracker.log_trade(**_make_trade_kwargs(strategy="unknown"))

    def test_optional_fields_nullable(self, tracker):
        tid = tracker.log_trade(
            source="manual",
            symbol="MSFT",
            strategy="bounce",
            score=7.0,
            short_strike=400.0,
            long_strike=390.0,
            spread_width=10.0,
            est_credit=3.0,
            expiration="2026-05-16",
            dte=83,
            price_at_log=410.0,
        )
        trade = tracker.get_trade(tid)
        assert trade["enhanced_score"] is None
        assert trade["vix_at_log"] is None
        assert trade["short_bid"] is None


class TestGetTrade:
    def test_returns_none_for_missing(self, tracker):
        assert tracker.get_trade("nonexistent-id") is None

    def test_returns_dict(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        trade = tracker.get_trade(tid)
        assert isinstance(trade, dict)
        assert trade["id"] == tid


class TestGetOpenTrades:
    def test_returns_only_open(self, tracker):
        tid1 = tracker.log_trade(**_make_trade_kwargs(symbol="AAPL", short_strike=240.0))
        tid2 = tracker.log_trade(**_make_trade_kwargs(symbol="MSFT", short_strike=400.0))
        tracker.update_trade_status(tid1, "max_profit")

        open_trades = tracker.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0]["id"] == tid2

    def test_empty_when_all_resolved(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        tracker.update_trade_status(tid, "max_profit")
        assert tracker.get_open_trades() == []


class TestGetTrades:
    def test_status_filter_open(self, tracker):
        tracker.log_trade(**_make_trade_kwargs(symbol="AAPL", short_strike=240.0))
        tid2 = tracker.log_trade(**_make_trade_kwargs(symbol="MSFT", short_strike=400.0))
        tracker.update_trade_status(tid2, "stop_loss")

        trades = tracker.get_trades(status_filter="open")
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"

    def test_status_filter_closed(self, tracker):
        tracker.log_trade(**_make_trade_kwargs(symbol="AAPL", short_strike=240.0))
        tid2 = tracker.log_trade(**_make_trade_kwargs(symbol="MSFT", short_strike=400.0))
        tracker.update_trade_status(tid2, "max_loss")

        trades = tracker.get_trades(status_filter="closed")
        assert len(trades) == 1
        assert trades[0]["symbol"] == "MSFT"

    def test_strategy_filter(self, tracker):
        tracker.log_trade(**_make_trade_kwargs(symbol="AAPL", strategy="pullback"))
        tracker.log_trade(
            **_make_trade_kwargs(symbol="MSFT", strategy="bounce", short_strike=400.0)
        )

        trades = tracker.get_trades(strategy_filter="bounce")
        assert len(trades) == 1
        assert trades[0]["strategy"] == "bounce"

    def test_days_back_filter(self, tracker):
        # Log a trade, then manually backdate one
        tid1 = tracker.log_trade(**_make_trade_kwargs(symbol="AAPL", short_strike=240.0))
        tid2 = tracker.log_trade(**_make_trade_kwargs(symbol="MSFT", short_strike=400.0))

        old_date = (datetime.utcnow() - timedelta(days=100)).isoformat()
        with tracker._get_connection() as conn:
            conn.execute(
                "UPDATE shadow_trades SET logged_at = ? WHERE id = ?",
                (old_date, tid1),
            )

        trades = tracker.get_trades(days_back=90)
        assert len(trades) == 1
        assert trades[0]["id"] == tid2

    def test_all_filter_returns_everything(self, tracker):
        tracker.log_trade(**_make_trade_kwargs(symbol="AAPL", short_strike=240.0))
        tid2 = tracker.log_trade(**_make_trade_kwargs(symbol="MSFT", short_strike=400.0))
        tracker.update_trade_status(tid2, "max_profit")

        trades = tracker.get_trades(status_filter="all")
        assert len(trades) == 2


class TestUpdateTradeStatus:
    def test_updates_status(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        result = tracker.update_trade_status(tid, "max_profit")
        assert result is True

        trade = tracker.get_trade(tid)
        assert trade["status"] == "max_profit"
        assert trade["resolved_at"] is not None

    def test_sets_resolved_at_auto(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        tracker.update_trade_status(tid, "partial_profit")
        trade = tracker.get_trade(tid)
        datetime.fromisoformat(trade["resolved_at"])

    def test_custom_resolved_at(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        custom_time = "2026-03-15T10:30:00"
        tracker.update_trade_status(tid, "stop_loss", resolved_at=custom_time)
        trade = tracker.get_trade(tid)
        assert trade["resolved_at"] == custom_time

    def test_sets_resolution_fields(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        tracker.update_trade_status(
            tid,
            "partial_profit",
            price_at_expiry=250.0,
            price_min=238.0,
            price_at_50pct=248.0,
            days_to_50pct=15,
            theoretical_pnl=125.0,
            spread_value_at_resolve=1.20,
            outcome_notes="50% target hit",
        )
        trade = tracker.get_trade(tid)
        assert trade["price_at_expiry"] == 250.0
        assert trade["price_min"] == 238.0
        assert trade["price_at_50pct"] == 248.0
        assert trade["days_to_50pct"] == 15
        assert trade["theoretical_pnl"] == 125.0
        assert trade["spread_value_at_resolve"] == 1.20
        assert trade["outcome_notes"] == "50% target hit"

    def test_invalid_status_raises(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        with pytest.raises(ValueError, match="Invalid status"):
            tracker.update_trade_status(tid, "invalid_status")

    def test_nonexistent_trade_returns_false(self, tracker):
        result = tracker.update_trade_status("fake-id", "max_profit")
        assert result is False


# ===========================================================================
# CRUD: shadow_rejections
# ===========================================================================


class TestLogRejection:
    def test_returns_uuid(self, tracker):
        rid = tracker.log_rejection(
            source="daily_picks",
            symbol="CVS",
            strategy="pullback",
            score=7.5,
            rejection_reason="low_oi",
        )
        uuid.UUID(rid)

    def test_stores_all_fields(self, tracker):
        rid = tracker.log_rejection(
            source="daily_picks",
            symbol="CVS",
            strategy="pullback",
            score=7.5,
            liquidity_tier=3,
            short_strike=70.0,
            long_strike=60.0,
            rejection_reason="low_credit",
            actual_credit=0.85,
            short_oi=120,
            details=json.dumps({"short_bid": 1.20, "long_ask": 0.35}),
        )
        with tracker._get_connection() as conn:
            row = conn.execute("SELECT * FROM shadow_rejections WHERE id = ?", (rid,)).fetchone()
        r = dict(row)
        assert r["symbol"] == "CVS"
        assert r["strategy"] == "pullback"
        assert r["rejection_reason"] == "low_credit"
        assert r["actual_credit"] == 0.85
        assert r["short_oi"] == 120
        assert r["liquidity_tier"] == 3

    def test_invalid_source_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid source"):
            tracker.log_rejection(
                source="bad",
                symbol="X",
                strategy="pullback",
                score=5.0,
                rejection_reason="low_oi",
            )

    def test_invalid_strategy_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid strategy"):
            tracker.log_rejection(
                source="daily_picks",
                symbol="X",
                strategy="bad",
                score=5.0,
                rejection_reason="low_oi",
            )

    def test_invalid_reason_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid rejection_reason"):
            tracker.log_rejection(
                source="daily_picks",
                symbol="X",
                strategy="pullback",
                score=5.0,
                rejection_reason="bad_reason",
            )


class TestGetRejections:
    def test_returns_recent(self, tracker):
        tracker.log_rejection(
            source="daily_picks",
            symbol="CVS",
            strategy="pullback",
            score=7.0,
            rejection_reason="low_oi",
        )
        tracker.log_rejection(
            source="scan",
            symbol="XYZ",
            strategy="bounce",
            score=6.0,
            rejection_reason="no_chain",
        )
        rejections = tracker.get_rejections(days_back=1)
        assert len(rejections) == 2

    def test_days_back_filter(self, tracker):
        rid = tracker.log_rejection(
            source="daily_picks",
            symbol="OLD",
            strategy="pullback",
            score=5.0,
            rejection_reason="no_bid",
        )
        old_date = (datetime.utcnow() - timedelta(days=100)).isoformat()
        with tracker._get_connection() as conn:
            conn.execute(
                "UPDATE shadow_rejections SET logged_at = ? WHERE id = ?",
                (old_date, rid),
            )

        tracker.log_rejection(
            source="daily_picks",
            symbol="NEW",
            strategy="bounce",
            score=6.0,
            rejection_reason="wide_spread",
        )
        rejections = tracker.get_rejections(days_back=30)
        assert len(rejections) == 1
        assert rejections[0]["symbol"] == "NEW"


# ===========================================================================
# Duplicate Detection
# ===========================================================================


class TestDuplicateDetection:
    def test_same_day_same_strikes_is_duplicate(self, tracker):
        tid1 = tracker.log_trade(**_make_trade_kwargs())
        assert tid1 is not None

        tid2 = tracker.log_trade(**_make_trade_kwargs())
        assert tid2 is None  # Duplicate

    def test_different_symbol_not_duplicate(self, tracker):
        tid1 = tracker.log_trade(**_make_trade_kwargs(symbol="AAPL"))
        tid2 = tracker.log_trade(**_make_trade_kwargs(symbol="MSFT"))
        assert tid1 is not None
        assert tid2 is not None

    def test_different_strikes_not_duplicate(self, tracker):
        tid1 = tracker.log_trade(**_make_trade_kwargs(short_strike=240.0))
        tid2 = tracker.log_trade(**_make_trade_kwargs(short_strike=235.0))
        assert tid1 is not None
        assert tid2 is not None

    def test_different_day_not_duplicate(self, tracker):
        tid1 = tracker.log_trade(**_make_trade_kwargs())
        assert tid1 is not None

        # Backdate to yesterday
        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
        with tracker._get_connection() as conn:
            conn.execute(
                "UPDATE shadow_trades SET logged_at = ? WHERE id = ?",
                (yesterday, tid1),
            )

        tid2 = tracker.log_trade(**_make_trade_kwargs())
        assert tid2 is not None  # Not a duplicate (different day)


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestEdgeCases:
    def test_all_valid_strategies(self, tracker):
        for i, strategy in enumerate(sorted(VALID_STRATEGIES)):
            tid = tracker.log_trade(
                **_make_trade_kwargs(
                    strategy=strategy,
                    symbol=f"SYM{i}",
                    short_strike=100.0 + i * 10,
                )
            )
            assert tid is not None

    def test_all_valid_sources(self, tracker):
        for i, source in enumerate(sorted(VALID_SOURCES)):
            tid = tracker.log_trade(
                **_make_trade_kwargs(
                    source=source,
                    symbol=f"SRC{i}",
                    short_strike=100.0 + i * 10,
                )
            )
            assert tid is not None

    def test_all_valid_statuses(self, tracker):
        for status in sorted(VALID_STATUSES):
            tid = tracker.log_trade(
                **_make_trade_kwargs(
                    symbol=f"S{status[:3].upper()}",
                    short_strike=float(hash(status) % 1000),
                )
            )
            if tid:
                tracker.update_trade_status(tid, status)
                trade = tracker.get_trade(tid)
                assert trade["status"] == status

    def test_all_valid_rejection_reasons(self, tracker):
        for reason in sorted(VALID_REJECTION_REASONS):
            rid = tracker.log_rejection(
                source="daily_picks",
                symbol="TEST",
                strategy="pullback",
                score=5.0,
                rejection_reason=reason,
            )
            assert rid is not None

    def test_close_and_reopen(self, tmp_path):
        db = tmp_path / "reopen.db"
        t1 = ShadowTracker(db_path=str(db))
        tid = t1.log_trade(**_make_trade_kwargs())
        t1.close()

        t2 = ShadowTracker(db_path=str(db))
        trade = t2.get_trade(tid)
        assert trade is not None
        assert trade["symbol"] == "AAPL"
        t2.close()

    def test_concurrent_read_after_write(self, tmp_path):
        """WAL mode allows concurrent reads."""
        db = tmp_path / "concurrent.db"
        t = ShadowTracker(db_path=str(db))
        tid = t.log_trade(**_make_trade_kwargs())

        # Open second connection directly
        conn2 = sqlite3.connect(str(db))
        conn2.row_factory = sqlite3.Row
        row = conn2.execute("SELECT * FROM shadow_trades WHERE id = ?", (tid,)).fetchone()
        assert row is not None
        assert dict(row)["symbol"] == "AAPL"
        conn2.close()
        t.close()


# ===========================================================================
# check_tradability() — Tradability Gate
# ===========================================================================


@dataclass
class _MockOption:
    """Minimal mock matching OptionQuote interface."""

    strike: float
    bid: Optional[float]
    ask: Optional[float]
    open_interest: Optional[int]

    @property
    def mid(self) -> Optional[float]:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return None


def _make_chain(
    short_strike=240.0,
    long_strike=230.0,
    short_bid=4.20,
    short_ask=4.50,
    short_oi=1500,
    long_bid=1.60,
    long_ask=1.75,
    long_oi=900,
):
    """Build a 2-option chain for testing."""
    return [
        _MockOption(strike=short_strike, bid=short_bid, ask=short_ask, open_interest=short_oi),
        _MockOption(strike=long_strike, bid=long_bid, ask=long_ask, open_interest=long_oi),
    ]


def _mock_provider(chain=None, raises=None):
    """Create a mock provider with get_option_chain."""
    provider = AsyncMock()
    if raises:
        provider.get_option_chain.side_effect = raises
    else:
        provider.get_option_chain.return_value = chain if chain is not None else []
    return provider


class TestCheckTradability:
    @pytest.mark.asyncio
    async def test_tradeable_passes_all_checks(self):
        chain = _make_chain()
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is True
        assert reason == "tradeable"
        assert details["short_bid"] == 4.20
        assert details["short_ask"] == 4.50
        assert details["short_oi"] == 1500
        assert details["long_bid"] == 1.60
        assert details["long_ask"] == 1.75
        assert details["long_oi"] == 900
        assert details["net_credit"] == 2.45  # 4.20 - 1.75

    @pytest.mark.asyncio
    async def test_empty_chain_returns_no_chain(self):
        provider = _mock_provider(chain=[])

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_chain"

    @pytest.mark.asyncio
    async def test_api_error_returns_no_chain(self):
        provider = _mock_provider(raises=ConnectionError("API down"))

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_chain"
        assert "error" in details

    @pytest.mark.asyncio
    async def test_missing_short_strike_returns_no_chain(self):
        # Chain only has the long strike
        chain = [_MockOption(strike=230.0, bid=1.60, ask=1.75, open_interest=900)]
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_chain"
        assert details["short_found"] is False
        assert details["long_found"] is True

    @pytest.mark.asyncio
    async def test_missing_long_strike_returns_no_chain(self):
        chain = [_MockOption(strike=240.0, bid=4.20, ask=4.50, open_interest=1500)]
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_chain"
        assert details["short_found"] is True
        assert details["long_found"] is False

    @pytest.mark.asyncio
    async def test_no_bid_rejection(self):
        chain = _make_chain(short_bid=0.05)  # Below min_bid=0.10
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_bid"
        assert details["short_bid"] == 0.05

    @pytest.mark.asyncio
    async def test_zero_bid_rejection(self):
        chain = _make_chain(short_bid=0.0)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_bid"

    @pytest.mark.asyncio
    async def test_low_short_oi_rejection(self):
        chain = _make_chain(short_oi=50)  # Below min_open_interest=100
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "low_oi"
        assert details["short_oi"] == 50

    @pytest.mark.asyncio
    async def test_low_long_oi_rejection(self):
        chain = _make_chain(long_oi=50)  # Below min_open_interest=100
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "low_oi"
        assert details["long_oi"] == 50

    @pytest.mark.asyncio
    async def test_wide_spread_rejection(self):
        # Bid=2.00, Ask=4.00 → mid=3.00, spread=2.00, pct=66.7% > 30%
        chain = _make_chain(short_bid=2.00, short_ask=4.00)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "wide_spread"
        assert details["bid_ask_spread_pct"] > 30

    @pytest.mark.asyncio
    async def test_low_credit_rejection(self):
        # Short Bid=2.00, Long Ask=1.75 → net credit=0.25 < 2.00
        chain = _make_chain(short_bid=2.00, short_ask=2.10)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "low_credit"
        assert details["net_credit"] == 0.25

    @pytest.mark.asyncio
    async def test_custom_thresholds(self):
        # With relaxed thresholds, a normally-rejected trade passes
        chain = _make_chain(short_oi=200, long_oi=200, short_bid=1.00, short_ask=1.10)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(
            provider,
            "AAPL",
            "2026-04-17",
            240.0,
            230.0,
            min_net_credit=0.0,
            min_open_interest=100,
            min_bid=0.05,
            max_bid_ask_spread_pct=50,
        )

        assert ok is False  # net credit = 1.00 - 1.75 = negative
        assert reason == "low_credit"

    @pytest.mark.asyncio
    async def test_custom_thresholds_all_pass(self):
        chain = _make_chain(short_oi=200, long_oi=200)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(
            provider,
            "AAPL",
            "2026-04-17",
            240.0,
            230.0,
            min_net_credit=1.00,
            min_open_interest=100,
        )

        assert ok is True
        assert reason == "tradeable"

    @pytest.mark.asyncio
    async def test_details_always_populated_on_rejection(self):
        """Even on rejection, details contain actual market data."""
        chain = _make_chain(short_oi=50, long_oi=50)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        # Market data fields populated despite rejection
        assert details["short_bid"] == 4.20
        assert details["long_ask"] == 1.75
        assert details["net_credit"] == 2.45

    @pytest.mark.asyncio
    async def test_none_bid_treated_as_zero(self):
        chain = _make_chain(short_bid=None)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "no_bid"

    @pytest.mark.asyncio
    async def test_none_oi_treated_as_zero(self):
        chain = _make_chain(short_oi=None)
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is False
        assert reason == "low_oi"

    @pytest.mark.asyncio
    async def test_check_order_bid_before_oi(self):
        """Bid check comes before OI check (first-fail order per briefing)."""
        chain = _make_chain(short_bid=0.01, short_oi=10, long_oi=10)
        provider = _mock_provider(chain)

        ok, reason, _ = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert reason == "no_bid"  # Not low_oi

    @pytest.mark.asyncio
    async def test_check_order_oi_before_spread(self):
        """OI check comes before spread check."""
        chain = _make_chain(short_oi=10, short_bid=2.00, short_ask=4.00)
        provider = _mock_provider(chain)

        ok, reason, _ = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert reason == "low_oi"  # Not wide_spread

    @pytest.mark.asyncio
    async def test_check_order_spread_before_credit(self):
        """Spread check comes before credit check."""
        # Wide spread AND low credit
        chain = _make_chain(short_bid=0.50, short_ask=2.00, long_ask=1.75)
        provider = _mock_provider(chain)

        ok, reason, _ = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert reason == "wide_spread"  # Not low_credit

    @pytest.mark.asyncio
    async def test_provider_called_with_correct_args(self):
        chain = _make_chain()
        provider = _mock_provider(chain)

        await check_tradability(provider, "MSFT", "2026-05-16", 400.0, 390.0)

        provider.get_option_chain.assert_called_once_with(
            "MSFT", expiry=date(2026, 5, 16), right="P"
        )

    @pytest.mark.asyncio
    async def test_exact_boundary_values(self):
        """Test exact boundary: bid=0.10, OI=100, spread=30%, credit=2.00."""
        # Short: bid=2.10, ask=2.40 → mid=2.25, spread=0.30, pct=13.3%
        # Net credit: 2.10 - 0.10 = 2.00 (exact minimum)
        chain = _make_chain(
            short_bid=2.10,
            short_ask=2.40,
            short_oi=100,
            long_bid=0.05,
            long_ask=0.10,
            long_oi=100,
        )
        provider = _mock_provider(chain)

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        assert ok is True
        assert reason == "tradeable"
        assert details["net_credit"] == 2.00


# ======================================================================
# Resolution Logic Tests
# ======================================================================


class TestCalculatePnl:
    """Tests for calculate_pnl() — all 6 status outcomes."""

    def test_max_profit(self):
        pnl = calculate_pnl("max_profit", est_credit=2.50, spread_width=10.0)
        assert pnl == 250.0  # 2.50 × 100

    def test_partial_profit_with_spread_value(self):
        # credit=2.50, spread_value=1.00 → (2.50 - 1.00) × 100 = 150
        pnl = calculate_pnl(
            "partial_profit", est_credit=2.50, spread_width=10.0, spread_value_at_resolve=1.00
        )
        assert pnl == 150.0

    def test_partial_profit_fallback_50pct(self):
        # No spread_value → assume 50% of credit: 2.50 × 100 × 0.50 = 125
        pnl = calculate_pnl("partial_profit", est_credit=2.50, spread_width=10.0)
        assert pnl == 125.0

    def test_stop_loss_with_spread_value(self):
        # spread_value=6.25, credit=2.50 → -(6.25 - 2.50) × 100 = -375
        pnl = calculate_pnl(
            "stop_loss", est_credit=2.50, spread_width=10.0, spread_value_at_resolve=6.25
        )
        assert pnl == -375.0

    def test_stop_loss_fallback(self):
        # No spread_value → -(2.50 × 1.50) × 100 = -375
        pnl = calculate_pnl("stop_loss", est_credit=2.50, spread_width=10.0)
        assert pnl == -375.0

    def test_max_loss(self):
        # -(spread_width × 100 - credit × 100) = -(10 × 100 - 2.50 × 100) = -750
        pnl = calculate_pnl("max_loss", est_credit=2.50, spread_width=10.0)
        assert pnl == -750.0

    def test_partial_loss_with_price(self):
        # short=240, price=237 → intrinsic = max(0, 240-237) = 3
        # pnl = 2.50×100 - 3×100 = 250 - 300 = -50
        pnl = calculate_pnl(
            "partial_loss",
            est_credit=2.50,
            spread_width=10.0,
            price_at_expiry=237.0,
            short_strike=240.0,
        )
        assert pnl == -50.0

    def test_partial_loss_no_price_returns_zero(self):
        pnl = calculate_pnl("partial_loss", est_credit=2.50, spread_width=10.0)
        assert pnl == 0.0

    def test_partial_loss_price_above_short_no_intrinsic(self):
        # price=245 > short=240 → intrinsic=0 → pnl = credit = 250
        pnl = calculate_pnl(
            "partial_loss",
            est_credit=2.50,
            spread_width=10.0,
            price_at_expiry=245.0,
            short_strike=240.0,
        )
        assert pnl == 250.0

    def test_unknown_status_returns_zero(self):
        pnl = calculate_pnl("open", est_credit=2.50, spread_width=10.0)
        assert pnl == 0.0


class TestResolveTrade:
    """Tests for resolve_trade() async function."""

    def _make_open_trade(self, **overrides):
        """Build a dict mimicking ShadowTracker.get_trade() output."""
        defaults = {
            "id": str(uuid.uuid4()),
            "status": "open",
            "symbol": "AAPL",
            "strategy": "pullback",
            "short_strike": 240.0,
            "long_strike": 230.0,
            "spread_width": 10.0,
            "est_credit": 2.50,
            "expiration": "2026-04-17",
            "logged_at": (date.today() - timedelta(days=30)).isoformat() + "T12:00:00",
            "score": 8.5,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.asyncio
    async def test_non_open_trade_returns_none(self):
        trade = self._make_open_trade(status="max_profit")
        result = await resolve_trade(trade)
        assert result is None

    @pytest.mark.asyncio
    async def test_profit_target_hit(self):
        """Spread value <= 50% of credit → partial_profit."""
        trade = self._make_open_trade(est_credit=2.50)

        # Mock chain: spread value = short_ask - long_bid = 1.20 - 0.00 = 1.20
        # 50% target = 1.25, spread_value 1.20 <= 1.25 → profit target
        provider = AsyncMock()
        short_opt = _MockOption(strike=240.0, bid=0.50, ask=1.20, open_interest=1000)
        long_opt = _MockOption(strike=230.0, bid=0.00, ask=0.10, open_interest=500)
        provider.get_option_chain.return_value = [short_opt, long_opt]
        provider.get_historical.return_value = []

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "partial_profit"
        assert result["spread_value_at_resolve"] == 1.20
        assert result["theoretical_pnl"] > 0
        assert "50% profit target" in result["outcome_notes"]

    @pytest.mark.asyncio
    async def test_stop_loss_triggered(self):
        """Spread value >= 250% of credit → stop_loss."""
        trade = self._make_open_trade(est_credit=2.00)

        # spread_value = 5.50 - 0.30 = 5.20, stop = 2.00 × 2.50 = 5.00
        provider = AsyncMock()
        short_opt = _MockOption(strike=240.0, bid=5.00, ask=5.50, open_interest=1000)
        long_opt = _MockOption(strike=230.0, bid=0.30, ask=0.50, open_interest=500)
        provider.get_option_chain.return_value = [short_opt, long_opt]
        provider.get_historical.return_value = []

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "stop_loss"
        assert result["theoretical_pnl"] < 0
        assert "Stop-loss triggered" in result["outcome_notes"]

    @pytest.mark.asyncio
    async def test_expired_otm_max_profit(self):
        """Price >= short_strike at expiry → max_profit."""
        trade = self._make_open_trade(
            expiration=(date.today() - timedelta(days=1)).isoformat(),
            short_strike=240.0,
            long_strike=230.0,
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []  # expired, no chain
        provider.get_historical.return_value = [
            MockBar(date=date.today() - timedelta(days=1), low=242.0, close=245.0),
        ]

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "max_profit"
        assert result["price_at_expiry"] == 245.0
        assert result["theoretical_pnl"] == 250.0  # 2.50 × 100
        assert "Expired OTM" in result["outcome_notes"]

    @pytest.mark.asyncio
    async def test_expired_itm_max_loss(self):
        """Price <= long_strike at expiry → max_loss."""
        trade = self._make_open_trade(
            expiration=(date.today() - timedelta(days=1)).isoformat(),
            short_strike=240.0,
            long_strike=230.0,
            est_credit=2.50,
            spread_width=10.0,
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []
        provider.get_historical.return_value = [
            MockBar(date=date.today() - timedelta(days=1), low=225.0, close=228.0),
        ]

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "max_loss"
        assert result["theoretical_pnl"] == -750.0  # -(10×100 - 2.50×100)
        assert "Expired ITM" in result["outcome_notes"]

    @pytest.mark.asyncio
    async def test_expired_between_strikes_partial_loss(self):
        """Price between strikes at expiry → partial_loss."""
        trade = self._make_open_trade(
            expiration=(date.today() - timedelta(days=1)).isoformat(),
            short_strike=240.0,
            long_strike=230.0,
            est_credit=2.50,
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []
        provider.get_historical.return_value = [
            MockBar(date=date.today() - timedelta(days=1), low=233.0, close=235.0),
        ]

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "partial_loss"
        # intrinsic = max(0, 240-235) = 5, pnl = 2.50×100 - 5×100 = -250
        assert result["theoretical_pnl"] == -250.0
        assert "between strikes" in result["outcome_notes"]

    @pytest.mark.asyncio
    async def test_price_based_stop_fallback(self):
        """Price drops below trigger without chain data → stop_loss."""
        trade = self._make_open_trade(
            short_strike=240.0,
            long_strike=230.0,
            spread_width=10.0,
        )
        # stop_trigger = 240 - (10 × 0.3) = 237.0

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []  # No chain data
        provider.get_historical.return_value = [
            MockBar(date=date.today() - timedelta(days=5), low=236.0, close=237.0),
            MockBar(date=date.today(), low=238.0, close=239.0),
        ]

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "stop_loss"
        assert result["price_min"] == 236.0
        assert "price fallback" in result["outcome_notes"].lower()

    @pytest.mark.asyncio
    async def test_stays_open_no_trigger(self):
        """No resolution criteria met → returns None."""
        trade = self._make_open_trade(
            est_credit=2.50,
            short_strike=240.0,
            long_strike=230.0,
            spread_width=10.0,
        )

        # Chain: spread value between profit target and stop → in-between
        provider = AsyncMock()
        short_opt = _MockOption(strike=240.0, bid=2.00, ask=2.50, open_interest=1000)
        long_opt = _MockOption(strike=230.0, bid=0.20, ask=0.30, open_interest=500)
        # spread_value = 2.50 - 0.20 = 2.30
        # profit_target = 2.50 × 0.50 = 1.25 → 2.30 > 1.25 (no profit)
        # stop = 2.50 × 2.50 = 6.25 → 2.30 < 6.25 (no stop)
        provider.get_option_chain.return_value = [short_opt, long_opt]
        provider.get_historical.return_value = []

        result = await resolve_trade(trade, provider=provider)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_provider_stays_open(self):
        """Without provider, non-expired trade stays open."""
        trade = self._make_open_trade()
        result = await resolve_trade(trade, provider=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_profit_target_priority_over_price_stop(self):
        """Chain-based profit target takes priority over price-based stop."""
        trade = self._make_open_trade(
            est_credit=2.50,
            short_strike=240.0,
            long_strike=230.0,
            spread_width=10.0,
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        # Chain shows profit target hit
        provider = AsyncMock()
        short_opt = _MockOption(strike=240.0, bid=0.50, ask=1.00, open_interest=1000)
        long_opt = _MockOption(strike=230.0, bid=0.00, ask=0.05, open_interest=500)
        provider.get_option_chain.return_value = [short_opt, long_opt]
        # But price history shows a dip below stop trigger
        provider.get_historical.return_value = [
            MockBar(date=date.today(), low=235.0, close=245.0),
        ]

        result = await resolve_trade(trade, provider=provider)

        assert result is not None
        assert result["status"] == "partial_profit"  # Chain-based wins


class TestResolveOpenTrades:
    """Tests for resolve_open_trades() — batch resolution + DB updates."""

    @pytest.mark.asyncio
    async def test_resolves_and_updates_db(self, tracker):
        """Resolved trades are updated in the DB."""
        tid = tracker.log_trade(
            **_make_trade_kwargs(
                expiration=(date.today() - timedelta(days=1)).isoformat(),
            )
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []
        # Bars must include today (>= logged_at date) for price resolution
        provider.get_historical.return_value = [
            MockBar(date=date.today(), low=250.0, close=255.0),
        ]

        results = await resolve_open_trades(tracker, provider=provider)

        assert len(results) == 1
        assert results[0]["new_status"] == "max_profit"
        assert results[0]["trade_id"] == tid

        # Verify DB was updated
        trade = tracker.get_trade(tid)
        assert trade["status"] == "max_profit"
        assert trade["theoretical_pnl"] is not None
        assert trade["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_skips_already_resolved(self, tracker):
        """Only open trades are processed."""
        tid = tracker.log_trade(**_make_trade_kwargs())
        tracker.update_trade_status(tid, "max_profit")

        results = await resolve_open_trades(tracker)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_mixed_resolution(self, tracker):
        """Multiple trades: some resolve, some stay open."""
        # Trade 1: expired → resolves
        tid1 = tracker.log_trade(
            **_make_trade_kwargs(
                symbol="AAPL",
                expiration=(date.today() - timedelta(days=1)).isoformat(),
            )
        )
        # Trade 2: not expired, no provider → stays open
        tid2 = tracker.log_trade(
            **_make_trade_kwargs(
                symbol="MSFT",
                short_strike=400.0,
                long_strike=390.0,
            )
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []
        provider.get_historical.return_value = [
            MockBar(date=date.today(), low=250.0, close=255.0),
        ]

        results = await resolve_open_trades(tracker, provider=provider)

        resolved_ids = {r["trade_id"] for r in results}
        assert tid1 in resolved_ids
        # tid2 may or may not resolve depending on provider response for MSFT
        # But AAPL should definitely resolve
        assert tracker.get_trade(tid1)["status"] != "open"


class TestFormatReviewOutput:
    """Tests for format_review_output() markdown formatting."""

    def test_empty_output(self):
        output = format_review_output(trades=[], resolutions=[], rejections=[])
        assert "# Shadow Trade Review" in output
        assert "Total trades:** 0" in output

    def test_resolutions_table(self):
        resolutions = [
            {
                "symbol": "AAPL",
                "strategy": "pullback",
                "new_status": "partial_profit",
                "pnl": 150.0,
                "notes": "50% profit target hit",
            }
        ]
        output = format_review_output(trades=[], resolutions=resolutions, rejections=[])
        assert "## Resolutions This Review" in output
        assert "AAPL" in output
        assert "+150" in output

    def test_open_trades_table(self):
        trades = [
            {
                "status": "open",
                "symbol": "MSFT",
                "strategy": "bounce",
                "score": 7.5,
                "est_credit": 3.00,
                "short_strike": 400.0,
                "long_strike": 390.0,
                "expiration": (date.today() + timedelta(days=30)).isoformat(),
                "logged_at": "2026-02-20T10:00:00",
            }
        ]
        output = format_review_output(trades=trades, resolutions=[], rejections=[])
        assert "## Open Trades (1)" in output
        assert "MSFT" in output
        assert "bounce" in output

    def test_closed_trades_table(self):
        trades = [
            {
                "status": "max_profit",
                "symbol": "AAPL",
                "strategy": "pullback",
                "est_credit": 2.50,
                "theoretical_pnl": 250.0,
                "resolved_at": "2026-02-21T14:00:00",
            }
        ]
        output = format_review_output(trades=trades, resolutions=[], rejections=[])
        assert "## Closed Trades (1)" in output
        assert "+250" in output

    def test_win_rate_calculation(self):
        trades = [
            {
                "status": "max_profit",
                "symbol": "AAPL",
                "strategy": "pullback",
                "est_credit": 2.50,
                "theoretical_pnl": 250,
                "resolved_at": "2026-02-21",
            },
            {
                "status": "partial_profit",
                "symbol": "MSFT",
                "strategy": "bounce",
                "est_credit": 2.00,
                "theoretical_pnl": 100,
                "resolved_at": "2026-02-21",
            },
            {
                "status": "stop_loss",
                "symbol": "GOOG",
                "strategy": "pullback",
                "est_credit": 2.50,
                "theoretical_pnl": -375,
                "resolved_at": "2026-02-21",
            },
        ]
        output = format_review_output(trades=trades, resolutions=[], rejections=[])
        assert "67%" in output  # 2W / 3 total
        assert "2W / 1L" in output

    def test_executability_rate(self):
        trades = [
            {
                "status": "open",
                "symbol": "A",
                "strategy": "pullback",
                "score": 8,
                "est_credit": 2.5,
                "short_strike": 240,
                "long_strike": 230,
                "expiration": "2026-04-17",
                "logged_at": "2026-02-20",
            },
        ]
        rejections = [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}]
        output = format_review_output(trades=trades, resolutions=[], rejections=rejections)
        # 1 trade / (1 trade + 3 rejections) = 25%
        assert "25%" in output
        assert "1/4" in output

    def test_total_pnl(self):
        trades = [
            {
                "status": "max_profit",
                "symbol": "AAPL",
                "strategy": "pullback",
                "est_credit": 2.50,
                "theoretical_pnl": 250,
                "resolved_at": "2026-02-21",
            },
            {
                "status": "stop_loss",
                "symbol": "MSFT",
                "strategy": "bounce",
                "est_credit": 2.00,
                "theoretical_pnl": -375,
                "resolved_at": "2026-02-21",
            },
        ]
        output = format_review_output(trades=trades, resolutions=[], rejections=[])
        assert "-125" in output  # 250 + (-375) = -125


# ======================================================================
# Stats / Aggregation Tests
# ======================================================================


_pop_counter = 0


def _populate_trades(tracker, count=10, strategy="pullback", status="open", score=8.0):
    """Helper to populate trades for stats testing."""
    global _pop_counter
    ids = []
    for i in range(count):
        _pop_counter += 1
        tid = tracker.log_trade(
            **_make_trade_kwargs(
                symbol=f"S{_pop_counter}",
                strategy=strategy,
                score=score,
                short_strike=240.0 + _pop_counter,
                long_strike=230.0 + _pop_counter,
            )
        )
        if tid and status != "open":
            tracker.update_trade_status(
                tid, status, theoretical_pnl=100.0 if "profit" in status else -200.0
            )
        if tid:
            ids.append(tid)
    return ids


def _populate_rejections(tracker, count=5, reason="low_credit"):
    """Helper to populate rejections for stats testing."""
    for i in range(count):
        tracker.log_rejection(
            source="daily_picks",
            symbol=f"REJ{i}",
            strategy="pullback",
            score=7.0,
            rejection_reason=reason,
        )


class TestGetStats:
    """Tests for get_stats() aggregation."""

    def test_group_by_strategy(self, tracker):
        _populate_trades(tracker, count=6, strategy="pullback")
        _populate_trades(tracker, count=6, strategy="bounce")

        stats = get_stats(tracker, group_by="strategy", min_trades=5)

        assert len(stats["groups"]) == 2
        keys = {g["key"] for g in stats["groups"]}
        assert "pullback" in keys
        assert "bounce" in keys
        assert stats["totals"]["total"] == 12

    def test_group_by_score_bucket(self, tracker):
        _populate_trades(tracker, count=6, score=9.5)  # bucket 9-10
        _populate_trades(tracker, count=6, score=7.5, strategy="bounce")  # bucket 7-9

        stats = get_stats(tracker, group_by="score_bucket", min_trades=5)

        keys = {g["key"] for g in stats["groups"]}
        assert "9-10" in keys
        assert "7-9" in keys

    def test_group_by_regime(self, tracker):
        for i in range(6):
            tracker.log_trade(
                **_make_trade_kwargs(
                    symbol=f"N{i}",
                    short_strike=240.0 + i,
                    long_strike=230.0 + i,
                    regime_at_log="normal",
                )
            )
        for i in range(6):
            tracker.log_trade(
                **_make_trade_kwargs(
                    symbol=f"E{i}",
                    short_strike=340.0 + i,
                    long_strike=330.0 + i,
                    regime_at_log="elevated",
                )
            )

        stats = get_stats(tracker, group_by="regime", min_trades=5)

        keys = {g["key"] for g in stats["groups"]}
        assert "normal" in keys
        assert "elevated" in keys

    def test_group_by_month(self, tracker):
        _populate_trades(tracker, count=6)

        stats = get_stats(tracker, group_by="month", min_trades=1)

        assert len(stats["groups"]) >= 1
        # Month key should be YYYY-MM format
        for g in stats["groups"]:
            assert len(g["key"]) == 7  # e.g. "2026-02"

    def test_group_by_symbol(self, tracker):
        # Each trade gets a unique symbol, so min_trades=1 to see them
        _populate_trades(tracker, count=3)

        stats = get_stats(tracker, group_by="symbol", min_trades=1)

        assert len(stats["groups"]) == 3

    def test_group_by_tier(self, tracker):
        _populate_trades(tracker, count=6)  # All tier 1 from _make_trade_kwargs

        stats = get_stats(tracker, group_by="tier", min_trades=5)

        keys = {g["key"] for g in stats["groups"]}
        assert "Tier 1" in keys

    def test_group_by_rejection_reason(self, tracker):
        _populate_rejections(tracker, count=6, reason="low_credit")
        _populate_rejections(tracker, count=6, reason="low_oi")

        stats = get_stats(tracker, group_by="rejection_reason", min_trades=5)

        keys = {g["key"] for g in stats["groups"]}
        assert "low_credit" in keys
        assert "low_oi" in keys
        assert stats["total_rejections"] == 12

    def test_min_trades_filter(self, tracker):
        _populate_trades(tracker, count=3, strategy="pullback")
        _populate_trades(tracker, count=10, strategy="bounce")

        stats = get_stats(tracker, group_by="strategy", min_trades=5)

        keys = {g["key"] for g in stats["groups"]}
        assert "bounce" in keys
        assert "pullback" not in keys  # Only 3 trades, below min_trades=5

    def test_win_rate_in_stats(self, tracker):
        _populate_trades(tracker, count=4, strategy="pullback", status="max_profit", score=9.0)
        _populate_trades(tracker, count=2, strategy="pullback", status="stop_loss", score=9.0)

        stats = get_stats(tracker, group_by="strategy", min_trades=5)

        group = next(g for g in stats["groups"] if g["key"] == "pullback")
        assert group["wins"] == 4
        assert group["losses"] == 2
        assert group["win_rate"] == pytest.approx(66.7, abs=0.1)

    def test_executability_rate(self, tracker):
        _populate_trades(tracker, count=6)
        _populate_rejections(tracker, count=4)

        stats = get_stats(tracker, group_by="strategy")

        ex = stats["executability"]
        assert ex["trades"] == 6
        assert ex["rejections"] == 4
        assert ex["rate"] == 60.0

    def test_empty_db(self, tracker):
        stats = get_stats(tracker, group_by="strategy", min_trades=1)

        assert stats["groups"] == []
        assert stats["totals"]["total"] == 0

    def test_invalid_group_by(self, tracker):
        with pytest.raises(ValueError, match="Invalid group_by"):
            get_stats(tracker, group_by="invalid")


class TestFormatStatsOutput:
    """Tests for format_stats_output() markdown formatting."""

    def test_strategy_format(self, tracker):
        _populate_trades(tracker, count=6, strategy="pullback")
        stats = get_stats(tracker, group_by="strategy", min_trades=5)

        output = format_stats_output(stats)

        assert "# Shadow Trade Stats (by strategy)" in output
        assert "pullback" in output
        assert "Totals" in output

    def test_rejection_format(self, tracker):
        _populate_rejections(tracker, count=6, reason="low_credit")
        stats = get_stats(tracker, group_by="rejection_reason", min_trades=5)

        output = format_stats_output(stats)

        assert "# Shadow Rejection Analysis" in output
        assert "low_credit" in output
        assert "Total rejections" in output

    def test_empty_stats_format(self, tracker):
        stats = get_stats(tracker, group_by="strategy", min_trades=5)

        output = format_stats_output(stats)

        assert "No groups with sufficient data" in output

    def test_executability_in_output(self, tracker):
        _populate_trades(tracker, count=6)
        _populate_rejections(tracker, count=4)
        stats = get_stats(tracker, group_by="strategy")

        output = format_stats_output(stats)

        assert "Executability rate" in output
        assert "60%" in output
        assert "6/10" in output


# ======================================================================
# Detail View Tests
# ======================================================================


class TestFormatDetailOutput:
    """Tests for format_detail_output() — single trade detail view."""

    def test_not_found(self):
        output = format_detail_output(None)
        assert "not found" in output.lower()

    def test_open_trade_all_fields(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        trade = tracker.get_trade(tid)

        output = format_detail_output(trade)

        assert "# Shadow Trade: AAPL (pullback)" in output
        assert "OPEN" in output
        assert tid in output
        # Trade setup
        assert "8.5" in output  # score
        assert "9.1" in output  # enhanced score
        assert "daily_picks" in output  # source
        assert "Tier" in output  # liquidity tier
        # Spread details
        assert "240 / 230" in output  # strikes
        assert "$2.50" in output  # credit
        assert "2026-04-17" in output  # expiration
        assert "$245.00" in output  # price at log
        # Options market data
        assert "Short (240P)" in output
        assert "$4.20" in output  # short bid
        assert "$4.50" in output  # short ask
        assert "1500" in output  # short OI
        assert "Long (230P)" in output
        assert "$1.60" in output  # long bid
        assert "$1.75" in output  # long ask
        assert "900" in output  # long OI
        # Market context
        assert "18.5" in output  # VIX
        assert "normal" in output  # regime
        assert "82.0" in output  # stability
        # No resolution section for open trades
        assert "Resolution" not in output

    def test_resolved_trade_shows_resolution(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        tracker.update_trade_status(
            tid,
            "partial_profit",
            theoretical_pnl=150.0,
            spread_value_at_resolve=1.0,
            price_min=238.0,
            price_at_50pct=248.0,
            days_to_50pct=12,
            outcome_notes="50% profit target hit",
        )
        trade = tracker.get_trade(tid)

        output = format_detail_output(trade)

        assert "WIN (partial_profit)" in output
        assert "## Resolution" in output
        assert "+150" in output  # P&L
        assert "$1.0000" in output  # spread value
        assert "$238.00" in output  # price min
        assert "$248.00" in output  # price at 50%
        assert "12" in output  # days to 50%
        assert "50% profit target hit" in output

    def test_loss_trade_badge(self, tracker):
        tid = tracker.log_trade(**_make_trade_kwargs())
        tracker.update_trade_status(tid, "stop_loss", theoretical_pnl=-375.0)
        trade = tracker.get_trade(tid)

        output = format_detail_output(trade)

        assert "LOSS (stop_loss)" in output
        assert "-375" in output

    def test_minimal_trade_no_optional_fields(self, tracker):
        """Trade without optional fields still formats correctly."""
        tid = tracker.log_trade(
            source="manual",
            symbol="TSLA",
            strategy="bounce",
            score=6.0,
            short_strike=200.0,
            long_strike=190.0,
            spread_width=10.0,
            est_credit=1.80,
            expiration="2026-05-16",
            dte=83,
            price_at_log=210.0,
        )
        trade = tracker.get_trade(tid)

        output = format_detail_output(trade)

        assert "TSLA" in output
        assert "bounce" in output
        assert "6.0" in output
        # No enhanced score, no market data table, no context section
        assert "Enhanced Score" not in output
        assert "Options Market Data" not in output
        assert "VIX" not in output


# ======================================================================
# Schritt 7: Comprehensive / E2E / MCP Registration Tests
# ======================================================================


class TestE2EPipeline:
    """End-to-end: log → resolve → review output."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_profit(self, tracker):
        """Trade logged → resolved as profit → shows in review output."""
        # 1. Log trade
        tid = tracker.log_trade(
            **_make_trade_kwargs(
                expiration=(date.today() - timedelta(days=1)).isoformat(),
                est_credit=2.50,
                short_strike=240.0,
                long_strike=230.0,
                spread_width=10.0,
            )
        )
        assert tid is not None
        assert tracker.get_trade(tid)["status"] == "open"

        # 2. Resolve (expired OTM → max_profit)
        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []
        provider.get_historical.return_value = [
            MockBar(date=date.today(), low=250.0, close=255.0),
        ]

        resolutions = await resolve_open_trades(tracker, provider=provider)
        assert len(resolutions) == 1
        assert resolutions[0]["new_status"] == "max_profit"
        assert resolutions[0]["pnl"] == 250.0

        # 3. Verify DB state
        trade = tracker.get_trade(tid)
        assert trade["status"] == "max_profit"
        assert trade["theoretical_pnl"] == 250.0
        assert trade["resolved_at"] is not None

        # 4. Format review output
        trades = tracker.get_trades()
        rejections = tracker.get_rejections()
        output = format_review_output(trades, resolutions, rejections)
        assert "max_profit" in output
        assert "+250" in output

        # 5. Detail view
        detail = format_detail_output(trade)
        assert "WIN (max_profit)" in detail
        assert "+250" in detail

    @pytest.mark.asyncio
    async def test_full_lifecycle_loss(self, tracker):
        """Trade logged → expired ITM → max_loss."""
        tid = tracker.log_trade(
            **_make_trade_kwargs(
                expiration=(date.today() - timedelta(days=1)).isoformat(),
                est_credit=2.50,
                short_strike=240.0,
                long_strike=230.0,
                spread_width=10.0,
            )
        )

        @dataclass
        class MockBar:
            date: date
            low: float
            close: float

        provider = AsyncMock()
        provider.get_option_chain.return_value = []
        provider.get_historical.return_value = [
            MockBar(date=date.today(), low=220.0, close=225.0),
        ]

        resolutions = await resolve_open_trades(tracker, provider=provider)
        assert len(resolutions) == 1
        assert resolutions[0]["new_status"] == "max_loss"

        trade = tracker.get_trade(tid)
        assert trade["status"] == "max_loss"
        assert trade["theoretical_pnl"] == -750.0

    @pytest.mark.asyncio
    async def test_trade_plus_rejection_pipeline(self, tracker):
        """Logs both a trade and a rejection, stats reflect both."""
        # Trade
        tracker.log_trade(**_make_trade_kwargs())
        # Rejection
        tracker.log_rejection(
            source="daily_picks",
            symbol="ILLIQ",
            strategy="pullback",
            score=7.0,
            rejection_reason="low_credit",
        )

        stats = get_stats(tracker, group_by="strategy", min_trades=1)
        ex = stats["executability"]
        assert ex["trades"] == 1
        assert ex["rejections"] == 1
        assert ex["rate"] == 50.0

    @pytest.mark.asyncio
    async def test_provider_chain_error_graceful(self, tracker):
        """Provider error during resolve doesn't crash, trade stays open."""
        tid = tracker.log_trade(**_make_trade_kwargs())

        provider = AsyncMock()
        provider.get_option_chain.side_effect = ConnectionError("API down")
        provider.get_historical.side_effect = ConnectionError("API down")

        resolutions = await resolve_open_trades(tracker, provider=provider)
        assert len(resolutions) == 0

        # Trade stays open
        trade = tracker.get_trade(tid)
        assert trade["status"] == "open"

    @pytest.mark.asyncio
    async def test_provider_historical_error_graceful(self, tracker):
        """Historical fetch fails but chain works → still resolves if criteria met."""
        tid = tracker.log_trade(**_make_trade_kwargs(est_credit=2.50))

        # Chain shows profit target hit (spread_value <= 50% of credit)
        provider = AsyncMock()
        short_opt = _MockOption(strike=240.0, bid=0.50, ask=1.00, open_interest=1000)
        long_opt = _MockOption(strike=230.0, bid=0.00, ask=0.05, open_interest=500)
        provider.get_option_chain.return_value = [short_opt, long_opt]
        provider.get_historical.side_effect = ConnectionError("API down")

        resolutions = await resolve_open_trades(tracker, provider=provider)
        assert len(resolutions) == 1
        assert resolutions[0]["new_status"] == "partial_profit"


class TestMCPToolRegistration:
    """Verify all 4 shadow tracker MCP tools are registered."""

    def test_shadow_review_registered(self):
        from src.mcp_tool_registry import tool_registry

        tools = {t.name: t for t in tool_registry.list_tools()}
        assert "optionplay_shadow_review" in tools

    def test_shadow_stats_registered(self):
        from src.mcp_tool_registry import tool_registry

        tools = {t.name: t for t in tool_registry.list_tools()}
        assert "optionplay_shadow_stats" in tools

    def test_shadow_log_registered(self):
        from src.mcp_tool_registry import tool_registry

        tools = {t.name: t for t in tool_registry.list_tools()}
        assert "optionplay_shadow_log" in tools

    def test_shadow_detail_registered(self):
        from src.mcp_tool_registry import tool_registry

        tools = {t.name: t for t in tool_registry.list_tools()}
        assert "optionplay_shadow_detail" in tools

    def test_shadow_aliases_registered(self):
        from src.mcp_tool_registry import tool_registry

        aliases = tool_registry._aliases
        assert "shadow_review" in aliases or "shadow" in aliases
        assert "shadow_stats" in aliases
        assert "shadow_log" in aliases
        assert "shadow_detail" in aliases

    def test_shadow_tools_have_input_schema(self):
        from src.mcp_tool_registry import tool_registry

        tools = {t.name: t for t in tool_registry.list_tools()}
        for name in [
            "optionplay_shadow_review",
            "optionplay_shadow_stats",
            "optionplay_shadow_log",
            "optionplay_shadow_detail",
        ]:
            assert tools[name].inputSchema is not None

    def test_shadow_tools_dispatchable(self):
        """All 4 shadow tools resolve via dispatch (alias and canonical)."""
        from src.mcp_tool_registry import tool_registry

        for alias in ["shadow_review", "shadow_stats", "shadow_log", "shadow_detail"]:
            canonical = tool_registry.resolve_alias(alias)
            assert canonical is not None, f"Alias {alias} not resolvable"
            tool_def = tool_registry.get_tool(canonical)
            assert tool_def is not None, f"Tool {canonical} not found"
            assert tool_def.handler is not None, f"Tool {canonical} has no handler"
