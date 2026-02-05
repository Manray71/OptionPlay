# OptionPlay - Scanner Configuration
# ====================================
"""
Configuration dataclasses and enums for the Multi-Strategy Scanner.

Extracted from multi_strategy_scanner.py (Phase 5 - Monolith Aufbrechen).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

try:
    from ..constants.trading_rules import ENTRY_STABILITY_MIN, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX
except ImportError:
    try:
        from constants.trading_rules import ENTRY_STABILITY_MIN, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX
    except ImportError:
        ENTRY_STABILITY_MIN = 70.0
        ENTRY_PRICE_MIN = 20.0
        ENTRY_PRICE_MAX = 1500.0


class ScanMode(Enum):
    """Scan-Modi für verschiedene Anwendungsfälle"""
    ALL = "all"                    # Alle Strategien
    PULLBACK_ONLY = "pullback"    # Nur Pullbacks (für Bull-Put-Spreads)
    BREAKOUT_ONLY = "breakout"    # Nur ATH Breakouts
    BOUNCE_ONLY = "bounce"        # Nur Support Bounces
    EARNINGS_DIP = "earnings_dip" # Nur Earnings Dips
    BEST_SIGNAL = "best"          # Nur bestes Signal pro Symbol


@dataclass
class ScanConfig:
    """Konfiguration für den Scanner"""
    # Score-Filter (normalized 0-10 scale)
    min_score: float = 3.5  # Minimum score for signal (normalized)
    min_actionable_score: float = 5.0  # Strong actionable signal

    # Earnings-Filter
    exclude_earnings_within_days: int = 60

    # IV-Rank Filter (für Credit-Spreads wichtig!)
    iv_rank_minimum: float = 30.0   # Min IV-Rank für ausreichend Prämie
    iv_rank_maximum: float = 80.0   # Max IV-Rank (zu hohe IV = erhöhtes Risiko)
    enable_iv_filter: bool = True   # IV-Filter aktivieren/deaktivieren

    # Liquidity Filter (basiert auf historischen Options-Daten)
    enable_liquidity_filter: bool = True  # Illiquide Symbole ausschließen

    # Output-Limits
    max_results_per_symbol: int = 3
    max_total_results: int = 50

    # Portfolio Concentration (verhindert zu viel Exposure auf ein Symbol)
    max_symbol_appearances: int = 2  # Max Anzahl ein Symbol in Multi-Strategy Results
    warn_on_concentration: bool = True  # Warnung bei hoher Symbol-Konzentration

    # Parallel Processing
    max_concurrent: int = 10

    # Data Requirements
    min_data_points: int = 60

    # Strategies to enable
    enable_pullback: bool = True
    enable_ath_breakout: bool = True
    enable_bounce: bool = True
    enable_earnings_dip: bool = True

    # Analyzer Pool Settings
    use_analyzer_pool: bool = True   # Object Pooling für Performance
    pool_size_per_strategy: int = 5  # Analyzer pro Strategie im Pool

    # Reliability Scoring (Phase 3 - Hochverlässlichkeits-Framework)
    enable_reliability_scoring: bool = True  # Reliability-Grades berechnen
    reliability_model_path: Optional[str] = None  # Pfad zum trainierten Modell
    reliability_min_grade: str = "D"  # Mindest-Grade für Signale (A-F)

    # Symbol Stability Filtering (Phase 4 - Outcome-basierte Filterung)
    enable_stability_scoring: bool = True  # Stability Scores aus Backtest-DB
    stability_min_score: float = ENTRY_STABILITY_MIN  # PLAYBOOK §1: ≥70
    stability_boost_threshold: float = 70.0  # Ab diesem Score wird Score erhöht
    stability_boost_amount: float = 1.0  # Score-Boost für stabile Symbole (LEGACY)
    warn_on_volatile_symbols: bool = True  # Warnung bei volatilen Symbolen

    # =========================================================================
    # STABILITY-FIRST FILTERING (Phase 6 - Stability > Score)
    # =========================================================================
    # Basierend auf Training-Ergebnissen:
    # - Stability ≥80: 94.5% Win Rate (Premium-Symbole)
    # - Stability 70-80: 86.1% Win Rate (Gute Symbole)
    # - Stability 50-70: 75% Win Rate (Akzeptabel)
    # - Stability <50: 66.0% Win Rate (Blacklist)
    enable_stability_first: bool = True  # Stability-First-Filterung aktivieren

    # Tiered Thresholds: Je höher Stability, desto niedriger min_score erlaubt
    stability_premium_threshold: float = 80.0  # Premium-Symbole (94.5% WR)
    stability_premium_min_score: float = 4.0   # Niedrigerer Score OK für Premium
    stability_good_threshold: float = 70.0     # Gute Symbole (86.1% WR)
    stability_good_min_score: float = 5.0      # Standard Score für gute Symbole
    stability_ok_threshold: float = 50.0       # Akzeptable Symbole
    stability_ok_min_score: float = 6.0        # Höherer Score für grenzwertige Symbole
    # Symbole unter stability_ok_threshold werden komplett gefiltert (Blacklist)

    # Win Rate Integration (Phase 5 - Proportionale Integration)
    # Formel: adjusted_score = base_score * (base_multiplier + win_rate/win_rate_divisor)
    # Beispiel: base=0.7, divisor=300, WR=90% => Multiplier = 0.7 + 0.30 = 1.0
    # Beispiel: base=0.7, divisor=300, WR=70% => Multiplier = 0.7 + 0.23 = 0.93
    enable_win_rate_integration: bool = True
    win_rate_base_multiplier: float = 0.7  # Basis-Multiplikator
    win_rate_divisor: float = 300.0  # Divisor für Win Rate (WR/Divisor = Bonus)

    # Drawdown Risk Adjustment (Phase 5 - Risk-basierte Filterung)
    enable_drawdown_adjustment: bool = True
    drawdown_penalty_threshold: float = 10.0  # Ab diesem Avg-Drawdown: Penalty
    drawdown_penalty_per_pct: float = 0.02  # Score-Reduktion pro % über Threshold

    # =========================================================================
    # FUNDAMENTALS PRE-FILTER (Phase 6 - symbol_fundamentals Integration)
    # =========================================================================
    # Filtert Symbole VOR dem Scan basierend auf Fundamentaldaten
    enable_fundamentals_filter: bool = True  # Master-Schalter

    # Stability-basierte Filterung (aus outcomes.db)
    fundamentals_min_stability: float = ENTRY_STABILITY_MIN  # PLAYBOOK §1: ≥70
    fundamentals_min_win_rate: float = 70.0   # Mindest historische Win Rate

    # Volatility-basierte Filterung
    fundamentals_max_volatility: float = 70.0  # Max HV (annualisiert %)
    fundamentals_max_beta: float = 2.0         # Max Beta zu SPY

    # IV Rank aus Fundamentals (symbol_fundamentals.iv_rank_252d)
    fundamentals_iv_rank_min: float = 20.0
    fundamentals_iv_rank_max: float = 80.0

    # SPY Correlation Filter
    fundamentals_max_spy_correlation: Optional[float] = None  # z.B. 0.7
    fundamentals_min_spy_correlation: Optional[float] = None  # z.B. 0.3

    # Sector/Market Cap Filter
    fundamentals_exclude_sectors: List[str] = field(default_factory=list)
    fundamentals_include_sectors: List[str] = field(default_factory=list)
    fundamentals_exclude_market_caps: List[str] = field(default_factory=list)
    fundamentals_include_market_caps: List[str] = field(default_factory=list)

    # Blacklist/Whitelist
    # Blacklist ist zentral in fundamentals_constants.py definiert
    fundamentals_blacklist: List[str] = field(default_factory=lambda: _get_default_blacklist_scanner())
    fundamentals_whitelist: List[str] = field(default_factory=list)  # Überschreibt alle Filter


def _get_default_blacklist_scanner() -> List[str]:
    """Lädt die Default-Blacklist aus fundamentals_constants."""
    try:
        from ..config.fundamentals_constants import DEFAULT_BLACKLIST
        return DEFAULT_BLACKLIST.copy()
    except ImportError:
        try:
            from config.fundamentals_constants import DEFAULT_BLACKLIST
            return DEFAULT_BLACKLIST.copy()
        except ImportError:
            # Fallback wenn Import fehlschlägt
            return [
                "ROKU", "SNAP", "UPST", "AFRM", "MRNA", "RUN", "MSTR", "TSLA", "COIN", "SQ",
                "DAVE", "IONQ", "QBTS", "QMCO", "QUBT", "RDW", "RGTI"
            ]
