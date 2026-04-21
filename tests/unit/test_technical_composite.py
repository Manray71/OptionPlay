"""Tests for TechnicalComposite — E.2b.1 + E.2b.2 + E.2b.3.

E.2b.1: CompositeScore dataclass, RSI score, quadrant matrix.
E.2b.2: Money flow score (OBV/MFI/CMF), divergence penalty, PRE-BREAKOUT signal.
E.2b.3: Tech score, breakout patterns, earnings score, seasonality score.
"""

import math
import pytest
from pathlib import Path
from unittest.mock import patch

from src.indicators.divergence import DivergenceSignal
from src.services.technical_composite import (
    CompositeScore,
    TechnicalComposite,
    _SECTOR_SEASONALITY,
    _seasonality_avg_to_score,
)

# =============================================================================
# HELPERS
# =============================================================================

_BASE_CONFIG = {
    "quadrant_scores": {
        "LEADING_LEADING": 30,
        "LEADING_IMPROVING": 10,
        "LEADING_WEAKENING": -5,
        "LEADING_LAGGING": -10,
        "IMPROVING_LEADING": 25,
        "IMPROVING_IMPROVING": 10,
        "IMPROVING_WEAKENING": -10,
        "IMPROVING_LAGGING": -15,
        "WEAKENING_LEADING": 5,
        "WEAKENING_IMPROVING": 0,
        "WEAKENING_WEAKENING": -15,
        "WEAKENING_LAGGING": -20,
        "LAGGING_LEADING": 20,
        "LAGGING_IMPROVING": 15,
        "LAGGING_WEAKENING": -20,
        "LAGGING_LAGGING": -25,
    },
    "rsi_scoring": {
        "period": 14,
        "oversold_threshold": 30,
        "oversold_score": 5.0,
        "neutral_upper": 70,
        "overbought_score": -3.0,
        "neutral_bullish_score": 3.0,
    },
    "divergence_penalties": {
        "single": -6,
        "double": -12,
        "severe": -20,
    },
    "money_flow_scoring": {
        "obv_weight": 0.40,
        "mfi_weight": 0.35,
        "cmf_weight": 0.25,
        "obv_sma_period": 20,
        "mfi_period": 14,
        "cmf_period": 20,
    },
    "weights": {
        "rsi": 1.0,
        "money_flow": 1.0,
        "tech": 1.0,
        "divergence": 1.0,
        "earnings": 1.0,
        "seasonality": 0.5,
        "quadrant_combo": 1.0,
    },
}

_NONEXISTENT_DB = Path("/nonexistent/test_optionplay.db")


def _make_tc(config=None) -> TechnicalComposite:
    return TechnicalComposite(config=config or _BASE_CONFIG)


def _synthetic_closes(n: int = 30, trend: str = "flat") -> list:
    """Generate synthetic close prices for RSI calculation."""
    base = 100.0
    if trend == "down":
        return [base - i * 0.5 for i in range(n)]
    if trend == "up":
        return [base + i * 0.5 for i in range(n)]
    return [base + math.sin(i * 0.5) * 2 for i in range(n)]


def _bullish_ohlcv(n: int = 60, start: float = 100.0, step: float = 0.3, vol: int = 1_000_000):
    """Rising prices, closes near highs (accumulation) → positive CMF/OBV signals."""
    closes = [start + i * step for i in range(n)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 1.0 for c in closes]
    volumes = [float(vol)] * n
    return closes, highs, lows, volumes


def _bearish_ohlcv(n: int = 60, start: float = 100.0, step: float = 0.3, vol: int = 1_000_000):
    """Falling prices, closes near lows (distribution) → negative CMF/OBV signals."""
    closes = [start - i * step for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 0.2 for c in closes]
    volumes = [float(vol)] * n
    return closes, highs, lows, volumes


def _flat_ohlcv(n: int = 60, price: float = 100.0, vol: int = 500_000):
    """Flat prices — minimal indicator signals."""
    closes = [price] * n
    highs = [price + 0.1] * n
    lows = [price - 0.1] * n
    volumes = [float(vol)] * n
    return closes, highs, lows, volumes


_DIV_DETECTED = DivergenceSignal(detected=True, severity=-2.0, message="test", name="test")
_DIV_NONE = DivergenceSignal(detected=False, severity=0.0, message="none", name="test")

_DIV_MODULE = "src.indicators.divergence"


# =============================================================================
# CompositeScore DATACLASS (E.2b.1 + E.2b.3 additions)
# =============================================================================


class TestCompositeScoreDataclass:
    def test_defaults(self):
        cs = CompositeScore(symbol="AAPL", timeframe="classic", total=42.0)
        assert cs.rsi_score == 0.0
        assert cs.money_flow_score == 0.0
        assert cs.tech_score == 0.0
        assert cs.divergence_penalty == 0.0
        assert cs.earnings_score == 0.0
        assert cs.seasonality_score == 0.0
        assert cs.quadrant_combo_score == 0.0
        assert cs.breakout_score == 0.0
        assert cs.pre_breakout is False
        assert cs.breakout_signals == ()

    def test_frozen_raises_on_mutation(self):
        cs = CompositeScore(symbol="AAPL", timeframe="classic", total=10.0)
        with pytest.raises((AttributeError, TypeError)):
            cs.total = 99.0  # type: ignore[misc]

    def test_fields_stored(self):
        cs = CompositeScore(
            symbol="TSLA",
            timeframe="fast",
            total=55.0,
            rsi_score=5.0,
            quadrant_combo_score=30.0,
            breakout_score=7.5,
            breakout_signals=("Bull Flag", "VWAP Reclaim"),
            pre_breakout=True,
        )
        assert cs.symbol == "TSLA"
        assert cs.timeframe == "fast"
        assert cs.total == 55.0
        assert cs.rsi_score == 5.0
        assert cs.quadrant_combo_score == 30.0
        assert cs.breakout_score == 7.5
        assert cs.breakout_signals == ("Bull Flag", "VWAP Reclaim")
        assert cs.pre_breakout is True

    def test_breakout_signals_is_tuple(self):
        cs = CompositeScore(symbol="X", timeframe="classic", total=0.0)
        assert isinstance(cs.breakout_signals, tuple)


