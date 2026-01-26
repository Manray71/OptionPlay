# OptionPlay - Spread Analyzer Tests
# ====================================
# Tests für spread_analyzer.py

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spread_analyzer import (
    SpreadAnalyzer,
    BullPutSpreadParams,
    SpreadAnalysis,
    SpreadRiskLevel,
    PnLScenario,
    analyze_bull_put_spread,
)


class TestBullPutSpreadParams:
    """Tests für BullPutSpreadParams Validierung"""

    def test_valid_params(self):
        """Test: Gültige Parameter werden akzeptiert"""
        params = BullPutSpreadParams(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45
        )
        assert params.symbol == "AAPL"
        assert params.short_strike == 175.0
        assert params.long_strike == 170.0

    def test_invalid_short_strike_below_long(self):
        """Test: Short Strike unter Long Strike wird abgelehnt"""
        with pytest.raises(ValueError, match="Short Strike muss höher"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=90.0,
                long_strike=95.0,  # Long > Short = ungültig
                net_credit=1.00,
                dte=30
            )

    def test_invalid_short_strike_equals_long(self):
        """Test: Short Strike gleich Long Strike wird abgelehnt"""
        with pytest.raises(ValueError, match="Short Strike muss höher"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=90.0,
                long_strike=90.0,  # Gleich = ungültig
                net_credit=1.00,
                dte=30
            )

    def test_invalid_negative_credit(self):
        """Test: Negativer Credit wird abgelehnt"""
        with pytest.raises(ValueError, match="Net Credit muss positiv"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=95.0,
                long_strike=90.0,
                net_credit=-0.50,  # Negativ = ungültig
                dte=30
            )

    def test_invalid_zero_credit(self):
        """Test: Zero Credit wird abgelehnt"""
        with pytest.raises(ValueError, match="Net Credit muss positiv"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=95.0,
                long_strike=90.0,
                net_credit=0.0,  # Zero = ungültig
                dte=30
            )

    def test_invalid_short_strike_above_current(self):
        """Test: Short Strike über aktuellem Preis wird abgelehnt (ITM)"""
        with pytest.raises(ValueError, match="unter dem aktuellen Preis"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=105.0,  # Über Current = ITM = ungültig
                long_strike=100.0,
                net_credit=2.00,
                dte=30
            )


class TestSpreadAnalyzerBasics:
    """Grundlegende Tests für SpreadAnalyzer"""

    @pytest.fixture
    def analyzer(self):
        """Standard Analyzer"""
        return SpreadAnalyzer()

    @pytest.fixture
    def sample_params(self):
        """Beispiel Bull-Put-Spread"""
        return BullPutSpreadParams(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
            contracts=1
        )

    def test_analyzer_initialization(self, analyzer):
        """Test: Analyzer wird korrekt initialisiert"""
        assert analyzer is not None
        assert analyzer.config is not None

    def test_analyze_returns_analysis(self, analyzer, sample_params):
        """Test: analyze gibt SpreadAnalysis zurück"""
        result = analyzer.analyze(sample_params)
        assert isinstance(result, SpreadAnalysis)

    def test_analysis_has_all_fields(self, analyzer, sample_params):
        """Test: Analyse hat alle Pflichtfelder"""
        result = analyzer.analyze(sample_params)

        # Basis-Metriken
        assert result.symbol == "AAPL"
        assert result.current_price == 180.0
        assert result.short_strike == 175.0
        assert result.long_strike == 170.0
        assert result.spread_width == 5.0
        assert result.net_credit == 1.50

        # Profit/Loss
        assert result.max_profit is not None
        assert result.max_loss is not None
        assert result.break_even is not None
        assert result.risk_reward_ratio is not None

        # Distanzen
        assert result.distance_to_short_strike is not None
        assert result.distance_to_break_even is not None

        # Wahrscheinlichkeiten
        assert result.prob_profit is not None
        assert result.prob_max_profit is not None
        assert result.expected_value is not None

        # Risiko
        assert result.risk_level is not None
        assert isinstance(result.risk_level, SpreadRiskLevel)


