# OptionPlay - Gap Analysis Indicators
# =====================================
# Erkennt und bewertet Price Gaps für Trading-Signale
#
# Grundannahme (zu validieren):
# - Up-Gaps: Oft Überkauft-Signal, erhöhtes Risiko für Pullback
# - Down-Gaps: Potenzielle Einstiegsgelegenheit (Überreaktion)
#
# Features:
# - Gap-Typ-Erkennung (Up/Down/Partial)
# - Gap-Fill-Tracking
# - Historische Gap-Statistiken
# - Quality-Score für Trading-Entscheidungen

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

try:
    from ..models.indicators import GapResult, GapStatistics
except ImportError:
    from models.indicators import GapResult, GapStatistics

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Minimale Gap-Größe (in %) um als signifikant zu gelten
MIN_GAP_THRESHOLD_PCT = 0.5

# Gap-Fill Toleranz - Gap gilt als gefüllt wenn Preis diese % des Gaps zurückgelegt hat
GAP_FILL_THRESHOLD_PCT = 90.0

# Lookback-Perioden
DEFAULT_LOOKBACK_DAYS = 20
STATS_LOOKBACK_DAYS = 252  # 1 Jahr für Statistiken

# Performance-Tracking
PERFORMANCE_FORWARD_DAYS = 5  # Tage nach Gap für Return-Berechnung


# =============================================================================
# CORE GAP DETECTION
# =============================================================================

def detect_gap(
    prev_open: float,
    prev_high: float,
    prev_low: float,
    prev_close: float,
    curr_open: float,
    curr_high: float,
    curr_low: float,
    curr_close: float,
    min_gap_pct: float = MIN_GAP_THRESHOLD_PCT,
) -> Tuple[str, float, float, bool, float]:
    """
    Erkennt Gap zwischen zwei aufeinanderfolgenden Bars.

    Gap-Definitionen:
    - Full Up-Gap: Open > Previous High (echte Lücke nach oben)
    - Full Down-Gap: Open < Previous Low (echte Lücke nach unten)
    - Partial Up-Gap: Open > Previous Close, aber <= Previous High
    - Partial Down-Gap: Open < Previous Close, aber >= Previous Low

    Args:
        prev_*: OHLC des vorherigen Tages
        curr_*: OHLC des aktuellen Tages
        min_gap_pct: Minimale Gap-Größe in %

    Returns:
        Tuple: (gap_type, gap_size_pct, gap_size_abs, is_filled, fill_percentage)
    """
    if prev_close <= 0:
        return ('none', 0.0, 0.0, False, 0.0)

    # Gap-Größe berechnen (relativ zum Previous Close)
    gap_size_abs = curr_open - prev_close
    gap_size_pct = (gap_size_abs / prev_close) * 100

    # Gap-Typ bestimmen
    gap_type = 'none'

    if curr_open > prev_high:
        # Full Up-Gap: Eröffnung über dem Vortagshoch
        gap_type = 'up'
    elif curr_open < prev_low:
        # Full Down-Gap: Eröffnung unter dem Vortagstief
        gap_type = 'down'
    elif gap_size_pct >= min_gap_pct:
        # Partial Up-Gap: Deutlich über Close, aber nicht über High
        gap_type = 'partial_up'
    elif gap_size_pct <= -min_gap_pct:
        # Partial Down-Gap: Deutlich unter Close, aber nicht unter Low
        gap_type = 'partial_down'

    # Prüfe ob Gap zu klein ist
    if gap_type != 'none' and abs(gap_size_pct) < min_gap_pct:
        gap_type = 'none'

    # Gap-Fill prüfen (wurde die Lücke intraday geschlossen?)
    is_filled = False
    fill_percentage = 0.0

    if gap_type in ('up', 'partial_up') and gap_size_abs > 0:
        # Up-Gap: Gefüllt wenn Preis zurück zum Previous Close fällt
        gap_fill_price = prev_close
        distance_to_fill = curr_open - gap_fill_price
        if distance_to_fill > 0:
            filled_amount = curr_open - curr_low
            fill_percentage = min(100.0, (filled_amount / distance_to_fill) * 100)
            is_filled = fill_percentage >= GAP_FILL_THRESHOLD_PCT

    elif gap_type in ('down', 'partial_down') and gap_size_abs < 0:
        # Down-Gap: Gefüllt wenn Preis zurück zum Previous Close steigt
        gap_fill_price = prev_close
        distance_to_fill = gap_fill_price - curr_open
        if distance_to_fill > 0:
            filled_amount = curr_high - curr_open
            fill_percentage = min(100.0, (filled_amount / distance_to_fill) * 100)
            is_filled = fill_percentage >= GAP_FILL_THRESHOLD_PCT

    return (gap_type, gap_size_pct, gap_size_abs, is_filled, fill_percentage)


