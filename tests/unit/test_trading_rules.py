"""
Tests for src/constants/trading_rules.py

Ensures all PLAYBOOK rules are correctly encoded.
"""

import pytest

from src.constants.trading_rules import (
    # Enums
    TradeDecision,
    VIXRegime,
    ExitAction,
    # Entry Rules
    ENTRY_STABILITY_MIN,
    ENTRY_EARNINGS_MIN_DAYS,
    ENTRY_VIX_MAX_NEW_TRADES,
    ENTRY_VIX_NO_TRADING,
    ENTRY_PRICE_MIN,
    ENTRY_PRICE_MAX,
    ENTRY_VOLUME_MIN,
    ENTRY_IV_RANK_MIN,
    ENTRY_IV_RANK_MAX,
    ENTRY_OPEN_INTEREST_MIN,
    ENTRY_BID_ASK_SPREAD_MAX,
    BLACKLIST_SYMBOLS,
    BLACKLIST_STABILITY_THRESHOLD,
    BLACKLIST_WIN_RATE_THRESHOLD,
    BLACKLIST_VOLATILITY_THRESHOLD,
    # Spread Parameters
    SPREAD_DTE_MIN,
    SPREAD_DTE_MAX,
    SPREAD_DTE_TARGET,
    SPREAD_SHORT_DELTA_TARGET,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_LONG_DELTA_MIN,
    SPREAD_LONG_DELTA_MAX,
    SPREAD_MIN_CREDIT_PCT,
    # VIX
    VIX_REGIME_RULES,
    VIXRegimeRules,
    get_vix_regime,
    get_regime_rules,
    VIX_LOW_VOL_MAX,
    VIX_NORMAL_MAX,
    VIX_DANGER_ZONE_MAX,
    VIX_ELEVATED_MAX,
    VIX_NO_TRADING_THRESHOLD,
    # Exit
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_PROFIT_PCT_HIGH_VIX,
    EXIT_STOP_LOSS_MULTIPLIER,
    EXIT_ROLL_DTE,
    EXIT_FORCE_CLOSE_DTE,
    # Roll
    ROLL_ALLOWED_MAX_LOSS_PCT,
    ROLL_NEW_DTE_MIN,
    ROLL_NEW_DTE_MAX,
    ROLL_MIN_CREDIT_PCT,
    # Sizing
    SIZING_MAX_RISK_PER_TRADE_PCT,
    SIZING_MAX_OPEN_POSITIONS,
    SIZING_MAX_PER_SECTOR,
    SIZING_MAX_NEW_TRADES_PER_DAY,
    # Discipline
    DISCIPLINE_MAX_TRADES_PER_MONTH,
    DISCIPLINE_MAX_TRADES_PER_DAY,
    DISCIPLINE_MAX_TRADES_PER_WEEK,
    DISCIPLINE_CONSECUTIVE_LOSSES_PAUSE,
    DISCIPLINE_PAUSE_DAYS,
    DISCIPLINE_MONTHLY_LOSSES_PAUSE,
    DISCIPLINE_MONTHLY_DRAWDOWN_PAUSE,
    # Watchlist
    PRIMARY_WATCHLIST,
    SECONDARY_WATCHLIST_STABILITY_MIN,
    # Filter Order
    FILTER_ORDER,
    # Convenience
    TradingRules,
)


class TestPlaybookEntryRules:
    """PLAYBOOK §1: Entry Rules."""

    def test_stability_minimum(self):
        assert ENTRY_STABILITY_MIN == 65.0

    def test_earnings_minimum_days(self):
        assert ENTRY_EARNINGS_MIN_DAYS == 45  # Unified to 45 days

    def test_vix_max_for_new_trades(self):
        assert ENTRY_VIX_MAX_NEW_TRADES == 30.0

    def test_vix_no_trading(self):
        assert ENTRY_VIX_NO_TRADING == 35.0

    def test_price_range(self):
        assert ENTRY_PRICE_MIN == 20.0
        assert ENTRY_PRICE_MAX == 1500.0

    def test_volume_minimum(self):
        assert ENTRY_VOLUME_MIN == 500_000

    def test_iv_rank_range(self):
        assert ENTRY_IV_RANK_MIN == 30.0
        assert ENTRY_IV_RANK_MAX == 80.0

    def test_blacklist_contains_known_symbols(self):
        for symbol in ["ROKU", "SNAP", "TSLA", "COIN", "MSTR"]:
            assert symbol in BLACKLIST_SYMBOLS, f"{symbol} should be on blacklist"

    def test_blacklist_excludes_primary_watchlist(self):
        for symbol in PRIMARY_WATCHLIST:
            assert symbol not in BLACKLIST_SYMBOLS, f"{symbol} is on both watchlist and blacklist"


