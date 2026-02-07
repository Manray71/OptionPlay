#!/usr/bin/env python3
"""
Entry/Exit Signal Logic for BacktestEngine

Extracted from engine.py for modularity.
Contains: _check_entry_signal, _open_position, _check_exit_signal,
          _close_position, _calculate_simple_pullback_score
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Callable

logger = logging.getLogger(__name__)


class EntryExitMixin:
    """
    Mixin providing entry/exit signal logic for BacktestEngine.

    Requires the host class to have:
    - self.config (BacktestConfig)
    - self._historical_data
    - self._simulator
    - self._get_price_on_date(symbol, date)
    - self._get_vix_on_date(date)
    - self._get_iv_on_date(symbol, date)
    - self._estimate_iv_from_hv(symbol, date)
    """

    def _check_entry_signal(
        self,
        symbol: str,
        current_date: date,
        entry_filter: Optional[Callable] = None
    ) -> Optional[Dict]:
        """
        Prüft ob Entry-Signal vorhanden.

        Returns:
            Entry-Signal Dict oder None
        """
        price_data = self._get_price_on_date(symbol, current_date)
        if not price_data:
            return None

        current_price = price_data.get("close", 0)
        if current_price <= 0:
            return None

        # Berechne einfachen Pullback-Score basierend auf Preis-Action
        # (In Produktion würde hier der echte Analyzer verwendet)
        result = self._calculate_simple_pullback_score(
            symbol, current_date, price_data, return_breakdown=True
        )

        if isinstance(result, tuple):
            score, score_breakdown = result
        else:
            score = result
            score_breakdown = None

        if score < self.config.min_pullback_score:
            return None

        # Custom Filter
        if entry_filter:
            if not entry_filter(symbol, current_date, price_data, score):
                return None

        vix = self._get_vix_on_date(current_date)

        return {
            "price": current_price,
            "score": score,
            "score_breakdown": score_breakdown,
            "vix": vix,
            "date": current_date,
        }

    def _calculate_simple_pullback_score(
        self,
        symbol: str,
        current_date: date,
        price_data: Dict,
        use_previous_day: bool = True,
        return_breakdown: bool = False,
    ) -> float:
        """
        Berechnet vereinfachten Pullback-Score.

        WICHTIG: Um Look-Ahead Bias zu vermeiden, wird der Score basierend auf
        VORHERIGEN Tages-Daten berechnet. Das Entry-Signal entsteht am Ende des
        vorherigen Tages, der Trade wird am nächsten Tag (current_date) ausgeführt.

        Args:
            symbol: Ticker-Symbol
            current_date: Datum für Trade-Entry (nicht für Signal-Berechnung)
            price_data: Preis-Daten vom current_date (nur für Entry-Preis)
            use_previous_day: True = Score basiert auf T-1 Daten (verhindert Look-Ahead)

        Returns:
            Pullback-Score (0-10)
        """
        if symbol not in self._historical_data:
            return 0.0

        # Hole historische Daten VOR dem Signal-Tag
        # Signal wird am Ende von T-1 generiert, Trade am T ausgeführt
        history = []
        signal_date = current_date - timedelta(days=1) if use_previous_day else current_date

        for bar in self._historical_data[symbol]:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            # KORREKTUR: Verwende Daten VOR dem Signal-Tag (strikt kleiner)
            if bar_date < signal_date:
                history.append(bar)

        if len(history) < 20:
            return 0.0

        # Sortiere und nimm die letzten 20 Tage VOR dem Signal-Tag
        history = sorted(history, key=lambda x: x.get("date", ""), reverse=True)[:20]
        closes = [bar.get("close", 0) for bar in history]

        if not closes or closes[0] <= 0:
            return 0.0

        # KORREKTUR: Verwende den VORHERIGEN Schlusskurs für Score-Berechnung
        # (nicht den aktuellen Tag, der noch nicht "bekannt" ist)
        prev_day_data = None
        if use_previous_day:
            # Signal-Tag Close = letzter verfügbarer Close vor current_date
            for bar in self._historical_data[symbol]:
                bar_date = bar.get("date")
                if isinstance(bar_date, str):
                    bar_date = date.fromisoformat(bar_date)
                if bar_date == signal_date:
                    prev_day_data = bar
                    break

            if prev_day_data:
                signal_close = prev_day_data.get("close", 0)
            else:
                # Fallback: letzter Close in history
                signal_close = closes[0]
        else:
            signal_close = price_data.get("close", 0)

        sma_20 = sum(closes) / len(closes)
        high_20 = max(bar.get("high", 0) for bar in history)

        # Score-Breakdown für Komponenten-Analyse
        score_breakdown = {
            "rsi_score": 0.0,
            "support_score": 0.0,
            "fibonacci_score": 0.0,
            "ma_score": 0.0,
            "trend_strength_score": 0.0,
            "volume_score": 0.0,
            "macd_score": 0.0,
            "stoch_score": 0.0,
            "keltner_score": 0.0,
        }

        score = 0.0

        # RSI-Score (simuliert, basierend auf Pullback) - max 2 Punkte
        pullback_pct = ((high_20 - signal_close) / high_20) * 100 if high_20 > 0 else 0
        if 3 <= pullback_pct <= 8:
            score_breakdown["rsi_score"] = 2.0
        elif 8 < pullback_pct <= 15:
            score_breakdown["rsi_score"] = 1.5
        elif pullback_pct > 15:
            score_breakdown["rsi_score"] = 0.5

        # Support-Score - max 2 Punkte
        lows = [bar.get("low", 0) for bar in history]
        support = min(lows) if lows else 0
        if support > 0:
            dist_to_support = ((signal_close - support) / signal_close) * 100
            if dist_to_support < 5:
                score_breakdown["support_score"] = 2.0
            elif dist_to_support < 10:
                score_breakdown["support_score"] = 1.0

        # Fibonacci-Score (basierend auf Retracement vom High) - max 1.5 Punkte
        if 3 <= pullback_pct <= 8:
            score_breakdown["fibonacci_score"] = 1.5  # ~38.2% Retracement
        elif 8 < pullback_pct <= 12:
            score_breakdown["fibonacci_score"] = 1.0  # ~50% Retracement
        elif 12 < pullback_pct <= 18:
            score_breakdown["fibonacci_score"] = 0.5  # ~61.8% Retracement

        # MA-Score (Preis relativ zu SMA20) - max 1.5 Punkte
        if signal_close > sma_20 * 1.02:
            score_breakdown["ma_score"] = 1.5
        elif signal_close > sma_20:
            score_breakdown["ma_score"] = 1.0
        elif signal_close > sma_20 * 0.98:
            score_breakdown["ma_score"] = 0.5

        # Trend-Strength-Score (SMA10 vs SMA20) - max 1.5 Punkte
        if len(closes) >= 10:
            sma_10 = sum(closes[:10]) / 10
            if sma_10 > sma_20 * 1.02:
                score_breakdown["trend_strength_score"] = 1.5
            elif sma_10 > sma_20:
                score_breakdown["trend_strength_score"] = 1.0
            elif sma_10 > sma_20 * 0.98:
                score_breakdown["trend_strength_score"] = 0.5

        # Volume-Score - max 1 Punkt
        if use_previous_day and prev_day_data:
            signal_vol = prev_day_data.get("volume", 0)
        else:
            signal_vol = price_data.get("volume", 0)

        avg_vol = sum(bar.get("volume", 0) for bar in history) / len(history)
        if avg_vol > 0:
            if signal_vol > avg_vol * 1.5:
                score_breakdown["volume_score"] = 1.0
            elif signal_vol > avg_vol * 1.2:
                score_breakdown["volume_score"] = 0.5

        # MACD-Score (simuliert basierend auf Momentum) - max 1 Punkt
        if len(closes) >= 5:
            recent_change = (closes[0] - closes[4]) / closes[4] * 100 if closes[4] > 0 else 0
            if recent_change > 2:
                score_breakdown["macd_score"] = 1.0
            elif recent_change > 0:
                score_breakdown["macd_score"] = 0.5

        # Stochastic-Score (simuliert) - max 1 Punkt
        if len(history) >= 14:
            highs_14 = [bar.get("high", 0) for bar in history[:14]]
            lows_14 = [bar.get("low", 0) for bar in history[:14]]
            high_14 = max(highs_14)
            low_14 = min(lows_14)
            if high_14 > low_14:
                stoch_k = ((signal_close - low_14) / (high_14 - low_14)) * 100
                if 20 <= stoch_k <= 40:  # Oversold recovery
                    score_breakdown["stoch_score"] = 1.0
                elif 40 < stoch_k <= 60:
                    score_breakdown["stoch_score"] = 0.5

        # Keltner-Score (simuliert basierend auf Volatilität) - max 0.5 Punkte
        if len(history) >= 10:
            atr_approx = sum(
                bar.get("high", 0) - bar.get("low", 0) for bar in history[:10]
            ) / 10
            if atr_approx > 0:
                keltner_upper = sma_20 + 2 * atr_approx
                keltner_lower = sma_20 - 2 * atr_approx
                if keltner_lower < signal_close < sma_20:
                    score_breakdown["keltner_score"] = 0.5

        # Gesamtscore berechnen
        score = sum(score_breakdown.values())

        if return_breakdown:
            return min(score, 12.0), score_breakdown

        return min(score, 12.0)

    def _open_position(
        self,
        symbol: str,
        entry_date: date,
        entry_signal: Dict,
        max_risk: float
    ) -> Optional[Dict]:
        """Öffnet eine neue Position"""
        current_price = entry_signal["price"]

        # =================================================================
        # STRIKE-AUSWAHL: Delta-basiert oder OTM%-basiert
        # =================================================================
        # IV holen oder schätzen (wird für beide Methoden benötigt)
        iv = None
        if self._simulator:
            iv = self._get_iv_on_date(symbol, entry_date)
            if iv is None:
                iv = self._estimate_iv_from_hv(symbol, entry_date)
        if iv is None:
            iv = self.config.default_iv

        short_strike = None
        long_strike = None
        entry_delta = None

        if self.config.use_delta_based_strikes:
            # Delta-basierte Strike-Auswahl (Basisstrategie gemäß strategies.yaml)
            from ...pricing import find_strike_for_delta

            T = self.config.dte_max / 365.0  # Zeit bis Verfall in Jahren

            # Short Put Strike (Delta ~ -0.20)
            short_strike = find_strike_for_delta(
                target_delta=self.config.short_delta_target,
                S=current_price,
                T=T,
                sigma=iv,
                option_type="P"
            )

            # Long Put Strike (Delta ~ -0.05)
            long_strike = find_strike_for_delta(
                target_delta=self.config.long_delta_target,
                S=current_price,
                T=T,
                sigma=iv,
                option_type="P"
            )

            entry_delta = self.config.short_delta_target

            # Validierung: Long Strike muss unter Short Strike liegen
            if short_strike and long_strike and long_strike >= short_strike:
                logger.debug(f"Delta-based strikes invalid for {symbol}: "
                           f"short={short_strike}, long={long_strike}. Using fallback.")
                short_strike = None
                long_strike = None

        # Fallback: OTM%-basierte Strike-Auswahl (alte Methode)
        if short_strike is None or long_strike is None:
            otm_pct = self.config.min_otm_pct / 100
            short_strike = round(current_price * (1 - otm_pct), 0)

            spread_width_pct = self.config.spread_width_pct / 100
            spread_width = max(5.0, round(current_price * spread_width_pct / 5) * 5)
            long_strike = short_strike - spread_width

        spread_width = short_strike - long_strike

        # Black-Scholes Pricing für realistische Credits
        if self._simulator and self.config.use_black_scholes:

            vix = entry_signal.get("vix")

            # Temporäres Sizing für Entry-Simulation (wird unten korrigiert)
            temp_entry = self._simulator.simulate_entry(
                symbol=symbol,
                underlying_price=current_price,
                short_strike=short_strike,
                long_strike=long_strike,
                dte=self.config.dte_max,
                iv=iv,
                entry_date=entry_date,
                contracts=1,
                vix=vix
            )

            net_credit = temp_entry.net_credit

            # Position-Sizing basierend auf realistischem Pricing
            max_loss_per_contract = temp_entry.max_loss
            if max_loss_per_contract <= 0:
                max_loss_per_contract = (spread_width - net_credit) * 100

            contracts = max(1, int(max_risk / max_loss_per_contract))

            # Finales Entry mit korrekter Contract-Anzahl
            entry = self._simulator.simulate_entry(
                symbol=symbol,
                underlying_price=current_price,
                short_strike=short_strike,
                long_strike=long_strike,
                dte=self.config.dte_max,
                iv=iv,
                entry_date=entry_date,
                contracts=contracts,
                vix=vix
            )

            return {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": current_price,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "spread_width": spread_width,
                "net_credit": entry.net_credit,
                "contracts": contracts,
                "max_profit": entry.max_profit,
                "max_loss": entry.max_loss,
                "entry_vix": vix,
                "entry_iv": iv,
                "pullback_score": entry_signal.get("score"),
                "score_breakdown": entry_signal.get("score_breakdown"),
                "dte_at_entry": self.config.dte_max,
                "expiry_date": entry.expiry_date,
                "commission": entry.commission,
                "last_price": current_price,
                "entry_delta": entry.entry_delta,
                "entry_theta": entry.entry_theta,
                # Store SpreadEntry for later calculations
                "_spread_entry": entry,
            }

        # Fallback: Vereinfachte Berechnung (alte Methode)
        credit_pct = self.config.min_credit_pct / 100
        net_credit = spread_width * credit_pct

        # Slippage
        net_credit *= (1 - self.config.slippage_pct / 100)

        # Position-Sizing
        max_loss_per_contract = (spread_width - net_credit) * 100
        contracts = max(1, int(max_risk / max_loss_per_contract))

        total_max_profit = net_credit * 100 * contracts
        total_max_loss = max_loss_per_contract * contracts

        # Kommission
        commission = self.config.commission_per_contract * contracts * 2  # Open + Close

        return {
            "symbol": symbol,
            "entry_date": entry_date,
            "entry_price": current_price,
            "short_strike": short_strike,
            "long_strike": long_strike,
            "spread_width": spread_width,
            "net_credit": net_credit,
            "contracts": contracts,
            "max_profit": total_max_profit - commission,
            "max_loss": total_max_loss + commission,
            "entry_vix": entry_signal.get("vix"),
            "pullback_score": entry_signal.get("score"),
            "score_breakdown": entry_signal.get("score_breakdown"),
            "dte_at_entry": self.config.dte_max,  # Annahme: Entry bei max DTE
            "expiry_date": entry_date + timedelta(days=self.config.dte_max),
            "commission": commission,
            "last_price": current_price,
        }

    def _check_exit_signal(
        self,
        position: Dict,
        current_date: date
    ) -> Optional[Tuple]:
        """
        Prüft ob Exit-Signal vorhanden.

        Returns:
            Tuple von (ExitReason, exit_price) oder None
        """
        # Import here to avoid circular imports
        from .engine import ExitReason

        symbol = position["symbol"]
        price_data = self._get_price_on_date(symbol, current_date)

        if price_data:
            position["last_price"] = price_data.get("close", position["entry_price"])

        current_price = position["last_price"]
        short_strike = position["short_strike"]
        net_credit = position["net_credit"]
        expiry = position["expiry_date"]

        # DTE berechnen
        dte = (expiry - current_date).days

        # 1. Expiration
        if current_date >= expiry:
            return (ExitReason.EXPIRATION, current_price)

        # Black-Scholes basierte Exit-Prüfung
        if self._simulator and self.config.use_black_scholes and "_spread_entry" in position:
            spread_entry = position["_spread_entry"]

            # IV für aktuellen Tag
            current_iv = self._get_iv_on_date(symbol, current_date)
            if current_iv is None:
                current_iv = self._estimate_iv_from_hv(symbol, current_date)

            vix = self._get_vix_on_date(current_date)

            # Berechne aktuellen Snapshot
            snapshot = self._simulator.calculate_snapshot(
                entry=spread_entry,
                current_date=current_date,
                current_price=current_price,
                current_iv=current_iv,
                vix=vix
            )

            # Store snapshot for close calculation
            position["_last_snapshot"] = snapshot

            # Prüfe Exit-Bedingungen mit realistischem P&L
            exit_reason = self._simulator.check_exit_conditions(
                snapshot=snapshot,
                entry=spread_entry,
                profit_target_pct=self.config.profit_target_pct,
                stop_loss_pct=self.config.stop_loss_pct,
                dte_exit_threshold=self.config.dte_exit_threshold
            )

            if exit_reason == "profit_target":
                return (ExitReason.PROFIT_TARGET_HIT, current_price)
            elif exit_reason == "stop_loss":
                return (ExitReason.STOP_LOSS_HIT, current_price)
            elif exit_reason == "dte_threshold":
                return (ExitReason.DTE_THRESHOLD, current_price)
            elif exit_reason == "deep_itm":
                return (ExitReason.BREACH_SHORT_STRIKE, current_price)
            elif exit_reason == "expiration":
                return (ExitReason.EXPIRATION, current_price)

            return None

        # Fallback: Vereinfachte Exit-Prüfung (alte Methode)
        # 2. Short Strike durchbrochen (simuliere Assignment-Risiko)
        if current_price < short_strike:
            # Simuliere erhöhte Spread-Kosten bei ITM
            spread_value = short_strike - current_price
            if spread_value >= position["spread_width"] * 0.8:
                return (ExitReason.BREACH_SHORT_STRIKE, current_price)

        # 3. Profit Target
        # Vereinfachte Annahme: Spread-Wert sinkt proportional zur Zeit und Preis-Distanz
        days_held = (current_date - position["entry_date"]).days
        if days_held > 0 and dte > 0:
            time_decay_factor = days_held / position["dte_at_entry"]
            price_buffer_pct = ((current_price - short_strike) / short_strike) * 100

            # Je höher der Preis über Short Strike und je mehr Zeit vergangen,
            # desto mehr hat sich der Spread-Wert reduziert
            estimated_profit_pct = min(
                (time_decay_factor * 50) + (price_buffer_pct * 5),
                100
            )

            if estimated_profit_pct >= self.config.profit_target_pct:
                return (ExitReason.PROFIT_TARGET_HIT, current_price)

        # 4. DTE Threshold
        if dte <= self.config.dte_exit_threshold and dte > 0:
            return (ExitReason.DTE_THRESHOLD, current_price)

        # 5. Stop Loss
        if current_price < short_strike:
            loss_pct = ((short_strike - current_price) / net_credit) * 100
            if loss_pct >= self.config.stop_loss_pct:
                return (ExitReason.STOP_LOSS_HIT, current_price)

        return None

    def _close_position(
        self,
        position: Dict,
        exit_date: date,
        exit_reason,  # ExitReason
        exit_price: float
    ):
        """Schließt eine Position und berechnet P&L"""
        # Import here to avoid circular imports
        from .engine import TradeOutcome, TradeResult

        short_strike = position["short_strike"]
        long_strike = position["long_strike"]
        net_credit = position["net_credit"]
        contracts = position["contracts"]
        commission = position["commission"]

        # Black-Scholes basierte P&L-Berechnung
        if self._simulator and self.config.use_black_scholes and "_spread_entry" in position:
            # Verwende letzten Snapshot wenn vorhanden
            if "_last_snapshot" in position:
                snapshot = position["_last_snapshot"]
                realized_pnl = snapshot.unrealized_pnl_total
            else:
                # Berechne finalen Snapshot
                spread_entry = position["_spread_entry"]
                current_iv = self._get_iv_on_date(position["symbol"], exit_date)
                if current_iv is None:
                    current_iv = self._estimate_iv_from_hv(position["symbol"], exit_date)

                vix = self._get_vix_on_date(exit_date)

                snapshot = self._simulator.calculate_snapshot(
                    entry=spread_entry,
                    current_date=exit_date,
                    current_price=exit_price,
                    current_iv=current_iv,
                    vix=vix
                )
                realized_pnl = snapshot.unrealized_pnl_total

            # Bestimme Outcome basierend auf P&L
            if realized_pnl >= position["max_profit"] * 0.95:
                outcome = TradeOutcome.MAX_PROFIT
            elif realized_pnl >= position["max_profit"] * 0.5:
                from .engine import ExitReason
                if exit_reason == ExitReason.PROFIT_TARGET_HIT:
                    outcome = TradeOutcome.PROFIT_TARGET
                else:
                    outcome = TradeOutcome.PARTIAL_PROFIT
            elif realized_pnl > 0:
                outcome = TradeOutcome.PARTIAL_PROFIT
            elif realized_pnl <= -position["max_loss"] * 0.95:
                outcome = TradeOutcome.MAX_LOSS
            elif realized_pnl < 0:
                from .engine import ExitReason
                if exit_reason == ExitReason.STOP_LOSS_HIT:
                    outcome = TradeOutcome.STOP_LOSS
                else:
                    outcome = TradeOutcome.PARTIAL_LOSS
            else:
                outcome = TradeOutcome.PARTIAL_PROFIT

        else:
            from .engine import ExitReason
            # Fallback: Vereinfachte P&L-Berechnung (alte Methode)
            if exit_price >= short_strike:
                # Beide Puts OTM - Max Profit
                realized_pnl = position["max_profit"]
                outcome = TradeOutcome.MAX_PROFIT
            elif exit_price <= long_strike:
                # Beide Puts ITM - Max Loss
                realized_pnl = -position["max_loss"]
                outcome = TradeOutcome.MAX_LOSS
            else:
                # Zwischen den Strikes
                intrinsic_value = short_strike - exit_price
                spread_cost = intrinsic_value * 100 * contracts
                realized_pnl = (net_credit * 100 * contracts) - spread_cost - commission

                if realized_pnl > 0:
                    if realized_pnl >= position["max_profit"] * 0.9:
                        outcome = TradeOutcome.MAX_PROFIT
                    elif exit_reason == ExitReason.PROFIT_TARGET_HIT:
                        outcome = TradeOutcome.PROFIT_TARGET
                    else:
                        outcome = TradeOutcome.PARTIAL_PROFIT
                elif realized_pnl < 0:
                    if exit_reason == ExitReason.STOP_LOSS_HIT:
                        outcome = TradeOutcome.STOP_LOSS
                    else:
                        outcome = TradeOutcome.PARTIAL_LOSS
                else:
                    outcome = TradeOutcome.PARTIAL_PROFIT

        dte_at_exit = (position["expiry_date"] - exit_date).days
        hold_days = (exit_date - position["entry_date"]).days

        return TradeResult(
            symbol=position["symbol"],
            entry_date=position["entry_date"],
            exit_date=exit_date,
            entry_price=position["entry_price"],
            exit_price=exit_price,
            short_strike=short_strike,
            long_strike=long_strike,
            spread_width=position["spread_width"],
            net_credit=net_credit,
            contracts=contracts,
            max_profit=position["max_profit"],
            max_loss=position["max_loss"],
            realized_pnl=realized_pnl,
            outcome=outcome,
            exit_reason=exit_reason,
            dte_at_entry=position["dte_at_entry"],
            dte_at_exit=max(0, dte_at_exit),
            hold_days=max(1, hold_days),
            entry_vix=position.get("entry_vix"),
            pullback_score=position.get("pullback_score"),
            short_delta_at_entry=position.get("entry_delta"),
            score_breakdown=position.get("score_breakdown"),
        )
