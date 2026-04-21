"""
Tests for Paket G — Exit-Verbesserungen

G.1 Gamma-Zone Stop (4 Tests)
G.2 Time-Stop (4 Tests)
G.3 RRG-basierter Exit (4 Tests)
G.4 Macro-Kalender (4 Tests)
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from src.constants.trading_rules import (
    EXIT_GAMMA_ZONE_DTE,
    EXIT_GAMMA_ZONE_LOSS_PCT,
    EXIT_TIME_STOP_DAYS,
    EXIT_TIME_STOP_LOSS_PCT,
    ExitAction,
)
from src.services.position_monitor import (
    MACRO_EVENTS_2026,
    PositionMonitor,
    PositionSnapshot,
    reset_position_monitor,
)


# =============================================================================
# HELPERS
# =============================================================================


def make_snap(
    symbol="AAPL",
    dte=45,
    pnl_pct=None,
    unrealized_pnl=None,
    entry_date=None,
    rrg_quadrant_at_entry=None,
    net_credit=2.50,
    contracts=1,
) -> PositionSnapshot:
    short_strike = 180.0
    long_strike = 170.0
    spread_width = short_strike - long_strike
    max_profit = net_credit * contracts * 100
    max_loss = (spread_width - net_credit) * contracts * 100
    exp_date = (date.today() + timedelta(days=dte)).isoformat()

    return PositionSnapshot(
        position_id=f"test_{symbol}_{dte}",
        symbol=symbol,
        short_strike=short_strike,
        long_strike=long_strike,
        spread_width=spread_width,
        net_credit=net_credit,
        contracts=contracts,
        expiration=exp_date,
        dte=dte,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=short_strike - net_credit,
        source="internal",
        pnl_pct_of_max_profit=pnl_pct,
        unrealized_pnl=unrealized_pnl,
        entry_date=entry_date,
        rrg_quadrant_at_entry=rrg_quadrant_at_entry,
    )


def _entry_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


@pytest.fixture
def monitor():
    reset_position_monitor()
    m = PositionMonitor()
    mock_earnings = MagicMock()
    mock_earnings.is_earnings_day_safe.return_value = (True, 120, "safe")
    m._earnings_manager = mock_earnings
    return m


# =============================================================================
# G.1 — GAMMA-ZONE STOP
# =============================================================================


class TestGammaZoneStop:
    """G.1: DTE < 21 UND Verlust > 30% → Exit."""

    def test_constants_from_config(self):
        """Schwellen aus config/trading.yaml geladen."""
        assert EXIT_GAMMA_ZONE_DTE == 21
        assert EXIT_GAMMA_ZONE_LOSS_PCT == 30.0

    def test_dte18_loss35_triggers(self, monitor):
        """DTE 18, Verlust -35% → GAMMA-ZONE STOP."""
        snap = make_snap(dte=18, pnl_pct=-35.0)
        signal = monitor._check_gamma_zone_stop(snap)

        assert signal is not None
        assert signal.action == ExitAction.CLOSE
        assert signal.priority == 5
        assert "GAMMA-ZONE" in signal.reason
        assert signal.details["gamma_zone_dte"] == 21

    def test_dte18_loss25_no_trigger(self, monitor):
        """DTE 18, Verlust -25% → kein Exit (unter Schwelle)."""
        snap = make_snap(dte=18, pnl_pct=-25.0)
        signal = monitor._check_gamma_zone_stop(snap)
        assert signal is None

    def test_dte25_loss35_no_trigger(self, monitor):
        """DTE 25, Verlust -35% → kein Exit (über DTE-Schwelle)."""
        snap = make_snap(dte=25, pnl_pct=-35.0)
        signal = monitor._check_gamma_zone_stop(snap)
        assert signal is None

    def test_dte5_positive_pnl_no_trigger(self, monitor):
        """DTE 5, kein Verlust → kein Exit."""
        snap = make_snap(dte=5, pnl_pct=10.0)
        signal = monitor._check_gamma_zone_stop(snap)
        assert signal is None

    def test_no_pnl_data_skips(self, monitor):
        """Ohne P&L-Daten kein Exit."""
        snap = make_snap(dte=18, pnl_pct=None)
        signal = monitor._check_gamma_zone_stop(snap)
        assert signal is None

    def test_exactly_at_threshold(self, monitor):
        """DTE 20, Verlust exakt -30% → Exit (Schwelle inklusive)."""
        snap = make_snap(dte=20, pnl_pct=-30.0)
        signal = monitor._check_gamma_zone_stop(snap)
        assert signal is not None
        assert signal.action == ExitAction.CLOSE

    @pytest.mark.asyncio
    async def test_gamma_zone_fires_before_21dte_check(self, monitor):
        """G.1 hat Priorität 5 — vor 21-DTE Check (Priorität 7)."""
        snap = make_snap(dte=18, pnl_pct=-35.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        signal = result.signals[0]
        assert signal.priority == 5
        assert "GAMMA-ZONE" in signal.reason


# =============================================================================
# G.2 — TIME-STOP
# =============================================================================


class TestTimeStop:
    """G.2: Haltedauer > 25 Tage UND Verlust > 20% → Exit."""

    def test_constants_from_config(self):
        """Schwellen aus config/trading.yaml geladen."""
        assert EXIT_TIME_STOP_DAYS == 25
        assert EXIT_TIME_STOP_LOSS_PCT == 20.0

    def test_30days_loss25_triggers(self, monitor):
        """30 Tage gehalten, -25% Verlust → TIME-STOP."""
        snap = make_snap(dte=45, pnl_pct=-25.0, entry_date=_entry_ago(30))
        signal = monitor._check_time_stop(snap)

        assert signal is not None
        assert signal.action == ExitAction.CLOSE
        assert signal.priority == 6
        assert "TIME-STOP" in signal.reason
        assert signal.details["days_held"] == 30

    def test_30days_loss15_no_trigger(self, monitor):
        """30 Tage gehalten, -15% → kein Exit (unter Verlustschwelle)."""
        snap = make_snap(dte=45, pnl_pct=-15.0, entry_date=_entry_ago(30))
        signal = monitor._check_time_stop(snap)
        assert signal is None

    def test_20days_loss25_no_trigger(self, monitor):
        """20 Tage gehalten, -25% → kein Exit (zu früh)."""
        snap = make_snap(dte=45, pnl_pct=-25.0, entry_date=_entry_ago(20))
        signal = monitor._check_time_stop(snap)
        assert signal is None

    def test_30days_profit_no_trigger(self, monitor):
        """30 Tage gehalten, +10% Gewinn → kein Exit."""
        snap = make_snap(dte=45, pnl_pct=10.0, entry_date=_entry_ago(30))
        signal = monitor._check_time_stop(snap)
        assert signal is None

    def test_no_entry_date_skips(self, monitor):
        """Ohne entry_date kein Exit."""
        snap = make_snap(dte=45, pnl_pct=-30.0, entry_date=None)
        signal = monitor._check_time_stop(snap)
        assert signal is None

    def test_invalid_entry_date_skips(self, monitor):
        """Ungültiges Datum → kein Crash, kein Exit."""
        snap = make_snap(dte=45, pnl_pct=-30.0, entry_date="not-a-date")
        signal = monitor._check_time_stop(snap)
        assert signal is None

    def test_exactly_at_threshold(self, monitor):
        """26 Tage (> 25) gehalten, Verlust -20% → Exit."""
        snap = make_snap(dte=45, pnl_pct=-20.0, entry_date=_entry_ago(26))
        signal = monitor._check_time_stop(snap)
        assert signal is not None
        assert signal.action == ExitAction.CLOSE

    @pytest.mark.asyncio
    async def test_time_stop_priority_6(self, monitor):
        """Time-Stop hat Priorität 6 — nach G.1 (5), vor 21-DTE (7)."""
        snap = make_snap(dte=45, pnl_pct=-25.0, entry_date=_entry_ago(30))
        result = await monitor.check_positions([snap], current_vix=18.0)
        signal = result.signals[0]
        assert signal.priority == 6
        assert "TIME-STOP" in signal.reason


# =============================================================================
# G.3 — RRG-BASIERTER EXIT
# =============================================================================


def _make_stock_rs(quadrant_str: str):
    """Mock StockRS mit gegebenem Quadrant."""
    rs = MagicMock()
    rs.quadrant.value = quadrant_str
    return rs


class TestRRGExit:
    """G.3: RRG-Rotation → Warnung oder Exit."""

    def test_leading_to_weakening_is_alert(self, monitor):
        """Entry LEADING, jetzt WEAKENING → ALERT (Warnung)."""
        snap = make_snap(dte=45, pnl_pct=20.0, rrg_quadrant_at_entry="leading")
        sector_rs_map = {"AAPL": _make_stock_rs("weakening")}

        signal = monitor._check_rrg_exit(snap, sector_rs_map)

        assert signal is not None
        assert signal.action == ExitAction.ALERT
        assert signal.priority == 10
        assert "ROTATION" in signal.reason
        assert "WEAKENING" in signal.reason

    def test_leading_to_lagging_is_close(self, monitor):
        """Entry LEADING, jetzt LAGGING → EXIT (CLOSE)."""
        snap = make_snap(dte=45, pnl_pct=10.0, rrg_quadrant_at_entry="leading")
        sector_rs_map = {"AAPL": _make_stock_rs("lagging")}

        signal = monitor._check_rrg_exit(snap, sector_rs_map)

        assert signal is not None
        assert signal.action == ExitAction.CLOSE
        assert signal.priority == 10
        assert "LAGGING" in signal.reason

    def test_improving_to_lagging_is_close(self, monitor):
        """Entry IMPROVING, jetzt LAGGING → EXIT."""
        snap = make_snap(dte=45, pnl_pct=5.0, rrg_quadrant_at_entry="improving")
        sector_rs_map = {"AAPL": _make_stock_rs("lagging")}

        signal = monitor._check_rrg_exit(snap, sector_rs_map)

        assert signal is not None
        assert signal.action == ExitAction.CLOSE

    def test_improving_to_leading_no_exit(self, monitor):
        """Entry IMPROVING, jetzt LEADING → kein Exit (verbessert)."""
        snap = make_snap(dte=45, pnl_pct=15.0, rrg_quadrant_at_entry="improving")
        sector_rs_map = {"AAPL": _make_stock_rs("leading")}

        signal = monitor._check_rrg_exit(snap, sector_rs_map)

        assert signal is None

    def test_no_entry_quadrant_skips(self, monitor):
        """Ohne entry_quadrant → kein Signal."""
        snap = make_snap(dte=45, rrg_quadrant_at_entry=None)
        sector_rs_map = {"AAPL": _make_stock_rs("lagging")}

        signal = monitor._check_rrg_exit(snap, sector_rs_map)
        assert signal is None

    def test_no_sector_rs_map_skips(self, monitor):
        """Ohne sector_rs_map → kein Signal."""
        snap = make_snap(dte=45, rrg_quadrant_at_entry="leading")
        signal = monitor._check_rrg_exit(snap, None)
        assert signal is None

    def test_symbol_not_in_map_skips(self, monitor):
        """Symbol nicht in sector_rs_map → kein Signal."""
        snap = make_snap(symbol="MSFT", dte=45, rrg_quadrant_at_entry="leading")
        sector_rs_map = {"AAPL": _make_stock_rs("lagging")}

        signal = monitor._check_rrg_exit(snap, sector_rs_map)
        assert signal is None

    @pytest.mark.asyncio
    async def test_rrg_exit_after_earnings_priority(self, monitor):
        """G.3 hat Priorität 10 — nach Earnings (9), vor HOLD (11)."""
        snap = make_snap(dte=45, pnl_pct=5.0, rrg_quadrant_at_entry="leading")
        sector_rs_map = {"AAPL": _make_stock_rs("lagging")}

        result = await monitor.check_positions(
            [snap], current_vix=18.0, sector_rs_map=sector_rs_map
        )
        signal = result.signals[0]
        assert signal.priority == 10
        assert signal.action == ExitAction.CLOSE


# =============================================================================
# G.4 — MACRO-KALENDER
# =============================================================================


class TestMacroCalendar:
    """G.4: FOMC/CPI/NFP Alert einen Tag vor Event."""

    def test_tomorrow_is_fomc(self):
        """Morgen ist FOMC → Alert."""
        fomc_date = date.fromisoformat(MACRO_EVENTS_2026["FOMC"][0])
        day_before = fomc_date - timedelta(days=1)

        alerts = PositionMonitor.check_macro_events(day_before)
        assert "FOMC" in alerts

    def test_today_is_fomc_no_alert(self):
        """Heute ist FOMC → kein Alert (zu spät)."""
        fomc_date = date.fromisoformat(MACRO_EVENTS_2026["FOMC"][0])

        alerts = PositionMonitor.check_macro_events(fomc_date)
        assert "FOMC" not in alerts

    def test_normal_day_no_alert(self):
        """Normaler Tag ohne Event → kein Alert."""
        # 2026-01-01 ist kein Macro-Event (kein FOMC/CPI/NFP)
        test_date = date(2026, 1, 1)
        alerts = PositionMonitor.check_macro_events(test_date)
        assert len(alerts) == 0

    def test_tomorrow_is_cpi(self):
        """Morgen ist CPI → Alert."""
        cpi_date = date.fromisoformat(MACRO_EVENTS_2026["CPI"][0])
        day_before = cpi_date - timedelta(days=1)

        alerts = PositionMonitor.check_macro_events(day_before)
        assert "CPI" in alerts

    def test_tomorrow_is_nfp(self):
        """Morgen ist NFP → Alert."""
        nfp_date = date.fromisoformat(MACRO_EVENTS_2026["NFP"][0])
        day_before = nfp_date - timedelta(days=1)

        alerts = PositionMonitor.check_macro_events(day_before)
        assert "NFP" in alerts

    def test_all_2026_fomc_dates_covered(self):
        """Alle 8 FOMC-Termine 2026 in der Liste."""
        assert len(MACRO_EVENTS_2026["FOMC"]) == 8

    def test_all_2026_cpi_dates_covered(self):
        """Alle 12 CPI-Termine 2026 in der Liste."""
        assert len(MACRO_EVENTS_2026["CPI"]) == 12

    def test_macro_alerts_in_monitor_result(self):
        """MonitorResult enthält macro_alerts Feld."""
        from src.services.position_monitor import MonitorResult
        result = MonitorResult(signals=[], positions_count=0, macro_alerts=["FOMC"])
        assert result.macro_alerts == ["FOMC"]

    @pytest.mark.asyncio
    async def test_check_positions_returns_macro_alerts(self, monitor):
        """check_positions befüllt macro_alerts im Ergebnis."""
        with patch.object(
            PositionMonitor, "check_macro_events", return_value=["FOMC"]
        ):
            result = await monitor.check_positions([], current_vix=18.0)

        assert "FOMC" in result.macro_alerts


# =============================================================================
# INTEGRATION: G.1 takes priority over 21-DTE
# =============================================================================


class TestGPriorityOrder:
    """G.1/G.2 haben Vorrang vor 21-DTE (Priorität 7)."""

    @pytest.mark.asyncio
    async def test_gamma_zone_beats_21dte(self, monitor):
        """DTE 18, Verlust -35% → Gamma-Zone (5) statt 21-DTE (7)."""
        snap = make_snap(dte=18, pnl_pct=-35.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority == 5

    @pytest.mark.asyncio
    async def test_time_stop_beats_hold(self, monitor):
        """30 Tage, -25% → Time-Stop (6) statt HOLD (11)."""
        snap = make_snap(dte=45, pnl_pct=-25.0, entry_date=_entry_ago(30))
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority == 6

    @pytest.mark.asyncio
    async def test_21dte_still_works_without_gamma(self, monitor):
        """DTE 18, Verlust -20% (unter G.1 Schwelle) → 21-DTE (7)."""
        snap = make_snap(dte=18, pnl_pct=-20.0, unrealized_pnl=-50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority == 7
        assert "im Verlust" in result.signals[0].reason
