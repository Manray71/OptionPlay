# OptionPlay - IV Cache & Calculator
# ====================================
# Implied Volatility History, IV-Rank und IV-Perzentil

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CACHE_FILE = Path.home() / ".optionplay" / "iv_cache.json"
DEFAULT_CACHE_MAX_AGE_DAYS = 14  # Cache-Eintrag gilt als "fresh" für 14 Tage
IV_HISTORY_DAYS = 252  # 1 Jahr Trading-Tage


class IVSource(Enum):
    """Datenquelle für IV"""
    TRADIER = "tradier"
    YAHOO = "yahoo"
    IBKR = "ibkr"
    MARKETDATA = "marketdata"
    MANUAL = "manual"
    UNKNOWN = "unknown"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class IVData:
    """IV-Daten für ein Symbol"""
    symbol: str
    current_iv: Optional[float]  # Aktuelle IV (dezimal, z.B. 0.35 = 35%)
    iv_rank: Optional[float]     # 0-100%
    iv_percentile: Optional[float]  # 0-100%
    iv_high_52w: Optional[float]  # 52-Wochen-Hoch
    iv_low_52w: Optional[float]   # 52-Wochen-Tief
    data_points: int              # Anzahl historischer Datenpunkte
    source: IVSource
    updated_at: str
    
    def is_elevated(self, threshold: float = 50.0) -> bool:
        """Prüft ob IV erhöht ist (IV-Rank > threshold)"""
        if self.iv_rank is None:
            return False
        return self.iv_rank >= threshold
    
    def is_low(self, threshold: float = 30.0) -> bool:
        """Prüft ob IV niedrig ist (IV-Rank < threshold)"""
        if self.iv_rank is None:
            return False
        return self.iv_rank < threshold
    
    def iv_status(self) -> str:
        """Gibt IV-Status als String zurück"""
        if self.iv_rank is None:
            return "unknown"
        if self.iv_rank >= 70:
            return "very_high"
        elif self.iv_rank >= 50:
            return "elevated"
        elif self.iv_rank >= 30:
            return "normal"
        else:
            return "low"
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'current_iv': round(self.current_iv * 100, 1) if self.current_iv else None,
            'current_iv_decimal': self.current_iv,
            'iv_rank': round(self.iv_rank, 1) if self.iv_rank is not None else None,
            'iv_percentile': round(self.iv_percentile, 1) if self.iv_percentile is not None else None,
            'iv_high_52w': round(self.iv_high_52w * 100, 1) if self.iv_high_52w else None,
            'iv_low_52w': round(self.iv_low_52w * 100, 1) if self.iv_low_52w else None,
            'iv_status': self.iv_status(),
            'data_points': self.data_points,
            'source': self.source.value,
            'updated_at': self.updated_at
        }


@dataclass 
class IVCacheEntry:
    """Cache-Eintrag für IV-History eines Symbols"""
    iv_history: List[float]  # Liste von IV-Werten (dezimal)
    iv_high: Optional[float]
    iv_low: Optional[float]
    data_points: int
    source: str
    updated: str


# =============================================================================
# IV CALCULATIONS
# =============================================================================

def calculate_iv_rank(current_iv: float, iv_history: List[float]) -> Optional[float]:
    """
    Berechnet IV-Rank.
    
    IV-Rank = (Current IV - 52w Low) / (52w High - 52w Low) * 100
    
    Zeigt wo die aktuelle IV im Vergleich zum 52-Wochen-Range liegt.
    
    Args:
        current_iv: Aktuelle IV (dezimal)
        iv_history: Liste historischer IV-Werte (dezimal)
        
    Returns:
        IV-Rank (0-100) oder None
    """
    if not iv_history or len(iv_history) < 20:
        return None
    if current_iv is None or current_iv <= 0:
        return None
    
    iv_high = max(iv_history)
    iv_low = min(iv_history)
    
    if iv_high == iv_low:
        return 50.0  # Keine Variation
    
    iv_rank = (current_iv - iv_low) / (iv_high - iv_low) * 100
    return max(0.0, min(100.0, iv_rank))


