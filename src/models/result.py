# OptionPlay - Result Types
# ==========================
"""
Einheitliche Result-Types für konsistente Returns.

Ermöglicht typsichere Fehlerbehandlung ohne Exceptions.

Verwendung:
    from src.models.result import Result, ServiceResult
    
    async def get_quote(symbol: str) -> ServiceResult[Quote]:
        try:
            quote = await provider.fetch(symbol)
            return ServiceResult.ok(quote)
        except APIError as e:
            return ServiceResult.fail(f"API error: {e}")
    
    # Aufruf
    result = await get_quote("AAPL")
    if result.success:
        print(f"Price: {result.data.last}")
    else:
        print(f"Error: {result.error}")
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar, Optional, List, Dict, Any, Callable
from enum import Enum

T = TypeVar('T')


class ResultStatus(Enum):
    """Status eines Results."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"  # Teilerfolg (z.B. einige Symbole fehlgeschlagen)


@dataclass
class Result(Generic[T]):
    """
    Generischer Result-Type für Operationen.
    
    Ermöglicht explizite Erfolg/Fehler-Behandlung ohne Exceptions.
    
    Attributes:
        success: Ob die Operation erfolgreich war
        data: Die Daten bei Erfolg
        error: Fehlermeldung bei Misserfolg
        warnings: Optionale Warnungen (auch bei Erfolg möglich)
    """
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    
    @classmethod
    def ok(cls, data: T, warnings: Optional[List[str]] = None) -> "Result[T]":
        """Erstellt ein erfolgreiches Result."""
        return cls(
            success=True,
            data=data,
            error=None,
            warnings=warnings or []
        )
    
    @classmethod
    def fail(cls, error: str, warnings: Optional[List[str]] = None) -> "Result[T]":
        """Erstellt ein fehlgeschlagenes Result."""
        return cls(
            success=False,
            data=None,
            error=error,
            warnings=warnings or []
        )
    
    @classmethod
    def from_exception(cls, e: Exception) -> "Result[T]":
        """Erstellt Result aus Exception."""
        return cls.fail(f"{type(e).__name__}: {str(e)}")
    
    def map(self, func: Callable[[T], Any]) -> "Result[Any]":
        """Transformiert data wenn erfolgreich."""
        if self.success and self.data is not None:
            try:
                new_data = func(self.data)
                return Result.ok(new_data, self.warnings)
            except Exception as e:
                return Result.fail(str(e), self.warnings)
        return Result.fail(self.error or "No data", self.warnings)
    
    def flat_map(self, func: Callable[[T], "Result[Any]"]) -> "Result[Any]":
        """Transformiert mit Funktion die Result zurückgibt."""
        if self.success and self.data is not None:
            try:
                return func(self.data)
            except Exception as e:
                return Result.fail(str(e), self.warnings)
        return Result.fail(self.error or "No data", self.warnings)
    
    def or_else(self, default: T) -> T:
        """Gibt data oder default zurück."""
        return self.data if self.success and self.data is not None else default
    
    def or_raise(self) -> T:
        """Gibt data zurück oder wirft Exception."""
        if self.success and self.data is not None:
            return self.data
        raise ValueError(self.error or "Result failed with no error message")
    
    def add_warning(self, warning: str) -> "Result[T]":
        """Fügt eine Warnung hinzu."""
        self.warnings.append(warning)
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialisiert zu Dictionary."""
        return {
            "success": self.success,
            "data": self.data if not hasattr(self.data, 'to_dict') else self.data.to_dict(),
            "error": self.error,
            "warnings": self.warnings,
        }


@dataclass
class ServiceResult(Generic[T]):
    """
    Erweitertes Result für Service-Operationen.
    
    Enthält zusätzliche Metadaten wie Timing und Source.
    
    Attributes:
        success: Ob die Operation erfolgreich war
        data: Die Daten bei Erfolg
        error: Fehlermeldung bei Misserfolg
        warnings: Optionale Warnungen
        status: Detaillierter Status (success/failure/partial)
        source: Datenquelle (z.B. "marketdata", "yahoo", "cache")
        cached: Ob Daten aus Cache kommen
        timestamp: Zeitpunkt der Operation
        duration_ms: Dauer in Millisekunden
    """
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    status: ResultStatus = ResultStatus.SUCCESS
    source: Optional[str] = None
    cached: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: Optional[float] = None
    
    @classmethod
    def ok(
        cls,
        data: T,
        source: Optional[str] = None,
        cached: bool = False,
        warnings: Optional[List[str]] = None,
        duration_ms: Optional[float] = None,
    ) -> "ServiceResult[T]":
        """Erstellt ein erfolgreiches ServiceResult."""
        return cls(
            success=True,
            data=data,
            error=None,
            warnings=warnings or [],
            status=ResultStatus.SUCCESS,
            source=source,
            cached=cached,
            duration_ms=duration_ms,
        )
    
    @classmethod
    def fail(
        cls,
        error: str,
        source: Optional[str] = None,
        warnings: Optional[List[str]] = None,
        duration_ms: Optional[float] = None,
    ) -> "ServiceResult[T]":
        """Erstellt ein fehlgeschlagenes ServiceResult."""
        return cls(
            success=False,
            data=None,
            error=error,
            warnings=warnings or [],
            status=ResultStatus.FAILURE,
            source=source,
            duration_ms=duration_ms,
        )
    
    @classmethod
    def partial(
        cls,
        data: T,
        error: str,
        source: Optional[str] = None,
        warnings: Optional[List[str]] = None,
    ) -> "ServiceResult[T]":
        """Erstellt ein Teilerfolg-Result."""
        return cls(
            success=True,  # Teildaten vorhanden
            data=data,
            error=error,
            warnings=warnings or [],
            status=ResultStatus.PARTIAL,
            source=source,
        )
    
    @classmethod
    def from_exception(cls, e: Exception, source: Optional[str] = None) -> "ServiceResult[T]":
        """Erstellt ServiceResult aus Exception."""
        return cls.fail(
            error=f"{type(e).__name__}: {str(e)}",
            source=source
        )
    
    def or_else(self, default: T) -> T:
        """Gibt data oder default zurück."""
        return self.data if self.success and self.data is not None else default
    
    def or_raise(self) -> T:
        """Gibt data zurück oder wirft Exception."""
        if self.success and self.data is not None:
            return self.data
        raise ValueError(self.error or "ServiceResult failed")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialisiert zu Dictionary."""
        data_dict = None
        if self.data is not None:
            if hasattr(self.data, 'to_dict'):
                data_dict = self.data.to_dict()
            elif isinstance(self.data, (dict, list, str, int, float, bool)):
                data_dict = self.data
            else:
                data_dict = str(self.data)
        
        return {
            "success": self.success,
            "data": data_dict,
            "error": self.error,
            "warnings": self.warnings,
            "status": self.status.value,
            "source": self.source,
            "cached": self.cached,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class BatchResult(Generic[T]):
    """
    Result für Batch-Operationen (z.B. Scan über viele Symbole).
    
    Attributes:
        successful: Erfolgreiche Ergebnisse
        failed: Fehlgeschlagene Items mit Fehlermeldung
        total: Gesamtanzahl Items
        warnings: Globale Warnungen
    """
    successful: List[T] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)  # item -> error
    total: int = 0
    warnings: List[str] = field(default_factory=list)
    duration_ms: Optional[float] = None
    
    @property
    def success_count(self) -> int:
        """Anzahl erfolgreicher Items."""
        return len(self.successful)
    
    @property
    def failure_count(self) -> int:
        """Anzahl fehlgeschlagener Items."""
        return len(self.failed)
    
    @property
    def success_rate(self) -> float:
        """Erfolgsquote (0.0 - 1.0)."""
        if self.total == 0:
            return 0.0
        return self.success_count / self.total
    
    @property
    def is_complete_success(self) -> bool:
        """Alle Items erfolgreich?"""
        return self.failure_count == 0 and self.success_count > 0
    
    @property
    def is_complete_failure(self) -> bool:
        """Alle Items fehlgeschlagen?"""
        return self.success_count == 0 and self.failure_count > 0
    
    @property
    def is_partial(self) -> bool:
        """Teilerfolg (einige erfolgreich, einige fehlgeschlagen)?"""
        return self.success_count > 0 and self.failure_count > 0
    
    def add_success(self, item: T) -> None:
        """Fügt erfolgreiches Item hinzu."""
        self.successful.append(item)
    
    def add_failure(self, key: str, error: str) -> None:
        """Fügt fehlgeschlagenes Item hinzu."""
        self.failed[key] = error
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialisiert zu Dictionary."""
        return {
            "total": self.total,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 3),
            "successful": [
                s.to_dict() if hasattr(s, 'to_dict') else s 
                for s in self.successful
            ],
            "failed": self.failed,
            "warnings": self.warnings,
            "duration_ms": self.duration_ms,
        }
