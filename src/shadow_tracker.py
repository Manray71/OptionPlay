"""Shadow Trade Tracker — protokolliert und verfolgt Empfehlungen.

Logs daily_picks recommendations and tracks their outcomes.
Uses a separate SQLite database (data/shadow_trades.db) in WAL mode.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Project root (src/../)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Default DB path
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "shadow_trades.db"

# Valid values for validation
VALID_STRATEGIES = frozenset(
    {
        "pullback",
        "bounce",
        "ath_breakout",
        "earnings_dip",
        "trend_continuation",
    }
)

VALID_SOURCES = frozenset({"daily_picks", "scan", "manual"})

VALID_STATUSES = frozenset(
    {
        "open",
        "max_profit",
        "partial_profit",
        "stop_loss",
        "max_loss",
        "partial_loss",
    }
)

VALID_REJECTION_REASONS = frozenset(
    {
        "low_credit",
        "low_oi",
        "no_bid",
        "wide_spread",
        "no_chain",
    }
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shadow_trades (
    id              TEXT PRIMARY KEY,
    logged_at       TEXT NOT NULL,
    source          TEXT NOT NULL,

    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    score           REAL NOT NULL,
    enhanced_score  REAL,
    liquidity_tier  INTEGER,

    short_strike    REAL NOT NULL,
    long_strike     REAL NOT NULL,
    spread_width    REAL NOT NULL,
    est_credit      REAL NOT NULL,
    expiration      TEXT NOT NULL,
    dte             INTEGER NOT NULL,

    short_bid       REAL,
    short_ask       REAL,
    short_oi        INTEGER,
    long_bid        REAL,
    long_ask        REAL,
    long_oi         INTEGER,

    price_at_log    REAL NOT NULL,
    vix_at_log      REAL,
    regime_at_log   TEXT,
    stability_at_log REAL,
    trade_context   TEXT,

    status          TEXT DEFAULT 'open',
    resolved_at     TEXT,
    price_at_expiry REAL,
    price_min       REAL,
    price_at_50pct  REAL,
    days_to_50pct   INTEGER,
    theoretical_pnl REAL,
    spread_value_at_resolve REAL,
    outcome_notes   TEXT
);

CREATE TABLE IF NOT EXISTS shadow_rejections (
    id              TEXT PRIMARY KEY,
    logged_at       TEXT NOT NULL,
    source          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    score           REAL NOT NULL,
    liquidity_tier  INTEGER,
    short_strike    REAL,
    long_strike     REAL,
    rejection_reason TEXT NOT NULL,
    actual_credit   REAL,
    short_oi        INTEGER,
    details         TEXT
);
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_shadow_symbol ON shadow_trades(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_shadow_status ON shadow_trades(status);",
    "CREATE INDEX IF NOT EXISTS idx_shadow_strategy ON shadow_trades(strategy);",
    "CREATE INDEX IF NOT EXISTS idx_shadow_expiration ON shadow_trades(expiration);",
    "CREATE INDEX IF NOT EXISTS idx_shadow_logged ON shadow_trades(logged_at);",
    "CREATE INDEX IF NOT EXISTS idx_shadow_tier ON shadow_trades(liquidity_tier);",
    "CREATE INDEX IF NOT EXISTS idx_rejected_reason ON shadow_rejections(rejection_reason);",
    "CREATE INDEX IF NOT EXISTS idx_rejected_symbol ON shadow_rejections(symbol);",
]


def _validate_db_path(db_path: Path) -> Path:
    """Validate and resolve a database path to prevent symlink attacks."""
    db_path = Path(db_path)

    if db_path.exists() and db_path.is_symlink():
        raise ValueError(f"Database path is a symlink (rejected): {db_path}")

    parent = db_path.parent
    if parent.exists() and parent.is_symlink():
        raise ValueError(f"Parent directory is a symlink (rejected): {parent}")

    if parent.exists():
        return parent.resolve(strict=True) / db_path.name
    return db_path


def _load_settings() -> dict:
    """Load shadow_tracker settings from config/settings.yaml."""
    try:
        import yaml

        config_path = _PROJECT_ROOT / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("shadow_tracker", {})
    except Exception:
        pass
    return {}


def _load_tradability_config() -> dict:
    """Load tradability_gate settings from config/settings.yaml."""
    try:
        import yaml

        config_path = _PROJECT_ROOT / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("tradability_gate", {})
    except Exception:
        pass
    return {}


# Tradability gate defaults (matching settings.yaml)
_tg_cfg = _load_tradability_config()
_TG_MIN_NET_CREDIT = _tg_cfg.get("min_net_credit", 2.00)
_TG_MIN_OPEN_INTEREST = _tg_cfg.get("min_open_interest", 100)
_TG_MIN_BID = _tg_cfg.get("min_bid", 0.10)
_TG_MAX_BID_ASK_SPREAD_PCT = _tg_cfg.get("max_bid_ask_spread_pct", 30)


async def check_tradability(
    provider,
    symbol: str,
    expiration: str,
    short_strike: float,
    long_strike: float,
    *,
    min_net_credit: float = _TG_MIN_NET_CREDIT,
    min_open_interest: int = _TG_MIN_OPEN_INTEREST,
    min_bid: float = _TG_MIN_BID,
    max_bid_ask_spread_pct: float = _TG_MAX_BID_ASK_SPREAD_PCT,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Check if a bull-put-spread is tradeable against the live options chain.

    Args:
        provider: TradierProvider (or compatible) with get_option_chain().
        symbol: Underlying symbol (e.g. "AAPL").
        expiration: Expiration date as "YYYY-MM-DD".
        short_strike: Short put strike price.
        long_strike: Long put strike price.
        min_net_credit: Minimum net credit (Short Bid - Long Ask).
        min_open_interest: Minimum OI per leg.
        min_bid: Minimum short put bid.
        max_bid_ask_spread_pct: Max bid-ask spread as % of midpoint.

    Returns:
        (tradeable, reason, details) where:
        - tradeable: True if all checks pass
        - reason: 'tradeable' or rejection reason
        - details: dict with actual market data for both legs
    """
    details: Dict[str, Any] = {
        "symbol": symbol,
        "expiration": expiration,
        "short_strike": short_strike,
        "long_strike": long_strike,
    }

    # Fetch options chain for the specific expiration
    try:
        expiry_date = date.fromisoformat(expiration)
        chain: List = await provider.get_option_chain(symbol, expiry=expiry_date, right="P")
    except Exception as e:
        logger.warning("Failed to fetch options chain for %s: %s", symbol, e)
        details["error"] = str(e)
        return (False, "no_chain", details)

    if not chain:
        logger.info("Empty options chain for %s exp=%s", symbol, expiration)
        return (False, "no_chain", details)

    # Build strike lookup
    chain_by_strike: Dict[float, Any] = {}
    for opt in chain:
        chain_by_strike[opt.strike] = opt

    # 3a. Strikes in chain?
    short_opt = chain_by_strike.get(short_strike)
    long_opt = chain_by_strike.get(long_strike)

    if short_opt is None or long_opt is None:
        details["short_found"] = short_opt is not None
        details["long_found"] = long_opt is not None
        return (False, "no_chain", details)

    # Populate details with actual market data
    details["short_bid"] = short_opt.bid
    details["short_ask"] = short_opt.ask
    details["short_oi"] = short_opt.open_interest
    details["long_bid"] = long_opt.bid
    details["long_ask"] = long_opt.ask
    details["long_oi"] = long_opt.open_interest

    # Calculate net credit: Short Bid - Long Ask
    short_bid_val = short_opt.bid or 0.0
    long_ask_val = long_opt.ask or 0.0
    net_credit = short_bid_val - long_ask_val
    details["net_credit"] = round(net_credit, 2)

    # Calculate bid-ask spread % for short leg
    short_mid = short_opt.mid
    if short_mid and short_mid > 0:
        spread_pct = ((short_opt.ask or 0) - (short_opt.bid or 0)) / short_mid * 100
    else:
        spread_pct = 100.0  # Worst case
    details["bid_ask_spread_pct"] = round(spread_pct, 1)

    # 3b. Short Put Bid >= min_bid?
    if short_bid_val < min_bid:
        return (False, "no_bid", details)

    # 3c. Short Put OI >= min_open_interest?
    short_oi = short_opt.open_interest or 0
    if short_oi < min_open_interest:
        return (False, "low_oi", details)

    # 3d. Long Put OI >= min_open_interest?
    long_oi = long_opt.open_interest or 0
    if long_oi < min_open_interest:
        return (False, "low_oi", details)

    # 3e. Bid-Ask Spread <= max %?
    if spread_pct > max_bid_ask_spread_pct:
        return (False, "wide_spread", details)

    # 3f. Net Credit >= min_net_credit?
    if net_credit < min_net_credit:
        return (False, "low_credit", details)

    # All checks passed
    return (True, "tradeable", details)


