#!/usr/bin/env python3
"""
Performance-Metriken für Backtesting

Berechnet verschiedene Risiko- und Performance-Kennzahlen:
- Sharpe Ratio
- Sortino Ratio
- Max Drawdown
- Profit Factor
- Win Rate
- Expectancy
- Kelly Criterion

Verwendung:
    from src.backtesting import PerformanceMetrics, calculate_metrics

    metrics = calculate_metrics(
        trades=trade_list,
        initial_capital=100000,
        risk_free_rate=0.05
    )
    print(metrics.summary())
"""

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Umfassende Performance-Metriken"""

    # Basis
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0

    # P&L
    total_pnl: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    # Durchschnitte
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

    # Verhältnisse
    win_rate: float = 0.0
    profit_factor: float = 0.0
    payoff_ratio: float = 0.0  # avg_win / avg_loss
    expectancy: float = 0.0  # E[R] = win_rate * avg_win - (1-win_rate) * avg_loss
    expectancy_pct: float = 0.0  # Expectancy als % des avg Trade

    # Risiko
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    max_runup: float = 0.0
    avg_drawdown: float = 0.0

    # Risiko-adjustierte Rendite
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0  # CAGR / Max Drawdown

    # Zeit
    avg_hold_days: float = 0.0
    avg_win_hold_days: float = 0.0
    avg_loss_hold_days: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Kapital
    initial_capital: float = 0.0
    final_capital: float = 0.0
    total_return: float = 0.0
    total_return_pct: float = 0.0
    cagr: float = 0.0  # Compound Annual Growth Rate

    # Kelly Criterion
    kelly_fraction: float = 0.0
    half_kelly: float = 0.0

    # Equity Curve Stats
    equity_volatility: float = 0.0
    equity_skewness: float = 0.0
    equity_kurtosis: float = 0.0

    def summary(self) -> str:
        """Formatierte Zusammenfassung"""
        lines = [
            "═══════════════════════════════════════════════════════════",
            "  PERFORMANCE METRIKEN",
            "═══════════════════════════════════════════════════════════",
            "",
            "───────────────────────────────────────────────────────────",
            "  TRADES",
            "───────────────────────────────────────────────────────────",
            f"  Gesamt:               {self.total_trades}",
            f"  Gewinner:             {self.winning_trades} ({self.win_rate:.1f}%)",
            f"  Verlierer:            {self.losing_trades}",
            f"  Max. Gewinnserie:     {self.max_consecutive_wins}",
            f"  Max. Verlustserie:    {self.max_consecutive_losses}",
            "",
            "───────────────────────────────────────────────────────────",
            "  PROFIT/LOSS",
            "───────────────────────────────────────────────────────────",
            f"  Gesamt P&L:           ${self.total_pnl:+,.2f}",
            f"  Total Return:         {self.total_return_pct:+.2f}%",
            f"  CAGR:                 {self.cagr:.2f}%",
            "",
            f"  Ø Gewinn:             ${self.avg_win:,.2f}",
            f"  Ø Verlust:            ${self.avg_loss:,.2f}",
            f"  Größter Gewinn:       ${self.largest_win:,.2f}",
            f"  Größter Verlust:      ${self.largest_loss:,.2f}",
            "",
            "───────────────────────────────────────────────────────────",
            "  KENNZAHLEN",
            "───────────────────────────────────────────────────────────",
            f"  Profit Factor:        {self.profit_factor:.2f}",
            f"  Payoff Ratio:         {self.payoff_ratio:.2f}",
            f"  Expectancy:           ${self.expectancy:+,.2f}",
            "",
            "───────────────────────────────────────────────────────────",
            "  RISIKO",
            "───────────────────────────────────────────────────────────",
            f"  Max Drawdown:         ${self.max_drawdown:,.2f} ({self.max_drawdown_pct:.1f}%)",
            f"  Sharpe Ratio:         {self.sharpe_ratio:.2f}",
            f"  Sortino Ratio:        {self.sortino_ratio:.2f}",
            f"  Calmar Ratio:         {self.calmar_ratio:.2f}",
            "",
            "───────────────────────────────────────────────────────────",
            "  POSITION SIZING",
            "───────────────────────────────────────────────────────────",
            f"  Kelly Fraction:       {self.kelly_fraction:.1f}%",
            f"  Half-Kelly:           {self.half_kelly:.1f}%",
            "",
            "───────────────────────────────────────────────────────────",
            "  HALTEDAUER",
            "───────────────────────────────────────────────────────────",
            f"  Ø Haltedauer:         {self.avg_hold_days:.1f} Tage",
            f"  Ø Gewinner:           {self.avg_win_hold_days:.1f} Tage",
            f"  Ø Verlierer:          {self.avg_loss_hold_days:.1f} Tage",
            "═══════════════════════════════════════════════════════════",
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary"""
        return {
            "trades": {
                "total": self.total_trades,
                "winning": self.winning_trades,
                "losing": self.losing_trades,
                "win_rate": self.win_rate,
            },
            "pnl": {
                "total": self.total_pnl,
                "total_return_pct": self.total_return_pct,
                "cagr": self.cagr,
                "avg_win": self.avg_win,
                "avg_loss": self.avg_loss,
            },
            "ratios": {
                "profit_factor": self.profit_factor,
                "payoff_ratio": self.payoff_ratio,
                "expectancy": self.expectancy,
            },
            "risk": {
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct,
                "sharpe_ratio": self.sharpe_ratio,
                "sortino_ratio": self.sortino_ratio,
                "calmar_ratio": self.calmar_ratio,
            },
            "position_sizing": {
                "kelly_fraction": self.kelly_fraction,
                "half_kelly": self.half_kelly,
            },
        }


