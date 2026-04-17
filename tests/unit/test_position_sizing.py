#!/usr/bin/env python3
"""
Tests für das Position Sizing Modul.

Verifiziert:
- Kelly Criterion Berechnung
- VIX-basierte Adjustments
- Reliability-basierte Adjustments
- Score-basierte Adjustments
- Portfolio Risk Limits
- Stop Loss Berechnung
"""

import pytest
from src.risk.position_sizing import (
    PositionSizer,
    PositionSizerConfig,
    PositionSizeResult,
    KellyMode,
    VIXRegime,
    calculate_optimal_position,
    get_recommended_stop_loss,
)


class TestKellyCriterion:
    """Tests für Kelly Criterion Berechnung"""

    def test_kelly_basic(self):
        """Basic Kelly Berechnung (mit erhöhtem Cap für Test)"""
        sizer = PositionSizer(
            account_size=100000,
            config=PositionSizerConfig(kelly_mode=KellyMode.FULL, kelly_cap=0.50),
        )

        # Win Rate 60%, Payoff 1.5:1
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.60,
            avg_win=150,
            avg_loss=100,
        )

        # Kelly = 0.60 - (0.40 / 1.5) = 0.60 - 0.267 = 0.333
        assert 0.30 < kelly < 0.35, f"Kelly calculation wrong: {kelly}"

    def test_kelly_half(self):
        """Half-Kelly sollte halb so groß sein"""
        config = PositionSizerConfig(kelly_mode=KellyMode.HALF)
        sizer = PositionSizer(account_size=100000, config=config)

        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.60,
            avg_win=150,
            avg_loss=100,
        )

        # Half-Kelly = 0.333 / 2 = 0.167
        assert 0.15 < kelly < 0.18, f"Half-Kelly wrong: {kelly}"

    def test_kelly_quarter(self):
        """Quarter-Kelly sollte viertel so groß sein"""
        config = PositionSizerConfig(kelly_mode=KellyMode.QUARTER)
        sizer = PositionSizer(account_size=100000, config=config)

        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.60,
            avg_win=150,
            avg_loss=100,
        )

        # Quarter-Kelly = 0.333 / 4 = 0.083
        assert 0.07 < kelly < 0.10, f"Quarter-Kelly wrong: {kelly}"

    def test_kelly_negative_edge(self):
        """Negativer Edge sollte Kelly = 0 ergeben"""
        sizer = PositionSizer(account_size=100000)

        # Win Rate 40%, Payoff 1:1 = negative edge
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.40,
            avg_win=100,
            avg_loss=100,
        )

        assert kelly == 0.0, f"Negative edge should have 0 Kelly: {kelly}"

    def test_kelly_cap(self):
        """Kelly sollte bei kelly_cap gecapped werden"""
        config = PositionSizerConfig(
            kelly_mode=KellyMode.FULL,
            kelly_cap=0.25,
        )
        sizer = PositionSizer(account_size=100000, config=config)

        # Extrem hoher Edge
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.80,
            avg_win=300,
            avg_loss=100,
        )

        assert kelly == 0.25, f"Kelly should be capped at 25%: {kelly}"


class TestVIXAdjustments:
    """Tests für VIX-basierte Adjustments"""

    def test_vix_regime_low(self):
        """VIX < 15 = LOW regime"""
        sizer = PositionSizer(account_size=100000)
        regime = sizer.get_vix_regime(12)
        assert regime == VIXRegime.LOW

    def test_vix_regime_normal(self):
        """VIX 15-20 = NORMAL regime"""
        sizer = PositionSizer(account_size=100000)
        regime = sizer.get_vix_regime(18)
        assert regime == VIXRegime.NORMAL

    def test_vix_regime_elevated(self):
        """VIX 20-30 = ELEVATED regime"""
        sizer = PositionSizer(account_size=100000)
        regime = sizer.get_vix_regime(25)
        assert regime == VIXRegime.ELEVATED

    def test_vix_regime_high(self):
        """VIX 30-35 = HIGH regime"""
        sizer = PositionSizer(account_size=100000)
        regime = sizer.get_vix_regime(32)
        assert regime == VIXRegime.HIGH

    def test_vix_regime_extreme(self):
        """VIX > 40 = EXTREME regime"""
        sizer = PositionSizer(account_size=100000)
        regime = sizer.get_vix_regime(50)
        assert regime == VIXRegime.EXTREME

    def test_vix_adjustment_scales(self):
        """Höhere VIX = kleinerer Adjustment (kleinere Positionen)"""
        sizer = PositionSizer(account_size=100000)

        adj_low = sizer.get_vix_adjustment(12)
        adj_normal = sizer.get_vix_adjustment(18)
        adj_elevated = sizer.get_vix_adjustment(25)
        adj_high = sizer.get_vix_adjustment(35)
        adj_extreme = sizer.get_vix_adjustment(50)

        # Sollte absteigend sein
        assert adj_low >= adj_normal
        assert adj_normal >= adj_elevated
        assert adj_elevated >= adj_high
        assert adj_high >= adj_extreme

        # Extreme sollte stark reduziert sein
        assert adj_extreme < 0.5


