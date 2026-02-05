# OptionPlay - Data Collector
# ===========================
# Automatische Datensammlung für kontinuierliches Training

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Callable
from pathlib import Path

from .tracking import (
    TradeTracker,
    PriceBar,
    VixDataPoint,
)

logger = logging.getLogger(__name__)


@dataclass
class CollectionConfig:
    """Konfiguration für Datensammlung"""
    # Symbole
    symbols: List[str] = field(default_factory=list)
    watchlist_path: Optional[str] = None  # Pfad zur watchlist.txt

    # Zeitraum
    lookback_days: int = 260  # ~1 Jahr Handelstage
    update_mode: str = "incremental"  # "full" oder "incremental"

    # API-Limits
    delay_between_symbols: float = 0.1  # Sekunden
    batch_size: int = 50  # Symbole pro Batch

    # Speicher
    db_path: Optional[str] = None  # Default: ~/.optionplay/trades.db


@dataclass
class CollectionResult:
    """Ergebnis einer Datensammlung"""
    timestamp: datetime
    symbols_requested: int
    symbols_collected: int
    symbols_failed: List[str]
    total_bars_collected: int
    vix_points_collected: int
    duration_seconds: float
    errors: List[str]

    @property
    def success_rate(self) -> float:
        if self.symbols_requested == 0:
            return 0.0
        return (self.symbols_collected / self.symbols_requested) * 100

    def __str__(self) -> str:
        return (
            f"Collection completed: {self.symbols_collected}/{self.symbols_requested} symbols "
            f"({self.success_rate:.1f}%), {self.total_bars_collected} bars, "
            f"{self.vix_points_collected} VIX points in {self.duration_seconds:.1f}s"
        )


