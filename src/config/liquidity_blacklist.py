"""
Liquidity Blacklist — geladen aus config/system.yaml.
Kein hardcodierter Content mehr.
"""
from pathlib import Path

import yaml


def _load_blacklist() -> frozenset:
    config_path = Path(__file__).resolve().parents[2] / "config" / "system.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    symbols = cfg.get("liquidity_blacklist", {}).get("symbols", [])
    return frozenset(symbols)


ILLIQUID_OPTIONS_BLACKLIST: frozenset = _load_blacklist()


def is_illiquid(symbol: str) -> bool:
    """Prüft ob ein Symbol auf der Illiquiditäts-Blacklist steht."""
    return symbol.upper() in ILLIQUID_OPTIONS_BLACKLIST


def filter_liquid_symbols(symbols: list[str]) -> list[str]:
    """Filtert illiquide Symbole aus einer Liste."""
    return [s for s in symbols if not is_illiquid(s)]


def get_illiquid_count() -> int:
    """Gibt die Anzahl der Symbole auf der Blacklist zurück."""
    return len(ILLIQUID_OPTIONS_BLACKLIST)


__all__ = [
    "ILLIQUID_OPTIONS_BLACKLIST",
    "is_illiquid",
    "filter_liquid_symbols",
    "get_illiquid_count",
]
