# Tests für MarkdownBuilder
# ==========================
"""
Comprehensive tests for the MarkdownBuilder utility class.

Run with: pytest tests/test_markdown_builder.py -v
"""

import pytest
from datetime import date

from src.utils.markdown_builder import (
    MarkdownBuilder,
    md,
    TableAlign,
    format_price,
    format_percent,
    format_volume,
    format_date,
    truncate,
)


class TestMarkdownBuilderHeadings:
    """Tests für Headings."""
    
    def test_h1(self):
        result = MarkdownBuilder().h1("Title").build()
        assert result == "# Title"
    
    def test_h2(self):
        result = MarkdownBuilder().h2("Section").build()
        assert result == "## Section"
    
    def test_h3(self):
        result = MarkdownBuilder().h3("Subsection").build()
        assert result == "### Subsection"
    
    def test_h4(self):
        result = MarkdownBuilder().h4("Minor").build()
        assert result == "#### Minor"
    
    def test_multiple_headings(self):
        result = (
            MarkdownBuilder()
            .h1("Title")
            .h2("Section")
            .h3("Subsection")
            .build()
        )
        lines = result.split("\n")
        assert lines[0] == "# Title"
        assert lines[1] == "## Section"
        assert lines[2] == "### Subsection"


class TestMarkdownBuilderKeyValue:
    """Tests für Key-Value-Formatierung."""
    
    def test_kv_basic(self):
        result = MarkdownBuilder().kv("Name", "Value").build()
        assert result == "**Name:** Value"
    
    def test_kv_with_number(self):
        result = MarkdownBuilder().kv("Score", 7.5).build()
        assert result == "**Score:** 7.5"
    
    def test_kv_with_format(self):
        result = MarkdownBuilder().kv("Price", 175.567, fmt=".2f").build()
        assert result == "**Price:** 175.57"
    
    def test_kv_currency_format(self):
        result = MarkdownBuilder().kv("Price", 175.5, fmt="$.2f").build()
        assert result == "**Price:** $175.50"
    
    def test_kv_percent_format(self):
        result = MarkdownBuilder().kv("Change", 2.5, fmt=".1f%").build()
        assert result == "**Change:** 2.5%"
    
    def test_kv_with_prefix_suffix(self):
        result = MarkdownBuilder().kv("Value", 100, prefix="~", suffix=" units").build()
        assert result == "**Value:** ~100 units"
    
    def test_kv_none_value(self):
        result = MarkdownBuilder().kv("Missing", None).build()
        assert result == "**Missing:** N/A"
    
    def test_kv_none_custom_na(self):
        result = MarkdownBuilder().kv("Missing", None, na_value="-").build()
        assert result == "**Missing:** -"
    
    def test_kv_line(self):
        result = MarkdownBuilder().kv_line("Item", "Value").build()
        assert result == "- **Item:** Value"
    
    def test_kv_line_with_format(self):
        result = MarkdownBuilder().kv_line("Price", 99.99, fmt="$.2f").build()
        assert result == "- **Price:** $99.99"
    
    def test_kv_inline_two_pairs(self):
        result = MarkdownBuilder().kv_inline(("A", 1), ("B", 2)).build()
        assert result == "**A:** 1 | **B:** 2"
    
    def test_kv_inline_custom_separator(self):
        result = MarkdownBuilder().kv_inline(("X", "Y"), ("Z", "W"), separator=" / ").build()
        assert result == "**X:** Y / **Z:** W"


class TestMarkdownBuilderLists:
    """Tests für Listen."""
    
    def test_single_bullet(self):
        result = MarkdownBuilder().bullet("Item").build()
        assert result == "- Item"
    
    def test_bullets(self):
        result = MarkdownBuilder().bullets(["A", "B", "C"]).build()
        lines = result.split("\n")
        assert lines == ["- A", "- B", "- C"]
    
    def test_numbered_single(self):
        result = MarkdownBuilder().numbered("First", 1).build()
        assert result == "1. First"
    
    def test_numbered_list(self):
        result = MarkdownBuilder().numbered_list(["One", "Two", "Three"]).build()
        lines = result.split("\n")
        assert lines == ["1. One", "2. Two", "3. Three"]
    
    def test_numbered_auto(self):
        """Test automatic numbering."""
        result = (
            MarkdownBuilder()
            .numbered("First")
            .numbered("Second")
            .numbered("Third")
            .build()
        )
        lines = result.split("\n")
        assert lines[0] == "1. First"
        assert lines[1] == "2. Second"
        assert lines[2] == "3. Third"


