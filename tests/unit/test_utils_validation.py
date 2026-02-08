# OptionPlay - Comprehensive Validation Tests
# ============================================
"""
Comprehensive unit tests for src/utils/validation.py.

Tests cover:
- validate_symbol function with all edge cases
- validate_symbols for batch validation
- validate_dte and validate_dte_range for DTE parameters
- validate_delta for delta values
- validate_right for put/call options
- validate_positive_int for generic integer validation
- MCP endpoint validations (batch_size, max_results, min_score, etc.)
- Convenience functions (safe_validate_symbol, is_valid_symbol, is_etf)
- ValidationError exception class
- ValidationLimits constants
- Symbol pattern constants
"""

import pytest
import re
from unittest.mock import patch

from src.utils.validation import (
    # Main validation functions
    ValidationError,
    validate_symbol,
    validate_symbols,
    validate_dte,
    validate_dte_range,
    validate_delta,
    validate_right,
    validate_positive_int,
    # MCP endpoint validations
    ValidationLimits,
    validate_batch_size,
    validate_max_results,
    validate_min_score,
    validate_num_alternatives,
    validate_min_days,
    validate_pause_seconds,
    # Convenience functions
    safe_validate_symbol,
    is_valid_symbol,
    is_etf,
    # Constants
    SYMBOL_PATTERN,
    SYMBOL_PATTERN_EXTENDED,
    INDEX_SYMBOLS,
    ETF_SYMBOLS,
)


# =============================================================================
# VALIDATION ERROR TESTS
# =============================================================================


class TestValidationError:
    """Tests for ValidationError exception class."""

    def test_is_value_error_subclass(self):
        """ValidationError should be a subclass of ValueError."""
        assert issubclass(ValidationError, ValueError)

    def test_can_be_raised(self):
        """ValidationError can be raised with a message."""
        with pytest.raises(ValidationError) as exc:
            raise ValidationError("Test error message")
        assert "Test error message" in str(exc.value)

    def test_can_be_caught_as_value_error(self):
        """ValidationError can be caught as ValueError."""
        with pytest.raises(ValueError):
            raise ValidationError("Test")

    def test_empty_message(self):
        """ValidationError can be raised with empty message."""
        with pytest.raises(ValidationError):
            raise ValidationError("")


# =============================================================================
# VALIDATE SYMBOL TESTS
# =============================================================================


class TestValidateSymbolBasic:
    """Basic tests for validate_symbol function."""

    def test_valid_single_letter_symbol(self):
        """Single letter symbols are valid (e.g., A, F)."""
        assert validate_symbol("A") == "A"
        assert validate_symbol("F") == "F"

    def test_valid_two_letter_symbol(self):
        """Two letter symbols are valid."""
        assert validate_symbol("GM") == "GM"
        assert validate_symbol("GE") == "GE"

    def test_valid_three_letter_symbol(self):
        """Three letter symbols are valid."""
        assert validate_symbol("IBM") == "IBM"
        assert validate_symbol("AMD") == "AMD"

    def test_valid_four_letter_symbol(self):
        """Four letter symbols are valid."""
        assert validate_symbol("AAPL") == "AAPL"
        assert validate_symbol("MSFT") == "MSFT"
        assert validate_symbol("TSLA") == "TSLA"

    def test_valid_five_letter_symbol(self):
        """Five letter symbols are valid."""
        assert validate_symbol("GOOGL") == "GOOGL"
        assert validate_symbol("AMZN") == "AMZN"[:5]  # Just AMZN is 4 letters
        assert validate_symbol("NVDA") == "NVDA"[:4]  # 4 letters


class TestValidateSymbolNormalization:
    """Tests for symbol normalization in validate_symbol."""

    def test_lowercase_to_uppercase(self):
        """Lowercase symbols are converted to uppercase."""
        assert validate_symbol("aapl") == "AAPL"
        assert validate_symbol("msft") == "MSFT"
        assert validate_symbol("googl") == "GOOGL"

    def test_mixed_case_to_uppercase(self):
        """Mixed case symbols are converted to uppercase."""
        assert validate_symbol("AaPl") == "AAPL"
        assert validate_symbol("MsFt") == "MSFT"
        assert validate_symbol("gOoGl") == "GOOGL"

    def test_leading_whitespace_stripped(self):
        """Leading whitespace is stripped."""
        assert validate_symbol("  AAPL") == "AAPL"
        assert validate_symbol("\tMSFT") == "MSFT"
        assert validate_symbol("\nGOOGL") == "GOOGL"

    def test_trailing_whitespace_stripped(self):
        """Trailing whitespace is stripped."""
        assert validate_symbol("AAPL  ") == "AAPL"
        assert validate_symbol("MSFT\t") == "MSFT"
        assert validate_symbol("GOOGL\n") == "GOOGL"

    def test_surrounding_whitespace_stripped(self):
        """Both leading and trailing whitespace is stripped."""
        assert validate_symbol("  AAPL  ") == "AAPL"
        assert validate_symbol("\t MSFT \t") == "MSFT"
        assert validate_symbol("\n  GOOGL  \n") == "GOOGL"