def calculate_metrics(
    trades: List[Dict],
    initial_capital: float = 100000.0,
    risk_free_rate: float = 0.05,
    trading_days_per_year: int = 252,
) -> PerformanceMetrics:
    """
    Berechnet alle Performance-Metriken aus Trade-Liste.

    Args:
        trades: Liste von Trade-Dicts mit mindestens:
            - realized_pnl: float
            - hold_days: int (optional)
            - entry_date: date (optional)
            - exit_date: date (optional)
        initial_capital: Startkapital
        risk_free_rate: Risikofreier Zinssatz (annualisiert)
        trading_days_per_year: Handelstage pro Jahr

    Returns:
        PerformanceMetrics mit allen Kennzahlen
    """
    if not trades:
        return PerformanceMetrics(initial_capital=initial_capital)

    metrics = PerformanceMetrics(initial_capital=initial_capital)
    metrics.total_trades = len(trades)

    # Extrahiere P&L
    pnls = [t.get("realized_pnl", 0) for t in trades]
    hold_days = [t.get("hold_days", 0) for t in trades]

    # Winners und Losers
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    breakeven = [p for p in pnls if p == 0]

    metrics.winning_trades = len(winners)
    metrics.losing_trades = len(losers)
    metrics.breakeven_trades = len(breakeven)

    # P&L Summen
    metrics.gross_profit = sum(winners)
    metrics.gross_loss = abs(sum(losers))
    metrics.total_profit = metrics.gross_profit
    metrics.total_loss = metrics.gross_loss
    metrics.total_pnl = metrics.gross_profit - metrics.gross_loss

    # Durchschnitte
    if winners:
        metrics.avg_win = metrics.gross_profit / len(winners)
        metrics.largest_win = max(winners)
    if losers:
        metrics.avg_loss = metrics.gross_loss / len(losers)
        metrics.largest_loss = abs(min(losers))
    if pnls:
        metrics.avg_trade = sum(pnls) / len(pnls)

    # Win Rate
    if metrics.total_trades > 0:
        metrics.win_rate = (metrics.winning_trades / metrics.total_trades) * 100

    # Profit Factor
    if metrics.gross_loss > 0:
        metrics.profit_factor = metrics.gross_profit / metrics.gross_loss

    # Payoff Ratio
    if metrics.avg_loss > 0:
        metrics.payoff_ratio = metrics.avg_win / metrics.avg_loss

    # Expectancy
    win_prob = metrics.win_rate / 100
    metrics.expectancy = (win_prob * metrics.avg_win) - ((1 - win_prob) * metrics.avg_loss)
    if metrics.avg_trade != 0:
        metrics.expectancy_pct = (metrics.expectancy / abs(metrics.avg_trade)) * 100

    # Kapital
    metrics.final_capital = initial_capital + metrics.total_pnl
    metrics.total_return = metrics.total_pnl
    metrics.total_return_pct = (metrics.total_pnl / initial_capital) * 100

    # Drawdown
    drawdown_stats = calculate_max_drawdown(pnls, initial_capital)
    metrics.max_drawdown = drawdown_stats["max_drawdown"]
    metrics.max_drawdown_pct = drawdown_stats["max_drawdown_pct"]
    metrics.max_runup = drawdown_stats.get("max_runup", 0)
    metrics.avg_drawdown = drawdown_stats.get("avg_drawdown", 0)

    # Consecutive Wins/Losses
    streaks = calculate_streaks(pnls)
    metrics.max_consecutive_wins = streaks["max_wins"]
    metrics.max_consecutive_losses = streaks["max_losses"]

    # Haltedauer
    if hold_days:
        valid_days = [d for d in hold_days if d > 0]
        if valid_days:
            metrics.avg_hold_days = statistics.mean(valid_days)

        winner_days = [hold_days[i] for i, p in enumerate(pnls) if p > 0 and hold_days[i] > 0]
        loser_days = [hold_days[i] for i, p in enumerate(pnls) if p < 0 and hold_days[i] > 0]

        if winner_days:
            metrics.avg_win_hold_days = statistics.mean(winner_days)
        if loser_days:
            metrics.avg_loss_hold_days = statistics.mean(loser_days)

    # CAGR
    if trades:
        first_date = trades[0].get("entry_date")
        last_date = trades[-1].get("exit_date")
        if first_date and last_date:
            if isinstance(first_date, str):
                first_date = date.fromisoformat(first_date)
            if isinstance(last_date, str):
                last_date = date.fromisoformat(last_date)
            years = (last_date - first_date).days / 365.25
            if years > 0 and metrics.final_capital > 0:
                metrics.cagr = ((metrics.final_capital / initial_capital) ** (1 / years) - 1) * 100

    # Sharpe Ratio
    metrics.sharpe_ratio = calculate_sharpe_ratio(
        pnls, initial_capital, risk_free_rate, trading_days_per_year
    )

    # Sortino Ratio
    metrics.sortino_ratio = calculate_sortino_ratio(
        pnls, initial_capital, risk_free_rate, trading_days_per_year
    )

    # Calmar Ratio
    if metrics.max_drawdown_pct > 0:
        metrics.calmar_ratio = metrics.cagr / metrics.max_drawdown_pct

    # Kelly Criterion
    kelly = calculate_kelly_criterion(metrics.win_rate / 100, metrics.payoff_ratio)
    metrics.kelly_fraction = kelly * 100
    metrics.half_kelly = (kelly / 2) * 100

    # Equity Curve Stats
    equity_stats = calculate_equity_stats(pnls, initial_capital)
    metrics.equity_volatility = equity_stats.get("volatility", 0)
    metrics.equity_skewness = equity_stats.get("skewness", 0)
    metrics.equity_kurtosis = equity_stats.get("kurtosis", 0)

    return metrics


