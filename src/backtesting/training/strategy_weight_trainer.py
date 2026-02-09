# OptionPlay - Strategy-Specific Weight Trainer (v3)
# ==================================================
"""
Trains scoring weights for a single strategy using v3 configuration.

Uses strategy-specific:
- Objective functions (win_rate, avg_profit, penalties)
- Walk-forward windows (larger for rarer strategies)
- Regularization (stronger for data-scarce strategies)
- Cross-validation methods

The trainer loads its config from scoring_weights.yaml → training.strategy_configs[strategy].

Usage:
    from src.backtesting.training.strategy_weight_trainer import StrategyWeightTrainer

    trainer = StrategyWeightTrainer("pullback")
    result = trainer.train(all_trades_df)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from scipy.optimize import minimize
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from ...config.scoring_config import get_scoring_resolver
from .ml_weight_optimizer import (
    STRATEGY_COMPONENTS,
    DEFAULT_WEIGHTS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class StrategyTrainingConfig:
    """Training configuration for a single strategy (from YAML)."""
    strategy: str
    # Walk-forward
    train_months: int = 6
    validation_months: int = 2
    min_trades: int = 100
    # Regularization
    l2_lambda: float = 0.01
    max_weight_change: float = 0.30
    weight_bounds: Tuple[float, float] = (0.5, 5.0)
    # Objective weights
    objective_weights: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, strategy: str) -> "StrategyTrainingConfig":
        """Load from scoring_weights.yaml → training.strategy_configs[strategy]."""
        resolver = get_scoring_resolver()
        cfg = resolver.get_training_config(strategy)
        if not cfg:
            logger.info(f"No training config for '{strategy}', using defaults")
            return cls(strategy=strategy)

        wf = cfg.get("walk_forward", {})
        reg = cfg.get("regularization", {})
        obj = cfg.get("objective_weights", {})
        bounds = reg.get("weight_bounds", [0.5, 5.0])

        return cls(
            strategy=strategy,
            train_months=wf.get("train_months", wf.get("train_quarters", 4) * 3),
            validation_months=wf.get("validation_months", wf.get("validation_quarters", 2) * 3),
            min_trades=wf.get("min_trades", 100),
            l2_lambda=reg.get("l2_lambda", 0.01),
            max_weight_change=reg.get("max_weight_change", 0.30),
            weight_bounds=(bounds[0], bounds[1]),
            objective_weights=obj,
        )


@dataclass
class StrategyTrainingResult:
    """Result of strategy-specific weight training."""
    strategy: str
    weights: Dict[str, float]
    metrics: Dict[str, float]
    n_trades: int
    n_train: int
    n_validation: int
    converged: bool
    regime_results: Optional[Dict[str, Dict[str, float]]] = None


# =============================================================================
# Objective Functions
# =============================================================================


def _score_weighted_objective(
    trades: np.ndarray,
    weights: np.ndarray,
    component_names: List[str],
    objective_weights: Dict[str, float],
    wr_key: str = "win_rate",
    pnl_key: str = "avg_profit",
    loss_penalty_key: Optional[str] = None,
) -> float:
    """
    Core objective: uses score-weighted evaluation where higher-scored trades
    contribute more to the objective. This gives the optimizer a gradient to follow.

    The score for each trade = X @ weights. We use a softmax-like weighting where
    higher-scored trades have more influence on the objective value. This means
    changing weights changes which trades are "emphasized", creating a proper gradient.
    """
    n_comp = len(component_names)
    scores = trades[:, :n_comp] @ weights
    outcomes = trades[:, -1]  # was_profitable
    pnl = trades[:, -2]       # pnl_pct

    if len(scores) == 0:
        return -999.0

    # Score-weighted evaluation: sigmoid-transform scores to [0, 1] importance
    # Higher-scored trades get more weight in the objective
    score_mean = scores.mean()
    score_std = scores.std() + 1e-8
    z_scores = (scores - score_mean) / score_std
    # Sigmoid-like soft selection: top-half trades get weight ~1, bottom ~0
    importance = 1.0 / (1.0 + np.exp(-2.0 * z_scores))
    importance = importance / (importance.sum() + 1e-8)

    # Weighted win rate
    weighted_wr = np.sum(importance * outcomes)

    # Weighted PnL
    weighted_pnl = np.sum(importance * pnl) / 100.0

    # Rank correlation: do high scores predict good outcomes?
    # Simple: correlation between scores and outcomes
    if scores.std() > 1e-8 and outcomes.std() > 1e-8:
        corr = np.corrcoef(scores, outcomes)[0, 1]
        if np.isnan(corr):
            corr = 0.0
    else:
        corr = 0.0

    # Rank correlation with PnL
    if scores.std() > 1e-8 and pnl.std() > 1e-8:
        pnl_corr = np.corrcoef(scores, pnl)[0, 1]
        if np.isnan(pnl_corr):
            pnl_corr = 0.0
    else:
        pnl_corr = 0.0

    obj = (
        objective_weights.get(wr_key, 0.30) * weighted_wr
        + objective_weights.get(pnl_key, 0.25) * weighted_pnl
        + objective_weights.get("score_outcome_corr", 0.25) * corr
        + objective_weights.get("score_pnl_corr", 0.20) * pnl_corr
    )

    # Optional loss penalty (for breakout strategy)
    if loss_penalty_key:
        loss_mask = outcomes < 0.5
        if loss_mask.sum() > 0:
            worst_losses = pnl[loss_mask]
            # Penalty = average of worst 10% of losses
            n_worst = max(1, int(loss_mask.sum() * 0.1))
            sorted_losses = np.sort(worst_losses)[:n_worst]
            tail_loss = sorted_losses.mean() / 100.0
            obj += objective_weights.get(loss_penalty_key, -0.15) * abs(tail_loss)

    return obj


def objective_pullback(
    trades: np.ndarray,
    weights: np.ndarray,
    component_names: List[str],
    objective_weights: Dict[str, float],
) -> float:
    """Pullback: trend-following → balanced win-rate and score-outcome correlation."""
    defaults = {"win_rate": 0.30, "avg_profit": 0.20, "score_outcome_corr": 0.30, "score_pnl_corr": 0.20}
    merged = {**defaults, **objective_weights}
    return _score_weighted_objective(trades, weights, component_names, merged)


def objective_bounce(
    trades: np.ndarray,
    weights: np.ndarray,
    component_names: List[str],
    objective_weights: Dict[str, float],
) -> float:
    """Bounce: mean-reversion → strong support-level reward."""
    defaults = {"win_rate": 0.25, "avg_profit": 0.20, "score_outcome_corr": 0.30, "score_pnl_corr": 0.25}
    merged = {**defaults, **objective_weights}
    return _score_weighted_objective(trades, weights, component_names, merged)


def objective_breakout(
    trades: np.ndarray,
    weights: np.ndarray,
    component_names: List[str],
    objective_weights: Dict[str, float],
) -> float:
    """ATH Breakout: momentum → harshest tail-loss penalty."""
    defaults = {"win_rate": 0.25, "avg_profit": 0.15, "score_outcome_corr": 0.25, "score_pnl_corr": 0.20, "tail_loss": -0.15}
    merged = {**defaults, **objective_weights}
    return _score_weighted_objective(
        trades, weights, component_names, merged, loss_penalty_key="tail_loss"
    )


def objective_dip(
    trades: np.ndarray,
    weights: np.ndarray,
    component_names: List[str],
    objective_weights: Dict[str, float],
) -> float:
    """Earnings Dip: contrarian → higher profit focus."""
    defaults = {"win_rate": 0.20, "avg_profit": 0.30, "score_outcome_corr": 0.25, "score_pnl_corr": 0.25}
    merged = {**defaults, **objective_weights}
    return _score_weighted_objective(trades, weights, component_names, merged)


STRATEGY_OBJECTIVES = {
    "pullback": objective_pullback,
    "bounce": objective_bounce,
    "ath_breakout": objective_breakout,
    "earnings_dip": objective_dip,
}


# =============================================================================
# Trainer
# =============================================================================


class StrategyWeightTrainer:
    """
    Trains weights for a single strategy using v3 config.

    Loads strategy-specific training parameters from scoring_weights.yaml
    and uses the corresponding objective function and regularization.
    """

    def __init__(self, strategy: str, config: Optional[StrategyTrainingConfig] = None) -> None:
        self.strategy = strategy
        self.config = config or StrategyTrainingConfig.from_yaml(strategy)
        self.components = STRATEGY_COMPONENTS.get(strategy, [])
        self.objective_fn = STRATEGY_OBJECTIVES.get(strategy, objective_pullback)

    def train(
        self,
        trades_df: Any,
        regime: Optional[str] = None,
    ) -> StrategyTrainingResult:
        """
        Train weights for this strategy.

        Args:
            trades_df: DataFrame with trade outcomes and score columns.
                       Must have columns matching self.components + 'pnl_pct' + 'was_profitable'.
            regime: Optional VIX regime filter. If None, trains on all regimes.

        Returns:
            StrategyTrainingResult with optimized weights.
        """
        if not HAS_SCIPY:
            logger.warning("scipy not available, returning default weights")
            return self._default_result(0)

        # Filter by strategy (highest strategy score)
        df = self._filter_strategy_trades(trades_df)

        # Optional regime filter
        if regime:
            df = df[df["vix_regime"] == regime] if "vix_regime" in df.columns else df

        n_trades = len(df)
        if n_trades < self.config.min_trades:
            logger.warning(
                f"{self.strategy}: Only {n_trades} trades (min={self.config.min_trades}). "
                f"Using default weights."
            )
            return self._default_result(n_trades)

        # Build feature matrix (filters to available, non-constant features)
        X, y, pnl, active_components = self._build_matrices(df)
        if X is None:
            return self._default_result(n_trades)

        # Train/validation split (time-based)
        split_idx = int(len(X) * 0.7)
        X_train, y_train, pnl_train = X[:split_idx], y[:split_idx], pnl[:split_idx]
        X_val, y_val, pnl_val = X[split_idx:], y[split_idx:], pnl[split_idx:]

        # Optimize using only active (non-constant) components
        initial_weights = self._get_initial_weights(active_components)

        def neg_objective(w) -> float:
            trades_matrix = np.column_stack([X_train, pnl_train, y_train])
            obj = self.objective_fn(
                trades_matrix, w, active_components, self.config.objective_weights
            )
            # L2 regularization toward initial weights (not toward zero)
            l2_penalty = self.config.l2_lambda * np.sum((w - initial_weights) ** 2)
            return -(obj - l2_penalty)

        bounds = [self.config.weight_bounds] * len(active_components)

        result = minimize(
            neg_objective,
            initial_weights,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500, "ftol": 1e-10},
        )

        # Enforce max weight change
        optimized = self._clamp_weight_change(initial_weights, result.x)

        # Build full weights dict: trained for active, default for inactive
        weights_dict = self._full_weights_dict(active_components, optimized)

        # Evaluate on validation set
        val_matrix = np.column_stack([X_val, pnl_val, y_val])
        val_score = self.objective_fn(
            val_matrix, optimized, active_components, self.config.objective_weights
        )
        val_win_rate = y_val.mean() if len(y_val) > 0 else 0

        return StrategyTrainingResult(
            strategy=self.strategy,
            weights=weights_dict,
            metrics={
                "objective_value": -result.fun,
                "val_objective": val_score,
                "val_win_rate": float(val_win_rate),
                "l2_lambda": self.config.l2_lambda,
                "active_components": len(active_components),
                "total_components": len(self.components),
            },
            n_trades=n_trades,
            n_train=len(X_train),
            n_validation=len(X_val),
            converged=result.success,
        )

    def _filter_strategy_trades(self, df: Any) -> Any:
        """Filter trades where this strategy has the highest score."""
        strategy_score_col = f"{self.strategy}_score"
        other_cols = [
            f"{s}_score" for s in ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]
            if s != self.strategy
        ]

        # Only keep rows where this strategy's score is highest
        existing_cols = [c for c in other_cols if c in df.columns]
        if strategy_score_col not in df.columns:
            return df

        mask = df[strategy_score_col].notna() & (df[strategy_score_col] > 0)
        for col in existing_cols:
            if col in df.columns:
                mask = mask & (df[strategy_score_col] >= df[col].fillna(0))

        return df[mask].copy()

    def _build_matrices(
        self, df: Any
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray], Optional[List[str]]]:
        """Build feature matrix X, outcome y, pnl arrays, and active component list.

        Filters out:
        - Components not present as columns in df
        - Zero-variance (constant) features that can't contribute to optimization
        """
        available = [c for c in self.components if c in df.columns]
        if len(available) < 3:
            logger.warning(f"{self.strategy}: Only {len(available)} components available")
            return None, None, None, None

        X_full = df[available].fillna(0).values.astype(np.float64)

        # Filter out constant (zero-variance) features
        active = []
        active_indices = []
        for i, comp in enumerate(available):
            col_std = X_full[:, i].std()
            if col_std > 1e-6:
                active.append(comp)
                active_indices.append(i)
            else:
                logger.debug(f"{self.strategy}: Skipping constant feature '{comp}' (std={col_std:.6f})")

        if len(active) < 2:
            logger.warning(f"{self.strategy}: Only {len(active)} non-constant components")
            return None, None, None, None

        X = X_full[:, active_indices]
        y = df["was_profitable"].values.astype(np.float64) if "was_profitable" in df.columns else np.ones(len(df))
        pnl = df["pnl_pct"].values.astype(np.float64) if "pnl_pct" in df.columns else np.zeros(len(df))

        return X, y, pnl, active

    def _get_initial_weights(self, active_components: Optional[List[str]] = None) -> np.ndarray:
        """Get initial weights from current config for active components."""
        resolver = get_scoring_resolver()
        resolved = resolver.resolve(self.strategy, "normal")

        components = active_components or self.components
        weights = []
        for comp in components:
            config_key = comp.replace("_score", "")
            w = resolved.weights.get(config_key, 1.0)
            weights.append(w)

        return np.array(weights, dtype=np.float64)

    def _full_weights_dict(
        self, active_components: List[str], trained_weights: np.ndarray
    ) -> Dict[str, float]:
        """Build full weights dict: trained for active, default for inactive."""
        resolver = get_scoring_resolver()
        resolved = resolver.resolve(self.strategy, "normal")

        weights = {}
        trained_map = dict(zip(active_components, trained_weights))
        for comp in self.components:
            if comp in trained_map:
                weights[comp] = float(trained_map[comp])
            else:
                config_key = comp.replace("_score", "")
                weights[comp] = resolved.weights.get(config_key, 1.0)
        return weights

    def _clamp_weight_change(
        self, initial: np.ndarray, optimized: np.ndarray
    ) -> np.ndarray:
        """Enforce max_weight_change constraint."""
        max_change = self.config.max_weight_change
        clamped = np.copy(optimized)

        for i in range(len(clamped)):
            if initial[i] > 0:
                max_val = initial[i] * (1 + max_change)
                min_val = initial[i] * (1 - max_change)
                clamped[i] = np.clip(clamped[i], min_val, max_val)

        return clamped

    def _default_result(self, n_trades: int) -> StrategyTrainingResult:
        """Return default weights when training isn't possible."""
        resolver = get_scoring_resolver()
        resolved = resolver.resolve(self.strategy, "normal")

        weights = {}
        for comp in self.components:
            config_key = comp.replace("_score", "")
            weights[comp] = resolved.weights.get(config_key, 1.0)

        return StrategyTrainingResult(
            strategy=self.strategy,
            weights=weights,
            metrics={"reason": "insufficient_data"},
            n_trades=n_trades,
            n_train=0,
            n_validation=0,
            converged=False,
        )
