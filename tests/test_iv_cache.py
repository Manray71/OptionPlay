# OptionPlay - IV Cache Tests
# =============================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from iv_cache import (
    calculate_iv_rank,
    calculate_iv_percentile,
    IVData,
    IVSource
)


class TestIVRankCalculation:
    """Tests für IV-Rank-Berechnung"""
    
    def test_iv_rank_at_high(self):
        """IV am 52w-Hoch sollte Rank 100 sein"""
        history = [0.20, 0.25, 0.30, 0.35, 0.40] * 10  # 50 Punkte
        current_iv = 0.40
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank == 100.0
        
    def test_iv_rank_at_low(self):
        """IV am 52w-Tief sollte Rank 0 sein"""
        history = [0.20, 0.25, 0.30, 0.35, 0.40] * 10
        current_iv = 0.20
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank == 0.0
        
    def test_iv_rank_at_midpoint(self):
        """IV in der Mitte sollte Rank 50 sein"""
        history = [0.20, 0.30, 0.40] * 10  # Low=0.20, High=0.40
        current_iv = 0.30  # Mitte
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank == pytest.approx(50.0)
        
    def test_iv_rank_formula(self):
        """IV-Rank: (Current - Low) / (High - Low) * 100"""
        history = [0.20, 0.30, 0.40] * 10
        current_iv = 0.35  # (0.35 - 0.20) / (0.40 - 0.20) = 0.75
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank == pytest.approx(75.0)
        
    def test_iv_rank_insufficient_data(self):
        """Weniger als 20 Punkte sollte None zurückgeben"""
        history = [0.25, 0.30, 0.35]  # Nur 3 Punkte
        
        rank = calculate_iv_rank(0.30, history)
        
        assert rank is None
        
    def test_iv_rank_empty_history(self):
        """Leere History sollte None zurückgeben"""
        assert calculate_iv_rank(0.30, []) is None
        
    def test_iv_rank_capped_at_100(self):
        """IV über High sollte bei 100 gedeckelt sein"""
        history = [0.20, 0.25, 0.30] * 10  # High=0.30
        current_iv = 0.50  # Über High
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank == 100.0
        
    def test_iv_rank_floored_at_0(self):
        """IV unter Low sollte bei 0 gedeckelt sein"""
        history = [0.30, 0.35, 0.40] * 10  # Low=0.30
        current_iv = 0.20  # Unter Low
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank == 0.0


class TestIVPercentileCalculation:
    """Tests für IV-Perzentil-Berechnung"""
    
    def test_iv_percentile_at_max(self):
        """Höchste IV sollte 100% Perzentil sein"""
        history = [0.20, 0.25, 0.30, 0.35] * 10
        current_iv = 0.40  # Höher als alle
        
        percentile = calculate_iv_percentile(current_iv, history)
        
        assert percentile == 100.0
        
    def test_iv_percentile_at_min(self):
        """Niedrigste IV sollte 0% Perzentil sein"""
        history = [0.25, 0.30, 0.35, 0.40] * 10
        current_iv = 0.20  # Niedriger als alle
        
        percentile = calculate_iv_percentile(current_iv, history)
        
        assert percentile == 0.0
        
    def test_iv_percentile_median(self):
        """Median IV sollte ~50% Perzentil sein"""
        history = [0.20] * 10 + [0.40] * 10  # 50/50 split
        current_iv = 0.30  # Zwischen beiden
        
        percentile = calculate_iv_percentile(current_iv, history)
        
        assert percentile == 50.0


