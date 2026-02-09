#!/usr/bin/env python3
"""
Watchlist Loader - Lädt Watchlists aus YAML-Konfiguration

Verwendung:
    from src.watchlist_loader import WatchlistLoader
    
    loader = WatchlistLoader()
    symbols = loader.get_all_symbols()
    tech_symbols = loader.get_sector("information_technology")
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class WatchlistLoader:
    """
    Lädt und verwaltet Watchlists aus config/watchlists.yaml
    
    Struktur:
        watchlists:
            default_275:
                sectors:
                    information_technology:
                        symbols: [AAPL, MSFT, ...]
    """
    
    def __init__(self, config_path: Optional[Path] = None) -> None:
        """
        Initialisiert den Loader

        Args:
            config_path: Pfad zur watchlists.yaml (default: ~/OptionPlay/config/)
        """
        if config_path is None:
            # Standard-Pfade versuchen
            possible_paths = [
                Path.home() / "OptionPlay" / "config" / "watchlists.yaml",
                Path(__file__).parent.parent / "config" / "watchlists.yaml",
                Path.cwd() / "config" / "watchlists.yaml"
            ]
            for path in possible_paths:
                if path.exists():
                    config_path = path
                    break
        
        self.config_path = config_path
        self._watchlists: Dict = {}
        self._sectors: Dict[str, List[str]] = {}
        self._all_symbols: List[str] = []
        
        if self.config_path and self.config_path.exists():
            self._load()
        else:
            logger.warning(f"watchlists.yaml nicht gefunden, nutze hardcodierte Fallback-Liste")
            self._use_fallback()
    
    def _load(self) -> None:
        """Lädt die YAML-Konfiguration"""
        try:
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f)
            
            self._watchlists = data.get('watchlists', {})
            
            # Extrahiere Sektoren aus der Default-Watchlist
            default_list = self._watchlists.get('default_275', {})
            sectors_data = default_list.get('sectors', {})
            
            for sector_key, sector_info in sectors_data.items():
                symbols = sector_info.get('symbols', [])
                self._sectors[sector_key] = symbols
                self._all_symbols.extend(symbols)
            
            # Duplikate entfernen, Reihenfolge beibehalten
            seen = set()
            self._all_symbols = [x for x in self._all_symbols if not (x in seen or seen.add(x))]
            
            logger.info(f"Watchlist geladen: {len(self._all_symbols)} Symbole in {len(self._sectors)} Sektoren")
        
        except Exception as e:
            logger.error(f"Fehler beim Laden der Watchlist: {e}")
            self._use_fallback()
    
    def _use_fallback(self) -> None:
        """Fallback auf hardcodierte Watchlist"""
        self._sectors = {
            "information_technology": [
                "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "ACN",
                "INTC", "IBM", "INTU", "TXN", "QCOM", "AMAT", "NOW", "PANW", "MU", "LRCX"
            ],
            "health_care": [
                "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN",
                "BMY", "ISRG", "GILD", "VRTX", "MDT", "SYK", "REGN", "BSX", "ZTS", "ELV"
            ],
            "financials": [
                "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK", "C",
                "AXP", "SCHW", "PGR", "CB", "CME", "ICE", "MCO", "PNC", "USB", "MET"
            ],
            "consumer_discretionary": [
                "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG",
                "ORLY", "MAR", "HLT", "AZO", "ROST", "RCL", "GM", "F", "DHI", "LEN"
            ],
            "communication_services": [
                "GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T", "CMCSA", "CHTR", "EA",
                "TTWO", "LYV", "OMC", "MTCH", "PARA"
            ],
            "industrials": [
                "GE", "CAT", "RTX", "HON", "UNP", "DE", "LMT", "BA", "UPS", "ETN",
                "PH", "GD", "NOC", "WM", "FDX", "CSX", "NSC", "EMR", "ITW", "MMM"
            ],
            "consumer_staples": [
                "WMT", "PG", "COST", "KO", "PEP", "PM", "MDLZ", "MO", "CL", "KMB",
                "GIS", "HSY", "SYY", "KR", "STZ", "ADM", "KHC", "TSN", "CLX", "CHD"
            ],
            "energy": [
                "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "WMB",
                "KMI", "FANG", "BKR", "TRGP", "OKE", "HAL", "DVN", "EQT", "HES", "MRO"
            ],
            "utilities": [
                "NEE", "SO", "DUK", "AEP", "D", "EXC", "SRE", "XEL", "ED", "WEC",
                "ETR", "PEG", "DTE", "FE", "PPL", "ES", "CMS", "CNP", "NI", "AWK"
            ],
            "real_estate": [
                "PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "DLR", "O", "CCI", "VICI",
                "VTR", "IRM", "EXR", "AVB", "EQR", "ARE", "MAA", "ESS", "UDR", "KIM"
            ],
            "materials": [
                "LIN", "SHW", "FCX", "APD", "ECL", "NEM", "NUE", "DD", "DOW", "VMC",
                "MLM", "CTVA", "PPG", "ALB", "IFF", "PKG", "IP", "CF", "MOS", "AVY"
            ]
        }
        
        self._all_symbols = []
        for symbols in self._sectors.values():
            self._all_symbols.extend(symbols)
        
        # Duplikate entfernen
        seen = set()
        self._all_symbols = [x for x in self._all_symbols if not (x in seen or seen.add(x))]
    
    def get_all_symbols(self) -> List[str]:
        """Gibt alle Symbole aus allen Sektoren zurück"""
        return self._all_symbols.copy()
    
    def get_sector(self, sector_name: str) -> List[str]:
        """
        Gibt Symbole eines Sektors zurück
        
        Args:
            sector_name: Name des Sektors (z.B. "information_technology")
        
        Returns:
            Liste der Symbole oder leere Liste
        """
        return self._sectors.get(sector_name, []).copy()
    
    def get_all_sectors(self) -> Dict[str, List[str]]:
        """Gibt alle Sektoren mit ihren Symbolen zurück"""
        return {k: v.copy() for k, v in self._sectors.items()}
    
    def get_sector_names(self) -> List[str]:
        """Gibt alle Sektor-Namen zurück"""
        return list(self._sectors.keys())
    
    def get_watchlist(self, name: str) -> Optional[Dict]:
        """
        Gibt eine spezifische Watchlist zurück
        
        Args:
            name: Name der Watchlist (z.B. "default_275", "tech_focus")
        
        Returns:
            Watchlist-Daten oder None
        """
        return self._watchlists.get(name)
    
    def get_symbols_from_watchlist(self, name: str) -> List[str]:
        """
        Gibt alle Symbole einer Watchlist zurück
        
        Args:
            name: Name der Watchlist
        
        Returns:
            Liste der Symbole
        """
        watchlist = self.get_watchlist(name)
        if not watchlist:
            return []
        
        symbols = []
        
        # Sektoren durchgehen
        if 'sectors' in watchlist:
            for sector_info in watchlist['sectors'].values():
                symbols.extend(sector_info.get('symbols', []))
        
        # Oder direkte Symbol-Liste
        if 'symbols' in watchlist:
            symbols.extend(watchlist['symbols'])
        
        return list(dict.fromkeys(symbols))  # Duplikate entfernen
    
    def symbol_in_sector(self, symbol: str) -> Optional[str]:
        """
        Findet den Sektor eines Symbols
        
        Args:
            symbol: Ticker-Symbol
        
        Returns:
            Sektor-Name oder None
        """
        for sector_name, symbols in self._sectors.items():
            if symbol in symbols:
                return sector_name
        return None
    
    def get_sector_display_name(self, sector_key: str) -> str:
        """
        Konvertiert Sektor-Key zu Display-Name
        
        Args:
            sector_key: z.B. "information_technology"
        
        Returns:
            z.B. "Information Technology"
        """
        mapping = {
            "information_technology": "Technology",
            "health_care": "Healthcare",
            "financials": "Financials",
            "consumer_discretionary": "Consumer Discretionary",
            "communication_services": "Communication Services",
            "industrials": "Industrials",
            "consumer_staples": "Consumer Staples",
            "energy": "Energy",
            "utilities": "Utilities",
            "real_estate": "Real Estate",
            "materials": "Materials"
        }
        return mapping.get(sector_key, sector_key.replace("_", " ").title())


# Singleton-Instanz für einfachen Import
_loader_instance: Optional[WatchlistLoader] = None


def get_watchlist_loader() -> WatchlistLoader:
    """Gibt die Singleton-Instanz des WatchlistLoaders zurück"""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = WatchlistLoader()
    return _loader_instance


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    loader = WatchlistLoader()
    
    print(f"\n=== Watchlist Loader Test ===")
    print(f"Sektoren: {loader.get_sector_names()}")
    print(f"Total Symbole: {len(loader.get_all_symbols())}")
    
    print(f"\nTechnology ({len(loader.get_sector('information_technology'))} Symbole):")
    print(f"  {loader.get_sector('information_technology')[:10]}...")
    
    print(f"\nAPPL ist in Sektor: {loader.symbol_in_sector('AAPL')}")
    print(f"JPM ist in Sektor: {loader.symbol_in_sector('JPM')}")
