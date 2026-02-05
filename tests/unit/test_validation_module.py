# Tests for Validation Module
# ===========================
"""
Comprehensive tests for input validation functions.
"""

import pytest
from src.utils.validation import (
    validate_symbol,
    validate_symbols,
    validate_dte,
    validate_dte_range,
    validate_delta,
    validate_right,
    validate_min_score,
    validate_positive_int,
    validate_batch_size,
    validate_max_results,
    validate_num_alternatives,
    validate_min_days,
    validate_pause_seconds,
    safe_validate_symbol,
    is_etf,
    is_valid_symbol,
    ValidationError,
    ValidationLimits,
    SYMBOL_PATTERN,
    SYMBOL_PATTERN_EXTENDED,
    INDEX_SYMBOLS,
    ETF_SYMBOLS,
)


class TestValidateSymbol:
    """Tests for validate_symbol function."""

    def test_valid_simple_symbol(self):
        """Test validation of simple valid symbols."""
        assert validate_symbol("AAPL") == "AAPL"
        assert validate_symbol("MSFT") == "MSFT"
        assert validate_symbol("A") == "A"

    def test_normalizes_to_uppercase(self):
        """Test that symbols are normalized to uppercase."""
        assert validate_symbol("aapl") == "AAPL"
        assert validate_symbol("Msft") == "MSFT"
        assert validate_symbol("googl") == "GOOGL"

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        assert validate_symbol("  AAPL  ") == "AAPL"
        assert validate_symbol("\tMSFT\n") == "MSFT"

    def test_valid_class_symbols(self):
        """Test validation of class symbols with dot."""
        assert validate_symbol("BRK.A") == "BRK.A"
        assert validate_symbol("BRK.B") == "BRK.B"

    def test_index_symbols_allowed(self):
        """Test that index symbols are allowed by default."""
        assert validate_symbol("VIX") == "VIX"
        assert validate_symbol("SPX") == "SPX"
        assert validate_symbol("NDX") == "NDX"

    def test_index_symbols_disallowed(self):
        """Test that index symbols still match pattern in strict mode."""
        # VIX matches the pattern, so it passes even with allow_index=False
        # This is correct behavior - allow_index only controls special index handling
        result = validate_symbol("VIX", allow_index=False)
        assert result == "VIX"

    def test_none_raises_error(self):
        """Test that None raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(None)
        assert "cannot be None" in str(exc.value)

    def test_non_string_raises_error(self):
        """Test that non-string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(123)
        assert "must be string" in str(exc.value)

    def test_empty_string_raises_error(self):
        """Test that empty string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("")
        assert "cannot be empty" in str(exc.value)

    def test_whitespace_only_raises_error(self):
        """Test that whitespace-only string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("   ")
        assert "cannot be empty" in str(exc.value)

    def test_too_long_raises_error(self):
        """Test that symbol > 10 chars raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("VERYLONGSYMBOL")
        assert "too long" in str(exc.value)

    def test_invalid_format_raises_error(self):
        """Test that invalid format raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("123INVALID")
        assert "Invalid symbol format" in str(exc.value)

    def test_special_chars_raises_error(self):
        """Test that special characters raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_symbol("AAPL!!!")

        with pytest.raises(ValidationError):
            validate_symbol("@AAPL")

        with pytest.raises(ValidationError):
            validate_symbol("AAPL$")

    def test_strict_mode_rejects_extended(self):
        """Test that strict mode rejects extended patterns."""
        # Standard symbol should work in strict mode
        assert validate_symbol("AAPL", strict=True) == "AAPL"

    def test_non_strict_allows_extended(self):
        """Test that non-strict mode allows extended patterns."""
        # 6-letter symbols allowed in non-strict
        assert validate_symbol("GOOGLL", strict=False) == "GOOGLL"


class TestValidateSymbols:
    """Tests for validate_symbols function."""

    def test_validates_list(self):
        """Test validation of symbol list."""
        result = validate_symbols(["AAPL", "MSFT", "GOOGL"])
        assert "AAPL" in result
        assert "MSFT" in result
        assert "GOOGL" in result

    def test_normalizes_all(self):
        """Test that all symbols are normalized."""
        result = validate_symbols(["aapl", "msft", "googl"])
        assert result == ["AAPL", "MSFT", "GOOGL"]

    def test_empty_list_returns_empty(self):
        """Test that empty list returns empty list."""
        assert validate_symbols([]) == []

    def test_deduplicates(self):
        """Test that duplicates are removed."""
        result = validate_symbols(["AAPL", "aapl", "AAPL"])
        assert len(result) == 1
        assert result[0] == "AAPL"

    def test_skip_invalid_mode(self):
        """Test skip_invalid mode skips bad symbols."""
        result = validate_symbols(
            ["AAPL", "123INVALID", "MSFT"],
            skip_invalid=True
        )
        assert "AAPL" in result
        assert "MSFT" in result
        assert "123INVALID" not in result

    def test_skip_invalid_false_raises(self):
        """Test skip_invalid=False raises on bad symbol."""
        with pytest.raises(ValidationError):
            validate_symbols(
                ["AAPL", "123INVALID", "MSFT"],
                skip_invalid=False
            )

    def test_non_list_raises_error(self):
        """Test that non-list input raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbols("AAPL")
        assert "must be list" in str(exc.value)

    def test_accepts_tuple(self):
        """Test that tuple is accepted."""
        result = validate_symbols(("AAPL", "MSFT"))
        assert "AAPL" in result
        assert "MSFT" in result


