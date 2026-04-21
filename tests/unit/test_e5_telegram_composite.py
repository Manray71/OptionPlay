"""E.5 — Tests für Telegram Composite-Scores, Breakout-Signals und Exit-Alerts.

Abdeckung (Mindestanforderung: 10 Tests):
  1.  format_pick_message — B+F Aufschlüsselung angezeigt
  2.  format_pick_message — keine Alpha-Zeile wenn b_raw/f_raw fehlen
  3.  format_pick_message — Dual-RRG-Label in Alpha-Zeile
  4.  format_pick_message — Breakout-Signals mit Icons
  5.  format_pick_message — keine Signal-Zeile wenn keine Signals
  6.  format_pick_message — PRE-BREAKOUT Flag via pre_breakout=True
  7.  format_top15_alpha — kompakte Tabelle mit korrekten Spalten
  8.  format_top15_alpha — leere Liste gibt Fallback-Meldung
  9.  format_top15_alpha — Signal-Icons in der Tabelle
 10.  format_exit_signal — Gamma-Zone Stop Header und P&L
 11.  format_exit_signal — Time-Stop Header
 12.  format_exit_signal — RRG-Exit (CLOSE) Header
 13.  format_exit_signal — RRG-Rotation (ALERT) Header
 14.  format_macro_alert — FOMC formatiert korrekt
 15.  format_macro_alert — leere Liste gibt leeren String
 16.  format_scan_summary — Breakout-Zählung in scan_stats
 17.  format_scan_summary — Top-B / Top-F Symbole
 18.  format_scan_summary — keine breakout_stats = altes Verhalten
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.telegram.notifier import (
    format_exit_signal,
    format_macro_alert,
    format_pick_message,
    format_scan_summary,
    format_top15_alpha,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strikes(**kw):
    defaults = dict(
        short_strike=185.0,
        long_strike=175.0,
        spread_width=10.0,
        estimated_credit=1.85,
        expiry="2026-05-16",
        dte=29,
        dte_warning=None,
        tradeable_status="READY",
        liquidity_quality="good",
        short_oi=1500,
        long_oi=800,
        short_spread_pct=0.5,
        long_spread_pct=1.2,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_pick(**kw):
    defaults = dict(
        rank=1,
        symbol="NVDA",
        strategy="pullback",
        score=8.1,
        enhanced_score=None,
        stability_score=75.0,
        reliability_grade="A",
        historical_win_rate=88.0,
        current_price=875.50,
        sector="Technology",
        market_cap_category="Mega",
        liquidity_tier=1,
        speed_score=7.2,
        suggested_strikes=_make_strikes(),
        spread_validation=None,
        reason="RSI oversold + support bounce",
        warnings=[],
        # Alpha fields
        alpha_raw=None,
        b_raw=None,
        f_raw=None,
        dual_label=None,
        breakout_signals=(),
        pre_breakout=False,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_candidate(**kw):
    defaults = dict(
        symbol="NVDA",
        alpha_raw=187.0,
        b_raw=72.0,
        f_raw=77.0,
        breakout_signals=(),
        pre_breakout=False,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_signal(**kw):
    """Build a mock PositionSignal."""
    from src.constants.trading_rules import ExitAction

    defaults = dict(
        position_id="pos_1",
        symbol="AAPL",
        action=ExitAction.CLOSE,
        reason="GAMMA-ZONE STOP — DTE 14 < 21, Verlust -32% <= -30%",
        priority=5,
        dte=14,
        pnl_pct=-32.0,
        details={},
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_snap(**kw):
    defaults = dict(
        symbol="AAPL",
        short_strike=125.0,
        long_strike=115.0,
        expiration="2026-05-15",
        dte=14,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 1-6 — format_pick_message composite + breakout
# ---------------------------------------------------------------------------


class TestPickMessageComposite:
    def test_bf_breakdown_shown(self):
        """B+F Aufschlüsselung erscheint wenn alpha-Felder gesetzt sind."""
        pick = _make_pick(alpha_raw=187.0, b_raw=72.0, f_raw=77.0)
        msg = format_pick_message(pick)
        assert "Alpha:" in msg
        assert "B:72" in msg
        assert "F:77" in msg
        assert "187" in msg

    def test_no_alpha_line_when_missing(self):
        """Keine Alpha-Zeile wenn b_raw/f_raw nicht gesetzt."""
        pick = _make_pick(alpha_raw=None, b_raw=None, f_raw=None)
        msg = format_pick_message(pick)
        assert "Alpha:" not in msg

    def test_dual_rrg_label_in_alpha_line(self):
        """Dual-RRG-Label erscheint in der Alpha-Zeile."""
        pick = _make_pick(alpha_raw=165.0, b_raw=68.0, f_raw=65.0, dual_label="IMP→LEAD")
        msg = format_pick_message(pick)
        assert "IMP→LEAD" in msg

    def test_breakout_signal_icons_shown(self):
        """Breakout-Signal-Icons erscheinen für aktive Signals."""
        pick = _make_pick(
            alpha_raw=187.0, b_raw=72.0, f_raw=77.0,
            breakout_signals=("BREAKOUT_IMMINENT", "VWAP_RECLAIM"),
        )
        msg = format_pick_message(pick)
        assert "🚩⚡" in msg
        assert "BREAKOUT IMMINENT" in msg
        assert "📊" in msg
        assert "VWAP Reclaim" in msg

    def test_no_signal_line_when_empty(self):
        """Keine Signal-Zeile wenn breakout_signals leer und pre_breakout False."""
        pick = _make_pick(alpha_raw=155.0, b_raw=60.0, f_raw=63.0)
        msg = format_pick_message(pick)
        assert "BREAKOUT" not in msg
        assert "PRE-BREAKOUT" not in msg

    def test_pre_breakout_flag(self):
        """PRE-BREAKOUT Flag erscheint als 🎯 wenn pre_breakout=True."""
        pick = _make_pick(
            alpha_raw=140.0, b_raw=55.0, f_raw=57.0,
            pre_breakout=True,
        )
        msg = format_pick_message(pick)
        assert "🎯" in msg
        assert "PRE-BREAKOUT" in msg


# ---------------------------------------------------------------------------
# 7-9 — format_top15_alpha
# ---------------------------------------------------------------------------


class TestTop15Alpha:
    def test_table_has_correct_columns(self):
        """Kompakte Tabelle enthält Symbol, Total, B, F Spalten."""
        candidates = [
            _make_candidate(symbol="NVDA", alpha_raw=187.0, b_raw=72.0, f_raw=77.0),
            _make_candidate(symbol="MSFT", alpha_raw=165.0, b_raw=68.0, f_raw=65.0),
        ]
        msg = format_top15_alpha(candidates)
        assert "Top 15 Alpha-Composite" in msg
        assert "NVDA" in msg
        assert "MSFT" in msg
        assert "187" in msg
        assert "72" in msg

    def test_empty_candidates_fallback(self):
        """Leere Liste gibt Fallback-Meldung ohne Exception."""
        msg = format_top15_alpha([])
        assert "Top 15" in msg
        assert "keine" in msg.lower() or "verfügbar" in msg.lower()

    def test_signal_icons_in_table(self):
        """Signal-Icons erscheinen in der Tabelle für Kandidaten mit Signals."""
        c1 = _make_candidate(
            symbol="NVDA",
            breakout_signals=("BREAKOUT_IMMINENT", "VWAP_RECLAIM"),
        )
        c2 = _make_candidate(symbol="MSFT", pre_breakout=True)
        msg = format_top15_alpha([c1, c2])
        assert "🚩⚡" in msg
        assert "📊" in msg
        assert "🎯" in msg  # PRE_BREAKOUT from pre_breakout=True


# ---------------------------------------------------------------------------
# 10-13 — format_exit_signal
# ---------------------------------------------------------------------------


class TestExitSignal:
    def test_gamma_zone_header_and_pnl(self):
        """Gamma-Zone Exit: 🔴 Header + P&L + Jetzt schliessen."""
        sig = _make_signal(priority=5)
        snap = _make_snap()
        msg = format_exit_signal(sig, snap)
        assert "🔴" in msg
        assert "GAMMA-ZONE EXIT" in msg
        assert "AAPL" in msg
        assert "-32" in msg
        assert "Jetzt schliessen" in msg

    def test_time_stop_header(self):
        """Time-Stop Exit: 🟡 Header."""
        from src.constants.trading_rules import ExitAction

        sig = _make_signal(
            priority=6,
            action=ExitAction.CLOSE,
            reason="TIME-STOP — 28 Tage gehalten, Verlust -22% <= -20%",
            pnl_pct=-22.0,
        )
        msg = format_exit_signal(sig)
        assert "🟡" in msg
        assert "TIME-STOP" in msg
        assert "Jetzt schliessen" in msg

    def test_rrg_exit_close_header(self):
        """RRG Lagging Exit (CLOSE, priority 10): 🔴 RRG LAGGING."""
        from src.constants.trading_rules import ExitAction

        sig = _make_signal(
            priority=10,
            action=ExitAction.CLOSE,
            reason="RRG EXIT — AAPL → LAGGING (Entry: LEADING)",
            pnl_pct=-15.0,
        )
        msg = format_exit_signal(sig)
        assert "🔴" in msg
        assert "RRG LAGGING" in msg

    def test_rrg_rotation_alert_header(self):
        """RRG Rotation Warning (ALERT, priority 10): 🟡 RRG ROTATION."""
        from src.constants.trading_rules import ExitAction

        sig = _make_signal(
            priority=10,
            action=ExitAction.ALERT,
            reason="RRG ROTATION — AAPL LEADING → WEAKENING",
            pnl_pct=5.0,
        )
        msg = format_exit_signal(sig)
        assert "🟡" in msg
        assert "RRG ROTATION" in msg
        assert "Position beobachten" in msg


# ---------------------------------------------------------------------------
# 14-15 — format_macro_alert
# ---------------------------------------------------------------------------


class TestMacroAlert:
    def test_fomc_formatted(self):
        """FOMC-Event formatiert korrekt als Macro-Alert."""
        msg = format_macro_alert(["FOMC"])
        assert "📅" in msg
        assert "FOMC" in msg
        assert "Gap-Risiko" in msg
        assert "Spreads" in msg

    def test_empty_events_returns_empty_string(self):
        """Keine Events → leerer String (keine Nachricht)."""
        assert format_macro_alert([]) == ""

    def test_multiple_events(self):
        """Mehrere Events werden mit + verbunden."""
        msg = format_macro_alert(["FOMC", "CPI"])
        assert "FOMC" in msg
        assert "CPI" in msg


# ---------------------------------------------------------------------------
# 16-18 — format_scan_summary breakout stats
# ---------------------------------------------------------------------------


class TestScanSummaryBreakout:
    def test_breakout_count_in_stats(self):
        """Breakout-Zählung erscheint in scan_stats."""
        picks = [_make_pick()]
        stats = {
            "symbols_scanned": 361,
            "duration": 5.3,
            "breakout_total": 8,
            "breakout_breakdown": {"VWAP_RECLAIM": 3, "THREE_BAR_PLAY": 2},
        }
        msg = format_scan_summary(picks, vix=18.5, scan_stats=stats)
        assert "8 aktiv" in msg
        assert "VWAP Reclaim" in msg or "VWAP" in msg
        assert "361 Symbole" in msg

    def test_top_b_top_f_symbols(self):
        """Top-B und Top-F Symbole erscheinen in der Summary."""
        picks = [_make_pick()]
        stats = {
            "symbols_scanned": 200,
            "duration": 4.0,
            "breakout_total": 3,
            "breakout_breakdown": {},
            "top_b_symbol": "NVDA",
            "top_b_score": 72,
            "top_f_symbol": "AMZN",
            "top_f_score": 77,
        }
        msg = format_scan_summary(picks, vix=17.0, scan_stats=stats)
        assert "NVDA" in msg
        assert "AMZN" in msg

    def test_no_stats_old_behavior(self):
        """Ohne scan_stats verhält sich die Funktion wie vorher."""
        picks = [_make_pick(), _make_pick(rank=2)]
        msg = format_scan_summary(picks, vix=19.0)
        assert "2 Empfehlungen" in msg
        assert "VIX: 19.00" in msg
        # keine Breakout-Stats
        assert "Breakout" not in msg
