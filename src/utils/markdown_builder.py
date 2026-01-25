# OptionPlay - Markdown Builder
# ===============================
"""
Fluent Builder für konsistente Markdown-Formatierung.

Eliminiert Code-Duplizierung bei der Output-Generierung
und sorgt für einheitliches Styling.

Verwendung:
    from src.utils.markdown_builder import MarkdownBuilder, md
    
    # Fluent Interface
    output = (
        MarkdownBuilder()
        .h1("Scan Results")
        .kv("VIX", 18.5, fmt=".2f")
        .kv("Strategy", "STANDARD")
        .blank()
        .h2("Top Candidates")
        .table(["Symbol", "Score", "Price"], rows)
        .build()
    )
    
    # Oder mit Shortcut-Funktionen
    output = md.h1("Title") + md.kv("Key", "Value")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, List, Optional, Tuple, Union
from enum import Enum


class TableAlign(Enum):
    """Tabellen-Ausrichtung."""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass
class TableColumn:
    """Tabellenspalten-Definition."""
    header: str
    align: TableAlign = TableAlign.LEFT
    width: Optional[int] = None  # Min-Breite für Padding


class MarkdownBuilder:
    """
    Fluent Builder für Markdown-Output.
    
    Bietet konsistente Formatierung für:
    - Überschriften (h1-h4)
    - Key-Value-Paare
    - Tabellen
    - Listen (bullet, numbered)
    - Status-Indikatoren
    - Warnings/Hints
    
    Beispiel:
        result = (
            MarkdownBuilder()
            .h1("Analysis: AAPL")
            .kv("Price", 175.50, fmt="$.2f")
            .kv("Change", 2.5, fmt="+.1f%")
            .blank()
            .h2("Technical Indicators")
            .bullet("RSI: 35.2")
            .bullet("MACD: Bullish crossover")
            .build()
        )
    """
    
    def __init__(self):
        self._lines: List[str] = []
    
    # =========================================================================
    # HEADINGS
    # =========================================================================
    
    def h1(self, text: str) -> MarkdownBuilder:
        """Level 1 Heading."""
        self._lines.append(f"# {text}")
        return self
    
    def h2(self, text: str) -> MarkdownBuilder:
        """Level 2 Heading."""
        self._lines.append(f"## {text}")
        return self
    
    def h3(self, text: str) -> MarkdownBuilder:
        """Level 3 Heading."""
        self._lines.append(f"### {text}")
        return self
    
    def h4(self, text: str) -> MarkdownBuilder:
        """Level 4 Heading."""
        self._lines.append(f"#### {text}")
        return self
    
    # =========================================================================
    # TEXT & FORMATTING
    # =========================================================================
    
    def text(self, content: str) -> MarkdownBuilder:
        """Plain text."""
        self._lines.append(content)
        return self
    
    def blank(self) -> MarkdownBuilder:
        """Blank line."""
        self._lines.append("")
        return self
    
    def hr(self) -> MarkdownBuilder:
        """Horizontal rule."""
        self._lines.append("---")
        return self
    
    def bold(self, text: str) -> str:
        """Return bold text (inline helper)."""
        return f"**{text}**"
    
    def italic(self, text: str) -> str:
        """Return italic text (inline helper)."""
        return f"*{text}*"
    
    def code(self, text: str) -> str:
        """Return inline code (inline helper)."""
        return f"`{text}`"
    
    def link(self, text: str, url: str) -> str:
        """Return markdown link (inline helper)."""
        return f"[{text}]({url})"
    
    # =========================================================================
    # KEY-VALUE PAIRS
    # =========================================================================
    
    def kv(
        self,
        key: str,
        value: Any,
        fmt: Optional[str] = None,
        prefix: str = "",
        suffix: str = "",
        na_value: str = "N/A"
    ) -> MarkdownBuilder:
        """
        Key-Value Paar auf einer Zeile.
        
        Args:
            key: Label
            value: Wert (wird formatiert)
            fmt: Format-String (z.B. ".2f", "$,.0f", "+.1f%")
            prefix: Prefix vor dem Wert (z.B. "$")
            suffix: Suffix nach dem Wert (z.B. "%")
            na_value: Anzeige wenn value None
            
        Beispiele:
            .kv("Price", 175.50, fmt="$.2f")     → **Price:** $175.50
            .kv("Change", 2.5, fmt="+.1f", suffix="%") → **Change:** +2.5%
            .kv("Volume", 1500000, fmt=",.0f")  → **Volume:** 1,500,000
        """
        if value is None:
            formatted = na_value
        elif fmt:
            # Smart format detection
            if fmt.startswith("$"):
                # Currency: "$,.2f" or "$.2f"
                actual_fmt = fmt[1:]
                formatted = f"${value:{actual_fmt}}"
            elif fmt.endswith("%"):
                # Percentage
                actual_fmt = fmt[:-1]
                formatted = f"{value:{actual_fmt}}%"
            else:
                formatted = f"{prefix}{value:{fmt}}{suffix}"
        else:
            formatted = f"{prefix}{value}{suffix}"
        
        self._lines.append(f"**{key}:** {formatted}")
        return self
    
    def kv_line(
        self,
        key: str,
        value: Any,
        fmt: Optional[str] = None,
        na_value: str = "N/A"
    ) -> MarkdownBuilder:
        """Key-Value als Listenpunkt."""
        if value is None:
            formatted = na_value
        elif fmt:
            if fmt.startswith("$"):
                actual_fmt = fmt[1:]
                formatted = f"${value:{actual_fmt}}"
            elif fmt.endswith("%"):
                actual_fmt = fmt[:-1]
                formatted = f"{value:{actual_fmt}}%"
            else:
                formatted = f"{value:{fmt}}"
        else:
            formatted = str(value)
        
        self._lines.append(f"- **{key}:** {formatted}")
        return self
    
    def kv_inline(
        self,
        *pairs: Tuple[str, Any],
        separator: str = " | "
    ) -> MarkdownBuilder:
        """
        Mehrere Key-Value-Paare auf einer Zeile.
        
        Beispiel:
            .kv_inline(("VIX", 18.5), ("Strategy", "STANDARD"))
            → **VIX:** 18.5 | **Strategy:** STANDARD
        """
        parts = [f"**{k}:** {v}" for k, v in pairs]
        self._lines.append(separator.join(parts))
        return self
    
    # =========================================================================
    # LISTS
    # =========================================================================
    
    def bullet(self, text: str) -> MarkdownBuilder:
        """Bullet point."""
        self._lines.append(f"- {text}")
        return self
    
    def bullets(self, items: List[str]) -> MarkdownBuilder:
        """Multiple bullet points."""
        for item in items:
            self._lines.append(f"- {item}")
        return self
    
    def numbered(self, text: str, number: Optional[int] = None) -> MarkdownBuilder:
        """Numbered list item."""
        # Auto-number wenn nicht angegeben
        if number is None:
            # Zähle vorherige numbered items
            count = sum(1 for line in self._lines if line and line[0].isdigit())
            number = count + 1
        self._lines.append(f"{number}. {text}")
        return self
    
    def numbered_list(self, items: List[str]) -> MarkdownBuilder:
        """Numbered list."""
        for i, item in enumerate(items, 1):
            self._lines.append(f"{i}. {item}")
        return self
    
    # =========================================================================
    # TABLES
    # =========================================================================
    
    def table(
        self,
        headers: List[str],
        rows: List[List[Any]],
        alignments: Optional[List[TableAlign]] = None
    ) -> MarkdownBuilder:
        """
        Markdown-Tabelle.
        
        Args:
            headers: Spaltenüberschriften
            rows: Datenzeilen (Liste von Listen)
            alignments: Ausrichtung pro Spalte
            
        Beispiel:
            .table(
                ["Symbol", "Score", "Price"],
                [
                    ["AAPL", 7.5, "$175.50"],
                    ["MSFT", 6.8, "$380.20"],
                ]
            )
        """
        if not headers:
            return self
        
        # Header
        self._lines.append("| " + " | ".join(headers) + " |")
        
        # Separator mit Alignment
        separators = []
        for i, header in enumerate(headers):
            align = alignments[i] if alignments and i < len(alignments) else TableAlign.LEFT
            if align == TableAlign.LEFT:
                separators.append("---")
            elif align == TableAlign.CENTER:
                separators.append(":---:")
            elif align == TableAlign.RIGHT:
                separators.append("---:")
        self._lines.append("| " + " | ".join(separators) + " |")
        
        # Rows
        for row in rows:
            cells = [str(cell) if cell is not None else "-" for cell in row]
            self._lines.append("| " + " | ".join(cells) + " |")
        
        return self
    
    def table_row(self, cells: List[Any]) -> MarkdownBuilder:
        """Einzelne Tabellenzeile (für inkrementellen Aufbau)."""
        cell_strs = [str(cell) if cell is not None else "-" for cell in cells]
        self._lines.append("| " + " | ".join(cell_strs) + " |")
        return self
    
    # =========================================================================
    # STATUS INDICATORS
    # =========================================================================
    
    def status_ok(self, text: str) -> MarkdownBuilder:
        """Success status."""
        self._lines.append(f"✅ {text}")
        return self
    
    def status_warning(self, text: str) -> MarkdownBuilder:
        """Warning status."""
        self._lines.append(f"⚠️ {text}")
        return self
    
    def status_error(self, text: str) -> MarkdownBuilder:
        """Error status."""
        self._lines.append(f"❌ {text}")
        return self
    
    def status_info(self, text: str) -> MarkdownBuilder:
        """Info status."""
        self._lines.append(f"ℹ️ {text}")
        return self
    
    def status(
        self,
        condition: bool,
        ok_text: str,
        fail_text: str
    ) -> MarkdownBuilder:
        """Conditional status."""
        if condition:
            return self.status_ok(ok_text)
        else:
            return self.status_warning(fail_text)
        return self
    
    # =========================================================================
    # SPECIAL SECTIONS
    # =========================================================================
    
    def warning_box(self, text: str) -> MarkdownBuilder:
        """Warning box."""
        self._lines.append("")
        self._lines.append(f"⚠️ **Warning:** {text}")
        return self
    
    def hint(self, text: str) -> MarkdownBuilder:
        """Hint/Tip."""
        self._lines.append(f"*{text}*")
        return self
    
    def note(self, text: str) -> MarkdownBuilder:
        """Note."""
        self._lines.append(f"*Note: {text}*")
        return self
    
    def quote(self, text: str) -> MarkdownBuilder:
        """Blockquote."""
        self._lines.append(f"> {text}")
        return self
    
    def code_block(self, code: str, language: str = "") -> MarkdownBuilder:
        """Code block."""
        self._lines.append(f"```{language}")
        self._lines.append(code)
        self._lines.append("```")
        return self
    
    # =========================================================================
    # CONDITIONAL
    # =========================================================================
    
    def if_true(
        self,
        condition: bool,
        callback: callable
    ) -> MarkdownBuilder:
        """
        Conditional content.
        
        Beispiel:
            .if_true(has_warnings, lambda b: b.h2("Warnings").bullets(warnings))
        """
        if condition:
            callback(self)
        return self
    
    def if_value(
        self,
        value: Any,
        callback: callable
    ) -> MarkdownBuilder:
        """
        Conditional auf Wert (nicht None/empty).
        
        Beispiel:
            .if_value(earnings_date, lambda b: b.kv("Earnings", earnings_date))
        """
        if value:
            callback(self)
        return self
    
    # =========================================================================
    # BUILD
    # =========================================================================
    
    def build(self) -> str:
        """Finales Markdown als String."""
        return "\n".join(self._lines)
    
    def __str__(self) -> str:
        """String representation."""
        return self.build()
    
    def __add__(self, other: Union[str, MarkdownBuilder]) -> MarkdownBuilder:
        """Concatenation support."""
        if isinstance(other, str):
            self._lines.append(other)
        elif isinstance(other, MarkdownBuilder):
            self._lines.extend(other._lines)
        return self


# =============================================================================
# SHORTCUT FUNCTIONS
# =============================================================================

class MarkdownShortcuts:
    """
    Statische Shortcut-Funktionen für schnelle Formatierung.
    
    Verwendung:
        from src.utils.markdown_builder import md
        
        output = md.h1("Title") + md.kv("Key", "Value")
    """
    
    @staticmethod
    def h1(text: str) -> str:
        return f"# {text}"
    
    @staticmethod
    def h2(text: str) -> str:
        return f"## {text}"
    
    @staticmethod
    def h3(text: str) -> str:
        return f"### {text}"
    
    @staticmethod
    def bold(text: str) -> str:
        return f"**{text}**"
    
    @staticmethod
    def italic(text: str) -> str:
        return f"*{text}*"
    
    @staticmethod
    def kv(key: str, value: Any, fmt: Optional[str] = None) -> str:
        if value is None:
            formatted = "N/A"
        elif fmt:
            if fmt.startswith("$"):
                formatted = f"${value:{fmt[1:]}}"
            elif fmt.endswith("%"):
                formatted = f"{value:{fmt[:-1]}}%"
            else:
                formatted = f"{value:{fmt}}"
        else:
            formatted = str(value)
        return f"**{key}:** {formatted}"
    
    @staticmethod
    def bullet(text: str) -> str:
        return f"- {text}"
    
    @staticmethod
    def ok(text: str) -> str:
        return f"✅ {text}"
    
    @staticmethod
    def warn(text: str) -> str:
        return f"⚠️ {text}"
    
    @staticmethod
    def error(text: str) -> str:
        return f"❌ {text}"


# Globale Shortcut-Instanz
md = MarkdownShortcuts()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def format_price(value: Optional[float], na: str = "N/A") -> str:
    """Formatiert Preis als $X.XX."""
    if value is None:
        return na
    return f"${value:.2f}"


def format_percent(value: Optional[float], na: str = "N/A", sign: bool = False) -> str:
    """Formatiert Prozent."""
    if value is None:
        return na
    if sign:
        return f"{value:+.1f}%"
    return f"{value:.1f}%"


def format_volume(value: Optional[int], na: str = "N/A") -> str:
    """Formatiert Volumen mit Tausender-Trennzeichen."""
    if value is None:
        return na
    return f"{value:,}"


def format_date(value: Optional[Union[date, datetime, str]], na: str = "N/A") -> str:
    """Formatiert Datum."""
    if value is None:
        return na
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return value.isoformat()


def truncate(text: str, max_len: int = 50, suffix: str = "...") -> str:
    """Kürzt Text auf max_len."""
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix
