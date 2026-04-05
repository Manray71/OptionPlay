# OptionPlay - Data Provider Orchestrator
# ========================================
# Intelligente Multi-Provider-Strategie mit Rate Limiting
#
# Provider-Hierarchie:
# 1. IBKR/TWS - Präzise Live-Daten (rate-limitiert, nur für finale Validierung)
# 2. Marketdata.app - Bulk-Daten, historische Daten, Scans
# 3. Yahoo Finance - Kostenloser Fallback für VIX, Earnings
#
# Strategie:
# - Scans und historische Daten: Marketdata.app
# - Finale Trade-Validierung: IBKR (wenn verfügbar)
# - VIX: Yahoo Finance (zuverlässiger als Marketdata.app)
# - Earnings: Multi-Source mit Cache

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProviderType(Enum):
    """Verfügbare Data Provider"""

    MARKETDATA = "marketdata"
    TRADIER = "tradier"
    IBKR = "ibkr"
    YAHOO = "yahoo"


class DataType(Enum):
    """Datentypen für Provider-Routing"""

    QUOTE = "quote"
    HISTORICAL = "historical"
    OPTIONS_CHAIN = "options_chain"
    VIX = "vix"
    EARNINGS = "earnings"
    SCAN = "scan"
    NEWS = "news"
    IV_RANK = "iv_rank"
    MAX_PAIN = "max_pain"
    STRIKE_RECOMMENDATION = "strike_recommendation"


@dataclass
class ProviderConfig:
    """Konfiguration für einen Provider"""

    name: str
    enabled: bool = True
    priority: int = 1  # Niedriger = höhere Priorität
    rate_limit_per_minute: int = 100
    daily_limit: Optional[int] = None
    supports: List[DataType] = None

    def __post_init__(self) -> None:
        if self.supports is None:
            self.supports = []


@dataclass
class ProviderStats:
    """Statistiken für einen Provider"""

    requests_today: int = 0
    requests_total: int = 0
    errors_today: int = 0
    last_error: Optional[str] = None
    last_request: Optional[datetime] = None
    avg_latency_ms: float = 0.0