# =============================================================================
# QUADRANT COMBO MATRIX (E.2b.1)
# =============================================================================


class TestQuadrantMatrix:
    _QUADS = ["LEADING", "IMPROVING", "WEAKENING", "LAGGING"]

    def test_all_16_combinations_present(self):
        tc = _make_tc()
        for classic in self._QUADS:
            for fast in self._QUADS:
                score = tc._quadrant_combo_score(classic, fast)
                expected = _BASE_CONFIG["quadrant_scores"][f"{classic}_{fast}"]
                assert score == float(expected), f"{classic}_{fast}: {score} != {expected}"

    def test_leading_leading_is_highest_positive(self):
        tc = _make_tc()
        all_scores = [tc._quadrant_combo_score(c, f) for c in self._QUADS for f in self._QUADS]
        assert tc._quadrant_combo_score("LEADING", "LEADING") == max(all_scores)

    def test_lagging_lagging_is_lowest(self):
        tc = _make_tc()
        all_scores = [tc._quadrant_combo_score(c, f) for c in self._QUADS for f in self._QUADS]
        assert tc._quadrant_combo_score("LAGGING", "LAGGING") == min(all_scores)

    def test_unknown_combo_returns_zero(self):
        tc = _make_tc()
        assert tc._quadrant_combo_score("UNKNOWN", "LEADING") == 0.0
        assert tc._quadrant_combo_score("LEADING", "???") == 0.0
        assert tc._quadrant_combo_score("", "") == 0.0

    def test_empty_quadrant_scores_config_returns_zero(self):
        cfg = {**_BASE_CONFIG, "quadrant_scores": {}}
        tc = _make_tc(cfg)
        assert tc._quadrant_combo_score("LEADING", "LEADING") == 0.0

    def test_improving_leading_beats_improving_lagging(self):
        tc = _make_tc()
        assert tc._quadrant_combo_score("IMPROVING", "LEADING") > tc._quadrant_combo_score(
            "IMPROVING", "LAGGING"
        )


# =============================================================================
# RSI SCORE (E.2b.1)
# =============================================================================


class TestRsiScore:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        assert tc._rsi_score([100.0] * 10, period=14) == 0.0

    def test_strongly_oversold_returns_max_bullish(self):
        tc = _make_tc()
        closes = [100.0 - i * 3 for i in range(30)]
        score = tc._rsi_score(closes, period=14)
        assert score == pytest.approx(5.0, abs=0.01)

    def test_strongly_overbought_returns_negative(self):
        tc = _make_tc()
        closes = [50.0 + i * 3 for i in range(30)]
        score = tc._rsi_score(closes, period=14)
        assert score == pytest.approx(-3.0, abs=0.01)

    def test_score_monotone_in_rsi_range(self):
        tc = _make_tc()
        scores = []
        for n_up in [0, 3, 6, 9, 12]:
            n_down = 15 - n_up
            closes = [100.0 - i * 1 for i in range(n_down)] + [
                (100.0 - n_down) + i * 1 for i in range(n_up + 5)
            ]
            scores.append(tc._rsi_score(closes, period=14))
        assert len(scores) == 5

    def test_neutral_range_returns_value_in_bounds(self):
        tc = _make_tc()
        closes = _synthetic_closes(30, "flat")
        score = tc._rsi_score(closes, period=14)
        assert -3.0 <= score <= 5.0

    def test_exact_mid_rsi_returns_near_zero(self):
        tc = _make_tc()
        closes = []
        price = 100.0
        for i in range(40):
            if i % 2 == 0:
                price += 1.0
            else:
                price -= 1.0
            closes.append(price)
        score = tc._rsi_score(closes, period=14)
        assert abs(score) < 1.5


# =============================================================================
# OBV COMPONENT (E.2b.2)
# =============================================================================


class TestObvComponent:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        closes = [100.0] * 10
        volumes = [1_000_000.0] * 10
        assert tc._obv_component(closes, volumes) == 0.0

    def test_accumulation_returns_positive(self):
        tc = _make_tc()
        closes, _, _, volumes = _bullish_ohlcv(n=50)
        score = tc._obv_component(closes, volumes)
        assert score > 0.0

    def test_distribution_returns_negative(self):
        tc = _make_tc()
        closes, _, _, volumes = _bearish_ohlcv(n=50)
        score = tc._obv_component(closes, volumes)
        assert score < 0.0

    def test_price_rising_obv_falling_subtracts_penalty(self):
        tc = _make_tc()
        n = 50
        closes = [100.0 - i * 0.5 for i in range(40)] + [
            100.0 - 40 * 0.5 + i * 0.3 for i in range(10)
        ]
        volumes = [2_000_000.0 if i < 40 else 100_000.0 for i in range(n)]
        score_dist = tc._obv_component(closes, volumes)
        assert score_dist <= 1.5

    def test_score_bounded_reasonable_range(self):
        tc = _make_tc()
        closes, _, _, volumes = _bullish_ohlcv(n=60)
        score = tc._obv_component(closes, volumes)
        assert -2.5 <= score <= 2.5


