"""
Validate Handler (Composition-Based)
======================================

Handles trade validation against PLAYBOOK rules.
Returns GO / NO_GO / WARNING for trade ideas.

This is the composition-based version of ValidateHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ValidateHandler(BaseHandler):
    """
    Handler for trade validation operations.

    Methods:
    - validate_trade(): Validate a trade idea against all PLAYBOOK rules
    """

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
        from ..services.trade_validator import (
            TradeValidationRequest,
            get_trade_validator,
        )
        from ..utils.validation import validate_symbol

        symbol = validate_symbol(symbol)

        current_vix = await self._get_vix()

        open_positions = await self._get_open_positions()

        request = TradeValidationRequest(
            symbol=symbol,
            short_strike=short_strike,
            long_strike=long_strike,
            expiration=expiration,
            credit=credit,
            contracts=contracts,
            portfolio_value=portfolio_value,
        )

        validator = get_trade_validator()
        result = await validator.validate(
            request=request,
            current_vix=current_vix,
            open_positions=open_positions,
        )

        return self._format_validation_result(result, request)

    def _format_validation_result(
        self,
        result: Any,
        request: Any,
    ) -> str:
        """Format validation result as Markdown."""
        from ..constants.trading_rules import TradeDecision
        from ..utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()

        decision_icon = {
            TradeDecision.GO: "[GO]",
            TradeDecision.NO_GO: "[NO-GO]",
            TradeDecision.WARNING: "[WARNING]",
        }
        icon = decision_icon.get(result.decision, "[?]")

        b.h1(f"Trade Validation: {result.symbol}")
        b.blank()

        b.h2(f"{icon} {result.decision.value}")
        b.text(result.summary)
        b.blank()

        if result.regime:
            b.kv_line("VIX-Regime", result.regime)
            if result.regime_notes:
                b.kv_line("Hinweis", result.regime_notes)
            b.blank()

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

        b.h2("Prüf-Ergebnisse")
        b.blank()

        if result.blockers:
            for check in result.blockers:
                b.text(f"**NO-GO** {check.name}: {check.message}")

        if result.warnings:
            for check in result.warnings:
                b.text(f"**WARNING** {check.name}: {check.message}")

        for check in result.passed:
            b.text(f"OK {check.name}: {check.message}")

        b.blank()

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
            # Try IBKR first
            if self._ctx.ibkr_bridge:
                try:
                    portfolio = self._ctx.ibkr_bridge.get_portfolio()
                    if portfolio:
                        return [
                            {
                                "symbol": p.get("symbol", ""),
                                "sector": p.get("sector", ""),
                            }
                            for p in portfolio
                        ]
                except Exception as e:
                    self._logger.debug(f"IBKR portfolio fetch failed: {e}")

            # Fallback: internal portfolio
            try:
                from ..portfolio import get_portfolio_manager

                portfolio = get_portfolio_manager()
                positions = portfolio.get_open_positions()
                return [
                    {
                        "symbol": p.symbol,
                        "sector": "",
                    }
                    for p in positions
                ]
            except Exception as e:
                self._logger.debug(f"Internal portfolio fetch failed: {e}")

        except Exception as e:
            self._logger.debug(f"Error getting open positions: {e}")

        return []

    # _get_vix() inherited from BaseHandler
