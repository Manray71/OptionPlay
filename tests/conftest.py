# OptionPlay - Test Configuration
# =================================
# Zentrale Konfiguration für alle Tests

import sys
from pathlib import Path

# Füge src zum Pfad hinzu (vor allen anderen Imports)
_src_path = Path(__file__).parent.parent / "src"
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

import pytest


@pytest.fixture
def sample_prices():
    """Sample price data for testing"""
    return [100 + i * 0.5 for i in range(250)]


@pytest.fixture
def sample_volumes():
    """Sample volume data for testing"""
    return [1000000 + i * 1000 for i in range(250)]


@pytest.fixture
def sample_highs(sample_prices):
    """Sample high prices"""
    return [p * 1.01 for p in sample_prices]


@pytest.fixture
def sample_lows(sample_prices):
    """Sample low prices"""
    return [p * 0.99 for p in sample_prices]
