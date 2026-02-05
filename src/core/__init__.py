"""
OptionPlay Core Module
======================

Core infrastructure components for the OptionPlay system.

This module contains:
- ServiceRegistry: Registry-based DI container with dependency resolution
"""

from .service_registry import ServiceRegistry

__all__ = ["ServiceRegistry"]
