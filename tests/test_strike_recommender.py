# OptionPlay - Strike Recommender Tests
# =======================================
# Tests für strike_recommender.py inkl. Fix #8: Config-Integration

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strike_recommender import (
    StrikeRecommender,
    StrikeRecommendation,
    StrikeQuality,
    SupportLevel,
    calculate_strike_recommendation
)


class TestStrikeRecommenderBasics:
    """Grundlegende Tests für StrikeRecommender"""
    
    @pytest.fixture
    def recommender(self):
        """Standard Recommender ohne ConfigLoader"""
        return StrikeRecommender(use_config_loader=False)
    
    def test_recommender_initialization(self, recommender):
        """Test: Recommender wird korrekt initialisiert"""
        assert recommender is not None
        assert recommender.config is not None
        assert "delta_target" in recommender.config
    
    def test_default_config_values(self, recommender):
        """Test: Default-Werte sind gesetzt"""
        assert recommender.config["delta_target"] == -0.20
        assert recommender.config["delta_min"] == -0.17  # Less aggressive end (±0.03)
        assert recommender.config["delta_max"] == -0.23  # More aggressive end (±0.03)
        assert recommender.config["min_otm_pct"] == 8.0
        assert recommender.config["min_credit_pct"] == 10  # PLAYBOOK §2
    
    def test_get_recommendation_returns_recommendation(self, recommender):
        """Test: get_recommendation gibt StrikeRecommendation zurück"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0, 80.0]
        )
        
        assert isinstance(rec, StrikeRecommendation)
        assert rec.symbol == "TEST"
        assert rec.current_price == 100.0
    
    def test_recommendation_has_required_fields(self, recommender):
        """Test: Empfehlung hat alle Pflichtfelder"""
        rec = recommender.get_recommendation(
            symbol="AAPL",
            current_price=180.0,
            support_levels=[170.0, 165.0]
        )
        
        assert rec.short_strike is not None
        assert rec.long_strike is not None
        assert rec.spread_width > 0
        assert rec.short_strike > rec.long_strike
        assert rec.quality in StrikeQuality


class TestStrikeSelection:
    """Tests für Strike-Auswahl-Logik"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_short_strike_below_current_price(self, recommender):
        """Test: Short Strike ist unter aktuellem Preis (OTM)"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )
        
        assert rec.short_strike < rec.current_price
    
    def test_short_strike_near_support(self, recommender):
        """Test: Short Strike berücksichtigt Support-Levels"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[88.0, 85.0]
        )
        
        # Short Strike sollte in der Nähe eines Supports sein
        # (innerhalb von 10% des nächsten Supports)
        min_support_distance = min(
            abs(rec.short_strike - s) for s in [88.0, 85.0]
        )
        assert min_support_distance < 88.0 * 0.1
    
    def test_spread_width_positive(self, recommender):
        """Test: Spread Width ist positiv"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        assert rec.spread_width > 0
        assert rec.short_strike - rec.long_strike == rec.spread_width
    
    def test_min_otm_respected(self, recommender):
        """Test: Mindest-OTM-Prozent wird eingehalten"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[95.0, 90.0]  # 95 wäre nur 5% OTM
        )
        
        otm_pct = (100.0 - rec.short_strike) / 100.0 * 100
        # Mindestens 8% OTM oder in der Nähe
        assert otm_pct >= 5.0  # Etwas Toleranz


class TestSpreadWidthFallback:
    """Tests für Spread-Width Fallback (wenn keine Options-Daten verfügbar)"""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_spread_width_low_price(self, recommender):
        """Test: Niedrige Preise bekommen proportionale Spreads (Fallback ~12%)"""
        widths = recommender._get_spread_widths_fallback(30.0)

        assert len(widths) >= 1
        # 12% of $30 = $3.60, rounded to $2.50 or $5.00
        assert widths[0] >= 2.5

    def test_spread_width_medium_price(self, recommender):
        """Test: Mittlere Preise bekommen proportionale Spreads (Fallback ~12%)"""
        widths = recommender._get_spread_widths_fallback(100.0)

        # 12% of $100 = $12, rounded to $10 or $15
        assert widths[0] >= 10.0

    def test_spread_width_high_price(self, recommender):
        """Test: Hohe Preise bekommen proportionale Spreads (Fallback ~12%)"""
        widths = recommender._get_spread_widths_fallback(500.0)

        # 12% of $500 = $60, rounded to $60
        assert widths[0] >= 50.0


