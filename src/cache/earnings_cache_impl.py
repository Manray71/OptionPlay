# OptionPlay - Earnings Cache
# ============================
# Cache für Earnings-Daten um API-Calls zu minimieren

import json
import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Callable, TypeVar, Any
from enum import Enum
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Type variable für retry decorator
T = TypeVar('T')


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    Decorator für Retry-Logik bei Netzwerkfehlern.
    
    Args:
        max_retries: Maximale Anzahl Versuche
        delay: Initiale Verzögerung in Sekunden
        backoff_factor: Multiplikator für exponentielles Backoff
        exceptions: Tuple von Exception-Typen die einen Retry auslösen
        
    Returns:
        Decorator-Funktion
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.warning(
                            f"{func.__name__} failed after {max_retries} attempts: {e}"
                        )
            
            # Gib None zurück statt Exception zu werfen (für graceful degradation)
            return None
        return wrapper
    return decorator


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CACHE_FILE = Path.home() / ".optionplay" / "earnings_cache.json"
DEFAULT_CACHE_MAX_AGE_HOURS = 672  # 4 Wochen (28 Tage * 24 Stunden)


class EarningsSource(Enum):
    """Datenquelle für Earnings"""
    YFINANCE = "yfinance"
    YAHOO_SCRAPE = "yahoo_scrape"
    TRADIER = "tradier"
    MARKETDATA = "marketdata"
    MANUAL = "manual"
    UNKNOWN = "unknown"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class EarningsInfo:
    """Earnings-Information für ein Symbol"""
    symbol: str
    earnings_date: Optional[str]  # ISO Format: YYYY-MM-DD
    days_to_earnings: Optional[int]
    source: EarningsSource
    updated_at: str  # ISO Format Timestamp
    confirmed: bool = False  # True wenn Datum bestätigt
    
    def is_safe(self, min_days: int = 60, unknown_is_safe: bool = False) -> bool:
        """
        Prüft ob genug Abstand zu Earnings.

        Args:
            min_days: Mindestabstand zu Earnings in Tagen
            unknown_is_safe: Wie unbekannte Earnings behandelt werden sollen.
                             False (default): Konservativ - unbekannt = nicht sicher
                             True: Permissiv - unbekannt = akzeptieren

        Returns:
            True wenn sicher, False wenn Earnings zu nah oder unbekannt
        """
        if self.days_to_earnings is None:
            return unknown_is_safe
        return self.days_to_earnings >= min_days
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'earnings_date': self.earnings_date,
            'days_to_earnings': self.days_to_earnings,
            'source': self.source.value,
            'updated_at': self.updated_at,
            'confirmed': self.confirmed,
            'is_safe_60d': self.is_safe(60, unknown_is_safe=False)
        }


@dataclass
class EarningsCacheEntry:
    """Cache-Eintrag für ein Symbol"""
    earnings_date: Optional[str]
    days_to_earnings: Optional[int]
    source: str
    updated: str
    confirmed: bool = False


# =============================================================================
# EARNINGS CACHE CLASS
# =============================================================================

