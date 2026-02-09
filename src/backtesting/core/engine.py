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

Implementation split into sub-modules:
- core/entry_exit.py  - Entry/exit signal logic (EntryExitMixin)
- core/metrics_calc.py - Metrics and IV estimation (MetricsCalcMixin)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import List, Dict, Optional, Tuple, Callable
import statistics

from ..simulation import OptionsSimulator, SpreadEntry, SpreadSnapshot, OptionsSimulatorConfig as SimulatorConfig
from .entry_exit import EntryExitMixin
from .metrics_calc import MetricsCalcMixin

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
    """
    Konfiguration für Backtest.

    WICHTIG - Stop Loss Korrektur:
    Der ursprüngliche stop_loss_pct von 200% war zu weit und ermöglichte
    fast vollständige Verluste. Der neue Default von 100% (1:1 Risk/Reward)
    ist realistischer und entspricht Best Practices.

    Hinweis zu Look-Ahead Bias:
    Das Backtesting verwendet jetzt T-1 Daten für Signal-Generierung,
    um Look-Ahead Bias zu vermeiden. Der Entry erfolgt am nächsten Tag.
    """
    # Zeitraum
    start_date: date
    end_date: date

    # Kapital
    initial_capital: float = 100000.0
    max_position_pct: float = 5.0  # Max % des Kapitals pro Position
    max_total_risk_pct: float = 25.0  # Max % des Kapitals als Gesamtrisiko

    # Entry-Kriterien
    min_pullback_score: float = 5.0
    min_otm_pct: float = 8.0  # Minimum OTM% für Short Strike (Fallback wenn kein Delta)
    dte_min: int = 60
    dte_max: int = 90

    # Delta-basierte Strike-Auswahl (gemäß strategies.yaml Basisstrategie)
    # Short Put: verkauft, Delta um -0.20
    short_delta_target: float = -0.20
    short_delta_min: float = -0.25
    short_delta_max: float = -0.15
    # Long Put: gekauft, Delta um -0.05
    long_delta_target: float = -0.05
    long_delta_min: float = -0.08
    long_delta_max: float = -0.03

    # Strike-Auswahl Methode
    use_delta_based_strikes: bool = True  # True = Delta-basiert, False = OTM%-basiert

    # Exit-Kriterien (KORRIGIERT)
    profit_target_pct: float = 50.0  # % des Max Profits
    stop_loss_pct: float = 100.0  # KORRIGIERT: 100% = 1:1 Risk/Reward (war 200%)
    dte_exit_threshold: int = 14  # Exit wenn DTE < X

    # Spread-Parameter
    min_credit_pct: float = 10.0  # Min Credit als % der Spread-Width (PLAYBOOK §2)
    spread_width_pct: float = 5.0  # Spread-Width als % des Aktienkurses

    # Simulation
    slippage_pct: float = 1.0  # Slippage in % des Spreads
    commission_per_contract: float = 1.30  # Kommission pro Contract

    # Earnings-Filter
    min_days_to_earnings: int = 14  # Keine Trades wenn Earnings < X Tage

    # Look-Ahead Bias Prevention (NEU)
    use_previous_day_signals: bool = True  # Signal von T-1, Entry am T

    # Black-Scholes Pricing (NEU)
    use_black_scholes: bool = True  # True = realistische Options-Pricing
    default_iv: float = 0.25  # Default IV wenn keine historischen Daten

    # E.6: Survivorship-Bias Mitigation
    include_delisted: bool = False  # True = include delisted symbols in backtest


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
    # Score-Breakdown für Komponenten-Analyse (Signal Validation)
    # Format: {"rsi_score": 2.0, "support_score": 1.5, ...}
    score_breakdown: Optional[Dict[str, float]] = None

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
            "=",
            "  BACKTEST ERGEBNIS",
            "=",
            f"  Zeitraum:          {self.config.start_date} bis {self.config.end_date}",
            f"  Startkapital:      ${self.config.initial_capital:,.2f}",
            "",
            "-",
            "  TRADES",
            "-",
            f"  Gesamt:            {self.total_trades}",
            f"  Gewinner:          {self.winning_trades} ({self.win_rate:.1f}%)",
            f"  Verlierer:         {self.losing_trades}",
            f"  Ø Haltedauer:      {self.avg_hold_days:.1f} Tage",
            "",
            "-",
            "  PERFORMANCE",
            "-",
            f"  Gesamt P&L:        ${self.total_pnl:+,.2f}",
            f"  Return:            {(self.total_pnl / self.config.initial_capital) * 100:+.2f}%",
            f"  Profit Factor:     {self.profit_factor:.2f}",
            "",
            f"  Ø Gewinn:          ${self.avg_win:,.2f}",
            f"  Ø Verlust:         ${self.avg_loss:,.2f}",
            "",
            "-",
            "  RISIKO",
            "-",
            f"  Max Drawdown:      ${self.max_drawdown:,.2f} ({self.max_drawdown_pct:.1f}%)",
            f"  Sharpe Ratio:      {self.sharpe_ratio:.2f}",
            "",
            "-",
            "  OUTCOME-VERTEILUNG",
            "-",
        ]

        for outcome, count in sorted(self.outcome_distribution.items()):
            pct = (count / self.total_trades * 100) if self.total_trades > 0 else 0
            lines.append(f"  {outcome:20s} {count:4d} ({pct:5.1f}%)")

        lines.append("=")

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