def analyze_gap(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_gap_pct: float = MIN_GAP_THRESHOLD_PCT,
) -> Optional[GapResult]:
    """
    Analysiert den aktuellen Gap und berechnet historische Statistiken.

    Args:
        opens: Open-Preise (älteste zuerst)
        highs: High-Preise
        lows: Low-Preise
        closes: Close-Preise
        lookback_days: Tage für historische Gap-Statistiken
        min_gap_pct: Minimale Gap-Größe

    Returns:
        GapResult mit aktueller Gap-Info und Statistiken
    """
    if len(opens) < 2:
        return None

    if len(opens) != len(highs) or len(highs) != len(lows) or len(lows) != len(closes):
        logger.warning("Gap analysis: Ungleiche Array-Längen")
        return None

    # Aktueller Gap (letzter Bar vs vorletzter Bar)
    gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = detect_gap(
        prev_open=opens[-2],
        prev_high=highs[-2],
        prev_low=lows[-2],
        prev_close=closes[-2],
        curr_open=opens[-1],
        curr_high=highs[-1],
        curr_low=lows[-1],
        curr_close=closes[-1],
        min_gap_pct=min_gap_pct,
    )

    # Historische Gap-Statistiken berechnen
    start_idx = max(0, len(opens) - lookback_days - 1)
    gaps_count = 0
    gap_sizes = []
    filled_count = 0

    for i in range(start_idx + 1, len(opens) - 1):  # Exkludiere aktuellen Tag
        hist_type, hist_size, _, hist_filled, _ = detect_gap(
            prev_open=opens[i - 1],
            prev_high=highs[i - 1],
            prev_low=lows[i - 1],
            prev_close=closes[i - 1],
            curr_open=opens[i],
            curr_high=highs[i],
            curr_low=lows[i],
            curr_close=closes[i],
            min_gap_pct=min_gap_pct,
        )
        if hist_type != 'none':
            gaps_count += 1
            gap_sizes.append(abs(hist_size))
            if hist_filled:
                filled_count += 1

    avg_gap_size = np.mean(gap_sizes) if gap_sizes else 0.0
    gap_fill_rate = filled_count / gaps_count if gaps_count > 0 else 0.0

    # Quality-Score berechnen
    quality_score = _calculate_gap_quality_score(
        gap_type=gap_type,
        gap_size_pct=gap_size_pct,
        is_filled=is_filled,
        fill_percentage=fill_pct,
        avg_gap_size=avg_gap_size,
    )

    return GapResult(
        gap_type=gap_type,
        gap_size_pct=gap_size_pct,
        gap_size_abs=gap_size_abs,
        is_filled=is_filled,
        fill_percentage=fill_pct,
        gaps_last_20_days=gaps_count,
        avg_gap_size_20d=avg_gap_size,
        gap_fill_rate_20d=gap_fill_rate,
        previous_close=closes[-2],
        current_open=opens[-1],
        current_high=highs[-1],
        current_low=lows[-1],
        quality_score=quality_score,
    )


