# OptionPlay - Fundamentals Data Provider
# ========================================
# Holt Analyst-Ratings, Kursziele und Earnings-Daten via yfinance
# Ersetzt die unzureichenden News-Headlines mit echten Fundamentaldaten

import logging
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Simple in-memory cache with TTL
_fundamentals_cache: Dict[str, tuple] = {}  # symbol -> (data, timestamp)
_CACHE_TTL_SECONDS = 3600  # 1 Stunde


def get_analyst_data(symbol: str) -> Dict[str, Any]:
    """
    Holt Analysten-Daten für ein Symbol via Yahoo Finance.

    Args:
        symbol: Stock-Symbol (z.B. "AAPL")

    Returns:
        Dict mit:
        - sentiment: "BULLISH", "NEUTRAL", "BEARISH"
        - buy: Anzahl Buy-Ratings
        - hold: Anzahl Hold-Ratings
        - sell: Anzahl Sell-Ratings
        - target_median: Median-Kursziel
        - target_high: Höchstes Kursziel
        - target_low: Niedrigstes Kursziel
        - current_price: Aktueller Preis
        - upside_pct: Upside zum Median-Ziel in %
    """
    symbol = symbol.upper()

    # Check cache
    cache_key = f"analyst_{symbol}"
    if cache_key in _fundamentals_cache:
        cached_data, cached_time = _fundamentals_cache[cache_key]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            logger.debug(f"Analyst cache hit for {symbol}")
            return cached_data

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        # Analysten-Empfehlungen zählen
        buy = hold = sell = 0

        # Methode 1: recommendation_summary (aggregiert)
        rec_summary = getattr(ticker, "recommendations_summary", None)
        if rec_summary is not None and not rec_summary.empty:
            # Summiere über alle Perioden
            for col in rec_summary.columns:
                col_lower = col.lower()
                total = rec_summary[col].sum()
                if "buy" in col_lower or "strong" in col_lower:
                    buy += int(total)
                elif "hold" in col_lower:
                    hold += int(total)
                elif "sell" in col_lower or "under" in col_lower:
                    sell += int(total)
        else:
            # Methode 2: Einzelne recommendations (Fallback)
            recs = ticker.recommendations
            if recs is not None and not recs.empty:
                recent = recs.tail(30)  # Letzte 30 Einträge
                for _, row in recent.iterrows():
                    grade = str(row.get("To Grade", "")).lower()
                    if any(x in grade for x in ["buy", "outperform", "overweight", "strong buy"]):
                        buy += 1
                    elif any(x in grade for x in ["hold", "neutral", "equal", "market perform"]):
                        hold += 1
                    elif any(x in grade for x in ["sell", "underperform", "underweight", "reduce"]):
                        sell += 1

        # Sentiment bestimmen
        total_ratings = buy + hold + sell
        if total_ratings > 0:
            if buy > (hold + sell):
                sentiment = "BULLISH"
            elif sell > (buy + hold):
                sentiment = "BEARISH"
            else:
                sentiment = "NEUTRAL"
        else:
            sentiment = "UNKNOWN"

        # Kursziele
        target_median = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        # Upside berechnen
        upside_pct = None
        if target_median and current_price and current_price > 0:
            upside_pct = round((target_median - current_price) / current_price * 100, 1)

        result = {
            "sentiment": sentiment,
            "buy": buy,
            "hold": hold,
            "sell": sell,
            "total_ratings": total_ratings,
            "target_median": target_median,
            "target_high": target_high,
            "target_low": target_low,
            "current_price": current_price,
            "upside_pct": upside_pct,
        }

        # Cache result
        _fundamentals_cache[cache_key] = (result, time.time())
        logger.debug(f"Fetched analyst data for {symbol}: {sentiment} ({buy}/{hold}/{sell})")

        return result

    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return _empty_analyst_data()
    except Exception as e:
        logger.warning(f"Failed to fetch analyst data for {symbol}: {e}")
        return _empty_analyst_data()


