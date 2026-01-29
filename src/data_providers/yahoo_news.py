# OptionPlay - Yahoo Finance News Provider
# =========================================
# Holt aktuelle News für Symbole via yfinance

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from functools import lru_cache
import time

logger = logging.getLogger(__name__)

# Simple in-memory cache with TTL
_news_cache: Dict[str, tuple] = {}  # symbol -> (news_list, timestamp)
_CACHE_TTL_SECONDS = 1800  # 30 Minuten


def get_stock_news(symbol: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """
    Holt aktuelle News für ein Symbol via Yahoo Finance.

    Args:
        symbol: Stock-Symbol (z.B. "AAPL")
        max_items: Maximale Anzahl News-Items (default: 5)

    Returns:
        Liste mit News-Dictionaries:
        [
            {
                "title": "Headline",
                "publisher": "Reuters",
                "link": "https://...",
                "timestamp": 1706000000,
                "date": "2026-01-23"
            }
        ]
    """
    symbol = symbol.upper()

    # Check cache
    if symbol in _news_cache:
        cached_news, cached_time = _news_cache[symbol]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            logger.debug(f"News cache hit for {symbol}")
            return cached_news[:max_items]

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []

        result = []
        for item in raw_news[:max_items]:
            # New yfinance format: news items have 'content' nested dict
            content = item.get("content", {}) if isinstance(item, dict) else {}

            # Extract from new format
            title = content.get("title", "") if content else item.get("title", "")

            # Publisher: check content.provider.displayName first
            publisher = "Unknown"
            if content:
                provider = content.get("provider", {})
                if provider:
                    publisher = provider.get("displayName", "Unknown")
            else:
                publisher = item.get("publisher", "Unknown")

            # Link: check content.canonicalUrl.url or content.clickThroughUrl.url
            link = ""
            if content:
                canonical = content.get("canonicalUrl", {})
                if canonical:
                    link = canonical.get("url", "")
                if not link:
                    click_through = content.get("clickThroughUrl", {})
                    if click_through:
                        link = click_through.get("url", "")
            else:
                link = item.get("link", "")

            # Date: check content.pubDate (ISO format) or providerPublishTime (timestamp)
            date_str = ""
            if content:
                pub_date = content.get("pubDate", "")
                if pub_date:
                    try:
                        # ISO format: 2026-01-26T17:17:00Z
                        dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                        date_str = dt.strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        date_str = pub_date[:10] if len(pub_date) >= 10 else ""

            # Fallback to old format timestamp
            if not date_str:
                timestamp = item.get("providerPublishTime", 0)
                if timestamp:
                    try:
                        dt = datetime.fromtimestamp(timestamp)
                        date_str = dt.strftime("%Y-%m-%d")
                    except (ValueError, OSError):
                        pass

            result.append({
                "title": title,
                "publisher": publisher,
                "link": link,
                "timestamp": 0,  # Not available in new format
                "date": date_str,
            })

        # Cache result
        _news_cache[symbol] = (result, time.time())
        logger.debug(f"Fetched {len(result)} news items for {symbol}")

        return result

    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return []
    except Exception as e:
        logger.warning(f"Failed to fetch news for {symbol}: {e}")
        return []


def clear_news_cache():
    """Leert den News-Cache."""
    global _news_cache
    _news_cache = {}
    logger.info("News cache cleared")


def get_news_for_symbols(symbols: List[str], max_items_per_symbol: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    """
    Holt News für mehrere Symbole.

    Args:
        symbols: Liste von Stock-Symbolen
        max_items_per_symbol: Max News pro Symbol

    Returns:
        Dict: {symbol: [news_items]}
    """
    result = {}
    for symbol in symbols:
        result[symbol] = get_stock_news(symbol, max_items_per_symbol)
    return result