class TestPlaybookSpreadParameters:
    """PLAYBOOK §2: Spread Parameters."""

    def test_dte_range(self):
        assert SPREAD_DTE_MIN == 60
        assert SPREAD_DTE_MAX == 90
        assert SPREAD_DTE_TARGET == 75

    def test_short_delta(self):
        """Delta -0.20 ±0.03."""
        assert SPREAD_SHORT_DELTA_TARGET == -0.20
        assert SPREAD_SHORT_DELTA_MIN == -0.17  # ±0.03
        assert SPREAD_SHORT_DELTA_MAX == -0.23  # ±0.03

    def test_long_delta(self):
        """Delta -0.05 ±0.02."""
        assert SPREAD_LONG_DELTA_TARGET == -0.05
        assert SPREAD_LONG_DELTA_MIN == -0.03  # ±0.02
        assert SPREAD_LONG_DELTA_MAX == -0.07  # ±0.02

    def test_min_credit(self):
        assert SPREAD_MIN_CREDIT_PCT == 10.0  # PLAYBOOK §2: 10% der Spread-Breite


class TestPlaybookVIXRegime:
    """PLAYBOOK §3: VIX Regime."""

    def test_regime_boundaries(self):
        assert VIX_LOW_VOL_MAX == 15.0
        assert VIX_NORMAL_MAX == 20.0
        assert VIX_DANGER_ZONE_MAX == 25.0
        assert VIX_ELEVATED_MAX == 30.0
        assert VIX_NO_TRADING_THRESHOLD == 35.0

    def test_get_vix_regime(self):
        assert get_vix_regime(12.0) == VIXRegime.LOW_VOL
        assert get_vix_regime(18.0) == VIXRegime.NORMAL
        assert get_vix_regime(22.0) == VIXRegime.DANGER_ZONE
        assert get_vix_regime(27.0) == VIXRegime.ELEVATED
        assert get_vix_regime(32.0) == VIXRegime.HIGH_VOL
        assert get_vix_regime(36.0) == VIXRegime.NO_TRADING

    def test_regime_boundaries_exact(self):
        """Test boundary values (PLAYBOOK uses < and >)."""
        assert get_vix_regime(15.0) == VIXRegime.NORMAL      # VIX 15 = Normal
        assert get_vix_regime(20.0) == VIXRegime.DANGER_ZONE  # VIX 20 = Danger Zone
        assert get_vix_regime(25.0) == VIXRegime.ELEVATED     # VIX 25 = Elevated
        assert get_vix_regime(30.0) == VIXRegime.HIGH_VOL     # VIX 30 = High Vol
        assert get_vix_regime(35.0) == VIXRegime.NO_TRADING   # VIX 35 = No Trading

    def test_low_vol_rules(self):
        rules = get_regime_rules(12.0)
        assert rules.regime == VIXRegime.LOW_VOL
        assert rules.stability_min == 65.0
        assert rules.new_trades_allowed is True
        assert rules.max_positions == 10
        assert rules.max_per_sector == 2
        assert rules.profit_exit_pct == 50.0

    def test_normal_rules(self):
        rules = get_regime_rules(18.0)
        assert rules.regime == VIXRegime.NORMAL
        assert rules.stability_min == 65.0
        assert rules.new_trades_allowed is True
        assert rules.max_positions == 10

    def test_danger_zone_rules(self):
        rules = get_regime_rules(22.0)
        assert rules.regime == VIXRegime.DANGER_ZONE
        assert rules.stability_min == 80.0  # Increased!
        assert rules.new_trades_allowed is True
        assert rules.max_positions == 5     # Reduced!
        assert rules.max_per_sector == 1    # Reduced!
        assert rules.profit_exit_pct == 30.0  # Faster exit!

    def test_elevated_rules(self):
        rules = get_regime_rules(27.0)
        assert rules.regime == VIXRegime.ELEVATED
        assert rules.stability_min == 80.0
        assert rules.new_trades_allowed is True
        assert rules.max_positions == 3     # Very limited
        assert rules.profit_exit_pct == 30.0

    def test_high_vol_no_new_trades(self):
        rules = get_regime_rules(32.0)
        assert rules.regime == VIXRegime.HIGH_VOL
        assert rules.new_trades_allowed is False
        assert rules.max_positions == 0

    def test_no_trading(self):
        rules = get_regime_rules(36.0)
        assert rules.regime == VIXRegime.NO_TRADING
        assert rules.new_trades_allowed is False

    def test_all_regimes_have_rules(self):
        for regime in VIXRegime:
            assert regime in VIX_REGIME_RULES, f"Missing rules for {regime}"