class BacktestEngine(MetricsCalcMixin, EntryExitMixin):
    """
    Backtesting Engine für Bull-Put-Spread Strategien.

    Features:
    - Historische Trade-Simulation
    - VIX-basierte Regime-Anpassung
    - Portfolio-Management (Position-Sizing)
    - Detaillierte Performance-Metriken

    Implementation delegated to mixins:
    - MetricsCalcMixin: data access, IV estimation, trading days
    - EntryExitMixin: entry/exit signals, position open/close
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
        self._iv_data: Dict[str, List[Dict]] = {}  # Historical IV per symbol

        # Options Simulator für realistische Pricing
        if config.use_black_scholes:
            sim_config = SimulatorConfig(
                entry_slippage_pct=config.slippage_pct,
                exit_slippage_pct=config.slippage_pct * 1.5,
                commission_per_contract=config.commission_per_contract
            )
            self._simulator = OptionsSimulator(sim_config)
        else:
            self._simulator = None

    def run_sync(
        self,
        symbols: List[str],
        historical_data: Dict[str, List[Dict]],
        vix_data: Optional[List[Dict]] = None,
        iv_data: Optional[Dict[str, List[Dict]]] = None,
        entry_filter: Optional[Callable] = None,
    ) -> BacktestResult:
        """
        Führt Backtest synchron durch (für Tests).

        Args:
            symbols: Liste der zu testenden Symbole
            historical_data: Dict mit {symbol: [{date, open, high, low, close, volume}, ...]}
            vix_data: Optional VIX-Historie [{date, close}, ...]
            iv_data: Optional IV-Historie {symbol: [{date, iv}, ...]}
            entry_filter: Optional Filter-Funktion für Entry-Signale

        Returns:
            BacktestResult mit allen Trades und Metriken
        """
        self._historical_data = historical_data
        self._vix_data = vix_data or []
        self._iv_data = iv_data or {}

        # E.6: Filter delisted symbols unless explicitly included
        if not self.config.include_delisted:
            symbols = self._filter_delisted(symbols)

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

    def _filter_delisted(self, symbols: List[str]) -> List[str]:
        """E.6: Filter out delisted symbols using symbol_fundamentals table."""
        try:
            from ...cache import get_fundamentals_manager
            manager = get_fundamentals_manager()
            filtered = []
            for sym in symbols:
                f = manager.get_fundamentals(sym)
                # Check delisted column (added via ALTER TABLE)
                if f and getattr(f, 'delisted', 0) == 1:
                    logger.info(f"Excluding delisted symbol: {sym}")
                    continue
                filtered.append(sym)
            return filtered
        except Exception as e:
            logger.debug(f"Delisted filter unavailable ({e}), using all symbols")
            return symbols