class EarningsCache:
    """
    Persistenter Cache für Earnings-Daten.
    
    Features:
    - Automatisches Laden/Speichern (JSON)
    - TTL-basierte Invalidierung (default: 24h)
    - Mehrere Datenquellen unterstützt
    - Thread-safe für einfache Verwendung
    
    Verwendung:
        cache = EarningsCache()
        
        # Prüfen ob im Cache
        info = cache.get("AAPL")
        if info:
            print(f"AAPL Earnings: {info.earnings_date}")
        
        # Speichern
        cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        
        # Bulk-Abfrage
        results = cache.get_many(["AAPL", "MSFT", "GOOGL"])
    """
    
    def __init__(
        self, 
        cache_file: Optional[Path] = None,
        max_age_hours: int = DEFAULT_CACHE_MAX_AGE_HOURS
    ):
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self.max_age_hours = max_age_hours
        self._cache: Dict[str, EarningsCacheEntry] = {}
        self._lock = threading.RLock()  # Reentrant lock für Thread-Safety
        self._ensure_directory()
        self._load_cache()
    
    @contextmanager
    def _cache_lock(self):
        """Context manager für Thread-safe Cache-Zugriff."""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()
    
    def _ensure_directory(self):
        """Erstellt Cache-Verzeichnis falls nötig"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_cache(self):
        """Lädt Cache von Disk (thread-safe)."""
        with self._cache_lock():
            if not self.cache_file.exists():
                self._cache = {}
                return
            
            try:
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                
                self._cache = {}
                for symbol, entry in data.items():
                    self._cache[symbol.upper()] = EarningsCacheEntry(
                        earnings_date=entry.get("earnings_date"),
                        days_to_earnings=entry.get("days_to_earnings"),
                        source=entry.get("source", "unknown"),
                        updated=entry.get("updated", ""),
                        confirmed=entry.get("confirmed", False)
                    )
                
                logger.debug(f"Earnings cache loaded: {len(self._cache)} entries")
                
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load earnings cache: {e}")
                self._cache = {}
    
    def _save_cache(self):
        """
        Speichert Cache auf Disk (thread-safe mit Atomic Write).
        
        Verwendet eine temporäre Datei und atomisches Umbenennen,
        um Datenkorruption bei gleichzeitigen Schreibvorgängen zu vermeiden.
        """
        with self._cache_lock():
            try:
                data = {}
                for symbol, entry in self._cache.items():
                    data[symbol] = {
                        "earnings_date": entry.earnings_date,
                        "days_to_earnings": entry.days_to_earnings,
                        "source": entry.source,
                        "updated": entry.updated,
                        "confirmed": entry.confirmed
                    }
                
                # Atomic write: erst in temp-Datei schreiben, dann umbenennen
                temp_file = self.cache_file.with_suffix('.tmp')
                with open(temp_file, "w") as f:
                    json.dump(data, f, indent=2)
                
                # Atomisches Umbenennen (auf den meisten Systemen)
                temp_file.replace(self.cache_file)
                
                logger.debug(f"Earnings cache saved: {len(data)} entries")
                
            except IOError as e:
                logger.error(f"Could not save earnings cache: {e}")
    
    def _is_fresh(self, entry: EarningsCacheEntry) -> bool:
        """
        Prüft ob Cache-Eintrag noch gültig ist.

        Einträge OHNE Earnings-Datum (None) werden kürzer gecacht (24h),
        da dies oft bedeutet, dass der API-Abruf fehlgeschlagen ist.
        """
        if not entry.updated:
            return False

        try:
            updated = datetime.fromisoformat(entry.updated)
            age_hours = (datetime.now() - updated).total_seconds() / 3600

            # Einträge ohne Earnings-Datum nur 24h cachen (API könnte gefailed sein)
            if entry.earnings_date is None:
                max_age = min(24, self.max_age_hours)
                return age_hours < max_age

            return age_hours < self.max_age_hours
        except (ValueError, TypeError):
            return False
    
    def _calculate_days_to_earnings(self, earnings_date_str: Optional[str]) -> Optional[int]:
        """Berechnet Tage bis Earnings"""
        if not earnings_date_str:
            return None
        
        try:
            earnings_date = datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            delta = (earnings_date - today).days
            return delta if delta >= 0 else None  # Vergangene Earnings ignorieren
        except ValueError:
            return None
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    def get(self, symbol: str) -> Optional[EarningsInfo]:
        """
        Holt Earnings-Info aus Cache.
        
        Args:
            symbol: Ticker-Symbol
            
        Returns:
            EarningsInfo oder None wenn nicht im Cache oder abgelaufen
        """
        symbol = symbol.upper()
        entry = self._cache.get(symbol)
        
        if not entry or not self._is_fresh(entry):
            return None
        
        # Tage neu berechnen (könnte sich geändert haben seit Cache)
        days = self._calculate_days_to_earnings(entry.earnings_date)
        
        return EarningsInfo(
            symbol=symbol,
            earnings_date=entry.earnings_date,
            days_to_earnings=days,
            source=EarningsSource(entry.source) if entry.source in [e.value for e in EarningsSource] else EarningsSource.UNKNOWN,
            updated_at=entry.updated,
            confirmed=entry.confirmed
        )
    
    def set(
        self, 
        symbol: str, 
        earnings_date: Optional[str],
        days_to_earnings: Optional[int] = None,
        source: EarningsSource = EarningsSource.UNKNOWN,
        confirmed: bool = False
    ):
        """
        Speichert Earnings-Info im Cache.
        
        Args:
            symbol: Ticker-Symbol
            earnings_date: Datum im Format YYYY-MM-DD (oder None)
            days_to_earnings: Optional - wird automatisch berechnet wenn None
            source: Datenquelle
            confirmed: True wenn Datum bestätigt ist
        """
        symbol = symbol.upper()
        
        # Tage berechnen wenn nicht angegeben
        if days_to_earnings is None and earnings_date:
            days_to_earnings = self._calculate_days_to_earnings(earnings_date)
        
        self._cache[symbol] = EarningsCacheEntry(
            earnings_date=earnings_date,
            days_to_earnings=days_to_earnings,
            source=source.value,
            updated=datetime.now().isoformat(),
            confirmed=confirmed
        )
        
        self._save_cache()
    
    def get_many(self, symbols: List[str]) -> Dict[str, Optional[EarningsInfo]]:
        """
        Holt Earnings-Info für mehrere Symbole.
        
        Returns:
            Dict mit Symbol -> EarningsInfo (oder None)
        """
        return {symbol: self.get(symbol) for symbol in symbols}
    
    def set_many(self, entries: List[Tuple[str, Optional[str], EarningsSource]]):
        """
        Speichert mehrere Earnings-Einträge.
        
        Args:
            entries: Liste von (symbol, earnings_date, source) Tupeln
        """
        for symbol, earnings_date, source in entries:
            symbol = symbol.upper()
            days = self._calculate_days_to_earnings(earnings_date)
            
            self._cache[symbol] = EarningsCacheEntry(
                earnings_date=earnings_date,
                days_to_earnings=days,
                source=source.value,
                updated=datetime.now().isoformat(),
                confirmed=False
            )
        
        self._save_cache()
    
    def invalidate(self, symbol: str):
        """Entfernt Symbol aus Cache"""
        symbol = symbol.upper()
        if symbol in self._cache:
            del self._cache[symbol]
            self._save_cache()
    
    def invalidate_all(self):
        """Leert den gesamten Cache"""
        self._cache = {}
        self._save_cache()
    
    def get_stale_symbols(self) -> List[str]:
        """Gibt Liste der abgelaufenen Symbole zurück"""
        stale = []
        for symbol, entry in self._cache.items():
            if not self._is_fresh(entry):
                stale.append(symbol)
        return stale
    
    def get_missing_symbols(self, symbols: List[str]) -> List[str]:
        """Gibt Symbole zurück, die nicht im Cache sind oder abgelaufen"""
        missing = []
        for symbol in symbols:
            symbol = symbol.upper()
            entry = self._cache.get(symbol)
            if not entry or not self._is_fresh(entry):
                missing.append(symbol)
        return missing
    
    def stats(self) -> Dict:
        """Cache-Statistiken"""
        total = len(self._cache)
        fresh = sum(1 for e in self._cache.values() if self._is_fresh(e))
        with_date = sum(1 for e in self._cache.values() if e.earnings_date)
        
        return {
            "total_entries": total,
            "fresh_entries": fresh,
            "stale_entries": total - fresh,
            "with_earnings_date": with_date,
            "cache_file": str(self.cache_file),
            "max_age_hours": self.max_age_hours
        }
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, symbol: str) -> bool:
        return self.get(symbol) is not None


# =============================================================================
# EARNINGS FETCHER (mit Cache)
# =============================================================================

class EarningsFetcher:
    """
    Holt Earnings-Daten mit automatischem Caching.
    
    Unterstützte Quellen:
    - yfinance (primär)
    - Yahoo Finance Scraping (fallback)
    
    Verwendung:
        fetcher = EarningsFetcher()
        
        # Einzelnes Symbol
        info = fetcher.fetch("AAPL")
        
        # Mehrere Symbole (mit Caching)
        results = fetcher.fetch_many(["AAPL", "MSFT", "GOOGL"])
    """
    
    def __init__(self, cache: Optional[EarningsCache] = None):
        self.cache = cache or EarningsCache()
        self._yfinance_available = self._check_yfinance()
    
    def _check_yfinance(self) -> bool:
        """Prüft ob yfinance verfügbar ist"""
        try:
            import yfinance
            return True
        except ImportError:
            logger.warning("yfinance not installed - using fallback methods")
            return False
    
    def _fetch_yfinance_inner(self, symbol: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Interne Methode für yfinance-Abruf (wird von _fetch_yfinance mit Retry aufgerufen).
        """
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Versuche calendar
        if hasattr(ticker, 'calendar') and ticker.calendar is not None:
            cal = ticker.calendar
            
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                earnings_list = cal['Earnings Date']
                
                if earnings_list and len(earnings_list) > 0:
                    next_earnings = earnings_list[0]
                    
                    # Konvertiere zu datetime
                    if hasattr(next_earnings, 'year'):
                        if not hasattr(next_earnings, 'hour'):
                            next_earnings = datetime.combine(
                                next_earnings, 
                                datetime.min.time()
                            )
                    
                    # Timezone entfernen
                    if hasattr(next_earnings, 'tzinfo') and next_earnings.tzinfo:
                        next_earnings = next_earnings.replace(tzinfo=None)
                    
                    today = datetime.now().replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    days_until = (next_earnings - today).days
                    
                    return next_earnings.strftime("%Y-%m-%d"), days_until
        
        return None, None
    
    def _fetch_yfinance(self, symbol: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Holt Earnings via yfinance mit Retry-Logik.
        
        Versucht bis zu 3x mit exponentiellem Backoff bei Netzwerkfehlern.
        """
        if not self._yfinance_available:
            return None, None
        
        # Retry-Wrapper inline (da wir eine Methode sind)
        max_retries = 3
        delay = 0.5
        
        for attempt in range(max_retries):
            try:
                return self._fetch_yfinance_inner(symbol)
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(
                        f"yfinance retry for {symbol} (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(delay * (attempt + 1))
                else:
                    logger.warning(f"yfinance failed for {symbol} after {max_retries} attempts: {e}")
        
        return None, None
    
    def _fetch_yahoo_scrape(self, symbol: str) -> Tuple[Optional[str], Optional[int]]:
        """Fallback: Scraped Yahoo Finance"""
        import urllib.request
        import re
        
        try:
            url = f"https://finance.yahoo.com/quote/{symbol}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            with urllib.request.urlopen(req, timeout=5) as response:
                html = response.read().decode('utf-8')
            
            # Suche nach "Earnings Date" Pattern
            pattern = r'Earnings Date.*?(\w{3} \d{1,2}, \d{4})'
            match = re.search(pattern, html, re.DOTALL)
            
            if match:
                date_str = match.group(1)
                earnings_date = datetime.strptime(date_str, "%b %d, %Y")
                days_until = (earnings_date - datetime.now()).days
                return earnings_date.strftime("%Y-%m-%d"), days_until
            
            return None, None
            
        except Exception as e:
            logger.debug(f"Yahoo scrape error for {symbol}: {e}")
            return None, None
    
    def fetch(self, symbol: str, force_refresh: bool = False) -> EarningsInfo:
        """
        Holt Earnings-Info für ein Symbol.
        
        Args:
            symbol: Ticker-Symbol
            force_refresh: True um Cache zu ignorieren
            
        Returns:
            EarningsInfo (kann earnings_date=None haben wenn nicht gefunden)
        """
        symbol = symbol.upper()
        
        # Cache prüfen
        if not force_refresh:
            cached = self.cache.get(symbol)
            if cached:
                return cached
        
        # yfinance versuchen
        earnings_date, days_until = self._fetch_yfinance(symbol)
        source = EarningsSource.YFINANCE
        
        # Fallback zu Scraping
        if earnings_date is None:
            earnings_date, days_until = self._fetch_yahoo_scrape(symbol)
            source = EarningsSource.YAHOO_SCRAPE
        
        # Im Cache speichern
        self.cache.set(symbol, earnings_date, days_until, source)
        
        return EarningsInfo(
            symbol=symbol,
            earnings_date=earnings_date,
            days_to_earnings=days_until,
            source=source,
            updated_at=datetime.now().isoformat(),
            confirmed=False
        )
    
    def fetch_many(
        self, 
        symbols: List[str], 
        force_refresh: bool = False,
        progress_callback=None
    ) -> Dict[str, EarningsInfo]:
        """
        Holt Earnings-Info für mehrere Symbole.
        
        Args:
            symbols: Liste von Ticker-Symbolen
            force_refresh: True um Cache zu ignorieren
            progress_callback: Optional callback(current, total, symbol)
            
        Returns:
            Dict mit Symbol -> EarningsInfo
        """
        results = {}
        total = len(symbols)
        
        for i, symbol in enumerate(symbols):
            results[symbol.upper()] = self.fetch(symbol, force_refresh)
            
            if progress_callback:
                progress_callback(i + 1, total, symbol)
        
        return results
    
    def filter_by_earnings(
        self, 
        symbols: List[str], 
        min_days: int = 60
    ) -> Tuple[List[str], List[str]]:
        """
        Filtert Symbole nach Earnings-Abstand.
        
        Args:
            symbols: Liste von Ticker-Symbolen
            min_days: Mindestabstand zu Earnings
            
        Returns:
            (safe_symbols, excluded_symbols) Tupel
        """
        safe = []
        excluded = []
        
        for symbol in symbols:
            info = self.fetch(symbol)
            
            if info.is_safe(min_days):
                safe.append(symbol)
            else:
                excluded.append(symbol)
        
        return safe, excluded


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Globale Cache-Instanz
_default_cache: Optional[EarningsCache] = None
_default_fetcher: Optional[EarningsFetcher] = None


def get_earnings_cache() -> EarningsCache:
    """Gibt globale Cache-Instanz zurück"""
    global _default_cache
    if _default_cache is None:
        _default_cache = EarningsCache()
    return _default_cache


def get_earnings_fetcher() -> EarningsFetcher:
    """Gibt globale Fetcher-Instanz zurück"""
    global _default_fetcher
    if _default_fetcher is None:
        _default_fetcher = EarningsFetcher(get_earnings_cache())
    return _default_fetcher


def get_earnings(symbol: str) -> EarningsInfo:
    """
    Convenience-Funktion für schnelle Earnings-Abfrage.
    
    Beispiel:
        >>> info = get_earnings("AAPL")
        >>> print(f"Earnings in {info.days_to_earnings} Tagen")
    """
    return get_earnings_fetcher().fetch(symbol)


def is_earnings_safe(symbol: str, min_days: int = 60) -> bool:
    """
    Prüft ob Symbol sicher vor Earnings ist.
    
    Beispiel:
        >>> if is_earnings_safe("AAPL", 60):
        ...     print("OK für Bull-Put-Spread")
    """
    info = get_earnings_fetcher().fetch(symbol)
    return info.is_safe(min_days)