class TestReliabilityAdjustments:
    """Tests für Reliability-basierte Adjustments"""

    def test_grade_a_full_size(self):
        """Grade A sollte volle Größe erlauben"""
        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_reliability_adjustment("A")
        assert adj == 1.0

    def test_grade_f_no_trade(self):
        """Grade F sollte 0 ergeben (kein Trade)"""
        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_reliability_adjustment("F")
        assert adj == 0.0

    def test_grades_descending(self):
        """Grades sollten absteigend sein: A > B > C > D > F"""
        sizer = PositionSizer(account_size=100000)

        adj_a = sizer.get_reliability_adjustment("A")
        adj_b = sizer.get_reliability_adjustment("B")
        adj_c = sizer.get_reliability_adjustment("C")
        adj_d = sizer.get_reliability_adjustment("D")
        adj_f = sizer.get_reliability_adjustment("F")

        assert adj_a > adj_b > adj_c > adj_d > adj_f

    def test_none_grade_conservative(self):
        """None Grade sollte konservativ sein"""
        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_reliability_adjustment(None)

        # Sollte zwischen C und D sein
        assert 0.5 < adj < 1.0


class TestScoreAdjustments:
    """Tests für Score-basierte Adjustments"""

    def test_below_min_score_no_trade(self):
        """Score unter Minimum = kein Trade"""
        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_score_adjustment(4.0)  # Default min ist 5.0
        assert adj == 0.0

    def test_high_score_full_size(self):
        """Hoher Score = volle Größe"""
        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_score_adjustment(9.0)  # Über Threshold
        assert adj == 1.0

    def test_mid_score_partial(self):
        """Mittlerer Score = teilweise Größe"""
        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_score_adjustment(6.5)

        # Sollte zwischen 0.5 und 1.0 sein
        assert 0.5 < adj < 1.0


class TestPositionSizeCalculation:
    """Tests für die Gesamtberechnung"""

    def test_basic_calculation(self):
        """Grundlegende Position Size Berechnung"""
        sizer = PositionSizer(account_size=100000)

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=20,
            reliability_grade="B",
        )

        assert isinstance(result, PositionSizeResult)
        assert result.contracts >= 0
        assert result.capital_at_risk >= 0
        assert result.kelly_fraction >= 0

    def test_respects_max_risk_per_trade(self):
        """Position sollte max_risk_per_trade respektieren"""
        config = PositionSizerConfig(max_risk_per_trade=0.02)
        sizer = PositionSizer(account_size=100000, config=config)

        result = sizer.calculate_position_size(
            max_loss_per_contract=100,  # Kleine Contracts
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=18,
            reliability_grade="A",
        )

        # Max risk = 2% von 100k = $2000
        assert result.capital_at_risk <= 2000

    def test_respects_portfolio_limit(self):
        """Position sollte Portfolio-Limit respektieren"""
        sizer = PositionSizer(
            account_size=100000,
            current_exposure=20000,  # Bereits 20% exposed
        )

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=18,
            reliability_grade="A",
        )

        # Remaining capacity: 25% - 20% = 5% = $5000
        assert result.capital_at_risk <= 5000

    def test_high_vix_reduces_size(self):
        """Hohe VIX sollte kleinere Position ergeben"""
        sizer = PositionSizer(account_size=100000)

        result_low_vix = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=15,
            reliability_grade="A",
        )

        result_high_vix = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=40,
            reliability_grade="A",
        )

        assert result_high_vix.contracts <= result_low_vix.contracts

    def test_poor_reliability_reduces_size(self):
        """Schlechte Reliability sollte kleinere Position ergeben"""
        sizer = PositionSizer(account_size=100000)

        result_good = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=18,
            reliability_grade="A",
        )

        result_bad = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=8.0,
            vix_level=18,
            reliability_grade="D",
        )

        assert result_bad.contracts <= result_good.contracts


