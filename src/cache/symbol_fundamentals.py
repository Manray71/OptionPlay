# OptionPlay - Symbol Fundamentals Manager
# =========================================
# SQLite-basierte Speicherung von Fundamentaldaten
#
# Datenquellen:
# - yfinance: Sector, Industry, Market Cap, Beta, Inst. Ownership
# - Tradier: 52-Week High/Low, Average Volume
# - Berechnet: SPY Correlation, IV Rank (aus eigenen Daten)
#
# Usage:
#     from src.cache.symbol_fundamentals import SymbolFundamentalsManager, get_fundamentals_manager
#
#     manager = get_fundamentals_manager()
#     manager.update_symbol("AAPL")
#     data = manager.get_fundamentals("AAPL")

import asyncio
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_DB_PATH = Path.home() / ".optionplay" / "trades.db"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SymbolFundamentals:
    """Fundamentaldaten für ein Symbol"""
    symbol: str

    # Statische Daten (yfinance)
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None  # in USD
    market_cap_category: Optional[str] = None  # Small/Mid/Large/Mega

    # Risiko-Metriken
    beta: Optional[float] = None

    # Preis-Levels (Tradier oder yfinance)
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    current_price: Optional[float] = None
    price_to_52w_high_pct: Optional[float] = None  # Abstand zu 52W High in %

    # Volumen
    average_volume: Optional[float] = None
    average_volume_10d: Optional[float] = None

    # Institutionelles
    institutional_ownership: Optional[float] = None  # 0.0 - 1.0

    # Analyst Ratings
    analyst_rating: Optional[str] = None  # BULLISH/NEUTRAL/BEARISH
    analyst_buy: Optional[int] = None
    analyst_hold: Optional[int] = None
    analyst_sell: Optional[int] = None
    target_price_median: Optional[float] = None
    target_price_high: Optional[float] = None
    target_price_low: Optional[float] = None
    upside_pct: Optional[float] = None

    # Dividende
    dividend_yield: Optional[float] = None

    # Bewertung
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None

    # Berechnete Metriken (aus eigenen Daten)
    spy_correlation_60d: Optional[float] = None
    iv_rank_252d: Optional[float] = None
    iv_percentile_252d: Optional[float] = None
    historical_volatility_30d: Optional[float] = None

    # Stability (aus outcomes.db)
    stability_score: Optional[float] = None
    historical_win_rate: Optional[float] = None
    avg_drawdown: Optional[float] = None

    # Earnings
    earnings_beat_rate: Optional[float] = None  # Aus earnings_history berechnet

    # Metadata
    updated_at: Optional[str] = None
    data_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SymbolFundamentals':
        """Erstellt aus Dictionary"""
        # Filtere nur bekannte Felder
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


def categorize_market_cap(market_cap: Optional[float]) -> Optional[str]:
    """Kategorisiert Market Cap in Small/Mid/Large/Mega"""
    if market_cap is None:
        return None

    if market_cap >= 200_000_000_000:  # >= $200B
        return "Mega"
    elif market_cap >= 10_000_000_000:  # >= $10B
        return "Large"
    elif market_cap >= 2_000_000_000:  # >= $2B
        return "Mid"
    elif market_cap >= 300_000_000:  # >= $300M
        return "Small"
    else:
        return "Micro"


# =============================================================================
# SYMBOL FUNDAMENTALS MANAGER
# =============================================================================

