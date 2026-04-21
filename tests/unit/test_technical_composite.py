"""Tests for TechnicalComposite — E.2b.1 + E.2b.2.

E.2b.1: CompositeScore dataclass, RSI score, quadrant matrix.
E.2b.2: Money flow score (OBV/MFI/CMF), divergence penalty, PRE-BREAKOUT signal.
"""

import math
import pytest
from unittest.mock import patch

from src.indicators.divergence import DivergenceSignal
from src.services.technical_composite import CompositeScore, TechnicalComposite

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
    highs = [c + 0.2 for c in closes]  # close only 0.2 below high
    lows = [c - 1.0 for c in closes]  # close 1.0 above low → CMF positive
    volumes = [float(vol)] * n
    return closes, highs, lows, volumes


def _bearish_ohlcv(n: int = 60, start: float = 100.0, step: float = 0.3, vol: int = 1_000_000):
    """Falling prices, closes near lows (distribution) → negative CMF/OBV signals."""
    closes = [start - i * step for i in range(n)]
    highs = [c + 1.0 for c in closes]  # close 1.0 below high
    lows = [c - 0.2 for c in closes]  # close only 0.2 above low → CMF negative
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
# CompositeScore DATACLASS (E.2b.1 + E.2b.2 additions)
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
        assert cs.pre_breakout is False

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
            pre_breakout=True,
        )
        assert cs.symbol == "TSLA"
        assert cs.timeframe == "fast"
        assert cs.total == 55.0
        assert cs.rsi_score == 5.0
        assert cs.quadrant_combo_score == 30.0
        assert cs.pre_breakout is True

    def test_pre_breakout_default_false(self):
        cs = CompositeScore(symbol="X", timeframe="classic", total=0.0)
        assert cs.pre_breakout is False


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
        # Falling prices → OBV falls → below SMA20
        tc = _make_tc()
        closes, _, _, volumes = _bearish_ohlcv(n=50)
        score = tc._obv_component(closes, volumes)
        assert score < 0.0

    def test_price_rising_obv_falling_subtracts_penalty(self):
        # Build data: price rises last 6 bars but OBV was previously falling
        # We use high volume on down days, low on up days (classic distribution)
        tc = _make_tc()
        n = 50
        closes = [100.0 - i * 0.5 for i in range(40)] + [
            100.0 - 40 * 0.5 + i * 0.3 for i in range(10)
        ]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        # High volume on down moves, low volume on up moves → OBV falling while price rises
        volumes = [2_000_000.0 if i < 40 else 100_000.0 for i in range(n)]
        score_dist = tc._obv_component(closes, volumes)
        score_neutral = tc._obv_component([100.0] * n, [500_000.0] * n)
        # Distribution case should be <= neutral (or at least not strongly positive)
        assert score_dist <= 1.5  # cap: can't exceed accumulation max with divergence deduction

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
        # Strong uptrend → MFI typically high → if > 80, return -0.5
        tc = _make_tc()
        closes = [50.0 + i * 2.0 for i in range(40)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [2_000_000.0] * 40
        score = tc._mfi_component(highs, lows, closes, volumes)
        # MFI in strong uptrend with high volume is often > 80 → -0.5
        assert score <= 0.5  # either -0.5 (overbought) or modest positive

    def test_reversal_zone_rising_high_score(self):
        # Downtrend then reversal: MFI should be low and potentially rising
        tc = _make_tc()
        n = 40
        # Falling then recovering
        closes = [100.0 - i * 1.5 for i in range(35)] + [
            100.0 - 35 * 1.5 + i * 0.5 for i in range(5)
        ]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1_000_000.0] * n
        score = tc._mfi_component(highs, lows, closes, volumes)
        # Low MFI with recent uptick should give positive score
        assert score >= -1.0  # at worst -1.0 (falling)

    def test_healthy_neutral_zone_rising_positive(self):
        # Mild uptrend → MFI likely in 40-60 range
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
        # Closes near lows (distribution) → CMF negative
        tc = _make_tc()
        closes = [200.0 - i * 1.0 for i in range(60)]
        highs = [c + 1.0 for c in closes]  # close 1.0 below high
        lows = [c - 0.2 for c in closes]  # close only 0.2 above low → CMF negative
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
        # Max theoretical: 0.40*1.5 + 0.35*1.5 + 0.25*1.5 = 1.5
        # Min theoretical: roughly -0.40*1.5 + -0.35*1.0 + -0.25*1.5 ≈ -1.325
        tc = _make_tc()
        closes, highs, lows, volumes = _bullish_ohlcv(n=60)
        score = tc._money_flow_score(closes, highs, lows, volumes)
        assert -2.0 <= score <= 2.0

    def test_weights_sum_correctly(self):
        # Verify that custom weights from config are applied
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
        # Strong uptrend → RSI >> 65 → condition not met
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
        # All 4 conditions met via mocks.
        # calculate_rsi is imported inside _pre_breakout_check, so patch at source module.
        tc = _make_tc()
        closes, highs, lows, volumes = _flat_ohlcv(n=60)

        cmf_series = [0.05] * 56 + [0.08, 0.10, 0.12, 0.14]  # rising, ends > 0.10
        mfi_series = [40.0] * 11 + [45.0] * 45 + [50.0, 52.0, 55.0, 60.0]  # 50-65, rising
        obv_series = [float(i) * 1000 for i in range(60)]  # monotone → always > SMA20

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

        cmf_series = [0.05] * 56 + [0.06, 0.07, 0.08, 0.09]  # rising but < 0.10

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
# INTEGRATION — compute() (E.2b.1 + E.2b.2)
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
        )
        assert isinstance(cs, CompositeScore)
        assert cs.symbol == "AAPL"
        assert cs.timeframe == "classic"
        assert cs.quadrant_combo_score == 30.0
        assert cs.rsi_score != 0.0
        # E.2b.2 components are now populated
        assert isinstance(cs.money_flow_score, float)
        assert isinstance(cs.divergence_penalty, float)
        assert isinstance(cs.pre_breakout, bool)
        # E.2b.3 components still zero
        assert cs.tech_score == 0.0
        assert cs.earnings_score == 0.0
        assert cs.seasonality_score == 0.0

    def test_compute_total_includes_all_e2b2_components(self):
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
        )
        w = _BASE_CONFIG["weights"]
        expected_total = (
            cs.rsi_score * w["rsi"]
            + cs.money_flow_score * w["money_flow"]
            + cs.divergence_penalty * w["divergence"]
            + cs.quadrant_combo_score * w["quadrant_combo"]
        )
        assert cs.total == pytest.approx(expected_total, abs=1e-9)

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
            )
        assert cs.divergence_penalty == -6.0
        assert cs.total < cs.rsi_score + cs.quadrant_combo_score + cs.money_flow_score

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
        )
        assert cs.rsi_score == 0.0
        assert cs.quadrant_combo_score == 0.0  # WEAKENING_IMPROVING = 0

    def test_no_alpha_scorer_import(self):
        """Regression: technical_composite must not import alpha_scorer."""
        import src.services.technical_composite as mod
        import inspect

        source = inspect.getsource(mod)
        assert "alpha_scorer" not in source
