# OptionPlay - Strategy Enum Tests
# ==================================
"""Tests für das Strategy Enum."""

import pytest
from src.models.strategy import (
    Strategy,
    STRATEGY_ICONS,
    STRATEGY_NAMES,
    get_strategy_icon,
    get_strategy_display_name,
)


class TestStrategyEnum:
    """Tests für Strategy Enum."""
    
    def test_all_strategies_defined(self):
        """Alle erwarteten Strategien sind definiert."""
        assert Strategy.PULLBACK.value == "pullback"
        assert Strategy.BOUNCE.value == "bounce"

    def test_strategy_count(self):
        """Mindestens 2 Strategien sind definiert."""
        assert len(Strategy) >= 2
    
    def test_icons_defined_for_all(self):
        """Jede Strategie hat ein Icon."""
        for strategy in Strategy:
            assert strategy.icon is not None
            assert len(strategy.icon) > 0
    
    def test_display_names_defined_for_all(self):
        """Jede Strategie hat einen Display-Name."""
        for strategy in Strategy:
            assert strategy.display_name is not None
            assert len(strategy.display_name) > 0
    
    def test_descriptions_defined_for_all(self):
        """Jede Strategie hat eine Beschreibung."""
        for strategy in Strategy:
            assert strategy.description is not None
            assert len(strategy.description) > 10


class TestStrategyProperties:
    """Tests für Strategy-Properties."""
    
    def test_pullback_is_credit_spread_suitable(self):
        """Pullback ist für Credit Spreads geeignet."""
        assert Strategy.PULLBACK.suitable_for_credit_spreads is True
    
    def test_bounce_is_credit_spread_suitable(self):
        """Bounce ist für Credit Spreads geeignet."""
        assert Strategy.BOUNCE.suitable_for_credit_spreads is True
    
    def test_earnings_filter_requirement(self):
        """Pullback und Bounce brauchen Earnings-Filter."""
        assert Strategy.PULLBACK.requires_earnings_filter is True
        assert Strategy.BOUNCE.requires_earnings_filter is True

    def test_min_historical_days(self):
        """Min historical days sind definiert."""
        assert Strategy.PULLBACK.min_historical_days == 90
        assert Strategy.BOUNCE.min_historical_days == 90

    def test_default_min_score(self):
        """Default Scores sind definiert."""
        assert Strategy.PULLBACK.default_min_score == 5.0
        assert Strategy.BOUNCE.default_min_score == 5.0


class TestStrategyClassMethods:
    """Tests für Strategy Class Methods."""
    
    def test_from_string_valid(self):
        """Konvertiert gültige Strings korrekt."""
        assert Strategy.from_string("pullback") == Strategy.PULLBACK
        assert Strategy.from_string("PULLBACK") == Strategy.PULLBACK
        assert Strategy.from_string("Pullback") == Strategy.PULLBACK
        assert Strategy.from_string("  pullback  ") == Strategy.PULLBACK
    
    def test_from_string_all_strategies(self):
        """Alle Strategien können aus String konvertiert werden."""
        for strategy in Strategy:
            result = Strategy.from_string(strategy.value)
            assert result == strategy
    
    def test_from_string_invalid(self):
        """Ungültige Strings werfen ValueError."""
        with pytest.raises(ValueError) as exc_info:
            Strategy.from_string("invalid")
        assert "Unknown strategy" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)
    
    def test_credit_spread_strategies(self):
        """Credit Spread Strategien werden korrekt gefiltert."""
        credit_strategies = Strategy.credit_spread_strategies()
        assert Strategy.PULLBACK in credit_strategies
        assert Strategy.BOUNCE in credit_strategies
    
    def test_all_values(self):
        """all_values gibt alle Values zurück."""
        values = Strategy.all_values()
        assert "pullback" in values
        assert "bounce" in values
    
    def test_to_dict(self):
        """to_dict serialisiert korrekt."""
        d = Strategy.PULLBACK.to_dict()
        assert d["name"] == "PULLBACK"
        assert d["value"] == "pullback"
        assert d["icon"] == "📊"
        assert "display_name" in d
        assert "description" in d
        assert d["suitable_for_credit_spreads"] is True
        assert d["requires_earnings_filter"] is True
        assert d["min_historical_days"] == 90
        assert d["default_min_score"] == 5.0


class TestBackwardsCompatibility:
    """Tests für Backwards-Compatibility Funktionen."""
    
    def test_strategy_icons_dict(self):
        """STRATEGY_ICONS Dict funktioniert."""
        assert STRATEGY_ICONS["pullback"] == "📊"
        assert STRATEGY_ICONS["bounce"] == "🔄"

    def test_strategy_names_dict(self):
        """STRATEGY_NAMES Dict funktioniert."""
        assert STRATEGY_NAMES["pullback"] == "Bull-Put-Spread"
        assert STRATEGY_NAMES["bounce"] == "Support Bounce"
    
    def test_get_strategy_icon_valid(self):
        """get_strategy_icon funktioniert für gültige Strategien."""
        assert get_strategy_icon("pullback") == "📊"
        assert get_strategy_icon("PULLBACK") == "📊"
    
    def test_get_strategy_icon_invalid(self):
        """get_strategy_icon gibt Default für ungültige zurück."""
        assert get_strategy_icon("invalid") == "•"
    
    def test_get_strategy_display_name_valid(self):
        """get_strategy_display_name funktioniert für gültige Strategien."""
        assert get_strategy_display_name("pullback") == "Bull-Put-Spread"
    
    def test_get_strategy_display_name_invalid(self):
        """get_strategy_display_name gibt Original für ungültige zurück."""
        assert get_strategy_display_name("unknown") == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