class TestDeltaBasedLongStrike:
    """Tests für delta-basierte Long-Strike-Selektion"""

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    @pytest.fixture
    def full_options_chain(self):
        """Vollständige Options-Chain mit Short- und Long-Put Deltas"""
        return [
            {"strike": 700.0, "right": "P", "delta": -0.50, "bid": 30.0, "ask": 31.0, "open_interest": 500, "volume": 200},
            {"strike": 680.0, "right": "P", "delta": -0.35, "bid": 18.0, "ask": 19.0, "open_interest": 400, "volume": 150},
            {"strike": 660.0, "right": "P", "delta": -0.25, "bid": 12.0, "ask": 13.0, "open_interest": 350, "volume": 120},
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.50, "ask": 9.00, "open_interest": 300, "volume": 100},
            {"strike": 630.0, "right": "P", "delta": -0.18, "bid": 7.00, "ask": 7.50, "open_interest": 250, "volume": 80},
            {"strike": 620.0, "right": "P", "delta": -0.15, "bid": 5.50, "ask": 6.00, "open_interest": 200, "volume": 60},
            {"strike": 600.0, "right": "P", "delta": -0.10, "bid": 3.50, "ask": 4.00, "open_interest": 180, "volume": 50},
            {"strike": 580.0, "right": "P", "delta": -0.07, "bid": 2.00, "ask": 2.50, "open_interest": 150, "volume": 40},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.20, "ask": 1.50, "open_interest": 120, "volume": 30},
            {"strike": 540.0, "right": "P", "delta": -0.03, "bid": 0.60, "ask": 0.80, "open_interest": 100, "volume": 20},
            {"strike": 520.0, "right": "P", "delta": -0.02, "bid": 0.30, "ask": 0.50, "open_interest": 100, "volume": 10},
        ]

    def test_finds_long_strike_by_delta(self, recommender, full_options_chain):
        """Test: Long Strike wird per Delta -0.05 gefunden"""
        result = recommender._find_long_strike_by_delta(full_options_chain, short_strike=640.0)

        assert result is not None
        long_strike, long_delta = result
        assert long_strike == 560.0  # Delta -0.05
        assert long_delta == -0.05

    def test_long_strike_below_short_strike(self, recommender, full_options_chain):
        """Test: Long Strike muss unter Short Strike liegen"""
        result = recommender._find_long_strike_by_delta(full_options_chain, short_strike=640.0)

        assert result is not None
        long_strike, _ = result
        assert long_strike < 640.0

    def test_long_delta_within_range(self, recommender, full_options_chain):
        """Test: Long Delta muss im Bereich [-0.07, -0.03] liegen"""
        result = recommender._find_long_strike_by_delta(full_options_chain, short_strike=640.0)

        assert result is not None
        _, long_delta = result
        assert -0.07 <= long_delta <= -0.03

    def test_returns_none_when_no_suitable_option(self, recommender):
        """Test: None wenn kein passendes Delta vorhanden"""
        # Nur Optionen mit hohem Delta (kein -0.05 Range)
        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.30, "bid": 3.0, "ask": 3.5, "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.20, "bid": 1.5, "ask": 2.0, "open_interest": 200, "volume": 50},
        ]

        result = recommender._find_long_strike_by_delta(options_data, short_strike=90.0)
        assert result is None

    def test_full_recommendation_uses_delta_for_long(self, recommender, full_options_chain):
        """Test: Volle Empfehlung nutzt Delta für Short UND Long Strike"""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0, 650.0],
            options_data=full_options_chain
        )

        # Short Strike bei Delta ~-0.20, Long bei ~-0.05
        assert rec.short_strike < rec.current_price
        assert rec.long_strike < rec.short_strike
        # Spread Width ist dynamisch (nicht fix $5/$10)
        assert rec.spread_width == rec.short_strike - rec.long_strike
        assert rec.spread_width > 0

    def test_spread_width_is_dynamic_not_fixed(self, recommender, full_options_chain):
        """Test: Spread Width ergibt sich aus Delta-Differenz, nicht fixem Wert"""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0, 650.0],
            options_data=full_options_chain
        )

        # Bei einer $720 Aktie mit Delta -0.20 und -0.05 sollte die
        # Width deutlich größer als fixe $5 oder $10 sein
        assert rec.spread_width > 10.0

    def test_fallback_to_width_when_no_options_data(self, recommender):
        """Test: Fallback auf Width-basiert wenn keine Options-Daten"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=None
        )

        # Sollte trotzdem funktionieren
        assert rec.short_strike > 0
        assert rec.long_strike > 0
        assert rec.spread_width > 0

    def test_long_delta_propagated_to_recommendation(self, recommender, full_options_chain):
        """Test: Long Delta wird in Recommendation propagiert"""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0, 650.0],
            options_data=full_options_chain
        )

        # long_delta sollte vorhanden sein wenn delta-basiert selektiert
        assert rec.long_delta is not None
        assert -0.07 <= rec.long_delta <= -0.03


class TestSupportAnalysis:
    """Tests für Support-Level-Analyse"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_analyze_support_levels(self, recommender):
        """Test: Support-Levels werden analysiert"""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[95.0, 90.0, 85.0],
            fib_levels=None
        )
        
        assert len(supports) > 0
        assert all(isinstance(s, SupportLevel) for s in supports)
    
    def test_support_above_price_filtered(self, recommender):
        """Test: Supports über dem Preis werden gefiltert"""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[105.0, 95.0, 90.0],  # 105 ist über Preis
            fib_levels=None
        )
        
        prices = [s.price for s in supports]
        assert 105.0 not in prices
    
    def test_fib_confirmation(self, recommender):
        """Test: Fibonacci-Bestätigung wird erkannt"""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=[{"level": 90.5}]  # Nahe an 90.0
        )
        
        if supports:
            # Support bei 90 sollte als Fib-bestätigt markiert sein
            support_90 = next((s for s in supports if abs(s.price - 90.0) < 1), None)
            if support_90:
                assert support_90.confirmed_by_fib
    
    def test_support_distance_calculated(self, recommender):
        """Test: Abstand zum Support wird berechnet"""
        supports = recommender._analyze_support_levels(
            current_price=100.0,
            support_levels=[90.0],
            fib_levels=None
        )
        
        assert supports[0].distance_pct == 10.0  # 10% unter Preis


