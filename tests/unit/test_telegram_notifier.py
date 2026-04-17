"""Tests for src/telegram/notifier.py — HTML formatting, buttons, confirmations."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.telegram.notifier import (
    format_later_confirmation,
    format_no_picks_message,
    format_pick_buttons,
    format_pick_message,
    format_scan_summary,
    format_shadow_confirmation,
    format_skip_confirmation,
    format_status_message,
    format_vix_message,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_strikes(**overrides):
    defaults = dict(
        short_strike=185.0,
        long_strike=175.0,
        spread_width=10.0,
        estimated_credit=1.85,
        estimated_delta=-0.18,
        prob_profit=0.82,
        risk_reward_ratio=0.23,
        quality="good",
        confidence_score=82.0,
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
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_pick(**overrides):
    defaults = dict(
        rank=1,
        symbol="AAPL",
        strategy="pullback",
        score=7.8,
        enhanced_score=8.2,
        stability_score=72.0,
        reliability_grade="A",
        historical_win_rate=88.3,
        current_price=192.50,
        sector="Technology",
        market_cap_category="Mega",
        liquidity_tier=1,
        speed_score=6.5,
        suggested_strikes=_make_strikes(),
        spread_validation=None,
        reason="RSI oversold + support bounce",
        warnings=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# format_pick_message
# ---------------------------------------------------------------------------


class TestFormatPickMessage:
    def test_basic_all_fields(self):
        pick = _make_pick()
        msg = format_pick_message(pick)
        # Print so Lars can see the format
        print("\n" + msg)

        assert "<b>AAPL</b>" in msg
        assert "Technology" in msg
        assert "Tier A" in msg
        assert "Pullback #1" in msg
        assert "SELL  $185.0P" in msg
        assert "BUY   $175.0P" in msg
        assert "Spread: $10.00" in msg
        assert "Aktie: $192.50" in msg
        assert "2026-05-16" in msg
        assert "(29d)" in msg
        assert "Kredit: ~$1.85" in msg
        assert "Score: 7.8" in msg
        assert "Enhanced: 8.2" in msg
        assert "Win Rate: 88.3%" in msg
        assert "Stability: 72" in msg
        assert "Speed: 6.5" in msg
        assert "T1" in msg
        # TWS order block
        assert "TWS ORDER" in msg
        assert "$1.85" in msg
        assert "$0.93" in msg  # profit target = 1.85 × 0.50
        assert "$2.78" in msg  # stop = 1.85 × 1.50

    def test_missing_enhanced_score(self):
        pick = _make_pick(enhanced_score=None)
        msg = format_pick_message(pick)
        assert "Enhanced:" not in msg
        assert "Score: 7.8" in msg

    def test_missing_suggested_strikes(self):
        pick = _make_pick(suggested_strikes=None)
        msg = format_pick_message(pick)
        assert "Strikes: n/a" in msg
        assert "TWS ORDER" not in msg

    def test_missing_credit_no_tws_block(self):
        strikes = _make_strikes(estimated_credit=None)
        pick = _make_pick(suggested_strikes=strikes)
        msg = format_pick_message(pick)
        assert "TWS ORDER" not in msg
        assert "Kredit" not in msg

    def test_html_escape_symbol(self):
        """Symbols with special HTML chars must be escaped."""
        pick = _make_pick(symbol="AT&T")
        msg = format_pick_message(pick)
        assert "&amp;" in msg
        assert "AT&T" not in msg  # raw unescaped ampersand not in output

    def test_html_escape_sector(self):
        pick = _make_pick(sector="Health<Care>")
        msg = format_pick_message(pick)
        assert "&lt;" in msg or "Health" in msg
        assert "<Care>" not in msg

    def test_none_win_rate(self):
        pick = _make_pick(historical_win_rate=None)
        msg = format_pick_message(pick)
        assert "Win Rate: n/a" in msg

    def test_warnings_included(self):
        pick = _make_pick(warnings=["VIX elevated", "Near earnings"])
        msg = format_pick_message(pick)
        assert "VIX elevated" in msg
        assert "Near earnings" in msg

    def test_bounce_strategy_label(self):
        pick = _make_pick(strategy="bounce")
        msg = format_pick_message(pick)
        assert "Bounce #1" in msg

    def test_no_liquidity_tier(self):
        pick = _make_pick(liquidity_tier=None)
        msg = format_pick_message(pick)
        assert "Liquidity: n/a" in msg

    def test_tws_order_profit_stop_values(self):
        """Profit = credit × 0.50, Stop = credit × 1.50."""
        strikes = _make_strikes(estimated_credit=2.00)
        pick = _make_pick(suggested_strikes=strikes)
        msg = format_pick_message(pick)
        assert "$1.00" in msg  # profit debit = 2.00 × 0.50
        assert "$3.00" in msg  # stop debit  = 2.00 × 1.50


# ---------------------------------------------------------------------------
# format_pick_buttons
# ---------------------------------------------------------------------------


class TestFormatPickButtons:
    def test_callback_data_format(self):
        pick = _make_pick()
        markup = format_pick_buttons(pick)
        buttons = markup.inline_keyboard[0]
        assert buttons[0].callback_data == "shadow:AAPL:pullback:1"
        assert buttons[1].callback_data == "skip:AAPL:1"
        assert buttons[2].callback_data == "later:AAPL:1"

    def test_callback_data_length_max_64_bytes(self):
        """Telegram hard limit: callback_data ≤ 64 bytes."""
        # Worst case: long symbol + strategy + rank
        pick = _make_pick(symbol="VRTX", strategy="pullback", rank=99)
        markup = format_pick_buttons(pick)
        for row in markup.inline_keyboard:
            for btn in row:
                data = btn.callback_data
                assert len(data.encode("utf-8")) <= 64, f"Too long: {data!r}"

    def test_button_labels(self):
        pick = _make_pick()
        markup = format_pick_buttons(pick)
        labels = [btn.text for btn in markup.inline_keyboard[0]]
        assert any("SHADOW" in t for t in labels)
        assert any("SKIP" in t for t in labels)
        assert any("SPÄTER" in t for t in labels)


# ---------------------------------------------------------------------------
# format_scan_summary / format_no_picks_message
# ---------------------------------------------------------------------------


class TestScanMessages:
    def test_scan_summary_with_vix(self):
        picks = [_make_pick(), _make_pick(rank=2)]
        msg = format_scan_summary(picks, vix=18.26, scan_type="morning")
        assert "VIX: 18.26" in msg
        assert "2 Empfehlungen" in msg

    def test_scan_summary_single_pick(self):
        msg = format_scan_summary([_make_pick()], vix=None)
        assert "1 Empfehlung" in msg
        assert "Empfehlungen" not in msg

    def test_no_picks_message(self):
        msg = format_no_picks_message(vix=22.5, scan_type="scheduled")
        assert "VIX: 22.50" in msg
        assert "Keine qualifizierten" in msg


# ---------------------------------------------------------------------------
# Confirmation messages
# ---------------------------------------------------------------------------


class TestConfirmations:
    def test_shadow_confirmation(self):
        msg = format_shadow_confirmation("AAPL", "abc123", "pullback")
        assert "Shadow-Trade geloggt" in msg
        assert "AAPL" in msg
        assert "abc123" in msg
        assert "Pullback" in msg

    def test_skip_confirmation(self):
        msg = format_skip_confirmation("MSFT")
        assert "MSFT" in msg
        assert "übersprungen" in msg

    def test_later_confirmation(self):
        msg = format_later_confirmation("NVDA", 120)
        assert "NVDA" in msg
        assert "120 Min" in msg


# ---------------------------------------------------------------------------
# Status / VIX formatters
# ---------------------------------------------------------------------------


class TestStatusVixFormatters:
    def test_format_status_message(self):
        msg = format_status_message(
            vix=19.3,
            regime="ELEVATED",
            open_positions=2,
            max_positions=4,
            shadow_stats={"total": 10, "wins": 8},
        )
        assert "VIX: 19.30" in msg
        assert "ELEVATED" in msg
        assert "2/4" in msg
        assert "10 Trades" in msg
        assert "80.0%" in msg

    def test_format_status_no_shadow_stats(self):
        msg = format_status_message(
            vix=None, regime=None, open_positions=0, max_positions=5
        )
        assert "Positionen: 0/5" in msg

    def test_format_vix_message(self):
        msg = format_vix_message(
            vix=18.26,
            regime="NORMAL",
            regime_params={"max_positions": 5, "min_score": 4.0, "spread_width": 5.0},
        )
        assert "VIX: 18.26" in msg
        assert "NORMAL" in msg
        assert "Max Positionen: 5" in msg
        assert "Min Score: 4.0" in msg
        assert "$5.00" in msg
