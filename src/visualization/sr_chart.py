# OptionPlay - Support/Resistance Chart Visualization
# ===================================================
# Matplotlib-basierte Visualisierung für S/R Levels und Volume Profile
#
# Features:
# - Candlestick-Chart mit S/R Linien
# - Volume Profile als horizontales Histogramm
# - Farbkodierung nach Level-Stärke
# - Export als PNG/PDF für Reports

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

# Lazy imports for matplotlib (may not be installed)
if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


@dataclass
class SRChartConfig:
    """
    Konfiguration für Support/Resistance Charts.

    Attributes:
        figsize: Größe der Figur (Breite, Höhe) in Inches
        dpi: Auflösung für Export
        title_fontsize: Schriftgröße für Titel
        label_fontsize: Schriftgröße für Labels

        # Farben
        support_color: Farbe für Support-Levels
        resistance_color: Farbe für Resistance-Levels
        price_color: Farbe für Preis-Linie
        volume_color: Farbe für Volume Bars
        hvn_color: Farbe für High Volume Nodes
        poc_color: Farbe für Point of Control
        value_area_color: Farbe für Value Area

        # Stil
        support_linestyle: Linienstil für Support
        resistance_linestyle: Linienstil für Resistance
        show_level_labels: Level-Preise anzeigen
        show_strength: Stärke-Werte anzeigen
        show_touches: Touch-Anzahl anzeigen

        # Volume Profile
        vp_width_pct: Breite des Volume Profile (% der Chart-Breite)
        vp_num_zones: Anzahl der Preiszonen
    """

    # Figure settings
    figsize: Tuple[float, float] = (14, 8)
    dpi: int = 150
    title_fontsize: int = 14
    label_fontsize: int = 10

    # Colors
    support_color: str = "#00C853"  # Grün
    resistance_color: str = "#FF1744"  # Rot
    price_color: str = "#1976D2"  # Blau
    volume_color: str = "#78909C"  # Grau-Blau
    hvn_color: str = "#7B1FA2"  # Lila
    poc_color: str = "#FF6F00"  # Orange
    value_area_color: str = "#E3F2FD"  # Hellblau
    candle_up_color: str = "#00C853"
    candle_down_color: str = "#FF1744"

    # Line styles
    support_linestyle: str = "--"
    resistance_linestyle: str = "--"
    support_linewidth: float = 1.5
    resistance_linewidth: float = 1.5

    # Labels
    show_level_labels: bool = True
    show_strength: bool = True
    show_touches: bool = True
    show_hold_rate: bool = True

    # Volume Profile
    vp_width_pct: float = 15.0
    vp_num_zones: int = 30

    # Grid
    show_grid: bool = True
    grid_alpha: float = 0.3

    # Background
    background_color: str = "#FAFAFA"

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "figsize": self.figsize,
            "dpi": self.dpi,
            "support_color": self.support_color,
            "resistance_color": self.resistance_color,
        }


def _check_matplotlib() -> bool:
    """Prüft ob matplotlib verfügbar ist."""
    try:
        import matplotlib

        return True
    except ImportError:
        logger.warning("matplotlib not installed. Install with: pip install matplotlib")
        return False


def _get_level_alpha(strength: float) -> float:
    """Berechnet Alpha-Wert basierend auf Level-Stärke."""
    # Stärke 0.0-1.0 -> Alpha 0.3-1.0
    return 0.3 + (strength * 0.7)


def _get_level_linewidth(strength: float, base_width: float = 1.5) -> float:
    """Berechnet Linienbreite basierend auf Level-Stärke."""
    # Stärke 0.0-1.0 -> Breite 1x-2x base
    return base_width * (1.0 + strength)


