#!/usr/bin/env python3
"""
Walk-Forward Epoch Runner

Extracted from walk_forward.py for modularity.
Contains: _train_epoch, _create_skipped_epoch, _extract_metrics,
          _calculate_overfit_score
"""

import logging
from datetime import date
from typing import Dict, List, Optional

from ..core import BacktestConfig, BacktestEngine, BacktestResult
from ..validation import SignalValidator

logger = logging.getLogger(__name__)


class WFEpochRunnerMixin:
    """
    Mixin providing single-epoch training logic for WalkForwardTrainer.

    Requires the host class to have:
    - self.config (TrainingConfig)
    """

    def _train_epoch(
        self,
        epoch_id: int,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        symbols: List[str],
        historical_data: Dict[str, List[Dict]],
        vix_data: List[Dict],
    ):
        """
        Trainiert eine einzelne Epoche.

        1. Backtest auf Training-Daten
        2. Signal-Validierung
        3. Backtest auf Test-Daten
        4. Vergleiche In-Sample vs Out-of-Sample
        """
        from .walk_forward import EpochResult

        # Erstelle Backtest-Config für Training
        train_config = BacktestConfig(
            start_date=train_start,
            end_date=train_end,
            min_pullback_score=self.config.min_pullback_score,
            profit_target_pct=self.config.profit_target_pct,
            stop_loss_pct=self.config.stop_loss_pct,
            dte_min=self.config.dte_min,
            dte_max=self.config.dte_max,
        )

        # 1. Training-Backtest
        train_engine = BacktestEngine(train_config)
        train_result = train_engine.run_sync(
            symbols=symbols,
            historical_data=historical_data,
            vix_data=vix_data,
        )

        # Prüfe Mindest-Trades
        if train_result.total_trades < self.config.min_trades_per_epoch:
            return self._create_skipped_epoch(
                epoch_id=epoch_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                reason=f"Nur {train_result.total_trades} Training-Trades "
                f"(min: {self.config.min_trades_per_epoch})",
            )

        # 2. Signal-Validierung
        validator = SignalValidator()
        validation_result = validator.validate(
            train_result,
            include_regime_analysis=self.config.include_regime_analysis,
        )

        optimal_threshold = validation_result.optimal_threshold

        # 3. Test-Backtest (mit optimiertem Threshold)
        test_config = BacktestConfig(
            start_date=test_start,
            end_date=test_end,
            min_pullback_score=optimal_threshold,
            profit_target_pct=self.config.profit_target_pct,
            stop_loss_pct=self.config.stop_loss_pct,
            dte_min=self.config.dte_min,
            dte_max=self.config.dte_max,
        )

        test_engine = BacktestEngine(test_config)
        test_result = test_engine.run_sync(
            symbols=symbols,
            historical_data=historical_data,
            vix_data=vix_data,
        )

        # Prüfe Test-Trades
        if test_result.total_trades < 10:
            return self._create_skipped_epoch(
                epoch_id=epoch_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                reason=f"Nur {test_result.total_trades} Test-Trades (min: 10)",
            )

        # 4. Metriken extrahieren
        in_sample = self._extract_metrics(train_result)
        out_sample = self._extract_metrics(test_result)

        # 5. Overfitting berechnen
        win_rate_degradation = in_sample["win_rate"] - out_sample["win_rate"]
        sharpe_degradation = in_sample["sharpe"] - out_sample["sharpe"]
        overfit_score = self._calculate_overfit_score(
            win_rate_degradation,
            sharpe_degradation,
        )

        return EpochResult(
            epoch_id=epoch_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            in_sample_trades=in_sample["trades"],
            in_sample_win_rate=in_sample["win_rate"],
            in_sample_sharpe=in_sample["sharpe"],
            in_sample_profit_factor=in_sample["profit_factor"],
            in_sample_avg_pnl=in_sample["avg_pnl"],
            out_sample_trades=out_sample["trades"],
            out_sample_win_rate=out_sample["win_rate"],
            out_sample_sharpe=out_sample["sharpe"],
            out_sample_profit_factor=out_sample["profit_factor"],
            out_sample_avg_pnl=out_sample["avg_pnl"],
            win_rate_degradation=win_rate_degradation,
            sharpe_degradation=sharpe_degradation,
            overfit_score=overfit_score,
            optimal_threshold=optimal_threshold,
            validation_result=validation_result,
            is_valid=True,
        )

    def _create_skipped_epoch(
        self,
        epoch_id: int,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        reason: str,
    ):
        """Erstellt eine übersprungene Epoche"""
        from .walk_forward import EpochResult

        return EpochResult(
            epoch_id=epoch_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            in_sample_trades=0,
            in_sample_win_rate=0,
            in_sample_sharpe=0,
            in_sample_profit_factor=0,
            in_sample_avg_pnl=0,
            out_sample_trades=0,
            out_sample_win_rate=0,
            out_sample_sharpe=0,
            out_sample_profit_factor=0,
            out_sample_avg_pnl=0,
            win_rate_degradation=0,
            sharpe_degradation=0,
            overfit_score=0,
            optimal_threshold=self.config.min_pullback_score,
            is_valid=False,
            skip_reason=reason,
        )

    def _extract_metrics(self, backtest_result: BacktestResult) -> Dict[str, float]:
        """Extrahiert relevante Metriken aus BacktestResult"""
        trades = backtest_result.trades

        if not trades:
            return {
                "trades": 0,
                "win_rate": 0,
                "sharpe": 0,
                "profit_factor": 0,
                "avg_pnl": 0,
            }

        return {
            "trades": backtest_result.total_trades,
            "win_rate": backtest_result.win_rate,
            "sharpe": backtest_result.sharpe_ratio,
            "profit_factor": backtest_result.profit_factor,
            "avg_pnl": (
                backtest_result.total_pnl / backtest_result.total_trades
                if backtest_result.total_trades > 0
                else 0
            ),
        }

    def _calculate_overfit_score(
        self,
        win_rate_degradation: float,
        sharpe_degradation: float,
    ) -> float:
        """
        Berechnet Overfit-Score (0-1).

        Kombiniert Win-Rate und Sharpe Degradation.
        """
        # Normalisiere Degradationen
        wr_factor = min(abs(win_rate_degradation) / 20.0, 1.0)  # 20% = max
        sharpe_factor = min(abs(sharpe_degradation) / 1.0, 1.0)  # 1.0 = max

        # Gewichteter Durchschnitt (Win Rate wichtiger)
        return 0.7 * wr_factor + 0.3 * sharpe_factor
