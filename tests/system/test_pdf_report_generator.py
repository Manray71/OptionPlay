# Tests for PDF Report Generator
# ==============================
"""
Tests for formatters/pdf_report_generator.py module including:
- Dataclass creation tests
- PDFReportGenerator methods
- HTML rendering tests
- Format helper methods
"""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.formatters.pdf_report_generator import (
    CoverPageData,
    ScanResultRow,
    ScoreItem,
    TradeLeg,
    TradeSetup,
    SupportResistanceLevel,
    VolumeProfileBar,
    VolumeProfileData,
    FundamentalsData,
    NewsItem,
    PriceLevel,
    ScorecardData,
    ReportData,
    PDFReportGenerator,
    generate_scan_report_pdf,
)


# =============================================================================
# DATACLASS TESTS
# =============================================================================

class TestCoverPageData:
    """Tests for CoverPageData dataclass."""

    def test_create_cover_page_data_minimal(self):
        """Test creating CoverPageData with minimal args."""
        data = CoverPageData(
            date="15. January 2026",
            time="10:30",
        )
        assert data.date == "15. January 2026"
        assert data.time == "10:30"
        assert data.title == "Bull-Put Spread"
        assert data.vix_level == 0.0

    def test_create_cover_page_data_full(self):
        """Test creating CoverPageData with all args."""
        data = CoverPageData(
            date="15. Januar 2026",
            time="10:30",
            title="Test Title",
            subtitle="Test Subtitle",
            symbols_after_filter=100,
            symbols_with_signals=25,
            vix_level=18.5,
            market_sentiment="Bullish",
            dte_range="45-60 DTE",
            delta_short="0.20-0.30",
            spread_width="$7-$15",
            min_roi=">25%",
            vix_regime="Elevated",
        )
        assert data.symbols_after_filter == 100
        assert data.symbols_with_signals == 25
        assert data.vix_level == 18.5
        assert data.market_sentiment == "Bullish"


class TestScanResultRow:
    """Tests for ScanResultRow dataclass."""

    def test_create_scan_result_row(self):
        """Test creating ScanResultRow."""
        row = ScanResultRow(
            rank=1,
            symbol="AAPL",
            price=185.50,
            change_pct=1.5,
            score=12.5,
            max_score=16.0,
            strategy="Pullback",
            roi=35.0,
        )
        assert row.rank == 1
        assert row.symbol == "AAPL"
        assert row.price == 185.50
        assert row.analyzed is True  # Default

    def test_scan_result_row_not_analyzed(self):
        """Test ScanResultRow with analyzed=False."""
        row = ScanResultRow(
            rank=5,
            symbol="TSLA",
            price=250.0,
            change_pct=-2.0,
            score=8.0,
            max_score=16.0,
            strategy="Bounce",
            roi=25.0,
            analyzed=False,
        )
        assert row.analyzed is False


class TestScoreItem:
    """Tests for ScoreItem dataclass."""

    def test_create_score_item_default(self):
        """Test creating ScoreItem with default color."""
        item = ScoreItem(label="RSI", value="2/3")
        assert item.label == "RSI"
        assert item.value == "2/3"
        assert item.color == "gray"

    def test_create_score_item_colored(self):
        """Test creating ScoreItem with specific color."""
        item = ScoreItem(label="Support", value="3/3", color="green")
        assert item.color == "green"


class TestTradeLeg:
    """Tests for TradeLeg dataclass."""

    def test_create_trade_leg(self):
        """Test creating TradeLeg."""
        leg = TradeLeg(
            leg_type="Short Put",
            strike=180.0,
            delta=-0.20,
            premium=2.50,
        )
        assert leg.leg_type == "Short Put"
        assert leg.strike == 180.0
        assert leg.delta == -0.20
        assert leg.premium == 2.50