class DataCollector:
    """
    Sammelt historische Daten und speichert sie im TradeTracker.

    Unterstützt:
    - Tägliche Updates (inkrementell)
    - Initiale Befüllung (full)
    - Watchlist aus Datei
    - VIX-Historie

    Usage:
        from src.backtesting import DataCollector, CollectionConfig
        from src.data_providers.marketdata import MarketDataProvider

        # Provider erstellen
        provider = MarketDataProvider(api_key="...")
        await provider.connect()

        # Collector erstellen
        config = CollectionConfig(
            symbols=["AAPL", "MSFT", "GOOGL"],
            lookback_days=260,
        )
        collector = DataCollector(config)

        # Daten sammeln
        result = await collector.collect(provider)
        print(result)

        # Oder mit Watchlist
        config = CollectionConfig(watchlist_path="~/.optionplay/watchlist.txt")
        result = await collector.collect(provider)
    """

    def __init__(self, config: Optional[CollectionConfig] = None):
        self.config = config or CollectionConfig()
        self._tracker: Optional[TradeTracker] = None

    @property
    def tracker(self) -> TradeTracker:
        """Lazy-Loading des Trackers"""
        if self._tracker is None:
            self._tracker = TradeTracker(db_path=self.config.db_path)
        return self._tracker

    def _load_watchlist(self) -> List[str]:
        """Lädt Symbole aus Watchlist-Datei"""
        if not self.config.watchlist_path:
            return []

        path = Path(self.config.watchlist_path).expanduser()
        if not path.exists():
            logger.warning(f"Watchlist not found: {path}")
            return []

        symbols = []
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip Kommentare und leere Zeilen
                if line and not line.startswith('#'):
                    symbols.append(line.upper())

        logger.info(f"Loaded {len(symbols)} symbols from watchlist")
        return symbols

    def _get_symbols(self) -> List[str]:
        """Kombiniert konfigurierte Symbole und Watchlist"""
        symbols = set()

        # Direkt konfigurierte Symbole
        symbols.update(s.upper() for s in self.config.symbols)

        # Watchlist
        if self.config.watchlist_path:
            symbols.update(self._load_watchlist())

        return sorted(symbols)

    async def collect(
        self,
        provider: Any,  # MarketDataProvider
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> CollectionResult:
        """
        Führt die Datensammlung durch.

        Args:
            provider: MarketDataProvider Instanz (muss connected sein)
            progress_callback: Optional Callback (symbol, current, total)

        Returns:
            CollectionResult mit Statistiken
        """
        start_time = datetime.now()
        symbols = self._get_symbols()

        if not symbols:
            logger.warning("No symbols to collect")
            return CollectionResult(
                timestamp=start_time,
                symbols_requested=0,
                symbols_collected=0,
                symbols_failed=[],
                total_bars_collected=0,
                vix_points_collected=0,
                duration_seconds=0.0,
                errors=["No symbols configured"],
            )

        logger.info(f"Starting collection for {len(symbols)} symbols")

        # Ergebnisse
        collected = 0
        failed = []
        total_bars = 0
        errors = []

        # VIX sammeln
        vix_count = await self._collect_vix(provider)

        # Symbole in Batches
        for batch_start in range(0, len(symbols), self.config.batch_size):
            batch = symbols[batch_start:batch_start + self.config.batch_size]

            for i, symbol in enumerate(batch):
                global_index = batch_start + i

                if progress_callback:
                    progress_callback(symbol, global_index + 1, len(symbols))

                try:
                    bars_count = await self._collect_symbol(provider, symbol)
                    if bars_count > 0:
                        collected += 1
                        total_bars += bars_count
                    else:
                        failed.append(symbol)
                        errors.append(f"{symbol}: No data returned")

                except Exception as e:
                    failed.append(symbol)
                    errors.append(f"{symbol}: {str(e)}")
                    logger.warning(f"Failed to collect {symbol}: {e}")

                # Rate limiting
                if i < len(batch) - 1:
                    await asyncio.sleep(self.config.delay_between_symbols)

        duration = (datetime.now() - start_time).total_seconds()

        result = CollectionResult(
            timestamp=start_time,
            symbols_requested=len(symbols),
            symbols_collected=collected,
            symbols_failed=failed,
            total_bars_collected=total_bars,
            vix_points_collected=vix_count,
            duration_seconds=duration,
            errors=errors[:20],  # Limit errors
        )

        logger.info(str(result))
        return result

    async def _collect_symbol(
        self,
        provider: Any,
        symbol: str,
    ) -> int:
        """
        Sammelt Daten für ein Symbol.

        Returns:
            Anzahl der gesammelten Bars
        """
        # Prüfe ob inkrementelles Update möglich
        existing_range = self.tracker.get_price_data_range(symbol)
        from_date = None

        if self.config.update_mode == "incremental" and existing_range:
            # Nur ab letztem Datum sammeln
            from_date = existing_range[1]
            days_needed = (date.today() - from_date).days + 5  # Buffer
            if days_needed <= 0:
                logger.debug(f"{symbol}: Already up to date")
                return 0
        else:
            days_needed = self.config.lookback_days

        # Daten vom Provider holen
        bars = await provider.get_historical(symbol, days=days_needed)

        if not bars:
            return 0

        # Konvertiere zu PriceBar
        price_bars = []
        for bar in bars:
            # Filter: nur ab from_date wenn inkrementell
            bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])
            if from_date and bar_date <= from_date:
                continue

            price_bars.append(PriceBar(
                date=bar_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            ))

        if not price_bars:
            return 0

        # Speichern (mit Merge)
        count = self.tracker.store_price_data(
            symbol,
            price_bars,
            merge=True,
        )

        logger.debug(f"{symbol}: Collected {len(price_bars)} new bars")
        return count

    async def _collect_vix(self, provider: Any) -> int:
        """
        Sammelt VIX-Historie.

        Returns:
            Anzahl der gesammelten Datenpunkte
        """
        try:
            # Prüfe bestehende VIX-Daten
            vix_range = self.tracker.get_vix_range()
            days_needed = self.config.lookback_days

            if self.config.update_mode == "incremental" and vix_range:
                days_needed = (date.today() - vix_range[1]).days + 5

            if days_needed <= 0:
                logger.debug("VIX data already up to date")
                return 0

            # VIX-Candles holen
            bars = await provider.get_index_candles("VIX", days=days_needed)

            if not bars:
                logger.warning("Could not fetch VIX data")
                return 0

            # Konvertiere zu VixDataPoint
            vix_points = []
            for bar in bars:
                bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])
                vix_points.append(VixDataPoint(
                    date=bar_date,
                    value=bar.close,
                ))

            count = self.tracker.store_vix_data(vix_points)
            logger.info(f"Collected {count} VIX data points")
            return count

        except Exception as e:
            logger.warning(f"Failed to collect VIX: {e}")
            return 0

    async def collect_single(
        self,
        provider: Any,
        symbol: str,
        days: Optional[int] = None,
    ) -> int:
        """
        Sammelt Daten für ein einzelnes Symbol.

        Args:
            provider: MarketDataProvider
            symbol: Ticker-Symbol
            days: Optionale Anzahl Tage (default: config.lookback_days)

        Returns:
            Anzahl gesammelter Bars
        """
        original_days = self.config.lookback_days
        if days:
            self.config.lookback_days = days

        try:
            return await self._collect_symbol(provider, symbol)
        finally:
            self.config.lookback_days = original_days

    def get_collection_status(self) -> Dict[str, Any]:
        """
        Gibt Status der gesammelten Daten zurück.

        Returns:
            Dictionary mit Statistiken
        """
        symbols = self.tracker.list_symbols_with_price_data()
        vix_range = self.tracker.get_vix_range()
        stats = self.tracker.get_storage_stats()

        # Finde veraltete Symbole
        stale_symbols = []
        cutoff = date.today() - timedelta(days=7)

        for s in symbols:
            end_date = date.fromisoformat(s['end_date'])
            if end_date < cutoff:
                stale_symbols.append({
                    'symbol': s['symbol'],
                    'last_date': s['end_date'],
                    'days_old': (date.today() - end_date).days,
                })

        return {
            'total_symbols': len(symbols),
            'symbols': symbols,
            'stale_symbols': stale_symbols,
            'vix_range': {
                'start': vix_range[0].isoformat() if vix_range else None,
                'end': vix_range[1].isoformat() if vix_range else None,
            },
            'storage': stats,
        }