def _empty_analyst_data() -> Dict[str, Any]:
    """Leeres Analyst-Data Dict."""
    return {
        "sentiment": "UNKNOWN",
        "buy": 0,
        "hold": 0,
        "sell": 0,
        "total_ratings": 0,
        "target_median": None,
        "target_high": None,
        "target_low": None,
        "current_price": None,
        "upside_pct": None,
    }


def get_earnings_data(symbol: str) -> Dict[str, Any]:
    """
    Holt Earnings-Daten für ein Symbol.

    Args:
        symbol: Stock-Symbol (z.B. "AAPL")

    Returns:
        Dict mit:
        - last_date: Datum des letzten Earnings (YYYY-MM-DD)
        - result: "Beat", "Miss", "Meet" oder None
        - eps_actual: Tatsächlicher EPS
        - eps_estimate: Erwarteter EPS
        - surprise_pct: Überraschung in %
        - next_date: Nächster Earnings-Termin
    """
    symbol = symbol.upper()

    # Check cache
    cache_key = f"earnings_{symbol}"
    if cache_key in _fundamentals_cache:
        cached_data, cached_time = _fundamentals_cache[cache_key]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            logger.debug(f"Earnings cache hit for {symbol}")
            return cached_data

    try:
        import pandas as pd
        import yfinance as yf

        ticker = yf.Ticker(symbol)

        # Earnings History
        earnings_dates = ticker.earnings_dates
        last_date = None
        result = None
        eps_actual = None
        eps_estimate = None
        surprise_pct = None
        next_date = None

        if earnings_dates is not None and not earnings_dates.empty:
            now = pd.Timestamp.now(tz="UTC")

            # Konvertiere Index zu UTC wenn nötig
            if earnings_dates.index.tz is None:
                earnings_dates.index = earnings_dates.index.tz_localize("UTC")

            # Vergangene Earnings (letzter bekannter)
            past = earnings_dates[earnings_dates.index < now]
            if not past.empty:
                last_row = past.iloc[0]
                last_date = past.index[0].strftime("%Y-%m-%d")

                # EPS Daten extrahieren
                eps_actual = last_row.get("Reported EPS")
                eps_estimate = last_row.get("EPS Estimate")

                if eps_actual is not None and eps_estimate is not None:
                    try:
                        eps_actual = float(eps_actual)
                        eps_estimate = float(eps_estimate)

                        # Beat/Miss/Meet bestimmen
                        if eps_actual > eps_estimate * 1.01:  # >1% über Erwartung
                            result = "Beat"
                        elif eps_actual < eps_estimate * 0.99:  # >1% unter Erwartung
                            result = "Miss"
                        else:
                            result = "Meet"

                        # Surprise berechnen
                        if eps_estimate != 0:
                            surprise_pct = round(
                                (eps_actual - eps_estimate) / abs(eps_estimate) * 100, 1
                            )
                    except (TypeError, ValueError):
                        pass

            # Nächster Earnings-Termin
            future = earnings_dates[earnings_dates.index >= now]
            if not future.empty:
                next_date = future.index[-1].strftime("%Y-%m-%d")

        result_data = {
            "last_date": last_date,
            "result": result,
            "eps_actual": eps_actual,
            "eps_estimate": eps_estimate,
            "surprise_pct": surprise_pct,
            "next_date": next_date,
        }

        # Cache result
        _fundamentals_cache[cache_key] = (result_data, time.time())
        logger.debug(f"Fetched earnings data for {symbol}: {result} on {last_date}")

        return result_data

    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return _empty_earnings_data()
    except Exception as e:
        logger.warning(f"Failed to fetch earnings data for {symbol}: {e}")
        return _empty_earnings_data()


def _empty_earnings_data() -> Dict[str, Any]:
    """Leeres Earnings-Data Dict."""
    return {
        "last_date": None,
        "result": None,
        "eps_actual": None,
        "eps_estimate": None,
        "surprise_pct": None,
        "next_date": None,
    }


def get_fundamentals(symbol: str) -> Dict[str, Any]:
    """
    Kombiniert Analyst- und Earnings-Daten.

    Args:
        symbol: Stock-Symbol

    Returns:
        Kombiniertes Dict mit allen Fundamentaldaten
    """
    analyst = get_analyst_data(symbol)
    earnings = get_earnings_data(symbol)

    return {
        **analyst,
        "earnings": earnings,
    }


