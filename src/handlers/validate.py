"""
Validate Handler Module
=======================

Handles trade validation against PLAYBOOK rules.
Returns GO / NO_GO / WARNING for trade ideas.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..constants.trading_rules import TradeDecision, get_vix_regime
from ..services.trade_validator import (
    TradeValidationRequest,
    TradeValidationResult,
    TradeValidator,
    get_trade_validator,
)
from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..utils.validation import validate_symbol
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)


class ValidateHandlerMixin(BaseHandlerMixin):
    """
    Mixin for trade validation handler methods.
    """

    @mcp_endpoint(operation="trade validation", symbol_param="symbol")
    async def validate_trade(
        self,
        symbol: str,
        short_strike: Optional[float] = None,
        expiration: Optional[str] = None,
        long_strike: Optional[float] = None,
        credit: Optional[float] = None,
        contracts: Optional[int] = None,
        portfolio_value: Optional[float] = None,
    ) -> str:
        """
        Validate a trade idea against all PLAYBOOK rules.

        Returns GO / NO_GO / WARNING with detailed explanation.

        Args:
            symbol: Ticker symbol to validate
            short_strike: Planned short put strike (optional)
            expiration: Planned expiration date YYYY-MM-DD (optional)
            long_strike: Planned long put strike (optional)
            credit: Expected net credit per share (optional)
            contracts: Number of contracts (optional)
            portfolio_value: Total portfolio value in USD (optional)

        Returns:
            Formatted Markdown with validation results
        """
        symbol = validate_symbol(symbol)

        # Get current VIX
        current_vix = await self.get_vix()

        # Get open positions for portfolio checks
        open_positions = await self._get_open_positions()

        # Build request
        request = TradeValidationRequest(
            symbol=symbol,
            short_strike=short_strike,
            long_strike=long_strike,
            expiration=expiration,
            credit=credit,
            contracts=contracts,
            portfolio_value=portfolio_value,
        )

        # Run validation
        validator = get_trade_validator()
        result = await validator.validate(
            request=request,
            current_vix=current_vix,
            open_positions=open_positions,
        )

        # Format output
        return self._format_validation_result(result, request)

    def _format_validation_result(
        self,
        result: TradeValidationResult,
        request: TradeValidationRequest,
    ) -> str:
        """Format validation result as Markdown."""
        b = MarkdownBuilder()

        # Header with decision
        decision_icon = {
            TradeDecision.GO: "[GO]",
            TradeDecision.NO_GO: "[NO-GO]",
            TradeDecision.WARNING: "[WARNING]",
        }
        icon = decision_icon.get(result.decision, "[?]")

        b.h1(f"Trade Validation: {result.symbol}")
        b.blank()

        # Decision banner
        b.h2(f"{icon} {result.decision.value}")
        b.text(result.summary)
        b.blank()

        # Regime info
        if result.regime:
            b.kv_line("VIX-Regime", result.regime)
            if result.regime_notes:
                b.kv_line("Hinweis", result.regime_notes)
            b.blank()

        # Trade details (if provided)
        if request.short_strike or request.expiration:
            b.h2("Trade-Details")
            if request.short_strike:
                b.kv_line("Short Strike", f"${request.short_strike:.2f}")
            if request.long_strike:
                b.kv_line("Long Strike", f"${request.long_strike:.2f}")
                if request.short_strike:
                    width = abs(request.short_strike - request.long_strike)
                    b.kv_line("Spread-Breite", f"${width:.2f}")
            if request.expiration:
                b.kv_line("Expiration", request.expiration)
            if request.credit:
                b.kv_line("Credit", f"${request.credit:.2f}")
            b.blank()

        # Check results
        b.h2("Prüf-Ergebnisse")
        b.blank()

        # Blockers first
        if result.blockers:
            for check in result.blockers:
                b.text(f"**NO-GO** {check.name}: {check.message}")

        # Warnings
        if result.warnings:
            for check in result.warnings:
                b.text(f"**WARNING** {check.name}: {check.message}")

        # Passed checks
        for check in result.passed:
            b.text(f"OK {check.name}: {check.message}")

        b.blank()

        # Position sizing recommendation
        if result.sizing_recommendation:
            sizing = result.sizing_recommendation
            b.h2("Position Sizing")
            b.kv_line("Spread-Breite", f"${sizing['spread_width']:.2f}")
            b.kv_line("Max Verlust/Kontrakt", f"${sizing['max_loss_per_contract']:.0f}")
            b.kv_line("Max Risiko", f"{sizing['risk_pct']:.1f}% = ${sizing['max_risk_usd']:.0f}")
            b.kv_line("Empfohlene Kontrakte", sizing["recommended_contracts"])
            b.kv_line("Gesamt-Credit", f"${sizing['total_credit']:.0f}")
            b.kv_line("Gesamt-Risiko", f"${sizing['total_risk']:.0f}")
            b.blank()

        return b.build()

    async def _get_open_positions(self) -> List[Dict[str, Any]]:
        """Get currently open positions from portfolio tracking."""
        try:
            from ..services.portfolio_constraints import get_constraint_checker

            # Try IBKR first, then internal tracking
            try:
                if hasattr(self, "_ibkr_bridge") and self._ibkr_bridge:
                    portfolio = self._ibkr_bridge.get_portfolio()
                    if portfolio:
                        return [
                            {
                                "symbol": p.get("symbol", ""),
                                "sector": p.get("sector", ""),
                            }
                            for p in portfolio
                        ]
            except Exception as e:
                logger.debug(f"IBKR portfolio fetch failed: {e}")

            # Fallback: internal portfolio
            try:
                from ..handlers.portfolio import _get_portfolio_db

                db = _get_portfolio_db()
                if db:
                    positions = db.get_open_positions()
                    return [
                        {
                            "symbol": p.get("symbol", ""),
                            "sector": "",
                        }
                        for p in positions
                    ]
            except Exception as e:
                logger.debug(f"Internal portfolio fetch failed: {e}")

        except Exception as e:
            logger.debug(f"Error getting open positions: {e}")

        return []
