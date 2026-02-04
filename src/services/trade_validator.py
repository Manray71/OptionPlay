# OptionPlay - Trade Validator Service
# ======================================
"""
Validates trade ideas against PLAYBOOK rules.

Returns GO / NO_GO / WARNING for any trade idea.
All rules are sourced from constants/trading_rules.py.

Usage:
    from src.services.trade_validator import TradeValidator, TradeValidationRequest

    validator = TradeValidator()
    result = await validator.validate(TradeValidationRequest(
        symbol="AAPL",
        short_strike=175.0,
        expiration="2026-04-17",
    ))

    if result.decision == TradeDecision.GO:
        print("Trade is valid!")
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..constants.trading_rules import (
    TradeDecision,
    VIXRegime,
    ENTRY_STABILITY_MIN,
    ENTRY_EARNINGS_MIN_DAYS,
    ENTRY_VIX_MAX_NEW_TRADES,
    ENTRY_VIX_NO_TRADING,
    ENTRY_PRICE_MIN,
    ENTRY_PRICE_MAX,
    ENTRY_VOLUME_MIN,
    ENTRY_IV_RANK_MIN,
    ENTRY_IV_RANK_MAX,
    BLACKLIST_SYMBOLS,
    is_blacklisted,
    get_adjusted_stability_min,
    SPREAD_DTE_MIN,
    SPREAD_DTE_MAX,
    SPREAD_SHORT_DELTA_TARGET,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_LONG_DELTA_MIN,
    SPREAD_LONG_DELTA_MAX,
    SPREAD_MIN_CREDIT_PCT,
    SPREAD_MIN_CREDIT_ABSOLUTE,
    SPREAD_FEE_WARNING_THRESHOLD,
    SPREAD_IBKR_ROUND_TRIP_FEE,
    SIZING_MAX_OPEN_POSITIONS,
    SIZING_MAX_PER_SECTOR,
    SIZING_MAX_RISK_PER_TRADE_PCT,
    SIZING_MAX_NEW_TRADES_PER_DAY,
    get_vix_regime,
    get_regime_rules,
    FILTER_ORDER,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TradeValidationRequest:
    """Input for trade validation."""
    symbol: str
    short_strike: Optional[float] = None
    long_strike: Optional[float] = None
    expiration: Optional[str] = None    # YYYY-MM-DD
    credit: Optional[float] = None
    contracts: Optional[int] = None
    portfolio_value: Optional[float] = None


@dataclass
class ValidationCheck:
    """Result of a single validation check."""
    name: str
    passed: bool
    decision: TradeDecision       # GO, NO_GO, or WARNING
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeValidationResult:
    """Complete validation result."""
    symbol: str
    decision: TradeDecision
    checks: List[ValidationCheck]
    regime: Optional[str] = None
    regime_notes: Optional[str] = None
    sizing_recommendation: Optional[Dict[str, Any]] = None

    @property
    def blockers(self) -> List[ValidationCheck]:
        """All checks that returned NO_GO."""
        return [c for c in self.checks if c.decision == TradeDecision.NO_GO]

    @property
    def warnings(self) -> List[ValidationCheck]:
        """All checks that returned WARNING."""
        return [c for c in self.checks if c.decision == TradeDecision.WARNING]

    @property
    def passed(self) -> List[ValidationCheck]:
        """All checks that returned GO."""
        return [c for c in self.checks if c.decision == TradeDecision.GO]

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        if self.decision == TradeDecision.GO:
            warn_count = len(self.warnings)
            if warn_count > 0:
                return f"GO mit {warn_count} Warnung(en)"
            return "GO — Alle Regeln erfüllt"
        elif self.decision == TradeDecision.NO_GO:
            reasons = [c.message for c in self.blockers]
            return f"NO-GO — {'; '.join(reasons)}"
        else:
            reasons = [c.message for c in self.warnings]
            return f"WARNING — {'; '.join(reasons)}"


# =============================================================================
# TRADE VALIDATOR
# =============================================================================

class TradeValidator:
    """
    Validates trades against PLAYBOOK rules.

    Uses local data + optional quote provider for volume:
    - symbol_fundamentals DB for stability, sector, price
    - earnings_history DB for earnings dates
    - VIX from cache or DB
    - Quote provider (Tradier/IBKR) for live volume data
    """

    def __init__(self, quote_provider=None):
        self._fundamentals_manager = None
        self._earnings_manager = None
        self._quote_provider = quote_provider

    @property
    def fundamentals(self):
        """Lazy-load Fundamentals Manager."""
        if self._fundamentals_manager is None:
            try:
                from ..cache import get_fundamentals_manager
                self._fundamentals_manager = get_fundamentals_manager()
            except ImportError:
                logger.warning("Fundamentals manager not available")
        return self._fundamentals_manager

    @property
    def earnings(self):
        """Lazy-load Earnings History Manager."""
        if self._earnings_manager is None:
            try:
                from ..cache import get_earnings_history_manager
                self._earnings_manager = get_earnings_history_manager()
            except ImportError:
                logger.warning("Earnings history manager not available")
        return self._earnings_manager

    async def validate(
        self,
        request: TradeValidationRequest,
        current_vix: Optional[float] = None,
        open_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> TradeValidationResult:
        """
        Run all PLAYBOOK checks against a trade idea.

        Args:
            request: Trade details to validate
            current_vix: Current VIX level (if None, fetched from cache/DB)
            open_positions: Currently open positions for portfolio checks

        Returns:
            TradeValidationResult with GO/NO_GO/WARNING decision
        """
        symbol = request.symbol.upper()
        checks: List[ValidationCheck] = []

        # Get VIX if not provided
        if current_vix is None:
            current_vix = await self._get_current_vix()

        # Get fundamentals
        fundamentals = None
        if self.fundamentals:
            try:
                fundamentals = self.fundamentals.get_fundamentals(symbol)
            except Exception as e:
                logger.debug(f"Error getting fundamentals for {symbol}: {e}")

        # Run checks in PLAYBOOK order (§1 Prüf-Reihenfolge)
        checks.append(self._check_blacklist(symbol))
        checks.append(self._check_stability(symbol, fundamentals, current_vix))
        checks.append(await self._check_earnings(symbol))
        checks.append(self._check_vix(current_vix))
        checks.append(self._check_price(symbol, fundamentals))
        checks.append(await self._check_volume(symbol, fundamentals))
        checks.append(self._check_iv_rank(symbol, fundamentals))

        # Spread parameter checks (if provided)
        if request.expiration:
            checks.append(self._check_dte(request.expiration))

        if request.short_strike and request.long_strike and request.credit:
            spread_width = abs(request.short_strike - request.long_strike)
            checks.append(self._check_credit(request.credit, spread_width))

        # Portfolio checks (if positions provided)
        if open_positions is not None:
            checks.extend(self._check_portfolio(
                symbol, fundamentals, open_positions, current_vix
            ))

        # Position sizing recommendation
        sizing = None
        if request.portfolio_value and request.short_strike and request.long_strike and request.credit:
            sizing = self._calculate_sizing(
                request, fundamentals, current_vix
            )

        # Determine overall decision
        has_blocker = any(c.decision == TradeDecision.NO_GO for c in checks)
        has_warning = any(c.decision == TradeDecision.WARNING for c in checks)

        if has_blocker:
            decision = TradeDecision.NO_GO
        elif has_warning:
            decision = TradeDecision.WARNING
        else:
            decision = TradeDecision.GO

        # Get regime info
        regime = None
        regime_notes = None
        if current_vix is not None:
            vix_regime = get_vix_regime(current_vix)
            regime_rules = get_regime_rules(current_vix)
            regime = f"{vix_regime.value} (VIX {current_vix:.1f})"
            regime_notes = regime_rules.notes

        return TradeValidationResult(
            symbol=symbol,
            decision=decision,
            checks=checks,
            regime=regime,
            regime_notes=regime_notes,
            sizing_recommendation=sizing,
        )

    # =========================================================================
    # INDIVIDUAL CHECKS
    # =========================================================================

    def _check_blacklist(self, symbol: str) -> ValidationCheck:
        """Check 1: Blacklist (PLAYBOOK §1)."""
        if is_blacklisted(symbol):
            return ValidationCheck(
                name="blacklist",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"{symbol} ist auf der Blacklist",
                details={"blacklisted": True},
            )

        return ValidationCheck(
            name="blacklist",
            passed=True,
            decision=TradeDecision.GO,
            message="Nicht auf Blacklist",
        )

    def _check_stability(
        self,
        symbol: str,
        fundamentals: Any,
        current_vix: Optional[float],
    ) -> ValidationCheck:
        """Check 2: Stability Score (PLAYBOOK §1 + §3 VIX adjustment)."""
        if fundamentals is None or fundamentals.stability_score is None:
            return ValidationCheck(
                name="stability",
                passed=False,
                decision=TradeDecision.WARNING,
                message=f"Stability Score für {symbol} nicht verfügbar",
                details={"stability": None},
            )

        stability = fundamentals.stability_score

        # VIX-adjusted minimum (PLAYBOOK §3)
        min_stability = get_adjusted_stability_min(current_vix)

        if stability < min_stability:
            return ValidationCheck(
                name="stability",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"Stability {stability:.0f} < {min_stability:.0f} (Minimum)",
                details={
                    "stability": stability,
                    "required": min_stability,
                    "vix_adjusted": min_stability != ENTRY_STABILITY_MIN,
                },
            )

        return ValidationCheck(
            name="stability",
            passed=True,
            decision=TradeDecision.GO,
            message=f"Stability {stability:.0f} >= {min_stability:.0f}",
            details={"stability": stability, "required": min_stability},
        )

    async def _check_earnings(self, symbol: str) -> ValidationCheck:
        """Check 3: Earnings distance (PLAYBOOK §1)."""
        from ..utils.validation import is_etf

        # ETFs have no earnings
        if is_etf(symbol):
            return ValidationCheck(
                name="earnings",
                passed=True,
                decision=TradeDecision.GO,
                message="ETF — keine Earnings",
                details={"is_etf": True},
            )

        is_safe = None
        days_to = None
        reason = None
        source = "db"

        # 1. Try local DB first (fast, offline)
        if self.earnings is not None:
            try:
                is_safe, days_to, reason = self.earnings.is_earnings_day_safe(
                    symbol,
                    target_date=date.today(),
                    min_days=ENTRY_EARNINGS_MIN_DAYS,
                )
            except Exception as e:
                logger.debug(f"Earnings DB check failed for {symbol}: {e}")

        # 2. Fallback to Live-APIs if DB has no future earnings data
        if reason == "no_earnings_data" or (is_safe is None and self.earnings is None):
            is_safe, days_to, source = await self._fetch_earnings_from_api(symbol)
            if is_safe is not None:
                reason = "api_fallback"

        # 3. If still no data, return WARNING (not NO_GO)
        if is_safe is None:
            return ValidationCheck(
                name="earnings",
                passed=False,
                decision=TradeDecision.WARNING,
                message="Earnings-Daten nicht verfügbar (DB + API)",
                details={"source": "none"},
            )

        if not is_safe:
            days_str = f"{days_to} Tage" if days_to is not None else "unbekannt"
            return ValidationCheck(
                name="earnings",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"Earnings in {days_str} (Min: {ENTRY_EARNINGS_MIN_DAYS})",
                details={
                    "days_to_earnings": days_to,
                    "required": ENTRY_EARNINGS_MIN_DAYS,
                    "source": source,
                },
            )

        days_str = f"{days_to} Tage" if days_to is not None else ">60"
        return ValidationCheck(
            name="earnings",
            passed=True,
            decision=TradeDecision.GO,
            message=f"Earnings in {days_str} — sicher",
            details={"days_to_earnings": days_to, "source": source},
        )

    async def _fetch_earnings_from_api(
        self, symbol: str
    ) -> tuple:
        """
        Fetch earnings from Live-APIs as fallback when DB has no future data.

        Returns:
            Tuple (is_safe: Optional[bool], days_to: Optional[int], source: str)
        """
        import asyncio

        # Try EarningsFetcher (yfinance/yahoo)
        try:
            from ..cache import get_earnings_fetcher

            fetcher = get_earnings_fetcher()
            info = await asyncio.to_thread(fetcher.fetch, symbol)

            if info and info.earnings_date:
                days_to = info.days_to_earnings
                is_safe = info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS)

                # Write-through: save to DB for future lookups
                self._save_earnings_to_db(symbol, info.earnings_date, days_to)

                return (is_safe, days_to, f"api_{info.source.value}")
        except Exception as e:
            logger.debug(f"API earnings fallback failed for {symbol}: {e}")

        # Try Yahoo Finance direct API
        try:
            import json
            import urllib.request

            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=calendarEvents"
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')

            def _fetch():
                with urllib.request.urlopen(req, timeout=10) as response:
                    return json.loads(response.read().decode())

            data = await asyncio.to_thread(_fetch)
            calendar = data.get('quoteSummary', {}).get('result', [{}])[0].get('calendarEvents', {})
            earnings_dates = calendar.get('earnings', {}).get('earningsDate', [])

            if earnings_dates:
                from datetime import datetime as dt
                timestamp = earnings_dates[0].get('raw')
                if timestamp:
                    earnings_date = dt.fromtimestamp(timestamp).date()
                    days_to = (earnings_date - date.today()).days
                    is_safe = days_to >= ENTRY_EARNINGS_MIN_DAYS

                    self._save_earnings_to_db(
                        symbol, earnings_date.isoformat(), days_to
                    )

                    return (is_safe, days_to, "api_yahoo_direct")
        except Exception as e:
            logger.debug(f"Yahoo direct earnings failed for {symbol}: {e}")

        return (None, None, "none")

    def _save_earnings_to_db(
        self, symbol: str, earnings_date: str, days_to: Optional[int]
    ) -> None:
        """Write-through cache: save API earnings result to DB."""
        if self.earnings is None or days_to is None or days_to < 0:
            return

        try:
            self.earnings.save_earnings(symbol, [{
                "earnings_date": earnings_date,
                "source": "api_fallback",
            }])
            logger.debug(f"Saved API earnings for {symbol}: {earnings_date}")
        except Exception as e:
            logger.debug(f"Failed to save earnings for {symbol}: {e}")

    def _check_vix(self, current_vix: Optional[float]) -> ValidationCheck:
        """Check 4: VIX regime (PLAYBOOK §1 + §3)."""
        if current_vix is None:
            return ValidationCheck(
                name="vix",
                passed=False,
                decision=TradeDecision.WARNING,
                message="VIX nicht verfügbar",
            )

        regime = get_vix_regime(current_vix)
        regime_rules = get_regime_rules(current_vix)

        if not regime_rules.new_trades_allowed:
            return ValidationCheck(
                name="vix",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"VIX {current_vix:.1f} = {regime.value} — {regime_rules.notes}",
                details={"vix": current_vix, "regime": regime.value},
            )

        # Warning for Danger Zone / Elevated
        if regime in (VIXRegime.DANGER_ZONE, VIXRegime.ELEVATED):
            return ValidationCheck(
                name="vix",
                passed=True,
                decision=TradeDecision.WARNING,
                message=f"VIX {current_vix:.1f} = {regime.value} — {regime_rules.notes}",
                details={
                    "vix": current_vix,
                    "regime": regime.value,
                    "max_positions": regime_rules.max_positions,
                    "profit_exit": regime_rules.profit_exit_pct,
                },
            )

        return ValidationCheck(
            name="vix",
            passed=True,
            decision=TradeDecision.GO,
            message=f"VIX {current_vix:.1f} = {regime.value}",
            details={"vix": current_vix, "regime": regime.value},
        )

    def _check_price(self, symbol: str, fundamentals: Any) -> ValidationCheck:
        """Check 5: Price range (PLAYBOOK §1)."""
        if fundamentals is None or fundamentals.current_price is None:
            return ValidationCheck(
                name="price",
                passed=False,
                decision=TradeDecision.WARNING,
                message="Preis nicht verfügbar",
            )

        price = fundamentals.current_price

        if price < ENTRY_PRICE_MIN or price > ENTRY_PRICE_MAX:
            return ValidationCheck(
                name="price",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"Preis ${price:.2f} außerhalb ${ENTRY_PRICE_MIN}-${ENTRY_PRICE_MAX}",
                details={"price": price, "min": ENTRY_PRICE_MIN, "max": ENTRY_PRICE_MAX},
            )

        return ValidationCheck(
            name="price",
            passed=True,
            decision=TradeDecision.GO,
            message=f"Preis ${price:.2f}",
            details={"price": price},
        )

    async def _check_volume(self, symbol: str, fundamentals: Any) -> ValidationCheck:
        """Check 6: Volume (PLAYBOOK §1).

        Requires quote_provider for live volume data.
        Falls back to WARNING (not NO_GO) if provider unavailable.
        """
        if self._quote_provider is None:
            return ValidationCheck(
                name="volume",
                passed=True,
                decision=TradeDecision.GO,
                message="Volume-Check übersprungen (kein Quote-Provider)",
                details={"note": "Volume check requires quote provider"},
            )

        try:
            quote = await self._quote_provider.get_quote(symbol)
            if quote is None or quote.volume is None:
                return ValidationCheck(
                    name="volume",
                    passed=True,
                    decision=TradeDecision.WARNING,
                    message=f"Volume für {symbol} nicht verfügbar — manuell prüfen",
                    details={"volume": None},
                )

            volume = quote.volume
            min_volume = ENTRY_VOLUME_MIN  # 500_000 aus trading_rules.py

            if volume < min_volume:
                return ValidationCheck(
                    name="volume",
                    passed=False,
                    decision=TradeDecision.NO_GO,
                    message=f"Volume {volume:,} < {min_volume:,} Minimum",
                    details={"volume": volume, "min": min_volume},
                )

            return ValidationCheck(
                name="volume",
                passed=True,
                decision=TradeDecision.GO,
                message=f"Volume {volume:,}",
                details={"volume": volume, "min": min_volume},
            )

        except Exception as e:
            logger.warning(f"Volume-Check für {symbol} fehlgeschlagen: {e}")
            return ValidationCheck(
                name="volume",
                passed=True,
                decision=TradeDecision.WARNING,
                message=f"Volume nicht verfügbar — manuell prüfen",
                details={"error": str(e)},
            )

    def _check_iv_rank(self, symbol: str, fundamentals: Any) -> ValidationCheck:
        """Check 7: IV Rank (PLAYBOOK §1 — soft filter)."""
        if fundamentals is None or fundamentals.iv_rank_252d is None:
            return ValidationCheck(
                name="iv_rank",
                passed=True,
                decision=TradeDecision.GO,
                message="IV Rank nicht verfügbar",
                details={"iv_rank": None},
            )

        iv_rank = fundamentals.iv_rank_252d

        if iv_rank < ENTRY_IV_RANK_MIN:
            return ValidationCheck(
                name="iv_rank",
                passed=True,
                decision=TradeDecision.WARNING,
                message=f"IV Rank {iv_rank:.0f}% < {ENTRY_IV_RANK_MIN:.0f}% — niedrige Prämie",
                details={"iv_rank": iv_rank, "min": ENTRY_IV_RANK_MIN},
            )

        if iv_rank > ENTRY_IV_RANK_MAX:
            return ValidationCheck(
                name="iv_rank",
                passed=True,
                decision=TradeDecision.WARNING,
                message=f"IV Rank {iv_rank:.0f}% > {ENTRY_IV_RANK_MAX:.0f}% — hohes IV-Risiko",
                details={"iv_rank": iv_rank, "max": ENTRY_IV_RANK_MAX},
            )

        return ValidationCheck(
            name="iv_rank",
            passed=True,
            decision=TradeDecision.GO,
            message=f"IV Rank {iv_rank:.0f}%",
            details={"iv_rank": iv_rank},
        )

    def _check_dte(self, expiration: str) -> ValidationCheck:
        """Check DTE range (PLAYBOOK §2)."""
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            dte = (exp_date - date.today()).days
        except ValueError:
            return ValidationCheck(
                name="dte",
                passed=False,
                decision=TradeDecision.WARNING,
                message=f"Ungültiges Expiration-Format: {expiration}",
            )

        if dte < SPREAD_DTE_MIN:
            return ValidationCheck(
                name="dte",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"DTE {dte} < {SPREAD_DTE_MIN} (Minimum)",
                details={"dte": dte, "min": SPREAD_DTE_MIN, "max": SPREAD_DTE_MAX},
            )

        if dte > SPREAD_DTE_MAX:
            return ValidationCheck(
                name="dte",
                passed=False,
                decision=TradeDecision.WARNING,
                message=f"DTE {dte} > {SPREAD_DTE_MAX} — zu viel Zeitwert gebunden",
                details={"dte": dte, "min": SPREAD_DTE_MIN, "max": SPREAD_DTE_MAX},
            )

        return ValidationCheck(
            name="dte",
            passed=True,
            decision=TradeDecision.GO,
            message=f"DTE {dte} (Optimal: {SPREAD_DTE_MIN}-{SPREAD_DTE_MAX})",
            details={"dte": dte},
        )

    def _check_credit(self, credit: float, spread_width: float) -> ValidationCheck:
        """Check credit percentage and absolute minimum (PLAYBOOK §2)."""
        if spread_width <= 0:
            return ValidationCheck(
                name="credit",
                passed=False,
                decision=TradeDecision.NO_GO,
                message="Spread-Breite muss > 0 sein",
            )

        credit_pct = (credit / spread_width) * 100
        credit_per_contract = credit * 100  # Per-share to per-contract

        # Check 1: Absolute minimum ($20/contract)
        if credit_per_contract < SPREAD_MIN_CREDIT_ABSOLUTE:
            return ValidationCheck(
                name="credit",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=(
                    f"Credit ${credit_per_contract:.0f}/Contract < "
                    f"${SPREAD_MIN_CREDIT_ABSOLUTE:.0f} Minimum "
                    f"(${credit:.2f}/Aktie)"
                ),
                details={
                    "credit": credit,
                    "credit_per_contract": credit_per_contract,
                    "spread_width": spread_width,
                    "credit_pct": credit_pct,
                    "min_absolute": SPREAD_MIN_CREDIT_ABSOLUTE,
                },
            )

        # Check 2: Percentage minimum (20% of spread width)
        if credit_pct < SPREAD_MIN_CREDIT_PCT:
            return ValidationCheck(
                name="credit",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=(
                    f"Credit {credit_pct:.1f}% < {SPREAD_MIN_CREDIT_PCT:.0f}% "
                    f"(${credit:.2f} / ${spread_width:.2f})"
                ),
                details={
                    "credit": credit,
                    "spread_width": spread_width,
                    "credit_pct": credit_pct,
                    "min_pct": SPREAD_MIN_CREDIT_PCT,
                },
            )

        # Check 3: Fee warning (credit < $40 → IBKR fees > 6.5%)
        if credit_per_contract < SPREAD_FEE_WARNING_THRESHOLD:
            fee_pct = (SPREAD_IBKR_ROUND_TRIP_FEE / credit_per_contract) * 100
            return ValidationCheck(
                name="credit",
                passed=True,
                decision=TradeDecision.WARNING,
                message=(
                    f"Credit ${credit_per_contract:.0f}/Contract — "
                    f"IBKR-Gebühren ${SPREAD_IBKR_ROUND_TRIP_FEE:.2f} = "
                    f"{fee_pct:.1f}% des Ertrags"
                ),
                details={
                    "credit_pct": credit_pct,
                    "credit_per_contract": credit_per_contract,
                    "fee_pct": fee_pct,
                    "fee_warning": True,
                },
            )

        return ValidationCheck(
            name="credit",
            passed=True,
            decision=TradeDecision.GO,
            message=f"Credit {credit_pct:.1f}% (${credit:.2f} / ${spread_width:.2f})",
            details={"credit_pct": credit_pct, "credit_per_contract": credit_per_contract},
        )

    def _check_portfolio(
        self,
        symbol: str,
        fundamentals: Any,
        open_positions: List[Dict[str, Any]],
        current_vix: Optional[float],
    ) -> List[ValidationCheck]:
        """Portfolio constraint checks (PLAYBOOK §5)."""
        checks: List[ValidationCheck] = []
        num_positions = len(open_positions)

        # Max positions (VIX-adjusted)
        max_positions = SIZING_MAX_OPEN_POSITIONS
        if current_vix is not None:
            regime_rules = get_regime_rules(current_vix)
            max_positions = regime_rules.max_positions

        if num_positions >= max_positions:
            checks.append(ValidationCheck(
                name="max_positions",
                passed=False,
                decision=TradeDecision.NO_GO,
                message=f"Positions-Limit erreicht: {num_positions}/{max_positions}",
                details={"current": num_positions, "max": max_positions},
            ))
        else:
            checks.append(ValidationCheck(
                name="max_positions",
                passed=True,
                decision=TradeDecision.GO,
                message=f"Positionen: {num_positions}/{max_positions}",
                details={"current": num_positions, "max": max_positions},
            ))

        # Sector limit
        if fundamentals and fundamentals.sector:
            sector = fundamentals.sector
            max_sector = SIZING_MAX_PER_SECTOR
            if current_vix is not None:
                regime_rules = get_regime_rules(current_vix)
                max_sector = regime_rules.max_per_sector

            sector_count = sum(
                1 for p in open_positions
                if p.get('sector', '') == sector
            )

            if sector_count >= max_sector:
                checks.append(ValidationCheck(
                    name="sector_limit",
                    passed=False,
                    decision=TradeDecision.NO_GO,
                    message=f"Sektor-Limit {sector}: {sector_count}/{max_sector}",
                    details={"sector": sector, "count": sector_count, "max": max_sector},
                ))
            elif sector_count > 0:
                checks.append(ValidationCheck(
                    name="sector_limit",
                    passed=True,
                    decision=TradeDecision.WARNING,
                    message=f"Bereits {sector_count} Position(en) in {sector}",
                    details={"sector": sector, "count": sector_count, "max": max_sector},
                ))

        return checks

    def _calculate_sizing(
        self,
        request: TradeValidationRequest,
        fundamentals: Any,
        current_vix: Optional[float],
    ) -> Dict[str, Any]:
        """Calculate position sizing recommendation (PLAYBOOK §5)."""
        spread_width = abs(request.short_strike - request.long_strike)
        max_loss_per_contract = (spread_width - request.credit) * 100

        # VIX-adjusted risk percentage
        risk_pct = SIZING_MAX_RISK_PER_TRADE_PCT
        if current_vix is not None:
            regime_rules = get_regime_rules(current_vix)
            risk_pct = regime_rules.risk_per_trade_pct

        max_risk_usd = request.portfolio_value * (risk_pct / 100.0)
        recommended_contracts = int(max_risk_usd / max_loss_per_contract) if max_loss_per_contract > 0 else 0

        # Ensure at least 1 contract if valid
        if recommended_contracts == 0 and max_loss_per_contract > 0 and max_loss_per_contract <= max_risk_usd:
            recommended_contracts = 1

        return {
            "spread_width": spread_width,
            "credit_per_contract": request.credit,
            "max_loss_per_contract": max_loss_per_contract,
            "risk_pct": risk_pct,
            "max_risk_usd": max_risk_usd,
            "recommended_contracts": recommended_contracts,
            "total_credit": request.credit * recommended_contracts * 100,
            "total_risk": max_loss_per_contract * recommended_contracts,
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _read_vix_from_db() -> Optional[float]:
        """Sync DB read for VIX value. Runs in thread pool."""
        import sqlite3
        import os

        db_path = os.path.expanduser("~/.optionplay/trades.db")
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT value FROM vix_data ORDER BY date DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return float(row[0])
        return None

    async def _get_current_vix(self) -> Optional[float]:
        """Get current VIX from cache or DB."""
        try:
            from ..cache.vix_cache import get_latest_vix
            return await asyncio.to_thread(get_latest_vix)
        except ImportError:
            logger.debug("vix_cache module not available, trying DB fallback")

        try:
            return await asyncio.to_thread(self._read_vix_from_db)
        except Exception as e:
            logger.debug(f"VIX fallback read failed: {e}")

        return None


# =============================================================================
# FACTORY / SINGLETON
# =============================================================================

_validator: Optional[TradeValidator] = None


def get_trade_validator(quote_provider=None) -> TradeValidator:
    """Get singleton TradeValidator instance.

    Args:
        quote_provider: Optional quote provider for live volume checks.
                       Only used when creating a new instance.
    """
    global _validator
    if _validator is None:
        _validator = TradeValidator(quote_provider=quote_provider)
    return _validator


def reset_trade_validator():
    """Reset singleton (for tests)."""
    global _validator
    _validator = None
