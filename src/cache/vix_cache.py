# OptionPlay - VIX Cache Manager
# ================================
"""
VIX data cache with DB fallback.

Responsibilities:
- Live VIX from memory cache (short TTL)
- Historical VIX values from DB
- Fallback to last known value

Usage:
    from src.cache import get_vix_manager

    manager = get_vix_manager()

    # Latest VIX from DB
    vix = manager.get_latest_vix()

    # VIX for specific date
    vix = manager.get_vix_at_date(date(2026, 1, 30))

    # Check range
    start, end = manager.get_vix_range()

Author: OptionPlay Team
Created: 2026-02-01
"""

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path.home() / ".optionplay" / "trades.db"


@dataclass
class VixDataPoint:
    """A VIX data point."""
    date: date
    value: float


class VixCacheManager:
    """
    VIX Cache Manager with DB fallback.

    Provides:
    - Latest VIX from database
    - VIX for specific dates
    - VIX range and statistics
    - Gap detection

    Note: Live VIX caching is handled by VIXService.
    This manager provides DB-based historical data.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize VIX Cache Manager.

        Args:
            db_path: Path to trades.db (default: ~/.optionplay/trades.db)
        """
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()

    def _ensure_db_exists(self) -> bool:
        """Check if database exists. Thread-safe."""
        with self._lock:
            if not self.db_path.exists():
                logger.warning(f"VIX database not found: {self.db_path}")
                return False
            return True

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_latest_vix(self) -> Optional[float]:
        """
        Get most recent VIX value from database.

        Returns:
            Latest VIX value or None
        """
        if not self._ensure_db_exists():
            return None

        try:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT value FROM vix_data
                ORDER BY date DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                return float(row['value'])
            return None

        except sqlite3.Error as e:
            logger.error(f"Error fetching latest VIX: {e}")
            return None

    def get_vix_at_date(self, target_date: date) -> Optional[float]:
        """
        Get VIX value for specific date.

        If no value for exact date, returns closest previous value.

        Args:
            target_date: Date to get VIX for

        Returns:
            VIX value or None
        """
        if not self._ensure_db_exists():
            return None

        try:
            conn = self._get_connection()

            # Try exact match first
            cursor = conn.execute(
                "SELECT value FROM vix_data WHERE date = ?",
                (target_date.isoformat(),)
            )
            row = cursor.fetchone()

            if row:
                conn.close()
                return float(row['value'])

            # Fallback: closest previous date
            cursor = conn.execute("""
                SELECT value FROM vix_data
                WHERE date < ?
                ORDER BY date DESC
                LIMIT 1
            """, (target_date.isoformat(),))
            row = cursor.fetchone()
            conn.close()

            if row:
                return float(row['value'])
            return None

        except sqlite3.Error as e:
            logger.error(f"Error fetching VIX for {target_date}: {e}")
            return None

    def get_vix_range(self) -> Optional[Tuple[date, date]]:
        """
        Get date range of stored VIX data.

        Returns:
            Tuple of (first_date, last_date) or None
        """
        if not self._ensure_db_exists():
            return None

        try:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT MIN(date) as first_date, MAX(date) as last_date
                FROM vix_data
            """)
            row = cursor.fetchone()
            conn.close()

            if row['first_date'] and row['last_date']:
                return (
                    date.fromisoformat(row['first_date']),
                    date.fromisoformat(row['last_date'])
                )
            return None

        except sqlite3.Error as e:
            logger.error(f"Error fetching VIX range: {e}")
            return None

    def get_vix_count(self) -> int:
        """Get total count of VIX records."""
        if not self._ensure_db_exists():
            return 0

        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT COUNT(*) FROM vix_data")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except sqlite3.Error:
            return 0

    def get_vix_history(self, days: int = 10) -> List[float]:
        """
        Get VIX history for the last N days.

        Args:
            days: Number of days to fetch

        Returns:
            List of VIX values (oldest first)
        """
        if not self._ensure_db_exists():
            return []

        try:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT value FROM vix_data
                ORDER BY date DESC
                LIMIT ?
            """, (days,))
            values = [row['value'] for row in cursor.fetchall()]
            conn.close()

            return list(reversed(values))  # Oldest first

        except sqlite3.Error as e:
            logger.error(f"Error fetching VIX history: {e}")
            return []

    def get_vix_statistics(self, days: int = 252) -> Optional[Dict]:
        """
        Get VIX statistics for the last N trading days.

        Args:
            days: Number of days for statistics

        Returns:
            Dict with min, max, mean, current, percentile
        """
        if not self._ensure_db_exists():
            return None

        try:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT value FROM vix_data
                ORDER BY date DESC
                LIMIT ?
            """, (days,))
            values = [row['value'] for row in cursor.fetchall()]
            conn.close()

            if not values:
                return None

            import statistics

            current = values[0]
            sorted_values = sorted(values)
            percentile = (sorted_values.index(min(sorted_values, key=lambda x: abs(x - current))) + 1) / len(sorted_values) * 100

            return {
                'current': current,
                'min': min(values),
                'max': max(values),
                'mean': statistics.mean(values),
                'median': statistics.median(values),
                'stdev': statistics.stdev(values) if len(values) > 1 else 0,
                'percentile': round(percentile, 1),
                'days_analyzed': len(values)
            }

        except (sqlite3.Error, statistics.StatisticsError) as e:
            logger.error(f"Error calculating VIX statistics: {e}")
            return None

    def find_gaps(self, days_back: int = 30) -> List[date]:
        """
        Find missing trading days in VIX data.

        Args:
            days_back: Number of days to check

        Returns:
            List of dates with missing VIX data
        """
        if not self._ensure_db_exists():
            return []

        try:
            conn = self._get_connection()
            start = (date.today() - timedelta(days=days_back)).isoformat()
            cursor = conn.execute(
                "SELECT date FROM vix_data WHERE date >= ? ORDER BY date",
                (start,)
            )
            existing = {date.fromisoformat(row['date']) for row in cursor.fetchall()}
            conn.close()

            # Generate expected trading days (Mon-Fri)
            gaps = []
            current = date.today() - timedelta(days=days_back)
            end = date.today() - timedelta(days=1)  # Yesterday

            while current <= end:
                if current.weekday() < 5:  # Mon-Fri
                    if current not in existing:
                        gaps.append(current)
                current += timedelta(days=1)

            return gaps

        except sqlite3.Error as e:
            logger.error(f"Error finding VIX gaps: {e}")
            return []

    def is_data_stale(self, max_age_days: int = 2) -> bool:
        """
        Check if VIX data is stale.

        Args:
            max_age_days: Maximum acceptable age in days

        Returns:
            True if data is older than max_age_days
        """
        vix_range = self.get_vix_range()
        if not vix_range:
            return True

        _, last_date = vix_range
        age = (date.today() - last_date).days
        return age > max_age_days


# Singleton instance
_vix_manager: Optional[VixCacheManager] = None
_vix_manager_lock = threading.Lock()


def get_vix_manager() -> VixCacheManager:
    """Get singleton VIX Cache Manager instance. Thread-safe."""
    global _vix_manager
    with _vix_manager_lock:
        if _vix_manager is None:
            _vix_manager = VixCacheManager()
        return _vix_manager


def reset_vix_manager():
    """Reset VIX Cache Manager (for testing)."""
    global _vix_manager
    with _vix_manager_lock:
        _vix_manager = None