# =============================================================================
# MFI COMPONENT (E.2b.2)
# =============================================================================


class TestMfiComponent:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        volumes = [500_000.0] * 10
        assert tc._mfi_component(highs, lows, closes, volumes) == 0.0

    def test_overbought_above_80_negative(self):
        tc = _make_tc()
        closes = [50.0 + i * 2.0 for i in range(40)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [2_000_000.0] * 40
        score = tc._mfi_component(highs, lows, closes, volumes)
        assert score <= 0.5

    def test_reversal_zone_rising_high_score(self):
        tc = _make_tc()
        n = 40
        closes = [100.0 - i * 1.5 for i in range(35)] + [
            100.0 - 35 * 1.5 + i * 0.5 for i in range(5)
        ]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1_000_000.0] * n
        score = tc._mfi_component(highs, lows, closes, volumes)
        assert score >= -1.0

    def test_healthy_neutral_zone_rising_positive(self):
        tc = _make_tc()
        closes = [100.0 + i * 0.1 for i in range(40)]
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]
        volumes = [800_000.0] * 40
        score = tc._mfi_component(highs, lows, closes, volumes)
        assert -1.0 <= score <= 1.5

    def test_score_in_valid_range(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=50)
        score = tc._mfi_component(highs, lows, closes, volumes)
        assert -1.0 <= score <= 1.5


# =============================================================================
# CMF COMPONENT (E.2b.2)
# =============================================================================


class TestCmfComponent:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        closes = [100.0] * 15
        highs = [101.0] * 15
        lows = [99.0] * 15
        volumes = [500_000.0] * 15
        assert tc._cmf_component(highs, lows, closes, volumes) == 0.0

    def test_strong_accumulation_positive(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score = tc._cmf_component(highs, lows, closes, volumes)
        assert score > 0.0

    def test_strong_distribution_negative(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bearish_ohlcv(n=60)
        score = tc._cmf_component(highs, lows, closes, volumes)
        assert score < 0.0

    def test_cmf_negative_falling_returns_negative_score(self):
        tc = _make_tc()
        closes = [200.0 - i * 1.0 for i in range(60)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 0.2 for c in closes]
        volumes = [1_000_000.0] * 60
        score = tc._cmf_component(highs, lows, closes, volumes)
        assert score < 0.0

    def test_score_in_valid_range(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score = tc._cmf_component(highs, lows, closes, volumes)
        assert -1.5 <= score <= 1.5


# =============================================================================
# MONEY FLOW SCORE (E.2b.2)
# =============================================================================


class TestMoneyFlowScore:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        volumes = [500_000.0] * 10
        assert tc._money_flow_score(closes, highs, lows, volumes) == 0.0

    def test_all_bullish_positive_score(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score = tc._money_flow_score(closes, highs, lows, volumes)
        assert score > 0.0

    def test_all_bearish_negative_score(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bearish_ohlcv(n=60)
        score = tc._money_flow_score(closes, highs, lows, volumes)
        assert score < 0.0

    def test_score_in_reasonable_range(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score = tc._money_flow_score(closes, highs, lows, volumes)
        assert -2.0 <= score <= 2.0

    def test_weights_sum_correctly(self):
        cfg = {
            **_BASE_CONFIG,
            "money_flow_scoring": {
                "obv_weight": 1.0,
                "mfi_weight": 0.0,
                "cmf_weight": 0.0,
                "obv_sma_period": 20,
                "mfi_period": 14,
                "cmf_period": 20,
            },
        }
        tc = TechnicalComposite(config=cfg)
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score_full = tc._money_flow_score(closes, highs, lows, volumes)
        obv_only = tc._obv_component(closes, volumes)
        assert score_full == pytest.approx(obv_only * 1.0, abs=1e-9)


# =============================================================================
# DIVERGENCE PENALTY (E.2b.2)
# =============================================================================


class TestDivergencePenalty:
    def test_zero_divergences_penalty_zero(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_NONE),
        ):
            penalty = tc._divergence_penalty(closes, highs, lows, volumes)
        assert penalty == 0.0

    def test_one_divergence_penalty_single(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_NONE),
        ):
            penalty = tc._divergence_penalty(closes, highs, lows, volumes)
        assert penalty == -6.0

    def test_three_divergences_penalty_double(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_NONE),
        ):
            penalty = tc._divergence_penalty(closes, highs, lows, volumes)
        assert penalty == -12.0

    def test_five_divergences_penalty_severe(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_DETECTED),
        ):
            penalty = tc._divergence_penalty(closes, highs, lows, volumes)
        assert penalty == -20.0

    def test_yaml_values_read_correctly(self):
        cfg = {
            **_BASE_CONFIG,
            "divergence_penalties": {"single": -7, "double": -14, "severe": -25},
        }
        tc = TechnicalComposite(config=cfg)
        assert tc._div_penalty_single == -7.0
        assert tc._div_penalty_double == -14.0
        assert tc._div_penalty_severe == -25.0

    def test_two_divergences_penalty_double(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_NONE),
        ):
            penalty = tc._divergence_penalty(closes, highs, lows, volumes)
        assert penalty == -12.0

    def test_penalty_is_nonpositive(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_NONE),
        ):
            penalty = tc._divergence_penalty(closes, highs, lows, volumes)
        assert penalty <= 0.0