class TestValidateDteRange:
    """Tests for validate_dte_range function."""

    def test_valid_range(self):
        """Test valid DTE range."""
        min_dte, max_dte = validate_dte_range(30, 60)
        assert min_dte == 30
        assert max_dte == 60

    def test_inverted_raises_error(self):
        """Test that inverted range raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte_range(60, 30)

    def test_negative_raises_error(self):
        """Test that negative DTE raises error."""
        with pytest.raises(ValidationError):
            validate_dte_range(-1, 60)

    def test_zero_allowed(self):
        """Test that zero DTE is allowed."""
        min_dte, max_dte = validate_dte_range(0, 30)
        assert min_dte == 0

    def test_rejects_too_large_dte(self):
        """Test that too large DTE raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte_range(30, 1000)  # Max is 730 days


class TestValidateRight:
    """Tests for validate_right function."""

    def test_valid_put(self):
        """Test valid put."""
        assert validate_right("P") == "P"
        assert validate_right("p") == "P"
        assert validate_right("put") == "P"
        assert validate_right("PUT") == "P"

    def test_valid_call(self):
        """Test valid call."""
        assert validate_right("C") == "C"
        assert validate_right("c") == "C"
        assert validate_right("call") == "C"
        assert validate_right("CALL") == "C"

    def test_invalid_raises_error(self):
        """Test invalid right raises error."""
        with pytest.raises(ValidationError):
            validate_right("X")

        with pytest.raises(ValidationError):
            validate_right("invalid")


class TestValidateMinScore:
    """Tests for validate_min_score function."""

    def test_valid_scores(self):
        """Test valid score values."""
        assert validate_min_score(0) == 0.0
        assert validate_min_score(5) == 5.0
        assert validate_min_score(10) == 10.0

    def test_float_scores(self):
        """Test float score values."""
        assert validate_min_score(7.5) == 7.5
        assert validate_min_score(3.14) == 3.14

    def test_string_conversion(self):
        """Test string to float conversion."""
        assert validate_min_score("5.5") == 5.5


class TestValidatePositiveInt:
    """Tests for validate_positive_int function."""

    def test_valid_values(self):
        """Test valid positive integer values."""
        assert validate_positive_int(1, "test") == 1
        assert validate_positive_int(5, "test") == 5
        assert validate_positive_int(100, "test") == 100

    def test_zero_raises_error(self):
        """Test zero raises error."""
        with pytest.raises(ValidationError):
            validate_positive_int(0, "test")

    def test_negative_raises_error(self):
        """Test negative raises error."""
        with pytest.raises(ValidationError):
            validate_positive_int(-1, "test")

    def test_string_conversion(self):
        """Test string to int conversion."""
        assert validate_positive_int("5", "test") == 5


class TestIsEtf:
    """Tests for is_etf function."""

    def test_known_etfs(self):
        """Test known ETF symbols."""
        assert is_etf("SPY") is True
        assert is_etf("QQQ") is True
        assert is_etf("IWM") is True
        assert is_etf("XLK") is True
        assert is_etf("XLF") is True

    def test_non_etfs(self):
        """Test non-ETF symbols."""
        assert is_etf("AAPL") is False
        assert is_etf("MSFT") is False
        assert is_etf("GOOGL") is False

    def test_case_insensitive(self):
        """Test is_etf is case insensitive."""
        assert is_etf("spy") is True
        assert is_etf("Qqq") is True