def _calculate_gap_quality_score(
    gap_type: str,
    gap_size_pct: float,
    is_filled: bool,
    fill_percentage: float,
    avg_gap_size: float,
) -> float:
    """
    Berechnet Quality-Score für Gap-basiertes Trading (Bull-Put-Spreads, 30-45 DTE).

    VALIDIERTE Score-Logik (basierend auf 174k+ Gap-Events, 907 Symbole, 5 Jahre Daten):

    Erkenntnisse aus Datenvalidierung:
    - Kurzfristig (1-5d): Up-Gaps performen leicht besser (Momentum)
    - Mittelfristig (10-60d): Down-Gaps performen besser (+0.43% bei 30d)
    - Große Gaps (>3%): Down-Gaps deutlich besser (+1.21% Differenz bei 5d)
    - Win-Rate 30d: Down-Gaps 56.7% vs Up-Gaps 54.8%

    Score-Logik für Bull-Put-Spreads (mittelfristige Perspektive):
    - Down-Gap (large, >3%): +0.8 bis +1.0 (beste Einstiegschance)
    - Down-Gap (medium, 1-3%): +0.3 bis +0.6
    - Down-Gap (small, <1%): +0.1 bis +0.3
    - No Gap: 0.0 (neutral)
    - Up-Gap (small): 0.0 (neutral, kurzfristiges Momentum)
    - Up-Gap (large, >3%): -0.3 bis -0.5 (Vorsicht, Überkauft)

    Args:
        gap_type: Typ des Gaps
        gap_size_pct: Größe in %
        is_filled: Wurde Gap gefüllt?
        fill_percentage: Wie viel % gefüllt
        avg_gap_size: Durchschnittliche Gap-Größe für Kontext

    Returns:
        Score von -1.0 (sehr bearish) bis +1.0 (sehr bullish für Entry)
    """
    if gap_type == 'none':
        return 0.0

    abs_size = abs(gap_size_pct)

    # Basis-Score basierend auf Gap-Typ (validiert mit 174k+ Events)
    if gap_type in ('down', 'partial_down'):
        # Down-Gaps sind gut für mittelfristige Entries (30-60d)
        # Validierung zeigt: +0.43% bessere 30d-Returns, +1.9pp höhere Win-Rate

        # Score skaliert stark mit Gap-Größe (validiert: >3% Gaps = +1.21% Outperformance)
        if abs_size >= 3.0:
            base_score = 0.8  # Sehr große Down-Gaps = beste Einstiegschance
        elif abs_size >= 2.0:
            base_score = 0.5
        elif abs_size >= 1.0:
            base_score = 0.3
        else:
            base_score = 0.1  # Kleine Gaps = schwaches Signal

        # Gap-Fill reduziert das Signal leicht
        if is_filled:
            base_score *= 0.7  # Gefüllter Gap = reduziertes Signal
        elif fill_percentage > 50:
            base_score *= 0.85  # Teilweise gefüllt

        # Full Down-Gap ist stärker als Partial
        if gap_type == 'partial_down':
            base_score *= 0.7

        return min(1.0, base_score)

    elif gap_type in ('up', 'partial_up'):
        # Up-Gaps: Kurzfristig gut (Momentum), aber mittelfristig schwächer
        # Für Bull-Put-Spreads (30-45 DTE): Neutrale bis leicht negative Bewertung

        # Kleine Up-Gaps sind neutral (kurzfristiges Momentum)
        if abs_size < 1.0:
            base_score = 0.0  # Neutral für kleine Up-Gaps

        # Mittlere Up-Gaps: leicht negativ
        elif abs_size < 2.0:
            base_score = -0.1

        # Große Up-Gaps: stärker negativ (Überkauft-Risiko)
        elif abs_size < 3.0:
            base_score = -0.2

        # Sehr große Up-Gaps: deutlich negativ
        else:
            base_score = -0.4

        # Gap-Fill mildert das negative Signal
        if is_filled:
            base_score *= 0.5  # Gefüllter Gap = weniger negativ
        elif fill_percentage > 50:
            base_score *= 0.7

        # Full Up-Gap ist stärker negativ als Partial
        if gap_type == 'partial_up':
            base_score *= 0.7

        return max(-1.0, base_score)

    return 0.0


# =============================================================================
# GAP STATISTICS & VALIDATION
# =============================================================================

