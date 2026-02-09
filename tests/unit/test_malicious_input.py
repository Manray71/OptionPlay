#!/usr/bin/env python3
"""
F.1: Negative/Malicious Input Tests

Tests for security-critical input handling:
- SQL injection attempts in symbols and parameters
- XSS/markdown injection in string inputs
- Extreme numeric values (NaN, Inf, MAX_FLOAT)
- Unicode attacks in symbols
- Control characters and null bytes

Usage:
    pytest tests/unit/test_malicious_input.py -v
"""

import math
import sys
import pytest
from pathlib import Path

from src.utils.validation import (
    ValidationError,
    validate_symbol,
    validate_symbols,
    validate_dte,
    validate_dte_range,
    validate_delta,
    validate_right,
    validate_positive_int,
    validate_batch_size,
    validate_max_results,
    validate_min_score,
    validate_num_alternatives,
    validate_min_days,
    validate_pause_seconds,
    safe_validate_symbol,
    is_valid_symbol,
)


# =============================================================================
# SQL INJECTION IN SYMBOLS
# =============================================================================

class TestSQLInjectionSymbols:
    """F.1a: SQL injection attempts via symbol parameters."""

    SQL_INJECTION_PAYLOADS = [
        "'; DROP TABLE options_prices;--",
        "AAPL' OR '1'='1",
        "AAPL'; DELETE FROM daily_prices;--",
        "UNION SELECT * FROM sqlite_master--",
        "1; ATTACH DATABASE '/tmp/evil.db' AS evil;--",
        "AAPL'/**/OR/**/1=1--",
        "' UNION SELECT password FROM users--",
        "AAPL\"; DROP TABLE vix_data;--",
        "AAPL') OR ('1'='1",
        "'; PRAGMA table_info(symbol_fundamentals);--",
    ]

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_rejected_by_validate_symbol(self, payload):
        """SQL injection payloads must be rejected by validate_symbol."""
        with pytest.raises(ValidationError):
            validate_symbol(payload)

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_rejected_by_validate_symbols(self, payload):
        """SQL injection in symbol list must be rejected."""
        with pytest.raises(ValidationError):
            validate_symbols([payload])

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_skipped_when_lenient(self, payload):
        """SQL injection in symbol list should be silently skipped with skip_invalid."""
        result = validate_symbols([payload], skip_invalid=True)
        assert result == []

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_safe_validate(self, payload):
        """safe_validate_symbol returns None for injection attempts."""
        assert safe_validate_symbol(payload) is None

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_is_valid_false(self, payload):
        """is_valid_symbol returns False for injection attempts."""
        assert is_valid_symbol(payload) is False


# =============================================================================
# XSS / MARKDOWN INJECTION
# =============================================================================

class TestXSSMarkdownInjection:
    """F.1b: XSS and markdown injection attempts."""

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)",
        "<svg onload=alert(1)>",
        "'\"><script>alert(1)</script>",
        "<iframe src='evil.com'>",
    ]

    MARKDOWN_INJECTION_PAYLOADS = [
        "[Click me](javascript:alert(1))",
        "![](https://evil.com/track.png)",
        "```\n<script>alert(1)</script>\n```",
        "# FAKE HEADER\n---\nMalicious content",
    ]

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_xss_rejected_by_validate_symbol(self, payload):
        """XSS payloads must be rejected as invalid symbols."""
        with pytest.raises(ValidationError):
            validate_symbol(payload)

    @pytest.mark.parametrize("payload", MARKDOWN_INJECTION_PAYLOADS)
    def test_markdown_injection_rejected(self, payload):
        """Markdown injection payloads must be rejected as invalid symbols."""
        with pytest.raises(ValidationError):
            validate_symbol(payload)


# =============================================================================
# UNICODE ATTACKS
# =============================================================================

