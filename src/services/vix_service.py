# OptionPlay - VIX Service
# ==========================
"""
Service für VIX-Daten und Strategie-Empfehlungen.

Verantwortlichkeiten:
- VIX abrufen (mit Caching)
- Strategie-Empfehlung basierend auf VIX
- Multi-Source Fallback (Marketdata → Yahoo)

Verwendung:
    from src.services import VIXService
    from src.services.base import create_service_context
    
    context = create_service_context()
    vix_service = VIXService(context)
    
    vix = await vix_service.get_vix()
    recommendation = await vix_service.get_strategy_recommendation()
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import datetime
from typing import Any, Optional

from .base import BaseService, ServiceContext
from ..models.result import ServiceResult
from ..vix_strategy import (
    VIXStrategySelector,
    get_strategy_for_vix,
    StrategyRecommendation,
)
from ..formatters import formatters

logger = logging.getLogger(__name__)


class VIXService(BaseService):
    """
    Service für VIX-Daten und Strategie-Empfehlungen.
    
    Features:
    - VIX mit 5-Minuten-Cache
    - Multi-Source Fallback (Marketdata.app → Yahoo Finance)
    - VIX-basierte Strategie-Auswahl
    
    Attributes:
        _vix_selector: VIX Strategy Selector
    """
    
    def __init__(self, context: ServiceContext):
        """Initialisiert den VIX Service."""
        super().__init__(context)
        self._vix_selector = VIXStrategySelector()
    
    async def get_vix(self, force_refresh: bool = False) -> ServiceResult[float]:
        """
        Holt aktuellen VIX (mit 5-Minuten-Cache).
        
        Verwendet Marketdata.app als primäre Quelle,
        Yahoo Finance als Fallback.
        
        Args:
            force_refresh: Cache ignorieren und neu abrufen
            
        Returns:
            ServiceResult mit VIX-Wert
        """
        vix_cache_seconds = self._config.settings.api_connection.vix_cache_seconds
        
        # Check Cache
        if not force_refresh and self._context._vix_cache and self._context._vix_updated:
            age = (datetime.now() - self._context._vix_updated).total_seconds()
            if age < vix_cache_seconds:
                return ServiceResult.ok(
                    data=self._context._vix_cache,
                    source="cache",
                    cached=True
                )
        
        start_time = datetime.now()
        vix = None
        source = "unknown"
        
        # 1. Try Marketdata.app
        try:
            provider = await self._get_provider()
            async with self._rate_limited():
                vix = await provider.get_vix()
            if vix:
                source = "marketdata"
        except Exception as e:
            self._logger.debug(f"Marketdata.app VIX failed: {e}")
        
        # 2. Fallback to Yahoo Finance
        if vix is None:
            try:
                vix = await asyncio.to_thread(self._fetch_vix_yahoo)
                if vix:
                    source = "yahoo"
            except Exception as e:
                self._logger.debug(f"Yahoo VIX failed: {e}")
        
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        # Update Cache
        if vix:
            self._context._vix_cache = vix
            self._context._vix_updated = datetime.now()
            self._logger.info(f"VIX updated: {vix:.2f} (source: {source})")
            return ServiceResult.ok(
                data=vix,
                source=source,
                cached=False,
                duration_ms=duration_ms
            )
        
        # Return cached value if available
        if self._context._vix_cache:
            return ServiceResult.ok(
                data=self._context._vix_cache,
                source="stale_cache",
                cached=True,
                warnings=["Using stale cached VIX value"]
            )
        
        return ServiceResult.fail(
            error="Could not fetch VIX from any source",
            duration_ms=duration_ms
        )
    
    def _fetch_vix_yahoo(self) -> Optional[float]:
        """
        Holt VIX von Yahoo Finance (synchron).
        
        Returns:
            VIX-Wert oder None
        """
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
            timeout = self._config.settings.api_connection.yahoo_timeout
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())
            
            result = data.get('chart', {}).get('result', [{}])[0]
            meta = result.get('meta', {})
            
            regular_price = meta.get('regularMarketPrice')
            if regular_price:
                return float(regular_price)
            
            # Fallback: last close from candles
            closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
            if closes:
                for c in reversed(closes):
                    if c is not None:
                        return float(c)
            
            return None
            
        except Exception as e:
            self._logger.debug(f"Yahoo VIX fetch error: {e}")
            return None
    
    async def get_vix_concurrent(self) -> ServiceResult[float]:
        """
        Holt VIX mit concurrent Fetching (schneller).
        
        Startet beide Quellen parallel und nimmt den ersten Erfolg.
        
        Returns:
            ServiceResult mit VIX-Wert
        """
        vix_cache_seconds = self._config.settings.api_connection.vix_cache_seconds
        
        # Check Cache first
        if self._context._vix_cache and self._context._vix_updated:
            age = (datetime.now() - self._context._vix_updated).total_seconds()
            if age < vix_cache_seconds:
                return ServiceResult.ok(
                    data=self._context._vix_cache,
                    source="cache",
                    cached=True
                )
        
        start_time = datetime.now()
        
        async def fetch_marketdata() -> Optional[tuple[Any, ...]]:
            try:
                provider = await self._get_provider()
                async with self._rate_limited():
                    vix = await provider.get_vix()
                if vix:
                    return (vix, "marketdata")
            except Exception as e:
                logger.debug(f"VIX fetch from marketdata failed: {e}")
            return None

        async def fetch_yahoo() -> Optional[tuple[Any, ...]]:
            try:
                vix = await asyncio.to_thread(self._fetch_vix_yahoo)
                if vix:
                    return (vix, "yahoo")
            except Exception as e:
                logger.debug(f"VIX fetch from yahoo failed: {e}")
            return None
        
        # Run both concurrently
        tasks = [
            asyncio.create_task(fetch_marketdata()),
            asyncio.create_task(fetch_yahoo()),
        ]
        
        # Wait for first successful result
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
            timeout=10.0
        )
        
        # Cancel pending tasks
        for task in pending:
            task.cancel()
        
        # Get first successful result
        for task in done:
            try:
                result = task.result()
                if result:
                    vix, source = result
                    duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                    
                    # Update cache
                    self._context._vix_cache = vix
                    self._context._vix_updated = datetime.now()
                    
                    return ServiceResult.ok(
                        data=vix,
                        source=source,
                        cached=False,
                        duration_ms=duration_ms
                    )
            except Exception as e:
                logger.debug(f"VIX task result extraction failed: {e}")

        # All failed - return cached if available
        if self._context._vix_cache:
            return ServiceResult.ok(
                data=self._context._vix_cache,
                source="stale_cache",
                cached=True,
                warnings=["Using stale cached VIX value"]
            )
        
        return ServiceResult.fail("Could not fetch VIX from any source")
    
    async def get_strategy_recommendation(self) -> ServiceResult[StrategyRecommendation]:
        """
        Holt Strategie-Empfehlung basierend auf aktuellem VIX.
        
        Returns:
            ServiceResult mit StrategyRecommendation
        """
        vix_result = await self.get_vix()
        
        if not vix_result.success:
            # Use default VIX if fetch failed
            vix = 20.0  # Assume normal conditions
            recommendation = get_strategy_for_vix(vix)
            return ServiceResult.ok(
                data=recommendation,
                warnings=["VIX fetch failed, using default (20.0)"]
            )
        
        vix = vix_result.data
        recommendation = get_strategy_for_vix(vix)
        
        return ServiceResult.ok(
            data=recommendation,
            source=vix_result.source,
            cached=vix_result.cached
        )
    
    async def get_strategy_recommendation_formatted(self) -> str:
        """
        Holt formatierte Strategie-Empfehlung.
        
        Returns:
            Markdown-formatierter String
        """
        vix_result = await self.get_vix()
        vix = vix_result.or_else(20.0)
        recommendation = get_strategy_for_vix(vix)
        return formatters.strategy.format(recommendation, vix)
    
    @property
    def current_vix(self) -> Optional[float]:
        """Gibt gecachten VIX zurück (ohne API-Call)."""
        return self._context._vix_cache
    
    @property
    def vix_updated(self) -> Optional[datetime]:
        """Gibt Zeitpunkt des letzten VIX-Updates zurück."""
        return self._context._vix_updated