class ShadowTracker:
    """Shadow Trade Tracker — protokolliert und verfolgt Empfehlungen."""

    @staticmethod
    def _load_settings_static() -> dict:
        """Load shadow_tracker settings without instantiation."""
        return _load_settings()

    def __init__(self, db_path: Optional[str] = None):
        if db_path is not None:
            self._db_path = _validate_db_path(Path(db_path))
        else:
            settings = _load_settings()
            configured = settings.get("db_path")
            if configured:
                raw = Path(configured)
                if not raw.is_absolute():
                    raw = _PROJECT_ROOT / raw
                self._db_path = _validate_db_path(raw)
            else:
                self._db_path = _validate_db_path(_DEFAULT_DB_PATH)

        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        logger.info("ShadowTracker initialized: %s", self._db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ------------------------------------------------------------------
    # DB Management
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create tables and indices if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
            for idx_sql in _INDEX_SQL:
                conn.execute(idx_sql)
            # Migrations for existing DBs
            cols = {r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()}
            if "trade_context" not in cols:
                conn.execute("ALTER TABLE shadow_trades ADD COLUMN trade_context TEXT")

    def _ensure_connection(self) -> sqlite3.Connection:
        """Create or return existing connection with WAL mode."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    @contextmanager
    def _get_connection(self):
        """Context manager for database connection (reuses connection)."""
        conn = self._ensure_connection()
        try:
            yield conn
            conn.commit()
        except (sqlite3.DatabaseError, OSError):
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # CRUD: shadow_trades
    # ------------------------------------------------------------------

    def log_trade(
        self,
        *,
        source: str,
        symbol: str,
        strategy: str,
        score: float,
        short_strike: float,
        long_strike: float,
        spread_width: float,
        est_credit: float,
        expiration: str,
        dte: int,
        price_at_log: float,
        enhanced_score: Optional[float] = None,
        liquidity_tier: Optional[int] = None,
        short_bid: Optional[float] = None,
        short_ask: Optional[float] = None,
        short_oi: Optional[int] = None,
        long_bid: Optional[float] = None,
        long_ask: Optional[float] = None,
        long_oi: Optional[int] = None,
        vix_at_log: Optional[float] = None,
        regime_at_log: Optional[str] = None,
        stability_at_log: Optional[float] = None,
        trade_context: Optional[str] = None,
    ) -> Optional[str]:
        """Log a shadow trade. Returns trade_id (UUID) or None if duplicate.

        Args:
            trade_context: JSON string with full analysis context (indicators,
                score breakdown, IV data, support/resistance levels, etc.)
                for later correlation analysis.
        """
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source: {source}. Must be one of {VALID_SOURCES}")
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}. Must be one of {VALID_STRATEGIES}")

        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._is_duplicate(symbol, short_strike, long_strike, today):
            logger.info(
                "Duplicate shadow trade skipped: %s %s/%s on %s",
                symbol,
                short_strike,
                long_strike,
                today,
            )
            return None

        trade_id = str(uuid.uuid4())
        logged_at = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO shadow_trades (
                    id, logged_at, source, symbol, strategy, score,
                    enhanced_score, liquidity_tier,
                    short_strike, long_strike, spread_width, est_credit,
                    expiration, dte,
                    short_bid, short_ask, short_oi,
                    long_bid, long_ask, long_oi,
                    price_at_log, vix_at_log, regime_at_log, stability_at_log,
                    trade_context, status
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, 'open'
                )
                """,
                (
                    trade_id,
                    logged_at,
                    source,
                    symbol,
                    strategy,
                    score,
                    enhanced_score,
                    liquidity_tier,
                    short_strike,
                    long_strike,
                    spread_width,
                    est_credit,
                    expiration,
                    dte,
                    short_bid,
                    short_ask,
                    short_oi,
                    long_bid,
                    long_ask,
                    long_oi,
                    price_at_log,
                    vix_at_log,
                    regime_at_log,
                    stability_at_log,
                    trade_context,
                ),
            )

        logger.info("Shadow trade logged: %s %s (%s) id=%s", symbol, strategy, score, trade_id)
        return trade_id

    def get_trade(self, trade_id: str) -> Optional[dict]:
        """Get a single trade by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM shadow_trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_open_trades(self) -> list:
        """Get all trades with status='open'."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM shadow_trades WHERE status = 'open' ORDER BY logged_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_trades(
        self,
        status_filter: str = "all",
        strategy_filter: Optional[str] = None,
        days_back: int = 90,
    ) -> list:
        """Get trades with optional filtering.

        Args:
            status_filter: 'all', 'open', or 'closed'
            strategy_filter: Filter by strategy name
            days_back: Only return trades from the last N days
        """
        conditions = []
        params = []

        cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
        conditions.append("logged_at >= ?")
        params.append(cutoff)

        if status_filter == "open":
            conditions.append("status = ?")
            params.append("open")
        elif status_filter == "closed":
            conditions.append("status != ?")
            params.append("open")

        if strategy_filter is not None:
            conditions.append("strategy = ?")
            params.append(strategy_filter)

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM shadow_trades WHERE {where} ORDER BY logged_at DESC"

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_trade_status(
        self,
        trade_id: str,
        status: str,
        *,
        resolved_at: Optional[str] = None,
        price_at_expiry: Optional[float] = None,
        price_min: Optional[float] = None,
        price_at_50pct: Optional[float] = None,
        days_to_50pct: Optional[int] = None,
        theoretical_pnl: Optional[float] = None,
        spread_value_at_resolve: Optional[float] = None,
        outcome_notes: Optional[str] = None,
    ) -> bool:
        """Update a trade's status and resolution fields.

        Returns True if the trade was found and updated.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

        if resolved_at is None and status != "open":
            resolved_at = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE shadow_trades SET
                    status = ?,
                    resolved_at = ?,
                    price_at_expiry = ?,
                    price_min = ?,
                    price_at_50pct = ?,
                    days_to_50pct = ?,
                    theoretical_pnl = ?,
                    spread_value_at_resolve = ?,
                    outcome_notes = ?
                WHERE id = ?
                """,
                (
                    status,
                    resolved_at,
                    price_at_expiry,
                    price_min,
                    price_at_50pct,
                    days_to_50pct,
                    theoretical_pnl,
                    spread_value_at_resolve,
                    outcome_notes,
                    trade_id,
                ),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # CRUD: shadow_rejections
    # ------------------------------------------------------------------

    def log_rejection(
        self,
        *,
        source: str,
        symbol: str,
        strategy: str,
        score: float,
        rejection_reason: str,
        liquidity_tier: Optional[int] = None,
        short_strike: Optional[float] = None,
        long_strike: Optional[float] = None,
        actual_credit: Optional[float] = None,
        short_oi: Optional[int] = None,
        details: Optional[str] = None,
    ) -> str:
        """Log a rejected trade candidate. Returns rejection_id (UUID)."""
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source: {source}. Must be one of {VALID_SOURCES}")
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}. Must be one of {VALID_STRATEGIES}")
        if rejection_reason not in VALID_REJECTION_REASONS:
            raise ValueError(
                f"Invalid rejection_reason: {rejection_reason}. "
                f"Must be one of {VALID_REJECTION_REASONS}"
            )

        rejection_id = str(uuid.uuid4())
        logged_at = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO shadow_rejections (
                    id, logged_at, source, symbol, strategy, score,
                    liquidity_tier, short_strike, long_strike,
                    rejection_reason, actual_credit, short_oi, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rejection_id,
                    logged_at,
                    source,
                    symbol,
                    strategy,
                    score,
                    liquidity_tier,
                    short_strike,
                    long_strike,
                    rejection_reason,
                    actual_credit,
                    short_oi,
                    details,
                ),
            )

        logger.info(
            "Shadow rejection logged: %s %s reason=%s id=%s",
            symbol,
            strategy,
            rejection_reason,
            rejection_id,
        )
        return rejection_id

    def get_rejections(self, days_back: int = 90) -> list:
        """Get rejections from the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM shadow_rejections
                WHERE logged_at >= ?
                ORDER BY logged_at DESC
                """,
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Duplikat-Check
    # ------------------------------------------------------------------

    def _is_duplicate(
        self, symbol: str, short_strike: float, long_strike: float, date: str
    ) -> bool:
        """Check if a trade with same symbol+strikes already exists today."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM shadow_trades
                WHERE symbol = ?
                  AND short_strike = ?
                  AND long_strike = ?
                  AND logged_at LIKE ?
                LIMIT 1
                """,
                (symbol, short_strike, long_strike, f"{date}%"),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Trade counts (for stats)
    # ------------------------------------------------------------------

    def get_trade_count(self) -> int:
        """Get total number of shadow trades."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()
        return row[0] if row else 0

    def get_rejection_count(self) -> int:
        """Get total number of shadow rejections."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM shadow_rejections").fetchone()
        return row[0] if row else 0