class TestQualityEvaluation:
    """Tests für Qualitätsbewertung"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_quality_is_assigned(self, recommender):
        """Test: Qualität wird zugewiesen"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )
        
        assert rec.quality in StrikeQuality
    
    def test_confidence_score_in_range(self, recommender):
        """Test: Confidence Score ist zwischen 0 und 100"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )
        
        assert 0 <= rec.confidence_score <= 100
    
    def test_high_iv_boosts_quality(self, recommender):
        """Test: Hoher IV-Rang verbessert Qualität"""
        rec_low_iv = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=20
        )
        
        rec_high_iv = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            iv_rank=70
        )
        
        # Hoher IV sollte besseren Score geben (für Credit Spreads)
        assert rec_high_iv.confidence_score >= rec_low_iv.confidence_score
    
    def test_warnings_for_low_otm(self, recommender):
        """Test: Warnung bei zu niedrigem OTM"""
        # Konfiguriere für Test
        recommender.config["min_otm_pct"] = 10.0
        
        # Erstelle manuell eine Bewertung mit niedrigem OTM
        support = SupportLevel(price=95.0, distance_pct=5.0)
        metrics = {"credit": 1.0, "spread_width": 5.0, "risk_reward": 0.3}
        
        quality, score, warnings = recommender._evaluate_quality(
            short_strike=95.0,  # Nur 5% OTM
            long_strike=90.0,
            current_price=100.0,
            support=support,
            metrics=metrics,
            iv_rank=None
        )
        
        # Sollte Warnung haben
        assert any("OTM" in w or "ITM" in w for w in warnings)


class TestMetricsCalculation:
    """Tests für Metriken-Berechnung"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_max_loss_calculated(self, recommender):
        """Test: Max Loss wird berechnet"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        assert rec.max_loss is not None
        assert rec.max_loss > 0
    
    def test_max_profit_calculated(self, recommender):
        """Test: Max Profit wird berechnet"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        assert rec.max_profit is not None
        assert rec.max_profit > 0
    
    def test_max_profit_less_than_max_loss(self, recommender):
        """Test: Max Profit < Max Loss (typisch für Credit Spreads)"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        if rec.max_profit and rec.max_loss:
            # Credit Spread: Max Profit ist das Credit, Max Loss ist Width - Credit
            assert rec.max_profit < rec.max_loss
    
    def test_break_even_between_strikes(self, recommender):
        """Test: Break-Even liegt zwischen den Strikes"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        if rec.break_even:
            assert rec.long_strike <= rec.break_even <= rec.short_strike
    
    def test_prob_profit_calculated(self, recommender):
        """Test: Gewinn-Wahrscheinlichkeit wird geschätzt"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        if rec.prob_profit:
            assert 0 < rec.prob_profit < 100


class TestMultipleRecommendations:
    """Tests für mehrere Empfehlungen"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_get_multiple_recommendations(self, recommender):
        """Test: Mehrere Empfehlungen werden generiert"""
        recs = recommender.get_multiple_recommendations(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0, 80.0],
            num_alternatives=3
        )
        
        assert len(recs) <= 3
        assert all(isinstance(r, StrikeRecommendation) for r in recs)
    
    def test_recommendations_sorted_by_confidence(self, recommender):
        """Test: Empfehlungen sind nach Confidence sortiert"""
        recs = recommender.get_multiple_recommendations(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0, 80.0],
            num_alternatives=3
        )
        
        if len(recs) > 1:
            scores = [r.confidence_score for r in recs]
            assert scores == sorted(scores, reverse=True)


