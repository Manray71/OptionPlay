# OptionPlay - Support/Resistance Indicators
# ============================================
# Optimierte Support/Resistance Level Detection
#
# Features:
# - O(n) Sliding Window Algorithmus mit Monotoner Deque
# - Volume-Weighted Level Scoring
# - Intelligentes Level-Clustering
# - Aktualitäts-Gewichtung
#
# Performance:
# - Alte Implementierung: O(n × window) pro Durchlauf
# - Neue Implementierung: O(n) pro Durchlauf
# - Bei 252 Tagen, window=20: ~5x schneller

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Deque
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class PriceLevel:
    """
    Repräsentiert ein Support- oder Resistance-Level mit Metadaten.

    Attributes:
        price: Der Preiswert des Levels
        strength: Stärke des Levels (0.0 - 1.0)
        touches: Anzahl der Berührungen/Tests
        indices: Indizes der Berührungspunkte
        volumes: Volumen bei jeder Berührung
        level_type: 'support' oder 'resistance'
        touch_quality: Qualität der Berührungen (0.0 - 1.0)
        volume_confirmation: Volumen-Bestätigung bei Level-Tests
        hold_count: Wie oft wurde das Level erfolgreich verteidigt
        break_count: Wie oft wurde das Level durchbrochen
    """
    price: float
    strength: float = 0.0
    touches: int = 1
    indices: List[int] = field(default_factory=list)
    volumes: List[int] = field(default_factory=list)
    level_type: str = "support"
    touch_quality: float = 0.0
    volume_confirmation: float = 0.0
    hold_count: int = 0
    break_count: int = 0

    @property
    def avg_volume(self) -> float:
        """Durchschnittliches Volumen bei Berührungen"""
        return sum(self.volumes) / len(self.volumes) if self.volumes else 0.0

    @property
    def last_touch_index(self) -> int:
        """Index der letzten Berührung"""
        return max(self.indices) if self.indices else -1

    @property
    def hold_rate(self) -> float:
        """Rate der erfolgreichen Verteidigungen (0.0 - 1.0)"""
        total = self.hold_count + self.break_count
        return self.hold_count / total if total > 0 else 0.0

    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary für JSON-Serialisierung"""
        return {
            'price': round(self.price, 2),
            'strength': round(self.strength, 3),
            'touches': self.touches,
            'avg_volume': round(self.avg_volume, 0),
            'last_touch_index': self.last_touch_index,
            'level_type': self.level_type,
            'touch_quality': round(self.touch_quality, 3),
            'volume_confirmation': round(self.volume_confirmation, 3),
            'hold_rate': round(self.hold_rate, 3)
        }


@dataclass
class VolumeZone:
    """
    Eine Zone im Volume Profile.

    Attributes:
        price_low: Untere Grenze der Zone
        price_high: Obere Grenze der Zone
        total_volume: Gesamtvolumen in dieser Zone
        bar_count: Anzahl der Bars in dieser Zone
        is_high_volume_node: True wenn signifikant hohes Volumen
        is_low_volume_node: True wenn signifikant niedriges Volumen
    """
    price_low: float
    price_high: float
    total_volume: int = 0
    bar_count: int = 0
    is_high_volume_node: bool = False
    is_low_volume_node: bool = False

    @property
    def price_center(self) -> float:
        """Zentrum der Preiszone"""
        return (self.price_low + self.price_high) / 2

    @property
    def avg_volume_per_bar(self) -> float:
        """Durchschnittliches Volumen pro Bar"""
        return self.total_volume / self.bar_count if self.bar_count > 0 else 0.0


@dataclass
class VolumeProfile:
    """
    Volume Profile Analyse-Ergebnis.

    Zeigt Volumenverteilung über Preiszonen.
    High Volume Nodes (HVN) = potenzielle S/R Zonen
    Low Volume Nodes (LVN) = Zonen mit wenig Interesse

    Attributes:
        zones: Liste aller Preiszonen
        poc: Point of Control (Zone mit höchstem Volumen)
        value_area_high: Obere Grenze der Value Area (70% Volumen)
        value_area_low: Untere Grenze der Value Area
        hvn_zones: High Volume Nodes
    """
    zones: List[VolumeZone] = field(default_factory=list)
    poc: Optional[VolumeZone] = None
    value_area_high: float = 0.0
    value_area_low: float = 0.0
    hvn_zones: List[VolumeZone] = field(default_factory=list)

    def get_hvn_prices(self) -> List[float]:
        """Gibt die Zentren der High Volume Nodes zurück"""
        return [zone.price_center for zone in self.hvn_zones]


@dataclass
class LevelTest:
    """
    Repräsentiert einen Test eines S/R Levels.

    Attributes:
        index: Index im Preisarray wo der Test stattfand
        price_at_test: Preis beim Test (Low für Support, High für Resistance)
        close_after: Schlusskurs nach dem Test
        volume_at_test: Volumen beim Test
        volume_ratio: Verhältnis zum Durchschnittsvolumen
        distance_pct: Abstand zum Level in Prozent
        held: True wenn Level gehalten hat
        bounce_pct: Bounce in Prozent (positiv = erfolgreich abgeprallt)
    """
    index: int
    price_at_test: float
    close_after: float
    volume_at_test: int
    volume_ratio: float = 1.0
    distance_pct: float = 0.0
    held: bool = True
    bounce_pct: float = 0.0


@dataclass
class SupportResistanceResult:
    """
    Container für Support/Resistance Analyse-Ergebnisse.

    Attributes:
        support_levels: Liste der Support-Levels (stärkste zuerst)
        resistance_levels: Liste der Resistance-Levels (stärkste zuerst)
        nearest_support: Nächstes Support-Level zum aktuellen Preis
        nearest_resistance: Nächstes Resistance-Level zum aktuellen Preis
        volume_profile: Volume Profile Analyse (optional)
    """
    support_levels: List[PriceLevel] = field(default_factory=list)
    resistance_levels: List[PriceLevel] = field(default_factory=list)
    nearest_support: Optional[PriceLevel] = None
    nearest_resistance: Optional[PriceLevel] = None
    volume_profile: Optional[VolumeProfile] = None

    def get_support_prices(self) -> List[float]:
        """Gibt nur die Preise der Support-Levels zurück"""
        return [level.price for level in self.support_levels]

    def get_resistance_prices(self) -> List[float]:
        """Gibt nur die Preise der Resistance-Levels zurück"""
        return [level.price for level in self.resistance_levels]

    def get_strongest_support(self) -> Optional[PriceLevel]:
        """Gibt das stärkste Support-Level zurück"""
        return self.support_levels[0] if self.support_levels else None

    def get_strongest_resistance(self) -> Optional[PriceLevel]:
        """Gibt das stärkste Resistance-Level zurück"""
        return self.resistance_levels[0] if self.resistance_levels else None


# =============================================================================
# O(n) SLIDING WINDOW ALGORITHMS
# =============================================================================

def find_local_minima_optimized(
    values: List[float],
    window: int
) -> List[int]:
    """
    Findet lokale Minima mit O(n) Komplexität durch Monotone Deque.

    Ein lokales Minimum ist ein Punkt, der das Minimum in einem Fenster
    von 'window' Punkten auf jeder Seite ist.

    Algorithmus:
    1. Sliding Window mit Monotoner Deque (aufsteigend sortiert)
    2. Deque speichert (index, value) Paare
    3. Bei jedem Schritt:
       - Entferne Elemente außerhalb des Fensters (links)
       - Entferne größere Elemente (rechts, können nie Minimum werden)
       - Prüfe ob Minimum in der Fenstermitte liegt

    Args:
        values: Liste von Werten (z.B. Tagestiefs)
        window: Halbe Fenstergröße (Gesamtfenster = 2*window + 1)

    Returns:
        Liste der Indizes, die lokale Minima sind
    """
    n = len(values)
    if n < 2 * window + 1:
        return []

    result: List[int] = []

    # Monotone Deque: speichert (index, value), aufsteigend nach value
    # Vorne ist immer das aktuelle Minimum
    dq: Deque[Tuple[int, float]] = deque()

    # Verarbeite jeden Punkt
    for i in range(n):
        # 1. Entferne Elemente außerhalb des Fensters (zu alt)
        while dq and dq[0][0] < i - window:
            dq.popleft()

        # 2. Entferne größere Elemente von hinten
        # (sie können nie Minimum werden, da neues Element kleiner ist)
        while dq and dq[-1][1] >= values[i]:
            dq.pop()

        # 3. Füge neues Element hinzu
        dq.append((i, values[i]))

        # 4. Prüfe ob wir genug Daten haben und ob Minimum in Mitte liegt
        if i >= 2 * window:
            center = i - window
            # Das Minimum im Fenster [center-window, center+window]
            # ist vorne in der Deque
            if dq[0][0] == center:
                result.append(center)

    return result


def find_local_maxima_optimized(
    values: List[float],
    window: int
) -> List[int]:
    """
    Findet lokale Maxima mit O(n) Komplexität durch Monotone Deque.

    Analog zu find_local_minima_optimized, aber für Maxima.

    Args:
        values: Liste von Werten (z.B. Tageshochs)
        window: Halbe Fenstergröße

    Returns:
        Liste der Indizes, die lokale Maxima sind
    """
    n = len(values)
    if n < 2 * window + 1:
        return []

    result: List[int] = []

    # Monotone Deque: absteigend sortiert (Vorne ist Maximum)
    dq: Deque[Tuple[int, float]] = deque()

    for i in range(n):
        # 1. Entferne Elemente außerhalb des Fensters
        while dq and dq[0][0] < i - window:
            dq.popleft()

        # 2. Entferne kleinere Elemente von hinten
        while dq and dq[-1][1] <= values[i]:
            dq.pop()

        # 3. Füge neues Element hinzu
        dq.append((i, values[i]))

        # 4. Prüfe ob Maximum in Mitte liegt
        if i >= 2 * window:
            center = i - window
            if dq[0][0] == center:
                result.append(center)

    return result


# =============================================================================
# LEVEL CLUSTERING
# =============================================================================

def cluster_levels(
    prices: List[float],
    indices: List[int],
    volumes: Optional[List[int]] = None,
    tolerance_pct: float = 1.5
) -> List[PriceLevel]:
    """
    Clustert ähnliche Preisniveaus zu gemeinsamen Levels.

    Verwendet einen einfachen greedy Clustering-Ansatz:
    - Sortiere Preise aufsteigend
    - Füge jeden Preis zum nächsten Cluster hinzu, wenn er innerhalb
      der Toleranz liegt, sonst erstelle neuen Cluster

    Args:
        prices: Liste von Preiswerten (z.B. Swing Lows)
        indices: Korrespondierende Indizes im Original-Array
        volumes: Volumen bei jedem Preis (optional)
        tolerance_pct: Toleranz für Clustering in Prozent

    Returns:
        Liste von PriceLevel-Objekten, nach Stärke sortiert
    """
    if not prices:
        return []

    # Erstelle (preis, index, volume) Tupel und sortiere nach Preis
    if volumes is None:
        volumes = [0] * len(prices)

    data = sorted(zip(prices, indices, volumes), key=lambda x: x[0])

    clusters: List[PriceLevel] = []

    for price, idx, vol in data:
        # Finde passenden Cluster
        found = False
        for cluster in clusters:
            # Prüfe ob Preis nahe genug am Cluster ist
            distance_pct = abs(price - cluster.price) / cluster.price * 100

            if distance_pct <= tolerance_pct:
                # Füge zum Cluster hinzu
                # Aktualisiere Durchschnittspreis gewichtet nach Touches
                old_price = cluster.price
                old_touches = cluster.touches
                cluster.price = (old_price * old_touches + price) / (old_touches + 1)
                cluster.touches += 1
                cluster.indices.append(idx)
                if vol > 0:
                    cluster.volumes.append(vol)
                found = True
                break

        if not found:
            # Erstelle neuen Cluster
            new_cluster = PriceLevel(
                price=price,
                touches=1,
                indices=[idx],
                volumes=[vol] if vol > 0 else []
            )
            clusters.append(new_cluster)

    return clusters


def score_levels(
    levels: List[PriceLevel],
    total_length: int,
    avg_volume: float,
    level_type: str = "support"
) -> List[PriceLevel]:
    """
    Berechnet Stärke-Score für jedes Level.

    Score basiert auf:
    - Touch-Count (mehr Touches = stärker)
    - Volume (hohes Volumen bei Touches = stärker)
    - Aktualität (jüngere Touches = relevanter)

    Args:
        levels: Liste von PriceLevel-Objekten
        total_length: Gesamtlänge der Originaldaten (für Aktualität)
        avg_volume: Durchschnittliches Volumen (für Normalisierung)
        level_type: 'support' oder 'resistance'

    Returns:
        Sortierte Liste nach Stärke (stärkste zuerst)
    """
    if not levels:
        return []

    for level in levels:
        level.level_type = level_type

        # 1. Touch-Score (0-0.4): log-skaliert, max bei 5+ Touches
        touch_score = min(level.touches / 5, 1.0) * 0.4

        # 2. Volume-Score (0-0.3): relativ zum Durchschnitt
        if level.avg_volume > 0 and avg_volume > 0:
            vol_ratio = level.avg_volume / avg_volume
            volume_score = min(vol_ratio / 2, 1.0) * 0.3
        else:
            volume_score = 0.15  # Neutral wenn keine Daten

        # 3. Aktualitäts-Score (0-0.3): jüngere = besser
        if level.last_touch_index >= 0 and total_length > 0:
            recency = level.last_touch_index / total_length
            recency_score = recency * 0.3
        else:
            recency_score = 0.15

        level.strength = touch_score + volume_score + recency_score

    # Sortiere nach Stärke (absteigend)
    return sorted(levels, key=lambda x: x.strength, reverse=True)


# =============================================================================
# MAIN API FUNCTIONS
# =============================================================================

def find_support_levels(
    lows: List[float],
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 3,
    volumes: Optional[List[int]] = None,
    tolerance_pct: float = 1.5
) -> List[float]:
    """
    Findet Support-Levels als Swing Lows (optimierte O(n) Version).

    Ein Swing Low ist ein Tief, das niedriger ist als alle Tiefs
    in einem Fenster von 'window' Tagen auf beiden Seiten.

    Args:
        lows: Tagestiefs (älteste zuerst)
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße für lokale Minima
        max_levels: Maximale Anzahl zurückgegebener Levels
        volumes: Optional: Volumen für Scoring
        tolerance_pct: Toleranz für Clustering

    Returns:
        Liste der Support-Levels (sortiert nach Stärke)
    """
    result = find_support_levels_enhanced(
        lows=lows,
        lookback=lookback,
        window=window,
        max_levels=max_levels,
        volumes=volumes,
        tolerance_pct=tolerance_pct
    )
    return result.get_support_prices()


def find_resistance_levels(
    highs: List[float],
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 3,
    volumes: Optional[List[int]] = None,
    tolerance_pct: float = 1.5
) -> List[float]:
    """
    Findet Resistance-Levels als Swing Highs (optimierte O(n) Version).

    Ein Swing High ist ein Hoch, das höher ist als alle Hochs
    in einem Fenster von 'window' Tagen auf beiden Seiten.

    Args:
        highs: Tageshochs (älteste zuerst)
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße für lokale Maxima
        max_levels: Maximale Anzahl zurückgegebener Levels
        volumes: Optional: Volumen für Scoring
        tolerance_pct: Toleranz für Clustering

    Returns:
        Liste der Resistance-Levels (sortiert nach Stärke)
    """
    result = find_resistance_levels_enhanced(
        highs=highs,
        lookback=lookback,
        window=window,
        max_levels=max_levels,
        volumes=volumes,
        tolerance_pct=tolerance_pct
    )
    return result.get_resistance_prices()


def find_support_levels_enhanced(
    lows: List[float],
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 5,
    volumes: Optional[List[int]] = None,
    tolerance_pct: float = 1.5
) -> SupportResistanceResult:
    """
    Erweiterte Support-Level Detection mit Scoring und Metadaten.

    Args:
        lows: Tagestiefs (älteste zuerst)
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße für lokale Minima
        max_levels: Maximale Anzahl zurückgegebener Levels
        volumes: Optional: Volumen für Scoring
        tolerance_pct: Toleranz für Clustering

    Returns:
        SupportResistanceResult mit detaillierten Level-Informationen
    """
    lookback = min(lookback, len(lows))
    min_required = 2 * window + 1

    if lookback < min_required:
        logger.debug(f"Not enough data for support detection: {lookback} < {min_required}")
        return SupportResistanceResult()

    # Arbeite nur mit den letzten 'lookback' Daten
    start_idx = len(lows) - lookback
    recent_lows = lows[start_idx:]
    recent_volumes = volumes[start_idx:] if volumes else None

    # O(n) Swing Low Detection
    swing_indices = find_local_minima_optimized(recent_lows, window)

    if not swing_indices:
        return SupportResistanceResult()

    # Extrahiere Preise und Volumen an Swing-Punkten
    swing_prices = [recent_lows[i] for i in swing_indices]
    swing_volumes = [recent_volumes[i] for i in swing_indices] if recent_volumes else None

    # Konvertiere zu globalen Indizes
    global_indices = [start_idx + i for i in swing_indices]

    # Cluster ähnliche Levels
    clustered = cluster_levels(
        prices=swing_prices,
        indices=global_indices,
        volumes=swing_volumes,
        tolerance_pct=tolerance_pct
    )

    # Berechne Scoring
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    scored = score_levels(
        levels=clustered,
        total_length=len(lows),
        avg_volume=avg_vol,
        level_type="support"
    )

    # Limitiere Anzahl
    support_levels = scored[:max_levels]

    # Finde nächstes Support zum aktuellen Preis
    current_price = lows[-1]
    nearest = None
    min_distance = float('inf')

    for level in support_levels:
        if level.price < current_price:
            distance = current_price - level.price
            if distance < min_distance:
                min_distance = distance
                nearest = level

    return SupportResistanceResult(
        support_levels=support_levels,
        nearest_support=nearest
    )


def find_resistance_levels_enhanced(
    highs: List[float],
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 5,
    volumes: Optional[List[int]] = None,
    tolerance_pct: float = 1.5
) -> SupportResistanceResult:
    """
    Erweiterte Resistance-Level Detection mit Scoring und Metadaten.

    Args:
        highs: Tageshochs (älteste zuerst)
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße für lokale Maxima
        max_levels: Maximale Anzahl zurückgegebener Levels
        volumes: Optional: Volumen für Scoring
        tolerance_pct: Toleranz für Clustering

    Returns:
        SupportResistanceResult mit detaillierten Level-Informationen
    """
    lookback = min(lookback, len(highs))
    min_required = 2 * window + 1

    if lookback < min_required:
        logger.debug(f"Not enough data for resistance detection: {lookback} < {min_required}")
        return SupportResistanceResult()

    # Arbeite nur mit den letzten 'lookback' Daten
    start_idx = len(highs) - lookback
    recent_highs = highs[start_idx:]
    recent_volumes = volumes[start_idx:] if volumes else None

    # O(n) Swing High Detection
    swing_indices = find_local_maxima_optimized(recent_highs, window)

    if not swing_indices:
        return SupportResistanceResult()

    # Extrahiere Preise und Volumen an Swing-Punkten
    swing_prices = [recent_highs[i] for i in swing_indices]
    swing_volumes = [recent_volumes[i] for i in swing_indices] if recent_volumes else None

    # Konvertiere zu globalen Indizes
    global_indices = [start_idx + i for i in swing_indices]

    # Cluster ähnliche Levels
    clustered = cluster_levels(
        prices=swing_prices,
        indices=global_indices,
        volumes=swing_volumes,
        tolerance_pct=tolerance_pct
    )

    # Berechne Scoring
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    scored = score_levels(
        levels=clustered,
        total_length=len(highs),
        avg_volume=avg_vol,
        level_type="resistance"
    )

    # Limitiere Anzahl
    resistance_levels = scored[:max_levels]

    # Finde nächste Resistance zum aktuellen Preis
    current_price = highs[-1]
    nearest = None
    min_distance = float('inf')

    for level in resistance_levels:
        if level.price > current_price:
            distance = level.price - current_price
            if distance < min_distance:
                min_distance = distance
                nearest = level

    return SupportResistanceResult(
        resistance_levels=resistance_levels,
        nearest_resistance=nearest
    )


def analyze_support_resistance(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: Optional[List[int]] = None,
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 5,
    tolerance_pct: float = 1.5
) -> SupportResistanceResult:
    """
    Vollständige Support/Resistance Analyse.

    Kombiniert Support- und Resistance-Detection in einem Aufruf.

    Args:
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        volumes: Tagesvolumen (optional)
        lookback: Wie weit zurückschauen
        window: Halbe Fenstergröße
        max_levels: Max Levels pro Typ
        tolerance_pct: Clustering-Toleranz

    Returns:
        Kombiniertes SupportResistanceResult
    """
    support_result = find_support_levels_enhanced(
        lows=lows,
        lookback=lookback,
        window=window,
        max_levels=max_levels,
        volumes=volumes,
        tolerance_pct=tolerance_pct
    )

    resistance_result = find_resistance_levels_enhanced(
        highs=highs,
        lookback=lookback,
        window=window,
        max_levels=max_levels,
        volumes=volumes,
        tolerance_pct=tolerance_pct
    )

    return SupportResistanceResult(
        support_levels=support_result.support_levels,
        resistance_levels=resistance_result.resistance_levels,
        nearest_support=support_result.nearest_support,
        nearest_resistance=resistance_result.nearest_resistance
    )


# =============================================================================
# UTILITY FUNCTIONS (Backward Compatibility)
# =============================================================================

def calculate_fibonacci(high: float, low: float) -> Dict[str, float]:
    """
    Berechnet Fibonacci Retracement Levels.

    Die Levels zeigen potenzielle Support/Resistance-Zonen
    basierend auf der Fibonacci-Sequenz.

    Args:
        high: Höchster Preis im Betrachtungszeitraum
        low: Niedrigster Preis im Betrachtungszeitraum

    Returns:
        Dict mit Fibonacci-Levels
    """
    diff = high - low
    return {
        '0.0%': high,
        '23.6%': high - diff * 0.236,
        '38.2%': high - diff * 0.382,
        '50.0%': high - diff * 0.5,
        '61.8%': high - diff * 0.618,
        '78.6%': high - diff * 0.786,
        '100.0%': low
    }


def find_pivot_points(
    high: float,
    low: float,
    close: float
) -> Dict[str, float]:
    """
    Berechnet klassische Pivot Points.

    Args:
        high: Tageshoch
        low: Tagestief
        close: Schlusskurs

    Returns:
        Dict mit Pivot, Support (S1-S3) und Resistance (R1-R3) Levels
    """
    pivot = (high + low + close) / 3

    return {
        'pivot': pivot,
        'r1': 2 * pivot - low,
        'r2': pivot + (high - low),
        'r3': high + 2 * (pivot - low),
        's1': 2 * pivot - high,
        's2': pivot - (high - low),
        's3': low - 2 * (high - pivot)
    }


def price_near_level(
    price: float,
    level: float,
    tolerance_pct: float = 2.0
) -> bool:
    """
    Prüft ob Preis nahe an einem Level ist.

    Args:
        price: Aktueller Preis
        level: Support/Resistance Level
        tolerance_pct: Toleranz in Prozent

    Returns:
        True wenn Preis innerhalb der Toleranz
    """
    if level == 0:
        return False
    distance_pct = abs(price - level) / level * 100
    return distance_pct <= tolerance_pct


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
    # Data structures
    'PriceLevel',
    'VolumeZone',
    'VolumeProfile',
    'LevelTest',
    'SupportResistanceResult',

    # Core algorithms
    'find_local_minima_optimized',
    'find_local_maxima_optimized',
    'cluster_levels',
    'score_levels',

    # Main API
    'find_support_levels',
    'find_resistance_levels',
    'find_support_levels_enhanced',
    'find_resistance_levels_enhanced',
    'analyze_support_resistance',

    # Volume Analysis
    'calculate_volume_profile',
    'analyze_level_tests',
    'validate_level_with_volume',
    'get_volume_at_level',
    'analyze_support_resistance_with_validation',

    # Event-Aware Analysis
    'analyze_sr_with_events',

    # Utilities
    'calculate_fibonacci',
    'find_pivot_points',
    'price_near_level',
]