def calculate_sharpe_ratio(
    pnls: List[float],
    initial_capital: float,
    risk_free_rate: float = 0.05,
    periods_per_year: int = 12,
    use_daily_returns: bool = False,
    daily_returns: Optional[List[float]] = None,
) -> float:
    """
    Berechnet die Sharpe Ratio korrekt nach der Standard-Formel.

    Sharpe = (Mean Return - Risk Free Rate) / Std(Returns) * sqrt(Periods)

    Die korrekte Annualisierung:
    - Sharpe_annual = Sharpe_period * sqrt(periods_per_year)
    - NICHT: excess_return * periods / (std * sqrt(periods))

    Args:
        pnls: Liste der Profits/Losses pro Trade
        initial_capital: Startkapital für Return-Berechnung
        risk_free_rate: Risikofreier Zinssatz (annualisiert, z.B. 0.05 für 5%)
        periods_per_year: Trading-Perioden pro Jahr
            - 252 für tägliche Returns
            - 52 für wöchentliche Returns
            - 12 für monatliche Returns
            - Anzahl Trades pro Jahr für trade-basiert
        use_daily_returns: True wenn daily_returns übergeben werden
        daily_returns: Optional Liste von täglichen Returns (bevorzugt)

    Returns:
        Annualisierte Sharpe Ratio

    Beispiel:
        >>> # Trade-basierte Berechnung (weniger genau)
        >>> sharpe = calculate_sharpe_ratio(pnls, 100000, periods_per_year=20)
        >>>
        >>> # Tägliche Returns (genauer)
        >>> sharpe = calculate_sharpe_ratio(
        ...     [], 100000, use_daily_returns=True,
        ...     daily_returns=daily_equity_returns
        ... )
    """
    # Bevorzuge tägliche Returns wenn verfügbar
    if use_daily_returns and daily_returns and len(daily_returns) >= 2:
        returns = daily_returns
        periods = 252  # Handelstage
    elif len(pnls) < 2:
        return 0.0
    else:
        # Trade-basierte Returns (weniger ideal aber funktional)
        returns = [p / initial_capital for p in pnls]
        periods = periods_per_year

    avg_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)

    if std_return == 0:
        return 0.0

    # Risikofreie Rate pro Periode
    rf_per_period = risk_free_rate / periods

    # Korrekte Sharpe Ratio Berechnung:
    # 1. Berechne Excess Return pro Periode
    excess_return_per_period = avg_return - rf_per_period

    # 2. Berechne Sharpe pro Periode
    sharpe_per_period = excess_return_per_period / std_return

    # 3. Annualisiere: multipliziere mit sqrt(periods)
    sharpe_annual = sharpe_per_period * math.sqrt(periods)

    return sharpe_annual