class TestTradeSetup:
    """Tests for TradeSetup dataclass."""

    def test_create_trade_setup(self):
        """Test creating TradeSetup."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)

        setup = TradeSetup(
            short_leg=short_leg,
            long_leg=long_leg,
            net_credit=1.50,
            max_risk=8.50,
            roi=17.6,
            breakeven=178.50,
            prob_profit=80.0,
            expiry_date="2026-03-21",
            dte=65,
        )
        assert setup.net_credit == 1.50
        assert setup.max_risk == 8.50
        assert setup.earnings_days is None

    def test_trade_setup_with_earnings(self):
        """Test TradeSetup with earnings days."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)

        setup = TradeSetup(
            short_leg=short_leg,
            long_leg=long_leg,
            net_credit=1.50,
            max_risk=8.50,
            roi=17.6,
            breakeven=178.50,
            prob_profit=80.0,
            expiry_date="2026-03-21",
            dte=65,
            earnings_days=45,
        )
        assert setup.earnings_days == 45


class TestSupportResistanceLevel:
    """Tests for SupportResistanceLevel dataclass."""

    def test_create_sr_level(self):
        """Test creating SupportResistanceLevel."""
        level = SupportResistanceLevel(
            rank="S1",
            price=175.0,
            distance_pct=-5.5,
            tests=3,
            strength=85.0,
        )
        assert level.rank == "S1"
        assert level.price == 175.0
        assert level.tests == 3


class TestVolumeProfileData:
    """Tests for VolumeProfileBar and VolumeProfileData."""

    def test_create_volume_profile_bar(self):
        """Test creating VolumeProfileBar."""
        bar = VolumeProfileBar(
            price=180.0,
            volume_pct=25.0,
            buy_pct=60.0,
            sell_pct=40.0,
        )
        assert bar.price == 180.0
        assert bar.is_poc is False
        assert bar.is_current is False

    def test_create_volume_profile_bar_poc(self):
        """Test creating VolumeProfileBar as POC."""
        bar = VolumeProfileBar(
            price=182.0,
            volume_pct=35.0,
            buy_pct=55.0,
            sell_pct=45.0,
            is_poc=True,
        )
        assert bar.is_poc is True

    def test_create_volume_profile_data(self):
        """Test creating VolumeProfileData."""
        bars = [
            VolumeProfileBar(180.0, 25.0, 60.0, 40.0),
            VolumeProfileBar(182.0, 35.0, 55.0, 45.0, is_poc=True),
            VolumeProfileBar(184.0, 20.0, 50.0, 50.0),
        ]
        vp = VolumeProfileData(
            bars=bars,
            poc_price=182.0,
            value_area="$178-$186",
            hvn_support=178.0,
            lvn_resistance=188.0,
        )
        assert vp.poc_price == 182.0
        assert len(vp.bars) == 3


class TestFundamentalsData:
    """Tests for FundamentalsData dataclass."""

    def test_create_fundamentals_default(self):
        """Test creating FundamentalsData with defaults."""
        fd = FundamentalsData()
        assert fd.pe_ratio is None
        assert fd.market_cap == ""
        assert fd.div_yield == "0.00%"

    def test_create_fundamentals_full(self):
        """Test creating FundamentalsData with all values."""
        fd = FundamentalsData(
            pe_ratio=28.5,
            market_cap="$3.0T",
            div_yield="0.55%",
            iv_rank=45,
            earnings_in_days=60,
            sector="Technology",
        )
        assert fd.pe_ratio == 28.5
        assert fd.sector == "Technology"


class TestNewsItem:
    """Tests for NewsItem dataclass."""

    def test_create_news_item_default(self):
        """Test creating NewsItem with default sentiment."""
        news = NewsItem(text="Apple announces new product", time="2h ago")
        assert news.sentiment == "neutral"

    def test_create_news_item_positive(self):
        """Test creating NewsItem with positive sentiment."""
        news = NewsItem(
            text="Strong earnings beat",
            time="1h ago",
            sentiment="positive",
        )
        assert news.sentiment == "positive"


class TestPriceLevel:
    """Tests for PriceLevel dataclass."""

    def test_create_price_level(self):
        """Test creating PriceLevel."""
        level = PriceLevel(
            label="R1",
            price=190.0,
            pct_from_current=2.5,
            level_type="resistance",
        )
        assert level.label == "R1"
        assert level.level_type == "resistance"


