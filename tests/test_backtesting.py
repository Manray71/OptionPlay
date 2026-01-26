# OptionPlay - Backtesting Tests
# ================================

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backtesting import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    TradeResult,
    TradeOutcome,
    ExitReason,
    TradeSimulator,
    PriceSimulator,
    SimulatedTrade,
    PerformanceMetrics,
    calculate_metrics,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
)


# =============================================================================
# BacktestConfig Tests
# =============================================================================

class TestBacktestConfig:
    """Tests für BacktestConfig"""

    def test_default_values(self):
        """Test: Default-Werte sind gesetzt"""
        config = BacktestConfig(
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
        )

        assert config.initial_capital == 100000.0
        assert config.profit_target_pct == 50.0
        assert config.stop_loss_pct == 200.0
        assert config.min_pullback_score == 5.0

    def test_custom_values(self):
        """Test: Custom-Werte werden übernommen"""
        config = BacktestConfig(
            start_date=date(2023, 1, 1),
            end_date=date(2023, 6, 30),
            initial_capital=50000.0,
            profit_target_pct=65.0,
            max_position_pct=3.0,
        )

        assert config.initial_capital == 50000.0
        assert config.profit_target_pct == 65.0
        assert config.max_position_pct == 3.0


# =============================================================================
# BacktestEngine Tests
# =============================================================================

class TestBacktestEngine:
    """Tests für BacktestEngine"""

    @pytest.fixture
    def simple_config(self):
        """Einfache Konfiguration für Tests"""
        return BacktestConfig(
            start_date=date(2023, 1, 1),
            end_date=date(2023, 1, 31),
            initial_capital=100000.0,
            min_pullback_score=3.0,  # Niedrig für mehr Trades
        )

    @pytest.fixture
    def sample_data(self):
        """Beispiel-Historische Daten"""
        # Generiere 30 Tage Daten mit leichtem Aufwärtstrend
        data = []
        base_price = 150.0
        current_date = date(2023, 1, 1)

        for i in range(30):
            if current_date.weekday() < 5:  # Nur Werktage
                price = base_price + i * 0.5  # Leichter Aufwärtstrend
                data.append({
                    "date": current_date.isoformat(),
                    "open": price - 1,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price,
                    "volume": 1000000,
                })
            current_date += timedelta(days=1)

        return {"AAPL": data}

    def test_engine_initialization(self, simple_config):
        """Test: Engine wird korrekt initialisiert"""
        engine = BacktestEngine(simple_config)
        assert engine.config == simple_config

    def test_run_sync_returns_result(self, simple_config, sample_data):
        """Test: run_sync gibt BacktestResult zurück"""
        engine = BacktestEngine(simple_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_data,
        )

        assert isinstance(result, BacktestResult)
        assert result.config == simple_config

    def test_empty_data_returns_empty_result(self, simple_config):
        """Test: Leere Daten geben leeres Ergebnis"""
        engine = BacktestEngine(simple_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data={},
        )

        assert result.total_trades == 0

    def test_result_summary(self, simple_config, sample_data):
        """Test: Result hat summary()-Methode"""
        engine = BacktestEngine(simple_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_data,
        )

        summary = result.summary()
        assert isinstance(summary, str)
        assert "BACKTEST" in summary


# =============================================================================
# TradeResult Tests
# =============================================================================

class TestTradeResult:
    """Tests für TradeResult"""

    @pytest.fixture
    def sample_trade(self):
        """Beispiel-Trade"""
        return TradeResult(
            symbol="AAPL",
            entry_date=date(2023, 1, 15),
            exit_date=date(2023, 2, 1),
            entry_price=150.0,
            exit_price=155.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            net_credit=1.25,
            contracts=2,
            max_profit=250.0,
            max_loss=750.0,
            realized_pnl=125.0,
            outcome=TradeOutcome.PROFIT_TARGET,
            exit_reason=ExitReason.PROFIT_TARGET_HIT,
            dte_at_entry=45,
            dte_at_exit=28,
            hold_days=17,
        )

    def test_pnl_pct(self, sample_trade):
        """Test: P&L % wird korrekt berechnet"""
        # 125 / 250 * 100 = 50%
        assert sample_trade.pnl_pct == 50.0

    def test_is_winner(self, sample_trade):
        """Test: is_winner ist True für positive P&L"""
        assert sample_trade.is_winner is True

    def test_is_winner_false_for_loss(self):
        """Test: is_winner ist False für negative P&L"""
        trade = TradeResult(
            symbol="AAPL",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=150.0,
            exit_price=140.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            net_credit=1.25,
            contracts=1,
            max_profit=125.0,
            max_loss=375.0,
            realized_pnl=-200.0,
            outcome=TradeOutcome.STOP_LOSS,
            exit_reason=ExitReason.STOP_LOSS_HIT,
            dte_at_entry=45,
            dte_at_exit=30,
            hold_days=15,
        )
        assert trade.is_winner is False