def get_fundamentals_for_symbols(
    symbols: List[str], max_symbols: int = 10
) -> Dict[str, Dict[str, Any]]:
    """
    Holt Fundamentaldaten für mehrere Symbole.

    Args:
        symbols: Liste von Stock-Symbolen
        max_symbols: Maximale Anzahl (für Performance)

    Returns:
        Dict: {symbol: fundamentals_dict}
    """
    result = {}
    for symbol in symbols[:max_symbols]:
        result[symbol] = get_fundamentals(symbol)
    return result


def clear_fundamentals_cache() -> None:
    """Leert den Fundamentals-Cache."""
    global _fundamentals_cache
    _fundamentals_cache = {}
    logger.info("Fundamentals cache cleared")


def generate_positive_factors(fundamentals: Dict[str, Any]) -> List[str]:
    """
    Generiert Liste von positiven Faktoren basierend auf Fundamentaldaten.

    Args:
        fundamentals: Fundamentaldaten-Dict

    Returns:
        Liste von positiven Faktoren als Strings
    """
    factors = []

    # Analyst Sentiment
    if fundamentals.get("sentiment") == "BULLISH":
        buy = fundamentals.get("buy", 0)
        total = fundamentals.get("total_ratings", 0)
        if total > 0:
            pct = round(buy / total * 100)
            factors.append(f"Starke Analysten-Unterstützung ({pct}% Buy-Ratings)")

    # Upside Potential
    upside = fundamentals.get("upside_pct")
    if upside and upside > 10:
        factors.append(f"Signifikantes Upside-Potential ({upside:.0f}% zum Kursziel)")

    # Earnings Beat
    earnings = fundamentals.get("earnings", {})
    if earnings.get("result") == "Beat":
        surprise = earnings.get("surprise_pct", 0)
        factors.append(f"Letzter Earnings Beat ({surprise:+.1f}% Überraschung)")

    # Price vs Target
    current = fundamentals.get("current_price")
    target_low = fundamentals.get("target_low")
    if current and target_low and current < target_low:
        factors.append("Preis unter niedrigstem Analysten-Kursziel")

    return factors if factors else ["Keine signifikanten positiven Faktoren identifiziert"]


def generate_negative_factors(fundamentals: Dict[str, Any]) -> List[str]:
    """
    Generiert Liste von negativen Faktoren/Risiken.

    Args:
        fundamentals: Fundamentaldaten-Dict

    Returns:
        Liste von Risikofaktoren als Strings
    """
    factors = []

    # Bearish Sentiment
    if fundamentals.get("sentiment") == "BEARISH":
        sell = fundamentals.get("sell", 0)
        total = fundamentals.get("total_ratings", 0)
        if total > 0:
            pct = round(sell / total * 100)
            factors.append(f"Negative Analysten-Stimmung ({pct}% Sell-Ratings)")

    # Downside Risk
    upside = fundamentals.get("upside_pct")
    if upside and upside < -10:
        factors.append(f"Preis über Kursziel ({abs(upside):.0f}% über Median)")

    # Earnings Miss
    earnings = fundamentals.get("earnings", {})
    if earnings.get("result") == "Miss":
        surprise = earnings.get("surprise_pct", 0)
        factors.append(f"Letzter Earnings Miss ({surprise:.1f}% unter Erwartung)")

    # No Analyst Coverage
    total = fundamentals.get("total_ratings", 0)
    if total == 0:
        factors.append("Keine Analysten-Abdeckung")

    return factors if factors else ["Keine signifikanten Risikofaktoren identifiziert"]


