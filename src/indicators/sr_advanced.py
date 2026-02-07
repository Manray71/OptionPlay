# OptionPlay - Support/Resistance Advanced Module
# =================================================
# Advanced analysis functions: nearest S/R levels with context,
# volume profile, level test analysis, volume-validated S/R,
# and event-aware analysis.

from __future__ import annotations

from typing import List, Dict, Optional, Tuple, Any
import logging

from .sr_core import (
    PriceLevel,
    VolumeZone,
    VolumeProfile,
    LevelTest,
    SupportResistanceResult,
    analyze_support_resistance,
    calculate_fibonacci,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ADVANCED: NEAREST S/R WITH CONTEXT
# =============================================================================

def get_nearest_sr_levels(
    current_price: float,
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: Optional[List[int]] = None,
    lookback: int = 252,  # 12 months
    num_levels: int = 3
) -> Dict[str, Any]:
    """
    Get the nearest support and resistance levels relative to current price.

    Returns the closest N support levels BELOW current price and
    the closest N resistance levels ABOVE current price, with touch counts
    and additional context (52-week high/low, Fibonacci, SMAs).

    Args:
        current_price: Current stock price
        prices: Close prices
        highs: High prices
        lows: Low prices
        volumes: Volume data (optional)
        lookback: Days to look back (default 252 = 12 months)
        num_levels: Number of levels to return per type (default 3)

    Returns:
        Dict with 'supports', 'resistances', and context data
    """
    result = {
        'supports': [],
        'resistances': [],
        'current_price': current_price,
        'context': {}
    }

    # Use effective lookback (max available data)
    effective_lookback = min(lookback, len(lows))

    if effective_lookback < 20:
        return result

    # Calculate context: 52-week high/low
    week_52_high = max(highs[-effective_lookback:]) if effective_lookback > 0 else current_price
    week_52_low = min(lows[-effective_lookback:]) if effective_lookback > 0 else current_price

    # Calculate SMAs
    sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else None
    sma_100 = sum(prices[-100:]) / 100 if len(prices) >= 100 else None
    sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else None

    # Calculate Fibonacci retracement levels (from 52-week range)
    fib_levels = calculate_fibonacci(week_52_high, week_52_low)

    # Store context
    result['context'] = {
        'week_52_high': round(week_52_high, 2),
        'week_52_low': round(week_52_low, 2),
        'sma_50': round(sma_50, 2) if sma_50 else None,
        'sma_100': round(sma_100, 2) if sma_100 else None,
        'sma_200': round(sma_200, 2) if sma_200 else None,
        'fib_levels': {k: round(v, 2) for k, v in fib_levels.items()}
    }

    # Get full S/R analysis with 12-month lookback
    sr_result = analyze_support_resistance(
        prices=prices,
        highs=highs,
        lows=lows,
        volumes=volumes,
        lookback=effective_lookback,
        window=5,
        max_levels=15,  # Get more to filter
        tolerance_pct=1.5
    )

    # Helper function to describe a level
    def describe_level(price: float, level_type: str) -> str:
        """Generate description for a support/resistance level."""
        descriptions = []

        # Check 52-week extremes
        if abs(price - week_52_low) / week_52_low < 0.02:
            descriptions.append("52W-Tief")
        elif abs(price - week_52_high) / week_52_high < 0.02:
            descriptions.append("52W-Hoch")

        # Check Fibonacci levels
        for fib_name, fib_price in fib_levels.items():
            if abs(price - fib_price) / fib_price < 0.015:  # 1.5% tolerance
                descriptions.append(f"Fib {fib_name}")
                break

        # Check SMAs
        if sma_50 and abs(price - sma_50) / sma_50 < 0.015:
            descriptions.append("SMA50")
        if sma_100 and abs(price - sma_100) / sma_100 < 0.015:
            descriptions.append("SMA100")
        if sma_200 and abs(price - sma_200) / sma_200 < 0.015:
            descriptions.append("SMA200")

        return ", ".join(descriptions) if descriptions else ""

    # Filter supports: only those BELOW current price, sorted by distance (closest first)
    supports_below = [
        lvl for lvl in sr_result.support_levels
        if lvl.price < current_price
    ]
    supports_below.sort(key=lambda x: current_price - x.price)  # Closest first

    for lvl in supports_below[:num_levels]:
        distance_pct = ((current_price - lvl.price) / current_price) * 100
        result['supports'].append({
            'price': round(lvl.price, 2),
            'touches': lvl.touches,
            'strength': round(lvl.strength, 3),
            'distance_pct': round(distance_pct, 2),
            'hold_rate': round(lvl.hold_rate, 2) if lvl.hold_rate else 0.0,
            'description': describe_level(lvl.price, 'support')
        })

    # Filter resistances: only those ABOVE current price, sorted by distance (closest first)
    resistances_above = [
        lvl for lvl in sr_result.resistance_levels
        if lvl.price > current_price
    ]
    resistances_above.sort(key=lambda x: x.price - current_price)  # Closest first

    for lvl in resistances_above[:num_levels]:
        distance_pct = ((lvl.price - current_price) / current_price) * 100
        result['resistances'].append({
            'price': round(lvl.price, 2),
            'touches': lvl.touches,
            'strength': round(lvl.strength, 3),
            'distance_pct': round(distance_pct, 2),
            'hold_rate': round(lvl.hold_rate, 2) if lvl.hold_rate else 0.0,
            'description': describe_level(lvl.price, 'resistance')
        })

    return result


# =============================================================================
# VOLUME PROFILE ANALYSIS
# =============================================================================

def calculate_volume_profile(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    num_zones: int = 20,
    value_area_pct: float = 70.0
) -> VolumeProfile:
    """
    Berechnet das Volume Profile für einen Preisbereich.

    Das Volume Profile zeigt die Volumenverteilung über Preiszonen.
    High Volume Nodes (HVN) sind potenzielle Support/Resistance Zonen.

    Args:
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        num_zones: Anzahl der Preiszonen
        value_area_pct: Prozentsatz für Value Area (typisch 70%)

    Returns:
        VolumeProfile mit allen Zonen und Analysen
    """
    if not prices or not volumes or len(prices) != len(volumes):
        return VolumeProfile()

    # Bestimme Preisbereich
    price_high = max(highs) if highs else max(prices)
    price_low = min(lows) if lows else min(prices)

    if price_high == price_low:
        return VolumeProfile()

    zone_height = (price_high - price_low) / num_zones

    # Initialisiere Zonen
    zones: List[VolumeZone] = []
    for i in range(num_zones):
        zone_low = price_low + i * zone_height
        zone_high = zone_low + zone_height
        zones.append(VolumeZone(price_low=zone_low, price_high=zone_high))

    # Verteile Volumen auf Zonen
    for i, (h, l, vol) in enumerate(zip(highs, lows, volumes)):
        # Verteile Volumen proportional auf alle berührten Zonen
        bar_range = h - l if h > l else zone_height

        for zone in zones:
            # Überlappung berechnen
            overlap_low = max(zone.price_low, l)
            overlap_high = min(zone.price_high, h)

            if overlap_high > overlap_low:
                # Proportionaler Anteil des Volumens
                overlap_ratio = (overlap_high - overlap_low) / bar_range
                zone.total_volume += int(vol * overlap_ratio)
                zone.bar_count += 1

    # Berechne Durchschnittsvolumen pro Zone
    total_vol = sum(z.total_volume for z in zones)
    avg_vol_per_zone = total_vol / num_zones if num_zones > 0 else 0

    # Identifiziere HVN und LVN (1.5x über/unter Durchschnitt)
    hvn_threshold = avg_vol_per_zone * 1.5
    lvn_threshold = avg_vol_per_zone * 0.5

    for zone in zones:
        zone.is_high_volume_node = zone.total_volume > hvn_threshold
        zone.is_low_volume_node = zone.total_volume < lvn_threshold

    # Finde POC (Point of Control = Zone mit höchstem Volumen)
    poc = max(zones, key=lambda z: z.total_volume) if zones else None

    # Berechne Value Area (70% des Volumens um POC)
    sorted_by_volume = sorted(zones, key=lambda z: z.total_volume, reverse=True)
    value_area_target = total_vol * (value_area_pct / 100)
    cumulative_vol = 0
    value_area_zones = []

    for zone in sorted_by_volume:
        cumulative_vol += zone.total_volume
        value_area_zones.append(zone)
        if cumulative_vol >= value_area_target:
            break

    value_area_high = max(z.price_high for z in value_area_zones) if value_area_zones else price_high
    value_area_low = min(z.price_low for z in value_area_zones) if value_area_zones else price_low

    hvn_zones = [z for z in zones if z.is_high_volume_node]

    return VolumeProfile(
        zones=zones,
        poc=poc,
        value_area_high=value_area_high,
        value_area_low=value_area_low,
        hvn_zones=hvn_zones
    )


# =============================================================================
# TOUCH QUALITY & VOLUME CONFIRMATION
# =============================================================================

def analyze_level_tests(
    level_price: float,
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    level_type: str = "support",
    tolerance_pct: float = 1.5,
    lookback: int = 60
) -> Tuple[List[LevelTest], float, float]:
    """
    Analysiert alle Tests eines S/R Levels.

    Für jeden Test wird geprüft:
    - Wie nah kam der Preis ans Level?
    - Wie hoch war das Volumen?
    - Hat das Level gehalten?
    - Wie stark war der Bounce?

    Args:
        level_price: Das zu analysierende S/R Level
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        level_type: 'support' oder 'resistance'
        tolerance_pct: Toleranz für Level-Test
        lookback: Wie weit zurückschauen

    Returns:
        Tuple von:
        - Liste der LevelTest-Objekte
        - Touch-Quality Score (0-1)
        - Volume Confirmation Score (0-1)
    """
    if not prices or len(prices) < 2:
        return [], 0.0, 0.0

    lookback = min(lookback, len(prices))
    start_idx = len(prices) - lookback

    # Berechne Durchschnittsvolumen
    avg_volume = sum(volumes[start_idx:]) / lookback if volumes else 1

    tests: List[LevelTest] = []
    tolerance = tolerance_pct / 100

    for i in range(start_idx, len(prices) - 1):
        test_price = lows[i] if level_type == "support" else highs[i]
        close_after = prices[i + 1]
        vol = volumes[i] if volumes else 0

        # Prüfe ob Level getestet wurde
        distance_pct = abs(test_price - level_price) / level_price

        if distance_pct <= tolerance:
            # Level wurde getestet
            vol_ratio = vol / avg_volume if avg_volume > 0 else 1.0

            # Prüfe ob Level gehalten hat
            if level_type == "support":
                held = close_after > level_price * (1 - tolerance)
                bounce_pct = (close_after - test_price) / test_price * 100
            else:
                held = close_after < level_price * (1 + tolerance)
                bounce_pct = (test_price - close_after) / test_price * 100

            test = LevelTest(
                index=i,
                price_at_test=test_price,
                close_after=close_after,
                volume_at_test=vol,
                volume_ratio=vol_ratio,
                distance_pct=distance_pct * 100,
                held=held,
                bounce_pct=bounce_pct
            )
            tests.append(test)

    if not tests:
        return [], 0.0, 0.0

    # Berechne Touch-Quality Score
    # Basiert auf: Präzision der Touches + Hold-Rate + Bounce-Stärke
    precision_scores = [1.0 - (t.distance_pct / (tolerance_pct * 100)) for t in tests]
    avg_precision = sum(precision_scores) / len(precision_scores)

    hold_rate = sum(1 for t in tests if t.held) / len(tests)

    avg_bounce = sum(abs(t.bounce_pct) for t in tests) / len(tests)
    bounce_score = min(avg_bounce / 3.0, 1.0)  # Max bei 3% Bounce

    touch_quality = (avg_precision * 0.3) + (hold_rate * 0.4) + (bounce_score * 0.3)

    # Berechne Volume Confirmation Score
    # Erhöhtes Volumen bei Tests = stärkere Bestätigung
    vol_ratios = [t.volume_ratio for t in tests]
    avg_vol_ratio = sum(vol_ratios) / len(vol_ratios)

    # Score: 0.5 bei normalem Volumen, 1.0 bei 2x Volumen
    volume_confirmation = min(avg_vol_ratio / 2.0, 1.0)

    return tests, touch_quality, volume_confirmation


def validate_level_with_volume(
    level: PriceLevel,
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    lookback: int = 60
) -> PriceLevel:
    """
    Erweitert ein PriceLevel mit Volumen-Validierung.

    Analysiert alle historischen Tests des Levels und fügt
    Touch-Quality und Volume-Confirmation Scores hinzu.

    Args:
        level: Das zu validierende PriceLevel
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        lookback: Wie weit zurückschauen

    Returns:
        Das Level mit aktualisierten Scores
    """
    tests, touch_quality, volume_confirmation = analyze_level_tests(
        level_price=level.price,
        prices=prices,
        highs=highs,
        lows=lows,
        volumes=volumes,
        level_type=level.level_type,
        lookback=lookback
    )

    level.touch_quality = touch_quality
    level.volume_confirmation = volume_confirmation
    level.hold_count = sum(1 for t in tests if t.held)
    level.break_count = sum(1 for t in tests if not t.held)

    # Aktualisiere Stärke mit neuen Faktoren
    # Originale Stärke bleibt zu 50%, 25% Touch-Quality, 25% Volume
    level.strength = (
        level.strength * 0.5 +
        touch_quality * 0.25 +
        volume_confirmation * 0.25
    )

    return level


def get_volume_at_level(
    level_price: float,
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    tolerance_pct: float = 1.5
) -> Tuple[int, float]:
    """
    Berechnet das Gesamtvolumen, das an einem Level gehandelt wurde.

    Args:
        level_price: Das S/R Level
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        tolerance_pct: Toleranz für Level-Bereich

    Returns:
        Tuple von:
        - Gesamtvolumen an diesem Level
        - Verhältnis zum Durchschnittsvolumen
    """
    if not volumes or not highs or not lows:
        return 0, 0.0

    tolerance = level_price * (tolerance_pct / 100)
    level_high = level_price + tolerance
    level_low = level_price - tolerance

    level_volume = 0
    touch_count = 0

    for h, l, vol in zip(highs, lows, volumes):
        # Prüfe ob Bar das Level berührt
        if l <= level_high and h >= level_low:
            # Proportionaler Anteil
            bar_range = h - l if h > l else 1
            overlap_low = max(level_low, l)
            overlap_high = min(level_high, h)

            if overlap_high > overlap_low:
                overlap_ratio = (overlap_high - overlap_low) / bar_range
                level_volume += int(vol * overlap_ratio)
                touch_count += 1

    avg_volume = sum(volumes) / len(volumes) if volumes else 1
    volume_ratio = level_volume / (avg_volume * max(touch_count, 1)) if avg_volume > 0 else 0

    return level_volume, volume_ratio


# =============================================================================
# ENHANCED ANALYSIS WITH VALIDATION
# =============================================================================

def analyze_support_resistance_with_validation(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 5,
    tolerance_pct: float = 1.5,
    include_volume_profile: bool = True
) -> SupportResistanceResult:
    """
    Vollständige S/R Analyse mit Volumen-Validierung.

    Kombiniert:
    - Swing High/Low Detection (optimiert O(n))
    - Level-Clustering
    - Touch-Quality Scoring
    - Volume Confirmation
    - Volume Profile (optional)

    Args:
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße für Swing Detection
        max_levels: Max Levels pro Typ
        tolerance_pct: Clustering-Toleranz
        include_volume_profile: Volume Profile berechnen

    Returns:
        SupportResistanceResult mit vollständiger Validierung
    """
    # Basis-Analyse
    result = analyze_support_resistance(
        prices=prices,
        highs=highs,
        lows=lows,
        volumes=volumes,
        lookback=lookback,
        window=window,
        max_levels=max_levels,
        tolerance_pct=tolerance_pct
    )

    # Validiere Support-Levels mit Volumen
    for level in result.support_levels:
        validate_level_with_volume(
            level=level,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=lookback
        )

    # Validiere Resistance-Levels mit Volumen
    for level in result.resistance_levels:
        validate_level_with_volume(
            level=level,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=lookback
        )

    # Re-sortiere nach aktualisierter Stärke
    result.support_levels.sort(key=lambda x: x.strength, reverse=True)
    result.resistance_levels.sort(key=lambda x: x.strength, reverse=True)

    # Volume Profile (optional)
    if include_volume_profile and volumes:
        result.volume_profile = calculate_volume_profile(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes
        )

    return result


# =============================================================================
# EVENT-AWARE ANALYSIS
# =============================================================================

def analyze_sr_with_events(
    symbol: str,
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    event_calendar=None,
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 5,
    tolerance_pct: float = 1.5,
    include_volume_profile: bool = True,
    lookahead_days: int = 14
) -> Tuple['SupportResistanceResult', Optional[Dict]]:
    """
    Vollständige S/R Analyse mit Event-Validierung.

    Kombiniert:
    - Technische S/R Detection
    - Volume Validation
    - Event-basierte Confidence-Anpassung

    Args:
        symbol: Ticker-Symbol
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen
        event_calendar: EventCalendar für Event-Prüfung (optional)
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße
        max_levels: Max Levels pro Typ
        tolerance_pct: Clustering-Toleranz
        include_volume_profile: Volume Profile berechnen
        lookahead_days: Tage voraus für Events prüfen

    Returns:
        Tuple von:
        - SupportResistanceResult mit vollständiger Analyse
        - Event-Validierung Dict (oder None wenn kein Calendar)
    """
    # Technische Analyse
    result = analyze_support_resistance_with_validation(
        prices=prices,
        highs=highs,
        lows=lows,
        volumes=volumes,
        lookback=lookback,
        window=window,
        max_levels=max_levels,
        tolerance_pct=tolerance_pct,
        include_volume_profile=include_volume_profile
    )

    # Event-Validierung (optional)
    event_validation = None
    if event_calendar is not None:
        try:
            validation = event_calendar.validate_for_sr(
                symbol=symbol,
                lookahead_days=lookahead_days
            )
            event_validation = validation.to_dict()

            # Adjustiere Level-Stärken basierend auf Event-Confidence
            multiplier = validation.confidence_multiplier
            if multiplier < 1.0:
                for level in result.support_levels:
                    level.strength *= multiplier
                for level in result.resistance_levels:
                    level.strength *= multiplier

                # Re-sortiere nach adjustierter Stärke
                result.support_levels.sort(key=lambda x: x.strength, reverse=True)
                result.resistance_levels.sort(key=lambda x: x.strength, reverse=True)

            # Füge Event-Warnungen zum Ergebnis hinzu
            if validation.blocking_events:
                logger.warning(
                    f"{symbol}: S/R Levels durch Events beeinträchtigt: "
                    f"{[e.event_type.value for e in validation.blocking_events]}"
                )

        except Exception as e:
            logger.debug(f"Event validation failed for {symbol}: {e}")

    return result, event_validation


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Advanced S/R with context
    'get_nearest_sr_levels',

    # Volume Profile
    'calculate_volume_profile',

    # Touch Quality & Volume Confirmation
    'analyze_level_tests',
    'validate_level_with_volume',
    'get_volume_at_level',

    # Enhanced Analysis with Validation
    'analyze_support_resistance_with_validation',

    # Event-Aware Analysis
    'analyze_sr_with_events',
]
