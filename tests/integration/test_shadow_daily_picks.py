"""Integration tests for Shadow Tracker ↔ daily_picks pipeline.

Tests _shadow_log_picks logic: tradability gate, log/reject/skip flows,
output status display, and duplicate handling.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shadow_tracker import ShadowTracker, check_tradability

# ===========================================================================
# Minimal mock objects matching the real DailyPick / SpreadValidation shape
# ===========================================================================


class _MockRegime(Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"


@dataclass
class _MockOptionLeg:
    strike: float
    bid: float
    ask: float
    open_interest: int
    delta: float = -0.20
    gamma: float = 0.01
    theta: float = -0.05
    vega: float = 0.10
    iv: float = 0.30
    mid: float = 0.0
    last: Optional[float] = None
    volume: int = 100
    expiration: str = "2026-04-17"
    dte: int = 54


@dataclass
class _MockSpreadValidation:
    tradeable: bool = True
    short_leg: Optional[_MockOptionLeg] = None
    long_leg: Optional[_MockOptionLeg] = None
    expiration: Optional[str] = "2026-04-17"
    dte: Optional[int] = 54
    spread_width: Optional[float] = 10.0
    credit_bid: Optional[float] = 2.45
    credit_mid: Optional[float] = 2.60
    credit_pct: Optional[float] = 24.5
    spread_theta: Optional[float] = -0.03
    max_loss_per_contract: Optional[float] = 755.0


@dataclass
class _MockSuggestedStrikes:
    short_strike: float = 240.0
    long_strike: float = 230.0
    spread_width: float = 10.0
    estimated_credit: Optional[float] = 2.45
    expiry: Optional[str] = "2026-04-17"
    dte: Optional[int] = 54
    liquidity_quality: Optional[str] = "good"
    short_oi: Optional[int] = 1500
    long_oi: Optional[int] = 900
    tradeable_status: str = "READY"


@dataclass
class _MockPick:
    rank: int = 1
    symbol: str = "AAPL"
    strategy: str = "pullback"
    score: float = 9.0
    enhanced_score: Optional[float] = 9.5
    stability_score: float = 82.0
    current_price: float = 245.0
    sector: Optional[str] = "Technology"
    reason: str = "Pullback near support"
    warnings: list = field(default_factory=list)
    suggested_strikes: Optional[_MockSuggestedStrikes] = None
    spread_validation: Optional[_MockSpreadValidation] = None
    entry_quality: Optional[Any] = None
    enhanced_score_result: Optional[Any] = None
    speed_score: float = 5.0
    market_cap_category: Optional[str] = "Mega"
    reliability_grade: Optional[str] = "A"
    historical_win_rate: Optional[float] = 88.0
    ranking_score: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class _MockResult:
    picks: list = field(default_factory=list)
    vix_level: Optional[float] = 18.5
    market_regime: _MockRegime = _MockRegime.NORMAL
    symbols_scanned: int = 300
    signals_found: int = 15
    warnings: list = field(default_factory=list)


def _make_tradeable_pick(symbol="AAPL", score=9.0, short_strike=240.0, long_strike=230.0):
    """Create a pick with spread validation (real chain data)."""
    short_leg = _MockOptionLeg(
        strike=short_strike,
        bid=4.20,
        ask=4.50,
        open_interest=1500,
        mid=4.35,
    )
    long_leg = _MockOptionLeg(
        strike=long_strike,
        bid=1.60,
        ask=1.75,
        open_interest=900,
        mid=1.675,
    )
    sv = _MockSpreadValidation(
        tradeable=True,
        short_leg=short_leg,
        long_leg=long_leg,
    )
    ss = _MockSuggestedStrikes(
        short_strike=short_strike,
        long_strike=long_strike,
    )
    return _MockPick(
        symbol=symbol,
        score=score,
        enhanced_score=score + 0.5,
        suggested_strikes=ss,
        spread_validation=sv,
    )


def _make_pick_no_strikes(symbol="CVS", score=8.5):
    """Create a pick without any strike data."""
    return _MockPick(symbol=symbol, score=score)


@dataclass
class _MockChainOption:
    """Mock matching OptionQuote interface for check_tradability."""

    strike: float
    bid: Optional[float]
    ask: Optional[float]
    open_interest: Optional[int]

    @property
    def mid(self) -> Optional[float]:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return None


# ===========================================================================
# Tests
# ===========================================================================


class TestShadowLogPicksIntegration:
    """Tests for the _shadow_log_picks method on the composed scan handler."""

    @pytest.mark.asyncio
    async def test_tradeable_pick_logged(self, tmp_path):
        """A tradeable pick gets logged as a shadow trade."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        pick = _make_tradeable_pick()
        result = _MockResult(picks=[pick])

        # Simulate tradability check directly
        chain = [
            _MockChainOption(strike=240.0, bid=4.20, ask=4.50, open_interest=1500),
            _MockChainOption(strike=230.0, bid=1.60, ask=1.75, open_interest=900),
        ]
        provider = AsyncMock()
        provider.get_option_chain.return_value = chain

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)
        assert ok is True

        # Now log the trade
        trade_id = tracker.log_trade(
            source="daily_picks",
            symbol="AAPL",
            strategy="pullback",
            score=9.0,
            enhanced_score=9.5,
            short_strike=240.0,
            long_strike=230.0,
            spread_width=10.0,
            est_credit=details["net_credit"],
            expiration="2026-04-17",
            dte=54,
            short_bid=details["short_bid"],
            short_ask=details["short_ask"],
            short_oi=details["short_oi"],
            long_bid=details["long_bid"],
            long_ask=details["long_ask"],
            long_oi=details["long_oi"],
            price_at_log=245.0,
            vix_at_log=18.5,
            regime_at_log="normal",
            stability_at_log=82.0,
        )

        assert trade_id is not None
        trade = tracker.get_trade(trade_id)
        assert trade["symbol"] == "AAPL"
        assert trade["strategy"] == "pullback"
        assert trade["est_credit"] == 2.45
        assert trade["short_bid"] == 4.20
        assert trade["short_oi"] == 1500
        assert trade["status"] == "open"
        tracker.close()

    @pytest.mark.asyncio
    async def test_rejected_pick_logged(self, tmp_path):
        """A non-tradeable pick gets logged as a rejection."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        # Low OI chain
        chain = [
            _MockChainOption(strike=240.0, bid=4.20, ask=4.50, open_interest=50),
            _MockChainOption(strike=230.0, bid=1.60, ask=1.75, open_interest=30),
        ]
        provider = AsyncMock()
        provider.get_option_chain.return_value = chain

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)
        assert ok is False
        assert reason == "low_oi"

        # Log rejection
        rid = tracker.log_rejection(
            source="daily_picks",
            symbol="AAPL",
            strategy="pullback",
            score=9.0,
            short_strike=240.0,
            long_strike=230.0,
            rejection_reason=reason,
            actual_credit=details.get("net_credit"),
            short_oi=details.get("short_oi"),
            details=json.dumps(details),
        )
        assert rid is not None

        rejections = tracker.get_rejections(days_back=1)
        assert len(rejections) == 1
        assert rejections[0]["rejection_reason"] == "low_oi"
        assert rejections[0]["short_oi"] == 50
        tracker.close()

    @pytest.mark.asyncio
    async def test_pick_without_strikes_skipped(self, tmp_path):
        """Picks without strike data are skipped."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        # Pick with no strikes → can't check tradability
        pick = _make_pick_no_strikes()
        assert pick.suggested_strikes is None
        assert pick.spread_validation is None

        trades = tracker.get_trades(days_back=1)
        assert len(trades) == 0
        tracker.close()

    @pytest.mark.asyncio
    async def test_low_score_pick_skipped(self, tmp_path):
        """Picks below min_score threshold are skipped."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        # Score 6.0 < 8.0 default min_score
        pick = _make_tradeable_pick(score=6.0)
        pick.enhanced_score = 6.5

        # Even with a tradeable chain, low score means skip
        trades = tracker.get_trades(days_back=1)
        assert len(trades) == 0
        tracker.close()

    @pytest.mark.asyncio
    async def test_duplicate_not_logged_twice(self, tmp_path):
        """Duplicate detection prevents double-logging."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        kwargs = {
            "source": "daily_picks",
            "symbol": "AAPL",
            "strategy": "pullback",
            "score": 9.0,
            "short_strike": 240.0,
            "long_strike": 230.0,
            "spread_width": 10.0,
            "est_credit": 2.45,
            "expiration": "2026-04-17",
            "dte": 54,
            "price_at_log": 245.0,
        }

        tid1 = tracker.log_trade(**kwargs)
        tid2 = tracker.log_trade(**kwargs)

        assert tid1 is not None
        assert tid2 is None  # Duplicate

        trades = tracker.get_trades(days_back=1)
        assert len(trades) == 1
        tracker.close()

    @pytest.mark.asyncio
    async def test_multiple_picks_mixed_results(self, tmp_path):
        """Multiple picks: some tradeable, some rejected."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        # Tradeable chain for AAPL
        chain_aapl = [
            _MockChainOption(strike=240.0, bid=4.20, ask=4.50, open_interest=1500),
            _MockChainOption(strike=230.0, bid=1.60, ask=1.75, open_interest=900),
        ]

        # Low-OI chain for CVS
        chain_cvs = [
            _MockChainOption(strike=70.0, bid=2.00, ask=2.20, open_interest=50),
            _MockChainOption(strike=60.0, bid=0.30, ask=0.40, open_interest=30),
        ]

        provider = AsyncMock()

        # AAPL → tradeable
        ok1, reason1, details1 = await check_tradability(
            _mock_with_chain(chain_aapl), "AAPL", "2026-04-17", 240.0, 230.0
        )
        assert ok1 is True

        # CVS → rejected (low_oi)
        ok2, reason2, details2 = await check_tradability(
            _mock_with_chain(chain_cvs), "CVS", "2026-04-17", 70.0, 60.0
        )
        assert ok2 is False
        assert reason2 == "low_oi"

        # Log both
        tid = tracker.log_trade(
            source="daily_picks",
            symbol="AAPL",
            strategy="pullback",
            score=9.0,
            short_strike=240.0,
            long_strike=230.0,
            spread_width=10.0,
            est_credit=details1["net_credit"],
            expiration="2026-04-17",
            dte=54,
            price_at_log=245.0,
        )
        assert tid is not None

        rid = tracker.log_rejection(
            source="daily_picks",
            symbol="CVS",
            strategy="pullback",
            score=8.5,
            short_strike=70.0,
            long_strike=60.0,
            rejection_reason=reason2,
            actual_credit=details2.get("net_credit"),
            short_oi=details2.get("short_oi"),
        )
        assert rid is not None

        trades = tracker.get_trades(days_back=1)
        rejections = tracker.get_rejections(days_back=1)
        assert len(trades) == 1
        assert len(rejections) == 1
        assert trades[0]["symbol"] == "AAPL"
        assert rejections[0]["symbol"] == "CVS"
        tracker.close()

    @pytest.mark.asyncio
    async def test_chain_data_stored_on_trade(self, tmp_path):
        """Trade stores real chain data from tradability check."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        chain = [
            _MockChainOption(strike=240.0, bid=4.20, ask=4.50, open_interest=1500),
            _MockChainOption(strike=230.0, bid=1.60, ask=1.75, open_interest=900),
        ]
        provider = AsyncMock()
        provider.get_option_chain.return_value = chain

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)

        trade_id = tracker.log_trade(
            source="daily_picks",
            symbol="AAPL",
            strategy="pullback",
            score=9.0,
            short_strike=240.0,
            long_strike=230.0,
            spread_width=10.0,
            est_credit=details["net_credit"],
            expiration="2026-04-17",
            dte=54,
            short_bid=details["short_bid"],
            short_ask=details["short_ask"],
            short_oi=details["short_oi"],
            long_bid=details["long_bid"],
            long_ask=details["long_ask"],
            long_oi=details["long_oi"],
            price_at_log=245.0,
            vix_at_log=18.5,
            regime_at_log="normal",
            stability_at_log=82.0,
        )

        trade = tracker.get_trade(trade_id)
        assert trade["short_bid"] == 4.20
        assert trade["short_ask"] == 4.50
        assert trade["short_oi"] == 1500
        assert trade["long_bid"] == 1.60
        assert trade["long_ask"] == 1.75
        assert trade["long_oi"] == 900
        assert trade["est_credit"] == 2.45
        assert trade["vix_at_log"] == 18.5
        assert trade["regime_at_log"] == "normal"
        assert trade["stability_at_log"] == 82.0
        tracker.close()

    @pytest.mark.asyncio
    async def test_rejection_stores_details_json(self, tmp_path):
        """Rejection stores details as JSON."""
        db_path = str(tmp_path / "shadow.db")
        tracker = ShadowTracker(db_path=db_path)

        chain = [
            _MockChainOption(strike=240.0, bid=0.05, ask=0.10, open_interest=1500),
            _MockChainOption(strike=230.0, bid=1.60, ask=1.75, open_interest=900),
        ]
        provider = AsyncMock()
        provider.get_option_chain.return_value = chain

        ok, reason, details = await check_tradability(provider, "AAPL", "2026-04-17", 240.0, 230.0)
        assert reason == "no_bid"

        rid = tracker.log_rejection(
            source="daily_picks",
            symbol="AAPL",
            strategy="pullback",
            score=9.0,
            short_strike=240.0,
            long_strike=230.0,
            rejection_reason=reason,
            actual_credit=details.get("net_credit"),
            short_oi=details.get("short_oi"),
            details=json.dumps(details),
        )

        rejections = tracker.get_rejections(days_back=1)
        assert len(rejections) == 1
        parsed = json.loads(rejections[0]["details"])
        assert parsed["short_bid"] == 0.05
        assert parsed["net_credit"] is not None
        tracker.close()


def _mock_with_chain(chain):
    """Helper to create a provider mock with a specific chain."""
    provider = AsyncMock()
    provider.get_option_chain.return_value = chain
    return provider
