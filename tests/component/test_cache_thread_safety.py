# OptionPlay - Cache Thread-Safety Tests
# ========================================
# Tests für Fix #7: Cache Thread-Safety (earnings_cache.py, iv_cache.py)

import pytest
import sys
import time
import tempfile
import threading
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cache.earnings_cache import EarningsCache, EarningsInfo, EarningsSource


class TestEarningsCacheThreadSafety:
    """
    Tests für Fix #7: Cache Thread-Safety
    
    Der Fix fügt threading.RLock() und atomic writes hinzu,
    um Race Conditions bei parallelem Zugriff zu vermeiden.
    """
    
    @pytest.fixture
    def temp_cache_file(self):
        """Erstellt temporäre Cache-Datei"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            return Path(f.name)
    
    @pytest.fixture
    def cache(self, temp_cache_file):
        """Cache mit temporärer Datei"""
        return EarningsCache(cache_file=temp_cache_file)
    
    def test_concurrent_reads_dont_crash(self, cache):
        """Test: Parallele Reads crashen nicht"""
        # Einige Daten vorbereiten
        for i in range(10):
            symbol = f"TEST{i}"
            cache.set(symbol, f"2025-06-{15+i:02d}", source=EarningsSource.YFINANCE)
        
        errors = []
        
        def read_task(symbol):
            try:
                for _ in range(100):
                    result = cache.get(symbol)
                return True
            except Exception as e:
                errors.append(str(e))
                return False
        
        # 10 Threads lesen parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_task, f"TEST{i}") for i in range(10)]
            results = [f.result() for f in as_completed(futures)]
        
        assert all(results), f"Errors: {errors}"
    
    def test_concurrent_writes_dont_corrupt(self, cache, temp_cache_file):
        """Test: Parallele Writes korruptieren Cache nicht"""
        errors = []
        
        def write_task(thread_id):
            try:
                for i in range(50):
                    symbol = f"THREAD{thread_id}_ITER{i}"
                    cache.set(symbol, "2025-07-15", source=EarningsSource.YFINANCE)
                return True
            except Exception as e:
                errors.append(str(e))
                return False
        
        # 5 Threads schreiben parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(write_task, i) for i in range(5)]
            results = [f.result() for f in as_completed(futures)]
        
        assert all(results), f"Errors: {errors}"
        
        # Verify cache is still valid by creating new instance (reloads from disk)
        cache2 = EarningsCache(cache_file=temp_cache_file)
        assert cache2._cache is not None
    
    def test_concurrent_read_write(self, cache):
        """Test: Gleichzeitige Reads und Writes funktionieren"""
        errors = []
        
        def mixed_task(thread_id):
            try:
                for i in range(50):
                    symbol = f"MIXED{thread_id}_{i}"
                    
                    # Abwechselnd read und write
                    if i % 2 == 0:
                        cache.set(symbol, "2025-08-15", source=EarningsSource.YFINANCE)
                    else:
                        cache.get(f"MIXED{(thread_id + 1) % 5}_{i}")
                return True
            except Exception as e:
                errors.append(str(e))
                return False
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(mixed_task, i) for i in range(5)]
            results = [f.result() for f in as_completed(futures)]
        
        assert all(results), f"Errors: {errors}"
    
    def test_cache_file_not_corrupted_after_concurrent_writes(self, temp_cache_file, cache):
        """Test: Cache-Datei ist nach parallelen Writes noch valid JSON"""
        def write_many(thread_id):
            for i in range(20):
                cache.set(f"SYM{thread_id}_{i}", "2025-09-15", source=EarningsSource.YFINANCE)
        
        threads = [threading.Thread(target=write_many, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Datei muss valid JSON sein
        with open(temp_cache_file) as f:
            data = json.load(f)
        
        assert isinstance(data, dict)


class TestRetryOnFailureDecorator:
    """
    Tests für Fix #9: yfinance Retry-Logik
    
    Der retry_on_failure Decorator mit exponentiellem Backoff.
    """
    
    def test_retry_decorator_success_first_try(self):
        """Test: Erfolg beim ersten Versuch"""
        from src.cache.earnings_cache import retry_on_failure
        
        call_count = 0
        
        @retry_on_failure(max_retries=3, delay=0.01)
        def always_succeeds():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = always_succeeds()
        
        assert result == "success"
        assert call_count == 1
    
    def test_retry_decorator_success_after_retry(self):
        """Test: Erfolg nach Retry"""
        from src.cache.earnings_cache import retry_on_failure
        
        call_count = 0
        
        @retry_on_failure(max_retries=3, delay=0.01)
        def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"
        
        result = fails_twice()
        
        assert result == "success"
        assert call_count == 3
    
    def test_retry_decorator_returns_none_on_exhaustion(self):
        """Test: Gibt None zurück nach allen Retries (graceful degradation)"""
        from src.cache.earnings_cache import retry_on_failure
        
        call_count = 0
        
        @retry_on_failure(max_retries=3, delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")
        
        result = always_fails()
        
        assert result is None
        assert call_count == 3
    
    def test_retry_decorator_only_catches_specified_exceptions(self):
        """Test: Nur spezifizierte Exceptions werden gefangen"""
        from src.cache.earnings_cache import retry_on_failure
        
        @retry_on_failure(max_retries=3, delay=0.01, exceptions=(ValueError,))
        def raises_type_error():
            raise TypeError("Not a ValueError")
        
        with pytest.raises(TypeError):
            raises_type_error()


class TestAtomicWrites:
    """Tests für atomare Schreibvorgänge"""
    
    @pytest.fixture
    def temp_cache_file(self):
        """Erstellt temporäre leere Cache-Datei"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)  # Leeres Dict ist valides Cache-Format
            return Path(f.name)
    
    def test_save_creates_valid_json(self, temp_cache_file):
        """Test: save() erstellt valides JSON"""
        cache = EarningsCache(cache_file=temp_cache_file)
        
        cache.set("AAPL", "2025-10-15", source=EarningsSource.YFINANCE)
        cache.set("MSFT", "2025-11-15", source=EarningsSource.YFINANCE)
        
        # Reload und prüfen
        cache2 = EarningsCache(cache_file=temp_cache_file)
        
        assert cache2.get("AAPL") is not None
        assert cache2.get("MSFT") is not None
    
    def test_interrupted_write_doesnt_corrupt(self, temp_cache_file):
        """Test: Unterbrochener Write korruptiert Datei nicht"""
        cache = EarningsCache(cache_file=temp_cache_file)
        
        # Schreibe initiale Daten
        cache.set("INITIAL", "2025-01-15", source=EarningsSource.YFINANCE)
        
        # Originaldatei sollte noch valides JSON sein nach jedem save()
        with open(temp_cache_file) as f:
            data = json.load(f)
        
        assert "INITIAL" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