class TestPlaybookExitRules:
    """PLAYBOOK §4: Exit Rules."""

    def test_profit_exits(self):
        assert EXIT_PROFIT_PCT_NORMAL == 50.0
        assert EXIT_PROFIT_PCT_HIGH_VIX == 30.0

    def test_stop_loss(self):
        assert EXIT_STOP_LOSS_MULTIPLIER == 2.0

    def test_time_exits(self):
        assert EXIT_ROLL_DTE == 21
        assert EXIT_FORCE_CLOSE_DTE == 7


class TestPlaybookPositionSizing:
    """PLAYBOOK §5: Position Sizing."""

    def test_max_risk_per_trade(self):
        assert SIZING_MAX_RISK_PER_TRADE_PCT == 2.0

    def test_max_positions(self):
        assert SIZING_MAX_OPEN_POSITIONS == 10

    def test_max_per_sector(self):
        assert SIZING_MAX_PER_SECTOR == 2  # PLAYBOOK §5: Max 2 Positionen pro Sektor

    def test_max_trades_per_day(self):
        assert SIZING_MAX_NEW_TRADES_PER_DAY == 2


class TestPlaybookDiscipline:
    """PLAYBOOK §6: Discipline Rules."""

    def test_monthly_limit(self):
        assert DISCIPLINE_MAX_TRADES_PER_MONTH == 25

    def test_daily_limit(self):
        assert DISCIPLINE_MAX_TRADES_PER_DAY == 2

    def test_consecutive_losses_pause(self):
        assert DISCIPLINE_CONSECUTIVE_LOSSES_PAUSE == 3
        assert DISCIPLINE_PAUSE_DAYS == 7


class TestPlaybookWatchlist:
    """PLAYBOOK §7: Watchlist."""

    def test_primary_watchlist_size(self):
        assert len(PRIMARY_WATCHLIST) == 20

    def test_primary_watchlist_contains_key_symbols(self):
        for symbol in ["SPY", "QQQ", "AAPL", "MSFT", "JPM"]:
            assert symbol in PRIMARY_WATCHLIST

    def test_no_overlap_with_blacklist(self):
        overlap = set(PRIMARY_WATCHLIST) & set(BLACKLIST_SYMBOLS)
        assert len(overlap) == 0, f"Overlap: {overlap}"


class TestTradingRulesConvenience:
    """Test the TradingRules convenience class."""

    def test_instantiation(self):
        tr = TradingRules()
        assert tr.ENTRY_STABILITY_MIN == 65.0
        assert tr.DTE_MIN == 60
        assert tr.DTE_MAX == 90
        assert tr.SHORT_DELTA == -0.20
        assert tr.LONG_DELTA == -0.05
        assert tr.MAX_RISK_PCT == 2.0
        assert tr.MAX_POSITIONS == 10
        assert tr.MAX_PER_SECTOR == 2  # PLAYBOOK §5: Max 2 pro Sektor
        assert tr.PROFIT_EXIT_NORMAL == 50.0
        assert tr.STOP_LOSS_MULT == 2.0
        assert tr.ROLL_DTE == 21
        assert tr.FORCE_CLOSE_DTE == 7

    def test_frozen(self):
        tr = TradingRules()
        with pytest.raises(AttributeError):
            tr.ENTRY_STABILITY_MIN = 50.0