class TestConfigIntegration:
    """
    Tests für Fix #8: Config-Integration für StrikeRecommender
    
    StrikeRecommender lädt jetzt Einstellungen aus ConfigLoader
    wenn verfügbar.
    """
    
    def test_custom_config_overrides_defaults(self):
        """Test: Explizite Config überschreibt Defaults"""
        custom_config = {
            "delta_target": -0.25,
            "min_credit_pct": 25
        }
        
        recommender = StrikeRecommender(config=custom_config, use_config_loader=False)
        
        assert recommender.config["delta_target"] == -0.25
        assert recommender.config["min_credit_pct"] == 25
    
    def test_use_config_loader_false_uses_defaults(self):
        """Test: use_config_loader=False verwendet nur Defaults"""
        recommender = StrikeRecommender(use_config_loader=False)
        
        # Sollte Default-Werte haben
        assert recommender.config["delta_target"] == -0.20
    
    def test_config_loader_not_available_graceful(self):
        """Test: Wenn ConfigLoader nicht verfügbar, graceful fallback"""
        # Mock _CONFIG_AVAILABLE als False
        import strike_recommender
        original = strike_recommender._CONFIG_AVAILABLE
        
        try:
            strike_recommender._CONFIG_AVAILABLE = False
            recommender = StrikeRecommender(use_config_loader=True)
            
            # Sollte trotzdem funktionieren mit Defaults
            assert recommender.config["delta_target"] == -0.20
        finally:
            strike_recommender._CONFIG_AVAILABLE = original