# =============================================================================
# TradeSimulator Tests
# =============================================================================

class TestTradeSimulator:
    """Tests für TradeSimulator"""

    @pytest.fixture
    def simulator(self):
        """Standard Simulator"""
        return TradeSimulator()

    def test_simulator_initialization(self, simulator):
        """Test: Simulator wird korrekt initialisiert"""
        assert simulator is not None
        assert "profit_target_pct" in simulator.config

    def test_simulate_trade_profit(self, simulator):
        """Test: Trade mit Profit-Szenario"""
        # Preis steigt -> Short Put bleibt OTM -> Profit
        price_path = [150.0, 152.0, 155.0, 158.0, 160.0]

        trade = simulator.simulate_trade(
            symbol="AAPL",
            entry_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            net_credit=1.25,
            dte=30,
            price_path=price_path,
        )

        assert isinstance(trade, SimulatedTrade)
        assert trade.symbol == "AAPL"

    def test_simulate_trade_loss(self, simulator):
        """Test: Trade mit Verlust-Szenario"""
        # Preis fällt unter Short Strike -> Verlust
        price_path = [150.0, 145.0, 142.0, 138.0, 135.0]

        trade = simulator.simulate_trade(
            symbol="AAPL",
            entry_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            net_credit=1.25,
            dte=30,
            price_path=price_path,
        )

        assert trade.realized_pnl < 0

    def test_spread_width_property(self, simulator):
        """Test: spread_width wird korrekt berechnet"""
        trade = simulator.simulate_trade(
            symbol="TEST",
            entry_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            price_path=[100.0, 100.0],
        )

        assert trade.spread_width == 5.0

    def test_max_profit_calculation(self, simulator):
        """Test: max_profit wird korrekt berechnet"""
        trade = simulator.simulate_trade(
            symbol="TEST",
            entry_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            price_path=[100.0],
            contracts=2,
        )

        # Max profit = credit * 100 * contracts (ohne Slippage)
        # Mit 1% Slippage: 0.99 * 100 * 2 = 198
        assert trade.max_profit > 0


# =============================================================================
# PriceSimulator Tests
# =============================================================================

class TestPriceSimulator:
    """Tests für PriceSimulator"""

    def test_estimate_volatility(self):
        """Test: Volatilität wird geschätzt"""
        prices = [100 + i * 0.1 for i in range(30)]  # Leichter Trend
        vol = PriceSimulator.estimate_volatility(prices)

        assert vol > 0
        assert vol < 1.0  # Sollte unter 100% sein

    def test_estimate_volatility_short_list(self):
        """Test: Kurze Liste gibt Default zurück"""
        prices = [100, 101, 102]
        vol = PriceSimulator.estimate_volatility(prices, window=20)

        assert vol == 0.25  # Default

    def test_generate_price_path(self):
        """Test: Preispfad wird generiert"""
        path = PriceSimulator.generate_price_path(
            start_price=100.0,
            days=30,
            volatility=0.25,
            seed=42,
        )

        assert len(path) == 31  # 30 Tage + Start
        assert path[0] == 100.0
        assert all(p > 0 for p in path)  # Alle Preise positiv

    def test_generate_price_path_reproducible(self):
        """Test: Seed macht Pfad reproduzierbar"""
        path1 = PriceSimulator.generate_price_path(100.0, 10, seed=42)
        path2 = PriceSimulator.generate_price_path(100.0, 10, seed=42)

        assert path1 == path2