# ======================================================================
# Stats / Aggregation
# ======================================================================

# Score bucket boundaries
_SCORE_BUCKETS = [
    (9.0, 10.0, "9-10"),
    (7.0, 9.0, "7-9"),
    (5.0, 7.0, "5-7"),
    (0.0, 5.0, "<5"),
]


def _score_to_bucket(score: float) -> str:
    """Map a score to its bucket label."""
    for lo, hi, label in _SCORE_BUCKETS:
        if lo <= score < hi or (hi == 10.0 and score >= 9.0):
            return label
    return "<5"


def get_stats(
    tracker: "ShadowTracker",
    group_by: str = "strategy",
    min_trades: int = 5,
) -> Dict[str, Any]:
    """Compute aggregated shadow trade statistics.

    Args:
        tracker: ShadowTracker instance
        group_by: Grouping key — 'strategy', 'score_bucket', 'regime',
                  'month', 'symbol', 'tier', 'rejection_reason'
        min_trades: Minimum trades per group for statistical relevance

    Returns:
        Dict with 'groups' (list of group dicts), 'totals', 'executability'.
    """
    valid_groups = {
        "strategy",
        "score_bucket",
        "regime",
        "month",
        "symbol",
        "tier",
        "rejection_reason",
    }
    if group_by not in valid_groups:
        raise ValueError(f"Invalid group_by: {group_by}. Must be one of {valid_groups}")

    # Rejection analysis uses a different table
    if group_by == "rejection_reason":
        return _stats_rejections(tracker, min_trades)

    # Fetch all trades (no days_back limit for stats)
    trades = tracker.get_trades(days_back=9999)
    rejections = tracker.get_rejections(days_back=9999)

    # Group trades
    groups: Dict[str, list] = {}
    for t in trades:
        key = _get_group_key(t, group_by)
        groups.setdefault(key, []).append(t)

    # Compute per-group stats
    result_groups = []
    for key in sorted(groups.keys()):
        group_trades = groups[key]
        if len(group_trades) < min_trades:
            continue
        result_groups.append(_compute_group_stats(key, group_trades))

    # Totals
    totals = _compute_group_stats("ALL", trades) if trades else _empty_stats("ALL")

    return {
        "groups": result_groups,
        "totals": totals,
        "executability": _calc_executability(len(trades), len(rejections)),
        "group_by": group_by,
    }


