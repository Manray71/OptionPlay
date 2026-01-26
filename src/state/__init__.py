# OptionPlay - State Management
# ==============================
"""
Zentralisierte State-Verwaltung für den OptionPlay Server.

Gruppiert zusammengehörigen State in Dataclasses für:
- Bessere Lesbarkeit
- Einfacheres Testing
- Klare Verantwortlichkeiten

Module:
- server_state: Gesamter Server-State
- connection_state: Connection-Lifecycle
- vix_state: VIX-bezogener State
- cache_metrics: Cache-Statistiken
"""

from .server_state import (
    ServerState,
    ConnectionState,
    VIXState,
    CacheMetrics,
    ConnectionStatus,
)

__all__ = [
    "ServerState",
    "ConnectionState",
    "VIXState",
    "CacheMetrics",
    "ConnectionStatus",
]