class TestEnums:
    """Test all enum values exist."""

    def test_trade_decision_values(self):
        assert TradeDecision.GO.value == "GO"
        assert TradeDecision.NO_GO.value == "NO_GO"
        assert TradeDecision.WARNING.value == "WARNING"
        assert len(TradeDecision) == 3

    def test_vix_regime_values(self):
        assert VIXRegime.LOW_VOL.value == "LOW_VOL"
        assert VIXRegime.NORMAL.value == "NORMAL"
        assert VIXRegime.DANGER_ZONE.value == "DANGER_ZONE"
        assert VIXRegime.ELEVATED.value == "ELEVATED"
        assert VIXRegime.HIGH_VOL.value == "HIGH_VOL"
        assert VIXRegime.NO_TRADING.value == "NO_TRADING"
        assert len(VIXRegime) == 6

    def test_exit_action_values(self):
        assert ExitAction.HOLD.value == "HOLD"
        assert ExitAction.CLOSE.value == "CLOSE"
        assert ExitAction.ROLL.value == "ROLL"
        assert ExitAction.ALERT.value == "ALERT"
        assert len(ExitAction) == 4


class TestBlacklistThresholds:
    """PLAYBOOK: Blacklist criteria."""

    def test_blacklist_stability_threshold(self):
        assert BLACKLIST_STABILITY_THRESHOLD == 40.0

    def test_blacklist_win_rate_threshold(self):
        assert BLACKLIST_WIN_RATE_THRESHOLD == 70.0

    def test_blacklist_volatility_threshold(self):
        assert BLACKLIST_VOLATILITY_THRESHOLD == 100.0


class TestSoftFilterConstants:
    """PLAYBOOK §1: Soft filter constants."""

    def test_open_interest_minimum(self):
        assert ENTRY_OPEN_INTEREST_MIN == 100

    def test_bid_ask_spread_max(self):
        assert ENTRY_BID_ASK_SPREAD_MAX == 0.20


class TestRollRules:
    """PLAYBOOK §4: Roll Rules."""

    def test_roll_max_loss(self):
        assert ROLL_ALLOWED_MAX_LOSS_PCT == 0.0  # Break-even

    def test_roll_dte_range(self):
        assert ROLL_NEW_DTE_MIN == 60
        assert ROLL_NEW_DTE_MAX == 90

    def test_roll_min_credit(self):
        assert ROLL_MIN_CREDIT_PCT == 10.0  # PLAYBOOK §4: ≥10% Spread-Breite


class TestDisciplineExtended:
    """PLAYBOOK §6: Extended discipline rules."""

    def test_weekly_limit(self):
        assert DISCIPLINE_MAX_TRADES_PER_WEEK == 8

    def test_monthly_losses_pause(self):
        assert DISCIPLINE_MONTHLY_LOSSES_PAUSE == 5

    def test_monthly_drawdown_pause(self):
        assert DISCIPLINE_MONTHLY_DRAWDOWN_PAUSE == 5.0


class TestWatchlistExtended:
    """PLAYBOOK §7: Extended watchlist tests."""

    def test_secondary_watchlist_threshold(self):
        assert SECONDARY_WATCHLIST_STABILITY_MIN == 70.0


class TestFilterOrder:
    """PLAYBOOK §1: Filter order (Prüf-Reihenfolge)."""

    def test_filter_order_length(self):
        assert len(FILTER_ORDER) == 8

    def test_filter_order_sequence(self):
        assert FILTER_ORDER == [
            "blacklist",
            "stability",
            "earnings",
            "vix",
            "price",
            "volume",
            "iv_rank",
            "score_ranking",
        ]

    def test_blacklist_is_first(self):
        assert FILTER_ORDER[0] == "blacklist"

    def test_score_ranking_is_last(self):
        assert FILTER_ORDER[-1] == "score_ranking"


class TestVIXRegimeRiskParameters:
    """Test risk_per_trade_pct across all regimes."""

    def test_low_vol_risk(self):
        rules = get_regime_rules(12.0)
        assert rules.risk_per_trade_pct == 2.0

    def test_normal_risk(self):
        rules = get_regime_rules(18.0)
        assert rules.risk_per_trade_pct == 2.0

    def test_danger_zone_risk(self):
        rules = get_regime_rules(22.0)
        assert rules.risk_per_trade_pct == 1.5

    def test_elevated_risk(self):
        rules = get_regime_rules(27.0)
        assert rules.risk_per_trade_pct == 1.0

    def test_high_vol_risk(self):
        rules = get_regime_rules(32.0)
        assert rules.risk_per_trade_pct == 0.0

    def test_no_trading_risk(self):
        rules = get_regime_rules(36.0)
        assert rules.risk_per_trade_pct == 0.0