class TestMarkdownBuilderTables:
    """Tests für Tabellen."""
    
    def test_simple_table(self):
        result = MarkdownBuilder().table(
            ["Col1", "Col2"],
            [["A", "B"], ["C", "D"]]
        ).build()
        
        lines = result.split("\n")
        assert lines[0] == "| Col1 | Col2 |"
        assert lines[1] == "| --- | --- |"
        assert lines[2] == "| A | B |"
        assert lines[3] == "| C | D |"
    
    def test_table_with_none(self):
        result = MarkdownBuilder().table(
            ["A", "B"],
            [[None, "X"], ["Y", None]]
        ).build()
        
        assert "| - | X |" in result
        assert "| Y | - |" in result
    
    def test_table_alignment(self):
        result = MarkdownBuilder().table(
            ["Left", "Center", "Right"],
            [["a", "b", "c"]],
            alignments=[TableAlign.LEFT, TableAlign.CENTER, TableAlign.RIGHT]
        ).build()
        
        assert "| --- | :---: | ---: |" in result
    
    def test_table_row(self):
        b = MarkdownBuilder()
        b.text("| A | B |")
        b.text("| --- | --- |")
        b.table_row(["1", "2"])
        result = b.build()
        
        assert "| 1 | 2 |" in result
    
    def test_empty_table(self):
        result = MarkdownBuilder().table([], []).build()
        assert result == ""


class TestMarkdownBuilderStatus:
    """Tests für Status-Indikatoren."""
    
    def test_status_ok(self):
        result = MarkdownBuilder().status_ok("Success").build()
        assert result == "✅ Success"
    
    def test_status_warning(self):
        result = MarkdownBuilder().status_warning("Caution").build()
        assert result == "⚠️ Caution"
    
    def test_status_error(self):
        result = MarkdownBuilder().status_error("Failed").build()
        assert result == "❌ Failed"
    
    def test_status_info(self):
        result = MarkdownBuilder().status_info("Note").build()
        assert result == "ℹ️ Note"
    
    def test_status_conditional_true(self):
        result = MarkdownBuilder().status(True, "Passed", "Failed").build()
        assert "✅ Passed" in result
        assert "Failed" not in result
    
    def test_status_conditional_false(self):
        result = MarkdownBuilder().status(False, "Passed", "Failed").build()
        assert "⚠️ Failed" in result
        assert "Passed" not in result


class TestMarkdownBuilderSpecial:
    """Tests für spezielle Sektionen."""
    
    def test_blank(self):
        result = MarkdownBuilder().text("A").blank().text("B").build()
        lines = result.split("\n")
        assert lines[1] == ""
    
    def test_hr(self):
        result = MarkdownBuilder().hr().build()
        assert result == "---"
    
    def test_hint(self):
        result = MarkdownBuilder().hint("A tip").build()
        assert result == "*A tip*"
    
    def test_note(self):
        result = MarkdownBuilder().note("Important").build()
        assert result == "*Note: Important*"
    
    def test_warning_box(self):
        result = MarkdownBuilder().warning_box("Danger!").build()
        assert "⚠️ **Warning:** Danger!" in result
    
    def test_quote(self):
        result = MarkdownBuilder().quote("Famous words").build()
        assert result == "> Famous words"
    
    def test_code_block(self):
        result = MarkdownBuilder().code_block("x = 1", "python").build()
        lines = result.split("\n")
        assert lines[0] == "```python"
        assert lines[1] == "x = 1"
        assert lines[2] == "```"
    
    def test_code_block_no_language(self):
        result = MarkdownBuilder().code_block("code").build()
        assert "```\ncode\n```" in result


