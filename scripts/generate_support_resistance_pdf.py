#!/usr/bin/env python3
"""
Generates PDF documentation for Support/Resistance Trading Strategy.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from datetime import datetime
import os


def create_pdf():
    """Generate the Support/Resistance strategy documentation PDF."""

    # Output path
    output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_path = os.path.join(output_dir, "docs", "SUPPORT_RESISTANCE_STRATEGY.pdf")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    # Styles
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=30,
        textColor=colors.HexColor('#1a365d')
    )

    h1_style = ParagraphStyle(
        'CustomH1',
        parent=styles['Heading1'],
        fontSize=18,
        spaceBefore=20,
        spaceAfter=12,
        textColor=colors.HexColor('#2c5282')
    )

    h2_style = ParagraphStyle(
        'CustomH2',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=8,
        textColor=colors.HexColor('#2b6cb0')
    )

    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=8,
        alignment=TA_JUSTIFY,
        leading=14
    )

    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Code'],
        fontSize=9,
        backColor=colors.HexColor('#f7fafc'),
        borderColor=colors.HexColor('#e2e8f0'),
        borderWidth=1,
        borderPadding=8,
        spaceAfter=10
    )

    # Build content
    story = []

    # Title Page
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("Support & Resistance", title_style))
    story.append(Paragraph("Trading Strategy Documentation", styles['Heading2']))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(f"OptionPlay Trading System", body_style))
    story.append(Paragraph(f"Version 1.0 - {datetime.now().strftime('%B %Y')}", body_style))
    story.append(PageBreak())

    # Table of Contents
    story.append(Paragraph("Inhaltsverzeichnis", h1_style))
    toc_items = [
        "1. Grundkonzepte",
        "2. Psychologie der Preisniveaus",
        "3. Erkennung von Support/Resistance",
        "4. Trading-Strategien",
        "5. Implementierung im Code",
        "6. Optimierungsansätze"
    ]
    for item in toc_items:
        story.append(Paragraph(item, body_style))
    story.append(PageBreak())

    # Section 1: Grundkonzepte
    story.append(Paragraph("1. Grundkonzepte", h1_style))

    story.append(Paragraph("Was ist Support?", h2_style))
    story.append(Paragraph(
        "<b>Support (Unterstützung)</b> ist ein Preisniveau, bei dem die Nachfrage stark genug ist, "
        "um weitere Kursrückgänge zu stoppen. An diesem Level treten vermehrt Käufer auf, "
        "die bereit sind, die Aktie zu kaufen.",
        body_style
    ))

    story.append(Paragraph("Was ist Resistance?", h2_style))
    story.append(Paragraph(
        "<b>Resistance (Widerstand)</b> ist ein Preisniveau, bei dem das Angebot stark genug ist, "
        "um weitere Kursanstiege zu stoppen. Hier treten vermehrt Verkäufer auf, "
        "die ihre Positionen auflösen möchten.",
        body_style
    ))

    story.append(Spacer(1, 0.5*cm))

    # Visual representation as table
    chart_data = [
        ["Preis", "Kursverlauf", "Level"],
        ["$150", "    /\\      /\\    ", "← Resistance"],
        ["$140", "   /  \\    /  \\   ", ""],
        ["$130", "  /    \\  /    \\  ", ""],
        ["$120", " /      \\/      \\ ", "← Support"],
    ]

    chart_table = Table(chart_data, colWidths=[2*cm, 8*cm, 3*cm])
    chart_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Courier'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
    ]))
    story.append(chart_table)
    story.append(PageBreak())

    # Section 2: Psychologie
    story.append(Paragraph("2. Psychologie der Preisniveaus", h1_style))

    story.append(Paragraph("Warum funktionieren Support und Resistance?", h2_style))

    story.append(Paragraph("Bei Support-Levels:", h2_style))
    story.append(Paragraph(
        "• <b>Verpasste Käufer:</b> Investoren, die vorher nicht gekauft haben, warten auf dieses günstigere Niveau<br/>"
        "• <b>Shortseller:</b> Nehmen Gewinne mit und kaufen ihre Positionen zurück<br/>"
        "• <b>Institutionen:</b> Haben häufig Kauforders bei runden Zahlen platziert",
        body_style
    ))

    story.append(Paragraph("Bei Resistance-Levels:", h2_style))
    story.append(Paragraph(
        "• <b>Verlustpositionen:</b> Investoren, die 'im Minus' waren, wollen bei Break-Even aussteigen<br/>"
        "• <b>Gewinnmitnahmen:</b> Käufer realisieren ihre Gewinne<br/>"
        "• <b>Institutionen:</b> Haben Verkaufsorders platziert",
        body_style
    ))

    story.append(Paragraph("Selbsterfüllende Prophezeiung", h2_style))
    story.append(Paragraph(
        "Da viele Trader dieselben technischen Levels beobachten und danach handeln, "
        "werden diese Levels oft tatsächlich respektiert. Die kollektive Erwartung wird zur Realität.",
        body_style
    ))
    story.append(PageBreak())

    # Section 3: Erkennung
    story.append(Paragraph("3. Erkennung von Support/Resistance", h1_style))

    story.append(Paragraph("Kriterium 1: Anzahl der 'Touches'", h2_style))
    story.append(Paragraph(
        "Je öfter ein Preisniveau getestet wurde ohne zu brechen, desto stärker ist es. "
        "Ein Level mit 4+ Tests gilt als sehr stark.",
        body_style
    ))

    # Touch count table
    touch_data = [
        ["Anzahl Tests", "Stärke", "Zuverlässigkeit"],
        ["1-2", "Schwach", "Niedriger"],
        ["3-4", "Moderat", "Mittel"],
        ["5+", "Stark", "Hoch"],
    ]
    touch_table = Table(touch_data, colWidths=[4*cm, 4*cm, 4*cm])
    touch_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#fed7d7')),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#fefcbf')),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#c6f6d5')),
    ]))
    story.append(touch_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Kriterium 2: Volumen beim Touch", h2_style))
    story.append(Paragraph(
        "Hohes Handelsvolumen am Support zeigt, dass viele Käufer eingestiegen sind. "
        "Dies verstärkt die Bedeutung des Levels.",
        body_style
    ))

    story.append(Paragraph("Kriterium 3: Zeitlicher Abstand", h2_style))
    story.append(Paragraph(
        "Levels, die über Monate hinweg respektiert werden, sind stärker als kurzfristige Levels. "
        "Langfristige Levels haben mehr 'Marktgedächtnis'.",
        body_style
    ))

    story.append(Paragraph("Kriterium 4: Aktualität", h2_style))
    story.append(Paragraph(
        "Jüngere Tests sind relevanter als ältere. Ein Level, das vor einer Woche getestet wurde, "
        "ist aussagekräftiger als eines vor 6 Monaten.",
        body_style
    ))
    story.append(PageBreak())

    # Section 4: Trading-Strategien
    story.append(Paragraph("4. Trading-Strategien", h1_style))

    story.append(Paragraph("Bounce-Strategie (Mean Reversion)", h2_style))
    story.append(Paragraph(
        "<b>Konzept:</b> Kaufe, wenn der Preis zum Support zurückkehrt und abprallt.",
        body_style
    ))

    bounce_rules = [
        ["Komponente", "Regel"],
        ["Entry", "Kauf bei Bounce vom Support (Close > Low)"],
        ["Stop-Loss", "2-3% unter dem Support-Level"],
        ["Target", "Vorheriger Swing-High oder 2:1 Risk/Reward"],
        ["Bestätigung", "Bullish Candlestick + erhöhtes Volumen"],
    ]
    bounce_table = Table(bounce_rules, colWidths=[3.5*cm, 9*cm])
    bounce_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#38a169')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(bounce_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Breakout-Strategie (Trend Following)", h2_style))
    story.append(Paragraph(
        "<b>Konzept:</b> Kaufe, wenn Resistance durchbrochen wird (wird zum neuen Support).",
        body_style
    ))

    breakout_rules = [
        ["Komponente", "Regel"],
        ["Entry", "Kauf bei Breakout über Resistance mit Volumen"],
        ["Stop-Loss", "Unter dem durchbrochenen Resistance-Level"],
        ["Target", "Measured Move oder Trailing Stop"],
        ["Bestätigung", "Close über Resistance + Volumen-Spike"],
    ]
    breakout_table = Table(breakout_rules, colWidths=[3.5*cm, 9*cm])
    breakout_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3182ce')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(breakout_table)
    story.append(PageBreak())

    # Section 5: Implementierung
    story.append(Paragraph("5. Implementierung im Code", h1_style))

    story.append(Paragraph("Aktuelle Architektur", h2_style))
    story.append(Paragraph(
        "Die Support/Resistance-Erkennung ist in mehreren Modulen implementiert:",
        body_style
    ))

    modules = [
        ["Modul", "Funktion"],
        ["src/analyzers/bounce.py", "BounceAnalyzer mit _find_support_levels()"],
        ["src/analyzers/context.py", "AnalysisContext für gemeinsame Berechnungen"],
        ["src/indicators/support_resistance.py", "Dedizierte S/R-Funktionen"],
    ]
    modules_table = Table(modules, colWidths=[6*cm, 7*cm])
    modules_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (0, -1), 'Courier'),
        ('FONTSIZE', (0, 1), (0, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
    ]))
    story.append(modules_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Swing-Low Detection Algorithmus", h2_style))
    story.append(Paragraph(
        "Ein <b>Swing Low</b> ist ein lokales Minimum, das niedriger ist als seine Nachbarn. "
        "Der Algorithmus prüft für jeden Punkt, ob er kleiner ist als alle Punkte im Fenster links und rechts.",
        body_style
    ))

    story.append(Paragraph(
        "<font face='Courier' size='9'>"
        "for i in range(window, len(lows) - window):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;is_swing_low = all(<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;lows[i] &lt;= lows[i-j] and lows[i] &lt;= lows[i+j]<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;for j in range(1, window + 1)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;)"
        "</font>",
        body_style
    ))

    story.append(Paragraph("Level-Clustering", h2_style))
    story.append(Paragraph(
        "Mehrere Swing-Lows bei ähnlichen Preisen werden zu einem Level zusammengefasst. "
        "Die Toleranz beträgt typischerweise 1-2% des Preises.",
        body_style
    ))
    story.append(PageBreak())

    # Section 6: Optimierungen
    story.append(Paragraph("6. Optimierungsansätze", h1_style))

    story.append(Paragraph("Performance-Optimierung: O(n) Sliding Window", h2_style))
    story.append(Paragraph(
        "Die aktuelle Implementierung hat O(n²) Komplexität. Durch Verwendung einer "
        "<b>Monotonen Deque</b> kann dies auf O(n) reduziert werden.",
        body_style
    ))

    complexity_data = [
        ["Ansatz", "Komplexität", "Bei 252 Tagen"],
        ["Aktuell (nested loops)", "O(n × window)", "~2.520 Operationen"],
        ["Sliding Window Deque", "O(n)", "~504 Operationen"],
        ["NumPy argrelextrema", "O(n)", "~252 Operationen"],
    ]
    complexity_table = Table(complexity_data, colWidths=[5*cm, 3.5*cm, 4*cm])
    complexity_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#553c9a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#fed7d7')),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#c6f6d5')),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#c6f6d5')),
    ]))
    story.append(complexity_table)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Signal-Qualität: Volume-Weighted Scoring", h2_style))
    story.append(Paragraph(
        "Levels können nach Volumen und Aktualität gewichtet werden:",
        body_style
    ))
    story.append(Paragraph(
        "• <b>Volumen-Faktor:</b> Hohes Volumen beim Touch → stärkeres Level<br/>"
        "• <b>Aktualitäts-Faktor:</b> Jüngere Tests → höhere Gewichtung<br/>"
        "• <b>Touch-Count:</b> Mehr Tests → robusteres Level",
        body_style
    ))

    story.append(Paragraph("Clustering: DBSCAN", h2_style))
    story.append(Paragraph(
        "Statt einfacher Prozent-Toleranz kann DBSCAN (Density-Based Spatial Clustering) "
        "verwendet werden, um Levels intelligent zu gruppieren und Noise zu reduzieren.",
        body_style
    ))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        f"<i>Generiert am {datetime.now().strftime('%d.%m.%Y %H:%M')} - OptionPlay Trading System</i>",
        ParagraphStyle('Footer', parent=body_style, alignment=TA_CENTER, textColor=colors.gray)
    ))

    # Build PDF
    doc.build(story)
    print(f"PDF generated: {output_path}")
    return output_path


if __name__ == "__main__":
    create_pdf()