class TestStopLossCalculation:
    """Tests für Stop Loss Berechnung"""

    def test_default_stop_loss(self):
        """Default Stop Loss sollte 100% sein (nicht 200%!)"""
        sizer = PositionSizer(account_size=100000)

        result = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=20,
        )

        # Default ist 100% = 1:1 Risk/Reward
        assert result['stop_loss_pct'] <= 100

    def test_high_vix_tighter_stop(self):
        """Hohe VIX sollte engeren Stop ergeben"""
        sizer = PositionSizer(account_size=100000)

        result_normal = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=18,
        )

        result_high = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=40,
        )

        assert result_high['stop_loss_pct'] <= result_normal['stop_loss_pct']

    def test_stop_loss_never_exceeds_max_loss(self):
        """Stop Loss sollte nie Spread Width übersteigen"""
        sizer = PositionSizer(account_size=100000)

        result = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=18,
        )

        max_possible_loss = 5.0 - 1.50  # Spread Width - Credit
        assert result['max_loss'] <= max_possible_loss


class TestConvenienceFunctions:
    """Tests für Convenience Functions"""

    def test_calculate_optimal_position(self):
        """calculate_optimal_position sollte funktionieren"""
        result = calculate_optimal_position(
            account_size=100000,
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            vix_level=20,
            signal_score=8.0,
            reliability_grade="B",
        )

        assert isinstance(result, PositionSizeResult)
        assert result.contracts >= 0

    def test_get_recommended_stop_loss(self):
        """get_recommended_stop_loss sollte validen Wert liefern"""
        stop_pct = get_recommended_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=20,
        )

        assert 0 < stop_pct <= 150
        assert stop_pct <= 100  # Sollte nicht über 100% sein


class TestEdgeCases:
    """Tests für Grenzfälle"""

    def test_zero_max_loss(self):
        """Zero max_loss sollte 0 Contracts ergeben"""
        sizer = PositionSizer(account_size=100000)

        result = sizer.calculate_position_size(
            max_loss_per_contract=0,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )

        assert result.contracts == 0

    def test_very_small_account(self):
        """Sehr kleiner Account sollte funktionieren"""
        sizer = PositionSizer(account_size=1000)

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )

        # Kann 0 sein wenn Account zu klein
        assert result.contracts >= 0

    def test_portfolio_full(self):
        """Volles Portfolio sollte 0 Contracts ergeben"""
        sizer = PositionSizer(
            account_size=100000,
            current_exposure=25000,  # Voll bei 25% limit
        )

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )

        assert result.contracts == 0
        # Kann verschiedene Gründe haben bei vollem Portfolio
        assert result.limiting_factor in ["portfolio_risk_full", "kelly_too_low", "insufficient_edge"]


class TestPositionSizerConfigFromYaml:
    """B.3.3: PositionSizerConfig.from_yaml() eliminates dataclass-vs-YAML drift."""

    def test_position_sizer_config_from_yaml_reads_max_risk_per_trade(self):
        """from_yaml() liest max_risk_per_trade_pct aus trading.yaml (aktuell 2.5%)."""
        from src.constants.trading_rules import SIZING_MAX_RISK_PER_TRADE_PCT

        config = PositionSizerConfig.from_yaml()
        expected_fraction = SIZING_MAX_RISK_PER_TRADE_PCT / 100.0
        assert config.max_risk_per_trade == pytest.approx(expected_fraction)

    def test_position_sizer_config_from_yaml_reads_max_portfolio_allocation(self):
        """from_yaml() liest max_portfolio_allocation aus trading.yaml (aktuell 50%)."""
        from src.constants.trading_rules import SIZING_MAX_PORTFOLIO_ALLOCATION

        config = PositionSizerConfig.from_yaml()
        expected_fraction = SIZING_MAX_PORTFOLIO_ALLOCATION / 100.0
        assert config.max_portfolio_allocation == pytest.approx(expected_fraction)

    def test_position_sizer_uses_yaml_value_when_constructed_via_from_yaml(self):
        """Regression: PositionSizer ohne explizite Config verwendet YAML-Werte.

        Verifiziert dass trading.yaml-Änderungen tatsächlich greifen,
        nicht stillschweigend durch Dataclass-Defaults überschrieben werden.
        """
        from src.constants.trading_rules import SIZING_MAX_RISK_PER_TRADE_PCT

        sizer = PositionSizer(account_size=100_000)  # kein config-Argument
        expected_fraction = SIZING_MAX_RISK_PER_TRADE_PCT / 100.0
        assert sizer.config.max_risk_per_trade == pytest.approx(expected_fraction)

    def test_position_sizer_config_from_yaml_preserves_other_defaults(self):
        """from_yaml() überschreibt nur bekannte YAML-Felder; andere Defaults bleiben."""
        config = PositionSizerConfig.from_yaml()
        default = PositionSizerConfig()

        # Kelly-Settings sollten unverändert sein
        assert config.kelly_mode == default.kelly_mode
        assert config.kelly_cap == default.kelly_cap
        assert config.max_portfolio_risk == default.max_portfolio_risk