class TestMarkdownBuilderConditional:
    """Tests für bedingte Inhalte."""
    
    def test_if_true_met(self):
        result = (
            MarkdownBuilder()
            .if_true(True, lambda b: b.text("Shown"))
            .build()
        )
        assert "Shown" in result
    
    def test_if_true_not_met(self):
        result = (
            MarkdownBuilder()
            .if_true(False, lambda b: b.text("Hidden"))
            .build()
        )
        assert "Hidden" not in result
    
    def test_if_value_with_value(self):
        result = (
            MarkdownBuilder()
            .if_value("something", lambda b: b.text("Has value"))
            .build()
        )
        assert "Has value" in result
    
    def test_if_value_none(self):
        result = (
            MarkdownBuilder()
            .if_value(None, lambda b: b.text("Has value"))
            .build()
        )
        assert "Has value" not in result
    
    def test_if_value_empty_string(self):
        result = (
            MarkdownBuilder()
            .if_value("", lambda b: b.text("Has value"))
            .build()
        )
        assert "Has value" not in result


class TestMarkdownBuilderFluent:
    """Tests für Fluent Interface."""
    
    def test_chaining(self):
        result = (
            MarkdownBuilder()
            .h1("Title")
            .blank()
            .kv("Key", "Value")
            .blank()
            .h2("Section")
            .bullet("Item")
            .build()
        )
        
        assert "# Title" in result
        assert "**Key:** Value" in result
        assert "## Section" in result
        assert "- Item" in result
    
    def test_str_method(self):
        b = MarkdownBuilder().h1("Test")
        assert str(b) == "# Test"
    
    def test_add_string(self):
        b = MarkdownBuilder().h1("Title")
        b = b + "Extra line"
        assert "Extra line" in b.build()
    
    def test_add_builder(self):
        b1 = MarkdownBuilder().h1("Part 1")
        b2 = MarkdownBuilder().h2("Part 2")
        result = (b1 + b2).build()
        
        assert "# Part 1" in result
        assert "## Part 2" in result


class TestMarkdownShortcuts:
    """Tests für md Shortcuts."""
    
    def test_md_h1(self):
        assert md.h1("Title") == "# Title"
    
    def test_md_h2(self):
        assert md.h2("Section") == "## Section"
    
    def test_md_h3(self):
        assert md.h3("Sub") == "### Sub"
    
    def test_md_bold(self):
        assert md.bold("text") == "**text**"
    
    def test_md_italic(self):
        assert md.italic("text") == "*text*"
    
    def test_md_kv(self):
        assert md.kv("K", "V") == "**K:** V"
    
    def test_md_kv_format(self):
        assert md.kv("P", 1.5, fmt="$.2f") == "**P:** $1.50"
    
    def test_md_bullet(self):
        assert md.bullet("item") == "- item"
    
    def test_md_ok(self):
        assert md.ok("done") == "✅ done"
    
    def test_md_warn(self):
        assert md.warn("careful") == "⚠️ careful"
    
    def test_md_error(self):
        assert md.error("failed") == "❌ failed"


class TestHelperFunctions:
    """Tests für Helper-Funktionen."""
    
    def test_format_price_normal(self):
        assert format_price(175.5) == "$175.50"
    
    def test_format_price_round(self):
        assert format_price(100.0) == "$100.00"
    
    def test_format_price_none(self):
        assert format_price(None) == "N/A"
    
    def test_format_price_custom_na(self):
        assert format_price(None, na="-") == "-"
    
    def test_format_percent_normal(self):
        assert format_percent(5.5) == "5.5%"
    
    def test_format_percent_negative(self):
        assert format_percent(-3.2) == "-3.2%"
    
    def test_format_percent_with_sign_positive(self):
        assert format_percent(5.5, sign=True) == "+5.5%"
    
    def test_format_percent_with_sign_negative(self):
        assert format_percent(-3.2, sign=True) == "-3.2%"
    
    def test_format_percent_none(self):
        assert format_percent(None) == "N/A"
    
    def test_format_volume_normal(self):
        assert format_volume(1500000) == "1,500,000"
    
    def test_format_volume_small(self):
        assert format_volume(500) == "500"
    
    def test_format_volume_none(self):
        assert format_volume(None) == "N/A"
    
    def test_format_date_date_object(self):
        d = date(2025, 1, 15)
        assert format_date(d) == "2025-01-15"
    
    def test_format_date_string(self):
        assert format_date("2025-01-15") == "2025-01-15"
    
    def test_format_date_none(self):
        assert format_date(None) == "N/A"
    
    def test_truncate_short(self):
        assert truncate("Short", max_len=10) == "Short"
    
    def test_truncate_exact(self):
        assert truncate("Exact", max_len=5) == "Exact"
    
    def test_truncate_long(self):
        result = truncate("This is a long string", max_len=15)
        assert len(result) == 15
        assert result.endswith("...")
    
    def test_truncate_custom_suffix(self):
        result = truncate("Long string", max_len=8, suffix="…")
        assert result.endswith("…")
        assert len(result) == 8