def calculate_iv_percentile(current_iv: float, iv_history: List[float]) -> Optional[float]:
    """
    Berechnet IV-Perzentil.
    
    Zeigt an welchem Prozentsatz der historischen Tage die IV niedriger war.
    
    Args:
        current_iv: Aktuelle IV (dezimal)
        iv_history: Liste historischer IV-Werte (dezimal)
        
    Returns:
        IV-Perzentil (0-100) oder None
    """
    if not iv_history or len(iv_history) < 20:
        return None
    if current_iv is None or current_iv <= 0:
        return None
    
    days_below = sum(1 for iv in iv_history if iv < current_iv)
    percentile = days_below / len(iv_history) * 100
    return round(percentile, 1)


# =============================================================================
# IV CACHE CLASS
# =============================================================================

class IVCache:
    """
    Persistenter Cache für IV-History.
    
    Speichert 52-Wochen IV-History für schnelle IV-Rank Berechnungen.
    
    Features:
    - JSON-basierter persistenter Speicher
    - TTL-basierte Invalidierung (default: 14 Tage)
    - Automatische High/Low Berechnung
    
    Verwendung:
        cache = IVCache()
        
        # History abrufen
        history = cache.get_history("AAPL")
        
        # History aktualisieren
        cache.update_history("AAPL", [0.25, 0.28, 0.32, ...], IVSource.TRADIER)
        
        # Neuen IV-Wert hinzufügen
        cache.add_iv_point("AAPL", 0.30)
    """
    
    def __init__(
        self, 
        cache_file: Optional[Path] = None,
        max_age_days: int = DEFAULT_CACHE_MAX_AGE_DAYS
    ):
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self.max_age_days = max_age_days
        self._cache: Dict[str, IVCacheEntry] = {}
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
                    self._cache[symbol.upper()] = IVCacheEntry(
                        iv_history=entry.get("iv_history", []),
                        iv_high=entry.get("iv_high"),
                        iv_low=entry.get("iv_low"),
                        data_points=entry.get("data_points", 0),
                        source=entry.get("source", "unknown"),
                        updated=entry.get("updated", "")
                    )
                
                logger.debug(f"IV cache loaded: {len(self._cache)} symbols")
                
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load IV cache: {e}")
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
                        "iv_history": entry.iv_history,
                        "iv_high": entry.iv_high,
                        "iv_low": entry.iv_low,
                        "data_points": entry.data_points,
                        "source": entry.source,
                        "updated": entry.updated
                    }
                
                # Atomic write: erst in temp-Datei schreiben, dann umbenennen
                temp_file = self.cache_file.with_suffix('.tmp')
                with open(temp_file, "w") as f:
                    json.dump(data, f, indent=2)
                
                # Atomisches Umbenennen
                temp_file.replace(self.cache_file)
                
                logger.debug(f"IV cache saved: {len(data)} symbols")
                
            except IOError as e:
                logger.error(f"Could not save IV cache: {e}")
    
    def _is_fresh(self, entry: IVCacheEntry) -> bool:
        """Prüft ob Cache-Eintrag noch gültig ist"""
        if not entry.updated:
            return False
        
        try:
            updated = datetime.fromisoformat(entry.updated)
            age_days = (datetime.now() - updated).days
            return age_days < self.max_age_days
        except (ValueError, TypeError):
            return False
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    def get_history(self, symbol: str) -> List[float]:
        """
        Gibt IV-History für ein Symbol zurück.
        
        Returns:
            Liste von IV-Werten (dezimal) oder leere Liste
        """
        symbol = symbol.upper()
        entry = self._cache.get(symbol)
        
        if not entry or not self._is_fresh(entry):
            return []
        
        return entry.iv_history
    
    def get_iv_data(self, symbol: str, current_iv: Optional[float] = None) -> Optional[IVData]:
        """
        Gibt vollständige IV-Daten für ein Symbol zurück.
        
        Args:
            symbol: Ticker-Symbol
            current_iv: Aktuelle IV (optional, wird aus History genommen wenn nicht angegeben)
            
        Returns:
            IVData oder None
        """
        symbol = symbol.upper()
        entry = self._cache.get(symbol)
        
        if not entry or not entry.iv_history:
            return None
        
        # Current IV: entweder übergeben oder letzter Wert aus History
        if current_iv is None:
            current_iv = entry.iv_history[-1] if entry.iv_history else None
        
        if current_iv is None:
            return None
        
        iv_rank = calculate_iv_rank(current_iv, entry.iv_history)
        iv_percentile = calculate_iv_percentile(current_iv, entry.iv_history)
        
        return IVData(
            symbol=symbol,
            current_iv=current_iv,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            iv_high_52w=entry.iv_high,
            iv_low_52w=entry.iv_low,
            data_points=entry.data_points,
            source=IVSource(entry.source) if entry.source in [e.value for e in IVSource] else IVSource.UNKNOWN,
            updated_at=entry.updated
        )
    
    def update_history(
        self, 
        symbol: str, 
        iv_history: List[float],
        source: IVSource = IVSource.UNKNOWN
    ):
        """
        Aktualisiert die komplette IV-History für ein Symbol.
        
        Args:
            symbol: Ticker-Symbol
            iv_history: Liste von IV-Werten (dezimal, älteste zuerst)
            source: Datenquelle
        """
        symbol = symbol.upper()
        
        # Nur gültige IV-Werte behalten
        valid_history = [iv for iv in iv_history if iv and iv > 0]
        
        # Auf 252 Tage begrenzen (1 Jahr)
        if len(valid_history) > IV_HISTORY_DAYS:
            valid_history = valid_history[-IV_HISTORY_DAYS:]
        
        self._cache[symbol] = IVCacheEntry(
            iv_history=valid_history,
            iv_high=max(valid_history) if valid_history else None,
            iv_low=min(valid_history) if valid_history else None,
            data_points=len(valid_history),
            source=source.value,
            updated=datetime.now().isoformat()
        )
        
        self._save_cache()
        logger.debug(f"Updated IV history for {symbol}: {len(valid_history)} points")
    
    def add_iv_point(self, symbol: str, iv_value: float, source: IVSource = IVSource.UNKNOWN):
        """
        Fügt einen neuen IV-Wert zur History hinzu.
        
        Nützlich für tägliche Updates.
        
        Args:
            symbol: Ticker-Symbol
            iv_value: Neuer IV-Wert (dezimal)
            source: Datenquelle
        """
        symbol = symbol.upper()
        
        if iv_value is None or iv_value <= 0:
            return
        
        entry = self._cache.get(symbol)
        
        if entry:
            history = entry.iv_history.copy()
        else:
            history = []
        
        # Neuen Wert anhängen
        history.append(iv_value)
        
        # Auf 252 Tage begrenzen
        if len(history) > IV_HISTORY_DAYS:
            history = history[-IV_HISTORY_DAYS:]
        
        self._cache[symbol] = IVCacheEntry(
            iv_history=history,
            iv_high=max(history),
            iv_low=min(history),
            data_points=len(history),
            source=source.value,
            updated=datetime.now().isoformat()
        )
        
        self._save_cache()
    
    def is_fresh(self, symbol: str) -> bool:
        """Prüft ob Cache-Eintrag für Symbol noch gültig ist"""
        symbol = symbol.upper()
        entry = self._cache.get(symbol)
        return entry is not None and self._is_fresh(entry)
    
    def get_cache_age(self, symbol: str) -> Optional[int]:
        """Gibt Alter des Cache-Eintrags in Tagen zurück"""
        symbol = symbol.upper()
        entry = self._cache.get(symbol)
        
        if not entry or not entry.updated:
            return None
        
        try:
            updated = datetime.fromisoformat(entry.updated)
            return (datetime.now() - updated).days
        except (ValueError, TypeError):
            return None
    
    def get_stale_symbols(self, symbols: List[str]) -> List[str]:
        """Gibt Liste der Symbole zurück, deren Cache abgelaufen ist"""
        return [s.upper() for s in symbols if not self.is_fresh(s)]
    
    def invalidate(self, symbol: str):
        """Entfernt Symbol aus Cache"""
        symbol = symbol.upper()
        if symbol in self._cache:
            del self._cache[symbol]
            self._save_cache()
    
    def stats(self) -> Dict:
        """Cache-Statistiken"""
        total = len(self._cache)
        fresh = sum(1 for e in self._cache.values() if self._is_fresh(e))
        with_sufficient_data = sum(1 for e in self._cache.values() if e.data_points >= 20)
        
        return {
            "total_symbols": total,
            "fresh_entries": fresh,
            "stale_entries": total - fresh,
            "with_sufficient_data": with_sufficient_data,
            "cache_file": str(self.cache_file),
            "max_age_days": self.max_age_days
        }
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, symbol: str) -> bool:
        return symbol.upper() in self._cache


