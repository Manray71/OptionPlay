# OptionPlay - Multi-Strategy Scanner Tests
# ==========================================

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Tuple, List

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scanner.multi_strategy_scanner import (
    MultiStrategyScanner,
    ScanConfig,
    ScanResult,
    ScanMode,
    create_scanner,
    quick_scan
)
from models.base import SignalType, SignalStrength


# =============================================================================
# Test Data Fixtures
# =============================================================================

def create_uptrend_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt Aufwärtstrend-Daten"""
    prices = [100 + i * 0.2 for i in range(n)]
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


def create_pullback_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt Pullback-Daten (Aufwärtstrend mit Rücksetzer)"""
    prices = []
    for i in range(n):
        if i < 80:
            prices.append(100 + i * 0.25)  # Aufwärtstrend
        else:
            prices.append(120 - (i - 80) * 0.3)  # Pullback
    
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


def create_bounce_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt Bounce-Daten (Support-Test)"""
    prices = []
    highs = []
    lows = []
    
    for i in range(n):
        if i < 60:
            p = 100 + i * 0.2
        elif i < 85:
            p = 112 - (i - 60) * 0.5  # Pullback
        else:
            p = 99.5 + (i - 85) * 0.3  # Bounce
        
        prices.append(p)
        highs.append(p + 0.5)
        lows.append(p - 0.5)
    
    # Support-Touches
    lows[30] = 99.0
    lows[55] = 99.2
    lows[84] = 99.0
    
    volumes = [1000000] * n
    volumes[-1] = 1500000  # Erhöhtes Volumen beim Bounce
    
    return prices, volumes, highs, lows


def create_flat_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt flache Daten (kein Signal)"""
    prices = [100.0] * n
    volumes = [1000000] * n
    highs = [100.5] * n
    lows = [99.5] * n
    return prices, volumes, highs, lows


# =============================================================================
# Scanner Initialization Tests
# =============================================================================

class TestScannerInitialization:
    """Tests für Scanner-Initialisierung"""
    
    def test_default_initialization(self):
        """Standard-Initialisierung sollte alle Analyzer registrieren"""
        scanner = MultiStrategyScanner()
        
        # Sollte mindestens 3 Analyzer haben (pullback könnte fehlen)
        assert len(scanner.available_strategies) >= 3
        assert 'ath_breakout' in scanner.available_strategies
        assert 'bounce' in scanner.available_strategies
        assert 'earnings_dip' in scanner.available_strategies
    
    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = ScanConfig(
            min_score=7.0,
            enable_earnings_dip=False,
            max_total_results=20
        )
        scanner = MultiStrategyScanner(config)
        
        assert scanner.config.min_score == 7.0
        assert scanner.config.max_total_results == 20
        assert 'earnings_dip' not in scanner.available_strategies
    
    def test_create_scanner_factory(self):
        """Factory-Funktion sollte funktionieren"""
        scanner = create_scanner(
            enable_pullback=False,
            enable_breakout=True,
            min_score=6.0
        )
        
        assert scanner.config.min_score == 6.0
        assert 'ath_breakout' in scanner.available_strategies


# =============================================================================
# Single Symbol Analysis Tests
# =============================================================================

class TestSingleSymbolAnalysis:
    """Tests für Einzelsymbol-Analyse"""
    
    @pytest.fixture
    def scanner(self):
        return MultiStrategyScanner()
    
    def test_analyze_uptrend(self, scanner):
        """Aufwärtstrend sollte analysiert werden"""
        prices, volumes, highs, lows = create_uptrend_data()
        
        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)
        
        # Sollte mindestens ein Signal zurückgeben oder leer sein
        assert isinstance(signals, list)
    
    def test_analyze_with_strategy_filter(self, scanner):
        """Strategie-Filter sollte funktionieren"""
        prices, volumes, highs, lows = create_uptrend_data()
        
        signals = scanner.analyze_symbol(
            "TEST", prices, volumes, highs, lows,
            strategies=['bounce']
        )
        
        # Alle Signale sollten von bounce sein
        for signal in signals:
            assert signal.strategy == 'bounce'
    
    def test_analyze_flat_no_signals(self, scanner):
        """Flache Daten sollten wenige/keine Signale geben"""
        prices, volumes, highs, lows = create_flat_data()
        
        # Erhöhe min_score um keine Signale zu bekommen
        scanner.config.min_score = 8.0
        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)
        
        assert len(signals) == 0
    
    def test_signals_sorted_by_score(self, scanner):
        """Signale sollten nach Score sortiert sein"""
        prices, volumes, highs, lows = create_bounce_data()
        scanner.config.min_score = 0  # Alle Signale
        
        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)
        
        if len(signals) > 1:
            scores = [s.score for s in signals]
            assert scores == sorted(scores, reverse=True)


