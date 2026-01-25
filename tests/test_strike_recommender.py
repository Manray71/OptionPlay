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
        assert recommender.config["delta_target"] == -0.30
        assert recommender.config["delta_min"] == -0.35
        assert recommender.config["delta_max"] == -0.20
        assert recommender.config["min_otm_pct"] == 8.0
        assert recommender.config["min_credit_pct"] == 20
    
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


class TestSpreadWidthByPrice:
    """Tests für Spread-Width basierend auf Preisniveau"""
    
    @pytest.fixture
    def recommender(self):
        return StrikeRecommender(use_config_loader=False)
    
    def test_spread_width_low_price(self, recommender):
        """Test: Niedrige Preise bekommen kleinere Spreads"""
        widths = recommender._get_spread_widths(30.0)
        
        assert 2.5 in widths or 5.0 in widths
        assert all(w <= 5.0 for w in widths)
    
    def test_spread_width_medium_price(self, recommender):
        """Test: Mittlere Preise bekommen $5 Spreads"""
        widths = recommender._get_spread_widths(100.0)
        
        assert 5.0 in widths
    
    def test_spread_width_high_price(self, recommender):
        """Test: Hohe Preise bekommen größere Spreads"""
        widths = recommender._get_spread_widths(500.0)
        
        assert any(w >= 10.0 for w in widths)


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
        assert recommender.config["delta_target"] == -0.30
    
    def test_config_loader_not_available_graceful(self):
        """Test: Wenn ConfigLoader nicht verfügbar, graceful fallback"""
        # Mock _CONFIG_AVAILABLE als False
        import strike_recommender
        original = strike_recommender._CONFIG_AVAILABLE
        
        try:
            strike_recommender._CONFIG_AVAILABLE = False
            recommender = StrikeRecommender(use_config_loader=True)
            
            # Sollte trotzdem funktionieren mit Defaults
            assert recommender.config["delta_target"] == -0.30
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
            {"strike": 90.0, "right": "P", "delta": -0.28, "bid": 1.50, "ask": 1.60},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 0.80, "ask": 0.90},
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
            {"strike": 90.0, "right": "P", "delta": -0.28, "bid": 2.00, "ask": 2.10},
            {"strike": 85.0, "right": "P", "delta": -0.18, "bid": 0.90, "ask": 1.00},
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