# =============================================================================
# IV FETCHER (mit Cache)
# =============================================================================

class IVFetcher:
    """
    Holt IV-Daten mit automatischem Caching.
    
    Unterstützte Quellen:
    - Tradier Options Chain (primär)
    - Yahoo Finance (fallback)
    
    Verwendung:
        fetcher = IVFetcher()
        
        # Einzelnes Symbol
        iv_data = fetcher.get_iv_rank("AAPL", current_iv=0.28)
        
        # Mit automatischem Fetch der aktuellen IV
        iv_data = fetcher.fetch_and_calculate("AAPL")
    """
    
    def __init__(self, cache: Optional[IVCache] = None):
        self.cache = cache or IVCache()
    
    def get_iv_rank(self, symbol: str, current_iv: float) -> IVData:
        """
        Berechnet IV-Rank für ein Symbol.
        
        Verwendet gecachte History wenn verfügbar.
        
        Args:
            symbol: Ticker-Symbol
            current_iv: Aktuelle IV (dezimal, z.B. 0.35)
            
        Returns:
            IVData mit IV-Rank und IV-Perzentil
        """
        symbol = symbol.upper()
        
        # Versuche aus Cache
        iv_data = self.cache.get_iv_data(symbol, current_iv)
        
        if iv_data:
            return iv_data
        
        # Keine History vorhanden - nur aktuelle IV zurückgeben
        return IVData(
            symbol=symbol,
            current_iv=current_iv,
            iv_rank=None,
            iv_percentile=None,
            iv_high_52w=None,
            iv_low_52w=None,
            data_points=0,
            source=IVSource.UNKNOWN,
            updated_at=datetime.now().isoformat()
        )
    
    def get_iv_rank_many(
        self, 
        symbols_with_iv: List[Tuple[str, float]]
    ) -> Dict[str, IVData]:
        """
        Berechnet IV-Rank für mehrere Symbole.
        
        Args:
            symbols_with_iv: Liste von (symbol, current_iv) Tupeln
            
        Returns:
            Dict mit Symbol -> IVData
        """
        return {
            symbol: self.get_iv_rank(symbol, current_iv)
            for symbol, current_iv in symbols_with_iv
        }
    
    def extract_atm_iv_from_chain(
        self, 
        options_chain: List[Dict], 
        underlying_price: float
    ) -> Optional[float]:
        """
        Extrahiert ATM-IV aus einer Options-Chain.
        
        Findet den Strike, der am nächsten am underlying_price liegt,
        und verwendet dessen mid_iv oder smv_vol.
        
        Args:
            options_chain: Liste von Options-Dicts (Tradier Format)
            underlying_price: Aktueller Aktienkurs
            
        Returns:
            ATM-IV (dezimal) oder None
        """
        if not options_chain or not underlying_price:
            return None
        
        # Finde ATM-Option (nächster Strike zum Preis)
        atm_option = None
        min_distance = float('inf')
        
        for opt in options_chain:
            strike = opt.get('strike', 0)
            distance = abs(strike - underlying_price)
            
            if distance < min_distance:
                min_distance = distance
                atm_option = opt
        
        if not atm_option:
            return None
        
        # IV extrahieren (Tradier Format)
        greeks = atm_option.get('greeks', {})
        
        # Präferenz: smv_vol > mid_iv > (bid_iv + ask_iv) / 2
        if greeks.get('smv_vol'):
            return greeks['smv_vol']
        elif greeks.get('mid_iv'):
            return greeks['mid_iv']
        elif greeks.get('bid_iv') and greeks.get('ask_iv'):
            return (greeks['bid_iv'] + greeks['ask_iv']) / 2
        
        return None
    
    def update_from_chain(
        self, 
        symbol: str, 
        options_chain: List[Dict],
        underlying_price: float
    ) -> Optional[float]:
        """
        Aktualisiert IV-History aus einer Options-Chain.
        
        Extrahiert ATM-IV und fügt sie zur History hinzu.
        
        Args:
            symbol: Ticker-Symbol
            options_chain: Tradier Options-Chain
            underlying_price: Aktueller Aktienkurs
            
        Returns:
            Extrahierte ATM-IV oder None
        """
        atm_iv = self.extract_atm_iv_from_chain(options_chain, underlying_price)
        
        if atm_iv:
            self.cache.add_iv_point(symbol, atm_iv, IVSource.TRADIER)
        
        return atm_iv


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Globale Instanzen
_default_cache: Optional[IVCache] = None
_default_fetcher: Optional[IVFetcher] = None


