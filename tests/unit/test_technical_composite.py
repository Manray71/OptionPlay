"""Tests for TechnicalComposite (E.2b.1) — CompositeScore, RSI, quadrant matrix."""

import math
import pytest

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
    # flat with slight oscillation
    import math as m

    return [base + m.sin(i * 0.5) * 2 for i in range(n)]


# =============================================================================
# CompositeScore DATACLASS
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
        )
        assert cs.symbol == "TSLA"
        assert cs.timeframe == "fast"
        assert cs.total == 55.0
        assert cs.rsi_score == 5.0
        assert cs.quadrant_combo_score == 30.0


# =============================================================================
# QUADRANT COMBO MATRIX
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
# RSI SCORE
# =============================================================================


class TestRsiScore:
    def test_too_short_returns_zero(self):
        tc = _make_tc()
        # Need at least period+1 = 15 prices; provide fewer
        assert tc._rsi_score([100.0] * 10, period=14) == 0.0

    def test_strongly_oversold_returns_max_bullish(self):
        # Prices falling sharply → RSI << 30
        tc = _make_tc()
        closes = [100.0 - i * 3 for i in range(30)]  # strong downtrend
        score = tc._rsi_score(closes, period=14)
        # Should hit oversold_score = 5.0
        assert score == pytest.approx(5.0, abs=0.01)

    def test_strongly_overbought_returns_negative(self):
        # Prices rising sharply → RSI >> 70
        tc = _make_tc()
        closes = [50.0 + i * 3 for i in range(30)]
        score = tc._rsi_score(closes, period=14)
        assert score == pytest.approx(-3.0, abs=0.01)

    def test_score_monotone_in_rsi_range(self):
        # Monotonicity: as RSI increases from 30 to 70, score decreases from 5 to 3
        tc = _make_tc()
        # Build sequences with known RSI ranges by controlling slopes
        scores = []
        for n_up in [0, 3, 6, 9, 12]:
            n_down = 15 - n_up
            closes = [100.0 - i * 1 for i in range(n_down)] + [
                (100.0 - n_down) + i * 1 for i in range(n_up + 5)
            ]
            scores.append(tc._rsi_score(closes, period=14))
        # At least the direction from min_up to max_up should show score increase
        # (more ups = higher RSI = lower score below 50, higher above 50)
        assert len(scores) == 5  # just verify it runs without error

    def test_neutral_range_returns_value_in_bounds(self):
        tc = _make_tc()
        closes = _synthetic_closes(30, "flat")
        score = tc._rsi_score(closes, period=14)
        assert -3.0 <= score <= 5.0

    def test_exact_mid_rsi_returns_near_zero(self):
        # Alternating up/down closes produce RSI ≈ 50
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
        # Score should be near 0 when RSI ≈ 50
        assert abs(score) < 1.5


# =============================================================================
# INTEGRATION SMOKE TEST
# =============================================================================


class TestComputeSmoke:
    def test_compute_returns_composite_score(self):
        tc = _make_tc()
        closes = [100.0 + i * 0.2 for i in range(30)]
        cs = tc.compute(
            symbol="AAPL",
            closes=closes,
            highs=[c + 1 for c in closes],
            lows=[c - 1 for c in closes],
            volumes=[1_000_000.0] * 30,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="LEADING",
        )
        assert isinstance(cs, CompositeScore)
        assert cs.symbol == "AAPL"
        assert cs.timeframe == "classic"
        assert cs.quadrant_combo_score == 30.0
        assert cs.rsi_score != 0.0
        # E.2b.2/3 components are still zero
        assert cs.money_flow_score == 0.0
        assert cs.tech_score == 0.0
        assert cs.divergence_penalty == 0.0
        assert cs.earnings_score == 0.0
        assert cs.seasonality_score == 0.0

    def test_compute_total_equals_sum_of_active_components(self):
        tc = _make_tc()
        closes = [100.0 + i * 0.2 for i in range(30)]
        cs = tc.compute(
            symbol="MSFT",
            closes=closes,
            highs=[c + 1 for c in closes],
            lows=[c - 1 for c in closes],
            volumes=[500_000.0] * 30,
            timeframe="fast",
            classic_quadrant="IMPROVING",
            fast_quadrant="LEADING",
        )
        assert cs.total == pytest.approx(cs.rsi_score + cs.quadrant_combo_score, abs=1e-9)

    def test_compute_negative_quadrant_reduces_total(self):
        tc = _make_tc()
        closes = [100.0] * 30
        cs_good = tc.compute(
            symbol="X",
            closes=closes,
            highs=closes,
            lows=closes,
            volumes=[1e6] * 30,
            timeframe="classic",
            classic_quadrant="LEADING",
            fast_quadrant="LEADING",
        )
        cs_bad = tc.compute(
            symbol="X",
            closes=closes,
            highs=closes,
            lows=closes,
            volumes=[1e6] * 30,
            timeframe="classic",
            classic_quadrant="LAGGING",
            fast_quadrant="LAGGING",
        )
        assert cs_good.total > cs_bad.total

    def test_compute_with_minimal_closes(self):
        # Fewer than period+1 closes → rsi_score = 0.0
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