def calculate_gap_statistics(
    symbol: str,
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback_days: int = STATS_LOOKBACK_DAYS,
    min_gap_pct: float = MIN_GAP_THRESHOLD_PCT,
    forward_days: int = PERFORMANCE_FORWARD_DAYS,
) -> Optional[GapStatistics]:
    """
    Berechnet umfassende Gap-Statistiken für Validierung der Gap-These.

    Diese Funktion wird verwendet um zu validieren, ob:
    - Down-Gaps tatsächlich gute Einstiegspunkte sind
    - Up-Gaps tatsächlich schlechtere Performance zeigen

    Args:
        symbol: Symbol-Name
        opens, highs, lows, closes: Preisdaten (älteste zuerst)
        lookback_days: Analysezeitraum
        min_gap_pct: Minimale Gap-Größe
        forward_days: Tage für Forward-Return-Berechnung

    Returns:
        GapStatistics mit aggregierten Metriken
    """
    n = len(closes)
    if n < lookback_days + forward_days:
        logger.warning(f"Gap stats: Nicht genug Daten für {symbol}")
        return None

    if len(opens) != n or len(highs) != n or len(lows) != n:
        logger.warning(f"Gap stats: Ungleiche Array-Längen für {symbol}")
        return None

    # Gap-Tracking
    up_gaps: List[Tuple[int, float]] = []  # (index, gap_size)
    down_gaps: List[Tuple[int, float]] = []
    partial_up_gaps: List[Tuple[int, float]] = []
    partial_down_gaps: List[Tuple[int, float]] = []

    # Fill-Tracking
    up_gap_fills = 0
    down_gap_fills = 0
    fill_times: List[int] = []

    start_idx = max(1, n - lookback_days)

    for i in range(start_idx, n - forward_days):
        gap_type, gap_size, _, is_filled, _ = detect_gap(
            prev_open=opens[i - 1],
            prev_high=highs[i - 1],
            prev_low=lows[i - 1],
            prev_close=closes[i - 1],
            curr_open=opens[i],
            curr_high=highs[i],
            curr_low=lows[i],
            curr_close=closes[i],
            min_gap_pct=min_gap_pct,
        )

        if gap_type == 'up':
            up_gaps.append((i, gap_size))
            if is_filled:
                up_gap_fills += 1
        elif gap_type == 'down':
            down_gaps.append((i, gap_size))
            if is_filled:
                down_gap_fills += 1
        elif gap_type == 'partial_up':
            partial_up_gaps.append((i, gap_size))
        elif gap_type == 'partial_down':
            partial_down_gaps.append((i, gap_size))

        # Multi-Day Fill-Tracking
        if gap_type in ('up', 'down') and not is_filled:
            fill_time = _find_gap_fill_time(
                gap_type=gap_type,
                gap_open=opens[i],
                target_price=closes[i - 1],
                highs=highs[i:],
                lows=lows[i:],
                max_days=forward_days,
            )
            if fill_time is not None:
                fill_times.append(fill_time)
                if gap_type == 'up':
                    up_gap_fills += 1
                else:
                    down_gap_fills += 1

    # Performance nach Gap berechnen
    up_gap_returns = _calculate_forward_returns(up_gaps, closes, forward_days)
    down_gap_returns = _calculate_forward_returns(down_gaps, closes, forward_days)

    # Aggregierte Statistiken
    total_gaps = len(up_gaps) + len(down_gaps) + len(partial_up_gaps) + len(partial_down_gaps)

    return GapStatistics(
        symbol=symbol,
        analysis_period_days=min(lookback_days, n - forward_days - 1),
        total_gaps=total_gaps,
        up_gaps=len(up_gaps),
        down_gaps=len(down_gaps),
        partial_up_gaps=len(partial_up_gaps),
        partial_down_gaps=len(partial_down_gaps),
        up_gap_fill_rate=up_gap_fills / len(up_gaps) if up_gaps else 0.0,
        down_gap_fill_rate=down_gap_fills / len(down_gaps) if down_gaps else 0.0,
        avg_fill_time_days=np.mean(fill_times) if fill_times else 0.0,
        avg_return_after_up_gap_5d=np.mean(up_gap_returns) if up_gap_returns else 0.0,
        avg_return_after_down_gap_5d=np.mean(down_gap_returns) if down_gap_returns else 0.0,
        win_rate_after_up_gap=sum(1 for r in up_gap_returns if r > 0) / len(up_gap_returns) if up_gap_returns else 0.0,
        win_rate_after_down_gap=sum(1 for r in down_gap_returns if r > 0) / len(down_gap_returns) if down_gap_returns else 0.0,
    )