def _get_group_key(trade: dict, group_by: str) -> str:
    """Extract group key from a trade dict."""
    if group_by == "strategy":
        return trade.get("strategy", "unknown")
    if group_by == "score_bucket":
        return _score_to_bucket(trade.get("score", 0))
    if group_by == "regime":
        return trade.get("regime_at_log") or "unknown"
    if group_by == "month":
        logged = trade.get("logged_at", "")
        return logged[:7] if len(logged) >= 7 else "unknown"
    if group_by == "symbol":
        return trade.get("symbol", "unknown")
    if group_by == "tier":
        tier = trade.get("liquidity_tier")
        return f"Tier {tier}" if tier is not None else "unknown"
    return "unknown"


def _compute_group_stats(key: str, trades: list) -> dict:
    """Compute win rate, P&L, and counts for a group of trades."""
    total = len(trades)
    open_count = sum(1 for t in trades if t["status"] == "open")
    closed = [t for t in trades if t["status"] != "open"]
    closed_count = len(closed)

    wins = sum(1 for t in closed if t["status"] in ("max_profit", "partial_profit"))
    losses = sum(1 for t in closed if t["status"] in ("max_loss", "partial_loss", "stop_loss"))
    win_rate = (wins / closed_count * 100) if closed_count > 0 else 0.0

    total_pnl = sum(t.get("theoretical_pnl", 0) or 0 for t in closed)
    avg_pnl = total_pnl / closed_count if closed_count > 0 else 0.0

    avg_score = sum(t.get("score", 0) or 0 for t in trades) / total if total > 0 else 0.0

    return {
        "key": key,
        "total": total,
        "open": open_count,
        "closed": closed_count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "avg_score": round(avg_score, 1),
    }