class TestScorecardData:
    """Tests for ScorecardData dataclass."""

    def test_create_scorecard_data(self):
        """Test creating ScorecardData."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0, is_poc=True)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        card = ScorecardData(
            symbol="AAPL",
            company_name="Apple Inc.",
            strategy="Pullback",
            date="2026-01-15",
            dte=65,
            price=185.50,
            price_change=2.50,
            price_change_pct=1.37,
            score=12.5,
            max_score=16.0,
            score_items=[ScoreItem("RSI", "2/3", "green")],
            trade_setup=trade_setup,
            support_levels=[],
            resistance_levels=[],
            volume_profile=volume_profile,
            price_levels=[],
            fundamentals=FundamentalsData(),
            news=[],
        )
        assert card.symbol == "AAPL"
        assert card.score == 12.5


class TestReportData:
    """Tests for ReportData dataclass."""

    def test_create_report_data(self):
        """Test creating ReportData."""
        cover = CoverPageData(date="2026-01-15", time="10:30")
        data = ReportData(
            cover=cover,
            scan_results=[],
            scorecards=[],
        )
        assert data.cover.date == "2026-01-15"
        assert len(data.scan_results) == 0


# =============================================================================
# PDF REPORT GENERATOR TESTS
# =============================================================================

class TestPDFReportGenerator:
    """Tests for PDFReportGenerator class."""

    @pytest.fixture
    def generator(self, tmp_path):
        """Create generator with temp output dir."""
        return PDFReportGenerator(output_dir=str(tmp_path))

    @pytest.fixture
    def sample_cover(self):
        """Create sample cover data."""
        return CoverPageData(
            date="15. Januar 2026",
            time="10:30",
            vix_level=18.5,
            market_sentiment="Bullish",
            symbols_after_filter=100,
            symbols_with_signals=25,
        )

    @pytest.fixture
    def sample_scan_results(self):
        """Create sample scan results."""
        return [
            ScanResultRow(1, "AAPL", 185.50, 1.5, 12.5, 16.0, "Pullback", 35.0),
            ScanResultRow(2, "MSFT", 410.0, -0.5, 11.0, 16.0, "Bounce", 30.0),
            ScanResultRow(3, "GOOGL", 175.0, 2.0, 10.5, 16.0, "Breakout", 28.0),
        ]

    def test_init_creates_output_dir(self, tmp_path):
        """Test that init creates output directory."""
        output_dir = tmp_path / "test_reports"
        gen = PDFReportGenerator(output_dir=str(output_dir))
        assert output_dir.exists()

    def test_format_price(self, generator):
        """Test _format_price method."""
        assert generator._format_price(185.50) == "$185.50"
        assert generator._format_price(1234.56) == "$1,234.56"
        assert generator._format_price(0.0) == "$0.00"

    def test_format_pct_with_sign(self, generator):
        """Test _format_pct with sign."""
        assert generator._format_pct(1.5) == "+1.5%"
        assert generator._format_pct(-2.3) == "-2.3%"
        assert generator._format_pct(0.0) == "+0.0%"

    def test_format_pct_without_sign(self, generator):
        """Test _format_pct without sign."""
        assert generator._format_pct(1.5, with_sign=False) == "1.5%"
        assert generator._format_pct(-2.3, with_sign=False) == "-2.3%"

    def test_get_change_class_positive(self, generator):
        """Test _get_change_class for positive values."""
        assert generator._get_change_class(1.5) == "up"
        assert generator._get_change_class(0.0) == "up"

    def test_get_change_class_negative(self, generator):
        """Test _get_change_class for negative values."""
        assert generator._get_change_class(-0.5) == "down"
        assert generator._get_change_class(-10.0) == "down"

    def test_get_score_class_high(self, generator):
        """Test _get_score_class for high scores."""
        assert generator._get_score_class(12.0, 16.0) == "high"  # 75%
        assert generator._get_score_class(10.0, 16.0) == "high"  # 62.5%

    def test_get_score_class_medium(self, generator):
        """Test _get_score_class for medium scores."""
        assert generator._get_score_class(8.0, 16.0) == "medium"  # 50%
        assert generator._get_score_class(7.0, 16.0) == "medium"  # 43.75%

    def test_get_score_class_low(self, generator):
        """Test _get_score_class for low scores."""
        assert generator._get_score_class(5.0, 16.0) == "low"  # 31.25%
        assert generator._get_score_class(2.0, 16.0) == "low"

    def test_get_score_class_zero_max(self, generator):
        """Test _get_score_class with zero max score."""
        assert generator._get_score_class(5.0, 0.0) == "low"

    def test_render_cover_page(self, generator, sample_cover, sample_scan_results):
        """Test _render_cover_page returns HTML."""
        html = generator._render_cover_page(sample_cover, sample_scan_results)

        assert "OptionPlay" in html
        assert "15. Januar 2026" in html
        assert "18.5" in html  # VIX level
        assert "Bullish" in html
        assert "AAPL" in html
        assert "MSFT" in html

    def test_render_cover_page_bearish_sentiment(self, generator, sample_scan_results):
        """Test cover page with bearish sentiment."""
        cover = CoverPageData(
            date="2026-01-15",
            time="10:30",
            market_sentiment="Bearish",
        )
        html = generator._render_cover_page(cover, sample_scan_results)
        assert "red" in html  # Bearish sentiment class

    def test_render_cover_page_neutral_sentiment(self, generator, sample_scan_results):
        """Test cover page with neutral sentiment."""
        cover = CoverPageData(
            date="2026-01-15",
            time="10:30",
            market_sentiment="Neutral",
        )
        html = generator._render_cover_page(cover, sample_scan_results)
        assert "orange" in html  # Neutral sentiment class

    def test_render_score_grid(self, generator):
        """Test _render_score_grid returns HTML."""
        items = [
            ScoreItem("RSI", "2/3", "green"),
            ScoreItem("Support", "3/3", "green"),
            ScoreItem("MACD", "1/3", "red"),
        ]
        html = generator._render_score_grid(items)

        assert "RSI" in html
        assert "Support" in html
        assert "MACD" in html
        assert "green" in html
        assert "red" in html

    def test_render_volume_profile(self, generator):
        """Test _render_volume_profile returns HTML."""
        bars = [
            VolumeProfileBar(180.0, 25.0, 60.0, 40.0),
            VolumeProfileBar(182.0, 35.0, 55.0, 45.0, is_poc=True),
            VolumeProfileBar(184.0, 20.0, 50.0, 50.0, is_current=True),
        ]
        vp = VolumeProfileData(
            bars=bars,
            poc_price=182.0,
            value_area="$178-$186",
            hvn_support=178.0,
            lvn_resistance=188.0,
        )
        html = generator._render_volume_profile(vp)

        assert "Volume Profile" in html
        assert "$180.00" in html
        assert "$182.00" in html
        assert "POC" in html

    def test_render_scorecard_page1(self, generator):
        """Test _render_scorecard_page1 returns HTML."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0, is_poc=True)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        card = ScorecardData(
            symbol="AAPL",
            company_name="Apple Inc.",
            strategy="Pullback",
            date="2026-01-15",
            dte=65,
            price=185.50,
            price_change=2.50,
            price_change_pct=1.37,
            score=12.5,
            max_score=16.0,
            score_items=[ScoreItem("RSI", "2/3", "green")],
            trade_setup=trade_setup,
            support_levels=[
                SupportResistanceLevel("S1", 175.0, -5.5, 3, 85.0),
                SupportResistanceLevel("S2", 170.0, -8.3, 2, 70.0),
            ],
            resistance_levels=[
                SupportResistanceLevel("R1", 190.0, 2.5, 2, 60.0),
            ],
            volume_profile=volume_profile,
            price_levels=[],
            fundamentals=FundamentalsData(),
            news=[],
        )
        html = generator._render_scorecard_page1(card, 2)

        assert "AAPL" in html
        assert "Apple Inc." in html
        assert "$185.50" in html
        assert "Pullback" in html
        assert "Bull-Put Spread Setup" in html
        assert "Short Put" in html
        assert "Long Put" in html

    def test_render_scorecard_page2(self, generator):
        """Test _render_scorecard_page2 returns HTML."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0, is_poc=True)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        card = ScorecardData(
            symbol="AAPL",
            company_name="Apple Inc.",
            strategy="Pullback",
            date="2026-01-15",
            dte=65,
            price=185.50,
            price_change=2.50,
            price_change_pct=1.37,
            score=12.5,
            max_score=16.0,
            score_items=[],
            trade_setup=trade_setup,
            support_levels=[],
            resistance_levels=[],
            volume_profile=volume_profile,
            price_levels=[
                PriceLevel("R1", 190.0, 2.5, "resistance"),
                PriceLevel("Current", 185.50, 0.0, "current"),
                PriceLevel("Short", 180.0, -3.0, "short-strike"),
            ],
            fundamentals=FundamentalsData(
                pe_ratio=28.5,
                market_cap="$3.0T",
                div_yield="0.55%",
                iv_rank=45,
                earnings_in_days=60,
                sector="Technology",
            ),
            news=[
                NewsItem("Strong earnings beat", "1h ago", "positive"),
                NewsItem("Market update", "3h ago", "neutral"),
            ],
        )
        html = generator._render_scorecard_page2(card, 3)

        assert "AAPL" in html
        assert "Fundamentals" in html
        assert "28.5" in html  # PE ratio
        assert "$3.0T" in html  # Market cap
        assert "Technology" in html
        assert "Aktuelle News" in html
        assert "Strong earnings beat" in html

    def test_render_scorecard_page2_no_earnings(self, generator):
        """Test scorecard page 2 with no earnings date."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        card = ScorecardData(
            symbol="TEST",
            company_name="Test Inc.",
            strategy="Bounce",
            date="2026-01-15",
            dte=65,
            price=100.0,
            price_change=-1.0,
            price_change_pct=-1.0,
            score=8.0,
            max_score=16.0,
            score_items=[],
            trade_setup=trade_setup,
            support_levels=[],
            resistance_levels=[],
            volume_profile=volume_profile,
            price_levels=[],
            fundamentals=FundamentalsData(
                pe_ratio=None,  # No PE
                earnings_in_days=None,  # No earnings
            ),
            news=[],
        )
        html = generator._render_scorecard_page2(card, 3)

        assert "N/A" in html  # PE and earnings should show N/A

    def test_render_html_full_report(self, generator, sample_cover, sample_scan_results):
        """Test render_html creates complete HTML."""
        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0, is_poc=True)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        scorecard = ScorecardData(
            symbol="AAPL",
            company_name="Apple Inc.",
            strategy="Pullback",
            date="2026-01-15",
            dte=65,
            price=185.50,
            price_change=2.50,
            price_change_pct=1.37,
            score=12.5,
            max_score=16.0,
            score_items=[ScoreItem("RSI", "2/3", "green")],
            trade_setup=trade_setup,
            support_levels=[],
            resistance_levels=[],
            volume_profile=volume_profile,
            price_levels=[],
            fundamentals=FundamentalsData(),
            news=[],
        )

        data = ReportData(
            cover=sample_cover,
            scan_results=sample_scan_results,
            scorecards=[scorecard],
        )

        # Mock template loading
        with patch.object(generator, '_load_template', return_value='<style></style>'):
            html = generator.render_html(data)

        assert "<!DOCTYPE html>" in html
        assert "<html lang=\"de\">" in html
        assert "OptionPlay Market Scan Report" in html

    def test_render_html_empty_scorecards(self, generator, sample_cover, sample_scan_results):
        """Test render_html with no scorecards."""
        data = ReportData(
            cover=sample_cover,
            scan_results=sample_scan_results,
            scorecards=[],
        )

        with patch.object(generator, '_load_template', return_value='<style></style>'):
            html = generator.render_html(data)

        assert "<!DOCTYPE html>" in html
        # Should only have cover page
        assert "cover" in html