class TestValidateSymbolClassShares:
    """Tests for class share symbols (e.g., BRK.A, BRK.B)."""

    def test_valid_class_a_share(self):
        """Class A shares (BRK.A) are valid."""
        assert validate_symbol("BRK.A") == "BRK.A"

    def test_valid_class_b_share(self):
        """Class B shares (BRK.B) are valid."""
        assert validate_symbol("BRK.B") == "BRK.B"

    def test_lowercase_class_share(self):
        """Lowercase class shares are normalized."""
        assert validate_symbol("brk.a") == "BRK.A"
        assert validate_symbol("brk.b") == "BRK.B"


class TestValidateSymbolIndexSymbols:
    """Tests for index symbol handling."""

    def test_vix_symbol_allowed_by_default(self):
        """VIX index symbol is allowed by default."""
        assert validate_symbol("VIX") == "VIX"

    def test_spx_symbol_allowed_by_default(self):
        """SPX index symbol is allowed by default."""
        assert validate_symbol("SPX") == "SPX"

    def test_ndx_symbol_allowed_by_default(self):
        """NDX index symbol is allowed by default."""
        assert validate_symbol("NDX") == "NDX"

    def test_dji_symbol_allowed_by_default(self):
        """DJI index symbol is allowed by default."""
        assert validate_symbol("DJI") == "DJI"

    def test_rut_symbol_allowed_by_default(self):
        """RUT index symbol is allowed by default."""
        assert validate_symbol("RUT") == "RUT"

    def test_index_symbols_with_allow_index_false(self):
        """Index symbols still pass pattern check when allow_index=False."""
        # These symbols match the pattern, so they pass
        assert validate_symbol("VIX", allow_index=False) == "VIX"
        assert validate_symbol("SPX", allow_index=False) == "SPX"


class TestValidateSymbolStrictMode:
    """Tests for strict mode in validate_symbol."""

    def test_strict_mode_accepts_standard_symbols(self):
        """Strict mode accepts standard 1-5 letter symbols."""
        assert validate_symbol("A", strict=True) == "A"
        assert validate_symbol("AAPL", strict=True) == "AAPL"
        assert validate_symbol("GOOGL", strict=True) == "GOOGL"

    def test_strict_mode_accepts_class_shares(self):
        """Strict mode accepts class share symbols."""
        assert validate_symbol("BRK.A", strict=True) == "BRK.A"
        assert validate_symbol("BRK.B", strict=True) == "BRK.B"

    def test_non_strict_accepts_six_letter_symbols(self):
        """Non-strict mode accepts 6 letter symbols."""
        assert validate_symbol("GOOGLL", strict=False) == "GOOGLL"

    def test_strict_rejects_six_letter_symbols(self):
        """Strict mode rejects 6 letter symbols."""
        with pytest.raises(ValidationError):
            validate_symbol("GOOGLL", strict=True)


