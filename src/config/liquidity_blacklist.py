# OptionPlay - Liquidity Blacklist
# =================================
# Symbole mit zu niedriger Options-Liquidität
# Diese werden automatisch vom Scanner ausgeschlossen
#
# Kriterium: < 300 historische Options-Bars in der Datenbank
# Generiert am: 2026-01-28
# Basiert auf: 409k+ Options-Datenpunkten von Tradier

"""
Illiquide Options-Symbole.

Diese Symbole haben zu wenige Options-Datenpunkte (<300 Bars),
was auf sehr geringe Options-Liquidität hindeutet.

Probleme bei illiquiden Optionen:
- Weite Bid-Ask Spreads (schlechte Fills)
- Geringe Open Interest (schwierig zu schließen)
- Ungenaue Preisstellung
- Slippage bei Ausführung

Empfehlung: Diese Symbole nicht für Bull-Put-Spreads verwenden.
"""

# =============================================================================
# ILLIQUID OPTIONS BLACKLIST (230 Symbole mit < 300 Bars)
# =============================================================================

# Gruppierung nach Liquiditäts-Level:
#   - Sehr niedrig (<50 Bars):    35 Symbole - praktisch illiquide
#   - Niedrig (50-99 Bars):       49 Symbole - sehr dünn gehandelt
#   - Mittel-niedrig (100-199):   67 Symbole - eingeschränkt nutzbar
#   - Mittel (200-299):           79 Symbole - eingeschränkt nutzbar

ILLIQUID_OPTIONS_BLACKLIST = {
    # === SEHR NIEDRIG (<50 Bars) - Praktisch illiquide ===
    "NWS",
    "FOX",
    "REG",
    "STE",
    "KRYS",
    "IEX",
    "NWSA",
    "AIZ",
    "SLAB",
    "WAT",
    "VLTO",
    "CRNX",
    "NDSN",
    "L",
    "RVTY",
    "ALLE",
    "ERIE",
    "PKG",
    "FTV",
    "AVY",
    "FORM",
    "PFG",
    "HSIC",
    "WAB",
    "GFS",
    "LNT",
    "WTW",
    "CHPT",
    "GL",
    "HUBB",
    "ROP",
    "TECH",
    "MTD",
    "CPAY",
    "EPAM",
    # === NIEDRIG (50-99 Bars) - Sehr dünn gehandelt ===
    "PNW",
    "HST",
    "AEE",
    "EXAS",
    "CMS",
    "SW",
    "UDR",
    "ATO",
    "PODD",
    "Q",
    "AMCR",
    "AOS",
    "WOLF",
    "TRMB",
    "CRL",
    "SNA",
    "ROL",
    "CPT",
    "DTE",
    "EXPD",
    "RDW",
    "VRSK",
    "FRT",
    "JKHY",
    "BG",
    "MAS",
    "TDY",
    "PTC",
    "VTRS",
    "DOCN",
    "GLBE",
    "ESS",
    "EVRG",
    "FOXA",
    "EG",
    "J",
    "SOLV",
    "VTR",
    "CRUS",
    "LII",
    "WST",
    "MLM",
    "KIM",
    "BRO",
    "NI",
    "NTRS",
    "CINF",
    "IR",
    "BR",
    # === MITTEL-NIEDRIG (100-199 Bars) - Eingeschränkt nutzbar ===
    "CDW",
    "TYL",
    "PNR",
    "AME",
    "NTRA",
    "ES",
    "LH",
    "TRGP",
    "IQV",
    "TME",
    "ZBRA",
    "DOC",
    "CBRE",
    "COO",
    "CHRW",
    "HII",
    "KEYS",
    "AMP",
    "HOLX",
    "CTVA",
    "WRB",
    "DAY",
    "GDDY",
    "AKAM",
    "UHS",
    "CHD",
    "EA",
    "DOV",
    "TXT",
    "HAS",
    "RJF",
    "ODFL",
    "SBAC",
    "DD",
    "BXP",
    "RMBS",
    "XYL",
    "VMC",
    "GLW",
    "GEN",
    "TSN",
    "CSGP",
    "ACGL",
    "VRSN",
    "CFLT",
    "TPL",
    "IVZ",
    "HIG",
    "EFX",
    "LHX",
    "MTB",
    "WEC",
    "ZBH",
    "ECL",
    "EXR",
    "VICI",
    "INCY",
    "BEN",
    "PAYC",
    "TKO",
    "CFG",
    "LCID",
    "ALB",
    "TER",
    "MPWR",
    "EQR",
    "INVH",
    # === MITTEL (200-299 Bars) - Eingeschränkt nutzbar ===
    "FIX",
    "MNDY",
    "BALL",
    "FISV",
    "ETR",
    "TDG",
    "AVB",
    "MOS",
    "LUNR",
    "GWW",
    "IDXX",
    "PPL",
    "CNP",
    "APH",
    "BKR",
    "LW",
    "STT",
    "ESTC",
    "GRMN",
    "OMC",
    "JBHT",
    "NTAP",
    "RSG",
    "MAA",
    "RMD",
    "DLO",
    "SRE",
    "DVA",
    "HUBS",
    "KEY",
    "RL",
    "CBOE",
    "EME",
    "SLB",
    "BEKE",
    "VEEV",
    "GPC",
    "CAH",
    "PENN",
    "XEL",
    "BK",
    "LRCX",
    "PH",
    "JBL",
    "KTOS",
    "TSCO",
    "CTRA",
    "PEG",
    "ROK",
    "WMB",
    "MCO",
    "LI",
    "AON",
    "FIS",
    "IT",
    "XLRE",
    "MKC",
    "WSM",
    "AES",
    "FFIV",
    "ADM",
    "NIO",
    "WDC",
    "COR",
    "DGX",
    "TEL",
    "A",
    "ED",
    "TAP",
    "TRV",
    "IFF",
    "SWKS",
    "PCAR",
    "NSC",
    "MTCH",
    "WY",
    "POOL",
    "EIX",
    "MSCI",
}


def is_illiquid(symbol: str) -> bool:
    """
    Prüft ob ein Symbol auf der Illiquiditäts-Blacklist steht.

    Args:
        symbol: Ticker-Symbol (case-insensitive)

    Returns:
        True wenn illiquide (sollte gemieden werden)
    """
    return symbol.upper() in ILLIQUID_OPTIONS_BLACKLIST


def filter_liquid_symbols(symbols: list[str]) -> list[str]:
    """
    Filtert illiquide Symbole aus einer Liste.

    Args:
        symbols: Liste von Ticker-Symbolen

    Returns:
        Liste ohne illiquide Symbole
    """
    return [s for s in symbols if not is_illiquid(s)]


def get_illiquid_count() -> int:
    """Gibt die Anzahl der Symbole auf der Blacklist zurück."""
    return len(ILLIQUID_OPTIONS_BLACKLIST)


# Convenience für direkten Import
__all__ = [
    "ILLIQUID_OPTIONS_BLACKLIST",
    "is_illiquid",
    "filter_liquid_symbols",
    "get_illiquid_count",
]