class TestProfitLossCalculations:
    """Tests für Profit/Loss Berechnungen"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_max_profit_calculation(self, analyzer):
        """Test: Max Profit = Credit * 100 * Contracts"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=2
        )
        result = analyzer.analyze(params)

        # Max Profit = $1.00 * 100 * 2 = $200
        assert result.max_profit == 200.0

    def test_max_loss_calculation(self, analyzer):
        """Test: Max Loss = (Width - Credit) * 100 * Contracts"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=2
        )
        result = analyzer.analyze(params)

        # Max Loss = ($5.00 - $1.00) * 100 * 2 = $800
        assert result.max_loss == 800.0

    def test_break_even_calculation(self, analyzer):
        """Test: Break-Even = Short Strike - Credit"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        # Break-Even = $95.00 - $1.50 = $93.50
        assert result.break_even == 93.50

    def test_risk_reward_ratio(self, analyzer):
        """Test: Risk/Reward = Max Profit / Max Loss"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.25,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        # Max Profit = $125, Max Loss = $375
        # R/R = 125 / 375 = 0.333...
        expected_rr = 125.0 / 375.0
        assert abs(result.risk_reward_ratio - expected_rr) < 0.01

    def test_credit_to_width_ratio(self, analyzer):
        """Test: Credit/Width Ratio"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.25,  # 25% von $5 Width
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        # $1.25 / $5.00 = 25%
        assert result.credit_to_width_ratio == 25.0


class TestDistanceCalculations:
    """Tests für Distanz-Berechnungen"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_distance_to_short_strike(self, analyzer):
        """Test: Distanz zum Short Strike in %"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,  # 10% unter Current
            long_strike=85.0,
            net_credit=1.00,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        # Distanz = (100 - 90) / 100 * 100 = 10%
        assert abs(result.distance_to_short_strike - 10.0) < 0.1

    def test_distance_to_break_even(self, analyzer):
        """Test: Distanz zum Break-Even in %"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=2.00,  # BE = 88
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        # BE = 90 - 2 = 88, Distanz = (100 - 88) / 100 * 100 = 12%
        assert abs(result.distance_to_break_even - 12.0) < 0.1


class TestPnLAtPrice:
    """Tests für P&L bei verschiedenen Preisen"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    @pytest.fixture
    def params(self):
        return BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1
        )

    def test_pnl_above_short_strike(self, analyzer, params):
        """Test: Preis über Short Strike = Max Profit"""
        pnl_per, pnl_total, status = analyzer.calculate_pnl_at_price(params, 96.0)

        assert pnl_per == 150.0  # $1.50 * 100
        assert pnl_total == 150.0
        assert status == "max_profit"

    def test_pnl_at_short_strike(self, analyzer, params):
        """Test: Preis am Short Strike = Max Profit"""
        pnl_per, pnl_total, status = analyzer.calculate_pnl_at_price(params, 95.0)

        assert pnl_per == 150.0
        assert status == "max_profit"

    def test_pnl_below_long_strike(self, analyzer, params):
        """Test: Preis unter Long Strike = Max Loss"""
        pnl_per, pnl_total, status = analyzer.calculate_pnl_at_price(params, 88.0)

        # Max Loss = (5 - 1.5) * 100 = 350
        assert pnl_per == -350.0
        assert status == "max_loss"

    def test_pnl_at_break_even(self, analyzer, params):
        """Test: Preis am Break-Even = 0"""
        break_even = 93.50  # 95 - 1.5
        pnl_per, pnl_total, status = analyzer.calculate_pnl_at_price(params, break_even)

        assert abs(pnl_per) < 1  # ~0
        assert status == "profit" or status == "loss"

    def test_pnl_between_strikes_profit(self, analyzer, params):
        """Test: Preis zwischen Strikes im Profit-Bereich"""
        pnl_per, pnl_total, status = analyzer.calculate_pnl_at_price(params, 94.0)

        # Intrinsic Short = 95 - 94 = 1
        # P&L = (1.50 - 1.00) * 100 = $50
        assert pnl_per == 50.0
        assert status == "profit"

    def test_pnl_between_strikes_loss(self, analyzer, params):
        """Test: Preis zwischen Strikes im Loss-Bereich"""
        pnl_per, pnl_total, status = analyzer.calculate_pnl_at_price(params, 91.0)

        # Intrinsic Short = 95 - 91 = 4
        # P&L = (1.50 - 4.00) * 100 = -$250
        assert pnl_per == -250.0
        assert status == "loss"