class TestValidateSymbolErrors:
    """Tests for error cases in validate_symbol."""

    def test_none_raises_validation_error(self):
        """None raises ValidationError with appropriate message."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(None)
        assert "cannot be None" in str(exc.value)

    def test_integer_raises_validation_error(self):
        """Integer raises ValidationError with appropriate message."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(123)
        assert "must be string" in str(exc.value)
        assert "int" in str(exc.value)

    def test_float_raises_validation_error(self):
        """Float raises ValidationError with appropriate message."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(123.45)
        assert "must be string" in str(exc.value)
        assert "float" in str(exc.value)

    def test_list_raises_validation_error(self):
        """List raises ValidationError with appropriate message."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(["AAPL"])
        assert "must be string" in str(exc.value)
        assert "list" in str(exc.value)

    def test_dict_raises_validation_error(self):
        """Dict raises ValidationError with appropriate message."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol({"symbol": "AAPL"})
        assert "must be string" in str(exc.value)
        assert "dict" in str(exc.value)

    def test_empty_string_raises_validation_error(self):
        """Empty string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("")
        assert "cannot be empty" in str(exc.value)

    def test_whitespace_only_raises_validation_error(self):
        """Whitespace-only string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("   ")
        assert "cannot be empty" in str(exc.value)

    def test_tab_only_raises_validation_error(self):
        """Tab-only string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("\t")
        assert "cannot be empty" in str(exc.value)

    def test_newline_only_raises_validation_error(self):
        """Newline-only string raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("\n")
        assert "cannot be empty" in str(exc.value)

    def test_symbol_too_long_raises_validation_error(self):
        """Symbol > 10 chars raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("VERYLONGSYMBOL")
        assert "too long" in str(exc.value)
        assert "14" in str(exc.value)  # Length of VERYLONGSYMBOL

    def test_exactly_11_chars_too_long(self):
        """Symbol of exactly 11 chars is too long."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("AAAAAAAAAAAA"[:11])  # 11 A's
        assert "too long" in str(exc.value)


class TestValidateSymbolInvalidFormats:
    """Tests for invalid symbol formats."""

    def test_numeric_only_invalid(self):
        """Numeric-only symbols are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("12345")
        assert "Invalid symbol format" in str(exc.value)

    def test_starts_with_number_invalid(self):
        """Symbols starting with number are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("1AAPL")
        assert "Invalid symbol format" in str(exc.value)

    def test_contains_number_invalid(self):
        """Symbols containing numbers are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("AAPL1")
        assert "Invalid symbol format" in str(exc.value)

    def test_special_char_exclamation_invalid(self):
        """Symbols with exclamation mark are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("AAPL!")
        assert "Invalid symbol format" in str(exc.value)

    def test_special_char_at_invalid(self):
        """Symbols with @ are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("@AAPL")
        assert "Invalid symbol format" in str(exc.value)

    def test_special_char_dollar_invalid(self):
        """Symbols with $ are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("AAPL$")
        assert "Invalid symbol format" in str(exc.value)

    def test_special_char_hash_invalid(self):
        """Symbols with # are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("#AAPL")
        assert "Invalid symbol format" in str(exc.value)

    def test_space_in_middle_invalid(self):
        """Symbols with space in middle are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("AA PL")
        assert "Invalid symbol format" in str(exc.value)

    def test_multiple_dots_invalid(self):
        """Symbols with multiple dots are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("A.B.C")
        assert "Invalid symbol format" in str(exc.value)

    def test_trailing_dot_invalid(self):
        """Symbols with trailing dot are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol("AAPL.")
        assert "Invalid symbol format" in str(exc.value)

    def test_leading_dot_invalid(self):
        """Symbols with leading dot are invalid."""
        with pytest.raises(ValidationError) as exc:
            validate_symbol(".AAPL")
        assert "Invalid symbol format" in str(exc.value)


# =============================================================================
# VALIDATE SYMBOLS (LIST) TESTS
# =============================================================================


class TestValidateSymbolsBasic:
    """Basic tests for validate_symbols function."""

    def test_empty_list_returns_empty(self):
        """Empty list returns empty list."""
        assert validate_symbols([]) == []

    def test_none_returns_empty(self):
        """None returns empty list."""
        assert validate_symbols(None) == []

    def test_single_symbol_list(self):
        """Single symbol list is validated."""
        result = validate_symbols(["AAPL"])
        assert result == ["AAPL"]

    def test_multiple_symbols_list(self):
        """Multiple symbols list is validated."""
        result = validate_symbols(["AAPL", "MSFT", "GOOGL"])
        assert result == ["AAPL", "MSFT", "GOOGL"]

    def test_tuple_accepted(self):
        """Tuple input is accepted."""
        result = validate_symbols(("AAPL", "MSFT"))
        assert "AAPL" in result
        assert "MSFT" in result


class TestValidateSymbolsNormalization:
    """Tests for normalization in validate_symbols."""

    def test_lowercase_normalized(self):
        """Lowercase symbols are normalized to uppercase."""
        result = validate_symbols(["aapl", "msft", "googl"])
        assert result == ["AAPL", "MSFT", "GOOGL"]

    def test_mixed_case_normalized(self):
        """Mixed case symbols are normalized."""
        result = validate_symbols(["AaPl", "MsFt"])
        assert result == ["AAPL", "MSFT"]


class TestValidateSymbolsDeduplication:
    """Tests for deduplication in validate_symbols."""

    def test_exact_duplicates_removed(self):
        """Exact duplicates are removed."""
        result = validate_symbols(["AAPL", "AAPL", "AAPL"])
        assert result == ["AAPL"]
        assert len(result) == 1

    def test_case_different_duplicates_removed(self):
        """Case-different duplicates are removed after normalization."""
        result = validate_symbols(["AAPL", "aapl", "AaPl"])
        assert result == ["AAPL"]
        assert len(result) == 1

    def test_order_preserved(self):
        """Order of first occurrence is preserved."""
        result = validate_symbols(["MSFT", "AAPL", "msft", "GOOGL"])
        assert result == ["MSFT", "AAPL", "GOOGL"]


class TestValidateSymbolsSkipInvalid:
    """Tests for skip_invalid mode in validate_symbols."""

    def test_skip_invalid_true_skips_bad_symbols(self):
        """skip_invalid=True skips invalid symbols without error."""
        result = validate_symbols(
            ["AAPL", "INVALID!!!", "MSFT"],
            skip_invalid=True
        )
        assert "AAPL" in result
        assert "MSFT" in result
        assert "INVALID!!!" not in result
        assert len(result) == 2

    def test_skip_invalid_false_raises_error(self):
        """skip_invalid=False raises ValidationError on bad symbol."""
        with pytest.raises(ValidationError):
            validate_symbols(["AAPL", "INVALID!!!", "MSFT"], skip_invalid=False)

    def test_skip_invalid_default_is_false(self):
        """Default skip_invalid is False."""
        with pytest.raises(ValidationError):
            validate_symbols(["AAPL", "INVALID!!!", "MSFT"])

    def test_skip_invalid_skips_multiple_bad_symbols(self):
        """skip_invalid skips multiple bad symbols."""
        result = validate_symbols(
            ["AAPL", "BAD1!", "MSFT", "BAD2@", "GOOGL"],
            skip_invalid=True
        )
        assert result == ["AAPL", "MSFT", "GOOGL"]


class TestValidateSymbolsErrors:
    """Tests for error cases in validate_symbols."""

    def test_string_input_raises_error(self):
        """String input raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbols("AAPL")
        assert "must be list" in str(exc.value)

    def test_dict_input_raises_error(self):
        """Dict input raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbols({"AAPL": 1})
        assert "must be list" in str(exc.value)

    def test_set_input_raises_error(self):
        """Set input raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_symbols({"AAPL", "MSFT"})
        assert "must be list" in str(exc.value)