# =============================================================================
# Sync Scan Tests
# =============================================================================

class TestSyncScan:
    """Tests für synchrones Scanning"""

    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,  # Alle Signale
            enable_liquidity_filter=False,  # Deaktiviere Filter für Tests
            enable_fundamentals_filter=False,
        )
        return MultiStrategyScanner(config)
    
    def test_scan_multiple_symbols(self, scanner):
        """Scan mehrerer Symbole"""
        data_map = {
            "AAPL": create_uptrend_data(),
            "MSFT": create_bounce_data(),
            "GOOGL": create_flat_data()
        }
        
        def data_fetcher(symbol):
            return data_map.get(symbol)
        
        result = scanner.scan_sync(
            symbols=list(data_map.keys()),
            data_fetcher=data_fetcher
        )
        
        assert isinstance(result, ScanResult)
        assert result.symbols_scanned == 3
        assert result.scan_duration_seconds > 0
    
    def test_scan_with_mode_filter(self, scanner):
        """Scan mit Mode-Filter"""
        def data_fetcher(symbol):
            return create_bounce_data()
        
        result = scanner.scan_sync(
            symbols=["TEST1", "TEST2"],
            data_fetcher=data_fetcher,
            mode=ScanMode.BOUNCE_ONLY
        )
        
        # Alle Signale sollten bounce sein
        for signal in result.signals:
            assert signal.strategy == 'bounce'
    
    def test_scan_best_signal_mode(self, scanner):
        """Best Signal Mode sollte nur bestes pro Symbol behalten"""
        def data_fetcher(symbol):
            return create_bounce_data()
        
        result = scanner.scan_sync(
            symbols=["TEST1", "TEST2", "TEST3"],
            data_fetcher=data_fetcher,
            mode=ScanMode.BEST_SIGNAL
        )
        
        # Maximal ein Signal pro Symbol
        symbols = [s.symbol for s in result.signals]
        assert len(symbols) == len(set(symbols))
    
    def test_progress_callback(self, scanner):
        """Progress Callback sollte aufgerufen werden"""
        progress_calls = []
        
        def progress(current, total, symbol):
            progress_calls.append((current, total, symbol))
        
        def data_fetcher(symbol):
            return create_flat_data()
        
        scanner.scan_sync(
            symbols=["A", "B", "C"],
            data_fetcher=data_fetcher,
            progress_callback=progress
        )
        
        assert len(progress_calls) == 3
        assert progress_calls[0] == (1, 3, "A")
        assert progress_calls[2] == (3, 3, "C")


# =============================================================================
# Async Scan Tests
# =============================================================================

class TestAsyncScan:
    """Tests für asynchrones Scanning"""
    
    @pytest.fixture
    def scanner(self):
        config = ScanConfig(min_score=0)
        return MultiStrategyScanner(config)
    
    @pytest.mark.asyncio
    async def test_async_scan(self, scanner):
        """Async Scan sollte funktionieren"""
        async def data_fetcher(symbol):
            await asyncio.sleep(0.01)  # Simuliere I/O
            return create_uptrend_data()
        
        result = await scanner.scan_async(
            symbols=["TEST1", "TEST2"],
            data_fetcher=data_fetcher
        )
        
        assert isinstance(result, ScanResult)
        assert result.symbols_scanned == 2
    
    @pytest.mark.asyncio
    async def test_async_with_errors(self, scanner):
        """Async Scan sollte Fehler handhaben"""
        async def data_fetcher(symbol):
            if symbol == "ERROR":
                raise ValueError("Test error")
            return create_flat_data()
        
        result = await scanner.scan_async(
            symbols=["OK", "ERROR", "OK2"],
            data_fetcher=data_fetcher
        )
        
        assert result.symbols_scanned == 3
        assert len(result.errors) == 1
        assert "ERROR" in result.errors[0]