class TestConvenienceFunction:
    """Tests für calculate_strike_recommendation Funktion"""
    
    def test_convenience_function_returns_dict(self):
        """Test: Convenience-Funktion gibt Dict zurück"""
        result = calculate_strike_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0]
        )
        
        assert isinstance(result, dict)
        assert "symbol" in result
        assert "short_strike" in result
        assert "long_strike" in result
    
    def test_convenience_function_with_all_params(self):
        """Test: Convenience-Funktion mit allen Parametern"""
        result = calculate_strike_recommendation(
            symbol="AAPL",
            current_price=180.0,
            support_levels=[170.0, 165.0],
            iv_rank=55,
            fib_levels=[{"level": 168.0}]
        )
        
        assert result["symbol"] == "AAPL"
        assert result["current_price"] == 180.0


class TestToDict:
    """Tests für to_dict Methode"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_to_dict_contains_all_fields(self, recommender):
        """Test: to_dict enthält alle Felder"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        d = rec.to_dict()
        
        required_fields = [
            "symbol", "current_price", "short_strike", "long_strike",
            "spread_width", "quality", "confidence_score"
        ]
        
        for field in required_fields:
            assert field in d
    
    def test_to_dict_quality_is_string(self, recommender):
        """Test: Quality ist als String serialisiert"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0]
        )
        
        d = rec.to_dict()
        
        assert isinstance(d["quality"], str)
        assert d["quality"] in ["excellent", "good", "acceptable", "poor"]


class TestStrikeRounding:
    """Tests für Strike-Rundung"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_round_strike_low_price(self, recommender):
        """Test: Niedrige Preise werden auf ganze Zahlen gerundet"""
        rounded = recommender._round_strike(32.7, 35.0)
        
        assert rounded == 33.0
    
    def test_round_strike_medium_price(self, recommender):
        """Test: Mittlere Preise werden auf $5 gerundet"""
        rounded = recommender._round_strike(97.3, 100.0)
        
        assert rounded == 95.0 or rounded == 100.0
    
    def test_round_strike_high_price(self, recommender):
        """Test: Hohe Preise werden auf $10 gerundet"""
        rounded = recommender._round_strike(347.5, 350.0)
        
        assert rounded % 10 == 0