class TestMaxPortfolioAllocation:
    """B.3.2-light: Notional-basierte max_portfolio_allocation Schranke.

    Hintergrund: Echte Margin (IBKR reqAccountSummary) steht erst in B.3.4 zur Verfügung.
    Bis dahin dient der Notional-Wert (spread_width * 100 * contracts) als konservative
    Approximation. Echte Margin bindet ca. 70-80% des Notionals.
    """

    def test_position_size_capped_by_max_portfolio_allocation(self):
        """Wenn Notional-Kapazität begrenzt ist, wird contracts entsprechend gedeckelt.

        Setup: Account 100k, Allocation 50% = 50k Notional erlaubt.
        current_notional 48k → nur 2k Kapazität.
        spread_width=10 → 10*100=1000 Notional/Contract → max 2 contracts by notional.
        Kelly würde mehr erlauben → Notional ist der bindende Faktor.
        """
        config = PositionSizerConfig(max_portfolio_allocation=0.50)
        sizer = PositionSizer(account_size=100_000, config=config)

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.70,
            avg_win=200,
            avg_loss=100,
            signal_score=8.0,
            vix_level=15.0,
            current_notional=48_000.0,  # 48k belegt → nur 2k Kapazität
            spread_width=10.0,          # 1000 Notional/Contract → max 2 by notional
        )

        assert result.contracts <= 2
        assert result.limiting_factor == "max_portfolio_allocation"

    def test_position_size_zero_when_allocation_full(self):
        """Keine neuen Contracts wenn Notional-Kapazität erschöpft."""
        config = PositionSizerConfig(max_portfolio_allocation=0.50)
        sizer = PositionSizer(account_size=100_000, config=config)

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.70,
            avg_win=200,
            avg_loss=100,
            signal_score=8.0,
            vix_level=15.0,
            current_notional=50_000.0,  # 100% der erlaubten Allokation bereits belegt
            spread_width=10.0,
        )

        assert result.contracts == 0
        assert result.limiting_factor == "max_portfolio_allocation"

    def test_position_size_normal_when_allocation_low(self):
        """Keine Einschränkung wenn Notional-Kapazität ausreichend vorhanden."""
        config = PositionSizerConfig(max_portfolio_allocation=0.50)
        sizer = PositionSizer(account_size=100_000, config=config)

        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.70,
            avg_win=200,
            avg_loss=100,
            signal_score=8.0,
            vix_level=15.0,
            current_notional=0.0,   # Kein Notional belegt
            spread_width=5.0,       # Enger Spread
        )

        # Bei freier Kapazität soll max_portfolio_allocation NICHT limitieren
        assert result.limiting_factor != "max_portfolio_allocation"
        assert result.contracts > 0

    def test_no_notional_constraint_without_spread_width(self):
        """Ohne spread_width Parameter greift die Notional-Schranke nicht (backward compat).

        Dies ist ein Approximations-Test: Der Parameter ist optional, damit bestehende
        Aufrufer ohne spread_width weiterhin funktionieren (bis B.3.4 IBKR Margin).
        """
        config = PositionSizerConfig(max_portfolio_allocation=0.50)
        sizer = PositionSizer(account_size=100_000, config=config)

        # current_notional sehr hoch, aber spread_width=0 (default) → keine Notional-Prüfung
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.70,
            avg_win=200,
            avg_loss=100,
            signal_score=8.0,
            vix_level=15.0,
            # spread_width nicht angegeben → kein Notional-Check
        )

        assert result.limiting_factor != "max_portfolio_allocation"


class TestBuyingPowerLimit:
    """Tests für B.3.5 — SIZING_MAX_BUYING_POWER_PCT Obergrenze."""

    def test_position_size_capped_by_buying_power(self):
        """Contracts werden durch 5% Buying-Power-Limit gedeckelt."""
        # Account $100k, 5% BP = $5k, spread_width $5 → $500 pro Kontrakt → max 10 Kontrakte
        config = PositionSizerConfig(max_buying_power_pct=0.05, max_portfolio_allocation=0.99)
        sizer = PositionSizer(account_size=100_000, config=config)

        result = sizer.calculate_position_size(
            max_loss_per_contract=100,
            win_rate=0.85,
            avg_win=300,
            avg_loss=100,
            signal_score=9.0,
            vix_level=15.0,
            spread_width=5.0,
            contracts_multiplier=100,
        )

        assert result.contracts <= 10  # $5k / ($5 × 100) = 10
        assert result.limiting_factor == "max_buying_power"

    def test_buying_power_from_yaml(self):
        """from_yaml() übernimmt SIZING_MAX_BUYING_POWER_PCT (5%)."""
        config = PositionSizerConfig.from_yaml()
        assert config.max_buying_power_pct == pytest.approx(0.05)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
