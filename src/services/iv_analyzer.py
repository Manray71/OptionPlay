# OptionPlay - IV Analyzer Service
# ==================================
"""
IV Analyzer — berechnet IV Rank und IV Percentile für Entry-Bewertung.

Wrapper um die bestehende IV-Infrastruktur (iv_cache_impl.py) mit
zusätzlichem DB-Fallback für historische IV-Daten.

Datenquellen-Priorität:
  1. IVCache (JSON-basiert, iv_cache.json) — schnell, wenn frisch
  2. Lokale DB (options_greeks) — 252 Tage historisch, ATM-Puts
  3. symbol_fundamentals.iv_rank_252d — Pre-computed, als Fallback

Verwendung:
    from src.services.iv_analyzer import IVAnalyzer, get_iv_analyzer

    analyzer = get_iv_analyzer()
    metrics = await analyzer.get_iv_metrics("AAPL")
    # metrics.iv_rank, metrics.iv_percentile, metrics.current_iv

Author: OptionPlay Team
Created: 2026-02-04
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    from ..cache.iv_cache_impl import (
        IVCache,
        IVData,
        IVFetcher,
        IVSource,
        calculate_iv_rank,
        calculate_iv_percentile,
        get_iv_cache,
        get_iv_fetcher,
    )
    from ..cache.symbol_fundamentals import get_fundamentals_manager
except ImportError:
    from cache.iv_cache_impl import (  # type: ignore[no-redef]  # fallback for non-package execution
        IVCache,
        IVData,
        IVFetcher,
        IVSource,
        calculate_iv_rank,
        calculate_iv_percentile,
        get_iv_cache,
        get_iv_fetcher,
    )
    from cache.symbol_fundamentals import get_fundamentals_manager  # type: ignore[no-redef]  # fallback for non-package execution

logger = logging.getLogger(__name__)

# DB-Pfad
DEFAULT_DB_PATH = Path.home() / ".optionplay" / "trades.db"

# =============================================================================
# CONSTANTS — extracted from inline magic numbers
# =============================================================================

# IV status thresholds (used in iv_status property)
IV_RANK_VERY_HIGH = 70
IV_RANK_ELEVATED = 50
IV_RANK_NORMAL = 30

# Minimum data points for cache validity
IV_CACHE_MIN_POINTS = 20

# ATM put selection criteria for DB query
IV_ATM_DELTA_MIN = -0.55
IV_ATM_DELTA_MAX = -0.45
IV_ATM_DTE_MIN = 25
IV_ATM_DTE_MAX = 35

# Lookback period for historical IV
IV_LOOKBACK_DAYS = 365

# Minimum data points for DB-based IV calculation
IV_DB_MIN_POINTS = 30


@dataclass
class IVMetrics:
    """IV-Metriken für ein Symbol — für EQS und Output."""
    symbol: str
    iv_rank: Optional[float]         # 0-100
    iv_percentile: Optional[float]   # 0-100
    current_iv: Optional[float]      # Dezimal (z.B. 0.35)
    current_iv_pct: Optional[float]  # Prozent (z.B. 35.0)
    iv_high_52w: Optional[float]     # Dezimal
    iv_low_52w: Optional[float]      # Dezimal
    data_points: int                 # Anzahl historischer Datenpunkte
    source: str                      # "cache", "db", "fundamentals"

    @property
    def is_elevated(self) -> bool:
        """IV Rank > 50% → IV ist erhöht."""
        return self.iv_rank is not None and self.iv_rank >= 50.0

    @property
    def iv_status(self) -> str:
        """Gibt IV-Status als String zurück."""
        if self.iv_rank is None:
            return "unknown"
        if self.iv_rank >= IV_RANK_VERY_HIGH:
            return "very_high"
        elif self.iv_rank >= IV_RANK_ELEVATED:
            return "elevated"
        elif self.iv_rank >= IV_RANK_NORMAL:
            return "normal"
        else:
            return "low"


class IVAnalyzer:
    """
    Analysiert IV-Daten für Entry-Bewertung.

    Kombiniert drei Quellen:
    1. IVCache (schnell, wenn frisch)
    2. Lokale DB (historisch, robust)
    3. symbol_fundamentals (Pre-computed, Fallback)
    """

    def __init__(
        self,
        iv_fetcher: Optional[IVFetcher] = None,
        db_path: Optional[Path] = None,
    ) -> None:
        """
        Args:
            iv_fetcher: Optional IVFetcher-Instanz (Default: globale Instanz)
            db_path: Pfad zur trades.db (Default: ~/.optionplay/trades.db)
        """
        self._fetcher = iv_fetcher
        self._db_path = db_path or DEFAULT_DB_PATH
        self._fundamentals: Any = None

    @property
    def fetcher(self) -> IVFetcher:
        """Lazy-load IVFetcher."""
        if self._fetcher is None:
            self._fetcher = get_iv_fetcher()
        return self._fetcher

    @property
    def fundamentals(self) -> Any:
        """Lazy-load Fundamentals Manager."""
        if self._fundamentals is None:
            try:
                self._fundamentals = get_fundamentals_manager()
            except Exception as e:
                logger.debug(f"Fundamentals manager not available: {e}")
        return self._fundamentals

    async def get_iv_metrics(
        self,
        symbol: str,
        current_iv: Optional[float] = None,
    ) -> IVMetrics:
        """
        Berechnet IV Rank und IV Percentile für ein Symbol.

        Versucht Quellen in dieser Reihenfolge:
        1. IVCache (wenn frisch und > 20 Datenpunkte)
        2. Lokale DB (options_greeks, 252 Tage ATM-Puts)
        3. symbol_fundamentals (Pre-computed IV Rank)

        Args:
            symbol: Ticker-Symbol
            current_iv: Aktuelle IV (dezimal). Wenn None, wird aus Quelle bestimmt.

        Returns:
            IVMetrics mit IV Rank und IV Percentile
        """
        symbol = symbol.upper()

        # 1. Versuch: IVCache
        metrics = self._try_iv_cache(symbol, current_iv)
        if metrics and metrics.iv_rank is not None:
            return metrics

        # 2. Versuch: Lokale DB
        metrics = await self._try_local_db(symbol)
        if metrics and metrics.iv_rank is not None:
            return metrics

        # 3. Versuch: symbol_fundamentals (Pre-computed)
        metrics = self._try_fundamentals(symbol, current_iv)
        if metrics and metrics.iv_rank is not None:
            return metrics

        # Fallback: Keine IV-Daten verfügbar
        return IVMetrics(
            symbol=symbol,
            iv_rank=None,
            iv_percentile=None,
            current_iv=current_iv,
            current_iv_pct=round(current_iv * 100, 1) if current_iv else None,
            iv_high_52w=None,
            iv_low_52w=None,
            data_points=0,
            source="none",
        )

    def _try_iv_cache(
        self,
        symbol: str,
        current_iv: Optional[float] = None,
    ) -> Optional[IVMetrics]:
        """Versucht IV-Metriken aus dem IVCache zu holen."""
        try:
            iv_data = self.fetcher.get_iv_rank(symbol, current_iv or 0.0)

            if iv_data and iv_data.iv_rank is not None and iv_data.data_points >= IV_CACHE_MIN_POINTS:
                return IVMetrics(
                    symbol=symbol,
                    iv_rank=round(iv_data.iv_rank, 1),
                    iv_percentile=round(iv_data.iv_percentile, 1) if iv_data.iv_percentile is not None else None,
                    current_iv=iv_data.current_iv,
                    current_iv_pct=round(iv_data.current_iv * 100, 1) if iv_data.current_iv else None,
                    iv_high_52w=iv_data.iv_high_52w,
                    iv_low_52w=iv_data.iv_low_52w,
                    data_points=iv_data.data_points,
                    source="cache",
                )
        except Exception as e:
            logger.debug(f"IVCache lookup failed for {symbol}: {e}")

        return None

    def _query_iv_from_db(self, symbol: str) -> Optional[list[Any]]:
        """Sync DB query for IV data. Runs in thread pool."""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        query = f"""
            SELECT g.iv_calculated, p.quote_date
            FROM options_greeks g
            JOIN options_prices p ON g.options_price_id = p.id
            WHERE p.underlying = ?
              AND p.option_type = 'P'
              AND g.delta BETWEEN {IV_ATM_DELTA_MIN} AND {IV_ATM_DELTA_MAX}
              AND p.dte BETWEEN {IV_ATM_DTE_MIN} AND {IV_ATM_DTE_MAX}
              AND p.quote_date >= date('now', '-{IV_LOOKBACK_DAYS} days')
              AND g.iv_calculated IS NOT NULL
              AND g.iv_calculated > 0
            ORDER BY p.quote_date
        """
        cursor.execute(query, (symbol,))
        rows = cursor.fetchall()
        conn.close()
        return rows

    async def _try_local_db(self, symbol: str) -> Optional[IVMetrics]:
        """
        Berechnet IV-Metriken aus der lokalen DB (options_greeks).

        Verwendet ATM-Puts (Delta ≈ -0.50) der letzten 252 Tage
        mit ~30 DTE für Vergleichbarkeit.
        """
        if not self._db_path.exists():
            return None

        try:
            rows = await asyncio.to_thread(self._query_iv_from_db, symbol)

            if not rows or len(rows) < IV_DB_MIN_POINTS:
                return None

            # Tages-Durchschnitt berechnen (mehrere Strikes pro Tag)
            daily_ivs: dict[str, list[float]] = {}
            for iv, qdate in rows:
                if qdate not in daily_ivs:
                    daily_ivs[qdate] = []
                daily_ivs[qdate].append(iv)

            # Durchschnitt pro Tag
            iv_values = [
                sum(ivs) / len(ivs)
                for ivs in daily_ivs.values()
            ]

            if len(iv_values) < IV_DB_MIN_POINTS:
                return None

            current_iv = iv_values[-1]
            iv_high = max(iv_values)
            iv_low = min(iv_values)

            iv_rank = calculate_iv_rank(current_iv, iv_values)
            iv_percentile = calculate_iv_percentile(current_iv, iv_values)

            return IVMetrics(
                symbol=symbol,
                iv_rank=round(iv_rank, 1) if iv_rank is not None else None,
                iv_percentile=round(iv_percentile, 1) if iv_percentile is not None else None,
                current_iv=round(current_iv, 4),
                current_iv_pct=round(current_iv * 100, 1),
                iv_high_52w=round(iv_high, 4),
                iv_low_52w=round(iv_low, 4),
                data_points=len(iv_values),
                source="db",
            )

        except Exception as e:
            logger.warning(f"DB IV lookup failed for {symbol}: {e}")
            return None

    def _try_fundamentals(
        self,
        symbol: str,
        current_iv: Optional[float] = None,
    ) -> Optional[IVMetrics]:
        """Versucht IV-Metriken aus symbol_fundamentals zu holen."""
        if not self.fundamentals:
            return None

        try:
            f = self.fundamentals.get_fundamentals(symbol)
            if not f:
                return None

            iv_rank = getattr(f, 'iv_rank_252d', None)
            iv_percentile = getattr(f, 'iv_percentile_252d', None)

            if iv_rank is None:
                return None

            return IVMetrics(
                symbol=symbol,
                iv_rank=round(iv_rank, 1),
                iv_percentile=round(iv_percentile, 1) if iv_percentile is not None else None,
                current_iv=current_iv,
                current_iv_pct=round(current_iv * 100, 1) if current_iv else None,
                iv_high_52w=None,
                iv_low_52w=None,
                data_points=0,
                source="fundamentals",
            )

        except Exception as e:
            logger.debug(f"Fundamentals IV lookup failed for {symbol}: {e}")
            return None

    async def get_iv_metrics_many(
        self,
        symbols: list[str],
    ) -> dict[str, IVMetrics]:
        """
        Berechnet IV-Metriken für mehrere Symbole.

        Args:
            symbols: Liste von Ticker-Symbolen

        Returns:
            Dict mit Symbol -> IVMetrics
        """
        results = {}
        for symbol in symbols:
            results[symbol.upper()] = await self.get_iv_metrics(symbol)
        return results


# =============================================================================
# SINGLETON
# =============================================================================

_iv_analyzer: Optional[IVAnalyzer] = None


def get_iv_analyzer(
    iv_fetcher: Optional[IVFetcher] = None,
    db_path: Optional[Path] = None,
) -> IVAnalyzer:
    """Gibt Singleton IVAnalyzer-Instanz zurück."""
    global _iv_analyzer
    if _iv_analyzer is None:
        _iv_analyzer = IVAnalyzer(iv_fetcher=iv_fetcher, db_path=db_path)
    return _iv_analyzer


def reset_iv_analyzer() -> None:
    """Setzt Singleton zurück (für Tests)."""
    global _iv_analyzer
    _iv_analyzer = None