def _find_gap_fill_time(
    gap_type: str,
    gap_open: float,
    target_price: float,
    highs: List[float],
    lows: List[float],
    max_days: int,
) -> Optional[int]:
    """
    Findet wie viele Tage es dauert, bis ein Gap gefüllt wird.

    Args:
        gap_type: 'up' oder 'down'
        gap_open: Opening-Preis am Gap-Tag
        target_price: Previous Close (Ziel für Fill)
        highs, lows: Preisdaten nach dem Gap
        max_days: Maximale Tage zum Suchen

    Returns:
        Anzahl Tage bis Fill oder None wenn nicht gefüllt
    """
    for day in range(1, min(max_days, len(highs))):
        if gap_type == 'up':
            # Up-Gap gefüllt wenn Low <= target_price
            if lows[day] <= target_price:
                return day
        else:
            # Down-Gap gefüllt wenn High >= target_price
            if highs[day] >= target_price:
                return day
    return None


def _calculate_forward_returns(
    gaps: List[Tuple[int, float]],
    closes: List[float],
    forward_days: int,
) -> List[float]:
    """
    Berechnet Forward-Returns nach Gap-Events.

    Args:
        gaps: Liste von (index, gap_size) Tupeln
        closes: Close-Preise
        forward_days: Tage für Return-Berechnung

    Returns:
        Liste von Returns (in %)
    """
    returns = []
    for idx, _ in gaps:
        if idx + forward_days < len(closes):
            entry_price = closes[idx]
            exit_price = closes[idx + forward_days]
            if entry_price > 0:
                ret = ((exit_price - entry_price) / entry_price) * 100
                returns.append(ret)
    return returns


# =============================================================================
# GAP SERIES FOR BACKTESTING
# =============================================================================

def calculate_gap_series(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    min_gap_pct: float = MIN_GAP_THRESHOLD_PCT,
) -> List[Optional[GapResult]]:
    """
    Berechnet Gap-Analyse für jeden Tag in der Serie.

    Nützlich für Backtesting und ML-Training.

    Args:
        opens, highs, lows, closes: Preisdaten (älteste zuerst)
        min_gap_pct: Minimale Gap-Größe

    Returns:
        Liste von GapResult (None für erste Tage ohne genug History)
    """
    n = len(closes)
    if n < 2:
        return [None] * n

    results: List[Optional[GapResult]] = [None]  # Erster Tag hat keinen Gap

    for i in range(1, n):
        # Verwende Daten bis zum aktuellen Tag
        result = analyze_gap(
            opens=opens[:i + 1],
            highs=highs[:i + 1],
            lows=lows[:i + 1],
            closes=closes[:i + 1],
            lookback_days=min(DEFAULT_LOOKBACK_DAYS, i),
            min_gap_pct=min_gap_pct,
        )
        results.append(result)

    return results


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def gap_type_to_score_factor(gap_type: str) -> float:
    """
    Konvertiert Gap-Typ zu einem einfachen Score-Faktor.

    Für schnelle Berechnungen ohne volle Analyse.

    Returns:
        +1.0 für Down-Gap (bullish für Entry)
        -1.0 für Up-Gap (bearish für Entry)
        0.0 für kein Gap
    """
    if gap_type in ('down', 'partial_down'):
        return 1.0
    elif gap_type in ('up', 'partial_up'):
        return -1.0
    return 0.0


def is_significant_gap(gap_size_pct: float, threshold: float = MIN_GAP_THRESHOLD_PCT) -> bool:
    """Prüft ob Gap groß genug ist um signifikant zu sein."""
    return abs(gap_size_pct) >= threshold


def get_gap_description(gap_result: GapResult) -> str:
    """
    Erstellt lesbare Beschreibung eines Gaps.

    Args:
        gap_result: GapResult Objekt

    Returns:
        Beschreibender String
    """
    if gap_result.gap_type == 'none':
        return "Kein signifikanter Gap"

    direction = "aufwärts" if 'up' in gap_result.gap_type else "abwärts"
    full_partial = "Full" if gap_result.gap_type in ('up', 'down') else "Partial"
    filled_str = "gefüllt" if gap_result.is_filled else f"{gap_result.fill_percentage:.0f}% gefüllt"

    quality_desc = "neutral"
    if gap_result.quality_score > 0.5:
        quality_desc = "bullish (guter Entry)"
    elif gap_result.quality_score > 0:
        quality_desc = "leicht bullish"
    elif gap_result.quality_score < -0.5:
        quality_desc = "bearish (Vorsicht)"
    elif gap_result.quality_score < 0:
        quality_desc = "leicht bearish"

    return (
        f"{full_partial} Gap {direction}: {gap_result.gap_size_pct:+.2f}% "
        f"({filled_str}) - {quality_desc}"
    )