class SymbolFundamentalsManager:
    """
    Manager für Symbol-Fundamentaldaten in SQLite.

    Features:
    - Thread-safe SQLite Operationen
    - Automatische Kategorisierung (Market Cap)
    - Integration mit yfinance für Fundamentaldaten
    - Berechnung von Metriken aus eigenen Daten
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.RLock()
        self._ensure_db_exists()
        self._create_table()

    def _ensure_db_exists(self) -> None:
        """Stellt sicher, dass das DB-Verzeichnis existiert"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """Context Manager für Thread-safe DB-Verbindung"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _create_table(self) -> None:
        """Erstellt die symbol_fundamentals Tabelle falls nicht vorhanden"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS symbol_fundamentals (
                        symbol TEXT PRIMARY KEY,

                        -- Statische Daten (yfinance)
                        sector TEXT,
                        industry TEXT,
                        market_cap REAL,
                        market_cap_category TEXT,

                        -- Risiko-Metriken
                        beta REAL,

                        -- Preis-Levels
                        week_52_high REAL,
                        week_52_low REAL,
                        current_price REAL,
                        price_to_52w_high_pct REAL,

                        -- Volumen
                        average_volume REAL,
                        average_volume_10d REAL,

                        -- Institutionelles
                        institutional_ownership REAL,

                        -- Analyst Ratings
                        analyst_rating TEXT,
                        analyst_buy INTEGER,
                        analyst_hold INTEGER,
                        analyst_sell INTEGER,
                        target_price_median REAL,
                        target_price_high REAL,
                        target_price_low REAL,
                        upside_pct REAL,

                        -- Dividende
                        dividend_yield REAL,

                        -- Bewertung
                        pe_ratio REAL,
                        forward_pe REAL,
                        peg_ratio REAL,

                        -- Berechnete Metriken
                        spy_correlation_60d REAL,
                        iv_rank_252d REAL,
                        iv_percentile_252d REAL,
                        historical_volatility_30d REAL,

                        -- Stability (aus outcomes.db)
                        stability_score REAL,
                        historical_win_rate REAL,
                        avg_drawdown REAL,

                        -- Earnings
                        earnings_beat_rate REAL,

                        -- Metadata
                        updated_at TEXT,
                        data_source TEXT
                    )
                """)

                # Indices für schnelle Abfragen
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sf_sector
                    ON symbol_fundamentals(sector)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sf_market_cap_cat
                    ON symbol_fundamentals(market_cap_category)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sf_stability
                    ON symbol_fundamentals(stability_score)
                """)

                conn.commit()
                logger.debug("symbol_fundamentals Tabelle initialisiert")

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def save_fundamentals(self, fundamentals: SymbolFundamentals) -> bool:
        """
        Speichert Fundamentaldaten für ein Symbol.

        Args:
            fundamentals: SymbolFundamentals Objekt

        Returns:
            True bei Erfolg
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                try:
                    data = fundamentals.to_dict()
                    data['updated_at'] = datetime.now().isoformat()

                    # Market Cap Kategorie setzen
                    if data.get('market_cap') and not data.get('market_cap_category'):
                        data['market_cap_category'] = categorize_market_cap(data['market_cap'])

                    # Price to 52W High berechnen
                    if data.get('current_price') and data.get('week_52_high'):
                        data['price_to_52w_high_pct'] = round(
                            (data['current_price'] / data['week_52_high'] - 1) * 100, 2
                        )

                    columns = list(data.keys())
                    placeholders = ', '.join(['?' for _ in columns])
                    columns_str = ', '.join(columns)

                    cursor.execute(f"""
                        INSERT OR REPLACE INTO symbol_fundamentals ({columns_str})
                        VALUES ({placeholders})
                    """, list(data.values()))

                    conn.commit()
                    logger.debug(f"Fundamentals für {fundamentals.symbol} gespeichert")
                    return True

                except sqlite3.Error as e:
                    logger.error(f"Fehler beim Speichern von {fundamentals.symbol}: {e}")
                    return False

    def save_fundamentals_batch(self, fundamentals_list: List[SymbolFundamentals]) -> int:
        """
        Speichert mehrere Fundamentaldaten in einer Transaktion.

        Vermeidet N+1 Query-Problem bei Bulk-Updates.

        Args:
            fundamentals_list: Liste von SymbolFundamentals Objekten

        Returns:
            Anzahl erfolgreich gespeicherter Einträge
        """
        if not fundamentals_list:
            return 0

        saved = 0

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                for fundamentals in fundamentals_list:
                    try:
                        data = fundamentals.to_dict()
                        data['updated_at'] = datetime.now().isoformat()

                        # Market Cap Kategorie setzen
                        if data.get('market_cap') and not data.get('market_cap_category'):
                            data['market_cap_category'] = categorize_market_cap(data['market_cap'])

                        # Price to 52W High berechnen
                        if data.get('current_price') and data.get('week_52_high'):
                            data['price_to_52w_high_pct'] = round(
                                (data['current_price'] / data['week_52_high'] - 1) * 100, 2
                            )

                        columns = list(data.keys())
                        placeholders = ', '.join(['?' for _ in columns])
                        columns_str = ', '.join(columns)

                        cursor.execute(f"""
                            INSERT OR REPLACE INTO symbol_fundamentals ({columns_str})
                            VALUES ({placeholders})
                        """, list(data.values()))
                        saved += 1

                    except sqlite3.Error as e:
                        logger.warning(f"Fehler beim Batch-Speichern von {fundamentals.symbol}: {e}")
                        continue

                conn.commit()

        logger.info(f"Batch-Save: {saved}/{len(fundamentals_list)} Fundamentals gespeichert")
        return saved

    def get_fundamentals(self, symbol: str) -> Optional[SymbolFundamentals]:
        """
        Holt Fundamentaldaten für ein Symbol.

        Args:
            symbol: Ticker-Symbol

        Returns:
            SymbolFundamentals oder None
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM symbol_fundamentals WHERE symbol = ?
                """, (symbol,))

                row = cursor.fetchone()

        if not row:
            return None

        return SymbolFundamentals.from_dict(dict(row))

    def get_fundamentals_batch(self, symbols: List[str]) -> Dict[str, SymbolFundamentals]:
        """
        Holt Fundamentaldaten für mehrere Symbole in einem Query.

        Vermeidet N+1 Query-Problem bei Bulk-Operationen.

        Args:
            symbols: Liste von Ticker-Symbolen

        Returns:
            Dict mit {symbol: SymbolFundamentals}
        """
        if not symbols:
            return {}

        symbols = [s.upper() for s in symbols]

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join(['?' for _ in symbols])
                cursor.execute(f"""
                    SELECT * FROM symbol_fundamentals
                    WHERE symbol IN ({placeholders})
                """, symbols)

                rows = cursor.fetchall()

        result = {}
        for row in rows:
            fundamentals = SymbolFundamentals.from_dict(dict(row))
            result[fundamentals.symbol] = fundamentals

        return result

    def get_all_fundamentals(self) -> List[SymbolFundamentals]:
        """Holt alle gespeicherten Fundamentaldaten"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM symbol_fundamentals ORDER BY symbol")
                rows = cursor.fetchall()

        return [SymbolFundamentals.from_dict(dict(row)) for row in rows]

    def get_symbols_by_sector(self, sector: str) -> List[SymbolFundamentals]:
        """Holt alle Symbole eines Sektors"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM symbol_fundamentals
                    WHERE sector = ? ORDER BY symbol
                """, (sector,))
                rows = cursor.fetchall()

        return [SymbolFundamentals.from_dict(dict(row)) for row in rows]

    def get_symbols_by_market_cap(self, category: str) -> List[SymbolFundamentals]:
        """Holt alle Symbole einer Market Cap Kategorie"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM symbol_fundamentals
                    WHERE market_cap_category = ? ORDER BY symbol
                """, (category,))
                rows = cursor.fetchall()

        return [SymbolFundamentals.from_dict(dict(row)) for row in rows]

    def get_stable_symbols(self, min_stability: float = 70.0) -> List[SymbolFundamentals]:
        """Holt alle Symbole mit Stability Score >= min_stability"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM symbol_fundamentals
                    WHERE stability_score >= ?
                    ORDER BY stability_score DESC
                """, (min_stability,))
                rows = cursor.fetchall()

        return [SymbolFundamentals.from_dict(dict(row)) for row in rows]

    # =========================================================================
    # Fetch from yfinance
    # =========================================================================

    def fetch_from_yfinance(self, symbol: str) -> Optional[SymbolFundamentals]:
        """
        Holt Fundamentaldaten von yfinance.

        Args:
            symbol: Ticker-Symbol

        Returns:
            SymbolFundamentals mit yfinance-Daten oder None
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance nicht installiert. Run: pip install yfinance")
            return None

        symbol = symbol.upper()

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}

            if not info or info.get('regularMarketPrice') is None:
                logger.warning(f"Keine yfinance-Daten für {symbol}")
                return None

            # Analyst Ratings extrahieren
            buy = hold = sell = 0
            rec_summary = getattr(ticker, 'recommendations_summary', None)
            if rec_summary is not None and not rec_summary.empty:
                for col in rec_summary.columns:
                    col_lower = col.lower()
                    total = rec_summary[col].sum()
                    if 'buy' in col_lower or 'strong' in col_lower:
                        buy += int(total)
                    elif 'hold' in col_lower:
                        hold += int(total)
                    elif 'sell' in col_lower or 'under' in col_lower:
                        sell += int(total)

            total_ratings = buy + hold + sell
            if total_ratings > 0:
                if buy > (hold + sell):
                    analyst_rating = "BULLISH"
                elif sell > (buy + hold):
                    analyst_rating = "BEARISH"
                else:
                    analyst_rating = "NEUTRAL"
            else:
                analyst_rating = "UNKNOWN"

            # Upside berechnen
            target_median = info.get('targetMeanPrice')
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            upside_pct = None
            if target_median and current_price and current_price > 0:
                upside_pct = round((target_median - current_price) / current_price * 100, 1)

            fundamentals = SymbolFundamentals(
                symbol=symbol,

                # Statische Daten
                sector=info.get('sector'),
                industry=info.get('industry'),
                market_cap=info.get('marketCap'),
                market_cap_category=categorize_market_cap(info.get('marketCap')),

                # Risiko
                beta=info.get('beta'),

                # Preis-Levels
                week_52_high=info.get('fiftyTwoWeekHigh'),
                week_52_low=info.get('fiftyTwoWeekLow'),
                current_price=current_price,

                # Volumen
                average_volume=info.get('averageVolume'),
                average_volume_10d=info.get('averageVolume10days'),

                # Institutionelles
                institutional_ownership=info.get('heldPercentInstitutions'),

                # Analyst Ratings
                analyst_rating=analyst_rating,
                analyst_buy=buy,
                analyst_hold=hold,
                analyst_sell=sell,
                target_price_median=target_median,
                target_price_high=info.get('targetHighPrice'),
                target_price_low=info.get('targetLowPrice'),
                upside_pct=upside_pct,

                # Dividende
                dividend_yield=info.get('dividendYield'),

                # Bewertung
                pe_ratio=info.get('trailingPE'),
                forward_pe=info.get('forwardPE'),
                peg_ratio=info.get('pegRatio'),

                # Metadata
                updated_at=datetime.now().isoformat(),
                data_source="yfinance"
            )

            logger.debug(f"yfinance-Daten für {symbol} geholt: {fundamentals.sector}, MC={fundamentals.market_cap_category}")
            return fundamentals

        except Exception as e:
            logger.error(f"Fehler beim Abrufen von yfinance-Daten für {symbol}: {e}")
            return None

    def update_from_yfinance(self, symbol: str) -> bool:
        """
        Aktualisiert Fundamentaldaten für ein Symbol von yfinance.

        Args:
            symbol: Ticker-Symbol

        Returns:
            True bei Erfolg
        """
        fundamentals = self.fetch_from_yfinance(symbol)
        if fundamentals:
            return self.save_fundamentals(fundamentals)
        return False

    def update_all_from_yfinance(
        self,
        symbols: List[str],
        delay_seconds: float = 0.5
    ) -> Dict[str, bool]:
        """
        Aktualisiert Fundamentaldaten für mehrere Symbole.

        Args:
            symbols: Liste von Ticker-Symbolen
            delay_seconds: Pause zwischen API-Aufrufen

        Returns:
            Dict mit {symbol: success}
        """
        import time

        results = {}
        total = len(symbols)

        for i, symbol in enumerate(symbols, 1):
            success = self.update_from_yfinance(symbol)
            results[symbol] = success

            status = "✓" if success else "✗"
            logger.info(f"[{i}/{total}] {symbol}: {status}")

            if i < total and delay_seconds > 0:
                time.sleep(delay_seconds)

        successful = sum(1 for v in results.values() if v)
        logger.info(f"Fundamentals Update: {successful}/{total} erfolgreich")

        return results

    # =========================================================================
    # Update calculated metrics
    # =========================================================================

    def update_stability_from_outcomes(self, symbol: str) -> bool:
        """
        Aktualisiert Stability-Metriken aus outcomes.db.

        Args:
            symbol: Ticker-Symbol

        Returns:
            True bei Erfolg
        """
        symbol = symbol.upper()
        outcomes_db = self.db_path.parent / "outcomes.db"

        if not outcomes_db.exists():
            logger.warning(f"outcomes.db nicht gefunden: {outcomes_db}")
            return False

        try:
            conn = sqlite3.connect(str(outcomes_db), timeout=30.0)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as trades,
                    AVG(CASE WHEN outcome = 'max_profit' THEN 1.0 ELSE 0.0 END) * 100 as win_rate,
                    AVG(max_drawdown_pct) as avg_drawdown
                FROM trade_outcomes
                WHERE symbol = ?
            """, (symbol,))

            row = cursor.fetchone()
            conn.close()

            if not row or row[0] == 0:
                return False

            trades, win_rate, avg_drawdown = row

            # Stability Score berechnen
            stability_score = 100 - (avg_drawdown * 3 + 0)  # Vereinfacht
            stability_score = max(0, min(100, stability_score))

            # Existierende Daten holen und updaten
            existing = self.get_fundamentals(symbol)
            if existing:
                existing.stability_score = round(stability_score, 1)
                existing.historical_win_rate = round(win_rate, 1)
                existing.avg_drawdown = round(avg_drawdown, 2)
                return self.save_fundamentals(existing)
            else:
                # Neuen Eintrag erstellen
                fundamentals = SymbolFundamentals(
                    symbol=symbol,
                    stability_score=round(stability_score, 1),
                    historical_win_rate=round(win_rate, 1),
                    avg_drawdown=round(avg_drawdown, 2),
                    data_source="outcomes"
                )
                return self.save_fundamentals(fundamentals)

        except Exception as e:
            logger.error(f"Fehler beim Updaten von Stability für {symbol}: {e}")
            return False

    def update_earnings_beat_rate(self, symbol: str) -> bool:
        """
        Berechnet und speichert die Earnings Beat Rate.

        Args:
            symbol: Ticker-Symbol

        Returns:
            True bei Erfolg
        """
        symbol = symbol.upper()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Beat Rate aus earnings_history berechnen
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN eps_actual > eps_estimate THEN 1 ELSE 0 END) as beats
                    FROM earnings_history
                    WHERE symbol = ? AND eps_actual IS NOT NULL AND eps_estimate IS NOT NULL
                """, (symbol,))

                row = cursor.fetchone()

                if not row or row[0] == 0:
                    return False

                total, beats = row
                beat_rate = (beats / total) * 100 if total > 0 else None

                # Update
                existing = self.get_fundamentals(symbol)
                if existing:
                    existing.earnings_beat_rate = round(beat_rate, 1) if beat_rate else None
                    return self.save_fundamentals(existing)
                else:
                    fundamentals = SymbolFundamentals(
                        symbol=symbol,
                        earnings_beat_rate=round(beat_rate, 1) if beat_rate else None,
                        data_source="calculated"
                    )
                    return self.save_fundamentals(fundamentals)

        except Exception as e:
            logger.error(f"Fehler beim Berechnen der Beat Rate für {symbol}: {e}")
            return False

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_symbol_count(self) -> int:
        """Anzahl der Symbole mit Fundamentaldaten"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM symbol_fundamentals")
                return cursor.fetchone()[0]

    def get_sectors(self) -> List[str]:
        """Liste aller vorhandenen Sektoren"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT sector FROM symbol_fundamentals
                    WHERE sector IS NOT NULL ORDER BY sector
                """)
                return [row[0] for row in cursor.fetchall()]

    def get_statistics(self) -> Dict[str, Any]:
        """Gibt Statistiken über die Fundamentaldaten zurück"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Gesamt
                cursor.execute("SELECT COUNT(*) FROM symbol_fundamentals")
                total = cursor.fetchone()[0]

                # Nach Sektor
                cursor.execute("""
                    SELECT sector, COUNT(*)
                    FROM symbol_fundamentals
                    WHERE sector IS NOT NULL
                    GROUP BY sector ORDER BY COUNT(*) DESC
                """)
                by_sector = dict(cursor.fetchall())

                # Nach Market Cap
                cursor.execute("""
                    SELECT market_cap_category, COUNT(*)
                    FROM symbol_fundamentals
                    WHERE market_cap_category IS NOT NULL
                    GROUP BY market_cap_category
                """)
                by_market_cap = dict(cursor.fetchall())

                # Stability Coverage
                cursor.execute("""
                    SELECT COUNT(*) FROM symbol_fundamentals
                    WHERE stability_score IS NOT NULL
                """)
                with_stability = cursor.fetchone()[0]

        return {
            "total_symbols": total,
            "by_sector": by_sector,
            "by_market_cap": by_market_cap,
            "with_stability_score": with_stability,
            "stability_coverage_pct": round(with_stability / total * 100, 1) if total > 0 else 0
        }

    # =========================================================================
    # Helpers
    # =========================================================================

    def delete_symbol(self, symbol: str) -> bool:
        """Löscht Fundamentaldaten für ein Symbol"""
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM symbol_fundamentals WHERE symbol = ?", (symbol,))
                deleted = cursor.rowcount > 0
                conn.commit()

        if deleted:
            logger.info(f"Fundamentals für {symbol} gelöscht")
        return deleted

    def clear_all(self) -> int:
        """Löscht alle Fundamentaldaten (Vorsicht!)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM symbol_fundamentals")
                deleted = cursor.rowcount
                conn.commit()

        logger.warning(f"Alle {deleted} Fundamentals-Einträge gelöscht")
        return deleted

    # =========================================================================
    # ASYNC WRAPPERS (für non-blocking I/O in async contexts)
    # =========================================================================
    # Diese Methoden wrappen die synchronen SQLite-Operationen mit
    # run_in_executor() um den Event-Loop nicht zu blockieren.

    async def get_fundamentals_async(
        self,
        symbol: str,
        executor: Optional[ThreadPoolExecutor] = None
    ) -> Optional[SymbolFundamentals]:
        """
        Async wrapper für get_fundamentals().

        Führt die SQLite-Operation in einem ThreadPoolExecutor aus,
        um den async Event-Loop nicht zu blockieren.

        Args:
            symbol: Ticker-Symbol
            executor: Optional ThreadPoolExecutor (default: None = default executor)

        Returns:
            SymbolFundamentals oder None
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.get_fundamentals, symbol)
        )

    async def get_fundamentals_batch_async(
        self,
        symbols: List[str],
        executor: Optional[ThreadPoolExecutor] = None
    ) -> Dict[str, SymbolFundamentals]:
        """
        Async wrapper für get_fundamentals_batch().

        Args:
            symbols: Liste von Ticker-Symbolen
            executor: Optional ThreadPoolExecutor

        Returns:
            Dict mit {symbol: SymbolFundamentals}
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.get_fundamentals_batch, symbols)
        )

    async def save_fundamentals_async(
        self,
        fundamentals: SymbolFundamentals,
        executor: Optional[ThreadPoolExecutor] = None
    ) -> bool:
        """
        Async wrapper für save_fundamentals().

        Args:
            fundamentals: SymbolFundamentals Objekt
            executor: Optional ThreadPoolExecutor

        Returns:
            True bei Erfolg
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.save_fundamentals, fundamentals)
        )

    async def save_fundamentals_batch_async(
        self,
        fundamentals_list: List[SymbolFundamentals],
        executor: Optional[ThreadPoolExecutor] = None
    ) -> int:
        """
        Async wrapper für save_fundamentals_batch().

        Args:
            fundamentals_list: Liste von SymbolFundamentals Objekten
            executor: Optional ThreadPoolExecutor

        Returns:
            Anzahl erfolgreich gespeicherter Einträge
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.save_fundamentals_batch, fundamentals_list)
        )


# =============================================================================
# SINGLETON & CONVENIENCE FUNCTIONS
# =============================================================================

_default_manager: Optional[SymbolFundamentalsManager] = None
_manager_lock = threading.Lock()


def get_fundamentals_manager(db_path: Optional[Path] = None) -> SymbolFundamentalsManager:
    """
    Gibt globale SymbolFundamentalsManager Instanz zurück.

    Thread-safe Singleton-Pattern.
    """
    global _default_manager

    with _manager_lock:
        if _default_manager is None:
            _default_manager = SymbolFundamentalsManager(db_path)
        return _default_manager


def reset_fundamentals_manager() -> None:
    """Setzt den globalen Manager zurück (für Tests)"""
    global _default_manager
    with _manager_lock:
        _default_manager = None
