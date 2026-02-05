# OptionPlay - SQLite Connection Pool
# =====================================
"""
Simple thread-safe connection pool for SQLite.

Eliminates the overhead of creating/closing connections per query.
SQLite connections with check_same_thread=False are safe for reuse
across threads when protected by a lock.

Usage:
    pool = SQLiteConnectionPool("/path/to/db.sqlite", pool_size=5)

    with pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ...")

    pool.close_all()  # On shutdown
"""

import sqlite3
import threading
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SQLiteConnectionPool:
    """Thread-safe SQLite connection pool."""

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = str(db_path)
        self.pool_size = pool_size
        self._available: list = []
        self._lock = threading.Lock()
        self._total_created = 0
        self._total_reused = 0

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read performance
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self._total_created += 1
        return conn

    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool.

        Returns the connection to the pool when done.
        Creates a new connection if pool is empty.
        """
        conn = None
        with self._lock:
            if self._available:
                conn = self._available.pop()
                self._total_reused += 1

        if conn is None:
            conn = self._create_connection()

        try:
            yield conn
        except Exception:
            # On error, don't return potentially corrupted connection
            try:
                conn.close()
            except Exception:
                pass
            raise
        else:
            with self._lock:
                if len(self._available) < self.pool_size:
                    self._available.append(conn)
                else:
                    conn.close()

    def close_all(self):
        """Close all pooled connections."""
        with self._lock:
            for conn in self._available:
                try:
                    conn.close()
                except Exception:
                    pass
            self._available.clear()
            logger.debug(
                f"Connection pool closed. Created: {self._total_created}, "
                f"Reused: {self._total_reused}"
            )

    @property
    def stats(self) -> dict:
        """Pool statistics."""
        with self._lock:
            return {
                "available": len(self._available),
                "pool_size": self.pool_size,
                "total_created": self._total_created,
                "total_reused": self._total_reused,
                "reuse_rate": (
                    self._total_reused / (self._total_created + self._total_reused)
                    if (self._total_created + self._total_reused) > 0
                    else 0.0
                ),
            }


# Singleton pool instances
_pools: dict = {}
_pools_lock = threading.Lock()


def get_connection_pool(
    db_path: str, pool_size: int = 5
) -> SQLiteConnectionPool:
    """Get or create a connection pool for a database path."""
    db_path = str(Path(db_path).resolve())
    with _pools_lock:
        if db_path not in _pools:
            _pools[db_path] = SQLiteConnectionPool(db_path, pool_size)
            logger.debug(f"Created connection pool for {db_path} (size={pool_size})")
        return _pools[db_path]


def close_all_pools():
    """Close all connection pools. Call on shutdown."""
    with _pools_lock:
        for pool in _pools.values():
            pool.close_all()
        _pools.clear()