def _empty_stats(key: str) -> dict:
    """Return an empty stats dict."""
    return {
        "key": key,
        "total": 0,
        "open": 0,
        "closed": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "avg_pnl": 0.0,
        "avg_score": 0.0,
    }


def _stats_rejections(tracker: "ShadowTracker", min_trades: int) -> Dict[str, Any]:
    """Compute rejection stats grouped by reason."""
    rejections = tracker.get_rejections(days_back=9999)
    trades = tracker.get_trades(days_back=9999)

    groups: Dict[str, list] = {}
    for r in rejections:
        reason = r.get("rejection_reason", "unknown")
        groups.setdefault(reason, []).append(r)

    result_groups = []
    for key in sorted(groups.keys()):
        group = groups[key]
        if len(group) < min_trades:
            continue
        avg_score = sum(r.get("score", 0) or 0 for r in group) / len(group) if group else 0.0
        result_groups.append(
            {
                "key": key,
                "count": len(group),
                "avg_score": round(avg_score, 1),
                "pct_of_rejections": (
                    round(len(group) / len(rejections) * 100, 1) if rejections else 0.0
                ),
            }
        )

    return {
        "groups": result_groups,
        "total_rejections": len(rejections),
        "executability": _calc_executability(len(trades), len(rejections)),
        "group_by": "rejection_reason",
    }


def _calc_executability(trade_count: int, rejection_count: int) -> dict:
    """Calculate executability rate."""
    total = trade_count + rejection_count
    rate = (trade_count / total * 100) if total > 0 else 0.0
    return {
        "trades": trade_count,
        "rejections": rejection_count,
        "total": total,
        "rate": round(rate, 1),
    }


def format_stats_output(stats: Dict[str, Any]) -> str:
    """Format get_stats() output as Markdown."""
    group_by = stats.get("group_by", "strategy")
    lines = [f"# Shadow Trade Stats (by {group_by})", ""]

    if group_by == "rejection_reason":
        return _format_rejection_stats(stats)

    groups = stats.get("groups", [])
    if groups:
        lines.append(
            "| Group | Trades | Open | Closed | Win Rate | " "Avg P&L | Total P&L | Avg Score |"
        )
        lines.append(
            "|-------|--------|------|--------|----------|" "---------|-----------|-----------|"
        )
        for g in groups:
            lines.append(
                f"| {g['key']} | {g['total']} | {g['open']} | {g['closed']} "
                f"| {g['win_rate']:.0f}% | ${g['avg_pnl']:+.0f} "
                f"| ${g['total_pnl']:+.0f} | {g['avg_score']:.1f} |"
            )
        lines.append("")
    else:
        lines.append("*No groups with sufficient data.*")
        lines.append("")

    # Totals
    totals = stats.get("totals", {})
    if totals.get("total", 0) > 0:
        lines.append("## Totals")
        lines.append("")
        lines.append(
            f"- **Trades:** {totals['total']} "
            f"({totals['open']} open, {totals['closed']} closed)"
        )
        if totals["closed"] > 0:
            lines.append(
                f"- **Win rate:** {totals['win_rate']:.0f}% "
                f"({totals['wins']}W / {totals['losses']}L)"
            )
            lines.append(f"- **Total P&L:** ${totals['total_pnl']:+.0f}")
            lines.append(f"- **Avg P&L per trade:** ${totals['avg_pnl']:+.0f}")
        lines.append("")

    # Executability
    ex = stats.get("executability", {})
    if ex.get("total", 0) > 0:
        lines.append(
            f"**Executability rate:** {ex['rate']:.0f}% " f"({ex['trades']}/{ex['total']})"
        )

    return "\n".join(lines)


def _format_rejection_stats(stats: Dict[str, Any]) -> str:
    """Format rejection-grouped stats as Markdown."""
    lines = ["# Shadow Rejection Analysis", ""]

    groups = stats.get("groups", [])
    if groups:
        lines.append("| Reason | Count | % of Rejections | Avg Score |")
        lines.append("|--------|-------|-----------------|-----------|")
        for g in groups:
            lines.append(
                f"| {g['key']} | {g['count']} "
                f"| {g['pct_of_rejections']:.0f}% | {g['avg_score']:.1f} |"
            )
        lines.append("")
    else:
        lines.append("*No rejection groups with sufficient data.*")
        lines.append("")

    total_rej = stats.get("total_rejections", 0)
    lines.append(f"**Total rejections:** {total_rej}")

    ex = stats.get("executability", {})
    if ex.get("total", 0) > 0:
        lines.append(
            f"**Executability rate:** {ex['rate']:.0f}% " f"({ex['trades']}/{ex['total']})"
        )

    return "\n".join(lines)


# ======================================================================
# Detail View
# ======================================================================