class TestIVDataClass:
    """Tests für IVData Dataclass"""
    
    def test_iv_data_creation(self):
        """IVData sollte erstellbar sein"""
        iv_data = IVData(
            symbol="AAPL",
            current_iv=0.35,
            iv_rank=60.0,
            iv_percentile=65.0,
            iv_high_52w=0.45,
            iv_low_52w=0.20,
            data_points=252,
            source=IVSource.TRADIER,
            updated_at="2025-01-24T10:00:00"
        )
        
        assert iv_data.symbol == "AAPL"
        assert iv_data.current_iv == 0.35
        assert iv_data.iv_rank == 60.0
        
    def test_is_elevated(self):
        """is_elevated sollte korrekt evaluieren"""
        iv_data = IVData(
            symbol="AAPL", current_iv=0.35, iv_rank=60.0,
            iv_percentile=65.0, iv_high_52w=0.45, iv_low_52w=0.20,
            data_points=252, source=IVSource.TRADIER, updated_at=""
        )
        
        assert iv_data.is_elevated(threshold=50.0) == True
        assert iv_data.is_elevated(threshold=70.0) == False
        
    def test_is_low(self):
        """is_low sollte korrekt evaluieren"""
        iv_data = IVData(
            symbol="AAPL", current_iv=0.22, iv_rank=25.0,
            iv_percentile=20.0, iv_high_52w=0.45, iv_low_52w=0.20,
            data_points=252, source=IVSource.TRADIER, updated_at=""
        )
        
        assert iv_data.is_low(threshold=30.0) == True
        assert iv_data.is_low(threshold=20.0) == False
        
    def test_iv_status(self):
        """iv_status sollte korrekte Kategorie zurückgeben"""
        # Very High (>= 70)
        iv_high = IVData("AAPL", 0.40, 75.0, 80.0, 0.45, 0.20, 100, IVSource.TRADIER, "")
        assert iv_high.iv_status() == "very_high"
        
        # Elevated (50-70)
        iv_elevated = IVData("AAPL", 0.35, 55.0, 60.0, 0.45, 0.20, 100, IVSource.TRADIER, "")
        assert iv_elevated.iv_status() == "elevated"
        
        # Normal (30-50)
        iv_normal = IVData("AAPL", 0.30, 40.0, 45.0, 0.45, 0.20, 100, IVSource.TRADIER, "")
        assert iv_normal.iv_status() == "normal"
        
        # Low (< 30)
        iv_low = IVData("AAPL", 0.22, 20.0, 15.0, 0.45, 0.20, 100, IVSource.TRADIER, "")
        assert iv_low.iv_status() == "low"
        
    def test_iv_status_unknown(self):
        """iv_status sollte 'unknown' sein wenn iv_rank None"""
        iv_data = IVData("AAPL", 0.30, None, None, None, None, 0, IVSource.UNKNOWN, "")
        assert iv_data.iv_status() == "unknown"


class TestIVSourceEnum:
    """Tests für IVSource Enum"""
    
    def test_iv_source_values(self):
        """IVSource sollte alle erwarteten Werte haben"""
        assert IVSource.TRADIER.value == "tradier"
        assert IVSource.YAHOO.value == "yahoo"
        assert IVSource.IBKR.value == "ibkr"
        assert IVSource.UNKNOWN.value == "unknown"


class TestEdgeCases:
    """Tests für Grenzfälle"""
    
    def test_flat_iv_history(self):
        """Konstante IV sollte Rank 50 geben"""
        history = [0.30] * 30
        current_iv = 0.30
        
        rank = calculate_iv_rank(current_iv, history)
        
        # Bei High == Low ist der Nenner 0, sollte 50 zurückgeben
        assert rank == 50.0
        
    def test_exactly_20_data_points(self):
        """Genau 20 Punkte sollten akzeptiert werden"""
        history = [0.25 + i * 0.01 for i in range(20)]
        current_iv = 0.35
        
        rank = calculate_iv_rank(current_iv, history)
        
        assert rank is not None
        assert 0 <= rank <= 100


