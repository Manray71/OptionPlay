#!/usr/bin/env python3
"""
Backtesting Engine für Bull-Put-Spread Strategien

Simuliert historische Trades basierend auf:
- Entry: Pullback-Score, VIX-Regime, Strike-Auswahl
- Exit: Profit-Target, Stop-Loss, DTE-basiert, Expiration
- Portfolio: Position-Sizing, Max-Risiko

Verwendung:
    from src.backtesting import BacktestEngine, BacktestConfig

    config = BacktestConfig(
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 31),
        initial_capital=100000,
        profit_target_pct=50,
        stop_loss_pct=200,
    )

    engine = BacktestEngine(config)
    result = await engine.run(symbols=["AAPL", "MSFT", "GOOGL"])
    print(result.summary())
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import List, Dict, Optional, Tuple, Callable
import statistics

logger = logging.getLogger(__name__)


class TradeOutcome(Enum):
    """Ergebnis eines Trades"""
    MAX_PROFIT = "max_profit"      # Expired worthless (100% profit)
    PROFIT_TARGET = "profit_target"  # Closed at profit target
    STOP_LOSS = "stop_loss"        # Closed at stop loss
    TIME_EXIT = "time_exit"        # Closed due to DTE threshold
    MAX_LOSS = "max_loss"          # Assigned (100% loss)
    PARTIAL_PROFIT = "partial_profit"  # Closed with some profit
    PARTIAL_LOSS = "partial_loss"  # Closed with some loss


class ExitReason(Enum):
    """Grund für Trade-Exit"""
    PROFIT_TARGET_HIT = "profit_target"
    STOP_LOSS_HIT = "stop_loss"
    DTE_THRESHOLD = "dte_threshold"
    EXPIRATION = "expiration"
    BREACH_SHORT_STRIKE = "breach_short_strike"
    MANUAL = "manual"


@dataclass
class BacktestConfig:
    """Konfiguration für Backtest"""
    # Zeitraum
    start_date: date
    end_date: date

    # Kapital
    initial_capital: float = 100000.0
    max_position_pct: float = 5.0  # Max % des Kapitals pro Position
    max_total_risk_pct: float = 25.0  # Max % des Kapitals als Gesamtrisiko

    # Entry-Kriterien
    min_pullback_score: float = 5.0
    min_otm_pct: float = 8.0  # Minimum OTM% für Short Strike
    target_delta: float = -0.20
    dte_min: int = 45
    dte_max: int = 75

    # Exit-Kriterien
    profit_target_pct: float = 50.0  # % des Max Profits
    stop_loss_pct: float = 200.0  # % des Credit (2x Credit = Stop)
    dte_exit_threshold: int = 14  # Exit wenn DTE < X

    # Spread-Parameter
    min_credit_pct: float = 20.0  # Min Credit als % der Spread-Width
    spread_width_pct: float = 5.0  # Spread-Width als % des Aktienkurses

    # Simulation
    slippage_pct: float = 1.0  # Slippage in % des Spreads
    commission_per_contract: float = 1.30  # Kommission pro Contract

    # Earnings-Filter
    min_days_to_earnings: int = 14  # Keine Trades wenn Earnings < X Tage


@dataclass
class TradeResult:
    """Ergebnis eines einzelnen Trades"""
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float  # Aktienkurs bei Entry
    exit_price: float  # Aktienkurs bei Exit

    short_strike: float
    long_strike: float
    spread_width: float
    net_credit: float  # Credit pro Aktie
    contracts: int

    max_profit: float  # In Dollar
    max_loss: float  # In Dollar
    realized_pnl: float  # Tatsächlicher P&L

    outcome: TradeOutcome
    exit_reason: ExitReason

    dte_at_entry: int
    dte_at_exit: int
    hold_days: int

    # Optional: zusätzliche Metriken
    entry_vix: Optional[float] = None
    pullback_score: Optional[float] = None
    short_delta_at_entry: Optional[float] = None

    @property
    def pnl_pct(self) -> float:
        """P&L als % des Max Profits"""
        if self.max_profit == 0:
            return 0.0
        return (self.realized_pnl / self.max_profit) * 100

    @property
    def is_winner(self) -> bool:
        """Trade war profitabel"""
        return self.realized_pnl > 0

    @property
    def risk_reward_achieved(self) -> float:
        """Tatsächliches Risk/Reward"""
        if self.max_loss == 0:
            return 0.0
        return self.realized_pnl / self.max_loss


@dataclass
class BacktestResult:
    """Gesamtergebnis des Backtests"""
    config: BacktestConfig
    trades: List[TradeResult]

    # Zusammenfassung
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0

    total_pnl: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0

    # Metriken
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    avg_hold_days: float = 0.0

    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0

    # Equity-Kurve
    equity_curve: List[Tuple[date, float]] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)

    # Outcome-Verteilung
    outcome_distribution: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        """Berechnet Metriken aus Trades"""
        if self.trades:
            self._calculate_metrics()

    def _calculate_metrics(self):
        """Berechnet alle Metriken"""
        self.total_trades = len(self.trades)

        winners = [t for t in self.trades if t.is_winner]
        losers = [t for t in self.trades if t.realized_pnl < 0]
        breakeven = [t for t in self.trades if t.realized_pnl == 0]

        self.winning_trades = len(winners)
        self.losing_trades = len(losers)
        self.breakeven_trades = len(breakeven)

        self.total_profit = sum(t.realized_pnl for t in winners)
        self.total_loss = abs(sum(t.realized_pnl for t in losers))
        self.total_pnl = self.total_profit - self.total_loss

        # Win Rate
        if self.total_trades > 0:
            self.win_rate = (self.winning_trades / self.total_trades) * 100

        # Durchschnitte
        if winners:
            self.avg_win = self.total_profit / len(winners)
        if losers:
            self.avg_loss = self.total_loss / len(losers)

        # Profit Factor
        if self.total_loss > 0:
            self.profit_factor = self.total_profit / self.total_loss

        # Hold Days
        if self.trades:
            self.avg_hold_days = statistics.mean(t.hold_days for t in self.trades)

        # Outcome-Verteilung
        for outcome in TradeOutcome:
            count = len([t for t in self.trades if t.outcome == outcome])
            if count > 0:
                self.outcome_distribution[outcome.value] = count

        # Equity-Kurve und Drawdown
        self._calculate_equity_curve()
        self._calculate_drawdown()
        self._calculate_sharpe()

    def _calculate_equity_curve(self):
        """Berechnet die Equity-Kurve"""
        if not self.trades:
            return

        # Sortiere Trades nach Exit-Datum
        sorted_trades = sorted(self.trades, key=lambda t: t.exit_date)

        equity = self.config.initial_capital
        self.equity_curve = [(self.config.start_date, equity)]

        for trade in sorted_trades:
            equity += trade.realized_pnl
            self.equity_curve.append((trade.exit_date, equity))

    def _calculate_drawdown(self):
        """Berechnet Max Drawdown"""
        if not self.equity_curve:
            return

        peak = self.config.initial_capital
        max_dd = 0.0

        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        self.max_drawdown = max_dd
        if peak > 0:
            self.max_drawdown_pct = (max_dd / peak) * 100

    def _calculate_sharpe(self):
        """Berechnet Sharpe Ratio (annualisiert)"""
        if len(self.trades) < 2:
            return

        # Berechne tägliche Returns (vereinfacht: pro Trade)
        returns = [t.realized_pnl / self.config.initial_capital for t in self.trades]
        self.daily_returns = returns

        if len(returns) < 2:
            return

        avg_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)

        if std_return > 0:
            # Annualisierung: ~252 Handelstage, ~12 Trades/Jahr angenommen
            trades_per_year = 12
            self.sharpe_ratio = (avg_return * trades_per_year) / (std_return * (trades_per_year ** 0.5))

    def summary(self) -> str:
        """Formatierte Zusammenfassung"""
        lines = [
            "═══════════════════════════════════════════════════════════",
            "  BACKTEST ERGEBNIS",
            "═══════════════════════════════════════════════════════════",
            f"  Zeitraum:          {self.config.start_date} bis {self.config.end_date}",
            f"  Startkapital:      ${self.config.initial_capital:,.2f}",
            "",
            "───────────────────────────────────────────────────────────",
            "  TRADES",
            "───────────────────────────────────────────────────────────",
            f"  Gesamt:            {self.total_trades}",
            f"  Gewinner:          {self.winning_trades} ({self.win_rate:.1f}%)",
            f"  Verlierer:         {self.losing_trades}",
            f"  Ø Haltedauer:      {self.avg_hold_days:.1f} Tage",
            "",
            "───────────────────────────────────────────────────────────",
            "  PERFORMANCE",
            "───────────────────────────────────────────────────────────",
            f"  Gesamt P&L:        ${self.total_pnl:+,.2f}",
            f"  Return:            {(self.total_pnl / self.config.initial_capital) * 100:+.2f}%",
            f"  Profit Factor:     {self.profit_factor:.2f}",
            "",
            f"  Ø Gewinn:          ${self.avg_win:,.2f}",
            f"  Ø Verlust:         ${self.avg_loss:,.2f}",
            "",
            "───────────────────────────────────────────────────────────",
            "  RISIKO",
            "───────────────────────────────────────────────────────────",
            f"  Max Drawdown:      ${self.max_drawdown:,.2f} ({self.max_drawdown_pct:.1f}%)",
            f"  Sharpe Ratio:      {self.sharpe_ratio:.2f}",
            "",
            "───────────────────────────────────────────────────────────",
            "  OUTCOME-VERTEILUNG",
            "───────────────────────────────────────────────────────────",
        ]

        for outcome, count in sorted(self.outcome_distribution.items()):
            pct = (count / self.total_trades * 100) if self.total_trades > 0 else 0
            lines.append(f"  {outcome:20s} {count:4d} ({pct:5.1f}%)")

        lines.append("═══════════════════════════════════════════════════════════")

        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary"""
        return {
            "config": {
                "start_date": str(self.config.start_date),
                "end_date": str(self.config.end_date),
                "initial_capital": self.config.initial_capital,
            },
            "summary": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "win_rate": self.win_rate,
                "total_pnl": self.total_pnl,
                "profit_factor": self.profit_factor,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct,
                "sharpe_ratio": self.sharpe_ratio,
                "avg_hold_days": self.avg_hold_days,
            },
            "outcome_distribution": self.outcome_distribution,
            "trades": [
                {
                    "symbol": t.symbol,
                    "entry_date": str(t.entry_date),
                    "exit_date": str(t.exit_date),
                    "realized_pnl": t.realized_pnl,
                    "outcome": t.outcome.value,
                }
                for t in self.trades
            ],
        }