def calculate_sortino_ratio(
    pnls: List[float],
    initial_capital: float,
    risk_free_rate: float = 0.05,
    periods_per_year: int = 12,
    target_return: float = 0.0,
    use_daily_returns: bool = False,
    daily_returns: Optional[List[float]] = None,
) -> float:
    """
    Berechnet die Sortino Ratio korrekt mit Target Return.

    Sortino = (Mean Return - Target Return) / Downside Deviation * sqrt(Periods)

    Die Downside Deviation verwendet nur Returns unter dem Target,
    nicht alle negativen Returns.

    Args:
        pnls: Liste der Profits/Losses pro Trade
        initial_capital: Startkapital
        risk_free_rate: Risikofreier Zinssatz (annualisiert)
        periods_per_year: Perioden pro Jahr (252 für täglich)
        target_return: Minimum akzeptabler Return pro Periode (default: 0)
        use_daily_returns: True wenn daily_returns übergeben werden
        daily_returns: Optional Liste von täglichen Returns

    Returns:
        Annualisierte Sortino Ratio
    """
    # Bevorzuge tägliche Returns wenn verfügbar
    if use_daily_returns and daily_returns and len(daily_returns) >= 2:
        returns = daily_returns
        periods = 252
    elif len(pnls) < 2:
        return 0.0
    else:
        returns = [p / initial_capital for p in pnls]
        periods = periods_per_year

    avg_return = statistics.mean(returns)

    # Downside Returns: alle Returns unter dem Target
    # (nicht nur negative, sondern unter MAR - Minimum Acceptable Return)
    downside_returns = [r - target_return for r in returns if r < target_return]

    if not downside_returns:
        return float("inf") if avg_return > target_return else 0.0

    # Downside Deviation (Semi-Deviation)
    # sqrt(mean(squared downside deviations))
    downside_dev = math.sqrt(
        sum(r**2 for r in downside_returns) / len(returns)  # Teile durch ALLE Returns
    )

    if downside_dev == 0:
        return 0.0

    # Excess Return über Target (nicht Risk-Free Rate für Sortino)
    excess_return = avg_return - target_return

    # Sortino pro Periode
    sortino_per_period = excess_return / downside_dev

    # Annualisieren
    sortino_annual = sortino_per_period * math.sqrt(periods)

    return sortino_annual


def calculate_max_drawdown(pnls: List[float], initial_capital: float) -> Dict:
    """
    Berechnet Max Drawdown und verwandte Metriken.

    Args:
        pnls: Liste der Profits/Losses
        initial_capital: Startkapital

    Returns:
        Dict mit max_drawdown, max_drawdown_pct, max_runup, avg_drawdown
    """
    if not pnls:
        return {"max_drawdown": 0, "max_drawdown_pct": 0}

    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0
    max_runup = 0.0
    drawdowns = []

    for pnl in pnls:
        equity += pnl

        if equity > peak:
            peak = equity
            max_runup = max(max_runup, equity - initial_capital)

        dd = peak - equity
        if dd > 0:
            drawdowns.append(dd)
        max_dd = max(max_dd, dd)

    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0
    avg_dd = statistics.mean(drawdowns) if drawdowns else 0

    return {
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "max_runup": max_runup,
        "avg_drawdown": avg_dd,
    }