def get_iv_cache() -> IVCache:
    """Gibt globale Cache-Instanz zurück"""
    global _default_cache
    if _default_cache is None:
        _default_cache = IVCache()
    return _default_cache


def get_iv_fetcher() -> IVFetcher:
    """Gibt globale Fetcher-Instanz zurück"""
    global _default_fetcher
    if _default_fetcher is None:
        _default_fetcher = IVFetcher(get_iv_cache())
    return _default_fetcher


def get_iv_rank(symbol: str, current_iv: float) -> IVData:
    """
    Convenience-Funktion für IV-Rank Berechnung.
    
    Beispiel:
        >>> iv_data = get_iv_rank("AAPL", 0.28)
        >>> print(f"IV-Rank: {iv_data.iv_rank}%")
    """
    return get_iv_fetcher().get_iv_rank(symbol, current_iv)


def is_iv_elevated(symbol: str, current_iv: float, threshold: float = 50.0) -> bool:
    """
    Prüft ob IV erhöht ist (gut für Credit-Spreads).
    
    Beispiel:
        >>> if is_iv_elevated("AAPL", 0.35):
        ...     print("Gute Zeit für Bull-Put-Spread")
    """
    iv_data = get_iv_fetcher().get_iv_rank(symbol, current_iv)
    return iv_data.is_elevated(threshold)