def plot_support_resistance(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    support_levels: Optional[List[float]] = None,
    resistance_levels: Optional[List[float]] = None,
    support_strengths: Optional[List[float]] = None,
    resistance_strengths: Optional[List[float]] = None,
    support_touches: Optional[List[int]] = None,
    resistance_touches: Optional[List[int]] = None,
    symbol: str = "",
    config: Optional[SRChartConfig] = None,
    ax: Optional[Any] = None,
) -> Tuple[Any, Any]:
    """
    Erstellt einen Preis-Chart mit Support/Resistance Levels.

    Args:
        prices: Schlusskurse (älteste zuerst)
        highs: Tageshochs
        lows: Tagestiefs
        support_levels: Support-Preise
        resistance_levels: Resistance-Preise
        support_strengths: Stärke jedes Supports (0-1)
        resistance_strengths: Stärke jeder Resistance (0-1)
        support_touches: Touch-Anzahl pro Support
        resistance_touches: Touch-Anzahl pro Resistance
        symbol: Ticker-Symbol für Titel
        config: Chart-Konfiguration
        ax: Vorhandene Axes (optional)

    Returns:
        Tuple von (Figure, Axes)
    """
    if not _check_matplotlib():
        return None, None

    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    config = config or SRChartConfig()

    # Erstelle Figure wenn keine Axes übergeben
    if ax is None:
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        fig.patch.set_facecolor(config.background_color)
    else:
        fig = ax.get_figure()

    ax.set_facecolor(config.background_color)

    # X-Achse: Index oder Datum
    x = list(range(len(prices)))

    # Zeichne Preis als Linie (vereinfacht, ohne Candlesticks)
    ax.plot(x, prices, color=config.price_color, linewidth=1.5, label="Close", zorder=5)

    # Zeichne High/Low Range als gefüllter Bereich
    ax.fill_between(x, lows, highs, alpha=0.15, color=config.price_color, label="High/Low Range")

    # Support Levels
    if support_levels:
        support_strengths = support_strengths or [0.5] * len(support_levels)
        support_touches = support_touches or [1] * len(support_levels)

        for i, (level, strength, touches) in enumerate(
            zip(support_levels, support_strengths, support_touches)
        ):
            alpha = _get_level_alpha(strength)
            linewidth = _get_level_linewidth(strength, config.support_linewidth)

            ax.axhline(
                y=level,
                color=config.support_color,
                linestyle=config.support_linestyle,
                linewidth=linewidth,
                alpha=alpha,
                zorder=3,
                label=f"Support" if i == 0 else None,
            )

            if config.show_level_labels:
                label_parts = [f"${level:.2f}"]
                if config.show_strength:
                    label_parts.append(f"({strength:.0%})")
                if config.show_touches:
                    label_parts.append(f"[{touches}x]")

                label = " ".join(label_parts)

                ax.annotate(
                    label,
                    xy=(len(x) * 0.02, level),
                    fontsize=config.label_fontsize - 2,
                    color=config.support_color,
                    alpha=alpha,
                    va="center",
                    ha="left",
                    fontweight="bold" if strength > 0.6 else "normal",
                )

    # Resistance Levels
    if resistance_levels:
        resistance_strengths = resistance_strengths or [0.5] * len(resistance_levels)
        resistance_touches = resistance_touches or [1] * len(resistance_levels)

        for i, (level, strength, touches) in enumerate(
            zip(resistance_levels, resistance_strengths, resistance_touches)
        ):
            alpha = _get_level_alpha(strength)
            linewidth = _get_level_linewidth(strength, config.resistance_linewidth)

            ax.axhline(
                y=level,
                color=config.resistance_color,
                linestyle=config.resistance_linestyle,
                linewidth=linewidth,
                alpha=alpha,
                zorder=3,
                label=f"Resistance" if i == 0 else None,
            )

            if config.show_level_labels:
                label_parts = [f"${level:.2f}"]
                if config.show_strength:
                    label_parts.append(f"({strength:.0%})")
                if config.show_touches:
                    label_parts.append(f"[{touches}x]")

                label = " ".join(label_parts)

                ax.annotate(
                    label,
                    xy=(len(x) * 0.02, level),
                    fontsize=config.label_fontsize - 2,
                    color=config.resistance_color,
                    alpha=alpha,
                    va="center",
                    ha="left",
                    fontweight="bold" if strength > 0.6 else "normal",
                )

    # Aktueller Preis
    current_price = prices[-1]
    ax.axhline(
        y=current_price, color=config.price_color, linestyle="-", linewidth=2, alpha=0.8, zorder=4
    )
    ax.annotate(
        f"${current_price:.2f}",
        xy=(len(x) - 1, current_price),
        fontsize=config.label_fontsize,
        color=config.price_color,
        va="bottom",
        ha="right",
        fontweight="bold",
    )

    # Grid
    if config.show_grid:
        ax.grid(True, alpha=config.grid_alpha, linestyle="-", linewidth=0.5)

    # Labels und Titel
    title = f"{symbol} - Support/Resistance Analysis" if symbol else "Support/Resistance Analysis"
    ax.set_title(title, fontsize=config.title_fontsize, fontweight="bold")
    ax.set_xlabel("Trading Days", fontsize=config.label_fontsize)
    ax.set_ylabel("Price ($)", fontsize=config.label_fontsize)

    # Legende
    ax.legend(loc="upper left", fontsize=config.label_fontsize - 2)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            plt.tight_layout()
        except Exception as e:
            logger.debug(f"tight_layout failed (non-critical): {e}")

    return fig, ax