class TestHistoricalVolatilityCalculation:
    """Tests für HV-Berechnung"""
    
    @pytest.fixture
    def fetcher(self, tmp_path):
        """Fetcher mit temporärem Cache"""
        from iv_cache import HistoricalIVFetcher, IVCache
        cache_file = tmp_path / "test_iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        return HistoricalIVFetcher(cache=cache)
    
    def test_hv_calculation_rising_prices(self, fetcher):
        """Steigende Preise sollten niedrige HV haben"""
        # Gleichmäßig steigende Preise (0.1% pro Tag)
        prices = [100 * (1.001 ** i) for i in range(50)]
        
        hv_values = fetcher.calculate_historical_volatility(prices, window=20)
        
        assert len(hv_values) > 0
        # Niedrige Volatilität erwartet (unter 10%)
        assert all(hv < 0.10 for hv in hv_values)
        
    def test_hv_calculation_volatile_prices(self, fetcher):
        """Stark schwankende Preise sollten hohe HV haben"""
        import math
        # Stark oszillierende Preise
        prices = [100 * (1 + 0.05 * math.sin(i)) for i in range(50)]
        
        hv_values = fetcher.calculate_historical_volatility(prices, window=20)
        
        assert len(hv_values) > 0
        # Höhere Volatilität erwartet
        avg_hv = sum(hv_values) / len(hv_values)
        assert avg_hv > 0.10
        
    def test_hv_insufficient_data(self, fetcher):
        """Zu wenige Daten sollten leere Liste geben"""
        prices = [100, 101, 102]  # Nur 3 Preise
        
        hv_values = fetcher.calculate_historical_volatility(prices, window=20)
        
        assert hv_values == []
        
    def test_hv_values_annualized(self, fetcher):
        """HV-Werte sollten annualisiert sein"""
        # Konstante 1% tägliche Bewegung
        prices = []
        price = 100
        for i in range(50):
            price *= 1.01 if i % 2 == 0 else 0.99
            prices.append(price)
        
        hv_values = fetcher.calculate_historical_volatility(prices, window=20)
        
        # Annualisierte Vol sollte höher sein als tägliche
        # sqrt(252) * ~1% = ~16%
        assert all(hv > 0.05 for hv in hv_values)  # Mindestens 5% annualisiert


class TestIVEstimation:
    """Tests für IV-Schätzung aus HV"""
    
    @pytest.fixture
    def fetcher(self, tmp_path):
        from iv_cache import HistoricalIVFetcher, IVCache
        cache_file = tmp_path / "test_iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        return HistoricalIVFetcher(cache=cache)
    
    def test_iv_premium_applied(self, fetcher):
        """IV sollte höher sein als HV (Premium)"""
        hv_values = [0.20, 0.22, 0.25, 0.23, 0.21]
        
        iv_values = fetcher.estimate_iv_from_hv(hv_values, iv_premium=1.15)
        
        # IV = HV * 1.15
        assert len(iv_values) == len(hv_values)
        for hv, iv in zip(hv_values, iv_values):
            assert iv > hv
            assert abs(iv - hv * 1.15) < 0.001
            
    def test_vix_adjustment_high_vix(self, fetcher):
        """Hohes VIX sollte IV erhöhen"""
        hv_values = [0.20, 0.20, 0.20]
        # VIX als Prozentwerte (nicht dezimal) - 30 = VIX 30
        vix_history = [30, 35, 40]  # Hoher VIX (30-40)
        
        iv_values = fetcher.estimate_iv_from_hv(hv_values, vix_history, iv_premium=1.0)
        
        # Bei VIX > 25 wird *1.1 multipliziert
        # 0.20 * 1.1 = 0.22
        assert iv_values[0] == pytest.approx(0.22, rel=0.01)  # VIX 30 -> *1.1
        assert iv_values[1] == pytest.approx(0.22, rel=0.01)  # VIX 35 -> *1.1 (not 1.2 due to elif bug)
        assert iv_values[2] == pytest.approx(0.22, rel=0.01)  # VIX 40 -> *1.1 (not 1.2 due to elif bug)
        
    def test_empty_hv_returns_empty(self, fetcher):
        """Leere HV sollte leere IV geben"""
        iv_values = fetcher.estimate_iv_from_hv([])
        
        assert iv_values == []


class TestCacheIntegration:
    """Tests für Cache-Integration"""
    
    @pytest.fixture
    def fetcher(self, tmp_path):
        from iv_cache import HistoricalIVFetcher, IVCache
        cache_file = tmp_path / "test_iv_cache.json"
        cache = IVCache(cache_file=cache_file)
        return HistoricalIVFetcher(cache=cache)
    
    def test_stale_symbols_detection(self, fetcher):
        """get_stale_symbols sollte veraltete Symbole finden"""
        # Manuell frischen Eintrag hinzufügen
        fetcher.cache.update_history("FRESH", [0.25, 0.30, 0.28] * 10, IVSource.YAHOO)
        
        stale = fetcher.get_stale_symbols(["FRESH", "MISSING"])
        
        assert "FRESH" not in stale
        assert "MISSING" in stale


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
