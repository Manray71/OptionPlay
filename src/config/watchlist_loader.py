#!/usr/bin/env python3
"""
Watchlist Loader - Lädt Watchlists aus YAML-Konfiguration

Verwendung:
    from src.config import WatchlistLoader, get_watchlist_loader
    
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
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            possible_paths = [
                Path.home() / "OptionPlay" / "config" / "watchlists.yaml",
                Path(__file__).parent.parent.parent / "config" / "watchlists.yaml",
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
            logger.warning("watchlists.yaml nicht gefunden, nutze Fallback")
            self._use_fallback()
    
    def _load(self) -> None:
        try:
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f)
            
            self._watchlists = data.get('watchlists', {})
            default_list = self._watchlists.get('default_275', {})
            sectors_data = default_list.get('sectors', {})
            
            for sector_key, sector_info in sectors_data.items():
                symbols = sector_info.get('symbols', [])
                self._sectors[sector_key] = symbols
                self._all_symbols.extend(symbols)
            
            seen = set()
            self._all_symbols = [x for x in self._all_symbols if not (x in seen or seen.add(x))]
            logger.info(f"Watchlist geladen: {len(self._all_symbols)} Symbole")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Watchlist: {e}")
            self._use_fallback()
    
    def _use_fallback(self) -> None:
        self._sectors = {
            "information_technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "ACN"],
            "health_care": ["UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN"],
            "financials": ["JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK", "C"],
            "consumer_discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG"],
            "industrials": ["GE", "CAT", "RTX", "HON", "UNP", "DE", "LMT", "BA", "UPS", "ETN"],
            "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "WMB"],
        }
        self._all_symbols = []
        for symbols in self._sectors.values():
            self._all_symbols.extend(symbols)
    
    def get_all_symbols(self) -> List[str]:
        return self._all_symbols.copy()
    
    def get_sector(self, sector_name: str) -> List[str]:
        return self._sectors.get(sector_name, []).copy()
    
    def get_all_sectors(self) -> Dict[str, List[str]]:
        return {k: v.copy() for k, v in self._sectors.items()}
    
    def get_sector_names(self) -> List[str]:
        return list(self._sectors.keys())
    
    def get_watchlist(self, name: str) -> Optional[Dict]:
        return self._watchlists.get(name)
    
    def get_symbols_from_watchlist(self, name: str) -> List[str]:
        watchlist = self.get_watchlist(name)
        if not watchlist:
            return []
        
        symbols = []
        if 'sectors' in watchlist:
            for sector_info in watchlist['sectors'].values():
                symbols.extend(sector_info.get('symbols', []))
        if 'symbols' in watchlist:
            symbols.extend(watchlist['symbols'])
        return list(dict.fromkeys(symbols))
    
    def symbol_in_sector(self, symbol: str) -> Optional[str]:
        for sector_name, symbols in self._sectors.items():
            if symbol in symbols:
                return sector_name
        return None
    
    def get_sector_display_name(self, sector_key: str) -> str:
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


_loader_instance: Optional[WatchlistLoader] = None


def get_watchlist_loader() -> WatchlistLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = WatchlistLoader()
    return _loader_instance