def plot_volume_profile(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    num_zones: int = 30,
    symbol: str = "",
    config: Optional[SRChartConfig] = None,
    ax: Optional[Any] = None,
) -> Tuple[Any, Any]:
    """
    Erstellt ein horizontales Volume Profile Histogramm.

    Args:
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        num_zones: Anzahl der Preiszonen
        symbol: Ticker-Symbol
        config: Chart-Konfiguration
        ax: Vorhandene Axes

    Returns:
        Tuple von (Figure, Axes)
    """
    if not _check_matplotlib():
        return None, None

    import matplotlib.pyplot as plt
    import numpy as np

    config = config or SRChartConfig()

    if ax is None:
        fig, ax = plt.subplots(figsize=(4, 8), dpi=config.dpi)
        fig.patch.set_facecolor(config.background_color)
    else:
        fig = ax.get_figure()

    ax.set_facecolor(config.background_color)

    # Berechne Volume Profile
    price_high = max(highs)
    price_low = min(lows)

    if price_high == price_low:
        return fig, ax

    zone_height = (price_high - price_low) / num_zones

    # Initialisiere Zonen
    zone_volumes = [0] * num_zones
    zone_centers = []

    for i in range(num_zones):
        zone_low = price_low + i * zone_height
        zone_high = zone_low + zone_height
        zone_centers.append((zone_low + zone_high) / 2)

    # Verteile Volumen
    for h, l, vol in zip(highs, lows, volumes):
        bar_range = h - l if h > l else zone_height

        for i, center in enumerate(zone_centers):
            zone_low = center - zone_height / 2
            zone_high = center + zone_height / 2

            overlap_low = max(zone_low, l)
            overlap_high = min(zone_high, h)

            if overlap_high > overlap_low:
                overlap_ratio = (overlap_high - overlap_low) / bar_range
                zone_volumes[i] += int(vol * overlap_ratio)

    # Normalisiere Volumen
    max_vol = max(zone_volumes) if zone_volumes else 1
    norm_volumes = [v / max_vol for v in zone_volumes]

    # Durchschnittsvolumen für HVN-Erkennung
    avg_vol = sum(zone_volumes) / len(zone_volumes) if zone_volumes else 0
    hvn_threshold = avg_vol * 1.5

    # Zeichne horizontale Bars
    colors = []
    for i, vol in enumerate(zone_volumes):
        if vol > hvn_threshold:
            colors.append(config.hvn_color)
        else:
            colors.append(config.volume_color)

    # POC (Point of Control)
    poc_idx = zone_volumes.index(max(zone_volumes)) if zone_volumes else 0
    colors[poc_idx] = config.poc_color

    bars = ax.barh(
        zone_centers,
        norm_volumes,
        height=zone_height * 0.9,
        color=colors,
        alpha=0.7,
        edgecolor="none",
    )

    # POC Label
    poc_price = zone_centers[poc_idx]
    ax.annotate(
        f"POC ${poc_price:.2f}",
        xy=(norm_volumes[poc_idx], poc_price),
        fontsize=config.label_fontsize - 1,
        color=config.poc_color,
        fontweight="bold",
        va="center",
        ha="left",
    )

    # Labels
    title = f"{symbol} Volume Profile" if symbol else "Volume Profile"
    ax.set_title(title, fontsize=config.title_fontsize - 2, fontweight="bold")
    ax.set_xlabel("Relative Volume", fontsize=config.label_fontsize - 1)
    ax.set_ylabel("Price ($)", fontsize=config.label_fontsize - 1)

    ax.set_xlim(0, 1.15)  # Etwas Platz für Labels
    ax.set_ylim(price_low - zone_height, price_high + zone_height)

    if config.show_grid:
        ax.grid(True, alpha=config.grid_alpha, axis="y", linestyle="-", linewidth=0.5)

    plt.tight_layout()

    return fig, ax