def calculate_profit_factor(gross_profit: float, gross_loss: float) -> float:
    """
    Berechnet den Profit Factor.

    Profit Factor = Gross Profit / Gross Loss

    Args:
        gross_profit: Summe aller Gewinne
        gross_loss: Summe aller Verluste (positiv)

    Returns:
        Profit Factor
    """
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calculate_kelly_criterion(win_probability: float, payoff_ratio: float) -> float:
    """
    Berechnet die optimale Positionsgröße nach Kelly.

    Kelly % = W - (1-W)/R

    Wobei:
    - W = Gewinnwahrscheinlichkeit
    - R = Payoff Ratio (avg win / avg loss)

    Args:
        win_probability: Gewinnwahrscheinlichkeit (0-1)
        payoff_ratio: Verhältnis avg win / avg loss

    Returns:
        Kelly Fraction (0-1), gekürzt auf max 1.0
    """
    if payoff_ratio <= 0:
        return 0.0

    kelly = win_probability - ((1 - win_probability) / payoff_ratio)

    # Clamp zwischen 0 und 1
    return max(0.0, min(1.0, kelly))


def calculate_streaks(pnls: List[float]) -> Dict:
    """
    Berechnet aufeinanderfolgende Gewinn-/Verlustserien.

    Args:
        pnls: Liste der Profits/Losses

    Returns:
        Dict mit max_wins, max_losses, current_streak
    """
    if not pnls:
        return {"max_wins": 0, "max_losses": 0, "current_streak": 0}

    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for pnl in pnls:
        if pnl > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)
        elif pnl < 0:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)
        else:
            # Breakeven unterbricht Serie nicht
            pass

    return {
        "max_wins": max_wins,
        "max_losses": max_losses,
        "current_streak": current_wins if current_wins > 0 else -current_losses,
    }


def calculate_equity_stats(pnls: List[float], initial_capital: float) -> Dict:
    """
    Berechnet Statistiken der Equity-Kurve.

    Args:
        pnls: Liste der Profits/Losses
        initial_capital: Startkapital

    Returns:
        Dict mit volatility, skewness, kurtosis
    """
    if len(pnls) < 3:
        return {"volatility": 0, "skewness": 0, "kurtosis": 0}

    returns = [p / initial_capital for p in pnls]

    # Volatilität
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0

    # Skewness (vereinfacht)
    mean_r = statistics.mean(returns)
    std_r = statistics.stdev(returns) if len(returns) > 1 else 1

    if std_r > 0:
        skewness = sum((r - mean_r) ** 3 for r in returns) / (len(returns) * std_r**3)
        kurtosis = sum((r - mean_r) ** 4 for r in returns) / (len(returns) * std_r**4) - 3
    else:
        skewness = 0
        kurtosis = 0

    return {
        "volatility": volatility,
        "skewness": skewness,
        "kurtosis": kurtosis,
    }


def calculate_risk_of_ruin(
    win_rate: float,
    payoff_ratio: float,
    risk_per_trade: float,
    max_drawdown_pct: float = 50.0,
) -> float:
    """
    Schätzt das Risk of Ruin.

    Vereinfachte Formel für fixed fractional betting.

    Args:
        win_rate: Gewinnwahrscheinlichkeit (0-1)
        payoff_ratio: avg win / avg loss
        risk_per_trade: Risiko pro Trade als Fraktion (z.B. 0.02 = 2%)
        max_drawdown_pct: Drawdown-Level für "Ruin" (z.B. 50%)

    Returns:
        Wahrscheinlichkeit des Ruins (0-1)
    """
    if win_rate <= 0 or win_rate >= 1:
        return 1.0 if win_rate <= 0 else 0.0

    if payoff_ratio <= 0:
        return 1.0

    # Edge
    edge = (win_rate * payoff_ratio) - (1 - win_rate)

    if edge <= 0:
        return 1.0  # Kein Edge = sicherer Ruin

    # Vereinfachte Formel
    # RoR ≈ ((1-edge)/(1+edge))^(ruin_units)
    ruin_units = max_drawdown_pct / (risk_per_trade * 100)

    base = (1 - edge) / (1 + edge)
    if base >= 1:
        return 1.0

    ror = base**ruin_units

    return min(1.0, max(0.0, ror))
