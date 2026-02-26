#!/usr/bin/env python3
"""
SHAP Analysis for Score Predictivity (DEBT-001)
================================================

Analyzes which score components actually predict trade success.

Uses:
- XGBoost classifier to predict trade outcome
- SHAP values to explain feature importance
- Correlation analysis between scores and win rate

Output:
- Feature importance ranking
- SHAP summary plots
- Recommendations for weight adjustments

Usage:
    python scripts/analyze_score_predictivity.py
    python scripts/analyze_score_predictivity.py --output-dir reports/shap
"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Database path
OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"
FUNDAMENTALS_DB = Path.home() / ".optionplay" / "trades.db"


def load_trade_data() -> pd.DataFrame:
    """Load trade outcomes with component scores."""
    conn = sqlite3.connect(str(OUTCOMES_DB))

    query = """
    SELECT
        symbol,
        entry_date,
        was_profitable,
        pnl_pct,
        vix_at_entry,

        -- Component scores
        rsi_score,
        support_score,
        fibonacci_score,
        ma_score,
        volume_score,
        macd_score,
        stoch_score,
        keltner_score,
        trend_strength_score,
        momentum_score,
        market_context_score,
        vwap_score,
        gap_score,

        -- Strategy scores
        pullback_score,
        bounce_score,
        ath_breakout_score,

        -- Additional context
        rsi_value,
        distance_to_support_pct,
        spy_trend

    FROM trade_outcomes
    WHERE pullback_score IS NOT NULL
      AND pullback_score > 0
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    logger.info(f"Loaded {len(df)} trades with scores")
    return df


def load_stability_scores() -> Dict[str, float]:
    """Load stability scores from fundamentals."""
    conn = sqlite3.connect(str(FUNDAMENTALS_DB))

    try:
        query = "SELECT symbol, stability_score FROM symbol_fundamentals WHERE stability_score IS NOT NULL"
        df = pd.read_sql_query(query, conn)
        stability = dict(zip(df["symbol"], df["stability_score"]))
        logger.info(f"Loaded stability scores for {len(stability)} symbols")
        return stability
    except Exception as e:
        logger.warning(f"Could not load stability scores: {e}")
        return {}
    finally:
        conn.close()