# =============================================================================
# Monte Carlo Tests
# =============================================================================

class TestMonteCarlo:
    """Tests für Monte Carlo Simulation"""

    def test_run_monte_carlo(self):
        """Test: Monte Carlo läuft durch"""
        simulator = TradeSimulator()
        results = simulator.run_monte_carlo(
            symbol="AAPL",
            entry_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            net_credit=1.25,
            dte=45,
            num_simulations=100,
        )

        assert "win_rate" in results
        assert "avg_pnl" in results
        assert "outcome_distribution" in results
        assert results["num_simulations"] == 100

    def test_monte_carlo_win_rate_range(self):
        """Test: Win Rate ist zwischen 0-100%"""
        simulator = TradeSimulator()
        results = simulator.run_monte_carlo(
            symbol="TEST",
            entry_price=100.0,
            short_strike=90.0,  # 10% OTM
            long_strike=85.0,
            net_credit=1.00,
            dte=30,
            num_simulations=100,
        )

        assert 0 <= results["win_rate"] <= 100


# =============================================================================
# Performance Metrics Tests
# =============================================================================

class TestPerformanceMetrics:
    """Tests für Performance-Metriken"""

    @pytest.fixture
    def sample_trades(self):
        """Beispiel-Trades als Dict"""
        return [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": -50, "hold_days": 15},
            {"realized_pnl": 150, "hold_days": 8},
            {"realized_pnl": 75, "hold_days": 12},
            {"realized_pnl": -100, "hold_days": 20},
        ]

    def test_calculate_metrics(self, sample_trades):
        """Test: Metriken werden berechnet"""
        metrics = calculate_metrics(sample_trades, initial_capital=10000)

        assert metrics.total_trades == 5
        assert metrics.winning_trades == 3
        assert metrics.losing_trades == 2

    def test_win_rate(self, sample_trades):
        """Test: Win Rate ist korrekt"""
        metrics = calculate_metrics(sample_trades)

        # 3 Gewinner / 5 Trades = 60%
        assert metrics.win_rate == 60.0

    def test_total_pnl(self, sample_trades):
        """Test: Total P&L ist korrekt"""
        metrics = calculate_metrics(sample_trades)

        # 100 + 150 + 75 - 50 - 100 = 175
        assert metrics.total_pnl == 175.0

    def test_profit_factor(self, sample_trades):
        """Test: Profit Factor ist korrekt"""
        metrics = calculate_metrics(sample_trades)

        # Gross Profit = 325, Gross Loss = 150
        # PF = 325 / 150 = 2.166...
        assert abs(metrics.profit_factor - 2.166) < 0.01

    def test_empty_trades(self):
        """Test: Leere Trade-Liste"""
        metrics = calculate_metrics([])

        assert metrics.total_trades == 0
        assert metrics.win_rate == 0
        assert metrics.total_pnl == 0

    def test_metrics_summary(self, sample_trades):
        """Test: Summary wird generiert"""
        metrics = calculate_metrics(sample_trades)
        summary = metrics.summary()

        assert isinstance(summary, str)
        assert "PERFORMANCE" in summary


# =============================================================================
# Sharpe Ratio Tests
# =============================================================================

class TestSharpeRatio:
    """Tests für Sharpe Ratio Berechnung"""

    def test_positive_sharpe(self):
        """Test: Positive Sharpe für konsistente Gewinne"""
        pnls = [100, 120, 90, 110, 105, 115]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)

        assert sharpe > 0

    def test_negative_sharpe(self):
        """Test: Negative Sharpe für konsistente Verluste"""
        pnls = [-100, -120, -90, -110, -105, -115]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)

        assert sharpe < 0

    def test_single_trade(self):
        """Test: Single Trade gibt 0 zurück"""
        sharpe = calculate_sharpe_ratio([100], initial_capital=10000)

        assert sharpe == 0


# =============================================================================
# Max Drawdown Tests
# =============================================================================