class TestInlineHelpers:
    """Tests für inline Helper-Methoden."""
    
    def test_bold_inline(self):
        b = MarkdownBuilder()
        bold_text = b.bold("important")
        assert bold_text == "**important**"
    
    def test_italic_inline(self):
        b = MarkdownBuilder()
        italic_text = b.italic("emphasis")
        assert italic_text == "*emphasis*"
    
    def test_code_inline(self):
        b = MarkdownBuilder()
        code_text = b.code("variable")
        assert code_text == "`variable`"
    
    def test_link_inline(self):
        b = MarkdownBuilder()
        link_text = b.link("Click here", "https://example.com")
        assert link_text == "[Click here](https://example.com)"


class TestRealWorldExamples:
    """Tests mit realistischen Beispielen."""
    
    def test_scan_result_format(self):
        """Test typisches Scan-Ergebnis."""
        result = (
            MarkdownBuilder()
            .h1("Pullback Scan Results")
            .blank()
            .kv("VIX", 18.5, fmt=".2f")
            .kv("Strategy", "STANDARD")
            .blank()
            .kv("Scanned", "275 symbols")
            .kv("With Signals", 12)
            .blank()
            .h2("Top Candidates")
            .blank()
            .table(
                ["Symbol", "Score", "Price"],
                [
                    ["AAPL", "7.5", "$175.50"],
                    ["MSFT", "6.8", "$380.20"],
                ]
            )
            .build()
        )
        
        assert "# Pullback Scan Results" in result
        assert "**VIX:** 18.50" in result
        assert "| AAPL | 7.5 | $175.50 |" in result
    
    def test_quote_format(self):
        """Test Quote-Formatierung."""
        result = (
            MarkdownBuilder()
            .h1("Quote: AAPL")
            .blank()
            .kv_line("Last", 175.50, fmt="$.2f")
            .kv_line("Bid", 175.48, fmt="$.2f")
            .kv_line("Ask", 175.52, fmt="$.2f")
            .kv_line("Volume", "15,234,567")
            .build()
        )
        
        assert "# Quote: AAPL" in result
        assert "- **Last:** $175.50" in result
    
    def test_health_check_format(self):
        """Test Health-Check-Formatierung."""
        result = (
            MarkdownBuilder()
            .h1("Server Health")
            .blank()
            .kv("Version", "3.1.0")
            .kv("Status", "✅ Connected")
            .blank()
            .h2("Cache")
            .kv_line("Entries", "150/500")
            .kv_line("Hit Rate", "87%")
            .blank()
            .h2("Circuit Breaker")
            .status_ok("Closed")
            .build()
        )
        
        assert "# Server Health" in result
        assert "**Version:** 3.1.0" in result
        assert "- **Hit Rate:** 87%" in result
        assert "✅ Closed" in result
    
    def test_conditional_warnings(self):
        """Test bedingte Warnings."""
        warnings = ["Earnings too close", "Below SMA 200"]
        
        result = (
            MarkdownBuilder()
            .h1("Analysis: TSLA")
            .blank()
            .kv("Price", 250.00, fmt="$.2f")
            .blank()
            .if_true(
                len(warnings) > 0,
                lambda b: b.h2("⚠️ Warnings").bullets(warnings)
            )
            .build()
        )
        
        assert "## ⚠️ Warnings" in result
        assert "- Earnings too close" in result
        assert "- Below SMA 200" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