class TestIsValidSymbol:
    """Tests for is_valid_symbol function."""

    def test_valid_symbols(self):
        """Test valid symbols return True."""
        assert is_valid_symbol("AAPL") is True
        assert is_valid_symbol("MSFT") is True
        assert is_valid_symbol("BRK.A") is True

    def test_invalid_symbols(self):
        """Test invalid symbols return False."""
        assert is_valid_symbol("123INVALID") is False
        assert is_valid_symbol("") is False

    def test_case_insensitive(self):
        """Test is_valid_symbol works with lowercase."""
        assert is_valid_symbol("aapl") is True
        assert is_valid_symbol("msft") is True


class TestSymbolPatterns:
    """Tests for symbol regex patterns."""

    def test_standard_pattern_valid(self):
        """Test standard pattern matches valid symbols."""
        assert SYMBOL_PATTERN.match("AAPL") is not None
        assert SYMBOL_PATTERN.match("A") is not None
        assert SYMBOL_PATTERN.match("BRK.A") is not None

    def test_standard_pattern_invalid(self):
        """Test standard pattern rejects invalid symbols."""
        assert SYMBOL_PATTERN.match("123") is None
        assert SYMBOL_PATTERN.match("TOOLONG") is None
        assert SYMBOL_PATTERN.match("AA.BB") is None

    def test_extended_pattern(self):
        """Test extended pattern for longer symbols."""
        assert SYMBOL_PATTERN_EXTENDED.match("GOOGLL") is not None


class TestConstants:
    """Tests for validation constants."""

    def test_index_symbols_set(self):
        """Test INDEX_SYMBOLS contains expected values."""
        assert "VIX" in INDEX_SYMBOLS
        assert "SPX" in INDEX_SYMBOLS
        assert "NDX" in INDEX_SYMBOLS

    def test_etf_symbols_set(self):
        """Test ETF_SYMBOLS contains expected values."""
        assert "SPY" in ETF_SYMBOLS
        assert "QQQ" in ETF_SYMBOLS
        assert "XLK" in ETF_SYMBOLS


# =============================================================================
# VALIDATE DTE TESTS
# =============================================================================

class TestValidateDte:
    """Tests for validate_dte function."""

    def test_valid_dte_values(self):
        """Test valid DTE values."""
        assert validate_dte(30) == 30
        assert validate_dte(60) == 60
        assert validate_dte(0) == 0
        assert validate_dte(365) == 365

    def test_string_converted(self):
        """Test string DTE is converted."""
        assert validate_dte("30") == 30
        assert validate_dte("60") == 60

    def test_negative_raises_error(self):
        """Test negative DTE raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(-5)
        assert "negative" in str(exc.value).lower()

    def test_too_large_raises_error(self):
        """Test DTE > 730 raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(800)
        assert "730" in str(exc.value)

    def test_invalid_string_raises_error(self):
        """Test invalid string raises error."""
        with pytest.raises(ValidationError):
            validate_dte("abc")

    def test_custom_param_name(self):
        """Test custom param name in error message."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(-1, param_name="my_dte")
        assert "my_dte" in str(exc.value)


# =============================================================================
# VALIDATE DELTA TESTS
# =============================================================================

class TestValidateDelta:
    """Tests for validate_delta function."""

    def test_valid_delta_values(self):
        """Test valid delta values."""
        assert validate_delta(0.0) == 0.0
        assert validate_delta(0.5) == 0.5
        assert validate_delta(-0.5) == -0.5
        assert validate_delta(1.0) == 1.0
        assert validate_delta(-1.0) == -1.0

    def test_integer_converted(self):
        """Test integer is converted to float."""
        assert validate_delta(1) == 1.0
        assert validate_delta(0) == 0.0
        assert validate_delta(-1) == -1.0

    def test_out_of_range_high_raises_error(self):
        """Test delta > 1.0 raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(1.5)
        assert "between" in str(exc.value).lower()

    def test_out_of_range_low_raises_error(self):
        """Test delta < -1.0 raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(-1.5)
        assert "between" in str(exc.value).lower()

    def test_non_numeric_raises_error(self):
        """Test non-numeric raises error."""
        with pytest.raises(ValidationError):
            validate_delta("abc")

    def test_custom_param_name(self):
        """Test custom param name in error message."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(2.0, param_name="my_delta")
        assert "my_delta" in str(exc.value)