class TestExitPriceCalculation:
    """Tests für Exit-Preis Berechnung"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    @pytest.fixture
    def params(self):
        return BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=2.00,
            dte=45,
            contracts=1
        )

    def test_exit_50_percent_profit(self, analyzer, params):
        """Test: Exit bei 50% Profit"""
        exit_price = analyzer.calculate_exit_price(params, 50)

        # 50% Profit = $1.00 behalten, Exit bei $1.00
        assert exit_price == 1.00

    def test_exit_75_percent_profit(self, analyzer, params):
        """Test: Exit bei 75% Profit"""
        exit_price = analyzer.calculate_exit_price(params, 75)

        # 75% Profit = $1.50 behalten, Exit bei $0.50
        assert exit_price == 0.50

    def test_exit_100_percent_profit(self, analyzer, params):
        """Test: Exit bei 100% Profit = 0"""
        exit_price = analyzer.calculate_exit_price(params, 100)

        assert exit_price == 0.0


class TestRiskLevelAssessment:
    """Tests für Risiko-Level Bewertung"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_low_risk_spread(self, analyzer):
        """Test: Niedriges Risiko bei gutem Credit/Width"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=85.0,  # 15% OTM
            long_strike=80.0,
            net_credit=0.80,  # 16% von Width
            dte=60,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert result.risk_level in [SpreadRiskLevel.LOW, SpreadRiskLevel.MODERATE]

    def test_high_risk_spread(self, analyzer):
        """Test: Hohes Risiko bei schlechtem Credit/Width und kurzer DTE"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=97.0,  # 3% OTM
            long_strike=92.0,
            net_credit=2.00,  # 40% von Width
            dte=10,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert result.risk_level in [SpreadRiskLevel.HIGH, SpreadRiskLevel.VERY_HIGH]


class TestScenarioGeneration:
    """Tests für Szenario-Generierung"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_scenarios_are_generated(self, analyzer):
        """Test: Szenarien werden generiert"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert len(result.scenarios) > 0
        assert all(isinstance(s, PnLScenario) for s in result.scenarios)

    def test_scenarios_include_key_prices(self, analyzer):
        """Test: Szenarien enthalten wichtige Preispunkte"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        prices = [s.price for s in result.scenarios]

        # Sollte Short Strike und Long Strike enthalten
        assert any(abs(p - 95.0) < 0.5 for p in prices)  # Short Strike
        assert any(abs(p - 90.0) < 0.5 for p in prices)  # Long Strike

    def test_scenarios_sorted_by_price(self, analyzer):
        """Test: Szenarien sind nach Preis sortiert"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        prices = [s.price for s in result.scenarios]
        assert prices == sorted(prices, reverse=True)