def generate_news_assessment_table(fundamentals: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Generiert eine Bewertungstabelle wie im Referenz-Report.

    Args:
        fundamentals: Fundamentaldaten-Dict

    Returns:
        Liste von Dicts: [{"factor": "...", "rating": "...", "comment": "..."}]
    """
    table = []

    # Earnings Bewertung
    earnings = fundamentals.get("earnings", {})
    if earnings.get("result"):
        rating = (
            "Positiv"
            if earnings["result"] == "Beat"
            else ("Negativ" if earnings["result"] == "Miss" else "Neutral")
        )
        table.append(
            {
                "factor": "Earnings",
                "rating": rating,
                "comment": f"Q-Ergebnis: {earnings['result']}"
                + (
                    f" ({earnings.get('surprise_pct', 0):+.1f}%)"
                    if earnings.get("surprise_pct")
                    else ""
                ),
            }
        )
    else:
        table.append(
            {
                "factor": "Earnings",
                "rating": "Unbekannt",
                "comment": "Keine Earnings-Daten verfügbar",
            }
        )

    # Analysten Bewertung
    sentiment = fundamentals.get("sentiment", "UNKNOWN")
    buy = fundamentals.get("buy", 0)
    hold = fundamentals.get("hold", 0)
    sell = fundamentals.get("sell", 0)

    if sentiment != "UNKNOWN":
        rating = (
            "Positiv"
            if sentiment == "BULLISH"
            else ("Negativ" if sentiment == "BEARISH" else "Neutral")
        )
        table.append(
            {
                "factor": "Analysten",
                "rating": rating,
                "comment": f"{buy} Buy / {hold} Hold / {sell} Sell",
            }
        )
    else:
        table.append(
            {"factor": "Analysten", "rating": "Unbekannt", "comment": "Keine Ratings verfügbar"}
        )

    # Kursziel Bewertung
    upside = fundamentals.get("upside_pct")
    if upside is not None:
        if upside > 15:
            rating = "Positiv"
            comment = f"{upside:+.0f}% Upside"
        elif upside < -10:
            rating = "Negativ"
            comment = f"{upside:+.0f}% (Downside)"
        else:
            rating = "Neutral"
            comment = f"{upside:+.0f}% zum Ziel"
        table.append({"factor": "Kursziel", "rating": rating, "comment": comment})

    # Gesamt-Risiko Bewertung
    negative = generate_negative_factors(fundamentals)
    risk_level = "Niedrig" if len(negative) <= 1 else ("Hoch" if len(negative) >= 3 else "Mittel")
    table.append(
        {"factor": "Risiko", "rating": risk_level, "comment": f"{len(negative)} Faktor(en)"}
    )

    return table


def generate_fundamental_conclusion(
    symbol: str, fundamentals: Dict[str, Any], for_bull_put_spread: bool = True
) -> str:
    """
    Generiert einen Fazit-Text basierend auf Fundamentaldaten.

    Args:
        symbol: Stock-Symbol
        fundamentals: Fundamentaldaten-Dict
        for_bull_put_spread: Bewertung für Bull-Put-Spread Strategie

    Returns:
        Fazit-Text als String
    """
    sentiment = fundamentals.get("sentiment", "UNKNOWN")
    earnings = fundamentals.get("earnings", {})
    upside = fundamentals.get("upside_pct")

    parts = []

    # Sentiment Einordnung
    if sentiment == "BULLISH":
        parts.append(f"{symbol} wird von Analysten überwiegend positiv bewertet")
    elif sentiment == "BEARISH":
        parts.append(f"{symbol} wird von Analysten kritisch gesehen")
    else:
        parts.append(f"Die Analysten-Meinung zu {symbol} ist gemischt")

    # Earnings Einordnung
    if earnings.get("result") == "Beat":
        parts.append("Der letzte Earnings-Report übertraf die Erwartungen")
    elif earnings.get("result") == "Miss":
        parts.append("Der letzte Earnings-Report verfehlte die Erwartungen")

    # Kursziel Einordnung
    if upside and upside > 10:
        parts.append(f"mit einem Upside-Potential von {upside:.0f}% zum Median-Kursziel")

    # Bull-Put-Spread Bewertung
    if for_bull_put_spread:
        if sentiment == "BULLISH" and earnings.get("result") in ["Beat", "Meet"]:
            parts.append("Die Fundamentaldaten unterstützen einen Bull-Put-Spread")
        elif sentiment == "BEARISH":
            parts.append("Vorsicht bei Bull-Put-Spread aufgrund negativer Stimmung geboten")
        else:
            parts.append("Die Fundamentaldaten sind für einen Bull-Put-Spread akzeptabel")

    return ". ".join(parts) + "."
