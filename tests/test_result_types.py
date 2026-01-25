# OptionPlay - Result Types Tests
# =================================
"""Tests für die Result-Types."""

import pytest
from datetime import datetime
from src.models.result import Result, ServiceResult, BatchResult, ResultStatus


class TestResult:
    """Tests für das generische Result."""
    
    def test_ok_creates_success(self):
        """Result.ok erstellt erfolgreiches Result."""
        result = Result.ok("data")
        assert result.success is True
        assert result.data == "data"
        assert result.error is None
    
    def test_fail_creates_failure(self):
        """Result.fail erstellt fehlgeschlagenes Result."""
        result = Result.fail("error message")
        assert result.success is False
        assert result.data is None
        assert result.error == "error message"
    
    def test_ok_with_warnings(self):
        """Result.ok kann Warnungen enthalten."""
        result = Result.ok("data", warnings=["warning 1", "warning 2"])
        assert result.success is True
        assert len(result.warnings) == 2
    
    def test_from_exception(self):
        """Result.from_exception konvertiert Exception."""
        try:
            raise ValueError("test error")
        except Exception as e:
            result = Result.from_exception(e)
        
        assert result.success is False
        assert "ValueError" in result.error
        assert "test error" in result.error
    
    def test_or_else_returns_data_on_success(self):
        """or_else gibt Daten bei Erfolg zurück."""
        result = Result.ok("actual")
        assert result.or_else("default") == "actual"
    
    def test_or_else_returns_default_on_failure(self):
        """or_else gibt Default bei Misserfolg zurück."""
        result = Result.fail("error")
        assert result.or_else("default") == "default"
    
    def test_or_raise_returns_data_on_success(self):
        """or_raise gibt Daten bei Erfolg zurück."""
        result = Result.ok("data")
        assert result.or_raise() == "data"
    
    def test_or_raise_raises_on_failure(self):
        """or_raise wirft Exception bei Misserfolg."""
        result = Result.fail("error message")
        with pytest.raises(ValueError) as exc_info:
            result.or_raise()
        assert "error message" in str(exc_info.value)
    
    def test_map_transforms_data(self):
        """map transformiert Daten bei Erfolg."""
        result = Result.ok(5)
        mapped = result.map(lambda x: x * 2)
        assert mapped.success is True
        assert mapped.data == 10
    
    def test_map_preserves_failure(self):
        """map propagiert Fehler."""
        result = Result.fail("error")
        mapped = result.map(lambda x: x * 2)
        assert mapped.success is False
        assert "error" in mapped.error
    
    def test_add_warning(self):
        """add_warning fügt Warnung hinzu."""
        result = Result.ok("data")
        result.add_warning("new warning")
        assert "new warning" in result.warnings
    
    def test_to_dict(self):
        """to_dict serialisiert korrekt."""
        result = Result.ok("data", warnings=["warn"])
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == "data"
        assert d["error"] is None
        assert "warn" in d["warnings"]


class TestServiceResult:
    """Tests für ServiceResult."""
    
    def test_ok_with_source(self):
        """ServiceResult.ok kann Source angeben."""
        result = ServiceResult.ok("data", source="api")
        assert result.success is True
        assert result.source == "api"
    
    def test_ok_with_cached(self):
        """ServiceResult.ok kann cached Flag setzen."""
        result = ServiceResult.ok("data", cached=True)
        assert result.cached is True
    
    def test_ok_with_duration(self):
        """ServiceResult.ok kann Duration angeben."""
        result = ServiceResult.ok("data", duration_ms=123.45)
        assert result.duration_ms == 123.45
    
    def test_fail_with_source(self):
        """ServiceResult.fail kann Source angeben."""
        result = ServiceResult.fail("error", source="api")
        assert result.success is False
        assert result.source == "api"
    
    def test_partial_status(self):
        """ServiceResult.partial erstellt Teilerfolg."""
        result = ServiceResult.partial(
            data=["partial", "data"],
            error="some items failed"
        )
        assert result.success is True
        assert result.status == ResultStatus.PARTIAL
        assert result.error == "some items failed"
    
    def test_timestamp_auto_set(self):
        """timestamp wird automatisch gesetzt."""
        before = datetime.now()
        result = ServiceResult.ok("data")
        after = datetime.now()
        
        assert result.timestamp >= before
        assert result.timestamp <= after
    
    def test_to_dict_includes_metadata(self):
        """to_dict enthält alle Metadaten."""
        result = ServiceResult.ok(
            "data",
            source="test",
            cached=True,
            duration_ms=100.0
        )
        d = result.to_dict()
        
        assert d["source"] == "test"
        assert d["cached"] is True
        assert d["duration_ms"] == 100.0
        assert "timestamp" in d
        assert d["status"] == "success"


