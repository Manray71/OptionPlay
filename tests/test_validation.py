# OptionPlay - Validation Tests
# ==============================
# Tests für Input-Validierung

import pytest
from src.utils.validation import (
    ValidationError,
    validate_symbol,
    validate_symbols,
    validate_dte,
    validate_dte_range,
    validate_delta,
    validate_right,
    validate_positive_int,
    safe_validate_symbol,
    is_valid_symbol,
)


class TestValidateSymbol:
    """Tests für validate_symbol()"""
    
    def test_basic_symbols(self):
        """Standard US-Ticker werden akzeptiert"""
        assert validate_symbol("AAPL") == "AAPL"
        assert validate_symbol("MSFT") == "MSFT"
        assert validate_symbol("A") == "A"  # Single letter
        assert validate_symbol("GOOGL") == "GOOGL"  # 5 letters
    
    def test_lowercase_converted(self):
        """Lowercase wird zu Uppercase konvertiert"""
        assert validate_symbol("aapl") == "AAPL"
        assert validate_symbol("Msft") == "MSFT"
    
    def test_whitespace_trimmed(self):
        """Whitespace wird entfernt"""
        assert validate_symbol("  AAPL  ") == "AAPL"
        assert validate_symbol("\tMSFT\n") == "MSFT"
    
    def test_class_shares(self):
        """Klassen-Aktien (BRK.A, BRK.B) werden akzeptiert"""
        assert validate_symbol("BRK.A") == "BRK.A"
        assert validate_symbol("BRK.B") == "BRK.B"
    
    def test_index_symbols(self):
        """Index-Symbole werden akzeptiert"""
        assert validate_symbol("VIX") == "VIX"
        assert validate_symbol("SPX") == "SPX"
        assert validate_symbol("NDX") == "NDX"
    
    def test_index_symbols_disabled(self):
        """Index-Symbole können deaktiviert werden"""
        # VIX ist 3 Buchstaben, sollte auch ohne allow_index funktionieren
        assert validate_symbol("VIX", allow_index=False) == "VIX"
    
    def test_empty_raises(self):
        """Leere Symbole werfen ValidationError"""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_symbol("")
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_symbol("   ")
    
    def test_none_raises(self):
        """None wirft ValidationError"""
        with pytest.raises(ValidationError, match="cannot be None"):
            validate_symbol(None)
    
    def test_non_string_raises(self):
        """Nicht-Strings werfen ValidationError"""
        with pytest.raises(ValidationError, match="must be string"):
            validate_symbol(123)
        with pytest.raises(ValidationError, match="must be string"):
            validate_symbol(["AAPL"])
    
    def test_invalid_characters_raises(self):
        """Ungültige Zeichen werfen ValidationError"""
        with pytest.raises(ValidationError, match="Invalid symbol format"):
            validate_symbol("AAPL!")
        with pytest.raises(ValidationError, match="Invalid symbol format"):
            validate_symbol("AA$PL")
        with pytest.raises(ValidationError, match="Invalid symbol format"):
            validate_symbol("AAPL123")
        with pytest.raises(ValidationError, match="Invalid symbol format"):
            validate_symbol("AA PL")
    
    def test_too_long_raises(self):
        """Zu lange Symbole werfen ValidationError"""
        with pytest.raises(ValidationError, match="too long"):
            validate_symbol("AAAAAAAAAAAA")  # 12 chars