def plot_sr_with_volume_profile(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    support_levels: Optional[List[float]] = None,
    resistance_levels: Optional[List[float]] = None,
    support_strengths: Optional[List[float]] = None,
    resistance_strengths: Optional[List[float]] = None,
    support_touches: Optional[List[int]] = None,
    resistance_touches: Optional[List[int]] = None,
    symbol: str = "",
    config: Optional[SRChartConfig] = None,
) -> Tuple[Any, Tuple[Any, Any]]:
    """
    Erstellt kombinierten Chart: S/R + Volume Profile.

    Layout:
    +---------------------------+-------+
    |                           |       |
    |   Price Chart mit S/R     | Vol   |
    |                           | Prof  |
    |                           |       |
    +---------------------------+-------+

    Args:
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        support_levels: Support-Preise
        resistance_levels: Resistance-Preise
        support_strengths: Stärke-Werte (0-1)
        resistance_strengths: Stärke-Werte (0-1)
        support_touches: Touch-Anzahl
        resistance_touches: Touch-Anzahl
        symbol: Ticker-Symbol
        config: Chart-Konfiguration

    Returns:
        Tuple von (Figure, (ax_price, ax_volume))
    """
    if not _check_matplotlib():
        return None, (None, None)

    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    config = config or SRChartConfig()

    # Berechne Breiten-Verhältnis
    vp_ratio = config.vp_width_pct / 100
    price_ratio = 1.0 - vp_ratio

    # Erstelle Figure mit GridSpec
    fig = plt.figure(figsize=config.figsize, dpi=config.dpi)
    fig.patch.set_facecolor(config.background_color)

    gs = GridSpec(1, 2, width_ratios=[price_ratio, vp_ratio], wspace=0.02)

    ax_price = fig.add_subplot(gs[0])
    ax_volume = fig.add_subplot(gs[1], sharey=ax_price)

    # Preis-Chart mit S/R
    plot_support_resistance(
        prices=prices,
        highs=highs,
        lows=lows,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        support_strengths=support_strengths,
        resistance_strengths=resistance_strengths,
        support_touches=support_touches,
        resistance_touches=resistance_touches,
        symbol=symbol,
        config=config,
        ax=ax_price,
    )

    # Volume Profile
    ax_volume.set_facecolor(config.background_color)

    # Berechne Volume Profile
    price_high = max(highs)
    price_low = min(lows)
    num_zones = config.vp_num_zones

    if price_high > price_low:
        zone_height = (price_high - price_low) / num_zones

        zone_volumes = [0] * num_zones
        zone_centers = []

        for i in range(num_zones):
            zone_low = price_low + i * zone_height
            zone_high = zone_low + zone_height
            zone_centers.append((zone_low + zone_high) / 2)

        for h, l, vol in zip(highs, lows, volumes):
            bar_range = h - l if h > l else zone_height

            for i, center in enumerate(zone_centers):
                zone_low = center - zone_height / 2
                zone_high = center + zone_height / 2

                overlap_low = max(zone_low, l)
                overlap_high = min(zone_high, h)

                if overlap_high > overlap_low:
                    overlap_ratio = (overlap_high - overlap_low) / bar_range
                    zone_volumes[i] += int(vol * overlap_ratio)

        max_vol = max(zone_volumes) if zone_volumes else 1
        norm_volumes = [v / max_vol for v in zone_volumes]

        avg_vol = sum(zone_volumes) / len(zone_volumes) if zone_volumes else 0
        hvn_threshold = avg_vol * 1.5

        colors = []
        for vol in zone_volumes:
            if vol > hvn_threshold:
                colors.append(config.hvn_color)
            else:
                colors.append(config.volume_color)

        # POC
        poc_idx = zone_volumes.index(max(zone_volumes)) if zone_volumes else 0
        colors[poc_idx] = config.poc_color

        ax_volume.barh(
            zone_centers,
            norm_volumes,
            height=zone_height * 0.9,
            color=colors,
            alpha=0.7,
            edgecolor="none",
        )

        # POC Label
        poc_price = zone_centers[poc_idx]
        ax_volume.annotate(
            f"POC",
            xy=(norm_volumes[poc_idx] + 0.05, poc_price),
            fontsize=config.label_fontsize - 2,
            color=config.poc_color,
            fontweight="bold",
            va="center",
        )

    ax_volume.set_title("Volume Profile", fontsize=config.title_fontsize - 2, fontweight="bold")
    ax_volume.set_xlabel("Vol", fontsize=config.label_fontsize - 1)
    ax_volume.tick_params(labelleft=False)
    ax_volume.set_xlim(0, 1.2)

    if config.show_grid:
        ax_volume.grid(True, alpha=config.grid_alpha, axis="y", linestyle="-", linewidth=0.5)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            fig.tight_layout()
        except Exception as e:
            logger.debug(f"tight_layout failed (non-critical): {e}")

    return fig, (ax_price, ax_volume)