class TestUnicodeAttacks:
    """F.1c: Unicode-based attack vectors in symbols."""

    UNICODE_PAYLOADS = [
        "\u0000AAPL",             # Null byte prefix
        "AAPL\u0000",             # Null byte suffix
        "\u200BAAPL",             # Zero-width space
        "A\u0301APL",             # Combining accent (Á)
        "\uFEFFAPL",              # BOM (byte order mark)
        "\u202EAAPL",             # RTL override
        "AAPL\u200D",             # Zero-width joiner
        "\U0001F4B0",             # Money bag emoji
        "ААPL",                   # Cyrillic А (looks like Latin A)
        "ΑAPL",                   # Greek Alpha (looks like Latin A)
        "ＡＰＬ",                # Fullwidth Latin letters
    ]

    @pytest.mark.parametrize("payload", UNICODE_PAYLOADS)
    def test_unicode_attack_rejected(self, payload):
        """Unicode attack vectors must be rejected as invalid symbols."""
        with pytest.raises(ValidationError):
            validate_symbol(payload)

    def test_ascii_only_symbols_accepted(self):
        """Only plain ASCII symbols should be accepted."""
        assert validate_symbol("AAPL") == "AAPL"
        assert validate_symbol("MSFT") == "MSFT"
        assert validate_symbol("BRK.B") == "BRK.B"

    def test_mixed_valid_and_unicode_batch(self):
        """Batch with Unicode mixed in should skip invalid."""
        result = validate_symbols(
            ["AAPL", "\u200BMSFT", "GOOGL", "ААPL"],
            skip_invalid=True
        )
        assert "AAPL" in result
        assert "GOOGL" in result
        # Unicode-tainted symbols should be skipped
        assert len(result) <= 3


# =============================================================================
# EXTREME NUMERIC VALUES
# =============================================================================

class TestExtremeNumericValues:
    """F.1d: Extreme numeric values in parameter validation."""

    def test_dte_nan(self):
        """NaN should be rejected for DTE."""
        with pytest.raises((ValidationError, ValueError)):
            validate_dte(float('nan'))

    def test_dte_inf(self):
        """Infinity should be rejected for DTE."""
        with pytest.raises((ValidationError, OverflowError)):
            validate_dte(float('inf'))

    def test_dte_negative_inf(self):
        """Negative infinity should be rejected for DTE."""
        with pytest.raises((ValidationError, OverflowError)):
            validate_dte(float('-inf'))

    def test_dte_max_float(self):
        """sys.float_info.max should be rejected for DTE."""
        with pytest.raises((ValidationError, OverflowError)):
            validate_dte(sys.float_info.max)

    def test_delta_nan(self):
        """NaN should be rejected for delta."""
        with pytest.raises(ValidationError):
            validate_delta(float('nan'))

    def test_delta_inf(self):
        """Infinity should be rejected for delta."""
        with pytest.raises(ValidationError):
            validate_delta(float('inf'))

    def test_delta_negative_inf(self):
        """Negative infinity should be rejected for delta."""
        with pytest.raises(ValidationError):
            validate_delta(float('-inf'))

    def test_min_score_nan(self):
        """NaN should be rejected for min_score."""
        with pytest.raises((ValidationError, ValueError)):
            validate_min_score(float('nan'))

    def test_min_score_inf(self):
        """Infinity should be rejected for min_score."""
        with pytest.raises(ValidationError):
            validate_min_score(float('inf'))

    def test_batch_size_max_int(self):
        """Very large int should be rejected for batch_size."""
        with pytest.raises(ValidationError):
            validate_batch_size(2**31)

    def test_max_results_max_int(self):
        """Very large int should be rejected for max_results."""
        with pytest.raises(ValidationError):
            validate_max_results(2**31)

    def test_dte_boundary_zero(self):
        """DTE=0 should be handled (negative check only)."""
        # validate_dte allows 0 (no negative check)
        result = validate_dte(0)
        assert result == 0

    def test_dte_boundary_730(self):
        """DTE=730 is the maximum allowed."""
        result = validate_dte(730)
        assert result == 730

    def test_dte_boundary_731(self):
        """DTE=731 exceeds the maximum."""
        with pytest.raises(ValidationError):
            validate_dte(731)

    def test_delta_boundary_minus_one(self):
        """Delta=-1.0 is allowed."""
        result = validate_delta(-1.0)
        assert result == -1.0

    def test_delta_boundary_plus_one(self):
        """Delta=1.0 is allowed."""
        result = validate_delta(1.0)
        assert result == 1.0

    def test_delta_boundary_slightly_over(self):
        """Delta=1.001 should be rejected."""
        with pytest.raises(ValidationError):
            validate_delta(1.001)

    def test_delta_boundary_slightly_under(self):
        """Delta=-1.001 should be rejected."""
        with pytest.raises(ValidationError):
            validate_delta(-1.001)