def calculate_correlations(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate correlations between features and trade success."""

    feature_cols = [
        "rsi_score",
        "support_score",
        "fibonacci_score",
        "ma_score",
        "volume_score",
        "macd_score",
        "stoch_score",
        "keltner_score",
        "trend_strength_score",
        "momentum_score",
        "market_context_score",
        "vwap_score",
        "gap_score",
        "pullback_score",
        "bounce_score",
        "ath_breakout_score",
        "vix_at_entry",
        "rsi_value",
        "distance_to_support_pct",
    ]

    # Add stability if available
    if "stability_score" in df.columns:
        feature_cols.append("stability_score")

    correlations = []

    for col in feature_cols:
        if col not in df.columns:
            continue

        # Drop NaN for this feature
        valid = df[[col, "was_profitable", "pnl_pct"]].dropna()

        if len(valid) < 100:
            continue

        # Pearson correlation with win/loss
        corr_win = valid[col].corr(valid["was_profitable"])

        # Pearson correlation with P&L %
        corr_pnl = valid[col].corr(valid["pnl_pct"])

        # Win rate by feature quartiles
        try:
            valid["quartile"] = pd.qcut(valid[col], q=4, labels=False, duplicates="drop")
            wr_by_quartile = valid.groupby("quartile")["was_profitable"].mean()

            # Q4 - Q1 spread (does higher score mean better performance?)
            if len(wr_by_quartile) >= 2:
                q4_q1_spread = wr_by_quartile.iloc[-1] - wr_by_quartile.iloc[0]
            else:
                q4_q1_spread = 0
        except (ValueError, IndexError):
            q4_q1_spread = 0

        correlations.append(
            {
                "feature": col,
                "corr_win": round(corr_win, 4),
                "corr_pnl": round(corr_pnl, 4),
                "q4_q1_spread": round(q4_q1_spread, 4),
                "n_samples": len(valid),
                "mean_value": round(valid[col].mean(), 2),
                "std_value": round(valid[col].std(), 2),
            }
        )

    result = pd.DataFrame(correlations)
    result = result.sort_values("corr_win", ascending=False)

    return result


def train_xgboost_model(df: pd.DataFrame) -> Tuple:
    """Train XGBoost classifier and return SHAP values."""
    try:
        import xgboost as xgb
        import shap
    except (ImportError, Exception) as e:
        logger.warning(f"XGBoost/SHAP not available: {e}")
        logger.info("Continuing with correlation analysis only...")
        return None, None, None

    try:
        feature_cols = [
            "rsi_score",
            "support_score",
            "fibonacci_score",
            "ma_score",
            "volume_score",
            "macd_score",
            "stoch_score",
            "keltner_score",
            "trend_strength_score",
            "momentum_score",
            "market_context_score",
            "vwap_score",
            "gap_score",
            "vix_at_entry",
        ]

        # Add stability if available
        if "stability_score" in df.columns:
            feature_cols.append("stability_score")

        # Filter to available columns
        available_cols = [c for c in feature_cols if c in df.columns]

        # Prepare data
        X = df[available_cols].copy()
        y = df["was_profitable"].copy()

        # Drop rows with NaN
        mask = X.notna().all(axis=1) & y.notna()
        X = X[mask]
        y = y[mask]

        logger.info(f"Training XGBoost on {len(X)} samples with {len(available_cols)} features")

        # Train model
        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
            use_label_encoder=False,
            eval_metric="logloss",
        )

        model.fit(X, y)

        # Calculate SHAP values
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)

        # Feature importance
        importance = pd.DataFrame(
            {
                "feature": available_cols,
                "importance": model.feature_importances_,
                "shap_mean_abs": np.abs(shap_values).mean(axis=0),
            }
        )
        importance = importance.sort_values("shap_mean_abs", ascending=False)

        return model, shap_values, importance

    except Exception as e:
        logger.warning(f"XGBoost training failed: {e}")
        return None, None, None


def generate_weight_recommendations(
    correlations: pd.DataFrame, importance: pd.DataFrame
) -> Dict[str, float]:
    """Generate recommended weights based on analysis."""

    # Merge correlation and importance data
    if importance is not None:
        merged = correlations.merge(
            importance[["feature", "shap_mean_abs"]], on="feature", how="left"
        )
    else:
        merged = correlations.copy()
        merged["shap_mean_abs"] = merged["corr_win"].abs()

    # Calculate combined score
    # Higher = more important for predicting wins
    merged["combined_score"] = (
        merged["corr_win"].fillna(0) * 0.3
        + merged["q4_q1_spread"].fillna(0) * 0.3
        + merged["shap_mean_abs"].fillna(0) / merged["shap_mean_abs"].max() * 0.4
    )

    # Normalize to weights (0.5 to 3.0 range)
    min_weight = 0.5
    max_weight = 3.0

    min_score = merged["combined_score"].min()
    max_score = merged["combined_score"].max()

    if max_score > min_score:
        merged["recommended_weight"] = min_weight + (merged["combined_score"] - min_score) / (
            max_score - min_score
        ) * (max_weight - min_weight)
    else:
        merged["recommended_weight"] = 1.0

    # Round to 2 decimals
    merged["recommended_weight"] = merged["recommended_weight"].round(2)

    # Create weight dict
    weights = dict(zip(merged["feature"], merged["recommended_weight"]))

    return weights, merged


def save_results(
    correlations: pd.DataFrame,
    importance: pd.DataFrame,
    recommendations: pd.DataFrame,
    weights: Dict[str, float],
    output_dir: Path,
):
    """Save analysis results."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save correlations
    corr_file = output_dir / f"correlations_{timestamp}.csv"
    correlations.to_csv(corr_file, index=False)
    logger.info(f"Saved correlations to {corr_file}")

    # Save importance
    if importance is not None:
        imp_file = output_dir / f"feature_importance_{timestamp}.csv"
        importance.to_csv(imp_file, index=False)
        logger.info(f"Saved feature importance to {imp_file}")

    # Save recommendations
    rec_file = output_dir / f"recommendations_{timestamp}.csv"
    recommendations.to_csv(rec_file, index=False)
    logger.info(f"Saved recommendations to {rec_file}")

    # Save weights as YAML
    weights_file = output_dir / f"recommended_weights_{timestamp}.yaml"
    with open(weights_file, "w") as f:
        f.write("# Recommended weights based on SHAP analysis\n")
        f.write(f"# Generated: {datetime.now().isoformat()}\n\n")
        f.write("score_weights:\n")
        for feature, weight in sorted(weights.items(), key=lambda x: -x[1]):
            f.write(f"  {feature}: {weight}\n")
    logger.info(f"Saved weights to {weights_file}")


def print_summary(
    correlations: pd.DataFrame, importance: pd.DataFrame, recommendations: pd.DataFrame
):
    """Print analysis summary."""
    print("\n" + "=" * 70)
    print("SCORE PREDICTIVITY ANALYSIS (DEBT-001)")
    print("=" * 70)

    print("\n### Top Correlations with Trade Success ###\n")
    print(
        correlations[["feature", "corr_win", "corr_pnl", "q4_q1_spread"]]
        .head(10)
        .to_string(index=False)
    )

    if importance is not None:
        print("\n### SHAP Feature Importance ###\n")
        print(
            importance[["feature", "shap_mean_abs", "importance"]].head(10).to_string(index=False)
        )

    print("\n### Recommended Weights ###\n")
    print(
        recommendations[["feature", "corr_win", "shap_mean_abs", "recommended_weight"]]
        .head(15)
        .to_string(index=False)
    )

    # Key insights
    print("\n### Key Insights ###")

    # Best predictors
    top_3 = recommendations.head(3)["feature"].tolist()
    print(f"\n1. Top predictors: {', '.join(top_3)}")

    # Weak predictors
    weak = correlations[correlations["corr_win"].abs() < 0.05]["feature"].tolist()
    if weak:
        print(f"2. Weak predictors (|r| < 0.05): {', '.join(weak[:5])}")

    # Negative correlations (bad signals)
    negative = correlations[correlations["corr_win"] < -0.05]["feature"].tolist()
    if negative:
        print(f"3. Negative correlation (higher score = worse): {', '.join(negative)}")

    # Overall correlation of pullback_score
    pullback_corr = correlations[correlations["feature"] == "pullback_score"]["corr_win"].values
    if len(pullback_corr) > 0:
        print(f"\n4. Overall pullback_score correlation: r = {pullback_corr[0]:.4f}")
        if abs(pullback_corr[0]) < 0.1:
            print("   -> CONFIRMED: Score is not predictive of success!")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Analyze score predictivity with SHAP")
    parser.add_argument(
        "--output-dir", type=str, default="reports/shap", help="Output directory for results"
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    logger.info("=" * 60)
    logger.info("Score Predictivity Analysis (DEBT-001)")
    logger.info("=" * 60)

    # Load data
    df = load_trade_data()

    if len(df) < 100:
        logger.error("Not enough data for analysis. Need at least 100 trades with scores.")
        return

    # Add stability scores
    stability = load_stability_scores()
    if stability:
        df["stability_score"] = df["symbol"].map(stability)
        logger.info(f"Added stability scores for {df['stability_score'].notna().sum()} trades")

    # Calculate correlations
    logger.info("Calculating correlations...")
    correlations = calculate_correlations(df)

    # Train XGBoost and get SHAP values
    logger.info("Training XGBoost model...")
    model, shap_values, importance = train_xgboost_model(df)

    # Generate recommendations
    logger.info("Generating weight recommendations...")
    weights, recommendations = generate_weight_recommendations(correlations, importance)

    # Save results
    save_results(correlations, importance, recommendations, weights, output_dir)

    # Print summary
    print_summary(correlations, importance, recommendations)

    logger.info(f"\nResults saved to {output_dir}/")


if __name__ == "__main__":
    main()
