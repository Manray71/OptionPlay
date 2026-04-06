"""
Risk Handler (Composition-Based)
==================================

Handles position sizing, stop loss recommendations, spread analysis,
and Monte Carlo simulations.

This is the composition-based version of RiskHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from ..constants.trading_rules import VIX_NORMAL_MAX
from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RiskHandler(BaseHandler):
    """
    Handler for risk management operations.

    Methods:
    - calculate_position_size(): Kelly Criterion position sizing
    - recommend_stop_loss(): VIX-adjusted stop loss recommendation
    - analyze_spread(): Comprehensive spread risk/reward analysis
    - run_monte_carlo(): Monte Carlo simulation for spreads
    """

    async def calculate_position_size(
        self,
        account_size: float,
        max_loss_per_contract: float,
        win_rate: float = 0.65,
        avg_win: float = 100,
        avg_loss: float = 350,
        signal_score: float = 7.0,
        reliability_grade: Optional[str] = None,
        current_exposure: float = 0,
    ) -> str:
        """
        Calculate optimal position size using Kelly Criterion.

        Args:
            account_size: Total account value in USD
            max_loss_per_contract: Maximum loss per contract in USD
            win_rate: Historical win rate (0.0 - 1.0)
            avg_win: Average winning trade in USD
            avg_loss: Average losing trade in USD
            signal_score: Signal quality score (0-10)
            reliability_grade: Optional reliability grade (A-F)
            current_exposure: Current portfolio exposure in USD

        Returns:
            Formatted Markdown with position sizing recommendation
        """
        from ..risk.position_sizing import KellyMode, PositionSizer, PositionSizerConfig, VIXRegime
        from ..utils.markdown_builder import MarkdownBuilder

        vix = await self._get_vix() or VIX_NORMAL_MAX

        config = PositionSizerConfig(kelly_mode=KellyMode.HALF)
        sizer = PositionSizer(
            account_size=account_size,
            current_exposure=current_exposure,
            config=config,
        )

        result = sizer.calculate_position_size(
            max_loss_per_contract=max_loss_per_contract,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            signal_score=signal_score,
            vix_level=vix,
            reliability_grade=reliability_grade,
        )

        vix_regime = sizer.get_vix_regime(vix)

        b = MarkdownBuilder()
        b.h1("Position Sizing Recommendation").blank()

        b.h2("Account Context")
        b.kv_line("Account Size", f"${account_size:,.0f}")
        b.kv_line("Current Exposure", f"${current_exposure:,.0f}")
        b.kv_line("Max Loss/Contract", f"${max_loss_per_contract:,.0f}")
        b.blank()

        b.h2("Market Conditions")
        b.kv_line("VIX", f"{vix:.1f}")
        b.kv_line("VIX Regime", vix_regime.value)
        b.kv_line("VIX Adjustment", f"{result.vix_adjustment:.0%}")
        b.blank()

        b.h2("Signal Quality")
        b.kv_line("Signal Score", f"{signal_score:.1f}/10")
        if reliability_grade:
            b.kv_line("Reliability Grade", reliability_grade)
        b.kv_line("Kelly Fraction", f"{result.kelly_fraction:.1%}")
        b.blank()

        b.h2("Recommendation")
        b.kv_line("Contracts", str(result.contracts))
        b.kv_line("Capital at Risk", f"${result.capital_at_risk:,.0f}")
        b.kv_line("Risk % of Account", f"{result.capital_at_risk / account_size * 100:.1f}%")
        b.blank()

        limit_icons = {
            "kelly": "[KELLY] Kelly Criterion",
            "max_risk_per_trade": "[RISK] Max Risk Per Trade",
            "portfolio_limit": "[PORT] Portfolio Limit",
            "vix_adjustment": "[VIX] VIX Adjustment",
            "reliability": "[REL] Reliability Grade",
            "score": "[SCORE] Signal Score",
        }
        b.kv_line("Limited By", limit_icons.get(result.limiting_factor, result.limiting_factor))

        if result.contracts == 0:
            b.blank()
            b.h3("No Trade Recommended")
            if result.limiting_factor == "insufficient_edge":
                b.text("The win rate and payoff ratio don't provide sufficient edge.")
            elif result.limiting_factor == "portfolio_risk_full":
                b.text("Portfolio exposure limit reached.")
            elif result.limiting_factor == "reliability":
                b.text("Signal reliability too low (Grade D or F).")
            elif result.limiting_factor == "score":
                b.text("Signal score below minimum threshold.")

        return b.build()

    async def recommend_stop_loss(
        self,
        net_credit: float,
        spread_width: float,
    ) -> str:
        """
        Get recommended stop loss level for a credit spread.

        Args:
            net_credit: Net credit received per share
            spread_width: Width of the spread in dollars

        Returns:
            Formatted Markdown with stop loss recommendations
        """
        from ..risk.position_sizing import PositionSizer
        from ..utils.markdown_builder import MarkdownBuilder

        vix = await self._get_vix() or VIX_NORMAL_MAX
        sizer = PositionSizer(account_size=100000)

        result = sizer.calculate_stop_loss(
            net_credit=net_credit,
            spread_width=spread_width,
            vix_level=vix,
        )

        max_possible_loss = spread_width - net_credit

        b = MarkdownBuilder()
        b.h1("Stop Loss Recommendation").blank()

        b.h2("Trade Details")
        b.kv_line("Net Credit", f"${net_credit:.2f}")
        b.kv_line("Spread Width", f"${spread_width:.2f}")
        b.kv_line("Max Loss", f"${max_possible_loss:.2f}")
        b.blank()

        b.h2("Market Context")
        b.kv_line("VIX", f"{vix:.1f}")
        b.kv_line("Regime", result["vix_regime"].upper())
        b.blank()

        b.h2("Stop Loss Settings")
        b.kv_line("Stop Loss %", f"{result['stop_loss_pct']:.0f}%")
        b.kv_line("Exit When Spread =", f"${result['stop_loss_price']:.2f}")
        b.kv_line("Max Loss at Stop", f"${result['max_loss']:.2f}")
        b.blank()

        b.h3("How to Use")
        b.text(f"Close the position if the spread price rises to ${result['stop_loss_price']:.2f}")
        b.text(f"This limits your loss to ${result['max_loss']:.2f} per spread.")

        return b.build()

    async def analyze_spread(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        net_credit: float,
        dte: int,
        contracts: int = 1,
    ) -> str:
        """
        Analyze a Bull-Put-Spread with comprehensive risk/reward metrics.

        Args:
            symbol: Ticker symbol
            short_strike: Short put strike price
            long_strike: Long put strike price
            net_credit: Net credit received per share
            dte: Days to expiration
            contracts: Number of contracts

        Returns:
            Formatted spread analysis
        """
        from ..options.spread_analyzer import BullPutSpreadParams, SpreadAnalyzer
        from ..utils.markdown_builder import MarkdownBuilder
        from ..utils.validation import validate_symbol

        symbol = validate_symbol(symbol)

        quote = await self._get_quote_cached(symbol)
        current_price = quote.last if quote else short_strike * 1.05

        params = BullPutSpreadParams(
            symbol=symbol,
            short_strike=short_strike,
            long_strike=long_strike,
            net_credit=net_credit,
            dte=dte,
            contracts=contracts,
            current_price=current_price,
        )

        analyzer = SpreadAnalyzer()
        analysis = analyzer.analyze(params)

        b = MarkdownBuilder()
        b.h1(f"Spread Analysis: {symbol}").blank()

        b.h2("Position Details")
        b.kv_line("Short Strike", f"${short_strike:.2f}")
        b.kv_line("Long Strike", f"${long_strike:.2f}")
        b.kv_line("Spread Width", f"${analysis.spread_width:.2f}")
        b.kv_line("Net Credit", f"${net_credit:.2f}")
        b.kv_line("Contracts", str(contracts))
        b.kv_line("DTE", str(dte))
        b.blank()

        b.h2("Risk/Reward")
        b.kv_line("Max Profit", f"${analysis.max_profit:.2f}")
        b.kv_line("Max Loss", f"${analysis.max_loss:.2f}")
        b.kv_line("Breakeven", f"${analysis.break_even:.2f}")
        b.kv_line("Risk/Reward", f"{analysis.risk_reward_ratio:.2f}:1")
        b.blank()

        roi_percent = (
            (analysis.max_profit / analysis.max_loss * 100) if analysis.max_loss > 0 else 0
        )
        annualized_roi = ((1 + roi_percent / 100) ** (365 / dte) - 1) * 100 if dte > 0 else 0

        b.h2("Profitability")
        b.kv_line("ROI", f"{roi_percent:.1f}%")
        b.kv_line("Annualized ROI", f"{annualized_roi:.1f}%")
        b.blank()

        b.h2("P&L at Expiration")
        scenarios = [
            ("At Current", current_price),
            ("At Short Strike", short_strike),
            ("At Breakeven", analysis.break_even),
            ("At Long Strike", long_strike),
        ]

        rows = []
        for label, price in scenarios:
            pnl = analyzer.calculate_pnl_at_price(params, price)
            pnl_total = pnl * contracts * 100
            sign = "+" if pnl_total >= 0 else ""
            rows.append([label, f"${price:.2f}", f"{sign}${pnl_total:.2f}"])

        b.table(["Scenario", "Price", "P&L"], rows)

        return b.build()

    async def run_monte_carlo(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        net_credit: float,
        dte: int,
        volatility: Optional[float] = None,
        num_simulations: int = 10000,
    ) -> str:
        """
        Run Monte Carlo simulation for a Bull-Put-Spread.

        Args:
            symbol: Ticker symbol
            short_strike: Short put strike price
            long_strike: Long put strike price
            net_credit: Net credit received per share
            dte: Days to expiration
            volatility: Annualized volatility (optional)
            num_simulations: Number of simulation paths

        Returns:
            Formatted simulation results
        """
        import math

        from ..backtesting import PriceSimulator
        from ..utils.markdown_builder import MarkdownBuilder
        from ..utils.validation import validate_symbol

        symbol = validate_symbol(symbol)

        quote = await self._get_quote_cached(symbol)
        if not quote or not quote.last:
            return f"Cannot get quote for {symbol}"

        current_price = quote.last

        if volatility is None:
            data = await self._fetch_historical_cached(symbol, days=30)
            if data:
                prices = data[0]
                returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
                daily_vol = (
                    sum((r - sum(returns) / len(returns)) ** 2 for r in returns) / len(returns)
                ) ** 0.5
                volatility = daily_vol * math.sqrt(252)
            else:
                volatility = 0.25

        final_prices = []
        for i in range(num_simulations):
            price_path = PriceSimulator.generate_price_path(
                start_price=current_price,
                days=dte,
                volatility=volatility,
                drift=0.0,
                seed=i,
            )
            final_prices.append(price_path[-1])

        max_profit = 0
        max_loss = 0
        partial_profit = 0
        partial_loss = 0
        breakeven = short_strike - net_credit

        for price in final_prices:
            if price >= short_strike:
                max_profit += 1
            elif price >= breakeven:
                partial_profit += 1
            elif price >= long_strike:
                partial_loss += 1
            else:
                max_loss += 1

        total = len(final_prices)
        prob_profit = (max_profit + partial_profit) / total
        prob_max_profit = max_profit / total
        prob_max_loss = max_loss / total

        b = MarkdownBuilder()
        b.h1(f"Monte Carlo Simulation: {symbol}").blank()

        b.h2("Simulation Parameters")
        b.kv_line("Current Price", f"${current_price:.2f}")
        b.kv_line("Volatility", f"{volatility:.1%}")
        b.kv_line("DTE", str(dte))
        b.kv_line("Simulations", f"{num_simulations:,}")
        b.blank()

        b.h2("Spread Details")
        b.kv_line("Short Strike", f"${short_strike:.2f}")
        b.kv_line("Long Strike", f"${long_strike:.2f}")
        b.kv_line("Net Credit", f"${net_credit:.2f}")
        b.kv_line("Breakeven", f"${breakeven:.2f}")
        b.blank()

        b.h2("Outcome Probabilities")
        b.kv_line("Prob. of Profit", f"{prob_profit:.1%}")
        b.kv_line("Prob. Max Profit", f"{prob_max_profit:.1%}")
        b.kv_line("Prob. Max Loss", f"{prob_max_loss:.1%}")
        b.blank()

        b.h2("Outcome Distribution")
        rows = [
            ["Max Profit (>= short)", f"{max_profit:,}", f"{prob_max_profit:.1%}"],
            ["Partial Profit", f"{partial_profit:,}", f"{partial_profit/total:.1%}"],
            ["Partial Loss", f"{partial_loss:,}", f"{partial_loss/total:.1%}"],
            ["Max Loss (<= long)", f"{max_loss:,}", f"{prob_max_loss:.1%}"],
        ]
        b.table(["Outcome", "Count", "Probability"], rows)

        return b.build()

    # --- Shared helper methods ---

    # _get_vix() inherited from BaseHandler
    # _get_quote_cached inherited from BaseHandler

    async def _fetch_historical_cached(self, symbol: str, days: Optional[int] = None):
        """Fetch historical data with caching.

        Priority: in-memory cache → IBKR.
        """
        from ..cache.historical_cache import CacheStatus

        if days is None:
            days = self._ctx.config.settings.performance.historical_days

        if self._ctx.historical_cache:
            cache_result = self._ctx.historical_cache.get(symbol, days)
            if cache_result.status == CacheStatus.HIT:
                return cache_result.data

        await self._ensure_connected()
        if self._ctx.ibkr_connected and self._ctx.ibkr_provider:
            try:
                data = await self._ctx.ibkr_provider.get_historical_for_scanner(
                    symbol, days=days
                )
                if data:
                    if self._ctx.historical_cache:
                        self._ctx.historical_cache.set(symbol, data, days=days)
                    return data
            except (ConnectionError, TimeoutError, ValueError) as e:
                self._logger.debug(f"IBKR historical failed for {symbol}: {e}")

        return None