# =============================================================================
# CONTROL CHARACTERS
# =============================================================================

class TestControlCharacters:
    """F.1e: Control characters and special bytes."""

    # Control chars that create invalid symbols (not stripped by .strip())
    NON_STRIPPABLE_CONTROL_CHARS = [
        "\x00",       # Null byte
        "\x01",       # SOH
        "\x07",       # Bell
        "\x08",       # Backspace
        "\x1b[2J",    # ANSI escape (clear screen)
    ]

    # Control chars that ARE stripped by Python's str.strip()
    STRIPPABLE_WHITESPACE = [
        "\x0b",       # Vertical tab
        "\x0c",       # Form feed
        "\r\n",       # CRLF
        "\t",         # Tab
    ]

    @pytest.mark.parametrize("char", NON_STRIPPABLE_CONTROL_CHARS)
    def test_control_char_in_symbol_rejected(self, char):
        """Non-strippable control characters in symbols must be rejected."""
        with pytest.raises(ValidationError):
            validate_symbol(f"AAPL{char}")

    @pytest.mark.parametrize("char", NON_STRIPPABLE_CONTROL_CHARS)
    def test_control_char_prefix_rejected(self, char):
        """Non-strippable control characters as symbol prefix must be rejected."""
        with pytest.raises(ValidationError):
            validate_symbol(f"{char}AAPL")

    @pytest.mark.parametrize("ws", STRIPPABLE_WHITESPACE)
    def test_strippable_whitespace_stripped(self, ws):
        """Whitespace chars stripped by .strip() result in valid symbol."""
        # These are stripped, leaving 'AAPL' which is valid
        result = validate_symbol(f"AAPL{ws}")
        assert result == "AAPL"

    def test_newline_in_symbol(self):
        """Newline should be rejected."""
        with pytest.raises(ValidationError):
            validate_symbol("AAPL\nMSFT")


# =============================================================================
# OVERSIZED INPUTS
# =============================================================================

class TestOversizedInputs:
    """F.1f: Oversized and boundary-length inputs."""

    def test_symbol_max_length_10(self):
        """Symbols longer than 10 chars should be rejected."""
        with pytest.raises(ValidationError, match="too long"):
            validate_symbol("A" * 11)

    def test_symbol_at_max_length(self):
        """10-char symbol passes length check but may fail pattern."""
        # 10 chars is accepted by length check, but 6+ alpha fails SYMBOL_PATTERN_EXTENDED
        with pytest.raises(ValidationError):
            validate_symbol("A" * 10)

    def test_symbols_list_deduplication(self):
        """Duplicate symbols should be deduplicated."""
        result = validate_symbols(["AAPL", "AAPL", "AAPL"])
        assert result == ["AAPL"]

    def test_dte_range_inverted(self):
        """Inverted DTE range should be rejected."""
        with pytest.raises(ValidationError, match="cannot be greater"):
            validate_dte_range(100, 50)

    def test_empty_symbol(self):
        """Empty string should be rejected."""
        with pytest.raises(ValidationError, match="empty"):
            validate_symbol("")

    def test_whitespace_only_symbol(self):
        """Whitespace-only symbol should be rejected."""
        with pytest.raises(ValidationError, match="empty"):
            validate_symbol("   ")

    def test_very_long_string_as_symbol(self):
        """Very long string (1000 chars) should be rejected."""
        with pytest.raises(ValidationError):
            validate_symbol("A" * 1000)