def format_detail_output(trade: dict) -> str:
    """Format a single shadow trade as a detailed Markdown view.

    Args:
        trade: Dict from ShadowTracker.get_trade()

    Returns:
        Markdown string with all trade fields.
    """
    if not trade:
        return "**Trade not found.**"

    lines = [f"# Shadow Trade: {trade['symbol']} ({trade['strategy']})", ""]

    # Status badge
    status = trade["status"]
    if status == "open":
        badge = "OPEN"
    elif status in ("max_profit", "partial_profit"):
        badge = f"WIN ({status})"
    else:
        badge = f"LOSS ({status})"
    lines.append(f"**Status:** {badge}")
    lines.append(f"**Trade ID:** `{trade['id']}`")
    lines.append("")

    # Trade setup
    lines.append("## Trade Setup")
    lines.append("")
    lines.append(f"- **Symbol:** {trade['symbol']}")
    lines.append(f"- **Strategy:** {trade['strategy']}")
    lines.append(f"- **Score:** {trade['score']:.1f}")
    if trade.get("enhanced_score"):
        lines.append(f"- **Enhanced Score:** {trade['enhanced_score']:.1f}")
    lines.append(f"- **Source:** {trade['source']}")
    lines.append(f"- **Logged:** {trade['logged_at']}")
    if trade.get("liquidity_tier"):
        lines.append(f"- **Liquidity Tier:** {trade['liquidity_tier']}")
    lines.append("")

    # Spread details
    lines.append("## Spread Details")
    lines.append("")
    lines.append(
        f"- **Strikes:** {trade['short_strike']:.0f} / {trade['long_strike']:.0f} "
        f"(width: ${trade['spread_width']:.0f})"
    )
    lines.append(f"- **Est. Credit:** ${trade['est_credit']:.2f}")
    lines.append(f"- **Expiration:** {trade['expiration']} (DTE: {trade['dte']})")
    lines.append(f"- **Price at Log:** ${trade['price_at_log']:.2f}")
    lines.append("")

    # Options market data at logging
    if trade.get("short_bid") is not None:
        lines.append("## Options Market Data (at Log)")
        lines.append("")
        lines.append("| Leg | Bid | Ask | OI |")
        lines.append("|-----|-----|-----|-----|")
        short_bid = trade.get("short_bid", 0)
        short_ask = trade.get("short_ask", 0)
        short_oi = trade.get("short_oi", 0)
        long_bid = trade.get("long_bid", 0)
        long_ask = trade.get("long_ask", 0)
        long_oi = trade.get("long_oi", 0)
        lines.append(
            f"| Short ({trade['short_strike']:.0f}P) "
            f"| ${short_bid:.2f} | ${short_ask:.2f} | {short_oi} |"
        )
        lines.append(
            f"| Long ({trade['long_strike']:.0f}P) "
            f"| ${long_bid:.2f} | ${long_ask:.2f} | {long_oi} |"
        )
        lines.append("")

    # Market context at logging
    if trade.get("vix_at_log") is not None or trade.get("regime_at_log"):
        lines.append("## Market Context (at Log)")
        lines.append("")
        if trade.get("vix_at_log") is not None:
            lines.append(f"- **VIX:** {trade['vix_at_log']:.1f}")
        if trade.get("regime_at_log"):
            lines.append(f"- **Regime:** {trade['regime_at_log']}")
        if trade.get("stability_at_log") is not None:
            lines.append(f"- **Stability:** {trade['stability_at_log']:.1f}")
        lines.append("")

    # Resolution data (if resolved)
    if status != "open":
        lines.append("## Resolution")
        lines.append("")
        if trade.get("resolved_at"):
            lines.append(f"- **Resolved:** {trade['resolved_at']}")
        if trade.get("price_at_expiry") is not None:
            lines.append(f"- **Price at Expiry:** ${trade['price_at_expiry']:.2f}")
        if trade.get("price_min") is not None:
            lines.append(f"- **Price Min (since log):** ${trade['price_min']:.2f}")
        if trade.get("spread_value_at_resolve") is not None:
            lines.append(f"- **Spread Value at Resolve:** ${trade['spread_value_at_resolve']:.4f}")
        if trade.get("price_at_50pct") is not None:
            lines.append(f"- **Price at 50% Target:** ${trade['price_at_50pct']:.2f}")
        if trade.get("days_to_50pct") is not None:
            lines.append(f"- **Days to 50%:** {trade['days_to_50pct']}")
        if trade.get("theoretical_pnl") is not None:
            pnl = trade["theoretical_pnl"]
            lines.append(f"- **P&L:** ${pnl:+.0f}")
        if trade.get("outcome_notes"):
            lines.append(f"- **Notes:** {trade['outcome_notes']}")
        lines.append("")

    return "\n".join(lines)


# ======================================================================
# Resolution Logic
# ======================================================================

# P&L multiplier (1 contract = 100 shares)
_CONTRACT_MULTIPLIER = 100


def calculate_pnl(
    status: str,
    est_credit: float,
    spread_width: float,
    spread_value_at_resolve: Optional[float] = None,
    price_at_expiry: Optional[float] = None,
    short_strike: Optional[float] = None,
) -> float:
    """Calculate theoretical P&L for a resolved shadow trade.

    All values are per-spread, multiplied by 100 (1 contract).

    Returns P&L in dollars (positive = profit, negative = loss).
    """
    credit = est_credit * _CONTRACT_MULTIPLIER

    if status == "max_profit":
        return credit

    if status == "partial_profit":
        if spread_value_at_resolve is not None:
            return (est_credit - spread_value_at_resolve) * _CONTRACT_MULTIPLIER
        return credit * 0.50  # Assume 50% target

    if status == "stop_loss":
        if spread_value_at_resolve is not None:
            return -(spread_value_at_resolve - est_credit) * _CONTRACT_MULTIPLIER
        return -(est_credit * 1.50) * _CONTRACT_MULTIPLIER  # Fallback: 150% of credit

    if status == "max_loss":
        return -(spread_width * _CONTRACT_MULTIPLIER - credit)

    if status == "partial_loss":
        if price_at_expiry is not None and short_strike is not None:
            intrinsic = max(0.0, short_strike - price_at_expiry)
            return credit - intrinsic * _CONTRACT_MULTIPLIER
        return 0.0

    return 0.0