# =============================================================================
# Earnings Filter Tests
# =============================================================================

class TestEarningsFilter:
    """Tests für Earnings-Filter"""
    
    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,
            exclude_earnings_within_days=30
        )
        return MultiStrategyScanner(config)
    
    def test_earnings_filter_excludes(self, scanner):
        """Symbole mit nahen Earnings sollten gefiltert werden"""
        # Setze Earnings in 10 Tagen
        scanner.set_earnings_date("AAPL", date.today() + timedelta(days=10))
        
        prices, volumes, highs, lows = create_bounce_data()
        
        # Bounce sollte gefiltert werden (nicht earnings_dip)
        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows,
            strategies=['bounce', 'earnings_dip']
        )
        
        bounce_signals = [s for s in signals if s.strategy == 'bounce']
        assert len(bounce_signals) == 0  # Bounce gefiltert
    
    def test_earnings_dip_with_upcoming_earnings_filtered(self, scanner):
        """earnings_dip sollte gefiltert werden wenn Earnings BEVORSTEHEN"""
        # Earnings in 10 Tagen -> noch nicht stattgefunden -> skip
        scanner.set_earnings_date("AAPL", date.today() + timedelta(days=10))
        should_skip = scanner._should_skip_for_earnings("AAPL", "earnings_dip")
        assert should_skip == True

    def test_earnings_dip_with_recent_past_earnings_not_filtered(self, scanner):
        """earnings_dip sollte NICHT gefiltert werden wenn Earnings KÜRZLICH waren"""
        # Earnings vor 5 Tagen -> kürzlich vergangen -> nicht skippen
        scanner.set_earnings_date("AAPL", date.today() - timedelta(days=5))
        should_skip = scanner._should_skip_for_earnings("AAPL", "earnings_dip")
        assert should_skip == False

    def test_earnings_dip_with_old_past_earnings_filtered(self, scanner):
        """earnings_dip sollte gefiltert werden wenn Earnings zu LANGE HER sind"""
        # Earnings vor 15 Tagen -> zu alt -> skip
        scanner.set_earnings_date("AAPL", date.today() - timedelta(days=15))
        should_skip = scanner._should_skip_for_earnings("AAPL", "earnings_dip")
        assert should_skip == True

    def test_past_earnings_not_filtered_for_other_strategies(self, scanner):
        """Vergangene Earnings sollten andere Strategien nicht filtern"""
        scanner.set_earnings_date("AAPL", date.today() - timedelta(days=5))
        should_skip = scanner._should_skip_for_earnings("AAPL", "bounce")
        assert should_skip == False

    def test_unknown_earnings_allowed_for_other_strategies(self, scanner):
        """Unbekannte Earnings sollten andere Strategien nicht blockieren"""
        # MSFT hat KEIN Earnings-Datum im Scanner-Cache
        # Neue Logik: erlaubt die Analyse statt konservativ zu überspringen
        should_skip = scanner._should_skip_for_earnings("MSFT", "bounce")
        assert should_skip == False

    def test_unknown_earnings_filtered_for_earnings_dip(self, scanner):
        """earnings_dip sollte auch bei unbekannten Earnings gefiltert werden"""
        # MSFT hat KEIN Earnings-Datum im Scanner-Cache
        # earnings_dip braucht bekannte, kürzlich vergangene Earnings -> skip
        should_skip = scanner._should_skip_for_earnings("MSFT", "earnings_dip")
        assert should_skip == True


# =============================================================================
# Result and Export Tests
# =============================================================================