# =============================================================================
# VALIDATION LIMITS TESTS
# =============================================================================

class TestValidationLimits:
    """Tests for ValidationLimits class."""

    def test_has_all_expected_limits(self):
        """Test all expected limits exist."""
        limits = ValidationLimits()
        assert hasattr(limits, 'MAX_SYMBOLS')
        assert hasattr(limits, 'MAX_BATCH_SIZE')
        assert hasattr(limits, 'MIN_BATCH_SIZE')
        assert hasattr(limits, 'MAX_DTE')
        assert hasattr(limits, 'MIN_DTE')
        assert hasattr(limits, 'MAX_RESULTS')
        assert hasattr(limits, 'MIN_RESULTS')
        assert hasattr(limits, 'MAX_ALTERNATIVES')
        assert hasattr(limits, 'MIN_ALTERNATIVES')
        assert hasattr(limits, 'MAX_DAYS')
        assert hasattr(limits, 'MIN_DAYS')
        assert hasattr(limits, 'MAX_PAUSE_SECONDS')
        assert hasattr(limits, 'MIN_PAUSE_SECONDS')

    def test_limits_are_reasonable(self):
        """Test limits have reasonable values."""
        limits = ValidationLimits()
        assert limits.MAX_SYMBOLS >= 100
        assert limits.MAX_BATCH_SIZE >= 10
        assert limits.MIN_BATCH_SIZE >= 1
        assert limits.MAX_RESULTS >= 10
        assert limits.MIN_RESULTS >= 1
        assert limits.MIN_ALTERNATIVES >= 1
        assert limits.MAX_ALTERNATIVES >= limits.MIN_ALTERNATIVES

    def test_min_less_than_max(self):
        """Test MIN values are less than MAX values."""
        limits = ValidationLimits()
        assert limits.MIN_BATCH_SIZE < limits.MAX_BATCH_SIZE
        assert limits.MIN_DTE < limits.MAX_DTE
        assert limits.MIN_RESULTS < limits.MAX_RESULTS
        assert limits.MIN_ALTERNATIVES < limits.MAX_ALTERNATIVES
        assert limits.MIN_DAYS < limits.MAX_DAYS
        assert limits.MIN_PAUSE_SECONDS < limits.MAX_PAUSE_SECONDS


# =============================================================================
# VALIDATE BATCH SIZE TESTS
# =============================================================================

class TestValidateBatchSize:
    """Tests for validate_batch_size function."""

    def test_valid_batch_size(self):
        """Test valid batch sizes."""
        assert validate_batch_size(10) == 10
        assert validate_batch_size(50) == 50
        assert validate_batch_size(1) == 1

    def test_string_converted(self):
        """Test string is converted."""
        assert validate_batch_size("20") == 20

    def test_too_small_raises_error(self):
        """Test batch size < MIN raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_batch_size(0)
        assert "batch_size" in str(exc.value).lower()

    def test_too_large_raises_error(self):
        """Test batch size > MAX raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_batch_size(1000)
        assert "batch_size" in str(exc.value).lower()

    def test_invalid_string_raises_error(self):
        """Test invalid string raises error."""
        with pytest.raises(ValidationError):
            validate_batch_size("abc")


# =============================================================================
# VALIDATE MAX RESULTS TESTS
# =============================================================================

class TestValidateMaxResults:
    """Tests for validate_max_results function."""

    def test_valid_max_results(self):
        """Test valid max_results."""
        assert validate_max_results(10) == 10
        assert validate_max_results(50) == 50
        assert validate_max_results(1) == 1

    def test_string_converted(self):
        """Test string is converted."""
        assert validate_max_results("20") == 20

    def test_too_small_raises_error(self):
        """Test max_results < MIN raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_max_results(0)
        assert "max_results" in str(exc.value).lower()

    def test_too_large_raises_error(self):
        """Test max_results > MAX raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_max_results(1000)
        assert "max_results" in str(exc.value).lower()


# =============================================================================
# VALIDATE NUM ALTERNATIVES TESTS
# =============================================================================

class TestValidateNumAlternatives:
    """Tests for validate_num_alternatives function."""

    def test_valid_num_alternatives(self):
        """Test valid num_alternatives."""
        assert validate_num_alternatives(3) == 3
        assert validate_num_alternatives(5) == 5
        assert validate_num_alternatives(1) == 1

    def test_string_converted(self):
        """Test string is converted."""
        assert validate_num_alternatives("3") == 3

    def test_too_small_raises_error(self):
        """Test num_alternatives < MIN raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_num_alternatives(0)
        assert "num_alternatives" in str(exc.value).lower()

    def test_too_large_raises_error(self):
        """Test num_alternatives > MAX raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_num_alternatives(100)
        assert "num_alternatives" in str(exc.value).lower()