class ProviderOrchestrator:
    """
    Orchestriert mehrere Data Provider für optimale Performance.

    Routing-Logik:
    - Bulk-Scans: Marketdata.app (schnell, hohe Rate Limits)
    - Live-Quotes für Trading: IBKR (wenn verbunden)
    - VIX: Yahoo Finance (zuverlässig)
    - Earnings: Cache → Yahoo → Marketdata

    Verwendung:
        orchestrator = ProviderOrchestrator()

        # Automatisches Routing
        quote = await orchestrator.get_quote("AAPL")

        # Expliziter Provider
        quote = await orchestrator.get_quote("AAPL", provider=ProviderType.IBKR)
    """

    # Default Provider-Konfiguration
    DEFAULT_PROVIDERS = {
        ProviderType.MARKETDATA: ProviderConfig(
            name="Marketdata.app",
            enabled=True,
            priority=3,  # Niedriger als Tradier
            rate_limit_per_minute=100,
            supports=[
                DataType.QUOTE,
                DataType.HISTORICAL,
                DataType.OPTIONS_CHAIN,
                DataType.EARNINGS,
                DataType.SCAN,
            ],
        ),
        ProviderType.TRADIER: ProviderConfig(
            name="Tradier",
            enabled=False,  # Wird aktiviert wenn API Key vorhanden
            priority=2,  # Höher als Marketdata, niedriger als IBKR
            rate_limit_per_minute=120,
            supports=[
                DataType.QUOTE,
                DataType.HISTORICAL,
                DataType.OPTIONS_CHAIN,
                DataType.SCAN,
                DataType.IV_RANK,
            ],
        ),
        ProviderType.IBKR: ProviderConfig(
            name="IBKR/TWS",
            enabled=False,  # Muss explizit aktiviert werden
            priority=1,  # Höchste Priorität für Live-Daten
            rate_limit_per_minute=30,  # Konservativ für TWS
            supports=[
                DataType.QUOTE,
                DataType.HISTORICAL,
                DataType.OPTIONS_CHAIN,
                DataType.NEWS,  # IBKR liefert News!
                DataType.IV_RANK,
                DataType.MAX_PAIN,
                DataType.STRIKE_RECOMMENDATION,
            ],
        ),
        ProviderType.YAHOO: ProviderConfig(
            name="Yahoo Finance",
            enabled=True,
            priority=4,  # Niedrigste Priorität
            rate_limit_per_minute=120,
            supports=[
                DataType.VIX,
                DataType.EARNINGS,
                DataType.HISTORICAL,
            ],
        ),
    }

    # Routing-Präferenzen pro Datentyp
    # Reihenfolge: IBKR (live) > Tradier (API) > Marketdata > Yahoo (fallback)
    ROUTING_PREFERENCES = {
        DataType.QUOTE: [ProviderType.IBKR, ProviderType.TRADIER, ProviderType.MARKETDATA],
        DataType.HISTORICAL: [ProviderType.TRADIER, ProviderType.MARKETDATA, ProviderType.IBKR],
        DataType.OPTIONS_CHAIN: [ProviderType.IBKR, ProviderType.TRADIER, ProviderType.MARKETDATA],
        DataType.VIX: [ProviderType.IBKR, ProviderType.YAHOO, ProviderType.MARKETDATA],
        DataType.EARNINGS: [
            ProviderType.YAHOO,
            ProviderType.MARKETDATA,
        ],  # Tradier hat keine Earnings
        DataType.SCAN: [ProviderType.TRADIER, ProviderType.MARKETDATA],  # Tradier für Bulk-Scans
        DataType.NEWS: [ProviderType.IBKR],  # NUR IBKR liefert News
        DataType.IV_RANK: [ProviderType.IBKR, ProviderType.TRADIER, ProviderType.MARKETDATA],
        DataType.MAX_PAIN: [ProviderType.IBKR],  # Nur IBKR hat präzise OI-Daten
        DataType.STRIKE_RECOMMENDATION: [ProviderType.IBKR],  # VIX-integriert
    }

    def __init__(self) -> None:
        self.providers = {
            k: ProviderConfig(
                name=v.name,
                enabled=v.enabled,
                priority=v.priority,
                rate_limit_per_minute=v.rate_limit_per_minute,
                daily_limit=v.daily_limit,
                supports=list(v.supports) if v.supports else [],
            )
            for k, v in self.DEFAULT_PROVIDERS.items()
        }
        self.stats: Dict[ProviderType, ProviderStats] = {p: ProviderStats() for p in ProviderType}
        self._ibkr_connected = False
        self._tradier_connected = False
        self._last_daily_reset = datetime.now().date()

    def enable_tradier(self, enabled: bool = True) -> None:
        """Legacy alias — routes to enable_ibkr."""
        self.enable_ibkr(enabled)

    def enable_ibkr(self, connected: bool = True) -> None:
        """Aktiviert/Deaktiviert IBKR Provider."""
        self.providers[ProviderType.IBKR].enabled = connected
        self._ibkr_connected = connected
        logger.info(f"IBKR Provider: {'aktiviert' if connected else 'deaktiviert'}")

    def get_best_provider(
        self, data_type: DataType, prefer_accuracy: bool = False
    ) -> Optional[ProviderType]:
        """
        Wählt den besten Provider für einen Datentyp.

        Args:
            data_type: Gewünschter Datentyp
            prefer_accuracy: True für höchste Genauigkeit (IBKR bevorzugt)

        Returns:
            Bester verfügbarer Provider oder None
        """
        preferences = self.ROUTING_PREFERENCES.get(data_type, [])

        for provider_type in preferences:
            config = self.providers.get(provider_type)

            if not config or not config.enabled:
                continue

            if data_type not in config.supports:
                continue

            # IBKR nur wenn verbunden und für Accuracy-Anfragen
            if provider_type == ProviderType.IBKR:
                if not self._ibkr_connected:
                    continue
                if not prefer_accuracy and data_type == DataType.SCAN:
                    continue  # Scans nie über IBKR

            # Tradier nur wenn verbunden/aktiviert
            if provider_type == ProviderType.TRADIER:
                if not self._tradier_connected:
                    continue

            # Daily Limit prüfen
            stats = self.stats[provider_type]
            if config.daily_limit and stats.requests_today >= config.daily_limit:
                logger.warning(f"{config.name}: Daily Limit erreicht")
                continue

            return provider_type

        return None

    def get_fallback_providers(
        self, data_type: DataType, exclude: Optional[ProviderType] = None
    ) -> List[ProviderType]:
        """Gibt Fallback-Provider für einen Datentyp zurück."""
        preferences = self.ROUTING_PREFERENCES.get(data_type, [])

        fallbacks = []
        for provider_type in preferences:
            if provider_type == exclude:
                continue

            config = self.providers.get(provider_type)
            if config and config.enabled and data_type in config.supports:
                fallbacks.append(provider_type)

        return fallbacks

    def record_request(
        self,
        provider: ProviderType,
        success: bool = True,
        latency_ms: float = 0,
        error: Optional[str] = None,
    ) -> None:
        """Zeichnet eine Anfrage auf."""
        # Daily Reset
        today = datetime.now().date()
        if today > self._last_daily_reset:
            for stats in self.stats.values():
                stats.requests_today = 0
                stats.errors_today = 0
            self._last_daily_reset = today

        stats = self.stats[provider]
        stats.requests_today += 1
        stats.requests_total += 1
        stats.last_request = datetime.now()

        if not success:
            stats.errors_today += 1
            stats.last_error = error

        # Moving Average für Latenz
        if latency_ms > 0:
            if stats.avg_latency_ms == 0:
                stats.avg_latency_ms = latency_ms
            else:
                stats.avg_latency_ms = stats.avg_latency_ms * 0.9 + latency_ms * 0.1

    def get_provider_status(self) -> Dict[str, Any]:
        """Gibt Status aller Provider zurück."""
        status = {}

        for provider_type, config in self.providers.items():
            stats = self.stats[provider_type]

            status[config.name] = {
                "enabled": config.enabled,
                "priority": config.priority,
                "rate_limit": config.rate_limit_per_minute,
                "requests_today": stats.requests_today,
                "errors_today": stats.errors_today,
                "avg_latency_ms": round(stats.avg_latency_ms, 1),
                "last_request": stats.last_request.isoformat() if stats.last_request else None,
                "supports": [dt.value for dt in config.supports],
            }

            if provider_type == ProviderType.IBKR:
                status[config.name]["connected"] = self._ibkr_connected
            if provider_type == ProviderType.TRADIER:
                status[config.name]["connected"] = self._tradier_connected

        return status

    def should_use_ibkr_for_validation(self, symbol: str) -> bool:
        """
        Entscheidet ob IBKR für finale Trade-Validierung verwendet werden soll.

        IBKR wird verwendet für:
        - Finale Preis-Validierung vor Trade-Eintrag
        - Options-Chain mit präzisen Greeks
        - Live-Daten während Market Hours
        """
        if not self._ibkr_connected:
            return False

        # Rate Limit prüfen (max 30/min für IBKR)
        stats = self.stats[ProviderType.IBKR]
        if stats.requests_today > 500:  # Konservatives Daily Limit
            logger.warning("IBKR Daily Limit fast erreicht, verwende Marketdata.app")
            return False

        return True

    def get_scan_provider(self) -> ProviderType:
        """Gibt Provider für Bulk-Scans zurück (immer Marketdata.app)."""
        return ProviderType.MARKETDATA

    def get_vix_provider(self) -> ProviderType:
        """Gibt Provider für VIX zurück (bevorzugt Yahoo)."""
        return self.get_best_provider(DataType.VIX) or ProviderType.YAHOO


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_orchestrator: Optional[ProviderOrchestrator] = None


def get_orchestrator() -> ProviderOrchestrator:
    """
    Gibt globale Orchestrator-Instanz zurück.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.
    """
    try:
        from .deprecation import warn_singleton_usage

        warn_singleton_usage("get_orchestrator", "ServiceContainer.provider_orchestrator")
    except ImportError:
        pass

    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = ProviderOrchestrator()
    return _default_orchestrator


def format_provider_status() -> str:
    """Formatiert Provider-Status als Markdown."""
    orchestrator = get_orchestrator()
    status = orchestrator.get_provider_status()

    lines = [
        "# Data Provider Status",
        "",
    ]

    for name, info in status.items():
        enabled = "✅" if info["enabled"] else "❌"
        connected = ""
        if "connected" in info:
            connected = f" ({'🟢 Connected' if info['connected'] else '🔴 Disconnected'})"

        lines.extend(
            [
                f"## {enabled} {name}{connected}",
                f"- **Requests Today:** {info['requests_today']}",
                f"- **Errors Today:** {info['errors_today']}",
                f"- **Avg Latency:** {info['avg_latency_ms']}ms",
                f"- **Rate Limit:** {info['rate_limit']}/min",
                "",
            ]
        )

    return "\n".join(lines)