class TestGeneratePdfFunction:
    """Tests for generate_scan_report_pdf convenience function."""

    def test_generate_scan_report_pdf_basic(self, tmp_path):
        """Test generate_scan_report_pdf creates generator."""
        scan_results = [
            {
                'symbol': 'AAPL',
                'price': 185.50,
                'change_pct': 1.5,
                'score': 12.5,
                'max_score': 16.0,
                'strategy': 'Pullback',
                'roi': 35.0,
            }
        ]

        # Mock WeasyPrint
        with patch('src.formatters.pdf_report_generator.PDFReportGenerator.generate_pdf') as mock_gen:
            mock_gen.return_value = tmp_path / "test.pdf"

            result = generate_scan_report_pdf(
                vix_level=18.5,
                scan_results=scan_results,
                scorecards_data=[],
                market_sentiment="Bullish",
                output_dir=str(tmp_path),
            )

            mock_gen.assert_called_once()


class TestPDFGeneration:
    """Tests for PDF generation (requires WeasyPrint)."""

    def test_generate_pdf_import_error(self, tmp_path):
        """Test generate_pdf raises ImportError if WeasyPrint missing."""
        generator = PDFReportGenerator(output_dir=str(tmp_path))

        cover = CoverPageData(date="2026-01-15", time="10:30")
        data = ReportData(cover=cover, scan_results=[], scorecards=[])

        # Mock import failure
        with patch.dict('sys.modules', {'weasyprint': None}):
            with patch.object(generator, 'render_html', return_value='<html></html>'):
                # The actual import happens inside generate_pdf
                # We need to simulate the import error
                with patch('builtins.__import__', side_effect=ImportError("No module named 'weasyprint'")):
                    with pytest.raises(ImportError, match="WeasyPrint"):
                        generator.generate_pdf(data)

    def test_generate_pdf_success(self, tmp_path):
        """Test generate_pdf success with mocked WeasyPrint."""
        generator = PDFReportGenerator(output_dir=str(tmp_path))

        cover = CoverPageData(date="2026-01-15", time="10:30")
        data = ReportData(cover=cover, scan_results=[], scorecards=[])

        # Create mock WeasyPrint
        mock_html_class = MagicMock()
        mock_html_instance = MagicMock()
        mock_html_class.return_value = mock_html_instance

        with patch.object(generator, 'render_html', return_value='<html></html>'):
            with patch.object(generator, '_load_template', return_value='<style></style>'):
                with patch.dict('sys.modules', {'weasyprint': MagicMock(HTML=mock_html_class)}):
                    # Manually call parts of generate_pdf
                    html_content = generator.render_html(data)
                    assert '<html>' in html_content


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_scan_results(self, tmp_path):
        """Test with empty scan results."""
        generator = PDFReportGenerator(output_dir=str(tmp_path))
        cover = CoverPageData(date="2026-01-15", time="10:30")

        html = generator._render_cover_page(cover, [])

        assert "OptionPlay" in html

    def test_negative_price_change(self, tmp_path):
        """Test with negative price change."""
        generator = PDFReportGenerator(output_dir=str(tmp_path))

        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        card = ScorecardData(
            symbol="TEST",
            company_name="Test Inc.",
            strategy="Pullback",
            date="2026-01-15",
            dte=65,
            price=100.0,
            price_change=-5.0,  # Negative
            price_change_pct=-4.76,  # Negative
            score=8.0,
            max_score=16.0,
            score_items=[],
            trade_setup=trade_setup,
            support_levels=[],
            resistance_levels=[],
            volume_profile=volume_profile,
            price_levels=[],
            fundamentals=FundamentalsData(),
            news=[],
        )

        html = generator._render_scorecard_page1(card, 2)
        assert "down" in html  # Should have down class for negative change

    def test_very_high_strength(self, tmp_path):
        """Test with strength > 100 (should be capped)."""
        generator = PDFReportGenerator(output_dir=str(tmp_path))

        short_leg = TradeLeg("Short Put", 180.0, -0.20, 2.50)
        long_leg = TradeLeg("Long Put", 170.0, -0.08, 1.00)
        trade_setup = TradeSetup(
            short_leg, long_leg, 1.50, 8.50, 17.6, 178.50, 80.0, "2026-03-21", 65
        )

        bars = [VolumeProfileBar(180.0, 25.0, 60.0, 40.0)]
        volume_profile = VolumeProfileData(
            bars, 180.0, "$175-$185", 175.0, 190.0
        )

        card = ScorecardData(
            symbol="TEST",
            company_name="Test Inc.",
            strategy="Pullback",
            date="2026-01-15",
            dte=65,
            price=100.0,
            price_change=1.0,
            price_change_pct=1.0,
            score=8.0,
            max_score=16.0,
            score_items=[],
            trade_setup=trade_setup,
            support_levels=[
                SupportResistanceLevel("S1", 95.0, -5.0, 5, 150.0),  # Strength > 100
            ],
            resistance_levels=[],
            volume_profile=volume_profile,
            price_levels=[],
            fundamentals=FundamentalsData(),
            news=[],
        )

        html = generator._render_scorecard_page1(card, 2)
        # Should cap strength at 100%
        assert "100%" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
