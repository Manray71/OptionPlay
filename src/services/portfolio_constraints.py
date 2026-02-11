# OptionPlay - Portfolio Constraints Service
# ============================================
"""
Portfolio-Constraints für Risiko-Management und Diversifikation.

Features:
- Positions-Limits (max. Anzahl offene Positionen)
- Sektor-Diversifikation (max. N Positionen pro Sektor)
- Tägliches und wöchentliches Risk-Budget
- Korrelations-Warnungen (basierend auf SPY-Korrelation)
- Cash-Reserve Minimum

Verwendung:
    from src.services.portfolio_constraints import (
        PortfolioConstraints,
        PortfolioConstraintChecker,
        get_constraint_checker
    )

    checker = get_constraint_checker()

    # Prüfen ob neue Position geöffnet werden kann
    allowed, messages = checker.can_open_position(
        symbol="AAPL",
        max_risk=500.0,
        open_positions=[...]
    )

    if not allowed:
        print("Blocked:", messages)

Author: OptionPlay Team
Created: 2026-02-01
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from ..constants.trading_rules import (
    BLACKLIST_SYMBOLS,
    ENTRY_STABILITY_MIN,
    EXIT_PROFIT_PCT_NORMAL,
    VIXRegimeRules,
    get_regime_rules,
    get_vix_regime,
)

logger = logging.getLogger(__name__)


@dataclass
class PortfolioConstraints:
    """
    Konfigurierbare Portfolio-Constraints.

    Alle Limits sind konfigurierbar und können überschrieben werden.
    """

    # Position Limits
    max_positions: int = 5  # Max. offene Positionen
    max_per_sector: int = 2  # Max. Positionen pro Sektor

    # Risk Limits (USD)
    max_daily_risk_usd: float = 1500.0  # Max. Risiko pro Tag
    max_weekly_risk_usd: float = 5000.0  # Max. Risiko pro Woche
    max_position_size_usd: float = 2000.0  # Max. Risiko pro Position

    # Diversification
    max_correlation: float = 0.70  # Warnung bei höherer Korrelation
    min_cash_reserve_pct: float = 0.20  # Min. 20% Cash-Reserve

    # Sector-spezifische Limits (optional)
    sector_limits: dict[str, int] = field(default_factory=dict)

    # Blacklist (Symbole die nicht gehandelt werden) — Single Source: trading_rules.py
    symbol_blacklist: list[str] = field(default_factory=lambda: list(BLACKLIST_SYMBOLS))


@dataclass
class ConstraintResult:
    """Ergebnis einer Constraint-Prüfung."""

    allowed: bool
    blockers: list[str]  # Harte Blocker (Position darf nicht geöffnet werden)
    warnings: list[str]  # Warnungen (Position erlaubt, aber Vorsicht)
    details: dict[str, Any]  # Zusätzliche Details

    @property
    def messages(self) -> list[str]:
        """Alle Nachrichten (Blocker + Warnungen)."""
        return self.blockers + self.warnings


class PortfolioConstraintChecker:
    """
    Prüft Portfolio-Constraints vor dem Öffnen neuer Positionen.

    Verwendet symbol_fundamentals aus der DB für Sektor- und Korrelationsdaten.
    """

    def __init__(self, constraints: Optional[PortfolioConstraints] = None) -> None:
        """
        Initialisiert den Constraint Checker.

        Args:
            constraints: Optionale Custom-Constraints
        """
        self.constraints = constraints or PortfolioConstraints()
        self._fundamentals_manager: Any = None
        self._daily_risk_used: float = 0.0
        self._weekly_risk_used: float = 0.0
        self._vix_provider: Optional[Callable[[], float]] = None

    def set_vix_provider(self, provider: Callable[[], float]) -> None:
        """Set a callable that returns the current VIX value."""
        self._vix_provider = provider

    def get_position_limits(self, vix: Optional[float] = None) -> dict[str, Any]:
        """
        Gibt VIX-abhaengige Position-Limits zurueck (PLAYBOOK Sec.5).

        Bei keinem VIX-Wert werden die statischen Defaults verwendet.

        Args:
            vix: Aktueller VIX-Wert (optional)

        Returns:
            Dict mit max_positions, max_per_sector, risk_per_trade_pct,
            new_trades_allowed, stability_min
        """
        # Try to get VIX from provider if not passed
        if vix is None and self._vix_provider is not None:
            try:
                vix = self._vix_provider()
            except Exception as e:
                logger.debug(f"VIX provider failed: {e}")

        if vix is not None:
            rules = get_regime_rules(vix)
            return {
                "max_positions": rules.max_positions,
                "max_per_sector": rules.max_per_sector,
                "risk_per_trade_pct": rules.risk_per_trade_pct,
                "new_trades_allowed": rules.new_trades_allowed,
                "stability_min": rules.stability_min,
                "profit_exit_pct": rules.profit_exit_pct,
                "regime": rules.regime.value,
                "notes": rules.notes,
            }

        # Fallback: static defaults
        return {
            "max_positions": self.constraints.max_positions,
            "max_per_sector": self.constraints.max_per_sector,
            "risk_per_trade_pct": 2.0,
            "new_trades_allowed": True,
            "stability_min": ENTRY_STABILITY_MIN,
            "profit_exit_pct": EXIT_PROFIT_PCT_NORMAL,
            "regime": "UNKNOWN",
            "notes": "Keine VIX-Daten, verwende statische Defaults",
        }

    @property
    def fundamentals(self) -> Any:
        """Lazy-load Fundamentals Manager."""
        if self._fundamentals_manager is None:
            try:
                from ..cache import get_fundamentals_manager

                self._fundamentals_manager = get_fundamentals_manager()
            except ImportError:
                logger.warning("Fundamentals manager not available")
                self._fundamentals_manager = None
        return self._fundamentals_manager

    def can_open_position(
        self,
        symbol: str,
        max_risk: float,
        open_positions: list[dict[str, Any]],
        account_value: Optional[float] = None,
    ) -> tuple[bool, list[str]]:
        """
        Prüft ob eine neue Position geöffnet werden kann.

        Args:
            symbol: Ticker-Symbol der neuen Position
            max_risk: Maximales Risiko der neuen Position in USD
            open_positions: Liste der offenen Positionen
                            Jede Position braucht mindestens 'symbol' Key
            account_value: Optionaler Account-Wert für Cash-Reserve-Check

        Returns:
            Tuple von (erlaubt: bool, nachrichten: list[str])
            - erlaubt=True: Position kann geöffnet werden
            - erlaubt=False: Position wird geblockt
            - nachrichten: Blocker und Warnungen
        """
        result = self.check_all_constraints(
            symbol=symbol,
            max_risk=max_risk,
            open_positions=open_positions,
            account_value=account_value,
        )
        return result.allowed, result.messages

    def check_all_constraints(
        self,
        symbol: str,
        max_risk: float,
        open_positions: list[dict[str, Any]],
        account_value: Optional[float] = None,
        current_vix: Optional[float] = None,
    ) -> ConstraintResult:
        """
        Prüft alle Constraints und gibt detailliertes Ergebnis zurück.

        Verwendet VIX-abhängige Limits wenn VIX-Wert verfügbar (PLAYBOOK §5).

        Args:
            symbol: Ticker-Symbol
            max_risk: Max. Risiko in USD
            open_positions: Offene Positionen
            account_value: Account-Wert
            current_vix: Aktueller VIX-Wert (optional, für dynamische Limits)

        Returns:
            ConstraintResult mit Blockern, Warnungen und Details
        """
        blockers: list[str] = []
        warnings: list[str] = []

        # Get VIX-adjusted limits (falls back to static defaults if no VIX)
        limits = self.get_position_limits(vix=current_vix)
        max_positions = limits["max_positions"]
        max_per_sector = limits["max_per_sector"]
        regime = limits.get("regime", "UNKNOWN")

        details: dict[str, Any] = {
            "symbol": symbol,
            "max_risk": max_risk,
            "current_positions": len(open_positions),
            "vix_regime": regime,
            "max_positions": max_positions,
            "max_per_sector": max_per_sector,
        }

        # 0. VIX Regime: No new trades allowed?
        if not limits["new_trades_allowed"]:
            blockers.append(f"🚫 VIX-Regime {regime}: Keine neuen Trades erlaubt")
            details["new_trades_blocked"] = True

        # 1. Blacklist Check
        if self._check_blacklist(symbol):
            blockers.append(f"🚫 {symbol} ist auf der Blacklist (hohes Risiko)")
            details["blacklisted"] = True

        # 2. Position Limit Check (VIX-adjusted)
        pos_result = self._check_position_limit(open_positions, max_positions)
        if not pos_result[0]:
            blockers.append(pos_result[1])
            details["position_limit_reached"] = True

        # 3. Sector Limit Check (VIX-adjusted)
        sector_result = self._check_sector_limit(symbol, open_positions, max_per_sector)
        if not sector_result[0]:
            blockers.append(sector_result[1])
            details["sector"] = sector_result[2]
            details["sector_count"] = sector_result[3]

        # 4. Daily Risk Check
        daily_result = self._check_daily_risk(max_risk)
        if not daily_result[0]:
            blockers.append(daily_result[1])
            details["daily_risk_used"] = self._daily_risk_used

        # 5. Position Size Check
        if max_risk > self.constraints.max_position_size_usd:
            blockers.append(
                f"⚠️ Position zu groß: ${max_risk:.0f} > "
                f"Max ${self.constraints.max_position_size_usd:.0f}"
            )

        # 6. Correlation Check (Warnung, kein Blocker)
        corr_warnings = self._check_correlations(symbol, open_positions)
        warnings.extend(corr_warnings)

        # 7. Same Sector Warning (wenn unter Limit aber > 1)
        sector_count = self._count_sector_positions(symbol, open_positions)
        if sector_count >= 1 and sector_count < max_per_sector:
            sector = self._get_sector(symbol)
            warnings.append(f"⚠️ Bereits {sector_count} Position(en) im Sektor {sector}")

        # 8. Weekly Risk Warning
        if self._weekly_risk_used + max_risk > self.constraints.max_weekly_risk_usd * 0.8:
            remaining = self.constraints.max_weekly_risk_usd - self._weekly_risk_used
            warnings.append(
                f"⚠️ Wochen-Budget fast erschöpft: "
                f"${remaining:.0f} von ${self.constraints.max_weekly_risk_usd:.0f} verbleibend"
            )

        allowed = len(blockers) == 0
        details["allowed"] = allowed

        return ConstraintResult(
            allowed=allowed, blockers=blockers, warnings=warnings, details=details
        )

    def _check_blacklist(self, symbol: str) -> bool:
        """Prüft ob Symbol auf Blacklist ist."""
        return symbol.upper() in [s.upper() for s in self.constraints.symbol_blacklist]

    def _check_position_limit(
        self,
        open_positions: list[dict[str, Any]],
        max_positions: Optional[int] = None,
    ) -> tuple[bool, str]:
        """Prüft Positions-Limit (VIX-adjusted wenn max_positions übergeben)."""
        current = len(open_positions)
        max_pos = max_positions if max_positions is not None else self.constraints.max_positions

        if current >= max_pos:
            return False, f"🚫 Positions-Limit erreicht: {current}/{max_pos}"

        return True, ""

    def _check_sector_limit(
        self,
        symbol: str,
        open_positions: list[dict[str, Any]],
        max_per_sector: Optional[int] = None,
    ) -> tuple[bool, str, str, int]:
        """
        Prüft Sektor-Limit (VIX-adjusted wenn max_per_sector übergeben).

        Returns:
            Tuple von (erlaubt, nachricht, sektor, anzahl)
        """
        sector = self._get_sector(symbol)
        count = self._count_sector_positions(symbol, open_positions)

        # Base limit: VIX-adjusted or static default
        base_limit = (
            max_per_sector if max_per_sector is not None else self.constraints.max_per_sector
        )

        # Sector-specific override: use the stricter (lower) of both
        sector_specific = self.constraints.sector_limits.get(sector)
        if sector_specific is not None:
            sector_limit = min(base_limit, sector_specific)
        else:
            sector_limit = base_limit

        if count >= sector_limit:
            return (
                False,
                f"🚫 Sektor-Limit erreicht: {count}/{sector_limit} in {sector}",
                sector,
                count,
            )

        return True, "", sector, count

    def _check_daily_risk(self, max_risk: float) -> tuple[bool, str]:
        """Prüft tägliches Risk-Budget."""
        potential_total = self._daily_risk_used + max_risk
        max_daily = self.constraints.max_daily_risk_usd

        if potential_total > max_daily:
            remaining = max_daily - self._daily_risk_used
            return (
                False,
                f"🚫 Tages-Budget überschritten: "
                f"${remaining:.0f} verbleibend, ${max_risk:.0f} benötigt",
            )

        return True, ""

    def _check_correlations(self, symbol: str, open_positions: list[dict[str, Any]]) -> list[str]:
        """
        Prüft Korrelationen mit bestehenden Positionen.

        Returns:
            Liste von Warnungen
        """
        warnings = []
        max_corr = self.constraints.max_correlation

        for pos in open_positions:
            pos_symbol = pos.get("symbol", "")
            if not pos_symbol or pos_symbol == symbol:
                continue

            corr = self._get_correlation(symbol, pos_symbol)
            if corr and corr > max_corr:
                warnings.append(f"⚠️ Hohe Korrelation ({corr:.2f}) mit {pos_symbol}")

        return warnings

    def _get_sector(self, symbol: str) -> str:
        """Holt Sektor für Symbol aus Fundamentals."""
        if not self.fundamentals:
            return "Unknown"

        try:
            f = self.fundamentals.get_fundamentals(symbol)
            return f.sector if f and f.sector else "Unknown"
        except Exception as e:
            logger.debug(f"Error getting sector for {symbol}: {e}")
            return "Unknown"

    def _count_sector_positions(self, symbol: str, open_positions: list[dict[str, Any]]) -> int:
        """Zählt offene Positionen im gleichen Sektor."""
        target_sector = self._get_sector(symbol)

        if target_sector == "Unknown":
            return 0

        count = 0
        for pos in open_positions:
            pos_symbol = pos.get("symbol", "")
            if not pos_symbol:
                continue

            pos_sector = self._get_sector(pos_symbol)
            if pos_sector == target_sector:
                count += 1

        return count

    def _get_correlation(self, sym1: str, sym2: str) -> Optional[float]:
        """
        Berechnet approximierte Korrelation zwischen zwei Symbolen.

        Verwendet:
        1. Gleicher Sektor = hohe Korrelation (0.75)
        2. SPY-Korrelation als Proxy
        """
        if not self.fundamentals:
            return None

        try:
            f1 = self.fundamentals.get_fundamentals(sym1)
            f2 = self.fundamentals.get_fundamentals(sym2)

            if not f1 or not f2:
                return None

            # Gleicher Sektor = hohe Korrelation
            if f1.sector and f2.sector and f1.sector == f2.sector:
                return 0.75

            # SPY-Korrelation als Proxy
            # Wenn beide stark mit SPY korrelieren, korrelieren sie auch miteinander
            if f1.spy_correlation_60d and f2.spy_correlation_60d:
                # Approximation: Produkt der SPY-Korrelationen
                corr1 = f1.spy_correlation_60d
                corr2 = f2.spy_correlation_60d
                # Wenn beide > 0.7 mit SPY, dann > 0.5 miteinander
                approx_corr = float(corr1) * float(corr2)
                return round(approx_corr, 2)

            return None

        except Exception as e:
            logger.debug(f"Error getting correlation for {sym1}/{sym2}: {e}")
            return None

    def update_risk_used(
        self,
        daily_risk: Optional[float] = None,
        weekly_risk: Optional[float] = None,
    ) -> None:
        """
        Aktualisiert verbrauchtes Risk-Budget.

        Args:
            daily_risk: Verbrauchtes tägliches Risiko
            weekly_risk: Verbrauchtes wöchentliches Risiko
        """
        if daily_risk is not None:
            self._daily_risk_used = daily_risk
        if weekly_risk is not None:
            self._weekly_risk_used = weekly_risk

    def reset_daily_risk(self) -> None:
        """Setzt tägliches Risk-Budget zurück (für neuen Trading-Tag)."""
        self._daily_risk_used = 0.0

    def reset_weekly_risk(self) -> None:
        """Setzt wöchentliches Risk-Budget zurück (für neue Woche)."""
        self._weekly_risk_used = 0.0

    def get_status(self) -> dict[str, Any]:
        """Gibt aktuellen Constraint-Status zurück."""
        return {
            "constraints": {
                "max_positions": self.constraints.max_positions,
                "max_per_sector": self.constraints.max_per_sector,
                "max_daily_risk_usd": self.constraints.max_daily_risk_usd,
                "max_weekly_risk_usd": self.constraints.max_weekly_risk_usd,
                "max_position_size_usd": self.constraints.max_position_size_usd,
                "max_correlation": self.constraints.max_correlation,
                "symbol_blacklist": self.constraints.symbol_blacklist,
            },
            "current": {
                "daily_risk_used": self._daily_risk_used,
                "weekly_risk_used": self._weekly_risk_used,
                "daily_remaining": self.constraints.max_daily_risk_usd - self._daily_risk_used,
                "weekly_remaining": self.constraints.max_weekly_risk_usd - self._weekly_risk_used,
            },
        }


# Singleton Instance
_constraint_checker: Optional[PortfolioConstraintChecker] = None


def get_constraint_checker(
    constraints: Optional[PortfolioConstraints] = None,
) -> PortfolioConstraintChecker:
    """
    Gibt Singleton PortfolioConstraintChecker zurück.

    Args:
        constraints: Optionale Custom-Constraints (nur beim ersten Aufruf relevant)

    Returns:
        PortfolioConstraintChecker Instanz
    """
    global _constraint_checker

    if _constraint_checker is None:
        _constraint_checker = PortfolioConstraintChecker(constraints)

    return _constraint_checker


def reset_constraint_checker() -> None:
    """Setzt Singleton zurück (für Tests)."""
    global _constraint_checker
    _constraint_checker = None