class TestScanResult:
    """Tests für ScanResult"""
    
    @pytest.fixture
    def scanner(self):
        return MultiStrategyScanner(ScanConfig(min_score=0))
    
    def test_get_by_strategy(self, scanner):
        """Filter by strategy sollte funktionieren"""
        def data_fetcher(symbol):
            return create_bounce_data()
        
        result = scanner.scan_sync(["TEST"], data_fetcher)
        
        bounce_signals = result.get_by_strategy('bounce')
        assert all(s.strategy == 'bounce' for s in bounce_signals)
    
    def test_get_actionable(self, scanner):
        """get_actionable sollte nur actionable Signale zurückgeben"""
        scanner.config.min_score = 0
        
        def data_fetcher(symbol):
            return create_bounce_data()
        
        result = scanner.scan_sync(["TEST"], data_fetcher)
        actionable = result.get_actionable()
        
        for signal in actionable:
            assert signal.is_actionable
    
    def test_to_dict(self, scanner):
        """to_dict sollte Dictionary zurückgeben"""
        def data_fetcher(symbol):
            return create_flat_data()
        
        result = scanner.scan_sync(["TEST"], data_fetcher)
        d = result.to_dict()
        
        assert 'timestamp' in d
        assert 'symbols_scanned' in d
        assert 'signals' in d
        assert isinstance(d['signals'], list)
    
    def test_export_csv(self, scanner):
        """CSV Export sollte funktionieren"""
        def data_fetcher(symbol):
            return create_bounce_data()
        
        result = scanner.scan_sync(["TEST"], data_fetcher)
        csv = scanner.export_signals(result, format='csv')
        
        assert csv is not None
        assert 'symbol,strategy' in csv
    
    def test_summary(self, scanner):
        """Summary sollte Text zurückgeben"""
        def data_fetcher(symbol):
            return create_bounce_data()
        
        result = scanner.scan_sync(["TEST"], data_fetcher)
        summary = scanner.get_summary(result)
        
        assert "SCAN SUMMARY" in summary
        assert "TEST" in summary or "Symbols scanned" in summary


# =============================================================================
# Quick Scan Tests
# =============================================================================

class TestQuickScan:
    """Tests für quick_scan Funktion"""
    
    def test_quick_scan_returns_signals(self):
        """quick_scan sollte Signale zurückgeben"""
        def data_fetcher(symbol):
            return create_bounce_data()
        
        signals = quick_scan(
            symbols=["TEST"],
            data_fetcher=data_fetcher,
            min_score=0
        )
        
        assert isinstance(signals, list)


# =============================================================================
# Stability-First Filter Tests (Phase 6)
# =============================================================================