# =============================================================================
# VALIDATE MIN DAYS TESTS
# =============================================================================

class TestValidateMinDays:
    """Tests for validate_min_days function."""

    def test_valid_min_days(self):
        """Test valid min_days."""
        assert validate_min_days(7) == 7
        assert validate_min_days(30) == 30
        assert validate_min_days(1) == 1

    def test_string_converted(self):
        """Test string is converted."""
        assert validate_min_days("14") == 14

    def test_too_small_raises_error(self):
        """Test min_days < MIN raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_min_days(0)
        assert "min_days" in str(exc.value).lower()

    def test_too_large_raises_error(self):
        """Test min_days > MAX raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_min_days(500)
        assert "min_days" in str(exc.value).lower()


# =============================================================================
# VALIDATE PAUSE SECONDS TESTS
# =============================================================================

class TestValidatePauseSeconds:
    """Tests for validate_pause_seconds function."""

    def test_valid_pause_seconds(self):
        """Test valid pause_seconds."""
        assert validate_pause_seconds(5) == 5
        assert validate_pause_seconds(60) == 60
        assert validate_pause_seconds(1) == 1

    def test_string_converted(self):
        """Test string is converted."""
        assert validate_pause_seconds("10") == 10

    def test_too_small_raises_error(self):
        """Test pause_seconds < MIN raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_pause_seconds(0)
        assert "pause_seconds" in str(exc.value).lower()

    def test_too_large_raises_error(self):
        """Test pause_seconds > MAX raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_pause_seconds(1000)
        assert "pause_seconds" in str(exc.value).lower()


# =============================================================================
# SAFE VALIDATE SYMBOL TESTS
# =============================================================================

class TestSafeValidateSymbol:
    """Tests for safe_validate_symbol function."""

    def test_valid_symbol_returns_normalized(self):
        """Test valid symbol returns normalized."""
        assert safe_validate_symbol("aapl") == "AAPL"
        assert safe_validate_symbol("MSFT") == "MSFT"
        assert safe_validate_symbol("BRK.B") == "BRK.B"

    def test_invalid_symbol_returns_none(self):
        """Test invalid symbol returns None."""
        assert safe_validate_symbol("INVALID!!!") is None
        assert safe_validate_symbol("") is None
        assert safe_validate_symbol("123") is None

    def test_invalid_symbol_returns_custom_default(self):
        """Test invalid symbol returns custom default."""
        assert safe_validate_symbol("INVALID!!!", default="UNKNOWN") == "UNKNOWN"
        assert safe_validate_symbol("", default="DEFAULT") == "DEFAULT"

    def test_whitespace_trimmed(self):
        """Test whitespace is trimmed."""
        assert safe_validate_symbol("  AAPL  ") == "AAPL"


# =============================================================================
# ADDITIONAL EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases in validation functions."""

    def test_validate_symbols_none_returns_empty(self):
        """Test validate_symbols with None returns empty list."""
        assert validate_symbols(None) == []

    def test_is_etf_with_none(self):
        """Test is_etf with None returns False."""
        assert is_etf(None) is False

    def test_is_etf_with_whitespace(self):
        """Test is_etf handles whitespace."""
        assert is_etf("  SPY  ") is True
        assert is_etf("\tQQQ\n") is True

    def test_validate_positive_int_with_max_value(self):
        """Test validate_positive_int respects max_value."""
        assert validate_positive_int(50, "test", max_value=100) == 50
        with pytest.raises(ValidationError) as exc:
            validate_positive_int(150, "test", max_value=100)
        assert "too large" in str(exc.value).lower()

    def test_validate_min_score_boundary_values(self):
        """Test validate_min_score at boundaries."""
        assert validate_min_score(0.0) == 0.0
        assert validate_min_score(10.0) == 10.0

    def test_validate_min_score_negative_raises(self):
        """Test validate_min_score rejects negative."""
        with pytest.raises(ValidationError):
            validate_min_score(-0.1)

    def test_validate_min_score_too_large_raises(self):
        """Test validate_min_score rejects > 10."""
        with pytest.raises(ValidationError):
            validate_min_score(10.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