class TestValidateSymbolsWithFlags:
    """Tests for validate_symbols with allow_index and strict flags."""

    def test_allow_index_passed_through(self):
        """allow_index flag is passed to validate_symbol."""
        result = validate_symbols(["VIX", "SPX"], allow_index=True)
        assert "VIX" in result
        assert "SPX" in result

    def test_strict_mode_passed_through(self):
        """strict flag is passed to validate_symbol."""
        # Standard symbols should work
        result = validate_symbols(["AAPL", "MSFT"], strict=True)
        assert result == ["AAPL", "MSFT"]


# =============================================================================
# VALIDATE DTE TESTS
# =============================================================================


class TestValidateDteBasic:
    """Basic tests for validate_dte function."""

    def test_valid_dte_zero(self):
        """Zero DTE is valid."""
        assert validate_dte(0) == 0

    def test_valid_dte_positive(self):
        """Positive DTE values are valid."""
        assert validate_dte(30) == 30
        assert validate_dte(45) == 45
        assert validate_dte(60) == 60

    def test_valid_dte_max(self):
        """Maximum DTE (730) is valid."""
        assert validate_dte(730) == 730

    def test_valid_dte_common_values(self):
        """Common DTE values are valid."""
        assert validate_dte(7) == 7
        assert validate_dte(14) == 14
        assert validate_dte(21) == 21
        assert validate_dte(30) == 30
        assert validate_dte(45) == 45
        assert validate_dte(60) == 60
        assert validate_dte(90) == 90


class TestValidateDteConversion:
    """Tests for type conversion in validate_dte."""

    def test_string_to_int_conversion(self):
        """String DTE is converted to int."""
        assert validate_dte("30") == 30
        assert validate_dte("45") == 45

    def test_string_with_leading_zeros(self):
        """String with leading zeros is converted."""
        assert validate_dte("030") == 30

    def test_float_string_rejected(self):
        """Float string raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte("30.5")


class TestValidateDteErrors:
    """Tests for error cases in validate_dte."""

    def test_negative_raises_error(self):
        """Negative DTE raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(-1)
        assert "cannot be negative" in str(exc.value)

    def test_negative_large_raises_error(self):
        """Large negative DTE raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(-100)
        assert "cannot be negative" in str(exc.value)

    def test_too_large_raises_error(self):
        """DTE > 730 raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(731)
        assert "too large" in str(exc.value)
        assert "730" in str(exc.value)

    def test_invalid_string_raises_error(self):
        """Invalid string raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte("abc")

    def test_empty_string_raises_error(self):
        """Empty string raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte("")

    def test_none_raises_error(self):
        """None raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte(None)


class TestValidateDteParamName:
    """Tests for custom param_name in validate_dte."""

    def test_default_param_name(self):
        """Default param_name is 'DTE'."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(-1)
        assert "DTE" in str(exc.value)

    def test_custom_param_name_in_error(self):
        """Custom param_name appears in error message."""
        with pytest.raises(ValidationError) as exc:
            validate_dte(-1, param_name="expiry_days")
        assert "expiry_days" in str(exc.value)


# =============================================================================
# VALIDATE DTE RANGE TESTS
# =============================================================================


class TestValidateDteRangeBasic:
    """Basic tests for validate_dte_range function."""

    def test_valid_range(self):
        """Valid range returns tuple."""
        result = validate_dte_range(30, 60)
        assert result == (30, 60)

    def test_equal_min_max(self):
        """Equal min and max is valid."""
        result = validate_dte_range(30, 30)
        assert result == (30, 30)

    def test_zero_min(self):
        """Zero min is valid."""
        result = validate_dte_range(0, 30)
        assert result == (0, 30)