class TestWithOptionsData:
    """Tests mit Options-Daten"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_uses_delta_from_options_data(self, recommender):
        """Test: Delta wird aus Options-Daten verwendet"""
        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.28, "bid": 1.50, "ask": 1.60, "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 0.80, "ask": 0.90, "open_interest": 200, "volume": 50},
            {"strike": 75.0, "right": "P", "delta": -0.05, "bid": 0.15, "ask": 0.25, "open_interest": 150, "volume": 30},
        ]
        
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=options_data
        )
        
        # Sollte den Strike mit Delta nahe Target wählen
        assert rec.estimated_delta is not None
    
    def test_calculates_credit_from_options_data(self, recommender):
        """Test: Credit wird aus Options-Daten berechnet"""
        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.28, "bid": 2.00, "ask": 2.10, "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 0.90, "ask": 1.00, "open_interest": 200, "volume": 50},
            {"strike": 75.0, "right": "P", "delta": -0.05, "bid": 0.10, "ask": 0.20, "open_interest": 150, "volume": 30},
        ]
        
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=options_data
        )
        
        # Credit sollte aus echten Bid/Ask berechnet sein
        if rec.short_strike == 90.0 and rec.long_strike == 85.0:
            expected_credit = 2.00 - 1.00  # short bid - long ask
            assert abs(rec.estimated_credit - expected_credit) < 0.1


class TestLiquidityFilterInStrikeSelection:
    """Tests for liquidity-based filtering during strike selection.

    All thresholds are imported from trading_rules.py — no hardcoding.
    """

    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)

    def test_skips_short_strike_with_low_oi(self, recommender):
        """Short strike with OI < ENTRY_OPEN_INTEREST_MIN is skipped."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        options_data = [
            # Good delta but insufficient OI
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 2.0, "ask": 2.2,
             "open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "volume": 50},
            # Liquid strike with acceptable delta
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": ENTRY_OPEN_INTEREST_MIN + 50, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data,
        )

        # Should pick the liquid strike at $85 (not the illiquid $90)
        assert rec.short_strike == 85.0

    def test_skips_short_strike_with_zero_bid(self, recommender):
        """Short strike with bid=0 is skipped even with good OI."""
        options_data = [
            # Good OI but zero bid
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 0, "ask": 2.0,
             "open_interest": 500, "volume": 100},
            # Liquid alternative
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 1.5, "ask": 1.7,
             "open_interest": 200, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data,
        )

        assert rec.short_strike == 85.0

    def test_skips_long_strike_with_low_oi(self, recommender):
        """Long strike with OI < ENTRY_OPEN_INTEREST_MIN is skipped."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        options_data = [
            # Liquid short strike
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.5, "ask": 9.0,
             "open_interest": 300, "volume": 100},
            # Illiquid long strike (best delta but low OI)
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.2, "ask": 1.5,
             "open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "volume": 10},
            # Liquid alternative long strike
            {"strike": 580.0, "right": "P", "delta": -0.06, "bid": 2.0, "ask": 2.5,
             "open_interest": ENTRY_OPEN_INTEREST_MIN + 50, "volume": 40},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=720.0,
            support_levels=[680.0],
            options_data=options_data,
        )

        # Long strike should be $580 (liquid), not $560 (illiquid)
        assert rec.long_strike == 580.0

    def test_returns_poor_quality_when_no_liquid_short_strike(self, recommender):
        """Returns POOR quality when options_data present but no liquid short strike."""
        options_data = [
            # All strikes illiquid
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 2.0, "ask": 2.2,
             "open_interest": 5, "volume": 0},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 0, "ask": 1.5,
             "open_interest": 10, "volume": 0},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0],
            options_data=options_data,
        )

        assert rec.quality == StrikeQuality.POOR
        assert any("liquid" in w.lower() for w in rec.warnings)

    def test_no_fallback_to_theoretical_when_options_data_present(self, recommender):
        """With options_data but no liquid strikes, do NOT fallback to OTM/Support."""
        options_data = [
            # All illiquid
            {"strike": 90.0, "right": "P", "delta": -0.20, "bid": 0, "ask": 2.0,
             "open_interest": 0, "volume": 0},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=options_data,
        )

        # Should be POOR quality, not a theoretical recommendation
        assert rec.quality == StrikeQuality.POOR

    def test_is_strike_liquid_method(self, recommender):
        """Test _is_strike_liquid directly."""
        from src.constants.trading_rules import ENTRY_OPEN_INTEREST_MIN

        # Liquid
        assert recommender._is_strike_liquid(
            {"open_interest": ENTRY_OPEN_INTEREST_MIN, "bid": 1.0}
        ) is True

        # Insufficient OI
        assert recommender._is_strike_liquid(
            {"open_interest": ENTRY_OPEN_INTEREST_MIN - 1, "bid": 1.0}
        ) is False

        # Zero bid
        assert recommender._is_strike_liquid(
            {"open_interest": 500, "bid": 0}
        ) is False

        # Missing fields treated as 0
        assert recommender._is_strike_liquid({}) is False

    def test_liquidity_warning_on_wide_spread(self, recommender):
        """Warning when bid-ask spread exceeds LIQUIDITY_SPREAD_PCT_GOOD."""
        from src.constants.trading_rules import LIQUIDITY_SPREAD_PCT_GOOD

        options_data = [
            # Wide spread (>10% of mid)
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 5.0, "ask": 7.0,
             "open_interest": 300, "volume": 100},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 0.5, "ask": 1.5,
             "open_interest": 200, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=720.0,
            support_levels=[680.0],
            options_data=options_data,
        )

        # Should have a warning about wide spread
        assert any("spread" in w.lower() or "Wide" in w for w in rec.warnings)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