class TestWarningsAndRecommendations:
    """Tests für Warnungen und Empfehlungen"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_warning_for_low_buffer(self, analyzer):
        """Test: Warnung bei niedrigem Buffer"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=97.0,  # Nur 3% OTM
            long_strike=92.0,
            net_credit=1.50,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        # Sollte Warnung über geringen Puffer enthalten
        assert any("Puffer" in w or "Buffer" in w for w in result.warnings)

    def test_warning_for_short_dte(self, analyzer):
        """Test: Warnung bei kurzer DTE"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.50,
            dte=10,  # Sehr kurz
            contracts=1
        )
        result = analyzer.analyze(params)

        # Sollte Warnung über kurze Laufzeit enthalten
        assert any("Laufzeit" in w or "Gamma" in w for w in result.warnings)

    def test_recommendations_include_profit_target(self, analyzer):
        """Test: Empfehlungen enthalten Profit-Target"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.50,
            dte=45,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert any("Profit" in r or "Target" in r for r in result.recommendations)

    def test_recommendations_include_stop_loss(self, analyzer):
        """Test: Empfehlungen enthalten Stop-Loss"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.50,
            dte=45,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert any("Stop" in r for r in result.recommendations)


class TestGreeksCalculation:
    """Tests für Greeks-Berechnung"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_net_delta_with_deltas(self, analyzer):
        """Test: Net Delta wird berechnet wenn Deltas vorhanden"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1,
            short_delta=-0.30,
            long_delta=-0.15
        )
        result = analyzer.analyze(params)

        assert result.net_delta is not None
        # Net Delta = -(-0.30) + (-0.15) = 0.30 - 0.15 = 0.15
        assert abs(result.net_delta - 0.15) < 0.01

    def test_theta_per_day_with_theta(self, analyzer):
        """Test: Theta/Tag wird berechnet wenn Theta vorhanden"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=2,
            short_theta=0.05  # $5/Tag pro Contract
        )
        result = analyzer.analyze(params)

        assert result.net_theta is not None
        assert result.theta_per_day is not None

    def test_greeks_calculated_via_black_scholes(self, analyzer):
        """Test: Greeks werden via Black-Scholes berechnet wenn keine Input-Greeks"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1
            # Keine Delta/Theta - Black-Scholes wird verwendet
        )
        result = analyzer.analyze(params)

        # Mit Black-Scholes Integration werden Greeks automatisch berechnet
        assert result.net_delta is not None
        assert result.theta_per_day is not None
        # Bull-Put-Spread hat positives Delta (bullish)
        assert result.net_delta > 0
        # Credit Spread hat positives Theta (verdient am Zeitwertverfall)
        assert result.theta_per_day > 0


class TestConvenienceFunction:
    """Tests für analyze_bull_put_spread Convenience-Funktion"""

    def test_analyze_bull_put_spread(self):
        """Test: Convenience-Funktion funktioniert"""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
            contracts=2
        )

        assert isinstance(result, SpreadAnalysis)
        assert result.symbol == "AAPL"
        assert result.contracts == 2
        assert result.max_profit == 300.0  # 1.50 * 100 * 2

    def test_analyze_with_delta(self):
        """Test: Convenience-Funktion mit Delta"""
        result = analyze_bull_put_spread(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            short_delta=-0.25
        )

        assert result.prob_max_profit > 0


class TestSummaryOutput:
    """Tests für formatierte Ausgabe"""

    def test_summary_is_string(self):
        """Test: summary() gibt String zurück"""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45
        )
        summary = result.summary()

        assert isinstance(summary, str)
        assert len(summary) > 100

    def test_summary_contains_key_info(self):
        """Test: Summary enthält wichtige Informationen"""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45
        )
        summary = result.summary()

        assert "AAPL" in summary
        assert "175" in summary
        assert "170" in summary
        assert "Max Profit" in summary or "Profit" in summary

    def test_to_dict(self):
        """Test: to_dict() gibt Dict zurück"""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45
        )
        data = result.to_dict()

        assert isinstance(data, dict)
        assert data["symbol"] == "AAPL"
        assert data["short_strike"] == 175.0
        assert "scenarios" in data
        assert isinstance(data["scenarios"], list)


class TestEdgeCases:
    """Tests für Randfälle"""

    @pytest.fixture
    def analyzer(self):
        return SpreadAnalyzer()

    def test_very_wide_spread(self, analyzer):
        """Test: Sehr breiter Spread"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=500.0,
            short_strike=400.0,
            long_strike=350.0,  # $50 Spread
            net_credit=15.00,
            dte=60,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert result.spread_width == 50.0
        assert result.max_profit == 1500.0

    def test_very_narrow_spread(self, analyzer):
        """Test: Sehr enger Spread"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=50.0,
            short_strike=45.0,
            long_strike=44.0,  # $1 Spread
            net_credit=0.25,
            dte=30,
            contracts=1
        )
        result = analyzer.analyze(params)

        assert result.spread_width == 1.0
        assert result.max_profit == 25.0
        assert result.max_loss == 75.0

    def test_multiple_contracts(self, analyzer):
        """Test: Mehrere Contracts"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=10
        )
        result = analyzer.analyze(params)

        assert result.contracts == 10
        assert result.max_profit == 1000.0  # $1 * 100 * 10
        assert result.max_loss == 4000.0   # $4 * 100 * 10

    def test_long_dte(self, analyzer):
        """Test: Lange Laufzeit"""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=2.00,
            dte=180,  # 6 Monate
            contracts=1
        )
        result = analyzer.analyze(params)

        assert result.dte == 180


class TestCustomConfig:
    """Tests für benutzerdefinierte Konfiguration"""

    def test_custom_risk_thresholds(self):
        """Test: Benutzerdefinierte Risiko-Schwellen"""
        custom_config = {
            "low_risk_max_credit_pct": 15,
            "moderate_risk_max_credit_pct": 25,
            "high_risk_max_credit_pct": 35,
        }
        analyzer = SpreadAnalyzer(config=custom_config)

        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=0.60,  # 12% von $5 Width
            dte=45,
            contracts=1
        )
        result = analyzer.analyze(params)

        # Mit 12% Credit sollte es LOW sein (< 15%)
        assert result.risk_level == SpreadRiskLevel.LOW

    def test_custom_profit_targets(self):
        """Test: Benutzerdefinierte Profit-Targets"""
        custom_config = {
            "profit_target_conservative": 40,
            "profit_target_standard": 55,
        }
        analyzer = SpreadAnalyzer(config=custom_config)

        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=2.00,
            dte=60,  # > 45 -> conservative target
            contracts=1
        )
        result = analyzer.analyze(params)

        # Empfehlung sollte 40% erwähnen
        assert any("40%" in r for r in result.recommendations)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