class TestStabilityFirstFilter:
    """Tests für Stability-First-Filterung"""

    @pytest.fixture
    def scanner_stability_enabled(self):
        """Scanner mit Stability-First aktiviert"""
        return MultiStrategyScanner(ScanConfig(
            min_score=3.5,
            enable_stability_first=True,
            stability_premium_threshold=80.0,
            stability_premium_min_score=4.0,
            stability_good_threshold=70.0,
            stability_good_min_score=5.0,
            stability_ok_threshold=50.0,
            stability_ok_min_score=6.0,
        ))

    @pytest.fixture
    def scanner_stability_disabled(self):
        """Scanner mit Stability-First deaktiviert"""
        return MultiStrategyScanner(ScanConfig(
            min_score=3.5,
            enable_stability_first=False,
        ))

    def _create_test_signal(self, symbol: str, score: float, stability_score: float = None):
        """Erstellt ein Test-Signal mit optionalem Stability-Score"""
        from models.base import TradeSignal, SignalType, SignalStrength

        details = {}
        if stability_score is not None:
            details['stability'] = {'score': stability_score}

        return TradeSignal(
            symbol=symbol,
            strategy='pullback',
            signal_type=SignalType.LONG,
            strength=SignalStrength.MODERATE,
            score=score,
            current_price=100.0,
            details=details
        )

    def test_premium_symbol_low_score_passes(self, scanner_stability_enabled):
        """Premium-Symbol (Stability ≥80) mit niedrigem Score sollte durchkommen"""
        signals = [self._create_test_signal('AAPL', score=4.5, stability_score=85.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 1
        assert stats['premium_kept'] == 1

    def test_premium_symbol_very_low_score_fails(self, scanner_stability_enabled):
        """Premium-Symbol mit zu niedrigem Score sollte gefiltert werden"""
        signals = [self._create_test_signal('MSFT', score=3.5, stability_score=85.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 0
        assert stats['score_too_low'] == 1

    def test_good_symbol_medium_score_passes(self, scanner_stability_enabled):
        """Gutes Symbol (Stability 70-80) mit mittlerem Score sollte durchkommen"""
        signals = [self._create_test_signal('GOOGL', score=5.5, stability_score=75.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 1
        assert stats['good_kept'] == 1

    def test_good_symbol_low_score_fails(self, scanner_stability_enabled):
        """Gutes Symbol mit zu niedrigem Score sollte gefiltert werden"""
        signals = [self._create_test_signal('META', score=4.5, stability_score=75.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 0
        assert stats['score_too_low'] == 1

    def test_ok_symbol_high_score_passes(self, scanner_stability_enabled):
        """OK-Symbol (Stability 50-70) mit hohem Score sollte durchkommen"""
        signals = [self._create_test_signal('NFLX', score=7.0, stability_score=55.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 1
        assert stats['ok_kept'] == 1

    def test_ok_symbol_medium_score_fails(self, scanner_stability_enabled):
        """OK-Symbol mit mittlerem Score sollte gefiltert werden"""
        signals = [self._create_test_signal('AMZN', score=5.5, stability_score=55.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 0
        assert stats['score_too_low'] == 1

    def test_blacklist_symbol_always_fails(self, scanner_stability_enabled):
        """Blacklist-Symbol (Stability <50) sollte immer gefiltert werden"""
        signals = [self._create_test_signal('TSLA', score=9.0, stability_score=40.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 0
        assert stats['blacklisted'] == 1

    def test_no_stability_data_uses_min_score(self, scanner_stability_enabled):
        """Symbol ohne Stability-Daten sollte min_score verwenden"""
        signals = [self._create_test_signal('UNKNOWN', score=4.0, stability_score=None)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        # Score 4.0 >= min_score 3.5, sollte durchkommen
        assert len(filtered) == 1
        assert stats['no_stability_data'] == 1

    def test_filter_disabled_passes_all(self, scanner_stability_disabled):
        """Bei deaktiviertem Filter sollten alle Signale durchkommen"""
        signals = [
            self._create_test_signal('AAPL', score=4.0, stability_score=85.0),
            self._create_test_signal('TSLA', score=9.0, stability_score=40.0),
        ]
        filtered, stats = scanner_stability_disabled._filter_by_stability(signals)

        assert len(filtered) == 2
        assert stats.get('reason') == 'disabled'

    def test_mixed_signals_correctly_filtered(self, scanner_stability_enabled):
        """Gemischte Signale sollten korrekt gefiltert werden"""
        signals = [
            self._create_test_signal('AAPL', score=4.5, stability_score=85.0),  # Premium OK
            self._create_test_signal('MSFT', score=3.5, stability_score=85.0),  # Premium score too low
            self._create_test_signal('GOOGL', score=5.5, stability_score=75.0),  # Good OK
            self._create_test_signal('META', score=4.5, stability_score=75.0),  # Good score too low
            self._create_test_signal('NFLX', score=7.0, stability_score=55.0),  # OK OK
            self._create_test_signal('AMZN', score=5.5, stability_score=55.0),  # OK score too low
            self._create_test_signal('TSLA', score=9.0, stability_score=40.0),  # Blacklist
        ]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 3
        passed_symbols = {s.symbol for s in filtered}
        assert passed_symbols == {'AAPL', 'GOOGL', 'NFLX'}

        assert stats['premium_kept'] == 1
        assert stats['good_kept'] == 1
        assert stats['ok_kept'] == 1
        assert stats['blacklisted'] == 1
        assert stats['score_too_low'] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