class TestValidateSymbols:
    """Tests für validate_symbols()"""
    
    def test_list_of_symbols(self):
        """Liste von Symbolen wird validiert"""
        result = validate_symbols(["AAPL", "MSFT", "GOOGL"])
        assert result == ["AAPL", "MSFT", "GOOGL"]
    
    def test_deduplication(self):
        """Duplikate werden entfernt"""
        result = validate_symbols(["AAPL", "aapl", "AAPL"])
        assert result == ["AAPL"]
    
    def test_skip_invalid(self):
        """Mit skip_invalid=True werden ungültige übersprungen"""
        result = validate_symbols(["AAPL", "INVALID!!!", "MSFT"], skip_invalid=True)
        assert result == ["AAPL", "MSFT"]
    
    def test_raise_on_invalid(self):
        """Ohne skip_invalid wirft ungültiges Symbol ValidationError"""
        with pytest.raises(ValidationError):
            validate_symbols(["AAPL", "INVALID!!!", "MSFT"])
    
    def test_empty_list(self):
        """Leere Liste gibt leere Liste zurück"""
        assert validate_symbols([]) == []
    
    def test_non_list_raises(self):
        """Nicht-Liste wirft ValidationError"""
        with pytest.raises(ValidationError, match="must be list"):
            validate_symbols("AAPL")


class TestValidateDTE:
    """Tests für DTE-Validierung"""
    
    def test_valid_dte(self):
        """Gültige DTE-Werte"""
        assert validate_dte(30) == 30
        assert validate_dte(45) == 45
        assert validate_dte(0) == 0
    
    def test_string_to_int(self):
        """String wird zu Int konvertiert"""
        assert validate_dte("30") == 30
    
    def test_negative_raises(self):
        """Negative Werte werfen ValidationError"""
        with pytest.raises(ValidationError, match="cannot be negative"):
            validate_dte(-1)
    
    def test_too_large_raises(self):
        """Zu große Werte werfen ValidationError"""
        with pytest.raises(ValidationError, match="too large"):
            validate_dte(1000)


class TestValidateDTERange:
    """Tests für DTE-Range-Validierung"""
    
    def test_valid_range(self):
        """Gültiger Bereich"""
        assert validate_dte_range(30, 60) == (30, 60)
    
    def test_min_greater_than_max_raises(self):
        """Min > Max wirft ValidationError"""
        with pytest.raises(ValidationError, match="cannot be greater"):
            validate_dte_range(60, 30)


class TestValidateDelta:
    """Tests für Delta-Validierung"""
    
    def test_valid_delta(self):
        """Gültige Delta-Werte"""
        assert validate_delta(-0.30) == -0.30
        assert validate_delta(0.5) == 0.5
        assert validate_delta(-1.0) == -1.0
        assert validate_delta(1.0) == 1.0
    
    def test_out_of_range_raises(self):
        """Außerhalb -1 bis 1 wirft ValidationError"""
        with pytest.raises(ValidationError, match="between -1.0 and 1.0"):
            validate_delta(-1.5)
        with pytest.raises(ValidationError, match="between -1.0 and 1.0"):
            validate_delta(1.1)


class TestValidateRight:
    """Tests für Options-Right-Validierung"""
    
    def test_put_variants(self):
        """Put-Varianten werden zu 'P'"""
        assert validate_right("P") == "P"
        assert validate_right("p") == "P"
        assert validate_right("PUT") == "P"
        assert validate_right("put") == "P"
    
    def test_call_variants(self):
        """Call-Varianten werden zu 'C'"""
        assert validate_right("C") == "C"
        assert validate_right("c") == "C"
        assert validate_right("CALL") == "C"
        assert validate_right("call") == "C"
    
    def test_invalid_raises(self):
        """Ungültige Werte werfen ValidationError"""
        with pytest.raises(ValidationError, match="Invalid right"):
            validate_right("X")
        with pytest.raises(ValidationError, match="Invalid right"):
            validate_right("PUTS")


class TestConvenienceFunctions:
    """Tests für Convenience-Funktionen"""
    
    def test_safe_validate_symbol(self):
        """safe_validate_symbol gibt default bei Fehler zurück"""
        assert safe_validate_symbol("AAPL") == "AAPL"
        assert safe_validate_symbol("INVALID!!!") is None
        assert safe_validate_symbol("INVALID!!!", default="ERROR") == "ERROR"
    
    def test_is_valid_symbol(self):
        """is_valid_symbol gibt bool zurück"""
        assert is_valid_symbol("AAPL") is True
        assert is_valid_symbol("INVALID!!!") is False
        assert is_valid_symbol("") is False