class TestValidateDteRangeErrors:
    """Tests for error cases in validate_dte_range."""

    def test_inverted_range_raises_error(self):
        """Min > max raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_dte_range(60, 30)
        assert "cannot be greater" in str(exc.value)

    def test_negative_min_raises_error(self):
        """Negative min raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte_range(-1, 30)

    def test_too_large_max_raises_error(self):
        """Max > 730 raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_dte_range(30, 800)


# =============================================================================
# VALIDATE DELTA TESTS
# =============================================================================


class TestValidateDeltaBasic:
    """Basic tests for validate_delta function."""

    def test_valid_delta_zero(self):
        """Zero delta is valid."""
        assert validate_delta(0.0) == 0.0

    def test_valid_delta_positive(self):
        """Positive delta values are valid."""
        assert validate_delta(0.5) == 0.5
        assert validate_delta(0.25) == 0.25
        assert validate_delta(0.75) == 0.75

    def test_valid_delta_negative(self):
        """Negative delta values are valid."""
        assert validate_delta(-0.5) == -0.5
        assert validate_delta(-0.25) == -0.25
        assert validate_delta(-0.75) == -0.75

    def test_valid_delta_boundaries(self):
        """Boundary delta values are valid."""
        assert validate_delta(1.0) == 1.0
        assert validate_delta(-1.0) == -1.0


class TestValidateDeltaConversion:
    """Tests for type conversion in validate_delta."""

    def test_integer_to_float(self):
        """Integer is converted to float."""
        assert validate_delta(0) == 0.0
        assert validate_delta(1) == 1.0
        assert validate_delta(-1) == -1.0


class TestValidateDeltaErrors:
    """Tests for error cases in validate_delta."""

    def test_above_one_raises_error(self):
        """Delta > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(1.1)
        assert "between -1.0 and 1.0" in str(exc.value)

    def test_below_negative_one_raises_error(self):
        """Delta < -1.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(-1.1)
        assert "between -1.0 and 1.0" in str(exc.value)

    def test_non_numeric_raises_error(self):
        """Non-numeric raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_delta("abc")
        assert "must be numeric" in str(exc.value)

    def test_none_raises_error(self):
        """None raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_delta(None)


class TestValidateDeltaParamName:
    """Tests for custom param_name in validate_delta."""

    def test_default_param_name(self):
        """Default param_name is 'delta'."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(2.0)
        assert "delta" in str(exc.value)

    def test_custom_param_name_in_error(self):
        """Custom param_name appears in error message."""
        with pytest.raises(ValidationError) as exc:
            validate_delta(2.0, param_name="short_delta")
        assert "short_delta" in str(exc.value)


# =============================================================================
# VALIDATE RIGHT TESTS
# =============================================================================


class TestValidateRightPut:
    """Tests for Put option validation in validate_right."""

    def test_uppercase_p(self):
        """'P' is normalized to 'P'."""
        assert validate_right("P") == "P"

    def test_lowercase_p(self):
        """'p' is normalized to 'P'."""
        assert validate_right("p") == "P"

    def test_uppercase_put(self):
        """'PUT' is normalized to 'P'."""
        assert validate_right("PUT") == "P"

    def test_lowercase_put(self):
        """'put' is normalized to 'P'."""
        assert validate_right("put") == "P"

    def test_mixed_case_put(self):
        """'Put' is normalized to 'P'."""
        assert validate_right("Put") == "P"


class TestValidateRightCall:
    """Tests for Call option validation in validate_right."""

    def test_uppercase_c(self):
        """'C' is normalized to 'C'."""
        assert validate_right("C") == "C"

    def test_lowercase_c(self):
        """'c' is normalized to 'C'."""
        assert validate_right("c") == "C"

    def test_uppercase_call(self):
        """'CALL' is normalized to 'C'."""
        assert validate_right("CALL") == "C"

    def test_lowercase_call(self):
        """'call' is normalized to 'C'."""
        assert validate_right("call") == "C"

    def test_mixed_case_call(self):
        """'Call' is normalized to 'C'."""
        assert validate_right("Call") == "C"


class TestValidateRightWhitespace:
    """Tests for whitespace handling in validate_right."""

    def test_leading_whitespace(self):
        """Leading whitespace is stripped."""
        assert validate_right("  P") == "P"
        assert validate_right("  C") == "C"

    def test_trailing_whitespace(self):
        """Trailing whitespace is stripped."""
        assert validate_right("P  ") == "P"
        assert validate_right("C  ") == "C"

    def test_surrounding_whitespace(self):
        """Surrounding whitespace is stripped."""
        assert validate_right("  PUT  ") == "P"
        assert validate_right("  CALL  ") == "C"


class TestValidateRightErrors:
    """Tests for error cases in validate_right."""

    def test_invalid_single_letter(self):
        """Invalid single letter raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_right("X")
        assert "Invalid right" in str(exc.value)

    def test_invalid_word(self):
        """Invalid word raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_right("PUTS")
        assert "Invalid right" in str(exc.value)

    def test_empty_string_raises_error(self):
        """Empty string raises error."""
        with pytest.raises(ValidationError):
            validate_right("")

    def test_non_string_raises_error(self):
        """Non-string raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_right(123)
        assert "must be string" in str(exc.value)

    def test_none_raises_error(self):
        """None raises error."""
        with pytest.raises(ValidationError):
            validate_right(None)


# =============================================================================
# VALIDATE POSITIVE INT TESTS
# =============================================================================


class TestValidatePositiveIntBasic:
    """Basic tests for validate_positive_int function."""

    def test_valid_positive_values(self):
        """Positive values are valid."""
        assert validate_positive_int(1, "test") == 1
        assert validate_positive_int(5, "test") == 5
        assert validate_positive_int(100, "test") == 100
        assert validate_positive_int(1000, "test") == 1000

    def test_string_conversion(self):
        """String is converted to int."""
        assert validate_positive_int("5", "test") == 5
        assert validate_positive_int("100", "test") == 100


class TestValidatePositiveIntErrors:
    """Tests for error cases in validate_positive_int."""

    def test_zero_raises_error(self):
        """Zero raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_positive_int(0, "count")
        assert "must be positive" in str(exc.value)

    def test_negative_raises_error(self):
        """Negative raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_positive_int(-1, "count")
        assert "must be positive" in str(exc.value)

    def test_invalid_string_raises_error(self):
        """Invalid string raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_positive_int("abc", "count")