async def resolve_trade(
    trade: dict,
    provider=None,
) -> Optional[Dict[str, Any]]:
    """Resolve a single open shadow trade against current market data.

    Args:
        trade: Dict from ShadowTracker.get_trade()
        provider: TradierProvider (or compatible) for live data

    Returns:
        Dict with resolution fields if resolved, None if trade stays open.
        Keys: status, spread_value_at_resolve, price_at_expiry, price_min,
              price_at_50pct, days_to_50pct, theoretical_pnl, outcome_notes
    """
    if trade["status"] != "open":
        return None

    symbol = trade["symbol"]
    expiration = trade["expiration"]
    short_strike = trade["short_strike"]
    long_strike = trade["long_strike"]
    spread_width = trade["spread_width"]
    est_credit = trade["est_credit"]
    logged_at = trade["logged_at"]

    today = date.today()
    expiry_date = date.fromisoformat(expiration)
    expired = expiry_date <= today

    # Calculate days since logging
    try:
        log_date = datetime.fromisoformat(logged_at).date()
    except (ValueError, TypeError):
        log_date = today
    days_held = (today - log_date).days

    # --- Try to get live options chain data ---
    chain_data = None
    if provider and not expired:
        try:
            chain = await provider.get_option_chain(symbol, expiry=expiry_date, right="P")
            if chain:
                chain_by_strike = {opt.strike: opt for opt in chain}
                short_opt = chain_by_strike.get(short_strike)
                long_opt = chain_by_strike.get(long_strike)
                if short_opt and long_opt:
                    short_ask = short_opt.ask or 0.0
                    long_bid = long_opt.bid or 0.0
                    chain_data = {
                        "spread_value": short_ask - long_bid,
                        "short_ask": short_ask,
                        "long_bid": long_bid,
                    }
        except Exception as e:
            logger.debug("Chain fetch failed for %s: %s", symbol, e)

    # --- Get historical prices for price_min ---
    price_min = None
    current_price = None
    if provider:
        try:
            bars = await provider.get_historical(symbol, days=max(days_held + 5, 30))
            if bars:
                # Filter to bars since logging
                relevant = [b for b in bars if b.date >= log_date]
                if relevant:
                    price_min = min(b.low for b in relevant)
                    current_price = relevant[-1].close
        except Exception as e:
            logger.debug("Historical fetch failed for %s: %s", symbol, e)

    # --- Resolution checks (in priority order) ---

    # 6. PROFIT-TARGET CHECK (50% of credit)
    if chain_data:
        spread_value = chain_data["spread_value"]
        profit_target = est_credit * 0.50
        if spread_value <= profit_target:
            pnl = calculate_pnl(
                "partial_profit",
                est_credit,
                spread_width,
                spread_value_at_resolve=spread_value,
            )
            return {
                "status": "partial_profit",
                "spread_value_at_resolve": round(spread_value, 4),
                "price_min": price_min,
                "price_at_50pct": current_price,
                "days_to_50pct": days_held,
                "theoretical_pnl": round(pnl, 2),
                "outcome_notes": (
                    f"50% profit target hit. Spread value ${spread_value:.2f} "
                    f"<= target ${profit_target:.2f}"
                ),
            }

        # 7. STOP-LOSS CHECK (spread value >= 250% of credit)
        stop_loss_value = est_credit * 2.50
        if spread_value >= stop_loss_value:
            pnl = calculate_pnl(
                "stop_loss",
                est_credit,
                spread_width,
                spread_value_at_resolve=spread_value,
            )
            return {
                "status": "stop_loss",
                "spread_value_at_resolve": round(spread_value, 4),
                "price_min": price_min,
                "theoretical_pnl": round(pnl, 2),
                "outcome_notes": (
                    f"Stop-loss triggered. Spread value ${spread_value:.2f} "
                    f">= stop ${stop_loss_value:.2f}"
                ),
            }

    # 8. EXPIRATION CHECK
    if expired:
        price_at_expiry = current_price
        if price_at_expiry is not None:
            if price_at_expiry >= short_strike:
                status = "max_profit"
                pnl = calculate_pnl("max_profit", est_credit, spread_width)
                notes = f"Expired OTM. Price ${price_at_expiry:.2f} >= short ${short_strike:.0f}"
            elif price_at_expiry <= long_strike:
                status = "max_loss"
                pnl = calculate_pnl("max_loss", est_credit, spread_width)
                notes = f"Expired ITM. Price ${price_at_expiry:.2f} <= long ${long_strike:.0f}"
            else:
                status = "partial_loss"
                pnl = calculate_pnl(
                    "partial_loss",
                    est_credit,
                    spread_width,
                    price_at_expiry=price_at_expiry,
                    short_strike=short_strike,
                )
                notes = (
                    f"Expired between strikes. Price ${price_at_expiry:.2f} "
                    f"(short ${short_strike:.0f}, long ${long_strike:.0f})"
                )

            return {
                "status": status,
                "price_at_expiry": price_at_expiry,
                "price_min": price_min,
                "theoretical_pnl": round(pnl, 2),
                "outcome_notes": notes,
            }

    # 9. PRICE-BASED STOP-LOSS FALLBACK
    if price_min is not None and not chain_data:
        stop_trigger = short_strike - (spread_width * 0.3)
        if price_min <= stop_trigger:
            pnl = calculate_pnl("stop_loss", est_credit, spread_width)
            return {
                "status": "stop_loss",
                "price_min": price_min,
                "theoretical_pnl": round(pnl, 2),
                "outcome_notes": (
                    f"Price-based stop triggered. Min ${price_min:.2f} "
                    f"<= trigger ${stop_trigger:.2f} (price fallback)"
                ),
            }

    # 10. Stays open
    return None