def save_chart(
    fig: Any,
    filepath: str,
    dpi: Optional[int] = None,
    format: Optional[str] = None,
    transparent: bool = False,
) -> bool:
    """
    Speichert Chart als Bild-Datei.

    Args:
        fig: Matplotlib Figure
        filepath: Zielpfad (z.B. 'report/chart.png')
        dpi: Auflösung (default: Figure-DPI)
        format: Format ('png', 'pdf', 'svg', etc.)
        transparent: Transparenter Hintergrund

    Returns:
        True bei Erfolg
    """
    if fig is None:
        logger.error("Cannot save: Figure is None")
        return False

    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Format aus Dateiendung wenn nicht angegeben
        if format is None:
            format = path.suffix.lstrip(".") or "png"

        fig.savefig(
            filepath,
            dpi=dpi or fig.dpi,
            format=format,
            transparent=transparent,
            bbox_inches="tight",
            pad_inches=0.1,
        )

        logger.info(f"Chart saved: {filepath}")
        return True

    except Exception as e:
        logger.error(f"Failed to save chart: {e}")
        return False


def create_sr_report_chart(
    symbol: str,
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    output_path: Optional[str] = None,
    config: Optional[SRChartConfig] = None,
) -> Tuple[Any, str]:
    """
    Convenience-Funktion: Erstellt vollständigen S/R Report Chart.

    Berechnet automatisch S/R Levels und erstellt kombinierten Chart.

    Args:
        symbol: Ticker-Symbol
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        output_path: Optional: Speicherpfad
        config: Chart-Konfiguration

    Returns:
        Tuple von (Figure, output_path oder "")
    """
    if not _check_matplotlib():
        return None, ""

    # Import S/R Analyse
    try:
        from ..indicators.support_resistance import analyze_support_resistance_with_validation
    except ImportError:
        from indicators.support_resistance import analyze_support_resistance_with_validation

    # Analysiere S/R mit Volumen-Validierung
    result = analyze_support_resistance_with_validation(
        prices=prices,
        highs=highs,
        lows=lows,
        volumes=volumes,
        lookback=min(60, len(prices)),
        include_volume_profile=True,
    )

    # Extrahiere Daten
    support_levels = [l.price for l in result.support_levels]
    support_strengths = [l.strength for l in result.support_levels]
    support_touches = [l.touches for l in result.support_levels]

    resistance_levels = [l.price for l in result.resistance_levels]
    resistance_strengths = [l.strength for l in result.resistance_levels]
    resistance_touches = [l.touches for l in result.resistance_levels]

    # Erstelle Chart
    fig, axes = plot_sr_with_volume_profile(
        prices=prices,
        highs=highs,
        lows=lows,
        volumes=volumes,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        support_strengths=support_strengths,
        resistance_strengths=resistance_strengths,
        support_touches=support_touches,
        resistance_touches=resistance_touches,
        symbol=symbol,
        config=config,
    )

    # Speichern wenn Pfad angegeben
    saved_path = ""
    if output_path and fig:
        if save_chart(fig, output_path):
            saved_path = output_path

    return fig, saved_path