class TestMaxDrawdown:
    """Tests für Max Drawdown Berechnung"""

    def test_no_drawdown(self):
        """Test: Keine Drawdown bei konstanten Gewinnen"""
        pnls = [100, 100, 100, 100]
        result = calculate_max_drawdown(pnls, initial_capital=10000)

        assert result["max_drawdown"] == 0

    def test_drawdown_calculation(self):
        """Test: Drawdown wird korrekt berechnet"""
        pnls = [100, 100, -300, 50]  # Peak 10200, Valley 9900
        result = calculate_max_drawdown(pnls, initial_capital=10000)

        assert result["max_drawdown"] == 300

    def test_drawdown_pct(self):
        """Test: Drawdown % wird berechnet"""
        pnls = [1000, -500]  # Peak 11000, Valley 10500
        result = calculate_max_drawdown(pnls, initial_capital=10000)

        # DD = 500, Peak = 11000, DD% = 500/11000 * 100 ≈ 4.5%
        assert result["max_drawdown_pct"] > 0


# =============================================================================
# Profit Factor Tests
# =============================================================================

class TestProfitFactor:
    """Tests für Profit Factor"""

    def test_positive_pf(self):
        """Test: Positiver PF bei mehr Gewinnen"""
        pf = calculate_profit_factor(1000, 500)
        assert pf == 2.0

    def test_zero_loss(self):
        """Test: Infinity bei keinen Verlusten"""
        pf = calculate_profit_factor(1000, 0)
        assert pf == float("inf")

    def test_zero_profit(self):
        """Test: 0 bei keinen Gewinnen"""
        pf = calculate_profit_factor(0, 500)
        assert pf == 0.0


# =============================================================================
# Kelly Criterion Tests
# =============================================================================

class TestKellyCriterion:
    """Tests für Kelly Criterion"""

    def test_kelly_calculation(self):
        """Test: Kelly wird berechnet"""
        from backtesting.metrics import calculate_kelly_criterion

        # Win Rate 60%, Payoff 2:1 -> Kelly = 0.6 - 0.4/2 = 0.4
        kelly = calculate_kelly_criterion(0.6, 2.0)
        assert abs(kelly - 0.4) < 0.01

    def test_kelly_negative(self):
        """Test: Negative Kelly wird auf 0 begrenzt"""
        from backtesting.metrics import calculate_kelly_criterion

        # Win Rate 30%, Payoff 1:1 -> Kelly = 0.3 - 0.7 = -0.4 -> 0
        kelly = calculate_kelly_criterion(0.3, 1.0)
        assert kelly == 0.0


# =============================================================================
# Streak Tests
# =============================================================================

class TestStreaks:
    """Tests für Gewinn-/Verlustserien"""

    def test_max_wins(self):
        """Test: Max consecutive wins"""
        from backtesting.metrics import calculate_streaks

        pnls = [100, 100, 100, -50, 100]
        result = calculate_streaks(pnls)

        assert result["max_wins"] == 3

    def test_max_losses(self):
        """Test: Max consecutive losses"""
        from backtesting.metrics import calculate_streaks

        pnls = [100, -50, -50, -50, -50, 100]
        result = calculate_streaks(pnls)

        assert result["max_losses"] == 4


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests für Randfälle"""

    def test_all_winners(self):
        """Test: Alle Trades sind Gewinner"""
        trades = [{"realized_pnl": 100, "hold_days": 10}] * 10
        metrics = calculate_metrics(trades)

        assert metrics.win_rate == 100.0
        assert metrics.losing_trades == 0

    def test_all_losers(self):
        """Test: Alle Trades sind Verlierer"""
        trades = [{"realized_pnl": -100, "hold_days": 10}] * 10
        metrics = calculate_metrics(trades)

        assert metrics.win_rate == 0.0
        assert metrics.winning_trades == 0

    def test_single_trade(self):
        """Test: Nur ein Trade"""
        trades = [{"realized_pnl": 100, "hold_days": 10}]
        metrics = calculate_metrics(trades)

        assert metrics.total_trades == 1
        assert metrics.win_rate == 100.0

    def test_very_large_pnl(self):
        """Test: Sehr große P&L Werte"""
        trades = [{"realized_pnl": 1000000, "hold_days": 10}]
        metrics = calculate_metrics(trades, initial_capital=100000)

        assert metrics.total_pnl == 1000000
        assert metrics.total_return_pct == 1000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
