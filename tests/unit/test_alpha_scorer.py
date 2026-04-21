"""Tests for AlphaScorer (E.2) — composite scoring, percentile-rank, ampel logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.alpha import AlphaCandidate
from src.services.alpha_scorer import AlphaScorer
from src.services.sector_rs import RSQuadrant, StockRS

# =============================================================================
# HELPERS
# =============================================================================


def _make_stock_rs(
    symbol: str,
    b_raw: float = 0.0,
    f_raw: float = 0.0,
    quadrant: RSQuadrant = RSQuadrant.LEADING,
    quadrant_fast: RSQuadrant = RSQuadrant.LEADING,
    dual_label: str = "LEADING",
) -> StockRS:
    return StockRS(
        symbol=symbol,
        rs_ratio=100.0 + b_raw,
        rs_momentum=101.0,
        quadrant=quadrant,
        rs_ratio_fast=100.0 + f_raw,
        rs_momentum_fast=101.0,
        quadrant_fast=quadrant_fast,
        dual_label=dual_label,
        b_raw=b_raw,
        f_raw=f_raw,
    )


def _build_scorer(
    stock_rs_map: dict,
    fast_weight: float = 1.5,
    sector_map: dict | None = None,
) -> AlphaScorer:
    """Build AlphaScorer with mocked SectorRSService."""
    mock_srs = MagicMock()
    mock_srs.get_all_stock_rs = AsyncMock(return_value=stock_rs_map)
    mock_srs.get_all_sector_rs = AsyncMock(return_value={})

    config = {"fast_weight": fast_weight, "alpha_longlist_size": 30}
    scorer = AlphaScorer(sector_rs_service=mock_srs, config=config)

    if sector_map:
        scorer._sector_map = sector_map

    return scorer


# =============================================================================
# COMPOSITE CALCULATION
# =============================================================================


class TestCompositeCalculation:
    @pytest.mark.asyncio
    async def test_basic_composite(self):
        """b_raw=2.0, f_raw=3.0, weight=1.5 -> alpha_raw = 2.0 + 1.5*3.0 = 6.5"""
        rs_map = {"AAPL": _make_stock_rs("AAPL", b_raw=2.0, f_raw=3.0)}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["AAPL"])
        assert len(result) == 1
        assert result[0].alpha_raw == pytest.approx(6.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_negative_b_positive_f(self):
        """b_raw=-1.0, f_raw=4.0 -> -1.0 + 1.5*4.0 = 5.0"""
        rs_map = {"TEST": _make_stock_rs("TEST", b_raw=-1.0, f_raw=4.0)}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["TEST"])
        assert result[0].alpha_raw == pytest.approx(5.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_both_negative(self):
        """b_raw=-2.0, f_raw=-1.0 -> -2.0 + 1.5*(-1.0) = -3.5"""
        rs_map = {"NEG": _make_stock_rs("NEG", b_raw=-2.0, f_raw=-1.0)}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["NEG"])
        assert result[0].alpha_raw == pytest.approx(-3.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_custom_weight(self):
        """With weight=2.0: 1.0 + 2.0*3.0 = 7.0"""
        rs_map = {"X": _make_stock_rs("X", b_raw=1.0, f_raw=3.0)}
        scorer = _build_scorer(rs_map, fast_weight=2.0)
        result = await scorer.generate_longlist(["X"])
        assert result[0].alpha_raw == pytest.approx(7.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_zero_values(self):
        """b_raw=0, f_raw=0 -> alpha_raw=0"""
        rs_map = {"Z": _make_stock_rs("Z", b_raw=0.0, f_raw=0.0)}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["Z"])
        assert result[0].alpha_raw == pytest.approx(0.0, abs=0.01)


# =============================================================================
# PERCENTILE RANK
# =============================================================================


class TestPercentileRank:
    def test_five_symbols(self):
        """5 symbols [1,2,3,4,5] -> percentiles [0,25,50,75,100]"""
        scorer = _build_scorer({})
        scores = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
        result = scorer._compute_percentile_ranks(scores)
        assert result["A"] == 0
        assert result["B"] == 25
        assert result["C"] == 50
        assert result["D"] == 75
        assert result["E"] == 100

    def test_single_symbol(self):
        """1 symbol -> percentile 50 (edge case)"""
        scorer = _build_scorer({})
        scores = {"ONLY": 42.0}
        result = scorer._compute_percentile_ranks(scores)
        assert result["ONLY"] == 50

    def test_100_symbols(self):
        """100 symbols: rank 0 -> P0, rank 99 -> P100"""
        scorer = _build_scorer({})
        scores = {f"S{i}": float(i) for i in range(100)}
        result = scorer._compute_percentile_ranks(scores)
        assert result["S0"] == 0
        assert result["S99"] == 100
        assert result["S50"] == pytest.approx(50, abs=1)

    def test_empty_scores(self):
        scorer = _build_scorer({})
        result = scorer._compute_percentile_ranks({})
        assert result == {}

    def test_two_symbols(self):
        """2 symbols: lower=P0, higher=P100"""
        scorer = _build_scorer({})
        scores = {"LO": 1.0, "HI": 5.0}
        result = scorer._compute_percentile_ranks(scores)
        assert result["LO"] == 0
        assert result["HI"] == 100

    def test_tied_scores(self):
        """Tied scores get different percentiles (rank-based, not value-based)."""
        scorer = _build_scorer({})
        scores = {"A": 5.0, "B": 5.0, "C": 5.0}
        result = scorer._compute_percentile_ranks(scores)
        vals = sorted(result.values())
        assert vals == [0, 50, 100]


# =============================================================================
# LONGLIST TOP-N
# =============================================================================


class TestLonglistTopN:
    @pytest.mark.asyncio
    async def test_top_n_selection(self):
        """50 symbols, top_n=10 -> exactly 10 returned."""
        rs_map = {
            f"S{i}": _make_stock_rs(f"S{i}", b_raw=float(i), f_raw=float(i)) for i in range(50)
        }
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist([f"S{i}" for i in range(50)], top_n=10)
        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_sorted_descending(self):
        """Highest percentile first."""
        rs_map = {
            "LOW": _make_stock_rs("LOW", b_raw=-5.0, f_raw=-5.0),
            "MID": _make_stock_rs("MID", b_raw=0.0, f_raw=0.0),
            "HIGH": _make_stock_rs("HIGH", b_raw=5.0, f_raw=5.0),
        }
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["LOW", "MID", "HIGH"], top_n=3)
        assert result[0].symbol == "HIGH"
        assert result[-1].symbol == "LOW"

    @pytest.mark.asyncio
    async def test_top_n_larger_than_symbols(self):
        """top_n > len(symbols) -> all returned, no crash."""
        rs_map = {"A": _make_stock_rs("A"), "B": _make_stock_rs("B")}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["A", "B"], top_n=100)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_default_top_n_from_config(self):
        """Default top_n from config (30)."""
        rs_map = {f"S{i}": _make_stock_rs(f"S{i}", b_raw=float(i)) for i in range(50)}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist([f"S{i}" for i in range(50)])
        assert len(result) == 30


# =============================================================================
# DUAL LABEL PASSTHROUGH
# =============================================================================


class TestDualLabelPassthrough:
    @pytest.mark.asyncio
    async def test_dual_label_preserved(self):
        """StockRS dual_label is passed through to AlphaCandidate."""
        rs_map = {
            "X": _make_stock_rs(
                "X",
                quadrant=RSQuadrant.LAGGING,
                quadrant_fast=RSQuadrant.IMPROVING,
                dual_label="LAG→IMP",
            )
        }
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["X"])
        assert result[0].dual_label == "LAG→IMP"

    @pytest.mark.asyncio
    async def test_quadrants_preserved(self):
        """Slow and fast quadrants are passed through."""
        rs_map = {
            "Y": _make_stock_rs(
                "Y",
                quadrant=RSQuadrant.WEAKENING,
                quadrant_fast=RSQuadrant.LEADING,
            )
        }
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["Y"])
        assert result[0].quadrant_slow == RSQuadrant.WEAKENING
        assert result[0].quadrant_fast == RSQuadrant.LEADING


# =============================================================================
# AMPEL LOGIC
# =============================================================================


class TestAmpelLogic:
    def _ampel(self, slow: RSQuadrant, fast: RSQuadrant) -> dict:
        return AlphaScorer._compute_ampel(slow, fast)

    def test_both_bullish_green(self):
        """IMP/LEAD + IMP/LEAD -> green"""
        for slow in [RSQuadrant.IMPROVING, RSQuadrant.LEADING]:
            for fast in [RSQuadrant.IMPROVING, RSQuadrant.LEADING]:
                result = self._ampel(slow, fast)
                assert result["color"] == "green", f"{slow}+{fast} should be green"
                assert result["text"] == "Tradeable"

    def test_slow_bearish_fast_bullish_yellow(self):
        """LAG/WEAK + IMP/LEAD -> yellow (100d noch schwach)"""
        for slow in [RSQuadrant.LAGGING, RSQuadrant.WEAKENING]:
            for fast in [RSQuadrant.IMPROVING, RSQuadrant.LEADING]:
                result = self._ampel(slow, fast)
                assert result["color"] == "yellow", f"{slow}+{fast} should be yellow"
                assert "100d" in result["text"]

    def test_both_bearish_red(self):
        """WEAK/LAG + WEAK/LAG -> red"""
        for slow in [RSQuadrant.WEAKENING, RSQuadrant.LAGGING]:
            for fast in [RSQuadrant.WEAKENING, RSQuadrant.LAGGING]:
                result = self._ampel(slow, fast)
                assert result["color"] == "red", f"{slow}+{fast} should be red"
                assert result["text"] == "Not tradeable"

    def test_slow_bullish_fast_bearish_yellow(self):
        """LEAD/IMP + WEAK/LAG -> yellow (20d schwächt sich ab)"""
        for slow in [RSQuadrant.LEADING, RSQuadrant.IMPROVING]:
            for fast in [RSQuadrant.WEAKENING, RSQuadrant.LAGGING]:
                result = self._ampel(slow, fast)
                assert result["color"] == "yellow", f"{slow}+{fast} should be yellow"
                assert "20d" in result["text"]


# =============================================================================
# GRACEFUL DEGRADATION
# =============================================================================


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_empty_symbols(self):
        """Empty symbol list -> empty longlist."""
        scorer = _build_scorer({})
        result = await scorer.generate_longlist([])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_valid_stock_rs(self):
        """StockRS returns nothing -> empty longlist."""
        mock_srs = MagicMock()
        mock_srs.get_all_stock_rs = AsyncMock(return_value={})
        scorer = AlphaScorer(sector_rs_service=mock_srs, config={"fast_weight": 1.5})
        result = await scorer.generate_longlist(["AAPL", "MSFT"])
        assert result == []

    @pytest.mark.asyncio
    async def test_partial_stock_rs(self):
        """Some symbols fail in StockRS -> only valid ones ranked."""
        rs_map = {
            "AAPL": _make_stock_rs("AAPL", b_raw=2.0, f_raw=1.0),
            # MSFT missing (simulates failed fetch)
        }
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["AAPL", "MSFT", "GOOGL"], top_n=10)
        assert len(result) == 1
        assert result[0].symbol == "AAPL"


# =============================================================================
# CONFIG REGRESSION
# =============================================================================


class TestConfigRegression:
    def test_fast_weight_from_yaml(self):
        """fast_weight is loaded from config."""
        scorer = AlphaScorer(
            sector_rs_service=AsyncMock(),
            config={"fast_weight": 2.0},
        )
        assert scorer._fast_weight == 2.0

    def test_fast_weight_default(self):
        """fast_weight defaults to 1.5."""
        scorer = AlphaScorer(
            sector_rs_service=AsyncMock(),
            config={},
        )
        assert scorer._fast_weight == 1.5

    def test_longlist_size_from_config(self):
        """alpha_longlist_size is loaded from config."""
        scorer = AlphaScorer(
            sector_rs_service=AsyncMock(),
            config={"alpha_longlist_size": 50},
        )
        assert scorer._default_top_n == 50

    def test_longlist_size_default(self):
        """alpha_longlist_size defaults to 30."""
        scorer = AlphaScorer(
            sector_rs_service=AsyncMock(),
            config={},
        )
        assert scorer._default_top_n == 30


# =============================================================================
# SECTOR LOOKUP
# =============================================================================


class TestSectorLookup:
    @pytest.mark.asyncio
    async def test_sector_from_map(self):
        """Sector is looked up from pre-built map."""
        rs_map = {"AAPL": _make_stock_rs("AAPL")}
        scorer = _build_scorer(rs_map, sector_map={"AAPL": "Technology"})
        result = await scorer.generate_longlist(["AAPL"])
        assert result[0].sector == "Technology"

    @pytest.mark.asyncio
    async def test_sector_financials(self):
        rs_map = {"JPM": _make_stock_rs("JPM")}
        scorer = _build_scorer(rs_map, sector_map={"JPM": "Financials"})
        result = await scorer.generate_longlist(["JPM"])
        assert result[0].sector == "Financials"

    @pytest.mark.asyncio
    async def test_unknown_symbol_sector(self):
        """Unknown symbol -> 'Unknown' sector (no crash)."""
        rs_map = {"XYZ123": _make_stock_rs("XYZ123")}
        scorer = _build_scorer(rs_map, sector_map={})
        scorer._build_sector_map = MagicMock()  # prevent DB lookup
        result = await scorer.generate_longlist(["XYZ123"])
        assert result[0].sector == "Unknown"


# =============================================================================
# SECTOR ALPHA SUMMARY
# =============================================================================


class TestSectorAlphaSummary:
    @pytest.mark.asyncio
    async def test_summary_structure(self):
        """Summary returns all expected keys."""
        from src.services.sector_rs import SectorRS

        mock_srs = MagicMock()
        mock_srs.get_all_sector_rs = AsyncMock(
            return_value={
                "Technology": SectorRS(
                    sector="Technology",
                    etf_symbol="XLK",
                    rs_ratio=102.0,
                    rs_momentum=101.0,
                    quadrant=RSQuadrant.LEADING,
                    score_modifier=0.5,
                    rs_ratio_fast=103.0,
                    rs_momentum_fast=102.0,
                    quadrant_fast=RSQuadrant.LEADING,
                    dual_label="LEADING",
                )
            }
        )
        scorer = AlphaScorer(sector_rs_service=mock_srs, config={"fast_weight": 1.5})
        result = await scorer.get_sector_alpha_summary()
        assert len(result) == 1
        entry = result[0]
        assert entry["sector"] == "Technology"
        assert entry["etf"] == "XLK"
        assert entry["ampel"] == "green"
        assert entry["ampel_text"] == "Tradeable"
        assert entry["quadrant_slow"] == "leading"
        assert entry["quadrant_fast"] == "leading"
        assert entry["dual_label"] == "LEADING"
        assert entry["score_modifier"] == 0.5

    @pytest.mark.asyncio
    async def test_summary_red_sector(self):
        """Bearish sector -> red ampel."""
        from src.services.sector_rs import SectorRS

        mock_srs = MagicMock()
        mock_srs.get_all_sector_rs = AsyncMock(
            return_value={
                "Energy": SectorRS(
                    sector="Energy",
                    etf_symbol="XLE",
                    rs_ratio=98.0,
                    rs_momentum=99.0,
                    quadrant=RSQuadrant.LAGGING,
                    score_modifier=-0.5,
                    rs_ratio_fast=97.0,
                    rs_momentum_fast=98.0,
                    quadrant_fast=RSQuadrant.LAGGING,
                    dual_label="LAGGING",
                )
            }
        )
        scorer = AlphaScorer(sector_rs_service=mock_srs, config={"fast_weight": 1.5})
        result = await scorer.get_sector_alpha_summary()
        assert result[0]["ampel"] == "red"


# =============================================================================
# ALPHA CANDIDATE DATACLASS
# =============================================================================


class TestAlphaCandidate:
    def test_frozen(self):
        """AlphaCandidate is immutable."""
        c = AlphaCandidate(
            symbol="AAPL",
            b_raw=1.0,
            f_raw=2.0,
            alpha_raw=4.0,
            alpha_percentile=75,
            quadrant_slow=RSQuadrant.LEADING,
            quadrant_fast=RSQuadrant.IMPROVING,
            dual_label="LEAD→IMP",
            sector="Technology",
        )
        with pytest.raises(AttributeError):
            c.symbol = "MSFT"  # type: ignore[misc]

    def test_fields(self):
        c = AlphaCandidate(
            symbol="JPM",
            b_raw=-0.5,
            f_raw=1.2,
            alpha_raw=1.3,
            alpha_percentile=60,
            quadrant_slow=RSQuadrant.LAGGING,
            quadrant_fast=RSQuadrant.IMPROVING,
            dual_label="LAG→IMP",
            sector="Financials",
        )
        assert c.symbol == "JPM"
        assert c.b_raw == -0.5
        assert c.f_raw == 1.2
        assert c.alpha_raw == 1.3
        assert c.alpha_percentile == 60
        assert c.dual_label == "LAG→IMP"
        assert c.sector == "Financials"


# =============================================================================
# INTEGRATION-STYLE: FULL PIPELINE
# =============================================================================


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_end_to_end_ranking(self):
        """Full pipeline: 5 symbols -> ranked by percentile."""
        rs_map = {
            "A": _make_stock_rs("A", b_raw=1.0, f_raw=0.5),  # 1.0 + 1.5*0.5 = 1.75
            "B": _make_stock_rs("B", b_raw=3.0, f_raw=2.0),  # 3.0 + 1.5*2.0 = 6.0
            "C": _make_stock_rs("C", b_raw=-1.0, f_raw=-0.5),  # -1.0 + 1.5*(-0.5) = -1.75
            "D": _make_stock_rs("D", b_raw=0.0, f_raw=0.0),  # 0.0
            "E": _make_stock_rs("E", b_raw=5.0, f_raw=3.0),  # 5.0 + 1.5*3.0 = 9.5
        }
        sector_map = {s: "Technology" for s in "ABCDE"}
        scorer = _build_scorer(rs_map, sector_map=sector_map)
        result = await scorer.generate_longlist(list("ABCDE"), top_n=5)

        assert len(result) == 5
        # Order: E (P100), B (P75), A (P50), D (P25), C (P0)
        assert result[0].symbol == "E"
        assert result[0].alpha_percentile == 100
        assert result[1].symbol == "B"
        assert result[1].alpha_percentile == 75
        assert result[2].symbol == "A"
        assert result[2].alpha_percentile == 50
        assert result[3].symbol == "D"
        assert result[3].alpha_percentile == 25
        assert result[4].symbol == "C"
        assert result[4].alpha_percentile == 0

    @pytest.mark.asyncio
    async def test_top_n_cuts_bottom(self):
        """Top-3 from 5 symbols cuts the two lowest."""
        rs_map = {
            f"S{i}": _make_stock_rs(f"S{i}", b_raw=float(i), f_raw=float(i)) for i in range(5)
        }
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist([f"S{i}" for i in range(5)], top_n=3)
        assert len(result) == 3
        symbols = [c.symbol for c in result]
        assert "S4" in symbols
        assert "S3" in symbols
        assert "S2" in symbols
        assert "S0" not in symbols
        assert "S1" not in symbols


# =============================================================================
# E.2b.4 — COMPOSITE FEATURE FLAG
# =============================================================================


def _make_composite_score(sym: str, timeframe: str, total: float, signals=()):
    from src.services.technical_composite import CompositeScore

    return CompositeScore(
        symbol=sym,
        timeframe=timeframe,
        total=total,
        breakout_signals=tuple(signals),
    )


def _make_ohlcv(n: int, base: float = 100.0):
    """Fake OHLCV tuple with n bars, oldest-first."""
    closes = [base + i * 0.1 for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    volumes = [1_000_000 for _ in closes]
    opens = [c - 0.5 for c in closes]
    return (closes, volumes, highs, lows, opens)


def _build_composite_scorer(stock_rs_map: dict, ohlcv_map: dict, compute_side_effect=None):
    """Build AlphaScorer with composite enabled and all external calls mocked."""
    mock_srs = MagicMock()
    mock_srs.get_all_stock_rs = AsyncMock(return_value=stock_rs_map)
    mock_srs.get_all_sector_rs = AsyncMock(return_value={})

    scorer = AlphaScorer(
        sector_rs_service=mock_srs,
        config={"fast_weight": 1.5, "alpha_longlist_size": 30},
        composite_config={"enabled": True},
    )
    scorer._load_batch_ohlcv = AsyncMock(return_value=ohlcv_map)

    mock_composite = MagicMock()
    if compute_side_effect is not None:
        mock_composite.compute.side_effect = compute_side_effect
    else:
        mock_composite.compute.return_value = _make_composite_score("X", "classic", 10.0)
    scorer._composite = mock_composite
    return scorer


class TestCompositeFeatureFlag:
    @pytest.mark.asyncio
    async def test_flag_false_uses_rs_path(self):
        """enabled=false -> b_raw + f_raw*1.5, no TechnicalComposite call."""
        rs_map = {"AAPL": _make_stock_rs("AAPL", b_raw=2.0, f_raw=3.0)}
        scorer = _build_scorer(rs_map)  # composite disabled by default
        result = await scorer.generate_longlist(["AAPL"])
        assert result[0].alpha_raw == pytest.approx(6.5, abs=0.01)
        assert result[0].b_composite is None
        assert result[0].f_composite is None

    @pytest.mark.asyncio
    async def test_flag_true_uses_composite(self):
        """enabled=true -> TechnicalComposite.compute called for each symbol."""
        rs_map = {"AAPL": _make_stock_rs("AAPL")}
        ohlcv_map = {"AAPL": _make_ohlcv(200)}

        call_log = []

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            call_log.append(timeframe)
            return _make_composite_score(symbol, timeframe, 20.0)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        result = await scorer.generate_longlist(["AAPL"])
        assert len(result) == 1
        assert "classic" in call_log
        assert "fast" in call_log

    @pytest.mark.asyncio
    async def test_composite_score_differs_from_rs(self):
        """Composite total != RS b_raw + 1.5*f_raw when enabled."""
        rs_map = {"AAPL": _make_stock_rs("AAPL", b_raw=2.0, f_raw=1.0)}
        # b_raw + 1.5*f_raw = 3.5; composite: 30.0 + 1.5*15.0 = 52.5
        ohlcv_map = {"AAPL": _make_ohlcv(200)}

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            total = 30.0 if timeframe == "classic" else 15.0
            return _make_composite_score(symbol, timeframe, total)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        result = await scorer.generate_longlist(["AAPL"])
        assert result[0].alpha_raw == pytest.approx(52.5, abs=0.01)
        # Confirm it differs from plain RS score
        assert result[0].alpha_raw != pytest.approx(3.5, abs=0.5)

    @pytest.mark.asyncio
    async def test_longlist_has_breakout_signals(self):
        """Breakout signals from CompositeScore propagate to AlphaCandidate."""
        rs_map = {"X": _make_stock_rs("X")}
        ohlcv_map = {"X": _make_ohlcv(200)}

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            sigs = ("BREAKOUT IMMINENT",) if timeframe == "fast" else ()
            return _make_composite_score(symbol, timeframe, 10.0, signals=sigs)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        result = await scorer.generate_longlist(["X"])
        assert "BREAKOUT IMMINENT" in result[0].breakout_signals

    @pytest.mark.asyncio
    async def test_post_crash_weights_applied(self):
        """VIX=30 -> classic*0.3 + fast*0.7*1.5 formula used."""
        rs_map = {"X": _make_stock_rs("X")}
        ohlcv_map = {"X": _make_ohlcv(200)}

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            total = 20.0 if timeframe == "classic" else 10.0
            return _make_composite_score(symbol, timeframe, total)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        result = await scorer.generate_longlist(["X"], vix=30.0)
        # post-crash: 20.0*0.3 + 10.0*0.7*1.5 = 6.0 + 10.5 = 16.5
        assert result[0].alpha_raw == pytest.approx(16.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_post_crash_vix_below_25_normal_mode(self):
        """VIX=15 -> normal composite formula: b + f*1.5."""
        rs_map = {"X": _make_stock_rs("X")}
        ohlcv_map = {"X": _make_ohlcv(200)}

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            total = 20.0 if timeframe == "classic" else 10.0
            return _make_composite_score(symbol, timeframe, total)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        result = await scorer.generate_longlist(["X"], vix=15.0)
        # normal: 20.0 + 10.0*1.5 = 35.0
        assert result[0].alpha_raw == pytest.approx(35.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_regression_generate_longlist_returns_candidates(self):
        """generate_longlist always returns list of AlphaCandidate (regression)."""
        rs_map = {"A": _make_stock_rs("A"), "B": _make_stock_rs("B")}
        scorer = _build_scorer(rs_map)
        result = await scorer.generate_longlist(["A", "B"], top_n=2)
        assert isinstance(result, list)
        assert all(isinstance(c, AlphaCandidate) for c in result)

    @pytest.mark.asyncio
    async def test_regression_get_alpha_filtered_symbols(self):
        """get_alpha_filtered_symbols returns (symbols_list, dict) — pipeline contract."""
        from src.services.alpha_scorer import get_alpha_filtered_symbols

        config = {"sector_rs": {"alpha_engine_enabled": False}}
        symbols, alpha_map = await get_alpha_filtered_symbols(["AAPL", "MSFT"], config=config)
        assert isinstance(symbols, list)
        assert isinstance(alpha_map, dict)


# =============================================================================
# E.2b.4 — BATCH OHLCV LOADING
# =============================================================================


class TestBatchOHLCV:
    @pytest.mark.asyncio
    async def test_batch_5_symbols_structure(self):
        """Batch load returns dict with (closes, volumes, highs, lows, opens) tuples."""
        rs_map = {f"S{i}": _make_stock_rs(f"S{i}") for i in range(5)}
        symbols = [f"S{i}" for i in range(5)]
        ohlcv_map = {sym: _make_ohlcv(200) for sym in symbols}

        scorer = _build_composite_scorer(rs_map, ohlcv_map)
        # _load_batch_ohlcv is already mocked — verify it was called with symbol list
        await scorer.generate_longlist(symbols, top_n=5)
        scorer._load_batch_ohlcv.assert_awaited_once()
        call_args = scorer._load_batch_ohlcv.call_args[0][0]
        assert set(call_args) == set(symbols)

    @pytest.mark.asyncio
    async def test_batch_slicing_correct_lengths(self):
        """Composite called with closes[-135:] (classic) and closes[-30:] (fast)."""
        rs_map = {"A": _make_stock_rs("A")}
        ohlcv_map = {"A": _make_ohlcv(260)}

        received_lengths = {}

        def capture_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            received_lengths[timeframe] = len(closes)
            return _make_composite_score(symbol, timeframe, 5.0)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=capture_compute)
        await scorer.generate_longlist(["A"])
        assert received_lengths["classic"] == 135
        assert received_lengths["fast"] == 30

    @pytest.mark.asyncio
    async def test_insufficient_bars_uses_rs_fallback(self):
        """Symbol with < 30 bars -> RS fallback, no crash, b_composite = None."""
        rs_map = {"SHORT": _make_stock_rs("SHORT", b_raw=3.0, f_raw=2.0)}
        ohlcv_map = {"SHORT": _make_ohlcv(10)}  # only 10 bars

        scorer = _build_composite_scorer(rs_map, ohlcv_map)
        result = await scorer.generate_longlist(["SHORT"])
        assert len(result) == 1
        # RS fallback: 3.0 + 1.5*2.0 = 6.0
        assert result[0].alpha_raw == pytest.approx(6.0, abs=0.01)
        assert result[0].b_composite is None


# =============================================================================
# E.2b.4 — COMPOSITE INTEGRATION
# =============================================================================


class TestCompositeIntegration:
    @pytest.mark.asyncio
    async def test_composite_ranking_plausible(self):
        """Symbol with higher composite score ranks above symbol with lower score."""
        rs_map = {
            "HIGH": _make_stock_rs("HIGH"),
            "LOW": _make_stock_rs("LOW"),
        }
        ohlcv_map = {"HIGH": _make_ohlcv(200), "LOW": _make_ohlcv(200)}

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            total = 50.0 if symbol == "HIGH" else 5.0
            return _make_composite_score(symbol, timeframe, total)

        scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        result = await scorer.generate_longlist(["HIGH", "LOW"], top_n=2)
        assert result[0].symbol == "HIGH"
        assert result[1].symbol == "LOW"

    @pytest.mark.asyncio
    async def test_feature_flag_toggle_changes_ranking(self):
        """Same RS data, flag=False gives RS ranking, flag=True gives composite ranking."""
        # With RS only: AAPL (b=5, f=0 -> 5.0) > MSFT (b=0, f=3 -> 4.5)
        # With composite mocked: MSFT gets composite total 100 > AAPL 10
        rs_map = {
            "AAPL": _make_stock_rs("AAPL", b_raw=5.0, f_raw=0.0),
            "MSFT": _make_stock_rs("MSFT", b_raw=0.0, f_raw=3.0),
        }

        # RS-only scorer
        rs_scorer = _build_scorer(rs_map)
        rs_result = await rs_scorer.generate_longlist(["AAPL", "MSFT"], top_n=2)
        assert rs_result[0].symbol == "AAPL"

        # Composite scorer where MSFT gets high composite score
        ohlcv_map = {"AAPL": _make_ohlcv(200), "MSFT": _make_ohlcv(200)}

        def fake_compute(symbol, closes, highs, lows, volumes, timeframe, **kwargs):
            total = 10.0 if symbol == "AAPL" else 100.0
            return _make_composite_score(symbol, timeframe, total)

        comp_scorer = _build_composite_scorer(rs_map, ohlcv_map, compute_side_effect=fake_compute)
        comp_result = await comp_scorer.generate_longlist(["AAPL", "MSFT"], top_n=2)
        assert comp_result[0].symbol == "MSFT"

    def test_no_circular_import(self):
        """Importing both modules does not raise ImportError (no circular dependency)."""
        import importlib

        importlib.import_module("src.services.alpha_scorer")
        importlib.import_module("src.services.technical_composite")  # no exception
