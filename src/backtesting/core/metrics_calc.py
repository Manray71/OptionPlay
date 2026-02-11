#!/usr/bin/env python3
"""
Metrics and IV Estimation Logic for BacktestEngine

Extracted from engine.py for modularity.
Contains: _estimate_iv_from_hv, _get_price_on_date, _get_vix_on_date,
          _get_iv_on_date, _get_trading_days
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class MetricsCalcMixin:
    """
    Mixin providing metrics calculation and data access for BacktestEngine.

    Requires the host class to have:
    - self.config (BacktestConfig)
    - self._historical_data
    - self._vix_data
    - self._iv_data
    """

    def _get_trading_days(self) -> List[date]:
        """Generiert Liste aller Trading-Tage im Zeitraum"""
        days = []
        current = self.config.start_date
        while current <= self.config.end_date:
            # Einfache Wochentag-Prüfung (Mo-Fr)
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days

    def _get_price_on_date(self, symbol: str, target_date: date) -> Optional[Dict]:
        """Holt Preis-Daten für ein Datum"""
        if symbol not in self._historical_data:
            return None

        for bar in self._historical_data[symbol]:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date == target_date:
                return bar
        return None

    def _get_vix_on_date(self, target_date: date) -> Optional[float]:
        """Holt VIX für ein Datum"""
        for bar in self._vix_data:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date == target_date:
                return bar.get("close")
        return None

    def _get_iv_on_date(self, symbol: str, target_date: date) -> Optional[float]:
        """Holt IV für ein Symbol an einem Datum"""
        if symbol not in self._iv_data:
            return None

        for bar in self._iv_data[symbol]:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date == target_date:
                return bar.get("iv")
        return None

    def _estimate_iv_from_hv(self, symbol: str, target_date: date) -> float:
        """
        Schätzt IV aus historischer Volatilität.

        Verwendet NumPy-optimierte 20-Tage HV mit VIX-Anpassung.
        """
        from ...pricing import batch_estimate_iv, batch_historical_volatility

        if symbol not in self._historical_data:
            return self.config.default_iv

        # Hole letzte 20+ Tage vor target_date
        history = []
        for bar in self._historical_data[symbol]:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date < target_date:
                history.append(bar)

        if len(history) < 20:
            return self.config.default_iv

        # Sortiere und nimm letzte 21 Tage (für 20 Returns)
        history = sorted(history, key=lambda x: x.get("date", ""), reverse=True)[:21]
        closes = np.array([bar.get("close", 0) for bar in history if bar.get("close", 0) > 0])

        if len(closes) < 2:
            return self.config.default_iv

        # NumPy-optimierte HV-Berechnung
        hv = float(batch_historical_volatility(closes, window=min(20, len(closes) - 1)))

        # VIX-basierte Anpassung mit batch_estimate_iv
        vix = self._get_vix_on_date(target_date)
        if vix is not None:
            iv = float(batch_estimate_iv(np.array([hv]), np.array([vix]))[0])
        else:
            iv = hv * 1.1  # Default IV premium ohne VIX

        # Bounds (10% - 80%)
        return float(np.clip(iv, 0.10, 0.80))