def plot_volume_profile_with_buysell(
    opens: List[float],
    closes: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    symbol: str = "",
    num_zones: int = 30,
    buy_color: str = "#00C853",
    sell_color: str = "#FF1744",
    alpha: float = 0.4,
    figsize: Tuple[float, float] = (14, 6),
    dpi: int = 150,
    show_price_line: bool = True,
) -> Tuple[Any, Any]:
    """
    Erstellt ein Volume Profile mit Kauf/Verkauf-Trennung.

    Kauf-Volumen (grün): Tage an denen Close > Open (bullish)
    Verkauf-Volumen (rot): Tage an denen Close < Open (bearish)

    Die Balken werden horizontal vom Preislevel nach rechts gezeichnet.

    Args:
        opens: Opening prices
        closes: Closing prices
        highs: High prices
        lows: Low prices
        volumes: Daily volumes
        symbol: Ticker symbol für Titel
        num_zones: Anzahl der Preiszonen
        buy_color: Farbe für Kauf-Volumen (grün)
        sell_color: Farbe für Verkauf-Volumen (rot)
        alpha: Transparenz (0.4 = 40% Deckung)
        figsize: Figure size (Breite, Höhe)
        dpi: Auflösung
        show_price_line: Zeige aktuellen Preis

    Returns:
        Tuple von (Figure, Axes)
    """
    if not _check_matplotlib():
        return None, None

    import matplotlib.pyplot as plt
    import numpy as np

    if len(opens) < 10:
        logger.warning(f"Not enough data for volume profile: {len(opens)} bars")
        return None, None

    # Berechne Preis-Range
    price_high = max(highs)
    price_low = min(lows)

    if price_high == price_low:
        return None, None

    zone_height = (price_high - price_low) / num_zones

    # Initialisiere Zonen für Kauf und Verkauf
    zone_buy_volumes = [0.0] * num_zones
    zone_sell_volumes = [0.0] * num_zones
    zone_centers = []

    for i in range(num_zones):
        zone_low = price_low + i * zone_height
        zone_high = zone_low + zone_height
        zone_centers.append((zone_low + zone_high) / 2)

    # Verteile Volumen nach Kauf/Verkauf
    for o, c, h, l, vol in zip(opens, closes, highs, lows, volumes):
        is_buy = c > o  # Bullish candle = Kauf
        bar_range = h - l if h > l else zone_height

        for i, center in enumerate(zone_centers):
            zone_low = center - zone_height / 2
            zone_high = center + zone_height / 2

            # Berechne Überlappung
            overlap_low = max(zone_low, l)
            overlap_high = min(zone_high, h)

            if overlap_high > overlap_low:
                overlap_ratio = (overlap_high - overlap_low) / bar_range
                allocated_vol = vol * overlap_ratio

                if is_buy:
                    zone_buy_volumes[i] += allocated_vol
                else:
                    zone_sell_volumes[i] += allocated_vol

    # Normalisiere für Darstellung
    max_total_vol = max(zone_buy_volumes[i] + zone_sell_volumes[i] for i in range(num_zones))
    if max_total_vol == 0:
        max_total_vol = 1

    norm_buy = [v / max_total_vol for v in zone_buy_volumes]
    norm_sell = [v / max_total_vol for v in zone_sell_volumes]

    # Erstelle Figure
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FAFAFA")

    # Zeichne Kauf-Balken (grün)
    ax.barh(
        zone_centers,
        norm_buy,
        height=zone_height * 0.9,
        color=buy_color,
        alpha=alpha,
        label="Kauf (Close > Open)",
        edgecolor="none",
    )

    # Zeichne Verkauf-Balken (rot) - gestapelt rechts neben Kauf
    ax.barh(
        zone_centers,
        norm_sell,
        height=zone_height * 0.9,
        color=sell_color,
        alpha=alpha,
        left=norm_buy,
        label="Verkauf (Close < Open)",
        edgecolor="none",
    )

    # POC (Point of Control) - Zone mit höchstem Gesamtvolumen
    total_volumes = [zone_buy_volumes[i] + zone_sell_volumes[i] for i in range(num_zones)]
    poc_idx = total_volumes.index(max(total_volumes))
    poc_price = zone_centers[poc_idx]

    # POC Linie
    ax.axhline(
        y=poc_price,
        color="#FF6F00",
        linestyle="--",
        linewidth=2,
        alpha=0.8,
        label=f"POC ${poc_price:.2f}",
    )

    # Aktueller Preis
    if show_price_line and closes:
        current_price = closes[-1]
        ax.axhline(
            y=current_price,
            color="#1976D2",
            linestyle="-",
            linewidth=2,
            alpha=0.9,
            label=f"Preis ${current_price:.2f}",
        )

    # Styling
    title = f"{symbol} Volume Profile (Buy/Sell)" if symbol else "Volume Profile (Buy/Sell)"
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Relatives Volumen", fontsize=10)
    ax.set_ylabel("Preis ($)", fontsize=10)

    ax.set_xlim(0, 1.1)
    ax.set_ylim(price_low - zone_height, price_high + zone_height)

    ax.grid(True, alpha=0.3, axis="y", linestyle="-", linewidth=0.5)
    ax.legend(loc="upper right", fontsize=9)

    plt.tight_layout()

    return fig, ax