# =============================================================================
# HISTORICAL IV FETCHER
# =============================================================================

class HistoricalIVFetcher:
    """
    Lädt historische IV-Daten von externen Quellen.
    
    Unterstützte Quellen:
    - Yahoo Finance (VIX-basierte Schätzung für Einzelaktien)
    - Historische Volatilität als Proxy für IV
    
    Verwendet:
    - HV (Historical Volatility) als Basis
    - VIX-Korrelation für Markt-Adjustment
    - Optional: CBOE-Daten wenn verfügbar
    
    Verwendung:
        fetcher = HistoricalIVFetcher()
        
        # IV-History für ein Symbol laden
        history = fetcher.fetch_iv_history("AAPL", days=252)
        
        # Cache automatisch aktualisieren
        fetcher.update_cache_from_history(["AAPL", "MSFT", "GOOGL"])
    """
    
    def __init__(self, cache: Optional[IVCache] = None):
        self.cache = cache or get_iv_cache()
        self._yf = None  # Lazy load
    
    def _get_yfinance(self):
        """Lazy-Load yfinance"""
        if self._yf is None:
            try:
                import yfinance as yf
                self._yf = yf
            except ImportError:
                raise ImportError(
                    "yfinance ist erforderlich für historische IV-Daten. "
                    "Installation: pip install yfinance"
                )
        return self._yf
    
    def calculate_historical_volatility(
        self,
        prices: List[float],
        window: int = 20
    ) -> List[float]:
        """
        Berechnet historische Volatilität (HV) aus Preisen.
        
        HV = StdDev(log returns) * sqrt(252)
        
        Args:
            prices: Liste von Schlusskursen (älteste zuerst)
            window: Rolling Window für Berechnung (default: 20 Tage)
            
        Returns:
            Liste von HV-Werten (annualisiert, dezimal)
        """
        import math
        
        if len(prices) < window + 1:
            return []
        
        # Log Returns berechnen
        log_returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0 and prices[i] > 0:
                log_returns.append(math.log(prices[i] / prices[i-1]))
            else:
                log_returns.append(0)
        
        # Rolling StdDev
        hv_values = []
        for i in range(window - 1, len(log_returns)):
            window_returns = log_returns[i - window + 1:i + 1]
            
            # StdDev berechnen
            mean = sum(window_returns) / len(window_returns)
            variance = sum((r - mean) ** 2 for r in window_returns) / len(window_returns)
            std_dev = math.sqrt(variance)
            
            # Annualisieren (252 Trading-Tage)
            annualized_vol = std_dev * math.sqrt(252)
            hv_values.append(annualized_vol)
        
        return hv_values
    
    def estimate_iv_from_hv(
        self,
        hv_values: List[float],
        vix_history: Optional[List[float]] = None,
        iv_premium: float = 1.15
    ) -> List[float]:
        """
        Schätzt IV aus historischer Volatilität.
        
        IV ist typischerweise 10-20% höher als HV (Volatility Risk Premium).
        
        Args:
            hv_values: Liste von HV-Werten (dezimal)
            vix_history: Optional VIX-History für Markt-Adjustment
            iv_premium: Multiplikator für IV (default: 1.15 = 15% Premium)
            
        Returns:
            Liste von geschätzten IV-Werten (dezimal)
        """
        if not hv_values:
            return []
        
        estimated_iv = []
        
        for i, hv in enumerate(hv_values):
            # Basis: HV mit Premium
            iv = hv * iv_premium
            
            # Optional: VIX-Adjustment
            if vix_history and i < len(vix_history):
                vix = vix_history[i]
                # Bei hohem VIX höheres IV-Premium
                if vix > 25:
                    iv *= 1.1  # +10% bei VIX > 25
                elif vix > 35:
                    iv *= 1.2  # +20% bei VIX > 35
            
            estimated_iv.append(round(iv, 4))
        
        return estimated_iv
    
    def fetch_vix_history(self, days: int = 252) -> List[float]:
        """
        Lädt VIX-History von Yahoo Finance.
        
        Args:
            days: Anzahl Handelstage (default: 252 = 1 Jahr)
            
        Returns:
            Liste von VIX-Werten (dezimal, z.B. 0.15 für VIX 15)
        """
        yf = self._get_yfinance()
        
        try:
            vix = yf.Ticker("^VIX")
            # ~1.5x Tage für Wochenenden/Feiertage
            hist = vix.history(period=f"{int(days * 1.5)}d")
            
            if hist.empty:
                logger.warning("Keine VIX-Daten verfügbar")
                return []
            
            # VIX ist in Prozent angegeben, konvertieren zu dezimal
            vix_values = [close / 100 for close in hist['Close'].tolist()]
            
            # Auf gewünschte Länge begrenzen
            if len(vix_values) > days:
                vix_values = vix_values[-days:]
            
            return vix_values
            
        except Exception as e:
            logger.warning(f"Fehler beim Laden der VIX-History: {e}")
            return []
    
    def fetch_iv_history(
        self,
        symbol: str,
        days: int = 252,
        use_vix_adjustment: bool = True
    ) -> List[float]:
        """
        Lädt/schätzt IV-History für ein Symbol.
        
        Verwendet historische Volatilität als Basis und
        adjustiert basierend auf VIX-Level.
        
        Args:
            symbol: Ticker-Symbol
            days: Anzahl Handelstage (default: 252 = 1 Jahr)
            use_vix_adjustment: VIX für Markt-Adjustment verwenden
            
        Returns:
            Liste von geschätzten IV-Werten (dezimal)
        """
        yf = self._get_yfinance()
        symbol = symbol.upper()
        
        try:
            ticker = yf.Ticker(symbol)
            # Mehr Tage laden für HV-Berechnung (braucht 20 Tage Vorlauf)
            hist = ticker.history(period=f"{int(days * 1.5 + 30)}d")
            
            if hist.empty:
                logger.warning(f"Keine Preisdaten für {symbol}")
                return []
            
            prices = hist['Close'].tolist()
            
            # HV berechnen
            hv_values = self.calculate_historical_volatility(prices, window=20)
            
            if not hv_values:
                logger.warning(f"Konnte HV für {symbol} nicht berechnen")
                return []
            
            # VIX-History für Adjustment laden
            vix_history = None
            if use_vix_adjustment:
                vix_history = self.fetch_vix_history(len(hv_values))
            
            # IV aus HV schätzen
            iv_history = self.estimate_iv_from_hv(hv_values, vix_history)
            
            # Auf gewünschte Länge begrenzen
            if len(iv_history) > days:
                iv_history = iv_history[-days:]
            
            logger.info(f"IV-History für {symbol}: {len(iv_history)} Datenpunkte")
            return iv_history
            
        except Exception as e:
            logger.error(f"Fehler beim Laden der IV-History für {symbol}: {e}")
            return []
    
    def update_cache_for_symbol(
        self,
        symbol: str,
        days: int = 252,
        force: bool = False
    ) -> bool:
        """
        Aktualisiert IV-Cache für ein Symbol.
        
        Args:
            symbol: Ticker-Symbol
            days: Anzahl Tage History
            force: Cache auch aktualisieren wenn noch frisch
            
        Returns:
            True wenn erfolgreich
        """
        symbol = symbol.upper()
        
        # Prüfen ob Update nötig
        if not force and self.cache.is_fresh(symbol):
            logger.debug(f"Cache für {symbol} noch frisch, überspringe")
            return True
        
        # IV-History laden
        iv_history = self.fetch_iv_history(symbol, days)
        
        if not iv_history:
            logger.warning(f"Keine IV-History für {symbol} verfügbar")
            return False
        
        # Cache aktualisieren
        self.cache.update_history(symbol, iv_history, IVSource.YAHOO)
        return True
    
    def update_cache_for_symbols(
        self,
        symbols: List[str],
        days: int = 252,
        force: bool = False,
        delay_seconds: float = 0.5
    ) -> Dict[str, bool]:
        """
        Aktualisiert IV-Cache für mehrere Symbole.
        
        Args:
            symbols: Liste von Ticker-Symbolen
            days: Anzahl Tage History pro Symbol
            force: Cache auch aktualisieren wenn noch frisch
            delay_seconds: Pause zwischen API-Calls (Rate-Limiting)
            
        Returns:
            Dict mit Symbol -> Erfolg (True/False)
        """
        import time
        
        results = {}
        total = len(symbols)
        
        for i, symbol in enumerate(symbols):
            logger.info(f"Aktualisiere IV-Cache [{i+1}/{total}]: {symbol}")
            
            success = self.update_cache_for_symbol(symbol, days, force)
            results[symbol.upper()] = success
            
            # Rate-Limiting
            if i < total - 1 and delay_seconds > 0:
                time.sleep(delay_seconds)
        
        successful = sum(1 for v in results.values() if v)
        logger.info(f"IV-Cache Update abgeschlossen: {successful}/{total} erfolgreich")
        
        return results
    
    def get_stale_symbols(self, symbols: List[str]) -> List[str]:
        """
        Gibt Symbole zurück, deren IV-Cache abgelaufen oder leer ist.
        
        Args:
            symbols: Liste zu prüfender Symbole
            
        Returns:
            Liste von Symbolen die ein Update brauchen
        """
        return self.cache.get_stale_symbols(symbols)


# Globale Instanz
_historical_iv_fetcher: Optional[HistoricalIVFetcher] = None


def get_historical_iv_fetcher() -> HistoricalIVFetcher:
    """Gibt globale HistoricalIVFetcher-Instanz zurück"""
    global _historical_iv_fetcher
    if _historical_iv_fetcher is None:
        _historical_iv_fetcher = HistoricalIVFetcher()
    return _historical_iv_fetcher


def fetch_iv_history(symbol: str, days: int = 252) -> List[float]:
    """
    Convenience-Funktion zum Laden der IV-History.
    
    Beispiel:
        >>> history = fetch_iv_history("AAPL")
        >>> print(f"{len(history)} Datenpunkte geladen")
    """
    return get_historical_iv_fetcher().fetch_iv_history(symbol, days)


def update_iv_cache(symbols: List[str], force: bool = False) -> Dict[str, bool]:
    """
    Convenience-Funktion zum Aktualisieren des IV-Cache.
    
    Beispiel:
        >>> results = update_iv_cache(["AAPL", "MSFT", "GOOGL"])
        >>> print(f"Erfolgreich: {sum(results.values())}")
    """
    return get_historical_iv_fetcher().update_cache_for_symbols(symbols, force=force)