class BacktestEngine:
    """
    Backtesting Engine für Bull-Put-Spread Strategien.

    Features:
    - Historische Trade-Simulation
    - VIX-basierte Regime-Anpassung
    - Portfolio-Management (Position-Sizing)
    - Detaillierte Performance-Metriken
    """

    def __init__(self, config: BacktestConfig):
        """
        Initialisiert die Backtest-Engine.

        Args:
            config: Backtest-Konfiguration
        """
        self.config = config
        self._historical_data: Dict[str, List[Dict]] = {}
        self._vix_data: List[Dict] = []

    def run_sync(
        self,
        symbols: List[str],
        historical_data: Dict[str, List[Dict]],
        vix_data: Optional[List[Dict]] = None,
        entry_filter: Optional[Callable] = None,
    ) -> BacktestResult:
        """
        Führt Backtest synchron durch (für Tests).

        Args:
            symbols: Liste der zu testenden Symbole
            historical_data: Dict mit {symbol: [{date, open, high, low, close, volume}, ...]}
            vix_data: Optional VIX-Historie [{date, close}, ...]
            entry_filter: Optional Filter-Funktion für Entry-Signale

        Returns:
            BacktestResult mit allen Trades und Metriken
        """
        self._historical_data = historical_data
        self._vix_data = vix_data or []

        trades: List[TradeResult] = []
        open_positions: List[Dict] = []
        current_capital = self.config.initial_capital
        current_risk = 0.0

        # Generiere alle Trading-Tage
        trading_days = self._get_trading_days()

        for current_date in trading_days:
            # 1. Prüfe bestehende Positionen auf Exit
            positions_to_close = []
            for pos in open_positions:
                exit_signal = self._check_exit_signal(pos, current_date)
                if exit_signal:
                    positions_to_close.append((pos, exit_signal))

            # Schließe Positionen
            for pos, (reason, exit_price) in positions_to_close:
                trade = self._close_position(pos, current_date, reason, exit_price)
                trades.append(trade)
                current_capital += trade.realized_pnl
                current_risk -= pos["max_loss"]
                open_positions.remove(pos)

            # 2. Prüfe Entry-Signale für neue Positionen
            for symbol in symbols:
                # Prüfe Kapital-Limits
                if current_risk >= self.config.initial_capital * (self.config.max_total_risk_pct / 100):
                    continue

                # Prüfe ob bereits Position in diesem Symbol
                if any(p["symbol"] == symbol for p in open_positions):
                    continue

                entry_signal = self._check_entry_signal(symbol, current_date, entry_filter)
                if entry_signal:
                    # Position-Sizing
                    max_position_risk = self.config.initial_capital * (self.config.max_position_pct / 100)
                    available_risk = (self.config.initial_capital * (self.config.max_total_risk_pct / 100)) - current_risk

                    position = self._open_position(
                        symbol, current_date, entry_signal,
                        min(max_position_risk, available_risk)
                    )
                    if position:
                        open_positions.append(position)
                        current_risk += position["max_loss"]

        # Schließe alle verbleibenden Positionen am Ende
        for pos in open_positions:
            trade = self._close_position(
                pos, self.config.end_date,
                ExitReason.MANUAL, pos.get("last_price", pos["entry_price"])
            )
            trades.append(trade)

        return BacktestResult(config=self.config, trades=trades)

    def _get_trading_days(self) -> List[date]:
        """Generiert Liste aller Trading-Tage im Zeitraum"""
        days = []
        current = self.config.start_date
        while current <= self.config.end_date:
            # Einfache Wochentag-Prüfung (Mo-Fr)
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days

    def _get_price_on_date(self, symbol: str, target_date: date) -> Optional[Dict]:
        """Holt Preis-Daten für ein Datum"""
        if symbol not in self._historical_data:
            return None

        for bar in self._historical_data[symbol]:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date == target_date:
                return bar
        return None

    def _get_vix_on_date(self, target_date: date) -> Optional[float]:
        """Holt VIX für ein Datum"""
        for bar in self._vix_data:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date == target_date:
                return bar.get("close")
        return None

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
        score = self._calculate_simple_pullback_score(symbol, current_date, price_data)

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
            "vix": vix,
            "date": current_date,
        }

    def _calculate_simple_pullback_score(
        self,
        symbol: str,
        current_date: date,
        price_data: Dict
    ) -> float:
        """
        Berechnet vereinfachten Pullback-Score.

        In Produktion würde hier der vollständige PullbackAnalyzer verwendet.
        """
        if symbol not in self._historical_data:
            return 0.0

        # Hole letzte 20 Tage
        history = []
        for bar in self._historical_data[symbol]:
            bar_date = bar.get("date")
            if isinstance(bar_date, str):
                bar_date = date.fromisoformat(bar_date)
            if bar_date < current_date:
                history.append(bar)

        if len(history) < 20:
            return 0.0

        history = sorted(history, key=lambda x: x.get("date", ""), reverse=True)[:20]
        closes = [bar.get("close", 0) for bar in history]

        if not closes or closes[0] <= 0:
            return 0.0

        current_close = price_data.get("close", 0)
        sma_20 = sum(closes) / len(closes)
        high_20 = max(bar.get("high", 0) for bar in history)

        score = 0.0

        # Pullback von High (max 3 Punkte)
        pullback_pct = ((high_20 - current_close) / high_20) * 100 if high_20 > 0 else 0
        if 3 <= pullback_pct <= 8:
            score += 3.0
        elif 8 < pullback_pct <= 15:
            score += 2.0
        elif pullback_pct > 15:
            score += 1.0

        # Über SMA20 (max 2 Punkte)
        if current_close > sma_20:
            score += 2.0
        elif current_close > sma_20 * 0.98:
            score += 1.0

        # Uptrend (max 2 Punkte)
        if len(closes) >= 10:
            sma_10 = sum(closes[:10]) / 10
            if sma_10 > sma_20:
                score += 2.0

        # Volume-Spike (max 1 Punkt)
        current_vol = price_data.get("volume", 0)
        avg_vol = sum(bar.get("volume", 0) for bar in history) / len(history)
        if avg_vol > 0 and current_vol > avg_vol * 1.2:
            score += 1.0

        # Support-Nähe (max 2 Punkte)
        lows = [bar.get("low", 0) for bar in history]
        support = min(lows) if lows else 0
        if support > 0:
            dist_to_support = ((current_close - support) / current_close) * 100
            if dist_to_support < 5:
                score += 2.0
            elif dist_to_support < 10:
                score += 1.0

        return min(score, 10.0)

    def _open_position(
        self,
        symbol: str,
        entry_date: date,
        entry_signal: Dict,
        max_risk: float
    ) -> Optional[Dict]:
        """Öffnet eine neue Position"""
        current_price = entry_signal["price"]

        # Berechne Strikes
        otm_pct = self.config.min_otm_pct / 100
        short_strike = round(current_price * (1 - otm_pct), 0)

        spread_width_pct = self.config.spread_width_pct / 100
        spread_width = max(5.0, round(current_price * spread_width_pct / 5) * 5)
        long_strike = short_strike - spread_width

        # Berechne Credit (vereinfacht: ~25% der Spread-Width)
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
            "dte_at_entry": self.config.dte_max,  # Annahme: Entry bei max DTE
            "expiry_date": entry_date + timedelta(days=self.config.dte_max),
            "commission": commission,
            "last_price": current_price,
        }

    def _check_exit_signal(
        self,
        position: Dict,
        current_date: date
    ) -> Optional[Tuple[ExitReason, float]]:
        """
        Prüft ob Exit-Signal vorhanden.

        Returns:
            Tuple von (ExitReason, exit_price) oder None
        """
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
        exit_reason: ExitReason,
        exit_price: float
    ) -> TradeResult:
        """Schließt eine Position und berechnet P&L"""
        short_strike = position["short_strike"]
        long_strike = position["long_strike"]
        net_credit = position["net_credit"]
        contracts = position["contracts"]
        commission = position["commission"]

        # Berechne P&L basierend auf Exit-Preis
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
        )