async def resolve_open_trades(
    tracker: "ShadowTracker",
    provider=None,
) -> List[Dict[str, Any]]:
    """Resolve all open shadow trades.

    Returns list of dicts with trade_id, symbol, old_status, new_status, pnl.
    """
    open_trades = tracker.get_open_trades()
    results = []

    for trade in open_trades:
        resolution = await resolve_trade(trade, provider=provider)
        if resolution:
            tracker.update_trade_status(
                trade["id"],
                resolution["status"],
                price_at_expiry=resolution.get("price_at_expiry"),
                price_min=resolution.get("price_min"),
                price_at_50pct=resolution.get("price_at_50pct"),
                days_to_50pct=resolution.get("days_to_50pct"),
                theoretical_pnl=resolution.get("theoretical_pnl"),
                spread_value_at_resolve=resolution.get("spread_value_at_resolve"),
                outcome_notes=resolution.get("outcome_notes"),
            )
            results.append(
                {
                    "trade_id": trade["id"],
                    "symbol": trade["symbol"],
                    "strategy": trade["strategy"],
                    "old_status": "open",
                    "new_status": resolution["status"],
                    "pnl": resolution.get("theoretical_pnl", 0),
                    "notes": resolution.get("outcome_notes", ""),
                }
            )

    return results


def format_review_output(
    trades: List[dict],
    resolutions: List[Dict[str, Any]],
    rejections: List[dict],
) -> str:
    """Format shadow_review output as Markdown.

    Args:
        trades: All trades matching filter criteria
        resolutions: Results from resolve_open_trades()
        rejections: Rejections for executability rate
    """
    lines = ["# Shadow Trade Review", ""]

    # Resolution summary
    if resolutions:
        lines.append("## Resolutions This Review")
        lines.append("")
        lines.append("| Symbol | Strategy | Status | P&L | Notes |")
        lines.append("|--------|----------|--------|-----|-------|")
        for r in resolutions:
            pnl_str = f"${r['pnl']:+.0f}" if r.get("pnl") else "-"
            lines.append(
                f"| {r['symbol']} | {r['strategy']} | {r['new_status']} "
                f"| {pnl_str} | {r.get('notes', '')[:60]} |"
            )
        lines.append("")

    # Open trades
    open_trades = [t for t in trades if t["status"] == "open"]
    if open_trades:
        lines.append(f"## Open Trades ({len(open_trades)})")
        lines.append("")
        lines.append("| Symbol | Strategy | Score | Credit | Strikes | DTE | Logged |")
        lines.append("|--------|----------|-------|--------|---------|-----|--------|")
        for t in open_trades:
            dte_now = (
                (date.fromisoformat(t["expiration"]) - date.today()).days
                if t.get("expiration")
                else "?"
            )
            logged_short = t["logged_at"][:10] if t.get("logged_at") else "?"
            lines.append(
                f"| {t['symbol']} | {t['strategy']} | {t['score']:.1f} "
                f"| ${t['est_credit']:.2f} "
                f"| {t['short_strike']:.0f}/{t['long_strike']:.0f} "
                f"| {dte_now} | {logged_short} |"
            )
        lines.append("")

    # Closed trades
    closed_trades = [t for t in trades if t["status"] != "open"]
    if closed_trades:
        lines.append(f"## Closed Trades ({len(closed_trades)})")
        lines.append("")
        lines.append("| Symbol | Strategy | Status | P&L | Credit | Resolved |")
        lines.append("|--------|----------|--------|-----|--------|----------|")
        for t in closed_trades:
            pnl_str = f"${t['theoretical_pnl']:+.0f}" if t.get("theoretical_pnl") else "-"
            resolved_short = t["resolved_at"][:10] if t.get("resolved_at") else "?"
            lines.append(
                f"| {t['symbol']} | {t['strategy']} | {t['status']} "
                f"| {pnl_str} | ${t['est_credit']:.2f} | {resolved_short} |"
            )
        lines.append("")

    # Summary
    total_trades = len(trades)
    total_closed = len(closed_trades)
    total_open = len(open_trades)
    total_pnl = sum(t.get("theoretical_pnl", 0) or 0 for t in closed_trades)
    win_count = sum(1 for t in closed_trades if t["status"] in ("max_profit", "partial_profit"))
    loss_count = sum(
        1 for t in closed_trades if t["status"] in ("max_loss", "partial_loss", "stop_loss")
    )
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total trades:** {total_trades} ({total_open} open, {total_closed} closed)")
    if total_closed > 0:
        lines.append(f"- **Win rate:** {win_rate:.0f}% ({win_count}W / {loss_count}L)")
        lines.append(f"- **Total P&L:** ${total_pnl:+.0f}")

    # Executability rate
    total_rejections = len(rejections)
    total_all = total_trades + total_rejections
    if total_all > 0:
        exec_rate = total_trades / total_all * 100
        lines.append(f"- **Executability rate:** {exec_rate:.0f}% ({total_trades}/{total_all})")

    lines.append("")
    lines.append(
        "*P&L basierend auf echten Options-Chain-Preisen bei Review. "
        "Expiration-Outcomes kursbasiert.*"
    )

    return "\n".join(lines)