# =============================================================================
# TYPE CONFUSION ATTACKS
# =============================================================================

class TestTypeConfusion:
    """F.1g: Passing wrong types to validation functions."""

    def test_symbol_none(self):
        """None should be rejected for symbol."""
        with pytest.raises(ValidationError, match="None"):
            validate_symbol(None)

    def test_symbol_int(self):
        """Integer should be rejected for symbol."""
        with pytest.raises(ValidationError, match="string"):
            validate_symbol(123)

    def test_symbol_float(self):
        """Float should be rejected for symbol."""
        with pytest.raises(ValidationError, match="string"):
            validate_symbol(3.14)

    def test_symbol_list(self):
        """List should be rejected for symbol."""
        with pytest.raises(ValidationError, match="string"):
            validate_symbol(["AAPL"])

    def test_symbol_dict(self):
        """Dict should be rejected for symbol."""
        with pytest.raises(ValidationError, match="string"):
            validate_symbol({"symbol": "AAPL"})

    def test_symbol_bool(self):
        """Boolean should be rejected for symbol."""
        with pytest.raises(ValidationError, match="string"):
            validate_symbol(True)

    def test_symbols_not_list(self):
        """Non-list passed to validate_symbols should be rejected."""
        with pytest.raises(ValidationError, match="list"):
            validate_symbols("AAPL")

    def test_symbols_set(self):
        """Set should be rejected for validate_symbols."""
        with pytest.raises(ValidationError, match="list"):
            validate_symbols({"AAPL", "MSFT"})

    def test_symbols_dict(self):
        """Dict should be rejected for validate_symbols."""
        with pytest.raises(ValidationError, match="list"):
            validate_symbols({"AAPL": 1})

    def test_dte_string_injection(self):
        """String with SQL injection in DTE should be caught."""
        with pytest.raises(ValidationError):
            validate_dte("60; DROP TABLE--")

    def test_dte_none(self):
        """None should be rejected for DTE."""
        with pytest.raises(ValidationError):
            validate_dte(None)

    def test_dte_float_truncation(self):
        """Float DTE should be truncated to int."""
        # validate_dte tries int() conversion, which truncates
        result = validate_dte(60.9)
        assert result == 60

    def test_delta_string(self):
        """String should be rejected for delta."""
        with pytest.raises(ValidationError, match="numeric"):
            validate_delta("not_a_number")

    def test_delta_none(self):
        """None should be rejected for delta."""
        with pytest.raises(ValidationError, match="numeric"):
            validate_delta(None)

    def test_right_int(self):
        """Integer should be rejected for right."""
        with pytest.raises(ValidationError, match="string"):
            validate_right(80)

    def test_right_none(self):
        """None should be rejected for right."""
        with pytest.raises(ValidationError, match="string"):
            validate_right(None)

    def test_batch_size_string_injection(self):
        """String injection in batch_size should be caught."""
        with pytest.raises(ValidationError):
            validate_batch_size("10; DROP TABLE--")

    def test_batch_size_none(self):
        """None should be rejected for batch_size."""
        with pytest.raises(ValidationError):
            validate_batch_size(None)

    def test_batch_size_float(self):
        """Float should be truncated for batch_size."""
        result = validate_batch_size(50.7)
        assert result == 50

    def test_max_results_none(self):
        """None should be rejected for max_results."""
        with pytest.raises(ValidationError):
            validate_max_results(None)

    def test_min_score_string(self):
        """Non-numeric string should be rejected for min_score."""
        with pytest.raises(ValidationError):
            validate_min_score("abc")

    def test_min_score_none(self):
        """None should be rejected for min_score."""
        with pytest.raises(ValidationError):
            validate_min_score(None)

    def test_positive_int_negative(self):
        """Negative value should be rejected for positive_int."""
        with pytest.raises(ValidationError, match="positive"):
            validate_positive_int(-5, "test_param")

    def test_positive_int_zero(self):
        """Zero should be rejected for positive_int."""
        with pytest.raises(ValidationError, match="positive"):
            validate_positive_int(0, "test_param")

    def test_positive_int_exceeds_max(self):
        """Value exceeding max should be rejected."""
        with pytest.raises(ValidationError, match="too large"):
            validate_positive_int(200, "test_param", max_value=100)

    def test_num_alternatives_string(self):
        """Non-numeric string should be rejected for num_alternatives."""
        with pytest.raises(ValidationError):
            validate_num_alternatives("abc")

    def test_min_days_zero(self):
        """Zero should be rejected for min_days (min is 1)."""
        with pytest.raises(ValidationError):
            validate_min_days(0)

    def test_pause_seconds_zero(self):
        """Zero should be rejected for pause_seconds (min is 1)."""
        with pytest.raises(ValidationError):
            validate_pause_seconds(0)

    def test_pause_seconds_over_max(self):
        """Over-max pause_seconds should be rejected."""
        with pytest.raises(ValidationError):
            validate_pause_seconds(301)