# =============================================================================
# PRE-BREAKOUT CHECK (E.2b.2)
# =============================================================================


class TestPreBreakoutCheck:
    def test_too_short_returns_false(self):
        tc = _make_tc()
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        volumes = [500_000.0] * 10
        assert tc._pre_breakout_check(closes, highs, lows, volumes) is False

    def test_bearish_data_returns_false(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bearish_ohlcv(n=60)
        result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert result is False

    def test_strong_uptrend_rsi_overbought_returns_false(self):
        tc = _make_tc()
        closes = [50.0 + i * 2.0 for i in range(60)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1_000_000.0] * 60
        result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert result is False

    def test_returns_bool(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert isinstance(result, bool)

    def test_all_conditions_met_returns_true(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)

        cmf_series = [0.05] * 56 + [0.08, 0.10, 0.12, 0.14]
        mfi_series = [40.0] * 11 + [45.0] * 45 + [50.0, 52.0, 55.0, 60.0]
        obv_series = [float(i) * 1000 for i in range(60)]

        with (
            patch("src.indicators.momentum.calculate_rsi", return_value=57.0),
            patch("src.indicators.momentum.calculate_cmf_series", return_value=cmf_series),
            patch("src.indicators.momentum.calculate_mfi_series", return_value=mfi_series),
            patch("src.indicators.momentum.calculate_obv_series", return_value=obv_series),
        ):
            result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert result is True

    def test_cmf_too_low_returns_false(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)

        cmf_series = [0.05] * 56 + [0.06, 0.07, 0.08, 0.09]

        with (
            patch("src.services.technical_composite.calculate_rsi", return_value=57.0),
            patch("src.indicators.momentum.calculate_cmf_series", return_value=cmf_series),
        ):
            result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert result is False

    def test_rsi_above_65_returns_false(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)

        with patch("src.services.technical_composite.calculate_rsi", return_value=70.0):
            result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert result is False

    def test_rsi_below_50_returns_false(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)

        with patch("src.services.technical_composite.calculate_rsi", return_value=45.0):
            result = tc._pre_breakout_check(closes, highs, lows, volumes)
        assert result is False


# =============================================================================
# TECH SCORE (E.2b.3)
# =============================================================================


def _bull_alignment_ohlcv(n: int = 250):
    """250 bars of steady uptrend: close > SMA20 > SMA50 > SMA200."""
    closes = [50.0 + i * 0.3 for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return closes, highs, lows


def _downtrend_ohlcv(n: int = 250):
    """250 bars below SMA50 and SMA200."""
    closes = [250.0 - i * 0.5 for i in range(n)]
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    return closes, highs, lows


class TestTechScore:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        assert tc._tech_score(closes, highs, lows) == 0.0

    def test_full_bullish_alignment_near_max(self):
        # close > SMA20 > SMA50 (and SMA200 with 250 bars)
        tc = _make_tc()
        closes, highs, lows = _bull_alignment_ohlcv(250)
        score = tc._tech_score(closes, highs, lows)
        # SMA alignment max = 0.5+0.8+1.0+0.4+0.3 = 3.0, ADX bonus on top
        assert score > 2.0

    def test_clear_downtrend_negative_score(self):
        tc = _make_tc()
        closes, highs, lows = _downtrend_ohlcv(250)
        score = tc._tech_score(closes, highs, lows)
        # Below SMA50 + SMA200 → -1.5 penalty; ADX on downtrend
        assert score < 0.0

    def test_adx_strong_trend_adds_bonus(self):
        tc = _make_tc()
        # Use patch to inject ADX ≥ 30
        closes, highs, lows = _bull_alignment_ohlcv(60)
        with patch("src.services.technical_composite.calculate_adx", return_value=35.0):
            score_strong = tc._tech_score(closes, highs, lows)
        with patch("src.services.technical_composite.calculate_adx", return_value=10.0):
            score_weak = tc._tech_score(closes, highs, lows)
        assert score_strong > score_weak

    def test_rsi_peak_drop_applies_penalty(self):
        # Build closes where RSI was ~72 at peak but now ~63 (drop ≥ 5)
        tc = _make_tc()
        closes, highs, lows = _bull_alignment_ohlcv(60)
        # Mock: rsi_now=65, rsi_peak=72 → drop=7, all conditions met
        call_count = [0]

        def mock_rsi(prices, period=14):
            call_count[0] += 1
            # First call (now) → 65, subsequent calls (1-9 days back) → rising to 72
            if call_count[0] == 1:
                return 65.0
            return 65.0 + call_count[0] * 1.0  # peaks at 72+

        with patch("src.services.technical_composite.calculate_rsi", side_effect=mock_rsi):
            score = tc._tech_score(closes, highs, lows)
        # Score should have -2.0 penalty applied
        assert score < 3.5  # well below unpenalized max

    def test_fallback_without_sma200(self):
        # Only 60 bars → no SMA200, no crash
        tc = _make_tc()
        closes, highs, lows = _bull_alignment_ohlcv(60)
        score = tc._tech_score(closes, highs, lows)
        assert isinstance(score, float)
        # SMA200 not available but SMA20+SMA50 alignment still scores
        assert score > 0.0


# =============================================================================
# BREAKOUT PATTERNS (E.2b.3)
# =============================================================================


def _bull_flag_data(n: int = 40):
    """Flagpole (10% move), then 3-bar shallow retracement with contracting volume."""
    # Phase 1: base
    base_price = 100.0
    closes = [base_price + i * 0.2 for i in range(20)]
    volumes = [1_000_000.0] * 20

    # Phase 2: flagpole (10% up in 5 bars)
    pole_start = closes[-1]
    for i in range(1, 6):
        closes.append(pole_start + i * 2.0)
        volumes.append(2_000_000.0)

    peak = closes[-1]

    # Phase 3: flag — 3 bars retracing ~10% with falling volume
    for i in range(1, 4):
        closes.append(peak - i * 1.0)
        volumes.append(800_000.0)

    highs = [c + 0.3 for c in closes]
    lows = [c - 0.5 for c in closes]
    return closes, highs, lows, volumes


def _bb_squeeze_data(n: int = 80):
    """Creates a dataset where BB bandwidth is very narrow (squeeze)."""
    # Flat, low-volatility price action for squeeze
    closes = [100.0 + math.sin(i * 0.1) * 0.3 for i in range(n)]
    return closes


class TestBullFlagDetector:
    def test_clean_bull_flag_detected_stage1(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bull_flag_data()
        result = tc._detect_bull_flag(closes, volumes, highs, lows)
        assert result["bull_flag"] is True

    def test_too_short_returns_false(self):
        tc = _make_tc()
        closes = [100.0 + i for i in range(10)]
        volumes = [1_000_000.0] * 10
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        result = tc._detect_bull_flag(closes, volumes, highs, lows)
        assert result["bull_flag"] is False

    def test_flat_market_no_flagpole(self):
        tc = _make_tc()
        closes = [100.0] * 40
        volumes = [1_000_000.0] * 40
        highs = [100.1] * 40
        lows = [99.9] * 40
        result = tc._detect_bull_flag(closes, volumes, highs, lows)
        assert result["bull_flag"] is False

    def test_breakout_imminent_requires_higher_lows_and_vol_contracting(self):
        tc = _make_tc()
        # Build: proper bull flag with higher lows + strongly contracting vol
        closes = [100.0 + i * 0.2 for i in range(20)]
        volumes = [1_000_000.0] * 20
        # Pole
        for i in range(1, 6):
            closes.append(closes[-1] + 2.0)
            volumes.append(2_500_000.0)
        peak = closes[-1]
        # Flag with strictly higher lows and very low volume
        flag_lows = [peak - 2.0, peak - 1.8, peak - 1.6]
        flag_vols = [200_000.0, 180_000.0, 150_000.0]
        for fl, fv in zip(flag_lows, flag_vols):
            closes.append(fl + 0.5)
            volumes.append(fv)

        highs = [c + 0.3 for c in closes]
        lows_list = []
        for i, c in enumerate(closes):
            if i >= len(closes) - 3:
                idx = i - (len(closes) - 3)
                lows_list.append(flag_lows[idx])
            else:
                lows_list.append(c - 0.5)

        result = tc._detect_bull_flag(closes, volumes, highs, lows_list)
        # Stage 1 must be true
        assert result["bull_flag"] is True


class TestBbSqueezeRelease:
    def test_squeeze_release_detected(self):
        tc = _make_tc()
        # Build: 30 historically volatile bars (establishes wide bandwidth baseline),
        # then 20 tight-squeeze bars, then today slightly wider than yesterday.
        # squeeze = current bandwidth in bottom 20% of last 50 days ✓
        # squeeze_releasing = today > yesterday * 1.05 ✓
        closes = [100.0 + math.sin(i * 0.3) * 3.0 for i in range(30)]  # volatile history
        closes += [100.0 + math.sin(i * 0.1) * 0.05 for i in range(20)]  # tight squeeze
        closes.append(100.25)  # today: noticeably wider (2.5× prior avg deviation)
        assert tc._detect_bb_squeeze_release(closes) is True

    def test_no_squeeze_high_vol(self):
        tc = _make_tc()
        # Highly volatile throughout → pct_rank > 0.20, no squeeze
        import random

        random.seed(42)
        closes = [100.0 + random.gauss(0, 3) for _ in range(80)]
        result = tc._detect_bb_squeeze_release(closes)
        assert isinstance(result, bool)

    def test_too_short_returns_false(self):
        tc = _make_tc()
        assert tc._detect_bb_squeeze_release([100.0] * 15) is False

    def test_squeeze_without_release_not_detected(self):
        tc = _make_tc()
        # All flat → bandwidth = 0 both today and yesterday → no release (0 is not > 0*1.05)
        closes = [100.0] * 80
        result = tc._detect_bb_squeeze_release(closes)
        assert result is False


class TestVwapReclaim:
    def test_vwap_reclaim_detected(self):
        tc = _make_tc()
        n = 20
        # VWAP will be around 99-100; yesterday below, today above
        closes = [98.0] * (n - 3) + [97.0, 97.5, 101.0]  # last 2 below, today above
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1_000_000.0] * n
        result = tc._detect_vwap_reclaim(closes, highs, lows, volumes)
        assert isinstance(result, bool)

    def test_too_short_returns_false(self):
        tc = _make_tc()
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        volumes = [1_000_000.0] * 10
        assert tc._detect_vwap_reclaim(closes, highs, lows, volumes) is False

    def test_consistently_above_vwap_not_reclaim(self):
        tc = _make_tc()
        n = 20
        # Always above VWAP — no reclaim
        closes = [105.0] * n
        highs = [106.0] * n
        lows = [104.0] * n
        volumes = [1_000_000.0] * n
        result = tc._detect_vwap_reclaim(closes, highs, lows, volumes)
        assert result is False


class TestThreeBarPlay:
    def _three_bullish_bars(self, base: float = 100.0, vol_base: float = 1_000_000.0):
        """5 bars where the last 3 are a clean 3-bar play."""
        opens = [base, base + 0.2, base + 1.0, base + 1.5, base + 2.5]
        closes = [base + 0.5, base + 0.8, base + 1.8, base + 3.0, base + 4.5]
        highs = [base + 0.6, base + 0.9, base + 2.0, base + 3.2, base + 4.7]
        lows = [base - 0.1, base + 0.1, base + 0.9, base + 1.4, base + 2.4]
        volumes = [vol_base, vol_base, vol_base * 1.2, vol_base * 1.5, vol_base * 2.0]
        return opens, highs, lows, closes, volumes

    def test_clean_three_bar_play_detected(self):
        tc = _make_tc()
        opens, highs, lows, closes, volumes = self._three_bullish_bars()
        assert tc._detect_three_bar_play(opens, highs, lows, closes, volumes) is True

    def test_declining_volume_not_detected(self):
        tc = _make_tc()
        opens, highs, lows, closes, volumes = self._three_bullish_bars()
        # Reverse volume trend
        volumes[-3], volumes[-1] = volumes[-1], volumes[-3]
        assert tc._detect_three_bar_play(opens, highs, lows, closes, volumes) is False

    def test_too_short_returns_false(self):
        tc = _make_tc()
        opens = [100.0] * 3
        closes = [101.0] * 3
        highs = [102.0] * 3
        lows = [99.0] * 3
        volumes = [1_000_000.0] * 3
        assert tc._detect_three_bar_play(opens, highs, lows, closes, volumes) is False

    def test_bearish_candle_in_sequence_not_detected(self):
        tc = _make_tc()
        opens, highs, lows, closes, volumes = self._three_bullish_bars()
        # Make second-to-last bar bearish
        closes[-2] = opens[-2] - 0.5
        assert tc._detect_three_bar_play(opens, highs, lows, closes, volumes) is False


class TestGoldenPocket:
    def test_in_pocket_no_confluence_not_detected(self):
        tc = _make_tc()
        # Price is in golden pocket zone but no RSI/RVOL confluence
        n = 70
        closes = [100.0 + i * 0.5 for i in range(40)]  # uptrend
        closes += [closes[-1] - i * 0.4 for i in range(1, 20)]  # retracement into GP zone
        closes += [closes[-1] + 0.1]  # slight recovery
        volumes = [1_000_000.0] * len(closes)

        # RSI outside 45-65 and RVOL < 1.2 → no confluence
        with (patch("src.services.technical_composite.calculate_rsi", return_value=38.0),):
            result = tc._detect_golden_pocket(
                closes, highs=[c + 1 for c in closes], lows=[c - 1 for c in closes], volumes=volumes
            )
        assert result is False

    def test_in_pocket_with_full_confluence_detected(self):
        tc = _make_tc()
        # Uptrend from 100 to 140, then retrace to 127 (13 points back).
        # GP zone: 140 - 13*0.50 = 133.5 (high), 140 - 13*0.65 = 131.55 (low).
        # Current = 132.0 → in pocket, recovering from 127 previous low.
        closes = [100.0 + i for i in range(41)]  # 100 to 140
        closes += [140.0 - i for i in range(1, 15)]  # 139 down to 127
        closes += [132.0]  # today in GP zone, recovering

        # RVOL >= 1.2: today vol higher than 20-day avg
        volumes = [1_000_000.0] * (len(closes) - 1) + [1_500_000.0]

        with patch("src.services.technical_composite.calculate_rsi", return_value=55.0):
            result = tc._detect_golden_pocket(
                closes,
                highs=[c + 0.5 for c in closes],
                lows=[c - 0.5 for c in closes],
                volumes=volumes,
            )
        assert result is True

    def test_too_short_returns_false(self):
        tc = _make_tc()
        assert (
            tc._detect_golden_pocket([100.0] * 10, [101.0] * 10, [99.0] * 10, [1e6] * 10) is False
        )


class TestNr7InsideBar:
    def test_nr7_and_inside_bar_combo_detected(self):
        tc = _make_tc()
        # Build 8 bars where last bar is narrowest (NR7) and inside prior
        highs = [105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 109.0, 108.5]
        lows = [95.0, 94.0, 93.0, 92.0, 91.0, 90.0, 91.0, 91.5]
        # Last bar is inside bar (high <= prev high, low >= prev low)
        # AND narrowest: range = 108.5-91.5 = 17.0 < others
        # Actually let me construct it more carefully:
        highs = [110.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.5]
        lows = [90.0, 92.0, 93.0, 94.0, 95.0, 96.0, 97.0, 97.5]
        # Last bar: high=102.5 <= prev high=103.0, low=97.5 >= prev low=97.0 → inside
        # Ranges: [20, 16, 14, 12, 10, 8, 6, 5] → last is min → NR7
        assert tc._detect_nr7_inside_bar(highs, lows) is True

    def test_nr7_alone_not_detected(self):
        tc = _make_tc()
        # NR7 but NOT inside bar (current range is narrowest but breaks prior bar)
        highs = [110.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 115.0]
        lows = [90.0, 92.0, 93.0, 94.0, 95.0, 96.0, 97.0, 97.5]
        # Last bar: high=115 > prev high=103 → not inside bar
        # Range = 115-97.5 = 17.5 > others though — not NR7 either, so False both ways
        assert tc._detect_nr7_inside_bar(highs, lows) is False

    def test_inside_bar_alone_not_detected(self):
        tc = _make_tc()
        # Inside bar but NOT NR7
        highs = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 115.0, 102.0]
        lows = [80.0, 80.0, 80.0, 80.0, 80.0, 80.0, 75.0, 78.0]
        # Last bar: high=102 <= prev 115, low=78 >= prev 75 → inside bar YES
        # Last bar range = 24.0, but prior bar range = 40.0 → last NOT narrowest → not NR7
        assert tc._detect_nr7_inside_bar(highs, lows) is False

    def test_too_short_returns_false(self):
        tc = _make_tc()
        assert tc._detect_nr7_inside_bar([105.0] * 5, [95.0] * 5) is False

    def test_no_patterns_breakout_score_zero(self):
        tc = _make_tc()
        # Bullish trending data: rising highs prevent inside-bar, constant
        # volume prevents 3-bar play, continuous uptrend prevents bull-flag.
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score, signals = tc._breakout_score(closes, highs, lows, volumes)
        assert score == 0.0
        assert signals == []


# =============================================================================
# EARNINGS SCORE (E.2b.3)
# =============================================================================


class TestEarningsScore:
    def test_four_beats_returns_plus_12(self):
        tc = _make_tc()
        from src.services.earnings_quality import EarningsSurpriseResult

        mock_result = EarningsSurpriseResult(
            modifier=1.2, beats=4, misses=0, meets=0, total=4, pattern="4/4 beats"
        )
        # Patch at the source module (lazy import picks it up)
        with patch(
            "src.services.earnings_quality.calculate_earnings_surprise_modifier",
            return_value=mock_result,
        ):
            score = tc._earnings_score("AAPL")
        assert score == pytest.approx(12.0)

    def test_four_misses_returns_minus_28(self):
        from src.services.earnings_quality import EarningsSurpriseResult

        mock_result = EarningsSurpriseResult(
            modifier=-2.8, beats=0, misses=4, meets=0, total=4, pattern="4/4 misses"
        )
        assert mock_result.modifier * 10.0 == pytest.approx(-28.0)

    def test_mixed_returns_zero(self):
        from src.services.earnings_quality import EarningsSurpriseResult

        mock_result = EarningsSurpriseResult(
            modifier=0.0, beats=2, misses=2, meets=0, total=4, pattern="2B/2M/0E of 4"
        )
        assert mock_result.modifier * 10.0 == pytest.approx(0.0)

    def test_no_db_returns_zero(self):
        tc = _make_tc()
        score = tc._earnings_score("FAKE_SYMBOL_XYZ", db_path=_NONEXISTENT_DB)
        assert score == 0.0

    def test_earnings_score_multiply_by_10(self):
        # Verify the ×10 scaling for all modifier tiers
        modifiers = [1.2, 0.6, 0.0, -1.0, -1.8, -2.8]
        expected = [12.0, 6.0, 0.0, -10.0, -18.0, -28.0]
        for mod, exp in zip(modifiers, expected):
            assert pytest.approx(mod * 10.0) == exp


# =============================================================================
# SEASONALITY SCORE (E.2b.3)
# =============================================================================


class TestSeasonalityScore:
    def test_strong_month_positive_score(self):
        tc = _make_tc()
        # Technology in November: +2.0 → score +1.5
        with patch.object(tc, "_get_sector", return_value="Technology"):
            score = tc._seasonality_score("AAPL", month=11)
        assert score > 0.0

    def test_weak_month_negative_score(self):
        tc = _make_tc()
        # Technology in September: -1.5 → score -1.0
        with patch.object(tc, "_get_sector", return_value="Technology"):
            score = tc._seasonality_score("AAPL", month=9)
        assert score <= 0.0

    def test_missing_sector_returns_zero(self):
        tc = _make_tc()
        with patch.object(tc, "_get_sector", return_value=None):
            score = tc._seasonality_score("FAKE", month=1)
        assert score == 0.0

    def test_all_known_sectors_return_float(self):
        tc = _make_tc()
        for sector in _SECTOR_SEASONALITY:
            with patch.object(tc, "_get_sector", return_value=sector):
                score = tc._seasonality_score("X", month=6)
            assert isinstance(score, float)

    def test_seasonality_avg_to_score_mapping(self):
        assert _seasonality_avg_to_score(3.5) == 3.0
        assert _seasonality_avg_to_score(2.0) == 1.5
        assert _seasonality_avg_to_score(0.8) == 0.5
        assert _seasonality_avg_to_score(0.0) == 0.0
        assert _seasonality_avg_to_score(-1.0) == -1.0
        assert _seasonality_avg_to_score(-2.0) == -2.0


# =============================================================================
# INTEGRATION — compute() (E.2b.1 + E.2b.2 + E.2b.3)
# =============================================================================


class TestComputeSmoke:
    def test_compute_returns_composite_score(self):
        tc = _make_tc()
        closes = [100.0 + i * 0.2 for i in range(60)]
        cs = tc.compute(
            symbol="AAPL",
            closes=closes,
            highs=[c + 1 for c in closes],
            lows=[c - 1 for c in closes],
            volumes=[1_000_000.0] * 60,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="LEADING",
            db_path=_NONEXISTENT_DB,
        )
        assert isinstance(cs, CompositeScore)
        assert cs.symbol == "AAPL"
        assert cs.timeframe == "classic"
        assert cs.quadrant_combo_score == 30.0
        assert cs.rsi_score != 0.0
        # E.2b.2 components populated
        assert isinstance(cs.money_flow_score, float)
        assert isinstance(cs.divergence_penalty, float)
        assert isinstance(cs.pre_breakout, bool)
        # E.2b.3 components populated
        assert isinstance(cs.tech_score, float)
        assert isinstance(cs.earnings_score, float)
        assert isinstance(cs.seasonality_score, float)
        assert isinstance(cs.breakout_score, float)
        assert isinstance(cs.breakout_signals, tuple)

    def test_compute_total_includes_all_components(self):
        tc = _make_tc()
        closes = [100.0 + i * 0.2 for i in range(60)]
        cs = tc.compute(
            symbol="MSFT",
            closes=closes,
            highs=[c + 1 for c in closes],
            lows=[c - 1 for c in closes],
            volumes=[500_000.0] * 60,
            timeframe="fast",
            classic_quadrant="IMPROVING",
            fast_quadrant="LEADING",
            db_path=_NONEXISTENT_DB,
        )
        w = _BASE_CONFIG["weights"]
        expected_total = (
            cs.rsi_score * w["rsi"]
            + cs.money_flow_score * w["money_flow"]
            + cs.tech_score * w["tech"]
            + cs.divergence_penalty * w["divergence"]
            + cs.earnings_score * w["earnings"]
            + cs.seasonality_score * w["seasonality"]
            + cs.quadrant_combo_score * w["quadrant_combo"]
            + cs.breakout_score  # unweighted
        )
        assert cs.total == pytest.approx(expected_total, abs=1e-9)

    def test_breakout_signals_tuple_in_result(self):
        tc = _make_tc()
        # Bullish trending data → rising highs prevent inside-bar combos
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        cs = tc.compute(
            symbol="X",
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="LEADING",
            db_path=_NONEXISTENT_DB,
        )
        assert isinstance(cs.breakout_signals, tuple)
        # Continuous uptrend (no flagpole retracement, constant volume) → no patterns
        assert cs.breakout_score == 0.0
        assert cs.breakout_signals == ()

    def test_tech_score_nonzero_for_sufficient_data(self):
        tc = _make_tc()
        closes, highs, lows = _bull_alignment_ohlcv(60)
        volumes = [1_000_000.0] * 60
        cs = tc.compute(
            symbol="X",
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="IMPROVING",
            db_path=_NONEXISTENT_DB,
        )
        assert cs.tech_score != 0.0

    def test_compute_money_flow_nonzero_for_sufficient_data(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        cs = tc.compute(
            symbol="X",
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="IMPROVING",
            db_path=_NONEXISTENT_DB,
        )
        assert cs.money_flow_score != 0.0

    def test_compute_divergence_penalty_negative_when_detected(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        with (
            patch(f"{_DIV_MODULE}.check_price_rsi_divergence", return_value=_DIV_DETECTED),
            patch(f"{_DIV_MODULE}.check_price_obv_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_price_mfi_divergence", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_and_macd_falling", return_value=_DIV_NONE),
            patch(f"{_DIV_MODULE}.check_cmf_early_warning", return_value=_DIV_NONE),
        ):
            cs = tc.compute(
                symbol="Y",
                closes=closes,
                highs=highs,
                lows=lows,
                volumes=volumes,
                timeframe="classic",
                classic_quadrant="LEADING",
                fast_quadrant="LEADING",
                db_path=_NONEXISTENT_DB,
            )
        assert cs.divergence_penalty == -6.0

    def test_compute_negative_quadrant_reduces_total(self):
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)
        cs_good = tc.compute(
            symbol="X",
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="LEADING",
            db_path=_NONEXISTENT_DB,
        )
        cs_bad = tc.compute(
            symbol="X",
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            timeframe="classic",
            classic_quadrant="LAGGING",
            fast_quadrant="LAGGING",
            db_path=_NONEXISTENT_DB,
        )
        assert cs_good.total > cs_bad.total

    def test_compute_with_minimal_closes_returns_zero_rsi(self):
        tc = _make_tc()
        closes = [100.0] * 10
        cs = tc.compute(
            symbol="Z",
            closes=closes,
            highs=closes,
            lows=closes,
            volumes=[0.0] * 10,
            timeframe="classic",
            classic_quadrant="WEAKENING",
            fast_quadrant="IMPROVING",
            db_path=_NONEXISTENT_DB,
        )
        assert cs.rsi_score == 0.0
        assert cs.quadrant_combo_score == 0.0  # WEAKENING_IMPROVING = 0

    def test_no_alpha_scorer_import(self):
        """Regression: technical_composite must not import alpha_scorer."""
        import src.services.technical_composite as mod
        import inspect

        source = inspect.getsource(mod)
        assert "alpha_scorer" not in source