class TestValidatePositiveIntMaxValue:
    """Tests for max_value constraint in validate_positive_int."""

    def test_within_max_value(self):
        """Value within max_value is valid."""
        assert validate_positive_int(50, "test", max_value=100) == 50

    def test_equal_to_max_value(self):
        """Value equal to max_value is valid."""
        assert validate_positive_int(100, "test", max_value=100) == 100

    def test_exceeds_max_value(self):
        """Value exceeding max_value raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_positive_int(150, "count", max_value=100)
        assert "too large" in str(exc.value)
        assert "100" in str(exc.value)


# =============================================================================
# MCP ENDPOINT VALIDATION TESTS
# =============================================================================


class TestValidationLimitsConstants:
    """Tests for ValidationLimits constants."""

    def test_all_limits_exist(self):
        """All expected limits are defined."""
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

    def test_limits_are_integers(self):
        """All limits are integers."""
        limits = ValidationLimits()
        assert isinstance(limits.MAX_SYMBOLS, int)
        assert isinstance(limits.MAX_BATCH_SIZE, int)
        assert isinstance(limits.MIN_BATCH_SIZE, int)

    def test_min_less_than_max(self):
        """MIN values are less than MAX values."""
        limits = ValidationLimits()
        assert limits.MIN_BATCH_SIZE < limits.MAX_BATCH_SIZE
        assert limits.MIN_DTE < limits.MAX_DTE
        assert limits.MIN_RESULTS < limits.MAX_RESULTS
        assert limits.MIN_ALTERNATIVES < limits.MAX_ALTERNATIVES
        assert limits.MIN_DAYS < limits.MAX_DAYS
        assert limits.MIN_PAUSE_SECONDS < limits.MAX_PAUSE_SECONDS


class TestValidateBatchSize:
    """Tests for validate_batch_size function."""

    def test_valid_batch_sizes(self):
        """Valid batch sizes are accepted."""
        assert validate_batch_size(1) == 1
        assert validate_batch_size(10) == 10
        assert validate_batch_size(50) == 50
        assert validate_batch_size(100) == 100

    def test_string_conversion(self):
        """String is converted to int."""
        assert validate_batch_size("20") == 20

    def test_below_min_raises_error(self):
        """Batch size below minimum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_batch_size(0)
        assert "batch_size" in str(exc.value).lower()

    def test_above_max_raises_error(self):
        """Batch size above maximum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_batch_size(1000)
        assert "batch_size" in str(exc.value).lower()

    def test_invalid_string_raises_error(self):
        """Invalid string raises error."""
        with pytest.raises(ValidationError):
            validate_batch_size("abc")


class TestValidateMaxResults:
    """Tests for validate_max_results function."""

    def test_valid_max_results(self):
        """Valid max_results are accepted."""
        assert validate_max_results(1) == 1
        assert validate_max_results(10) == 10
        assert validate_max_results(50) == 50
        assert validate_max_results(100) == 100

    def test_string_conversion(self):
        """String is converted to int."""
        assert validate_max_results("20") == 20

    def test_below_min_raises_error(self):
        """max_results below minimum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_max_results(0)
        assert "max_results" in str(exc.value).lower()

    def test_above_max_raises_error(self):
        """max_results above maximum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_max_results(1000)
        assert "max_results" in str(exc.value).lower()


class TestValidateMinScore:
    """Tests for validate_min_score function."""

    def test_valid_scores(self):
        """Valid scores are accepted."""
        assert validate_min_score(0) == 0.0
        assert validate_min_score(5) == 5.0
        assert validate_min_score(7.5) == 7.5
        assert validate_min_score(10) == 10.0

    def test_float_scores(self):
        """Float scores are accepted."""
        assert validate_min_score(3.14) == 3.14
        assert validate_min_score(6.28) == 6.28

    def test_string_conversion(self):
        """String is converted to float."""
        assert validate_min_score("5.5") == 5.5

    def test_negative_raises_error(self):
        """Negative score raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_min_score(-0.1)
        assert "negative" in str(exc.value).lower()

    def test_above_max_raises_error(self):
        """Score above 10 raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_min_score(10.1)
        assert "10" in str(exc.value)

    def test_boundary_values(self):
        """Boundary values are valid."""
        assert validate_min_score(0.0) == 0.0
        assert validate_min_score(10.0) == 10.0


class TestValidateNumAlternatives:
    """Tests for validate_num_alternatives function."""

    def test_valid_values(self):
        """Valid num_alternatives are accepted."""
        assert validate_num_alternatives(1) == 1
        assert validate_num_alternatives(3) == 3
        assert validate_num_alternatives(5) == 5
        assert validate_num_alternatives(10) == 10

    def test_string_conversion(self):
        """String is converted to int."""
        assert validate_num_alternatives("3") == 3

    def test_below_min_raises_error(self):
        """num_alternatives below minimum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_num_alternatives(0)
        assert "num_alternatives" in str(exc.value).lower()

    def test_above_max_raises_error(self):
        """num_alternatives above maximum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_num_alternatives(100)
        assert "num_alternatives" in str(exc.value).lower()


class TestValidateMinDays:
    """Tests for validate_min_days function."""

    def test_valid_values(self):
        """Valid min_days are accepted."""
        assert validate_min_days(1) == 1
        assert validate_min_days(7) == 7
        assert validate_min_days(14) == 14
        assert validate_min_days(30) == 30

    def test_string_conversion(self):
        """String is converted to int."""
        assert validate_min_days("14") == 14

    def test_below_min_raises_error(self):
        """min_days below minimum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_min_days(0)
        assert "min_days" in str(exc.value).lower()

    def test_above_max_raises_error(self):
        """min_days above maximum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_min_days(500)
        assert "min_days" in str(exc.value).lower()


class TestValidatePauseSeconds:
    """Tests for validate_pause_seconds function."""

    def test_valid_values(self):
        """Valid pause_seconds are accepted."""
        assert validate_pause_seconds(1) == 1
        assert validate_pause_seconds(5) == 5
        assert validate_pause_seconds(60) == 60
        assert validate_pause_seconds(300) == 300

    def test_string_conversion(self):
        """String is converted to int."""
        assert validate_pause_seconds("10") == 10

    def test_below_min_raises_error(self):
        """pause_seconds below minimum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_pause_seconds(0)
        assert "pause_seconds" in str(exc.value).lower()

    def test_above_max_raises_error(self):
        """pause_seconds above maximum raises error."""
        with pytest.raises(ValidationError) as exc:
            validate_pause_seconds(1000)
        assert "pause_seconds" in str(exc.value).lower()


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestSafeValidateSymbol:
    """Tests for safe_validate_symbol function."""

    def test_valid_symbol_returns_normalized(self):
        """Valid symbol returns normalized version."""
        assert safe_validate_symbol("aapl") == "AAPL"
        assert safe_validate_symbol("MSFT") == "MSFT"
        assert safe_validate_symbol("BRK.B") == "BRK.B"

    def test_invalid_symbol_returns_none(self):
        """Invalid symbol returns None by default."""
        assert safe_validate_symbol("INVALID!!!") is None
        assert safe_validate_symbol("123") is None
        assert safe_validate_symbol("") is None

    def test_invalid_symbol_returns_default(self):
        """Invalid symbol returns custom default."""
        assert safe_validate_symbol("INVALID!!!", default="UNKNOWN") == "UNKNOWN"
        assert safe_validate_symbol("", default="DEFAULT") == "DEFAULT"
        assert safe_validate_symbol("123", default="ERROR") == "ERROR"

    def test_none_input_returns_default(self):
        """None input returns default."""
        # This would raise in validate_symbol, but safe version returns default
        result = safe_validate_symbol(None, default="FALLBACK")
        assert result == "FALLBACK"


