#!/usr/bin/env python3
"""
Watchlist Loader - Lädt Watchlists aus YAML-Konfiguration

Verwendung:
    from src.config import WatchlistLoader, get_watchlist_loader

    loader = WatchlistLoader()
    symbols = loader.get_all_symbols()
    tech_symbols = loader.get_sector("information_technology")

    # Stability-basierte Listen
    stable = loader.get_stable_symbols()  # Stability >= 60
    risky = loader.get_risk_symbols()     # Stability < 60 oder unbekannt
"""

import yaml
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class WatchlistLoader:
    """
    Lädt und verwaltet Watchlists aus config/watchlists.yaml

    Verwendet die `default_list` Einstellung aus settings.yaml um die
    aktive Watchlist zu bestimmen.

    Unterstützt Stability-basierte Aufteilung:
    - stable_list: Symbole mit Stability Score >= threshold
    - risk_list: Symbole mit Stability Score < threshold oder unbekannt
    """

    def __init__(self, config_path: Optional[Path] = None, default_list: Optional[str] = None) -> None:
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
        self._default_list = default_list or self._get_default_list_from_settings()

        # Stability-Split Konfiguration
        self._stability_split_enabled = False
        self._stable_min_score = 60.0
        self._include_unknown_in_risk = True
        self._load_stability_config()

        # Gecachte Listen
        self._stable_symbols: Optional[List[str]] = None
        self._risk_symbols: Optional[List[str]] = None

        if self.config_path and self.config_path.exists():
            self._load()
        else:
            logger.warning("watchlists.yaml nicht gefunden, nutze Fallback")
            self._use_fallback()

    def _get_default_list_from_settings(self) -> str:
        """Liest default_list aus settings.yaml"""
        possible_paths = [
            Path.home() / "OptionPlay" / "config" / "settings.yaml",
            Path(__file__).parent.parent.parent / "config" / "settings.yaml",
            Path.cwd() / "config" / "settings.yaml"
        ]

        for path in possible_paths:
            if path.exists():
                try:
                    with open(path, 'r') as f:
                        data = yaml.safe_load(f)
                    if data and 'watchlist' in data:
                        return data['watchlist'].get('default_list', 'default_275')
                except Exception as e:
                    logger.warning(f"Konnte settings.yaml nicht lesen: {e}")

        return 'default_275'

    def _load_stability_config(self) -> None:
        """Lädt Stability-Split Konfiguration aus settings.yaml"""
        possible_paths = [
            Path.home() / "OptionPlay" / "config" / "settings.yaml",
            Path(__file__).parent.parent.parent / "config" / "settings.yaml",
            Path.cwd() / "config" / "settings.yaml"
        ]

        for path in possible_paths:
            if path.exists():
                try:
                    with open(path, 'r') as f:
                        data = yaml.safe_load(f)
                    if data and 'watchlist' in data:
                        split_config = data['watchlist'].get('stability_split', {})
                        self._stability_split_enabled = split_config.get('enabled', False)
                        self._stable_min_score = split_config.get('stable_min_score', 60.0)
                        self._include_unknown_in_risk = split_config.get('include_unknown_in_risk', True)
                        if self._stability_split_enabled:
                            logger.debug(f"Stability split enabled: min_score={self._stable_min_score}")
                        return
                except Exception as e:
                    logger.warning(f"Konnte stability_split config nicht lesen: {e}")
    
    def _load(self) -> None:
        try:
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f)

            self._watchlists = data.get('watchlists', {})

            # Verwende die konfigurierte default_list
            default_list = self._watchlists.get(self._default_list, {})
            if not default_list:
                # Fallback auf default_275 wenn die konfigurierte Liste nicht existiert
                logger.warning(f"Watchlist '{self._default_list}' nicht gefunden, nutze default_275")
                default_list = self._watchlists.get('default_275', {})

            # Lade Symbole aus 'sectors' oder direkt aus 'symbols'
            if 'sectors' in default_list:
                sectors_data = default_list.get('sectors', {})
                for sector_key, sector_info in sectors_data.items():
                    symbols = sector_info.get('symbols', [])
                    # Filter nur echte Strings (keine booleans oder None)
                    symbols = [s for s in symbols if isinstance(s, str)]
                    self._sectors[sector_key] = symbols
                    self._all_symbols.extend(symbols)
            elif 'symbols' in default_list:
                # Flat symbol list (sp500_complete, extended_600)
                symbols = default_list.get('symbols', [])
                # Filter nur echte Strings
                self._all_symbols = [s for s in symbols if isinstance(s, str)]

            # Deduplizieren
            seen = set()
            self._all_symbols = [x for x in self._all_symbols if not (x in seen or seen.add(x))]
            logger.info(f"Watchlist '{self._default_list}' geladen: {len(self._all_symbols)} Symbole")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Watchlist: {e}")
            self._use_fallback()
    
    def _use_fallback(self) -> None:
        self._sectors = {
            "information_technology": [
                "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "ACN",
                "INTC", "IBM", "INTU", "TXN", "QCOM", "AMAT", "NOW", "PANW", "MU", "LRCX",
            ],
            "health_care": [
                "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN",
                "BMY", "ISRG", "GILD", "VRTX", "MDT", "SYK", "REGN", "BSX", "ZTS", "ELV",
            ],
            "financials": [
                "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK", "C",
                "AXP", "SCHW", "PGR", "CB", "CME", "ICE", "MCO", "PNC", "USB", "MET",
            ],
            "consumer_discretionary": [
                "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG",
                "ORLY", "MAR", "HLT", "AZO", "ROST", "RCL", "GM", "F", "DHI", "LEN",
            ],
            "communication_services": [
                "GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T", "CMCSA", "CHTR", "EA",
                "TTWO", "LYV", "OMC", "MTCH", "PARA",
            ],
            "industrials": [
                "GE", "CAT", "RTX", "HON", "UNP", "DE", "LMT", "BA", "UPS", "ETN",
                "PH", "GD", "NOC", "WM", "FDX", "CSX", "NSC", "EMR", "ITW", "MMM",
            ],
            "consumer_staples": [
                "WMT", "PG", "COST", "KO", "PEP", "PM", "MDLZ", "MO", "CL", "KMB",
                "GIS", "HSY", "SYY", "KR", "STZ", "ADM", "KHC", "TSN", "CLX", "CHD",
            ],
            "energy": [
                "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "WMB",
                "KMI", "FANG", "BKR", "TRGP", "OKE", "HAL", "DVN", "EQT", "HES", "MRO",
            ],
            "utilities": [
                "NEE", "SO", "DUK", "AEP", "D", "EXC", "SRE", "XEL", "ED", "WEC",
                "ETR", "PEG", "DTE", "FE", "PPL", "ES", "CMS", "CNP", "NI", "AWK",
            ],
            "real_estate": [
                "PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "DLR", "O", "CCI", "VICI",
                "VTR", "IRM", "EXR", "AVB", "EQR", "ARE", "MAA", "ESS", "UDR", "KIM",
            ],
            "materials": [
                "LIN", "SHW", "FCX", "APD", "ECL", "NEM", "NUE", "DD", "DOW", "VMC",
                "MLM", "CTVA", "PPG", "ALB", "IFF", "PKG", "IP", "CF", "MOS", "AVY",
            ],
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

    # =========================================================================
    # STABILITY-BASIERTE LISTEN
    # =========================================================================

    def _compute_stability_split(self) -> Tuple[List[str], List[str]]:
        """
        Teilt die Watchlist basierend auf Stability Scores auf.

        Logik:
        - Symbole auf Blacklist → ausgeschlossen (weder stable noch risk)
        - Symbole mit Stability Score >= threshold → stable
        - Symbole mit Stability Score < threshold → risk
        - Symbole ohne Score → je nach include_unknown_in_risk

        Returns:
            Tuple: (stable_symbols, risk_symbols)
        """
        try:
            from ..cache import get_fundamentals_manager
        except ImportError:
            try:
                from src.cache import get_fundamentals_manager
            except ImportError:
                logger.warning("FundamentalsManager nicht verfügbar, alle Symbole als stable")
                return self._all_symbols.copy(), []

        # Lade Blacklist aus Konfiguration
        blacklist = set()
        try:
            from ..config.fundamentals_constants import DEFAULT_BLACKLIST
            blacklist = set(DEFAULT_BLACKLIST)
        except ImportError:
            try:
                from src.config.fundamentals_constants import DEFAULT_BLACKLIST
                blacklist = set(DEFAULT_BLACKLIST)
            except ImportError:
                logger.debug("DEFAULT_BLACKLIST not available, using empty blacklist")

        manager = get_fundamentals_manager()
        all_symbols = self._all_symbols

        # Fundamentals für alle Symbole in einem Batch holen
        fundamentals_map = manager.get_fundamentals_batch(all_symbols)

        stable = []
        risk = []
        excluded = 0

        for symbol in all_symbols:
            # Blacklist-Check zuerst
            if symbol in blacklist:
                excluded += 1
                continue

            fund = fundamentals_map.get(symbol)

            if fund and fund.stability_score is not None:
                if fund.stability_score >= self._stable_min_score:
                    stable.append(symbol)
                else:
                    risk.append(symbol)
            else:
                # Symbol ohne Stability-Daten
                if self._include_unknown_in_risk:
                    risk.append(symbol)
                else:
                    stable.append(symbol)

        logger.info(
            f"Stability split: {len(stable)} stable, {len(risk)} risk, "
            f"{excluded} blacklisted (threshold: {self._stable_min_score})"
        )
        return stable, risk

    def get_stable_symbols(self, force_refresh: bool = False) -> List[str]:
        """
        Gibt Symbole mit Stability Score >= threshold zurück.

        Diese Liste enthält qualitativ hochwertige Symbole für den Standard-Scan.

        Args:
            force_refresh: Wenn True, wird der Cache invalidiert

        Returns:
            Liste von stabilen Symbolen
        """
        if not self._stability_split_enabled:
            return self._all_symbols.copy()

        if self._stable_symbols is None or force_refresh:
            self._stable_symbols, self._risk_symbols = self._compute_stability_split()

        return self._stable_symbols.copy()

    def get_risk_symbols(self, force_refresh: bool = False) -> List[str]:
        """
        Gibt Symbole mit Stability Score < threshold oder unbekannt zurück.

        Diese Liste enthält riskantere Symbole für separate Scans.

        Args:
            force_refresh: Wenn True, wird der Cache invalidiert

        Returns:
            Liste von Risk-Symbolen
        """
        if not self._stability_split_enabled:
            return []

        if self._risk_symbols is None or force_refresh:
            self._stable_symbols, self._risk_symbols = self._compute_stability_split()

        return self._risk_symbols.copy()

    def get_symbols_by_list_type(
        self,
        list_type: str = "stable",
        force_refresh: bool = False
    ) -> List[str]:
        """
        Gibt Symbole basierend auf dem Listen-Typ zurück.

        Args:
            list_type: "stable", "risk", oder "all"
            force_refresh: Wenn True, wird der Cache invalidiert

        Returns:
            Liste von Symbolen
        """
        if list_type == "stable":
            return self.get_stable_symbols(force_refresh)
        elif list_type == "risk":
            return self.get_risk_symbols(force_refresh)
        else:  # "all"
            return self._all_symbols.copy()

    def get_stability_split_stats(self) -> Dict:
        """
        Gibt Statistiken zur Stability-Aufteilung zurück.

        Returns:
            Dict mit Statistiken
        """
        stable = self.get_stable_symbols()
        risk = self.get_risk_symbols()
        total = len(self._all_symbols)

        return {
            "enabled": self._stability_split_enabled,
            "min_score_threshold": self._stable_min_score,
            "total_symbols": total,
            "stable_count": len(stable),
            "risk_count": len(risk),
            "stable_pct": round(len(stable) / total * 100, 1) if total > 0 else 0,
            "risk_pct": round(len(risk) / total * 100, 1) if total > 0 else 0,
        }

    @property
    def stability_split_enabled(self) -> bool:
        """Gibt zurück ob Stability Split aktiviert ist"""
        return self._stability_split_enabled


_loader_instance: Optional[WatchlistLoader] = None
_loader_lock = threading.Lock()


def get_watchlist_loader(force_reload: bool = False) -> WatchlistLoader:
    """
    Gibt den WatchlistLoader Singleton zurück. Thread-safe.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.

    Args:
        force_reload: Wenn True, wird der Singleton neu erstellt (z.B. nach Config-Änderungen)
    """
    try:
        from ..utils.deprecation import warn_singleton_usage
        warn_singleton_usage("get_watchlist_loader", "ServiceContainer.watchlist_loader")
    except ImportError:
        pass

    global _loader_instance
    with _loader_lock:
        if _loader_instance is None or force_reload:
            _loader_instance = WatchlistLoader()
        return _loader_instance


def reset_watchlist_loader() -> None:
    """Setzt den Singleton zurück, damit die Config neu geladen wird."""
    global _loader_instance
    with _loader_lock:
        _loader_instance = None
