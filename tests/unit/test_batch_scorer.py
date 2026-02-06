# Tests for BatchScorer (Schritt 5B)
import pytest
import numpy as np
import yaml

from src.config.scoring_config import RecursiveConfigResolver
from src.analyzers.batch_scorer import BatchScorer


@pytest.fixture(autouse=True)
def reset_singleton():
    RecursiveConfigResolver.reset()
    yield
    RecursiveConfigResolver.reset()


@pytest.fixture
def sample_yaml(tmp_path):
    config = {
        "version": "1.0.0",
        "defaults": {"min_stability": 70},
        "strategies": {
            "pullback": {
                "weights": {
                    "rsi": 3.0,
                    "support": 2.5,
                    "macd": 2.0,
                    "vwap": 3.0,
                },
                "max_possible": 10.5,
                "regimes": {"normal": {}, "danger": {"min_stability": 80}},
                "sectors": {
                    "Technology": {"weights": {"rsi": 2.0}},
                },
            },
        },
    }
    yaml_path = tmp_path / "scoring_weights.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    return str(yaml_path)


@pytest.fixture
def scorer(sample_yaml):
    resolver = RecursiveConfigResolver(sample_yaml)
    return BatchScorer(resolver)


class TestBatchScorer:
    def test_batch_equals_sequential(self, scorer):
        """Batch result must match sequential results within tolerance."""
        component_names = ["rsi", "support", "macd", "vwap"]
        # 5 symbols, all same sector
        matrix = np.array([
            [1.0, 0.8, 0.5, 0.7],
            [0.5, 1.0, 1.0, 0.3],
            [0.9, 0.6, 0.8, 1.0],
            [0.0, 0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0, 1.0],
        ])
        sectors = [None, None, None, None, None]

        batch_scores = scorer.score_batch("pullback", "normal", sectors, matrix, component_names)

        # Sequential comparison
        for i in range(5):
            components = dict(zip(component_names, matrix[i]))
            seq_score = scorer.score_single("pullback", "normal", None, components)
            assert abs(batch_scores[i] - seq_score) < 0.001, (
                f"Symbol {i}: batch={batch_scores[i]:.4f} != seq={seq_score:.4f}"
            )

    def test_different_sectors_grouped(self, scorer):
        """Symbols with different sectors get different weight vectors."""
        component_names = ["rsi", "support", "macd", "vwap"]
        matrix = np.array([
            [1.0, 1.0, 1.0, 1.0],  # No sector
            [1.0, 1.0, 1.0, 1.0],  # Technology (rsi=2.0 instead of 3.0)
        ])
        sectors = [None, "Technology"]

        scores = scorer.score_batch("pullback", "normal", sectors, matrix, component_names)

        # Technology has lower rsi weight (2.0 vs 3.0), so score should differ
        assert scores[0] != scores[1]
        # Technology score should be lower
        assert scores[1] < scores[0]

    def test_empty_matrix(self, scorer):
        """Empty matrix returns empty array."""
        matrix = np.zeros((0, 4))
        scores = scorer.score_batch("pullback", "normal", [], matrix, ["rsi", "support", "macd", "vwap"])
        assert scores.shape == (0,)

    def test_numpy_types(self, scorer):
        """Results should be numpy float64."""
        matrix = np.array([[1.0, 0.5, 0.3, 0.8]])
        scores = scorer.score_batch("pullback", "normal", [None], matrix, ["rsi", "support", "macd", "vwap"])
        assert scores.dtype == np.float64

    def test_scores_clamped_0_10(self, scorer):
        """Scores must be within [0, 10]."""
        # Very high component values
        matrix = np.array([[10.0, 10.0, 10.0, 10.0]])
        scores = scorer.score_batch("pullback", "normal", [None], matrix, ["rsi", "support", "macd", "vwap"])
        assert scores[0] <= 10.0

        # Negative component values
        matrix2 = np.array([[-5.0, -5.0, -5.0, -5.0]])
        scores2 = scorer.score_batch("pullback", "normal", [None], matrix2, ["rsi", "support", "macd", "vwap"])
        assert scores2[0] >= 0.0

    def test_single_symbol_matches_batch(self, scorer):
        """score_single should match a 1-symbol batch."""
        components = {"rsi": 0.8, "support": 0.6, "macd": 0.4, "vwap": 0.9}
        single = scorer.score_single("pullback", "normal", None, components)

        names = list(components.keys())
        matrix = np.array([[components[n] for n in names]])
        batch = scorer.score_batch("pullback", "normal", [None], matrix, names)

        assert abs(single - batch[0]) < 0.001


class TestBatchPerformance:
    def test_large_batch(self, scorer):
        """Verify batch scoring works for 275+ symbols."""
        n = 275
        component_names = ["rsi", "support", "macd", "vwap"]
        matrix = np.random.rand(n, len(component_names))
        sectors = [None] * n

        scores = scorer.score_batch("pullback", "normal", sectors, matrix, component_names)
        assert scores.shape == (n,)
        assert np.all(scores >= 0)
        assert np.all(scores <= 10)