class TestIsValidSymbol:
    """Tests for is_valid_symbol function."""

    def test_valid_symbols_return_true(self):
        """Valid symbols return True."""
        assert is_valid_symbol("AAPL") is True
        assert is_valid_symbol("MSFT") is True
        assert is_valid_symbol("BRK.A") is True
        assert is_valid_symbol("VIX") is True

    def test_lowercase_valid(self):
        """Lowercase valid symbols return True."""
        assert is_valid_symbol("aapl") is True
        assert is_valid_symbol("msft") is True

    def test_invalid_symbols_return_false(self):
        """Invalid symbols return False."""
        assert is_valid_symbol("INVALID!!!") is False
        assert is_valid_symbol("123") is False
        assert is_valid_symbol("") is False
        assert is_valid_symbol("@AAPL") is False


class TestIsEtf:
    """Tests for is_etf function."""

    def test_known_index_etfs(self):
        """Known index ETFs return True."""
        assert is_etf("SPY") is True
        assert is_etf("QQQ") is True
        assert is_etf("IWM") is True
        assert is_etf("DIA") is True

    def test_sector_spdr_etfs(self):
        """Sector SPDR ETFs return True."""
        assert is_etf("XLE") is True
        assert is_etf("XLK") is True
        assert is_etf("XLF") is True
        assert is_etf("XLV") is True
        assert is_etf("XLI") is True
        assert is_etf("XLY") is True
        assert is_etf("XLP") is True
        assert is_etf("XLB") is True
        assert is_etf("XLU") is True
        assert is_etf("XLRE") is True
        assert is_etf("XLC") is True

    def test_non_etfs_return_false(self):
        """Non-ETF symbols return False."""
        assert is_etf("AAPL") is False
        assert is_etf("MSFT") is False
        assert is_etf("GOOGL") is False
        assert is_etf("TSLA") is False

    def test_case_insensitive(self):
        """is_etf is case insensitive."""
        assert is_etf("spy") is True
        assert is_etf("Qqq") is True
        assert is_etf("iwm") is True

    def test_none_returns_false(self):
        """None returns False."""
        assert is_etf(None) is False

    def test_whitespace_handled(self):
        """Whitespace is handled."""
        assert is_etf("  SPY  ") is True
        assert is_etf("\tQQQ\n") is True


# =============================================================================
# PATTERN CONSTANT TESTS
# =============================================================================


