"""
VIX Handler (Composition-Based)
================================

Handles VIX, strategy, and regime operations.

This is the composition-based version of VixHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class VixHandler(BaseHandler):
    """
    Handler for VIX-related operations.

    Methods:
    - get_vix(): Get current VIX value
    - get_strategy_recommendation(): Get VIX-based strategy recommendation
    - get_regime_status(): Get current VIX regime and parameters
    """

    VIX_CACHE_SECONDS = 300  # 5 minutes

    async def get_vix(self, force_refresh: bool = False) -> Optional[float]:
        """
        Get current VIX value.

        Uses cached value if available and not expired (5 min TTL).

        Args:
            force_refresh: Force API call even if cached

        Returns:
            VIX value or None if unavailable
        """
        # Check cache
        if not force_refresh and self._ctx.current_vix is not None:
            if self._ctx.vix_updated:
                age = (datetime.now() - self._ctx.vix_updated).total_seconds()
                if age < self.VIX_CACHE_SECONDS:
                    return self._ctx.current_vix

        # Try IBKR first
        if self._ctx.ibkr_bridge:
            try:
                vix = await self._ctx.ibkr_bridge.get_vix()
                if vix is not None:
                    self._ctx.current_vix = vix
                    self._ctx.vix_updated = datetime.now()
                    return vix
            except Exception as e:
                self._logger.debug(f"IBKR VIX failed: {e}")

        # Fallback to MarketData provider
        if self._ctx.provider:
            try:
                quote = await self._ctx.provider.get_quote("VIX")
                if quote and hasattr(quote, 'last') and quote.last:
                    self._ctx.current_vix = quote.last
                    self._ctx.vix_updated = datetime.now()
                    return quote.last
            except Exception as e:
                self._logger.warning(f"VIX fetch failed: {e}")

        return self._ctx.current_vix

    async def get_strategy_recommendation(self) -> str:
        """
        Get VIX-based strategy recommendation.

        Returns formatted Markdown with:
        - Current VIX level
        - Regime classification
        - Recommended strategies
        - Position sizing guidance
        """
        vix = await self.get_vix()

        if vix is None:
            return "❌ Unable to fetch VIX data"

        selector = self._ctx.vix_selector
        strategy = selector.get_strategy(vix)
        regime = selector.get_regime(vix)

        lines = [
            f"# 📊 VIX Strategy Recommendation",
            "",
            f"**Current VIX:** {vix:.2f}",
            f"**Regime:** {regime.name}",
            f"**Strategy:** {strategy.name}",
            "",
            "## Parameters",
            f"- Min Score: {strategy.min_score}",
            f"- Max DTE: {strategy.max_dte}",
            f"- Position Size: {strategy.position_size_pct * 100:.0f}%",
            "",
        ]

        # Regime-specific advice
        if regime.name == "LOW":
            lines.extend([
                "## 💡 Low Volatility Environment",
                "- Premium is reduced - consider wider spreads",
                "- Good for selling premium on quality stocks",
                "- Lower probability plays may be worthwhile",
            ])
        elif regime.name == "NORMAL":
            lines.extend([
                "## 💡 Normal Volatility Environment",
                "- Balanced premium vs risk",
                "- Standard position sizing appropriate",
                "- Focus on high-probability setups",
            ])
        elif regime.name == "ELEVATED":
            lines.extend([
                "## ⚠️ Elevated Volatility",
                "- Enhanced premium available",
                "- Reduce position sizes",
                "- Focus on quality stocks only",
            ])
        elif regime.name == "HIGH":
            lines.extend([
                "## 🔴 High Volatility - Caution",
                "- Extreme premium but high risk",
                "- Minimal new positions recommended",
                "- Consider closing existing trades",
            ])

        return "\n".join(lines)

    async def get_regime_status(self) -> str:
        """
        Get current VIX regime status with trading parameters.

        Returns formatted status including:
        - Current VIX and regime
        - Enabled strategies
        - Trained model recommendations
        """
        vix = await self.get_vix()

        if vix is None:
            return "❌ Unable to fetch VIX data"

        selector = self._ctx.vix_selector
        regime = selector.get_regime(vix)
        strategy = selector.get_strategy(vix)

        lines = [
            f"# 🎯 VIX Regime Status",
            "",
            f"**VIX:** {vix:.2f}",
            f"**Regime:** {regime.name} ({regime.description})",
            "",
            "## Current Parameters",
            f"- Strategy: {strategy.name}",
            f"- Min Score Threshold: {strategy.min_score}",
            f"- Position Size: {strategy.position_size_pct * 100:.0f}%",
            f"- Max DTE: {strategy.max_dte}",
            "",
            "## Enabled Strategies",
        ]

        # Add enabled strategies based on regime
        strategies = ["Pullback", "Bounce"]
        if regime.name in ("LOW", "NORMAL"):
            strategies.append("ATH Breakout")
        if regime.name in ("NORMAL", "ELEVATED"):
            strategies.append("Earnings Dip")

        for s in strategies:
            lines.append(f"- ✅ {s}")

        return "\n".join(lines)
