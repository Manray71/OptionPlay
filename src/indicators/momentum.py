# OptionPlay - Momentum Indicators
# ==================================
# RSI, MACD, Stochastic

from typing import List, Optional, Tuple

import numpy as np

try:
    from ..models.indicators import MACDResult, RSIDivergenceResult, StochasticResult
except ImportError:
    from models.indicators import MACDResult, RSIDivergenceResult, StochasticResult


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """
    Berechnet RSI (Relative Strength Index) mit Wilder's Smoothing.

    Args:
        prices: Schlusskurse (älteste zuerst)
        period: RSI-Periode (default: 14)

    Returns:
        RSI-Wert zwischen 0 und 100
    """
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(
    prices: List[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> Optional[MACDResult]:
    """
    Berechnet MACD (Moving Average Convergence Divergence).

    Args:
        prices: Schlusskurse
        fast_period: Schnelle EMA-Periode
        slow_period: Langsame EMA-Periode
        signal_period: Signal-Linie Periode

    Returns:
        MACDResult oder None bei unzureichenden Daten
    """
    min_required = slow_period + signal_period
    if len(prices) < min_required:
        return None

    def ema(data: List[float], period: int) -> List[float]:
        multiplier = 2 / (period + 1)
        ema_values = [np.mean(data[:period])]
        for price in data[period:]:
            ema_values.append((price * multiplier) + (ema_values[-1] * (1 - multiplier)))
        return ema_values

    ema_fast = ema(prices, fast_period)
    ema_slow = ema(prices, slow_period)

    offset = slow_period - fast_period
    macd_line = []
    for i in range(len(ema_slow)):
        fast_idx = i + offset
        if fast_idx < len(ema_fast):
            macd_line.append(ema_fast[fast_idx] - ema_slow[i])

    if len(macd_line) < signal_period:
        return None

    signal_line = ema(macd_line, signal_period)

    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    histogram = current_macd - current_signal

    crossover = None
    if len(signal_line) >= 2:
        prev_diff = macd_line[-2] - signal_line[-2]
        curr_diff = current_macd - current_signal

        if prev_diff < 0 and curr_diff > 0:
            crossover = "bullish"
        elif prev_diff > 0 and curr_diff < 0:
            crossover = "bearish"

    return MACDResult(
        macd_line=current_macd, signal_line=current_signal, histogram=histogram, crossover=crossover
    )


def calculate_rsi_series(prices: List[float], period: int = 14) -> List[float]:
    """
    Berechnet RSI-Serie für alle Datenpunkte.

    Args:
        prices: Schlusskurse (älteste zuerst)
        period: RSI-Periode (default: 14)

    Returns:
        Liste mit RSI-Werten (erste `period` Werte sind 50.0 als Placeholder)
    """
    if len(prices) < period + 1:
        return [50.0] * len(prices)

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    rsi_values = [50.0] * period  # Placeholder für initiale Werte

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


def find_swing_lows(
    values: List[float], window: int = 5, lookback: int = 50
) -> List[Tuple[int, float]]:
    """
    Findet Swing-Tiefs in einer Wertereihe.

    Ein Swing-Tief ist ein lokales Minimum, das niedriger ist als
    die `window` Werte davor und danach.

    Args:
        values: Wertereihe (Preise oder RSI)
        window: Anzahl Bars links/rechts für Bestätigung
        lookback: Nur die letzten N Bars betrachten

    Returns:
        Liste von (Index, Wert) Tupeln für gefundene Swing-Tiefs
    """
    swing_lows = []
    start_idx = max(0, len(values) - lookback)

    for i in range(start_idx + window, len(values) - window):
        is_low = True
        current = values[i]

        # Prüfe ob niedriger als alle Werte im Fenster
        for j in range(i - window, i + window + 1):
            if j != i and values[j] < current:
                is_low = False
                break

        if is_low:
            swing_lows.append((i, current))

    return swing_lows


def find_swing_highs(
    values: List[float], window: int = 5, lookback: int = 50
) -> List[Tuple[int, float]]:
    """
    Findet Swing-Hochs in einer Wertereihe.

    Ein Swing-Hoch ist ein lokales Maximum, das höher ist als
    die `window` Werte davor und danach.

    Args:
        values: Wertereihe (Preise oder RSI)
        window: Anzahl Bars links/rechts für Bestätigung
        lookback: Nur die letzten N Bars betrachten

    Returns:
        Liste von (Index, Wert) Tupeln für gefundene Swing-Hochs
    """
    swing_highs = []
    start_idx = max(0, len(values) - lookback)

    for i in range(start_idx + window, len(values) - window):
        is_high = True
        current = values[i]

        # Prüfe ob höher als alle Werte im Fenster
        for j in range(i - window, i + window + 1):
            if j != i and values[j] > current:
                is_high = False
                break

        if is_high:
            swing_highs.append((i, current))

    return swing_highs


def calculate_rsi_divergence(
    prices: List[float],
    lows: List[float],
    highs: List[float],
    rsi_period: int = 14,
    lookback: int = 50,
    swing_window: int = 5,
    min_divergence_bars: int = 5,
    max_divergence_bars: int = 30,
) -> Optional[RSIDivergenceResult]:
    """
    Erkennt RSI-Divergenzen.

    Bullische Divergenz:
        - Kurs macht tieferes Tief (lower low)
        - RSI macht höheres Tief (higher low)
        - Signal: Verkaufsdruck lässt nach, Bodenbildung wahrscheinlich

    Bärische Divergenz:
        - Kurs macht höheres Hoch (higher high)
        - RSI macht tieferes Hoch (lower high)
        - Signal: Kaufdruck lässt nach, Top-Bildung wahrscheinlich

    Args:
        prices: Schlusskurse (älteste zuerst)
        lows: Tagestiefs
        highs: Tageshochs
        rsi_period: RSI-Periode (default: 14)
        lookback: Lookback-Periode für Swing-Erkennung
        swing_window: Fenster für Swing-Point-Bestätigung
        min_divergence_bars: Minimale Bars zwischen Pivots
        max_divergence_bars: Maximale Bars zwischen Pivots

    Returns:
        RSIDivergenceResult oder None wenn keine Divergenz gefunden
    """
    min_required = rsi_period + lookback + swing_window
    if len(prices) < min_required:
        return None

    # RSI-Serie berechnen
    rsi_values = calculate_rsi_series(prices, rsi_period)

    # === BULLISCHE DIVERGENZ (für Bounce/Pullback relevant) ===
    # Suche Swing-Tiefs im Preis und RSI
    price_swing_lows = find_swing_lows(lows, swing_window, lookback)
    rsi_swing_lows = find_swing_lows(rsi_values, swing_window, lookback)

    bullish_divergence = _find_bullish_divergence(
        price_swing_lows,
        rsi_swing_lows,
        rsi_values,
        lows,
        min_divergence_bars,
        max_divergence_bars,
        len(prices),
    )

    if bullish_divergence:
        return bullish_divergence

    # === BÄRISCHE DIVERGENZ (für Warnsignale) ===
    price_swing_highs = find_swing_highs(highs, swing_window, lookback)
    rsi_swing_highs = find_swing_highs(rsi_values, swing_window, lookback)

    bearish_divergence = _find_bearish_divergence(
        price_swing_highs,
        rsi_swing_highs,
        rsi_values,
        highs,
        min_divergence_bars,
        max_divergence_bars,
        len(prices),
    )

    if bearish_divergence:
        return bearish_divergence

    return None


def _find_bullish_divergence(
    price_lows: List[Tuple[int, float]],
    rsi_lows: List[Tuple[int, float]],
    rsi_values: List[float],
    prices: List[float],
    min_bars: int,
    max_bars: int,
    data_len: int,
) -> Optional[RSIDivergenceResult]:
    """
    Findet bullische Divergenz (Preis lower low, RSI higher low).

    Sucht vom aktuellsten Swing-Tief rückwärts nach einer Divergenz.
    """
    if len(price_lows) < 2:
        return None

    # Vom aktuellsten Swing-Tief rückwärts suchen
    for i in range(len(price_lows) - 1, 0, -1):
        recent_idx, recent_price = price_lows[i]

        # Nur betrachten wenn nahe am aktuellen Preis (letzte 10 Bars)
        if data_len - recent_idx > 10:
            continue

        # Suche früheres Swing-Tief
        for j in range(i - 1, -1, -1):
            earlier_idx, earlier_price = price_lows[j]

            bars_between = recent_idx - earlier_idx
            if bars_between < min_bars or bars_between > max_bars:
                continue

            # Preis macht lower low?
            if recent_price >= earlier_price:
                continue

            # RSI an diesen Punkten holen
            rsi_at_earlier = rsi_values[earlier_idx]
            rsi_at_recent = rsi_values[recent_idx]

            # RSI macht higher low? (Bullische Divergenz)
            if rsi_at_recent > rsi_at_earlier:
                # Stärke berechnen
                price_change = (earlier_price - recent_price) / earlier_price  # % lower
                rsi_change = (rsi_at_recent - rsi_at_earlier) / 100  # Normalisiert

                # Stärke ist Kombination aus Preis-Abweichung und RSI-Abweichung
                strength = min(1.0, (price_change + rsi_change) * 2)

                # Bonus wenn RSI im überverkauften Bereich
                if rsi_at_recent < 30:
                    strength = min(1.0, strength * 1.3)

                return RSIDivergenceResult(
                    divergence_type="bullish",
                    price_pivot_1=earlier_price,
                    price_pivot_2=recent_price,
                    rsi_pivot_1=rsi_at_earlier,
                    rsi_pivot_2=rsi_at_recent,
                    strength=strength,
                    formation_days=bars_between,
                    pivot_1_idx=earlier_idx,
                    pivot_2_idx=recent_idx,
                )

    return None


def _find_bearish_divergence(
    price_highs: List[Tuple[int, float]],
    rsi_highs: List[Tuple[int, float]],
    rsi_values: List[float],
    prices: List[float],
    min_bars: int,
    max_bars: int,
    data_len: int,
) -> Optional[RSIDivergenceResult]:
    """
    Findet bärische Divergenz (Preis higher high, RSI lower high).

    Sucht vom aktuellsten Swing-Hoch rückwärts nach einer Divergenz.
    """
    if len(price_highs) < 2:
        return None

    # Vom aktuellsten Swing-Hoch rückwärts suchen
    for i in range(len(price_highs) - 1, 0, -1):
        recent_idx, recent_price = price_highs[i]

        # Nur betrachten wenn nahe am aktuellen Preis (letzte 10 Bars)
        if data_len - recent_idx > 10:
            continue

        # Suche früheres Swing-Hoch
        for j in range(i - 1, -1, -1):
            earlier_idx, earlier_price = price_highs[j]

            bars_between = recent_idx - earlier_idx
            if bars_between < min_bars or bars_between > max_bars:
                continue

            # Preis macht higher high?
            if recent_price <= earlier_price:
                continue

            # RSI an diesen Punkten holen
            rsi_at_earlier = rsi_values[earlier_idx]
            rsi_at_recent = rsi_values[recent_idx]

            # RSI macht lower high? (Bärische Divergenz)
            if rsi_at_recent < rsi_at_earlier:
                # Stärke berechnen
                price_change = (recent_price - earlier_price) / earlier_price  # % higher
                rsi_change = (rsi_at_earlier - rsi_at_recent) / 100  # Normalisiert

                # Stärke ist Kombination aus Preis-Abweichung und RSI-Abweichung
                strength = min(1.0, (price_change + rsi_change) * 2)

                # Bonus wenn RSI im überkauften Bereich
                if rsi_at_recent > 70:
                    strength = min(1.0, strength * 1.3)

                return RSIDivergenceResult(
                    divergence_type="bearish",
                    price_pivot_1=earlier_price,
                    price_pivot_2=recent_price,
                    rsi_pivot_1=rsi_at_earlier,
                    rsi_pivot_2=rsi_at_recent,
                    strength=strength,
                    formation_days=bars_between,
                    pivot_1_idx=earlier_idx,
                    pivot_2_idx=recent_idx,
                )

    return None


def calculate_obv_series(
    closes: List[float],
    volumes: List[int],
) -> List[float]:
    """Berechnet die OBV-Zeitreihe (On-Balance Volume).

    OBV kumuliert Volumen: hoehere Schlusskurse addieren Volumen,
    niedrigere subtrahieren es. Dient als Volume-Flow-Indikator.

    Args:
        closes: Schlusskurse (aelteste zuerst)
        volumes: Volumen pro Bar (gleiche Laenge wie closes)

    Returns:
        OBV-Werte, gleiche Laenge wie closes.
        Erster Wert ist 0.0 (Konvention).
        Bei unzureichenden Daten (len < 2 oder Laengen ungleich): []
    """
    if len(closes) < 2 or len(closes) != len(volumes):
        return []

    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def calculate_stochastic(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    k_period: int = 14,
    d_period: int = 3,
    smooth: int = 3,
    oversold: float = 20,
    overbought: float = 80,
) -> Optional[StochasticResult]:
    """
    Berechnet Stochastik-Oszillator.

    Args:
        highs: Tageshochs
        lows: Tagestiefs
        closes: Schlusskurse
        k_period: %K Periode
        d_period: %D Periode
        smooth: Glättung für %K
        oversold: Oversold-Schwelle
        overbought: Overbought-Schwelle

    Returns:
        StochasticResult oder None
    """
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None

    min_required = k_period + d_period + smooth
    if len(closes) < min_required:
        return None

    raw_k = []
    for i in range(k_period - 1, len(closes)):
        period_high = max(highs[i - k_period + 1 : i + 1])
        period_low = min(lows[i - k_period + 1 : i + 1])

        if period_high == period_low:
            raw_k.append(50.0)
        else:
            k = 100 * (closes[i] - period_low) / (period_high - period_low)
            raw_k.append(k)

    smooth_k = []
    for i in range(smooth - 1, len(raw_k)):
        smooth_k.append(np.mean(raw_k[i - smooth + 1 : i + 1]))

    d_values = []
    for i in range(d_period - 1, len(smooth_k)):
        d_values.append(np.mean(smooth_k[i - d_period + 1 : i + 1]))

    if not smooth_k or not d_values:
        return None

    current_k = smooth_k[-1]
    current_d = d_values[-1]

    crossover = None
    if len(smooth_k) >= 2 and len(d_values) >= 2:
        prev_diff = smooth_k[-2] - d_values[-2]
        curr_diff = smooth_k[-1] - d_values[-1]

        if prev_diff < 0 and curr_diff > 0:
            crossover = "bullish"
        elif prev_diff > 0 and curr_diff < 0:
            crossover = "bearish"

    if current_k < oversold:
        zone = "oversold"
    elif current_k > overbought:
        zone = "overbought"
    else:
        zone = "neutral"

    return StochasticResult(k=current_k, d=current_d, crossover=crossover, zone=zone)
