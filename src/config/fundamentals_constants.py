# OptionPlay - Fundamentals Filter Constants
# ==========================================
# Zentrale Konstanten für Fundamentals-basierte Filterung.
#
# Diese Datei enthält die aus dem Training (2026-01-31) abgeleiteten
# Konstanten für Symbol-Filterung basierend auf historischen Backtest-Ergebnissen.
#
# Änderungen hier wirken sich auf:
# - config_loader.py (FundamentalsFilterConfig Defaults)
# - multi_strategy_scanner.py (ScanConfig Defaults)
# - settings.yaml (sollte synchron gehalten werden)

from typing import List, Tuple

try:
    from ..constants.trading_rules import ENTRY_IV_RANK_MAX
except ImportError:
    from constants.trading_rules import ENTRY_IV_RANK_MAX

# =============================================================================
# BLACKLIST - Symbole die NIEMALS gehandelt werden sollten
# =============================================================================
# Kriterien: Stability Score < 50 ODER Win Rate < 70%
# Quelle: Training-Erkenntnisse aus 17.438 Backtest-Trades

# Symbole mit historisch schlechter Performance
BLACKLIST_LOW_STABILITY: List[str] = [
    "ROKU",    # Stability 24, WR 61%
    "SNAP",    # Stability 13, WR 64%
    "UPST",    # Stability 15, WR 60%
    "AFRM",    # Stability 18, WR 66%
    "MRNA",    # Stability 30, WR 64%
    "RUN",     # Stability 0, WR 40%
    "MSTR",    # Stability 37, WR 58%
    "TSLA",    # Stability 41, WR 78% (Meme-Stock-Dynamik)
    "COIN",    # Stability 33, WR 73% (Crypto-Korrelation)
    "SQ",      # Stability 36, WR 68%
]

# Extreme-Volatilität Symbole (>100% annualisierte Volatilität)
BLACKLIST_EXTREME_VOL: List[str] = [
    "DAVE",    # Fintech, >100% Vol
    "IONQ",    # Quantum Computing, >100% Vol
    "QBTS",    # Quantum Computing, >100% Vol
    "QMCO",    # Quantum Computing, >100% Vol
    "QUBT",    # Quantum Computing, >100% Vol
    "RDW",     # Space/SPAC, >100% Vol
    "RGTI",    # Quantum Computing, >100% Vol
]

# Kombinierte Blacklist (für einfachen Import)
DEFAULT_BLACKLIST: List[str] = BLACKLIST_LOW_STABILITY + BLACKLIST_EXTREME_VOL


# =============================================================================
# FILTER DEFAULTS - Basierend auf Training-Erkenntnissen
# =============================================================================

# Stability Filter
# Stability Score >= 70 → 94.5% Win Rate (vs. 66% bei <50)
DEFAULT_MIN_STABILITY_SCORE: float = 50.0
DEFAULT_WARN_BELOW_STABILITY: float = 60.0
DEFAULT_BOOST_ABOVE_STABILITY: float = 70.0

# Win Rate Filter
DEFAULT_MIN_HISTORICAL_WIN_RATE: float = 70.0

# Volatility Filter
# HV > 70% hat nur 27-31% Win Rate → ausschließen
DEFAULT_MAX_HISTORICAL_VOLATILITY: float = 70.0
DEFAULT_MAX_BETA: float = 2.0

# IV Rank Filter
# Optimal: IV Rank 20-80 (ausreichend Prämie, nicht zu riskant)
DEFAULT_IV_RANK_MIN: float = 20.0
DEFAULT_IV_RANK_MAX: float = ENTRY_IV_RANK_MAX  # from trading_rules (80.0)

# Market Cap Filter
# Micro Caps ausschließen (weniger liquide, höheres Risiko)
DEFAULT_EXCLUDE_MARKET_CAPS: List[str] = ["Micro"]


# =============================================================================
# STABILITY TIERS - Für Score-Adjustierung
# =============================================================================

# (min_stability, max_stability, win_rate_range, recommendation)
STABILITY_TIERS: List[Tuple[float, float, str, str]] = [
    (80.0, 100.0, "94-96%", "EXCELLENT - Bevorzugen"),
    (70.0, 80.0, "89-94%", "VERY_GOOD - Empfohlen"),
    (60.0, 70.0, "85-89%", "GOOD - Akzeptabel"),
    (50.0, 60.0, "75-85%", "MODERATE - Mit Vorsicht"),
    (0.0, 50.0, "<75%", "POOR - Vermeiden"),
]


def get_stability_tier(stability_score: float) -> Tuple[str, str]:
    """
    Gibt das Stability-Tier und die erwartete Win Rate Range zurück.

    Args:
        stability_score: Stability Score (0-100)

    Returns:
        Tuple: (win_rate_range, recommendation)
    """
    for min_s, max_s, wr_range, recommendation in STABILITY_TIERS:
        if min_s <= stability_score < max_s:
            return wr_range, recommendation
    return "<75%", "POOR - Vermeiden"


# =============================================================================
# VOLATILITY CLUSTERS - Aus Training
# =============================================================================

VOLATILITY_CLUSTERS = {
    "low_vol": {
        "max_volatility": 30.0,
        "max_beta": 0.5,
        "expected_win_rate": 80.0,
        "recommendation": "EXCELLENT",
    },
    "moderate": {
        "max_volatility": 50.0,
        "max_beta": 1.0,
        "expected_win_rate": 75.0,
        "recommendation": "GOOD",
    },
    "high_vol": {
        "max_volatility": 70.0,
        "max_beta": 1.5,
        "expected_win_rate": 65.0,
        "recommendation": "BORDERLINE",
    },
    "extreme_vol": {
        "max_volatility": 100.0,
        "max_beta": 2.0,
        "expected_win_rate": 30.0,
        "recommendation": "EXCLUDE",
    },
}