# =============================================================================
# PARAMETER BOUNDARY ATTACKS
# =============================================================================

class TestParameterBoundaries:
    """F.1h: Parameter boundary edge cases."""

    def test_batch_size_min_boundary(self):
        """batch_size=1 is the minimum."""
        assert validate_batch_size(1) == 1

    def test_batch_size_max_boundary(self):
        """batch_size=100 is the maximum."""
        assert validate_batch_size(100) == 100

    def test_batch_size_below_min(self):
        """batch_size=0 is below minimum."""
        with pytest.raises(ValidationError):
            validate_batch_size(0)

    def test_batch_size_above_max(self):
        """batch_size=101 is above maximum."""
        with pytest.raises(ValidationError):
            validate_batch_size(101)

    def test_max_results_min_boundary(self):
        """max_results=1 is the minimum."""
        assert validate_max_results(1) == 1

    def test_max_results_max_boundary(self):
        """max_results=100 is the maximum."""
        assert validate_max_results(100) == 100

    def test_min_score_zero(self):
        """min_score=0.0 is allowed."""
        assert validate_min_score(0.0) == 0.0

    def test_min_score_ten(self):
        """min_score=10.0 is allowed."""
        assert validate_min_score(10.0) == 10.0

    def test_min_score_negative(self):
        """Negative min_score should be rejected."""
        with pytest.raises(ValidationError):
            validate_min_score(-0.1)

    def test_min_score_over_ten(self):
        """min_score > 10.0 should be rejected."""
        with pytest.raises(ValidationError):
            validate_min_score(10.1)

    def test_num_alternatives_min(self):
        """num_alternatives=1 is the minimum."""
        assert validate_num_alternatives(1) == 1

    def test_num_alternatives_max(self):
        """num_alternatives=10 is the maximum."""
        assert validate_num_alternatives(10) == 10

    def test_min_days_min(self):
        """min_days=1 is the minimum."""
        assert validate_min_days(1) == 1

    def test_min_days_max(self):
        """min_days=365 is the maximum."""
        assert validate_min_days(365) == 365

    def test_pause_seconds_min(self):
        """pause_seconds=1 is the minimum."""
        assert validate_pause_seconds(1) == 1

    def test_pause_seconds_max(self):
        """pause_seconds=300 is the maximum."""
        assert validate_pause_seconds(300) == 300

    def test_string_numeric_coercion_valid(self):
        """Valid numeric strings should be coerced."""
        assert validate_dte("60") == 60
        assert validate_batch_size("50") == 50
        assert validate_min_score("5.5") == 5.5

    def test_string_numeric_coercion_invalid(self):
        """Invalid numeric strings should raise."""
        with pytest.raises(ValidationError):
            validate_dte("not_a_number")
        with pytest.raises(ValidationError):
            validate_batch_size("abc")
        with pytest.raises(ValidationError):
            validate_min_score("xyz")