def format_collection_status(status: Dict[str, Any]) -> str:
    """Formatiert Collection-Status als lesbaren Text"""
    lines = [
        "=" * 50,
        "DATA COLLECTION STATUS",
        "=" * 50,
        "",
        f"Total Symbols: {status['total_symbols']}",
        f"Total Bars: {status['storage']['total_price_bars']}",
        f"Database Size: {status['storage']['database_size_mb']:.2f} MB",
        "",
    ]

    if status['vix_range']['start']:
        lines.append(f"VIX Data: {status['vix_range']['start']} to {status['vix_range']['end']}")
        lines.append(f"VIX Points: {status['storage']['vix_data_points']}")
    else:
        lines.append("VIX Data: None")

    if status['stale_symbols']:
        lines.extend(["", "STALE SYMBOLS (>7 days old):", "-" * 30])
        for s in status['stale_symbols'][:10]:
            lines.append(f"  {s['symbol']}: last update {s['last_date']} ({s['days_old']} days)")
        if len(status['stale_symbols']) > 10:
            lines.append(f"  ... and {len(status['stale_symbols']) - 10} more")

    return "\n".join(lines)


async def run_daily_collection(
    api_key: str,
    watchlist_path: Optional[str] = None,
    symbols: Optional[List[str]] = None,
) -> CollectionResult:
    """
    Convenience-Funktion für tägliche Datensammlung.

    Args:
        api_key: Marketdata.app API Key
        watchlist_path: Pfad zur Watchlist-Datei
        symbols: Optional Liste von Symbolen

    Returns:
        CollectionResult
    """
    # Import hier um zirkuläre Imports zu vermeiden
    try:
        from ..data_providers.marketdata import MarketDataProvider, MarketDataConfig
    except ImportError:
        from src.data_providers.marketdata import MarketDataProvider, MarketDataConfig

    # Provider erstellen
    config = MarketDataConfig(api_key=api_key)
    provider = MarketDataProvider(config)

    try:
        await provider.connect()

        # Collector konfigurieren
        collection_config = CollectionConfig(
            symbols=symbols or [],
            watchlist_path=watchlist_path,
            update_mode="incremental",
        )
        collector = DataCollector(collection_config)

        # Sammeln
        result = await collector.collect(provider)
        return result

    finally:
        await provider.close()


def create_collector(
    symbols: Optional[List[str]] = None,
    watchlist_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> DataCollector:
    """Factory-Funktion für DataCollector"""
    config = CollectionConfig(
        symbols=symbols or [],
        watchlist_path=watchlist_path,
        db_path=db_path,
    )
    return DataCollector(config)