class TestSymbolPatternConstant:
    """Tests for SYMBOL_PATTERN constant."""

    def test_pattern_is_compiled_regex(self):
        """SYMBOL_PATTERN is a compiled regex."""
        assert isinstance(SYMBOL_PATTERN, re.Pattern)

    def test_matches_single_letter(self):
        """Pattern matches single letter."""
        assert SYMBOL_PATTERN.match("A") is not None
        assert SYMBOL_PATTERN.match("F") is not None

    def test_matches_five_letters(self):
        """Pattern matches five letters."""
        assert SYMBOL_PATTERN.match("GOOGL") is not None
        assert SYMBOL_PATTERN.match("AAAAA") is not None

    def test_matches_class_shares(self):
        """Pattern matches class shares."""
        assert SYMBOL_PATTERN.match("BRK.A") is not None
        assert SYMBOL_PATTERN.match("BRK.B") is not None

    def test_rejects_six_letters(self):
        """Pattern rejects six letters."""
        assert SYMBOL_PATTERN.match("GOOGLL") is None
        assert SYMBOL_PATTERN.match("AAAAAA") is None

    def test_rejects_numbers(self):
        """Pattern rejects numbers."""
        assert SYMBOL_PATTERN.match("123") is None
        assert SYMBOL_PATTERN.match("AAPL1") is None


class TestSymbolPatternExtendedConstant:
    """Tests for SYMBOL_PATTERN_EXTENDED constant."""

    def test_pattern_is_compiled_regex(self):
        """SYMBOL_PATTERN_EXTENDED is a compiled regex."""
        assert isinstance(SYMBOL_PATTERN_EXTENDED, re.Pattern)

    def test_matches_standard_symbols(self):
        """Pattern matches standard symbols."""
        assert SYMBOL_PATTERN_EXTENDED.match("AAPL") is not None
        assert SYMBOL_PATTERN_EXTENDED.match("A") is not None

    def test_matches_six_letters(self):
        """Extended pattern matches six letters."""
        assert SYMBOL_PATTERN_EXTENDED.match("GOOGLL") is not None
        assert SYMBOL_PATTERN_EXTENDED.match("AAAAAA") is not None


class TestIndexSymbolsConstant:
    """Tests for INDEX_SYMBOLS constant."""

    def test_is_set(self):
        """INDEX_SYMBOLS is a set."""
        assert isinstance(INDEX_SYMBOLS, set)

    def test_contains_vix(self):
        """INDEX_SYMBOLS contains VIX."""
        assert "VIX" in INDEX_SYMBOLS

    def test_contains_spx(self):
        """INDEX_SYMBOLS contains SPX."""
        assert "SPX" in INDEX_SYMBOLS

    def test_contains_ndx(self):
        """INDEX_SYMBOLS contains NDX."""
        assert "NDX" in INDEX_SYMBOLS

    def test_contains_dji(self):
        """INDEX_SYMBOLS contains DJI."""
        assert "DJI" in INDEX_SYMBOLS

    def test_contains_rut(self):
        """INDEX_SYMBOLS contains RUT."""
        assert "RUT" in INDEX_SYMBOLS


class TestEtfSymbolsConstant:
    """Tests for ETF_SYMBOLS constant."""

    def test_is_set(self):
        """ETF_SYMBOLS is a set."""
        assert isinstance(ETF_SYMBOLS, set)

    def test_contains_index_etfs(self):
        """ETF_SYMBOLS contains index ETFs."""
        assert "SPY" in ETF_SYMBOLS
        assert "QQQ" in ETF_SYMBOLS
        assert "IWM" in ETF_SYMBOLS
        assert "DIA" in ETF_SYMBOLS

    def test_contains_all_sector_spdrs(self):
        """ETF_SYMBOLS contains all 11 sector SPDRs."""
        sector_spdrs = ["XLE", "XLK", "XLF", "XLV", "XLI",
                        "XLY", "XLP", "XLB", "XLU", "XLRE", "XLC"]
        for spdr in sector_spdrs:
            assert spdr in ETF_SYMBOLS, f"{spdr} missing from ETF_SYMBOLS"

    def test_has_expected_count(self):
        """ETF_SYMBOLS has expected number of entries."""
        # 4 index ETFs + 11 sector SPDRs + 2 thematic (ARKK, SMH) = 17
        assert len(ETF_SYMBOLS) == 17


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestValidationIntegration:
    """Integration tests for validation functions."""

    def test_validate_symbols_uses_validate_symbol(self):
        """validate_symbols uses validate_symbol internally."""
        # If validate_symbol fails, validate_symbols should fail
        with pytest.raises(ValidationError):
            validate_symbols(["AAPL", "INVALID!!!"], skip_invalid=False)

    def test_safe_validate_symbol_catches_validation_error(self):
        """safe_validate_symbol catches ValidationError from validate_symbol."""
        # This should not raise, even though validate_symbol would
        result = safe_validate_symbol("INVALID!!!")
        assert result is None

    def test_is_valid_symbol_uses_validate_symbol(self):
        """is_valid_symbol uses validate_symbol internally."""
        # Valid for validate_symbol should be valid for is_valid_symbol
        assert is_valid_symbol("AAPL") is True
        # Invalid for validate_symbol should be False for is_valid_symbol
        assert is_valid_symbol("INVALID!!!") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
