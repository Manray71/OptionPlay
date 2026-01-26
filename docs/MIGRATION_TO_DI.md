# Migration to Dependency Injection Architecture

This document describes how to migrate from the legacy singleton-based architecture to the new Dependency Injection (DI) pattern.

## Overview

The OptionPlay codebase has been refactored to use:
1. **ServiceContainer** - Centralized dependency management
2. **ServerState** - Unified state management
3. **Service Layer** - Focused service classes (QuoteService, OptionsService, etc.)
4. **CacheManager** - Coordinated caching with cascading invalidation

## Deprecation Timeline

- **v3.5.0**: Deprecation warnings added to singleton getters
- **v4.0.0**: Singleton getters will be removed

## Migration Steps

### 1. Replace Singleton Getters with Container

**Before (deprecated):**
```python
from src.config import get_config
from src.cache import get_historical_cache

config = get_config()
cache = get_historical_cache()
```

**After:**
```python
from src.container import ServiceContainer

container = ServiceContainer.create_default()
config = container.config
cache = container.historical_cache
```

### 2. Use ServerCore for Coordinated Services

**Before:**
```python
from src.mcp_server import OptionPlayServer

server = OptionPlayServer()
vix = await server.get_vix()
quote = await server.get_quote("AAPL")
```

**After:**
```python
from src.services import ServerCore

async with ServerCore.create_default() as core:
    vix = await core.get_vix()
    quote = await core.get_quote("AAPL")
```

### 3. Use ServerState for State Management

**Before:**
```python
# Scattered state in OptionPlayServer
self._connected = False
self._current_vix = None
self._vix_updated = None
self._quote_cache = {}
self._quote_cache_hits = 0
```

**After:**
```python
from src.state import ServerState

state = ServerState()

# Connection lifecycle
state.connection.mark_connecting()
state.connection.mark_connected()

# VIX state
state.vix.update(18.5)
if state.vix.is_stale:
    # refresh VIX

# Cache metrics
state.quote_cache.record_hit()
print(f"Hit rate: {state.quote_cache.hit_rate_pct}%")
```

### 4. Use CacheManager for Coordinated Caching

**Before:**
```python
# Multiple uncoordinated caches
from src.cache import get_historical_cache, get_earnings_cache

hist_cache = get_historical_cache()
earn_cache = get_earnings_cache()
# Manual invalidation needed
```

**After:**
```python
from src.cache.cache_manager import CacheManager, get_cache_manager

# Get singleton or create new manager
manager = get_cache_manager()  # Singleton
# OR
manager = CacheManager()  # New instance

# Access pre-configured caches
quotes_cache = manager.get_cache("quotes")
earnings_cache = manager.get_cache("earnings")

# Get/Set values directly
manager.set("quotes", "AAPL", {"price": 150.0})
price = manager.get("quotes", "AAPL")

# Cascading invalidation (using default dependencies)
# earnings -> scans dependency is pre-configured
manager.invalidate("earnings", cascade=True)  # Also clears scans cache
```

CacheManager comes with pre-configured caches and dependencies:
- **Caches**: `historical`, `quotes`, `scans`, `earnings`, `iv`, `options`
- **Dependencies**: `earnings` → `scans`, `iv` → `scans`, `historical` → `quotes, scans`

## Testing with New Architecture

```python
from src.services import ServerCore
from src.state import ServerState
from src.container import ServiceContainer
from unittest.mock import Mock, AsyncMock

# Create test container with mocks
mock_provider = Mock()
mock_provider.get_quote = AsyncMock(return_value={"last": 150.0})

container = ServiceContainer.create_for_testing(provider=mock_provider)
core = ServerCore.create_for_testing(container=container)

# Custom initial state
state = ServerState()
state.vix.update(18.5)
core = ServerCore.create_for_testing(state=state)
```

## New Module Structure

```
src/
├── state/
│   ├── __init__.py
│   └── server_state.py      # ConnectionState, VIXState, CacheMetrics, ServerState
├── services/
│   ├── __init__.py
│   ├── base.py              # BaseService, ServiceContext
│   ├── server_core.py       # ServerCore (service coordinator)
│   ├── quote_service.py     # QuoteService
│   ├── options_service.py   # OptionsService
│   ├── vix_service.py       # VIXService
│   └── scanner_service.py   # ScannerService
├── cache/
│   ├── cache_manager.py     # CacheManager, BaseCache, CachePolicy
│   └── ...
├── container.py             # ServiceContainer
└── utils/
    └── deprecation.py       # Deprecation utilities
```

## Benefits

1. **Testability**: Easy to inject mocks
2. **Clarity**: Clear dependency graph
3. **Maintainability**: Single source of truth for services
4. **Performance**: Coordinated caching prevents inconsistencies
5. **Observability**: Unified state and metrics