def plot_price_with_volume_profile(
    opens: List[float],
    closes: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    dates: Optional[List[Any]] = None,
    symbol: str = "",
    num_zones: int = 30,
    buy_color: str = "#00C853",
    sell_color: str = "#FF1744",
    alpha: float = 0.4,
    figsize: Tuple[float, float] = (16, 8),
    dpi: int = 150,
    vp_width_pct: float = 20.0,
) -> Tuple[Any, Tuple[Any, Any]]:
    """
    Erstellt kombinierten Chart: Preis-Chart links + Volume Profile rechts.

    Layout:
    +--------------------------------+--------+
    |                                |        |
    |   Candlestick / Price Chart    | Volume |
    |   (Zeit auf X-Achse)           | Profile|
    |                                |        |
    +--------------------------------+--------+

    Args:
        opens: Opening prices
        closes: Closing prices
        highs: High prices
        lows: Low prices
        volumes: Daily volumes
        dates: Optionale Datumsliste
        symbol: Ticker symbol
        num_zones: Anzahl der Preiszonen
        buy_color: Farbe für Kauf-Volumen
        sell_color: Farbe für Verkauf-Volumen
        alpha: Transparenz
        figsize: Figure size
        dpi: Auflösung
        vp_width_pct: Breite des Volume Profile (% der Gesamtbreite)

    Returns:
        Tuple von (Figure, (ax_price, ax_volume))
    """
    if not _check_matplotlib():
        return None, (None, None)

    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.gridspec import GridSpec

    if len(opens) < 10:
        logger.warning(f"Not enough data: {len(opens)} bars")
        return None, (None, None)

    # Berechne Breiten-Verhältnis
    vp_ratio = vp_width_pct / 100
    price_ratio = 1.0 - vp_ratio

    # Erstelle Figure mit GridSpec
    fig = plt.figure(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("#FAFAFA")

    gs = GridSpec(1, 2, width_ratios=[price_ratio, vp_ratio], wspace=0.02)

    ax_price = fig.add_subplot(gs[0])
    ax_volume = fig.add_subplot(gs[1], sharey=ax_price)

    # === Linker Chart: Preis mit Candlesticks ===
    ax_price.set_facecolor("#FAFAFA")

    x = list(range(len(closes)))

    # Zeichne Candlesticks (vereinfacht als Linien)
    for i, (o, c, h, l) in enumerate(zip(opens, closes, highs, lows)):
        color = buy_color if c >= o else sell_color

        # High-Low Linie (Docht)
        ax_price.plot([i, i], [l, h], color=color, linewidth=0.8, alpha=0.7)

        # Body
        body_bottom = min(o, c)
        body_top = max(o, c)
        ax_price.plot([i, i], [body_bottom, body_top], color=color, linewidth=3, alpha=0.9)

    # Aktueller Preis
    current_price = closes[-1]
    ax_price.axhline(y=current_price, color="#1976D2", linestyle="-", linewidth=2, alpha=0.8)
    ax_price.annotate(
        f"${current_price:.2f}",
        xy=(len(x) - 1, current_price),
        fontsize=10,
        color="#1976D2",
        va="bottom",
        ha="right",
        fontweight="bold",
    )

    ax_price.grid(True, alpha=0.3, linestyle="-", linewidth=0.5)
    title = f"{symbol} Price + Volume Profile" if symbol else "Price + Volume Profile"
    ax_price.set_title(title, fontsize=14, fontweight="bold")
    ax_price.set_xlabel("Trading Days", fontsize=10)
    ax_price.set_ylabel("Preis ($)", fontsize=10)

    # === Rechter Chart: Volume Profile ===
    ax_volume.set_facecolor("#FAFAFA")

    # Berechne Preis-Range
    price_high = max(highs)
    price_low = min(lows)
    zone_height = (price_high - price_low) / num_zones

    zone_buy_volumes = [0.0] * num_zones
    zone_sell_volumes = [0.0] * num_zones
    zone_centers = []

    for i in range(num_zones):
        zone_low = price_low + i * zone_height
        zone_high = zone_low + zone_height
        zone_centers.append((zone_low + zone_high) / 2)

    # Verteile Volumen
    for o, c, h, l, vol in zip(opens, closes, highs, lows, volumes):
        is_buy = c > o
        bar_range = h - l if h > l else zone_height

        for i, center in enumerate(zone_centers):
            zone_low = center - zone_height / 2
            zone_high = center + zone_height / 2

            overlap_low = max(zone_low, l)
            overlap_high = min(zone_high, h)

            if overlap_high > overlap_low:
                overlap_ratio = (overlap_high - overlap_low) / bar_range
                allocated_vol = vol * overlap_ratio

                if is_buy:
                    zone_buy_volumes[i] += allocated_vol
                else:
                    zone_sell_volumes[i] += allocated_vol

    # Normalisiere
    max_total_vol = max(zone_buy_volumes[i] + zone_sell_volumes[i] for i in range(num_zones))
    if max_total_vol == 0:
        max_total_vol = 1

    norm_buy = [v / max_total_vol for v in zone_buy_volumes]
    norm_sell = [v / max_total_vol for v in zone_sell_volumes]

    # Zeichne Volume Profile
    ax_volume.barh(
        zone_centers,
        norm_buy,
        height=zone_height * 0.9,
        color=buy_color,
        alpha=alpha,
        label="Kauf",
        edgecolor="none",
    )

    ax_volume.barh(
        zone_centers,
        norm_sell,
        height=zone_height * 0.9,
        color=sell_color,
        alpha=alpha,
        left=norm_buy,
        label="Verkauf",
        edgecolor="none",
    )

    # POC
    total_volumes = [zone_buy_volumes[i] + zone_sell_volumes[i] for i in range(num_zones)]
    poc_idx = total_volumes.index(max(total_volumes))
    poc_price = zone_centers[poc_idx]

    ax_volume.axhline(y=poc_price, color="#FF6F00", linestyle="--", linewidth=2, alpha=0.8)
    ax_volume.annotate(
        "POC", xy=(0.95, poc_price), fontsize=9, color="#FF6F00", fontweight="bold", va="center"
    )

    ax_volume.set_title("Volume Profile", fontsize=12, fontweight="bold")
    ax_volume.set_xlabel("Vol", fontsize=9)
    ax_volume.tick_params(labelleft=False)
    ax_volume.set_xlim(0, 1.1)
    ax_volume.grid(True, alpha=0.3, axis="y", linestyle="-", linewidth=0.5)
    ax_volume.legend(loc="upper right", fontsize=8)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            fig.tight_layout()
        except Exception as e:
            logger.debug(f"tight_layout failed (non-critical): {e}")

    return fig, (ax_price, ax_volume)