class TestBatchResult:
    """Tests für BatchResult."""
    
    def test_empty_batch(self):
        """Leeres BatchResult hat korrekte Defaults."""
        result = BatchResult()
        assert result.success_count == 0
        assert result.failure_count == 0
        assert result.total == 0
    
    def test_add_success(self):
        """add_success fügt erfolgreiche Items hinzu."""
        result = BatchResult()
        result.add_success("item1")
        result.add_success("item2")
        
        assert result.success_count == 2
        assert "item1" in result.successful
    
    def test_add_failure(self):
        """add_failure fügt fehlgeschlagene Items hinzu."""
        result = BatchResult()
        result.add_failure("key1", "error 1")
        result.add_failure("key2", "error 2")
        
        assert result.failure_count == 2
        assert result.failed["key1"] == "error 1"
    
    def test_success_rate(self):
        """success_rate berechnet korrekt."""
        result = BatchResult(total=10)
        result.add_success("a")
        result.add_success("b")
        result.add_success("c")
        result.add_failure("x", "err")
        result.add_failure("y", "err")
        
        # 3 von 5 processed = 60% success
        # Aber total ist 10, also berechnet es basierend auf success_count/total
        assert result.success_rate == 0.3  # 3/10
    
    def test_is_complete_success(self):
        """is_complete_success prüft vollständigen Erfolg."""
        result = BatchResult()
        result.add_success("a")
        result.add_success("b")
        
        assert result.is_complete_success is True
        
        result.add_failure("x", "err")
        assert result.is_complete_success is False
    
    def test_is_complete_failure(self):
        """is_complete_failure prüft vollständigen Misserfolg."""
        result = BatchResult()
        result.add_failure("x", "err")
        result.add_failure("y", "err")
        
        assert result.is_complete_failure is True
        
        result.add_success("a")
        assert result.is_complete_failure is False
    
    def test_is_partial(self):
        """is_partial prüft Teilerfolg."""
        result = BatchResult()
        result.add_success("a")
        result.add_failure("x", "err")
        
        assert result.is_partial is True
    
    def test_to_dict(self):
        """to_dict serialisiert korrekt."""
        result = BatchResult(total=5, duration_ms=100.0)
        result.add_success("a")
        result.add_failure("x", "err")
        
        d = result.to_dict()
        
        assert d["total"] == 5
        assert d["success_count"] == 1
        assert d["failure_count"] == 1
        assert d["duration_ms"] == 100.0
        assert "success_rate" in d


class TestResultChaining:
    """Tests für Result-Chaining Operationen."""
    
    def test_map_chain(self):
        """Mehrere map Aufrufe können verkettet werden."""
        result = Result.ok(2)
        chained = result.map(lambda x: x * 3).map(lambda x: x + 1)
        
        assert chained.data == 7  # (2 * 3) + 1
    
    def test_flat_map(self):
        """flat_map verkettet Results."""
        def double_if_positive(x):
            if x > 0:
                return Result.ok(x * 2)
            return Result.fail("not positive")
        
        result = Result.ok(5)
        chained = result.flat_map(double_if_positive)
        
        assert chained.success is True
        assert chained.data == 10
    
    def test_flat_map_failure(self):
        """flat_map propagiert Fehler."""
        def double_if_positive(x):
            if x > 0:
                return Result.ok(x * 2)
            return Result.fail("not positive")
        
        result = Result.ok(-5)
        chained = result.flat_map(double_if_positive)
        
        assert chained.success is False
        assert "not positive" in chained.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
